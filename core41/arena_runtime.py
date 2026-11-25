"""Агенты и матч арены: исполнение работ, награды и терминальные исходы.

Вынесено из ``core41/arena.py`` после W4. Разрешение работ и профили
наград остаются в ``arena.py``; этот модуль содержит ``ArenaAgent``,
``ArenaMatch`` и утилиты матча.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .environment import ArenaEnvironment
from .intel import Intel
from .model import (
    DEFAULT_HEALTH_FACTORS,
    FORCE_FEEDBACK_SHARE,
    HEALTH_FACTOR_MAX,
    HEALTH_MAX,
    OPEN_PRESSURE,
    PRESSURE_PER_WORK,
    RECEIVE_ENERGY_SHARE,
    REST_FORCE,
    REST_REGEN,
    SICKNESS_TREAT_RATE,
    SICKNESS_MAX,
    TREAT_ENERGY_FRACTION,
    WOUND_MAX,
    WOUND_TREAT_RATE,
    INTEL_DAMAGE_BONUS,
    Automaton,
    conversion_report,
    success_probability,
    transmit_sickness,
)
from .types import Action, Observation, Transition, Work, WorkReport
from .arena import (
    CAPTURE_FRAC,
    CAPTURE_RATIO,
    CAPTURE_STREAK,
    CHARGE_DAMAGE_BONUS,
    CORE_ACTIONS,
    FORMS,
    INFO_PRESSURE_PER_WORK,
    L_STEP,
    PROFILE_SKILLS,
    REWARD_PROFILES,
    REWARD_PROFILE_DEFAULT,
    WAIT_ACTION,
    WOUND_HIT_SEVERITY,
    _RestPolicy,
    _plan_events,
    action_from_index,
    resolve_pair,
    reward_delta,
    terminal_reward,
)


def _transfer_event(side, agent, result):
    events = []
    if result.get("kind") == "work" and result.get("spent", 0.0) > 0:
        events.append(
            {
                "kind": "transfer",
                "frm": side,
                "work": float(result.get("spent", 0.0)),
                "hit": bool(result.get("success", False)),
                "gained": int(max(0.0, result.get("gain", 0.0))),
                "type": str(result.get("form", agent.defense)),
            }
        )
    infection = float(result.get("infection", 0.0))
    if infection > 0.0:
        events.append(
            {
                "kind": "infection",
                "frm": side,
                "amount": infection,
            }
        )
    return events


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
        wound=0.0,
        fog=True,
    ):
        self.id = str(agent_id)
        self.profile = str(profile)
        self.seed = int(seed)
        self.rng = random.Random(seed)
        self.policy = policy if policy is not None else _RestPolicy()
        self.fog = bool(fog)
        self.intel = Intel()
        self.pending = None
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
            wound=max(0.0, min(WOUND_MAX, float(wound))),
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

    @property
    def wound(self):
        return float(self.unit.wound)

    @wound.setter
    def wound(self, value):
        self.unit.wound = max(0.0, min(WOUND_MAX, float(value)))

    @property
    def is_wounded(self):
        return self.unit.is_wounded

    def infect(self, severity):
        return self.unit.infect(severity)

    def treat(self, amount):
        return self.unit.treat(amount)

    def injure(self, severity):
        return self.unit.injure(severity)

    def treat_wound(self, amount):
        return self.unit.treat_wound(amount)

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
        if self.last_action.kind in ("WORK", "TREAT"):
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
        self.unit.wound = 0.0
        self.unit.state["pressure"] = 0.0
        self.last_action = Action("REST", form="rest")
        self.last_act = "REST"
        self.last_work = 0.0
        self.rest_units = 0.0
        self.pending = None
        self.intel = Intel()
        self._last_observation = None
        self._last_action = None

    def condition_state(self):
        """Снимок состояния здоровья.

        `wound` включается только когда он ненулевой: легаси-снимки
        `(health, sickness)` остаются каноничными для здоровых агентов,
        а острые раны переносятся между матчами и сохранениями.
        """
        state = {
            "health": float(self.health),
            "sickness": float(self.sickness),
        }
        if self.wound > 0.0:
            state["wound"] = float(self.wound)
        return state

    def load_condition(self, state):
        state = state or {}
        if state.get("health") is not None:
            self.unit.health = max(
                0.0,
                min(self.unit.max_health, float(state["health"])),
            )
        if state.get("sickness") is not None:
            self.sickness = float(state["sickness"])
        if state.get("wound") is not None:
            self.wound = float(state["wound"])
        return self.condition_state()

    def actions(self):
        if self.pending is not None:
            return (WAIT_ACTION,)
        actions = []
        if self.needs_recovery():
            actions.append(action_from_index(0))
        if self.sickness > 0.0 or self.wound > 0.0:
            actions.append(action_from_index(1))
        for index in range(2, len(CORE_ACTIONS)):
            actions.append(action_from_index(index))
        return tuple(actions)

    def needs_recovery(self):
        """Есть ли смысл в REST: неполная энергия/сила/здоровье или болезнь."""
        return bool(
            self.energy_pool < self.max_energy - 1e-9
            or self.force < self.max_force - 1e-9
            or self.health < self.max_health - 1e-9
            or self.sickness > 0.0
            or self.wound > 0.0
        )

    def advance_pending(self):
        """Продвинуть многотактную работу; вернуть `Work` в такт удара."""
        pending = self.pending
        if pending is None:
            return None
        pending.remaining -= 1
        if pending.remaining > 0:
            return None
        self.pending = None
        return pending.work

    def observe(self, opponent):
        other = opponent.unit if hasattr(opponent, "unit") else opponent
        forms = tuple(
            form for form in self.unit.outputs if other.can_receive(form)
        )
        if not forms:
            forms = ("force",)
        if self.fog:
            opponent_energy = self.intel.estimate(
                "energy", other.energy
            )
            opponent_health = self.intel.estimate(
                "health", other.health
            )
            opponent_sickness = self.intel.estimate(
                "sickness", other.sickness
            )
            opponent_wound = self.intel.estimate(
                "wound", other.wound
            )
        else:
            opponent_energy = float(other.energy)
            opponent_health = float(other.health)
            opponent_sickness = float(other.sickness)
            opponent_wound = float(other.wound)
        pending = getattr(opponent, "pending", None)
        pending_action = pending.action if pending is not None else None
        observation = Observation(
            self_force=self.force,
            self_energy=self.energy_pool,
            self_max_force=self.unit.max_force,
            self_max_energy=self.unit.max_energy,
            opponent_force=float(other.force),
            opponent_energy=opponent_energy,
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
            self_sickness=self.sickness,
            opponent_health=opponent_health,
            opponent_max_health=float(other.max_health),
            opponent_sickness=opponent_sickness,
            self_wound=self.wound,
            opponent_wound=opponent_wound,
            env_pressure=float(getattr(self, "_env_pressure", 0.0)),
            env_season=float(getattr(self, "_env_season", 1.0)),
            env_window=float(getattr(self, "_env_window", 0.0)),
            opponent_confidence=(
                float(self.intel.confidence) if self.fog else 1.0
            ),
            opponent_weak_point=(
                float(self.intel.weak_point) if self.fog else 0.0
            ),
            self_busy=1.0 if self.pending is not None else 0.0,
            opponent_busy=1.0 if pending is not None else 0.0,
            opponent_pending_form=(
                str(pending_action.form) if pending_action else ""
            ),
            opponent_pending_fraction=(
                float(pending_action.fraction) if pending_action else 0.0
            ),
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

    def learn(
        self,
        reward,
        next_observation,
        done,
        opponent=None,
        opponent_action=None,
    ):
        if self._last_observation is None or self._last_action is None:
            return
        other = opponent if opponent is not None else self._last_opponent
        next_actions = self.actions()
        if other is not None:
            next_actions = tuple(
                action
                for action in self.actions()
                if action.kind in ("REST", "WAIT")
                or other.unit.can_receive(action.form)
            )
        info = {}
        if opponent_action is not None:
            info["opponent_action"] = opponent_action
        transition = Transition(
            observation=self._last_observation,
            action=self._last_action,
            reward=float(reward),
            next_observation=next_observation,
            done=bool(done),
            next_actions=next_actions,
            info=info,
        )
        self.policy.observe(transition)
        self._last_observation = None
        self._last_action = None
        self._last_opponent = None

    def _force_handler(self, target, work, source, world):
        return _receive_force(target, work, source, world)

    def _info_handler(self, target, work, source, world):
        return _receive_info(target, work, source, world)


def _receive_force(target, work, source, world):
    """Канонический обработчик формы `force`.

    Детерминированная функция `(target, work, source, world) -> WorkReport`:
    стохастика (`rng`, `chance`) приходит из `world`, чтобы обработчик
    оставался чистым. Возвращает `WorkReport` с полями, ожидаемыми
    `resolve_work` (`accepted/success/energy/force/pressure/...`).

    Урон **копится в ``world``**, а не применяется к ``target`` напрямую:
    иначе `_ResolveWorld.flush` применит его второй раз. Это то же
    разделение, что в легаси-ветке (`apply_force_damage` там внутри
    `resolve_work`, а не в обработчике).
    """
    return _receive_channel(target, work, source, world, "force")


def _receive_info(target, work, source, world):
    """Канонический обработчик формы `info`: давление без урона.

    Давление копится в ``world``; ``flush`` применит его к получателю.
    """
    return _receive_channel(target, work, source, world, "info")


def _receive_channel(target, work, source, world, form):
    """Общий канонический обработчик арены для `force`/`info`.

    Сохраняет калибровку легаси-ветки один-в-один: `force` — урон
    `0.55/0.30`, прирост `0.20`, энергия `0.12`; `info` — давление
    `INFO_PRESSURE_PER_WORK`, без энергии и урона.

    Ключевое отличие от легаси: обработчик **не применяет**
    урон/давление/рану к ``target`` напрямую, а копит их в ``world``
    (`add_force_damage`, `add_gain`, `add_wound`, `add_infection`,
    `add_pressure`). ``_ResolveWorld.flush`` применит всё за один раз.
    Это устраняет двойное применение урона и сохраняет golden.
    """
    from .model import _report_from_conversion

    if not target.can_receive(form):
        report = conversion_report(work.amount, form, 0.0, 0.0)
        return _report_from_conversion(
            report,
            accepted=False,
            success=False,
        )
    chance = float(getattr(world, "chance", 0.0))
    rng = getattr(world, "rng", None)
    if rng is None:
        rng = random.Random(0)
    was_open = bool(getattr(world, "was_open", target.is_open()))
    pressure_rate = (
        INFO_PRESSURE_PER_WORK if form == "info" else PRESSURE_PER_WORK
    )
    pressure = work.amount * pressure_rate
    success = rng.random() < chance
    if form == "info":
        world.add_pressure(pressure)
        report = conversion_report(work.amount, form, 0.0)
        return _report_from_conversion(
            report,
            accepted=True,
            success=bool(success),
            extra={
                "energy": 0.0,
                "force": 0.0,
                "damage": 0.0,
                "health": 0.0,
                "wound": 0.0,
                "gain": 0.0,
                "pressure": pressure,
                "chance": chance,
                "was_open": was_open,
            },
        )
    stored = target.add_energy(work.amount * 0.12)
    damage = 0.0
    gain = 0.0
    health_damage = 0.0
    wound_severity = 0.0
    infection = 0.0
    if success:
        charge = 1.0 + CHARGE_DAMAGE_BONUS * max(
            0.0, float(work.duration) - 1.0
        )
        weak_point = float(getattr(world, "weak_point", 0.0))
        exploit = 1.0 + INTEL_DAMAGE_BONUS * min(
            1.0, max(0.0, weak_point)
        )
        damage = max(
            0.0,
            work.amount
            * (0.55 - 0.30 * target.resistance(form))
            * charge
            * exploit,
        )
        world.add_force_damage(damage)
        if source is not None:
            gain = min(
                source.max_force - source.force,
                damage * 0.20,
            )
            world.add_gain(gain)
        if damage > 0.0:
            wound_severity = min(
                WOUND_MAX,
                WOUND_HIT_SEVERITY * damage
                / max(1.0, target.max_health),
            )
            if wound_severity > 0.0:
                world.add_wound(wound_severity)
        if source is not None:
            infection = transmit_sickness(
                source, target, rng, form
            )
            if infection > 0.0:
                world.add_infection(infection)
    world.add_pressure(pressure)
    report = conversion_report(work.amount, form, stored)
    extra = {
        "energy": work.amount * 0.12,
        "force": damage,
        "damage": damage,
        "health": health_damage,
        "wound": wound_severity,
        "gain": gain,
        "pressure": pressure,
        "chance": chance,
        "was_open": was_open,
        "infection": infection,
    }
    payload = getattr(work, "payload", ())
    if payload:
        extra["payload_received"] = True
    return _report_from_conversion(
        report,
        accepted=True,
        success=bool(success),
        extra=extra,
    )


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
        wound_rl=0.0,
        wound_ai=0.0,
        with_env=False,
        env_plan=None,
        auto_learn=True,
        fog=True,
        reward_profile=REWARD_PROFILE_DEFAULT,
    ):
        self.seed = int(seed)
        self.steps_total = int(steps)
        self.rng = random.Random(self.seed)
        self.with_env = bool(with_env)
        self.auto_learn = bool(auto_learn)
        if reward_profile not in REWARD_PROFILES:
            raise ValueError(
                "неизвестный профиль награды: %r" % (reward_profile,)
            )
        self.reward_profile = str(reward_profile)
        self.fog = bool(fog)
        self.time = 0
        self.step = 0
        self.winner = None
        self.finished = False
        self.events = []
        self.last_rewards = {"rl": 0.0, "ai": 0.0}
        self.rl_hist = []
        self.ai_hist = []
        self.dom_rl = 0
        self.dom_ai = 0
        self.rl_rest_ticks = 0
        self.ai_rest_ticks = 0
        self.last_rl_action = ("REST", 0.0)
        self.last_ai_action = ("REST", 0.0)
        self.env_outcome = None
        self.env_event = None
        self.rl = ArenaAgent(
            "rl",
            policy=rl_policy,
            profile=profile_rl,
            seed=self.seed ^ 0x5EED,
            health_factors=health_factors_rl,
            sickness=sickness_rl,
            wound=wound_rl,
            fog=self.fog,
        )
        self.ai = ArenaAgent(
            "ai",
            policy=ai_policy,
            profile=profile_ai,
            seed=self.seed ^ 0xA11E,
            health_factors=health_factors_ai,
            sickness=sickness_ai,
            wound=wound_ai,
            fog=self.fog,
        )
        self.rl.intel.reset(self.ai.unit)
        self.ai.intel.reset(self.rl.unit)
        self.env = (
            ArenaEnvironment(seed=self.seed ^ 0xE7E7, plan=env_plan)
            if self.with_env
            else None
        )

    def _coerce_action(self, action):
        if isinstance(action, Action):
            return action
        return action_from_index(action)

    def step_tick(self, forced_rl_action=None, forced_ai_action=None):
        if self.finished:
            return
        self.events = []
        self.env_event = None
        rl, ai = self.rl, self.ai

        rl._time = self.time
        ai._time = self.time
        if self.env is not None:
            env_state = self.env.public_state()
            for actor in (rl, ai):
                actor._env_pressure = env_state["strain"]
                actor._env_season = env_state["season_multiplier"]
                actor._env_window = 1.0 if env_state["window"] else 0.0
        else:
            for actor in (rl, ai):
                actor._env_pressure = 0.0
                actor._env_season = 1.0
                actor._env_window = 0.0
        rl_obs = rl.observe(ai)
        ai_obs = ai.observe(rl)

        if self.env is not None:
            env_events = self.env.tick(rl, ai)
            self.events.extend(env_events)
            for event in env_events:
                if (
                    event.get("kind") == "environment"
                    and event.get("event") in ("goal", "collapse")
                ):
                    self.env_event = event["event"]
                    self.env_outcome = self.env_event
                    break

        if forced_rl_action is None:
            rl_action, _ = rl.choose_action(ai, explore=True)
        else:
            rl_action = self._coerce_action(forced_rl_action)
            rl.record_action(rl_action, ai, rl_obs)

        if forced_ai_action is None:
            ai_action, _ = ai.choose_action(rl, explore=True)
        else:
            ai_action = self._coerce_action(forced_ai_action)
            ai.record_action(ai_action, rl, ai_obs)

        rl_before = (
            rl.force,
            rl.energy_pool,
            rl.health,
            rl.sickness,
            rl.wound,
        )
        ai_before = (
            ai.force,
            ai.energy_pool,
            ai.health,
            ai.sickness,
            ai.wound,
        )

        rl_plan, ai_plan, rl_result, ai_result = resolve_pair(
            rl,
            ai,
            rl_action,
            ai_action,
            self.rng,
            env=self.env,
        )
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

        if terminal:
            reward_rl += terminal_reward(self.winner, "rl")
            reward_ai += terminal_reward(self.winner, "ai")
        self.last_rewards = {"rl": reward_rl, "ai": reward_ai}

        rl_next = rl.observe(ai)
        ai_next = ai.observe(rl)
        if self.auto_learn:
            rl.learn(
                reward_rl,
                rl_next,
                terminal,
                ai,
                opponent_action=ai_action,
            )
            ai.learn(
                reward_ai,
                ai_next,
                terminal,
                rl,
                opponent_action=rl_action,
            )

        self.events.extend(
            _plan_events("rl", rl, rl_plan, rl_result)
        )
        self.events.extend(
            _plan_events("ai", ai, ai_plan, ai_result)
        )

        self.last_rl_action = (
            rl.last_act,
            float(rl_result.get("spent", 0.0)),
        )
        self.last_ai_action = (
            ai.last_act,
            float(ai_result.get("spent", 0.0)),
        )

        if rl_plan.get("kind") == "rest":
            self.rl_rest_ticks += 1
        if ai_plan.get("kind") == "rest":
            self.ai_rest_ticks += 1

        self.rl.rest_units = max(0.0, rl.rest_ceiling - rl.force)
        self.ai.rest_units = max(0.0, ai.rest_ceiling - ai.force)
        self.rl_hist.append(rl.force)
        self.ai_hist.append(ai.force)

    def _reward(self, me, before, other, other_before):
        return reward_delta(
            me,
            before,
            other,
            other_before,
            profile=self.reward_profile,
        )

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
    """Один одновременный такт дуэли для UI и экспериментов.

    Оба действия считаются от снимка начала такта; результат не зависит от
    порядка сторон. Возвращает события, результат левой и правой стороны.
    """
    left_plan, right_plan, left_result, right_result = resolve_pair(
        left,
        right,
        left_action,
        right_action,
        rng or random.Random(0),
    )
    events = []
    events.extend(_plan_events(left_id, left, left_plan, left_result))
    events.extend(_plan_events(right_id, right, right_plan, right_result))
    return events, left_result, right_result


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
    "FORCE_WORK_RATIO",
    "FORMS",
    "FRACTIONS",
    "INFO_COST_FACTOR",
    "L_STEP",
    "OPEN_PRESSURE",
    "PendingWork",
    "WAIT_ACTION",
    "action_from_index",
    "check_capture",
    "resolve_pair",
    "resolve_work",
    "run_duel_tick",
    "work_amount",
    "work_duration",
]


if __name__ == "__main__":
    print("core41.arena — библиотечный модуль арены, а не точка входа.")
    print("Запуск арены: python3 main.py --arena")
    print("Демо ядра:    python3 -m core41 --demo")
    print("Импорт:       from core41.arena import ArenaMatch")
    raise SystemExit(0)
