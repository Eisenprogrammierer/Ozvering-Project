from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import random
import re
from typing import Dict, Mapping, Optional, Tuple

from .core import SystemError, as_float, as_int, clamp, text


class EventError(SystemError):
    pass


_SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_FALLBACKS = {
    "actor": "безымянный герой",
    "target": "неизвестный",
    "child": "ребёнок",
    "rival": "соперник",
    "organization": "безымянная организация",
    "rival_organization": "соперники",
    "place": "на окраине",
    "object": "старая вещь",
    "cause": "роковая случайность",
    "consequence": "последствия ещё впереди",
    "amount": "немало",
}
_PLACES = (
    "«Старая переправа»",
    "«Лесная дорога»",
    "«Горное ущелье»",
    "«Городская площадь»",
    "«Речной брод»",
    "«Заброшенная крепость»",
    "«Пыльный тракт»",
    "«Приграничная деревня»",
    "«Поле боя»",
    "«Подземелья под городом»",
    "«Берег холодного моря»",
)
_OBJECTS = (
    "старая печать",
    "кованый ларец",
    "письмо без подписи",
    "обломок клинка",
    "карта с пометками",
    "медальон с чужим гербом",
    "книга в потёртом переплёте",
    "ключ неизвестной формы",
    "фляга с клеймом",
    "связка долговых расписок",
)
_CAUSES = (
    "внезапная буря",
    "ошибка разведки",
    "старый долг",
    "чужая интрига",
    "голод",
    "предательство",
    "роковая случайность",
    "забытое пророчество",
)
_AMOUNTS = (
    "немало",
    "тридцать монет",
    "целое состояние",
    "сущий пустяк",
    "двадцать возов зерна",
    "годовой доход",
    "цена крови",
)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise EventError("конфиг не найден: %s" % path)
    except Exception as exc:
        raise EventError("не удалось прочитать %s: %s" % (path, exc))


def _tags(value):
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        return (str(value),)
    return tuple(str(item).strip() for item in value if str(item).strip())


@dataclass(frozen=True)
class EventTemplate:
    id: str
    category: str
    title: str
    tags: Tuple[str, ...]
    severity: float
    stakes: float
    weight: float
    templates: Tuple[str, ...]

    @classmethod
    def from_data(cls, data, index=0, source="event"):
        if not isinstance(data, Mapping):
            raise EventError("%s[%d] должен быть объектом" % (source, index))
        event_id = text(data.get("id")).strip()
        if not event_id:
            raise EventError("%s[%d]: пустой id" % (source, index))
        category = text(data.get("category")).strip()
        if not category:
            raise EventError("%s: пустая category" % event_id)
        raw = data.get("templates")
        if raw is None:
            raw = [data.get("template")]
        if not isinstance(raw, (list, tuple)):
            raw = [raw]
        templates = tuple(
            str(item).strip() for item in raw if str(item or "").strip()
        )
        if not templates:
            raise EventError("%s: нет templates" % event_id)
        return cls(
            id=event_id,
            category=category,
            title=str(data.get("title") or event_id),
            tags=_tags(data.get("tags")),
            severity=clamp(data.get("severity", 0.5), 0.0, 1.0),
            stakes=clamp(data.get("stakes", 0.5), 0.0, 1.0),
            weight=max(0.0, as_float(data.get("weight", 1.0), 1.0)),
            templates=templates,
        )

    @property
    def slots(self):
        return tuple(
            sorted(
                {
                    match.group(1)
                    for template in self.templates
                    for match in _SLOT.finditer(template)
                }
            )
        )

    def as_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "tags": list(self.tags),
            "severity": self.severity,
            "stakes": self.stakes,
            "weight": self.weight,
            "templates": list(self.templates),
        }


@dataclass(frozen=True)
class GameEvent:
    id: str
    category: str
    title: str
    text: str
    tags: Tuple[str, ...]
    severity: float
    stakes: float
    template: str
    seed: int = 0
    context: Dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "text": self.text,
            "tags": list(self.tags),
            "severity": self.severity,
            "stakes": self.stakes,
            "template": self.template,
            "seed": self.seed,
            "context": dict(self.context),
        }

    def __str__(self):
        return self.text


class EventCatalog:

    def __init__(self, events, categories, root=None, schema=1):
        self.events = {event.id: event for event in events}
        if len(self.events) != len(events):
            raise EventError("повторяются id событий")
        self.categories = dict(categories)
        self.root = Path(root) if root is not None else None
        self.schema = as_int(schema, 1)
        self.validate()

    @classmethod
    def load(cls, root=None):
        root = Path(root) if root is not None else default_root()
        data = _read_json(root / "events.json")
        return cls.from_data(data, root=root)

    @classmethod
    def from_data(cls, data, root=None):
        if not isinstance(data, Mapping):
            raise EventError("events.json должен быть объектом")
        categories = data.get("categories") or {}
        if not isinstance(categories, Mapping):
            raise EventError("categories должен быть объектом")
        parsed_categories = {}
        for key, value in categories.items():
            key = str(key).strip()
            if not key:
                raise EventError("пустая категория")
            if isinstance(value, Mapping):
                parsed_categories[key] = {
                    "label": str(value.get("label") or key),
                    "weight": max(
                        0.0, as_float(value.get("weight", 1.0), 1.0)
                    ),
                }
            else:
                parsed_categories[key] = {
                    "label": str(value or key),
                    "weight": 1.0,
                }
        raw = data.get("events") or ()
        if not isinstance(raw, (list, tuple)):
            raise EventError("events должен быть списком")
        events = [
            EventTemplate.from_data(item, number, "events")
            for number, item in enumerate(raw)
        ]
        return cls(
            events, parsed_categories, root=root, schema=data.get("schema", 1)
        )

    def validate(self):
        if not self.events:
            raise EventError("нет ни одного события")
        if not self.categories:
            raise EventError("нет ни одной категории")
        for event in self.events.values():
            if event.category not in self.categories:
                raise EventError(
                    "%s: неизвестная категория %r" % (event.id, event.category)
                )
        return self

    def event(self, event_id):
        if event_id not in self.events:
            raise EventError("нет события %r" % (event_id,))
        return self.events[event_id]

    def event_ids(self):
        return sorted(self.events)

    def category_ids(self):
        return sorted(self.categories)

    def events_in(self, category=None, tags=None):
        wanted_tags = set(tags or ())
        result = []
        for event_id in self.event_ids():
            event = self.events[event_id]
            if category and event.category != category:
                continue
            if wanted_tags and not wanted_tags.intersection(event.tags):
                continue
            result.append(event)
        return result

    def as_dict(self):
        return {
            "schema": self.schema,
            "categories": {
                key: dict(value) for key, value in self.categories.items()
            },
            "events": [self.events[key].as_dict() for key in self.event_ids()],
        }


def _as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if hasattr(value, "text"):
        return str(value.text).strip()
    if hasattr(value, "name"):
        return str(value.name).strip()
    return str(value).strip()


class EventTextGenerator:

    def __init__(
        self,
        catalog: Optional[EventCatalog] = None,
        seed=0,
        people=None,
        organizations=None,
        auto_names=True,
    ):
        self.catalog = catalog or default_catalog()
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.auto_names = bool(auto_names)
        if people is None and self.auto_names:
            from naming.people import PersonNameGenerator

            people = PersonNameGenerator(seed=self.seed)
        self.people = people
        if organizations is None and self.auto_names:
            try:
                from naming import NameGenerator

                organizations = NameGenerator(seed=self.seed)
            except Exception:
                organizations = None
        self.organizations = organizations

    def _rng(self, seed=None):
        return self.rng if seed is None else random.Random(int(seed))

    def _organization(self, rng, mode=None):
        if self.organizations is None:
            return None
        modes = (
            "order",
            "meaning",
            "exchange",
            "care",
            "knowledge",
            "provision",
            "status",
        )
        mode = mode or rng.choice(modes)
        try:
            item = self.organizations.automaton_name(
                mode, level=rng.choice((1, 2, 2, 3)), seed=rng.randrange(2**31)
            )
            return item.text
        except Exception:
            return None

    def default_context(self, seed=None, rng=None):
        rng = rng or self._rng(seed)
        base_seed = int(seed) if seed is not None else rng.randrange(2**31)
        values = {}
        if self.auto_names and self.people is not None:
            persons = self.people.generate_many(
                count=4, seed=rng.randrange(2**31)
            )
            names = [item.text for item in persons]
            while len(names) < 4:
                names.append("безымянный герой")
            values.update(
                {
                    "actor": names[0],
                    "target": names[1],
                    "child": names[2],
                    "rival": names[3],
                }
            )
        if self.auto_names and self.organizations is not None:
            first = self._organization(rng, "order")
            second = self._organization(rng, "status")
            if second == first:
                second = self._organization(rng, "meaning")
            values["organization"] = first
            values["rival_organization"] = second
        values.update(
            {
                "place": rng.choice(_PLACES),
                "object": rng.choice(_OBJECTS),
                "cause": rng.choice(_CAUSES),
                "amount": rng.choice(_AMOUNTS),
                "consequence": "последствия ещё впереди",
            }
        )
        values = {
            key: value
            for key, value in values.items()
            if value not in (None, "")
        }
        values["_seed"] = base_seed
        return values

    def render(self, event_id, context=None, seed=None):
        event = self.catalog.event(event_id)
        rng = self._rng(seed)
        template = rng.choice(event.templates)
        values = self.default_context(seed=seed, rng=rng)
        for key, value in (context or {}).items():
            rendered = _as_text(value)
            if rendered:
                values[str(key)] = rendered
        values.pop("_seed", None)

        def replace(match):
            key = match.group(1)
            return str(values.get(key) or _FALLBACKS.get(key, "неизвестно"))

        text = _SLOT.sub(replace, template)
        return GameEvent(
            id=event.id,
            category=event.category,
            title=event.title,
            text=text,
            tags=event.tags,
            severity=event.severity,
            stakes=event.stakes,
            template=template,
            seed=int(seed if seed is not None else self.seed),
            context=dict(values),
        )

    def generate(
        self, event_id=None, category=None, tags=None, context=None, seed=None
    ):
        if event_id:
            return self.render(event_id, context=context, seed=seed)
        rng = self._rng(seed)
        candidates = self.catalog.events_in(category=category, tags=tags)
        if not candidates:
            raise EventError(
                "нет событий для category=%r tags=%r" % (category, tags)
            )
        weights = [
            max(0.0, event.weight)
            * self.catalog.categories.get(event.category, {}).get(
                "weight", 1.0
            )
            * (0.5 + event.stakes)
            for event in candidates
        ]
        total = sum(weights)
        if total <= 0.0:
            selected = rng.choice(candidates)
        else:
            roll = rng.random() * total
            cursor = 0.0
            selected = candidates[-1]
            for event, weight in zip(candidates, weights):
                cursor += weight
                if roll <= cursor:
                    selected = event
                    break
        return self.render(
            selected.id,
            context=context,
            seed=seed if seed is not None else rng.randrange(2**31),
        )

    def generate_many(
        self, count=10, category=None, tags=None, context=None, seed=None
    ):
        rng = self._rng(seed)
        return [
            self.generate(
                category=category,
                tags=tags,
                context=context,
                seed=rng.randrange(2**31),
            )
            for _ in range(max(1, int(count)))
        ]


def default_root():
    return Path(__file__).resolve().parents[1] / "configs" / "systems"


_DEFAULT = None


def default_catalog():
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = EventCatalog.load()
    return _DEFAULT


__all__ = [
    "EventError",
    "EventTemplate",
    "GameEvent",
    "EventCatalog",
    "EventTextGenerator",
    "default_catalog",
    "default_root",
]
