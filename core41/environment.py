"""Детерминированный актор среды для активной арены.

Легаси-канон (`simulation.Environment`) был третьим агентом, который
получал давление и открывал окно. В `core41` среда пока отсутствовала, а
флаг `with_env` оставался мёртвым. Здесь — актор среды: он не воюет и не
принадлежит ни одной стороне, а по расписанию добавляет внешнее давление.

Первый срез был строго симметричным. Слой P1.8 добавил:

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

Слой A1 (2026-10-31) превращает среду в осмысленного третьего актора по
канону `simulation.Environment`:

- **накопленное давление**: работа сторон доходит до среды через
  `ingest()`/`receive_pressure()` (схема Шмитта из канона — порог
  `max(ON_MIN, ON_FRAC*F)`, спад `DECAY_ADOPT`, TTL окна);
- **окно уязвимости** (`window_open()`): достигнув порога, среда на
  короткое время усиливает успех атак обеих сторон (канонный
  `ENV_BONUS`) — наблюдательный сигнал в `public_state()["window"]`
  попадает в 21-й признак политик (`env_window`);
- **собственная сила и доход**: среда копит `force` (канонный
  `ENV_INCOME` за такт, потолок `rest_ceiling`) и обслуживает её
  (`UPKEEP`), т.е. имеет собственный ресурсный цикл;
- **цель существования**: `goal_reached()` — накопить целевую силу за
  отведённый горизонт; недостижение цели означает коллапс среды
  (`collapse=True`), и обе стороны теряют внешнего партнёра (событие
  `environment/collapse`);
- **реакция на истощение сторон**: при очень низком `E` у стороны среда
  даёт ей передышку раньше расписания — «заинтересована» в том, чтобы
  дуэль не угасла.

Экономика остаётся фоновой: среда не наносит урон целенаправленно и не
воюет; окно лишь меняет вероятность успеха работы (как `in_open` у
агентов). Полная миграция организационных шкал — всё ещё следующий слой.
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

# --- A1: экономика и собственная цель среды (канон simulation) ---------
# Значения перенесены из таблицы `simulation.PARAMETERS` (ON_FRAC 0.25,
# ON_MIN 6, OFF_FRAC 0.4, OPEN_TTL 8, DECAY_ADOPT 0.95, ENV_INCOME 2,
# UPKEEP 1, ENV_BONUS 0.25, receive_pressure w*0.01 с потолком
# ENV_REST_CAP 10); здесь они закреплены константами, чтобы `core41` не
# импортировал легаси-модуль.
ENV_PRESSURE_GAIN = 0.01        # receive_pressure: rest_units += w * 0.01
ENV_REST_CAP = 10.0             # потолок накопленного давления
ENV_ON_FRAC = 0.25              # schmitt_on = max(ON_MIN, ON_FRAC * F)
ENV_ON_MIN = 6.0
ENV_DECAY_ADOPT = 0.95          # спад w_adopt за такт
ENV_OPEN_TTL = 8                # тактов окно держится после пика
ENV_OFF_FRAC = 0.4              # закрытие: w_adopt < OFF_FRAC * порог
ENV_INCOME = 2.0                # собственный доход силы за такт
ENV_UPKEEP = 1.0                # обслуживание силы за такт
ENV_BONUS = 0.25                # успех работы при открытом окне среды
ENV_FORCE_BASE = 10.0           # стартовая сила среды
ENV_GOAL_RATIO = 0.60           # цель: 60% потолка к deadline
ENV_GOAL_HORIZON = 900          # тактов на достижение цели
ENV_STARVING_E = 2.0            # E стороны ниже — среда даёт передышку


def _env_rng(world):
    """Детерминированный rng среды из носителя (`ArenaMatch`/модель UI)."""
    rng = getattr(world, "rng", None)
    if rng is None:
        import random

        rng = random.Random(0)
    return rng


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
    """Внешний фон: сезонность, истощение, болезнь, раны, асимметрия.

    Слой A1 добавляет среде собственную экономику и цель (канон
    `simulation.Environment`): накопленное давление с окном уязвимости
    (`ingest`/`window_open`), собственная сила с доходом/обслуживанием и
    горизонтом цели (`goal_reached`/`collapse`). Экономика фоновая: среда
    не воюет, окно лишь усиливает успех работы обеих сторон.
    """

    def __init__(
        self,
        seed=0,
        event_interval=ENV_EVENT_INTERVAL,
        relief_interval=ENV_RELIEF_INTERVAL,
        illness_interval=ENV_ILLNESS_INTERVAL,
        wound_interval=ENV_WOUND_INTERVAL,
        season_length=ENV_SEASON_LENGTH,
        asymmetric=True,
        force=ENV_FORCE_BASE,
        goal_ratio=ENV_GOAL_RATIO,
        goal_horizon=ENV_GOAL_HORIZON,
        with_economy=True,
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
        # --- A1: экономика и цель --------------------------------------
        self.with_economy = bool(with_economy)
        self.force = max(0.0, float(force))
        self.goal_ratio = max(0.0, min(1.0, float(goal_ratio)))
        self.goal_horizon = max(1, int(goal_horizon))
        self.pressure = 0.0          # w_adopt канона: сырое давление
        self.open_timer = 0
        self.in_window = False
        self.collapsed = False
        self.goal_reached = False

    @property
    def rest_ceiling(self):
        """Потолок собственной силы среды (как `L` у агентов канона)."""
        return 60.0 + 10.0 * min(ENV_REST_CAP, self.pressure)

    @property
    def goal_force(self):
        """Целевая сила: доля от базового потолка к дедлайну."""
        return self.goal_ratio * (60.0 + 10.0 * ENV_REST_CAP)

    def schmitt_on(self):
        return max(ENV_ON_MIN, ENV_ON_FRAC * self.force)

    def receive_pressure(self, work):
        """Давление работы доходит до среды (как в легаси-каноне).

        Возвращает True, если на этом такте открылось окно уязвимости.
        """
        if not self.with_economy or self.collapsed:
            return False
        self.pressure += max(0.0, float(work))
        opened = False
        if not self.in_window and self.pressure >= self.schmitt_on():
            self.in_window = True
            self.open_timer = ENV_OPEN_TTL
            opened = True
        return opened

    def ingest(self, work):
        """Симметричный вход экономики: давление и накопление rest-единиц."""
        opened = self.receive_pressure(work)
        self.pressure_rest = min(
            ENV_REST_CAP,
            getattr(self, "pressure_rest", 0.0)
            + max(0.0, float(work)) * ENV_PRESSURE_GAIN,
        )
        return opened

    def window_open(self):
        return bool(self.in_window and not self.collapsed)

    def _tick_window(self):
        """Шмиттов гистерезис окна: спад давления и закрытие по TTL/порогу."""
        if not self.with_economy:
            return None
        self.pressure *= ENV_DECAY_ADOPT
        if not self.in_window:
            return None
        self.open_timer -= 1
        off_now = ENV_OFF_FRAC * self.schmitt_on()
        if self.open_timer <= 0 or self.pressure < off_now:
            self.in_window = False
            return {
                "kind": "environment",
                "event": "window_close",
                "ticks": self.ticks,
                "text": "Среда: окно закрылось.",
            }
        return None

    def _tick_economy(self):
        """Собственный ресурсный цикл среды и проверка цели/коллапса."""
        if not self.with_economy or self.collapsed:
            return None
        self.force = min(self.force + ENV_INCOME, self.rest_ceiling)
        self.force = max(0.0, self.force - ENV_UPKEEP)
        if self.force >= self.goal_force:
            self.goal_reached = True
            self.collapsed = True
            return {
                "kind": "environment",
                "event": "goal",
                "ticks": self.ticks,
                "force": float(self.force),
                "target": float(self.goal_force),
                "text": "Среда: цель достигнута (%.1f) — фон укрепился."
                % self.force,
            }
        if self.ticks >= self.goal_horizon:
            self.collapsed = True
            return {
                "kind": "environment",
                "event": "collapse",
                "ticks": self.ticks,
                "force": float(self.force),
                "target": float(self.goal_force),
                "text": "Среда: цель не достигнута за %d тактов — коллапс "
                "фона (сила %.1f/%.1f)."
                % (self.ticks, self.force, self.goal_force),
            }
        return None

    def react_to_exhaustion(self, left, right):
        """Забота о партнёрах: истощённая сторона получает передышку раньше.

        Это минимальная «собственная заинтересованность» среды: ей выгоден
        живой контрагент дуэли, поэтому при E стороны ниже ENV_STARVING_E
        среда отдаёт часть накопленного давления в виде энергии.
        """
        events = []
        if not self.with_economy or self.collapsed:
            return events
        for side, actor in (("rl", left), ("ai", right)):
            energy = _energy(actor)
            if energy > ENV_STARVING_E or _health(actor) <= 0.0:
                continue
            gift = min(3.0, max(0.5, self.pressure * 0.05))
            _set_energy(actor, energy + gift)
            self.pressure = max(0.0, self.pressure - gift)
            events.append(
                {
                    "kind": "environment",
                    "event": "support",
                    "ticks": self.ticks,
                    "target": side,
                    "energy": gift,
                    "text": "Среда: поддержка истощённой %s (+%.1f E)."
                    % (side, gift),
                }
            )
        return events

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
            # --- A1: наблюдаемая экономика и цель ----------------------
            "window": self.window_open(),
            "pressure": float(self.pressure),
            "pressure_ratio": (
                min(1.0, self.pressure / max(1.0, self.schmitt_on()))
                if self.with_economy
                else 0.0
            ),
            "env_force": float(self.force),
            "goal_force": float(self.goal_force),
            "goal_progress": (
                min(1.0, self.force / max(1.0, self.goal_force))
                if self.with_economy
                else 0.0
            ),
            "deadline": int(self.goal_horizon),
            "collapsed": bool(self.collapsed),
            "goal_reached": bool(self.goal_reached),
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
        # A1: экономика — сначала спад/закрытие окна, затем свой цикл.
        close_event = self._tick_window()
        if close_event is not None:
            events.append(close_event)
        economy_event = self._tick_economy()
        if economy_event is not None:
            events.append(economy_event)
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
        # A1: реакция на истощение сторон (забота о живом контрагенте).
        events.extend(self.react_to_exhaustion(left, right))
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
            # A1: экономика/цель. Старые снимки без этих ключей грузятся
            # в значения по умолчанию — совместимость сохранена.
            "with_economy": self.with_economy,
            "force": float(self.force),
            "goal_ratio": float(self.goal_ratio),
            "goal_horizon": int(self.goal_horizon),
            "pressure": float(self.pressure),
            "pressure_rest": float(getattr(self, "pressure_rest", 0.0)),
            "open_timer": int(self.open_timer),
            "in_window": bool(self.in_window),
            "collapsed": bool(self.collapsed),
            "goal_reached": bool(self.goal_reached),
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
        # A1: экономика/цель (старые снимки — значения по умолчанию).
        self.with_economy = bool(
            state.get("with_economy", self.with_economy)
        )
        self.force = max(0.0, float(state.get("force", self.force)))
        self.goal_ratio = max(
            0.0, min(1.0, float(state.get("goal_ratio", self.goal_ratio)))
        )
        self.goal_horizon = max(
            1, int(state.get("goal_horizon", self.goal_horizon))
        )
        self.pressure = max(
            0.0, float(state.get("pressure", self.pressure))
        )
        self.pressure_rest = max(
            0.0,
            min(
                ENV_REST_CAP,
                float(state.get("pressure_rest", getattr(
                    self, "pressure_rest", 0.0
                ))),
            ),
        )
        self.open_timer = int(state.get("open_timer", self.open_timer))
        self.in_window = bool(state.get("in_window", self.in_window))
        self.collapsed = bool(state.get("collapsed", self.collapsed))
        self.goal_reached = bool(
            state.get("goal_reached", self.goal_reached)
        )
        return self.state_dict()
