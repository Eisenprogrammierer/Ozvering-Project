import copy
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
# Калибровка 2026-11-03 (N=200, env on/off): после среза A9 (дешёвая
# разведка, одновременный такт, туман) захват вытеснял смерть и таймаут.
# Поэтому переполнение в здоровье снижено до 0.25, голод — до 0.20, а
# CAPTURE_STREAK поднят до 36: доминирование требует более длительной
# серии, и исходы возвращаются в полосы §2.3.2.
HEALTH_REST_REGEN = 0.78
HEALTH_STARVE_DECAY = 0.20
HEALTH_DAMAGE_RATIO = 0.25
HEALTH_FACTOR_MAX = 10.0
# A9: здоровье влияет на нападение. Живой боец не теряет способности
# действовать полностью: множитель не опускается ниже 0.5.
HEALTH_ATTACK_FLOOR = 0.50
# A9: разведка вскрывает слабую точку. Бонус к логиту успеха силовой
# атаки и к её урону; действует только на `force`, не на `info`.
INTEL_ATTACK_BONUS = 0.80
INTEL_DAMAGE_BONUS = 0.25

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
# Устойчивая рана в дуэли (слой A2): зеркало болезни по механике, но со
# своей скоростью — рана тяжелее мешает работе и быстрее проходит при
# лечении (`WOUND_TREAT_RATE`), зато медленнее накапливается вне боя.
WOUND_WORK_PENALTY = 0.70
WOUND_WORK_FLOOR = 0.30
WOUND_PROGRESS = 0.002

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

# ---------------------------------------------------------------------------
# Единицы и конверсия работы (WORLD_CORE_MODEL §2.6, §7.1 №1–4).
#
# `E` и `F` — не типы энергии, а две шкалы одной онтологии. Обе нормированы
# на `max_*` (для персонажа — 100 пунктов), поэтому:
#
#   * 1 пункт `E` — работа, которую автомат может оплатить без потери
#     способности действовать; `E = 0` — граница истощения;
#   * 1 пункт `F` — одновременно запас структурной целостности и
#     пропускная способность за такт. Урон сначала расходует `F`, а работа
#     не может превысить `F · duration · FORCE_WORK_RATIO`;
#   * `H` (здоровье) и `sickness`/`wound` — отдельные состояния `S`, а не
#     ещё один запас энергии.
#
# Конверсия работы всегда идёт с потерями. Принятая работа делится на:
#   `accepted = amount · efficiency(form)`,
#   `stored   = accepted · ENERGY_STORAGE_SHARE`,
#   `loss     = amount - accepted` (не дошло до цели),
#   `entropy  = accepted - stored` (рассеялось внутри).
# Это позволяет учитывать потери, не вводя типизированную энергию.
# ---------------------------------------------------------------------------

UNIT_SCALE = 100.0
WORK_UNITS = 1.0
FORM_CONVERSION_EFFICIENCY = {
    "force": 0.55,
    "info": 0.75,
}
DEFAULT_CONVERSION_EFFICIENCY = 0.55
ENERGY_STORAGE_SHARE = 0.35
# Доля успешной работы, возвращающаяся атакующему как структурный отклик.
FORCE_FEEDBACK_SHARE = 0.20
# Доля работы, которую получатель сохраняет как энергию давления/отклика
# (аренный срез `_receive_work`). Это не второй вид энергии, а буфер.
RECEIVE_ENERGY_SHARE = 0.12


def conversion_efficiency(form):
    """КПД канала работы: сколько принятой работы доходит до цели.

    Значение зависит только от канала, а не от типа энергии: `force` и
    `info` — две формы одной работы, поэтому КПД — контекст обработчика.
    Неизвестный канал получает нижнюю оценку, а не бесплатную конверсию.
    """
    return float(
        FORM_CONVERSION_EFFICIENCY.get(
            str(form), DEFAULT_CONVERSION_EFFICIENCY
        )
    )


def conversion_report(amount, form, stored, efficiency=None):
    """Разложить работу на принятую часть, потери и энтропию.

    `stored` — сколько фактически попало в `E` получателя. Отчёт аддитивен:
    `loss + entropy + stored == max(0, amount)` (с точностью до округления),
    поэтому потери не теряются из учёта и не превращаются в скрытый доход.
    `efficiency` можно переопределить для отказа: отклонённая работа — это
    потеря целиком, а не конверсия с КПД канала.
    """
    amount = max(0.0, float(amount))
    stored = max(0.0, min(amount, float(stored)))
    if efficiency is None:
        efficiency = conversion_efficiency(form)
    efficiency = max(0.0, min(1.0, float(efficiency)))
    accepted = min(amount, amount * efficiency)
    entropy = max(0.0, accepted - stored)
    loss = max(0.0, amount - accepted)
    return {
        "amount": amount,
        "arrived": accepted,
        "stored": stored,
        "loss": loss,
        "entropy": entropy,
        "efficiency": efficiency,
    }


def sigmoid(value):
    if value < -60.0:
        return 0.0
    if value > 60.0:
        return 1.0
    return 1.0 / (1.0 + math.exp(-value))


def success_probability(
    attacker,
    defender,
    work,
    is_open,
    env_bonus=0.0,
    weak_point=0.0,
):
    """Вероятность успеха работы (канон ядра 4-2-1).

    `env_bonus` — аддитивный бонус открытого окна среды (слой A1,
    `ENV_BONUS` легаси-канона `simulation`). По умолчанию 0.0, поэтому
    прежняя калибровка дуэлей и контрольного плеча `with_env=False`
    не меняется.

    `weak_point` — свежая уязвимость, найденная разведкой (A9). Бонус
    применяется только к силовой форме: информационная работа сама
    вскрывает точку, но не пользуется ею.
    """
    intel_bonus = 0.0
    if work.form == "force" and weak_point > 0.0:
        intel_bonus = INTEL_ATTACK_BONUS * min(1.0, float(weak_point))
    return sigmoid(
        -0.4
        + 2.2
        * attacker.skill(work.form)
        * attacker.work_effectiveness()
        * attacker.attack_effectiveness()
        + 1.3 * attacker.authority
        - 1.8 * defender.resistance(work.form)
        + (0.9 if is_open else 0.0)
        + float(env_bonus or 0.0)
        + intel_bonus
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

    @property
    def force_ratio(self):
        """Доля структурной целостности `F` в `[0, 1]`."""
        return max(0.0, min(1.0, self.force / max(1.0, self.max_force)))

    @property
    def energy_ratio(self):
        """Доля энергии `E` в `[0, 1]`; граница `0` — истощение."""
        return max(0.0, min(1.0, self.energy / max(1.0, self.max_energy)))

    def force_throughput(self):
        """Пропускная способность `F` за такт (единицы работы).

        `F` — не только запас прочности: пока он цел, он ограничивает
        объём работы, которую автомат способен провести за такт. Умножение
        на длительность выполняет вызывающий резолвер (`work_amount`).
        """
        return max(0.0, self.force)

    def add_energy(self, amount):
        """Добавить `E` с насыщением на `max_energy`; вернуть прирост."""
        before = self.energy
        self.energy = max(
            0.0, min(self.max_energy, self.energy + float(amount))
        )
        return self.energy - before

    def add_force(self, amount):
        """Добавить `F` с насыщением на `max_force`; вернуть прирост."""
        before = self.force
        self.force = max(
            0.0, min(self.max_force, self.force + float(amount))
        )
        return self.force - before

    def work_effectiveness(self):
        # Острая болезнь и устойчивая рана (слой A2) снижают успех работы,
        # но не меняют сохранённый навык и не удорожают `E`: это отдельные
        # шкалы `sickness`/`wound`, а не второй множитель `illness`.
        # `illness` влияет на работу только косвенно, через скорость
        # прогресса и восстановления болезни. Эффекты перемножаются:
        # одновременно больной и раненый автомат работает хуже каждого
        # из них по отдельности, с общим полом (рана не обнуляет труд).
        sickness_factor = max(
            SICKNESS_WORK_FLOOR,
            1.0 - SICKNESS_WORK_PENALTY * self.sickness,
        )
        wound_factor = max(
            WOUND_WORK_FLOOR,
            1.0 - WOUND_WORK_PENALTY * self.wound,
        )
        return max(
            SICKNESS_WORK_FLOOR * WOUND_WORK_FLOOR,
            sickness_factor * wound_factor,
        )

    @property
    def health_ratio(self):
        return max(
            0.0,
            min(1.0, self.health / max(1.0, self.max_health)),
        )

    def attack_effectiveness(self):
        """Множитель нападения от текущего здоровья (A9).

        Полное здоровье даёт 1.0, критическое — около 0.5; боец остаётся
        способным действовать, но бьёт слабее. Рана и болезнь уже входят
        в `work_effectiveness`, поэтому здесь только здоровье.
        """
        return HEALTH_ATTACK_FLOOR + (
            1.0 - HEALTH_ATTACK_FLOOR
        ) * self.health_ratio

    def clone_for_tick(self):
        """Лёгкая копия для одновременного разрешения такта.

        Копируются только изменяемые поля (`state`). Обработчики не
        переносятся: резолвер такта вызывает чистые функции, а не
        привязанные к `ArenaAgent` методы.
        """
        clone = copy.copy(self)
        clone.state = dict(self.state)
        clone.handlers = {}
        return clone

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
            else:
                # Без покоя рана медленно расползается (кровотечение),
                # зеркально прогрессу болезни, но медленнее: раненый
                # автомат вынужден беречь силы, иначе повреждение растёт.
                progress = (
                    WOUND_PROGRESS * self.health_decay_multiplier()
                )
                self.wound = min(WOUND_MAX, severity + progress)
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

    def set_handler(self, form, handler):
        """Заменить обработчик канала во время жизни автомата.

        Обработчик — детерминированная функция `(target, work, source,
        world) -> result`; стохастика живёт в резолвере (`world.rng`), а не
        внутри обработчика. `None` возвращает канал к `default_receive`.
        """
        form = str(form)
        if handler is not None and not callable(handler):
            raise TypeError("handler must be callable or None")
        if handler is None:
            self.handlers.pop(form, None)
        else:
            self.handlers[form] = handler
        return handler

    def default_receive(self, work):
        if not self.can_receive(work.form):
            report = conversion_report(work.amount, work.form, 0.0, 0.0)
            report.update(
                {
                    "accepted": False,
                    "success": False,
                    "energy": 0.0,
                    "force": 0.0,
                    "pressure": 0.0,
                }
            )
            return report
        efficiency = conversion_efficiency(work.form)
        transferred = work.amount * efficiency
        stored = self.add_energy(transferred * ENERGY_STORAGE_SHARE)
        report = conversion_report(work.amount, work.form, stored)
        self.state["pressure"] = min(
            30.0, self.pressure() + work.amount * PRESSURE_PER_WORK
        )
        report.update(
            {
                "accepted": True,
                "success": True,
                "energy": transferred,
                "force": 0.0,
                "pressure": work.amount * PRESSURE_PER_WORK,
            }
        )
        return report
