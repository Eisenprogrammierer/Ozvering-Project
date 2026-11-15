# campaign/identity.py
"""Личность героя кампании автоматов и каталог архетипов.

Модуль отделяет **содержание личности** (происхождение, призвание,
ценности, слабость, характер) от экрана и от пресета кампании. Все
варианты личности лежат в ``configs/characters/identity.json``.

Архетипы персонажей (уличный музыкант, школьник, жрец, чиновник,
ремесленник, солдат, торговец, аристократ) — отдельный каталог
``configs/characters/archetypes.json``. Архетип описывает не личность
саму по себе, а стартовую точку: социальный слой, стартовые работы,
доступные сцены, теги сюжета. Личность накладывается на архетип, а не
заменяет его.

Личность и архетип не заменяют роль: роль отвечает за фракцию и мандат,
личность — за имя, биографию, потребности и черту характера конкретного
человека, который этот мандат держит, а архетип — за его социальный
слой и стартовые работы.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple

import character_traits as CT

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "configs" / "characters" / "identity.json"
DEFAULT_ARCHETYPES_PATH = (
    ROOT / "configs" / "characters" / "archetypes.json"
)

ENTITY_KINDS = (
    "character",
    "organization",
    "item",
    "place",
    "deity",
)

SOCIAL_LAYERS = (
    "street",
    "school",
    "temple",
    "court",
    "market",
    "army",
    "guild",
    "free",
)

IDENTITY_SECTIONS = (
    "genders",
    "origins",
    "vocations",
    "values",
    "flaws",
    "traits",
)


class IdentityError(ValueError):
    """Файл личности или архетипов содержит некорректные данные."""


def default_root():
    return DEFAULT_PATH.parent


def default_identity_path():
    return DEFAULT_PATH


def default_archetypes_path():
    return DEFAULT_ARCHETYPES_PATH


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _text(value, default=""):
    text = str(value or "").strip()
    return text or default


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _number(value, low)))


def _string_list(value):
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, Iterable):
        return ()
    result = []
    for item in value:
        text = str(item).strip()
        if text:
            result.append(text)
    return tuple(result)


@dataclass(frozen=True)
class IdentityOption:
    id: str
    label: str
    summary: str
    text: str
    needs: Mapping[str, float]
    traits: Mapping[str, float]


def _options(data, where):
    if not isinstance(data, Mapping) or not data:
        raise IdentityError("%s должен быть непустым объектом" % where)
    result: Dict[str, IdentityOption] = {}
    for key, value in data.items():
        key = str(key)
        if not isinstance(value, Mapping):
            raise IdentityError("%s.%s должен быть объектом" % (where, key))
        label = _text(value.get("label"))
        if not label:
            raise IdentityError("%s.%s: нужен label" % (where, key))
        summary = _text(value.get("summary"), label)
        text = _text(value.get("text"), summary)
        needs = {
            str(name): _number(amount, 0.0)
            for name, amount in _mapping(value.get("needs")).items()
        }
        traits = {
            str(name): _number(amount, 0.0)
            for name, amount in _mapping(value.get("traits")).items()
        }
        result[key] = IdentityOption(
            id=key,
            label=label,
            summary=summary,
            text=text,
            needs=needs,
            traits=traits,
        )
    return result


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


class IdentityCatalog:
    """Каталог вариантов личности и сборка нормализованного профиля."""

    def __init__(self, data, path=None):
        if not isinstance(data, Mapping):
            raise IdentityError("корень файла личности должен быть объектом")
        self.path = Path(path) if path is not None else None
        self.schema = int(_number(data.get("schema"), 1))
        if self.schema != 1:
            raise IdentityError(
                "неподдерживаемая версия схемы: %s" % self.schema
            )
        self.label = _text(data.get("label"), "Личность героя")
        self.default_name = _text(data.get("default_name"))
        self.genders = _options(data.get("genders"), "genders")
        self.origins = _options(data.get("origins"), "origins")
        self.vocations = _options(data.get("vocations"), "vocations")
        self.values = _options(data.get("values"), "values")
        self.flaws = _options(data.get("flaws"), "flaws")
        model = CT.load_traits()
        self.trait_labels = dict(model.labels)
        self.trait_summaries = {
            key: item.summary for key, item in model.traits.items()
        }
        self.trait_order = tuple(model.traits)

    @classmethod
    def load(cls, path=None):
        path = Path(path) if path is not None else DEFAULT_PATH
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise IdentityError(
                "файл личности не найден: %s" % path
            ) from exc
        except json.JSONDecodeError as exc:
            raise IdentityError(
                "битый JSON личности %s: %s" % (path, exc)
            ) from exc
        return cls(data, path=path)

    def option(self, section, key):
        table = getattr(self, section)
        key = str(key or "")
        if key in table:
            return table[key]
        return next(iter(table.values()))

    def option_ids(self, section):
        return tuple(getattr(self, section))

    def trait_label(self, key):
        return self.trait_labels.get(str(key), str(key))

    def build(self, values, sections=None):
        """Собрать профиль личности из выбранных идентификаторов.

        ``sections`` ограничивает набор разделов. ``None`` означает все
        разделы; пустой набор не отключает пол и имя.
        """
        values = dict(values or {})
        active = None if sections is None else set(sections)

        def enabled(name):
            return active is None or name in active

        gender = self.option("genders", values.get("gender"))
        origin = (
            self.option("origins", values.get("origin"))
            if enabled("origin")
            else None
        )
        vocation = (
            self.option("vocations", values.get("vocation"))
            if enabled("vocation")
            else None
        )
        value = (
            self.option("values", values.get("value"))
            if enabled("value")
            else None
        )
        flaw = (
            self.option("flaws", values.get("flaw"))
            if enabled("flaw")
            else None
        )
        trait = ""
        if enabled("trait"):
            trait = str(values.get("trait") or "")
            if trait not in self.trait_labels:
                trait = self.trait_order[0]
        name = _text(values.get("name"), self.default_name)
        if not name:
            name = "Новый правитель"

        traits = {}
        needs = {}
        for option in (origin, vocation, value, flaw):
            if option is None:
                continue
            for key, amount in option.traits.items():
                traits[key] = traits.get(key, 0.0) + amount
            for key, amount in option.needs.items():
                needs[key] = needs.get(key, 0.0) + amount
        if trait:
            traits[trait] = traits.get(trait, 0.0) + 0.22
        biography = " ".join(
            item.text
            for item in (origin, vocation, value, flaw)
            if item is not None
        )
        summary = " · ".join(
            item
            for item in (
                origin.label if origin is not None else "",
                vocation.label if vocation is not None else "",
                value.label if value is not None else "",
                self.trait_label(trait) if trait else "",
            )
            if item
        )
        data = {
            "name": name,
            "gender": gender.id,
            "gender_label": gender.label,
            "biography": biography,
            "summary": summary,
            "needs": {
                key: round(_clamp(amount, -1.0, 1.0), 4)
                for key, amount in needs.items()
            },
            "traits": {
                key: round(_number(amount, 0.0), 4)
                for key, amount in traits.items()
            },
        }
        for key, option in (
            ("origin", origin),
            ("vocation", vocation),
            ("value", value),
            ("flaw", flaw),
        ):
            if option is None:
                continue
            data[key] = option.id
            data[key + "_label"] = option.label
            data[key + "_summary"] = option.summary
        if trait:
            data["trait"] = trait
            data["trait_label"] = self.trait_label(trait)
            data["trait_summary"] = self.trait_summaries.get(trait, "")
        return data


@dataclass(frozen=True)
class ArchetypeSpec:
    """Стартовая точка персонажа: слой, работы, сцены, теги сюжета.

    Архетип не заменяет роль и не заменяет личность. Он отвечает за
    социальный слой, стартовые работы (по id), доступные сцены и теги
    сюжета, к которым персонаж подходит. Работы появятся в P3/P4; до тех
    пор ``start_offices`` — просто список id, не требующих обработчика.
    """

    id: str
    label: str
    description: str = ""
    entity_kind: str = "character"
    social_layer: str = ""
    start_offices: Tuple[str, ...] = ()
    start_faction: str = ""
    storyline_tags: Tuple[str, ...] = ()
    playable: bool = True
    identity_sections: Tuple[str, ...] = ()
    priority_needs: Tuple[str, ...] = ()
    needs: Mapping[str, float] = field(default_factory=dict)
    traits: Mapping[str, float] = field(default_factory=dict)
    scenes: Tuple[str, ...] = ()

    def __post_init__(self):
        archetype_id = str(self.id or "").strip()
        label = str(self.label or "").strip()
        if not archetype_id:
            raise IdentityError("archetype: пустой id")
        if not label:
            raise IdentityError("%s: пустой label" % archetype_id)
        object.__setattr__(self, "id", archetype_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "description", _text(self.description))
        kind = str(self.entity_kind or "character").strip().lower()
        if kind not in ENTITY_KINDS:
            raise IdentityError(
                "%s: entity_kind=%r не из %s"
                % (archetype_id, kind, ", ".join(ENTITY_KINDS))
            )
        object.__setattr__(self, "entity_kind", kind)
        layer = str(self.social_layer or "").strip().lower()
        if layer and layer not in SOCIAL_LAYERS:
            raise IdentityError(
                "%s: social_layer=%r не из %s"
                % (archetype_id, layer, ", ".join(SOCIAL_LAYERS))
            )
        object.__setattr__(self, "social_layer", layer)
        object.__setattr__(
            self, "start_offices", _string_list(self.start_offices)
        )
        object.__setattr__(
            self, "start_faction", str(self.start_faction or "").strip()
        )
        object.__setattr__(
            self, "storyline_tags", _string_list(self.storyline_tags)
        )
        object.__setattr__(self, "playable", bool(self.playable))
        object.__setattr__(
            self,
            "identity_sections",
            _string_list(self.identity_sections),
        )
        for section in self.identity_sections:
            if section not in IDENTITY_SECTIONS:
                raise IdentityError(
                    "%s: identity_sections=%r не из %s"
                    % (
                        archetype_id,
                        section,
                        ", ".join(IDENTITY_SECTIONS),
                    )
                )
        object.__setattr__(
            self,
            "priority_needs",
            _string_list(self.priority_needs),
        )
        needs = {
            str(key): _number(value, 0.0)
            for key, value in _mapping(self.needs).items()
        }
        object.__setattr__(self, "needs", needs)
        traits = {
            str(key): _number(value, 0.0)
            for key, value in _mapping(self.traits).items()
        }
        object.__setattr__(self, "traits", traits)
        object.__setattr__(
            self, "scenes", _string_list(self.scenes)
        )

    @classmethod
    def from_data(cls, data):
        if not isinstance(data, Mapping):
            raise IdentityError("archetype должен быть объектом")
        return cls(
            id=data.get("id"),
            label=data.get("label") or data.get("name"),
            description=data.get("description", ""),
            entity_kind=data.get("entity_kind", "character"),
            social_layer=data.get("social_layer", ""),
            start_offices=data.get("start_offices") or (),
            start_faction=data.get("start_faction", ""),
            storyline_tags=data.get("storyline_tags") or (),
            playable=data.get("playable", True),
            identity_sections=data.get("identity_sections") or (),
            priority_needs=data.get("priority_needs") or (),
            needs=data.get("needs") or {},
            traits=data.get("traits") or {},
            scenes=data.get("scenes") or (),
        )

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "entity_kind": self.entity_kind,
            "social_layer": self.social_layer,
            "start_offices": list(self.start_offices),
            "start_faction": self.start_faction,
            "storyline_tags": list(self.storyline_tags),
            "playable": self.playable,
            "identity_sections": list(self.identity_sections),
            "priority_needs": list(self.priority_needs),
            "needs": dict(self.needs),
            "traits": dict(self.traits),
            "scenes": list(self.scenes),
        }


class ArchetypeCatalog:
    """Каталог архетипов персонажей. Читается из JSON, без домена."""

    def __init__(self, data, path=None):
        if not isinstance(data, Mapping):
            raise IdentityError("корень файла архетипов должен быть объектом")
        self.path = Path(path) if path is not None else None
        self.schema = int(_number(data.get("schema"), 1))
        if self.schema != 1:
            raise IdentityError(
                "неподдерживаемая версия схемы архетипов: %s" % self.schema
            )
        self.label = _text(data.get("label"), "Архетипы персонажей")
        raw = data.get("archetypes")
        if not isinstance(raw, (list, tuple)) or not raw:
            raise IdentityError("archetypes должен быть непустым списком")
        result: Dict[str, ArchetypeSpec] = {}
        for index, item in enumerate(raw):
            spec = ArchetypeSpec.from_data(item)
            if spec.id in result:
                raise IdentityError(
                    "повторяется id архетипа: %s (позиция %d)"
                    % (spec.id, index)
                )
            result[spec.id] = spec
        self.archetypes = result

    @classmethod
    def load(cls, path=None):
        path = Path(path) if path is not None else DEFAULT_ARCHETYPES_PATH
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise IdentityError(
                "файл архетипов не найден: %s" % path
            ) from exc
        except json.JSONDecodeError as exc:
            raise IdentityError(
                "битый JSON архетипов %s: %s" % (path, exc)
            ) from exc
        return cls(data, path=path)

    def get(self, archetype_id):
        return self.archetypes.get(str(archetype_id or ""))

    def require(self, archetype_id):
        archetype = self.get(archetype_id)
        if archetype is None:
            raise IdentityError("нет архетипа %r" % (archetype_id,))
        return archetype

    def all(self):
        return sorted(
            self.archetypes.values(),
            key=lambda item: (item.social_layer, item.label, item.id),
        )

    def by_layer(self, layer):
        layer = str(layer or "").strip().lower()
        return [
            item for item in self.all() if item.social_layer == layer
        ]

    def playable(self):
        return [item for item in self.all() if item.playable]

    def by_tag(self, tag):
        tag = str(tag or "").strip()
        if not tag:
            return list(self.all())
        return [
            item for item in self.all() if tag in item.storyline_tags
        ]

    def as_dict(self):
        return {
            "schema": self.schema,
            "label": self.label,
            "archetypes": [item.as_dict() for item in self.all()],
        }


@lru_cache(maxsize=4)
def _load_cached(path_text, mtime_ns):
    del mtime_ns
    return IdentityCatalog.load(path_text)


def load_identity_catalog(path=None, use_cache=True):
    path = Path(path) if path is not None else DEFAULT_PATH
    if not use_cache:
        return IdentityCatalog.load(path)
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise IdentityError(
            "файл личности не найден: %s" % path
        ) from exc
    return _load_cached(str(path.resolve()), stat.st_mtime_ns)


@lru_cache(maxsize=4)
def _load_archetypes_cached(path_text, mtime_ns):
    del mtime_ns
    return ArchetypeCatalog.load(path_text)


def load_archetypes_catalog(path=None, use_cache=True):
    """Загрузить каталог архетипов; ошибка не роняет пресет.

    Возврат ``None`` — если файла нет. Это осознанно: старые пресеты и
    старые сейвы не должны падать из-за нового каталога.
    """
    path = Path(path) if path is not None else DEFAULT_ARCHETYPES_PATH
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    if not use_cache:
        return ArchetypeCatalog.load(path)
    return _load_archetypes_cached(str(path.resolve()), stat.st_mtime_ns)


__all__ = [
    "DEFAULT_PATH",
    "DEFAULT_ARCHETYPES_PATH",
    "ENTITY_KINDS",
    "SOCIAL_LAYERS",
    "IdentityCatalog",
    "IdentityError",
    "IdentityOption",
    "ArchetypeCatalog",
    "ArchetypeSpec",
    "default_identity_path",
    "default_archetypes_path",
    "load_identity_catalog",
    "load_archetypes_catalog",
]
