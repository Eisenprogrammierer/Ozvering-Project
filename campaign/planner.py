"""Очередь намерений кампании — real-time-планировщик (срезы 1–2).

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

Срез 2 (A4, 2026-10-31): у намерений появились **приоритеты** (`priority`,
больше = исполняется раньше в пределах одного дня), **отмена по условию**
(`cancel_when`: условие из легаси-полей персонажа, при истинности которого
намерение аннулируется перед исполнением) и **осмысленная политика
автономии**: персонаж выбирает вид контакта по своим отношениям и доверию
(сближение / примирение / дистанцирование), а исход бросается общей
функцией успеха `campaign_success_chance` — той же, что действует игрок.

Границы: намерения исполняются на границе дня (внутридневные тики — A5);
политика автономных структур (узлов) вне кадра остаётся открытой.
"""

from dataclasses import dataclass, field

MAX_INTENTS = 64
AUTONOMY_PERIOD = 3
KNOWN_KINDS = ("message", "contact")

# Диапазон приоритета: 0 — обычный фон, выше — срочные события.
PRIORITY_MIN = 0
PRIORITY_MAX = 9


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_priority(value, default=0):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(PRIORITY_MIN, min(PRIORITY_MAX, number))


def condition_holds(condition, character):
    """Проверить условие отмены намерения по легаси-полям персонажа.

    Формат: `{"field": "<поле>", "op": "<сравнение>", "value": <число>}`.
    Поддерживаются `lt/le/gt/ge/eq/ne` (синонимы `< <= > >= == !=`).
    Неизвестное поле или операция условием НЕ считаются (безопаснее
    исполнить намерение, чем молча его потерять).
    """
    if not isinstance(condition, dict) or character is None:
        return False
    field_name = str(condition.get("field") or "")
    if not field_name or field_name not in character:
        return False
    op = str(condition.get("op") or "lt").strip()
    aliases = {
        "<": "lt", "<=": "le", ">": "gt", ">=": "ge",
        "==": "eq", "!=": "ne",
    }
    op = aliases.get(op, op)
    try:
        left = float(character.get(field_name) or 0.0)
        right = float(condition.get("value"))
    except (TypeError, ValueError):
        return False
    if op == "lt":
        return left < right
    if op == "le":
        return left <= right
    if op == "gt":
        return left > right
    if op == "ge":
        return left >= right
    if op == "eq":
        return abs(left - right) < 1e-9
    if op == "ne":
        return abs(left - right) >= 1e-9
    return False


@dataclass(frozen=True)
class Intent:
    """Отложенное намерение мира.

    `due_day` — день кампании, в начале которого намерение исполняется.
    `kind` — `message` (только запись в журнал) или `contact`
    (персонаж `actor` сам выходит на связь и применяет `payload["effects"]`).
    `priority` — порядок исполнения внутри одного дня (больше = раньше).
    `cancel_when` — опциональное условие отмены (см. `condition_holds`);
    если к моменту исполнения оно истинно для актёра, намерение
    аннулируется без последствий.
    """

    due_day: int
    kind: str
    actor: str = ""
    target: str = ""
    payload: dict = field(default_factory=dict)
    source: str = "world"
    priority: int = 0
    cancel_when: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "due_day": int(self.due_day),
            "kind": str(self.kind),
            "actor": str(self.actor),
            "target": str(self.target),
            "payload": dict(self.payload),
            "source": str(self.source),
            "priority": _as_priority(self.priority),
            "cancel_when": dict(self.cancel_when),
        }

    @classmethod
    def from_dict(cls, raw):
        raw = raw or {}
        payload = raw.get("payload")
        cancel_when = raw.get("cancel_when")
        return cls(
            due_day=_as_int(raw.get("due_day"), 0),
            kind=str(raw.get("kind") or ""),
            actor=str(raw.get("actor") or ""),
            target=str(raw.get("target") or ""),
            payload=dict(payload) if isinstance(payload, dict) else {},
            source=str(raw.get("source") or "world"),
            priority=_as_priority(raw.get("priority")),
            cancel_when=(
                dict(cancel_when) if isinstance(cancel_when, dict) else {}
            ),
        )


class IntentQueue:
    """Ограниченная очередь намерений: день → приоритет → детерминированный хвост."""

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
        # Стабильный порядок: день, затем приоритет (срочные раньше),
        # затем вид/источник/актор. Иначе одинаковые снимки могли бы
        # исполнять намерения в разном порядке.
        self.items.sort(
            key=lambda item: (
                item.due_day,
                -_as_priority(item.priority),
                item.kind,
                item.source,
                item.actor,
            )
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
        priority=0,
        cancel_when=None,
    ):
        return self.add(
            Intent(
                due_day=_as_int(due_day, 0),
                kind=str(kind),
                actor=str(actor or ""),
                target=str(target or ""),
                payload=dict(payload or {}),
                source=str(source or "world"),
                priority=_as_priority(priority),
                cancel_when=(
                    dict(cancel_when) if isinstance(cancel_when, dict) else {}
                ),
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

    def cancel(self, **criteria):
        """Снять намерения, подходящие под критерии; вернуть число снятых.

        Пример: `queue.cancel(actor="c1", kind="contact")` — отменить все
        отложенные контакты персонажа `c1`. Используется сюжетом и
        реактивной логикой мира («игрок поссорился — контакт не состоится»).
        """
        before = len(self.items)
        self.items = [
            item
            for item in self.items
            if not all(
                getattr(item, key, None) == value
                for key, value in criteria.items()
            )
        ]
        return before - len(self.items)

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
    "PRIORITY_MAX",
    "PRIORITY_MIN",
    "condition_holds",
]
