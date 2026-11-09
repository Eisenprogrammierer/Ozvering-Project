from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import random
import re
from typing import Dict, List, Mapping, Optional, Tuple

_GENDER_KEYS = ("m", "f")
_GENDER_ALIASES = {
    "m": "m",
    "male": "m",
    "man": "m",
    "м": "m",
    "муж": "m",
    "f": "f",
    "female": "f",
    "woman": "f",
    "ж": "f",
    "жен": "f",
}
_SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_POLICY_MODES = ("cultures", "epithets")


class PeopleError(ValueError):
    pass


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
        raise PeopleError(
            "%s: неизвестные полы %s" % (label, ", ".join(unknown))
        )
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


def _weights(value, label):
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PeopleError("%s должен быть объектом" % label)
    result = {}
    for key, amount in value.items():
        key = str(key).strip()
        if not key:
            raise PeopleError("%s: пустой ключ" % label)
        try:
            weight = float(amount)
        except (TypeError, ValueError):
            raise PeopleError(
                "%s.%s: вес должен быть числом" % (label, key)
            )
        if weight <= 0.0:
            raise PeopleError(
                "%s.%s: вес должен быть положительным" % (label, key)
            )
        result[key] = weight
    return result


@dataclass(frozen=True)
class NamingPolicy:

    id: str
    label: str
    mode: str = "cultures"
    cultures: Mapping[str, float] = field(default_factory=dict)
    themes: Mapping[str, float] = field(default_factory=dict)
    allow_epithets: bool = False
    epithets: Tuple[str, ...] = ()
    patterns: Tuple[str, ...] = ("{epithet}",)

    @classmethod
    def from_data(cls, item_id, data, source="policies"):
        if not isinstance(data, Mapping):
            raise PeopleError("%s.%s должен быть объектом" % (source, item_id))
        mode = str(data.get("mode") or "cultures").strip().lower()
        if mode not in _POLICY_MODES:
            raise PeopleError(
                "%s.%s: неизвестный режим %r" % (source, item_id, mode)
            )
        cultures = _weights(
            data.get("cultures"), "%s.%s.cultures" % (source, item_id)
        )
        themes = _weights(
            data.get("themes"), "%s.%s.themes" % (source, item_id)
        )
        epithets = _as_list(
            data.get("epithets"), "%s.%s.epithets" % (source, item_id)
        )
        patterns = _as_list(
            data.get("patterns"), "%s.%s.patterns" % (source, item_id)
        )
        if mode == "epithets":
            if not epithets:
                raise PeopleError(
                    "%s.%s: режиму epithets нужны эпитеты"
                    % (source, item_id)
                )
            if not patterns:
                patterns = ["{epithet}"]
            for pattern in patterns:
                if "{epithet}" not in pattern:
                    raise PeopleError(
                        "%s.%s: шаблон %r не содержит {epithet}"
                        % (source, item_id, pattern)
                    )
                if "{given}" in pattern:
                    raise PeopleError(
                        "%s.%s: шаблон %r не может содержать {given}"
                        % (source, item_id, pattern)
                    )
        elif not cultures and not themes:
            raise PeopleError(
                "%s.%s: нужен хотя бы один пул культур или тем"
                % (source, item_id)
            )
        return cls(
            id=_as_text(item_id, source),
            label=str(data.get("label") or item_id),
            mode=mode,
            cultures=cultures,
            themes=themes,
            allow_epithets=bool(data.get("allow_epithets", False)),
            epithets=tuple(epithets),
            patterns=tuple(patterns or ("{epithet}",)),
        )

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "mode": self.mode,
            "cultures": dict(self.cultures),
            "themes": dict(self.themes),
            "allow_epithets": self.allow_epithets,
            "epithets": list(self.epithets),
            "patterns": list(self.patterns),
        }


class PersonPolicyCatalog:

    def __init__(self, policies, aliases=None, root=None, schema=1):
        self.policies = dict(policies)
        self.aliases = {
            str(key): str(value) for key, value in (aliases or {}).items()
        }
        self.root = Path(root) if root is not None else None
        self.schema = int(schema or 1)
        self.validate()

    @classmethod
    def load(cls, root=None):
        root = Path(root) if root is not None else default_root()
        data = _read_json(root / "policies.json")
        return cls.from_data(data, root=root)

    @classmethod
    def from_data(cls, data, root=None):
        if not isinstance(data, Mapping):
            raise PeopleError("policies.json должен быть объектом")
        raw = data.get("policies") or {}
        if not isinstance(raw, Mapping):
            raise PeopleError("policies должен быть объектом")
        aliases = data.get("aliases") or {}
        if not isinstance(aliases, Mapping):
            raise PeopleError("aliases должен быть объектом")
        policies = {
            str(key): NamingPolicy.from_data(key, value)
            for key, value in raw.items()
        }
        return cls(
            policies,
            aliases=aliases,
            root=root,
            schema=data.get("schema", 1),
        )

    def validate(self):
        if not self.policies:
            raise PeopleError("нет ни одной политики имён")
        unknown = sorted(set(self.aliases.values()) - set(self.policies))
        if unknown:
            raise PeopleError(
                "aliases ссылаются на неизвестные политики: %s"
                % ", ".join(unknown)
            )
        return self

    def ids(self):
        return sorted(self.policies)

    def resolve(self, key):
        if key is None:
            return None
        if isinstance(key, NamingPolicy):
            return key
        name = str(key).strip()
        seen = set()
        while name and name not in seen:
            seen.add(name)
            if name in self.policies:
                return self.policies[name]
            name = self.aliases.get(name, "")
        return None

    def get(self, key):
        policy = self.resolve(key)
        if policy is None:
            raise PeopleError("нет политики имён %r" % (key,))
        return policy

    def as_dict(self):
        return {
            "schema": self.schema,
            "aliases": dict(self.aliases),
            "policies": {
                key: self.policies[key].as_dict() for key in self.ids()
            },
        }


@dataclass(frozen=True)
class PersonCulture:

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
        patterns = _as_list(
            data.get("patterns"), "%s.%s.patterns" % (source, item_id)
        )
        if not patterns:
            patterns = ["{given} {family}"]
        for pattern in patterns:
            if "{given}" not in pattern:
                raise PeopleError(
                    "%s.%s: шаблон %r не содержит {given}"
                    % (source, item_id, pattern)
                )
            if "{family}" in pattern and not any(family.values()):
                raise PeopleError(
                    "%s.%s: шаблону %r нужна фамилия"
                    % (source, item_id, pattern)
                )
        profile = cls(
            id=_as_text(item_id, source),
            label=str(data.get("label") or item_id),
            style=style,
            given=given,
            family=family,
            epithets=_as_list(
                data.get("epithets"), "%s.%s.epithets" % (source, item_id)
            ),
            patterns=tuple(patterns),
            description=str(data.get("description") or ""),
        )
        return profile

    def given_for(self, gender):
        names = self.given.get(gender) or []
        if not names:
            raise PeopleError("%s: нет имён для пола %s" % (self.id, gender))
        return names

    def family_for(self, gender):
        names = self.family.get(gender) or []
        if not names:
            raise PeopleError(
                "%s: нет фамилий для пола %s" % (self.id, gender)
            )
        return names

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
        return self.given or self.full

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

    def __init__(
        self, cultures, themes, default_culture="russian", root=None, schema=1
    ):
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
                key, value, "fantasy", "fantasy_themes"
            )
            for key, value in themes_raw.items()
        }
        return cls(
            cultures,
            themes,
            default_culture=data.get("default_culture", "russian"),
            root=root,
            schema=data.get("schema", 1),
        )

    @classmethod
    def from_data(cls, data):
        if not isinstance(data, Mapping):
            raise PeopleError("данные people должны быть объектом")
        cultures = {
            str(key): PersonCulture.from_data(key, value, "real", "cultures")
            for key, value in (data.get("cultures") or {}).items()
        }
        themes = {
            str(key): PersonCulture.from_data(
                key, value, "fantasy", "fantasy_themes"
            )
            for key, value in (data.get("fantasy_themes") or {}).items()
        }
        return cls(
            cultures,
            themes,
            default_culture=data.get("default_culture", "russian"),
        )

    def validate(self):
        if not self.cultures:
            raise PeopleError("нет ни одной реальной культуры")
        if not self.themes:
            raise PeopleError("нет ни одной фэнтезийной темы")
        if self.default_culture not in self.cultures:
            raise PeopleError(
                "default_culture %r отсутствует в cultures"
                % self.default_culture
            )
        for key, profile in list(self.cultures.items()) + list(
            self.themes.items()
        ):
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
            self.themes[key] for key in self.theme_ids()
        ]

    def as_dict(self):
        return {
            "schema": self.schema,
            "default_culture": self.default_culture,
            "cultures": {
                key: self.cultures[key].as_dict() for key in self.culture_ids()
            },
            "fantasy_themes": {
                key: self.themes[key].as_dict() for key in self.theme_ids()
            },
        }


def _render_pattern(pattern, values):
    def replace(match):
        key = match.group(1)
        return str(values.get(key) or "").strip()

    text = _SLOT.sub(replace, pattern)
    return re.sub(r"\s+", " ", text).strip(" -")


class PersonNameGenerator:

    def __init__(
        self,
        catalog: Optional[PersonCatalog] = None,
        seed=0,
        policies: Optional[PersonPolicyCatalog] = None,
    ):
        self.catalog = catalog or default_catalog()
        self.policy_catalog = policies or default_policies()
        self.seed = int(seed)
        self.rng = random.Random(self.seed)

    def _rng(self, seed=None):
        return self.rng if seed is None else random.Random(int(seed))

    def policy(self, key):
        return self.policy_catalog.resolve(key)

    def real(self, culture=None, gender=None, seed=None):
        rng = self._rng(seed)
        culture_id = culture or self.catalog.default_culture
        if culture is None:
            culture_id = rng.choice(self.catalog.culture_ids())
        profile = self.catalog.culture(culture_id)
        return self._one(
            profile,
            "real",
            gender,
            rng,
            seed if seed is not None else self.seed,
        )

    def fantasy(self, theme=None, gender=None, seed=None):
        rng = self._rng(seed)
        theme_id = theme
        if theme_id is None:
            theme_id = rng.choice(self.catalog.theme_ids())
        profile = self.catalog.theme(theme_id)
        return self._one(
            profile,
            "fantasy",
            gender,
            rng,
            seed if seed is not None else self.seed,
        )

    def generate(
        self, culture=None, theme=None, gender=None, seed=None, policy=None
    ):
        if culture and theme:
            raise PeopleError("нельзя одновременно указать culture и theme")
        if policy is not None:
            if culture or theme:
                raise PeopleError(
                    "нельзя одновременно указать policy и culture/theme"
                )
            return self.generate_policy(policy, gender=gender, seed=seed)
        if culture:
            return self.real(culture=culture, gender=gender, seed=seed)
        if theme:
            return self.fantasy(theme=theme, gender=gender, seed=seed)
        rng = self._rng(seed)
        if rng.random() < 0.65:
            profile = self.catalog.culture(
                rng.choice(self.catalog.culture_ids())
            )
            style = "real"
        else:
            profile = self.catalog.theme(rng.choice(self.catalog.theme_ids()))
            style = "fantasy"
        return self._one(
            profile,
            style,
            gender,
            rng,
            seed if seed is not None else self.seed,
        )

    def generate_many(
        self,
        count=10,
        culture=None,
        theme=None,
        gender=None,
        seed=None,
        policy=None,
    ):
        if culture and theme:
            raise PeopleError("нельзя одновременно указать culture и theme")
        if policy is not None:
            if culture or theme:
                raise PeopleError(
                    "нельзя одновременно указать policy и culture/theme"
                )
            return self.generate_many_policy(
                count, policy, gender=gender, seed=seed
            )
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
                profile = self.catalog.culture(
                    rng.choice(self.catalog.culture_ids())
                )
                style = "real"
            else:
                profile = self.catalog.theme(
                    rng.choice(self.catalog.theme_ids())
                )
                style = "fantasy"
            item = self._one(
                profile,
                style,
                gender,
                rng,
                seed if seed is not None else self.seed,
            )
            if item.full in seen:
                continue
            seen.add(item.full)
            results.append(item)
        return results

    def generate_policy(self, policy, gender=None, seed=None):
        resolved = self._require_policy(policy)
        rng = self._rng(seed)
        item_seed = seed if seed is not None else self.seed
        if resolved.mode == "epithets":
            return self._one_epithet(resolved, gender, rng, item_seed)
        pool = self._policy_pool(resolved)
        if not pool:
            raise PeopleError(
                "политика %r не даёт ни одного профиля имён" % resolved.id
            )
        profile, style, patterns = self._choose_profile(rng, pool)
        return self._one(
            profile, style, gender, rng, item_seed, patterns=patterns
        )

    def generate_many_policy(
        self, count=10, policy=None, gender=None, seed=None
    ):
        resolved = self._require_policy(policy)
        limit = max(1, int(count))
        rng = self._rng(seed)
        item_seed = seed if seed is not None else self.seed
        results = []
        seen = set()
        attempts = 0
        pool = () if resolved.mode == "epithets" else self._policy_pool(
            resolved
        )
        if resolved.mode != "epithets" and not pool:
            raise PeopleError(
                "политика %r не даёт ни одного профиля имён" % resolved.id
            )
        while len(results) < limit and attempts < limit * 80:
            attempts += 1
            if resolved.mode == "epithets":
                item = self._one_epithet(
                    resolved, gender, rng, item_seed
                )
            else:
                profile, style, patterns = self._choose_profile(rng, pool)
                item = self._one(
                    profile,
                    style,
                    gender,
                    rng,
                    item_seed,
                    patterns=patterns,
                )
            if item.full in seen:
                continue
            seen.add(item.full)
            results.append(item)
        return results

    def _require_policy(self, policy):
        if isinstance(policy, NamingPolicy):
            return policy
        resolved = self.policy_catalog.resolve(policy)
        if resolved is None:
            raise PeopleError("нет политики имён %r" % (policy,))
        return resolved

    def _policy_pool(self, policy):
        pool = []
        for culture_id, weight in policy.cultures.items():
            ids = (
                self.catalog.culture_ids()
                if culture_id == "*"
                else [culture_id]
            )
            for item_id in ids:
                profile = self.catalog.culture(item_id)
                patterns = self._policy_patterns(profile, policy)
                if patterns:
                    pool.append(
                        (profile, "real", patterns, float(weight))
                    )
        for theme_id, weight in policy.themes.items():
            ids = (
                self.catalog.theme_ids() if theme_id == "*" else [theme_id]
            )
            for item_id in ids:
                profile = self.catalog.theme(item_id)
                patterns = self._policy_patterns(profile, policy)
                if patterns:
                    pool.append(
                        (profile, "fantasy", patterns, float(weight))
                    )
        return pool

    def _policy_patterns(self, profile, policy):
        patterns = [
            pattern
            for pattern in profile.patterns
            if policy.allow_epithets or "{epithet}" not in pattern
        ]
        result = []
        for pattern in patterns:
            if "{family}" in pattern and not profile.has_family():
                continue
            if "{epithet}" in pattern and not profile.has_epithets():
                continue
            result.append(pattern)
        return result

    def _choose_profile(self, rng, pool):
        total = sum(item[3] for item in pool)
        roll = rng.random() * total
        for profile, style, patterns, weight in pool:
            roll -= weight
            if roll <= 0.0:
                return profile, style, patterns
        profile, style, patterns, _weight = pool[-1]
        return profile, style, patterns

    def _one_epithet(self, policy, gender, rng, seed):
        gender = _normalize_gender(gender) or rng.choice(list(_GENDER_KEYS))
        epithet = rng.choice(list(policy.epithets))
        pattern = rng.choice(list(policy.patterns or ("{epithet}",)))
        full = _render_pattern(pattern, {"epithet": epithet})
        return PersonName(
            given="",
            family="",
            full=full or epithet,
            style="epithet",
            gender=gender,
            epithet=epithet,
            seed=int(seed),
        )

    def _one(self, profile, style, gender, rng, seed, patterns=None):
        gender = _normalize_gender(gender) or rng.choice(list(_GENDER_KEYS))
        pattern = rng.choice(tuple(patterns or profile.patterns))
        given = rng.choice(profile.given_for(gender))
        family = ""
        if "{family}" in pattern:
            family = rng.choice(profile.family_for(gender))
        epithet = ""
        if "{epithet}" in pattern:
            if not profile.has_epithets():
                raise PeopleError(
                    "%s: шаблону %r нужен эпитет"
                    % (profile.id, pattern)
                )
            epithet = rng.choice(profile.epithets)
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


_DEFAULT_POLICIES = None


def default_policies():
    global _DEFAULT_POLICIES
    if _DEFAULT_POLICIES is None:
        _DEFAULT_POLICIES = PersonPolicyCatalog.load()
    return _DEFAULT_POLICIES


__all__ = [
    "NamingPolicy",
    "PeopleError",
    "PersonCatalog",
    "PersonCulture",
    "PersonName",
    "PersonNameGenerator",
    "PersonPolicyCatalog",
    "default_catalog",
    "default_policies",
    "default_root",
]
