"""Генератор имён персонажей: реальные культуры и фэнтезийные темы.

Конфиг лежит в ``configs/naming/people.json``. В отличие от генератора
названий автоматов, этот слой не пытается строить морфологию: имена — это
собственные имена, а не русские нарицательные конструкции. Шаблоны текста
используют имя в именительном падеже, поэтому генератору достаточно вернуть
готовую строку.

Слой чистый: он не импортирует pygame, ``simulation`` или ``warfare``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import random
import re
from typing import Dict, List, Mapping, Optional, Tuple


_GENDER_KEYS = ("m", "f")
_GENDER_ALIASES = {
    "m": "m", "male": "m", "man": "m", "м": "m", "муж": "m",
    "f": "f", "female": "f", "woman": "f", "ж": "f", "жен": "f",
}
_SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class PeopleError(ValueError):
    """Ошибка конфига или запроса генератора имён."""


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise PeopleError("конфиг не найден: %s" % path)
    except Exception as exc:
        raise PeopleError("не удалось прочитать %s: %s" % (path, exc))


def _as_list(value, label):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise PeopleError("%s должен быть списком" % label)
    return [str(item).strip() for item in value if str(item).strip()]


def _pool(value, label):
    """Пул имён: либо список для обоих полов, либо объект ``m``/``f``."""
    if value is None:
        return {key: [] for key in _GENDER_KEYS}
    if isinstance(value, (list, tuple)):
        names = _as_list(value, label)
        return {key: list(names) for key in _GENDER_KEYS}
    if not isinstance(value, Mapping):
        raise PeopleError("%s должен быть списком или объектом" % label)
    result = {}
    for key in _GENDER_KEYS:
        result[key] = _as_list(value.get(key), "%s.%s" % (label, key))
    unknown = sorted(set(value) - set(_GENDER_KEYS))
    if unknown:
        raise PeopleError("%s: неизвестные полы %s" % (label, ", ".join(unknown)))
    return result


def _normalize_gender(value):
    if value is None:
        return None
    key = str(value).strip().lower()
    if key in ("any", "random", "любой", "любая"):
        return None
    if key not in _GENDER_ALIASES:
        raise PeopleError("неизвестный пол: %r" % (value,))
    return _GENDER_ALIASES[key]


def _as_text(value, label):
    text = str(value or "").strip()
    if not text:
        raise PeopleError("%s: пустое значение" % label)
    return text


@dataclass(frozen=True)
class PersonCulture:
    """Культура или фэнтезийная тема с пулами имён и шаблонами."""

    id: str
    label: str
    style: str
    given: Dict[str, List[str]]
    family: Dict[str, List[str]]
    epithets: List[str] = field(default_factory=list)
    patterns: Tuple[str, ...] = ("{given} {family}",)
    description: str = ""

    @classmethod
    def from_data(cls, item_id, data, style, source="people"):
        if not isinstance(data, Mapping):
            raise PeopleError("%s.%s должен быть объектом" % (source, item_id))
        given = _pool(data.get("given"), "%s.%s.given" % (source, item_id))
        family = _pool(data.get("family"), "%s.%s.family" % (source, item_id))
        if not any(given.values()):
            raise PeopleError("%s.%s: нет имён" % (source, item_id))
        patterns = _as_list(data.get("patterns"),
                            "%s.%s.patterns" % (source, item_id))
        if not patterns:
            patterns = ["{given} {family}"]
        for pattern in patterns:
            if "{given}" not in pattern:
                raise PeopleError(
                    "%s.%s: шаблон %r не содержит {given}"
                    % (source, item_id, pattern))
            if "{family}" in pattern and not any(family.values()):
                raise PeopleError(
                    "%s.%s: шаблону %r нужна фамилия"
                    % (source, item_id, pattern))
        profile = cls(
            id=_as_text(item_id, source),
            label=str(data.get("label") or item_id),
            style=style,
            given=given,
            family=family,
            epithets=_as_list(data.get("epithets"),
                              "%s.%s.epithets" % (source, item_id)),
            patterns=tuple(patterns),
            description=str(data.get("description") or ""),
        )
        return profile

    def given_for(self, gender):
        if gender in self.given and self.given[gender]:
            return self.given[gender]
        merged = self.given.get("m", []) + self.given.get("f", [])
        if not merged:
            raise PeopleError("%s: нет имён для пола %s" % (self.id, gender))
        return merged

    def family_for(self, gender):
        if gender in self.family and self.family[gender]:
            return self.family[gender]
        merged = self.family.get("m", []) + self.family.get("f", [])
        return merged

    def has_family(self):
        return bool(any(self.family.values()))

    def has_epithets(self):
        return bool(self.epithets)

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "style": self.style,
            "description": self.description,
            "given": {key: list(value) for key, value in self.given.items()},
            "family": {key: list(value) for key, value in self.family.items()},
            "epithets": list(self.epithets),
            "patterns": list(self.patterns),
        }


@dataclass(frozen=True)
class PersonName:
    """Готовое имя персонажа и его происхождение."""

    given: str
    family: str
    full: str
    style: str
    culture: Optional[str] = None
    theme: Optional[str] = None
    gender: str = "m"
    epithet: str = ""
    seed: int = 0

    @property
    def text(self):
        return self.full

    @property
    def short(self):
        return self.given

    def as_dict(self):
        return {
            "given": self.given,
            "family": self.family,
            "full": self.full,
            "text": self.text,
            "style": self.style,
            "culture": self.culture,
            "theme": self.theme,
            "gender": self.gender,
            "epithet": self.epithet,
            "seed": self.seed,
        }

    def __str__(self):
        return self.full


class PersonCatalog:
    """Загруженный набор реальных культур и фэнтезийных тем."""

    def __init__(self, cultures, themes, default_culture="russian",
                 root=None, schema=1):
        self.cultures = dict(cultures)
        self.themes = dict(themes)
        self.default_culture = str(default_culture or "russian")
        self.root = Path(root) if root is not None else None
        self.schema = int(schema or 1)
        self.validate()

    @classmethod
    def load(cls, root=None):
        root = Path(root) if root is not None else default_root()
        path = root / "people.json"
        data = _read_json(path)
        if not isinstance(data, Mapping):
            raise PeopleError("people.json должен быть объектом")
        cultures_raw = data.get("cultures") or {}
        themes_raw = data.get("fantasy_themes") or {}
        if not isinstance(cultures_raw, Mapping):
            raise PeopleError("cultures должен быть объектом")
        if not isinstance(themes_raw, Mapping):
            raise PeopleError("fantasy_themes должен быть объектом")
        cultures = {
            str(key): PersonCulture.from_data(key, value, "real", "cultures")
            for key, value in cultures_raw.items()
        }
        themes = {
            str(key): PersonCulture.from_data(
                key, value, "fantasy", "fantasy_themes")
            for key, value in themes_raw.items()
        }
        return cls(
            cultures, themes,
            default_culture=data.get("default_culture", "russian"),
            root=root,
            schema=data.get("schema", 1),
        )

    @classmethod
    def from_data(cls, data):
        if not isinstance(data, Mapping):
            raise PeopleError("данные people должны быть объектом")
        cultures = {
            str(key): PersonCulture.from_data(
                key, value, "real", "cultures")
            for key, value in (data.get("cultures") or {}).items()
        }
        themes = {
            str(key): PersonCulture.from_data(
                key, value, "fantasy", "fantasy_themes")
            for key, value in (data.get("fantasy_themes") or {}).items()
        }
        return cls(cultures, themes,
                   default_culture=data.get("default_culture", "russian"))

    def validate(self):
        if not self.cultures:
            raise PeopleError("нет ни одной реальной культуры")
        if not self.themes:
            raise PeopleError("нет ни одной фэнтезийной темы")
        if self.default_culture not in self.cultures:
            raise PeopleError("default_culture %r отсутствует в cultures"
                              % self.default_culture)
        for key, profile in list(self.cultures.items()) + \
                list(self.themes.items()):
            if not profile.id:
                raise PeopleError("пустой id профиля имён")
            if not any(profile.given.values()):
                raise PeopleError("%s: нет given" % key)
            if not profile.patterns:
                raise PeopleError("%s: нет patterns" % key)
        return self

    def culture_ids(self):
        return sorted(self.cultures)

    def theme_ids(self):
        return sorted(self.themes)

    def culture(self, culture_id):
        if culture_id not in self.cultures:
            raise PeopleError("нет культуры %r" % (culture_id,))
        return self.cultures[culture_id]

    def theme(self, theme_id):
        if theme_id not in self.themes:
            raise PeopleError("нет фэнтезийной темы %r" % (theme_id,))
        return self.themes[theme_id]

    def all_profiles(self):
        return [self.cultures[key] for key in self.culture_ids()] + [
            self.themes[key] for key in self.theme_ids()]

    def as_dict(self):
        return {
            "schema": self.schema,
            "default_culture": self.default_culture,
            "cultures": {key: self.cultures[key].as_dict()
                         for key in self.culture_ids()},
            "fantasy_themes": {key: self.themes[key].as_dict()
                               for key in self.theme_ids()},
        }


def _render_pattern(pattern, values):
    """Подставить слоты, не падая на необязательных частях имени."""
    def replace(match):
        key = match.group(1)
        return str(values.get(key) or "").strip()
    text = _SLOT.sub(replace, pattern)
    return re.sub(r"\s+", " ", text).strip(" -")


class PersonNameGenerator:
    """Детерминированный по seed генератор имён персонажей."""

    def __init__(self, catalog: Optional[PersonCatalog] = None, seed=0):
        self.catalog = catalog or default_catalog()
        self.seed = int(seed)
        self.rng = random.Random(self.seed)

    def _rng(self, seed=None):
        return self.rng if seed is None else random.Random(int(seed))

    def real(self, culture=None, gender=None, seed=None):
        """Имя из реальной культуры (по умолчанию — случайной)."""
        rng = self._rng(seed)
        culture_id = culture or self.catalog.default_culture
        if culture is None:
            culture_id = rng.choice(self.catalog.culture_ids())
        profile = self.catalog.culture(culture_id)
        return self._one(profile, "real", gender, rng,
                         seed if seed is not None else self.seed)

    def fantasy(self, theme=None, gender=None, seed=None):
        """Имя из фэнтезийной темы (по умолчанию — случайной)."""
        rng = self._rng(seed)
        theme_id = theme
        if theme_id is None:
            theme_id = rng.choice(self.catalog.theme_ids())
        profile = self.catalog.theme(theme_id)
        return self._one(profile, "fantasy", gender, rng,
                         seed if seed is not None else self.seed)

    def generate(self, culture=None, theme=None, gender=None, seed=None):
        """Имя в реальном или фэнтезийном стиле.

        ``culture`` и ``theme`` взаимоисключающи. Без них стиль выбирается
        случайно с небольшим перевесом в сторону реальных культур.
        """
        if culture and theme:
            raise PeopleError("нельзя одновременно указать culture и theme")
        if culture:
            return self.real(culture=culture, gender=gender, seed=seed)
        if theme:
            return self.fantasy(theme=theme, gender=gender, seed=seed)
        rng = self._rng(seed)
        if rng.random() < 0.65:
            profile = self.catalog.culture(rng.choice(
                self.catalog.culture_ids()))
            style = "real"
        else:
            profile = self.catalog.theme(rng.choice(
                self.catalog.theme_ids()))
            style = "fantasy"
        return self._one(profile, style, gender, rng,
                         seed if seed is not None else self.seed)

    def generate_many(self, count=10, culture=None, theme=None, gender=None,
                      seed=None):
        """Несколько разных имён, детерминированно по seed."""
        if culture and theme:
            raise PeopleError("нельзя одновременно указать culture и theme")
        limit = max(1, int(count))
        rng = self._rng(seed)
        results = []
        seen = set()
        attempts = 0
        while len(results) < limit and attempts < limit * 80:
            attempts += 1
            if culture:
                profile = self.catalog.culture(culture)
                style = "real"
            elif theme:
                profile = self.catalog.theme(theme)
                style = "fantasy"
            elif rng.random() < 0.65:
                profile = self.catalog.culture(rng.choice(
                    self.catalog.culture_ids()))
                style = "real"
            else:
                profile = self.catalog.theme(rng.choice(
                    self.catalog.theme_ids()))
                style = "fantasy"
            item = self._one(
                profile, style, gender, rng,
                seed if seed is not None else self.seed)
            if item.full in seen:
                continue
            seen.add(item.full)
            results.append(item)
        return results

    def _one(self, profile, style, gender, rng, seed):
        gender = _normalize_gender(gender) or rng.choice(list(_GENDER_KEYS))
        given = rng.choice(profile.given_for(gender))
        family = rng.choice(profile.family_for(gender)) \
            if profile.has_family() else ""
        epithet = rng.choice(profile.epithets) if profile.has_epithets() else ""
        pattern = rng.choice(profile.patterns)
        values = {
            "given": given,
            "family": family,
            "epithet": epithet,
        }
        full = _render_pattern(pattern, values)
        if not full:
            full = given
        return PersonName(
            given=given,
            family=family,
            full=full,
            style=style,
            culture=profile.id if style == "real" else None,
            theme=profile.id if style == "fantasy" else None,
            gender=gender,
            epithet=epithet,
            seed=int(seed),
        )

    def as_dict(self):
        return self.catalog.as_dict()


def default_root():
    return Path(__file__).resolve().parents[1] / "configs" / "naming"


def _default_catalog():
    return PersonCatalog.load()


_DEFAULT = None


def default_catalog():
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = _default_catalog()
    return _DEFAULT


__all__ = [
    "PeopleError", "PersonCatalog", "PersonCulture", "PersonName",
    "PersonNameGenerator", "default_catalog", "default_root",
]
