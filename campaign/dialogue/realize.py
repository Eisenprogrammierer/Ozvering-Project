"""Композиционный синтез русской фразы по данным."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .features import select_best
from .inference import InferenceEngine, is_variable
from .knowledge import AgentKnowledge
from .model import DialogueCatalog, LexEntry, StyleSpec
from .morph import Morphology
from .style import StyleEngine, normalize_gender

ACT_FOR_KIND = {
    "yes": "confirm",
    "no": "deny",
    "no_reason": "deny_reason",
    "unknown": "unknown",
    "clarification": "clarify",
    "clarify": "clarify",
    "smalltalk": "text",
    "explanation": "text",
    "description": "text",
    "summary": "text",
    "entity": "leader",
    "list": "list",
    "value": "value",
    "comparison": "text",
}

_NUMBER_ALIASES = {
    "sing": "sg",
    "plur": "pl",
    "sg": "sg",
    "pl": "pl",
}


def _capitalize(text: str) -> str:
    text = str(text or "")
    return text[:1].upper() + text[1:] if text else text


def _format_number(value: Any) -> str:
    try:
        return "%.2f" % float(value)
    except (TypeError, ValueError):
        return str(value)


def _marker_concept(identifier: str) -> str:
    text = str(identifier or "")
    if text.startswith("marker:"):
        text = text[len("marker:") :]
    return text.split("_", 1)[0]


def _normalize_number(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _NUMBER_ALIASES.get(text, "sg")


class Realizer:
    """Собирает русский текст из данных и морфологии."""

    def __init__(
        self,
        catalog: DialogueCatalog,
        knowledge: AgentKnowledge,
        engine: InferenceEngine,
        style_engine: Optional[StyleEngine] = None,
        memory: Any = None,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.engine = engine
        self.style_engine = style_engine or StyleEngine(catalog)
        self.style: StyleSpec = StyleSpec(id="", label="")
        self.memory = memory
        self.trace: List[Dict[str, Any]] = []
        self.discourse_trace: List[Dict[str, Any]] = []
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
        self.markers: List[Dict[str, Any]] = []
        for key, value in (self.synthesis.get("markers") or {}).items():
            if not isinstance(value, Mapping):
                continue
            item = dict(value)
            item["id"] = str(key)
            item.setdefault("concept", _marker_concept(str(key)))
            self.markers.append(item)
        self.lexical_groups: Mapping[str, Any] = (
            self.synthesis.get("lexical_groups") or {}
        )
        self.relations: Dict[str, List[Dict[str, Any]]] = {}
        self.act_constructions: Dict[str, List[Dict[str, Any]]] = {}
        for key, value in self.constructions.items():
            if not isinstance(value, Mapping):
                continue
            item = dict(value)
            item["id"] = str(key)
            relation = str(item.get("relation") or "")
            if relation:
                self.relations.setdefault(relation, []).append(item)
            act = str(item.get("act") or "")
            if act:
                self.act_constructions.setdefault(act, []).append(item)
        discourse = getattr(catalog, "discourse", None)
        self.discourse = discourse
        self.connectives: List[Dict[str, Any]] = [
            dict(item)
            for item in getattr(discourse, "connectives", ()) or ()
            if isinstance(item, Mapping)
        ]
        self.anaphora: Any = getattr(discourse, "anaphora", None)

    # --- публичный API ----------------------------------------------

    def set_style(self, style: Optional[StyleSpec]) -> None:
        self.style = style or StyleSpec(id="", label="")

    def set_discourse(self, catalog: Any) -> None:
        self.discourse = catalog
        self.connectives = [
            dict(item)
            for item in getattr(catalog, "connectives", ()) or ()
            if isinstance(item, Mapping)
        ]
        self.anaphora = getattr(catalog, "anaphora", None)

    def take_trace(self) -> List[Dict[str, Any]]:
        trace = self.trace
        self.trace = []
        return trace

    def take_discourse_trace(self) -> List[Dict[str, Any]]:
        trace = self.discourse_trace
        self.discourse_trace = []
        return trace

    def _recent(self) -> List[str]:
        if self.memory is None:
            return []
        getter = getattr(self.memory, "recent_constructions", None)
        return list(getter()) if callable(getter) else []

    def _recent_discourse(self) -> List[str]:
        if self.memory is None:
            return []
        getter = getattr(self.memory, "recent_discourse", None)
        return list(getter()) if callable(getter) else []

    def _note(self, construction_id: str) -> None:
        if self.memory is None or not construction_id:
            return
        note = getattr(self.memory, "note_construction", None)
        if callable(note):
            note(construction_id)

    def _note_discourse(self, connective_id: str) -> None:
        if self.memory is None or not connective_id:
            return
        note = getattr(self.memory, "note_discourse", None)
        if callable(note):
            note(connective_id)

    def _features(self) -> Mapping[str, str]:
        return StyleEngine.features(self.style)

    def _avoid_recent(self) -> int:
        try:
            return max(0, int(self.style.selection.get("avoid_recent") or 0))
        except (TypeError, ValueError):
            return 0

    def _select(self, candidates: Iterable[Any]) -> Any:
        items = list(candidates)
        if not items:
            return None
        return select_best(
            items,
            self._features(),
            recent=self._recent(),
            avoid=self._avoid_recent(),
        )

    def _record(self, kind: str, identifier: str, **extra: Any) -> None:
        entry = {
            "kind": kind,
            "id": identifier,
            "register": self.style.register,
        }
        entry.update(extra)
        self.trace.append(entry)
        self._note(identifier)

    def statement(self, relation: str, args: Iterable[Any]) -> str:
        spec = self.statements.get(str(relation))
        if not isinstance(spec, Mapping):
            return ""
        return self._statement_data(
            str(relation), spec, self.values_for(relation, args)
        )

    def values_for(
        self, relation: str, args: Iterable[Any]
    ) -> Dict[str, str]:
        spec = self.statements.get(str(relation))
        if not isinstance(spec, Mapping):
            return {}
        args = tuple(str(item) for item in args)
        data: Dict[str, str] = {}
        for name, index in (spec.get("args") or {}).items():
            try:
                position = int(index)
            except (TypeError, ValueError):
                continue
            if 0 <= position < len(args):
                data[str(name)] = args[position]
        return data

    def statement_map(
        self, relation: str, values: Mapping[str, Any]
    ) -> str:
        spec = self.statements.get(str(relation))
        if not isinstance(spec, Mapping):
            return ""
        data = {
            str(name): str(value)
            for name, value in values.items()
        }
        return self._statement_data(str(relation), spec, data)

    def _statement_data(
        self,
        relation: str,
        spec: Mapping[str, Any],
        data: Dict[str, Any],
    ) -> str:
        for name, value in (spec.get("consts") or {}).items():
            data[str(name)] = value
        prefix = str(spec.get("label_prefix") or "")
        if prefix and "key" in data:
            data["label"] = prefix + str(data["key"])
        explicit = str(spec.get("construction") or "")
        candidates = [
            item for item in (self.relations.get(relation) or ())
            if str(item.get("id") or "") != explicit
        ]
        chosen = self._select(candidates)
        if chosen is not None:
            text = self._render_spec(chosen, data)
            if text:
                self._record(
                    "construction",
                    str(chosen.get("id") or ""),
                    relation=relation,
                )
                return text
        text = self.construction(explicit, data)
        if text:
            self._record(
                "construction", explicit, relation=relation
            )
        return text

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
        spec = self.answers.get(str(key))
        if not isinstance(spec, Mapping):
            return ""
        phrase_id = str(spec.get("phrase") or "")
        if phrase_id:
            return self.phrase(phrase_id, data)
        return self.construction(str(spec.get("construction") or ""), data)

    def realize_act(
        self, act: str, data: Mapping[str, Any], fallback: str = ""
    ) -> str:
        if StyleEngine.is_neutral(self.style):
            return fallback
        chosen = self._select(self.act_constructions.get(str(act)) or ())
        if chosen is None:
            return fallback
        values = dict(data)
        values.setdefault("message", fallback)
        text = self._render_spec(chosen, values)
        if not text:
            return fallback
        self._record("act", str(chosen.get("id") or ""), act=str(act))
        return self._wrap_address(text, values, str(act))

    def _wrap_address(
        self, text: str, data: Mapping[str, Any], act: str
    ) -> str:
        mode = str(self.style.feature("address_mode", "none"))
        if mode not in ("pre", "post"):
            return text
        if not self._address({}, data):
            return text
        chosen = self._select(
            self.act_constructions.get("address_wrap") or ()
        )
        if chosen is None:
            return text
        values = dict(data)
        values["inner"] = (
            text.rstrip(".") if mode == "post" else text
        )
        wrapped = self._render_spec(chosen, values)
        if not wrapped:
            return text
        self._record(
            "act", str(chosen.get("id") or ""), act="address_wrap"
        )
        return wrapped

    def realize_answer(
        self,
        kind: str,
        data: Mapping[str, Any],
        fallback: str = "",
        keys: Optional[Iterable[str]] = None,
    ) -> str:
        act = ACT_FOR_KIND.get(str(kind), str(kind))
        base: Dict[str, Any] = {
            "speaker": getattr(self.knowledge, "speaker_name", ""),
            "speaker_post": getattr(self.knowledge, "speaker_post", ""),
            "speaker_faction": getattr(self.knowledge, "faction_name", ""),
            "player": getattr(self.knowledge, "player_name", ""),
            "player_post": getattr(self.knowledge, "player_post", ""),
            "player_faction": getattr(self.knowledge, "player_faction", ""),
            "player_gender": getattr(self.knowledge, "player_gender", ""),
        }
        values = dict(base)
        values.update(data)
        return self.realize_act(act, values, fallback)

    # --- дискурсивный слой ------------------------------------------

    def render_moves(
        self, moves: Sequence[Mapping[str, Any]]
    ) -> str:
        """Собрать ответ из ходов, связок и анафоры.

        ``plain``-связка ставится после точки: «A. При этом B.».
        Если текст связки — сама точка, второе предложение просто
        идёт следом: «A. B.». ``clause``-связка встраивается внутрь
        одного предложения через запятую: «A, потому что B.».
        """

        if not moves:
            return ""
        rendered: List[Dict[str, Any]] = []
        for raw in moves:
            if not isinstance(raw, Mapping):
                continue
            text = str(raw.get("text") or "").strip()
            if not text:
                continue
            item = {
                "id": str(raw.get("id") or ""),
                "kind": str(raw.get("kind") or ""),
                "text": text,
            }
            entities = raw.get("entities") or ()
            item["entities"] = tuple(
                str(entity) for entity in entities if entity
            )
            rendered.append(item)
        if not rendered:
            return ""
        first_entities = self._first_entities(rendered[0])
        if first_entities:
            for index in range(1, len(rendered)):
                rendered[index]["text"] = self._apply_anaphora(
                    rendered[index]["text"],
                    rendered[index]["kind"],
                    first_entities,
                )
        result_parts: List[str] = [rendered[0]["text"]]
        for index in range(1, len(rendered)):
            connective = self._pick_connective(
                rendered[index - 1], rendered[index]
            )
            next_text = rendered[index]["text"]
            if connective is None:
                glue = "."
                mode = "plain"
            else:
                glue = str(connective.get("text") or ".")
                mode = str(connective.get("mode") or "plain")
                if bool(connective.get("lowercase_next")):
                    next_text = (
                        next_text[:1].lower() + next_text[1:]
                        if next_text
                        else next_text
                    )
                self.discourse_trace.append(
                    {
                        "kind": "connective",
                        "id": str(connective.get("id") or ""),
                        "register": self.style.register,
                        "mode": mode,
                        "between": (
                            rendered[index - 1]["id"],
                            rendered[index]["id"],
                        ),
                    }
                )
                self._note_discourse(
                    str(connective.get("id") or "")
                )
            previous = result_parts[-1].rstrip(".!?")
            if mode == "clause":
                result_parts[-1] = (
                    previous + ", " + glue + " " + next_text
                )
            else:
                if glue == "." or not glue:
                    result_parts[-1] = previous + ". " + next_text
                else:
                    result_parts[-1] = (
                        previous + ". " + glue + " " + next_text
                    )
        text = " ".join(part for part in result_parts if part)
        return self._finish(text, ".", True)

    def _first_entities(
        self, move: Mapping[str, Any]
    ) -> List[Mapping[str, Any]]:
        if not self._anaphora_enabled():
            return []
        allowed_types = set(self._anaphora_types())
        if not allowed_types:
            return []
        min_length = self._anaphora_min_length()
        result: List[Mapping[str, Any]] = []
        seen: set = set()
        for entity in move.get("entities") or ():
            entity = str(entity)
            if not entity or entity in seen:
                continue
            type_name = self.knowledge.type_of(entity)
            if type_name not in allowed_types:
                continue
            name = self.knowledge.name(entity)
            if len(name) < min_length:
                continue
            seen.add(entity)
            result.append(
                {
                    "id": entity,
                    "name": name,
                    "type": type_name,
                    "gender": self.morphology.gender_of(name),
                    "number": _normalize_number(
                        self.morphology.number_of(name)
                    ),
                }
            )
        return result

    def _apply_anaphora(
        self,
        text: str,
        kind: str,
        entities: Sequence[Mapping[str, Any]],
    ) -> str:
        if not self._anaphora_enabled():
            return text
        allowed_kinds = set(self._anaphora_kinds())
        if kind not in allowed_kinds:
            return text
        pronouns = self._anaphora_pronouns()
        result = str(text)
        replaced: set = set()
        for entity in entities:
            entity_id = str(entity.get("id") or "")
            name = str(entity.get("name") or "")
            if not entity_id or not name or entity_id in replaced:
                continue
            pattern = re.compile(re.escape(name), re.IGNORECASE)
            match = pattern.search(result)
            if match is None:
                continue
            gender = str(entity.get("gender") or "m")
            number = _normalize_number(entity.get("number") or "sg")
            key = "%s:%s" % (gender, number)
            pronoun = str(pronouns.get(key) or "")
            if not pronoun:
                continue
            original = match.group(0)
            if original.isupper() and len(original) > 1:
                replacement = pronoun.upper()
            elif original[:1].isupper():
                replacement = pronoun[:1].upper() + pronoun[1:]
            else:
                replacement = pronoun
            result = (
                result[: match.start()]
                + replacement
                + result[match.end() :]
            )
            replaced.add(entity_id)
            self.discourse_trace.append(
                {
                    "kind": "anaphora",
                    "entity": entity_id,
                    "pronoun": pronoun,
                    "gender": gender,
                    "number": number,
                    "in": kind,
                }
            )
        return result

    def _anaphora_enabled(self) -> bool:
        anaphora = self.anaphora
        if anaphora is None:
            return False
        return bool(getattr(anaphora, "enabled", False))

    def _anaphora_types(self) -> Sequence[str]:
        anaphora = self.anaphora
        if anaphora is None:
            return ()
        return tuple(getattr(anaphora, "types", ()) or ())

    def _anaphora_kinds(self) -> Sequence[str]:
        anaphora = self.anaphora
        if anaphora is None:
            return ()
        return tuple(getattr(anaphora, "kinds", ()) or ())

    def _anaphora_pronouns(self) -> Mapping[str, str]:
        anaphora = self.anaphora
        if anaphora is None:
            return {}
        return dict(getattr(anaphora, "pronouns", {}) or {})

    def _anaphora_min_length(self) -> int:
        anaphora = self.anaphora
        if anaphora is None:
            return 3
        try:
            return max(1, int(getattr(anaphora, "min_length", 3)))
        except (TypeError, ValueError):
            return 3

    def _pick_connective(
        self, left: Mapping[str, Any], right: Mapping[str, Any]
    ) -> Optional[Mapping[str, Any]]:
        if not self.connectives:
            return None
        candidates = [
            item for item in self.connectives
            if str(item.get("position") or "between") == "between"
        ]
        if not candidates:
            return None
        return select_best(
            candidates,
            self._features(),
            recent=self._recent_discourse(),
            avoid=self._avoid_recent(),
        )

    # --- остальное без изменений -----------------------------------

    def list_intro(self, key: str, owner: str) -> str:
        data = {"owner": owner, "key": str(key)}
        spec = self.lists.get(str(key)) or {}
        phrase_id = str(spec.get("intro") or "")
        return self.phrase(phrase_id, data) if phrase_id else ""

    def list_empty(self, key: str, owner: str) -> str:
        data = {"owner": owner, "key": str(key)}
        spec = self.lists.get(str(key)) or {}
        phrase_id = str(spec.get("empty") or "")
        return self.phrase(phrase_id, data) if phrase_id else ""

    def list_separator(self, key: str, default: str = ", ") -> str:
        spec = self.lists.get(str(key)) or {}
        return str(spec.get("separator") or default)

    def belief_sentences(self, target: str) -> List[str]:
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
            if not text:
                continue
            if parts and str(part.get("glue") or "") == "before":
                parts[-1] = parts[-1] + text
            else:
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
            text = str(value)
            if bool(part.get("lower")):
                text = text[:1].lower() + text[1:] if text else text
            return (
                str(part.get("prefix") or "")
                + text
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
        if kind == "clause":
            return self._clause(part, data)
        if kind == "address":
            return self._address(part, data)
        if kind == "items":
            return self._items_part(part, data)
        if kind == "marker":
            return self._marker(part)
        if kind == "act":
            source = str(part.get("source") or "")
            value = data.get(source, "")
            if value in (None, ""):
                value = data.get("claim") or data.get("message") or ""
            if not value or isinstance(value, Mapping):
                return ""
            return str(value)
        if kind == "particle":
            return self._particle(part)
        return ""

    def _clause(
        self, part: Mapping[str, Any], data: Mapping[str, Any]
    ) -> str:
        relation = str(part.get("relation") or "")
        source = str(part.get("source") or "")
        if not relation and source:
            relation = str(data.get(source) or "")
        if not relation:
            return ""
        values: Dict[str, Any] = {}
        mapping = part.get("args")
        if isinstance(mapping, str):
            raw = data.get(mapping) or {}
            mapping = raw if isinstance(raw, Mapping) else {}
        if isinstance(mapping, Mapping):
            for name, slot in mapping.items():
                if isinstance(slot, str):
                    value = data.get(slot, slot)
                else:
                    value = slot
                if value is not None and value != "":
                    values[str(name)] = value
        text = self.statement_map(relation, values)
        if not text:
            return ""
        text = text.rstrip(".")
        if bool(part.get("lower")):
            text = text[:1].lower() + text[1:] if text else text
        conjunction = str(part.get("conjunction") or "")
        if conjunction:
            text = conjunction + " " + text
        return text

    def _address(
        self, part: Mapping[str, Any], data: Mapping[str, Any]
    ) -> str:
        if str(self.style.feature("address_mode", "none")) == "none":
            source = str(part.get("source") or "")
            return str(data.get(source) or "") if source else ""
        group = [
            str(item)
            for item in self.lexical_groups.get("address") or ()
        ]
        entries = [
            self._entries[item]
            for item in group
            if item in self._entries
        ]
        gender = normalize_gender(
            getattr(self.knowledge, "player_gender", "")
        )
        wanted = gender if gender in ("m", "f") else "m"
        exact = [
            entry
            for entry in entries
            if str(entry.features.get("gender") or "") == wanted
        ]
        pool = exact or [
            entry
            for entry in entries
            if not str(entry.features.get("gender") or "")
        ]
        chosen = self._select(
            [self._lexical_item(entry) for entry in pool]
        )
        if chosen is None:
            return ""
        entry = chosen["entry"]
        self._record("address", entry.id, gender=wanted)
        if entry.type == "adjective" or entry.cat == "ADJ":
            return self.morphology.adjective(
                entry.lemma,
                case=str(part.get("case") or "nom"),
                number=str(part.get("number") or "sg"),
                gender=str(part.get("gender") or wanted),
                entry_id=entry.id,
            )
        return self.morphology.noun(
            entry.lemma,
            case=str(part.get("case") or "nom"),
            number=str(part.get("number") or "sg"),
            entry_id=entry.id,
        )

    def _marker(self, part: Mapping[str, Any]) -> str:
        concept = str(part.get("concept") or "")
        pool = [
            item
            for item in self.markers
            if str(item.get("concept") or "") == concept
            or str(item.get("id") or "").startswith(
                "marker:%s_" % concept
            )
        ]
        chosen = self._select(pool)
        if chosen is None:
            return ""
        self._record(
            "marker", str(chosen.get("id") or ""), concept=concept
        )
        return str(chosen.get("text") or "")

    def _items_part(
        self, part: Mapping[str, Any], data: Mapping[str, Any]
    ) -> str:
        values = data.get(str(part.get("source") or "items")) or ()
        if isinstance(values, str):
            return values
        separator = str(part.get("separator") or ", ")
        return separator.join(str(item) for item in values if item)

    def _particle(self, part: Mapping[str, Any]) -> str:
        values = part.get("values") or ()
        if isinstance(values, str):
            return values
        return str(values[0]) if values else str(part.get("default") or "")

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

    @staticmethod
    def _lexical_item(entry: LexEntry) -> Dict[str, Any]:
        features = {
            str(name): str(value)
            for name, value in (entry.features or {}).items()
            if str(name) not in ("gender", "number", "case")
        }
        return {"id": entry.id, "features": features, "entry": entry}

    def _concept_entries(self, concept: str) -> List[LexEntry]:
        group = self.lexical_groups.get(str(concept)) or ()
        return [
            self._entries[str(item)]
            for item in group
            if str(item) in self._entries
        ]

    def _entry(
        self, part: Mapping[str, Any], data: Mapping[str, Any]
    ) -> Optional[LexEntry]:
        entry_id = str(part.get("entry") or "")
        if not entry_id:
            concept = str(part.get("concept") or "")
            if concept:
                chosen = self._select(
                    [
                        self._lexical_item(entry)
                        for entry in self._concept_entries(concept)
                    ]
                )
                if chosen is None:
                    return None
                entry = chosen["entry"]
                self.trace.append(
                    {
                        "kind": "lexeme",
                        "concept": concept,
                        "to": entry.id,
                        "register": self.style.register,
                    }
                )
                return entry
            mapping = str(part.get("entry_from") or "")
            source = str(part.get("source") or "")
            if mapping and source:
                value = str(data.get(source) or "")
                entry_id = str(self.value_lexicon.get(value) or "")
        if not entry_id:
            return None
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