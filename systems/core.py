"""Общие примитивы системных автоматов.

Системный автомат — это обычный ``automata.model.Automaton`` плюс текущее
состояние и история переходов. Слой не рисует граф и не знает pygame: он нужен
среде и драматургу, чтобы их поведение было выражено тем же языком состояний и
переходов, что и остальные автоматы проекта.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from automata.model import Automaton, Transition, valid_id


class SystemError(ValueError):
    """Ошибка конфигурации или работы системного автомата."""


def clamp(value, low=0.0, high=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float(low)
    if value != value:  # NaN
        return float(low)
    return max(float(low), min(float(high), value))


def text(value, default=""):
    if value is None:
        return default
    return str(value)


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


@dataclass
class SystemAutomaton:
    """Обёртка над ``Automaton`` с текущим состоянием.

    ``fire(event)`` ищет исходящий переход из текущего состояния, у которого
    совпадает ``event`` (и, если задан, ``guard``). Это минимальный протокол,
    достаточный для среды и драматурга.
    """

    id: str
    name: str
    automaton: Automaton
    current: str = ""
    history: List[dict] = field(default_factory=list)

    def __post_init__(self):
        self.id = str(self.id or "").strip()
        if not self.id:
            raise SystemError("у системного автомата должен быть id")
        if not isinstance(self.automaton, Automaton):
            raise SystemError("%s: automaton должен быть Automaton" % self.id)
        if not self.automaton.states:
            raise SystemError("%s: у автомата нет состояний" % self.id)
        if not self.current:
            initial = self.automaton.initial_states
            self.current = initial[0].id if initial else \
                self.automaton.states[0].id
        if self.automaton.state(self.current) is None:
            raise SystemError("%s: текущего состояния %r нет"
                              % (self.id, self.current))

    @property
    def state(self):
        return self.automaton.state(self.current)

    def state_name(self):
        state = self.state
        return state.name if state is not None else self.current

    def outgoing(self):
        return self.automaton.outgoing(self.current)

    def can_fire(self, event, guard=None):
        return any(
            transition.event == event and
            (guard is None or transition.guard == guard)
            for transition in self.outgoing()
        )

    def fire(self, event, guard=None):
        """Совершить первый подходящий переход; вернуть его или ``None``."""
        for transition in self.outgoing():
            if transition.event != event:
                continue
            if guard is not None and transition.guard != guard:
                continue
            previous = self.current
            self.current = transition.target
            self.history.append({
                "from": previous,
                "to": self.current,
                "event": transition.event,
                "transition": transition.id,
            })
            self.history = self.history[-200:]
            return transition
        return None

    def set_state(self, state_id):
        state_id = str(state_id or "").strip()
        if self.automaton.state(state_id) is None:
            raise SystemError("%s: нет состояния %r" % (self.id, state_id))
        if state_id == self.current:
            return False
        previous = self.current
        self.current = state_id
        self.history.append({
            "from": previous,
            "to": state_id,
            "event": "set_state",
            "transition": None,
        })
        self.history = self.history[-200:]
        return True

    def snapshot(self):
        return {
            "id": self.id,
            "name": self.name,
            "current": self.current,
            "state_name": self.state_name(),
            "history": [dict(item) for item in self.history[-20:]],
            "automaton": self.automaton.to_dict(),
        }


def make_state_id(value, prefix="s"):
    """Проверить/нормализовать id состояния из конфига."""
    state_id = text(value).strip()
    if not valid_id(state_id):
        raise SystemError("некорректный id состояния: %r" % (state_id,))
    return state_id


def find_transition(automaton: Automaton, transition_id):
    return automaton.transition(text(transition_id).strip())


__all__ = [
    "SystemError", "SystemAutomaton", "clamp", "text", "as_float",
    "as_int", "as_list", "make_state_id", "find_transition",
]
