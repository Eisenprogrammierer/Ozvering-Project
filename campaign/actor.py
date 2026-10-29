"""Персонаж кампании на ядре 4-2-1.

Кампания исторически жила на собственных шкалах: `standing`, `power`,
`cohesion` и дневной счётчик `actions_left`. Этот модуль вводит первый
полноценный слой персонажа на тех же `E/F/H`, что и арена:

- `E` — единая энергия персонажа; в дневном срезе она является бюджетом
  действий дня (`CAMPAIGN_ENERGY_MAX / actions_per_day` на действие);
- `F` — сила позиции (`standing`, 0..1), то же состояние, что и раньше,
  но теперь это `force` автомата;
- `H`/`sickness` — здоровье и болезнь, уже общие с ареной.

`actions_left` остаётся совместимым представлением `E`: это не второй
счётчик, а проекция `floor(E / energy_per_action)`. Поэтому старый UI,
сейвы и тесты продолжают работать, а среда обучения видит те же `E/F/H`,
что и арена.
"""

from core41 import Automaton, HEALTH_MAX, SICKNESS_MAX
from core41.model import success_probability
from core41.types import Work

# Ёмкость дневной энергии. Значение не обязано совпадать с `max_energy`
# арены: важен единый тип шкалы `E`, а не абсолютные единицы.
CAMPAIGN_ENERGY_MAX = 100.0
# Вес ядровой вероятности в итоговом шансе кампанийного действия. База
# остаётся авторской (конфиг мира), но `F`/навык/болезнь/сопротивление
# цели дают сдвиг через ту же `success_probability`, что и на арене.
CAMPAIGN_CORE_CHANCE_WEIGHT = 0.30


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def campaign_success_chance(
    base,
    attacker,
    defender,
    form="force",
    amount=0.0,
    is_open=False,
    weight=CAMPAIGN_CORE_CHANCE_WEIGHT,
):
    """Смешать авторский шанс действия с ядровой `success_probability`.

    `attacker`/`defender` — `Automaton` (или `CampaignActor` с `.unit`).
    Так `F` (standing/authority), навык, болезнь и сопротивление цели
    входят в кампанийный бросок, а не остаются декоративными шкалами.
    """
    attacker_unit = getattr(attacker, "unit", attacker)
    defender_unit = getattr(defender, "unit", defender)
    core = success_probability(
        attacker_unit,
        defender_unit,
        Work(amount=float(amount), form=form or "force"),
        bool(is_open),
    )
    blended = float(base) + float(weight) * (core - 0.5)
    return _clamp(blended, 0.05, 0.95)



class CampaignActor:
    """Игровой персонаж кампании: `Automaton` + дневной бюджет действий."""

    def __init__(
        self,
        actions_per_day=3,
        health=HEALTH_MAX,
        sickness=0.0,
        standing=0.0,
        energy=CAMPAIGN_ENERGY_MAX,
    ):
        self.actions_per_day = max(1, int(actions_per_day))
        self.unit = Automaton(
            id="player",
            # `standing` — политическая сила позиции в [0, 1].
            force=_clamp(standing),
            max_force=1.0,
            energy=_clamp(energy, 0.0, CAMPAIGN_ENERGY_MAX),
            max_energy=CAMPAIGN_ENERGY_MAX,
            health=_clamp(health, 0.0, HEALTH_MAX),
            max_health=HEALTH_MAX,
            sickness=_clamp(sickness, 0.0, SICKNESS_MAX),
            inputs=("force", "info", "care"),
            outputs=("force", "info"),
            skills={"force": 0.6, "info": 0.4},
            # `standing` — и политическая сила позиции, и полномочия:
            # `success_probability` использует authority, поэтому F
            # участвует в шансе действия, а не только в отображении.
            authority=_clamp(standing),
        )

    # -- E -----------------------------------------------------------------

    @property
    def energy(self):
        return float(self.unit.energy)

    @energy.setter
    def energy(self, value):
        self.unit.energy = _clamp(value, 0.0, self.unit.max_energy)

    @property
    def max_energy(self):
        return float(self.unit.max_energy)

    @property
    def energy_per_action(self):
        return float(self.unit.max_energy) / self.actions_per_day

    @property
    def actions_left(self):
        """Проекция `E` в целое число действий (совместимость с UI).

        Небольшой допуск нужен из-за деления `100 / 3`: после одного
        действия остаток равен `66.666…`, и без допуска он мог бы
        округлиться вниз до одного действия.
        """
        if self.unit.energy <= 1e-9:
            return 0
        ratio = self.unit.energy / self.energy_per_action + 1e-9
        return max(0, min(self.actions_per_day, int(ratio)))

    @actions_left.setter
    def actions_left(self, value):
        value = max(0, min(self.actions_per_day, int(value)))
        self.unit.energy = value * self.energy_per_action

    def spend_action(self):
        """Списать одно действие; `False`, если энергии не хватает."""
        if self.actions_left <= 0:
            return False
        self.unit.energy = max(
            0.0, self.unit.energy - self.energy_per_action
        )
        return True

    def restore_day(self):
        """Новый день: энергия действий восстанавливается полностью."""
        self.unit.energy = self.unit.max_energy

    # -- F / H -------------------------------------------------------------

    @property
    def force(self):
        return float(self.unit.force)

    @force.setter
    def force(self, value):
        self.unit.force = _clamp(value, 0.0, self.unit.max_force)
        self.unit.authority = self.unit.force

    @property
    def max_force(self):
        return float(self.unit.max_force)

    @property
    def health(self):
        return float(self.unit.health)

    @health.setter
    def health(self, value):
        self.unit.health = _clamp(value, 0.0, self.unit.max_health)

    @property
    def max_health(self):
        return float(self.unit.max_health)

    @property
    def sickness(self):
        return float(self.unit.sickness)

    @sickness.setter
    def sickness(self, value):
        self.unit.sickness = _clamp(value, 0.0, SICKNESS_MAX)

    @property
    def alive(self):
        return self.unit.health > 0.0

    @property
    def standing(self):
        return self.force

    @standing.setter
    def standing(self, value):
        self.force = value

    def work_effectiveness(self):
        return self.unit.work_effectiveness()

    # -- Персистентность ---------------------------------------------------

    def state_dict(self):
        return {
            "actions_per_day": self.actions_per_day,
            "energy": self.energy,
            "max_energy": self.max_energy,
            "force": self.force,
            "max_force": self.max_force,
            "health": self.health,
            "max_health": self.max_health,
            "sickness": self.sickness,
            "alive": self.alive,
        }

    def load_state_dict(self, state):
        state = state or {}
        actions_per_day = int(
            state.get("actions_per_day", self.actions_per_day)
        )
        self.actions_per_day = max(1, actions_per_day)
        if "health" in state:
            self.health = state["health"]
        if "sickness" in state:
            self.sickness = state["sickness"]
        if "force" in state:
            self.force = state["force"]
        if "energy" in state:
            self.energy = state["energy"]
        elif "actions_left" in state:
            self.actions_left = state["actions_left"]
        return self.state_dict()
