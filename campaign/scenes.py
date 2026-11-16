"""Локальная сцена мира: место, публика, работы, вход и время.

`SceneSpec` отделяет *сцену* от узла мира. Узел задаёт структуру и
экономику, сцена — кто здесь находится, какие работы уместны и по каким
правилам сюда входят. Это данные: новая улица, школа или храм
добавляются JSON-файлом, а не правкой `WorldEngine`.

Сцена не создаёт второй движок. Её работы — те же `ActionSpec` мира;
локальная публика — те же персонажи `WorldEngine`, только объявленные в
сцене; время сцены лишь читает/переопределяет `seconds_per_day` и
`actions_per_day` мира.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence, Tuple

from .errors import CampaignError

SCENE_SCHEMA_VERSION = 1


class SceneError(CampaignError):
    """Некорректная сцена или каталог сцен."""


def _text(value, default=""):
    if value is None:
        return default
    return str(value)


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _integer(value, default=0):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return int(default)


def _string_list(value):
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if str(item))


@dataclass(frozen=True)
class LocalPublic:
    """Именованный человек сцены.

    Это не «толпа»-счётчик: запись становится обычным персонажем мира с
    отношениями, здоровьем и адресацией через `entity_ref`.
    """

    id: str
    name: str
    role: str = ""
    description: str = ""
    tags: Tuple[str, ...] = ()
    affinity: float = 0.0
    trust: float = 0.0
    fear: float = 0.0
    respect: float = 0.0
    circle: str = "acquaintance"
    health: float = 100.0
    node_id: str = ""

    @classmethod
    def from_dict(cls, data, location=""):
        if isinstance(data, str):
            data = {"id": data}
        if not isinstance(data, Mapping):
            raise SceneError("публика сцены должна быть объектом")
        public_id = _text(data.get("id")).strip()
        if not public_id:
            raise SceneError("у публики сцены нужен id")
        return cls(
            id=public_id,
            name=_text(data.get("name"), public_id),
            role=_text(data.get("role")),
            description=_text(data.get("description")),
            tags=_string_list(data.get("tags")),
            affinity=_number(data.get("affinity"), 0.0),
            trust=_number(data.get("trust"), 0.0),
            fear=_number(data.get("fear"), 0.0),
            respect=_number(data.get("respect"), 0.0),
            circle=_text(data.get("circle"), "acquaintance"),
            health=_number(data.get("health"), 100.0),
            node_id=_text(data.get("node_id"), location),
        )

    def as_character(self, location=""):
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "description": self.description,
            "tags": list(self.tags),
            "affinity": self.affinity,
            "trust": self.trust,
            "fear": self.fear,
            "respect": self.respect,
            "circle": self.circle,
            "health": self.health,
            "node_id": self.node_id or location,
        }

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "description": self.description,
            "tags": list(self.tags),
            "affinity": self.affinity,
            "trust": self.trust,
            "fear": self.fear,
            "respect": self.respect,
            "circle": self.circle,
            "health": self.health,
            "node_id": self.node_id,
        }


@dataclass(frozen=True)
class SceneSpec:
    """Сцена: локация, локальная публика, работы и правила."""

    id: str
    label: str
    description: str = ""
    location: str = ""
    tags: Tuple[str, ...] = ()
    public: Tuple[LocalPublic, ...] = ()
    works: Tuple[str, ...] = ()
    requires: Mapping = field(default_factory=dict)
    exit: Mapping = field(default_factory=dict)
    time: Mapping = field(default_factory=dict)
    remote: bool = False
    meta: Mapping = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise SceneError("сцена должна быть объектом")
        scene_id = _text(data.get("id")).strip()
        if not scene_id:
            raise SceneError("у сцены нужен id")
        location = _text(data.get("location") or data.get("node_id"))
        public = []
        seen = set()
        for entry in data.get("public") or ():
            person = LocalPublic.from_dict(entry, location)
            if person.id in seen:
                raise SceneError(
                    "%s: публика %r объявлена дважды"
                    % (scene_id, person.id)
                )
            seen.add(person.id)
            public.append(person)
        requires = data.get("requires") or data.get("entry") or {}
        exit_rules = data.get("exit") or {}
        scene_time = data.get("time") or {}
        if not isinstance(requires, Mapping):
            raise SceneError("%s: requires должен быть объектом" % scene_id)
        if not isinstance(exit_rules, Mapping):
            raise SceneError("%s: exit должен быть объектом" % scene_id)
        if not isinstance(scene_time, Mapping):
            raise SceneError("%s: time должен быть объектом" % scene_id)
        return cls(
            id=scene_id,
            label=_text(data.get("label"), scene_id),
            description=_text(data.get("description")),
            location=location,
            tags=_string_list(data.get("tags")),
            public=tuple(public),
            works=_string_list(data.get("works")),
            requires=dict(requires),
            exit=dict(exit_rules),
            time=dict(scene_time),
            remote=bool(data.get("remote", False)),
            meta=dict(data.get("meta") or {}),
        )

    def allows(
        self,
        *,
        attached=True,
        office=None,
        day=1,
        tags=(),
        has_office=None,
    ):
        """Проверить правила входа; вернуть ``(bool, reason)``."""
        rules = self.requires or {}
        if rules.get("attached") is True and not attached:
            return False, "сцена требует должности"
        office = office or {}
        office_id = _text(office.get("id"))
        domain = _text(office.get("domain"))
        allowed_offices = set(_string_list(rules.get("office_ids")))
        if allowed_offices and office_id not in allowed_offices:
            return False, "сцена открыта другой должности"
        allowed_domains = set(_string_list(rules.get("domains")))
        if allowed_domains and domain not in allowed_domains:
            return False, "сцена открыта другому домену"
        if rules.get("has_office") is True and not office_id:
            return False, "сцена требует должности"
        if rules.get("has_office") is False and office_id:
            return False, "сцена только для людей без должности"
        minimum = rules.get("day_min")
        if minimum is not None and _integer(day, 1) < _integer(minimum):
            return False, "сцена ещё закрыта"
        maximum = rules.get("day_max")
        if maximum is not None and _integer(day, 1) > _integer(maximum):
            return False, "сцена уже закрыта"
        wanted = set(_string_list(rules.get("tags_any")))
        if wanted and not wanted.intersection(tags or ()):
            return False, "не хватает тега сцены"
        if has_office is not None and rules.get("has_office") is not None:
            if bool(has_office) != bool(rules.get("has_office")):
                return False, "сцена не подходит по должности"
        return True, ""

    def exit_reason(self, *, day=1, entered_day=None, attached=True):
        rules = self.exit or {}
        if rules.get("when_detached") and not attached:
            return "сцена закрыта без должности"
        after_days = rules.get("after_days")
        if after_days is not None and entered_day is not None:
            if _integer(day, 1) - _integer(entered_day) >= _integer(
                after_days, 1
            ):
                return "сцена закончилась"
        return ""

    def allows_action(self, action_id):
        return not self.works or _text(action_id) in self.works

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "location": self.location,
            "tags": list(self.tags),
            "public": [person.as_dict() for person in self.public],
            "works": list(self.works),
            "requires": dict(self.requires),
            "exit": dict(self.exit),
            "time": dict(self.time),
            "remote": self.remote,
            "meta": dict(self.meta),
        }


@dataclass
class SceneCatalog:
    """Каталог сцен, загруженный из JSON или списка."""

    scenes: dict = field(default_factory=dict)
    source: str = ""

    @classmethod
    def from_list(cls, items: Iterable, source="scenes"):
        catalog = cls(source=str(source))
        seen = set()
        for item in items or ():
            scene = SceneSpec.from_dict(item)
            if scene.id in seen:
                raise SceneError(
                    "%s: сцена %r объявлена дважды"
                    % (catalog.source, scene.id)
                )
            seen.add(scene.id)
            catalog.scenes[scene.id] = scene
        return catalog

    @classmethod
    def from_data(cls, data, source="scenes"):
        if isinstance(data, Mapping):
            if "scenes" in data:
                return cls.from_list(data.get("scenes") or (), source)
            if "id" in data:
                return cls.from_list([data], source)
            raise SceneError("%s: нужен список scenes" % source)
        return cls.from_list(data, source)

    @classmethod
    def load(cls, path=None):
        if path is None:
            path = (
                Path(__file__).resolve().parents[1]
                / "configs"
                / "worlds"
                / "scenes"
            )
        target = Path(path)
        files = (
            sorted(target.glob("*.json"))
            if target.is_dir()
            else [target]
        )
        merged = {}
        for file_path in files:
            try:
                with open(file_path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError) as exc:
                raise SceneError(
                    "не удалось прочитать сцену %s: %s" % (file_path, exc)
                )
            catalog = cls.from_data(data, str(file_path))
            for scene_id, scene in catalog.scenes.items():
                if scene_id in merged:
                    raise SceneError(
                        "сцена %r объявлена дважды: %s"
                        % (scene_id, file_path)
                    )
                merged[scene_id] = scene
        return cls(merged, str(path))

    def __contains__(self, scene_id):
        return _text(scene_id) in self.scenes

    def __iter__(self):
        return iter(self.all())

    def __len__(self):
        return len(self.scenes)

    def get(self, scene_id):
        return self.scenes.get(_text(scene_id))

    def require(self, scene_id):
        scene = self.get(scene_id)
        if scene is None:
            raise SceneError("нет сцены %r" % (scene_id,))
        return scene

    def all(self):
        return sorted(
            self.scenes.values(), key=lambda scene: (scene.location, scene.id)
        )

    def for_node(self, node_id):
        node_id = _text(node_id)
        if not node_id:
            return None
        for scene in self.all():
            if scene.location == node_id:
                return scene
        return None

    def for_tags(self, tags: Sequence[str] = ()):
        wanted = set(tags or ())
        if not wanted:
            return self.all()
        scored = []
        for scene in self.all():
            score = len(wanted.intersection(scene.tags))
            if score:
                scored.append((-score, scene.label, scene.id, scene))
        return [item[-1] for item in sorted(scored)]


__all__ = [
    "SCENE_SCHEMA_VERSION",
    "LocalPublic",
    "SceneCatalog",
    "SceneError",
    "SceneSpec",
]
