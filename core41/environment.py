"""Детерминированный актор среды для активной арены.

Легаси-канон (`simulation.Environment`) был третьим агентом, который
получал давление и открывал окно. В `core41` среда пока отсутствовала, а
флаг `with_env` оставался мёртвым. Здесь — актор среды: он не воюет и не
принадлежит ни одной стороне, а по расписанию добавляет внешнее давление.

Первый срез был строго симметричным. Текущий слой добавляет:

- сезонность (`SEASONS`) — множитель силы событий;
- асимметричные события: истощение/передышка/болезнь/рана выбирают одну
  сторону, вторая получает половину эффекта;
- наблюдаемое расписание (`public_state()`), которое попадает в
  `Observation.env_pressure`/`env_season` и в признаки политик;
- **средовые источники болезни** (`ENV_ILLNESS_INTERVAL`): редкое событие
  «мор/сырость» поднимает `sickness` цели, а не только явный `--sickness`;
- **раны** (`ENV_WOUND_INTERVAL`): редкое событие наносит прямой урон `H`
  и оставляет устойчивое состояние `wound`, которое капает здоровьем,
  замедляет отдых и лечится отдыхом/`TREAT`.

Полной экономики среды (`force/defense/in_open`) по-прежнему нет — это
следующий слой.
"""

from .model import SICKNESS_MAX

ENV_EVENT_INTERVAL = 17
ENV_RELIEF_INTERVAL = 31
ENV_ILLNESS_INTERVAL = 500
ENV_WOUND_INTERVAL = 700
ENV_ENERGY_DRAIN = 2.0
ENV_HEALTH_DRAIN = 0.2
ENV_ENERGY_RELIEF = 3.0
ENV_HEALTH_RELIEF = 0.1
# Источник болезни намеренно редкий и слабый: за 2000 тактов он даёт
# несколько событий и не заменяет явную `sickness`/контактную передачу.
ENV_SICKNESS = 0.04
# Рана среды — сначала удар, затем устойчивое состояние: событие наносит
# прямой урон и оставляет `wound`, который сам капает здоровьем и лечится
# отдыхом/TREAT. Частота ниже истощения, чтобы среда оставалась фоном, а не
# вторым бойцом.
ENV_WOUND_DAMAGE = 3.0
ENV_WOUND_SEVERITY = 0.30
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


def _sickness(actor):
    return float(_agent(actor).sickness)


def _set_sickness(actor, value):
    _agent(actor).sickness = max(0.0, min(SICKNESS_MAX, float(value)))


def _energy(actor):
    return float(_agent(actor).energy_pool)


def _set_energy(actor, value):
    _agent(actor).energy_pool = max(0.0, float(value))


def _wound(actor):
    return float(getattr(_agent(actor), "wound", 0.0))


def _set_wound(actor, value):
    agent = _agent(actor)
    if not hasattr(agent, "wound"):
        return
    agent.wound = max(0.0, min(1.0, float(value)))


def _health(actor):
    return float(_agent(actor).health)


def _set_health(actor, value):
    _agent(actor).health = max(0.0, float(value))


def _max_energy(actor):
    return float(getattr(_agent(actor), "max_energy", 100.0))


class ArenaEnvironment:
    """Внешний фон: сезонность, истощение, болезнь, раны, асимметрия."""

    def __init__(
        self,
        seed=0,
        event_interval=ENV_EVENT_INTERVAL,
        relief_interval=ENV_RELIEF_INTERVAL,
        illness_interval=ENV_ILLNESS_INTERVAL,
        wound_interval=ENV_WOUND_INTERVAL,
        season_length=ENV_SEASON_LENGTH,
        asymmetric=True,
    ):
        self.seed = int(seed)
        self.event_interval = max(1, int(event_interval))
        self.relief_interval = max(1, int(relief_interval))
        self.illness_interval = max(1, int(illness_interval))
        self.wound_interval = max(1, int(wound_interval))
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
        next_illness = self.illness_interval - (
            self.ticks % self.illness_interval
        )
        next_wound = self.wound_interval - (
            self.ticks % self.wound_interval
        )
        return {
            "ticks": self.ticks,
            "season": season_name,
            "season_multiplier": float(season_multiplier),
            # 0 сразу после события, →1 перед следующим.
            "strain": 1.0 - next_event / float(self.event_interval),
            "relief": 1.0 - next_relief / float(self.relief_interval),
            "illness": 1.0 - next_illness / float(self.illness_interval),
            "wound": 1.0 - next_wound / float(self.wound_interval),
            "next_event": next_event,
            "next_relief": next_relief,
            "next_illness": next_illness,
            "next_wound": next_wound,
            "last_target": self.last_target,
            "asymmetric": self.asymmetric,
        }

    def _targets(self, kind):
        if not self.asymmetric:
            self.last_target = "both"
            return (("rl", 1.0), ("ai", 1.0))
        # Детерминированное чередование: воспроизводимо без хранения rng.
        interval = {
            "strain": self.event_interval,
            "relief": self.relief_interval,
            "illness": self.illness_interval,
            "wound": self.wound_interval,
        }.get(kind, self.event_interval)
        slot = self.ticks // interval
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
        if self.ticks % self.illness_interval == 0:
            for side, share in self._targets("illness"):
                actor = actors[side]
                if _health(actor) <= 0.0:
                    continue
                _set_sickness(
                    actor,
                    _sickness(actor)
                    + ENV_SICKNESS * season_multiplier * share,
                )
            events.append(
                {
                    "kind": "environment",
                    "event": "illness",
                    "ticks": self.ticks,
                    "season": season_name,
                    "target": self.last_target,
                    "sickness": ENV_SICKNESS * season_multiplier,
                    "text": "Среда: сырость и мор (%s, сезон %s)."
                    % (self.last_target, season_name),
                }
            )
        if self.ticks % self.wound_interval == 0:
            for side, share in self._targets("wound"):
                actor = actors[side]
                if _health(actor) <= 0.0:
                    continue
                _set_health(
                    actor,
                    _health(actor)
                    - ENV_WOUND_DAMAGE * season_multiplier * share,
                )
                _set_wound(
                    actor,
                    _wound(actor)
                    + ENV_WOUND_SEVERITY * season_multiplier * share,
                )
            events.append(
                {
                    "kind": "environment",
                    "event": "wound",
                    "ticks": self.ticks,
                    "season": season_name,
                    "target": self.last_target,
                    "health": -ENV_WOUND_DAMAGE * season_multiplier,
                    "wound": ENV_WOUND_SEVERITY * season_multiplier,
                    "text": "Среда: несчастный случай (%s, сезон %s)."
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
            "illness_interval": self.illness_interval,
            "wound_interval": self.wound_interval,
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
        self.illness_interval = max(
            1, int(state.get("illness_interval", self.illness_interval))
        )
        self.wound_interval = max(
            1, int(state.get("wound_interval", self.wound_interval))
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
