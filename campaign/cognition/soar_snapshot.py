"""JSON-снимок рабочей памяти Soar-агента.

Решение §12.6 плана миграции: родной бинарный снимок Soar не
используется. Рабочая память сериализуется в версионированный JSON
(``schema``, ``snapshot_version``, ``agent_id``, ``ai_model``, узлы WM,
счётчики) и загружается обратно в чистый агент. Несовместимая версия —
явная ошибка, а не «тихое» обнуление.

Граница записи: input-link пишет только Python, Soar его не меняет.
Поэтому снимок — это JSON-зеркало input-link, а не результат чтения
SML: после ``SynchronizeInputLink`` биндинг отдаёт input-link только на
запись, а внутренние WME (операторы, состояние) выводятся из входа и
пересобираются при следующем цикле. Зеркало детерминировано и не
зависит от версии SML.

Модуль разделён на две части:

* чистые функции ``validate_snapshot``/``build_snapshot`` работают без
  SML и проверяют JSON до запуска Soar;
* ``create_wm``/``load_wm`` создают WME через SML; без пакета
  ``soar-sml`` их вызывать нельзя, но импорт модуля остаётся безопасным.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Mapping, Optional

from .errors import SnapshotError

SNAPSHOT_SCHEMA = "soar_snapshot.v1"
SNAPSHOT_VERSION = 1
STORE_SCHEMA = "soar_snapshots.v1"
STORE_VERSION = 1
MAX_DEPTH = 64
NODE_KINDS = ("id", "string", "int", "double")

# Миграции между версиями снимка. Ключ — версия, значение — функция,
# превращающая словарь в следующую версию. Пока версия одна, таблица
# пуста; она существует, чтобы отказ не подменялся молчаливым сбросом.
_MIGRATIONS: Dict[int, Any] = {}


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SnapshotError("%s должен быть объектом" % name)
    return value


def _text(value: Any, name: str = "", default: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        if default:
            return default
        raise SnapshotError("%s обязателен" % name)
    return text


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotError("%s должен быть целым числом" % name) from exc
    if number < minimum:
        raise SnapshotError("%s должен быть >= %d" % (name, minimum))
    return number


def _counter_map(value: Any) -> Dict[str, int]:
    if value is None:
        return {}
    data = _mapping(value, "counters")
    result: Dict[str, int] = {}
    for key, item in data.items():
        result[str(key)] = _integer(item, "counters.%s" % key)
    return {key: result[key] for key in sorted(result)}


def _validate_nodes(value: Any, depth: int = 0) -> List[Dict[str, Any]]:
    if depth > MAX_DEPTH:
        raise SnapshotError(
            "снимок Soar глубже %d уровней" % MAX_DEPTH
        )
    if not isinstance(value, (list, tuple)):
        raise SnapshotError("wm должен быть списком узлов")
    nodes: List[Dict[str, Any]] = []
    for index, item in enumerate(value):
        node = _mapping(item, "wm[%d]" % index)
        attribute = _text(
            node.get("attribute"), "wm[%d].attribute" % index
        )
        kind = str(node.get("kind") or "id").strip()
        if kind not in NODE_KINDS:
            raise SnapshotError(
                "wm[%d].kind=%r не поддерживается; допустимо: %s"
                % (index, kind, ", ".join(NODE_KINDS))
            )
        if kind == "id":
            children = _validate_nodes(
                node.get("children") or [], depth + 1
            )
            nodes.append(
                {
                    "attribute": attribute,
                    "kind": "id",
                    "children": children,
                }
            )
            continue
        if "value" not in node:
            raise SnapshotError(
                "wm[%d].value обязателен для %s" % (index, kind)
            )
        value = node.get("value")
        if kind == "int":
            value = _integer(value, "wm[%d].value" % index, minimum=-2**63)
            if value >= 2**63:
                raise SnapshotError(
                    "wm[%d].value не помещается в 64-битное целое" % index
                )
        elif kind == "double":
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise SnapshotError(
                    "wm[%d].value должен быть числом" % index
                ) from exc
            if not math.isfinite(value):
                raise SnapshotError(
                    "wm[%d].value должен быть конечным числом" % index
                )
        else:
            value = str(value)
        nodes.append(
            {"attribute": attribute, "kind": kind, "value": value}
        )
    return nodes


def validate_snapshot(data: Any) -> Dict[str, Any]:
    """Проверить снимок и вернуть нормализованную копию.

    Неизвестная будущая версия отвергается явно; известная старая
    проходит через таблицу миграций.
    """

    raw = _mapping(data, "снимок Soar")
    schema = str(raw.get("schema") or SNAPSHOT_SCHEMA).strip()
    if schema != SNAPSHOT_SCHEMA:
        raise SnapshotError(
            "неизвестная схема снимка Soar: %r" % schema
        )
    version = _integer(
        raw.get("snapshot_version", SNAPSHOT_VERSION),
        "snapshot_version",
    )
    if version > SNAPSHOT_VERSION:
        raise SnapshotError(
            "снимок Soar новее этой сборки: %d > %d"
            % (version, SNAPSHOT_VERSION)
        )
    migrated = dict(raw)
    while version < SNAPSHOT_VERSION:
        migrate = _MIGRATIONS.get(version)
        if migrate is None:
            raise SnapshotError(
                "нет миграции снимка Soar с версии %d" % version
            )
        migrated = migrate(migrated)
        version += 1
    agent_id = _text(migrated.get("agent_id"), "agent_id")
    ai_model = str(migrated.get("ai_model") or "")
    tick = _integer(migrated.get("tick", 0), "tick")
    counters = _counter_map(migrated.get("counters"))
    nodes = _validate_nodes(migrated.get("wm") or [])
    return {
        "schema": SNAPSHOT_SCHEMA,
        "snapshot_version": SNAPSHOT_VERSION,
        "agent_id": agent_id,
        "ai_model": ai_model,
        "tick": tick,
        "counters": counters,
        "wm": nodes,
    }


class SoarSnapshotStore:
    """Набор снимков по именным Soar-агентам (один агент на NPC)."""

    def __init__(self, data: Any = None):
        raw = _mapping(data, "набор снимков Soar") if data else {}
        if not raw:
            self.agents: Dict[str, Dict[str, Any]] = {}
            return
        schema = str(raw.get("schema") or STORE_SCHEMA).strip()
        if schema != STORE_SCHEMA:
            raise SnapshotError(
                "неизвестная схема набора снимков Soar: %r" % schema
            )
        version = _integer(
            raw.get("snapshot_version", STORE_VERSION),
            "snapshot_version",
        )
        if version > STORE_VERSION:
            raise SnapshotError(
                "набор снимков Soar новее этой сборки: %d > %d"
                % (version, STORE_VERSION)
            )
        if version < 1:
            raise SnapshotError(
                "неизвестная версия набора снимков Soar: %r" % version
            )
        self.agents = {}
        for agent_id, item in _mapping(
            raw.get("agents") or {}, "agents"
        ).items():
            snapshot = validate_snapshot(item)
            if snapshot["agent_id"] != str(agent_id):
                raise SnapshotError(
                    "ключ %r не совпадает с agent_id %r"
                    % (agent_id, snapshot["agent_id"])
                )
            self.agents[str(agent_id)] = snapshot

    @classmethod
    def from_dict(cls, data: Any) -> "SoarSnapshotStore":
        return cls(data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": STORE_SCHEMA,
            "snapshot_version": STORE_VERSION,
            "agents": {
                key: self.agents[key] for key in sorted(self.agents)
            },
        }

    def save(self, snapshot: Any) -> Dict[str, Any]:
        data = validate_snapshot(snapshot)
        self.agents[data["agent_id"]] = data
        return data

    def load(self, agent_id: str) -> Dict[str, Any]:
        key = str(agent_id or "").strip()
        return copy.deepcopy(self.agents.get(key) or {})

    def clear(self) -> None:
        self.agents.clear()

    def __len__(self) -> int:
        return len(self.agents)

    def __contains__(self, agent_id: Any) -> bool:
        return str(agent_id or "").strip() in self.agents


def build_snapshot(
    wm: Any,
    *,
    agent_id: str,
    ai_model: str = "",
    tick: int = 0,
    counters: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Собрать JSON-снимок из зеркала input-link.

    ``wm`` — уже нормализованные узлы (``create_wm``/``validate_snapshot``)
    либо исходное JSON-описание; результат всегда проходит валидацию.
    """

    return validate_snapshot(
        {
            "schema": SNAPSHOT_SCHEMA,
            "snapshot_version": SNAPSHOT_VERSION,
            "agent_id": agent_id,
            "ai_model": ai_model,
            "tick": tick,
            "counters": dict(counters or {}),
            "wm": wm,
        }
    )


def _create_children(
    agent: Any,
    parent: Any,
    nodes: List[Dict[str, Any]],
    depth: int = 0,
) -> List[Any]:
    """Создать узлы и вернуть SML-хэндлы верхнего уровня.

    Хэндлы нужны для диагностики и точного roundtrip снимка. Менять
    WME после ``SynchronizeInputLink`` нельзя (SML отдаёт input-link
    только на запись), поэтому замена входа идёт через ``init-soar``,
    а не через ``DestroyWME``.
    """

    if depth > MAX_DEPTH:
        raise SnapshotError(
            "снимок Soar глубже %d уровней" % MAX_DEPTH
        )
    handles: List[Any] = []
    for node in nodes:
        attribute = node["attribute"]
        kind = node["kind"]
        if kind == "id":
            child = agent.CreateIdWME(parent, attribute)
            if child is None:
                # Фейковый агент в тестах бюджета принимает parent=None
                # и возвращает None: для него узлы не нужны, важен лишь
                # расход циклов. Настоящий SML всегда отдаёт хэндл.
                if parent is not None:
                    raise SnapshotError(
                        "Soar не создал узел %r" % attribute
                    )
                handles.append(None)
                continue
            _create_children(agent, child, node["children"], depth + 1)
            handles.append(child)
        elif kind == "int":
            handles.append(
                agent.CreateIntWME(parent, attribute, int(node["value"]))
            )
        elif kind == "double":
            handles.append(
                agent.CreateFloatWME(
                    parent, attribute, float(node["value"])
                )
            )
        else:
            handles.append(
                agent.CreateStringWME(
                    parent, attribute, str(node["value"])
                )
            )
    return handles


def load_wm(agent: Any, snapshot: Any) -> Dict[str, Any]:
    """Загрузить снимок в агент и вернуть нормализованные данные.

    Незавершённые WME проверяются до синхронизации; после неё SML отдаёт
    input-link только на запись, поэтому ``SoarAgent.restore`` всегда
    создаёт новый агент, а не переиспользует старый.
    """

    data, _handles = load_wm_handles(agent, snapshot)
    return data


def load_wm_handles(
    agent: Any,
    snapshot: Any,
) -> tuple:
    """Загрузить снимок и вернуть ``(данные, хэндлы верхнего уровня)``."""

    data = validate_snapshot(snapshot)
    link = agent.GetInputLink()
    if link is None:
        raise SnapshotError("у Soar-агента нет input-link")
    if link.GetNumberChildren():
        raise SnapshotError(
            "снимок Soar грузится только в чистый input-link"
        )
    handles = _create_children(agent, link, data["wm"])
    agent.SynchronizeInputLink()
    return data, handles


def create_wm(
    agent: Any,
    nodes: Any,
    parent: Any = None,
) -> List[Dict[str, Any]]:
    """Создать WME из JSON-описания под input-link или узлом."""

    data, _handles = create_wm_handles(agent, nodes, parent)
    return data


def create_wm_handles(
    agent: Any,
    nodes: Any,
    parent: Any = None,
) -> tuple:
    """Создать WME и вернуть ``(данные, хэндлы верхнего уровня)``."""

    data = _validate_nodes(nodes)
    link = agent.GetInputLink() if parent is None else parent
    handles = _create_children(agent, link, data)
    if parent is None:
        agent.SynchronizeInputLink()
    return data, handles


__all__ = [
    "MAX_DEPTH",
    "NODE_KINDS",
    "SNAPSHOT_SCHEMA",
    "SNAPSHOT_VERSION",
    "STORE_SCHEMA",
    "STORE_VERSION",
    "SoarSnapshotStore",
    "build_snapshot",
    "create_wm",
    "create_wm_handles",
    "load_wm",
    "load_wm_handles",
    "validate_snapshot",
]
