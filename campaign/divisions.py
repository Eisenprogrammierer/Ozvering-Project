"""Пятнадцать делений персонажа — ролевой слой, а не метрика автомата.

Деления отвечают на вопрос «кем персонаж является для мира»: к какой
земле, сословию, вере, институту и семье он принадлежит. Они не меняют
формулы силы и энергии напрямую; их читают события, диалоги, видимость и
кампанийные проверки.

Все определения лежат в ``configs/characters/divisions.json``. Код знает
только контракт:

* делений ровно 15 и они перечислены в :data:`DIMENSIONS`;
* каждое деление — одна выбранная роль из списка значений;
* неизвестное деление или значение отвергается (если ``strict``);
* ``Divisions`` умеет сериализоваться, сливаться и описываться.

Так деления остаются контентом: добавить новое значение можно в JSON, не
трогая Python.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent
    / "configs"
    / "characters"
    / "divisions.json"
)

#: Канонический порядок 15 делений.
DIMENSIONS = (
    "territorial",
    "social",
    "economic",
    "political",
    "religious",
    "ethnic",
    "age",
    "sex",
    "professional",
    "institutional",
    "migratory",
    "educational",
    "property",
    "legal",
    "family",
)


class DivisionError(ValueError):
    """Некорректный файл делений или неизвестное значение."""


def _text(value, default=""):
    text = str(value or "").strip()
    return text or default


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True)
class DivisionValue:
    id: str
    label: str
    summary: str = ""

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class DivisionDefinition:
    key: str
    label: str
    summary: str
    values: Tuple[DivisionValue, ...] = ()

    def value(self, value_id):
        value_id = _text(value_id)
        for item in self.values:
            if item.id == value_id:
                return item
        return None

    def has(self, value_id):
        return self.value(value_id) is not None

    @property
    def value_ids(self):
        return tuple(item.id for item in self.values)

    def as_dict(self):
        return {
            "key": self.key,
            "label": self.label,
            "summary": self.summary,
            "values": [item.as_dict() for item in self.values],
        }


class DivisionCatalog:
    """Разобранный справочник делений."""

    def __init__(self, data, path=None):
        if not isinstance(data, Mapping):
            raise DivisionError("корень divisions.json должен быть объектом")
        self.path = Path(path) if path is not None else None
        self.schema = int(data.get("schema", 1) or 1)
        if self.schema != 1:
            raise DivisionError(
                "неподдерживаемая схема делений: %s" % self.schema
            )
        self.label = _text(data.get("label"), "Деления персонажей")
        self.description = _text(data.get("description"))
        self.strict = bool(data.get("strict", False))
        raw = data.get("dimensions")
        if not isinstance(raw, Mapping):
            raise DivisionError("dimensions должен быть объектом")
        self.dimensions: Dict[str, DivisionDefinition] = {}
        for key, value in raw.items():
            key = _text(key)
            value = _as_mapping(value)
            values = tuple(
                DivisionValue(
                    id=_text(item.get("id")),
                    label=_text(item.get("label"), _text(item.get("id"))),
                    summary=_text(item.get("summary")),
                )
                for item in (value.get("values") or ())
                if isinstance(item, Mapping) and _text(item.get("id"))
            )
            self.dimensions[key] = DivisionDefinition(
                key=key,
                label=_text(value.get("label"), key),
                summary=_text(value.get("summary")),
                values=values,
            )
        missing = [key for key in DIMENSIONS if key not in self.dimensions]
        extra = [key for key in self.dimensions if key not in DIMENSIONS]
        if missing or extra:
            raise DivisionError(
                "нужно ровно 15 канонических делений; нет: %s; лишние: %s"
                % (missing, extra)
            )
        for definition in self.dimensions.values():
            if not definition.values:
                raise DivisionError(
                    "деление %s не содержит значений" % definition.key
                )
            ids = [item.id for item in definition.values]
            if len(ids) != len(set(ids)):
                raise DivisionError(
                    "деление %s: повторяются значения" % definition.key
                )
        self.presets = {
            _text(key): self.validate(value)
            for key, value in _as_mapping(data.get("presets")).items()
        }

    @classmethod
    def load(cls, path=None):
        path = Path(path) if path is not None else DEFAULT_PATH
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError as exc:
            raise DivisionError("файл делений не найден: %s" % path) from exc
        except json.JSONDecodeError as exc:
            raise DivisionError(
                "битый JSON делений %s: %s" % (path, exc)
            ) from exc
        return cls(data, path=path)

    @property
    def keys(self):
        return tuple(DIMENSIONS)

    def definition(self, key):
        return self.dimensions.get(_text(key))

    def value(self, key, value_id):
        definition = self.definition(key)
        return definition.value(value_id) if definition else None

    def validate(self, values):
        values = _as_mapping(values)
        result = {}
        for key, value_id in values.items():
            key = _text(key)
            value_id = _text(value_id)
            definition = self.definition(key)
            if definition is None:
                if self.strict:
                    raise DivisionError("неизвестное деление %r" % key)
                continue
            if not value_id:
                continue
            if not definition.has(value_id):
                if self.strict:
                    raise DivisionError(
                        "деление %s: неизвестное значение %r"
                        % (key, value_id)
                    )
                continue
            result[key] = value_id
        return result

    def empty(self):
        return Divisions(catalog=self)

    def preset(self, name, fallback=None):
        """Готовый набор делений по культуре или ``fallback``."""
        if name in self.presets:
            return dict(self.presets[name])
        if fallback is not None and fallback in self.presets:
            return dict(self.presets[fallback])
        return {}

    def from_data(self, values):
        return Divisions(catalog=self, values=self.validate(values))

    def as_dict(self):
        return {
            "schema": self.schema,
            "label": self.label,
            "description": self.description,
            "strict": self.strict,
            "dimensions": {
                key: self.dimensions[key].as_dict() for key in DIMENSIONS
            },
        }


@dataclass
class Divisions:
    """Текущие деления одного персонажа."""

    catalog: DivisionCatalog = field(default_factory=DivisionCatalog.load)
    values: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        self.values = self.catalog.validate(self.values)

    def set(self, key, value_id):
        key = _text(key)
        definition = self.catalog.definition(key)
        if definition is None:
            raise DivisionError("неизвестное деление %r" % key)
        value_id = _text(value_id)
        if not value_id:
            self.values.pop(key, None)
            return None
        item = definition.value(value_id)
        if item is None:
            raise DivisionError(
                "деление %s: неизвестное значение %r" % (key, value_id)
            )
        self.values[key] = value_id
        return item

    def get(self, key, default=None):
        return self.values.get(_text(key), default)

    def clear(self, key=None):
        if key is None:
            self.values.clear()
        else:
            self.values.pop(_text(key), None)

    def update(self, values):
        self.values.update(self.catalog.validate(values))
        return self

    def missing(self):
        return [key for key in DIMENSIONS if key not in self.values]

    def is_complete(self):
        return not self.missing()

    def label(self, key):
        definition = self.catalog.definition(key)
        if definition is None:
            return _text(key)
        item = definition.value(self.values.get(_text(key), ""))
        return item.label if item else ""

    def describe(self, key):
        definition = self.catalog.definition(key)
        if definition is None:
            return ""
        item = definition.value(self.values.get(_text(key), ""))
        if item is None:
            return ""
        return item.summary or item.label

    def tags(self):
        result = []
        for key in DIMENSIONS:
            if key in self.values:
                result.append("%s:%s" % (key, self.values[key]))
        return result

    def as_dict(self):
        return {
            key: value
            for key, value in self.values.items()
            if key in self.catalog.dimensions
        }

    def snapshot(self):
        return {
            key: {
                "id": value_id,
                "label": self.label(key),
                "summary": self.describe(key),
            }
            for key, value_id in self.as_dict().items()
        }

    @classmethod
    def from_data(cls, values, catalog=None):
        catalog = catalog or DivisionCatalog.load()
        return cls(catalog=catalog, values=values)


@lru_cache(maxsize=8)
def _load_cached(path_text, mtime_ns):
    return DivisionCatalog.load(path_text)


def load_divisions(path=None, use_cache=True):
    path = Path(path) if path is not None else DEFAULT_PATH
    if not use_cache:
        return DivisionCatalog.load(path)
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise DivisionError("файл делений не найден: %s" % path) from exc
    return _load_cached(str(path.resolve()), stat.st_mtime_ns)


def default_divisions_path():
    return DEFAULT_PATH


def division_tags(values, catalog=None):
    """Теги ``dimension:value`` для событий и видимости."""
    return Divisions.from_data(values, catalog).tags()


__all__ = [
    "DEFAULT_PATH",
    "DIMENSIONS",
    "DivisionCatalog",
    "DivisionDefinition",
    "DivisionError",
    "DivisionValue",
    "Divisions",
    "default_divisions_path",
    "division_tags",
    "load_divisions",
]
