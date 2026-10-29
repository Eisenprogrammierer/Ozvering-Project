"""Персонажи кампании как лёгкие `core41.Automaton`-обёртки.

Исторически персонажи кампании были обычными словарями (`affinity`,
`trust`, `health`, `sickness`). Игрок уже мигрирован на `CampaignActor`,
а остальные участники мира оставались пассивными записями. Этот модуль
закрывает разрыв без переписывания конфигов: `CampaignCharacter` — это
`dict`-совместимая обёртка, поэтому UI, сейвы и существующие проверки
продолжают работать, но у каждого персонажа появляется:

- `unit` — `Automaton` с `F` (отношение, 0..1), `E` (доверие, 0..1),
  `H`/`sickness`;
- `sync()` — проекция легаси-полей в автомат;
- `tick()` — минимальная автономная динамика: отношения и доверие
  медленно тянутся к нейтральному фону, здоровье/болезнь двигаются по
  тем же дневным правилам, что у игрока.

Это первый срез автономии: персонаж живёт и меняет состояние без действия
игрока, но полноценный выбор социальных действий его собственной политикой
остаётся открытым (см. `docs/TODO.md`).
"""

from core41 import Automaton, HEALTH_MAX, SICKNESS_MAX


def _clamp(value, low=0.0, high=1.0):
    return max(float(low), min(float(high), float(value)))


def _ratio(value):
    """Легаси-шкала `[-1, 1]` → ядровая `[0, 1]`."""
    return _clamp((float(value) + 1.0) / 2.0)


class CampaignCharacter(dict):
    """Словарь персонажа + `Automaton` и дневная автономная динамика."""

    # Скорость возврата к нейтральному фону. Медленно, чтобы отношения,
    # заработанные игроком, не исчезали за несколько дней.
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
