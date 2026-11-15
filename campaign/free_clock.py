"""RTS-часы свободного режима.

Свободный режим не ставит пользовательскую паузу и не перематывает время
назад: физические секунды умножаются на выбранную скорость, а часы решают,
сколько суток и внутридневных слотов должен просимулировать ``WorldEngine``.

Границы:

* скорость всегда ``>= 1x``; доступные уровни приходят из конфига мира;
* ``advance()`` игнорирует отрицательный/нулевой ``dt``;
* снимок хранит только накопленный остаток суток и скорость, а не
  альтернативную временную линию;
* часы не меняют правила мира, отношения и потребности — это делает
  ``WorldEngine.tick()``/``end_day()``.

Модуль не знает о фракциях, ролях или свободных профессиях: новые уровни
скорости и длительность суток задаются полями мира.
"""

from __future__ import annotations

from .clock import CampaignClock, normalize_seconds_per_day

MIN_SPEED = 1.0
DEFAULT_SPEEDS = (1.0, 2.0, 4.0, 8.0)


def normalize_speeds(speeds=None):
    """Привести список уровней скорости к возрастающему кортежу ``>= 1``."""
    values = []
    for value in speeds or DEFAULT_SPEEDS:
        try:
            speed = float(value)
        except (TypeError, ValueError):
            continue
        speed = max(MIN_SPEED, speed)
        if speed not in values:
            values.append(speed)
    if not values:
        values = list(DEFAULT_SPEEDS)
    values.sort()
    return tuple(values)


def _nearest_speed(speed, levels):
    try:
        value = max(MIN_SPEED, float(speed))
    except (TypeError, ValueError):
        value = levels[0]
    return min(levels, key=lambda item: abs(item - value))


class FreeClock(CampaignClock):
    """Физическое время свободного режима с ускорением без rewind."""

    def __init__(
        self,
        seconds_per_day=120.0,
        max_catchup_days=7,
        speeds=None,
        speed=1.0,
        acc=0.0,
    ):
        super().__init__(
            seconds_per_day=seconds_per_day,
            max_catchup_days=max_catchup_days,
            paused=False,
        )
        self.speeds = normalize_speeds(speeds)
        self.speed = _nearest_speed(speed, self.speeds)
        self.acc = max(0.0, self._as_float(acc))

    @staticmethod
    def _as_float(value):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return 0.0
        if result != result or result in (float("inf"), float("-inf")):
            return 0.0
        return result

    @property
    def speed_index(self):
        try:
            return self.speeds.index(self.speed)
        except ValueError:
            return 0

    @property
    def can_speed_up(self):
        return self.speed_index < len(self.speeds) - 1

    @property
    def can_slow_down(self):
        return self.speed_index > 0

    def speed_up(self):
        if self.can_speed_up:
            self.speed = self.speeds[self.speed_index + 1]
        return self.speed

    def slow_down(self):
        if self.can_slow_down:
            self.speed = self.speeds[self.speed_index - 1]
        return self.speed

    def set_speed(self, value):
        self.speed = _nearest_speed(value, self.speeds)
        return self.speed

    def advance(self, dt):
        """Продвинуть физическое время; отрицательный ``dt`` запрещён."""
        try:
            seconds = float(dt)
        except (TypeError, ValueError):
            return 0
        if seconds <= 0.0:
            return 0
        return super().advance(seconds * self.speed)

    @property
    def day_fraction(self):
        if self.seconds_per_day <= 0.0:
            return 0.0
        return (self.acc % self.seconds_per_day) / self.seconds_per_day

    def time_label(self):
        minutes = int(self.day_fraction * 24 * 60) % (24 * 60)
        return "%02d:%02d" % (minutes // 60, minutes % 60)

    def speed_label(self):
        value = self.speed
        if float(value).is_integer():
            return "%dx" % int(value)
        return "%gx" % value

    def to_snapshot(self):
        return {
            "seconds_per_day": float(self.seconds_per_day),
            "speed": float(self.speed),
            "acc": float(self.acc),
            "days": int(self.days),
        }

    @classmethod
    def from_snapshot(
        cls,
        snapshot,
        seconds_per_day=120.0,
        max_catchup_days=7,
        speeds=None,
    ):
        data = snapshot if isinstance(snapshot, dict) else {}
        clock = cls(
            seconds_per_day=data.get("seconds_per_day", seconds_per_day),
            max_catchup_days=max_catchup_days,
            speeds=speeds,
            speed=data.get("speed", MIN_SPEED),
            acc=data.get("acc", 0.0),
        )
        try:
            clock.days = max(0, int(data.get("days", 0)))
        except (TypeError, ValueError):
            clock.days = 0
        return clock


__all__ = [
    "DEFAULT_SPEEDS",
    "MIN_SPEED",
    "FreeClock",
    "normalize_speeds",
]
