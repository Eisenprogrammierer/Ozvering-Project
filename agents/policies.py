import ast
import json
import math
import random

from core41.model import TREAT_ENERGY_FRACTION
from core41.types import Action, Observation, Transition

# Версия формата чекпойнтов (проблема готовности №5). Файлы без поля
# ``version`` считаются v0 — легаси-форматом до введения болезни в ключ
# QTable и до появления MLPPolicy. Текущий формат — v1:
#   - QTable: 12-полевой ключ; при загрузке v0 мигрируют ключи 8 и 10
#     полей (недостающие sickness-поля заполняются нулём);
#   - BDI: 18 признаков; при загрузке v0 вектор веса 16 дополняется нулями;
#   - MLP: v1 — первый сетевой baseline, миграции из v0 не существует.
CHECKPOINT_VERSION = 1
LEGACY_CHECKPOINT_VERSION = 0


def _migrate_qtable_key(key):
    """Приводит легаси-ключ QTable (8 или 10 полей) к 12-полевому формату.

    Порядок полей v0 совпадает с v1, кроме пропущенных индексов 6-7
    (self_sickness/opponent_sickness) в 10-полевом варианте и их отсутствия
    в 8-полевом. Миграция вставляет нули на позиции болезни, сохраняя
    остальные разряды, чтобы старые таблицы не обнулялись молча.
    """
    key = tuple(key)
    if len(key) == 12:
        return key
    if len(key) == 10:
        # v0 (10 полей): force/energy x2, health x2, open, kind, form, fraction
        head, tail = key[:6], key[6:]
        return head + (0, 0) + tail
    if len(key) == 8:
        # самый ранний v0: без здоровья и болезни
        head, tail = key[:4], key[4:]
        return head + (0, 0, 0, 0) + tail
    raise ValueError("unsupported qtable key length: %d" % len(key))

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


FEATURE_COUNT = 18


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
        return {
            "kind": "random",
            "version": CHECKPOINT_VERSION,
        }

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
            "version": CHECKPOINT_VERSION,
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
            "version": CHECKPOINT_VERSION,
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
        # Версия не указана — легаси-v0; ключи мигрируются по длине
        # (8/10 -> 12), чтобы старые таблицы не терялись молча.
        table = state.get("table", {})
        migrated = {}
        for key, value in table.items():
            parsed = _migrate_qtable_key(ast.literal_eval(key))
            merged = float(value)
            # Коллизия при слиянии v0-разрядов болезни (несколько старых
            # ключей могут дать один новый) — берём среднее, а не перезапись.
            if parsed in migrated:
                old_value, count = migrated[parsed]
                migrated[parsed] = ((old_value * count + merged) / (count + 1), count + 1)
            else:
                migrated[parsed] = (merged, 1)
        self.table = {key: value for key, (value, _count) in migrated.items()}
        self.epsilon = float(state.get("epsilon", self.epsilon))
        self.learning_rate = float(
            state.get("learning_rate", self.learning_rate)
        )
        self.discount = float(state.get("discount", self.discount))


class MLPPolicy:
    """Небольшая нейросетевая Q-политика без внешних зависимостей.

    Это function approximation для роста ёмкости: один скрытый слой `tanh`
    и линейный выход. Вход — те же 18 признаков, что у `BDIPolicy`, поэтому
    политика совместима с `ArenaEnv` и `DuelEnv`. Обучение — online TD(0):
    цель `reward + discount * max_a Q(next, a)`, обратное распространение
    только по выбранному действию. `BDIPolicy` и `QTablePolicy` остаются
    baseline и не меняются.
    """

    def __init__(
        self,
        seed=0,
        learning_rate=0.01,
        discount=0.94,
        epsilon=0.22,
        min_epsilon=0.03,
        hidden=16,
    ):
        self.rng = random.Random(seed)
        self.learning_rate = float(learning_rate)
        self.discount = float(discount)
        self.epsilon = float(epsilon)
        self.min_epsilon = float(min_epsilon)
        self.hidden = int(hidden)
        self.updates = 0
        self.weights1 = [
            [self.rng.uniform(-0.05, 0.05) for _ in range(FEATURE_COUNT)]
            for _ in range(self.hidden)
        ]
        self.bias1 = [0.0 for _ in range(self.hidden)]
        self.weights2 = [
            self.rng.uniform(-0.05, 0.05) for _ in range(self.hidden)
        ]
        self.bias2 = 0.0

    def _forward(self, vector):
        hidden = []
        for index in range(self.hidden):
            value = self.bias1[index] + dot(
                self.weights1[index], vector
            )
            hidden.append(math.tanh(value))
        output = self.bias2 + dot(self.weights2, hidden)
        return output, hidden

    def score(self, observation, action):
        output, _hidden = self._forward(features(observation, action))
        return output

    def act(self, observation, actions, explore=True):
        actions = tuple(actions)
        if not actions:
            return Action("REST", form="rest")
        if explore and self.rng.random() < self.epsilon:
            return self.rng.choice(actions)
        return max(actions, key=lambda item: self.score(observation, item))

    def observe(self, transition):
        vector = features(transition.observation, transition.action)
        current, hidden = self._forward(vector)
        if transition.done:
            target = 0.0
        else:
            next_actions = transition.next_actions
            if not next_actions:
                next_actions = default_actions(
                    transition.next_observation
                )
            target = max(
                self.score(transition.next_observation, candidate)
                for candidate in next_actions
            )
        error = transition.reward + self.discount * target - current
        error = max(-5.0, min(5.0, error))

        hidden_deltas = [
            error * self.weights2[index] * (1.0 - hidden[index] ** 2)
            for index in range(self.hidden)
        ]
        for index in range(self.hidden):
            self.weights2[index] += (
                self.learning_rate * error * hidden[index]
            )
        self.bias2 += self.learning_rate * error
        for index in range(self.hidden):
            delta = self.learning_rate * hidden_deltas[index]
            row = self.weights1[index]
            for feature_index, value in enumerate(vector):
                row[feature_index] += delta * value
            self.bias1[index] += delta
        self.updates += 1
        self.epsilon = max(self.min_epsilon, self.epsilon * 0.9995)

    def state_dict(self):
        return {
            "kind": "mlp",
            "version": CHECKPOINT_VERSION,
            "feature_count": FEATURE_COUNT,
            "hidden": self.hidden,
            "weights1": [list(row) for row in self.weights1],
            "bias1": list(self.bias1),
            "weights2": list(self.weights2),
            "bias2": self.bias2,
            "epsilon": self.epsilon,
            "updates": self.updates,
            "learning_rate": self.learning_rate,
            "discount": self.discount,
        }

    def load_state_dict(self, state):
        if not state:
            return
        hidden = int(state.get("hidden", self.hidden))
        weights1 = state.get("weights1")
        if (
            weights1
            and len(weights1) == hidden
            and all(len(row) == FEATURE_COUNT for row in weights1)
        ):
            self.hidden = hidden
            self.weights1 = [
                [float(value) for value in row] for row in weights1
            ]
            self.bias1 = [
                float(value)
                for value in state.get(
                    "bias1", [0.0 for _ in range(hidden)]
                )
            ]
            self.weights2 = [
                float(value)
                for value in state.get(
                    "weights2", [0.0 for _ in range(hidden)]
                )
            ]
            self.bias2 = float(state.get("bias2", 0.0))
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


def make_policy(name, seed=0):
    if name in ("bdi", "adaptive"):
        return BDIPolicy(seed=seed)
    if name in ("qtable", "q"):
        return QTablePolicy(seed=seed)
    if name in ("mlp", "neural", "nn"):
        return MLPPolicy(seed=seed)
    if name in ("random", "none"):
        return RandomPolicy(seed=seed)
    return None


def checkpoint_version(state):
    """Версия формата чекпойнта; отсутствующее поле ``version`` = v0."""
    try:
        return int(state.get("version", LEGACY_CHECKPOINT_VERSION))
    except (TypeError, ValueError):
        return LEGACY_CHECKPOINT_VERSION


def load_policy(path, seed=0, kind=None):
    with open(path, encoding="utf-8") as handle:
        state = json.load(handle)
    policy_kind = kind or state.get("kind")
    version = checkpoint_version(state)
    if version > CHECKPOINT_VERSION:
        raise ValueError(
            "checkpoint %r has version %d, this build supports up to %d"
            % (path, version, CHECKPOINT_VERSION)
        )
    if policy_kind == "bdi":
        policy = BDIPolicy(seed=seed)
    elif policy_kind == "qtable":
        policy = QTablePolicy(seed=seed)
    elif policy_kind == "mlp":
        policy = MLPPolicy(seed=seed)
    else:
        raise ValueError(
            "unknown policy checkpoint %r (kind=%r)"
            % (path, policy_kind)
        )
    policy.load_state_dict(state)
    return policy
