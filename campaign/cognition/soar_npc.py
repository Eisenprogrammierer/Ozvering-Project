"""Долгоживущие Soar-агенты именных NPC.

Решение §12.2 плана миграции: у каждого именного NPC и лидера фракции
свой Soar-агент с BDI-памятью. Python остаётся единственным писателем
состояния: он переводит BDI персонажа в JSON-узлы рабочей памяти,
отдаёт агенту кандидатов работы и читает решение.

Агент переиспользуется между ходами: продукции остаются в Soar, а вход
заменяется через ``init-soar`` и повторную выдачу настроек выбора (SML
не позволяет менять WME после синхронизации). Поэтому прошлые кандидаты
не накапливаются и не влияют на новое решение, а BDI-память каждый ход
восстанавливается из JSON. Рабочая память Soar при этом сбрасывается;
RL-обучение потребует отдельного механизма поверх снимков.

Пул ``SoarNpcPool`` лениво создаёт агентов, выгружает самых давних при
переполнении и хранит JSON-снимки в ``SoarSnapshotStore``. Снимок — это
зеркало BDI-памяти, а не эфемерные кандидаты хода, поэтому сохранение
не зависит от того, какой именно ход был последним.
"""

from __future__ import annotations

import copy
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .errors import BackendError, SoarError
from .soar_runtime import (
    DEFAULT_SOAR_DIR,
    SoarAgent,
    SoarNpcPolicy,
    _normalise,
    _read_decision,
    candidate_nodes,
    check_decision_budget,
)
from .soar_snapshot import SoarSnapshotStore

DEFAULT_MAX_AGENTS = 32
DEFAULT_MAX_BELIEFS = 64
DEFAULT_MAX_INTENTIONS = 8


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: Any) -> float:
    return max(0.0, min(1.0, _number(value)))


def _need_nodes(needs: Mapping[str, Any]) -> Dict[str, Any]:
    children = [
        {
            "attribute": str(key),
            "kind": "double",
            "value": _clamp(value),
        }
        for key, value in sorted(dict(needs or {}).items())
        if str(key)
    ]
    return {"attribute": "needs", "kind": "id", "children": children}


def _belief_nodes(beliefs: Iterable[Any], limit: int) -> List[Dict[str, Any]]:
    items = list(beliefs or ())[-max(0, int(limit)) :]
    nodes: List[Dict[str, Any]] = []
    for item in items:
        data = item.as_dict() if hasattr(item, "as_dict") else dict(item)
        children = [
            {
                "attribute": "subject",
                "kind": "string",
                "value": _text(data.get("subject")),
            },
            {
                "attribute": "predicate",
                "kind": "string",
                "value": _text(data.get("predicate")),
            },
            {
                "attribute": "object",
                "kind": "string",
                "value": _text(data.get("object")),
            },
            {
                "attribute": "value",
                "kind": "double",
                "value": _clamp(data.get("value", 1.0)),
            },
            {
                "attribute": "confidence",
                "kind": "double",
                "value": _clamp(data.get("confidence", 1.0)),
            },
            {
                "attribute": "source",
                "kind": "string",
                "value": _text(data.get("source")),
            },
        ]
        if data.get("ttl") is not None:
            children.append(
                {
                    "attribute": "ttl",
                    "kind": "double",
                    "value": max(0.0, _number(data.get("ttl"))),
                }
            )
        nodes.append(
            {"attribute": "belief", "kind": "id", "children": children}
        )
    return nodes


def _intention_nodes(
    intentions: Iterable[Any], limit: int
) -> List[Dict[str, Any]]:
    items = list(intentions or ())[-max(0, int(limit)) :]
    return [
        {
            "attribute": "intention",
            "kind": "id",
            "children": [
                {
                    "attribute": "target",
                    "kind": "string",
                    "value": _text(
                        item.get("target")
                        if isinstance(item, Mapping)
                        else getattr(item, "target", "")
                    ),
                },
                {
                    "attribute": "essence",
                    "kind": "string",
                    "value": _text(
                        item.get("essence")
                        if isinstance(item, Mapping)
                        else getattr(item, "essence", "")
                    ),
                },
            ],
        }
        for item in items
    ]


def _map_nodes(
    attribute: str, values: Mapping[str, Any], kind: str
) -> Dict[str, Any]:
    children = []
    for key, value in sorted(dict(values or {}).items()):
        if not str(key):
            continue
        children.append(
            {
                "attribute": str(key),
                "kind": kind,
                "value": (
                    _clamp(value) if kind == "double" else _text(value)
                ),
            }
        )
    return {"attribute": attribute, "kind": "id", "children": children}


def bdi_memory(
    character: Any,
    *,
    tick: int = 0,
    max_beliefs: int = DEFAULT_MAX_BELIEFS,
    max_intentions: int = DEFAULT_MAX_INTENTIONS,
) -> List[Dict[str, Any]]:
    """Перевести персонажа в узлы BDI-памяти Soar.

    Возвращает один узел ``self``. Это стабильная часть рабочей памяти:
    кандидаты хода добавляются к ней только на время решения.
    """

    bdi = getattr(character, "bdi", None)
    character_id = _text(
        getattr(character, "campaign_id", "")
        or getattr(character, "id", "")
        or getattr(character, "name", "")
        or "character"
    )
    name = _text(getattr(character, "name", "")) or character_id
    needs = getattr(character, "needs", None)
    if not isinstance(needs, Mapping):
        needs = getattr(bdi, "needs", {}) if bdi is not None else {}
    beliefs = getattr(bdi, "beliefs", ()) if bdi is not None else ()
    intentions = (
        getattr(bdi, "intentions", ()) if bdi is not None else ()
    )
    traits = getattr(bdi, "traits", {}) if bdi is not None else {}
    conditions = (
        getattr(bdi, "conditions", {}) if bdi is not None else {}
    )
    children: List[Dict[str, Any]] = [
        {"attribute": "id", "kind": "string", "value": character_id},
        {"attribute": "name", "kind": "string", "value": name},
        {"attribute": "tick", "kind": "int", "value": max(0, int(tick))},
        _need_nodes(needs),
        _map_nodes("traits", traits, "double"),
        _map_nodes("conditions", conditions, "double"),
    ]
    children.extend(_belief_nodes(beliefs, max_beliefs))
    children.extend(_intention_nodes(intentions, max_intentions))
    for attribute in ("morale", "force", "energy"):
        value = getattr(character, attribute, None)
        if value is not None:
            children.append(
                {
                    "attribute": attribute,
                    "kind": "double",
                    "value": _number(value),
                }
            )
    return [{"attribute": "self", "kind": "id", "children": children}]


class SoarNpcAgent:
    """Один именной NPC: долгоживущий Soar-агент и его BDI-зеркало."""

    def __init__(
        self,
        agent_id: str,
        *,
        model: Any = None,
        policy_path: Any = None,
        source_dir: Any = DEFAULT_SOAR_DIR,
        ai_model: str = "",
        max_beliefs: int = DEFAULT_MAX_BELIEFS,
        max_intentions: int = DEFAULT_MAX_INTENTIONS,
        timeout_ms: float = 0.0,
    ):
        self.agent_id = _text(agent_id)
        if not self.agent_id:
            raise BackendError("agent_id обязателен")
        self.runtime = SoarAgent(
            agent_id=self.agent_id,
            model=model,
            policy_path=policy_path,
            source_dir=source_dir,
            ai_model=ai_model,
        )
        self.policy = SoarNpcPolicy(
            model=self.runtime.model,
            policy_path=self.runtime.path,
            source_dir=source_dir,
            timeout_ms=timeout_ms,
        )
        self.max_beliefs = max(0, int(max_beliefs))
        self.max_intentions = max(0, int(max_intentions))
        self.memory: List[Dict[str, Any]] = []
        self.character_id = ""
        self.last_elapsed_ms = 0.0
        self.last_used = 0
        self.decisions = 0
        self.errors = 0

    def start(self) -> "SoarNpcAgent":
        self.runtime.start()
        return self

    def close(self) -> None:
        self.runtime.close()

    def __enter__(self) -> "SoarNpcAgent":
        return self.start()

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def remember(self, character: Any, tick: Optional[int] = None) -> None:
        """Обновить BDI-память перед решением."""

        self.character_id = _text(
            getattr(character, "campaign_id", "")
            or getattr(character, "id", "")
            or getattr(character, "name", "")
        )
        self.memory = bdi_memory(
            character,
            tick=int(tick or 0),
            max_beliefs=self.max_beliefs,
            max_intentions=self.max_intentions,
        )
        self.last_used = int(tick or 0)

    def snapshot(self) -> Dict[str, Any]:
        return self.runtime.snapshot()

    def restore(self, snapshot: Any) -> Dict[str, Any]:
        data = self.runtime.restore(snapshot)
        self.memory = copy.deepcopy(data["wm"])
        self.last_used = int(data.get("tick") or 0)
        self.decisions = int(data["counters"].get("decisions", 0))
        self.errors = int(data["counters"].get("errors", 0))
        self.character_id = _text(
            self.character_id
            or next(
                (
                    child["value"]
                    for node in self.memory
                    if node.get("attribute") == "self"
                    for child in node.get("children", [])
                    if child.get("attribute") == "id"
                ),
                "",
            )
        )
        return data

    def choose(
        self,
        candidates: Iterable[Any],
        needs: Mapping[str, Any],
        *,
        weights: Optional[Mapping[str, Any]] = None,
        timeout_ms: Optional[float] = None,
    ) -> Optional[str]:
        """Выбрать работу на текущем BDI-снимке и сохранить память."""

        items = _normalise(candidates)
        if not items:
            return None
        nodes, ranks = candidate_nodes(items, needs, weights)
        limit = self.policy._budget(timeout_ms)
        started = time.perf_counter()
        self.last_elapsed_ms = 0.0
        try:
            self.runtime.replace_wm(self.memory + nodes)
            cycles = max(1, int(self.runtime.model.decision_cycles))
            for _cycle in range(cycles):
                check_decision_budget(started, limit)
                self.runtime.agent.RunSelf(1)
            decision = _read_decision(self.runtime.agent)
        except Exception:
            self.errors += 1
            self.runtime.counters["errors"] = self.errors
            raise
        finally:
            self.last_elapsed_ms = (
                time.perf_counter() - started
            ) * 1000.0
            # Снимок показывает только BDI-память: кандидаты хода
            # эфемерны. Следующее решение всё равно сбросит WM через
            # ``init-soar``, поэтому второй сброс здесь не нужен.
            self.runtime.wm = copy.deepcopy(self.memory)
        if decision is None:
            raise SoarError("Soar не выбрал работу")
        if decision not in ranks:
            raise SoarError(
                "Soar выбрал неизвестную работу %r" % (decision,)
            )
        if limit and self.last_elapsed_ms > limit:
            raise SoarError(
                "Soar превысил бюджет решения: %.2f мс > %.2f мс"
                % (self.last_elapsed_ms, limit)
            )
        self.decisions += 1
        self.runtime.counters["decisions"] = self.decisions
        self.runtime.tick += 1
        return decision


class SoarNpcPool:
    """Пул именных агентов с ленивым запуском и выгрузкой по LRU."""

    def __init__(
        self,
        *,
        max_agents: int = DEFAULT_MAX_AGENTS,
        store: Optional[SoarSnapshotStore] = None,
        max_beliefs: int = DEFAULT_MAX_BELIEFS,
        max_intentions: int = DEFAULT_MAX_INTENTIONS,
        timeout_ms: float = 0.0,
        source_dir: Any = DEFAULT_SOAR_DIR,
    ):
        self.max_agents = max(1, int(max_agents))
        self.store = store or SoarSnapshotStore()
        self.max_beliefs = max(0, int(max_beliefs))
        self.max_intentions = max(0, int(max_intentions))
        self.timeout_ms = max(0.0, float(timeout_ms or 0.0))
        self.source_dir = source_dir
        self.agents: Dict[str, SoarNpcAgent] = {}
        self.evictions = 0
        self.starts = 0

    def __len__(self) -> int:
        return len(self.agents)

    def get(
        self,
        agent_id: str,
        character: Any = None,
        *,
        tick: Optional[int] = None,
    ) -> SoarNpcAgent:
        key = _text(agent_id)
        if not key:
            raise BackendError("agent_id обязателен")
        agent = self.agents.get(key)
        if agent is None:
            if len(self.agents) >= self.max_agents:
                self._evict()
            agent = SoarNpcAgent(
                key,
                source_dir=self.source_dir,
                max_beliefs=self.max_beliefs,
                max_intentions=self.max_intentions,
                timeout_ms=self.timeout_ms,
            )
            saved = self.store.load(key)
            if saved:
                agent.restore(saved)
            self.agents[key] = agent
            self.starts += 1
        if character is not None:
            agent.remember(character, tick=tick)
        return agent

    def _evict(self) -> None:
        if not self.agents:
            return
        key = min(
            self.agents,
            key=lambda item: (
                self.agents[item].last_used,
                item,
            ),
        )
        self.save(key)
        self.agents[key].close()
        del self.agents[key]
        self.evictions += 1

    def save(self, agent_id: str) -> Dict[str, Any]:
        agent = self.agents.get(_text(agent_id))
        if agent is None:
            return {}
        return self.store.save(agent.snapshot())

    def snapshot(self) -> Dict[str, Any]:
        for key in sorted(self.agents):
            self.save(key)
        return self.store.to_dict()

    def restore(self, data: Any) -> None:
        store = SoarSnapshotStore.from_dict(data or {})
        for agent in self.agents.values():
            agent.close()
        self.agents.clear()
        self.store = store

    def close(self) -> None:
        for agent in self.agents.values():
            agent.close()
        self.agents.clear()

    def report(self) -> Dict[str, Any]:
        return {
            "agents": len(self.agents),
            "max_agents": self.max_agents,
            "starts": self.starts,
            "evictions": self.evictions,
            "saved": len(self.store),
            "decisions": sum(
                agent.decisions for agent in self.agents.values()
            ),
            "errors": sum(agent.errors for agent in self.agents.values()),
            "ids": sorted(self.agents),
        }


__all__ = [
    "DEFAULT_MAX_AGENTS",
    "DEFAULT_MAX_BELIEFS",
    "DEFAULT_MAX_INTENTIONS",
    "SoarNpcAgent",
    "SoarNpcPool",
    "bdi_memory",
]
