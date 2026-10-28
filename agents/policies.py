import ast
import json
import random

from core41.model import TREAT_ENERGY_FRACTION
from core41.types import Action, Observation, Transition

COUNTERS = {
    ("FIRE", "EARTH"),
    ("EARTH", "WATER"),
    ("WATER", "FIRE"),
}


def default_actions(observation):
    actions = [Action("REST", form="rest")]
    if getattr(observation, "self_sickness", 0.0) > 0.0:
        actions.append(
            Action(
                "TREAT",
                form="care",
                fraction=TREAT_ENERGY_FRACTION,
            )
        )
    for form in observation.forms:
        for fraction in (0.25, 0.5, 0.75):
            actions.append(
                Action("WORK", form=form, fraction=fraction)
            )
    return tuple(actions)


def features(observation, action):
    max_energy = max(1.0, observation.self_max_energy)
    max_force = max(1.0, observation.self_max_force)
    opponent_energy = max(1.0, observation.opponent_max_energy)
    opponent_force = max(1.0, observation.opponent_max_force)
    is_rest = 1.0 if action.kind == "REST" else 0.0
    is_work = 1.0 if action.kind == "WORK" else 0.0
    is_treat = 1.0 if action.kind == "TREAT" else 0.0
    return (
        1.0,
        observation.self_energy / max_energy,
        observation.self_force / max_force,
        observation.opponent_energy / opponent_energy,
        observation.opponent_force / opponent_force,
        1.0 if observation.opponent_open else 0.0,
        min(1.0, observation.opponent_pressure / 8.0),
        is_rest,
        is_work,
        action.fraction,
        1.0 if action.form == "force" else 0.0,
        1.0 if action.form == "info" else 0.0,
        1.0
        if (action.form, observation.opponent_defense) in COUNTERS
        else 0.0,
        observation.self_health / max(1.0, observation.self_max_health),
        observation.opponent_health
        / max(1.0, observation.opponent_max_health),
        float(getattr(observation, "self_sickness", 0.0)),
        float(getattr(observation, "opponent_sickness", 0.0)),
        is_treat,
    )


def dot(left, right):
    return sum(a * b for a, b in zip(left, right))


class RandomPolicy:

    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def act(self, observation, actions, explore=True):
        if not actions:
            return Action("REST", form="rest")
        return self.rng.choice(tuple(actions))

    def observe(self, transition):
        return None

    def state_dict(self):
        return {"kind": "random"}

    def load_state_dict(self, state):
        return None


class BDIPolicy:

    def __init__(
        self,
        seed=0,
        learning_rate=0.05,
        discount=0.94,
        epsilon=0.22,
        min_epsilon=0.03,
    ):
        self.rng = random.Random(seed)
        self.learning_rate = float(learning_rate)
        self.discount = float(discount)
        self.epsilon = float(epsilon)
        self.min_epsilon = float(min_epsilon)
        self.updates = 0
        self.beliefs = {
            "opponent_open": False,
            "opponent_pressure": 0.0,
            "self_energy": 0.0,
            "opponent_force": 0.0,
        }
        self.desires = {
            "survive": 1.0,
            "dominate": 0.8,
            "conserve": 0.5,
        }
        self.intentions = ()
        self.weights = [
            0.0,
            -0.5,
            0.3,
            0.0,
            -0.2,
            1.1,
            0.6,
            0.8,
            -0.4,
            -0.5,
            0.3,
            0.0,
            0.6,
            1.2,
            -0.6,
            -0.6,
            0.2,
            0.4,
        ]

    def score(self, observation, action):
        return dot(self.weights, features(observation, action))

    def act(self, observation, actions, explore=True):
        actions = tuple(actions)
        if not actions:
            chosen = Action("REST", form="rest")
        elif explore and self.rng.random() < self.epsilon:
            chosen = self.rng.choice(actions)
        else:
            chosen = actions[0]
            best_score = self.score(observation, chosen)
            for action in actions[1:]:
                value = self.score(observation, action)
                if value > best_score:
                    chosen = action
                    best_score = value
        self.intentions = (chosen,)
        return chosen

    def observe(self, transition):
        observation = transition.observation
        action = transition.action
        vector = features(observation, action)
        current = dot(self.weights, vector)
        if transition.done:
            target = 0.0
        else:
            next_actions = transition.next_actions
            if not next_actions:
                next_actions = default_actions(transition.next_observation)
            target = max(
                dot(
                    self.weights,
                    features(transition.next_observation, candidate),
                )
                for candidate in next_actions
            )
        error = transition.reward + self.discount * target - current
        for index, value in enumerate(vector):
            self.weights[index] += self.learning_rate * error * value
        next_observation = transition.next_observation
        self.beliefs.update(
            {
                "opponent_open": bool(next_observation.opponent_open),
                "opponent_pressure": float(
                    next_observation.opponent_pressure
                ),
                "self_energy": float(
                    next_observation.self_energy
                    / max(1.0, next_observation.self_max_energy)
                ),
                "opponent_force": float(
                    next_observation.opponent_force
                    / max(1.0, next_observation.opponent_max_force)
                ),
                "self_health": float(
                    next_observation.self_health
                    / max(1.0, next_observation.self_max_health)
                ),
                "opponent_health": float(
                    next_observation.opponent_health
                    / max(1.0, next_observation.opponent_max_health)
                ),
            }
        )
        self.updates += 1
        self.epsilon = max(
            self.min_epsilon,
            self.epsilon * 0.9995,
        )

    def state_dict(self):
        return {
            "kind": "bdi",
            "weights": list(self.weights),
            "beliefs": dict(self.beliefs),
            "desires": dict(self.desires),
            "intentions": [
                {
                    "kind": action.kind,
                    "form": action.form,
                    "fraction": action.fraction,
                }
                for action in self.intentions
            ],
            "epsilon": self.epsilon,
            "updates": self.updates,
            "learning_rate": self.learning_rate,
            "discount": self.discount,
        }

    def load_state_dict(self, state):
        if not state:
            return
        weights = state.get("weights")
        if weights is not None:
            values = [float(value) for value in weights]
            if len(values) < len(self.weights):
                values.extend([0.0] * (len(self.weights) - len(values)))
            self.weights = values[: len(self.weights)]
        beliefs = state.get("beliefs")
        if beliefs:
            self.beliefs = dict(beliefs)
        desires = state.get("desires")
        if desires:
            self.desires = {
                str(key): float(value)
                for key, value in desires.items()
            }
        intentions = state.get("intentions")
        if intentions:
            self.intentions = tuple(
                Action(
                    kind=item.get("kind", "REST"),
                    form=item.get("form", "rest"),
                    fraction=float(item.get("fraction", 0.0)),
                )
                for item in intentions
            )
        self.epsilon = float(state.get("epsilon", self.epsilon))
        self.updates = int(state.get("updates", self.updates))
        self.learning_rate = float(
            state.get("learning_rate", self.learning_rate)
        )
        self.discount = float(state.get("discount", self.discount))

    def save(self, path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.state_dict(), handle, ensure_ascii=False)

    def load(self, path):
        with open(path, encoding="utf-8") as handle:
            self.load_state_dict(json.load(handle))


class QTablePolicy:

    def __init__(
        self,
        seed=0,
        learning_rate=0.1,
        discount=0.94,
        table=None,
    ):
        self.rng = random.Random(seed)
        self.learning_rate = float(learning_rate)
        self.discount = float(discount)
        self.epsilon = 0.22
        self.table = table if table is not None else {}

    def key(self, observation, action):
        return (
            round(observation.self_force / 10.0),
            round(observation.self_energy / 10.0),
            round(observation.opponent_force / 10.0),
            round(observation.opponent_energy / 10.0),
            round(observation.self_health / 20.0),
            round(observation.opponent_health / 20.0),
            round(float(getattr(observation, "self_sickness", 0.0)) * 4.0),
            round(
                float(getattr(observation, "opponent_sickness", 0.0)) * 4.0
            ),
            int(observation.opponent_open),
            action.kind,
            action.form,
            round(action.fraction, 2),
        )

    def value(self, observation, action):
        return self.table.get(self.key(observation, action), 0.0)

    def act(self, observation, actions, explore=True):
        actions = tuple(actions)
        if not actions:
            return Action("REST", form="rest")
        if explore and self.rng.random() < self.epsilon:
            return self.rng.choice(actions)
        return max(actions, key=lambda item: self.value(observation, item))

    def observe(self, transition):
        key = self.key(transition.observation, transition.action)
        current = self.table.get(key, 0.0)
        if transition.done:
            target = 0.0
        else:
            next_actions = transition.next_actions
            if not next_actions:
                next_actions = default_actions(transition.next_observation)
            target = max(
                self.value(transition.next_observation, candidate)
                for candidate in next_actions
            )
        self.table[key] = current + self.learning_rate * (
            transition.reward + self.discount * target - current
        )
        self.epsilon = max(0.03, self.epsilon * 0.9995)

    def state_dict(self):
        return {
            "kind": "qtable",
            "table": {
                repr(key): value for key, value in self.table.items()
            },
            "epsilon": self.epsilon,
            "learning_rate": self.learning_rate,
            "discount": self.discount,
        }

    def load_state_dict(self, state):
        if not state:
            return
        table = state.get("table", {})
        self.table = {
            tuple(ast.literal_eval(key)): float(value)
            for key, value in table.items()
        }
        self.epsilon = float(state.get("epsilon", self.epsilon))
        self.learning_rate = float(
            state.get("learning_rate", self.learning_rate)
        )
        self.discount = float(state.get("discount", self.discount))


def make_policy(name, seed=0):
    if name in ("bdi", "adaptive"):
        return BDIPolicy(seed=seed)
    if name in ("qtable", "q"):
        return QTablePolicy(seed=seed)
    if name in ("random", "none"):
        return RandomPolicy(seed=seed)
    return None


def load_policy(path, seed=0, kind=None):
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
    policy_kind = kind or state.get("kind")
    if policy_kind == "bdi":
        policy = BDIPolicy(seed=seed)
    elif policy_kind == "qtable":
        policy = QTablePolicy(seed=seed)
    else:
        raise ValueError(
            "unknown policy checkpoint %r (kind=%r)"
            % (path, policy_kind)
        )
    policy.load_state_dict(state)
    return policy
    raise ValueError("unknown policy")
