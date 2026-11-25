"""Линтер BDI-ядра: желания, убеждения, намерения и эффекты."""

from __future__ import annotations

from collections.abc import Mapping

import bdi
from . import content_schema


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


EFFECT_KEYS = content_schema.schema_keys("effects")
REQUIRE_KEYS = content_schema.schema_keys("requires")
CONDITION_KINDS = content_schema.condition_kinds()


def _belief_parts(item):
    if isinstance(item, Mapping):
        return (
            str(item.get("subject") or ""),
            str(item.get("predicate") or ""),
            str(item.get("object") or ""),
        )
    if isinstance(item, (list, tuple)) and len(item) == 3:
        return tuple(str(part or "") for part in item)
    return ("", "", "")


def _intention_parts(item):
    if isinstance(item, Mapping):
        return (
            str(item.get("target") or ""),
            str(item.get("essence") or ""),
        )
    if isinstance(item, (list, tuple)) and len(item) == 2:
        return tuple(str(part or "") for part in item)
    return ("", "")


def check_bdi(config):
    """Проверить ``configs/characters/bdi.json``."""
    problems: List[str] = []
    if tuple(config.needs) != bdi.NEEDS:
        problems.append(
            "needs: набор должен совпадать с bdi.NEEDS (%d позиций)"
            % len(bdi.NEEDS)
        )
    for key, definition in config.predicates.items():
        definition = _as_mapping(definition)
        kind = str(definition.get("kind") or "")
        if kind not in ("relation", "property"):
            problems.append(
                "belief_predicates.%s: kind должен быть relation/property"
                % key
            )
        rule = definition.get("object")
        if rule is not None and str(rule) not in ("required", "forbidden"):
            problems.append(
                "belief_predicates.%s.object: ожидалось "
                "required/forbidden" % key
            )
    for key, essence in config.essences.items():
        need = str(_as_mapping(essence).get("need") or "")
        if need not in config.needs:
            problems.append(
                "intention_essences.%s: неизвестная потребность %r"
                % (key, need)
            )
    return problems


def check_beliefs(source, items, config):
    problems: List[str] = []
    for index, item in enumerate(_as_list(items)):
        subject, predicate, obj = _belief_parts(item)
        where = "%s.beliefs[%d]" % (source, index)
        if not subject or not predicate:
            problems.append(
                "%s: убеждение требует subject и predicate" % where
            )
            continue
        if predicate not in config.predicates:
            problems.append(
                "%s: неизвестный предикат %r" % (where, predicate)
            )
            continue
        rule = config.predicate_object_rule(predicate)
        if rule == "required" and not obj:
            problems.append(
                "%s: предикат %r требует object" % (where, predicate)
            )
        elif rule == "forbidden" and obj:
            problems.append(
                "%s: предикат-свойство %r не имеет object"
                % (where, predicate)
            )
    return problems


def check_intentions(source, items, config):
    problems: List[str] = []
    for index, item in enumerate(_as_list(items)):
        target, essence = _intention_parts(item)
        where = "%s.intentions[%d]" % (source, index)
        if not target or not essence:
            problems.append(
                "%s: намерение должно быть дуплетом target/essence" % where
            )
            continue
        if essence not in config.essences:
            problems.append("%s: неизвестная суть %r" % (where, essence))
    return problems


def check_effects(source, effects):
    problems: List[str] = content_schema.validate(
        "effects", effects, source
    )
    effects = _as_mapping(effects)
    for key, value in effects.items():
        where = "%s.%s" % (source, key)
        if key not in EFFECT_KEYS:
            problems.append(
                "%s: эффект %r не поддерживается ядром" % (where, key)
            )
        elif key in (
            "self",
            "target",
            "assets",
            "needs",
            "traits",
            "conditions",
            "organs",
            "subfactions",
            "flags",
        ):
            if not isinstance(value, Mapping):
                problems.append("%s: ожидался объект" % where)
    return problems


def _condition_problems(source, conditions):
    problems: List[str] = []
    if isinstance(conditions, Mapping):
        if any(key in conditions for key in ("all", "any", "not")):
            items = [conditions]
        else:
            items = [conditions]
    elif isinstance(conditions, (list, tuple)):
        items = list(conditions)
    else:
        return ["%s: условие должно быть объектом или списком" % source]
    for index, clause in enumerate(items):
        where = "%s[%d]" % (source, index)
        clause = _as_mapping(clause)
        if not clause:
            problems.append("%s: пустое условие" % where)
            continue
        for group in ("all", "any"):
            if group in clause:
                problems.extend(
                    _condition_problems(
                        "%s.%s" % (where, group), clause.get(group)
                    )
                )
        if "not" in clause:
            problems.extend(
                _condition_problems(where + ".not", clause.get("not"))
            )
        if any(key in clause for key in ("all", "any", "not")):
            continue
        kind = str(clause.get("kind") or "asset")
        if kind not in CONDITION_KINDS:
            problems.append(
                "%s: неизвестный вид условия %r" % (where, kind)
            )
        elif kind == "distance" and not (
            clause.get("from") and clause.get("to")
        ):
            problems.append(
                "%s: для distance нужны from и to" % where
            )
        elif kind == "angle" and not (
            clause.get("node") and clause.get("from") and clause.get("to")
        ):
            problems.append(
                "%s: для angle нужны node, from и to" % where
            )
        elif kind == "relation" and not (
            clause.get("target") or clause.get("key") or clause.get("id")
        ):
            problems.append(
                "%s: для relation нужна цель (target/key)" % where
            )
    return problems


def check_requires(source, requires):
    problems: List[str] = content_schema.validate(
        "requires", requires, source
    )
    requires = _as_mapping(requires)
    for key in requires:
        if key not in REQUIRE_KEYS:
            problems.append(
                "%s: условие %r не поддерживается ядром" % (source, key)
            )
    if "when" in requires:
        problems.extend(
            _condition_problems(
                source + ".when", requires.get("when")
            )
        )
    return problems
