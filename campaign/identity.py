"""Личность героя кампании автоматов.

Модуль отделяет **содержание личности** (происхождение, призвание,
ценности, слабость, характер) от экрана и от пресета кампании. Все
варианты лежат в ``configs/characters/identity.json``; код знает только,
как свести выбранные записи в нормализованный словарь и как перенести
его на персонажа пресета.

Личность не заменяет роль: роль отвечает за фракцию и мандат, а личность
— за имя, биографию, потребности и черту характера конкретного человека,
который этот мандат держит.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Dict, Mapping

import character_traits as CT

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "configs" / "characters" / "identity.json"


class IdentityError(ValueError):
    """Файл личности отсутствует или содержит некорректные данные."""


def default_root():
    return DEFAULT_PATH.parent


def default_identity_path():
    return DEFAULT_PATH


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

    def build(self, values):
        """Собрать профиль личности из выбранных идентификаторов."""
        values = dict(values or {})
        gender = self.option("genders", values.get("gender"))
        origin = self.option("origins", values.get("origin"))
        vocation = self.option("vocations", values.get("vocation"))
        value = self.option("values", values.get("value"))
        flaw = self.option("flaws", values.get("flaw"))
        trait = str(values.get("trait") or "")
        if trait not in self.trait_labels:
            trait = self.trait_order[0]
        name = _text(values.get("name"), self.default_name)
        if not name:
            name = "Новый правитель"

        traits = {}
        needs = {}
        for option in (origin, vocation, value, flaw):
            for key, amount in option.traits.items():
                traits[key] = traits.get(key, 0.0) + amount
            for key, amount in option.needs.items():
                needs[key] = needs.get(key, 0.0) + amount
        traits[trait] = traits.get(trait, 0.0) + 0.22
        biography = " ".join(
            item.text for item in (origin, vocation, value, flaw)
        )
        summary = " · ".join(
            item
            for item in (
                origin.label,
                vocation.label,
                value.label,
                self.trait_label(trait),
            )
            if item
        )
        return {
            "name": name,
            "gender": gender.id,
            "gender_label": gender.label,
            "origin": origin.id,
            "origin_label": origin.label,
            "origin_summary": origin.summary,
            "vocation": vocation.id,
            "vocation_label": vocation.label,
            "vocation_summary": vocation.summary,
            "value": value.id,
            "value_label": value.label,
            "value_summary": value.summary,
            "flaw": flaw.id,
            "flaw_label": flaw.label,
            "flaw_summary": flaw.summary,
            "trait": trait,
            "trait_label": self.trait_label(trait),
            "trait_summary": self.trait_summaries.get(trait, ""),
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


__all__ = [
    "DEFAULT_PATH",
    "IdentityCatalog",
    "IdentityError",
    "IdentityOption",
    "default_identity_path",
    "load_identity_catalog",
]
