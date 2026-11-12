"""Исполняемые автоматы кампании.

Автомат — данные: состояния, переходы, условия и эффекты лежат в
``configs/automata/*.json``. Модуль умеет две вещи:

* собрать граф для редактора/пресета (:class:`StateMachineDefinition`);
* исполнить жизненный цикл (:class:`StateMachine`) — проверить переходы по
  приоритету и выполнить ``on_enter``/``on_tick`` через единый движок
  эффектов.

События сюда не входят: автомат меняет состояние, событие только читает.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from .conditions import check_conditions
from .effects import apply_effects


class StateMachineError(ValueError):
    """Некорректный файл автомата или нарушение схемы."""


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _text(value, default=""):
    text = str(value or "").strip()
    return text or default


def _effects(value):
    """Нормализовать эффекты: один объект или список объектов."""
    items = _as_list(value)
    return [item for item in items if isinstance(item, Mapping)]


def _looks_like_machine(payload):
    """Отличить исполняемый автомат от графа редактора."""
    if not isinstance(payload, Mapping):
        return False
    if payload.get("schema") == 2:
        return True
    return (
        payload.get("kind") in ("faction", "organ", "subfaction")
        and isinstance(payload.get("states"), Mapping)
    )


@dataclass
class TransitionSpec:
    to: str
    when: object = None
    priority: int = 0
    event: str = ""
    guard: str = ""

    @classmethod
    def from_data(cls, data, source="transition"):
        data = _as_mapping(data)
        target = _text(data.get("to") or data.get("target"))
        if not target:
            raise StateMachineError("%s: пустой to" % source)
        try:
            priority = int(data.get("priority", 0))
        except (TypeError, ValueError):
            priority = 0
        return cls(
            to=target,
            when=data.get("when"),
            priority=priority,
            event=_text(data.get("event")),
            guard=_text(data.get("guard")),
        )

    def to_dict(self):
        return {
            "to": self.to,
            "priority": self.priority,
            "event": self.event,
            "guard": self.guard,
        }


@dataclass
class StateSpec:
    id: str
    label: str = ""
    x: int = 0
    y: int = 0
    initial: bool = False
    final: bool = False
    on_enter: List[dict] = field(default_factory=list)
    on_tick: List[dict] = field(default_factory=list)
    outputs: List[dict] = field(default_factory=list)
    transitions: List[TransitionSpec] = field(default_factory=list)

    @classmethod
    def from_data(cls, state_id, data):
        data = _as_mapping(data)
        state_id = _text(state_id)
        if not state_id:
            raise StateMachineError("состояние без id")
        try:
            x = int(round(float(data.get("x", 0))))
            y = int(round(float(data.get("y", 0))))
        except (TypeError, ValueError):
            x = y = 0
        transitions = [
            TransitionSpec.from_data(item, "%s.transitions[%d]" % (state_id, index))
            for index, item in enumerate(_as_list(data.get("transitions")))
        ]
        return cls(
            id=state_id,
            label=_text(data.get("label") or data.get("name"), state_id),
            x=x,
            y=y,
            initial=bool(data.get("initial", False)),
            final=bool(data.get("final", False)),
            on_enter=_effects(data.get("on_enter")),
            on_tick=_effects(data.get("on_tick")),
            outputs=_effects(data.get("outputs")),
            transitions=transitions,
        )

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "x": self.x,
            "y": self.y,
            "initial": self.initial,
            "final": self.final,
            "on_enter": list(self.on_enter),
            "on_tick": list(self.on_tick),
            "outputs": list(self.outputs),
            "transitions": [item.to_dict() for item in self.transitions],
        }


@dataclass
class StateMachineDefinition:
    id: str
    kind: str = "faction"
    name: str = ""
    description: str = ""
    initial: str = ""
    states: Dict[str, StateSpec] = field(default_factory=dict)
    handlers: Dict[str, dict] = field(default_factory=dict)
    inputs: Dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_data(cls, data, source="automaton"):
        data = _as_mapping(data)
        machine_id = _text(data.get("id"))
        if not machine_id:
            raise StateMachineError("%s: пустой id" % source)
        kind = _text(data.get("kind"), "faction")
        if kind not in ("faction", "organ", "subfaction"):
            raise StateMachineError(
                "%s: неизвестный kind %r" % (source, kind)
            )
        raw_states = _as_mapping(data.get("states"))
        if not raw_states:
            raise StateMachineError("%s: нет states" % source)
        states = {
            str(state_id): StateSpec.from_data(state_id, value)
            for state_id, value in raw_states.items()
        }
        initial = _text(data.get("initial"))
        if not initial:
            initial = next(
                (key for key, item in states.items() if item.initial),
                "",
            )
        if not initial and states:
            initial = next(iter(states))
        if initial not in states:
            raise StateMachineError(
                "%s: начальное состояние %r отсутствует" % (source, initial)
            )
        for state in states.values():
            for transition in state.transitions:
                if transition.to not in states:
                    raise StateMachineError(
                        "%s: переход %s → %r ведёт в никуда"
                        % (source, state.id, transition.to)
                    )
        machine = cls(
            id=machine_id,
            kind=kind,
            name=_text(data.get("name"), machine_id),
            description=_text(data.get("description")),
            initial=initial,
            states=states,
            handlers={
                str(key): dict(_as_mapping(value))
                for key, value in _as_mapping(
                    data.get("handlers")
                ).items()
            },
            inputs=dict(_as_mapping(data.get("inputs"))),
        )
        return machine

    @property
    def final_states(self):
        return [key for key, item in self.states.items() if item.final]

    def to_dict(self):
        return {
            "schema": 2,
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "initial": self.initial,
            "states": {
                key: item.to_dict() for key, item in self.states.items()
            },
            "handlers": dict(self.handlers),
            "inputs": dict(self.inputs),
        }


@dataclass
class StateMachine:
    definition: StateMachineDefinition
    state: str = ""
    history: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.state:
            self.state = self.definition.initial
        if self.state not in self.definition.states:
            raise StateMachineError(
                "нет состояния %r" % self.state
            )

    @property
    def id(self):
        return self.definition.id

    @classmethod
    def from_definition(cls, definition):
        return cls(definition=definition)

    def _apply(self, effects, context, actor, target, scale):
        reports = []
        for effect in _effects(effects):
            reports.append(
                apply_effects(
                    actor,
                    effect,
                    target=target,
                    scale=scale,
                    source="machine:%s" % self.id,
                )
            )
        return reports

    def tick(self, context=None, *, actor=None, target=None, scale=1.0):
        """Проверить переходы и выполнить текущее состояние.

        Возвращает список отчётов: ``{"from", "to", "effects"}`` для
        каждого перехода плюс отчёт ``on_tick``.
        """
        context = dict(context or {})
        context.setdefault("machine", self)
        context.setdefault("machine_id", self.id)
        if actor is not None:
            context.setdefault("faction", actor)
        current = self.definition.states.get(self.state)
        if current is None:
            raise StateMachineError("нет состояния %r" % self.state)
        reports = []
        reports.extend(
            self._apply(
                current.on_tick,
                context,
                actor,
                target,
                scale,
            )
        )
        for transition in sorted(
            current.transitions,
            key=lambda item: item.priority,
            reverse=True,
        ):
            if transition.when and check_conditions(
                transition.when, context
            ):
                continue
            previous = self.state
            self.state = transition.to
            self.history.append(previous)
            self.history = self.history[-64:]
            entered = self.definition.states[transition.to]
            reports.append(
                {
                    "machine": self.id,
                    "from": previous,
                    "to": self.state,
                    "effects": self._apply(
                        entered.on_enter,
                        context,
                        actor,
                        target,
                        scale,
                    ),
                }
            )
            break
        return reports

    def handle(self, event, context=None, *, actor=None, target=None, scale=1.0):
        """Выполнить обработчик события, если он объявлен."""
        payload = _as_mapping(self.definition.handlers.get(str(event)))
        if not payload:
            return []
        when = payload.get("when")
        context = dict(context or {})
        context.setdefault("event", str(event))
        if actor is not None:
            context.setdefault("faction", actor)
        if when and check_conditions(when, context):
            return []
        return self._apply(
            payload.get("effects"),
            context,
            actor,
            target,
            scale,
        )

    def to_dict(self):
        return {
            "id": self.id,
            "state": self.state,
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, data, definition):
        data = _as_mapping(data)
        return cls(
            definition=definition,
            state=_text(data.get("state"), definition.initial),
            history=[
                str(item) for item in _as_list(data.get("history"))
            ][-64:],
        )


@dataclass
class StateMachineCatalog:
    machines: Dict[str, StateMachineDefinition] = field(
        default_factory=dict
    )

    def add(self, definition):
        if definition.id in self.machines:
            raise StateMachineError(
                "повторяющийся id автомата %r" % definition.id
            )
        self.machines[definition.id] = definition
        return definition

    def get(self, machine_id):
        return self.machines.get(str(machine_id))

    def by_kind(self, kind):
        return [
            item for item in self.machines.values() if item.kind == kind
        ]

    def first(self, kind, default=None):
        for item in self.machines.values():
            if item.kind == kind:
                return item
        return default

    @classmethod
    def from_data(cls, data, source="automata"):
        catalog = cls()
        data = _as_mapping(data)
        raw = data.get("machines")
        if raw is None:
            raw = [data] if data.get("id") else []
        for index, item in enumerate(_as_list(raw)):
            catalog.add(
                StateMachineDefinition.from_data(
                    item, "%s[%d]" % (source, index)
                )
            )
        return catalog

    @classmethod
    def load(cls, path):
        path = Path(path)
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        data = {"machines": []}
        for item in files:
            try:
                with item.open(encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError) as error:
                raise StateMachineError(
                    "%s: %s" % (item, error)
                ) from error
            if isinstance(payload, Mapping) and "machines" in payload:
                raw = payload.get("machines") or ()
                data["machines"].extend(
                    entry
                    for entry in raw
                    if _looks_like_machine(entry)
                )
            elif _looks_like_machine(payload):
                data["machines"].append(payload)
            # Файлы редактора (граф `Automaton`, schema 1) лежат в той же
            # папке, но не являются исполняемыми автоматами. Их пропускаем,
            # иначе один старый файл отключил бы весь каталог.
        return cls.from_data(data, source=str(path))


def default_root():
    return (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "campaigns"
        / "base"
        / "automata"
    )


def load_catalog(path=None):
    path = Path(path) if path else default_root()
    if not path.exists():
        return StateMachineCatalog()
    return StateMachineCatalog.load(path)


def machine_map(
    catalog,
    *,
    kind,
    ids: Iterable[str],
    seed=None,
):
    """Создать рантаймы для набора объектов одного вида."""
    definition = catalog.first(kind)
    if definition is None:
        return {}
    del seed
    return {
        str(machine_id): StateMachine(definition)
        for machine_id in ids
    }


__all__ = [
    "StateMachine",
    "StateMachineCatalog",
    "StateMachineDefinition",
    "StateMachineError",
    "StateSpec",
    "TransitionSpec",
    "default_root",
    "load_catalog",
    "machine_map",
]
