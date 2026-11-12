"""Загрузка диалоговых данных из JSON.

Код не знает содержания: он читает онтологию, лексикон и грамматику,
проверяет базовые контракты и отдаёт неизменяемый каталог.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from .errors import DialogueError
from .model import (
    DialogueCatalog,
    Grammar,
    GrammarRule,
    LexEntry,
    LexForm,
    Ontology,
    RuleItem,
)

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "configs" / "dialogue"

CASES = ("nom", "gen", "dat", "acc", "ins", "prep")


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


def load_dialogue(directory: Path | str | None = None) -> DialogueCatalog:
    """Загрузить онтологию, лексикон и грамматику из каталога."""

    root = Path(directory) if directory is not None else DEFAULT_DIR
    ontology = load_ontology(root / "ontology.json")
    lexicon = load_lexicon(root / "lexicon.json")
    grammar = load_grammar(root / "grammar.json")
    raw = {
        "directory": str(root),
        "ontology": ontology.raw,
        "lexicon": {"count": len(lexicon)},
        "grammar": {
            "start": grammar.start,
            "rules": len(grammar.rules),
        },
    }
    return DialogueCatalog(
        ontology=ontology,
        lexicon=lexicon,
        grammar=grammar,
        raw=raw,
    )
