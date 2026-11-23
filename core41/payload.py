"""Типизированная полезная нагрузка работы (§7.1 №4).

`Work = {amount, form, payload, duration}` остаётся минимальным контрактом.
`form` — канал доставки, `amount` — сколько работы оплачено, а `payload` —
что именно доставлено: предмет, свидетельство, приказ, сведения или
намерение принуждения.

Payload хранится как неизменяемый кортеж пар `(ключ, значение)`, а не как
произвольный словарь:

* `Work` остаётся hashable/frozen и безопасно копируется в составные
  автоматы;
* снимок и JSON не получают скрытых вложенных структур;
* схема вида проверяется один раз, а обработчик видит уже нормализованные
  поля.

Тип задаётся ключом `kind`. Реестр известных видов читается из
`configs/content/payload_kinds.json` (переменная окружения
`OZVERING_PAYLOAD_KINDS` позволяет подменить файл) и доступен как
`PAYLOAD_KINDS`; неизвестный `kind` отвергается. Payload без `kind`
остаётся «непрозрачным» для собственного обработчика: это обратная
совместимость для контента, который передаёт произвольные пары.

`apply_payload()` — детерминированное применение нагрузки к состоянию
получателя. Оно не заменяет энергию и не создаёт второй бюджет: предметы,
свидетельства и приказы — это данные/состояние, а их доставка уже оплачена
работой `amount`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Mapping

logger = logging.getLogger(__name__)

PAYLOAD_SCHEMA_VERSION = 1
PAYLOAD_HISTORY_LIMIT = 32
PAYLOAD_STRING_LIMIT = 240

PAYLOAD_REGISTRY_ENV = "OZVERING_PAYLOAD_KINDS"
PAYLOAD_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "content"
    / "payload_kinds.json"
)


class PayloadError(ValueError):
    """Некорректная полезная нагрузка: неизвестный вид или поле."""


def _as_text(value, default="", limit=PAYLOAD_STRING_LIMIT):
    if value is None:
        return default
    text = str(value)
    if len(text) > limit:
        return text[:limit]
    return text


def _scalar(value, field_name):
    if isinstance(value, (dict, list, set, tuple)):
        raise PayloadError(
            "payload.%s: ожидается скаляр, получено %s"
            % (field_name, type(value).__name__)
        )
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise PayloadError(
        "payload.%s: неподдерживаемый тип %s"
        % (field_name, type(value).__name__)
    )


def _field_names(value, where):
    """Список имён полей без пустых и повторяющихся значений."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise PayloadError("%s: ожидался список полей" % where)
    result = []
    for item in value:
        name = _as_text(item).strip()
        if not name:
            raise PayloadError("%s: пустое имя поля" % where)
        if name in result:
            raise PayloadError("%s: поле %r повторяется" % (where, name))
        result.append(name)
    return result


def normalize_payload_kinds(data):
    """Проверить и нормализовать реестр видов payload.

    Новый вид — это данные, а не ветка Python: обязательные поля,
    значения по умолчанию, числовые поля и шаблон описания. Ошибка в
    реестре должна быть громкой, поэтому неизвестные ключи и
    несовпадающие типы полей отвергаются.
    """
    if not isinstance(data, Mapping):
        raise PayloadError("payload_kinds: ожидался объект")
    unknown_root = set(data) - {"schema", "description", "kinds"}
    if unknown_root:
        raise PayloadError(
            "payload_kinds: неизвестные ключи %s"
            % ", ".join(sorted(str(key) for key in unknown_root))
        )
    raw_kinds = data.get("kinds")
    if not isinstance(raw_kinds, Mapping) or not raw_kinds:
        raise PayloadError("payload_kinds.kinds: нужен непустой объект")
    allowed_keys = {
        "label",
        "describe",
        "required",
        "defaults",
        "numeric",
        "describe_defaults",
    }
    result = {}
    for raw_name, raw_spec in raw_kinds.items():
        kind = _as_text(raw_name).strip()
        if not kind:
            raise PayloadError("payload_kinds: пустое имя вида")
        if not isinstance(raw_spec, Mapping):
            raise PayloadError(
                "payload_kinds.%s: ожидался объект" % kind
            )
        where = "payload_kinds.%s" % kind
        unknown = set(raw_spec) - allowed_keys
        if unknown:
            raise PayloadError(
                "%s: неизвестные ключи %s"
                % (where, ", ".join(sorted(str(key) for key in unknown)))
            )
        required = _field_names(raw_spec.get("required"), where + ".required")
        raw_defaults = raw_spec.get("defaults") or {}
        if not isinstance(raw_defaults, Mapping):
            raise PayloadError("%s.defaults: ожидался объект" % where)
        defaults = {}
        for raw_field, value in raw_defaults.items():
            field = _as_text(raw_field).strip()
            if not field:
                raise PayloadError("%s.defaults: пустое имя поля" % where)
            if field in defaults:
                raise PayloadError(
                    "%s.defaults: поле %r повторяется" % (where, field)
                )
            defaults[field] = _scalar(value, "%s.defaults.%s" % (where, field))
        for field in required:
            if field in defaults:
                raise PayloadError(
                    "%s: поле %r одновременно required и defaults"
                    % (where, field)
                )
        numeric = _field_names(raw_spec.get("numeric"), where + ".numeric")
        known = set(required) | set(defaults)
        for field in numeric:
            if field not in known:
                raise PayloadError(
                    "%s.numeric: поле %r не объявлено в required/defaults"
                    % (where, field)
                )
            if field in defaults:
                try:
                    float(defaults[field])
                except (TypeError, ValueError) as exc:
                    raise PayloadError(
                        "%s.defaults.%s: ожидается число"
                        % (where, field)
                    ) from exc
        raw_describe_defaults = raw_spec.get("describe_defaults") or {}
        if not isinstance(raw_describe_defaults, Mapping):
            raise PayloadError(
                "%s.describe_defaults: ожидался объект" % where
            )
        describe_defaults = {}
        for raw_field, value in raw_describe_defaults.items():
            field = _as_text(raw_field).strip()
            if not field:
                raise PayloadError(
                    "%s.describe_defaults: пустое имя поля" % where
                )
            if field not in known:
                raise PayloadError(
                    "%s.describe_defaults: неизвестное поле %r"
                    % (where, field)
                )
            describe_defaults[field] = _scalar(
                value, "%s.describe_defaults.%s" % (where, field)
            )
        result[kind] = {
            "label": _as_text(raw_spec.get("label")) or kind,
            "describe": _as_text(raw_spec.get("describe")),
            "required": tuple(required),
            "defaults": defaults,
            "numeric": tuple(numeric),
            "describe_defaults": describe_defaults,
        }
    return result


def load_payload_kinds(path=None):
    """Прочитать реестр видов из JSON.

    Путь можно задать аргументом или переменной окружения
    ``OZVERING_PAYLOAD_KINDS``. По умолчанию берётся
    ``configs/content/payload_kinds.json`` рядом с репозиторием.
    """
    source = path or os.environ.get(PAYLOAD_REGISTRY_ENV)
    source = Path(source) if source else PAYLOAD_REGISTRY_PATH
    try:
        text = Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise PayloadError(
            "payload_kinds: не удалось прочитать %s: %s" % (source, exc)
        ) from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PayloadError(
            "payload_kinds: некорректный JSON %s: %s" % (source, exc)
        ) from exc
    return normalize_payload_kinds(data)


try:
    PAYLOAD_KINDS = load_payload_kinds()
except PayloadError as exc:  # pragma: no cover - защита от битого контента
    logger.error("Реестр payload не загружен: %s", exc)
    PAYLOAD_KINDS = {}


def _pairs(payload):
    if payload is None:
        return []
    if isinstance(payload, dict):
        return list(payload.items())
    try:
        items = list(payload)
    except TypeError as exc:
        raise PayloadError(
            "payload должен быть отображением или парами"
        ) from exc
    result = []
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise PayloadError("payload: ожидается пара (ключ, значение)")
        result.append((item[0], item[1]))
    return result


def payload_map(payload):
    """Развернуть payload в обычный словарь (без валидации схемы)."""
    result = {}
    for key, value in _pairs(payload):
        key = _as_text(key)
        if not key:
            raise PayloadError("payload: пустой ключ")
        result[key] = _scalar(value, key)
    return result


def make_payload(kind, **fields):
    """Собрать типизированный payload с проверкой обязательных полей.

    Неизвестные поля отвергаются: опечатка в контенте не должна молча
    теряться. Значения по умолчанию добавляются всегда, поэтому payload
    самодокументирован в снимке и отчёте получателя.
    """
    kind = _as_text(kind)
    schema = PAYLOAD_KINDS.get(kind)
    if schema is None:
        raise PayloadError("неизвестный тип payload: %r" % kind)
    known = set(schema["defaults"]) | set(schema["required"])
    unknown = sorted(set(fields) - known)
    if unknown:
        raise PayloadError(
            "payload %s: неизвестные поля %s"
            % (kind, ", ".join(unknown))
        )
    data = {}
    for key, default in schema["defaults"].items():
        value = fields.get(key, default)
        if key in schema["numeric"]:
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise PayloadError(
                    "payload %s.%s: ожидается число" % (kind, key)
                ) from exc
        elif isinstance(value, bool):
            value = value
        else:
            value = _as_text(value)
        data[key] = value
    for key in schema["required"]:
        value = fields.get(key)
        if key in schema["numeric"]:
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise PayloadError(
                    "payload %s.%s: ожидается число" % (kind, key)
                ) from exc
        else:
            value = _as_text(value)
        if value in (None, ""):
            raise PayloadError("payload %s: поле %s обязательно" % (kind, key))
        data[key] = value
    return (("kind", kind),) + tuple(sorted(data.items()))


def normalize_payload(payload):
    """Привести payload к каноническому кортежу пар.

    Пустой payload остаётся `()`. Словарь или пары с `kind` проходят через
    `make_payload`; пары без `kind` сохраняются как непрозрачные данные
    обработчика. Это позволяет старым вызовам `Work(payload=...)` работать
    без миграции.
    """
    if payload is None or payload == () or payload == {}:
        return ()
    data = payload_map(payload)
    if "kind" not in data:
        return tuple(sorted(data.items()))
    kind = data.pop("kind")
    return make_payload(kind, **data)


def payload_kind(payload):
    try:
        return _as_text(payload_map(payload).get("kind"))
    except PayloadError:
        return ""


def payload_fields(payload):
    """Поля payload без служебного `kind`."""
    data = payload_map(payload)
    data.pop("kind", None)
    return data


def describe_payload(payload):
    """Короткое русское описание payload для журнала/UI.

    Текст берётся из шаблона ``describe`` реестра видов. Новый вид
    получает описание в конфиге, а не новой веткой Python.
    """
    try:
        data = payload_map(payload)
    except PayloadError:
        return "payload: некорректные данные"
    kind = _as_text(data.get("kind"))
    if not kind:
        return "payload: %d полей" % len(data) if data else "payload: пусто"
    schema = PAYLOAD_KINDS.get(kind)
    if schema is None:
        return "payload %s" % kind
    template = str(schema.get("describe") or "")
    if not template:
        return "payload %s" % kind
    values = dict(schema.get("defaults") or {})
    values.update(schema.get("describe_defaults") or {})
    values.update(
        {
            key: value
            for key, value in data.items()
            if value not in (None, "")
        }
    )
    try:
        return template.format_map(values)
    except (KeyError, ValueError, IndexError, AttributeError):
        return "payload %s" % kind


def _bounded_append(store, value):
    store.append(value)
    if len(store) > PAYLOAD_HISTORY_LIMIT:
        del store[:-PAYLOAD_HISTORY_LIMIT]


def apply_payload(target, payload):
    """Применить типизированную нагрузку к `target.state`.

    Возвращает список фактических изменений `(метка, величина)`.
    Детерминированно, без случайности и без изменения `E/F/H`: нагрузка —
    состояние получателя, а не второй бюджет. Неизвестный/пустой payload
    ничего не меняет.
    """
    if target is None or payload in (None, (), {}):
        return []
    try:
        normalized = normalize_payload(payload)
        data = payload_map(normalized)
    except PayloadError:
        return []
    kind = _as_text(data.get("kind"))
    if not kind:
        return []
    state = target.state
    if kind == "item":
        item_id = _as_text(data.get("item_id"))
        if not item_id:
            return []
        quantity = max(0.0, float(data.get("quantity", 0.0)))
        if quantity <= 0.0:
            return []
        items = state.setdefault("items", {})
        before = float(items.get(item_id, 0.0))
        items[item_id] = before + quantity
        return [("item:%s" % item_id, quantity)]
    if kind == "evidence":
        claim = _as_text(data.get("claim"))
        if not claim:
            return []
        store = state.setdefault("evidence", [])
        _bounded_append(
            store,
            {
                "claim": claim,
                "strength": float(data.get("strength", 0.0)),
                "subject": _as_text(data.get("subject")),
                "source": _as_text(data.get("source")),
            },
        )
        return [("evidence", 1.0)]
    if kind == "order":
        action = _as_text(data.get("action"))
        if not action:
            return []
        store = state.setdefault("orders", [])
        _bounded_append(
            store,
            {
                "action": action,
                "target": _as_text(data.get("target")),
                "deadline_day": int(data.get("deadline_day", 0)),
                "priority": float(data.get("priority", 0.0)),
            },
        )
        return [("order", 1.0)]
    if kind == "info":
        topic = _as_text(data.get("topic"))
        if not topic:
            return []
        knowledge = state.setdefault("knowledge", {})
        before = float(knowledge.get(topic, 0.0))
        knowledge[topic] = max(
            before, float(data.get("confidence", 0.0))
        )
        return [("info:%s" % topic, knowledge[topic] - before)]
    if kind == "force":
        state["last_force_intent"] = _as_text(data.get("intent"))
        return [("force_intent", 1.0)]
    return []


def payload_state(target):
    """Срез состояния, созданного payload, для отчёта и UI."""
    state = getattr(target, "state", {}) or {}
    return {
        "items": dict(state.get("items") or {}),
        "evidence": list(state.get("evidence") or ()),
        "orders": list(state.get("orders") or ()),
        "knowledge": dict(state.get("knowledge") or {}),
        "last_force_intent": _as_text(state.get("last_force_intent")),
    }


__all__ = [
    "PAYLOAD_HISTORY_LIMIT",
    "PAYLOAD_KINDS",
    "PAYLOAD_REGISTRY_ENV",
    "PAYLOAD_REGISTRY_PATH",
    "PAYLOAD_SCHEMA_VERSION",
    "PAYLOAD_STRING_LIMIT",
    "PayloadError",
    "apply_payload",
    "describe_payload",
    "load_payload_kinds",
    "make_payload",
    "normalize_payload",
    "normalize_payload_kinds",
    "payload_fields",
    "payload_kind",
    "payload_map",
    "payload_state",
]
