"""Адаптер нового войскового слоя (``warfare.py``) к экранам ``view``.

Легаси-UI ожидал ``WorldState`` с массивами сегментов/напряжений и движок
с приказами. Здесь эти ожидания реализованы как тонкий *presентера*: данные
берутся из ``WarfareSimulation``, а действия игрока переводятся в пассивные
приказы ``warfare.Order``. Математическое ядро не изменяется.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

import warfare as W
from .content import Content
from .geometry import FrontGeometry
from .log_journal import get_logger
from .logistics import LogisticsSystem, UnitSupply
from .needs import NeedsSystem

logger = get_logger("view.world")

MAP_SIZE = 256
CELL_SIZE = 24

# Автоплан — не тактическая команда отдельной роте, а замысел на уровне
# армии. Подразделения получают не одну общую точку, а свои полосы/места
# на рубеже, поэтому не сбиваются в кучу и не останавливаются навсегда
# на дистанции огня.
PLAN_MODES = ("off", "hold", "advance")
PLAN_LABELS = {
    "off": "выключен",
    "hold": "оборона",
    "advance": "наступление",
}
PLAN_ADVANCE_DISTANCE = 5.0
PLAN_LANE_WIDTH_MIN = 6.0
PLAN_LANE_WIDTH_MAX = 20.0


def _distance(a, b):
    """Манхэттенское расстояние между клетками поля."""
    return abs(int(a[0]) - int(b[0])) + abs(int(a[1]) - int(b[1]))


def _clamp_cell(point):
    """Привести точку сетки 24×24 к допустимой клетке."""
    return (
        max(0, min(CELL_SIZE, int(round(float(point[0]))))),
        max(0, min(CELL_SIZE, int(round(float(point[1]))))),
    )


def _unit_vector(vector, fallback=(1.0, 0.0)):
    """Нормировать вектор; при нулевой длине вернуть запасной."""
    x, y = float(vector[0]), float(vector[1])
    length = (x * x + y * y) ** 0.5
    if length < 1e-9:
        return (float(fallback[0]), float(fallback[1]))
    return (x / length, y / length)


@dataclass
class ArmyPlan:
    """Замысел армии: держать рубеж или наступать по оси.

    ``line`` хранится двумя клетками рубежа, ``target`` — точкой, которую
    выбрал игрок. Если цели нет, наступление автоматически ведёт армию к
    центру противника. План сериализуется в снимок кампании.
    """

    mode: str = "off"
    axis: tuple = (1.0, 0.0)
    target: tuple | None = None
    line: tuple | None = None
    auto: bool = False

    def __post_init__(self):
        if self.mode not in PLAN_MODES:
            self.mode = "off"
        self.axis = _unit_vector(self.axis)
        if self.target is not None:
            self.target = _clamp_cell(self.target)
        if self.line is not None:
            try:
                first, second = self.line
                self.line = (_clamp_cell(first), _clamp_cell(second))
            except (TypeError, ValueError):
                self.line = None

    @property
    def active(self):
        return self.mode in ("hold", "advance")

    @property
    def label(self):
        return PLAN_LABELS.get(self.mode, self.mode)

    def to_dict(self):
        return {
            "mode": self.mode,
            "axis": [round(float(self.axis[0]), 4),
                     round(float(self.axis[1]), 4)],
            "target": list(self.target) if self.target is not None else None,
            "line": (
                [list(self.line[0]), list(self.line[1])]
                if self.line is not None else None
            ),
            "auto": bool(self.auto),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls()
        line = data.get("line")
        if (not isinstance(line, (list, tuple)) or len(line) != 2):
            line = None
        return cls(
            mode=str(data.get("mode", "off")),
            axis=tuple(data.get("axis") or (1.0, 0.0)),
            target=(tuple(data["target"])
                    if isinstance(data.get("target"), (list, tuple))
                    and len(data["target"]) == 2 else None),
            line=(tuple(line[0]), tuple(line[1])) if line else None,
            auto=bool(data.get("auto", False)),
        )


class SegmentLayout:
    """Совместимый носитель описания сегментов (для UI)."""

    def __init__(self, segments):
        self.segments = segments


class VoltageLayout:
    """Совместимый носитель описания каналов (для UI)."""

    def __init__(self, channel_index):
        self.channel_index = channel_index


class ClassConfig:
    """Минимальная конфигурация класса боевой единицы."""

    def __init__(self):
        self.class_name = "military_unit"
        self.label = "Отделение"
        order_states = [
            "holding_defense", "aggressive_attack", "attack",
            "cautious_attack", "defense", "desperate_defense", "move",
            "rest", "forced_march", "withdrawal",
        ]
        self.segment_layout = SegmentLayout({
            "condition": (0, 2, ["Уничтожено", "Потрёпано",
                                 "Боеспособно", "Полная готовность"]),
            "order": (2, 5, order_states),
            "size": (5, 3, ["company", "battalion", "regiment",
                            "brigade", "division"]),
            "morale": (10, 3, ["", "", "", "", "", ""]),
            "discipline": (13, 3, ["", "", "", "", "", ""]),
            "supply": (16, 2, ["", "", "", ""]),
            "fatigue": (18, 2, ["", "", "", ""]),
            "profession": (20, 3, ["", "", "", "", "", ""]),
            "cohesion": (23, 3, ["", "", "", "", "", ""]),
            "initiative": (26, 2, ["", "", "", ""]),
            "health": (28, 3, ["", "", "", "", "", ""]),
        })
        self.voltage_layout = VoltageLayout({
            "U_manpower": 0,
            "U_casualties": 1,
            "U_supply": 2,
            "U_tanks": 3,
            "U_sp_guns": 4,
            "U_at_guns": 5,
            "U_artillery": 6,
            "U_mlrs": 7,
            "U_otrk": 8,
            "U_sam": 9,
            "U_experience_progress": 10,
        })


@dataclass
class OrderType:
    """Совместимая запись таблицы приказов."""

    id: str
    label: str
    raw: dict


class OrderTable:
    """Таблица приказов с атрибутом ``orders`` как в легаси."""

    def __init__(self, content):
        self.orders = list(content.order_types)
        self.id_to_index = {
            item.get("id"): i for i, item in enumerate(self.orders)
        }

    def index_of(self, order_id):
        for i, item in enumerate(self.orders):
            if item.get("id") == order_id:
                return i
        return 0

    def label_of(self, order_id):
        for item in self.orders:
            if item.get("id") == order_id:
                return item.get("label", order_id)
        return order_id or "—"


class CampaignState:
    """Состояние кампании поверх ``warfare.WarfareSimulation``."""

    def __init__(self, sim, player_side="red", content=None, map_name="valley_01"):
        self.sim = sim
        self.player_side = player_side
        self.content = content or Content()
        self.map_name = map_name
        self.player_gender = "male"
        self.commander_trait = None
        # Кампанийная роль и пресет. В снимок кладём только идентификаторы и
        # метаданные роли; полный пресет передаётся отдельно при сохранении,
        # чтобы не раздувать каждый снимок на сотни килобайт.
        self.campaign_preset = None
        self.campaign_preset_id = ""
        self.campaign_role = None
        self.campaign_role_id = ""
        self.player_faction_id = ""
        self.campaign_factions = {}
        self.campaign_organizations = {}
        self.campaign_automata = {}
        self.organization_runtimes = []
        self.event_log = []
        self.tick_events = []
        self.engagements = []
        self.class_configs = {3: ClassConfig()}
        self.supplies = {}
        self._event_cursor = 0
        self._initial_forces = {}
        self.logistics = LogisticsSystem(self)
        self.logistics_system = self.logistics
        self.engine = None
        # Планы сторон и роты, временно выведенные из автоплана ручным
        # приказом. Хранятся в состоянии, чтобы переживать save/load.
        self.auto_plans = {}
        self.plan_exempt = set()
        self.needs = NeedsSystem(self, self.supplies)
        for det in self.sim.all_detachments:
            self._remember_start(det)
        self.geometry = FrontGeometry(self)
        # Шесть пользовательских групп рот. Храним имена, а не индексы:
        # список отделений может меняться при выбытии подразделений.
        self.groups = {i: [] for i in range(1, 7)}

    # --- базовые представления ------------------------------------------
    def _remember_start(self, det):
        if not hasattr(det, "ui_order"):
            det.ui_order = (
                "holding_defense" if det.side == self.player_side
                else "attack"
            )
        if not hasattr(det, "ui_supply"):
            det.ui_supply = 0.82
        if det.name not in self._initial_forces:
            self._initial_forces[det.name] = min(
                34.0, 6.0 + 2.0 * len(getattr(det, "characters", []))
            )

    @property
    def units(self):
        for det in self.sim.all_detachments:
            self._remember_start(det)
        return list(self.sim.all_detachments)

    @property
    def count(self):
        return len(self.units)

    @property
    def player_idx(self):
        for i, det in enumerate(self.units):
            if det.side == self.player_side:
                return i
        return 0

    @property
    def class_ids(self):
        return [3] * self.count

    @property
    def factions(self):
        return [
            "player" if det.side == self.player_side else "enemy"
            for det in self.units
        ]

    @property
    def labels(self):
        return [det.name for det in self.units]

    @property
    def entity_ids(self):
        return [det.name for det in self.units]

    @property
    def tactical_ids(self):
        return []

    @property
    def parent_ids(self):
        return np.full(self.count, -1, dtype=int)

    @property
    def headings(self):
        return np.zeros(self.count, dtype=int)

    @property
    def coords(self):
        rows = []
        for det in self.units:
            x = int(24 + det.position[0] * 8.2)
            y = int(24 + det.position[1] * 8.6)
            rows.append((min(MAP_SIZE - 2, x), min(MAP_SIZE - 2, y)))
        return np.asarray(rows, dtype=float).reshape((-1, 2))

    @property
    def initial_manpower(self):
        return [
            self._initial_forces.get(det.name, 16.0) * 500.0
            for det in self.units
        ]

    @property
    def current_tick(self):
        return self.sim.turn

    @property
    def center(self):
        return (MAP_SIZE // 2, MAP_SIZE // 2)

    @property
    def height(self):
        return MAP_SIZE

    # --- доступ к отделениям --------------------------------------------
    def det_at(self, idx):
        units = self.units
        if 0 <= idx < len(units):
            return units[idx]
        return None

    def label_of(self, idx):
        det = self.det_at(idx)
        return det.name if det is not None else "?"

    def _start_force(self, det):
        self._remember_start(det)
        return self._initial_forces.get(det.name, 16.0)

    def sector_of(self, det):
        geometry = getattr(self, "geometry", None)
        if geometry is not None:
            return geometry.sector_of(det)
        return getattr(det, "sector", "front")

    def projected_force(self, det):
        """Сила роты с учётом проекции (фронт/фланг/тыл)."""
        geometry = getattr(self, "geometry", None)
        if geometry is not None:
            return geometry.projected_force(det)
        return max(0.0, float(getattr(det, "force", 0.0)))

    def casualty_fraction(self, idx):
        """Доля безвозвратных потерь отделения (0..1).

        Считается по накопленному ``Detachment.losses``, а не по текущей
        силе: сила может колебаться в бою, но понесённые потери не исчезают.
        """
        det = self.det_at(idx)
        if det is None:
            return 0.0
        start = max(1.0, self._start_force(det))
        losses = float(getattr(det, "losses", 0.0))
        return max(0.0, min(1.0, losses / start))

    def division_loss_percent(self):
        """Потери дивизии игрока в процентах (все боевые подразделения)."""
        total_start = 0.0
        total_losses = 0.0
        for idx, det in enumerate(self.units):
            if det.side != self.player_side:
                continue
            total_start += max(1.0, self._start_force(det))
            total_losses += max(0.0, float(getattr(det, "losses", 0.0)))
        if total_start <= 0.0:
            return 0.0
        return round(100.0 * min(1.0, total_losses / total_start), 2)

    # --- сегменты и каналы ----------------------------------------------
    def read_segment(self, idx, name):
        det = self.det_at(idx)
        if det is None:
            return 0
        if name == "condition":
            if det.broken or det.force <= 1:
                return 0
            ratio = det.force / max(1.0, self._start_force(det))
            if ratio < 0.35:
                return 1
            if ratio < 0.70:
                return 2
            return 3
        if name == "order":
            return self.order_index(det)
        if name == "size":
            force = det.force
            if force < 8:
                return 1
            if force < 16:
                return 2
            if force < 24:
                return 3
            if force < 30:
                return 4
            return 5
        if name == "morale":
            return max(0, min(5, int(det.morale / 20.0)))
        if name == "discipline":
            return max(0, min(5, int(det.discipline * 5)))
        if name == "supply":
            return max(0, min(3, int(self.read_voltage(idx, "U_supply") * 3)))
        if name == "fatigue":
            avg = sum(c.needs.get("fatigue", 0.0) for c in det.characters) / max(
                1, len(det.characters)
            )
            return max(0, min(3, int(avg * 4)))
        if name == "profession":
            return max(0, min(5, int(det.cohesion * 5)))
        if name == "cohesion":
            return max(0, min(5, int(det.cohesion * 5)))
        if name == "initiative":
            return max(0, min(3, int(det.aggression * 3)))
        if name == "health":
            ratio = det.force / max(1.0, self._start_force(det))
            return max(0, min(5, int(ratio * 5)))
        return 0

    def order_index(self, det):
        return self.engine.order_table.index_of(det.ui_order) if self.engine else 0

    def get_segment_label(self, idx, name):
        det = self.det_at(idx)
        if name == "order" and det is not None:
            if self.engine is not None:
                return self.engine.order_table.label_of(det.ui_order)
            return getattr(det, "ui_order", "—")
        value = self.read_segment(idx, name)
        cfg = self.class_configs[self.class_ids[idx]]
        segment = cfg.segment_layout.segments.get(name)
        if segment and len(segment) >= 3:
            states = segment[2]
            if 0 <= value < len(states):
                return states[value]
        return str(value)

    def set_segment(self, idx, name, value):
        det = self.det_at(idx)
        if det is None:
            return
        if name == "order":
            if isinstance(value, int):
                if self.engine is not None and 0 <= value < len(
                        self.engine.order_table.orders):
                    value = self.engine.order_table.orders[value].get("id", "attack")
                else:
                    value = "attack"
            if self.engine is not None:
                self.engine.assign_order(idx, str(value))
            else:
                det.ui_order = str(value)
        else:
            setattr(det, "ui_" + name, value)

    def read_voltage(self, idx, channel):
        det = self.det_at(idx)
        if det is None:
            return 0.0
        if channel == "U_manpower":
            force = min(float(det.force), self._start_force(det))
            return max(0.0, force * 500.0)
        if channel == "U_casualties":
            return self.casualty_fraction(idx)
        if channel == "U_supply":
            return float(getattr(det, "ui_supply", 0.82))
        if channel == "U_experience_progress":
            return min(1.0, 0.35 + 0.01 * self.sim.turn)
        return float(getattr(det, "ui_" + channel, 0.0))

    def add_voltage(self, idx, channel, delta):
        det = self.det_at(idx)
        if det is None:
            return
        if channel == "U_manpower":
            det.force = max(1.0, min(40.0, det.force + float(delta) / 500.0))
        elif channel == "U_casualties":
            det.force = max(1.0, det.force * (1.0 - float(delta)))
        elif channel == "U_supply":
            det.ui_supply = max(0.0, min(1.5,
                                          getattr(det, "ui_supply", 0.82)
                                          + float(delta)))
        else:
            det.morale = max(0.0, min(100.0, det.morale + float(delta) * 10.0))

    # --- события ---------------------------------------------------------
    def log_event(self, idx, message):
        unit_id = self.entity_ids[idx] if 0 <= idx < self.count else None
        item = {
            "tick": self.sim.turn,
            "entity_id": unit_id,
            "message": str(message),
            "kind": "ui",
        }
        self.event_log.append(item)
        self.tick_events.append(item)

    def begin_tick(self):
        self.tick_events = []

    def sync_events(self):
        events = getattr(self.sim, "events", [])
        while self._event_cursor < len(events):
            raw = events[self._event_cursor]
            self._event_cursor += 1
            actor = raw.get("actor")
            unit_id = actor if actor in self.entity_ids else None
            item = {
                "tick": raw.get("turn", self.sim.turn),
                "entity_id": unit_id,
                "message": raw.get("text", ""),
                "kind": raw.get("kind", "log"),
                "side": raw.get("side"),
            }
            self.event_log.append(item)
            self.tick_events.append(item)

    # --- сохранение/восстановление --------------------------------------
    def to_snapshot(self):
        dets = []
        for det in self.units:
            dets.append({
                "name": det.name,
                "side": det.side,
                "force": det.force,
                "morale": det.morale,
                "position": list(det.position),
                "sector": self.sector_of(det),
                "role": det.role,
                "doctrine": det.doctrine,
                "ui_order": getattr(det, "ui_order", "holding_defense"),
                "ui_supply": getattr(det, "ui_supply", 0.82),
                "ui_fortification": getattr(det, "ui_fortification", 0.0),
                "losses": float(getattr(det, "losses", 0.0)),
                "retreating": det.retreating,
                "panicked": det.panicked,
                "broken": det.broken,
                "surrendered": bool(getattr(det, "surrendered", False)),
                "needs": [dict(c.needs) for c in det.characters],
            })
        return {
            "seed": self.sim.seed,
            "turn": self.sim.turn,
            "max_turns": self.sim.max_turns,
            "player_side": self.player_side,
            "player_gender": self.player_gender,
            "commander_trait": self.commander_trait,
            "campaign_preset_id": self.campaign_preset_id,
            "campaign_role_id": self.campaign_role_id,
            "campaign_role": self.campaign_role,
            "player_faction_id": self.player_faction_id,
            "detachments": dets,
            "event_log": self.event_log[-250:],
            "supplies": dict(getattr(self, "supplies", {})),
            "needs": (self.needs.get_save_snapshot()
                      if getattr(self, "needs", None) else {}),
            "geometry": (self.geometry.snapshot()
                         if getattr(self, "geometry", None) else {}),
            "logistics": (self.logistics.get_save_snapshot()
                          if getattr(self, "logistics", None) else {}),
            "groups": {
                str(key): list(names)
                for key, names in getattr(self, "groups", {}).items()
            },
            "auto_plans": {
                side: plan.to_dict()
                for side, plan in getattr(self, "auto_plans", {}).items()
                if isinstance(plan, ArmyPlan)
            },
            "plan_exempt": sorted(getattr(self, "plan_exempt", set())),
        }

    def apply_snapshot(self, snapshot):
        if not snapshot:
            return
        self.player_side = snapshot.get("player_side", self.player_side)
        self.player_gender = snapshot.get("player_gender", self.player_gender)
        self.commander_trait = snapshot.get(
            "commander_trait", self.commander_trait
        )
        self.campaign_preset_id = snapshot.get(
            "campaign_preset_id", self.campaign_preset_id
        )
        self.campaign_role_id = snapshot.get(
            "campaign_role_id", self.campaign_role_id
        )
        self.campaign_role = snapshot.get(
            "campaign_role", self.campaign_role
        )
        self.player_faction_id = snapshot.get(
            "player_faction_id", self.player_faction_id
        )
        if getattr(self, "needs", None) is not None:
            self.needs.set_commander_trait(self.commander_trait)
        self.sim.turn = int(snapshot.get("turn", self.sim.turn))
        by_name = {det.name: det for det in self.units}
        for item in snapshot.get("detachments", []):
            det = by_name.get(item.get("name"))
            if det is None:
                continue
            det.force = float(item.get("force", det.force))
            det.morale = float(item.get("morale", det.morale))
            det.position = tuple(item.get("position", det.position))
            # Поле ``sector`` в старых снимках оставлено для совместимости,
            # но больше не восстанавливается как истина: проекция производна
            # от позиции и фронта и будет пересчитана ниже.
            det.ui_order = item.get("ui_order", getattr(det, "ui_order",
                                                        "holding_defense"))
            det.ui_supply = float(item.get("ui_supply",
                                          getattr(det, "ui_supply", 0.82)))
            det.ui_fortification = float(item.get(
                "ui_fortification", getattr(det, "ui_fortification", 0.0)))
            det.losses = float(item.get("losses", getattr(det, "losses", 0.0)))
            det.retreating = bool(item.get("retreating", det.retreating))
            det.panicked = bool(item.get("panicked", det.panicked))
            det.broken = bool(item.get("broken", det.broken))
            det.surrendered = bool(item.get(
                "surrendered", getattr(det, "surrendered", False)
            ))
            for character, values in zip(
                    det.characters, item.get("needs", [])):
                if not isinstance(values, dict):
                    continue
                for need, value in values.items():
                    if need in character.needs:
                        character.needs[need] = max(
                            0.0, min(1.0, float(value))
                        )
            det.refresh_psychology()
        self.event_log = list(snapshot.get("event_log", []))[-250:]
        self.tick_events = []
        self._event_cursor = len(getattr(self.sim, "events", []))
        if getattr(self, "needs", None):
            needs_snapshot = snapshot.get("needs")
            if not needs_snapshot and "supplies" in snapshot:
                # Совместимость с промежуточными сохранениями, где ресурсы
                # лежали только на верхнем уровне.
                needs_snapshot = {"supplies": snapshot.get("supplies") or {}}
            # Старые сохранения без ресурсов сохраняют стартовые значения.
            if needs_snapshot:
                self.needs.load_from_snapshot(needs_snapshot)
        if getattr(self, "logistics", None) is not None and snapshot.get(
                "logistics"):
            self.logistics.load_from_snapshot(snapshot.get("logistics"))
        if getattr(self, "geometry", None) is not None:
            self.geometry.load_snapshot(snapshot.get("geometry"))
            # Загрузка могла не содержать геометрию (старое сохранение), но
            # позиции уже восстановлены — проекции всё равно производны.
            self.geometry.refresh_sectors()
            self.geometry.recompute()
        groups = snapshot.get("groups")
        if isinstance(groups, dict):
            loaded = {i: [] for i in range(1, 7)}
            alive = {
                det.name for det in self.units
                if not getattr(det, "broken", False)
            }
            for key, names in groups.items():
                try:
                    number = int(key)
                except (TypeError, ValueError):
                    continue
                if number not in loaded or not isinstance(names, list):
                    continue
                loaded[number] = [
                    str(name) for name in names if str(name) in alive
                ]
            self.groups = loaded
        plans = snapshot.get("auto_plans")
        if isinstance(plans, dict):
            self.auto_plans = {
                str(side): ArmyPlan.from_dict(data)
                for side, data in plans.items()
                if isinstance(data, dict)
            }
        alive_names = {
            det.name for det in self.units
            if not getattr(det, "broken", False)
        }
        self.plan_exempt = {
            str(name) for name in snapshot.get("plan_exempt", [])
            if str(name) in alive_names
        }


class CampaignEngine:
    """Минимальный движок для UI: такт, приказы и цели перемещения."""

    def __init__(self, state):
        self.state = state
        state.engine = self
        self.tick_count = state.sim.turn
        self.order_table = OrderTable(state.content)
        self.rng = state.sim.rng
        self.engagements = []
        self.logistics = state.logistics
        state.logistics_system = self.logistics
        self.time_system = None
        self._targets = {}
        self._ui_orders = {}
        # Явно выбранная цель для сосредоточенного огня: имя отделения ->
        # имя противника. В отличие от обычной «атаки ближайшего», эта цель
        # сохраняется, пока жива, и передаётся в сопоставление пар боя.
        self._focus_targets = {}
        self.state.sim.focus_targets = {}
        # Оперативные цели автоплана. Обычные ``_targets`` могут быть
        # ручными; отдельный словарь нужен, чтобы отличить цель плана от
        # приказа игрока и не перетирать ручной приказ каждый такт.
        self._plan_goals = {}
        self._plan_orders = {}
        # Продавливание фронта: не больше одного сдвига на сторону за
        # несколько тактов, иначе автоплан «пролетает» карту за полчаса.
        self._push_tick = {}
        self._push_budget = {}
        # Один войсковой такт = 5 игровых минут. Часы при этом идут по
        # минутам; интервал настраивается временем кампании.
        self.combat_seconds = 300
        self._ensure_default_plans()

    def tick(self, seconds=None):
        state = self.state
        if seconds is None:
            seconds = self.combat_seconds
        state.begin_tick()
        self._sync_focus_targets()
        self._advance_ai()
        pairs = state.sim._pair_engagements()
        self.engagements = [
            {"attacker": a.name, "defender": b.name} for a, b in pairs
        ]
        self._advance_targets()
        force_before = {
            det.name: det.force for det in state.sim.all_detachments
        }
        for det in state.sim.all_detachments:
            det.needs_tick_seconds = seconds
        state.sim.tick()
        # Ядро уже потратило силу на случайный обмен огнём. Кампанийный слой
        # восстанавливает её к началу такта и начисляет потери по историческим
        # суточным нормам через ``FrontGeometry``. Так бой не уничтожает
        # дивизию за два часа и не зависит от случайной силы отдельного удара.
        for det in state.sim.all_detachments:
            before = force_before.get(det.name)
            cap = float(getattr(det, "start_force", det.force))
            if before is None:
                # Резерв/подкрепление впервые появилось в этом такте. Его
                # стартовая сила — штатная, а не «прирост» относительно нуля:
                # иначе первый же такт после выхода даёт фиктивные потери и
                # мгновенно приближает поражение по потерям дивизии.
                det.force = min(cap, max(1.0, float(det.force)))
                continue
            det.force = min(cap, max(1.0, float(before)))

        engaged_sides = {
            item.get("attacker") for item in self.engagements
        }
        # В ``engagements`` лежат имена, а не стороны: восстановим стороны по
        # актуальному списку отделений.
        side_by_name = {
            det.name: det.side for det in state.sim.all_detachments
        }
        engaged_sides = {
            side_by_name[name] for name in engaged_sides
            if name in side_by_name
        }
        engaged_sides |= {
            side_by_name.get(item.get("defender"))
            for item in self.engagements
        }
        engaged_sides.discard(None)
        geometry = getattr(state, "geometry", None)
        if geometry is not None:
            geometry.update(engaged_sides=engaged_sides,
                            tick=state.sim.turn)
            geometry.apply_attrition(force_before, engaged_sides)
        else:
            # Совместимость с синтетическими состояниями без геометрии.
            for det in state.sim.all_detachments:
                before = force_before.get(det.name)
                if before is None:
                    continue
                cap = float(getattr(det, "start_force", det.force))
                det.force = min(cap, det.force)
                det.losses = min(
                    max(0.0, cap - 1.0),
                    det.losses + max(0.0, before - det.force),
                )
        self.tick_count = state.sim.turn
        if getattr(state, "needs", None) is not None:
            engaged = {
                item.get("attacker") for item in self.engagements
            } | {
                item.get("defender") for item in self.engagements
            }
            state.needs.on_tick(seconds, engaged)
        if getattr(state, "logistics", None) is not None:
            engaged = {
                item.get("attacker") for item in self.engagements
            } | {
                item.get("defender") for item in self.engagements
            }
            state.logistics.on_tick(seconds, engaged)
        state.sync_events()
        if state.sim.finished:
            state.log_event(
                state.player_idx,
                "Итог операции: %s" % (state.sim.winner or "—"),
            )
        return not state.sim.finished

    def _step_toward(self, det, target, steps=1):
        x, y = det.position
        tx, ty = target
        for _ in range(max(1, int(steps))):
            if (x, y) == (tx, ty):
                break
            if x != tx:
                x += 1 if tx > x else -1
            elif y != ty:
                y += 1 if ty > y else -1
        det.position = (
            max(0, min(CELL_SIZE, x)),
            max(0, min(CELL_SIZE, y)),
        )
        return det.position

    def _nearest_enemy(self, det):
        enemies = [
            other for other in self.state.units
            if other.side != det.side and not getattr(other, "broken", False)
        ]
        if not enemies:
            return None
        return min(enemies, key=lambda other: (
            _distance(det.position, other.position), other.name
        ))

    def _enemy_by_name(self, name):
        if not name:
            return None
        return next((
            det for det in self.state.units
            if det.name == name and not getattr(det, "broken", False)
        ), None)

    def _sync_focus_targets(self):
        """Передать UI-цели в боевое ядро для сосредоточенного огня."""
        self.state.sim.focus_targets = dict(self._focus_targets)

    def set_focus_target(self, idx, enemy):
        """Явно назначить противника целью отделения.

        ``enemy`` может быть индексом, именем или объектом отделения.
        Возвращает True, если цель принята.
        """
        det = self.state.det_at(idx)
        if det is None:
            return False
        if isinstance(enemy, int):
            target = self.state.det_at(enemy)
        elif isinstance(enemy, str):
            target = self._enemy_by_name(enemy)
        else:
            target = enemy
        if (target is None or target.side == det.side or
                getattr(target, "broken", False)):
            return False
        self._mark_plan_exempt(det)
        self._focus_targets[det.name] = target.name
        self._targets[det.name] = tuple(target.position)
        self._sync_focus_targets()
        return True

    def clear_focus_target(self, idx_or_name=None):
        """Снять явную цель (для одного отделения или для всех)."""
        if idx_or_name is None:
            self._focus_targets.clear()
            self._sync_focus_targets()
            return
        if isinstance(idx_or_name, int):
            det = self.state.det_at(idx_or_name)
            name = det.name if det is not None else str(idx_or_name)
        elif hasattr(idx_or_name, "name"):
            name = idx_or_name.name
        else:
            name = str(idx_or_name)
        self._focus_targets.pop(name, None)
        self._sync_focus_targets()

    def focus_target_name(self, idx_or_name):
        if isinstance(idx_or_name, int):
            det = self.state.det_at(idx_or_name)
            name = det.name if det is not None else str(idx_or_name)
        elif hasattr(idx_or_name, "name"):
            name = idx_or_name.name
        else:
            name = str(idx_or_name)
        return self._focus_targets.get(name)

    # --- автоплан армии --------------------------------------------------
    def plan_for(self, side=None):
        """Вернуть план стороны (по умолчанию — игрока)."""
        side = side or self.state.player_side
        plan = getattr(self.state, "auto_plans", {}).get(side)
        if not isinstance(plan, ArmyPlan):
            plan = ArmyPlan()
            self.state.auto_plans[side] = plan
        return plan

    def _other_side(self, side):
        return "blue" if side == "red" else "red"

    def _plan_units(self, side, include_exempt=False):
        exempt = getattr(self.state, "plan_exempt", set())
        return [
            det for det in self.state.units
            if det.side == side
            and not getattr(det, "broken", False)
            and float(getattr(det, "force", 0.0)) > 1.0
            and (include_exempt or det.name not in exempt)
        ]

    def _center_of(self, units):
        if not units:
            return None
        return (
            sum(float(det.position[0]) for det in units) / len(units),
            sum(float(det.position[1]) for det in units) / len(units),
        )

    def _opponent_center(self, side):
        return self._center_of(self._plan_units(self._other_side(side),
                                                include_exempt=True))

    def _advance_target(self, side, axis, center=None):
        """Начальная цель наступления — центр противостоящей стороны.

        Цель фиксируется, а не пересчитывается на центр врага каждый такт.
        Иначе после прохода армий друг друга ось разворачивалась на 180°,
        и роты бесконечно дёргались поперёк фронта.
        """
        units = self._plan_units(side, include_exempt=True)
        center = center or self._center_of(units)
        enemy_center = self._opponent_center(side)
        if enemy_center is not None:
            return _clamp_cell(enemy_center)
        if center is not None:
            return _clamp_cell((
                center[0] + axis[0] * PLAN_ADVANCE_DISTANCE,
                center[1] + axis[1] * PLAN_ADVANCE_DISTANCE,
            ))
        return _clamp_cell((CELL_SIZE // 2, CELL_SIZE // 2))

    def _facing_of(self, side):
        geometry = getattr(self.state, "geometry", None)
        if geometry is not None:
            try:
                return _unit_vector(geometry.facing_of(side))
            except Exception:                      # noqa: BLE001
                pass
        enemy = self._opponent_center(side)
        own = self._center_of(self._plan_units(side, include_exempt=True))
        if enemy is not None and own is not None:
            return _unit_vector((enemy[0] - own[0], enemy[1] - own[1]))
        return (1.0, 0.0) if side == "red" else (-1.0, 0.0)

    def _line_width(self, units):
        if len(units) < 2:
            return PLAN_LANE_WIDTH_MIN
        xs = [float(det.position[0]) for det in units]
        ys = [float(det.position[1]) for det in units]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        return max(PLAN_LANE_WIDTH_MIN,
                   min(PLAN_LANE_WIDTH_MAX, span + 2.0))

    def _default_hold_line(self, units, side=None):
        """Рубеж по текущему построению, перпендикулярно фронту.

        Если армия уже стоит линией, план не заставляет её сдвигаться:
        каждый сохраняет своё место, но получает явную цель «держать
        рубеж». После выбора точки на карте рубеж переносится туда.
        """
        center = self._center_of(units)
        if center is None:
            return ((0, 0), (CELL_SIZE, 0))
        facing = self._facing_of(side or self.state.player_side)
        right = (-facing[1], facing[0])
        half = self._line_width(units) / 2.0
        return (
            _clamp_cell((center[0] - right[0] * half,
                         center[1] - right[1] * half)),
            _clamp_cell((center[0] + right[0] * half,
                         center[1] + right[1] * half)),
        )

    def _line_through(self, target, units, side=None):
        """Построить рубеж через выбранную точку."""
        facing = self._facing_of(side or self.state.player_side)
        right = (-facing[1], facing[0])
        half = self._line_width(units) / 2.0
        cx, cy = float(target[0]), float(target[1])
        return (
            _clamp_cell((cx - right[0] * half, cy - right[1] * half)),
            _clamp_cell((cx + right[0] * half, cy + right[1] * half)),
        )

    def _clear_plan_goals(self, side):
        names = {
            det.name for det in self.state.units if det.side == side
        }
        for name in names:
            if name in self._plan_goals:
                self._plan_goals.pop(name, None)
                self._targets.pop(name, None)

    def _deactivate_ui_orders(self, side):
        """Погасить прежние ручные приказы при включении плана.

        Иначе армейский приказ суммировался бы со старыми сигналами рот,
        хотя план уже снова охватил всю сторону.
        """
        for idx, order in list(self._ui_orders.items()):
            det = self.state.det_at(idx)
            if det is None or det.side != side:
                continue
            order.state["active"] = False
            self._ui_orders.pop(idx, None)
            self._focus_targets.pop(det.name, None)
        self._sync_focus_targets()

    def _apply_plan_order(self, side, plan):
        """Выдать широкий пассивный приказ, соответствующий плану."""
        old = self._plan_orders.pop(side, None)
        if old is not None:
            old.state["active"] = False
        if not plan.active:
            return
        units = self._plan_units(side)
        if not units:
            return
        if plan.mode == "hold":
            signal = W.OrderSignal(
                aggression=0.02, discipline=0.16, morale=0.9,
                retreat_allowed=True, label="автоплан: оборона",
            )
        else:
            signal = W.OrderSignal(
                aggression=0.18, discipline=0.05, morale=0.9,
                retreat_allowed=True, label="автоплан: наступление",
            )
        order = W.Order(
            "Автоплан: %s" % plan.label, signal, duration=5000,
            targets=units, side=side,
        )
        self.state.sim.issue_order(order)
        self._plan_orders[side] = order

    def set_auto_plan(self, mode, target=None, line=None, side=None,
                      axis=None, auto=False, silent=False,
                      keep_exemptions=False):
        """Включить армейский план.

        Args:
            mode: ``hold`` (занять рубеж) или ``advance`` (наступать).
            target: клетка сетки 24×24; для обороны задаёт точку рубежа,
                для наступления — направление/цель.
            line: явные две точки рубежа (приоритетнее ``target``).
            side: сторона; по умолчанию игрок.
            axis: явная ось наступления, если цель не задана.
            auto: план выставлен ИИ, а не игроком.
            silent: не писать событие в журнал (инициализация мира).
            keep_exemptions: не снимать ручные исключения (перенос
                рубежа/направления без повторного охвата всей армии).
        """
        side = side or self.state.player_side
        mode = str(mode or "off").lower()
        if mode == "attack":
            mode = "advance"
        if mode not in PLAN_MODES:
            return False
        if mode == "off":
            return self.clear_auto_plan(side, silent=silent)

        units = self._plan_units(side, include_exempt=True)
        if not units:
            return False
        center = self._center_of(units)
        facing = self._facing_of(side)
        # Новый приказ игрока снимает прежние ручные исключения: план снова
        # охватывает всю армию. Перенос рубежа/направления (Shift+ПКМ)
        # исключения сохраняет.
        if not keep_exemptions:
            self.state.plan_exempt = {
                name for name in getattr(self.state, "plan_exempt", set())
                if next((det.side for det in self.state.units
                         if det.name == name), None) != side
            }
            self._deactivate_ui_orders(side)
        self._clear_plan_goals(side)

        if target is not None:
            target = _clamp_cell(target)
        if mode == "hold":
            if line is not None:
                endpoints = line
            elif target is not None:
                endpoints = self._line_through(target, units, side)
            else:
                endpoints = self._default_hold_line(units, side)
            plan = ArmyPlan(
                mode="hold", target=target, line=endpoints,
                axis=facing, auto=bool(auto),
            )
        else:
            if target is not None and center is not None:
                chosen_axis = _unit_vector(
                    (target[0] - center[0], target[1] - center[1]),
                    fallback=facing,
                )
            elif axis is not None:
                chosen_axis = _unit_vector(axis, fallback=facing)
            else:
                enemy_center = self._opponent_center(side)
                chosen_axis = (
                    _unit_vector(
                        (enemy_center[0] - center[0],
                         enemy_center[1] - center[1]),
                        fallback=facing,
                    )
                    if enemy_center is not None and center is not None
                    else facing
                )
            if target is None:
                target = self._advance_target(side, chosen_axis, center)
            plan = ArmyPlan(
                mode="advance", target=target, axis=chosen_axis,
                auto=bool(auto),
            )

        self.state.auto_plans[side] = plan
        self._apply_plan_order(side, plan)
        self._refresh_plan_for_side(side)
        if not silent:
            where = ""
            if plan.mode == "advance" and plan.target is not None:
                where = " · направление %d:%d" % plan.target
            elif plan.mode == "hold" and plan.line is not None:
                where = " · рубеж %d:%d–%d:%d" % (
                    plan.line[0][0], plan.line[0][1],
                    plan.line[1][0], plan.line[1][1],
                )
            self.state.log_event(
                self.state.player_idx,
                "Автоплан: %s%s" % (plan.label, where),
            )
        return True

    def clear_auto_plan(self, side=None, silent=False):
        """Снять автоплан и остановить его оперативные цели."""
        side = side or self.state.player_side
        plan = self.plan_for(side)
        was_active = plan.active
        old = self._plan_orders.pop(side, None)
        if old is not None:
            old.state["active"] = False
        self._clear_plan_goals(side)
        exempt = getattr(self.state, "plan_exempt", set())
        for det in self._plan_units(side, include_exempt=True):
            if det.name in exempt:
                continue
            self._targets.pop(det.name, None)
            if det.ui_order in (
                    "aggressive_attack", "attack", "cautious_attack",
                    "forced_march"):
                det.ui_order = "holding_defense"
        self.state.auto_plans[side] = ArmyPlan(
            mode="off", axis=self._facing_of(side)
        )
        self.state.plan_exempt = {
            name for name in exempt
            if next((det.side for det in self.state.units
                     if det.name == name), None) != side
        }
        if was_active and not silent:
            self.state.log_event(
                self.state.player_idx, "Автоплан снят"
            )
        return True

    def _refresh_plan_for_side(self, side):
        plan = self.plan_for(side)
        if not plan.active:
            return
        units = self._plan_units(side)
        if not units:
            return
        center = self._center_of(units)
        if center is None:
            return
        if plan.mode == "hold":
            if plan.line is None:
                plan.line = self._default_hold_line(units, side)
            self._assign_hold_goals(side, plan, units, center)
            return
        self._assign_advance_goals(side, plan, units, center)

    def _assign_hold_goals(self, side, plan, units, center):
        first, second = plan.line
        vx = float(second[0] - first[0])
        vy = float(second[1] - first[1])
        length = (vx * vx + vy * vy) ** 0.5
        if length < 1e-6:
            right = (-plan.axis[1], plan.axis[0])
            half = self._line_width(units) / 2.0
            first = _clamp_cell((center[0] - right[0] * half,
                                 center[1] - right[1] * half))
            second = _clamp_cell((center[0] + right[0] * half,
                                  center[1] + right[1] * half))
            vx = float(second[0] - first[0])
            vy = float(second[1] - first[1])
            length = max(1e-6, (vx * vx + vy * vy) ** 0.5)
        ux, uy = vx / length, vy / length
        line_center = (
            (float(first[0]) + float(second[0])) / 2.0,
            (float(first[1]) + float(second[1])) / 2.0,
        )
        # Каждая рота сохраняет своё место вдоль рубежа: это не перестроение
        # в одну точку, а именно линия с интервалами.
        for det in units:
            lateral = ((det.position[0] - center[0]) * ux +
                       (det.position[1] - center[1]) * uy)
            lateral = max(-length / 2.0, min(length / 2.0, lateral))
            goal = _clamp_cell((
                line_center[0] + ux * lateral,
                line_center[1] + uy * lateral,
            ))
            det.ui_order = "holding_defense"
            # Цель хранится даже при совпадении с текущей клеткой: она
            # служит якорем для манёвра в соприкосновении.
            self._plan_goals[det.name] = goal
            self._targets[det.name] = goal

    def _assign_advance_goals(self, side, plan, units, center):
        # Ось наступления фиксируется при выдаче плана. Раньше она
        # пересчитывалась каждый такт «на центр врага», и как только армии
        # проходили друг друга, вектор разворачивался на 180° — роты
        # дёргались поперёк фронта, не меняя общей линии.
        axis = plan.axis
        if plan.target is None:
            # Совместимость со старыми снимками, где цель ещё не была
            # материализована. Новая цель тоже фиксируется.
            plan.target = self._advance_target(side, axis, center)
        goal_center = (float(plan.target[0]), float(plan.target[1]))
        right = (-axis[1], axis[0])
        width = self._line_width(units)
        for det in units:
            lateral = ((det.position[0] - center[0]) * right[0] +
                       (det.position[1] - center[1]) * right[1])
            lateral = max(-width / 2.0, min(width / 2.0, lateral))
            goal = _clamp_cell((
                goal_center[0] + right[0] * lateral,
                goal_center[1] + right[1] * lateral,
            ))
            det.ui_order = "attack"
            # Даже совпадающая с текущей клеткой цель остаётся якорем:
            # в соприкосновении от неё считается боковой манёвр.
            self._plan_goals[det.name] = goal
            self._targets[det.name] = goal

    def _refresh_auto_plan_goals(self):
        for side in (self.state.player_side,
                     self._other_side(self.state.player_side)):
            self._refresh_plan_for_side(side)

    def _mark_plan_exempt(self, det):
        """Ручной приказ роте временно выводит её из армейского плана."""
        if det is None:
            return
        plan = self.plan_for(det.side)
        if not plan.active:
            return
        self.state.plan_exempt.add(det.name)
        goal = self._plan_goals.pop(det.name, None)
        if goal is not None and self._targets.get(det.name) == goal:
            self._targets.pop(det.name, None)

    def plan_status_text(self, side=None):
        """Короткая строка для панели приказов."""
        side = side or self.state.player_side
        plan = self.plan_for(side)
        if not plan.active:
            return "не включён"
        exempt = {
            name for name in getattr(self.state, "plan_exempt", set())
        }
        total = len(self._plan_units(side, include_exempt=True))
        manual = len([
            det for det in self._plan_units(side, include_exempt=True)
            if det.name in exempt
        ])
        if plan.mode == "hold":
            where = "рубеж"
            if plan.line is not None:
                where = "рубеж %d:%d–%d:%d" % (
                    plan.line[0][0], plan.line[0][1],
                    plan.line[1][0], plan.line[1][1],
                )
        else:
            where = "к противнику"
            if plan.target is not None:
                where = "цель %d:%d" % plan.target
        suffix = ""
        if manual:
            suffix = " · ручных %d/%d" % (manual, total)
        return "%s · %s%s" % (plan.label.capitalize(), where, suffix)

    def _ensure_default_plans(self):
        """Загрузить планы из снимка или включить наступление ИИ."""
        plans = getattr(self.state, "auto_plans", None)
        if not isinstance(plans, dict):
            plans = {}
            self.state.auto_plans = plans
        player = self.state.player_side
        enemy = self._other_side(player)
        if enemy not in plans:
            enemy_axis = self._facing_of(enemy)
            plans[enemy] = ArmyPlan(
                mode="advance", axis=enemy_axis,
                target=self._advance_target(enemy, enemy_axis),
                auto=True,
            )
        if player not in plans:
            plans[player] = ArmyPlan(mode="off")
        # У ИИ нет кнопки, поэтому его план должен быть активен с первого
        # такта. Загруженный активный план игрока тоже нужно снова связать
        # с пассивным приказом: снимок хранит план, но не список приказов.
        for side, plan in plans.items():
            if isinstance(plan, ArmyPlan) and plan.active:
                self._apply_plan_order(side, plan)

    def _step_with_avoidance(self, det, target, blocked, steps=1):
        """Шаг к цели, не заходя на занятые противником клетки.

        Автоплан ведёт роту в глубину, поэтому прямая линия к цели может
        проходить через чужой жетон. В этом случае выбирается боковой
        вариант с минимальным расстоянием до цели — это и есть манёвр
        вдоль фронта, а не «прошивание» строя насквозь.
        """
        blocked = set(blocked or ())
        for _ in range(max(1, int(steps))):
            if tuple(det.position) == tuple(target):
                break
            x, y = det.position
            tx, ty = target
            candidates = [(x + 1, y), (x - 1, y),
                          (x, y + 1), (x, y - 1)]
            # Сначала прямой шаг, затем боковые — но только если они не
            # отдаляют от цели. Иначе рота у занятой клетки противника
            # начинает ходить вперёд-назад на одном месте.
            candidates.sort(key=lambda cell: (
                _distance(cell, target), 0 if cell[1] == y else 1,
            ))
            current_distance = _distance(det.position, target)
            chosen = None
            for cell in candidates:
                cell = (max(0, min(CELL_SIZE, cell[0])),
                        max(0, min(CELL_SIZE, cell[1])))
                if cell in blocked:
                    continue
                if cell == tuple(det.position):
                    continue
                if _distance(cell, target) > current_distance:
                    continue
                chosen = cell
                break
            if chosen is None:
                break
            det.position = chosen
            if tuple(det.position) == tuple(target):
                break
        return det.position

    @staticmethod
    def _point_to_segment_distance(point, first, second):
        px, py = float(point[0]), float(point[1])
        ax, ay = float(first[0]), float(first[1])
        bx, by = float(second[0]), float(second[1])
        vx, vy = bx - ax, by - ay
        length_sq = vx * vx + vy * vy
        if length_sq < 1e-9:
            return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) /
                          length_sq))
        cx, cy = ax + vx * t, ay + vy * t
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    def _is_entrenched(self, det):
        plan = self.plan_for(det.side)
        if plan.mode != "hold" or plan.line is None:
            return False
        return self._point_to_segment_distance(
            det.position, plan.line[0], plan.line[1]
        ) <= 2.0

    def _nearest_forward_enemy(self, det, axis, max_distance=None):
        """Ближайший противник в передней полусфере плана."""
        if max_distance is None:
            radius = getattr(self.state.sim, "engage_range", 3) or 3
            max_distance = max(4, int(radius) + 2)
        forward = []
        for other in self.state.units:
            if other.side == det.side or getattr(other, "broken", False):
                continue
            dx = other.position[0] - det.position[0]
            dy = other.position[1] - det.position[1]
            if dx * axis[0] + dy * axis[1] < -1.0:
                continue
            distance = _distance(det.position, other.position)
            if distance <= max_distance:
                forward.append((distance, other))
        if not forward:
            return None
        return min(forward, key=lambda item: (item[0], item[1].name))[1]

    def _contact_maneuver(self, det, goal, axis):
        """Движение в соприкосновении: давление или обход.

        Если рота сильнее локальной группы врага, она продавливает цель
        плана. Если слабее — смещается вдоль фронта, ищет стык и не стоит
        вечно на одной и той же дистанции. Это ключевое отличие от старого
        поведения, где обе стороны замирали на ``engage_range``.
        """
        radius = getattr(self.state.sim, "engage_range", 3) or 3
        radius = max(1, int(radius))
        # Если рота уже продвинулась за оперативную цель, старая точка
        # осталась позади. Якорем становится текущий фронт, иначе манёвр
        # начинает оттягивать роту назад и она дёргается на одной клетке.
        if ((det.position[0] - goal[0]) * axis[0] +
                (det.position[1] - goal[1]) * axis[1]) > 0:
            goal = tuple(det.position)
        opponents = [
            other for other in self.state.units
            if other.side != det.side
            and not getattr(other, "broken", False)
            and other.force > 1
            and _distance(det.position, other.position) <= radius + 1
            and (
                (other.position[0] - det.position[0]) * axis[0] +
                (other.position[1] - det.position[1]) * axis[1]
            ) >= -1.0
        ]
        blocked = {
            tuple(other.position) for other in self.state.units
            if other.side != det.side and not getattr(other, "broken", False)
        }
        if not opponents:
            # Впереди свободно — идём к оперативной цели плана.
            self._step_with_avoidance(det, goal, blocked, steps=1)
            return
        # В соприкосновении движение становится прерывистым: ровно на
        # маневренном такте, а не каждый войсковой такт. Иначе весь фронт
        # мелко дрожит, хотя общая линия не меняется.
        index = next((
            i for i, other in enumerate(self.state.units)
            if other is det
        ), 0)
        if (self.tick_count + index) % 2 != 0:
            return
        allies = [
            other for other in self.state.units
            if other.side == det.side and other is not det
            and not getattr(other, "broken", False)
            and other.force > 1
            and _distance(det.position, other.position) <= radius + 1
        ]
        own_force = float(det.force) + sum(
            float(other.force) for other in allies
        )
        enemy_force = sum(float(other.force) for other in opponents)
        right = (-axis[1], axis[0])
        # Сторона обхода постоянна для роты: иначе подразделение дёргается
        # влево-вправо на одном месте вместо того, чтобы искать стык.
        sign = 1.0 if index % 2 == 0 else -1.0
        nearest = min(
            opponents,
            key=lambda other: (
                _distance(det.position, other.position), other.name
            ),
        )
        required = 1.15
        if self.plan_for(nearest.side).mode == "hold":
            required = 2.2 if self._is_entrenched(nearest) else 1.7
        if own_force >= enemy_force * required:
            # Локальное превосходство: сначала сближение, затем продавливание
            # передней клетки. Противник отходит на шаг, атакующий занимает
            # его место — линия фронта реально смещается, а не дрожит.
            if _distance(det.position, nearest.position) > 1:
                self._step_with_avoidance(
                    det, tuple(nearest.position), blocked, steps=1
                )
                return
            if (self._push_budget.get(det.side, 0) > 0 and
                    self.tick_count -
                    self._push_tick.get(det.side, -999) >= 3):
                sx = int(round(axis[0]))
                sy = int(round(axis[1]))
                if sx == 0 and sy == 0:
                    sx = 1 if axis[0] >= 0 else -1
                old_cell = tuple(nearest.position)
                push_cell = (old_cell[0] + sx, old_cell[1] + sy)
                push_cell = (max(0, min(CELL_SIZE, push_cell[0])),
                             max(0, min(CELL_SIZE, push_cell[1])))
                occupied = {
                    tuple(other.position) for other in self.state.units
                    if other is not nearest
                }
                if (push_cell != old_cell and
                        push_cell not in occupied):
                    nearest.position = push_cell
                    det.position = old_cell
                    self._push_tick[det.side] = self.tick_count
                    self._push_budget[det.side] -= 1
                    return
            target = tuple(nearest.position)
            self._step_with_avoidance(det, target, blocked, steps=1)
            return
        # Локально слабее — ищем стык вдоль фронта, но не уходим далеко
        # от своего места в плане: иначе рота уползает вдоль линии до
        # края карты. В четырёх клетках от якоря возвращаемся к нему.
        if _distance(det.position, goal) >= 4:
            lateral_goal = goal
        else:
            lateral_goal = (
                det.position[0] + right[0] * sign * 2.0,
                det.position[1] + right[1] * sign * 2.0,
            )
        self._step_with_avoidance(
            det, _clamp_cell(lateral_goal), blocked, steps=1
        )

    def _advance_ai(self):
        """Движение войск по приказу или армейскому автоплану.

        Явно выбранная цель (``set_focus_target``) имеет приоритет над
        ближайшим врагом. Ручной приказ роте временно исключает её из
        автоплана. План ведёт роты к своим полосам, а в соприкосновении
        позволяет давить или обходить, а не стоять на одной дистанции.
        """
        self._refresh_auto_plan_goals()
        self._push_budget = {
            self.state.player_side: 1,
            self._other_side(self.state.player_side): 1,
        }
        radius = getattr(self.state.sim, "engage_range", None)
        attack_orders = ("aggressive_attack", "attack", "cautious_attack")
        for det in self.state.units:
            if getattr(det, "broken", False) or det.force <= 1:
                continue
            if getattr(det, "retreating", False):
                continue
            order = getattr(det, "ui_order", "holding_defense")
            plan = self.plan_for(det.side)
            plan_goal = self._plan_goals.get(det.name)
            if plan.active and plan_goal is not None:
                if plan.mode == "advance":
                    forward = self._nearest_forward_enemy(
                        det, plan.axis,
                        max_distance=max(4, int(radius or 3) + 2),
                    )
                    blocked = {
                        tuple(other.position) for other in self.state.units
                        if other.side != det.side
                        and not getattr(other, "broken", False)
                    }
                    if (forward is not None and
                            _distance(det.position, forward.position) >
                            max(1, int(radius or 3))):
                        # Противник впереди: сначала сближение с ним, а не
                        # марш сквозь его порядки к дальней точке плана.
                        self._step_with_avoidance(
                            det, tuple(forward.position), blocked, steps=1
                        )
                    elif forward is not None:
                        self._contact_maneuver(det, plan_goal, plan.axis)
                    else:
                        # Если рота уже прошла цель и впереди никого нет,
                        # она остаётся на достигнутом рубеже, а не отходит
                        # назад к старой точке плана.
                        advanced_past = (
                            (det.position[0] - plan_goal[0]) *
                            plan.axis[0] +
                            (det.position[1] - plan_goal[1]) *
                            plan.axis[1]
                        ) > 0
                        if not advanced_past:
                            self._step_with_avoidance(
                                det, plan_goal, blocked, steps=1
                            )
                else:
                    # На рубеже рота идёт к своему месту, но под огнём не
                    # обязана проходить сквозь противника: обходим занятые
                    # клетки, а не слипаемся в центре линии.
                    blocked = {
                        tuple(other.position) for other in self.state.units
                        if other.side != det.side
                        and not getattr(other, "broken", False)
                    }
                    self._step_with_avoidance(
                        det, plan_goal, blocked, steps=1
                    )
                continue
            target = self._targets.get(det.name)
            if target is not None:
                if order in attack_orders or order == "forced_march":
                    if det.name not in self._plan_goals:
                        enemy = (self._enemy_by_name(
                            self._focus_targets.get(det.name)
                        ) or self._nearest_enemy(det))
                        if enemy is not None:
                            target = tuple(enemy.position)
                            self._targets[det.name] = target
                            distance = _distance(det.position, target)
                            if (radius is not None and
                                    distance <= max(1, int(radius))):
                                # Уже в зоне огня: держим дистанцию.
                                continue
                steps = 2 if order == "forced_march" else 1
                self._step_toward(det, target, steps)
                if det.position == tuple(target):
                    self._targets.pop(det.name, None)
                    det.ui_order = "holding_defense"
                continue
            if order in attack_orders or order == "forced_march":
                enemy = (self._enemy_by_name(
                    self._focus_targets.get(det.name)
                ) or self._nearest_enemy(det))
                if enemy is None:
                    continue
                distance = _distance(det.position, enemy.position)
                if radius is None or distance > max(1, int(radius)):
                    steps = 2 if order == "forced_march" else 1
                    self._step_toward(det, enemy.position, steps)

    def _advance_targets(self):
        for name in list(self._targets):
            det = next((d for d in self.state.units if d.name == name), None)
            if det is None or getattr(det, "broken", False):
                self._targets.pop(name, None)
                continue
            focus_name = self._focus_targets.get(name)
            if focus_name and self._enemy_by_name(focus_name) is None:
                # Цель уничтожена: снимаем захват и возвращаем обычную атаку.
                self._focus_targets.pop(name, None)
                self._sync_focus_targets()
                if det.ui_order in (
                        "aggressive_attack", "attack", "cautious_attack"):
                    enemy = self._nearest_enemy(det)
                    if enemy is not None:
                        self._targets[name] = tuple(enemy.position)
                    else:
                        self._targets.pop(name, None)
                else:
                    self._targets.pop(name, None)

    def set_move_target(self, idx, target):
        det = self.state.det_at(idx)
        if det is None:
            return False
        try:
            x, y = target
        except Exception:                          # noqa: BLE001
            return False
        # Экран карты работает в координатах 256x256, бой — в 24x24.
        cell_x = int(round(float(x) / MAP_SIZE * CELL_SIZE))
        cell_y = int(round(float(y) / MAP_SIZE * CELL_SIZE))
        self._mark_plan_exempt(det)
        self._focus_targets.pop(det.name, None)
        self._sync_focus_targets()
        self._targets[det.name] = (
            max(0, min(CELL_SIZE, cell_x)),
            max(0, min(CELL_SIZE, cell_y)),
        )
        det.ui_order = "move"
        return True

    def set_cell_target(self, idx, target):
        """Поставить цель движения в координатах боевой сетки 24x24."""
        det = self.state.det_at(idx)
        if det is None:
            return False
        try:
            x, y = target
        except Exception:                          # noqa: BLE001
            return False
        self._mark_plan_exempt(det)
        self._focus_targets.pop(det.name, None)
        self._sync_focus_targets()
        self._targets[det.name] = (
            max(0, min(CELL_SIZE, int(round(float(x))))),
            max(0, min(CELL_SIZE, int(round(float(y))))),
        )
        det.ui_order = "move"
        return True

    def _signal_for(self, order_id):
        if order_id == "aggressive_attack":
            return W.OrderSignal(aggression=0.20, morale=1.0,
                                 retreat_allowed=False, label=order_id)
        if order_id == "attack":
            return W.OrderSignal(aggression=0.12, morale=1.0,
                                 label=order_id)
        if order_id == "cautious_attack":
            return W.OrderSignal(aggression=0.06, discipline=0.06,
                                 label=order_id)
        if order_id == "holding_defense":
            return W.OrderSignal(discipline=0.14, morale=0.8,
                                 retreat_allowed=False, label=order_id)
        if order_id == "defense":
            return W.OrderSignal(discipline=0.10, morale=0.4,
                                 label=order_id)
        if order_id == "desperate_defense":
            return W.OrderSignal(discipline=0.18, morale=2.0,
                                 retreat_allowed=False, label=order_id)
        if order_id == "rest":
            return W.OrderSignal(aggression=-0.08, morale=3.0, fear=-0.04,
                                 needs={"fatigue": 0.18}, label=order_id)
        if order_id in ("withdrawal", "movement"):
            return W.OrderSignal(aggression=-0.10, morale=-2.0, fear=0.05,
                                 retreat_allowed=False, label=order_id)
        if order_id == "move":
            return W.OrderSignal(aggression=-0.05, label=order_id)
        if order_id == "forced_march":
            return W.OrderSignal(aggression=0.02, needs={"fatigue": -0.08},
                                 label=order_id)
        return W.OrderSignal(aggression=0.05, label=order_id)

    def assign_order(self, idx, order_id, by_plan=False):
        det = self.state.det_at(idx)
        if det is None:
            return False
        order_id = str(order_id)
        if not by_plan:
            self._mark_plan_exempt(det)
        old = self._ui_orders.get(idx)
        if old is not None:
            old.state["active"] = False
        signal = self._signal_for(order_id)
        label = self.order_table.label_of(order_id)
        order = W.Order(
            "UI:%s" % label, signal, duration=8, targets=[det],
            side=det.side,
        )
        self.state.sim.issue_order(order)
        self._ui_orders[idx] = order
        det.ui_order = order_id
        attack_orders = ("aggressive_attack", "attack", "cautious_attack")
        if order_id in ("withdrawal", "movement"):
            self._focus_targets.pop(det.name, None)
            self._sync_focus_targets()
            self._targets.pop(det.name, None)
            det.retreating = True
            det.panicked = False
            enemy = self._nearest_enemy(det)
            if enemy is not None:
                dx = 1 if det.position[0] <= enemy.position[0] else -1
                dy = 1 if det.position[1] <= enemy.position[1] else -1
                target = (
                    max(0, min(CELL_SIZE, det.position[0] - 4 * dx)),
                    max(0, min(CELL_SIZE, det.position[1] - 3 * dy)),
                )
                self._targets[det.name] = target
        else:
            det.retreating = False
            det.panicked = False
            if order_id in attack_orders or order_id == "forced_march":
                # Явная цель сохраняется при повторной команде атаки.
                enemy = (self._enemy_by_name(
                    self._focus_targets.get(det.name)
                ) or self._nearest_enemy(det))
                if enemy is not None:
                    self._targets[det.name] = tuple(enemy.position)
            else:
                self._focus_targets.pop(det.name, None)
                self._sync_focus_targets()
                if order_id not in ("move",):
                    self._targets.pop(det.name, None)
        self.state.log_event(idx, "Приказ: %s" % label)
        return True
