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
# Калибровка 2026-10-29 (N=100, env on/off): 0.62/0.78 и
# CAPTURE_STREAK=20 удерживают смерть/захват/таймаут/медиану в полосах
# §2.3.2 и при включённом ArenaEnvironment.
HEALTH_REST_REGEN = 0.78
HEALTH_STARVE_DECAY = 1.0
HEALTH_DAMAGE_RATIO = 0.62
HEALTH_FACTOR_MAX = 10.0

SICKNESS_MAX = 1.0
SICKNESS_CRITICAL = 0.75
SICKNESS_HEALTH_DECAY = 1.5
SICKNESS_DAMAGE_BONUS = 0.5
SICKNESS_PROGRESS = 0.004
SICKNESS_REST_RECOVERY = 0.01
SICKNESS_TREAT_RATE = 0.08
TREAT_ENERGY_FRACTION = 0.10
CONTAGION_CHANCE = 0.35
CONTAGION_SEVERITY = 0.50
SICKNESS_WORK_PENALTY = 0.60
SICKNESS_WORK_FLOOR = 0.40

# Устойчивая рана — отдельное состояние, а не разовый урон `H`. Она
# замедляет отдых, вызывает небольшое кровотечение и усиливает урон от
# переполнения `force`, но не подменяет болезнь: `sickness` — процесс,
# `wound` — повреждение. Лечится тем же действием `TREAT` и отдыхом.
WOUND_MAX = 1.0
WOUND_HEALTH_DECAY = 0.60
WOUND_REST_RECOVERY = 0.012
WOUND_TREAT_RATE = 0.10
WOUND_REGEN_PENALTY = 0.50
WOUND_DAMAGE_BONUS = 0.25

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


def success_probability(attacker, defender, work, is_open, env_bonus=0.0):
    """Вероятность успеха работы (канон ядра 4-2-1).

    `env_bonus` — аддитивный бонус открытого окна среды (слой A1,
    `ENV_BONUS` легаси-канона `simulation`). По умолчанию 0.0, поэтому
    прежняя калибровка дуэлей и контрольного плеча `with_env=False`
    не меняется.
    """
    return sigmoid(
        -0.4
        + 2.2 * attacker.skill(work.form) * attacker.work_effectiveness()
        + 1.3 * attacker.authority
        - 1.8 * defender.resistance(work.form)
        + (0.9 if is_open else 0.0)
        + float(env_bonus or 0.0)
        - 0.5 * min(1.0, work.amount / max(1.0, defender.max_force))
    )


def transmit_sickness(source, target, rng, form="force"):
    severity = max(0.0, min(SICKNESS_MAX, float(source.sickness)))
    if (
        severity <= 0.0
        or form != "force"
        or target.sickness >= SICKNESS_MAX
        or target.health <= 0.0
    ):
        return 0.0
    if rng.random() >= CONTAGION_CHANCE * severity:
        return 0.0
    before = target.sickness
    target.infect(CONTAGION_SEVERITY * severity)
    return float(target.sickness - before)


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
    wound: float = 0.0

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
    def is_wounded(self):
        return self.wound > 0.0

    def work_effectiveness(self):
        # Острая болезнь снижает успех работы, но не меняет сохранённый
        # навык и не удорожает `E`: это одна шкала `sickness`, а не второй
        # множитель `illness`. `illness` влияет на работу только косвенно,
        # через скорость прогресса и восстановления болезни.
        return max(
            SICKNESS_WORK_FLOOR,
            1.0 - SICKNESS_WORK_PENALTY * self.sickness,
        )

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
        # `illness` уже задаёт скорость прогресса и восстановления болезни.
        # Повторно умножать на него урон от текущей `sickness` нельзя: это
        # дало бы квадратичный штраф (illness ** 2). Урон от болезни зависит
        # от тяжести процесса и только от возрастной хрупкости.
        return self.health_factor("aging")

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

    def injure(self, severity):
        """Получить устойчивую рану; повторная рана не лечит старую."""
        severity = max(0.0, min(WOUND_MAX, float(severity)))
        self.wound = max(self.wound, severity)
        return self.wound

    def treat_wound(self, amount):
        amount = max(0.0, float(amount))
        if amount <= 0.0 or self.wound <= 0.0:
            return self.wound
        care = self.health_factor("care")
        self.wound = max(0.0, self.wound - amount * care)
        return self.wound

    def apply_force_damage(self, damage):
        damage = max(0.0, float(damage))
        absorbed = min(self.force, damage)
        self.force = max(0.0, self.force - absorbed)
        overflow = max(0.0, damage - absorbed)
        health_damage = (
            overflow
            * HEALTH_DAMAGE_RATIO
            * self.health_damage_multiplier()
            * (1.0 + WOUND_DAMAGE_BONUS * self.wound)
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
            # Рана мешает восстановлению: отдых даёт меньше здоровья, пока
            # повреждение не залечено. Это отличает рану от болезни, которая
            # бьёт по работе и добавляет собственный урон.
            regen = (
                HEALTH_REST_REGEN
                * self.health_regen_multiplier()
                * max(0.25, 1.0 - WOUND_REGEN_PENALTY * self.wound)
            )
            self.health += regen
        if self.wound > 0.0:
            severity = self.wound
            self.health -= (
                WOUND_HEALTH_DECAY
                * severity
                * self.health_sickness_multiplier()
            )
            if resting:
                recovery = (
                    WOUND_REST_RECOVERY
                    * self.health_factor("care")
                    / max(0.25, self.health_factor("illness"))
                )
                self.wound = max(0.0, severity - recovery)
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
