"""Проверка диалоговых JSON: ссылки, категории, роли, покрытие."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set

from .errors import DialogueError
from .loader import DEFAULT_DIR, load_dialogue
from .model import AtomSpec, DialogueCatalog, GrammarRule

_ANSWER_TYPES = frozenset(
    {
        "smalltalk",
        "prove",
        "explain",
        "list",
        "value",
        "leader",
        "describe",
        "summary",
        "located",
        "started",
        "last_works",
    }
)
_CASES = frozenset({"nom", "gen", "dat", "acc", "ins", "prep"})
_VAR = re.compile(r"\$([A-Za-z0-9_]+)")

_REF = re.compile(r"^\$([A-Za-z0-9_]+)(?:\.[A-Za-z0-9_.]+)?$")


def _walk_refs(value, found: Set[str]) -> None:
    if isinstance(value, str):
        match = _REF.match(value)
        if match:
            found.add(match.group(1))
        return
    if isinstance(value, list):
        for item in value:
            _walk_refs(item, found)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _walk_refs(item, found)


def _rule_problems(rule: GrammarRule) -> List[str]:
    problems: List[str] = []
    roles: Set[str] = set()
    for index, item in enumerate(rule.rhs):
        role = item.role or str(index + 1)
        if role in roles:
            problems.append(
                "правило %s: роль %r повторяется" % (rule.id, role)
            )
        roles.add(role)
    if rule.head and rule.head not in roles:
        problems.append(
            "правило %s: head %r не совпадает ни с одной ролью"
            % (rule.id, rule.head)
        )
    refs: Set[str] = set()
    _walk_refs(rule.sem, refs)
    for ref in sorted(refs):
        if ref not in roles:
            problems.append(
                "правило %s: семантика ссылается на неизвестную роль %r"
                % (rule.id, ref)
            )
    return problems


def _variables(value: Any) -> Set[str]:
    found: Set[str] = set()
    if isinstance(value, str):
        found.update(_VAR.findall(value))
        return found
    if isinstance(value, list):
        for item in value:
            found.update(_variables(item))
        return found
    if isinstance(value, Mapping):
        for item in value.values():
            found.update(_variables(item))
    return found


def _entity_problems(
    catalog: DialogueCatalog, value: Any, where: str
) -> List[str]:
    entity_types = set(catalog.ontology.entity_types)
    known = {entry.id for entry in catalog.lexicon}
    problems: List[str] = []
    if not isinstance(value, str) or "$" in value or ":" not in value:
        return problems
    prefix = value.split(":", 1)[0]
    if prefix in entity_types and value not in known:
        problems.append(
            "%s: сущность %r отсутствует в лексиконе" % (where, value)
        )
    return problems


def _relations(catalog: DialogueCatalog) -> Dict[str, int]:
    raw = catalog.world.get("relations") or {}
    return {
        str(name): int(arity)
        for name, arity in raw.items()
    }


def _atom_problems(
    atom: AtomSpec, known: Mapping[str, int], where: str
) -> List[str]:
    problems: List[str] = []
    if atom.rel not in known:
        problems.append(
            "%s: отношение %r не объявлено в world.relations"
            % (where, atom.rel)
        )
    elif known[atom.rel] != len(atom.args):
        problems.append(
            "%s: у отношения %r арность %d, использовано %d"
            % (where, atom.rel, known[atom.rel], len(atom.args))
        )
    return problems


def _rule_data_problems(
    catalog: DialogueCatalog, known: Mapping[str, int]
) -> List[str]:
    problems: List[str] = []
    for rule in catalog.rules:
        problems.extend(
            _atom_problems(rule.head, known, "правило %s.head" % rule.id)
        )
        premise_vars: Set[str] = set()
        for index, premise in enumerate(rule.premises):
            problems.extend(
                _atom_problems(
                    premise,
                    known,
                    "правило %s.premises[%d]" % (rule.id, index),
                )
            )
            premise_vars.update(
                arg for arg in premise.args if arg.startswith("$")
            )
        for arg in rule.head.args:
            if arg.startswith("$") and arg not in premise_vars:
                problems.append(
                    "правило %s: переменная %r в голове не связана "
                    "посылками" % (rule.id, arg)
                )
    return problems


def _fact_problems(
    catalog: DialogueCatalog, known: Mapping[str, int]
) -> List[str]:
    problems: List[str] = []
    for index, fact in enumerate(catalog.facts):
        where = "факт[%d] %s" % (index, fact.rel)
        problems.extend(_atom_problems(fact, known, where))
        for arg in fact.args:
            problems.extend(_entity_problems(catalog, arg, where))
    return problems


def _realization_keys(
    catalog: DialogueCatalog,
) -> tuple:
    answers = catalog.realization.get("answers") or {}
    statements = catalog.realization.get("statements") or {}
    return answers, statements


def _plan_problems(
    catalog: DialogueCatalog, known: Mapping[str, int]
) -> List[str]:
    problems: List[str] = []
    answers, statements = _realization_keys(catalog)
    list_intros = answers.get("list") or {}
    list_empty = answers.get("empty") or {}
    for plan in catalog.plans:
        where = "план %s" % plan.id
        answer = plan.answer
        kind = str(answer.get("type") or "")
        if kind not in _ANSWER_TYPES:
            problems.append(
                "%s: неизвестный тип ответа %r" % (where, kind)
            )
            continue
        captured = {"$" + key for key in _variables(plan.match)}
        derived = {"$" + key for key in plan.output}
        derived.update(
            {"$" + str(key) for key in answer.get("output") or ()}
        )
        allowed = captured | derived
        relation = str(answer.get("relation") or "")
        raw_args = answer.get("args") or ()
        if relation and isinstance(raw_args, Mapping):
            arity = known.get(relation)
            for name, value in raw_args.items():
                try:
                    position = int(value)
                except (TypeError, ValueError):
                    problems.append(
                        "%s: args.%s не число" % (where, name)
                    )
                    continue
                if arity is not None and not 0 <= position < arity:
                    problems.append(
                        "%s: args.%s=%d вне арности %d"
                        % (where, name, position, arity)
                    )
        elif relation:
            args = [str(item) for item in raw_args]
            problems.extend(
                _atom_problems(
                    AtomSpec(relation, tuple(args)), known, where
                )
            )
            for arg in args:
                for name in _VAR.findall(arg):
                    if "$" + name not in allowed:
                        problems.append(
                            "%s: переменная $%s в args не связана "
                            "шаблоном или output" % (where, name)
                        )
        label_relation = str(answer.get("label_relation") or "")
        if label_relation:
            label_args = [
                str(item) for item in answer.get("label_args") or ()
            ]
            problems.extend(
                _atom_problems(
                    AtomSpec(label_relation, tuple(label_args)),
                    known,
                    where + ".label_args",
                )
            )
        synthesis_answers = catalog.synthesis.get("answers") or {}
        for key in (
            "prefix_key",
            "empty_prefix_key",
            "template_key",
            "phrase_key",
        ):
            name = str(answer.get(key) or "")
            if (
                name
                and name not in answers
                and name not in synthesis_answers
            ):
                problems.append(
                    "%s: ключ %s=%r отсутствует в synthesis.answers "
                    "и realization.answers" % (where, key, name)
                )
        for name in (answer.get("keys") or {}).values():
            name = str(name)
            if name and name not in answers and name not in synthesis_answers:
                problems.append(
                    "%s: ключ %r отсутствует в synthesis.answers "
                    "и realization.answers" % (where, name)
                )
        if kind == "smalltalk":
            key = str(answer.get("key") or "")
            if not key:
                problems.append("%s: smalltalk без key" % where)
            elif key != "greeting" and not any(
                key in persona.smalltalk
                for persona in catalog.personas.values()
            ):
                problems.append(
                    "%s: smalltalk key %r отсутствует в персонах"
                    % (where, key)
                )
        if kind == "list":
            intro = str(answer.get("intro_key") or "")
            empty = str(answer.get("empty_key") or "")
            synthesis_lists = catalog.synthesis.get("lists") or {}
            if (
                intro
                and intro not in list_intros
                and intro not in synthesis_lists
            ):
                problems.append(
                    "%s: intro_key %r отсутствует" % (where, intro)
                )
            if (
                empty
                and empty not in list_empty
                and empty not in synthesis_lists
            ):
                problems.append(
                    "%s: empty_key %r отсутствует" % (where, empty)
                )
            if not plan.output:
                problems.append("%s: list без output" % where)
        if kind == "value" and not plan.output:
            problems.append("%s: value без output" % where)
        statement = str(answer.get("statement") or "")
        synthesis_statements = catalog.synthesis.get("statements") or {}
        if (
            statement
            and statement not in statements
            and statement not in synthesis_statements
        ):
            problems.append(
                "%s: statement %r отсутствует в synthesis.statements "
                "и realization.statements" % (where, statement)
            )
        missing = str(answer.get("missing") or "")
        if missing and missing not in ("unknown", "no"):
            problems.append(
                "%s: missing=%r, ожидается unknown или no"
                % (where, missing)
            )
    return problems


def _realization_problems(
    catalog: DialogueCatalog, known: Mapping[str, int]
) -> List[str]:
    problems: List[str] = []
    statements = catalog.realization.get("statements") or {}
    entity_types = set(catalog.ontology.entity_types)
    for relation, spec in statements.items():
        if relation not in known:
            problems.append(
                "realization.statements: отношение %r не объявлено" % relation
            )
            continue
        arity = known[relation]
        for slot_name, slot in (spec.get("slots") or {}).items():
            try:
                index = int(slot.get("arg", 0))
            except (TypeError, ValueError):
                problems.append(
                    "realization.statements.%s.%s: arg не число"
                    % (relation, slot_name)
                )
                continue
            if index < 0 or index >= arity:
                problems.append(
                    "realization.statements.%s.%s: arg %d вне арности %d"
                    % (relation, slot_name, index, arity)
                )
            case = str(slot.get("case") or "")
            if case and case not in _CASES:
                problems.append(
                    "realization.statements.%s.%s: неизвестный падеж %r"
                    % (relation, slot_name, case)
                )
    for section in ("describe", "summary"):
        for type_name in (catalog.realization.get(section) or {}):
            if type_name not in entity_types:
                problems.append(
                    "realization.%s: неизвестный тип %r"
                    % (section, type_name)
                )
    return problems


def _synthesis_problems(
    catalog: DialogueCatalog, known: Mapping[str, int]
) -> List[str]:
    problems: List[str] = []
    synthesis = catalog.synthesis or {}
    entries = {entry.id: entry for entry in catalog.lexicon}
    constructions = synthesis.get("constructions") or {}
    statements = synthesis.get("statements") or {}
    phrases = synthesis.get("phrases") or {}
    collections = synthesis.get("collections") or {}
    entity_fields = synthesis.get("entity_fields") or {}
    answers = synthesis.get("answers") or {}
    lists = synthesis.get("lists") or {}
    value_lexicon = synthesis.get("value_lexicon") or {}
    entity_types = set(catalog.ontology.entity_types)

    if not constructions:
        problems.append("synthesis.constructions: пусто")
    if not statements:
        problems.append("synthesis.statements: пусто")

    for value, entry_id in value_lexicon.items():
        if str(entry_id) not in entries:
            problems.append(
                "synthesis.value_lexicon.%s: лексема %r отсутствует"
                % (value, entry_id)
            )

    for entry_id, forms in (synthesis.get("word_forms") or {}).items():
        if str(entry_id) not in entries:
            problems.append(
                "synthesis.word_forms: лексема %r отсутствует" % entry_id
            )
            continue
        if not isinstance(forms, Mapping):
            problems.append(
                "synthesis.word_forms.%s: ожидался объект" % entry_id
            )
            continue
        for key, value in forms.items():
            if not str(key) or not isinstance(value, str) or not value:
                problems.append(
                    "synthesis.word_forms.%s.%s: нужна непустая строка"
                    % (entry_id, key)
                )

    for construction_id, spec in constructions.items():
        where = "synthesis.constructions.%s" % construction_id
        if not isinstance(spec, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        parts = spec.get("parts")
        if not isinstance(parts, list) or not parts:
            problems.append("%s.parts: пустой список" % where)
            continue
        for index, part in enumerate(parts):
            problems.extend(
                _part_problems(
                    part,
                    entries,
                    value_lexicon,
                    where + ".parts[%d]" % index,
                )
            )

    for relation, spec in statements.items():
        where = "synthesis.statements.%s" % relation
        if relation not in known:
            problems.append(
                "%s: отношение не объявлено в world.relations" % where
            )
            continue
        if not isinstance(spec, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        construction = str(spec.get("construction") or "")
        if construction not in constructions:
            problems.append(
                "%s: конструкция %r отсутствует" % (where, construction)
            )
        arity = known[relation]
        for name, index in (spec.get("args") or {}).items():
            try:
                position = int(index)
            except (TypeError, ValueError):
                problems.append(
                    "%s.args.%s: индекс не число" % (where, name)
                )
                continue
            if position < 0 or position >= arity:
                problems.append(
                    "%s.args.%s: индекс %d вне арности %d"
                    % (where, name, position, arity)
                )
        for name, value in (spec.get("consts") or {}).items():
            problems.extend(
                _entity_problems(
                    catalog, value, "%s.consts.%s" % (where, name)
                )
            )

    for name, spec in collections.items():
        where = "synthesis.collections.%s" % name
        if not isinstance(spec, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        kind = str(spec.get("kind") or "items")
        if kind not in ("items", "numbered", "beliefs"):
            problems.append("%s: неизвестный kind %r" % (where, kind))
            continue
        if kind == "beliefs":
            continue
        relation = str(spec.get("relation") or "")
        if relation not in known:
            problems.append(
                "%s: отношение %r не объявлено" % (where, relation)
            )
            continue
        pattern = list(spec.get("pattern") or ())
        if len(pattern) != known[relation]:
            problems.append(
                "%s.pattern: длина %d, арность %d"
                % (where, len(pattern), known[relation])
            )
        variables = {
            str(item) for item in pattern if str(item).startswith("$")
        }
        for key in ("var", "key", "value"):
            name_value = str(spec.get(key) or "")
            if name_value and name_value not in variables:
                problems.append(
                    "%s.%s: переменная %r отсутствует в pattern"
                    % (where, key, name_value)
                )
        for item in pattern:
            if item == "$self":
                continue
            if not str(item).startswith("$"):
                problems.extend(
                    _entity_problems(catalog, item, where + ".pattern")
                )

    for phrase_id, spec in phrases.items():
        where = "synthesis.phrases.%s" % phrase_id
        if not isinstance(spec, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        requires = spec.get("requires")
        if requires is not None and not isinstance(requires, list):
            problems.append("%s.requires: ожидался список" % where)
        kind = str(spec.get("kind") or "")
        if kind in ("list", "sentences"):
            collection = str(
                spec.get("collection") or spec.get("source") or ""
            )
            if collection not in collections:
                problems.append(
                    "%s: коллекция %r отсутствует" % (where, collection)
                )
            continue
        parts = spec.get("parts")
        if not isinstance(parts, list) or not parts:
            problems.append("%s.parts: пустой список" % where)
            continue
        for index, part in enumerate(parts):
            problems.extend(
                _part_problems(
                    part,
                    entries,
                    value_lexicon,
                    where + ".parts[%d]" % index,
                )
            )
        sources = {
            str(part.get("source") or "")
            for part in parts
            if isinstance(part, Mapping)
        }
        for name in requires or ():
            if not isinstance(name, str) or not name:
                problems.append(
                    "%s.requires: нужна непустая строка" % where
                )
            elif name not in sources:
                problems.append(
                    "%s.requires: источник %r не используется в parts"
                    % (where, name)
                )

    for type_name, fields in entity_fields.items():
        where = "synthesis.entity_fields.%s" % type_name
        if type_name not in entity_types:
            problems.append("%s: неизвестный тип" % where)
        if not isinstance(fields, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        for field_name, spec in fields.items():
            if not isinstance(spec, Mapping):
                problems.append(
                    "%s.%s: ожидался объект" % (where, field_name)
                )
                continue
            kind = str(spec.get("kind") or "relation")
            if kind == "collection":
                collection = str(spec.get("collection") or "")
                if collection not in collections:
                    problems.append(
                        "%s.%s: коллекция %r отсутствует"
                        % (where, field_name, collection)
                    )
                continue
            relation = str(spec.get("relation") or "")
            if relation not in known:
                problems.append(
                    "%s.%s: отношение %r не объявлено"
                    % (where, field_name, relation)
                )
                continue
            pattern = list(spec.get("pattern") or ())
            if len(pattern) != known[relation]:
                problems.append(
                    "%s.%s.pattern: длина %d, арность %d"
                    % (
                        where,
                        field_name,
                        len(pattern),
                        known[relation],
                    )
                )
            variables = {
                str(item)
                for item in pattern
                if str(item).startswith("$")
            }
            for name, mapping in (spec.get("fields") or {}).items():
                variable = (
                    str(mapping.get("var") or "")
                    if isinstance(mapping, Mapping)
                    else str(mapping)
                )
                if variable and variable not in variables:
                    problems.append(
                        "%s.%s.fields.%s: переменная %r отсутствует "
                        "в pattern"
                        % (where, field_name, name, variable)
                    )

    for section in ("describe", "summary"):
        for type_name, ids in (synthesis.get(section) or {}).items():
            where = "synthesis.%s.%s" % (section, type_name)
            if type_name not in entity_types:
                problems.append("%s: неизвестный тип" % where)
            for phrase_id in ids or ():
                if str(phrase_id) not in phrases:
                    problems.append(
                        "%s: фраза %r отсутствует" % (where, phrase_id)
                    )

    for key, spec in answers.items():
        where = "synthesis.answers.%s" % key
        if not isinstance(spec, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        construction = str(spec.get("construction") or "")
        phrase = str(spec.get("phrase") or "")
        if construction and construction not in constructions:
            problems.append(
                "%s: конструкция %r отсутствует" % (where, construction)
            )
        if phrase and phrase not in phrases:
            problems.append("%s: фраза %r отсутствует" % (where, phrase))
        if not construction and not phrase:
            problems.append(
                "%s: нужна construction или phrase" % where
            )

    for key, spec in lists.items():
        where = "synthesis.lists.%s" % key
        if not isinstance(spec, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        for name in ("intro", "empty"):
            phrase_id = str(spec.get(name) or "")
            if phrase_id and phrase_id not in phrases:
                problems.append(
                    "%s.%s: фраза %r отсутствует"
                    % (where, name, phrase_id)
                )

    for predicate, spec in (
        catalog.world.get("belief_predicates") or {}
    ).items():
        relation = str((spec or {}).get("relation") or "")
        if relation and relation not in statements:
            problems.append(
                "world.belief_predicates.%s: для отношения %r нет "
                "конструкции в synthesis.statements"
                % (predicate, relation)
            )
    return problems


def _part_problems(
    part: Any,
    entries: Mapping[str, Any],
    value_lexicon: Mapping[str, Any],
    where: str,
) -> List[str]:
    if not isinstance(part, Mapping):
        return ["%s: ожидался объект" % where]
    kind = str(part.get("kind") or "")
    problems: List[str] = []
    if kind in ("literal", "text", "number", "np"):
        source = str(part.get("source") or part.get("text") or "")
        if not source:
            problems.append("%s: пустой источник" % where)
        if kind == "np":
            case = str(part.get("case") or "nom")
            if case not in _CASES:
                problems.append("%s: неизвестный падеж %r" % (where, case))
        return problems
    if kind in ("lex", "adj"):
        entry_id = str(part.get("entry") or "")
        mapping = str(part.get("entry_from") or "")
        source = str(part.get("source") or "")
        if mapping:
            if mapping not in ("value_lexicon",):
                problems.append(
                    "%s: неизвестный entry_from %r" % (where, mapping)
                )
            elif not source:
                problems.append(
                    "%s: entry_from без source" % where
                )
            elif not value_lexicon:
                problems.append(
                    "%s: пустой value_lexicon" % where
                )
        elif not entry_id:
            problems.append(
                "%s: нужен entry или entry_from" % where
            )
        elif entry_id not in entries:
            problems.append(
                "%s: лексема %r отсутствует" % (where, entry_id)
            )
        case = str(part.get("case") or "")
        if case and case not in _CASES:
            problems.append("%s: неизвестный падеж %r" % (where, case))
        form = str(part.get("form") or "")
        if form and form not in (
            "present",
            "past",
            "infinitive",
            "long",
            "short",
        ):
            problems.append("%s: неизвестная форма %r" % (where, form))
        return problems
    problems.append("%s: неизвестный вид части %r" % (where, kind))
    return problems


def _world_problems(catalog: DialogueCatalog) -> List[str]:
    problems: List[str] = []
    assets = {entry.id for entry in catalog.lexicon if entry.type == "asset"}
    known_entities = {entry.id for entry in catalog.lexicon}
    for side, item in (catalog.world.get("factions") or {}).items():
        data = item if isinstance(item, Mapping) else {}
        entity = str(data.get("entity") or "")
        if entity and entity not in known_entities:
            problems.append(
                "world.factions.%s: сущность %r отсутствует в лексиконе"
                % (side, entity)
            )
        if not str(data.get("campaign_id") or ""):
            problems.append(
                "world.factions.%s: пустой campaign_id" % side
            )
    for key in catalog.world.get("assets") or ():
        if "asset:%s" % key not in assets:
            problems.append(
                "world.assets: нет лексемы asset:%s" % key
            )
    relations = catalog.world.get("relations") or {}
    if not relations:
        problems.append("world.relations: пусто")
    for role, relation in (catalog.world.get("adapter") or {}).items():
        if str(relation) not in relations:
            problems.append(
                "world.adapter.%s: отношение %r не объявлено"
                % (role, relation)
            )
    for predicate, spec in (
        catalog.world.get("belief_predicates") or {}
    ).items():
        relation = str((spec or {}).get("relation") or "")
        if relation not in relations:
            problems.append(
                "world.belief_predicates.%s: отношение %r не объявлено"
                % (predicate, relation)
            )
    return problems


def _persona_problems(catalog: DialogueCatalog) -> List[str]:
    problems: List[str] = []
    if not catalog.personas:
        problems.append("personas: пусто")
    for key, persona in catalog.personas.items():
        if not persona.greeting:
            problems.append("persona %s: пустое greeting" % key)
        if not persona.unknown:
            problems.append("persona %s: пустое unknown" % key)
        if not persona.parse_unknown:
            problems.append("persona %s: пустое parse_unknown" % key)
        if persona.max_list_items < 1:
            problems.append("persona %s: max_list_items < 1" % key)
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
