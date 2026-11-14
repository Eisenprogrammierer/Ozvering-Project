"""Загрузка диалоговых данных из JSON.

Весь содержательный контент диалога — онтология, лексикон, грамматика,
правила, факты, планы, синтез, стили, дискурс, социальный слой,
сравнения и контрфакты — читается из ``configs/dialogue``. Python здесь
только разбирает структуру и проверяет обязательные поля.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .errors import DialogueError
from .model import (
    AtomSpec,
    ComparisonCatalog,
    ComparisonSpec,
    CounterfactualSpec,
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

CONTEXT_OPERATORS = frozenset({"eq", "ne", "in", "not_in", "exists"})
EFFECT_TYPES = frozenset(
    {
        "commitment",
        "refusal",
        "evasion",
        "counter_offer",
        "clarification",
    }
)

_CASES = ("nom", "gen", "dat", "acc", "ins", "prep")
_NUMBERS = ("sg", "pl")


# --- низкоуровневые помощники -----------------------------------------


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise DialogueError("файл не найден: %s" % path)
    except json.JSONDecodeError as error:
        raise DialogueError(
            "некорректный JSON в %s: %s" % (path, error)
        )
    if not isinstance(data, Mapping):
        raise DialogueError(
            "ожидался объект в корне %s, получено %s"
            % (path, type(data).__name__)
        )
    return data


def _require_schema(raw: Mapping[str, Any], path: Path) -> None:
    """Проверить, что в файле объявлена схема (если поле есть)."""

    if "schema" not in raw:
        return
    schema = raw.get("schema")
    if not isinstance(schema, int) or schema < 1:
        raise DialogueError(
            "%s: schema должна быть целым >= 1, получено %r"
            % (path, schema)
        )


def _text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_forms(value: Any) -> Tuple[LexForm, ...]:
    forms: List[LexForm] = []
    if isinstance(value, Mapping):
        for key, items in value.items():
            features = _features_from_key(str(key))
            for text in _list(items):
                if _text(text):
                    forms.append(LexForm(str(text), dict(features)))
        return tuple(forms)
    for item in _list(value):
        if isinstance(item, Mapping):
            text = _text(item.get("text"))
            if text:
                forms.append(
                    LexForm(text, dict(_mapping(item.get("features"))))
                )
        else:
            text = _text(item)
            if text:
                forms.append(LexForm(text))
    return tuple(forms)


def _features_from_key(key: str) -> Dict[str, str]:
    """Разобрать ключ формы ``номен``/``номер`` в признаки.

    ``"nom"``        → ``{"case": "nom", "number": "sg"}``
    ``"nom_pl"``     → ``{"case": "nom", "number": "pl"}``
    ``"nom_pl_..."`` → то же (хвост игнорируется)
    Пустой ключ      → пусто.
    """

    features: Dict[str, str] = {}
    if not key:
        return features
    parts = key.split("_")
    if not parts:
        return features
    case = parts[0]
    if case not in _CASES:
        return features
    features["case"] = case
    features["number"] = "sg"
    if len(parts) >= 2 and parts[1] in _NUMBERS:
        features["number"] = parts[1]
    return features


# --- онтология и лексикон ---------------------------------------------


def load_ontology(root: Path) -> Ontology:
    path = root / "ontology.json"
    raw = _read_json(path) if path.exists() else {}
    _require_schema(raw, path)
    return Ontology(
        entity_types=_mapping(raw.get("entity_types")),
        relations=_mapping(raw.get("relations")),
        question_types=_mapping(raw.get("question_types")),
        roles=_mapping(raw.get("roles")),
        raw=raw,
    )


def load_lexicon(root: Path) -> Tuple[LexEntry, ...]:
    path = root / "lexicon.json"
    raw = _read_json(path)
    _require_schema(raw, path)
    entries: List[LexEntry] = []
    for item in _list(raw.get("entries")):
        if not isinstance(item, Mapping):
            raise DialogueError(
                "%s: entry должен быть объектом" % path
            )
        entry_id = _text(item.get("id"))
        if not entry_id:
            raise DialogueError("%s: у лексемы нет id" % path)
        entries.append(
            LexEntry(
                id=entry_id,
                type=_text(item.get("type"), "concept"),
                cat=_text(item.get("cat"), "N"),
                lemma=_text(item.get("lemma"), entry_id),
                semantic=_mapping(item.get("semantic")),
                forms=_load_forms(item.get("forms")),
                aliases=_load_forms(item.get("aliases")),
                features=_mapping(item.get("features")),
            )
        )
    return tuple(entries)


# --- грамматика -------------------------------------------------------


def _load_rhs(value: Any) -> Tuple[RuleItem, ...]:
    items: List[RuleItem] = []
    for item in _list(value):
        if not isinstance(item, Mapping):
            continue
        cat = _text(item.get("cat"))
        if not cat:
            continue
        items.append(
            RuleItem(
                cat=cat,
                role=_text(item.get("as")),
                features=_mapping(item.get("features")),
            )
        )
    return tuple(items)


def load_grammar(root: Path) -> Grammar:
    path = root / "grammar.json"
    raw = _read_json(path)
    _require_schema(raw, path)
    start = _text(raw.get("start"))
    if not start:
        raise DialogueError("%s: пустой start" % path)
    rules: List[GrammarRule] = []
    for item in _list(raw.get("rules")):
        if not isinstance(item, Mapping):
            continue
        rule_id = _text(item.get("id"))
        lhs = _text(item.get("lhs"))
        if not rule_id or not lhs:
            raise DialogueError(
                "%s: у правила нет id или lhs" % path
            )
        rules.append(
            GrammarRule(
                id=rule_id,
                lhs=lhs,
                rhs=_load_rhs(item.get("rhs")),
                sem=item.get("sem"),
                features=_mapping(item.get("features")),
                head=_text(item.get("head")),
            )
        )
    return Grammar(start=start, rules=tuple(rules))


# --- факты и правила --------------------------------------------------


def _atom(value: Any) -> AtomSpec:
    data = _mapping(value)
    rel = _text(data.get("rel"))
    args = tuple(str(arg) for arg in _list(data.get("args")))
    return AtomSpec(rel, args)


def load_rules(root: Path) -> Tuple[RuleSpec, ...]:
    path = root / "rules.json"
    if not path.exists():
        return ()
    raw = _read_json(path)
    _require_schema(raw, path)
    rules: List[RuleSpec] = []
    for item in _list(raw.get("rules")):
        data = _mapping(item)
        rule_id = _text(data.get("id"))
        head = _atom(data.get("head"))
        if not rule_id or not head.rel:
            continue
        premises = tuple(
            _atom(premise) for premise in _list(data.get("premises"))
        )
        try:
            priority = int(data.get("priority") or 0)
        except (TypeError, ValueError):
            priority = 0
        rules.append(
            RuleSpec(
                id=rule_id,
                head=head,
                premises=premises,
                because=_text(data.get("because")),
                priority=priority,
            )
        )
    return tuple(rules)


def load_facts(root: Path) -> Tuple[FactSpec, ...]:
    path = root / "facts.json"
    if not path.exists():
        return ()
    raw = _read_json(path)
    _require_schema(raw, path)
    facts: List[FactSpec] = []
    for item in _list(raw.get("facts")):
        data = _mapping(item)
        rel = _text(data.get("rel"))
        if not rel:
            continue
        args = tuple(str(arg) for arg in _list(data.get("args")))
        facts.append(FactSpec(rel, args))
    return tuple(facts)


# --- планы ------------------------------------------------------------


def load_plans(root: Path) -> Tuple[PlanSpec, ...]:
    path = root / "plans.json"
    if not path.exists():
        return ()
    raw = _read_json(path)
    _require_schema(raw, path)
    plans: List[PlanSpec] = []
    for item in _list(raw.get("plans")):
        data = _mapping(item)
        plan_id = _text(data.get("id"))
        if not plan_id:
            continue
        try:
            priority = int(data.get("priority") or 0)
        except (TypeError, ValueError):
            priority = 0
        answer = _mapping(data.get("answer"))
        raw_output = data.get("output")
        if raw_output is None:
            raw_output = answer.get("output")
        output = tuple(str(name) for name in _list(raw_output))
        plans.append(
            PlanSpec(
                id=plan_id,
                priority=priority,
                match=data.get("match"),
                answer=answer,
                output=output,
            )
        )
    return tuple(plans)


# --- realization / synthesis -----------------------------------------


def load_realization(root: Path) -> Mapping[str, Any]:
    path = root / "realization.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    return raw


def load_synthesis(root: Path) -> Mapping[str, Any]:
    path = root / "synthesis.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    return raw


def load_state(root: Path) -> Mapping[str, Any]:
    path = root / "state.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    return raw


# --- персонажи --------------------------------------------------------


def _persona_from(data: Mapping[str, Any], key: str) -> Persona:
    return Persona(
        id=_text(data.get("id"), str(key)),
        greeting=_text(data.get("greeting")),
        smalltalk={
            str(name): str(text)
            for name, text in _mapping(data.get("smalltalk")).items()
        },
        unknown=_text(data.get("unknown")),
        parse_unknown=_text(data.get("parse_unknown")),
        clarify={
            str(name): str(text)
            for name, text in _mapping(data.get("clarify")).items()
        },
        max_list_items=_int(data.get("max_list_items"), 20),
        max_discourse_moves=_int(
            data.get("max_discourse_moves"), 3
        ),
        default_style=_text(data.get("default_style")),
        disclosure=_mapping(data.get("disclosure")),
        lie_probability=_float(data.get("lie_probability"), 0.0),
    )


def load_personas(root: Path) -> Mapping[str, Persona]:
    path = root / "personas.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    block = raw.get("personas")
    source = block if isinstance(block, Mapping) else raw
    personas: Dict[str, Persona] = {}
    for key, item in source.items():
        if str(key) in ("schema",):
            continue
        if not isinstance(item, Mapping):
            continue
        personas[str(key)] = _persona_from(item, str(key))
    return personas


# --- стили ------------------------------------------------------------


def load_features(root: Path) -> FeatureSchema:
    path = root / "features.json"
    if not path.exists():
        return FeatureSchema()
    raw = _read_json(path)
    _require_schema(raw, path)
    return FeatureSchema(dimensions=_mapping(raw.get("dimensions")))


def load_styles(root: Path) -> StyleCatalog:
    path = root / "styles.json"
    if not path.exists():
        return StyleCatalog()
    raw = _read_json(path)
    _require_schema(raw, path)
    styles: Dict[str, StyleSpec] = {}
    for key, item in _mapping(raw.get("styles")).items():
        data = _mapping(item)
        styles[str(key)] = StyleSpec(
            id=_text(data.get("id"), str(key)),
            label=_text(data.get("label"), str(key)),
            description=_text(data.get("description")),
            register=_text(data.get("register"), "neutral"),
            features={
                str(name): str(value)
                for name, value in _mapping(
                    data.get("features")
                ).items()
            },
            selection=_mapping(data.get("selection")),
        )
    return StyleCatalog(
        default=_text(raw.get("default"), "neutral"),
        styles=styles,
    )


def load_style_context(root: Path) -> StyleContextCatalog:
    path = root / "style_context.json"
    if not path.exists():
        return StyleContextCatalog()
    raw = _read_json(path)
    _require_schema(raw, path)
    rules: List[StyleContextRule] = []
    for item in _list(raw.get("rules")):
        data = _mapping(item)
        rule_id = _text(data.get("id"))
        if not rule_id:
            continue
        try:
            priority = int(data.get("priority") or 0)
        except (TypeError, ValueError):
            priority = 0
        rules.append(
            StyleContextRule(
                id=rule_id,
                style_id=_text(data.get("style")),
                priority=priority,
                conditions=tuple(
                    _mapping(cond)
                    for cond in _list(data.get("when"))
                ),
                description=_text(data.get("description")),
            )
        )
    return StyleContextCatalog(
        rules=tuple(rules),
        enabled=bool(raw.get("enabled", True)),
    )


# --- дискурс ----------------------------------------------------------


def _load_pattern(key: str, value: Mapping[str, Any]) -> DiscoursePattern:
    data = dict(_mapping(value))
    if not data.get("id"):
        data["id"] = str(key)
    return DiscoursePattern(
        id=_text(data.get("id"), str(key)),
        kind=_text(data.get("kind")),
        plan_id=_text(data.get("plan_id")),
        moves=tuple(
            str(name) for name in _list(data.get("moves"))
        ),
        topic=_text(data.get("topic")),
        topics=tuple(
            str(name) for name in _list(data.get("topics"))
        ),
        priority=_int(data.get("priority"), 0),
    )


def _load_connective(key: str, value: Mapping[str, Any]) -> Dict[str, Any]:
    data = dict(_mapping(value))
    if not data.get("id"):
        data["id"] = str(key)
    return data


def _load_patterns(raw: Any) -> Tuple[DiscoursePattern, ...]:
    patterns: List[DiscoursePattern] = []
    if isinstance(raw, Mapping):
        for key, item in raw.items():
            if not isinstance(item, Mapping):
                continue
            patterns.append(_load_pattern(str(key), item))
        return tuple(patterns)
    for item in _list(raw):
        data = _mapping(item)
        if not data:
            continue
        identifier = _text(data.get("id"))
        if not identifier:
            continue
        patterns.append(_load_pattern(identifier, data))
    return tuple(patterns)


def _load_connectives(raw: Any) -> Tuple[Mapping[str, Any], ...]:
    result: List[Mapping[str, Any]] = []
    if isinstance(raw, Mapping):
        for key, item in raw.items():
            if not isinstance(item, Mapping):
                continue
            result.append(_load_connective(str(key), item))
        return tuple(result)
    for item in _list(raw):
        data = _mapping(item)
        if not data:
            continue
        identifier = _text(data.get("id"))
        if not identifier:
            continue
        result.append(data)
    return tuple(result)


def load_discourse(root: Path) -> DiscourseCatalog:
    path = root / "discourse.json"
    if not path.exists():
        return DiscourseCatalog()
    raw = _read_json(path)
    _require_schema(raw, path)
    moves: Dict[str, DiscourseMove] = {}
    for key, item in _mapping(raw.get("moves")).items():
        data = _mapping(item)
        moves[str(key)] = DiscourseMove(
            id=_text(data.get("id"), str(key)),
            label=_text(data.get("label")),
            act=_text(data.get("act")),
            construction=_text(data.get("construction")),
            relation=_text(data.get("relation")),
            source=_text(data.get("source")),
            optional=bool(data.get("optional", False)),
            features=_mapping(data.get("features")),
            priority=_int(data.get("priority"), 0),
        )
    patterns = _load_patterns(raw.get("patterns"))
    connectives = _load_connectives(raw.get("connectives"))
    anaphora_raw = _mapping(raw.get("anaphora"))
    anaphora = DiscourseAnaphora(
        types=tuple(
            str(name) for name in _list(anaphora_raw.get("types"))
        ),
        kinds=tuple(
            str(name) for name in _list(anaphora_raw.get("kinds"))
        ),
        pronouns={
            str(key): str(value)
            for key, value in _mapping(
                anaphora_raw.get("pronouns")
            ).items()
        },
        min_length=_int(anaphora_raw.get("min_length"), 3),
        enabled=bool(anaphora_raw.get("enabled", False)),
    )
    return DiscourseCatalog(
        moves=moves,
        patterns=patterns,
        connectives=connectives,
        anaphora=anaphora,
    )


# --- социальный слой --------------------------------------------------


def load_social(root: Path) -> SocialCatalog:
    path = root / "social.json"
    if not path.exists():
        return SocialCatalog()
    raw = _read_json(path)
    _require_schema(raw, path)
    acts: Dict[str, SocialActSpec] = {}
    for key, item in _mapping(raw.get("acts")).items():
        data = _mapping(item)
        acts[str(key)] = SocialActSpec(
            id=_text(data.get("id"), str(key)),
            label=_text(data.get("label"), str(key)),
            match=_mapping(data.get("match")),
            proposition=_mapping(data.get("proposition")),
            interaction=_text(data.get("interaction")),
            validity=tuple(
                _atom(atom) for atom in _list(data.get("validity"))
            ),
            taboo=tuple(
                str(name) for name in _list(data.get("taboo"))
            ),
            reactions=tuple(
                str(name) for name in _list(data.get("reactions"))
            ),
        )
    reactions: Dict[str, ReactionSpec] = {}
    for key, item in _mapping(raw.get("reactions")).items():
        data = _mapping(item)
        reactions[str(key)] = ReactionSpec(
            id=_text(data.get("id"), str(key)),
            label=_text(data.get("label"), str(key)),
            effect=_mapping(data.get("effect")),
            conditions=tuple(
                _atom(atom)
                for atom in _list(data.get("conditions"))
            ),
            priority=_int(data.get("priority"), 0),
            construction=_text(data.get("construction")),
        )
    return SocialCatalog(
        acts=acts,
        reactions=reactions,
        commitments=_mapping(raw.get("commitments")),
    )


# --- сравнения --------------------------------------------------------


def load_comparison(root: Path) -> ComparisonCatalog:
    path = root / "comparison.json"
    if not path.exists():
        return ComparisonCatalog()
    raw = _read_json(path)
    _require_schema(raw, path)
    comparisons: Dict[str, ComparisonSpec] = {}
    for key, item in _mapping(raw.get("comparisons")).items():
        data = _mapping(item)
        comparisons[str(key)] = ComparisonSpec(
            id=_text(data.get("id"), str(key)),
            relation=_text(data.get("relation"), str(key)),
            args={
                str(name): _int(position, 0)
                for name, position in _mapping(
                    data.get("args")
                ).items()
            },
            value_arg=_int(data.get("value_arg"), 2),
            key_arg=_int(data.get("key_arg"), 1),
            subject_arg=_int(data.get("subject_arg"), 0),
            key_prefix=_text(data.get("key_prefix")),
            greater=_text(data.get("greater")),
            less=_text(data.get("less")),
            equal=_text(data.get("equal")),
            unknown_left=_text(data.get("unknown_left")),
            unknown_right=_text(data.get("unknown_right")),
            both_unknown=_text(data.get("both_unknown")),
        )
    return ComparisonCatalog(comparisons=comparisons)


# --- контрфакты ------------------------------------------------------


def load_counterfactual(root: Path) -> CounterfactualSpec:
    """Загрузить правила контрфакта из ``counterfactual.json``."""

    path = root / "counterfactual.json"
    if not path.exists():
        return CounterfactualSpec()
    raw = _read_json(path)
    _require_schema(raw, path)
    relations = tuple(
        str(item) for item in _list(raw.get("relations"))
    )
    max_steps = _int(raw.get("max_steps"), 2)
    outcomes = {
        str(key): str(value)
        for key, value in _mapping(raw.get("outcomes")).items()
        if str(value)
    }
    return CounterfactualSpec(
        relations=relations,
        max_steps=max(1, max_steps),
        outcomes=outcomes,
    )


# --- мир --------------------------------------------------------------


def load_disclosure(root: Path) -> Mapping[str, Any]:
    """Загрузить политики раскрытия из ``disclosure.json``."""

    path = root / "disclosure.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    return raw


def load_parsing(root: Path) -> Mapping[str, Any]:
    """Загрузить детерминированный beam-профиль из ``parsing.json``."""

    path = root / "parsing.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    return raw


def load_paraphrases(root: Path) -> Mapping[str, Any]:
    """Загрузить корпус парафраз из ``paraphrases.json``."""

    path = root / "paraphrases.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    return raw


def load_goals(root: Path) -> Mapping[str, Any]:
    """Загрузить цели разговора и действий из ``goals.json``."""

    path = root / "goals.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    return raw


def load_actions(root: Path) -> Mapping[str, Any]:
    """Загрузить псевдонимы действий из ``actions.json``."""

    path = root / "actions.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    return raw


def load_console(root: Path) -> Mapping[str, Any]:
    """Загрузить настройки текстового интерфейса из ``console.json``."""

    path = root / "console.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    return raw


def load_world(root: Path) -> Mapping[str, Any]:
    path = root / "world.json"
    if not path.exists():
        return {}
    raw = _read_json(path)
    _require_schema(raw, path)
    return raw


# --- главный загрузчик ------------------------------------------------


def load_dialogue(directory: Optional[Path | str] = None) -> DialogueCatalog:
    root = Path(directory) if directory is not None else DEFAULT_DIR
    if not root.exists():
        raise DialogueError("каталог диалога не найден: %s" % root)
    ontology = load_ontology(root)
    lexicon = load_lexicon(root)
    grammar = load_grammar(root)
    rules = load_rules(root)
    facts = load_facts(root)
    realization = load_realization(root)
    synthesis = load_synthesis(root)
    state = load_state(root)
    personas = load_personas(root)
    styles = load_styles(root)
    features = load_features(root)
    social = load_social(root)
    discourse = load_discourse(root)
    style_context = load_style_context(root)
    comparison = load_comparison(root)
    counterfactual = load_counterfactual(root)
    disclosure = load_disclosure(root)
    parsing = load_parsing(root)
    paraphrases = load_paraphrases(root)
    goals = load_goals(root)
    actions = load_actions(root)
    console = load_console(root)
    world = load_world(root)
    plans = load_plans(root)
    max_depth = _int(
        (ontology.raw or {}).get("max_depth"),
        32,
    )
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
        features=features,
        social=social,
        discourse=discourse,
        style_context=style_context,
        comparison=comparison,
        counterfactual=counterfactual,
        disclosure=disclosure,
        parsing=parsing,
        paraphrases=paraphrases,
        goals=goals,
        actions=actions,
        console=console,
        world=world,
        raw={
            "ontology": ontology.raw,
            "realization": realization,
            "synthesis": synthesis,
            "state": state,
            "disclosure": disclosure,
            "parsing": parsing,
            "paraphrases": paraphrases,
            "goals": goals,
            "actions": actions,
            "console": console,
        },
    )
