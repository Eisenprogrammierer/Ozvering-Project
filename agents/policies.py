import ast
import json
import math
import random

from core41.model import TREAT_ENERGY_FRACTION
from core41.types import (
    Action,
    CampaignAction,
    CampaignObservation,
    Observation,
    Transition,
)

# Служебное действие кампанейного среза (проблема готовности №6).
# Импортируется локально, чтобы не создавать цикл campaign.env -> agents.
from campaign.env import END_DAY

# Версия формата чекпойнтов (проблема готовности №5). Файлы без поля
# ``version`` считаются v0 — легаси-форматом до введения болезни в ключ
# QTable и до появления MLPPolicy. Текущий формат — v3:
#   - QTable: 12-полевой ключ; при загрузке v0 мигрируют ключи 8 и 10
#     полей (недостающие sickness-поля заполняются нулём);
#   - BDI: 22 признака (18 прежних + код действия + 2 признака среды +
#     окно среды A1); при загрузке v0/v1/v2 короткий вектор веса
#     дополняется нулями;
#   - MLP: 22 входа; при загрузке v1/v2 строки 18/19/21→22 дополняются
#     нулями, поэтому старые сети не теряют выученные веса.
# QTable-ключи не меняются: код действия уже входит в ключ отдельным полем.
CHECKPOINT_VERSION = 3
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
    if isinstance(observation, CampaignObservation):
        # Кампанейный fallback (проблема №6): если next_actions пуст,
        # служебный END_DAY всегда легален до завершения сюжета.
        if observation.finished:
            return tuple()
        return (CampaignAction(END_DAY),)
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


# Стабильные коды действий для 19-го признака. Это не семантическая
# величина, а только способ отличить действия друг от друга в линейной/MLP
# политике: у кампании `fraction` всегда 0, поэтому без кода `inspect` и
# `build_network` давали бы одинаковый вектор. Код фиксирован, чтобы
# чекпойнт не зависел от порядка действий в конфиге мира.
ACTION_FEATURE_CODES = {
    ("REST", "rest"): 0.00,
    ("REST", ""): 0.00,
    ("TREAT", "care"): 0.05,
    ("TREAT", ""): 0.05,
    ("WORK", "force"): 0.10,
    ("WORK", "info"): 0.15,
    ("END_DAY", ""): 0.20,
    ("inspect", ""): 0.25,
    ("build_network", ""): 0.30,
    ("treat", ""): 0.35,
    ("seek_promotion", ""): 0.40,
    ("request_transfer", ""): 0.45,
    ("resign", ""): 0.50,
    ("TREAT_SELF", ""): 0.55,
    ("TREAT_WOUND", ""): 0.57,
}

UNKNOWN_ACTION_CODE = 0.95


def action_feature_code(action):
    """Код действия для 19-го признака (0..1, детерминированный)."""
    kind = str(getattr(action, "kind", "") or "")
    form = str(getattr(action, "form", "") or "")
    return ACTION_FEATURE_CODES.get((kind, form), UNKNOWN_ACTION_CODE)


def campaign_features(observation, action):
    """Признаки кампанейного среза (проблема готовности №6).

    Тот же формат вектора, что и у арены: 21 признак, где слоты
    «противника» занимают позиции собственной организации (power — чужая
    сила, cohesion — «открытость» структуры), а `action.kind` кодируется
    через флаги REST/WORK/TREAT по аналогии с ареной: END_DAY ведёт себя
    как отдых (тик мира без затрат), ordinary-действие — как работа,
    heal/self-действие — как лечение. Девятнадцатый слот — стабильный код
    действия: без него `inspect` и `build_network` неразличимы для
    BDI/MLP, потому что у обоих `fraction=0`. Последние два слота —
    признаки среды (в кампании нейтральные). Признаки нормированы к
    [0, 1], как и в `features()`.
    """
    is_end_day = 1.0 if action.kind == "END_DAY" else 0.0
    self_target = 1.0 if not action.target else 0.0
    is_heal = 1.0 if (self_target and not is_end_day) else 0.0
    is_work = 1.0 if (not self_target and not is_end_day) else 0.0
    if float(observation.energy) >= 0.0 and float(
        observation.max_energy
    ) > 0.0:
        energy_ratio = float(observation.energy) / float(
            observation.max_energy
        )
    else:
        energy_ratio = float(observation.actions_left) / max(
            1, int(observation.actions_per_day)
        )
    if float(observation.force) >= 0.0 and float(
        observation.max_force
    ) > 0.0:
        force_ratio = float(observation.force) / float(
            observation.max_force
        )
    else:
        force_ratio = float(observation.standing)
    return (
        1.0,
        _clamp01(energy_ratio),
        _clamp01(float(observation.day) / max(1, int(observation.total_days))),
        _clamp01(force_ratio),
        _clamp01(float(observation.power)),
        1.0 if observation.attached else 0.0,
        _clamp01(float(observation.cohesion)),
        is_end_day,
        is_work,
        _clamp01(float(action.fraction)),
        _clamp01(float(observation.influence)),
        _clamp01(float(observation.favor)),
        _clamp01(float(observation.evidence)),
        _clamp01(float(observation.health) / max(1.0, observation.max_health)),
        _clamp01(float(observation.authority)),
        _clamp01(float(observation.sickness)),
        1.0 if not observation.alive else 0.0,
        is_heal,
        action_feature_code(action),
        # Кампания не имеет собственного актора среды; 20-й слот —
        # устойчивая рана героя (общее состояние `wound` с ареной). На
        # арене этот слот занят `env_pressure`, но кампанейный вектор
        # строится отдельно (`campaign_features`). Слой A1 добавил в
        # аренный вектор 22-й признак (окно среды); кампанейный дополнен
        # фиксированным 0.0 (у кампании нет env-актора), поэтому длины
        # векторов совпадают и общие веса политик грузятся без миграции.
        _clamp01(float(getattr(observation, "wound", 0.0))),
        1.0,
        # 22-й слот (A1): окно среды. У кампании env-актора нет — всегда
        # 0.0, чтобы длина вектора равнялась FEATURE_COUNT.
        0.0,
    )


def _campaign_vector(observation, action):
    """Диспетчер: выбирает армейный или кампанейный вектор признаков."""
    if isinstance(observation, CampaignObservation):
        return campaign_features(observation, action)
    return features(observation, action)


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


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
        action_feature_code(action),
        _clamp01(float(getattr(observation, "env_pressure", 0.0))),
        _clamp01(float(getattr(observation, "env_season", 1.0))),
        # A1: открытое окно уязвимости среды (0/1). Вне env-актора всегда
        # 0.0 — старые векторы дополняются нулём при миграции чекпойнтов.
        _clamp01(float(getattr(observation, "env_window", 0.0))),
    )


FEATURE_COUNT = 22
CHECKPOINT_VERSION = 3
LEGACY_CHECKPOINT_VERSION = 0


def campaign_weights_from(weights):
    """Кампанейный приор BDI поверх аренных весов.

    В кампании слот 7 — `END_DAY` (аналог отдыха), слот 8 — обычное
    действие. Аренные веса поощряют отдых (`+0.8`) и наказывают работу
    (`-0.4`), из-за чего BDI всегда завершал день и не тренировал навыки.
    Кампанейский приор меняет знак этих слотов и включает код действия,
    чтобы baseline действительно действовал, пока есть бюджет.
    """
    result = list(weights)
    if len(result) >= 19:
        result[7] = -0.6
        result[8] = 0.6
        result[18] = 0.3
    return result


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
            0.0,
            0.0,
            0.0,
            # A1: базовая реакция на открытое окно среды (22-й слот).
            0.3,
        ]
        # Кампанейный срез — отдельная задача: общие аренные веса
        # предпочитают отдых, поэтому baseline завершал день вместо
        # действий. Приор задаёт рабочее поведение, а `observe()` обновляет
        # именно тот набор весов, который использовался.
        self.campaign_weights = campaign_weights_from(self.weights)

    def _active_weights(self, observation):
        if isinstance(observation, CampaignObservation):
            return self.campaign_weights
        return self.weights

    def score(self, observation, action):
        return dot(
            self._active_weights(observation),
            _campaign_vector(observation, action),
        )

    def _beliefs_from(self, observation):
        """Обновление верований BDI для любого среза (арена/кампания).

        На арене «противник» — второй боец; в кампании (`CampaignObservation`,
        проблема №6) те же слоты верований занимают организация и позиция:
        open → attached, pressure → cohesion, energy → actions_left, force →
        power. Это сохраняет семантику BDI-машин (Beliefs о мире), не вводя
        новых шкал.
        """
        if isinstance(observation, CampaignObservation):
            return {
                "opponent_open": bool(observation.attached),
                "opponent_pressure": float(observation.cohesion),
                "self_energy": (
                    float(observation.energy)
                    / max(1.0, float(observation.max_energy))
                    if float(observation.energy) >= 0.0
                    and float(observation.max_energy) > 0.0
                    else float(observation.actions_left)
                    / max(1, int(observation.actions_per_day))
                ),
                "opponent_force": float(observation.power),
                "self_health": float(observation.health)
                / max(1.0, observation.max_health),
                "opponent_health": float(observation.standing),
            }
        return {
            "opponent_open": bool(observation.opponent_open),
            "opponent_pressure": float(observation.opponent_pressure),
            "self_energy": float(
                observation.self_energy / max(1.0, observation.self_max_energy)
            ),
            "opponent_force": float(
                observation.opponent_force
                / max(1.0, observation.opponent_max_force)
            ),
            "self_health": float(
                observation.self_health
                / max(1.0, observation.self_max_health)
            ),
            "opponent_health": float(
                observation.opponent_health
                / max(1.0, observation.opponent_max_health)
            ),
        }

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
        vector = _campaign_vector(observation, action)
        weights = self._active_weights(observation)
        current = dot(weights, vector)
        if transition.done:
            target = 0.0
        else:
            next_actions = transition.next_actions
            if not next_actions:
                next_actions = default_actions(transition.next_observation)
            target = max(
                dot(
                    weights,
                    _campaign_vector(transition.next_observation, candidate),
                )
                for candidate in next_actions
            )
        error = transition.reward + self.discount * target - current
        for index, value in enumerate(vector):
            weights[index] += self.learning_rate * error * value
        next_observation = transition.next_observation
        self.beliefs.update(self._beliefs_from(next_observation))
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
            "campaign_weights": list(self.campaign_weights),
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
        campaign_weights = state.get("campaign_weights")
        if campaign_weights is not None:
            values = [float(value) for value in campaign_weights]
            if len(values) < len(self.campaign_weights):
                values.extend(
                    [0.0] * (len(self.campaign_weights) - len(values))
                )
            self.campaign_weights = values[: len(self.campaign_weights)]
        else:
            # Старый чекпойнт: сохраняем выученные аренные веса и
            # накладываем на них кампанейный приор.
            self.campaign_weights = campaign_weights_from(self.weights)
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
        campaign=False,
    ):
        self.rng = random.Random(seed)
        self.learning_rate = float(learning_rate)
        self.discount = float(discount)
        self.epsilon = 0.22
        # campaign=True — таблица обучается на дневном срезе (проблема №6):
        # ключ строится из нормированных кампанейных разрядов и не
        # смешивается с аренной таблицей.
        self.campaign = bool(campaign)
        self.table = table if table is not None else {}
        self.updates = 0

    def key(self, observation, action):
        if isinstance(observation, CampaignObservation) or self.campaign:
            # Кампанейный ключ (проблема №6): тот же 12-полевой формат,
            # но разряды взяты из нормированных признаков кампании —
            # так таблица не смешивается с аренной и не требует миграции.
            vector = campaign_features(observation, action)
            return (
                round(vector[3] * 4.0),   # standing
                round(vector[4] * 4.0),   # power организации
                round(vector[13] * 4.0),  # health/HEALTH_MAX
                round(vector[15] * 4.0),  # sickness
                round(vector[1] * 4.0),   # actions_left/actions_per_day
                round(vector[2] * 4.0),   # прогресс дня (day/total_days)
                0,
                0,
                int(bool(vector[5])),     # attached
                action.kind,
                action.target,
                round(action.fraction, 2),
            )
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
        self.updates += 1
        self.epsilon = max(0.03, self.epsilon * 0.9995)

    def state_dict(self):
        return {
            "kind": "qtable",
            "version": CHECKPOINT_VERSION,
            "campaign": bool(self.campaign),
            "table": {
                repr(key): value for key, value in self.table.items()
            },
            "epsilon": self.epsilon,
            "learning_rate": self.learning_rate,
            "discount": self.discount,
            "updates": self.updates,
        }

    def load_state_dict(self, state):
        if not state:
            return
        # Версия не указана — легаси-v0; ключи мигрируются по длине
        # (8/10 -> 12), чтобы старые таблицы не терялись молча.
        # Флаг среза сохраняется в чекпойнте (проблема №6): аренная и
        # кампанейная таблицы не должны молча подменять формат ключа.
        self.campaign = bool(state.get("campaign", self.campaign))
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
        self.updates = int(state.get("updates", self.updates))


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
        target_sync=50,
    ):
        self.rng = random.Random(seed)
        self.learning_rate = float(learning_rate)
        self.discount = float(discount)
        self.epsilon = float(epsilon)
        self.min_epsilon = float(min_epsilon)
        self.hidden = int(hidden)
        self.target_sync = max(1, int(target_sync))
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
        # Target-сеть стабилизирует bootstrap: цель TD считается по
        # «замороженным» весам и синхронизируется каждые `target_sync`
        # обновлений. Это снижает расходимость длинного online TD(0).
        self.target_weights1 = [list(row) for row in self.weights1]
        self.target_bias1 = list(self.bias1)
        self.target_weights2 = list(self.weights2)
        self.target_bias2 = self.bias2

    def _forward_with(self, vector, weights1, bias1, weights2, bias2):
        hidden = []
        for index in range(self.hidden):
            value = bias1[index] + dot(weights1[index], vector)
            hidden.append(math.tanh(value))
        output = bias2 + dot(weights2, hidden)
        return output, hidden

    def _forward(self, vector):
        return self._forward_with(
            vector,
            self.weights1,
            self.bias1,
            self.weights2,
            self.bias2,
        )

    def _target_forward(self, vector):
        return self._forward_with(
            vector,
            self.target_weights1,
            self.target_bias1,
            self.target_weights2,
            self.target_bias2,
        )

    def _sync_target(self):
        self.target_weights1 = [list(row) for row in self.weights1]
        self.target_bias1 = list(self.bias1)
        self.target_weights2 = list(self.weights2)
        self.target_bias2 = self.bias2

    def score(self, observation, action):
        output, _hidden = self._forward(_campaign_vector(observation, action))
        return output

    def target_score(self, observation, action):
        output, _hidden = self._target_forward(
            _campaign_vector(observation, action)
        )
        return output

    def act(self, observation, actions, explore=True):
        actions = tuple(actions)
        if not actions:
            return Action("REST", form="rest")
        if explore and self.rng.random() < self.epsilon:
            return self.rng.choice(actions)
        return max(actions, key=lambda item: self.score(observation, item))

    def observe(self, transition):
        vector = _campaign_vector(
            transition.observation, transition.action
        )
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
                self.target_score(
                    transition.next_observation, candidate
                )
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
        if self.updates % self.target_sync == 0:
            self._sync_target()
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
            "target_weights1": [list(row) for row in self.target_weights1],
            "target_bias1": list(self.target_bias1),
            "target_weights2": list(self.target_weights2),
            "target_bias2": self.target_bias2,
            "target_sync": self.target_sync,
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
        rows = []
        if weights1:
            rows = [[float(value) for value in row] for row in weights1]
            # v1 MLP имел 18 входов, v2 — 19, v2(среда) — 21, текущий
            # (A1: окно среды) — 22. Дополняем строки нулями, чтобы
            # старые веса не терялись.
            if all(len(row) <= FEATURE_COUNT for row in rows):
                rows = [
                    row + [0.0] * (FEATURE_COUNT - len(row)) for row in rows
                ]
        if (
            rows
            and len(rows) == hidden
            and all(len(row) == FEATURE_COUNT for row in rows)
        ):
            self.hidden = hidden
            self.weights1 = rows
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
        self.target_sync = max(
            1, int(state.get("target_sync", self.target_sync))
        )
        target_rows = state.get("target_weights1")
        if target_rows:
            target_rows = [
                [float(value) for value in row] for row in target_rows
            ]
            if all(len(row) <= FEATURE_COUNT for row in target_rows):
                target_rows = [
                    row + [0.0] * (FEATURE_COUNT - len(row))
                    for row in target_rows
                ]
            if (
                len(target_rows) == self.hidden
                and all(len(row) == FEATURE_COUNT for row in target_rows)
            ):
                self.target_weights1 = target_rows
                self.target_bias1 = [
                    float(value)
                    for value in state.get(
                        "target_bias1",
                        [0.0 for _ in range(self.hidden)],
                    )
                ]
                self.target_weights2 = [
                    float(value)
                    for value in state.get(
                        "target_weights2",
                        [0.0 for _ in range(self.hidden)],
                    )
                ]
                self.target_bias2 = float(
                    state.get("target_bias2", 0.0)
                )
            else:
                self._sync_target()
        else:
            # Старый чекпойнт без target-сети: копируем online-веса, чтобы
            # первый bootstrap не был случайным.
            self._sync_target()
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
    if name == "qtable-campaign":
        # Кампанейная таблица (проблема №6): тот же QTable, но ключ
        # строится из дневных признаков CampaignObservation.
        return QTablePolicy(seed=seed, campaign=True)
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
