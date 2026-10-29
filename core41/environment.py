"""Детерминированный актор среды для активной арены.

Легаси-канон (`simulation.Environment`) был третьим агентом, который
получал давление и открывал окно. В `core41` среда пока отсутствовала, а
флаг `with_env` оставался мёртвым. Здесь — первый срез именно актора
среды: он не воюет и не принадлежит ни одной стороне, а по фиксированному
расписанию добавляет внешнее давление обоим участникам одинаково.

Это не полная экономика среды: состав, сезонность и асимметричные события
остаются открытыми. Важно, что `with_env=True` теперь означает реальный
такт среды, а не просто сохранённый флаг.
"""

ENV_EVENT_INTERVAL = 17
ENV_RELIEF_INTERVAL = 31
ENV_ENERGY_DRAIN = 2.0
ENV_HEALTH_DRAIN = 0.2
ENV_ENERGY_RELIEF = 3.0
ENV_HEALTH_RELIEF = 0.1


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
    """Симметричный внешний фон: периодическое истощение и передышка."""

    def __init__(
        self,
        seed=0,
        event_interval=ENV_EVENT_INTERVAL,
        relief_interval=ENV_RELIEF_INTERVAL,
    ):
        self.seed = int(seed)
        self.event_interval = max(1, int(event_interval))
        self.relief_interval = max(1, int(relief_interval))
        self.ticks = 0
        self.events = []

    def tick(self, left, right):
        """Один такт среды; возвращает события этого такта."""
        self.ticks += 1
        events = []
        agents = (left, right)
        if self.ticks % self.event_interval == 0:
            for actor in agents:
                _set_energy(actor, _energy(actor) - ENV_ENERGY_DRAIN)
                _set_health(actor, _health(actor) - ENV_HEALTH_DRAIN)
            events.append(
                {
                    "kind": "environment",
                    "event": "strain",
                    "ticks": self.ticks,
                    "energy": -ENV_ENERGY_DRAIN,
                    "health": -ENV_HEALTH_DRAIN,
                    "text": "Среда: истощение (обоим сторонам).",
                }
            )
        if self.ticks % self.relief_interval == 0:
            for actor in agents:
                ceiling = _max_energy(actor)
                _set_energy(actor, min(ceiling, _energy(actor) + ENV_ENERGY_RELIEF))
                _set_health(actor, _health(actor) + ENV_HEALTH_RELIEF)
            events.append(
                {
                    "kind": "environment",
                    "event": "relief",
                    "ticks": self.ticks,
                    "energy": ENV_ENERGY_RELIEF,
                    "health": ENV_HEALTH_RELIEF,
                    "text": "Среда: передышка (обоим сторонам).",
                }
            )
        self.events = events
        return tuple(events)

    def state_dict(self):
        return {
            "seed": self.seed,
            "event_interval": self.event_interval,
            "relief_interval": self.relief_interval,
            "ticks": self.ticks,
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
        self.ticks = max(0, int(state.get("ticks", self.ticks)))
        return self.state_dict()
