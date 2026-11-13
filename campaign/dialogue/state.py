"""Диалоговое состояние: QUD, референты, эллипсис и память партии.

Модуль ничего не решает о содержании мира. Он читает политику из
``state.json`` и интерпретирует её: разрешает местоимения по весам
референтов, восстанавливает неполные реплики по шаблонам, ведёт стек
обсуждаемых вопросов и долговременную память партии.

Память ограничена одной игровой сессией. Она сериализуется в сейв, не
меняет кампанию и BDI и не хранит сырые транскрипты: только значимые
факты, сущности, общий фонд и краткие сводки.

D4 добавляет ``commitments`` — обязательства и отказы из речевых
действий. Это социальное состояние разговора, а не факт мира: диалог
по-прежнему read-only по отношению к кампании и BDI.

D5.1 добавляет ``discourse`` — историю связок дискурсивного слоя.
Отдельный список нужен, чтобы антиповтор связок не вытеснял антиповтор
конструкций и лексем: это разные уровни вариативности.
"""

from __future__ import annotations

import copy
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from .morph import Morphology
from .morphology import tokenize

SCHEMA = 1


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _normalized_tokens(value: Any) -> List[str]:
    return tokenize(str(value or ""))


def _path_parts(path: str) -> List[str]:
    return [part for part in str(path or "").split(".") if part]


def _path_exists(root: Any, path: str) -> bool:
    current = root
    for part in _path_parts(path):
        if not isinstance(current, Mapping) or part not in current:
            return False
        current = current[part]
    return True


def _path_set(root: Any, path: str, value: Any) -> Any:
    parts = _path_parts(path)
    if not parts or not isinstance(root, dict):
        return root
    current = root
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value
    return root


def _ordered_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Стабильный порядок ключей записи памяти."""

    return {str(key): record[key] for key in sorted(record)}


class EntityIndex:
    """Поверхностные формы сущностей и местоимений из данных."""

    def __init__(
        self,
        catalog: Any,
        knowledge: Any,
        policy: Mapping[str, Any],
    ):
        resolution = _mapping(policy.get("entity_resolution"))
        self.max_tokens = max(1, _integer(resolution.get("max_tokens"), 5))
        self.ignore_prefixes = tuple(
            str(item) for item in resolution.get("ignore_prefixes") or ()
        )
        self.by_text: Dict[str, str] = {}
        self.by_name: Dict[str, str] = {}
        self.types: Dict[str, str] = {}
        self.names: Dict[str, str] = {}
        self.pronouns: Dict[str, str] = {}
        self.pronoun_ids: set = set()
        self.known: set = set()
        for entry in getattr(catalog, "lexicon", ()) or ():
            semantic = _mapping(getattr(entry, "semantic", {}))
            kind = str(semantic.get("kind") or "")
            if kind == "pronoun":
                identifier = str(semantic.get("id") or "")
                self.pronoun_ids.add(identifier)
                for form in entry.all_forms():
                    for text in _normalized_variants(form.text):
                        self.pronouns.setdefault(text, identifier)
                continue
            if kind != "entity":
                continue
            identifier = _text(semantic.get("id"))
            if not identifier:
                continue
            self.known.add(identifier)
            self.types[identifier] = _text(
                semantic.get("type"), str(getattr(entry, "type", ""))
            )
            name = _text(getattr(entry, "name", "")) or identifier
            self.names[identifier] = name
            for form in entry.all_forms():
                self._add(form.text, identifier)
        entities = getattr(knowledge, "entities", {}) or {}
        for identifier, info in entities.items():
            identifier = str(identifier)
            if identifier in self.pronoun_ids:
                continue
            if identifier.startswith("pron:"):
                continue
            name = _text(getattr(info, "name", ""), identifier)
            self.known.add(identifier)
            self.types.setdefault(
                identifier, _text(getattr(info, "type", ""))
            )
            self.names[identifier] = name
            self._add(name, identifier)
            self._add_name(name, identifier)

    def _add(self, text: Any, identifier: str) -> None:
        tokens = _normalized_tokens(text)
        if not tokens:
            return
        key = " ".join(tokens)
        self.by_text.setdefault(key, identifier)

    def _add_name(self, text: Any, identifier: str) -> None:
        tokens = _normalized_tokens(text)
        if not tokens:
            return
        self.by_name.setdefault(" ".join(tokens), identifier)

    def resolve(
        self, tokens: Sequence[str], start: int, kind: str
    ) -> Optional[Tuple[str, int]]:
        total = len(tokens)
        if kind == "pronoun":
            if start >= total:
                return None
            identifier = self.pronouns.get(str(tokens[start]))
            return (identifier, 1) if identifier else None
        limit = min(self.max_tokens, total - start)
        for span in range(limit, 0, -1):
            key = " ".join(tokens[start : start + span])
            identifier = self.by_text.get(key)
            if not identifier:
                continue
            if kind == "noun" and not identifier.startswith("noun:"):
                continue
            if kind == "entity" and identifier.startswith("noun:"):
                continue
            if kind != "noun" and self.ignored(identifier):
                continue
            return identifier, span
        return None

    def resolve_text(self, text: Any) -> str:
        tokens = _normalized_tokens(text)
        if not tokens:
            return ""
        for span in range(min(self.max_tokens, len(tokens)), 0, -1):
            identifier = self.by_text.get(" ".join(tokens[:span]))
            if identifier:
                return identifier
        return ""

    def by_name_text(self, text: Any) -> str:
        tokens = _normalized_tokens(text)
        if not tokens:
            return ""
        return self.by_name.get(" ".join(tokens), "")

    def ignored(self, identifier: Any) -> bool:
        value = str(identifier or "")
        return any(value.startswith(prefix) for prefix in self.ignore_prefixes)

    def type_of(self, identifier: str) -> str:
        default = str(identifier).split(":", 1)[0]
        return self.types.get(str(identifier), default)

    def name_of(self, identifier: str) -> str:
        return self.names.get(str(identifier), str(identifier))


def _normalized_variants(text: Any) -> Tuple[str, ...]:
    tokens = _normalized_tokens(text)
    if not tokens:
        return ()
    return (" ".join(tokens),)


def _describe_sem(entity: str) -> Dict[str, Any]:
    return {
        "kind": "question",
        "wh": "what",
        "body": {
            "kind": "assert",
            "copula": True,
            "subject": {"kind": "np", "head": {"entity": entity}},
        },
    }


class DialogueMemory:
    """Долговременная память одной партии."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        run_id: str = "campaign",
        clock: int = 0,
    ):
        self.policy = _mapping(policy.get("memory"))
        self.run_id = _text(run_id) or "campaign"
        self.clock = _integer(clock)
        self.turns = 0
        self.entities: Dict[str, Dict[str, Any]] = {}
        self.facts: Dict[str, Dict[str, Any]] = {}
        self.summaries: List[Dict[str, Any]] = []
        self.common_ground: Dict[str, Dict[str, Any]] = {}
        self.realizations: List[str] = []
        self.discourse: List[str] = []

    @classmethod
    def from_dict(
        cls, policy: Mapping[str, Any], data: Any
    ) -> "DialogueMemory":
        raw = _mapping(data)
        memory = cls(
            policy,
            run_id=_text(raw.get("run_id")) or "campaign",
            clock=_integer(raw.get("clock")),
        )
        memory.turns = max(0, _integer(raw.get("turns")))
        for identifier, item in _mapping(raw.get("entities")).items():
            record = _entity_record(str(identifier), item)
            if record is not None:
                memory.entities[str(identifier)] = record
        for key, item in _mapping(raw.get("facts")).items():
            record = _fact_record(str(key), item)
            if record is not None:
                memory.facts[str(key)] = record
        for item in raw.get("summaries") or ():
            record = _summary_record(item)
            if record is not None:
                memory.summaries.append(record)
        for key, item in _mapping(raw.get("common_ground")).items():
            record = _ground_record(str(key), item)
            if record is not None:
                memory.common_ground[str(key)] = record
        memory.realizations = [
            str(item)
            for item in raw.get("realizations") or ()
            if str(item)
        ][-8:]
        memory.discourse = [
            str(item)
            for item in raw.get("discourse") or ()
            if str(item)
        ][-8:]
        memory.prune()
        return memory

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "run_id": self.run_id,
            "clock": self.clock,
            "turns": self.turns,
            "entities": {
                key: _ordered_record(record)
                for key, record in sorted(self.entities.items())
            },
            "facts": {
                key: _ordered_record(record)
                for key, record in sorted(self.facts.items())
            },
            "summaries": [
                _ordered_record(record)
                for record in sorted(self.summaries, key=_record_sort_key)
            ],
            "common_ground": {
                key: _ordered_record(record)
                for key, record in sorted(self.common_ground.items())
            },
            "realizations": list(self.realizations[-8:]),
            "discourse": list(self.discourse[-8:]),
        }

    def recent_constructions(self) -> List[str]:
        """Последние использованные конструкции — для антиповтора."""

        return list(self.realizations[-8:])

    def note_construction(self, construction_id: str) -> None:
        """Запомнить выбранную конструкцию, не раздувая сейв."""

        construction_id = _text(construction_id)
        if not construction_id:
            return
        self.realizations.append(construction_id)
        if len(self.realizations) > 16:
            del self.realizations[: len(self.realizations) - 16]

    def recent_discourse(self) -> List[str]:
        """Последние использованные связки — отдельно от конструкций."""

        return list(self.discourse[-8:])

    def note_discourse(self, connective_id: str) -> None:
        """Запомнить связку дискурсивного слоя.

        Отдельный список, а не общий с конструкциями: иначе связки будут
        вытеснять антиповтор конструкций, и наоборот.
        """

        connective_id = _text(connective_id)
        if not connective_id:
            return
        self.discourse.append(connective_id)
        if len(self.discourse) > 16:
            del self.discourse[: len(self.discourse) - 16]

    def observe_clock(self, clock: int) -> None:
        clock = _integer(clock)
        if clock > self.clock:
            delta = clock - self.clock
            factor = _number(self.policy.get("decay_per_day"), 0.92) ** delta
            for collection in (
                self.entities.values(),
                self.facts.values(),
                self.summaries,
                self.common_ground.values(),
            ):
                for record in collection:
                    if not record.get("pinned"):
                        record["weight"] = (
                            _number(record.get("weight")) * factor
                        )
            self.clock = clock
            self.prune()

    def note_entity(
        self,
        identifier: str,
        name: str,
        type_name: str,
        gender: str,
        clock: int,
    ) -> None:
        identifier = _text(identifier)
        if not identifier:
            return
        gain = _number(self.policy.get("mention_gain"), 0.2)
        weights = _mapping(self.policy.get("weights"))
        initial = _number(weights.get("entity"), 1.0)
        pins = _mapping(self.policy.get("pins"))
        pinned_types = {str(item) for item in pins.get("types") or ()}
        record = self.entities.get(identifier)
        if record is None:
            self.entities[identifier] = {
                "id": identifier,
                "name": _text(name) or identifier,
                "type": _text(type_name),
                "gender": _text(gender),
                "weight": initial + gain,
                "mentions": 1,
                "first": clock,
                "last": clock,
                "pinned": _text(type_name) in pinned_types,
            }
            return
        record["weight"] = _number(record.get("weight")) + gain
        record["mentions"] = _integer(record.get("mentions")) + 1
        record["last"] = clock
        if name:
            record["name"] = _text(name)
        if type_name:
            record["type"] = _text(type_name)
        if gender:
            record["gender"] = _text(gender)
        if _text(type_name) in pinned_types:
            record["pinned"] = True

    def note_fact(
        self,
        relation: str,
        args: Iterable[Any],
        clock: int,
        known_entities: Optional[set] = None,
    ) -> None:
        relation = _text(relation)
        arguments = tuple(_text(item) for item in args)
        if not relation or not arguments:
            return
        significant = _mapping(self.policy.get("significant"))
        relations = {str(item) for item in significant.get("relations") or ()}
        if relation not in relations:
            return
        if len(arguments) < _integer(significant.get("min_args"), 2):
            return
        requires = significant.get("require_known_entity")
        if requires and known_entities is not None:
            if not any(item in known_entities for item in arguments):
                return
        key = relation + "|" + "|".join(arguments)
        gain = _number(self.policy.get("mention_gain"), 0.2)
        weights = _mapping(self.policy.get("weights"))
        initial = _number(weights.get("fact"), 1.0)
        record = self.facts.get(key)
        pinned_relations = _mapping(self.policy.get("pins"))
        pinned = relation in {
            str(item)
            for item in pinned_relations.get("relations") or ()
        }
        if record is None:
            self.facts[key] = {
                "key": key,
                "rel": relation,
                "args": arguments,
                "weight": initial + gain,
                "mentions": 1,
                "first": clock,
                "last": clock,
                "pinned": pinned,
            }
            return
        record["weight"] = _number(record.get("weight")) + gain
        record["mentions"] = _integer(record.get("mentions")) + 1
        record["last"] = clock
        if pinned:
            record["pinned"] = True

    def note_summary(
        self,
        text: str,
        entities: Iterable[str],
        clock: int,
    ) -> None:
        settings = _mapping(self.policy.get("summaries"))
        limit = max(1, _integer(settings.get("max_chars"), 240))
        body = _text(text)
        if not body:
            return
        if len(body) > limit:
            body = body[:limit].rstrip()
        identifiers = tuple(
            sorted({_text(item) for item in entities if _text(item)})
        )
        pinned = any(
            self.entities.get(item, {}).get("pinned") for item in identifiers
        )
        gain = _number(self.policy.get("mention_gain"), 0.2)
        weights = _mapping(self.policy.get("weights"))
        initial = _number(weights.get("summary"), 1.0)
        for record in self.summaries:
            if record.get("text") == body:
                record["weight"] = _number(record.get("weight")) + gain
                record["mentions"] = _integer(record.get("mentions")) + 1
                record["last"] = clock
                if pinned:
                    record["pinned"] = True
                return
        self.summaries.append(
            {
                "text": body,
                "entities": identifiers,
                "weight": initial + gain,
                "mentions": 1,
                "first": clock,
                "last": clock,
                "pinned": pinned,
            }
        )

    def note_common_ground(
        self,
        kind: str,
        relation: str,
        args: Iterable[Any],
        clock: int,
    ) -> None:
        relation = _text(relation)
        arguments = tuple(_text(item) for item in args)
        if not relation:
            return
        polarity = "no" if _text(kind) == "no" else "yes"
        key = "|".join((polarity, relation) + arguments)
        gain = _number(self.policy.get("mention_gain"), 0.2)
        initial = _number(
            _mapping(self.policy.get("weights")).get("common_ground"), 1.0
        )
        pinned_relations = _mapping(self.policy.get("pins"))
        pinned = relation in {
            str(item)
            for item in pinned_relations.get("relations") or ()
        }
        record = self.common_ground.get(key)
        if record is None:
            self.common_ground[key] = {
                "key": key,
                "polarity": polarity,
                "rel": relation,
                "args": arguments,
                "weight": initial + gain,
                "mentions": 1,
                "first": clock,
                "last": clock,
                "pinned": pinned,
            }
            return
        record["weight"] = _number(record.get("weight")) + gain
        record["mentions"] = _integer(record.get("mentions")) + 1
        record["last"] = clock
        if pinned:
            record["pinned"] = True

    def active_entities(self, limit: int) -> List[Dict[str, Any]]:
        records = sorted(
            self.entities.values(),
            key=lambda item: (
                -_number(item.get("weight")),
                -_integer(item.get("last")),
                str(item.get("id")),
            ),
        )
        return records[: max(0, limit)]

    def prune(self) -> None:
        minimum = _number(self.policy.get("min_weight"), 0.08)
        for collection in (
            self.entities,
            self.facts,
            self.common_ground,
        ):
            for key in list(collection):
                record = collection[key]
                if not record.get("pinned") and _number(
                    record.get("weight")
                ) < minimum:
                    del collection[key]
        self.summaries = [
            record
            for record in self.summaries
            if record.get("pinned")
            or _number(record.get("weight")) >= minimum
        ]
        limits = _mapping(self.policy.get("limits"))
        for name, collection in (
            ("entities", self.entities),
            ("facts", self.facts),
            ("common_ground", self.common_ground),
        ):
            limit = max(1, _integer(limits.get(name), 1))
            if len(collection) <= limit:
                continue
            keep = sorted(collection.values(), key=_record_sort_key)[:limit]
            collection.clear()
            for record in keep:
                collection[str(record.get("key") or record.get("id"))] = record
        limit = max(1, _integer(limits.get("summaries"), 1))
        if len(self.summaries) > limit:
            self.summaries = sorted(
                self.summaries, key=_record_sort_key
            )[:limit]


def _record_sort_key(record: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (
        0 if record.get("pinned") else 1,
        -_number(record.get("weight")),
        -_integer(record.get("last")),
        str(record.get("key") or record.get("id") or record.get("text")),
    )


def _entity_record(identifier: str, value: Any) -> Optional[Dict[str, Any]]:
    data = _mapping(value)
    if not data:
        return None
    return {
        "id": _text(data.get("id"), identifier),
        "name": _text(data.get("name"), identifier),
        "type": _text(data.get("type")),
        "gender": _text(data.get("gender")),
        "weight": _number(data.get("weight")),
        "mentions": max(0, _integer(data.get("mentions"))),
        "first": _integer(data.get("first")),
        "last": _integer(data.get("last")),
        "pinned": bool(data.get("pinned")),
    }


def _fact_record(key: str, value: Any) -> Optional[Dict[str, Any]]:
    data = _mapping(value)
    if not data:
        return None
    args = data.get("args") or ()
    if not isinstance(args, (list, tuple)):
        return None
    return {
        "key": _text(data.get("key"), key),
        "rel": _text(data.get("rel")),
        "args": tuple(_text(item) for item in args),
        "weight": _number(data.get("weight")),
        "mentions": max(0, _integer(data.get("mentions"))),
        "first": _integer(data.get("first")),
        "last": _integer(data.get("last")),
        "pinned": bool(data.get("pinned")),
    }


def _summary_record(value: Any) -> Optional[Dict[str, Any]]:
    data = _mapping(value)
    if not data or not _text(data.get("text")):
        return None
    entities = data.get("entities") or ()
    if not isinstance(entities, (list, tuple)):
        entities = ()
    return {
        "text": _text(data.get("text")),
        "entities": tuple(_text(item) for item in entities),
        "weight": _number(data.get("weight")),
        "mentions": max(0, _integer(data.get("mentions"))),
        "first": _integer(data.get("first")),
        "last": _integer(data.get("last")),
        "pinned": bool(data.get("pinned")),
    }


def _ground_record(key: str, value: Any) -> Optional[Dict[str, Any]]:
    data = _mapping(value)
    if not data:
        return None
    args = data.get("args") or ()
    if not isinstance(args, (list, tuple)):
        return None
    return {
        "key": _text(data.get("key"), key),
        "polarity": _text(data.get("polarity"), "yes"),
        "rel": _text(data.get("rel")),
        "args": tuple(_text(item) for item in args),
        "weight": _number(data.get("weight")),
        "mentions": max(0, _integer(data.get("mentions"))),
        "first": _integer(data.get("first")),
        "last": _integer(data.get("last")),
        "pinned": bool(data.get("pinned")),
    }


class ConversationState:
    """Текущий разговор: QUD, активные референты и общий фонд."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        entities: EntityIndex,
        morphology: Morphology,
        memory: Optional[DialogueMemory] = None,
        run_id: str = "campaign",
        clock: int = 0,
        social: Any = None,
    ):
        self.policy = policy
        self.entities = entities
        self.morphology = morphology
        self.memory = memory or DialogueMemory(
            policy, run_id=run_id, clock=clock
        )
        self.social = social
        self.clock = _integer(clock)
        self.turn = 0
        self.qud: List[Dict[str, Any]] = []
        self.referents: Dict[str, Dict[str, Any]] = {}
        self.last_sem: Optional[Any] = None
        self.last_answer: Dict[str, Any] = {}
        self.common_ground: Dict[str, Dict[str, Any]] = {}
        self.commitments: List[Dict[str, Any]] = []
        self._seed_from_memory()

    # --- жизненный цикл ---------------------------------------------

    def _seed_from_memory(self) -> None:
        referents = _mapping(self.policy.get("referents"))
        limit = max(0, _integer(referents.get("max_active"), 16))
        for record in self.memory.active_entities(limit):
            identifier = _text(record.get("id"))
            if not identifier:
                continue
            self.referents[identifier] = {
                "id": identifier,
                "name": _text(record.get("name"), identifier),
                "type": _text(record.get("type")),
                "gender": _text(record.get("gender")),
                "number": "sg",
                "salience": _number(record.get("weight")),
                "mentions": _integer(record.get("mentions")),
                "first": _integer(record.get("first")),
                "last": _integer(record.get("last")),
            }
        for key, record in self.memory.common_ground.items():
            self.common_ground[key] = dict(record)

    def begin_turn(self, clock: int) -> None:
        self.turn += 1
        self.clock = _integer(clock)
        self.memory.observe_clock(self.clock)
        decay = _number(
            _mapping(self.policy.get("referents")).get("decay_per_turn"), 0.82
        )
        minimum = _number(
            _mapping(self.policy.get("referents")).get("min_salience"), 0.04
        )
        for identifier in list(self.referents):
            record = self.referents[identifier]
            record["salience"] = _number(record.get("salience")) * decay
            if record["salience"] < minimum:
                del self.referents[identifier]

    # --- социальные эффекты -----------------------------------------

    def apply_effect(self, effect: Mapping[str, Any]) -> None:
        """Записать социальный эффект в состояние разговора.

        Эффекты типизированы: ``commitment``/``refusal``/``evasion``/
        ``counter_offer``/``clarification``. Добавление нового типа — это
        новая ветка здесь и запись в ``social.commitments.kinds``; новый
        акт с существующим эффектом сюда не доходит. Мир и BDI не
        меняются: только социальное состояние разговора.
        """

        if not isinstance(effect, Mapping):
            return
        kind = str(effect.get("type") or "")
        base = {
            "kind": kind,
            "subject": str(effect.get("subject") or ""),
            "object": str(effect.get("object") or ""),
            "turn": int(self.turn),
        }
        if kind in ("commitment", "refusal", "counter_offer"):
            if kind == "counter_offer":
                base["condition"] = str(effect.get("condition") or "")
            self.commitments.append(base)
            self._prune_commitments()
            return
        # evasion / clarification состояния не меняют

    def _prune_commitments(self) -> None:
        """Снять обязательства старше TTL из политики ``social.json``."""

        ttl = 0
        social = getattr(self, "social", None)
        if social is not None:
            try:
                ttl = int(
                    getattr(social, "commitments", {}).get("ttl_turns")
                    or 0
                )
            except (TypeError, ValueError):
                ttl = 0
        if ttl <= 0:
            return
        threshold = int(self.turn) - ttl
        self.commitments = [
            item for item in self.commitments
            if int(item.get("turn", 0)) > threshold
        ]

    def commitments_snapshot(self) -> Tuple[Mapping[str, Any], ...]:
        """Срез обязательств для отладки и тестов."""

        return tuple(dict(item) for item in self.commitments)

    # --- референты и местоимения ------------------------------------

    def _gender_of(self, identifier: str) -> str:
        referents = _mapping(self.policy.get("referents"))
        sources = [str(item) for item in referents.get("gender_sources") or ()]
        if "name" in sources:
            name = self.entities.name_of(identifier)
            gender = self.morphology.gender_of(name)
            if gender:
                return gender
        if "type_default" in sources:
            table = _mapping(referents.get("type_gender"))
            type_name = self.entities.type_of(identifier)
            if type_name in table:
                return str(table[type_name])
        return ""

    def note_entity(self, identifier: str, role: str = "") -> None:
        identifier = _text(identifier)
        if not identifier or self.entities.ignored(identifier):
            return
        if identifier in self.entities.pronoun_ids:
            return
        referents = _mapping(self.policy.get("referents"))
        weights = _mapping(referents.get("position_weights"))
        gain = _number(weights.get(role, weights.get("default", 1.0)), 1.0)
        record = self.referents.get(identifier)
        if record is None:
            record = {
                "id": identifier,
                "name": self.entities.name_of(identifier),
                "type": self.entities.type_of(identifier),
                "gender": self._gender_of(identifier),
                "number": "sg",
                "salience": gain,
                "mentions": 1,
                "first": self.turn,
                "last": self.turn,
            }
            self.referents[identifier] = record
        else:
            record["salience"] = _number(record.get("salience")) + gain
            record["mentions"] = _integer(record.get("mentions")) + 1
            record["last"] = self.turn
        limit = max(0, _integer(referents.get("max_active"), 16))
        if len(self.referents) > limit:
            keep = sorted(
                self.referents.values(),
                key=lambda item: (
                    -_number(item.get("salience")),
                    -_integer(item.get("last")),
                    str(item.get("id")),
                ),
            )[:limit]
            self.referents = {str(item["id"]): item for item in keep}

    def observe_sem(self, sem: Any) -> List[str]:
        found: List[str] = []
        self._walk_sem(sem, "", found)
        return found

    def _walk_sem(self, value: Any, role: str, found: List[str]) -> None:
        if isinstance(value, Mapping):
            kind = value.get("kind")
            if kind == "entity":
                identifier = _text(value.get("id"))
                if identifier:
                    if not self.entities.ignored(identifier):
                        found.append(identifier)
                        self.note_entity(identifier, role)
                return
            if kind == "pronoun":
                return
            if "entity" in value and len(value) == 1:
                identifier = _text(value.get("entity"))
                if identifier:
                    if not self.entities.ignored(identifier):
                        found.append(identifier)
                        self.note_entity(identifier, role)
                return
            weights = _mapping(
                _mapping(self.policy.get("referents")).get("position_weights")
            )
            for key, item in value.items():
                next_role = str(key) if str(key) in weights else role
                self._walk_sem(item, next_role, found)
            return
        if isinstance(value, list):
            for item in value:
                self._walk_sem(item, role, found)

    def resolve_pronoun(self, pronoun: str) -> str:
        spec = _mapping(_mapping(self.policy.get("pronouns")).get(pronoun))
        if not spec or not spec.get("resolvable", False):
            return ""
        referents = _mapping(self.policy.get("referents"))
        strict_gender = bool(referents.get("strict_gender", True))
        strict_number = bool(referents.get("strict_number", False))
        gender = _text(spec.get("gender"))
        number = _text(spec.get("number"))
        candidates = []
        for record in self.referents.values():
            if strict_gender and gender and record.get("gender") != gender:
                continue
            if strict_number and number and record.get("number") != number:
                continue
            candidates.append(record)
        if not candidates:
            return ""
        candidates.sort(
            key=lambda item: (
                -_number(item.get("salience")),
                -_integer(item.get("last")),
                str(item.get("id")),
            )
        )
        return _text(candidates[0].get("id"))

    def resolve_pronouns(self, sem: Any) -> Tuple[Any, List[str]]:
        unresolved: List[str] = []
        return self._resolve_node(sem, unresolved), unresolved

    def _resolve_node(self, value: Any, unresolved: List[str]) -> Any:
        pronouns = _mapping(self.policy.get("pronouns"))
        if isinstance(value, Mapping):
            kind = value.get("kind")
            if kind == "pronoun":
                identifier = _text(value.get("id"))
                entity = self.resolve_pronoun(identifier)
                if entity:
                    return {"kind": "np", "head": {"entity": entity}}
                if _mapping(pronouns.get(identifier)).get("resolvable", False):
                    unresolved.append(identifier)
                return dict(value)
            if kind == "np":
                head = value.get("head")
                if isinstance(head, str) and head in pronouns:
                    entity = self.resolve_pronoun(head)
                    if entity:
                        result = dict(value)
                        result["head"] = {"entity": entity}
                        return result
                    if _mapping(pronouns.get(head)).get("resolvable", False):
                        unresolved.append(head)
                return {
                    str(key): self._resolve_node(item, unresolved)
                    for key, item in value.items()
                }
            return {
                str(key): self._resolve_node(item, unresolved)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._resolve_node(item, unresolved) for item in value]
        if isinstance(value, str) and value in pronouns:
            entity = self.resolve_pronoun(value)
            if entity:
                return {"kind": "np", "head": {"entity": entity}}
            if _mapping(pronouns.get(value)).get("resolvable", False):
                unresolved.append(value)
        return value

    # --- эллипсис ----------------------------------------------------

    def fragment(self, text: str) -> Tuple[Optional[Any], str, str]:
        tokens = _normalized_tokens(text)
        if not tokens:
            return None, "", "no_match"
        for spec in self.policy.get("fragments") or ():
            data = _mapping(spec)
            if not data:
                continue
            pattern = data.get("tokens") or ()
            captures = self._match_fragment(pattern, tokens)
            if captures is None:
                continue
            result, reason = self._build_fragment(data, captures)
            if result is None:
                return None, str(data.get("id") or ""), reason
            return result, str(data.get("id") or ""), ""
        return None, "", "no_match"

    def _match_fragment(
        self, pattern: Sequence[Any], tokens: Sequence[str]
    ) -> Optional[Dict[str, str]]:
        def walk(
            pattern_index: int,
            token_index: int,
            captures: Dict[str, str],
        ):
            if pattern_index >= len(pattern):
                return captures if token_index == len(tokens) else None
            spec = pattern[pattern_index]
            if isinstance(spec, str):
                if token_index < len(tokens) and tokens[token_index] == spec:
                    return walk(pattern_index + 1, token_index + 1, captures)
                return None
            data = _mapping(spec)
            if not data:
                return None
            if "any" in data:
                if (
                    token_index < len(tokens)
                    and tokens[token_index] in {
                        str(item) for item in data.get("any") or ()
                    }
                ):
                    return walk(pattern_index + 1, token_index + 1, captures)
                return None
            slot = _text(data.get("slot"))
            kind = _text(data.get("kind"), "entity")
            resolved = self.entities.resolve(tokens, token_index, kind)
            if resolved is None:
                return None
            identifier, span = resolved
            next_captures = dict(captures)
            next_captures[slot] = identifier
            return walk(
                pattern_index + 1, token_index + span, next_captures
            )

        return walk(0, 0, {})

    def _build_fragment(
        self, spec: Mapping[str, Any], captures: Mapping[str, str]
    ) -> Tuple[Optional[Any], str]:
        describe = spec.get("describe")
        if describe:
            entity = self._capture(str(describe), captures)
            if not entity:
                return None, "no_referent"
            return _describe_sem(entity), ""
        base = self._base_sem()
        if base is None:
            return None, "no_qud"
        edited = copy.deepcopy(base)
        for edit in spec.get("edits") or ():
            data = _mapping(edit)
            value = self._edit_value(data.get("value"), captures)
            if value is None:
                return None, "no_entity"
            paths = data.get("paths")
            if isinstance(paths, (list, tuple)) and paths:
                candidates = [str(item) for item in paths]
            else:
                candidates = [str(data.get("path") or "")]
            path = ""
            for candidate in candidates:
                if _path_exists(edited, candidate):
                    path = candidate
                    break
            if not path:
                path = candidates[0]
            _path_set(edited, path, value)
        if isinstance(edited, Mapping) and edited.get("kind") == "assert":
            wh = edited.get("wh") or "yesno"
            body = {key: item for key, item in edited.items() if key != "wh"}
            body["kind"] = "assert"
            return {"kind": "question", "wh": wh, "body": body}, ""
        return edited, ""

    def _base_sem(self) -> Optional[Any]:
        qud = _mapping(self.policy.get("qud"))
        order = [
            str(item)
            for item in qud.get("base_order") or ()
        ] or ["qud", "last_sem"]
        for name in order:
            if name == "qud" and self.qud:
                return self.qud[-1].get("sem")
            if name == "last_sem" and self.last_sem is not None:
                return self.last_sem
        return None

    def _capture(self, value: str, captures: Mapping[str, str]) -> str:
        if value.startswith("$"):
            captured = _text(captures.get(value[1:]))
            if captured in self.entities.pronoun_ids:
                return self.resolve_pronoun(captured)
            return captured
        return value

    def _edit_value(
        self, value: Any, captures: Mapping[str, str]
    ) -> Optional[Any]:
        if isinstance(value, str):
            if value.startswith("$"):
                found = _text(captures.get(value[1:]))
                return found or None
            return value
        return value

    # --- QUD, ответы и память ---------------------------------------

    def apply_question_intent(self, sem: Any, text: str) -> Any:
        settings = _mapping(self.policy.get("question_intent"))
        if not isinstance(sem, Mapping):
            return sem
        if sem.get("kind") not in {
            str(item) for item in settings.get("wrap_kinds") or ()
        }:
            return sem
        marks = tuple(str(item) for item in settings.get("marks") or ())
        if not marks or not str(text or "").rstrip().endswith(marks):
            return sem
        body = {key: item for key, item in sem.items() if key != "wh"}
        return {"kind": "question", "wh": "yesno", "body": body}

    def push_turn(self, sem: Any, answer: Any) -> None:
        if sem is not None:
            self.last_sem = copy.deepcopy(sem)
        self.last_answer = {
            "kind": _text(getattr(answer, "kind", "")),
            "plan_id": _text(getattr(answer, "plan_id", "")),
        }
        if isinstance(sem, Mapping) and sem.get("kind") == "question":
            self.qud.append(
                {
                    "turn": self.turn,
                    "wh": _text(sem.get("wh")),
                    "sem": copy.deepcopy(sem),
                    "answer_kind": self.last_answer["kind"],
                    "plan_id": self.last_answer["plan_id"],
                }
            )
            qud = _mapping(self.policy.get("qud"))
            limit = max(1, _integer(qud.get("max_size"), 16))
            if len(self.qud) > limit:
                self.qud = self.qud[-limit:]

    def remember(
        self,
        sem: Any,
        answer: Any,
        mentioned: Optional[Iterable[str]] = None,
    ) -> None:
        kind = _text(getattr(answer, "kind", ""))
        if not kind or kind in ("unknown", "clarification"):
            return
        if mentioned is None:
            mentioned = self.observe_sem(sem)
        else:
            mentioned = list(mentioned)
        data = _mapping(getattr(answer, "data", {}))
        answer_entities = self._answer_entities(data)
        for identifier in answer_entities:
            self.note_entity(identifier, "target")
            if identifier not in mentioned:
                mentioned.append(identifier)
        for identifier in self._relation_entities(data):
            if identifier not in mentioned:
                mentioned.append(identifier)
        for identifier in mentioned:
            self.memory.note_entity(
                identifier,
                self.entities.name_of(identifier),
                self.entities.type_of(identifier),
                self._gender_of(identifier),
                self.clock,
            )
        known = set(self.entities.known)
        relation = _text(data.get("relation"))
        args = data.get("args") or ()
        if relation and isinstance(args, (list, tuple)):
            self.memory.note_fact(relation, args, self.clock, known)
            ground = _mapping(self.policy.get("common_ground"))
            if kind in {
                str(item) for item in ground.get("kinds") or ()
            }:
                self.memory.note_common_ground(
                    kind, relation, args, self.clock
                )
                self._mirror_ground(kind, relation, args)
        settings = _mapping(
            _mapping(self.policy.get("memory")).get("summaries")
        )
        if kind in {str(item) for item in settings.get("kinds") or ()}:
            self.memory.note_summary(
                _text(getattr(answer, "text", "")),
                mentioned,
                self.clock,
            )
        self.memory.turns += 1
        self.memory.prune()

    def _answer_entities(self, data: Mapping[str, Any]) -> List[str]:
        found: List[str] = []
        resolution = _mapping(self.policy.get("entity_resolution"))
        prefixes = [
            str(item) for item in resolution.get("answer_value_prefixes") or ()
        ]
        known = self.entities.known

        def add(value: str) -> None:
            value = _text(value)
            if not value:
                return
            identifier = ""
            if value in known:
                identifier = value
            elif self.entities.ignored(value) and value not in known:
                identifier = ""
            else:
                for prefix in prefixes:
                    candidate = prefix + value
                    if candidate in known:
                        identifier = candidate
                        break
            if not identifier:
                identifier = self.entities.by_name_text(value)
            if identifier and self.entities.ignored(identifier):
                identifier = ""
            if identifier and identifier not in found:
                found.append(identifier)

        def walk(value: Any) -> None:
            if isinstance(value, str):
                add(value)
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)
                return
            if isinstance(value, Mapping):
                for item in value.values():
                    walk(item)

        walk(data)
        return found

    def _relation_entities(self, data: Mapping[str, Any]) -> List[str]:
        found: List[str] = []
        args = data.get("args") or ()
        if not isinstance(args, (list, tuple)):
            return found
        for item in args:
            identifier = _text(item)
            if identifier in self.entities.known and identifier not in found:
                found.append(identifier)
        return found

    def _mirror_ground(
        self, kind: str, relation: str, args: Iterable[Any]
    ) -> None:
        record = self.memory.common_ground
        key = None
        for candidate, item in record.items():
            if (
                item.get("rel") == relation
                and tuple(item.get("args") or ())
                == tuple(_text(arg) for arg in args)
            ):
                key = candidate
                break
        if key is None:
            return
        self.common_ground[key] = dict(record[key])
        limit = max(
            1,
            _integer(
                _mapping(self.policy.get("common_ground")).get("max_items"),
                96,
            ),
        )
        if len(self.common_ground) > limit:
            keep = sorted(
                self.common_ground.values(), key=_record_sort_key
            )[:limit]
            self.common_ground = {str(item["key"]): item for item in keep}


class DialogueMemoryStore:
    """Память по агентам в рамках одной партии.

    Каждый собеседник имеет собственный след разговора: один агент не
    должен помнить то, что игрок сказал другому. Хранилище целиком лежит
    в сейве партии, поэтому новая игра начинается с пустой памяти.
    """

    SCHEMA = 1

    def __init__(
        self,
        policy: Mapping[str, Any],
        data: Any = None,
    ):
        self.policy = policy
        self.agents: Dict[str, DialogueMemory] = {}
        raw = _mapping(data)
        for agent_id, item in _mapping(raw.get("agents")).items():
            self.agents[str(agent_id)] = DialogueMemory.from_dict(policy, item)

    @classmethod
    def from_dict(
        cls, policy: Mapping[str, Any], data: Any
    ) -> "DialogueMemoryStore":
        return cls(policy, data)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "agents": {
                key: memory.to_dict()
                for key, memory in sorted(self.agents.items())
            },
        }

    def memory(
        self,
        agent_id: str,
        run_id: str = "",
        clock: int = 0,
    ) -> DialogueMemory:
        key = _text(agent_id) or "agent"
        memory = self.agents.get(key)
        if memory is None or (run_id and memory.run_id != run_id):
            memory = DialogueMemory(self.policy, run_id=run_id, clock=clock)
            self.agents[key] = memory
        memory.observe_clock(clock)
        return memory


def build_state(
    catalog: Any,
    knowledge: Any,
    memory: Optional[DialogueMemory] = None,
    morphology: Optional[Morphology] = None,
) -> ConversationState:
    """Собрать состояние разговора из каталога и снимка знания."""

    policy = _mapping(getattr(catalog, "state", {}))
    synthesis = _mapping(getattr(catalog, "synthesis", {}))
    if not isinstance(morphology, Morphology):
        morphology = Morphology(synthesis)
    index = EntityIndex(catalog, knowledge, policy)
    return ConversationState(
        policy,
        index,
        morphology,
        memory=memory,
        run_id=_text(getattr(knowledge, "run_id", "")) or "campaign",
        clock=_integer(getattr(knowledge, "clock", 0)),
        social=getattr(catalog, "social", None),
    )