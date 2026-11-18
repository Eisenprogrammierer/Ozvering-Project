"""Единый движок проекций кампании.

Задача модуля — быть **единственной точкой записи** декларативного
словаря проекций: работы, взаимодействия персонажей, состояния
автоматов и подсистемы. События сюда не входят: они только читают
состояние.

Работа и взаимодействие проходят один путь:
``build_work`` → ``handlers.receive`` → ``WorkReport`` →
``apply_report``. ``apply_report`` берёт ``report.projections`` и
применяет их через ``apply_effects``; других входов в состояние из
работы нет. ``apply_effects`` остаётся публичным движком проекций
(его используют тесты и сам ``apply_report``), но не является
источником эффекта работы.

**Адресация персонажа.** ``needs``/``traits``/``conditions``/
``beliefs``/``intentions``/``morale`` по умолчанию применяются ко всем
персонажам фракции (legacy-совместимость). Если в словаре есть
``character_id``, изменение идёт только в этого персонажа — это
используется взаимодействиями (``character_interaction``), где цель —
конкретный человек, а не вся фракция.

**Мораль.** ``morale`` — отдельное поле ``Character.morale`` в диапазоне
``0..100``, не актив и не потребность. Принимает либо число
(``{"morale": 6.0}``), либо словарь
(``{"character_id": "...", "amount": 6.0}``); в обоих случаях
умножается на ``scale``.

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

STRUCTURAL_KEYS = {
    "assets",
    "needs",
    "traits",
    "conditions",
    "beliefs",
    "intentions",
    "organs",
    "subfactions",
    "relations",
    "flags",
    "text",
    "scope",
    "character_id",
    "morale",
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


def _character_id(character):
    return str(
        getattr(character, "campaign_id", "")
        or getattr(character, "name", "")
        or ""
    )


def _selected_characters(faction, character_id):
    """Персонажи для записи: один по id или все (legacy)."""
    characters = _characters(faction)
    if not character_id:
        return characters
    for character in characters:
        if _character_id(character) == str(character_id):
            return [character]
    return []


def _apply_assets(faction, values, scale, applied, scope):
    if faction is None:
        return
    for key, value in _as_mapping(values).items():
        if key == "character_id":
            continue
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
    values = _as_mapping(values)
    character_id = values.get("character_id")
    for key, value in values.items():
        if key == "character_id":
            continue
        delta = _number(value) * scale
        if not delta:
            continue
        for character in _selected_characters(faction, character_id):
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
    values = _as_mapping(values)
    character_id = values.get("character_id")
    for key, value in values.items():
        if key == "character_id":
            continue
        delta = _number(value) * scale
        if not delta:
            continue
        for character in _selected_characters(faction, character_id):
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
    values = _as_mapping(values)
    character_id = values.get("character_id")
    for key, value in values.items():
        if key == "character_id":
            continue
        delta = _number(value) * scale
        if not delta:
            continue
        for character in _selected_characters(faction, character_id):
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


def _apply_morale(faction, values, scale, applied, scope):
    """Изменить мораль персонажа (0..100), одного или всех.

    ``values`` — либо число (``{"morale": 6.0}``), либо словарь
    ``{"character_id": "...", "amount": 6.0}``. Взаимодействия
    используют второй вид: ``character_id`` адресует конкретного
    персонажа, ``amount`` — сдвиг морали. Запись кладётся в
    ``applied["flags"]`` с ``kind: "morale"``, чтобы не путать с
    флагами фракции.
    """
    if faction is None:
        return
    if isinstance(values, Mapping):
        character_id = values.get("character_id")
        amount = _number(values.get("amount"), 0.0)
    else:
        character_id = None
        amount = _number(values, 0.0)
    delta = amount * scale
    if not delta:
        return
    for character in _selected_characters(faction, character_id):
        before = _number(getattr(character, "morale", 0.0), 0.0)
        character.morale = max(0.0, min(100.0, before + delta))
        applied["flags"].append(
            {
                "scope": scope,
                "kind": "morale",
                "character": _character_id(character),
                "delta": character.morale - before,
            }
        )


def _belief_subject(item, character):
    return str(item.get("subject") or _character_id(character))


def _apply_beliefs(faction, values, scale, applied, scope):
    characters = _characters(faction)
    if not characters:
        return
    values = _as_mapping(values)
    character_id = values.get("character_id")
    targets = _selected_characters(faction, character_id) or characters[:1]
    for character in targets:
        state = getattr(character, "bdi", None)
        if state is None:
            continue
        for item in values.get("add") or ():
            data = dict(_as_mapping(item))
            data.setdefault("subject", _character_id(character))
            data.setdefault("source", "effect")
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
                {
                    "scope": scope,
                    "action": "add",
                    "character": _character_id(character),
                    "belief": belief.as_dict(),
                }
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
                        "character": _character_id(character),
                        "count": len(removed),
                    }
                )


def _apply_intentions(faction, values, scale, applied, scope):
    characters = _characters(faction)
    if not characters:
        return
    values = _as_mapping(values)
    character_id = values.get("character_id")
    targets = _selected_characters(faction, character_id) or characters[:1]
    for character in targets:
        state = getattr(character, "bdi", None)
        if state is None:
            continue
        if values.get("clear"):
            state.intentions = []
            applied["intentions"].append(
                {
                    "scope": scope,
                    "action": "clear",
                    "character": _character_id(character),
                }
            )
        pushed: List[dict] = []
        for item in values.get("push") or ():
            try:
                intention = state.config.validate_intention(item)
            except bdi.BDIError:
                applied["ignored"].append(
                    {
                        "scope": scope,
                        "intention": item,
                        "reason": "invalid",
                    }
                )
                continue
            pushed.append(intention)
            applied["intentions"].append(
                {
                    "scope": scope,
                    "action": "push",
                    "character": _character_id(character),
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
        for scale_key, value in _as_mapping(
            payload.get("scales")
        ).items():
            scale_key = str(scale_key)
            delta = _number(value) * scale
            if not delta:
                continue
            before = organ.scales.get(scale_key, 0.0)
            organ.scales[scale_key] = _clamp(before + delta)
            applied["organs"].append(
                {
                    "scope": scope,
                    "organ": str(organ_id),
                    "key": "scale:%s" % scale_key,
                    "delta": organ.scales[scale_key] - before,
                }
            )


def _apply_subfactions(faction, values, scale, applied, scope):
    """Записать активы подфракций: ``{id: {"assets": {...}}}``."""
    if faction is None:
        return
    for sub_id, payload in _as_mapping(values).items():
        sub = faction.subfaction(str(sub_id))
        if sub is None:
            applied["ignored"].append(
                {
                    "scope": scope,
                    "key": "subfaction:%s" % sub_id,
                    "reason": "unknown",
                }
            )
            continue
        payload = _as_mapping(payload)
        for key, value in _as_mapping(payload.get("assets")).items():
            delta = _number(value) * scale
            if not delta:
                continue
            before = sub.asset(key)
            sub.add_asset(key, delta)
            applied["subfactions"].append(
                {
                    "scope": scope,
                    "subfaction": sub.id,
                    "key": str(key),
                    "delta": sub.asset(key) - before,
                }
            )
        if payload.get("share") is not None:
            before = sub.share
            sub.share = _clamp(
                before + _number(payload.get("share")) * scale
            )
            applied["subfactions"].append(
                {
                    "scope": scope,
                    "subfaction": sub.id,
                    "key": "share",
                    "delta": sub.share - before,
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
        elif key == "subfactions":
            _apply_subfactions(faction, value, scale, applied, scope)
        elif key == "flags":
            _apply_flags(faction, value, scale, applied, scope)
        elif key == "morale":
            _apply_morale(faction, value, scale, applied, scope)
        elif key == "relations":
            applied["ignored"].append(
                {"scope": scope, "key": "relations", "reason": "deferred"}
            )
        elif key == "text" or key == "scope" or key == "character_id":
            continue
        else:
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

    **Движок проекций.** Работы и взаимодействия не вызывают
    ``apply_effects`` напрямую: они применяют ``WorkReport`` через
    ``apply_report``, который передаёт сюда ``report.projections``.
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
        "subfactions": [],
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


def apply_report(
    actor,
    target,
    report,
    *,
    scale=1.0,
    source="work",
):
    """Применить ``WorkReport.projections`` через ``apply_effects``.

    Единственный вход для ``WorkReport``: ``campaign.automata.perform`` и
    ``perform_*_interaction`` зовут этот метод, а не раскидывают
    ``projections`` вручную.

    Возвращает ``applied``-отчёт ``apply_effects`` плюс поле
    ``report`` с исходным ``WorkReport.as_dict()`` — это удобно для
    журнала и отладки.

    Не бросает: если ``report`` пуст или без ``projections``, возвращает
    пустой ``applied`` (с ``report``, если он был).
    """
    projections = {}
    report_dict = {}
    if report is None:
        return {
            "source": str(source or ""),
            "scale": max(0.0, _number(scale, 1.0)),
            "assets": [],
            "needs": [],
            "traits": [],
            "conditions": [],
            "beliefs": [],
            "intentions": [],
            "organs": [],
            "subfactions": [],
            "flags": [],
            "ignored": [],
            "report": report_dict,
        }
    if hasattr(report, "projections"):
        projections = dict(getattr(report, "projections") or {})
    elif isinstance(report, Mapping):
        projections = dict(_as_mapping(report.get("projections")))
    if hasattr(report, "as_dict"):
        try:
            report_dict = report.as_dict()
        except Exception:
            report_dict = {}
    elif isinstance(report, Mapping):
        report_dict = dict(report)
    applied = apply_effects(
        actor,
        projections,
        target=target,
        scale=scale,
        source=source,
    )
    applied["report"] = report_dict
    return applied


__all__ = [
    "STRUCTURAL_KEYS",
    "apply_effects",
    "apply_report",
]
