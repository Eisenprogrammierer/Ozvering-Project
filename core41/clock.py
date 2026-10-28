from __future__ import annotations

BASE_TICK_SECONDS = 1.0
SPEEDS = (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)
DEFAULT_SPEED = 1.0
MAX_CATCHUP_TICKS = 64


def normalize_speed(value):
    value = float(value)
    if value <= 0.0:
        return 0.0
    allowed = SPEEDS[1:]
    return min(allowed, key=lambda item: (abs(item - value), item))


def speed_label(value):
    speed = normalize_speed(value)
    if speed <= 0.0:
        return "PAUSE"
    return "%dx" % int(speed)


class SimulationClock:

    def __init__(
        self,
        speed=DEFAULT_SPEED,
        auto_pause=True,
        max_catchup=MAX_CATCHUP_TICKS,
    ):
        self.base_tick_seconds = float(BASE_TICK_SECONDS)
        self.auto_pause = bool(auto_pause)
        self.max_catchup = max(1, int(max_catchup))
        self._speed = normalize_speed(speed)
        if self._speed <= 0.0:
            self._speed = DEFAULT_SPEED
        self._last_speed = self._speed
        self.pause_reason = ""
        self.acc = 0.0
        self.ticks = 0
        self.elapsed = 0.0
        self.dropped_ticks = 0

    @property
    def speed(self):
        return self._speed

    @speed.setter
    def speed(self, value):
        self.set_speed(value)

    @property
    def paused(self):
        return self._speed <= 0.0

    @paused.setter
    def paused(self, value):
        self.set_paused(value)

    @property
    def ticks_per_sec(self):
        if self.paused:
            return 0.0
        return self._speed / self.base_tick_seconds

    @property
    def seconds_per_tick(self):
        rate = self.ticks_per_sec
        if rate <= 0.0:
            return None
        return 1.0 / rate

    @property
    def label(self):
        return speed_label(self._speed)

    @property
    def selected_speed(self):
        return self._last_speed

    @property
    def selected_label(self):
        return speed_label(self._last_speed)

    def set_speed(self, value, reason="manual"):
        speed = normalize_speed(value)
        if speed <= 0.0:
            return self.pause(reason)
        self._last_speed = speed
        if not self.paused:
            self._speed = speed
            self.pause_reason = ""
        return speed

    def pause(self, reason="manual"):
        if not self.paused:
            self._last_speed = self._speed
        self._speed = 0.0
        self.pause_reason = str(reason or "manual")
        return self._speed

    def resume(self):
        self._speed = self._last_speed or DEFAULT_SPEED
        self.pause_reason = ""
        return self._speed

    def set_paused(self, value):
        if value:
            return self.pause("manual")
        return self.resume()

    def toggle_pause(self):
        if self.paused:
            return self.resume()
        return self.pause("manual")

    def faster(self):
        index = SPEEDS.index(normalize_speed(self._current_speed()))
        if index + 1 < len(SPEEDS):
            self.set_speed(SPEEDS[index + 1])
        return self._current_speed()

    def slower(self):
        index = SPEEDS.index(normalize_speed(self._current_speed()))
        if index > 0:
            self.set_speed(SPEEDS[index - 1])
        return self._current_speed()

    def _current_speed(self):
        if self.paused:
            return self._last_speed
        return self._speed

    def advance(self, dt):
        if dt <= 0.0 or self.paused:
            return 0
        self.elapsed += float(dt)
        self.acc += float(dt) * self.ticks_per_sec
        ticks = int(self.acc)
        if ticks > self.max_catchup:
            self.dropped_ticks += ticks - self.max_catchup
            ticks = self.max_catchup
            self.acc = 0.0
        else:
            self.acc -= ticks
        self.ticks += ticks
        return ticks

    def reset_counters(self):
        self.acc = 0.0
        self.ticks = 0
        self.elapsed = 0.0
        self.dropped_ticks = 0
