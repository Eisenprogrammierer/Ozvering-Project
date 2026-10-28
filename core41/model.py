import math
from dataclasses import dataclass, field

from .types import Work

OPEN_PRESSURE = 8.0
PRESSURE_DECAY = 0.82
PRESSURE_PER_WORK = 0.30
REST_REGEN = 14.0
REST_FORCE = 0.6

HEALTH_MAX = 100.0
HEALTH_CRITICAL = 25.0
HEALTH_REST_REGEN = 0.75
HEALTH_STARVE_DECAY = 1.0
HEALTH_DAMAGE_RATIO = 0.70
HEALTH_FACTOR_MAX = 10.0

SICKNESS_MAX = 1.0
SICKNESS_CRITICAL = 0.75
SICKNESS_HEALTH_DECAY = 1.5
SICKNESS_DAMAGE_BONUS = 0.5
SICKNESS_PROGRESS = 0.004
SICKNESS_REST_RECOVERY = 0.01
SICKNESS_TREAT_RATE = 0.08
TREAT_ENERGY_FRACTION = 0.10

DEFAULT_HEALTH_FACTORS = {
    "aging": 1.0,
    "illness": 1.0,
    "stress": 1.0,
    "care": 1.0,
}


def sigmoid(value):
    if value < -60.0:
        return 0.0
    if value > 60.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-value))


def success_probability(attacker, defender, work, is_open):
    return sigmoid(
        -0.4
        + 2.2 * attacker.skill(work.form)
        + 1.3 * attacker.authority
        - 1.8 * defender.resistance(work.form)
        + (0.9 if is_open else 0.0)
        - 0.5 * min(1.0, work.amount / max(1.0, defender.max_force))
    )


@dataclass
class Automaton:
    id: str
    force: float = 100.0
    energy: float = 100.0
    max_force: float = 100.0
    max_energy: float = 100.0
    inputs: tuple = ("force", "info")
    outputs: tuple = ("force",)
    skills: dict = field(default_factory=lambda: {"force": 0.6})
    authority: float = 0.0
    state: dict = field(default_factory=lambda: {"pressure": 0.0})
    handlers: dict = field(default_factory=dict)
    relations: dict = field(default_factory=dict)
    health: float = HEALTH_MAX
    max_health: float = HEALTH_MAX
    health_factors: dict = field(
        default_factory=lambda: dict(DEFAULT_HEALTH_FACTORS)
    )
    sickness: float = 0.0

    @property
    def F(self):
        return self.force

    @property
    def E(self):
        return self.energy

    @property
    def is_dead(self):
        return self.health <= 0.0

    @property
    def is_sick(self):
        return self.sickness > 0.0

    @property
    def health_ratio(self):
        return self.health / max(1.0, self.max_health)

    def health_factor(self, name):
        value = float(self.health_factors.get(name, 1.0))
        return max(0.0, min(HEALTH_FACTOR_MAX, value))

    def set_health_factor(self, name, value):
        value = max(0.0, min(HEALTH_FACTOR_MAX, float(value)))
        self.health_factors[str(name)] = value
        return value

    def health_decay_multiplier(self):
        return min(
            HEALTH_FACTOR_MAX,
            self.health_factor("aging")
            * self.health_factor("illness")
            * self.health_factor("stress"),
        )

    def health_regen_multiplier(self):
        illness = max(0.25, self.health_factor("illness"))
        return min(
            HEALTH_FACTOR_MAX,
            self.health_factor("care") / illness,
        )

    def health_damage_multiplier(self):
        frailty = min(
            HEALTH_FACTOR_MAX,
            self.health_factor("aging")
            * self.health_factor("illness"),
        )
        return frailty * self.sickness_damage_multiplier()

    def sickness_damage_multiplier(self):
        return 1.0 + SICKNESS_DAMAGE_BONUS * self.sickness

    def health_sickness_multiplier(self):
        return min(
            HEALTH_FACTOR_MAX,
            self.health_factor("aging")
            * self.health_factor("illness"),
        )

    def infect(self, severity):
        severity = max(0.0, min(SICKNESS_MAX, float(severity)))
        self.sickness = max(self.sickness, severity)
        return self.sickness

    def treat(self, amount):
        amount = max(0.0, float(amount))
        if amount <= 0.0 or self.sickness <= 0.0:
            return self.sickness
        care = self.health_factor("care")
        illness = max(0.25, self.health_factor("illness"))
        self.sickness = max(
            0.0,
            self.sickness - amount * care / illness,
        )
        return self.sickness

    def apply_force_damage(self, damage):
        damage = max(0.0, float(damage))
        absorbed = min(self.force, damage)
        self.force = max(0.0, self.force - absorbed)
        overflow = max(0.0, damage - absorbed)
        health_damage = (
            overflow * HEALTH_DAMAGE_RATIO * self.health_damage_multiplier()
        )
        if health_damage:
            self.health = max(0.0, self.health - health_damage)
        return absorbed, overflow, health_damage

    def tick_health(self, resting=False):
        if self.health <= 0.0:
            return 0.0
        if self.energy <= 0.0:
            self.health -= (
                HEALTH_STARVE_DECAY * self.health_decay_multiplier()
            )
        elif resting:
            self.health += (
                HEALTH_REST_REGEN * self.health_regen_multiplier()
            )
        if self.sickness > 0.0:
            severity = self.sickness
            self.health -= (
                SICKNESS_HEALTH_DECAY
                * severity
                * self.health_sickness_multiplier()
            )
            if resting:
                recovery = (
                    SICKNESS_REST_RECOVERY
                    * self.health_factor("care")
                    / max(0.25, self.health_factor("illness"))
                )
                self.sickness = max(0.0, severity - recovery)
            else:
                progress = (
                    SICKNESS_PROGRESS * self.health_decay_multiplier()
                )
                self.sickness = min(
                    SICKNESS_MAX, severity + progress
                )
        self.health = max(0.0, min(self.max_health, self.health))
        return self.health

    def can_receive(self, form):
        return form in self.inputs

    def skill(self, form):
        return float(self.skills.get(form, 0.0))

    def resistance(self, form):
        if not self.can_receive(form):
            return 1.0
        return min(
            1.0,
            0.65 * self.force / max(1.0, self.max_force)
            + 0.35 * self.energy / max(1.0, self.max_energy),
        )

    def pressure(self):
        return float(self.state.get("pressure", 0.0))

    def is_open(self):
        return self.pressure() >= OPEN_PRESSURE

    def decay_pressure(self):
        self.state["pressure"] = max(
            0.0, self.pressure() * PRESSURE_DECAY
        )

    def receive(self, work, source=None, world=None):
        handler = self.handlers.get(work.form)
        if handler is not None:
            return handler(self, work, source, world)
        return self.default_receive(work)

    def default_receive(self, work):
        if not self.can_receive(work.form):
            return {
                "accepted": False,
                "success": False,
                "energy": 0.0,
                "force": 0.0,
                "pressure": 0.0,
            }
        efficiency = 0.75 if work.form == "info" else 0.55
        transferred = work.amount * efficiency
        self.energy = min(self.max_energy, self.energy + transferred * 0.35)
        self.state["pressure"] = min(
            30.0, self.pressure() + work.amount * PRESSURE_PER_WORK
        )
        return {
            "accepted": True,
            "success": True,
            "energy": transferred,
            "force": 0.0,
            "pressure": work.amount * PRESSURE_PER_WORK,
        }
