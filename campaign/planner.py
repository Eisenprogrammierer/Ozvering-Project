"""Очередь намерений кампании — первый срез real-time-планировщика.

Кампания остаётся дневной: `WorldEngine.end_day()` — единица хода мира.
Но события мира не обязаны происходить ровно в момент действия игрока.
`IntentQueue` хранит отложенные намерения (кто, что, к какому дню) и
исполняет их в начале соответствующего дня. Это даёт три вещи, которых
не было в чисто дневном цикле:

- **непрерывность** — намерение, назначенное на день `N`, сработает, даже
  если игрок пропустил день через фон/оффлайн-догон;
- **автономию** — персонаж с `autonomous: true` сам назначает контакты
  по своему периоду, а не ждёт действия игрока;
- **персистентность** — очередь входит в снимок мира, поэтому отложенные
  события переживают сохранение и загрузку.

Границы первого среза: намерения исполняются на границе дня, а не внутри
непрерывного таймера; нет приоритетов реального времени, отмены по
условию и полноценной политики персонажей. Это описано в `docs/TODO.md`.
"""

from dataclasses import dataclass, field

MAX_INTENTS = 64
AUTONOMY_PERIOD = 3
KNOWN_KINDS = ("message", "contact")


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


@dataclass(frozen=True)
class Intent:
    """Отложенное намерение мира.

    `due_day` — день кампании, в начале которого намерение исполняется.
    `kind` — `message` (только запись в журнал) или `contact`
    (персонаж `actor` сам выходит на связь и применяет `payload["effects"]`).
    """

    due_day: int
    kind: str
    actor: str = ""
    target: str = ""
    payload: dict = field(default_factory=dict)
    source: str = "world"

    def to_dict(self):
        return {
            "due_day": int(self.due_day),
            "kind": str(self.kind),
            "actor": str(self.actor),
            "target": str(self.target),
            "payload": dict(self.payload),
            "source": str(self.source),
        }

    @classmethod
    def from_dict(cls, raw):
        raw = raw or {}
        payload = raw.get("payload")
        return cls(
            due_day=_as_int(raw.get("due_day"), 0),
            kind=str(raw.get("kind") or ""),
            actor=str(raw.get("actor") or ""),
            target=str(raw.get("target") or ""),
            payload=dict(payload) if isinstance(payload, dict) else {},
            source=str(raw.get("source") or "world"),
        )


class IntentQueue:
    """Ограниченная очередь намерений, отсортированная по дню."""

    def __init__(self, items=None, limit=MAX_INTENTS):
        self.limit = max(1, int(limit))
        self.items = []
        for item in items or ():
            intent = item if isinstance(item, Intent) else Intent.from_dict(item)
            if intent.kind in KNOWN_KINDS:
                self.items.append(intent)
        self._sort()
        self._trim()

    def _sort(self):
        # Стабильный порядок: день, затем вид и источник. Иначе одинаковые
        # снимки могли бы исполнять намерения в разном порядке.
        self.items.sort(
            key=lambda item: (item.due_day, item.kind, item.source, item.actor)
        )

    def _trim(self):
        # При переполнении отбрасываем самые далёкие намерения: близкие
        # события важнее для игрока, а «хвост» всё равно не виден.
        if len(self.items) > self.limit:
            del self.items[self.limit :]

    def __len__(self):
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def add(self, intent):
        """Добавить намерение; `None`, если очередь переполнена."""
        if not isinstance(intent, Intent):
            intent = Intent.from_dict(intent)
        if intent.kind not in KNOWN_KINDS:
            raise ValueError("неизвестный вид намерения: %r" % (intent.kind,))
        if len(self.items) >= self.limit:
            return None
        self.items.append(intent)
        self._sort()
        return intent

    def schedule(
        self,
        due_day,
        kind,
        actor="",
        target="",
        payload=None,
        source="world",
    ):
        return self.add(
            Intent(
                due_day=_as_int(due_day, 0),
                kind=str(kind),
                actor=str(actor or ""),
                target=str(target or ""),
                payload=dict(payload or {}),
                source=str(source or "world"),
            )
        )

    def has(self, **criteria):
        """Есть ли уже намерение с такими полями (защита от дублей)."""
        for item in self.items:
            if all(
                getattr(item, key, None) == value
                for key, value in criteria.items()
            ):
                return True
        return False

    def due(self, day):
        """Намерения, которые пора исполнить в начале `day`."""
        return [item for item in self.items if item.due_day <= int(day)]

    def pop_due(self, day):
        """Извлечь и вернуть намерения, срок которых наступил."""
        day = int(day)
        ready = self.due(day)
        if not ready:
            return []
        ready_ids = {id(item) for item in ready}
        self.items = [item for item in self.items if id(item) not in ready_ids]
        return ready

    def clear(self):
        self.items = []

    def to_list(self):
        return [item.to_dict() for item in self.items]

    def load(self, items):
        self.items = []
        for item in items or ():
            intent = item if isinstance(item, Intent) else Intent.from_dict(item)
            if intent.kind in KNOWN_KINDS:
                self.items.append(intent)
        self._sort()
        self._trim()
        return self

    def copy(self):
        return IntentQueue(self.to_list(), limit=self.limit)


__all__ = [
    "AUTONOMY_PERIOD",
    "Intent",
    "IntentQueue",
    "KNOWN_KINDS",
    "MAX_INTENTS",
]
