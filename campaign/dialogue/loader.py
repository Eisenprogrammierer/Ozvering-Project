"""Загрузка диалоговых данных из JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .errors import DialogueError
from .model import (
    AtomSpec,
    ComparisonCatalog,
    ComparisonSpec,
    DialogueCatalog,
    DiscourseAnaphora,
    DiscourseCatalog,
    DiscourseMove,
    DiscoursePattern,
    FactSpec,
    FeatureSchema,
    Grammar,
    GrammarRule,
    LexEntry,
    LexForm,
    Ontology,
    Persona,
    PlanSpec,
    ReactionSpec,
    RuleItem,
    RuleSpec,
    SocialActSpec,
    SocialCatalog,
    StyleCatalog,
    StyleContextCatalog,
    StyleContextRule,
    StyleSpec,
)

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "configs" / "dialogue"

CASES = ("nom", "gen", "dat", "acc", "ins", "prep")

EFFECT_TYPES = frozenset(
    {
        "commitment",
        "refusal",
        "evasion",
        "counter_offer",
        "clarification",
    }
)

MOVE_MODES = ("act", "construction", "relation")

CONTEXT_OPERATORS = frozenset(
    {
        "eq",
        "ne",
        "in",
        "not_in",
        "exists",
    }
)

CONNECTIVE_MODES = frozenset({"plain", "clause"})


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DialogueError("%s: ожидался объект" % where)
    return value


def _sequence(value: Any, where: str) -> Iterable[Any]:
    if isinstance(value, (list, tuple)):
        return value
    raise DialogueError("%s: ожидался список" % where)


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DialogueError("%s: ожидалась непустая строка" % where)
    return value.strip()


def _features(value: Any, where: str) -> Dict[str, str]:
    if value is None:
        return {}
    data = _mapping(value, where)
    result: Dict[str, str] = {}
    for key, item in data.items():
        if not isinstance(item, (str, int, float, bool)):
            raise DialogueError(
                "%s.%s: признак должен быть скаляром" % (where, key)
            )
        result[str(key)] = str(item)
    return result


def _form_from_text(
    text: str, features: Mapping[str, Any], where: str
) -> LexForm:
    return LexForm(
        text=_text(text, where),
        features=_features(features, where + ".features"),
    )


def _parse_forms(value: Any, where: str) -> Tuple[LexForm, ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        result: List[LexForm] = []
        for key, texts in value.items():
            if isinstance(texts, str):
                texts = [texts]
            if key in CASES:
                features = {"case": key, "number": "sg"}
            elif key.endswith("_pl") and key[:-3] in CASES:
                features = {"case": key[:-3], "number": "pl"}
            else:
                features = {"form": str(key)}
            for text in _sequence(texts, "%s.%s" % (where, key)):
                result.append(
                    _form_from_text(text, features, "%s.%s" % (where, key))
                )
        return tuple(result)
    result = []
    for index, item in enumerate(_sequence(value, where)):
        item_where = "%s[%d]" % (where, index)
        if isinstance(item, str):
            result.append(_form_from_text(item, {}, item_where))
            continue
        data = _mapping(item, item_where)
        text = data.get("text") or data.get("form")
        features = {
            key: value
            for key, value in data.items()
            if key not in ("text", "form")
        }
        result.append(_form_from_text(text, features, item_where))
    return tuple(result)


def _entity_types(raw: Any) -> Dict[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for key, value in _mapping(raw, "ontology.entity_types").items():
        result[str(key)] = dict(_mapping(value, "entity_types.%s" % key))
    return result


def _relations(raw: Any) -> Dict[str, Mapping[str, Any]]:
    result: Dict[str, Mapping[str, Any]] = {}
    for key, value in _mapping(raw, "ontology.relations").items():
        result[str(key)] = dict(_mapping(value, "relations.%s" % key))
    return result


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise DialogueError("нет файла диалоговых данных: %s" % path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        raise DialogueError("%s: %s" % (path, error)) from error


def load_ontology(path: Path) -> Ontology:
    raw = _mapping(_read_json(path), str(path))
    entity_types = _entity_types(raw.get("entity_types"))
    relations = _relations(raw.get("relations", {}))
    question_types = {
        str(key): dict(_mapping(value, "question_types.%s" % key))
        for key, value in _mapping(
            raw.get("question_types", {}), "ontology.question_types"
        ).items()
    }
    roles = {
        str(key): _text(value, "roles.%s" % key)
        for key, value in _mapping(
            raw.get("roles", {}), "ontology.roles"
        ).items()
    }
    if not entity_types:
        raise DialogueError("ontology.entity_types: пусто")
    return Ontology(
        entity_types=entity_types,
        relations=relations,
        question_types=question_types,
        roles=roles,
        raw=dict(raw),
    )


def load_lexicon(path: Path) -> Tuple[LexEntry, ...]:
    raw = _mapping(_read_json(path), str(path))
    entries: List[LexEntry] = []
    seen: Dict[str, str] = {}
    for index, item in enumerate(
        _sequence(raw.get("entries"), "lexicon.entries")
    ):
        where = "lexicon.entries[%d]" % index
        data = _mapping(item, where)
        entry_id = _text(data.get("id"), where + ".id")
        if entry_id in seen:
            raise DialogueError(
                "%s: повтор id %r (уже был в %s)"
                % (where, entry_id, seen[entry_id])
            )
        seen[entry_id] = where
        entry_type = _text(data.get("type"), where + ".type")
        cat = _text(data.get("cat") or entry_type, where + ".cat")
        lemma = _text(data.get("lemma") or entry_id, where + ".lemma")
        semantic = data.get("semantic")
        if semantic is None:
            semantic = {"kind": "entity", "type": entry_type, "id": entry_id}
        semantic = _mapping(semantic, where + ".semantic")
        entries.append(
            LexEntry(
                id=entry_id,
                type=entry_type,
                cat=cat,
                lemma=lemma,
                semantic=dict(semantic),
                forms=_parse_forms(data.get("forms"), where + ".forms"),
                aliases=_parse_forms(
                    data.get("aliases"), where + ".aliases"
                ),
                features=_features(
                    data.get("features"), where + ".features"
                ),
            )
        )
    if not entries:
        raise DialogueError("lexicon.entries: пусто")
    return tuple(entries)


def load_grammar(path: Path) -> Grammar:
    raw = _mapping(_read_json(path), str(path))
    start = _text(raw.get("start") or "S", "grammar.start")
    rules: List[GrammarRule] = []
    seen: Dict[str, str] = {}
    for index, item in enumerate(
        _sequence(raw.get("rules"), "grammar.rules")
    ):
        where = "grammar.rules[%d]" % index
        data = _mapping(item, where)
        rule_id = _text(data.get("id"), where + ".id")
        if rule_id in seen:
            raise DialogueError(
                "%s: повтор id %r (уже был в %s)"
                % (where, rule_id, seen[rule_id])
            )
        seen[rule_id] = where
        lhs = _text(data.get("lhs"), where + ".lhs")
        rhs: List[RuleItem] = []
        for rhs_index, rhs_item in enumerate(
            _sequence(data.get("rhs"), where + ".rhs")
        ):
            rhs_where = "%s.rhs[%d]" % (where, rhs_index)
            if isinstance(rhs_item, str):
                rhs.append(RuleItem(cat=_text(rhs_item, rhs_where)))
                continue
            rhs_data = _mapping(rhs_item, rhs_where)
            rhs.append(
                RuleItem(
                    cat=_text(rhs_data.get("cat"), rhs_where + ".cat"),
                    role=str(rhs_data.get("as") or ""),
                    features=_features(
                        rhs_data.get("features"), rhs_where + ".features"
                    ),
                )
            )
        if not rhs:
            raise DialogueError("%s.rhs: пусто" % where)
        rules.append(
            GrammarRule(
                id=rule_id,
                lhs=lhs,
                rhs=tuple(rhs),
                sem=data.get("sem", {}),
                features=_features(
                    data.get("features"), where + ".features"
                ),
                head=str(data.get("head") or ""),
            )
        )
    if not rules:
        raise DialogueError("grammar.rules: пусто")
    return Grammar(start=start, rules=tuple(rules))


def _atom(raw: Any, where: str) -> AtomSpec:
    data = _mapping(raw, where)
    rel = _text(data.get("rel"), where + ".rel")
    args = tuple(
        str(item)
        for item in _sequence(data.get("args", []), where + ".args")
    )
    return AtomSpec(rel=rel, args=args)


def load_rules(path: Path) -> Tuple[RuleSpec, ...]:
    raw = _mapping(_read_json(path), str(path))
    rules: List[RuleSpec] = []
    seen: Dict[str, str] = {}
    for index, item in enumerate(
        _sequence(raw.get("rules"), "rules.rules")
    ):
        where = "rules.rules[%d]" % index
        data = _mapping(item, where)
        rule_id = _text(data.get("id"), where + ".id")
        if rule_id in seen:
            raise DialogueError(
                "%s: повтор id %r (уже был в %s)"
                % (where, rule_id, seen[rule_id])
            )
        seen[rule_id] = where
        premises = tuple(
            _atom(premise, "%s.premises[%d]" % (where, premise_index))
            for premise_index, premise in enumerate(
                _sequence(data.get("premises"), where + ".premises")
            )
        )
        if not premises:
            raise DialogueError("%s.premises: пусто" % where)
        rules.append(
            RuleSpec(
                id=rule_id,
                head=_atom(data.get("head"), where + ".head"),
                premises=premises,
                because=str(data.get("because") or ""),
                priority=int(data.get("priority") or 0),
            )
        )
    if not rules:
        raise DialogueError("rules.rules: пусто")
    return tuple(rules)


def load_facts(path: Path) -> Tuple[FactSpec, ...]:
    raw = _mapping(_read_json(path), str(path))
    return tuple(
        _atom(item, "facts.facts[%d]" % index)
        for index, item in enumerate(
            _sequence(raw.get("facts"), "facts.facts")
        )
    )


def load_plans(path: Path) -> Tuple[PlanSpec, ...]:
    raw = _mapping(_read_json(path), str(path))
    plans: List[PlanSpec] = []
    seen: Dict[str, str] = {}
    for index, item in enumerate(
        _sequence(raw.get("plans"), "plans.plans")
    ):
        where = "plans.plans[%d]" % index
        data = _mapping(item, where)
        plan_id = _text(data.get("id"), where + ".id")
        if plan_id in seen:
            raise DialogueError(
                "%s: повтор id %r (уже был в %s)"
                % (where, plan_id, seen[plan_id])
            )
        seen[plan_id] = where
        answer = dict(_mapping(data.get("answer"), where + ".answer"))
        output = data.get("output", answer.get("output", []))
        plans.append(
            PlanSpec(
                id=plan_id,
                priority=int(data.get("priority") or 0),
                match=data.get("match", {}),
                answer=answer,
                output=tuple(
                    str(key)
                    for key in _sequence(output, where + ".output")
                ),
            )
        )
    if not plans:
        raise DialogueError("plans.plans: пусто")
    return tuple(plans)


def load_realization(path: Path) -> Mapping[str, Any]:
    return dict(_mapping(_read_json(path), str(path)))


def load_synthesis(path: Path) -> Mapping[str, Any]:
    raw = _mapping(_read_json(path), str(path))
    for key in (
        "constructions",
        "statements",
        "phrases",
        "collections",
        "entity_fields",
        "describe",
        "summary",
    ):
        value = raw.get(key)
        if value is None:
            continue
        _mapping(value, "synthesis.%s" % key)
    return dict(raw)


def load_state(path: Path) -> Mapping[str, Any]:
    raw = _mapping(_read_json(path), str(path))
    for key in (
        "pronouns",
        "entity_resolution",
        "referents",
        "qud",
        "question_intent",
        "fragments",
        "clarifications",
        "memory",
        "common_ground",
    ):
        value = raw.get(key)
        if value is None:
            continue
        if key == "fragments":
            _sequence(value, "state.fragments")
        else:
            _mapping(value, "state.%s" % key)
    return dict(raw)


def load_personas(path: Path) -> Dict[str, Persona]:
    raw = _mapping(_read_json(path), str(path))
    result: Dict[str, Persona] = {}
    for key, value in raw.items():
        if str(key) == "schema":
            continue
        where = "personas.%s" % key
        data = _mapping(value, where)
        result[str(key)] = Persona(
            id=str(data.get("id") or key),
            greeting=str(data.get("greeting") or ""),
            smalltalk={
                str(name): str(text)
                for name, text in _mapping(
                    data.get("smalltalk", {}), where + ".smalltalk"
                ).items()
            },
            unknown=str(data.get("unknown") or ""),
            parse_unknown=str(data.get("parse_unknown") or ""),
            clarify={
                str(name): str(text)
                for name, text in _mapping(
                    data.get("clarify", {}), where + ".clarify"
                ).items()
            },
            max_list_items=max(
                1, int(data.get("max_list_items") or 20)
            ),
            max_discourse_moves=max(
                1, int(data.get("max_discourse_moves") or 3)
            ),
            default_style=str(data.get("default_style") or ""),
        )
    if not result:
        raise DialogueError("personas: пусто")
    return result


def load_features(path: Path) -> FeatureSchema:
    raw = _mapping(_read_json(path), str(path))
    dimensions: Dict[str, Dict[str, Any]] = {}
    for name, value in _mapping(
        raw.get("dimensions"), "features.dimensions"
    ).items():
        where = "features.dimensions.%s" % name
        data = _mapping(value, where)
        values = [
            str(item)
            for item in _sequence(data.get("values"), where + ".values")
        ]
        if not values:
            raise DialogueError("%s.values: пусто" % where)
        default = str(data.get("default") or values[0])
        if default not in values:
            raise DialogueError(
                "%s.default: %r отсутствует в values" % (where, default)
            )
        dimensions[str(name)] = {
            "values": tuple(values),
            "default": default,
        }
    if not dimensions:
        raise DialogueError("features.dimensions: пусто")
    return FeatureSchema(dimensions=dimensions)


def load_styles(
    path: Path, schema: FeatureSchema | None = None
) -> StyleCatalog:
    raw = _mapping(_read_json(path), str(path))
    default = str(raw.get("default") or "neutral")
    items = _mapping(raw.get("styles"), "styles.styles")
    cached: Dict[str, StyleSpec] = {}

    def resolve(name: str, stack: Tuple[str, ...] = ()) -> StyleSpec:
        key = str(name)
        if key in cached:
            return cached[key]
        if key in stack:
            raise DialogueError(
                "styles.%s: цикл наследования %s"
                % (key, " -> ".join(stack + (key,)))
            )
        if key not in items:
            raise DialogueError("styles.%s: стиль отсутствует" % key)
        where = "styles.%s" % key
        data = _mapping(items[key], where)
        base_features = (
            dict(schema.defaults()) if schema is not None else {}
        )
        base_selection: Dict[str, Any] = {}
        base_register = "neutral"
        parent = str(data.get("extends") or "")
        if parent:
            if parent not in items:
                raise DialogueError(
                    "%s.extends: стиль %r отсутствует" % (where, parent)
                )
            base = resolve(parent, stack + (key,))
            base_features.update(base.features)
            base_selection.update(base.selection)
            base_register = base.register
        base_features.update(
            {
                str(name_item): str(value)
                for name_item, value in _mapping(
                    data.get("features", {}), where + ".features"
                ).items()
            }
        )
        base_selection.update(
            dict(
                _mapping(
                    data.get("selection", {}), where + ".selection"
                )
            )
        )
        style = StyleSpec(
            id=str(data.get("id") or key),
            label=str(data.get("label") or key),
            description=str(data.get("description") or ""),
            register=str(data.get("register") or base_register),
            features=base_features,
            selection=base_selection,
        )
        cached[key] = style
        return style

    styles = {str(key): resolve(str(key)) for key in items}
    if not styles:
        raise DialogueError("styles.styles: пусто")
    if default not in styles:
        raise DialogueError(
            "styles.default: стиль %r отсутствует" % default
        )
    return StyleCatalog(default=default, styles=styles)


def _context_condition(raw: Any, where: str) -> Mapping[str, Any]:
    data = _mapping(raw, where)
    kind = str(data.get("kind") or "field")
    if kind == "fact":
        rel = _text(data.get("rel"), where + ".rel")
        args = tuple(
            str(item)
            for item in _sequence(data.get("args", []), where + ".args")
        )
        return {"kind": "fact", "rel": rel, "args": args}
    if kind == "field":
        field_name = _text(data.get("field"), where + ".field")
        operator = str(data.get("op") or "eq")
        if operator not in CONTEXT_OPERATORS:
            raise DialogueError(
                "%s.op: неизвестный оператор %r" % (where, operator)
            )
        value = data.get("value")
        if isinstance(value, Mapping):
            value = {
                str(key): str(item)
                for key, item in value.items()
            }
        elif isinstance(value, (list, tuple)):
            value = [str(item) for item in value]
        elif value is not None:
            value = str(value)
        return {
            "kind": "field",
            "field": field_name,
            "op": operator,
            "value": value,
        }
    raise DialogueError("%s.kind: неизвестный вид условия" % where)


def load_style_context(
    path: Path, styles: StyleCatalog
) -> StyleContextCatalog:
    if not path.is_file():
        return StyleContextCatalog()
    raw = _mapping(_read_json(path), str(path))
    enabled = bool(raw.get("enabled", True))
    items = _sequence(raw.get("rules", []), "style_context.rules")
    rules: List[StyleContextRule] = []
    seen: Dict[str, str] = {}
    for index, item in enumerate(items):
        where = "style_context.rules[%d]" % index
        data = _mapping(item, where)
        rule_id = _text(data.get("id"), where + ".id")
        if rule_id in seen:
            raise DialogueError(
                "%s: повтор id %r (уже был в %s)"
                % (where, rule_id, seen[rule_id])
            )
        seen[rule_id] = where
        style_id = _text(data.get("style"), where + ".style")
        if style_id not in styles.styles:
            raise DialogueError(
                "%s.style: стиль %r отсутствует в styles.styles"
                % (where, style_id)
            )
        conditions: List[Mapping[str, Any]] = []
        for cond_index, cond in enumerate(
            _sequence(data.get("when", []), where + ".when")
        ):
            conditions.append(
                _context_condition(
                    cond, "%s.when[%d]" % (where, cond_index)
                )
            )
        if not conditions:
            raise DialogueError("%s.when: пусто" % where)
        rules.append(
            StyleContextRule(
                id=rule_id,
                style_id=style_id,
                priority=int(data.get("priority") or 0),
                conditions=tuple(conditions),
                description=str(data.get("description") or ""),
            )
        )
    return StyleContextCatalog(rules=tuple(rules), enabled=enabled)


def _social_atoms(value: Any, where: str) -> Tuple[AtomSpec, ...]:
    if value is None:
        return ()
    result: List[AtomSpec] = []
    for index, item in enumerate(_sequence(value, where)):
        result.append(_atom(item, "%s[%d]" % (where, index)))
    return tuple(result)


def load_social(path: Path) -> SocialCatalog:
    raw = _mapping(_read_json(path), str(path))
    acts_raw = _mapping(raw.get("acts", {}), "social.acts")
    reactions_raw = _mapping(
        raw.get("reactions", {}), "social.reactions"
    )
    acts: Dict[str, SocialActSpec] = {}
    for key, value in acts_raw.items():
        where = "social.acts.%s" % key
        data = _mapping(value, where)
        act_id = str(data.get("id") or key)
        match = dict(_mapping(data.get("match", {}), where + ".match"))
        proposition = dict(
            _mapping(data.get("proposition", {}), where + ".proposition")
        )
        reactions = tuple(
            str(item)
            for item in _sequence(
                data.get("reactions", []), where + ".reactions"
            )
        )
        taboo = tuple(
            str(item)
            for item in _sequence(
                data.get("taboo", []), where + ".taboo"
            )
        )
        acts[str(key)] = SocialActSpec(
            id=act_id,
            label=str(data.get("label") or act_id),
            match=match,
            proposition=proposition,
            validity=_social_atoms(
                data.get("validity"), where + ".validity"
            ),
            taboo=taboo,
            reactions=reactions,
        )
    reactions: Dict[str, ReactionSpec] = {}
    for key, value in reactions_raw.items():
        where = "social.reactions.%s" % key
        data = _mapping(value, where)
        reaction_id = str(data.get("id") or key)
        effect = dict(_mapping(data.get("effect", {}), where + ".effect"))
        kind = str(effect.get("type") or "")
        if kind and kind not in EFFECT_TYPES:
            raise DialogueError(
                "%s.effect.type: неизвестный %r" % (where, kind)
            )
        reactions[str(key)] = ReactionSpec(
            id=reaction_id,
            label=str(data.get("label") or reaction_id),
            effect=effect,
            conditions=_social_atoms(
                data.get("conditions"), where + ".conditions"
            ),
            priority=int(data.get("priority") or 0),
            construction=str(data.get("construction") or ""),
        )
    commitments = dict(
        _mapping(raw.get("commitments", {}), "social.commitments")
    )
    return SocialCatalog(
        acts=acts,
        reactions=reactions,
        commitments=commitments,
    )


def _discourse_move(key: str, value: Any) -> DiscourseMove:
    where = "discourse.moves.%s" % key
    data = _mapping(value, where)
    move_id = str(data.get("id") or key)
    act = str(data.get("act") or "")
    construction = str(data.get("construction") or "")
    relation = str(data.get("relation") or "")
    source = str(data.get("source") or "")
    modes = sum(1 for item in (act, construction, relation) if item)
    if modes == 0 and not source:
        raise DialogueError(
            "%s: нужен act, construction, relation или source" % where
        )
    if modes > 1:
        raise DialogueError(
            "%s: одновременно act/construction/relation запрещены"
            % where
        )
    if relation and not source:
        raise DialogueError(
            "%s: relation без source (имя поля данных)" % where
        )
    return DiscourseMove(
        id=move_id,
        label=str(data.get("label") or move_id),
        act=act,
        construction=construction,
        relation=relation,
        source=source,
        optional=bool(data.get("optional", False)),
        features=_features(
            data.get("features"), where + ".features"
        ),
        priority=int(data.get("priority") or 0),
    )


def _discourse_pattern(key: str, value: Any) -> DiscoursePattern:
    where = "discourse.patterns.%s" % key
    data = _mapping(value, where)
    pattern_id = str(data.get("id") or key)
    kind = str(data.get("kind") or "")
    plan_id = str(data.get("plan_id") or "")
    if not kind and not plan_id:
        raise DialogueError(
            "%s: нужен kind или plan_id" % where
        )
    moves = tuple(
        str(item)
        for item in _sequence(data.get("moves"), where + ".moves")
    )
    if not moves:
        raise DialogueError("%s.moves: пусто" % where)
    topic = str(data.get("topic") or "")
    if topic and topic not in moves:
        raise DialogueError(
            "%s.topic: %r отсутствует в moves" % (where, topic)
        )
    return DiscoursePattern(
        id=pattern_id,
        kind=kind,
        plan_id=plan_id,
        moves=moves,
        topic=topic,
        priority=int(data.get("priority") or 0),
    )


def _discourse_connective(key: str, value: Any) -> Mapping[str, Any]:
    where = "discourse.connectives.%s" % key
    data = _mapping(value, where)
    text = str(data.get("text") or "")
    if not text.strip():
        raise DialogueError("%s.text: пусто" % where)
    item = dict(data)
    item["id"] = str(data.get("id") or key)
    item["text"] = text
    item["features"] = _features(
        data.get("features"), where + ".features"
    )
    mode = str(data.get("mode") or "plain")
    if mode not in CONNECTIVE_MODES:
        raise DialogueError(
            "%s.mode: неизвестный режим %r" % (where, mode)
        )
    item["mode"] = mode
    try:
        item["priority"] = int(data.get("priority") or 0)
    except (TypeError, ValueError) as error:
        raise DialogueError(
            "%s.priority: ожидалось число" % where
        ) from error
    return item


def _discourse_anaphora(raw: Any) -> DiscourseAnaphora:
    if raw is None:
        return DiscourseAnaphora()
    data = _mapping(raw, "discourse.anaphora")
    enabled = bool(data.get("enabled", False))
    types = tuple(
        str(item)
        for item in _sequence(
            data.get("types", []), "discourse.anaphora.types"
        )
    )
    kinds = tuple(
        str(item)
        for item in _sequence(
            data.get("kinds", []), "discourse.anaphora.kinds"
        )
    )
    pronouns = {
        str(name): str(value)
        for name, value in _mapping(
            data.get("pronouns", {}), "discourse.anaphora.pronouns"
        ).items()
    }
    try:
        min_length = int(data.get("min_length") or 3)
    except (TypeError, ValueError) as error:
        raise DialogueError(
            "discourse.anaphora.min_length: ожидалось число"
        ) from error
    return DiscourseAnaphora(
        types=types,
        kinds=kinds,
        pronouns=pronouns,
        min_length=max(1, min_length),
        enabled=enabled,
    )


def load_discourse(path: Path) -> DiscourseCatalog:
    if not path.is_file():
        return DiscourseCatalog()
    raw = _mapping(_read_json(path), str(path))
    moves_raw = _mapping(raw.get("moves", {}), "discourse.moves")
    patterns_raw = _mapping(
        raw.get("patterns", {}), "discourse.patterns"
    )
    connectives_raw = _mapping(
        raw.get("connectives", {}), "discourse.connectives"
    )
    moves: Dict[str, DiscourseMove] = {}
    for key, value in moves_raw.items():
        move = _discourse_move(str(key), value)
        if str(key) in moves:
            raise DialogueError(
                "discourse.moves.%s: повтор id" % key
            )
        moves[str(key)] = move
    patterns: List[DiscoursePattern] = []
    for key, value in patterns_raw.items():
        patterns.append(_discourse_pattern(str(key), value))
    connectives: List[Mapping[str, Any]] = []
    for key, value in connectives_raw.items():
        connectives.append(_discourse_connective(str(key), value))
    anaphora = _discourse_anaphora(raw.get("anaphora"))
    return DiscourseCatalog(
        moves=moves,
        patterns=tuple(patterns),
        connectives=tuple(connectives),
        anaphora=anaphora,
    )


def load_comparison(path: Path) -> ComparisonCatalog:
    if not path.is_file():
        return ComparisonCatalog()
    raw = _mapping(_read_json(path), str(path))
    items = _mapping(raw.get("comparisons", {}), "comparison.comparisons")
    comparisons: Dict[str, ComparisonSpec] = {}
    for key, value in items.items():
        where = "comparison.comparisons.%s" % key
        data = _mapping(value, where)
        relation = _text(data.get("relation"), where + ".relation")
        args = dict(_mapping(data.get("args", {}), where + ".args"))
        try:
            value_arg = int(data.get("value_arg") or 2)
            key_arg = int(data.get("key_arg") or 1)
            subject_arg = int(data.get("subject_arg") or 0)
        except (TypeError, ValueError) as error:
            raise DialogueError(
                "%s: числовые поля должны быть целыми" % where
            ) from error
        comparisons[str(key)] = ComparisonSpec(
            id=str(key),
            relation=relation,
            args={
                str(name): int(index)
                for name, index in args.items()
            },
            value_arg=value_arg,
            key_arg=key_arg,
            subject_arg=subject_arg,
            key_prefix=str(data.get("key_prefix") or ""),
            greater=str(data.get("greater") or ""),
            less=str(data.get("less") or ""),
            equal=str(data.get("equal") or ""),
            unknown_left=str(data.get("unknown_left") or ""),
            unknown_right=str(data.get("unknown_right") or ""),
            both_unknown=str(data.get("both_unknown") or ""),
        )
    return ComparisonCatalog(comparisons=comparisons)


def load_world(path: Path) -> Mapping[str, Any]:
    return dict(_mapping(_read_json(path), str(path)))


def load_dialogue(directory: Path | str | None = None) -> DialogueCatalog:
    root = Path(directory) if directory is not None else DEFAULT_DIR
    ontology = load_ontology(root / "ontology.json")
    lexicon = load_lexicon(root / "lexicon.json")
    grammar = load_grammar(root / "grammar.json")
    rules_raw = _mapping(
        _read_json(root / "rules.json"), str(root / "rules.json")
    )
    max_depth = max(1, int(rules_raw.get("max_depth") or 32))
    rules = load_rules(root / "rules.json")
    facts = load_facts(root / "facts.json")
    plans = load_plans(root / "plans.json")
    realization = load_realization(root / "realization.json")
    synthesis = load_synthesis(root / "synthesis.json")
    state = load_state(root / "state.json")
    personas = load_personas(root / "personas.json")
    feature_schema = load_features(root / "features.json")
    styles = load_styles(root / "styles.json", feature_schema)
    social = load_social(root / "social.json")
    discourse = load_discourse(root / "discourse.json")
    style_context = load_style_context(
        root / "style_context.json", styles
    )
    comparison = load_comparison(root / "comparison.json")
    world = load_world(root / "world.json")
    raw = {
        "directory": str(root),
        "ontology": ontology.raw,
        "lexicon": {"count": len(lexicon)},
        "grammar": {
            "start": grammar.start,
            "rules": len(grammar.rules),
        },
        "rules": {"count": len(rules)},
        "facts": {"count": len(facts)},
        "plans": {"count": len(plans)},
        "synthesis": {
            "constructions": len(synthesis.get("constructions") or {}),
            "statements": len(synthesis.get("statements") or {}),
            "phrases": len(synthesis.get("phrases") or {}),
        },
        "state": {
            "pronouns": len(state.get("pronouns") or {}),
            "fragments": len(state.get("fragments") or ()),
        },
        "personas": {"count": len(personas)},
        "features": {"count": len(feature_schema.dimensions)},
        "styles": {
            "default": styles.default,
            "count": len(styles.styles),
        },
        "social": {
            "acts": len(social.acts),
            "reactions": len(social.reactions),
        },
        "discourse": {
            "moves": len(discourse.moves),
            "patterns": len(discourse.patterns),
            "connectives": len(discourse.connectives),
            "anaphora": bool(discourse.anaphora.enabled),
        },
        "style_context": {
            "enabled": style_context.enabled,
            "rules": len(style_context.rules),
        },
        "comparison": {
            "comparisons": len(comparison.comparisons),
        },
    }
    return DialogueCatalog(
        ontology=ontology,
        lexicon=lexicon,
        grammar=grammar,
        rules=rules,
        facts=facts,
        max_depth=max_depth,
        plans=plans,
        realization=realization,
        synthesis=synthesis,
        state=state,
        personas=personas,
        styles=styles,
        features=feature_schema,
        social=social,
        discourse=discourse,
        style_context=style_context,
        comparison=comparison,
        world=world,
        raw=raw,
    )