"""Чистая модель конечного автомата для графического редактора.

Модель ничего не знает о pygame, предметной области и способе отрисовки. Это
обычный ориентированный граф: состояния (узлы), переходы (рёбра), координаты
для раскладки и два флага нотации — начальное и финальное состояние.

JSON-формат (``schema = 1``)::

    {
      "version": 1,
      "name": "Пример",
      "description": "",
      "states": [
        {"id": "s1", "name": "Ожидание", "x": 120, "y": 140,
         "initial": true, "final": false}
      ],
      "transitions": [
        {"id": "t1", "source": "s1", "target": "s2",
         "event": "старт", "guard": ""}
      ]
    }

Идентификаторы состояний и переходов — короткие латинские имена (``s1``,
``t1``). Имена состояний и подписи переходов могут быть любыми строками.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import re

SCHEMA = 1

#: Допустимые идентификаторы: латиница/цифры, без пробелов.
ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


class AutomatonError(ValueError):
    """Ошибка структуры автомата или некорректной операции."""


def slugify(value):
    """Превратить имя в безопасное имя файла (латиница, цифры, ``_``)."""
    text = str(value or "").strip().lower()
    text = "".join(_CYRILLIC.get(ch, ch) for ch in text)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return (text[:48].strip("_") or "automaton")


def valid_id(value):
    return bool(ID_RE.match(str(value or "")))


def _text(value, default=""):
    if value is None:
        return default
    return str(value)


def _coord(value, default=0):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return int(default)
    return max(-100000, min(100000, number))


@dataclass
class State:
    """Узел автомата."""

    id: str
    name: str = ""
    x: int = 0
    y: int = 0
    initial: bool = False
    final: bool = False

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "x": int(self.x),
            "y": int(self.y),
            "initial": bool(self.initial),
            "final": bool(self.final),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise AutomatonError("состояние должно быть объектом JSON")
        state_id = _text(data.get("id")).strip()
        if not valid_id(state_id):
            raise AutomatonError("некорректный id состояния: %r" % (state_id,))
        return cls(
            id=state_id,
            name=_text(data.get("name")),
            x=_coord(data.get("x")),
            y=_coord(data.get("y")),
            initial=bool(data.get("initial", False)),
            final=bool(data.get("final", False)),
        )


@dataclass
class Transition:
    """Направленное ребро автомата. ``event`` и ``guard`` — свободный текст."""

    id: str
    source: str
    target: str
    event: str = ""
    guard: str = ""

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "event": self.event,
            "guard": self.guard,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise AutomatonError("переход должен быть объектом JSON")
        transition_id = _text(data.get("id")).strip()
        if not valid_id(transition_id):
            raise AutomatonError("некорректный id перехода: %r"
                                 % (transition_id,))
        source = _text(data.get("source")).strip()
        target = _text(data.get("target")).strip()
        if not source or not target:
            raise AutomatonError("у перехода %r нет source/target"
                                 % (transition_id,))
        return cls(
            id=transition_id,
            source=source,
            target=target,
            event=_text(data.get("event")),
            guard=_text(data.get("guard")),
        )


@dataclass
class Issue:
    """Замечание проверки структуры."""

    code: str
    level: str            # "error" | "warning"
    message: str

    @property
    def is_error(self):
        return self.level == "error"


@dataclass
class Automaton:
    """Конечный автомат: список состояний и переходов + метаданные."""

    name: str = "Без названия"
    description: str = ""
    states: list = field(default_factory=list)
    transitions: list = field(default_factory=list)

    # --- поиск ----------------------------------------------------------
    def state(self, state_id):
        for item in self.states:
            if item.id == state_id:
                return item
        return None

    def transition(self, transition_id):
        for item in self.transitions:
            if item.id == transition_id:
                return item
        return None

    def outgoing(self, state_id):
        return [t for t in self.transitions if t.source == state_id]

    def incoming(self, state_id):
        return [t for t in self.transitions if t.target == state_id]

    @property
    def initial_states(self):
        return [s for s in self.states if s.initial]

    @property
    def final_states(self):
        return [s for s in self.states if s.final]

    # --- идентификаторы -------------------------------------------------
    def _next_state_id(self):
        used = {s.id for s in self.states}
        number = 1
        while "s%d" % number in used:
            number += 1
        return "s%d" % number

    def _next_transition_id(self):
        used = {t.id for t in self.transitions}
        number = 1
        while "t%d" % number in used:
            number += 1
        return "t%d" % number

    # --- операции -------------------------------------------------------
    def add_state(self, name="", x=0, y=0, initial=False, final=False):
        state = State(self._next_state_id(), _text(name), _coord(x),
                      _coord(y), bool(initial), bool(final))
        if state.initial:
            for other in self.states:
                other.initial = False
        self.states.append(state)
        return state

    def remove_state(self, state_id):
        state = self.state(state_id)
        if state is None:
            return False
        self.states.remove(state)
        self.transitions = [t for t in self.transitions
                            if t.source != state_id and t.target != state_id]
        return True

    def add_transition(self, source, target, event="", guard=""):
        if self.state(source) is None:
            raise AutomatonError("нет исходного состояния %r" % (source,))
        if self.state(target) is None:
            raise AutomatonError("нет целевого состояния %r" % (target,))
        transition = Transition(self._next_transition_id(), source, target,
                                _text(event), _text(guard))
        self.transitions.append(transition)
        return transition

    def remove_transition(self, transition_id):
        transition = self.transition(transition_id)
        if transition is None:
            return False
        self.transitions.remove(transition)
        return True

    def rename_state(self, state_id, new_id):
        state = self.state(state_id)
        if state is None:
            raise AutomatonError("нет состояния %r" % (state_id,))
        new_id = _text(new_id).strip()
        if not valid_id(new_id):
            raise AutomatonError(
                "id: латиница/цифры, первый символ — буква или «_»")
        if new_id == state_id:
            return state
        if self.state(new_id) is not None:
            raise AutomatonError("состояние с id %r уже существует" % (new_id,))
        state.id = new_id
        for transition in self.transitions:
            if transition.source == state_id:
                transition.source = new_id
            if transition.target == state_id:
                transition.target = new_id
        return state

    def set_initial(self, state_id, value=True):
        state = self.state(state_id)
        if state is None:
            raise AutomatonError("нет состояния %r" % (state_id,))
        if value:
            for other in self.states:
                other.initial = False
            state.initial = True
        else:
            state.initial = False
        return state

    def set_final(self, state_id, value=True):
        state = self.state(state_id)
        if state is None:
            raise AutomatonError("нет состояния %r" % (state_id,))
        state.final = bool(value)
        return state

    def move_state(self, state_id, x, y):
        state = self.state(state_id)
        if state is None:
            raise AutomatonError("нет состояния %r" % (state_id,))
        state.x = _coord(x)
        state.y = _coord(y)
        return state

    # --- проверка -------------------------------------------------------
    def reachable_ids(self):
        """Множество состояний, достижимых из начального (или пустое)."""
        starts = [s.id for s in self.states if s.initial]
        if not starts:
            return set()
        seen = set(starts)
        todo = list(starts)
        while todo:
            current = todo.pop()
            for transition in self.transitions:
                if transition.source != current:
                    continue
                if (self.state(transition.target) is not None
                        and transition.target not in seen):
                    seen.add(transition.target)
                    todo.append(transition.target)
        return seen

    def validate(self):
        """Вернуть список ``Issue``; ошибки — нарушения структуры."""
        issues = []
        if not self.states:
            issues.append(Issue("empty", "error",
                                "В автомате нет ни одного состояния."))
            return issues

        state_ids = [s.id for s in self.states]
        transition_ids = [t.id for t in self.transitions]
        if len(set(state_ids)) != len(state_ids):
            issues.append(Issue("duplicate_state", "error",
                                "Повторяются идентификаторы состояний."))
        if len(set(transition_ids)) != len(transition_ids):
            issues.append(Issue("duplicate_transition", "error",
                                "Повторяются идентификаторы переходов."))

        initials = [s.id for s in self.states if s.initial]
        if not initials:
            issues.append(Issue("no_initial", "warning",
                                "Не выбрано начальное состояние."))
        elif len(initials) > 1:
            issues.append(Issue(
                "multiple_initial", "error",
                "Начальных состояний больше одного: %s."
                % ", ".join(initials)))

        known = set(state_ids)
        broken = False
        for transition in self.transitions:
            missing = []
            if transition.source not in known:
                missing.append("source=%s" % transition.source)
            if transition.target not in known:
                missing.append("target=%s" % transition.target)
            if missing:
                broken = True
                issues.append(Issue(
                    "missing_state", "error",
                    "Переход %s ссылается на отсутствующее состояние (%s)."
                    % (transition.id, ", ".join(missing))))

        pairs = {}
        for transition in self.transitions:
            key = (transition.source, transition.target, transition.event)
            pairs[key] = pairs.get(key, 0) + 1
        for (source, target, event), count in pairs.items():
            if count > 1:
                issues.append(Issue(
                    "duplicate_edge", "warning",
                    "Переходы %s → %s с подписью «%s» повторяются (%d)."
                    % (source, target, event or "—", count)))

        if initials and not broken:
            reachable = self.reachable_ids()
            unreachable = [s.id for s in self.states if s.id not in reachable]
            if unreachable:
                issues.append(Issue(
                    "unreachable", "warning",
                    "Недостижимы из начального: %s."
                    % ", ".join(unreachable)))

        if not self.final_states:
            issues.append(Issue("no_final", "warning",
                                "Не отмечено ни одного финального состояния."))

        for state in self.states:
            if state.final:
                continue
            if not any(t.source == state.id for t in self.transitions):
                issues.append(Issue(
                    "dead_end", "warning",
                    "У состояния %s нет исходящих переходов." % state.id))

        return issues

    # --- сериализация ---------------------------------------------------
    def to_dict(self):
        return {
            "version": SCHEMA,
            "name": self.name,
            "description": self.description,
            "states": [s.to_dict() for s in self.states],
            "transitions": [t.to_dict() for t in self.transitions],
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise AutomatonError("корень JSON должен быть объектом")
        raw_states = data.get("states", [])
        raw_transitions = data.get("transitions", [])
        if not isinstance(raw_states, list):
            raise AutomatonError("поле states должно быть массивом")
        if not isinstance(raw_transitions, list):
            raise AutomatonError("поле transitions должно быть массивом")

        states = [State.from_dict(item) for item in raw_states]
        transitions = [Transition.from_dict(item) for item in raw_transitions]
        ids = [s.id for s in states]
        if len(set(ids)) != len(ids):
            raise AutomatonError("повторяющиеся id состояний")
        tids = [t.id for t in transitions]
        if len(set(tids)) != len(tids):
            raise AutomatonError("повторяющиеся id переходов")

        automaton = cls(
            name=_text(data.get("name"), "Без названия") or "Без названия",
            description=_text(data.get("description")),
            states=states,
            transitions=transitions,
        )
        # В файле может быть несколько initial: сохраняем как есть, чтобы
        # редактор мог показать ошибку и дать её исправить.
        return automaton

    def clone(self):
        return Automaton.from_dict(self.to_dict())

    def bounds(self):
        """Габариты по координатам верхних левых углов состояний."""
        if not self.states:
            return None
        xs = [s.x for s in self.states]
        ys = [s.y for s in self.states]
        return (min(xs), min(ys), max(xs), max(ys))

    def counts(self):
        return len(self.states), len(self.transitions)


class History:
    """История снимков документа для отмены/повтора."""

    def __init__(self, initial=None, limit=100):
        self.limit = max(2, int(limit))
        self._items = []
        self.index = -1
        if initial is not None:
            self.reset(initial)

    def reset(self, snapshot):
        self._items = [deepcopy(snapshot)]
        self.index = 0

    def push(self, snapshot):
        """Добавить снимок; вернуть True, если история изменилась."""
        if not self._items:
            self.reset(snapshot)
            return True
        snapshot = deepcopy(snapshot)
        if snapshot == self._items[self.index]:
            return False
        self._items = self._items[:self.index + 1]
        self._items.append(snapshot)
        if len(self._items) > self.limit:
            drop = len(self._items) - self.limit
            self._items = self._items[drop:]
        self.index = len(self._items) - 1
        return True

    def undo(self):
        if self.index <= 0:
            return None
        self.index -= 1
        return deepcopy(self._items[self.index])

    def redo(self):
        if self.index >= len(self._items) - 1:
            return None
        self.index += 1
        return deepcopy(self._items[self.index])

    @property
    def can_undo(self):
        return self.index > 0

    @property
    def can_redo(self):
        return 0 <= self.index < len(self._items) - 1

    def __len__(self):
        return len(self._items)
