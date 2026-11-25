"""Персонажи кампании как лёгкие `core41.Automaton`-обёртки.

Исторически персонажи кампании были обычными словарями (`affinity`,
`trust`, `health`, `sickness`). Игрок уже мигрирован на `CampaignActor`,
а остальные участники мира оставались пассивными записями. Этот модуль
закрывает разрыв без переписывания конфигов: `CampaignCharacter` — это
`dict`-совместимая обёртка, поэтому UI, сейвы и существующие проверки
продолжают работать, но у каждого персонажа появляется:

- `unit` — `Automaton` с `F` (отношение, 0..1), `E` (доверие, 0..1),
  `H`/`sickness`;
- `bdi` — `bdi.BDIState` с теми же 16 потребностями, что у арены и
  automata-кампаний; потребности растут, давят на `F/E` и удовлетворяются
  суточной рутиной (`campaign/routine.py`);
- `sync()` — проекция легаси-полей в автомат;
- `tick()` — минимальная автономная динамика: отношения и доверие
  медленно тянутся к нейтральному фону, здоровье/болезнь двигаются по
  тем же дневным правилам, что у игрока.

Это первый срез автономии: персонаж живёт и меняет состояние без действия
игрока, но полноценный выбор социальных действий его собственной политикой
остаётся открытым (см. `docs/TODO.md`).
"""

from bdi import BDIState
from core41 import Automaton, HEALTH_MAX, SICKNESS_MAX

DAY_SECONDS = 86400.0
_NEED_TICK_KEYS = frozenset(
    (
        "in_combat",
        "under_fire",
        "support",
        "resting",
        "resting_needs",
        "order_needs",
        "rate_multipliers",
        "trait_model",
        "seconds_per_unit",
    )
)


def _clamp(value, low=0.0, high=1.0):
    return max(float(low), min(float(high), float(value)))


def _ratio(value):
    """Легаси-шкала `[-1, 1]` → ядровая `[0, 1]`."""
    return _clamp((float(value) + 1.0) / 2.0)


class CampaignCharacter(dict):
    """Словарь персонажа + `Automaton` и дневная автономная динамика."""

    AFFINITY_DRIFT = 0.002
    TRUST_DRIFT = 0.001

    def __init__(self, raw):
        super().__init__(raw)
        self.unit = Automaton(
            id=str(raw.get("id", "character")),
            force=_ratio(raw.get("affinity", 0.0)),
            max_force=1.0,
            energy=_ratio(raw.get("trust", 0.0)),
            max_energy=1.0,
            health=_clamp(raw.get("health", HEALTH_MAX), 0.0, HEALTH_MAX),
            max_health=HEALTH_MAX,
            sickness=_clamp(raw.get("sickness", 0.0), 0.0, SICKNESS_MAX),
            skills={"force": 0.5, "info": 0.5},
        )
        self.bdi = BDIState(
            character_id=str(raw.get("id", "character")),
            needs=raw.get("needs") or {},
            traits=raw.get("traits") or {},
        )
        self._sync_bdi_conditions()

    @property
    def needs(self):
        """16 потребностей BDI; изменяемая проекция состояния персонажа."""
        return self.bdi.needs

    @property
    def is_dead(self):
        return not bool(self.get("alive", True)) or self.unit.force <= 0.0

    def load_needs(self, values):
        """Восстановить потребности из снимка, сохранив контракт BDI."""
        self.bdi.needs = {
            str(key): _clamp(value)
            for key, value in dict(values or {}).items()
            if str(key) in self.bdi.needs
        }
        return self.bdi.needs

    def _sync_bdi_conditions(self):
        self.bdi.conditions["sickness"] = _clamp(
            self.get("sickness", 0.0)
        )
        self.bdi.conditions["wound"] = _clamp(self.get("wound", 0.0))

    def tick_needs(self, seconds=DAY_SECONDS, **kwargs):
        """Продвинуть 16 потребностей и вернуть дельты BDI.

        Лишние аргументы рутины (мораль, моральные множители) отбрасываются:
        у дневного персонажа нет морали арены, но контракт ``run_day``
        остаётся общим.
        """
        self._sync_bdi_conditions()
        allowed = {
            key: value
            for key, value in kwargs.items()
            if key in _NEED_TICK_KEYS
        }
        deltas = self.bdi.tick(seconds=seconds, **allowed)
        self._sync_bdi_conditions()
        return deltas

    def satisfy(self, effects, morale_bonus=0.0):
        """Удовлетворить потребности и вернуть восстановленные значения."""
        result = self.bdi.satisfy(effects)
        if result.get("force"):
            self["affinity"] = _clamp(
                float(self.get("affinity", 0.0)) + result["force"],
                -1.0,
                1.0,
            )
        if result.get("energy"):
            self["trust"] = _clamp(
                float(self.get("trust", 0.0)) + result["energy"],
                -1.0,
                1.0,
            )
        return dict(result.get("restored") or {})

    def sync(self):
        """Обновить автомат из легаси-полей (после эффектов/сейва)."""
        self.unit.force = _ratio(self.get("affinity", 0.0))
        self.unit.energy = _ratio(self.get("trust", 0.0))
        self.unit.health = _clamp(
            self.get("health", HEALTH_MAX), 0.0, HEALTH_MAX
        )
        self.unit.sickness = _clamp(
            self.get("sickness", 0.0), 0.0, SICKNESS_MAX
        )
        return self.unit

    def tick(self):
        """Один день автономной жизни персонажа.

        Возвращает `(affinity_delta, trust_delta)`. Здоровье/болезнь
        считает `WorldEngine._advance_condition`, чтобы не дублировать
        дневные правила; здесь — только социальный дрейф и синхронизация.
        """
        affinity_before = float(self.get("affinity", 0.0))
        trust_before = float(self.get("trust", 0.0))
        if self.get("alive", True):
            affinity = affinity_before - self.AFFINITY_DRIFT * (
                1.0 if affinity_before > 0.0 else -1.0
            )
            trust = trust_before - self.TRUST_DRIFT * (
                1.0 if trust_before > 0.0 else -1.0
            )
            self["affinity"] = _clamp(affinity, -1.0, 1.0)
            self["trust"] = _clamp(trust, -1.0, 1.0)
        self.sync()
        return (
            float(self.get("affinity", 0.0)) - affinity_before,
            float(self.get("trust", 0.0)) - trust_before,
        )


__all__ = ["CampaignCharacter"]
