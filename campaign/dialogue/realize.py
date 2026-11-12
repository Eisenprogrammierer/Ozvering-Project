"""Композиционный синтез русской фразы по данным.

Слой не содержит готовых ответов и не знает предметной области. Он умеет
только собирать предложение из частей, описанных в ``synthesis.json``:
именная группа, лексема, прилагательное, число, литерал. Падежи, род,
число и спряжение берутся из ``morph.py``.

Конструкции — это деревья частей. Одна и та же логическая связь может
быть выражена разными конструкциями; выбор задаётся данными, а шаблоны
из ``realization.json`` используются только как аварийный fallback.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .inference import InferenceEngine, is_variable
from .knowledge import AgentKnowledge
from .model import DialogueCatalog, LexEntry
from .morph import Morphology


def _capitalize(text: str) -> str:
    text = str(text or "")
    return text[:1].upper() + text[1:] if text else text


def _format_number(value: Any) -> str:
    try:
        return "%.2f" % float(value)
    except (TypeError, ValueError):
        return str(value)


class Realizer:
    """Собирает русский текст из данных и морфологии."""

    def __init__(
        self,
        catalog: DialogueCatalog,
        knowledge: AgentKnowledge,
        engine: InferenceEngine,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.engine = engine
        self.synthesis: Mapping[str, Any] = catalog.synthesis or {}
        self.constructions = self.synthesis.get("constructions") or {}
        self.statements = self.synthesis.get("statements") or {}
        self.phrases = self.synthesis.get("phrases") or {}
        self.collections = self.synthesis.get("collections") or {}
        self.entity_fields = self.synthesis.get("entity_fields") or {}
        self.answers = self.synthesis.get("answers") or {}
        self.lists = self.synthesis.get("lists") or {}
        self.value_lexicon = self.synthesis.get("value_lexicon") or {}
        self.morphology = Morphology(self.synthesis)
        self._entries: Dict[str, LexEntry] = {
            entry.id: entry for entry in catalog.lexicon
        }

    # --- публичный API ----------------------------------------------

    def statement(self, relation: str, args: Iterable[Any]) -> str:
        """Выразить логическую связь предложением из конструкции."""

        spec = self.statements.get(str(relation))
        if not isinstance(spec, Mapping):
            return ""
        args = tuple(str(item) for item in args)
        data: Dict[str, Any] = {}
        for name, index in (spec.get("args") or {}).items():
            try:
                position = int(index)
            except (TypeError, ValueError):
                continue
            if 0 <= position < len(args):
                data[str(name)] = args[position]
        for name, value in (spec.get("consts") or {}).items():
            data[str(name)] = value
        prefix = str(spec.get("label_prefix") or "")
        if prefix and "key" in data:
            data["label"] = prefix + str(data["key"])
        return self.construction(str(spec.get("construction") or ""), data)

    def construction(
        self, construction_id: str, data: Mapping[str, Any]
    ) -> str:
        spec = self.constructions.get(str(construction_id))
        if not isinstance(spec, Mapping):
            return ""
        return self._render_spec(spec, data)

    def phrase(self, phrase_id: str, data: Mapping[str, Any]) -> str:
        spec = self.phrases.get(str(phrase_id))
        if not isinstance(spec, Mapping):
            return ""
        kind = str(spec.get("kind") or "")
        if kind in ("list", "sentences"):
            return self._render_collection(spec, data)
        return self._render_spec(spec, data)

    def describe(self, target: str) -> str:
        type_name = self.knowledge.type_of(target)
        ids = (self.synthesis.get("describe") or {}).get(type_name) or ()
        return self._render_sequence(ids, target)

    def summary(self, target: str) -> str:
        type_name = self.knowledge.type_of(target)
        ids = (self.synthesis.get("summary") or {}).get(type_name) or ()
        return self._render_sequence(ids, target)

    def answer(self, key: str, data: Mapping[str, Any]) -> str:
        """Готовая ответная конструкция по ключу из данных."""

        spec = self.answers.get(str(key))
        if not isinstance(spec, Mapping):
            return ""
        phrase_id = str(spec.get("phrase") or "")
        if phrase_id:
            return self.phrase(phrase_id, data)
        return self.construction(str(spec.get("construction") or ""), data)

    def list_intro(self, key: str, owner: str) -> str:
        spec = self.lists.get(str(key)) or {}
        phrase_id = str(spec.get("intro") or "")
        return self.phrase(phrase_id, {"owner": owner}) if phrase_id else ""

    def list_empty(self, key: str, owner: str) -> str:
        spec = self.lists.get(str(key)) or {}
        phrase_id = str(spec.get("empty") or "")
        return self.phrase(phrase_id, {"owner": owner}) if phrase_id else ""

    def list_separator(self, key: str, default: str = ", ") -> str:
        spec = self.lists.get(str(key)) or {}
        return str(spec.get("separator") or default)

    def belief_sentences(self, target: str) -> List[str]:
        """Убеждения говорящего о цели — предложениями из конструкций."""

        predicates = self.knowledge.world.get("belief_predicates") or {}
        result: List[str] = []
        seen: set = set()
        for fact in self.knowledge.facts_for("belief"):
            if len(fact.args) < 4:
                continue
            holder, subject, predicate, obj = fact.args[:4]
            if holder != self.knowledge.speaker_id:
                continue
            if subject != target and obj != target:
                continue
            spec = predicates.get(predicate) or {}
            relation = str(spec.get("relation") or "")
            if not relation:
                continue
            args = (subject, obj) if spec.get("object") else (subject,)
            sentence = self.statement(relation, args)
            if sentence and sentence not in seen:
                seen.add(sentence)
                result.append(sentence)
        return result

    # --- данные описания --------------------------------------------

    def description_data(self, target: str) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "target": target,
            "owner": target,
            "name": self.knowledge.name(target),
            "type_label": self.knowledge.type_label(target),
        }
        type_name = self.knowledge.type_of(target)
        for field, spec in (
            self.entity_fields.get(type_name) or {}
        ).items():
            if not isinstance(spec, Mapping):
                continue
            if str(spec.get("kind") or "relation") == "collection":
                value = self.collection(
                    str(spec.get("collection") or ""), target
                )
                if value:
                    data[str(field)] = value
                continue
            data.update(self._field_values(spec, target))
        return data

    def _field_values(
        self, spec: Mapping[str, Any], target: str
    ) -> Dict[str, str]:
        relation = str(spec.get("relation") or "")
        if not relation:
            return {}
        pattern = [
            target if str(item) == "$self" else str(item)
            for item in spec.get("pattern") or ()
        ]
        solution = self.engine.first(relation, *pattern)
        if solution is None:
            return {}
        values: Dict[str, str] = {}
        for name, mapping in (spec.get("fields") or {}).items():
            if isinstance(mapping, Mapping):
                variable = str(mapping.get("var") or "")
                value = solution.bindings.get(variable, "")
                text = self._field_text(value, mapping)
            else:
                variable = str(mapping)
                value = solution.bindings.get(variable, variable)
                text = str(value)
            if text:
                values[str(name)] = text
        return values

    def _field_text(
        self, value: str, mapping: Mapping[str, Any]
    ) -> str:
        value = str(value or "")
        if not value or is_variable(value):
            return ""
        if str(mapping.get("format") or "") == "number":
            return _format_number(value)
        case = str(mapping.get("case") or "")
        if case:
            return self.noun(value, case, str(mapping.get("number") or "sg"))
        return value

    def collection(self, name: str, target: str) -> str:
        spec = self.collections.get(str(name))
        if not isinstance(spec, Mapping):
            return ""
        kind = str(spec.get("kind") or "items")
        if kind == "beliefs":
            sentences = self.belief_sentences(target)
            separator = str(spec.get("separator") or "; ")
            return separator.join(item.rstrip(".") for item in sentences)
        relation = str(spec.get("relation") or "")
        pattern = [
            target if str(item) == "$self" else str(item)
            for item in spec.get("pattern") or ()
        ]
        if not relation:
            return ""
        if kind == "numbered":
            return self._numbered(spec, relation, pattern)
        return self._items(spec, relation, pattern)

    def _items(
        self, spec: Mapping[str, Any], relation: str, pattern: Sequence[str]
    ) -> str:
        variables = [
            str(item) for item in pattern if str(item).startswith("$")
        ]
        variable = str(
            spec.get("var") or (variables[0] if variables else "$item")
        )
        case = str(spec.get("case") or "nom")
        number = str(spec.get("number") or "sg")
        values: List[str] = []
        seen: set = set()
        for solution in self.engine.prove(relation, pattern):
            value = solution.bindings.get(variable, "")
            if not value or value in seen:
                continue
            seen.add(value)
            values.append(self.noun(value, case, number))
        if bool(spec.get("sort", True)):
            values.sort()
        return str(spec.get("join") or ", ").join(values)

    def _numbered(
        self, spec: Mapping[str, Any], relation: str, pattern: Sequence[str]
    ) -> str:
        variables = [
            str(item) for item in pattern if str(item).startswith("$")
        ]
        key_var = str(
            spec.get("key") or (variables[0] if variables else "$key")
        )
        value_var = str(
            spec.get("value")
            or (variables[1] if len(variables) > 1 else "$value")
        )
        prefix = str(spec.get("label_prefix") or "")
        template = str(spec.get("format") or "{label} {value}")
        rows: List[str] = []
        seen: set = set()
        for solution in self.engine.prove(relation, pattern):
            key = solution.bindings.get(key_var, "")
            value = solution.bindings.get(value_var, "")
            if not key or not value:
                continue
            label = self.knowledge.surface(prefix + key, "nom")
            text = template.format(
                label=label, value=_format_number(value), key=key
            )
            if text in seen:
                continue
            seen.add(text)
            rows.append(text)
        if bool(spec.get("sort", True)):
            rows.sort()
        return str(spec.get("join") or ", ").join(rows)

    # --- сборка фразы ----------------------------------------------

    def _render_collection(
        self, spec: Mapping[str, Any], data: Mapping[str, Any]
    ) -> str:
        if not self._requirements_met(spec, data):
            return ""
        target = str(data.get("target") or data.get("owner") or "")
        name = str(spec.get("collection") or spec.get("source") or "")
        items = self.collection(name, target) if name else ""
        if not items:
            items = str(spec.get("empty") or "")
        label = str(spec.get("label") or "")
        separator = str(spec.get("separator") or ", ")
        if label:
            text = "%s: %s" % (label, items) if items else label
        else:
            text = items
        return self._finish(
            text,
            str(spec.get("end") if spec.get("end") is not None else "."),
            bool(spec.get("capitalize", True)),
        )

    def _render_sequence(self, ids: Iterable[Any], target: str) -> str:
        data = self.description_data(target)
        rendered = []
        for phrase_id in ids or ():
            text = self.phrase(str(phrase_id), data)
            if text:
                rendered.append(text)
        return " ".join(rendered)

    def _requirements_met(
        self, spec: Mapping[str, Any], data: Mapping[str, Any]
    ) -> bool:
        """Проверить, есть ли в данных все обязательные источники фразы.

        Фраза с ``requires`` не рендерится, если хотя бы одного источника
        нет. Так описание не превращается в «Начало:» без начала или в
        «— работа работы» у словарной лексемы без владельца. Набор
        обязательных полей задаётся в JSON, а не в коде.
        """

        for name in spec.get("requires") or ():
            value = data.get(str(name), "")
            if value is None or value == "" or isinstance(value, Mapping):
                return False
        return True

    def _render_spec(
        self, spec: Mapping[str, Any], data: Mapping[str, Any]
    ) -> str:
        if not self._requirements_met(spec, data):
            return ""
        parts: List[str] = []
        for part in spec.get("parts") or ():
            if not isinstance(part, Mapping):
                continue
            text = self._part(part, data)
            if text:
                parts.append(text)
        text = " ".join(parts)
        return self._finish(
            text,
            str(spec.get("end") if spec.get("end") is not None else "."),
            bool(spec.get("capitalize", True)),
        )

    def _part(self, part: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        kind = str(part.get("kind") or "")
        if kind == "literal":
            return str(part.get("text") or "")
        if kind == "text":
            value = data.get(str(part.get("source") or ""), "")
            if value is None or value == "" or isinstance(value, Mapping):
                return ""
            return (
                str(part.get("prefix") or "")
                + str(value)
                + str(part.get("suffix") or "")
            )
        if kind == "number":
            value = data.get(str(part.get("source") or ""), "")
            return _format_number(value) if value != "" else ""
        if kind == "np":
            entity = data.get(str(part.get("source") or ""), "")
            if not entity:
                return ""
            return self.noun(
                str(entity),
                str(part.get("case") or "nom"),
                self._part_number(part, data),
            )
        if kind == "lex":
            return self._lex(part, data)
        if kind == "adj":
            return self._adj(part, data)
        return ""

    def _lex(self, part: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        entry = self._entry(part, data)
        if entry is None:
            return ""
        form = str(part.get("form") or "")
        number = self._part_number(part, data)
        gender = self._part_gender(part, data)
        if form in ("present", "past", "infinitive"):
            return self.morphology.verb(
                entry.lemma,
                form=form,
                number=number,
                gender=gender,
                person=str(part.get("person") or "3"),
                entry_id=entry.id,
            )
        if entry.type == "adjective" or entry.cat == "ADJ":
            return self.morphology.adjective(
                entry.lemma,
                case=str(part.get("case") or "nom"),
                number=number,
                gender=gender,
                form=str(part.get("form") or "long"),
                entry_id=entry.id,
            )
        return self.morphology.noun(
            entry.lemma,
            case=str(part.get("case") or "nom"),
            number=number,
            entry_id=entry.id,
        )

    def _adj(self, part: Mapping[str, Any], data: Mapping[str, Any]) -> str:
        entry = self._entry(part, data)
        lemma = (
            entry.lemma
            if entry is not None
            else str(data.get(str(part.get("source") or ""), "") or "")
        )
        if not lemma:
            return ""
        return self.morphology.adjective(
            lemma,
            case=str(part.get("case") or "nom"),
            number=self._part_number(part, data),
            gender=self._part_gender(part, data),
            form=str(part.get("form") or "long"),
            entry_id=entry.id if entry is not None else "",
        )

    def _entry(
        self, part: Mapping[str, Any], data: Mapping[str, Any]
    ) -> Optional[LexEntry]:
        entry_id = str(part.get("entry") or "")
        if not entry_id:
            mapping = str(part.get("entry_from") or "")
            source = str(part.get("source") or "")
            if mapping and source:
                value = str(data.get(source) or "")
                entry_id = str(self.value_lexicon.get(value) or "")
        return self._entries.get(entry_id)

    def _part_number(
        self, part: Mapping[str, Any], data: Mapping[str, Any]
    ) -> str:
        number = str(part.get("number") or "")
        source = str(part.get("number_from") or "")
        if source:
            number = self.entity_number(str(data.get(source) or ""))
        return number or "sg"

    def _part_gender(
        self, part: Mapping[str, Any], data: Mapping[str, Any]
    ) -> str:
        gender = str(part.get("gender") or "")
        source = str(part.get("gender_from") or "")
        if not source and str(part.get("agreement") or ""):
            source = str(part.get("agreement") or "")
        if source:
            gender = self.entity_gender(str(data.get(source) or ""))
        return gender

    # --- именные группы и признаки ----------------------------------

    def noun(self, entity: str, case: str = "nom", number: str = "sg") -> str:
        entity = str(entity or "")
        if not entity:
            return ""
        info = self.knowledge.entity(entity)
        if info is not None and info.source == "dynamic":
            if number == "sg" and self.morphology.number_of(info.name) == "pl":
                number = "pl"
            return self.morphology.inflect_phrase(info.name, case, number)
        surface = self.knowledge.surface(entity, case, number)
        if info is None and surface == entity:
            return self.morphology.inflect_phrase(entity, case, number)
        return surface

    def entity_gender(self, entity: str) -> str:
        entry = self._entries.get(str(entity))
        if entry is not None:
            gender = str(entry.features.get("gender") or "")
            if gender:
                return gender
        return self.morphology.gender_of(self.knowledge.name(entity))

    def entity_number(self, entity: str) -> str:
        entry = self._entries.get(str(entity))
        if entry is not None:
            has_singular = False
            has_plural = False
            for form in entry.forms:
                if form.features.get("case") != "nom":
                    continue
                if form.features.get("number") == "pl":
                    has_plural = True
                elif form.features.get("number") == "sg":
                    has_singular = True
            if has_plural and not has_singular:
                return "pl"
        return "sg"

    # --- мелочи ------------------------------------------------------

    @staticmethod
    def _finish(text: str, end: str = ".", capitalize: bool = True) -> str:
        text = " ".join(str(text or "").split())
        if not text:
            return ""
        if capitalize:
            text = _capitalize(text)
        if end and not text.endswith((".", "!", "?", ":", ";")):
            text += end
        return text


def render_lines(lines: Iterable[str], data: Mapping[str, Any]) -> str:
    """Аварийный рендер строк realization.json (только fallback)."""

    rendered: List[str] = []
    for line in lines or ():
        fields = [
            name
            for _, name, _, _ in _parse_format(str(line))
            if name is not None
        ]
        if any(not data.get(name) for name in fields):
            continue
        try:
            text = str(line).format(**data).strip()
        except (KeyError, IndexError, ValueError):
            continue
        if text:
            rendered.append(_capitalize(text))
    return " ".join(rendered)


def _parse_format(line: str):
    import string

    try:
        return list(string.Formatter().parse(line))
    except ValueError:
        return []
