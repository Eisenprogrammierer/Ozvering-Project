"""Единый движок эффектов кампании.

Задача модуля — быть **единственной точкой записи** декларативного словаря
эффектов: работы, взаимодействия персонажей, состояния автоматов и позже
подсистемы. События сюда не входят: они только читают состояние.

Старый формат::

    "effects": {
      "self": {"legitimacy": 0.02},
      "target": {"cohesion": -0.05},
      "needs": {"target": {"fear": 0.02}}
    }

Новый формат::

    "effects": {
      "self": {
        "assets": {"legitimacy": 0.02},
        "needs": {"fear": 0.05},
        "beliefs": {"add": [
          {"predicate": "is_legitimate", "value": 0.4}
        ]}
      },
      "target": {"organs": {"staff": {"integrity": -0.1}}},
      "flags": {"amnesty_offered": true}
    }

Все числа аддитивны и умножаются на ``scale``. Неизвестная область не
ломает ход: она попадает в ``applied["ignored"]`` и в лог вызывающего.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Dict, List

import bdi

# Ключи области, которые являются не активами, а отдельными эффектами.
STRUCTURAL_KEYS = {
    "assets",
    "needs",
    "traits",
    "conditions",
    "beliefs",
    "intentions",
    "organs",
    "relations",
    "flags",
    "text",
    "scope",
}


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _number(value, low)))


def _characters(faction):
    return list(getattr(faction, "characters", ()) or ())


def _leader(faction):
    characters = _characters(faction)
    return characters[0] if characters else None


def _character_id(character):
    return str(
        getattr(character, "campaign_id", "")
        or getattr(character, "name", "")
        or ""
    )


def _apply_assets(faction, values, scale, applied, scope):
    if faction is None:
        return
    for key, value in _as_mapping(values).items():
        delta = _number(value) * scale
        if not delta:
            continue
        faction.add_asset(key, delta)
        applied["assets"].append(
            {"scope": scope, "key": str(key), "delta": delta}
        )


def _apply_needs(faction, values, scale, applied, scope):
    if faction is None:
        return
    for key, value in _as_mapping(values).items():
        delta = _number(value) * scale
        if not delta:
            continue
        for character in _characters(faction):
            if key not in getattr(character, "needs", {}):
                continue
            character.needs[key] = _clamp(
                character.needs.get(key, 0.0) + delta
            )
            applied["needs"].append(
                {
                    "scope": scope,
                    "character": _character_id(character),
                    "key": str(key),
                    "delta": delta,
                }
            )


def _apply_conditions(faction, values, scale, applied, scope):
    if faction is None:
        return
    for key, value in _as_mapping(values).items():
        delta = _number(value) * scale
        if not delta:
            continue
        for character in _characters(faction):
            state = getattr(character, "bdi", None)
            if state is None:
                continue
            definition = state.config.conditions.get(str(key))
            if definition is None:
                continue
            maximum = definition.maximum
            before = state.conditions.get(str(key), 0.0)
            state.conditions[str(key)] = _clamp(
                before + delta, 0.0, maximum
            )
            applied["conditions"].append(
                {
                    "scope": scope,
                    "character": _character_id(character),
                    "key": str(key),
                    "delta": state.conditions[str(key)] - before,
                }
            )


def _apply_traits(faction, values, scale, applied, scope):
    if faction is None:
        return
    for key, value in _as_mapping(values).items():
        delta = _number(value) * scale
        if not delta:
            continue
        for character in _characters(faction):
            personality = getattr(character, "personality", None)
            if personality is None:
                continue
            if key not in personality.values:
                continue
            before = personality.values[key]
            personality.values[key] = _clamp(before + delta)
            applied["traits"].append(
                {
                    "scope": scope,
                    "character": _character_id(character),
                    "key": str(key),
                    "delta": personality.values[key] - before,
                }
            )


def _belief_subject(item, character):
    return str(item.get("subject") or _character_id(character))


def _apply_beliefs(faction, values, scale, applied, scope):
    character = _leader(faction)
    if character is None:
        return
    state = getattr(character, "bdi", None)
    if state is None:
        return
    values = _as_mapping(values)
    for item in values.get("add") or ():
        data = dict(_as_mapping(item))
        data.setdefault("subject", _character_id(character))
        if "value" in data:
            data["value"] = _clamp(
                _number(data.get("value")) * scale
            )
        try:
            belief = state.config.validate_belief(data)
        except bdi.BDIError:
            applied["ignored"].append(
                {"scope": scope, "belief": data, "reason": "invalid"}
            )
            continue
        existing = next(
            (
                current
                for current in state.beliefs
                if current.as_tuple() == belief.as_tuple()
            ),
            None,
        )
        if existing is not None and existing.value >= belief.value:
            continue
        state.beliefs = [
            current
            for current in state.beliefs
            if current.as_tuple() != belief.as_tuple()
        ]
        state.beliefs.append(belief)
        applied["beliefs"].append(
            {"scope": scope, "action": "add", "belief": belief.as_dict()}
        )
    for item in values.get("remove") or ():
        data = _as_mapping(item)
        predicate = str(data.get("predicate") or "")
        if not predicate:
            continue
        subject = _belief_subject(data, character)
        removed = state.forget(
            subject, predicate, data.get("object")
        )
        if removed:
            applied["beliefs"].append(
                {
                    "scope": scope,
                    "action": "remove",
                    "count": len(removed),
                }
            )


def _apply_intentions(faction, values, scale, applied, scope):
    character = _leader(faction)
    if character is None:
        return
    state = getattr(character, "bdi", None)
    if state is None:
        return
    values = _as_mapping(values)
    if values.get("clear"):
        state.intentions = []
        applied["intentions"].append(
            {"scope": scope, "action": "clear"}
        )
    pushed: List[dict] = []
    for item in values.get("push") or ():
        try:
            intention = state.config.validate_intention(item)
        except bdi.BDIError:
            applied["ignored"].append(
                {"scope": scope, "intention": item, "reason": "invalid"}
            )
            continue
        pushed.append(intention)
        applied["intentions"].append(
            {
                "scope": scope,
                "action": "push",
                "intention": intention.as_dict(),
            }
        )
    if pushed:
        state.intentions = (state.intentions + pushed)[
            -state.config.history :
        ]


def _apply_organs(faction, values, scale, applied, scope):
    if faction is None:
        return
    for organ_id, payload in _as_mapping(values).items():
        organ = faction.organ(str(organ_id))
        if organ is None:
            applied["ignored"].append(
                {
                    "scope": scope,
                    "organ": str(organ_id),
                    "reason": "unknown",
                }
            )
            continue
        payload = _as_mapping(payload)
        delta = _number(payload.get("integrity")) * scale
        if delta:
            before = organ.integrity
            organ.integrity = _clamp(before + delta)
            applied["organs"].append(
                {
                    "scope": scope,
                    "organ": str(organ_id),
                    "key": "integrity",
                    "delta": organ.integrity - before,
                }
            )
        if payload.get("state") is not None:
            applied["organs"].append(
                {
                    "scope": scope,
                    "organ": str(organ_id),
                    "key": "state",
                    "value": str(payload.get("state")),
                }
            )


def _apply_flags(faction, values, scale, applied, scope):
    if faction is None:
        return
    flags = getattr(faction, "flags", None)
    if flags is None:
        return
    for key, value in _as_mapping(values).items():
        key = str(key)
        if isinstance(value, bool):
            flags[key] = value
        elif isinstance(value, (int, float)):
            flags[key] = _number(value) * scale
        else:
            flags[key] = value
        applied["flags"].append(
            {"scope": scope, "key": key, "value": flags[key]}
        )


def _apply_scope(faction, payload, scope, scale, applied):
    payload = _as_mapping(payload)
    for key, value in payload.items():
        if key == "assets":
            _apply_assets(faction, value, scale, applied, scope)
        elif key == "needs":
            _apply_needs(faction, value, scale, applied, scope)
        elif key == "traits":
            _apply_traits(faction, value, scale, applied, scope)
        elif key == "conditions":
            _apply_conditions(faction, value, scale, applied, scope)
        elif key == "beliefs":
            _apply_beliefs(faction, value, scale, applied, scope)
        elif key == "intentions":
            _apply_intentions(faction, value, scale, applied, scope)
        elif key == "organs":
            _apply_organs(faction, value, scale, applied, scope)
        elif key == "flags":
            _apply_flags(faction, value, scale, applied, scope)
        elif key == "relations":
            # Отношения живут в WorldEngine; для AutomataCampaign это
            # отложенная область. Не превращаем её в актив молча.
            applied["ignored"].append(
                {"scope": scope, "key": "relations", "reason": "deferred"}
            )
        elif key == "text" or key == "scope":
            continue
        else:
            # Старый плоский формат: любой неструктурный ключ — актив.
            _apply_assets(
                faction, {key: value}, scale, applied, scope
            )


def apply_effects(
    actor,
    effects,
    *,
    target=None,
    scale=1.0,
    source="",
):
    """Применить словарь эффектов к действующей фракции и цели.

    ``actor`` и ``target`` — :class:`FactionRuntime`. Возвращает отчёт
    ``{"assets": [...], "needs": [...], ...}``; он же попадает в журнал
    вызывающего. Функция не знает про события: события вызывать её не
    должны.
    """
    scale = max(0.0, _number(scale, 1.0))
    applied = {
        "source": str(source or ""),
        "scale": scale,
        "assets": [],
        "needs": [],
        "traits": [],
        "conditions": [],
        "beliefs": [],
        "intentions": [],
        "organs": [],
        "flags": [],
        "ignored": [],
    }
    effects = _as_mapping(effects)
    if not effects:
        return applied

    if "self" in effects:
        _apply_scope(actor, effects.get("self"), "self", scale, applied)
    if "target" in effects:
        _apply_scope(
            target, effects.get("target"), "target", scale, applied
        )

    # Верхнеуровневые ключи нового формата применяются к действующему.
    for key, value in effects.items():
        if key in ("self", "target", "text", "scope"):
            continue
        if key == "needs" and (
            "self" in _as_mapping(value) or "target" in _as_mapping(value)
        ):
            by_scope = _as_mapping(value)
            if "self" in by_scope:
                _apply_needs(
                    actor,
                    by_scope.get("self"),
                    scale,
                    applied,
                    "self",
                )
            if "target" in by_scope:
                _apply_needs(
                    target,
                    by_scope.get("target"),
                    scale,
                    applied,
                    "target",
                )
            continue
        _apply_scope(actor, {key: value}, "self", scale, applied)
    return applied
