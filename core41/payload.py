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

Тип задаётся ключом `kind`. Известные виды описаны в `PAYLOAD_KINDS`;
неизвестный `kind` отвергается. Payload без `kind` остаётся «непрозрачным»
для собственного обработчика: это обратная совместимость для контента,
который передаёт произвольные пары.

`apply_payload()` — детерминированное применение нагрузки к состоянию
получателя. Оно не заменяет энергию и не создаёт второй бюджет: предметы,
свидетельства и приказы — это данные/состояние, а их доставка уже оплачена
работой `amount`.
"""

from __future__ import annotations

PAYLOAD_SCHEMA_VERSION = 1
PAYLOAD_HISTORY_LIMIT = 32
PAYLOAD_STRING_LIMIT = 240

PAYLOAD_KINDS = {
    "item": {
        "required": ("item_id",),
        "defaults": {"quantity": 1.0, "quality": 1.0, "label": ""},
        "numeric": ("quantity", "quality"),
    },
    "evidence": {
        "required": ("claim",),
        "defaults": {
            "strength": 0.5,
            "subject": "",
            "source": "",
        },
        "numeric": ("strength",),
    },
    "order": {
        "required": ("action",),
        "defaults": {
            "target": "",
            "deadline_day": 0,
            "priority": 0.5,
        },
        "numeric": ("deadline_day", "priority"),
    },
    "info": {
        "required": ("topic",),
        "defaults": {
            "confidence": 0.5,
            "source": "",
        },
        "numeric": ("confidence",),
    },
    "force": {
        "required": (),
        "defaults": {"intent": "", "severity": 0.5},
        "numeric": ("severity",),
    },
}


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
    """Короткое русское описание payload для журнала/UI."""
    try:
        data = payload_map(payload)
    except PayloadError:
        return "payload: некорректные данные"
    kind = _as_text(data.get("kind"))
    if not kind:
        return "payload: %d полей" % len(data) if data else "payload: пусто"
    if kind == "item":
        return "предмет %s ×%g" % (
            _as_text(data.get("item_id"), "?"),
            float(data.get("quantity", 0.0)),
        )
    if kind == "evidence":
        return "свидетельство: %s" % _as_text(data.get("claim"), "?")
    if kind == "order":
        return "приказ: %s → %s" % (
            _as_text(data.get("action"), "?"),
            _as_text(data.get("target")) or "себя",
        )
    if kind == "info":
        return "сведения: %s (%.2f)" % (
            _as_text(data.get("topic"), "?"),
            float(data.get("confidence", 0.0)),
        )
    if kind == "force":
        return "принуждение: %s" % (
            _as_text(data.get("intent")) or "без интента"
        )
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
    "PAYLOAD_SCHEMA_VERSION",
    "PAYLOAD_STRING_LIMIT",
    "PayloadError",
    "apply_payload",
    "describe_payload",
    "make_payload",
    "normalize_payload",
    "payload_fields",
    "payload_kind",
    "payload_map",
    "payload_state",
]
