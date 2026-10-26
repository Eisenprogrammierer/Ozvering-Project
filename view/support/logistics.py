"""Логистика кампании: запасы, расход, подвоз и операции.

Модуль намеренно не меняет боевую математику ``warfare.py``: он ведёт
снабженческие запасы дивизии, переводит их в готовность подразделений
(``ui_supply``) и выполняет операции из ``configs/content/logistics.json``.
Потребности персонажей живут в ``needs.py``; логистика лишь поставляет
ресурсы, которые эти действия расходуют.

Классы запасов (I–VII) совпадают с конфигом и раскладываются в общий
словарь ``CampaignState.supplies``:

    I   — продовольствие      -> food
    II  — боеприпасы          -> ammo
    III — горючее             -> fuel
    IV  — медикаменты         -> medicine
    V   — инженерное имущество-> engineering
    VI  — вода                -> water
    VII — предметы морали     -> morale

«Влияние» (``influence``) — отдельный командирский ресурс: за него
запрашиваются конвои и штабные операции, но им не кормят людей.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .config_loader import load_json
from .log_journal import get_logger
from .traits import trait_modifiers

logger = get_logger("view.logistics")

# Соответствие классов запасов и ключей ``state.supplies``.
CLASS_TO_KEY = {
    "I": "food",
    "II": "ammo",
    "III": "fuel",
    "IV": "medicine",
    "V": "engineering",
    "VI": "water",
    "VII": "morale",
}
KEY_TO_CLASS = {value: key for key, value in CLASS_TO_KEY.items()}

DEFAULT_RESOURCE_DEFS = {
    "I": {"label": "Продовольствие", "unit": "кг"},
    "II": {"label": "Боеприпасы", "unit": "кг"},
    "III": {"label": "Горючее", "unit": "л"},
    "IV": {"label": "Медикаменты", "unit": "компл"},
    "V": {"label": "Инженерное имущество", "unit": "компл"},
    "VI": {"label": "Питьевая вода", "unit": "л"},
    "VII": {"label": "Предметы морали", "unit": "компл"},
}

DEFAULT_STOCKS = {
    "food": 420.0,
    "ammo": 260.0,
    "fuel": 180.0,
    "medicine": 75.0,
    "engineering": 55.0,
    "water": 620.0,
    "morale": 70.0,
    "influence": 30.0,
}

# Небольшой постоянный приток влияния за штабную работу и редкие
# автоколонны. Это не отменяет ручные конвои, но не даёт застрять без
# единственного ресурса, которым оплачивается подвоз.
DEFAULT_INFLUENCE_PER_HOUR = 4.0
DEFAULT_FREE_CONVOY_MINUTES = 180
FREE_CONVOY_KINDS = ("general", "water", "ammo", "medical", "fuel")
FREE_CONVOY_GAINS = {
    "general": {"food": 30, "water": 38, "ammo": 18},
    "water": {"water": 50},
    "ammo": {"ammo": 55},
    "medical": {"medicine": 18, "morale": 6},
    "fuel": {"fuel": 40},
}

# Ручные конвои: плата влиянием и заявка груза. Прибытие не мгновенное —
# конвой получает ETA, риск атаки и возможные потери в пути.
CONVOY_PRICES = {
    "general": {"influence": 5},
    "water": {"influence": 2},
    "ammo": {"influence": 4},
    "medical": {"influence": 3},
    "fuel": {"influence": 2},
}
CONVOY_GAINS = {
    "general": {"food": 70, "water": 85, "ammo": 40},
    "water": {"water": 120},
    "ammo": {"ammo": 90},
    "medical": {"medicine": 30, "morale": 10},
    "fuel": {"fuel": 70},
}
CONVOY_LABELS = {
    "general": "Общий конвой",
    "water": "Питьевая вода",
    "ammo": "Боеприпасы",
    "medical": "Медикаменты",
    "fuel": "Горючее",
}

# Суточные нормы на одного человека (и на подразделение в бою).
PER_MAN_MINUTE = {
    "food": 0.0015,
    "water": 0.0022,
    "medicine": 0.00018,
    "ammo": 0.0009,
    "fuel": 0.0007,
    "morale": 0.00018,
    "engineering": 0.00012,
}

SUPPLY_LABELS = {
    "food": "Продовольствие",
    "ammo": "Боеприпасы",
    "fuel": "Горючее",
    "medicine": "Медикаменты",
    "engineering": "Инженерное",
    "water": "Вода",
    "morale": "Мораль",
    "influence": "Влияние",
}


@dataclass
class UnitSupply:
    """Совместимый снимок снабжения одного отделения."""

    value: float

    def __post_init__(self):
        self.value = max(0.0, min(1.5, float(self.value)))
        self.norm = {cls: 100.0 for cls in CLASS_TO_KEY}
        pct = 100.0 * self.value
        self.actual = {cls: pct for cls in CLASS_TO_KEY}


@dataclass
class Convoy:
    """Конвой в пути: груз, ETA, риск и признак бесплатной автоколонны."""

    kind: str
    cargo: dict
    remaining_minutes: float
    total_minutes: float
    risk: float
    free: bool = False

    @property
    def eta_minutes(self):
        return max(0, int(round(self.remaining_minutes)))

    @property
    def cargo_text(self):
        return ", ".join(
            "%s +%d" % (SUPPLY_LABELS.get(key, key), round(amount))
            for key, amount in self.cargo.items() if amount > 0
        )

    def to_dict(self):
        return {
            "kind": self.kind,
            "cargo": dict(self.cargo),
            "remaining_minutes": float(self.remaining_minutes),
            "total_minutes": float(self.total_minutes),
            "risk": float(self.risk),
            "free": bool(self.free),
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            kind=str(data.get("kind", "general")),
            cargo={
                str(key): float(value)
                for key, value in (data.get("cargo") or {}).items()
            },
            remaining_minutes=float(data.get("remaining_minutes", 0.0)),
            total_minutes=float(data.get("total_minutes", 1.0)),
            risk=max(0.0, min(1.0, float(data.get("risk", 0.0)))),
            free=bool(data.get("free", False)),
        )


class LogisticsSystem:
    """Запасы дивизии, готовность подразделений и операции снабжения."""

    def __init__(self, state, stocks=None):
        self.state = state
        config = load_json("configs/content/logistics.json", {}) or {}
        resource_defs = config.get("resource_classes") or DEFAULT_RESOURCE_DEFS
        self.resource_defs = {
            cls: dict(value) for cls, value in resource_defs.items()
        }
        for cls, value in DEFAULT_RESOURCE_DEFS.items():
            self.resource_defs.setdefault(cls, dict(value))
        self.operations = dict(config.get("operations") or {})
        self.vehicles = dict(config.get("vehicle_types") or {})
        influence_cfg = config.get("influence") or {}
        self.influence_per_hour = max(
            0.0, float(influence_cfg.get(
                "passive_per_hour", DEFAULT_INFLUENCE_PER_HOUR
            ))
        )
        self.free_convoy_minutes = max(
            30, int(influence_cfg.get(
                "free_convoy_minutes", DEFAULT_FREE_CONVOY_MINUTES
            ))
        )
        convoy_cfg = config.get("convoy_config") or {}
        self.convoy_base_hours = max(
            0.25, float(convoy_cfg.get(
                "base_trip_hours", convoy_cfg.get("base_trip_time", 2.5)
            ))
        )
        self.convoy_base_loss_chance = max(
            0.0, min(0.95, float(convoy_cfg.get("base_loss_chance", 0.08)))
        )
        self.convoy_risk_combat_bonus = max(
            0.0, float(convoy_cfg.get("combat_risk_bonus", 0.10))
        )
        self.convoy_full_loss_chance = max(
            0.0, min(1.0, float(convoy_cfg.get("full_loss_chance", 0.25)))
        )
        partial = convoy_cfg.get("partial_loss_fraction") or [0.15, 0.55]
        self.convoy_partial_loss = (
            max(0.0, min(1.0, float(partial[0]))),
            max(0.0, min(1.0, float(partial[-1]))),
        )
        self.convoy_route = str(convoy_cfg.get("route_type", "dirt"))
        route_mods = convoy_cfg.get("route_type_time_modifier") or {}
        self.convoy_route_modifier = max(
            0.5, float(route_mods.get(self.convoy_route, 1.5))
        )
        jitter = (config.get("uncertainty") or {}).get("eta_jitter") or [1.0, 1.5]
        self.convoy_eta_jitter = (
            max(0.5, float(jitter[0])),
            max(0.5, float(jitter[-1])),
        )
        self._influence_accum = 0.0
        self._free_convoy_elapsed = 0.0
        self._free_convoy_index = 0
        self.convoys = []
        seed = int(getattr(getattr(state, "sim", None), "seed", 0) or 0)
        self.rng = random.Random(seed * 7919 + 13)
        self.supplies = self.state.supplies
        for key, amount in DEFAULT_STOCKS.items():
            self.supplies.setdefault(key, float(amount))
        if stocks:
            self.supplies.update(stocks)
        self.cooldowns = {}
        self.last_report = ""
        self._ensure_unit_state()

    # --- представление для оверлеев -------------------------------------
    def _ensure_unit_state(self):
        for det in getattr(self.state, "units", []):
            if not hasattr(det, "ui_supply"):
                det.ui_supply = 0.82
            if not hasattr(det, "ui_ammo"):
                det.ui_ammo = 0.82
            if not hasattr(det, "ui_fortification"):
                det.ui_fortification = 0.0

    @property
    def unit_supply(self):
        self._ensure_unit_state()
        return {
            i: UnitSupply(self.state.read_voltage(i, "U_supply"))
            for i in range(self.state.count)
        }

    def supply_of(self, idx):
        det = self.state.det_at(idx)
        if det is None:
            return 0.0
        return max(0.0, min(1.5, float(getattr(det, "ui_supply", 0.82))))

    def get_ammo_modifier(self, idx):
        return max(0.1, min(1.3, self.supply_of(idx)))

    def get_defense_modifier(self, idx):
        det = self.state.det_at(idx)
        fort = float(getattr(det, "ui_fortification", 0.0)) if det else 0.0
        return max(0.0, 0.2 * self.supply_of(idx) + fort)

    def get_offense_modifier(self, idx):
        return max(0.0, 0.15 * self.supply_of(idx))

    def stock(self, key):
        return float(self.supplies.get(key, 0.0))

    def daily_need(self, key):
        """Оценка суточного расхода по всем живым подразделениям игрока."""
        units = self._player_units()
        manpower = sum(max(1, len(getattr(det, "characters", []))) for det in units)
        return manpower * PER_MAN_MINUTE.get(key, 0.0) * 24 * 60

    def days_left(self, key):
        need = self.daily_need(key)
        if need <= 0:
            return None
        return self.stock(key) / need

    def _player_units(self):
        side = getattr(self.state, "player_side", "red")
        return [
            det for det in self.state.units
            if det.side == side and not getattr(det, "broken", False)
        ]

    def _trait_mods(self):
        return trait_modifiers(getattr(self.state, "commander_trait", None))

    def _has_active_combat(self):
        engine = getattr(self.state, "engine", None)
        engagements = getattr(engine, "engagements", None)
        if engagements:
            return True
        return bool(getattr(self.state, "engagements", None))

    # --- ежедневный/потактовый расход -----------------------------------
    def on_tick(self, seconds=300, engaged_names=None):
        """Списать довольствие и обновить готовность подразделений.

        Расход идёт по фактическому составу. Если запасов не хватает,
        готовность падает и мораль проседает; при покрытии — готовность
        медленно восстанавливается. Это единственное место, где логистика
        влияет на войска, и оно не вмешивается в ``warfare``.
        """
        minutes = max(0.0, float(seconds)) / 60.0
        if minutes <= 0:
            return
        engaged = set(engaged_names or [])
        mods = self._trait_mods()
        consumption = float(mods.get("supply_consumption", 1.0))
        for key in list(self.cooldowns):
            self.cooldowns[key] = max(0.0, self.cooldowns[key] - minutes)
            if self.cooldowns[key] <= 0:
                self.cooldowns.pop(key, None)

        self._process_convoys(minutes)

        for idx, det in enumerate(self.state.units):
            if det.side != getattr(self.state, "player_side", "red"):
                continue
            if getattr(det, "broken", False) or det.force <= 1:
                continue
            people = max(1, len(getattr(det, "characters", [])))
            demand = {
                key: rate * people * minutes * consumption
                for key, rate in PER_MAN_MINUTE.items()
            }
            if det.name in engaged or getattr(det, "engagements", 0):
                demand["ammo"] *= 6.0
                demand["fuel"] *= 3.0
                demand["medicine"] *= 2.5
            coverage = 1.0
            care_coverage = 1.0
            for key, amount in demand.items():
                if amount <= 0:
                    continue
                available = min(self.stock(key), amount)
                self.supplies[key] = max(0.0, self.stock(key) - available)
                ratio = available / amount if amount else 1.0
                coverage = min(coverage, ratio)
                if key in ("food", "water", "medicine"):
                    care_coverage = min(care_coverage, ratio)
            supply = float(getattr(det, "ui_supply", 0.82))
            if coverage >= 0.95:
                supply = min(1.15, supply + 0.010 * minutes / 5.0)
            elif coverage >= 0.5:
                supply = max(0.05, supply - 0.008 * minutes / 5.0)
            else:
                supply = max(0.0, supply - 0.035 * minutes / 5.0)
            det.ui_supply = supply
            det.ui_ammo = max(0.0, min(1.2, supply * (1.1 if coverage > .5 else .6)))
            if coverage < 0.5:
                self._adjust_morale(det, -0.35 * minutes / 5.0)
            elif coverage >= 0.95 and det.morale < 100.0:
                self._adjust_morale(det, 0.06 * minutes / 5.0)
            # Подразделение само закрывает базовые потребности по мере
            # подвоза. Игрок не «кормит» его вручную: это делает тыл.
            self._self_care(det, care_coverage, minutes,
                            det.name in engaged)
        self._accrue_influence(minutes)
        self.last_report = (
            "Снабжение: %s" % self.short_status()
        )

    def _adjust_morale(self, det, delta):
        """Изменить мораль роты через персонажей.

        ``refresh_psychology`` восстанавливает ``det.morale`` как среднее по
        персонажам, поэтому правка только агрегата была бы потеряна на
        следующем такте.
        """
        delta = float(delta)
        if not delta:
            return
        for character in det.characters:
            character.morale = max(
                0.0, min(100.0, character.morale + delta)
            )
        det.morale = max(0.0, min(100.0, det.morale + delta))

    def _accrue_influence(self, minutes):
        """Начислить пассивное влияние и, если подошло время, автоколонну.

        Влияние — не топливо и не еда, поэтому оно не тратится на
        самообеспечение. Прирост дробный; интерфейс округляет его при
        отображении, но запас растёт уже с первого такта.
        """
        if self.influence_per_hour > 0 and minutes > 0:
            rate = self.influence_per_hour * float(
                self._trait_mods().get("influence_rate", 1.0)
            )
            gain = rate / 60.0 * float(minutes)
            self._influence_accum += gain
            self.supplies["influence"] = self.stock("influence") + gain
        if minutes <= 0:
            return
        self._free_convoy_elapsed += float(minutes)
        while self._free_convoy_elapsed >= self.free_convoy_minutes:
            self._free_convoy_elapsed -= self.free_convoy_minutes
            self._deliver_free_convoy()

    @property
    def next_free_convoy_minutes(self):
        """Сколько игровых минут осталось до следующей автоколонны."""
        return max(
            0.0, self.free_convoy_minutes - self._free_convoy_elapsed
        )

    def _deliver_free_convoy(self):
        """Отправить редкую бесплатную автоколонну (без влияния).

        Название метода сохранено для совместимости, но доставка теперь
        отложенная: сначала конвой едет, затем может прибыть полностью,
        частично или не прибыть вовсе.
        """
        kind = FREE_CONVOY_KINDS[
            self._free_convoy_index % len(FREE_CONVOY_KINDS)
        ]
        self._free_convoy_index += 1
        gains = FREE_CONVOY_GAINS.get(kind, FREE_CONVOY_GAINS["general"])
        convoy = self._schedule_convoy(kind, gains, free=True, risk_scale=0.6)
        message = "Автоколонна отправлена: %s · ETA %d мин · риск %d%%" % (
            convoy.cargo_text, convoy.eta_minutes, round(convoy.risk * 100)
        )
        if getattr(self.state, "log_event", None) is not None:
            self.state.log_event(self.state.player_idx, message)
        logger.info("Логистика: бесплатная автоколонна (%s), %s",
                    kind, message)
        return {
            "ok": True,
            "kind": kind,
            "gains": dict(gains),
            "eta_minutes": convoy.eta_minutes,
            "risk": convoy.risk,
        }

    # --- конвои в пути ---------------------------------------------------
    def _schedule_convoy(self, kind, cargo, free=False, risk=None,
                         risk_scale=1.0, eta_minutes=None):
        """Поставить конвой в очередь и вернуть объект ``Convoy``."""
        if eta_minutes is None:
            jitter = self.rng.uniform(*self.convoy_eta_jitter)
            hours = (
                self.convoy_base_hours
                * self.convoy_route_modifier
                * jitter
                * float(self._trait_mods().get("convoy_time", 1.0))
            )
            eta_minutes = max(20.0, hours * 60.0)
        if risk is None:
            risk = (
                self.convoy_base_loss_chance
                + (self.convoy_risk_combat_bonus
                   if self._has_active_combat() else 0.0)
            ) * float(self._trait_mods().get("convoy_risk", 1.0)) * risk_scale
        risk = max(0.0, min(0.92, float(risk)))
        convoy = Convoy(
            kind=str(kind),
            cargo={
                str(key): float(value)
                for key, value in (cargo or {}).items() if value > 0
            },
            remaining_minutes=float(eta_minutes),
            total_minutes=max(1.0, float(eta_minutes)),
            risk=risk,
            free=bool(free),
        )
        self.convoys.append(convoy)
        return convoy

    def _process_convoys(self, minutes):
        """Продвинуть конвои и разрешить прибывшие."""
        remaining = []
        for convoy in self.convoys:
            convoy.remaining_minutes -= float(minutes)
            if convoy.remaining_minutes > 0:
                remaining.append(convoy)
                continue
            delayed = self._arrive_convoy(convoy)
            if delayed is not None:
                remaining.append(delayed)
        self.convoys = remaining

    def _arrive_convoy(self, convoy):
        """Разрешить один конвой. Вернуть конвой, если он задержан атакой."""
        cargo = dict(convoy.cargo)
        attacked = (
            convoy.risk > 0.0
            and self.rng.random() < max(0.0, min(1.0, convoy.risk))
        )
        if attacked:
            if self.rng.random() < self.convoy_full_loss_chance:
                self.state.log_event(
                    self.state.player_idx,
                    "Конвой уничтожен на маршруте: %s" % convoy.cargo_text,
                )
                logger.warning("Логистика: конвой (%s) уничтожен", convoy.kind)
                return None
            low, high = self.convoy_partial_loss
            loss = self.rng.uniform(min(low, high), max(low, high))
            cargo = {
                key: amount * (1.0 - loss)
                for key, amount in cargo.items()
            }
            delay = self.rng.randint(30, 90)
            convoy.cargo = cargo
            convoy.remaining_minutes = float(delay)
            convoy.total_minutes += float(delay)
            convoy.risk *= 0.45
            self.state.log_event(
                self.state.player_idx,
                "Конвой атакован: потеряно %d%%, задержка %d мин, "
                "уцелело: %s" % (
                    round(loss * 100), delay, convoy.cargo_text,
                ),
            )
            logger.warning(
                "Логистика: конвой (%s) атакован, потеря %d%%, задержка %d",
                convoy.kind, round(loss * 100), delay,
            )
            return convoy
        for key, amount in cargo.items():
            self.supplies[key] = self.stock(key) + amount
        self.state.log_event(
            self.state.player_idx,
            "Прибыл конвой: %s" % ", ".join(
                "%s +%d" % (SUPPLY_LABELS.get(key, key), round(amount))
                for key, amount in cargo.items()
            ),
        )
        logger.info("Логистика: конвой (%s) прибыл, %s",
                    convoy.kind, short_supplies(self.supplies))
        return None

    def convoy_status_rows(self):
        """Активные конвои для оверлея логистики."""
        return [
            {
                "kind": convoy.kind,
                "label": CONVOY_LABELS.get(convoy.kind, convoy.kind),
                "eta": convoy.eta_minutes,
                "risk": convoy.risk,
                "cargo": convoy.cargo_text,
                "free": convoy.free,
            }
            for convoy in sorted(
                self.convoys, key=lambda item: item.remaining_minutes
            )
        ]

    def _self_care(self, det, coverage, minutes, engaged):
        """Автоматическое самообеспечение отделения из общих запасов.

        Эффект сознательно слабее ручных действий: подвоз поддерживает
        людей, но не отменяет усталость, страх и боевой стресс.
        """
        if coverage < 0.35:
            return
        share = max(0.0, float(minutes)) / 5.0
        factor = min(1.0, float(coverage)) * share
        rested = getattr(det, "ui_order", "") == "rest"
        effects = {
            "hunger": 0.0020 * factor,
            "thirst": 0.0028 * factor,
            "fatigue": (0.0005 if engaged else 0.0016) * factor *
                       (1.5 if rested else 1.0),
            "health": 0.0008 * factor,
            "fear": 0.0006 * factor,
            "anxiety": 0.0005 * factor,
            "boredom": 0.0005 * factor if not engaged else 0.0,
        }
        det.satisfy_needs(
            {need: value for need, value in effects.items() if value > 0.0}
        )

    def short_status(self):
        return " | ".join(
            "%s %d" % (SUPPLY_LABELS.get(key, key), int(self.stock(key)))
            for key in ("food", "water", "ammo", "medicine")
        )

    # --- операции и подвоз ----------------------------------------------
    def operation_cost(self, operation_id, count=1):
        """Стоимость операции на ``count`` выбранных подразделений.

        Базовая цена в конфиге задана за одну роту; при действии на несколько
        рот расход умножается на их число. Это не даёт «бесплатно» снабдить
        всю дивизию одной операцией и оставляет выбор, кого снабжать.
        """
        op = self.operations.get(operation_id) or {}
        cost = op.get("cost") or {}
        multiplier = max(1, int(count))
        trait_mult = float(self._trait_mods().get("operation_cost", 1.0))
        return {
            CLASS_TO_KEY.get(cls, cls): float(amount) * multiplier * trait_mult
            for cls, amount in cost.items()
        }

    def can_operation(self, operation_id, count=1):
        if operation_id not in self.operations:
            return False, "операция недоступна"
        for key, amount in self.operation_cost(operation_id, count).items():
            if self.stock(key) < amount:
                return False, "нет: %s" % SUPPLY_LABELS.get(key, key)
        return True, ""

    def _resolve_targets(self, targets=None):
        """Привести индексы/имена/объекты к живым ротам игрока.

        ``None`` означает «все живые роты игрока» (совместимость со старым
        вызовом). Пустой список — сознательный отказ от целей: игрок может
        не снабжать никого и тем самым лишить конкретные роты помощи.
        """
        if targets is None:
            return self._player_units()
        if (isinstance(targets, (int, str)) or
                hasattr(targets, "side")):
            targets = [targets]
        player_side = getattr(self.state, "player_side", "red")
        resolved = []
        seen = set()
        for target in targets:
            det = None
            if isinstance(target, int) and not isinstance(target, bool):
                det = self.state.det_at(target)
            elif isinstance(target, str):
                det = next((
                    item for item in self.state.units
                    if item.name == target
                ), None)
            elif hasattr(target, "side"):
                det = target
            if det is None or det.side != player_side:
                continue
            if getattr(det, "broken", False) or det.force <= 1:
                continue
            if det.name in seen:
                continue
            seen.add(det.name)
            resolved.append(det)
        return resolved

    def apply_operation(self, operation_id, targets=None):
        """Выполнить операцию для одной или нескольких рот.

        ``targets`` может быть индексом, именем, объектом-отделением или
        списком таких значений. Стоимость умножается на число целей, а
        проверка запасов — общая (all-or-nothing): нельзя оплатить половину
        и оставить остальные роты без эффекта.
        """
        if operation_id not in self.operations:
            return {"ok": False, "reason": "операция недоступна"}
        resolved = self._resolve_targets(targets)
        if not resolved:
            return {"ok": False, "reason": "нет подразделений"}
        count = len(resolved)
        ok, reason = self.can_operation(operation_id, count)
        if not ok:
            return {"ok": False, "reason": reason}
        op = self.operations[operation_id]
        for key, amount in self.operation_cost(operation_id, count).items():
            self.supplies[key] = max(0.0, self.stock(key) - amount)
        targets = resolved
        effect = op.get("effect_type", operation_id)
        for det in targets:
            if effect == "fortify" or operation_id == "fortify":
                det.ui_fortification = min(
                    0.45, float(getattr(det, "ui_fortification", 0.0)) + 0.15
                )
                det.ui_supply = min(1.2, self.supply_of(
                    self.state.units.index(det)) + 0.08)
            elif effect == "fierce_attack":
                det.morale = min(100.0, det.morale + 4.0)
                det.aggression = min(1.5, det.aggression + 0.08)
                det.satisfy_needs({"fear": 0.10, "status": 0.06},
                                  morale_bonus=0.3)
            elif effect == "offense":
                det.aggression = min(1.5, det.aggression + 0.12)
                det.morale = min(100.0, det.morale + 3.0)
                det.satisfy_needs({"fear": 0.08, "status": 0.08},
                                  morale_bonus=0.4)
            elif effect in ("active_defense", "defense"):
                det.discipline = min(1.5, det.discipline + 0.06)
                det.satisfy_needs({"anxiety": 0.10, "fear": 0.06},
                                  morale_bonus=0.2)
            elif effect == "medevac":
                det.losses = max(0.0, det.losses * 0.82)
                cap = float(getattr(det, "start_force", 40.0))
                det.force = min(cap, det.force + 0.5)
                det.satisfy_needs({"health": 0.30, "fear": 0.10},
                                  morale_bonus=0.8)
            elif effect == "morale_boost":
                det.morale = min(100.0, det.morale + 5.0)
                det.satisfy_needs(
                    {"boredom": 0.20, "loneliness": 0.18, "status": 0.10},
                    morale_bonus=0.9,
                )
        self.state.log_event(
            self.state.player_idx,
            "Логистическая операция: %s (%d %s)" % (
                operation_id, count,
                "рота" if count == 1 else "рот",
            ),
        )
        logger.info("Логистика: операция %s для %d рот, остатки=%s",
                    operation_id, count, short_supplies(self.supplies))
        return {
            "ok": True,
            "count": count,
            "targets": [det.name for det in targets],
            "stocks": dict(self.supplies),
        }

    def request_convoy(self, kind="general", risk=None):
        """Отправить конвой. Стоимость — влияние; прибытие отложенное.

        ``risk`` — необязательное переопределение вероятности атаки для
        тестов и сценарных проверок. В обычной игре риск вычисляется из
        обстановки, маршрута и черты командира.
        """
        if kind not in CONVOY_GAINS:
            return {"ok": False, "reason": "неизвестный тип конвоя"}
        price = CONVOY_PRICES.get(kind, CONVOY_PRICES["general"])
        for key, amount in price.items():
            if self.stock(key) < amount:
                return {"ok": False, "reason": "нет влияния"}
        for key, amount in price.items():
            self.supplies[key] = max(0.0, self.stock(key) - amount)
        gains = dict(CONVOY_GAINS[kind])
        convoy = self._schedule_convoy(kind, gains, free=False, risk=risk)
        self.state.log_event(
            self.state.player_idx,
            "Конвой отправлен: %s · ETA %d мин · риск %d%%" % (
                convoy.cargo_text, convoy.eta_minutes,
                round(convoy.risk * 100),
            ),
        )
        logger.info(
            "Логистика: отправлен конвой %s, ETA %d мин, риск %d%%, груз %s",
            kind, convoy.eta_minutes, round(convoy.risk * 100),
            short_supplies(gains),
        )
        return {
            "ok": True,
            "kind": kind,
            "gains": gains,
            "eta_minutes": convoy.eta_minutes,
            "risk": convoy.risk,
        }

    def morning_resupply(self):
        """Ночной подвоз: небольшой бесплатный приток запасов.

        Это тоже колонна, а не телепорт: она отправляется утром и прибывает
        через несколько часов, поэтому игрок должен планировать запас.
        """
        gains = {
            "food": 26, "water": 34, "ammo": 16, "medicine": 6,
            "fuel": 10, "engineering": 4, "morale": 5,
        }
        convoy = self._schedule_convoy(
            "general", gains, free=True, risk_scale=0.75
        )
        self.state.log_event(
            self.state.player_idx,
            "Ночной подвоз отправлен: ETA %d мин · риск %d%%" % (
                convoy.eta_minutes, round(convoy.risk * 100)
            ),
        )
        logger.info("Логистика: ночной подвоз отправлен, ETA %d мин",
                    convoy.eta_minutes)

    def status_rows(self):
        """Строки для оверлея логистики."""
        rows = []
        for cls in ("I", "II", "III", "IV", "V", "VI", "VII"):
            key = CLASS_TO_KEY[cls]
            label = self.resource_defs.get(cls, {}).get(
                "label", SUPPLY_LABELS.get(key, key)
            )
            rows.append({
                "key": key,
                "label": label,
                "stock": self.stock(key),
                "daily": self.daily_need(key),
                "days": self.days_left(key),
            })
        return rows

    # --- сохранение ------------------------------------------------------
    def get_save_snapshot(self):
        rng_state = self.rng.getstate()
        return {
            "supplies": dict(self.supplies),
            "cooldowns": dict(self.cooldowns),
            "influence_accum": float(self._influence_accum),
            "free_convoy_elapsed": float(self._free_convoy_elapsed),
            "free_convoy_index": int(self._free_convoy_index),
            "convoys": [convoy.to_dict() for convoy in self.convoys],
            "rng_state": [rng_state[0], list(rng_state[1]), rng_state[2]],
        }

    def load_from_snapshot(self, snapshot):
        if not snapshot:
            return
        supplies = dict(self.supplies)
        supplies.update(snapshot.get("supplies") or {})
        self.supplies.clear()
        self.supplies.update(supplies)
        self.cooldowns = {
            str(key): float(value)
            for key, value in (snapshot.get("cooldowns") or {}).items()
        }
        self._influence_accum = float(snapshot.get(
            "influence_accum", self._influence_accum
        ))
        self._free_convoy_elapsed = float(snapshot.get(
            "free_convoy_elapsed", self._free_convoy_elapsed
        ))
        self._free_convoy_index = int(snapshot.get(
            "free_convoy_index", self._free_convoy_index
        ))
        self.convoys = [
            Convoy.from_dict(item)
            for item in (snapshot.get("convoys") or [])
            if isinstance(item, dict)
        ]
        rng_state = snapshot.get("rng_state")
        if isinstance(rng_state, (list, tuple)) and len(rng_state) == 3:
            try:
                self.rng.setstate((
                    int(rng_state[0]),
                    tuple(int(value) for value in rng_state[1]),
                    rng_state[2],
                ))
            except (TypeError, ValueError):
                logger.warning("Логистика: не удалось восстановить RNG конвоев")
        self._ensure_unit_state()


def short_supplies(supplies):
    return ", ".join(
        "%s=%d" % (key, int(value))
        for key, value in supplies.items()
    )
