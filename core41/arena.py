from __future__ import annotations

import random

from .model import (
    DEFAULT_HEALTH_FACTORS,
    HEALTH_FACTOR_MAX,
    HEALTH_MAX,
    OPEN_PRESSURE,
    PRESSURE_PER_WORK,
    REST_FORCE,
    REST_REGEN,
    SICKNESS_MAX,
    Automaton,
    success_probability,
)
from .types import Action, Observation, Transition, Work

FORMS = ("force", "info")
FRACTIONS = (0.3, 0.7)

CORE_ACTIONS = (
    ("REST", 0.0),
    ("force", FRACTIONS[0]),
    ("force", FRACTIONS[1]),
    ("info", FRACTIONS[0]),
    ("info", FRACTIONS[1]),
)

CAPTURE_RATIO = 1.5
CAPTURE_STREAK = 20
CAPTURE_FRAC = 0.10
L_STEP = 10.0

PROFILE_SKILLS = {
    "CANON": (0.60, 0.00),
    "ZEALOT": (0.68, 0.05),
    "ORTHODOX": (0.55, 0.10),
}


def action_from_index(index):
    name, fraction = CORE_ACTIONS[int(index) % len(CORE_ACTIONS)]
    if name == "REST":
        return Action("REST", form="rest")
    return Action("WORK", form=name, fraction=fraction)


def _default_action(observation):
    return Action("REST", form="rest")


class _RestPolicy:
    def act(self, observation, actions, explore=True):
        return _default_action(observation)

    def observe(self, transition):
        return None

    def state_dict(self):
        return {"kind": "rest"}

    def load_state_dict(self, state):
        return None


def _perform(attacker, defender, action, world):
    attacker.last_action = action
    if action.kind != "WORK":
        attacker.unit.energy = min(
            attacker.unit.max_energy,
            attacker.unit.energy + REST_REGEN,
        )
        attacker.unit.force = min(
            attacker.unit.max_force,
            attacker.unit.force + REST_FORCE,
        )
        attacker.unit.state["pressure"] = attacker.unit.pressure() * 0.5
        attacker.unit.tick_health(resting=True)
        return {
            "kind": "rest",
            "spent": 0.0,
            "success": True,
            "damage": 0.0,
            "form": "REST",
        }
    amount = min(
        attacker.energy_pool,
        max(0.0, min(1.0, action.fraction)) * attacker.unit.max_energy,
    )
    if amount <= 0.0:
        attacker.unit.state["pressure"] = attacker.unit.pressure() * 0.5
        attacker.unit.tick_health(resting=True)
        return {
            "kind": "rest",
            "spent": 0.0,
            "success": True,
            "damage": 0.0,
            "form": "REST",
        }
    attacker.energy_pool -= amount
    work = Work(amount=amount, form=action.form or "force")
    result = defender.unit.receive(work, attacker.unit, world)
    result["kind"] = "work"
    result["spent"] = amount
    result["form"] = work.form
    attacker.unit.tick_health(resting=False)
    return result


def _transfer_event(side, agent, result):
    if result.get("kind") != "work" or result.get("spent", 0.0) <= 0:
        return []
    return [
        {
            "kind": "transfer",
            "frm": side,
            "work": float(result.get("spent", 0.0)),
            "hit": bool(result.get("success", False)),
            "gained": int(max(0.0, result.get("gain", 0.0))),
            "type": str(result.get("form", agent.defense)),
        }
    ]


class ArenaAgent:
    def __init__(
        self,
        agent_id,
        policy=None,
        profile="CANON",
        seed=0,
        force=100.0,
        energy=100.0,
        max_force=100.0,
        max_energy=100.0,
        health=HEALTH_MAX,
        max_health=HEALTH_MAX,
        health_factors=None,
        sickness=0.0,
    ):
        self.id = str(agent_id)
        self.profile = str(profile)
        self.seed = int(seed)
        self.rng = random.Random(seed)
        self.policy = policy if policy is not None else _RestPolicy()
        skill, authority = PROFILE_SKILLS.get(
            self.profile, PROFILE_SKILLS["CANON"]
        )
        factors = dict(DEFAULT_HEALTH_FACTORS)
        if health_factors:
            factors.update(health_factors)
        self.unit = Automaton(
            id=self.id,
            force=float(force),
            energy=float(energy),
            max_force=float(max_force),
            max_energy=float(max_energy),
            health=float(health),
            max_health=float(max_health),
            health_factors=factors,
            sickness=max(0.0, min(SICKNESS_MAX, float(sickness))),
            inputs=FORMS,
            outputs=FORMS,
            skills={
                "force": float(skill),
                "info": max(0.0, 1.0 - float(skill)),
            },
            authority=float(authority),
        )
        self.unit.handlers["force"] = self._force_handler
        self.unit.handlers["info"] = self._info_handler
        self.last_action = Action("REST", form="rest")
        self.last_act = "REST"
        self.last_work = 0.0
        self.rest_units = 0.0
        self.p = 1.0
        self._last_observation = None
        self._last_action = None
        self._last_opponent = None

    @property
    def force(self):
        return float(self.unit.force)

    @force.setter
    def force(self, value):
        self.unit.force = max(0.0, float(value))

    @property
    def energy_pool(self):
        return float(self.unit.energy)

    @energy_pool.setter
    def energy_pool(self, value):
        self.unit.energy = max(0.0, float(value))

    @property
    def rest_ceiling(self):
        return float(self.unit.max_force)

    @property
    def max_force(self):
        return float(self.unit.max_force)

    @property
    def max_energy(self):
        return float(self.unit.max_energy)

    @property
    def energy_ratio(self):
        return self.energy_pool / max(1.0, self.max_energy)

    @property
    def health(self):
        return float(self.unit.health)

    @health.setter
    def health(self, value):
        self.unit.health = max(0.0, min(self.unit.max_health, float(value)))

    @property
    def max_health(self):
        return float(self.unit.max_health)

    @property
    def health_ratio(self):
        return self.unit.health_ratio

    @property
    def is_dead(self):
        return self.unit.is_dead

    @property
    def sickness(self):
        return float(self.unit.sickness)

    @sickness.setter
    def sickness(self, value):
        self.unit.sickness = max(
            0.0, min(SICKNESS_MAX, float(value))
        )

    @property
    def is_sick(self):
        return self.unit.is_sick

    def infect(self, severity):
        return self.unit.infect(severity)

    def treat(self, amount):
        return self.unit.treat(amount)

    def set_health_factor(self, name, value):
        self.unit.health_factors[str(name)] = max(
            0.0, min(HEALTH_FACTOR_MAX, float(value))
        )
        return self.unit.health_factors[str(name)]

    def set_health_factors(self, factors):
        for name, value in dict(factors).items():
            self.set_health_factor(name, value)

    @property
    def regen(self):
        return int(REST_REGEN)

    @property
    def defense(self):
        if self.last_action.kind == "WORK":
            return self.last_action.form
        return "force"

    @property
    def in_open(self):
        return bool(self.unit.is_open())

    @property
    def w_adopt(self):
        return float(self.unit.pressure())

    @property
    def open_timer(self):
        return int(max(0.0, self.unit.pressure()))

    def schmitt_on(self):
        return OPEN_PRESSURE

    @property
    def Q(self):
        table = getattr(self.policy, "table", None)
        return table if isinstance(table, dict) else {}

    def set_profile(self, profile):
        profile = str(profile)
        if profile not in PROFILE_SKILLS:
            return False
        self.profile = profile
        skill, authority = PROFILE_SKILLS[profile]
        self.unit.skills = {
            "force": float(skill),
            "info": max(0.0, 1.0 - float(skill)),
        }
        self.unit.authority = float(authority)
        return True

    def reset_state(self, seed=None):
        if seed is not None:
            self.seed = int(seed)
            self.rng = random.Random(self.seed)
        self.unit.force = self.unit.max_force
        self.unit.energy = self.unit.max_energy
        self.unit.health = self.unit.max_health
        self.unit.sickness = 0.0
        self.unit.state["pressure"] = 0.0
        self.last_action = Action("REST", form="rest")
        self.last_act = "REST"
        self.last_work = 0.0
        self.rest_units = 0.0
        self._last_observation = None
        self._last_action = None

    def actions(self):
        return tuple(
            action_from_index(index) for index in range(len(CORE_ACTIONS))
        )

    def observe(self, opponent):
        other = opponent.unit if hasattr(opponent, "unit") else opponent
        forms = tuple(
            form for form in self.unit.outputs if other.can_receive(form)
        )
        if not forms:
            forms = ("force",)
        observation = Observation(
            self_force=self.force,
            self_energy=self.energy_pool,
            self_max_force=self.unit.max_force,
            self_max_energy=self.unit.max_energy,
            opponent_force=float(other.force),
            opponent_energy=float(other.energy),
            opponent_max_force=float(other.max_force),
            opponent_max_energy=float(other.max_energy),
            opponent_pressure=float(other.pressure()),
            opponent_open=bool(other.is_open()),
            time=float(getattr(self, "_time", 0.0)),
            forms=forms,
            opponent_defense=(
                getattr(opponent, "defense", "")
                if hasattr(opponent, "defense")
                else ""
            ),
            self_health=self.health,
            self_max_health=self.max_health,
            opponent_health=float(other.health),
            opponent_max_health=float(other.max_health),
        )
        return observation

    def choose_action(self, opponent, explore=True):
        observation = self.observe(opponent)
        action = self.policy.act(observation, self.actions(), explore=explore)
        self.record_action(action, opponent, observation)
        return action, observation

    def record_action(self, action, opponent=None, observation=None):
        self._last_observation = (
            observation if observation is not None else self.observe(opponent)
        )
        self._last_action = action
        self._last_opponent = opponent
        return action

    def learn(self, reward, next_observation, done, opponent=None):
        if self._last_observation is None or self._last_action is None:
            return
        other = opponent if opponent is not None else self._last_opponent
        next_actions = self.actions()
        if other is not None:
            next_actions = tuple(
                action
                for action in self.actions()
                if action.kind == "REST"
                or other.unit.can_receive(action.form)
            )
        transition = Transition(
            observation=self._last_observation,
            action=self._last_action,
            reward=float(reward),
            next_observation=next_observation,
            done=bool(done),
            next_actions=next_actions,
        )
        self.policy.observe(transition)
        self._last_observation = None
        self._last_action = None
        self._last_opponent = None

    def _force_handler(self, target, work, source, world):
        return self._receive_work(target, work, source, world, "force")

    def _info_handler(self, target, work, source, world):
        return self._receive_work(target, work, source, world, "info")

    def _receive_work(self, target, work, source, world, form):
        if source is None:
            return target.default_receive(work)
        if not target.can_receive(form):
            return {
                "accepted": False,
                "success": False,
                "energy": 0.0,
                "force": 0.0,
                "pressure": 0.0,
            }
        was_open = target.is_open()
        chance = success_probability(source, target, work, was_open)
        rng = getattr(world, "rng", self.rng)
        target.energy = min(
            target.max_energy, target.energy + work.amount * 0.12
        )
        pressure = work.amount * PRESSURE_PER_WORK
        target.state["pressure"] = min(
            30.0, target.pressure() + pressure
        )
        success = rng.random() < chance
        damage = 0.0
        gain = 0.0
        health_damage = 0.0
        if success:
            base = 0.55 if form == "force" else 0.30
            scale = 0.30 if form == "force" else 0.15
            damage = max(
                0.0,
                work.amount * (base - scale * target.resistance(form)),
            )
            _absorbed, _overflow, health_damage = target.apply_force_damage(
                damage
            )
            gain = min(
                source.max_force - source.force, damage * 0.20
            )
            source.force += max(0.0, gain)
        return {
            "accepted": True,
            "success": success,
            "energy": work.amount * 0.12,
            "force": damage,
            "damage": damage,
            "health": health_damage,
            "gain": gain,
            "pressure": pressure,
            "chance": chance,
            "was_open": was_open,
        }


class ArenaMatch:
    def __init__(
        self,
        seed=0,
        steps=2000,
        rl_policy=None,
        ai_policy=None,
        profile_rl="CANON",
        profile_ai="CANON",
        health_factors_rl=None,
        health_factors_ai=None,
        sickness_rl=0.0,
        sickness_ai=0.0,
        with_env=False,
    ):
        self.seed = int(seed)
        self.steps_total = int(steps)
        self.rng = random.Random(self.seed)
        self.with_env = bool(with_env)
        self.time = 0
        self.step = 0
        self.winner = None
        self.finished = False
        self.events = []
        self.rl_hist = []
        self.ai_hist = []
        self.dom_rl = 0
        self.dom_ai = 0
        self.rl_rest_ticks = 0
        self.ai_rest_ticks = 0
        self.last_rl_action = ("REST", 0.0)
        self.last_ai_action = ("REST", 0.0)
        self.rl = ArenaAgent(
            "rl",
            policy=rl_policy,
            profile=profile_rl,
            seed=self.seed ^ 0x5EED,
            health_factors=health_factors_rl,
            sickness=sickness_rl,
        )
        self.ai = ArenaAgent(
            "ai",
            policy=ai_policy,
            profile=profile_ai,
            seed=self.seed ^ 0xA11E,
            health_factors=health_factors_ai,
            sickness=sickness_ai,
        )

    def step_tick(self, forced_rl_action=None):
        if self.finished:
            return
        self.events = []
        rl, ai = self.rl, self.ai

        rl._time = self.time
        ai._time = self.time
        rl_obs = rl.observe(ai)
        ai_obs = ai.observe(rl)

        if forced_rl_action is None:
            rl_action, _ = rl.choose_action(ai, explore=True)
        else:
            if isinstance(forced_rl_action, Action):
                rl_action = forced_rl_action
            else:
                rl_action = action_from_index(forced_rl_action)
            rl.record_action(rl_action, ai, rl_obs)

        ai_action, _ = ai.choose_action(rl, explore=True)

        rl_before = (rl.force, rl.energy_pool, rl.health)
        ai_before = (ai.force, ai.energy_pool, ai.health)

        rl_result = self._perform(rl, ai, rl_action)
        ai_result = self._perform(ai, rl, ai_action)

        rl.unit.decay_pressure()
        ai.unit.decay_pressure()
        self.time += 1
        self.step += 1

        reward_rl = self._reward(rl, rl_before, ai, ai_before)
        reward_ai = self._reward(ai, ai_before, rl, rl_before)

        terminal = self._check_terminal()
        if not terminal:
            capture_winner, cap = self._check_capture()
            if capture_winner and not self.finished:
                self.events.append(
                    {
                        "kind": "capture",
                        "winner": capture_winner,
                        "cap": cap,
                    }
                )
                self.winner = capture_winner
                self.finished = True
                terminal = True

        rl_next = rl.observe(ai)
        ai_next = ai.observe(rl)
        rl.learn(reward_rl, rl_next, terminal, ai)
        ai.learn(reward_ai, ai_next, terminal, rl)

        self.events.extend(self._event("rl", rl, rl_result))
        self.events.extend(self._event("ai", ai, ai_result))

        self.last_rl_action = (
            rl_action.form if rl_action.kind == "WORK" else "REST",
            float(rl_result.get("spent", 0.0)),
        )
        self.last_ai_action = (
            ai_action.form if ai_action.kind == "WORK" else "REST",
            float(ai_result.get("spent", 0.0)),
        )
        rl.last_act = self.last_rl_action[0]
        ai.last_act = self.last_ai_action[0]
        rl.last_work = rl_result.get("spent", 0.0)
        ai.last_work = ai_result.get("spent", 0.0)

        if rl_result.get("spent", 0.0) <= 0.0:
            self.rl_rest_ticks += 1
        if ai_result.get("spent", 0.0) <= 0.0:
            self.ai_rest_ticks += 1

        self.rl.rest_units = max(0.0, rl.rest_ceiling - rl.force)
        self.ai.rest_units = max(0.0, ai.rest_ceiling - ai.force)
        self.rl_hist.append(rl.force)
        self.ai_hist.append(ai.force)

    def _reward(self, me, before, other, other_before):
        return (
            (me.force - before[0]) / max(1.0, me.rest_ceiling)
            + (other_before[0] - other.force) / max(1.0, other.rest_ceiling)
            - 0.6 * (before[1] - me.energy_pool) / max(1.0, me.unit.max_energy)
            + (me.health - before[2]) / max(1.0, me.max_health)
            + (other_before[2] - other.health)
            / max(1.0, other.max_health)
        )

    def _perform(self, attacker, defender, action):
        return _perform(attacker, defender, action, self)

    def _event(self, side, agent, result):
        return _transfer_event(side, agent, result)

    def _check_terminal(self):
        if self.finished:
            return True
        rl, ai = self.rl, self.ai
        if rl.is_dead and ai.is_dead:
            self.winner = "draw"
        elif rl.is_dead:
            self.winner = "AI"
        elif ai.is_dead:
            self.winner = "RL"
        if self.winner is not None:
            self.finished = True
            return True
        if self.step >= self.steps_total:
            self.finished = True
            if (rl.force, rl.health) > (ai.force, ai.health):
                self.winner = "RL"
            elif (ai.force, ai.health) > (rl.force, rl.health):
                self.winner = "AI"
            else:
                self.winner = None
            return True
        return False

    def _check_capture(self):
        winner, self.dom_rl, self.dom_ai, cap = _resolve_capture(
            self.rl, self.ai, self.dom_rl, self.dom_ai
        )
        return winner, cap


def run_duel_tick(
    left,
    left_action,
    right,
    right_action,
    rng=None,
    *,
    left_id="left",
    right_id="right",
):
    match = _DuelTick(left, right, rng or random.Random(0))
    left_result = match.perform(left, right, left_action)
    right_result = match.perform(right, left, right_action)
    left.last_action = left_action
    right.last_action = right_action
    left.last_act = left_action.form if left_action.kind == "WORK" else "REST"
    right.last_act = (
        right_action.form if right_action.kind == "WORK" else "REST"
    )
    left.last_work = float(left_result.get("spent", 0.0))
    right.last_work = float(right_result.get("spent", 0.0))
    left.unit.decay_pressure()
    right.unit.decay_pressure()
    left.rest_units = max(0.0, left.rest_ceiling - left.force)
    right.rest_units = max(0.0, right.rest_ceiling - right.force)
    events = []
    for side, agent, result in (
        (left_id, left, left_result),
        (right_id, right, right_result),
    ):
        events.extend(_transfer_event(side, agent, result))
    return events, left_result, right_result


class _DuelTick:
    def __init__(self, left, right, rng):
        self.left = left
        self.right = right
        self.rng = rng

    def perform(self, attacker, defender, action):
        return _perform(attacker, defender, action, self)


def _resolve_capture(
    rl, ai, dom_rl=0, dom_ai=0, winner_rl="RL", winner_ai="AI"
):
    dom_rl = (
        dom_rl + 1
        if (
            rl.energy_pool >= CAPTURE_RATIO * ai.energy_pool
            and rl.force > ai.force
        )
        else 0
    )
    dom_ai = (
        dom_ai + 1
        if (
            ai.energy_pool >= CAPTURE_RATIO * rl.energy_pool
            and ai.force > rl.force
        )
        else 0
    )
    if dom_rl >= CAPTURE_STREAK:
        severity = 2.0 if ai.in_open else 1.0
        cap = int(ai.force * min(CAPTURE_FRAC * severity, 0.5))
        ai.force = max(1.0, ai.force - cap)
        ai.rest_units = max(0.0, ai.rest_units - cap / L_STEP)
        rl.force = min(rl.rest_ceiling, rl.force + cap * 0.20)
        return winner_rl, 0, 0, cap
    if dom_ai >= CAPTURE_STREAK:
        severity = 2.0 if rl.in_open else 1.0
        cap = int(rl.force * min(CAPTURE_FRAC * severity, 0.5))
        rl.force = max(1.0, rl.force - cap)
        rl.rest_units = max(0.0, rl.rest_units - cap / L_STEP)
        ai.force = min(ai.rest_ceiling, ai.force + cap * 0.20)
        return winner_ai, 0, 0, cap
    return None, dom_rl, dom_ai, 0


def check_capture(
    rl,
    ai,
    dom_rl=0,
    dom_ai=0,
    winner_rl="RL",
    winner_ai="AI",
):
    winner, dom_rl, dom_ai, _cap = _resolve_capture(
        rl, ai, dom_rl, dom_ai, winner_rl, winner_ai
    )
    return winner, dom_rl, dom_ai


__all__ = [
    "ArenaAgent",
    "ArenaMatch",
    "CAPTURE_FRAC",
    "CAPTURE_RATIO",
    "CAPTURE_STREAK",
    "CORE_ACTIONS",
    "FORMS",
    "FRACTIONS",
    "L_STEP",
    "OPEN_PRESSURE",
    "action_from_index",
    "check_capture",
    "run_duel_tick",
]
