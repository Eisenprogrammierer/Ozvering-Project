import random

from .arena import reward_delta, terminal_reward
from .model import (
    PRESSURE_PER_WORK,
    REST_FORCE,
    REST_REGEN,
    SICKNESS_TREAT_RATE,
    TREAT_ENERGY_FRACTION,
    Automaton,
    success_probability,
    transmit_sickness,
)
from .types import Action, Observation, Work


class DuelWorld:

    def __init__(self, seed=0, max_steps=200):
        self.seed = seed
        self.max_steps = max_steps
        self.rng = random.Random(seed)
        self.time = 0
        self.agent = None
        self.opponent = None
        self.reset(seed)

    def _make(self, name, skill, authority):
        unit = Automaton(
            id=name,
            skills={"force": skill, "info": max(0.0, 1.0 - skill)},
            authority=authority,
        )
        unit.handlers["force"] = self._force_handler
        return unit

    def _force_handler(self, target, work, source, world):
        if source is None:
            return target.default_receive(work)
        if not target.can_receive(work.form):
            return {
                "accepted": False,
                "success": False,
                "energy": 0.0,
                "force": 0.0,
                "pressure": 0.0,
            }
        was_open = target.is_open()
        chance = success_probability(source, target, work, was_open)
        target.energy = min(
            target.max_energy, target.energy + work.amount * 0.12
        )
        target.state["pressure"] = min(
            30.0, target.pressure() + work.amount * PRESSURE_PER_WORK
        )
        success = self.rng.random() < chance
        damage = 0.0
        gain = 0.0
        health_damage = 0.0
        if success:
            damage = work.amount * (
                0.55 - 0.30 * target.resistance(work.form)
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
            "health": health_damage,
            "gain": gain,
            "pressure": work.amount * PRESSURE_PER_WORK,
            "chance": chance,
            "was_open": was_open,
        }

    def reset(self, seed=None):
        if seed is not None:
            self.seed = seed
        self.rng = random.Random(self.seed)
        self.time = 0
        self.agent = self._make("agent", 0.62, 0.10)
        self.opponent = self._make("opponent", 0.52, 0.0)
        return self.observe("agent")

    def _perform(self, attacker, defender, action):
        if action.kind == "TREAT":
            amount = min(
                attacker.energy,
                max(0.0, min(1.0, action.fraction))
                * attacker.max_energy,
            )
            attacker.energy -= amount
            if amount > 0.0 and attacker.sickness > 0.0:
                attacker.treat(SICKNESS_TREAT_RATE)
            attacker.tick_health(resting=False)
            return {
                "kind": "treat",
                "spent": amount,
                "success": True,
                "damage": 0.0,
                "form": "care",
            }
        if action.kind == "REST":
            attacker.energy = min(
                attacker.max_energy, attacker.energy + REST_REGEN
            )
            attacker.force = min(
                attacker.max_force, attacker.force + REST_FORCE
            )
            attacker.state["pressure"] = attacker.pressure() * 0.5
            attacker.tick_health(resting=True)
            return {
                "kind": "rest",
                "spent": 0.0,
                "success": True,
                "damage": 0.0,
            }
        amount = min(
            attacker.energy,
            max(0.0, min(1.0, action.fraction)) * attacker.max_energy,
        )
        if amount <= 0.0:
            attacker.state["pressure"] = attacker.pressure() * 0.5
            attacker.tick_health(resting=True)
            return {
                "kind": "rest",
                "spent": 0.0,
                "success": True,
                "damage": 0.0,
            }
        attacker.energy -= amount
        form = action.form or "force"
        work = Work(amount=amount, form=form)
        result = defender.receive(work, attacker, self)
        result["kind"] = "work"
        result["spent"] = amount
        result["form"] = form
        infection = 0.0
        if result.get("success"):
            infection = transmit_sickness(
                attacker, defender, self.rng, form
            )
        result["infection"] = infection
        attacker.tick_health(resting=False)
        return result

    def step(self, actions):
        actions = actions or {}
        agent_before = (
            self.agent.force,
            self.agent.energy,
            self.agent.health,
            self.agent.sickness,
        )
        opponent_before = (
            self.opponent.force,
            self.opponent.energy,
            self.opponent.health,
            self.opponent.sickness,
        )
        agent_result = self._perform(
            self.agent, self.opponent, actions.get("agent", Action("REST"))
        )
        opponent_result = self._perform(
            self.opponent,
            self.agent,
            actions.get("opponent", Action("REST")),
        )
        self.agent.decay_pressure()
        self.opponent.decay_pressure()
        self.time += 1
        reward_agent = reward_delta(
            self.agent, agent_before, self.opponent, opponent_before
        )
        reward_opponent = reward_delta(
            self.opponent, opponent_before, self.agent, agent_before
        )
        done = False
        winner = None
        if self.agent.is_dead and self.opponent.is_dead:
            done = True
            winner = "draw"
        elif self.agent.is_dead:
            done = True
            winner = "opponent"
        elif self.opponent.is_dead:
            done = True
            winner = "agent"
        elif self.time >= self.max_steps:
            done = True
            if (self.agent.force, self.agent.health) > (
                self.opponent.force,
                self.opponent.health,
            ):
                winner = "agent"
            elif (self.opponent.force, self.opponent.health) > (
                self.agent.force,
                self.agent.health,
            ):
                winner = "opponent"
            else:
                winner = "draw"
        winner_side = {"agent": "RL", "opponent": "AI"}.get(
            winner, winner
        )
        if done:
            reward_agent += terminal_reward(winner_side, "rl")
            reward_opponent += terminal_reward(winner_side, "ai")
        info = {
            "agent": agent_result,
            "opponent": opponent_result,
            "winner": winner,
            "time": self.time,
        }
        observations = {
            "agent": self.observe("agent"),
            "opponent": self.observe("opponent"),
        }
        rewards = {"agent": reward_agent, "opponent": reward_opponent}
        return observations, rewards, done, info

    def observe(self, agent_id="agent"):
        if agent_id == "agent":
            me, other = self.agent, self.opponent
        elif agent_id == "opponent":
            me, other = self.opponent, self.agent
        else:
            raise ValueError("unknown automaton")
        forms = tuple(f for f in me.outputs if other.can_receive(f))
        if not forms:
            forms = ("force",)
        return Observation(
            self_force=me.force,
            self_energy=me.energy,
            self_max_force=me.max_force,
            self_max_energy=me.max_energy,
            opponent_force=other.force,
            opponent_energy=other.energy,
            opponent_max_force=other.max_force,
            opponent_max_energy=other.max_energy,
            opponent_pressure=other.pressure(),
            opponent_open=other.is_open(),
            time=float(self.time),
            forms=forms,
            self_health=me.health,
            self_max_health=me.max_health,
            self_sickness=me.sickness,
            opponent_health=other.health,
            opponent_max_health=other.max_health,
            opponent_sickness=other.sickness,
        )

    def legal_actions(self, agent_id="agent"):
        if agent_id == "agent":
            me, other = self.agent, self.opponent
        elif agent_id == "opponent":
            me, other = self.opponent, self.agent
        else:
            raise ValueError("unknown automaton")
        actions = [Action("REST", form="rest")]
        if me.sickness > 0.0:
            actions.append(
                Action(
                    "TREAT",
                    form="care",
                    fraction=TREAT_ENERGY_FRACTION,
                )
            )
        for form in me.outputs:
            if not other.can_receive(form):
                continue
            for fraction in (0.25, 0.5, 0.75):
                actions.append(
                    Action("WORK", form=form, fraction=fraction)
                )
        return tuple(actions)
