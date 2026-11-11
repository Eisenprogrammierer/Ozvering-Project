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
class EventCondition:
    """Одно условие события; все условия списка объединяются через ``AND``.

    ``kind`` задаёт источник данных, ``key`` — конкретное поле, ``op`` —
    сравнение, ``value`` — порог. Для делений ``key`` — измерение, а
    ``value`` — идентификатор значения. Для убеждений дополнительно
    используются ``subject``/``predicate``/``object``.
    """

    kind: str
    key: str = ""
    op: str = ">="
    value: object = 0.0
    subject: str = ""
    predicate: str = ""
    object: str = ""
    negate: bool = False

    @classmethod
    def from_data(cls, data, index=0, source="conditions"):
        if not isinstance(data, Mapping):
            raise EventError("%s[%d] должен быть объектом" % (source, index))
        kind = text(data.get("kind") or data.get("type")).strip()
        if not kind:
            raise EventError("%s[%d]: пустой kind" % (source, index))
        present = kind in ("belief", "tag", "alive")
        if (
            present
            and "op" not in data
            and "value" not in data
            and "threshold" not in data
        ):
            # Для наличия убеждения/тега/жизни условие — это проверка
            # «да/нет», а не числовой порог по умолчанию.
            op = "=="
            value = True
        else:
            op = str(data.get("op") or ">=").strip()
            value = data.get("value", data.get("threshold", 0.0))
        if op not in (">=", "<=", ">", "<", "==", "!=", "in", "not in"):
            raise EventError(
                "%s[%d]: неизвестная операция %r" % (source, index, op)
            )
        return cls(
            kind=kind,
            key=str(data.get("key") or "").strip(),
            op=op,
            value=value,
            subject=str(data.get("subject") or "").strip(),
            predicate=str(data.get("predicate") or "").strip(),
            object=str(data.get("object") or "").strip(),
            negate=bool(data.get("negate", False)),
        )

    def evaluate(self, context):
        context = context if isinstance(context, Mapping) else {}
        actual = _condition_value(self, context)
        result = _compare(actual, self.op, self.value)
        return not result if self.negate else result

    def as_dict(self):
        return {
            "kind": self.kind,
            "key": self.key,
            "op": self.op,
            "value": self.value,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "negate": self.negate,
        }


def _condition_value(condition, context):
    kind = condition.kind
    key = condition.key
    if kind in ("need", "desire"):
        needs = context.get("needs") or {}
        if key:
            return needs.get(key, 0.0)
        return sum(float(v) for v in needs.values()) / max(1, len(needs))
    if kind == "trait":
        traits = context.get("traits") or context.get("personality") or {}
        return traits.get(key, 0.0)
    if kind == "division":
        divisions = context.get("divisions") or {}
        return divisions.get(key, "")
    if kind == "force":
        return context.get("force", 0.0)
    if kind == "energy":
        return context.get("energy", 0.0)
    if kind in ("condition", "sickness", "wound"):
        conditions = context.get("conditions") or {}
        if kind in ("sickness", "wound") and not key:
            key = kind
        return conditions.get(key, 0.0)
    if kind == "belief":
        beliefs = context.get("beliefs") or ()
        for item in beliefs:
            if isinstance(item, Mapping):
                s = item.get("subject")
                p = item.get("predicate")
                o = item.get("object")
            elif hasattr(item, "subject"):
                s, p, o = item.subject, item.predicate, item.object
            elif isinstance(item, (list, tuple)) and len(item) == 3:
                s, p, o = item
            else:
                continue
            if condition.subject and s != condition.subject:
                continue
            if condition.predicate and p != condition.predicate:
                continue
            if condition.object and o != condition.object:
                continue
            return True
        return False
    if kind == "tag":
        return key in set(context.get("tags") or ())
    if kind == "category":
        return context.get("category", "") == key
    if kind == "side":
        return context.get("side", "") == key
    if kind == "faction":
        return context.get("faction_id", "") == key
    if kind == "role":
        return context.get("role", "") == key
    if kind == "alive":
        return bool(context.get("alive", True))
    if kind == "time":
        return context.get("time", 0.0)
    if kind in context:
        return context.get(kind)
    return context.get(key, context.get(kind))


def _compare(actual, op, expected):
    try:
        if op == "in":
            return actual in (expected or ())
        if op == "not in":
            return actual not in (expected or ())
        if op == "==":
            return actual == expected
        if op == "!=":
            return actual != expected
        left = float(actual)
        right = float(expected)
    except (TypeError, ValueError):
        if op == "==":
            return str(actual) == str(expected)
        if op == "!=":
            return str(actual) != str(expected)
        return False
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    return False


@dataclass(frozen=True)
class EventVisibility:
    scope: str = "global"
    divisions: Tuple[str, ...] = ()
    sides: Tuple[str, ...] = ()
    factions: Tuple[str, ...] = ()
    roles: Tuple[str, ...] = ()
    min_force: float = 0.0
    max_force: float = 1.0
    min_energy: float = 0.0
    max_energy: float = 1.0

    @classmethod
    def from_data(cls, data):
        if data is None:
            return cls()
        if isinstance(data, str):
            return cls(scope=str(data).strip() or "global")
        if not isinstance(data, Mapping):
            raise EventError("visibility должен быть объектом или строкой")
        return cls(
            scope=str(data.get("scope") or "global").strip(),
            divisions=_tags(data.get("divisions")),
            sides=_tags(data.get("sides")),
            factions=_tags(data.get("factions")),
            roles=_tags(data.get("roles")),
            min_force=as_float(data.get("min_force", 0.0), 0.0),
            max_force=as_float(data.get("max_force", 1.0), 1.0),
            min_energy=as_float(data.get("min_energy", 0.0), 0.0),
            max_energy=as_float(data.get("max_energy", 1.0), 1.0),
        )

    def visible_to(self, viewer):
        viewer = viewer if isinstance(viewer, Mapping) else {}
        if self.scope == "hidden":
            return False
        if self.sides and str(viewer.get("side", "")) not in self.sides:
            return False
        if self.factions and str(
            viewer.get("faction_id", "")
        ) not in self.factions:
            return False
        if self.roles and str(viewer.get("role", "")) not in self.roles:
            return False
        if self.scope == "character" and not viewer.get("id"):
            return False
        tags = set(viewer.get("tags") or ())
        divisions = viewer.get("divisions") or {}
        for tag in self.divisions:
            if tag in tags:
                continue
            if ":" in tag:
                dimension, _, value = tag.partition(":")
                if str(divisions.get(dimension, "")) == value:
                    continue
            return False
        force = as_float(viewer.get("force", 0.0), 0.0)
        energy = as_float(viewer.get("energy", 0.0), 0.0)
        if not self.min_force <= force <= self.max_force:
            return False
        if not self.min_energy <= energy <= self.max_energy:
            return False
        return True

    def as_dict(self):
        return {
            "scope": self.scope,
            "divisions": list(self.divisions),
            "sides": list(self.sides),
            "factions": list(self.factions),
            "roles": list(self.roles),
            "min_force": self.min_force,
            "max_force": self.max_force,
            "min_energy": self.min_energy,
            "max_energy": self.max_energy,
        }


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
    conditions: Tuple[EventCondition, ...] = ()
    probability: float = 1.0
    visibility: EventVisibility = EventVisibility()
    speed: float = 0.0
    duration: float = 0.0
    cooldown: float = 0.0
    effects: Mapping = field(default_factory=dict)

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
        raw_conditions = data.get("conditions") or ()
        if not isinstance(raw_conditions, (list, tuple)):
            raw_conditions = [raw_conditions]
        conditions = tuple(
            EventCondition.from_data(
                item, number, "%s.conditions" % event_id
            )
            for number, item in enumerate(raw_conditions)
        )
        probability = data.get("probability", data.get("chance", 1.0))
        return cls(
            id=event_id,
            category=category,
            title=str(data.get("title") or event_id),
            tags=_tags(data.get("tags")),
            severity=clamp(data.get("severity", 0.5), 0.0, 1.0),
            stakes=clamp(data.get("stakes", 0.5), 0.0, 1.0),
            weight=max(0.0, as_float(data.get("weight", 1.0), 1.0)),
            templates=templates,
            conditions=conditions,
            probability=clamp(probability, 0.0, 1.0),
            visibility=EventVisibility.from_data(data.get("visibility")),
            speed=max(0.0, as_float(data.get("speed", 0.0), 0.0)),
            duration=max(0.0, as_float(data.get("duration", 0.0), 0.0)),
            cooldown=max(0.0, as_float(data.get("cooldown", 0.0), 0.0)),
            effects=dict(data.get("effects") or {}),
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

    def matches(self, context):
        return all(item.evaluate(context) for item in self.conditions)

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
            "conditions": [item.as_dict() for item in self.conditions],
            "probability": self.probability,
            "visibility": self.visibility.as_dict(),
            "speed": self.speed,
            "duration": self.duration,
            "cooldown": self.cooldown,
            "effects": dict(self.effects),
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

    def category_weight(self, category):
        return max(
            0.0,
            as_float(
                (self.categories.get(str(category)) or {}).get(
                    "weight", 1.0
                ),
                1.0,
            ),
        )

    def eligible(self, context=None, category=None, tags=None):
        """События, чьи условия выполнены для контекста."""
        context = context if isinstance(context, Mapping) else {}
        wanted = set(tags or ())
        result = []
        for event_id in self.event_ids():
            event = self.events[event_id]
            if category and event.category != category:
                continue
            if wanted and not wanted.intersection(event.tags):
                continue
            if not event.matches(context):
                continue
            result.append(event)
        return result

    def probability_shares(self, context=None, category=None, tags=None):
        """Нормированные доли вероятности для подходящих событий.

        Возвращает список ``(event, share)``; сумма долей равна ``1``.
        Вес события — ``weight × category.weight × probability``. Если все
        веса нулевые, доли распределяются равномерно.
        """
        events = self.eligible(context, category, tags)
        weights = []
        for event in events:
            weight = (
                max(0.0, event.weight)
                * self.category_weight(event.category)
                * max(0.0, min(1.0, event.probability))
            )
            weights.append(weight)
        total = sum(weights)
        if total <= 0.0:
            if not events:
                return []
            share = 1.0 / float(len(events))
            return [(event, share) for event in events]
        return [
            (event, weight / total)
            for event, weight in zip(events, weights)
        ]


@dataclass
class EventInstance:
    """Живой экземпляр события с таймингом и видимостью."""

    id: str
    template_id: str
    category: str
    title: str
    text: str
    severity: float
    stakes: float
    visibility: EventVisibility
    speed: float = 0.0
    duration: float = 0.0
    elapsed: float = 0.0
    context: Dict = field(default_factory=dict)
    effects: Mapping = field(default_factory=dict)
    active: bool = True
    visible_now: bool = True

    @property
    def age(self):
        return self.elapsed

    @property
    def mature(self):
        return self.elapsed + 1e-9 >= self.speed

    @property
    def remaining(self):
        if self.duration <= 0.0:
            return 0.0
        return max(0.0, self.speed + self.duration - self.elapsed)

    @property
    def progress(self):
        if self.duration <= 0.0:
            return 1.0 if self.mature else 0.0
        return max(
            0.0,
            min(1.0, (self.elapsed - self.speed) / self.duration),
        )

    def advance(self, seconds):
        if not self.active:
            return False
        self.elapsed += max(0.0, float(seconds))
        if self.mature and self.duration > 0.0:
            if self.elapsed + 1e-9 >= self.speed + self.duration:
                self.active = False
        elif self.duration <= 0.0 and self.mature:
            self.active = False
        return self.active

    def visible_to(self, viewer):
        self.visible_now = self.mature and self.visibility.visible_to(viewer)
        return self.visible_now

    def as_dict(self):
        return {
            "id": self.id,
            "template_id": self.template_id,
            "category": self.category,
            "title": self.title,
            "text": self.text,
            "severity": self.severity,
            "stakes": self.stakes,
            "visibility": self.visibility.as_dict(),
            "speed": self.speed,
            "duration": self.duration,
            "elapsed": round(self.elapsed, 6),
            "remaining": round(self.remaining, 6),
            "progress": round(self.progress, 6),
            "mature": bool(self.mature),
            "active": bool(self.active),
            "effects": dict(self.effects),
            "context": dict(self.context),
        }


class EventEngine:
    """Алгоритм событий: подбор, вероятность, скорость и длительность.

    Содержимое (тексты, условия, видимость, тайминг) приходит из
    ``events.json``. Код отвечает только за:

    1. фильтр по ``conditions``;
    2. розыгрыш по нормированной доле ``probability``;
    3. накопление ``speed`` до публикации;
    4. удержание события ``duration`` секунд;
    5. проверку ``visibility`` для конкретного зрителя.
    """

    def __init__(self, catalog=None, generator=None, seed=0):
        self.catalog = catalog or default_catalog()
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.generator = generator or EventTextGenerator(
            catalog=self.catalog, seed=self.seed
        )
        self.active: List[EventInstance] = []
        self.history: List[EventInstance] = []
        self._cooldowns: Dict[str, float] = {}
        self._counter = 0
        self.time = 0.0

    def _roll(self, event):
        return self.rng.random() <= max(0.0, min(1.0, event.probability))

    def pick(self, context=None, category=None, tags=None, rng=None):
        """Выбрать событие по условиям и долям вероятности."""
        rng = rng or self.rng
        shares = self.catalog.probability_shares(
            context=context, category=category, tags=tags
        )
        available = [
            (event, share)
            for event, share in shares
            if self._cooldowns.get(event.id, 0.0) <= self.time
        ]
        if not available:
            return None
        total = sum(share for _event, share in available)
        if total <= 0.0:
            event = rng.choice([item[0] for item in available])
        else:
            roll = rng.random() * total
            cursor = 0.0
            event = available[-1][0]
            for candidate, share in available:
                cursor += share
                if roll <= cursor:
                    event = candidate
                    break
        if not self._roll(event):
            return None
        return event

    def spawn(self, event, context=None, text=None, seed=None):
        self._counter += 1
        rendered = text
        if rendered is None:
            rendered = self.generator.render(
                event.id,
                context=context,
                seed=(
                    int(seed)
                    if seed is not None
                    else self.rng.randrange(2**31)
                ),
            )
        instance = EventInstance(
            id="event-%d" % self._counter,
            template_id=event.id,
            category=event.category,
            title=rendered.title,
            text=rendered.text,
            severity=rendered.severity,
            stakes=rendered.stakes,
            visibility=event.visibility,
            speed=event.speed,
            duration=event.duration,
            context=dict(rendered.context),
            effects=dict(event.effects),
        )
        if event.cooldown > 0.0:
            self._cooldowns[event.id] = self.time + event.cooldown
        if event.speed <= 0.0:
            self.active.append(instance)
        else:
            self.active.append(instance)
        self.history.append(instance)
        return instance

    def trigger(self, context=None, category=None, tags=None, seed=None):
        event = self.pick(context=context, category=category, tags=tags)
        if event is None:
            return None
        return self.spawn(event, context=context, seed=seed)

    def advance(self, seconds, context=None, category=None, tags=None):
        """Продвинуть время, вернуть новые и всё ещё активные события.

        ``seconds`` — длительность шага. Событие публикуется, когда
        накопленное время достигает ``speed``, и исчезает после
        ``speed + duration``. Вернувшийся список — только видимые и
        зрелые экземпляры.
        """
        self.time += max(0.0, float(seconds))
        finished = []
        for instance in list(self.active):
            instance.advance(seconds)
            if not instance.active:
                finished.append(instance)
                self.active.remove(instance)
        return self.visible(context)

    def visible(self, viewer=None):
        viewer = viewer if isinstance(viewer, Mapping) else {}
        return [
            instance
            for instance in self.active
            if instance.mature and instance.visibility.visible_to(viewer)
        ]

    def pending(self):
        return [item for item in self.active if not item.mature]

    def effects(self, viewer=None):
        """Суммарные эффекты зрелых видимых событий."""
        totals = {"force": 0.0, "energy": 0.0, "needs": {}, "conditions": {}}
        for instance in self.visible(viewer):
            for key, value in (instance.effects or {}).items():
                if key in ("force", "energy"):
                    try:
                        totals[key] += float(value)
                    except (TypeError, ValueError):
                        continue
                elif key == "needs":
                    for need, amount in (value or {}).items():
                        totals["needs"][str(need)] = totals["needs"].get(
                            str(need), 0.0
                        ) + as_float(amount, 0.0)
                elif key == "conditions":
                    for condition, amount in (value or {}).items():
                        totals["conditions"][
                            str(condition)
                        ] = totals["conditions"].get(
                            str(condition), 0.0
                        ) + as_float(amount, 0.0)
        return totals

    def snapshot(self):
        return {
            "time": round(self.time, 6),
            "active": [item.as_dict() for item in self.active],
            "history": [item.as_dict() for item in self.history[-32:]],
            "cooldowns": {
                key: round(value, 6)
                for key, value in self._cooldowns.items()
            },
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
    "EventCondition",
    "EventEngine",
    "EventError",
    "EventInstance",
    "EventTemplate",
    "EventVisibility",
    "GameEvent",
    "EventCatalog",
    "EventTextGenerator",
    "default_catalog",
    "default_root",
]
