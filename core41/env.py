"""Gym-подобные среды для обучения политик.

`DuelEnv` — минимальная дуэль `force`-канала из раннего среза.
`ArenaEnv` — среда активной арены: те же `ArenaAgent`, `CORE_ACTIONS`,
захват и награда, что видит игрок в `ArenaMatch`. Среда всегда создаёт матч
с `auto_learn=False`: политики обновляет внешний цикл обучения, поэтому
`Transition` одной и той же стороны не учитывается дважды.

Обе среды дают симметричный доступ к сторонам через `observe(side)` и
`legal_actions(side)`, где `side` — `"rl"`/`"ai"` (для `DuelEnv` также
принимаются легаси-имена `"agent"`/`"opponent"`). Это нужно для self-play:
у каждой стороны своё наблюдение, действие и награда.

Доменная рандомизация (проблема готовности №7): перед матчем можно вызвать
`randomize_draw(rng)`, и он вернёт словарь параметров `ArenaEnv` (профили,
стартовая болезнь, множители здоровья), распределение которого ограничено
флагами CLI `agents.train`. Draw детерминирован rng'ом вызывающего цикла:
один и тот же seed обучения даёт одну и ту же последовательность доменов,
поэтому воспроизводимость сохраняется без скрытых состояний среды.
"""

import random

from .arena import PROFILE_SKILLS, ArenaMatch
from .duel import DuelWorld
from .model import DEFAULT_HEALTH_FACTORS, HEALTH_FACTOR_MAX, SICKNESS_MAX

# Диапазоны доменной рандомизации по умолчанию (проблема №7). Широкие, но
# физически осмысленные: sickness ∈ [0, 0.6] оставляет TREAT нетривиальным
# выбором, health-факторы ±25% вокруг канона, aging/illness/stress/care
# ограничены сверху HEALTH_FACTOR_MAX внутри Automaton.health_factor().
DRIFT_SICKNESS_MIN = 0.0
DRIFT_SICKNESS_MAX = 0.6
DRIFT_HEALTH_MIN = 0.75
DRIFT_HEALTH_MAX = 1.25


def _clamp_unit(value):
    return max(0.0, min(1.0, float(value)))


def randomize_draw(
    rng=None,
    profiles=(),
    health_factors=(),
    sickness_min=DRIFT_SICKNESS_MIN,
    sickness_max=DRIFT_SICKNESS_MAX,
    health_min=DRIFT_HEALTH_MIN,
    health_max=DRIFT_HEALTH_MAX,
):
    """Сэмплировать один домен арены (параметры конструктора `ArenaEnv`).

    - `profiles` — кортеж имён профилей (`CANON`/`ZEALOT`/`ORTHODOX`);
      пусто — только `CANON` (без джиттера профиля);
    - `health_factors` — имена факторов (`aging`, `illness`, `stress`,
      `care`), которым назначается случайный множитель; пусто — факторы
      остаются каноническими; неизвестное имя — `ValueError`;
    - sickness и health-множители берутся из указанных диапазонов.
    """
    rng = rng or random.Random()
    names = tuple(str(name).upper() for name in profiles) or ("CANON",)
    unknown = [name for name in names if name not in PROFILE_SKILLS]
    if unknown:
        raise ValueError("неизвестные профили: %r" % (unknown,))
    lo_s = _clamp_unit(sickness_min)
    hi_s = max(lo_s, _clamp_unit(sickness_max))
    lo_h = max(0.05, float(health_min))
    hi_h = min(float(HEALTH_FACTOR_MAX), max(lo_h, float(health_max)))
    factors = {}
    unknown_factors = [
        str(factor)
        for factor in health_factors
        if str(factor) not in DEFAULT_HEALTH_FACTORS
    ]
    if unknown_factors:
        raise ValueError("неизвестные health-факторы: %r" % (unknown_factors,))
    for factor in health_factors:
        factors[str(factor)] = round(rng.uniform(lo_h, hi_h), 4)
    return {
        "profile_rl": rng.choice(names),
        "profile_ai": rng.choice(names),
        "sickness_rl": round(rng.uniform(lo_s, hi_s), 4),
        "sickness_ai": round(rng.uniform(lo_s, hi_s), 4),
        "health_factors_rl": dict(factors),
        "health_factors_ai": dict(factors),
    }


def _side_id(side):
    side = str(side).lower()
    if side in ("rl", "agent"):
        return "agent"
    if side in ("ai", "opponent"):
        return "opponent"
    raise ValueError("unknown side: %r" % (side,))


class DuelEnv:

    def __init__(self, seed=0, max_steps=200):
        self.world = DuelWorld(seed=seed, max_steps=max_steps)
        self.last_rewards = {}
        self.last_observations = {}

    @property
    def action_space(self):
        return self.world.legal_actions("agent")

    def observe(self, side="rl"):
        return self.world.observe(_side_id(side))

    def legal_actions(self, side="rl"):
        return self.world.legal_actions(_side_id(side))

    def reset(self, seed=None):
        observation = self.world.reset(seed)
        self.last_rewards = {"agent": 0.0, "opponent": 0.0}
        self.last_observations = {
            "agent": observation,
            "opponent": self.world.observe("opponent"),
        }
        return observation

    def step(self, action, opponent_action=None):
        if opponent_action is None:
            choices = self.world.legal_actions("opponent")
            opponent_action = choices[
                self.world.rng.randrange(len(choices))
            ]
        observations, rewards, done, info = self.world.step(
            {"agent": action, "opponent": opponent_action}
        )
        self.last_rewards = dict(rewards)
        self.last_observations = dict(observations)
        truncated = bool(
            done
            and self.world.time >= self.world.max_steps
            and not self.world.agent.is_dead
            and not self.world.opponent.is_dead
        )
        return (
            observations["agent"],
            rewards["agent"],
            done,
            truncated,
            info,
        )


class ArenaEnv:
    """Среда активной арены с внешним обучением.

    Параметры повторяют `ArenaMatch`; `policy` — обучаемая политика стороны
    `rl`, `opponent_policy` — политика стороны `ai`. Если политика
    противника не задана, среда выбирает случайное легальное действие.
    `with_env=True` по умолчанию: train/eval совпадают с активной игрой;
    `with_env=False` — контрольное плечо без среды.
    """

    def __init__(
        self,
        seed=0,
        steps=2000,
        policy=None,
        opponent_policy=None,
        profile_rl="CANON",
        profile_ai="CANON",
        health_factors_rl=None,
        health_factors_ai=None,
        sickness_rl=0.0,
        sickness_ai=0.0,
        wound_rl=0.0,
        wound_ai=0.0,
        # Обучение по умолчанию идёт в той же конфигурации, что активная
        # игра (`MatchEngine`/`BattlefieldModel`): среда включена. Для
        # контрольного плеча без среды передайте `with_env=False`.
        with_env=True,
    ):
        self.seed = int(seed)
        self.steps = int(steps)
        self.policy = policy
        self.opponent_policy = opponent_policy
        self.profile_rl = str(profile_rl)
        self.profile_ai = str(profile_ai)
        self.health_factors_rl = dict(health_factors_rl or {})
        self.health_factors_ai = dict(health_factors_ai or {})
        self.sickness_rl = float(sickness_rl)
        self.sickness_ai = float(sickness_ai)
        self.wound_rl = float(wound_rl)
        self.wound_ai = float(wound_ai)
        self.with_env = bool(with_env)
        self.match = None
        self.last_rewards = {"rl": 0.0, "ai": 0.0}
        self.reset(seed=self.seed)

    def apply_domain(self, **kwargs):
        """Применить словарь домена (`randomize_draw`) и пересоздать матч.

        Принимаются только параметры конструктора; неизвестные ключи —
        ошибка (защита от опечаток в CLI-пробросе проблемы №7).
        """
        allowed = {
            "profile_rl",
            "profile_ai",
            "health_factors_rl",
            "health_factors_ai",
            "sickness_rl",
            "sickness_ai",
            "wound_rl",
            "wound_ai",
        }
        unknown = set(kwargs) - allowed
        if unknown:
            raise ValueError(
                "неизвестные параметры домена: %r" % (sorted(unknown),)
            )
        for key, value in kwargs.items():
            if key.startswith("health_factors"):
                setattr(self, key, dict(value or {}))
            elif key.startswith("profile"):
                setattr(self, key, str(value))
            else:
                setattr(self, key, float(value))
        return self.reset()

    @property
    def action_space(self):
        if self.match is None:
            return ()
        return self.match.rl.actions()

    def _agents(self, side="rl"):
        if self.match is None:
            raise RuntimeError("ArenaEnv используется до reset()")
        side = str(side).lower()
        if side in ("rl", "agent"):
            return self.match.rl, self.match.ai
        if side in ("ai", "opponent"):
            return self.match.ai, self.match.rl
        raise ValueError("unknown side: %r" % (side,))

    def observe(self, side="rl"):
        agent, other = self._agents(side)
        return agent.observe(other)

    def legal_actions(self, side="rl"):
        agent, _other = self._agents(side)
        return agent.actions()

    def reset(self, seed=None):
        if seed is not None:
            self.seed = int(seed)
        self.last_rewards = {"rl": 0.0, "ai": 0.0}
        self.match = ArenaMatch(
            seed=self.seed,
            steps=self.steps,
            rl_policy=self.policy,
            ai_policy=self.opponent_policy,
            profile_rl=self.profile_rl,
            profile_ai=self.profile_ai,
            health_factors_rl=self.health_factors_rl,
            health_factors_ai=self.health_factors_ai,
            sickness_rl=self.sickness_rl,
            sickness_ai=self.sickness_ai,
            wound_rl=self.wound_rl,
            wound_ai=self.wound_ai,
            with_env=self.with_env,
            auto_learn=False,
        )
        return self.match.rl.observe(self.match.ai)

    def _opponent_action(self):
        match = self.match
        observation = match.ai.observe(match.rl)
        actions = match.ai.actions()
        if self.opponent_policy is not None:
            return self.opponent_policy.act(
                observation, actions, explore=True
            )
        return actions[match.rng.randrange(len(actions))]

    def step(self, action, opponent_action=None):
        match = self.match
        if match is None:
            raise RuntimeError("ArenaEnv.step() вызван до reset()")
        if match.finished:
            raise RuntimeError("ArenaEnv.step() после завершения партии")
        if opponent_action is None:
            opponent_action = self._opponent_action()
        match.step_tick(
            forced_rl_action=action,
            forced_ai_action=opponent_action,
        )
        self.last_rewards = dict(match.last_rewards)
        observation = match.rl.observe(match.ai)
        reward = float(match.last_rewards["rl"])
        done = bool(match.finished)
        truncated = bool(
            done
            and match.step >= match.steps_total
            and not match.rl.is_dead
            and not match.ai.is_dead
        )
        info = {
            "winner": match.winner,
            "events": list(match.events),
            "step": match.step,
            "time": match.time,
            "rewards": dict(match.last_rewards),
            "rl_action": match.last_rl_action,
            "ai_action": match.last_ai_action,
        }
        return observation, reward, done, truncated, info
