"""Единый движок условий кампании.

Условия читают состояние и возвращают причину отказа (пустая строка —
условие выполнено). Модуль обслуживает ``requires`` работ и оставляет
место для автоматов, подсистем и слоя отражения.

Поддерживаются два формата.

Старый (активы)::

    "self": {"legitimacy": {"min": 0.4}}
    "target": {"cohesion": {"max": 0.6}}

Новый (типизированные клаузы)::

    "when": [
      {"kind": "need", "key": "fear", "op": ">=", "value": 0.5},
      {"kind": "belief", "predicate": "is_legitimate"},
      {"kind": "organ", "id": "staff", "op": ">=", "value": 0.3},
      {"any": [
        {"kind": "flag", "key": "amnesty_offered"},
        {"kind": "turn", "op": ">=", "value": 10}
      ]}
    ]

Неизвестный ``kind`` — это причина отказа, а не молчаливое «да»:
контент с опечаткой должен быть громким.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Iterable


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _text(value, default=""):
    text = str(value or "").strip()
    return text or default


def compare(current, op, expected):
    op = str(op or "==").strip()
    try:
        if op == ">=":
            return current >= expected
        if op == "<=":
            return current <= expected
        if op == ">":
            return current > expected
        if op == "<":
            return current < expected
        if op == "!=":
            return current != expected
        if op == "in":
            return current in expected
        if op == "not in":
            return current not in expected
        return current == expected
    except TypeError:
        return False


def _threshold(spec):
    """Вернуть ``(minimum, maximum, strict_min, strict_max)`` из спеки."""
    minimum = None
    maximum = None
    strict_min = False
    strict_max = False
    if isinstance(spec, Mapping):
        minimum = spec.get("min", spec.get("gte", spec.get("at_least")))
        maximum = spec.get("max", spec.get("lte", spec.get("at_most")))
        if "gt" in spec:
            minimum = spec.get("gt")
            strict_min = True
        if "lt" in spec:
            maximum = spec.get("lt")
            strict_max = True
    elif spec is not None:
        minimum = spec
    return minimum, maximum, strict_min, strict_max


def asset_reason(prefix, assets, conditions, labels=None):
    """Проверить старый формат условий на активы."""
    labels = labels or {}
    for key, spec in _as_mapping(conditions).items():
        current = _number(_as_mapping(assets).get(str(key)), 0.0)
        label = str(labels.get(str(key), key))
        minimum, maximum, strict_min, strict_max = _threshold(spec)
        if minimum is not None:
            threshold = _number(minimum)
            if current < threshold or (
                strict_min and current <= threshold
            ):
                sign = ">" if strict_min else "≥"
                return "%s: %s %s %.2f" % (
                    prefix,
                    label,
                    sign,
                    threshold,
                )
        if maximum is not None:
            threshold = _number(maximum)
            if current > threshold or (
                strict_max and current >= threshold
            ):
                sign = "<" if strict_max else "≤"
                return "%s: %s %s %.2f" % (
                    prefix,
                    label,
                    sign,
                    threshold,
                )
    return ""


def _character(context, scope="self"):
    if scope == "target":
        return context.get("target_character")
    return context.get("character")


def _faction(context, scope="self"):
    if scope == "target":
        return context.get("target")
    return context.get("faction")


def _belief_strength(character, payload):
    predicate = _text(payload.get("predicate"))
    if character is None or not predicate:
        return 0.0
    obj = _text(payload.get("object"))
    subject = _text(payload.get("subject"))
    total = 0.0
    for item in getattr(getattr(character, "bdi", None), "beliefs", ()):
        if item.predicate != predicate:
            continue
        if obj and item.object != obj:
            continue
        if subject and item.subject != subject:
            continue
        total = max(total, item.value * item.confidence)
    return total


def _belief_present(character, payload):
    predicate = _text(payload.get("predicate"))
    if character is None or not predicate:
        return False
    obj = payload.get("object")
    subject = payload.get("subject")
    for item in getattr(getattr(character, "bdi", None), "beliefs", ()):
        if item.predicate != predicate:
            continue
        if obj is not None and item.object != _text(obj):
            continue
        if subject is not None and item.subject != _text(subject):
            continue
        return True
    return False


def _intention_present(character, payload):
    target = _text(payload.get("target"))
    essence = _text(payload.get("essence"))
    intentions = getattr(
        getattr(character, "bdi", None), "intentions", ()
    )
    for item in intentions:
        if target and item.target != target:
            continue
        if essence and item.essence != essence:
            continue
        return True
    return False


def _clause_reason(clause, context):
    if not isinstance(clause, Mapping):
        return "условие должно быть объектом"
    if "all" in clause:
        for item in clause.get("all") or ():
            reason = _clause_reason(item, context)
            if reason:
                return reason
        return ""
    if "any" in clause:
        reasons = []
        for item in clause.get("any") or ():
            reason = _clause_reason(item, context)
            if not reason:
                return ""
            reasons.append(reason)
        return reasons[0] if reasons else "ни одно условие не выполнено"
    if "not" in clause:
        inner = _clause_reason(clause.get("not"), context)
        return "" if inner else "запрещённое условие выполнено"

    kind = _text(clause.get("kind") or "asset")
    scope = _text(clause.get("scope") or "self")
    op = clause.get("op", "==")
    expected = clause.get("value")
    key = _text(clause.get("key") or clause.get("id"))

    if kind == "asset":
        faction = _faction(context, scope)
        assets = getattr(faction, "assets", {}) if faction else {}
        current = _number(
            assets.get(key) if hasattr(assets, "get") else 0.0
        )
        if "min" in clause or "max" in clause:
            return asset_reason(
                "нужно" if scope == "self" else "цель",
                assets,
                {key: clause},
                context.get("labels"),
            )
        if not compare(current, op, expected):
            return "нужно: %s %s %s" % (key, op, expected)
        return ""

    character = _character(context, scope)
    faction = _faction(context, scope)

    if kind in ("need", "desire"):
        current = _number(
            _as_mapping(getattr(character, "needs", {})).get(key)
        )
        if not compare(current, op, expected):
            return "нужно: %s %s %s" % (key, op, expected)
        return ""
    if kind == "trait":
        values = _as_mapping(
            getattr(getattr(character, "personality", None), "values", {})
        )
        if not compare(_number(values.get(key)), op, expected):
            return "нужно: черта %s %s %s" % (key, op, expected)
        return ""
    if kind in ("condition", "sickness", "wound"):
        conditions = _as_mapping(
            getattr(getattr(character, "bdi", None), "conditions", {})
        )
        if kind in ("sickness", "wound") and key in ("", "condition"):
            key = kind
        if not compare(_number(conditions.get(key)), op, expected):
            return "нужно: состояние %s %s %s" % (key, op, expected)
        return ""
    if kind == "belief":
        if op == "==" and expected is None:
            return "" if _belief_present(character, clause) else (
                "нужно: убеждение %s" % (key or clause.get("predicate"))
            )
        strength = _belief_strength(character, clause)
        if not compare(strength, op, expected):
            return "нужно: убеждение %s %s %s" % (
                key or clause.get("predicate"),
                op,
                expected,
            )
        return ""
    if kind == "intention":
        return "" if _intention_present(character, clause) else (
            "нужно: намерение %s" % (key or clause.get("essence"))
        )
    if kind == "organ":
        organ = faction.organ(key) if faction is not None else None
        if organ is None:
            return "нужно: орган %s" % key
        if not compare(_number(organ.integrity), op, expected):
            return "нужно: орган %s %s %s" % (key, op, expected)
        return ""
    if kind == "subfaction":
        sub = context.get("subfaction")
        sub_id = _text(
            clause.get("subfaction") or clause.get("id")
        )
        if sub_id and faction is not None:
            sub = faction.subfaction(sub_id)
        if sub is None:
            return "нужно: подфракция %s" % (sub_id or "?")
        asset_key = _text(clause.get("asset") or clause.get("key"))
        current = _number(
            _as_mapping(getattr(sub, "assets", {})).get(asset_key)
        )
        if not compare(current, op, expected):
            return "нужно: подфракция %s.%s %s %s" % (
                sub.id,
                asset_key,
                op,
                expected,
            )
        return ""
    if kind in ("flag", "context"):
        attribute = "flags" if kind == "flag" else "context"
        values = (
            getattr(faction, attribute, {})
            if faction is not None
            else {}
        )
        if key not in values:
            if expected is None or expected is False:
                return "нужно: флаг %s" % key
            return "нужно: флаг %s" % key
        if expected is None:
            return ""
        if not compare(values.get(key), op, expected):
            return "нужно: флаг %s %s %s" % (key, op, expected)
        return ""
    if kind == "turn":
        if not compare(_number(context.get("turn")), op, expected):
            return "нужно: цикл %s %s" % (op, expected)
        return ""
    if kind == "used_action":
        used = set(context.get("used_actions") or ())
        return "" if key in used else "сначала нужно: %s" % key
    if kind == "not_used_action":
        used = set(context.get("used_actions") or ())
        return "несовместимо с: %s" % key if key in used else ""
    return "неизвестное условие: %s" % kind


def check_conditions(conditions, context):
    """Проверить список/группу клауз. Пустая строка — всё выполнено."""
    if not conditions:
        return ""
    if isinstance(conditions, Mapping) and (
        "all" in conditions or "any" in conditions or "not" in conditions
    ):
        return _clause_reason(conditions, context)
    items: Iterable = conditions
    if isinstance(conditions, Mapping):
        items = [conditions]
    for clause in items:
        reason = _clause_reason(clause, context)
        if reason:
            return reason
    return ""


__all__ = [
    "asset_reason",
    "check_conditions",
    "compare",
]
