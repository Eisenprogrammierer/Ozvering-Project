"""Загрузка и проверка конфигов имён.

Конфиги лежат в ``configs/naming``:
``lexicon.json`` — морфология слов; ``classes/*.json`` — классы автоматов;
``interactions/*.json`` — семантические типы взаимодействий.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
from typing import Dict, List, Mapping

from .morphology import Adjective, Noun, Phrase, load_word


POOL_KEYS = (
    "heads", "adjectives", "dependents", "dependent_adjectives", "extensions",
)
REQUIRED_QUINTUPLE = (
    "recipient_input", "sender_output", "handlers", "states",
    "surrounding_influence",
)


class NamingError(ValueError):
    """Ошибка конфигурации имён."""


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise NamingError("конфиг не найден: %s" % path)
    except Exception as exc:
        raise NamingError("не удалось прочитать %s: %s" % (path, exc))


def _as_list(value, label):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise NamingError("%s должен быть списком" % label)
    return [str(item) for item in value if str(item or "").strip()]


def _pool(data, label):
    data = data or {}
    if not isinstance(data, Mapping):
        raise NamingError("%s должен быть объектом" % label)
    return {key: _as_list(data.get(key), "%s.%s" % (label, key))
            for key in POOL_KEYS}


def _merge_pool(*pools):
    result = {key: [] for key in POOL_KEYS}
    seen = {key: set() for key in POOL_KEYS}
    for pool in pools:
        for key in POOL_KEYS:
            for value in (pool or {}).get(key, []):
                if value not in seen[key]:
                    seen[key].add(value)
                    result[key].append(value)
    return result


def _descriptor(value, label, allowed_kinds=None):
    """Проверить один элемент онтологии или пятёрки."""
    if not isinstance(value, Mapping):
        raise NamingError("%s должен быть объектом" % label)
    if not str(value.get("label") or "").strip():
        raise NamingError("%s: пустой label" % label)
    kind = str(value.get("kind") or "").strip()
    if not kind:
        raise NamingError("%s: пустой kind" % label)
    if allowed_kinds is not None and kind not in allowed_kinds:
        raise NamingError("%s: недопустимый kind %r" % (label, kind))
    keywords = value.get("keywords")
    if not isinstance(keywords, (list, tuple)) or not keywords:
        raise NamingError("%s: пустые keywords" % label)
    return value


@dataclass(frozen=True)
class Pool:
    """Набор ссылок на словарь для одного класса/темы/уровня."""

    heads: List[str] = field(default_factory=list)
    adjectives: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    dependent_adjectives: List[str] = field(default_factory=list)
    extensions: List[str] = field(default_factory=list)

    @classmethod
    def from_data(cls, data, label="pool"):
        raw = _pool(data, label)
        return cls(**raw)

    def merged(self, other):
        raw = _merge_pool(self.as_dict(), other.as_dict() if other else {})
        return Pool(**raw)

    def as_dict(self):
        return {key: list(getattr(self, key)) for key in POOL_KEYS}

    def validate(self, lexicon, label):
        for word_id in self.heads + self.dependents:
            word = lexicon.get(word_id)
            if not isinstance(word, Noun):
                raise NamingError("%s: %s не существительное" % (label, word_id))
        for word_id in self.adjectives + self.dependent_adjectives:
            word = lexicon.get(word_id)
            if not isinstance(word, Adjective):
                raise NamingError("%s: %s не прилагательное" % (label, word_id))
        for word_id in self.extensions:
            word = lexicon.get(word_id)
            if not isinstance(word, Phrase):
                raise NamingError("%s: %s не готовая фраза" % (label, word_id))


@dataclass(frozen=True)
class ClassProfile:
    id: str
    label: str
    description: str
    default_theme: str
    need_themes: Dict[str, str]
    base: Pool
    themes: Dict[str, Pool]
    levels: Dict[str, Pool]
    ontology: Dict

    @classmethod
    def from_data(cls, data, source="class"):
        class_id = str(data.get("class") or "").strip()
        if not class_id:
            raise NamingError("%s: пустой class" % source)
        base = Pool.from_data(data.get("base"), "%s.base" % class_id)
        themes_raw = data.get("themes") or {}
        if not isinstance(themes_raw, Mapping):
            raise NamingError("%s.themes должен быть объектом" % class_id)
        themes = {
            str(name): Pool.from_data(value, "%s.themes.%s" % (class_id, name))
            for name, value in themes_raw.items()
        }
        levels_raw = data.get("levels") or {}
        if not isinstance(levels_raw, Mapping):
            raise NamingError("%s.levels должен быть объектом" % class_id)
        levels = {
            str(name): Pool.from_data(value, "%s.levels.%s" % (class_id, name))
            for name, value in levels_raw.items()
        }
        need_themes = data.get("need_themes") or {}
        if not isinstance(need_themes, Mapping):
            raise NamingError("%s.need_themes должен быть объектом" % class_id)
        default_theme = str(data.get("default_theme") or
                            next(iter(themes), "default"))
        ontology = data.get("ontology") or {}
        if not isinstance(ontology, Mapping):
            raise NamingError("%s.ontology должен быть объектом" % class_id)
        profile = cls(
            id=class_id,
            label=str(data.get("label") or class_id),
            description=str(data.get("description") or ""),
            default_theme=default_theme,
            need_themes={str(key): str(value)
                         for key, value in need_themes.items()},
            base=base,
            themes=themes,
            levels=levels,
            ontology=dict(ontology),
        )
        profile.validate()
        return profile

    def validate(self):
        if self.default_theme not in self.themes and self.themes:
            raise NamingError("%s: default_theme %r отсутствует в themes"
                              % (self.id, self.default_theme))
        for need, theme in self.need_themes.items():
            if theme not in self.themes:
                raise NamingError("%s: need %s ссылается на тему %r"
                                  % (self.id, need, theme))
        for key in ("1", "2", "3"):
            if key not in self.levels:
                raise NamingError("%s: нет уровня %s" % (self.id, key))
        if not (self.base.heads or any(theme.heads for theme in
                                       self.themes.values())):
            raise NamingError("%s: нет ни одного head" % self.id)
        self.validate_ontology()

    def theme_for(self, need=None, theme=None):
        if theme and theme in self.themes:
            return theme
        selected = self.need_themes.get(need or "")
        if selected in self.themes:
            return selected
        if self.default_theme in self.themes:
            return self.default_theme
        return next(iter(self.themes), "default")

    def pool_for(self, need=None, level=1, theme=None):
        selected = self.theme_for(need=need, theme=theme)
        level_key = str(min(3, max(1, int(level or 1))))
        parts = [self.base]
        if selected in self.themes:
            parts.append(self.themes[selected])
        if level_key in self.levels:
            parts.append(self.levels[level_key])
        merged = _merge_pool(*(part.as_dict() for part in parts))
        theme = self.themes.get(selected)
        level_pool = self.levels.get(level_key)
        # Тема и уровень задают ядро названия; широкая base остаётся
        # разделяемым слоем для расширений и редких fallback-слов. Иначе
        # соседние темы дают противоречия вроде «древняя молодая улица».
        primary = _merge_pool(
            theme.as_dict() if theme else {},
            level_pool.as_dict() if level_pool else {},
        )
        merged["primary_heads"] = list(theme.heads) if theme else []
        for key in ("adjectives", "dependents", "dependent_adjectives"):
            merged["primary_" + key] = list(primary[key])
        return merged, selected

    def validate_ontology(self):
        for key in ("inputs", "outputs", "states", "handlers",
                    "surrounding"):
            items = self.ontology.get(key)
            if not isinstance(items, (list, tuple)) or not items:
                raise NamingError("%s.ontology.%s должен быть непустым списком"
                                  % (self.id, key))
            for index, value in enumerate(items):
                allowed = (("nested_automaton", "scheme")
                           if key == "handlers" else None)
                _descriptor(value, "%s.ontology.%s[%d]"
                            % (self.id, key, index), allowed)

    def validate_lexicon(self, lexicon):
        for label, pool in [("base", self.base)] + [
                ("theme.%s" % key, value) for key, value in self.themes.items()
        ] + [
                ("level.%s" % key, value) for key, value in self.levels.items()
        ]:
            pool.validate(lexicon, "%s.%s" % (self.id, label))


@dataclass(frozen=True)
class InteractionType:
    id: str
    label: str
    description: str
    quintuple: Dict
    naming: Pool

    @classmethod
    def from_data(cls, data, source="interaction"):
        type_id = str(data.get("type") or "").strip()
        if not type_id:
            raise NamingError("%s: пустой type" % source)
        quintuple = data.get("quintuple") or {}
        if not isinstance(quintuple, Mapping):
            raise NamingError("%s.quintuple должен быть объектом" % type_id)
        missing = [key for key in REQUIRED_QUINTUPLE if key not in quintuple]
        if missing:
            raise NamingError("%s: в пятёрке нет %s"
                              % (type_id, ", ".join(missing)))
        _descriptor(quintuple.get("recipient_input"),
                    "%s.recipient_input" % type_id)
        _descriptor(quintuple.get("sender_output"),
                    "%s.sender_output" % type_id)
        handlers = quintuple.get("handlers") or {}
        if not isinstance(handlers, Mapping):
            raise NamingError("%s.handlers должен быть объектом" % type_id)
        states = quintuple.get("states") or {}
        if not isinstance(states, Mapping):
            raise NamingError("%s.states должен быть объектом" % type_id)
        for side in ("sender", "recipient"):
            if side not in handlers:
                raise NamingError("%s.handlers: нет %s" % (type_id, side))
            side_handlers = handlers[side]
            if not isinstance(side_handlers, (list, tuple)) or not side_handlers:
                raise NamingError("%s.handlers.%s должен быть непустым списком"
                                  % (type_id, side))
            for index, value in enumerate(side_handlers):
                _descriptor(value, "%s.handlers.%s[%d]"
                            % (type_id, side, index),
                            ("nested_automaton", "scheme"))
            if side not in states:
                raise NamingError("%s.states: нет %s" % (type_id, side))
            side_states = states[side]
            if not isinstance(side_states, (list, tuple)) or not side_states:
                raise NamingError("%s.states.%s должен быть непустым списком"
                                  % (type_id, side))
            for index, value in enumerate(side_states):
                _descriptor(value, "%s.states.%s[%d]"
                            % (type_id, side, index))
        influence = quintuple.get("surrounding_influence") or {}
        if not isinstance(influence, Mapping):
            raise NamingError("%s.surrounding_influence должен быть объектом"
                              % type_id)
        sources = influence.get("sources")
        if not isinstance(sources, (list, tuple)) or not sources:
            raise NamingError("%s.surrounding_influence.sources должен быть "
                              "непустым списком" % type_id)
        for index, value in enumerate(sources):
            _descriptor(value, "%s.surrounding_influence.sources[%d]"
                        % (type_id, index))
        naming = Pool.from_data(data.get("naming"), "%s.naming" % type_id)
        if not naming.heads:
            raise NamingError("%s.naming.heads пуст" % type_id)
        return cls(
            id=type_id,
            label=str(data.get("label") or type_id),
            description=str(data.get("description") or ""),
            quintuple=dict(quintuple),
            naming=naming,
        )

    def validate_lexicon(self, lexicon):
        self.naming.validate(lexicon, "%s.naming" % self.id)


class NamingCatalog:
    """Лексикон + классы автоматов + типы взаимодействий."""

    def __init__(self, lexicon, classes, interactions, root=None):
        self.lexicon = dict(lexicon)
        self.classes = dict(classes)
        self.interactions = dict(interactions)
        self.root = Path(root) if root is not None else None

    @classmethod
    def load(cls, root=None):
        root = Path(root) if root is not None else default_root()
        lexicon_path = root / "lexicon.json"
        if not lexicon_path.is_file():
            raise NamingError("нет лексикона: %s" % lexicon_path)
        raw_lexicon = _read_json(lexicon_path)
        words = {}
        for word_id, data in (raw_lexicon.get("words") or {}).items():
            words[str(word_id)] = load_word(str(word_id), data)
        class_dir = root / "classes"
        classes = {}
        for path in sorted(class_dir.glob("*.json")):
            profile = ClassProfile.from_data(_read_json(path), path.name)
            if profile.id in classes:
                raise NamingError("дублируется класс %s" % profile.id)
            classes[profile.id] = profile
        interaction_dir = root / "interactions"
        interactions = {}
        for path in sorted(interaction_dir.glob("*.json")):
            item = InteractionType.from_data(_read_json(path), path.name)
            if item.id in interactions:
                raise NamingError("дублируется тип взаимодействия %s"
                                  % item.id)
            interactions[item.id] = item
        if not classes:
            raise NamingError("в %s нет классов автоматов" % class_dir)
        catalog = cls(words, classes, interactions, root=root)
        catalog.validate()
        return catalog

    @classmethod
    def from_data(cls, lexicon, classes, interactions):
        catalog = cls(lexicon, classes, interactions)
        catalog.validate()
        return catalog

    def validate(self):
        for word_id, word in self.lexicon.items():
            if not getattr(word, "id", None):
                raise NamingError("слово %s без id" % word_id)
        for profile in self.classes.values():
            profile.validate_lexicon(self.lexicon)
            for need, theme in profile.need_themes.items():
                if theme not in profile.themes:
                    raise NamingError("%s: тема %s не определена"
                                      % (profile.id, theme))
        for interaction in self.interactions.values():
            interaction.validate_lexicon(self.lexicon)
        return self

    def word(self, word_id):
        if word_id not in self.lexicon:
            raise NamingError("нет слова %r" % (word_id,))
        return self.lexicon[word_id]

    def words(self, ids):
        return [self.word(word_id) for word_id in ids]

    def class_ids(self):
        return sorted(self.classes)

    def interaction_ids(self):
        return sorted(self.interactions)

    def class_profile(self, class_id):
        if class_id not in self.classes:
            raise NamingError("нет класса %r" % (class_id,))
        return self.classes[class_id]

    def interaction(self, type_id):
        if type_id not in self.interactions:
            raise NamingError("нет типа взаимодействия %r" % (type_id,))
        return self.interactions[type_id]

    def pool_for(self, class_id, need=None, level=1, theme=None):
        raw, selected = self.class_profile(class_id).pool_for(
            need=need, level=level, theme=theme)
        pool = {key: self.words(raw[key]) for key in POOL_KEYS}
        for key in ("heads", "adjectives", "dependents",
                    "dependent_adjectives"):
            pool["primary_" + key] = self.words(
                raw.get("primary_" + key, []))
        return pool, selected

    def interaction_pool(self, type_id):
        item = self.interaction(type_id)
        return {key: self.words(getattr(item.naming, key))
                for key in POOL_KEYS}

    def ontology_for(self, class_id):
        return self.class_profile(class_id).ontology

    def interactions_with_quintuple(self):
        return [self.interactions[key] for key in self.interaction_ids()]


def default_root():
    return Path(__file__).resolve().parents[1] / "configs" / "naming"


@lru_cache(maxsize=1)
def default_catalog():
    return NamingCatalog.load()


__all__ = [
    "POOL_KEYS", "REQUIRED_QUINTUPLE", "NamingError", "Pool",
    "ClassProfile", "InteractionType", "NamingCatalog", "default_root",
    "default_catalog",
]
