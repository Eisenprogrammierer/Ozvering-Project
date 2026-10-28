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
"""

from .arena import ArenaMatch
from .duel import DuelWorld


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
        with_env=False,
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
        self.with_env = bool(with_env)
        self.match = None
        self.last_rewards = {"rl": 0.0, "ai": 0.0}
        self.reset(seed=self.seed)

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
