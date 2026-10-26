"""Среда как системный автомат.

Среда — это не «фон» и не набор модификаторов, а коллекция автоматов-особенностей
(река, овраг, лес, буря, руины...). У каждой особенности есть собственные
состояния и переходы, а взаимодействие с ней описано теми же ``Target`` /
``ActionSpec`` / ``OutcomeSpec``, что и остальные взаимодействия проекта.

Ключевой контракт:

* ``EnvironmentFeature.machine`` — настоящий ``SystemAutomaton``;
* ``EnvironmentFeature.as_target()`` — объект для ``interaction.InteractionModel``;
* ``EnvironmentRuntime.interact(actor, feature, action)`` — actor-автомат
  взаимодействует с feature-автоматом, получает исход и эффекты, а состояние
  особенности может измениться.

Слой чистый: pygame, ``simulation`` и ``warfare`` не импортируются.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import random
from typing import Dict, List, Mapping, Optional, Tuple

from automata.model import Automaton, State, Transition
from interaction import ActionSpec, InteractionModel, OutcomeSpec, Target

from .core import (
    SystemAutomaton, SystemError, as_float, as_list, as_int, clamp,
    make_state_id, text,
)


class EnvironmentError(SystemError):
    """Ошибка конфигурации среды."""


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise EnvironmentError("конфиг не найден: %s" % path)
    except Exception as exc:
        raise EnvironmentError("не удалось прочитать %s: %s" % (path, exc))


def _tags(value):
    return tuple(str(item).strip() for item in as_list(value)
                 if str(item).strip())


def _effects(value):
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise EnvironmentError("effects должен быть объектом")
    result = {}
    for key, item in value.items():
        key = str(key).strip()
        if not key:
            raise EnvironmentError("effect: пустой ключ")
        if isinstance(item, bool):
            result[key] = item
        elif isinstance(item, (int, float)):
            result[key] = float(item)
        elif isinstance(item, str):
            result[key] = item
        else:
            raise EnvironmentError("effect %s: недопустимое значение" % key)
    return result


@dataclass(frozen=True)
class EnvironmentState:
    id: str
    name: str
    description: str = ""
    difficulty: float = 0.5
    passable: bool = True
    tags: Tuple[str, ...] = ()
    outcome_bias: Dict[str, float] = field(default_factory=dict)
    blocked_actions: Tuple[str, ...] = ()
    uncertainty: float = 0.0

    @classmethod
    def from_data(cls, data, index=0, source="state"):
        if not isinstance(data, Mapping):
            raise EnvironmentError("%s[%d] должен быть объектом" % (source, index))
        state_id = make_state_id(data.get("id"))
        bias = data.get("outcome_bias") or {}
        if not isinstance(bias, Mapping):
            raise EnvironmentError("%s.%s.outcome_bias должен быть объектом"
                                   % (source, state_id))
        return cls(
            id=state_id,
            name=str(data.get("name") or state_id),
            description=str(data.get("description") or ""),
            difficulty=clamp(data.get("difficulty", 0.5), 0.0, 1.0),
            passable=bool(data.get("passable", True)),
            tags=_tags(data.get("tags")),
            outcome_bias={str(key): max(0.0, as_float(value, 1.0))
                          for key, value in bias.items()},
            blocked_actions=_tags(data.get("blocked_actions")),
            uncertainty=clamp(data.get("uncertainty", 0.0), 0.0, 1.0),
        )

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "difficulty": self.difficulty,
            "passable": self.passable,
            "tags": list(self.tags),
            "outcome_bias": dict(self.outcome_bias),
            "blocked_actions": list(self.blocked_actions),
            "uncertainty": self.uncertainty,
        }


@dataclass(frozen=True)
class EnvironmentOutcome:
    spec: OutcomeSpec
    effects: Dict = field(default_factory=dict)
    next_state: str = ""

    @classmethod
    def from_data(cls, data, index=0, source="outcome"):
        if not isinstance(data, Mapping):
            raise EnvironmentError("%s[%d] должен быть объектом" % (source, index))
        spec = OutcomeSpec(
            id=text(data.get("id")),
            label=text(data.get("label")),
            description=text(data.get("description")),
            probability=max(0.0, as_float(data.get("probability", 1.0), 1.0)),
            uncertainty=clamp(data.get("uncertainty", 0.1), 0.0, 1.0),
            hidden=bool(data.get("hidden", False)),
            tone=text(data.get("tone"), "neutral"),
        )
        return cls(
            spec=spec,
            effects=_effects(data.get("effects")),
            next_state=text(data.get("next_state") or data.get("state")),
        )

    def as_dict(self):
        return {
            "id": self.spec.id,
            "label": self.spec.label,
            "description": self.spec.description,
            "probability": self.spec.probability,
            "uncertainty": self.spec.uncertainty,
            "hidden": self.spec.hidden,
            "tone": self.spec.tone,
            "effects": dict(self.effects),
            "next_state": self.next_state,
        }


@dataclass(frozen=True)
class EnvironmentAction:
    id: str
    label: str
    description: str = ""
    tags: Tuple[str, ...] = ()
    uncertainty: float = 0.15
    unknown_share: float = 0.0
    outcomes: Tuple[EnvironmentOutcome, ...] = ()
    required_states: Tuple[str, ...] = ()
    blocked_states: Tuple[str, ...] = ()

    @classmethod
    def from_data(cls, data, index=0, source="action"):
        if not isinstance(data, Mapping):
            raise EnvironmentError("%s[%d] должен быть объектом" % (source, index))
        action_id = text(data.get("id")).strip()
        if not action_id:
            raise EnvironmentError("%s[%d]: пустой id" % (source, index))
        outcomes = tuple(
            EnvironmentOutcome.from_data(item, number, "%s.outcomes" % action_id)
            for number, item in enumerate(data.get("outcomes") or ())
        )
        if not outcomes:
            raise EnvironmentError("%s: нет outcomes" % action_id)
        outcome_ids = {item.spec.id for item in outcomes}
        if len(outcome_ids) != len(outcomes):
            raise EnvironmentError("%s: повторяются id исходов" % action_id)
        return cls(
            id=action_id,
            label=str(data.get("label") or action_id),
            description=str(data.get("description") or ""),
            tags=_tags(data.get("tags")),
            uncertainty=clamp(data.get("uncertainty", 0.15), 0.0, 1.0),
            unknown_share=clamp(data.get("unknown_share", 0.0), 0.0, 1.0),
            outcomes=outcomes,
            required_states=_tags(data.get("required_states")),
            blocked_states=_tags(data.get("blocked_states")),
        )

    def outcome(self, outcome_id):
        for item in self.outcomes:
            if item.spec.id == outcome_id:
                return item
        return None

    def enabled(self, state):
        if state.id in self.blocked_states:
            return False
        if self.id in state.blocked_actions:
            return False
        if self.required_states and state.id not in self.required_states:
            return False
        return True

    def spec(self, state):
        outcomes = []
        for item in self.outcomes:
            probability = item.spec.probability * \
                state.outcome_bias.get(item.spec.id, 1.0)
            if probability <= 0.0:
                continue
            outcomes.append(OutcomeSpec(
                id=item.spec.id,
                label=item.spec.label,
                description=item.spec.description,
                probability=probability,
                uncertainty=item.spec.uncertainty,
                hidden=item.spec.hidden,
                tone=item.spec.tone,
            ))
        return ActionSpec(
            id=self.id,
            label=self.label,
            description=self.description,
            outcomes=tuple(outcomes),
            uncertainty=clamp(self.uncertainty + state.uncertainty, 0.0, 1.0),
            unknown_share=self.unknown_share,
            enabled=self.enabled(state),
        )

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "tags": list(self.tags),
            "uncertainty": self.uncertainty,
            "unknown_share": self.unknown_share,
            "required_states": list(self.required_states),
            "blocked_states": list(self.blocked_states),
            "outcomes": [item.as_dict() for item in self.outcomes],
        }


@dataclass(frozen=True)
class EnvironmentTransition:
    id: str
    source: str
    target: str
    event: str
    weight: float = 1.0
    guard: str = ""

    @classmethod
    def from_data(cls, data, index=0, source="transition"):
        if not isinstance(data, Mapping):
            raise EnvironmentError("%s[%d] должен быть объектом" % (source, index))
        transition_id = text(data.get("id")).strip()
        if not transition_id:
            raise EnvironmentError("%s[%d]: пустой id" % (source, index))
        return cls(
            id=transition_id,
            source=text(data.get("source")).strip(),
            target=text(data.get("target")).strip(),
            event=text(data.get("event")).strip(),
            weight=max(0.0, as_float(data.get("weight", 1.0), 1.0)),
            guard=text(data.get("guard")),
        )

    def as_model(self):
        return Transition(self.id, self.source, self.target,
                          self.event, self.guard)

    def as_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "event": self.event,
            "weight": self.weight,
            "guard": self.guard,
        }


@dataclass
class EnvironmentFeature:
    id: str
    name: str
    description: str
    tags: Tuple[str, ...]
    states: Tuple[EnvironmentState, ...]
    transitions: Tuple[EnvironmentTransition, ...]
    actions: Tuple[EnvironmentAction, ...]
    drift_chance: float = 0.15
    machine: SystemAutomaton = field(init=False)

    @classmethod
    def from_data(cls, data, index=0, source="feature"):
        if not isinstance(data, Mapping):
            raise EnvironmentError("%s[%d] должен быть объектом" % (source, index))
        feature_id = text(data.get("id")).strip()
        if not feature_id:
            raise EnvironmentError("%s[%d]: пустой id" % (source, index))
        states = tuple(
            EnvironmentState.from_data(item, number,
                                       "%s.states" % feature_id)
            for number, item in enumerate(data.get("states") or ())
        )
        if not states:
            raise EnvironmentError("%s: нет states" % feature_id)
        transitions = tuple(
            EnvironmentTransition.from_data(item, number,
                                            "%s.transitions" % feature_id)
            for number, item in enumerate(data.get("transitions") or ())
        )
        raw_actions = data.get("actions")
        if raw_actions is None:
            raw_actions = data.get("interactions") or ()
        actions = tuple(
            EnvironmentAction.from_data(item, number,
                                        "%s.actions" % feature_id)
            for number, item in enumerate(raw_actions)
        )
        if not actions:
            raise EnvironmentError("%s: нет actions" % feature_id)
        return cls(
            id=feature_id,
            name=str(data.get("name") or feature_id),
            description=str(data.get("description") or ""),
            tags=_tags(data.get("tags")),
            states=states,
            transitions=transitions,
            actions=actions,
            drift_chance=clamp(data.get("drift_chance", 0.15), 0.0, 1.0),
        )

    def __post_init__(self):
        self.id = str(self.id or "").strip()
        if not self.id:
            raise EnvironmentError("у особенности должен быть id")
        state_ids = [state.id for state in self.states]
        if len(set(state_ids)) != len(state_ids):
            raise EnvironmentError("%s: повторяются id состояний" % self.id)
        self._states = {state.id: state for state in self.states}
        action_ids = [action.id for action in self.actions]
        if len(set(action_ids)) != len(action_ids):
            raise EnvironmentError("%s: повторяются id действий" % self.id)
        self._actions = {action.id: action for action in self.actions}

        for action in self.actions:
            for outcome in action.outcomes:
                if outcome.next_state and outcome.next_state not in self._states:
                    raise EnvironmentError(
                        "%s.%s.%s: нет состояния %r"
                        % (self.id, action.id, outcome.spec.id,
                           outcome.next_state))
        initial = next((state for state in self.states), None)
        raw_states = []
        for number, state in enumerate(self.states):
            raw_states.append(State(
                state.id,
                state.name,
                x=80 + 220 * (number % 4),
                y=80 + 160 * (number // 4),
                initial=(state is initial),
                final=False,
            ))
        raw_transitions = []
        for transition in self.transitions:
            if transition.source not in self._states:
                raise EnvironmentError("%s.%s: нет source-состояния %r"
                                       % (self.id, transition.id,
                                          transition.source))
            if transition.target not in self._states:
                raise EnvironmentError("%s.%s: нет target-состояния %r"
                                       % (self.id, transition.id,
                                          transition.target))
            raw_transitions.append(transition.as_model())
        automaton = Automaton(
            self.name, self.description,
            states=raw_states, transitions=raw_transitions)
        self.machine = SystemAutomaton(
            self.id, self.name, automaton, current=initial.id)

    def state(self) -> EnvironmentState:
        return self._states[self.machine.current]

    def action(self, action_id):
        return self._actions.get(str(action_id))

    def outcome_effects(self, action_id, outcome_id):
        action = self.action(action_id)
        if action is None or not outcome_id:
            return {}
        outcome = action.outcome(outcome_id)
        return dict(outcome.effects) if outcome is not None else {}

    def apply_outcome(self, action_id, outcome_id):
        action = self.action(action_id)
        if action is None or not outcome_id:
            return False
        outcome = action.outcome(outcome_id)
        if outcome is None or not outcome.next_state:
            return False
        return self.machine.set_state(outcome.next_state)

    def drift(self, rng):
        choices = [item for item in self.transitions
                   if item.source == self.machine.current and item.weight > 0.0]
        if not choices:
            return None
        total = sum(item.weight for item in choices)
        if total <= 0.0:
            return None
        roll = rng.random() * total
        cursor = 0.0
        selected = choices[-1]
        for item in choices:
            cursor += item.weight
            if roll <= cursor:
                selected = item
                break
        previous = self.machine.current
        if not self.machine.set_state(selected.target):
            return None
        # set_state нужен, чтобы не зависеть от guard; сохраняем в истории
        # именно переход автомата, а не техническую запись set_state.
        if self.machine.history and \
                self.machine.history[-1].get("event") == "set_state":
            self.machine.history[-1]["event"] = selected.event or selected.id
            self.machine.history[-1]["transition"] = selected.id
        return EnvironmentShift(
            feature_id=self.id,
            feature_name=self.name,
            event=selected.event or selected.id,
            from_state=previous,
            to_state=self.machine.current,
            from_name=self._states[previous].name,
            to_name=self.state().name,
        )

    def as_target(self):
        state = self.state()
        actions = tuple(action.spec(state) for action in self.actions
                        if action.enabled(state))
        description = self.description.strip()
        if state.description:
            description = (description + " " + state.description).strip()
        return Target(
            id=self.id,
            label=self.name,
            description=description,
            tags=self.tags + state.tags + (state.id,),
            actions=actions,
            available=bool(actions),
        )

    def as_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "drift_chance": self.drift_chance,
            "state": self.machine.current,
            "state_name": self.state().name,
            "states": [item.as_dict() for item in self.states],
            "transitions": [item.as_dict() for item in self.transitions],
            "actions": [item.as_dict() for item in self.actions],
            "automaton": self.machine.automaton.to_dict(),
        }


@dataclass(frozen=True)
class EnvironmentShift:
    feature_id: str
    feature_name: str
    event: str
    from_state: str
    to_state: str
    from_name: str
    to_name: str

    @property
    def text(self):
        return "%s: %s → %s (%s)" % (
            self.feature_name, self.from_name, self.to_name, self.event)

    def as_dict(self):
        return {
            "feature_id": self.feature_id,
            "feature_name": self.feature_name,
            "event": self.event,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "from_name": self.from_name,
            "to_name": self.to_name,
            "text": self.text,
        }


@dataclass(frozen=True)
class EnvironmentInteraction:
    actor_id: str
    feature_id: str
    feature_name: str
    action_id: str
    action_label: str
    outcome_id: Optional[str]
    outcome_label: str
    description: str
    tone: str = "neutral"
    unknown: bool = False
    effects: Dict = field(default_factory=dict)
    state_before: str = ""
    state_after: str = ""
    seed: int = 0

    @property
    def text(self):
        if self.unknown:
            return "%s: неизвестный исход взаимодействия с «%s»" % (
                self.actor_id, self.feature_name)
        return "%s: %s → %s" % (
            self.actor_id, self.action_label, self.outcome_label)

    def as_dict(self):
        return {
            "actor_id": self.actor_id,
            "feature_id": self.feature_id,
            "feature_name": self.feature_name,
            "action_id": self.action_id,
            "action_label": self.action_label,
            "outcome_id": self.outcome_id,
            "outcome_label": self.outcome_label,
            "description": self.description,
            "tone": self.tone,
            "unknown": self.unknown,
            "effects": dict(self.effects),
            "state_before": self.state_before,
            "state_after": self.state_after,
            "seed": self.seed,
            "text": self.text,
        }


class EnvironmentCatalog:
    """Набор особенностей среды из ``configs/systems/environment.json``."""

    def __init__(self, features, drift_chance=0.15, root=None, schema=1):
        self.features = {feature.id: feature for feature in features}
        if len(self.features) != len(features):
            raise EnvironmentError("повторяются id особенностей среды")
        self.drift_chance = clamp(drift_chance, 0.0, 1.0)
        self.root = Path(root) if root is not None else None
        self.schema = as_int(schema, 1)

    @classmethod
    def load(cls, root=None):
        root = Path(root) if root is not None else default_root()
        data = _read_json(root / "environment.json")
        return cls.from_data(data, root=root)

    @classmethod
    def from_data(cls, data, root=None):
        if not isinstance(data, Mapping):
            raise EnvironmentError("environment.json должен быть объектом")
        raw = data.get("features") or ()
        if not isinstance(raw, (list, tuple)):
            raise EnvironmentError("features должен быть списком")
        features = [
            EnvironmentFeature.from_data(item, number, "features")
            for number, item in enumerate(raw)
        ]
        if not features:
            raise EnvironmentError("нет ни одной особенности среды")
        return cls(features, drift_chance=data.get("drift_chance", 0.15),
                   root=root, schema=data.get("schema", 1))

    def feature(self, feature_id):
        if feature_id not in self.features:
            raise EnvironmentError("нет особенности %r" % (feature_id,))
        return self.features[feature_id]

    def feature_ids(self):
        return sorted(self.features)

    def as_dict(self):
        return {
            "schema": self.schema,
            "drift_chance": self.drift_chance,
            "features": [self.features[key].as_dict()
                         for key in self.feature_ids()],
        }


def _actor_id(actor):
    if actor is None:
        return "actor"
    if isinstance(actor, str):
        return actor
    if isinstance(actor, Mapping):
        return str(actor.get("id") or actor.get("name") or "actor")
    return str(getattr(actor, "id", None) or
               getattr(actor, "name", None) or actor)


class EnvironmentRuntime:
    """Живая среда: такты дрейфа и взаимодействия actor → feature."""

    def __init__(self, catalog_or_features, seed=0, drift_chance=None):
        if isinstance(catalog_or_features, EnvironmentCatalog):
            self.catalog = catalog_or_features
            features = list(catalog_or_features.features.values())
            default_drift = catalog_or_features.drift_chance
        else:
            self.catalog = None
            features = list(catalog_or_features or ())
            default_drift = 0.15
        self.features = {feature.id: feature for feature in features}
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.drift_chance = (default_drift if drift_chance is None
                             else clamp(drift_chance, 0.0, 1.0))
        self.history: List[EnvironmentInteraction] = []
        self.shifts: List[EnvironmentShift] = []

    def feature(self, feature_id):
        if feature_id not in self.features:
            raise EnvironmentError("нет особенности %r" % (feature_id,))
        return self.features[feature_id]

    def feature_ids(self):
        return sorted(self.features)

    def targets(self):
        return [self.features[key].as_target() for key in self.feature_ids()]

    def available_targets(self):
        return [target for target in self.targets() if target.available]

    def _next_seed(self, seed=None):
        return int(self.rng.randrange(2 ** 31)) if seed is None else int(seed)

    def interact(self, actor, feature_id, action_id, seed=None):
        feature = self.feature(feature_id)
        target = feature.as_target()
        action = feature.action(action_id)
        if action is None or not action.enabled(feature.state()):
            return None
        interaction_seed = self._next_seed(seed)
        model = InteractionModel([target], seed=interaction_seed)
        if not model.select_target(feature.id):
            return None
        if not model.select_action(action.id):
            return None
        result = model.resolve()
        if result is None:
            return None
        state_before = feature.machine.current
        effects = feature.outcome_effects(action.id, result.outcome_id)
        if result.outcome_id and not result.unknown:
            feature.apply_outcome(action.id, result.outcome_id)
        state_after = feature.machine.current
        item = EnvironmentInteraction(
            actor_id=_actor_id(actor),
            feature_id=feature.id,
            feature_name=feature.name,
            action_id=result.action_id,
            action_label=result.action_label,
            outcome_id=result.outcome_id,
            outcome_label=result.label,
            description=result.description,
            tone=result.tone,
            unknown=result.unknown,
            effects=effects,
            state_before=state_before,
            state_after=state_after,
            seed=interaction_seed,
        )
        self.history.append(item)
        self.history = self.history[-500:]
        return item

    def tick(self, seed=None):
        rng = self.rng if seed is None else random.Random(int(seed))
        shifts = []
        for feature in self.features.values():
            chance = feature.drift_chance if self.drift_chance is None \
                else self.drift_chance
            if rng.random() >= chance:
                continue
            shift = feature.drift(rng)
            if shift is not None:
                shifts.append(shift)
        self.shifts.extend(shifts)
        self.shifts = self.shifts[-500:]
        return shifts

    def reset(self):
        self.rng = random.Random(self.seed)
        self.history = []
        self.shifts = []
        for feature in self.features.values():
            initial = feature.machine.automaton.initial_states
            if initial:
                feature.machine.set_state(initial[0].id)

    def snapshot(self):
        return {
            "seed": self.seed,
            "drift_chance": self.drift_chance,
            "features": {key: self.features[key].as_dict()
                         for key in self.feature_ids()},
            "last_interaction": (self.history[-1].as_dict()
                                 if self.history else None),
            "history": [item.as_dict() for item in self.history],
            "shifts": [item.as_dict() for item in self.shifts],
        }


def default_root():
    return Path(__file__).resolve().parents[1] / "configs" / "systems"


_DEFAULT = None


def default_catalog():
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = EnvironmentCatalog.load()
    return _DEFAULT


__all__ = [
    "EnvironmentError", "EnvironmentState", "EnvironmentOutcome",
    "EnvironmentAction", "EnvironmentTransition", "EnvironmentFeature",
    "EnvironmentShift", "EnvironmentInteraction", "EnvironmentCatalog",
    "EnvironmentRuntime", "default_catalog", "default_root",
]
