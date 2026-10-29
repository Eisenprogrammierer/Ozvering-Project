"""Детерминированный актор среды для активной арены.

Легаси-канон (`simulation.Environment`) был третьим агентом, который
получал давление и открывал окно. В `core41` среда пока отсутствовала, а
флаг `with_env` оставался мёртвым. Здесь — актор среды: он не воюет и не
принадлежит ни одной стороне, а по расписанию добавляет внешнее давление.

Первый срез был строго симметричным. Текущий слой добавляет:

- сезонность (`SEASONS`) — множитель силы событий;
- асимметричные события: истощение/передышка выбирают одну сторону, вторая
  получает половину эффекта;
- наблюдаемое расписание (`public_state()`), которое попадает в
  `Observation.env_pressure`/`env_season` и в признаки политик.

Полной экономики среды (резервуары, раны, `force/defense/in_open`) по-
прежнему нет — это следующий слой.
"""

ENV_EVENT_INTERVAL = 17
ENV_RELIEF_INTERVAL = 31
ENV_ENERGY_DRAIN = 2.0
ENV_HEALTH_DRAIN = 0.2
ENV_ENERGY_RELIEF = 3.0
ENV_HEALTH_RELIEF = 0.1
ENV_SEASON_LENGTH = 240
# (имя, множитель силы событий)
SEASONS = (
    ("calm", 0.60),
    ("lean", 1.00),
    ("harsh", 1.30),
    ("recovery", 0.80),
)
ENV_SECONDARY_SHARE = 0.5


def _agent(actor):
    """Достать `ArenaAgent` из фасада (`Commander` и т.п.)."""
    return getattr(actor, "agent", actor)


def _energy(actor):
    return float(_agent(actor).energy_pool)


def _set_energy(actor, value):
    _agent(actor).energy_pool = max(0.0, float(value))


def _health(actor):
    return float(_agent(actor).health)


def _set_health(actor, value):
    _agent(actor).health = max(0.0, float(value))


def _max_energy(actor):
    return float(getattr(_agent(actor), "max_energy", 100.0))


class ArenaEnvironment:
    """Внешний фон: сезонность, истощение/передышка, асимметрия."""

    def __init__(
        self,
        seed=0,
        event_interval=ENV_EVENT_INTERVAL,
        relief_interval=ENV_RELIEF_INTERVAL,
        season_length=ENV_SEASON_LENGTH,
        asymmetric=True,
    ):
        self.seed = int(seed)
        self.event_interval = max(1, int(event_interval))
        self.relief_interval = max(1, int(relief_interval))
        self.season_length = max(1, int(season_length))
        self.asymmetric = bool(asymmetric)
        self.ticks = 0
        self.events = []
        self.last_target = "both"

    def season(self):
        index = (self.ticks // self.season_length) % len(SEASONS)
        return SEASONS[index]

    def public_state(self):
        """Наблюдаемое агентом расписание среды."""
        season_name, season_multiplier = self.season()
        next_event = self.event_interval - (self.ticks % self.event_interval)
        next_relief = self.relief_interval - (
            self.ticks % self.relief_interval
        )
        return {
            "ticks": self.ticks,
            "season": season_name,
            "season_multiplier": float(season_multiplier),
            # 0 сразу после события, →1 перед следующим.
            "strain": 1.0 - next_event / float(self.event_interval),
            "relief": 1.0 - next_relief / float(self.relief_interval),
            "next_event": next_event,
            "next_relief": next_relief,
            "last_target": self.last_target,
            "asymmetric": self.asymmetric,
        }

    def _targets(self, kind):
        if not self.asymmetric:
            self.last_target = "both"
            return (("rl", 1.0), ("ai", 1.0))
        # Детерминированное чередование: воспроизводимо без хранения rng.
        slot = self.ticks // (
            self.event_interval if kind == "strain" else self.relief_interval
        )
        primary = "rl" if slot % 2 == 0 else "ai"
        secondary = "ai" if primary == "rl" else "rl"
        self.last_target = primary
        return ((primary, 1.0), (secondary, ENV_SECONDARY_SHARE))

    def tick(self, left, right):
        """Один такт среды; возвращает события этого такта."""
        self.ticks += 1
        events = []
        actors = {"rl": left, "ai": right}
        season_name, season_multiplier = self.season()
        if self.ticks % self.event_interval == 0:
            for side, share in self._targets("strain"):
                actor = actors[side]
                _set_energy(
                    actor,
                    _energy(actor)
                    - ENV_ENERGY_DRAIN * season_multiplier * share,
                )
                _set_health(
                    actor,
                    _health(actor)
                    - ENV_HEALTH_DRAIN * season_multiplier * share,
                )
            events.append(
                {
                    "kind": "environment",
                    "event": "strain",
                    "ticks": self.ticks,
                    "season": season_name,
                    "target": self.last_target,
                    "energy": -ENV_ENERGY_DRAIN * season_multiplier,
                    "health": -ENV_HEALTH_DRAIN * season_multiplier,
                    "text": "Среда: истощение (%s, сезон %s)."
                    % (self.last_target, season_name),
                }
            )
        if self.ticks % self.relief_interval == 0:
            for side, share in self._targets("relief"):
                actor = actors[side]
                ceiling = _max_energy(actor)
                _set_energy(
                    actor,
                    min(
                        ceiling,
                        _energy(actor)
                        + ENV_ENERGY_RELIEF * season_multiplier * share,
                    ),
                )
                _set_health(
                    actor,
                    _health(actor)
                    + ENV_HEALTH_RELIEF * season_multiplier * share,
                )
            events.append(
                {
                    "kind": "environment",
                    "event": "relief",
                    "ticks": self.ticks,
                    "season": season_name,
                    "target": self.last_target,
                    "energy": ENV_ENERGY_RELIEF * season_multiplier,
                    "health": ENV_HEALTH_RELIEF * season_multiplier,
                    "text": "Среда: передышка (%s, сезон %s)."
                    % (self.last_target, season_name),
                }
            )
        self.events = events
        return tuple(events)

    def state_dict(self):
        return {
            "seed": self.seed,
            "event_interval": self.event_interval,
            "relief_interval": self.relief_interval,
            "season_length": self.season_length,
            "asymmetric": self.asymmetric,
            "ticks": self.ticks,
            "last_target": self.last_target,
        }

    def load_state_dict(self, state):
        state = state or {}
        self.seed = int(state.get("seed", self.seed))
        self.event_interval = max(
            1, int(state.get("event_interval", self.event_interval))
        )
        self.relief_interval = max(
            1, int(state.get("relief_interval", self.relief_interval))
        )
        self.season_length = max(
            1, int(state.get("season_length", self.season_length))
        )
        self.asymmetric = bool(
            state.get("asymmetric", self.asymmetric)
        )
        self.ticks = max(0, int(state.get("ticks", self.ticks)))
        self.last_target = str(
            state.get("last_target", self.last_target)
        )
        return self.state_dict()
