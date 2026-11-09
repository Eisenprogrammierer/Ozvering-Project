"""Ценностные ограничения кампании (WORLD_CORE_MODEL §7.3 №18).

Ценности героя — не украшение биографии и не второй бюджет. Это **жёсткие
запреты только там, где их явно объявил контент**. По умолчанию предательство
разрешено и имеет цену в отношениях/репутации/обязательствах; ценность может
сделать его невозможным, если действие помечено соответствующим ограничением.

Формат ограничения на действии:

```json
"values": {
  "forbid": ["honor"],
  "require_any": ["order", "faith"],
  "threshold": 0.7,
  "betrayal": true,
  "reason": "честь не позволяет предать союзника"
}
```

* `forbid` — ценности, при наличии которых действие невозможно;
* `require_any` — хотя бы одна из ценностей обязательна;
* `threshold` — сила ценности, начиная с которой запрет действует;
* `betrayal` — действие считается предательством; мир может задать для
  этого признака ограничение по умолчанию (`values.defaults.betrayal`);
* `reason` — переопределение русского объяснения для UI/журнала.

Профиль хранит `value_ids` (идентификаторы из `identity.json`) и/или
`values` (русские метки). Старые снимки без `value_ids` сопоставляются по
меткам, поэтому ограничения не зависят от формата снимка.
"""

from __future__ import annotations

VALUE_IDS = (
    "order",
    "freedom",
    "faith",
    "profit",
    "knowledge",
    "honor",
    "mercy",
)

VALUE_LABELS = {
    "order": "Порядок",
    "freedom": "Свобода",
    "faith": "Вера",
    "profit": "Выгода",
    "knowledge": "Знание",
    "honor": "Честь",
    "mercy": "Милосердие",
}

LABEL_TO_ID = {
    label.lower(): value_id for value_id, label in VALUE_LABELS.items()
}

VALUE_PRIMARY_STRENGTH = 1.0
VALUE_SECONDARY_STRENGTH = 0.7
DEFAULT_FORBID_THRESHOLD = 0.7

DEFAULT_VALUE_RULES = {
    "primary": VALUE_PRIMARY_STRENGTH,
    "secondary": VALUE_SECONDARY_STRENGTH,
    "threshold": DEFAULT_FORBID_THRESHOLD,
    "defaults": {},
}


def _as_text(value, default=""):
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _as_float(value, low)))


def _list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return []


def value_id(value):
    """Нормализовать метку/идентификатор ценности в id."""
    text = _as_text(value)
    if not text:
        return ""
    if text in VALUE_IDS:
        return text
    return LABEL_TO_ID.get(text.lower(), text.lower())


def label_for(value):
    value = value_id(value)
    return VALUE_LABELS.get(value, value or "—")


def value_rules(raw=None):
    """Нормализовать блок `values` конфига мира.

    Отсутствие блока не меняет поведение: ограничения действуют только там,
    где действие объявило `values`.
    """
    raw = raw if isinstance(raw, dict) else {}
    rules = dict(DEFAULT_VALUE_RULES)
    rules["primary"] = _clamp(
        raw.get("primary", VALUE_PRIMARY_STRENGTH), 0.0, 1.0
    )
    rules["secondary"] = _clamp(
        raw.get("secondary", VALUE_SECONDARY_STRENGTH), 0.0, 1.0
    )
    rules["threshold"] = _clamp(
        raw.get("threshold", DEFAULT_FORBID_THRESHOLD), 0.0, 1.0
    )
    defaults = raw.get("defaults")
    rules["defaults"] = defaults if isinstance(defaults, dict) else {}
    return rules


def profile_value_ids(profile):
    """Идентификаторы ценностей профиля без потери старых снимков."""
    profile = profile if isinstance(profile, dict) else {}
    ids = []
    for raw in profile.get("value_ids") or ():
        item = value_id(raw)
        if item and item not in ids:
            ids.append(item)
    if ids:
        return ids
    for raw in profile.get("values") or ():
        item = value_id(raw)
        if item and item not in ids:
            ids.append(item)
    return ids


def value_strengths(profile, rules=None):
    """Сила ценностей: главная, поддерживающие или явная карта."""
    profile = profile if isinstance(profile, dict) else {}
    rules = rules or value_rules()
    explicit = profile.get("value_strength")
    if isinstance(explicit, dict):
        return {
            value_id(key): _clamp(value, 0.0, 1.0)
            for key, value in explicit.items()
            if value_id(key)
        }
    result = {}
    for index, item in enumerate(profile_value_ids(profile)):
        strength = rules["primary"] if index == 0 else rules["secondary"]
        result[item] = max(result.get(item, 0.0), _clamp(strength))
    values = profile.get("values")
    if isinstance(values, dict):
        for key, value in values.items():
            item = value_id(key)
            if item:
                result[item] = max(result.get(item, 0.0), _clamp(value))
    return result


def _constraint_block(raw):
    if raw is None:
        return {}
    if isinstance(raw, (list, tuple, set, str)):
        return {"forbid": _list(raw)}
    return raw if isinstance(raw, dict) else {}


def action_constraints(action, rules=None):
    """Собрать ограничение действия из `values`/`value_constraints`.

    Поддерживаются короткая форма-список (`["honor"]` = запрет) и словарь.
    Мир может добавить ограничение по признаку `betrayal` через
    `values.defaults`.
    """
    action = action if isinstance(action, dict) else {}
    rules = rules or value_rules()
    raw = action.get("values")
    if raw is None:
        raw = action.get("value_constraints")
    block = dict(_constraint_block(raw))
    betrayal = bool(action.get("betrayal", block.get("betrayal", False)))
    if not block and betrayal:
        default = (rules.get("defaults") or {}).get("betrayal")
        block = dict(_constraint_block(default))
    forbid = []
    for key in ("forbid", "forbidden", "absolute"):
        for item in _list(block.get(key)):
            value = value_id(item)
            if value and value not in forbid:
                forbid.append(value)
    require_any = []
    for key in ("require_any", "requires_any", "values_any"):
        for item in _list(block.get(key)):
            value = value_id(item)
            if value and value not in require_any:
                require_any.append(value)
    threshold = _clamp(
        block.get("threshold", rules.get("threshold")), 0.0, 1.0
    )
    return {
        "forbid": tuple(forbid),
        "require_any": tuple(require_any),
        "threshold": threshold,
        "betrayal": betrayal,
        "reason": _as_text(block.get("reason")),
    }


def check_action(action, profile, rules=None):
    """Проверить жёсткие ценностные ограничения действия.

    Возвращает `{allowed, reason, ...}`. Пустое ограничение всегда разрешает
    действие: предательство по умолчанию возможно и оплачивается отношениями,
    репутацией и обязательствами, а не молчаливым запретом.
    """
    rules = rules or value_rules()
    constraint = action_constraints(action, rules)
    if not constraint["forbid"] and not constraint["require_any"]:
        return {
            "allowed": True,
            "reason": "",
            "constraint": constraint,
            "blocked_by": "",
        }
    strengths = value_strengths(profile, rules)
    if constraint["forbid"]:
        for item in constraint["forbid"]:
            if strengths.get(item, 0.0) + 1e-9 >= constraint["threshold"]:
                reason = constraint["reason"] or (
                    "ценность «%s» не позволяет это действие"
                    % label_for(item)
                )
                return {
                    "allowed": False,
                    "reason": reason,
                    "constraint": constraint,
                    "blocked_by": item,
                }
    if constraint["require_any"] and not any(
        strengths.get(item, 0.0) + 1e-9 >= constraint["threshold"]
        for item in constraint["require_any"]
    ):
        reason = constraint["reason"] or (
            "действие требует ценности: %s"
            % ", ".join(label_for(item) for item in constraint["require_any"])
        )
        return {
            "allowed": False,
            "reason": reason,
            "constraint": constraint,
            "blocked_by": "",
        }
    return {
        "allowed": True,
        "reason": "",
        "constraint": constraint,
        "blocked_by": "",
    }


def value_view(profile, rules=None, actions=None):
    """Срез ценностей и ограничений для UI/отладки."""
    rules = rules or value_rules()
    strengths = value_strengths(profile, rules)
    constraints = {}
    for action in actions or ():
        if not isinstance(action, dict):
            continue
        constraint = action_constraints(action, rules)
        if constraint["forbid"] or constraint["require_any"]:
            constraints[_as_text(action.get("id"))] = constraint
    return {
        "ids": profile_value_ids(profile),
        "strengths": strengths,
        "labels": {
            item: label_for(item)
            for item in set(strengths) | set(VALUE_LABELS)
        },
        "threshold": rules["threshold"],
        "constraints": constraints,
    }


__all__ = [
    "DEFAULT_FORBID_THRESHOLD",
    "DEFAULT_VALUE_RULES",
    "LABEL_TO_ID",
    "VALUE_IDS",
    "VALUE_LABELS",
    "VALUE_PRIMARY_STRENGTH",
    "VALUE_SECONDARY_STRENGTH",
    "action_constraints",
    "check_action",
    "label_for",
    "profile_value_ids",
    "value_id",
    "value_rules",
    "value_strengths",
    "value_view",
]
