import math
from dataclasses import dataclass, field

from .types import Work

OPEN_PRESSURE = 8.0
PRESSURE_DECAY = 0.82
PRESSURE_PER_WORK = 0.30
REST_REGEN = 14.0
REST_FORCE = 0.6


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

    @property
    def F(self):
        return self.force

    @property
    def E(self):
        return self.energy

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
