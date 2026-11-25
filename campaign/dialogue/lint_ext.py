"""Верхние слои диалога и сборка отчёта линтера.

Стиль, фолбэк, социальные акты, движение, время, нарратор, анафора,
дискурс, сравнения, контрфакты и состояние. Публичный API остаётся в
``campaign.dialogue.lint``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set

from .errors import DialogueError
from .loader import (
    CONTEXT_OPERATORS,
    DEFAULT_DIR,
    EFFECT_TYPES,
    load_dialogue,
)
from .model import AtomSpec, DialogueCatalog, GrammarRule
from .style import SELECTION_KEYS, _SUBJECT_FIELDS
from .lint_base import (
    _DISCOURSE_KINDS,
    _atom_problems,
    _fact_problems,
    _paraphrase_problems,
    _parsing_problems,
    _persona_problems,
    _plan_problems,
    _realization_problems,
    _relations,
    _rule_data_problems,
    _rule_problems,
    _synthesis_problems,
    _variables,
    _world_problems,
)
from .lint_mid import (
    _action_problems,
    _answer_kind_problems,
    _console_problems,
    _disclosure_problems,
    _goal_problems,
    _marker_problems,
    _verb_path_problems,
)


def _style_problems(catalog: DialogueCatalog) -> List[str]:
    problems: List[str] = []
    styles = getattr(catalog, "styles", None)
    if styles is None or not styles.styles:
        return ["styles: пусто"]
    if styles.default not in styles.styles:
        problems.append(
            "styles.default: стиль %r отсутствует" % styles.default
        )
    for key, style in styles.styles.items():
        where = "styles.%s" % key
        if style.id != key:
            problems.append(
                "%s.id: %r не совпадает с ключом" % (where, style.id)
            )
        if not str(style.label or "").strip():
            problems.append("%s.label: пусто" % where)
        if not str(style.register or "").strip():
            problems.append("%s.register: пусто" % where)
        for name, value in style.features.items():
            if not str(name).strip():
                problems.append("%s.features: пустое имя признака" % where)
            if not str(value).strip():
                problems.append(
                    "%s.features.%s: пустое значение" % (where, name)
                )
        for field in style.selection:
            if str(field) not in SELECTION_KEYS:
                problems.append(
                    "%s.selection.%s: неизвестное поле" % (where, field)
                )
        avoid = style.selection.get("avoid_recent")
        if avoid is not None:
            try:
                value = int(avoid)
            except (TypeError, ValueError):
                value = -1
            if value < 0:
                problems.append(
                    "%s.selection.avoid_recent: ожидалось целое >= 0"
                    % where
                )
    return problems


_FALLBACK_FIELDS = {
    "target",
    "speaker_faction",
    "player_faction",
    "speaker_id",
    "player_id",
    "side",
}
_FALLBACK_KINDS = frozenset({"question", "request"})


def _fallback_problems(catalog: DialogueCatalog) -> List[str]:
    spec = getattr(catalog, "fallback", None)
    if not isinstance(spec, Mapping) or not spec:
        return []
    problems: List[str] = []
    seen: Set[str] = set()
    for index, rule in enumerate(spec.get("rules") or ()):
        where = "fallback.rules[%d]" % index
        if not isinstance(rule, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        rule_id = str(rule.get("id") or "")
        if not rule_id:
            problems.append("%s.id: пусто" % where)
        elif rule_id in seen:
            problems.append("%s: повтор id %r" % (where, rule_id))
        seen.add(rule_id)
        when = rule.get("when")
        groups = (
            when.get("all") or when.get("any")
            if isinstance(when, Mapping)
            else when
        )
        if not groups:
            problems.append("%s.when: пусто" % where)
        sem = rule.get("sem")
        if not isinstance(sem, Mapping):
            problems.append("%s.sem: ожидался объект" % where)
            continue
        kind = str(sem.get("kind") or "")
        if kind not in _FALLBACK_KINDS:
            problems.append(
                "%s.sem.kind: неизвестный вид %r" % (where, kind)
            )
        for name in _variables(sem):
            if name not in _FALLBACK_FIELDS:
                problems.append(
                    "%s.sem: неизвестная подстановка $%s"
                    % (where, name)
                )
        if bool(rule.get("requires_target", False)) and (
            "target" not in _variables(sem)
        ):
            problems.append(
                "%s.sem: requires_target без $target" % where
            )
        use_focus = rule.get("use_focus")
        if use_focus is not None and not isinstance(use_focus, bool):
            problems.append("%s.use_focus: ожидалось true/false" % where)
        default_target = str(rule.get("default_target") or "")
        if default_target.startswith("$"):
            if default_target[1:] not in _FALLBACK_FIELDS:
                problems.append(
                    "%s.default_target: неизвестная подстановка %s"
                    % (where, default_target)
                )
    return problems


def _style_context_problems(catalog: DialogueCatalog) -> List[str]:
    problems: List[str] = []
    context = getattr(catalog, "style_context", None)
    if context is None or not context.rules:
        return problems
    known_fields = set(_SUBJECT_FIELDS.values())
    relations = set(_relations(catalog))
    seen: Set[str] = set()
    for rule in context.rules:
        where = "style_context.rules.%s" % rule.id
        if rule.id in seen:
            problems.append("%s: повтор id" % where)
        seen.add(rule.id)
        if rule.style_id not in catalog.styles.styles:
            problems.append(
                "%s.style: стиль %r отсутствует"
                % (where, rule.style_id)
            )
        if not rule.conditions:
            problems.append("%s.when: пусто" % where)
        for index, condition in enumerate(rule.conditions):
            cond_where = "%s.when[%d]" % (where, index)
            if not isinstance(condition, Mapping):
                problems.append(
                    "%s: ожидался объект" % cond_where
                )
                continue
            kind = str(condition.get("kind") or "field")
            if kind == "fact":
                rel = str(condition.get("rel") or "")
                if rel not in relations:
                    problems.append(
                        "%s.rel: отношение %r не объявлено"
                        % (cond_where, rel)
                    )
                continue
            if kind == "field":
                field_name = str(condition.get("field") or "")
                if field_name not in known_fields:
                    problems.append(
                        "%s.field: неизвестное поле %r"
                        % (cond_where, field_name)
                    )
                operator = str(condition.get("op") or "eq")
                if operator not in CONTEXT_OPERATORS:
                    problems.append(
                        "%s.op: неизвестный оператор %r"
                        % (cond_where, operator)
                    )
                continue
            problems.append(
                "%s.kind: неизвестный вид условия %r"
                % (cond_where, kind)
            )
    return problems


def _social_problems(
    catalog: DialogueCatalog, known: Mapping[str, int]
) -> List[str]:
    problems: List[str] = []
    social = getattr(catalog, "social", None)
    if social is None or not social.acts or not social.reactions:
        return ["social: пусто (нет актов или реакций)"]
    constructions = (catalog.synthesis or {}).get("constructions") or {}
    for key, act in social.acts.items():
        where = "social.acts.%s" % key
        if act.id != key:
            problems.append(
                "%s.id: %r не совпадает с ключом" % (where, act.id)
            )
        if not isinstance(act.match, Mapping) or not act.match:
            problems.append("%s.match: пустой шаблон" % where)
        if not act.reactions:
            problems.append("%s.reactions: пусто" % where)
        interaction = str(act.interaction or "")
        if interaction and not re.fullmatch(
            r"[a-z][a-z0-9_]*", interaction
        ):
            problems.append(
                "%s.interaction: %r не идентификатор кампании"
                % (where, interaction)
            )
        for reaction_id in act.reactions:
            if reaction_id not in social.reactions:
                problems.append(
                    "%s.reactions: %r отсутствует в social.reactions"
                    % (where, reaction_id)
                )
        for index, atom in enumerate(act.validity):
            problems.extend(
                _atom_problems(
                    atom, known, "%s.validity[%d]" % (where, index)
                )
            )
        for index, name in enumerate(act.taboo):
            if not str(name).strip():
                problems.append(
                    "%s.taboo[%d]: пустое имя" % (where, index)
                )
    for key, reaction in social.reactions.items():
        where = "social.reactions.%s" % key
        if reaction.id != key:
            problems.append(
                "%s.id: %r не совпадает с ключом" % (where, reaction.id)
            )
        kind = str((reaction.effect or {}).get("type") or "")
        if not kind:
            problems.append("%s.effect.type: пусто" % where)
        elif kind not in EFFECT_TYPES:
            problems.append(
                "%s.effect.type: неизвестный %r" % (where, kind)
            )
        for index, atom in enumerate(reaction.conditions):
            problems.extend(
                _atom_problems(
                    atom, known, "%s.conditions[%d]" % (where, index)
                )
            )
        construction = str(reaction.construction or "")
        if not construction:
            problems.append("%s.construction: пусто" % where)
        elif construction not in constructions:
            problems.append(
                "%s.construction: %r отсутствует в synthesis.constructions"
                % (where, construction)
            )
    commitments = social.commitments or {}
    kinds = commitments.get("kinds") or ()
    for name in kinds:
        if str(name) not in social.acts:
            problems.append(
                "social.commitments.kinds: %r отсутствует в social.acts"
                % name
            )
    try:
        ttl = int(commitments.get("ttl_turns") or 0)
    except (TypeError, ValueError):
        ttl = 0
    if ttl < 1:
        problems.append(
            "social.commitments.ttl_turns: ожидалось целое >= 1"
        )
    return problems


def _movement_problems(catalog: DialogueCatalog) -> List[str]:
    """Проверить данные перемещения: места, пороги и сообщения."""

    problems: List[str] = []
    spec = getattr(catalog, "movement", None)
    if not spec:
        return problems
    defaults = spec.get("defaults")
    if not isinstance(defaults, Mapping) or not defaults:
        problems.append("movement.defaults: пусто")
    else:
        for side, node in defaults.items():
            if not str(side).strip() or not str(node or "").strip():
                problems.append(
                    "movement.defaults.%s: пустая сторона или узел"
                    % side
                )
    places = spec.get("places")
    if not isinstance(places, Mapping) or not places:
        problems.append("movement.places: пусто")
        places = {}
    for entity_id, mapping in places.items():
        where = "movement.places.%s" % entity_id
        if not isinstance(mapping, Mapping) or not mapping:
            problems.append("%s: пустое соответствие" % where)
            continue
        for side, node in mapping.items():
            if not str(side).strip():
                problems.append("%s: пустая сторона" % where)
            if not str(node or "").strip():
                problems.append("%s.%s: пустой узел" % (where, side))
    for entry in catalog.lexicon:
        if entry.type != "organ" or not entry.id.startswith("organ:"):
            continue
        parts = entry.id.split(":")
        if len(parts) != 3:
            continue
        side, node = parts[1], parts[2]
        mapping = places.get(entry.id)
        if not isinstance(mapping, Mapping):
            problems.append(
                "movement.places.%s: нет места для органа" % entry.id
            )
        elif str(mapping.get(side) or "") != node:
            problems.append(
                "movement.places.%s: ожидался узел %r для стороны %r"
                % (entry.id, node, side)
            )
    bands = spec.get("bands")
    if not isinstance(bands, list) or not bands:
        problems.append("movement.bands: пусто")
    else:
        previous = None
        for index, band in enumerate(bands):
            where = "movement.bands[%d]" % index
            if not isinstance(band, Mapping):
                problems.append("%s: не объект" % where)
                continue
            if not str(band.get("id") or "").strip():
                problems.append("%s.id: пусто" % where)
            if not str(band.get("label") or "").strip():
                problems.append("%s.label: пусто" % where)
            maximum = band.get("max")
            if maximum is None:
                continue
            try:
                value = float(maximum)
            except (TypeError, ValueError):
                problems.append("%s.max: не число" % where)
                continue
            if previous is not None and value <= previous:
                problems.append(
                    "%s.max: пороги должны возрастать" % where
                )
            previous = value
    messages = spec.get("messages")
    if not isinstance(messages, Mapping) or not messages:
        problems.append("movement.messages: пусто")
    else:
        required = (
            "arrived",
            "route",
            "already",
            "disabled",
            "unknown",
            "no_path",
            "no_geometry",
            "no_start",
            "not_move",
        )
        for key in required:
            if not str(messages.get(key) or "").strip():
                problems.append(
                    "movement.messages.%s: пусто" % key
                )
    return problems


def _time_problems(catalog: DialogueCatalog) -> List[str]:
    """Проверить длительности, фазы, темп и сообщения ``time.json``."""

    problems: List[str] = []
    spec = getattr(catalog, "time", None)
    if not spec:
        return problems
    for key in ("wait_seconds", "cycle_seconds"):
        try:
            value = float(spec.get(key))
        except (TypeError, ValueError):
            problems.append("time.%s: не число" % key)
            continue
        if value <= 0.0:
            problems.append("time.%s: должно быть больше нуля" % key)
    phases = spec.get("phases")
    if not isinstance(phases, Mapping) or not phases:
        problems.append("time.phases: пусто")
        phases = {}
    entity_ids = set()
    for entry in catalog.lexicon:
        semantic = entry.semantic
        if isinstance(semantic, Mapping) and semantic.get("kind") == "entity":
            entity_ids.add(str(semantic.get("id") or ""))
    for entity_id, entry in phases.items():
        where = "time.phases.%s" % entity_id
        if not isinstance(entry, Mapping):
            problems.append("%s: не объект" % where)
            continue
        if str(entity_id) not in entity_ids:
            problems.append("%s: нет такой сущности в лексиконе" % where)
        try:
            hour = float(entry.get("hour"))
        except (TypeError, ValueError):
            problems.append("%s.hour: не число" % where)
        else:
            if hour < 0.0 or hour >= 24.0:
                problems.append("%s.hour: вне 0..23" % where)
        if not str(entry.get("label") or "").strip():
            problems.append("%s.label: пусто" % where)
    speeds = spec.get("speeds")
    if not isinstance(speeds, Mapping) or not speeds:
        problems.append("time.speeds: пусто")
        speeds = {}
    for direction in ("up", "down", "reset"):
        where = "time.speeds.%s" % direction
        entry = speeds.get(direction)
        if not isinstance(entry, Mapping):
            problems.append("%s: нет направления" % where)
            continue
        for key in ("label", "done", "limit"):
            if not str(entry.get(key) or "").strip():
                problems.append("%s.%s: пусто" % (where, key))
    messages = spec.get("messages")
    if not isinstance(messages, Mapping) or not messages:
        problems.append("time.messages: пусто")
    else:
        required = (
            "waited",
            "planned_wait",
            "arrived",
            "planned_phase",
            "unknown_phase",
            "speed_done",
            "speed_planned",
            "speed_limit",
            "no_campaign",
            "finished",
            "finished_during",
            "not_time",
        )
        for key in required:
            if not str(messages.get(key) or "").strip():
                problems.append("time.messages.%s: пусто" % key)
    return problems


def _narrator_problems(catalog: DialogueCatalog) -> List[str]:
    """Проверить лимиты, шаблоны и подписи ``narrator.json``."""

    problems: List[str] = []
    spec = getattr(catalog, "narrator", None)
    if not spec:
        return problems
    limit = spec.get("limit")
    maximum = spec.get("max_limit")
    try:
        limit_value = int(limit)
    except (TypeError, ValueError):
        problems.append("narrator.limit: ожидалось целое >= 1")
        limit_value = 0
    try:
        max_value = int(maximum)
    except (TypeError, ValueError):
        problems.append("narrator.max_limit: ожидалось целое >= 1")
        max_value = 0
    if limit_value < 1:
        problems.append("narrator.limit: ожидалось целое >= 1")
    if max_value < 1:
        problems.append("narrator.max_limit: ожидалось целое >= 1")
    if limit_value > 0 and max_value > 0 and limit_value > max_value:
        problems.append("narrator.limit: больше max_limit")
    if not isinstance(spec.get("visible_only"), bool):
        problems.append("narrator.visible_only: ожидался bool")
    if not isinstance(spec.get("line_prefix"), str):
        problems.append("narrator.line_prefix: ожидалась строка")
    sources = spec.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        problems.append("narrator.sources: пусто")
    else:
        for source, value in sources.items():
            try:
                priority = int(value)
            except (TypeError, ValueError):
                problems.append(
                    "narrator.sources.%s: не целое" % source
                )
                continue
            if priority < 0:
                problems.append(
                    "narrator.sources.%s: отрицательный приоритет"
                    % source
                )
    bands = spec.get("severity_bands")
    if not isinstance(bands, (list, tuple)) or not bands:
        problems.append("narrator.severity_bands: пусто")
    else:
        previous = None
        terminal = False
        for index, band in enumerate(bands):
            where = "narrator.severity_bands[%d]" % index
            if not isinstance(band, Mapping):
                problems.append("%s: не объект" % where)
                continue
            if not str(band.get("label") or "").strip():
                problems.append("%s.label: пусто" % where)
            boundary = band.get("max")
            if boundary is None:
                if terminal:
                    problems.append(
                        "%s.max: None должен быть последним" % where
                    )
                terminal = True
                continue
            if terminal:
                problems.append(
                    "%s.max: значение после None" % where
                )
            try:
                value = float(boundary)
            except (TypeError, ValueError):
                problems.append("%s.max: не число" % where)
                continue
            if previous is not None and value <= previous:
                problems.append("%s.max: пороги должны возрастать" % where)
            previous = value
        if not terminal:
            problems.append("narrator.severity_bands: нет последней полосы")
    forms = spec.get("forms")
    if not isinstance(forms, Mapping) or not forms:
        problems.append("narrator.forms: пусто")
    else:
        for key, value in forms.items():
            if not str(key).strip():
                problems.append("narrator.forms: пустой ключ")
            if not str(value or "").strip():
                problems.append("narrator.forms.%s: пусто" % key)
        if "work" not in forms:
            problems.append("narrator.forms.work: отсутствует")
    outcomes = spec.get("outcomes")
    if not isinstance(outcomes, Mapping) or not outcomes:
        problems.append("narrator.outcomes: пусто")
    else:
        for key in ("success", "failure"):
            if not str(outcomes.get(key) or "").strip():
                problems.append("narrator.outcomes.%s: пусто" % key)
    kinds = spec.get("kinds")
    if not isinstance(kinds, Mapping) or not kinds:
        problems.append("narrator.kinds: пусто")
        kinds = {}
    for kind in ("story", "work", "organ", "automaton", "character"):
        where = "narrator.kinds.%s" % kind
        entry = kinds.get(kind)
        if not isinstance(entry, Mapping):
            problems.append("%s: отсутствует" % where)
            continue
        template = str(entry.get("template") or "")
        if not template.strip():
            problems.append("%s.template: пусто" % where)
        elif "{text}" not in template:
            problems.append("%s.template: нет {text}" % where)
    fallback = spec.get("fallback")
    if not isinstance(fallback, Mapping):
        problems.append("narrator.fallback: ожидался объект")
    else:
        template = str(fallback.get("template") or "")
        if not template.strip():
            problems.append("narrator.fallback.template: пусто")
        elif "{text}" not in template:
            problems.append("narrator.fallback.template: нет {text}")
    messages = spec.get("messages")
    if not isinstance(messages, Mapping) or not messages:
        problems.append("narrator.messages: пусто")
    else:
        for key in ("header", "empty", "no_campaign"):
            if not str(messages.get(key) or "").strip():
                problems.append("narrator.messages.%s: пусто" % key)
    return problems


def _anaphora_problems(catalog: DialogueCatalog) -> List[str]:
    """Проверить анафору: типы, роды, местоимения, min_length."""

    problems: List[str] = []
    discourse = getattr(catalog, "discourse", None)
    if discourse is None:
        return problems
    anaphora = getattr(discourse, "anaphora", None)
    if anaphora is None or not getattr(anaphora, "enabled", False):
        return problems
    entity_types = set(catalog.ontology.entity_types)
    for type_name in getattr(anaphora, "types", ()) or ():
        if type_name not in entity_types:
            problems.append(
                "discourse.anaphora.types: неизвестный тип %r"
                % type_name
            )
    known_kinds = {str(move_id) for move_id in discourse.moves}
    for kind in getattr(anaphora, "kinds", ()) or ():
        if kind not in known_kinds:
            problems.append(
                "discourse.anaphora.kinds: ход %r отсутствует"
                % kind
            )
    try:
        min_length = int(getattr(anaphora, "min_length", 0))
    except (TypeError, ValueError):
        min_length = 0
    if min_length < 1:
        problems.append(
            "discourse.anaphora.min_length: должно быть >= 1"
        )
    pronouns = getattr(anaphora, "pronouns", {}) or {}
    for key, value in pronouns.items():
        gender, _, number = str(key).partition(":")
        if gender not in ("m", "f", "n"):
            problems.append(
                "discourse.anaphora.pronouns.%s: "
                "неизвестный род %r" % (key, gender)
            )
        if number not in ("sg", "pl"):
            problems.append(
                "discourse.anaphora.pronouns.%s: "
                "неизвестное число %r" % (key, number)
            )
        if not str(value).strip():
            problems.append(
                "discourse.anaphora.pronouns.%s: пустое местоимение"
                % key
            )
    return problems


def _discourse_problems(
    catalog: DialogueCatalog, known: Mapping[str, int]
) -> List[str]:
    problems: List[str] = []
    discourse = getattr(catalog, "discourse", None)
    if discourse is None:
        return problems
    if not discourse.moves:
        return problems
    constructions = (catalog.synthesis or {}).get("constructions") or {}
    relations = known
    for key, move in discourse.moves.items():
        where = "discourse.moves.%s" % key
        if move.id != key:
            problems.append(
                "%s.id: %r не совпадает с ключом" % (where, move.id)
            )
        modes = sum(
            1 for item in (move.act, move.construction, move.relation)
            if item
        )
        if modes == 0 and not move.source:
            problems.append(
                "%s: нужен act, construction, relation или source"
                % where
            )
        if modes > 1:
            problems.append(
                "%s: одновременно act/construction/relation запрещены"
                % where
            )
        if move.construction and move.construction not in constructions:
            problems.append(
                "%s.construction: %r отсутствует в synthesis.constructions"
                % (where, move.construction)
            )
        if move.relation and move.relation not in relations:
            problems.append(
                "%s.relation: %r не объявлено в world.relations"
                % (where, move.relation)
            )
        if move.relation and not move.source:
            problems.append(
                "%s.source: relation без source (имя поля данных)"
                % where
            )
    seen_patterns: Set[str] = set()
    for pattern in discourse.patterns:
        where = "discourse.patterns.%s" % pattern.id
        if pattern.id in seen_patterns:
            problems.append("%s: повтор id" % where)
        seen_patterns.add(pattern.id)
        if not pattern.moves:
            problems.append("%s.moves: пусто" % where)
        for move_id in pattern.moves:
            if move_id not in discourse.moves:
                problems.append(
                    "%s.moves: ход %r отсутствует в discourse.moves"
                    % (where, move_id)
                )
        if pattern.topic and pattern.topic not in pattern.moves:
            problems.append(
                "%s.topic: %r отсутствует в moves"
                % (where, pattern.topic)
            )
        seen_topics: Set[str] = set()
        for topic_id in pattern.topics:
            if not str(topic_id).strip():
                problems.append(
                    "%s.topics: пустой id" % where
                )
                continue
            if topic_id in seen_topics:
                problems.append(
                    "%s.topics: повтор хода %r" % (where, topic_id)
                )
                continue
            seen_topics.add(topic_id)
            if topic_id not in pattern.moves:
                problems.append(
                    "%s.topics: ход %r отсутствует в moves"
                    % (where, topic_id)
                )
        if pattern.kind and pattern.kind not in _DISCOURSE_KINDS:
            problems.append(
                "%s.kind: неизвестный вид ответа %r"
                % (where, pattern.kind)
            )
    seen_connectives: Set[str] = set()
    for connective in discourse.connectives:
        where = "discourse.connectives.%s" % (
            connective.get("id") or "?"
        )
        identifier = str(connective.get("id") or "")
        if not identifier:
            problems.append("%s: пустой id" % where)
        elif identifier in seen_connectives:
            problems.append("%s: повтор id" % where)
        seen_connectives.add(identifier)
        text = str(connective.get("text") or "")
        if not text.strip():
            problems.append("%s.text: пусто" % where)
        features = connective.get("features")
        if features is not None and not isinstance(features, Mapping):
            problems.append(
                "%s.features: ожидался объект" % where
            )
        position = str(connective.get("position") or "between")
        if position not in ("between", "after", "before"):
            problems.append(
                "%s.position: неизвестное значение %r"
                % (where, position)
            )
        mode = str(connective.get("mode") or "plain")
        if mode not in ("plain", "clause"):
            problems.append(
                "%s.mode: неизвестный режим %r" % (where, mode)
            )
        lowercase_glue = connective.get("lowercase_glue")
        if lowercase_glue is not None:
            if not isinstance(lowercase_glue, bool):
                problems.append(
                    "%s.lowercase_glue: ожидалось true/false" % where
                )
            elif mode != "clause":
                problems.append(
                    "%s.lowercase_glue: имеет смысл только для "
                    "mode=clause" % where
                )
    problems.extend(_anaphora_problems(catalog))
    return problems


def _comparison_problems(
    catalog: DialogueCatalog, known: Mapping[str, int]
) -> List[str]:
    problems: List[str] = []
    comparison = getattr(catalog, "comparison", None)
    if comparison is None or not comparison.comparisons:
        return problems
    constructions = (catalog.synthesis or {}).get("constructions") or {}
    for key, spec in comparison.comparisons.items():
        where = "comparison.comparisons.%s" % key
        if spec.id != key:
            problems.append(
                "%s.id: %r не совпадает с ключом" % (where, spec.id)
            )
        if spec.relation not in known:
            problems.append(
                "%s.relation: %r не объявлено в world.relations"
                % (where, spec.relation)
            )
        else:
            arity = known[spec.relation]
            for name in (
                "value_arg",
                "key_arg",
                "subject_arg",
            ):
                position = getattr(spec, name)
                if position < 0 or position >= arity:
                    problems.append(
                        "%s.%s: позиция %d вне арности %d"
                        % (where, name, position, arity)
                    )
            for arg_name, position in spec.args.items():
                if position < 0 or position >= arity:
                    problems.append(
                        "%s.args.%s: позиция %d вне арности %d"
                        % (where, arg_name, position, arity)
                    )
        if spec.scale:
            if len(spec.scale) < 2:
                problems.append(
                    "%s.scale: нужно минимум два значения" % where
                )
            seen_scale = set()
            for index, item in enumerate(spec.scale):
                token = str(item or "").strip().casefold()
                if not token:
                    problems.append(
                        "%s.scale[%d]: пустое значение"
                        % (where, index)
                    )
                    continue
                if token in seen_scale:
                    problems.append(
                        "%s.scale[%d]: повтор значения %r"
                        % (where, index, item)
                    )
                seen_scale.add(token)
        for name in (
            "greater",
            "less",
            "equal",
            "unknown_left",
            "unknown_right",
            "both_unknown",
        ):
            construction = str(getattr(spec, name, "") or "")
            if not construction:
                problems.append(
                    "%s.%s: пустая конструкция" % (where, name)
                )
                continue
            if construction not in constructions:
                problems.append(
                    "%s.%s: конструкция %r отсутствует"
                    % (where, name, construction)
                )
    return problems


def _counterfactual_problems(
    catalog: DialogueCatalog, known: Mapping[str, int]
) -> List[str]:
    """Проверить whitelist, шаги и ссылки на конструкции."""

    problems: List[str] = []
    spec = getattr(catalog, "counterfactual", None)
    if spec is None or not spec.relations:
        return problems
    constructions = (catalog.synthesis or {}).get("constructions") or {}
    for relation in spec.relations:
        if relation not in known:
            problems.append(
                "counterfactual.relations: %r не объявлено в "
                "world.relations" % relation
            )
    try:
        steps = int(spec.max_steps)
    except (TypeError, ValueError):
        steps = 0
    if steps < 1:
        problems.append(
            "counterfactual.max_steps: ожидалось целое >= 1"
        )
    for outcome, construction in spec.outcomes.items():
        if outcome not in ("changed", "unchanged", "unknown"):
            problems.append(
                "counterfactual.outcomes.%s: неизвестный исход"
                % outcome
            )
        if not construction:
            problems.append(
                "counterfactual.outcomes.%s: пустая конструкция"
                % outcome
            )
        elif construction not in constructions:
            problems.append(
                "counterfactual.outcomes.%s: конструкция %r "
                "отсутствует в synthesis.constructions"
                % (outcome, construction)
            )
    return problems


def _state_problems(catalog: DialogueCatalog) -> List[str]:
    policy = catalog.state or {}
    problems: List[str] = []
    if not policy:
        return ["state: пусто"]
    pronouns = policy.get("pronouns") or {}
    if not isinstance(pronouns, Mapping) or not pronouns:
        problems.append("state.pronouns: пусто")
    else:
        for key, item in pronouns.items():
            data = item if isinstance(item, Mapping) else {}
            if not data:
                problems.append("state.pronouns.%s: ожидался объект" % key)
                continue
            gender = str(data.get("gender") or "")
            if gender and gender not in ("m", "f", "n", "pl"):
                problems.append(
                    "state.pronouns.%s: неизвестный род %r" % (key, gender)
                )
            number = str(data.get("number") or "")
            if number and number not in ("sg", "pl"):
                problems.append(
                    "state.pronouns.%s: неизвестное число %r"
                    % (key, number)
                )
    referents = policy.get("referents") or {}
    if not isinstance(referents, Mapping):
        problems.append("state.referents: ожидался объект")
        referents = {}
    try:
        if int(referents.get("max_active", 0)) < 1:
            problems.append("state.referents.max_active: должно быть > 0")
    except (TypeError, ValueError):
        problems.append("state.referents.max_active: ожидалось число")
    types = set(catalog.ontology.entity_types)
    for type_name in (referents.get("type_gender") or {}):
        if str(type_name) not in types:
            problems.append(
                "state.referents.type_gender.%s: нет такого типа"
                % type_name
            )
    focus = policy.get("focus") or {}
    if not isinstance(focus, Mapping):
        problems.append("state.focus: ожидался объект")
        focus = {}
    for type_name in focus.get("types") or ():
        if str(type_name) not in types:
            problems.append(
                "state.focus.types: неизвестный тип %r" % str(type_name)
            )
    if focus:
        try:
            if float(focus.get("min_salience", 0)) < 0:
                problems.append(
                    "state.focus.min_salience: должно быть >= 0"
                )
        except (TypeError, ValueError):
            problems.append(
                "state.focus.min_salience: ожидалось число"
            )
        try:
            if int(focus.get("max_age", 0)) < 0:
                problems.append("state.focus.max_age: должно быть >= 0")
        except (TypeError, ValueError):
            problems.append("state.focus.max_age: ожидалось число")
    qud = policy.get("qud") or {}
    for source in qud.get("base_order") or ():
        if str(source) not in ("qud", "last_sem"):
            problems.append(
                "state.qud.base_order: неизвестный источник %r" % source
            )
    known_relations = set(_relations(catalog))
    memory = policy.get("memory") or {}
    for section in ("significant", "pins"):
        for relation in (memory.get(section) or {}).get("relations") or ():
            if str(relation) not in known_relations:
                problems.append(
                    "state.memory.%s.relations: %r не объявлено"
                    % (section, relation)
                )
    for type_name in (memory.get("pins") or {}).get("types") or ():
        if str(type_name) not in types:
            problems.append(
                "state.memory.pins.types: неизвестный тип %r" % type_name
            )
    limits = memory.get("limits") or {}
    for name, value in limits.items():
        try:
            if int(value) < 1:
                problems.append(
                    "state.memory.limits.%s: должно быть > 0" % name
                )
        except (TypeError, ValueError):
            problems.append(
                "state.memory.limits.%s: ожидалось число" % name
            )
    kinds = {"pronoun", "entity", "noun"}
    fragments = policy.get("fragments") or ()
    if not isinstance(fragments, (list, tuple)) or not fragments:
        problems.append("state.fragments: пусто")
        fragments = ()
    seen: set = set()
    for index, item in enumerate(fragments):
        data = item if isinstance(item, Mapping) else {}
        where = "state.fragments[%d]" % index
        if not data:
            problems.append("%s: ожидался объект" % where)
            continue
        identifier = str(data.get("id") or "").strip()
        if not identifier:
            problems.append("%s: пустой id" % where)
            continue
        if identifier in seen:
            problems.append("%s: повтор id %r" % (where, identifier))
        seen.add(identifier)
        where = "state.fragments.%s" % identifier
        tokens = data.get("tokens") or ()
        if not isinstance(tokens, (list, tuple)) or not tokens:
            problems.append("%s.tokens: пусто" % where)
            continue
        slots: Set[str] = set()
        for token in tokens:
            if isinstance(token, str):
                continue
            spec = token if isinstance(token, Mapping) else {}
            if not spec:
                problems.append(
                    "%s.tokens: ожидалась строка или объект" % where
                )
                continue
            if "any" in spec:
                values = spec.get("any") or ()
                if not isinstance(values, (list, tuple)) or not values:
                    problems.append("%s.tokens.any: пусто" % where)
                continue
            slot = str(spec.get("slot") or "").strip()
            kind = str(spec.get("kind") or "entity")
            if not slot:
                problems.append("%s.tokens: пустой slot" % where)
                continue
            if slot in slots:
                problems.append("%s.tokens: повтор слота %r" % (where, slot))
            slots.add(slot)
            if kind not in kinds:
                problems.append(
                    "%s.tokens.%s: неизвестный вид %r"
                    % (where, slot, kind)
                )
        describe = data.get("describe")
        if describe is not None:
            reference = str(describe)
            if not reference.startswith("$") or reference[1:] not in slots:
                problems.append(
                    "%s.describe: ссылка %r не на слот"
                    % (where, describe)
                )
        for edit_index, edit in enumerate(data.get("edits") or ()):
            edit_where = "%s.edits[%d]" % (where, edit_index)
            spec = edit if isinstance(edit, Mapping) else {}
            if not spec:
                problems.append("%s: ожидался объект" % edit_where)
                continue
            paths = spec.get("paths")
            if paths is None:
                path = str(spec.get("path") or "").strip()
                if not path:
                    problems.append("%s: пустой path" % edit_where)
            elif not isinstance(paths, (list, tuple)) or not paths:
                problems.append("%s.paths: пусто" % edit_where)
            value = spec.get("value")
            if value is None:
                problems.append("%s: пустое value" % edit_where)
            elif isinstance(value, str) and value.startswith("$"):
                if value[1:] not in slots:
                    problems.append(
                        "%s.value: ссылка %r не на слот"
                        % (edit_where, value)
                    )
    clarifications = policy.get("clarifications") or {}
    for reason in ("no_qud", "no_referent", "no_entity", "no_match"):
        if not str(clarifications.get(reason) or "").strip():
            problems.append("state.clarifications.%s: пусто" % reason)
    return problems


def lint_catalog(catalog: DialogueCatalog) -> List[str]:
    problems: List[str] = []
    lexicon_cats = {entry.cat for entry in catalog.lexicon}
    lhs_cats = {rule.lhs for rule in catalog.grammar.rules}
    known_cats = lexicon_cats | lhs_cats

    if catalog.grammar.start not in lhs_cats:
        problems.append(
            "грамматика: стартовый символ %r не является lhs ни одного "
            "правила" % catalog.grammar.start
        )

    for rule in catalog.grammar.rules:
        problems.extend(_rule_problems(rule))
        for item in rule.rhs:
            if item.cat not in known_cats:
                problems.append(
                    "правило %s: неизвестная категория %r"
                    % (rule.id, item.cat)
                )

    entity_types = set(catalog.ontology.entity_types)
    for entry in catalog.lexicon:
        if not entry.all_forms():
            problems.append(
                "лексема %s: нет ни одной поверхностной формы" % entry.id
            )
        form_texts = {form.text for form in entry.forms}
        for alias in entry.aliases:
            if alias.text in form_texts:
                problems.append(
                    "лексема %s: псевдоним %r дублирует форму"
                    % (entry.id, alias.text)
                )
        semantic = entry.semantic
        if isinstance(semantic, Mapping):
            kind = semantic.get("kind")
            if kind == "entity":
                entry_type = str(semantic.get("type") or "")
                if entry_type and entry_type not in entity_types:
                    problems.append(
                        "лексема %s: тип %r отсутствует в онтологии"
                        % (entry.id, entry_type)
                    )

    known = _relations(catalog)
    problems.extend(_rule_data_problems(catalog, known))
    problems.extend(_fact_problems(catalog, known))
    problems.extend(_plan_problems(catalog, known))
    problems.extend(_realization_problems(catalog, known))
    problems.extend(_synthesis_problems(catalog, known))
    problems.extend(_world_problems(catalog))
    problems.extend(_persona_problems(catalog))
    problems.extend(_style_problems(catalog))
    problems.extend(_style_context_problems(catalog))
    problems.extend(_state_problems(catalog))
    problems.extend(_social_problems(catalog, known))
    problems.extend(_discourse_problems(catalog, known))
    problems.extend(_anaphora_problems(catalog))
    problems.extend(_comparison_problems(catalog, known))
    problems.extend(_counterfactual_problems(catalog, known))
    problems.extend(_parsing_problems(catalog))
    problems.extend(_paraphrase_problems(catalog))
    problems.extend(_goal_problems(catalog))
    problems.extend(_action_problems(catalog))
    problems.extend(_marker_problems(catalog))
    problems.extend(_verb_path_problems(catalog))
    problems.extend(_answer_kind_problems(catalog))
    problems.extend(_console_problems(catalog))
    problems.extend(_movement_problems(catalog))
    problems.extend(_time_problems(catalog))
    problems.extend(_narrator_problems(catalog))
    problems.extend(_disclosure_problems(catalog))
    problems.extend(_fallback_problems(catalog))
    return problems


def lint_directory(directory: Path | str | None = None) -> List[str]:
    root = Path(directory) if directory is not None else DEFAULT_DIR
    try:
        catalog = load_dialogue(root)
    except DialogueError as error:
        return [str(error)]
    return lint_catalog(catalog)


def main() -> int:
    problems = lint_directory()
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print("диалоговые данные в порядке")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
