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
    return abs(int(a[0]) - int(b[0])) + abs(int(a[1]) - int(b[1]))


def _clamp_cell(point):
    return (
        max(0, min(CELL_SIZE, int(round(float(point[0]))))),
        max(0, min(CELL_SIZE, int(round(float(point[1]))))),
    )


def _unit_vector(vector, fallback=(1.0, 0.0)):
    x, y = float(vector[0]), float(vector[1])
    length = (x * x + y * y) ** 0.5
    if length < 1e-9:
        return (float(fallback[0]), float(fallback[1]))
    return (x / length, y / length)


@dataclass
class ArmyPlan:

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
            "axis": [
                round(float(self.axis[0]), 4),
                round(float(self.axis[1]), 4),
            ],
            "target": list(self.target) if self.target is not None else None,
            "line": (
                [list(self.line[0]), list(self.line[1])]
                if self.line is not None
                else None
            ),
            "auto": bool(self.auto),
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls()
        line = data.get("line")
        if not isinstance(line, (list, tuple)) or len(line) != 2:
            line = None
        return cls(
            mode=str(data.get("mode", "off")),
            axis=tuple(data.get("axis") or (1.0, 0.0)),
            target=(
                tuple(data["target"])
                if isinstance(data.get("target"), (list, tuple))
                and len(data["target"]) == 2
                else None
            ),
            line=(tuple(line[0]), tuple(line[1])) if line else None,
            auto=bool(data.get("auto", False)),
        )


class SegmentLayout:

    def __init__(self, segments):
        self.segments = segments


class VoltageLayout:

    def __init__(self, channel_index):
        self.channel_index = channel_index


class ClassConfig:

    def __init__(self):
        self.class_name = "military_unit"
        self.label = "Отделение"
        order_states = [
            "holding_defense",
            "aggressive_attack",
            "attack",
            "cautious_attack",
            "defense",
            "desperate_defense",
            "move",
            "rest",
            "forced_march",
            "withdrawal",
        ]
        self.segment_layout = SegmentLayout(
            {
                "condition": (
                    0,
                    2,
                    [
                        "Уничтожено",
                        "Потрёпано",
                        "Боеспособно",
                        "Полная готовность",
                    ],
                ),
                "order": (2, 5, order_states),
                "size": (
                    5,
                    3,
                    [
                        "company",
                        "battalion",
                        "regiment",
                        "brigade",
                        "division",
                    ],
                ),
                "morale": (10, 3, ["", "", "", "", "", ""]),
                "discipline": (13, 3, ["", "", "", "", "", ""]),
                "supply": (16, 2, ["", "", "", ""]),
                "fatigue": (18, 2, ["", "", "", ""]),
                "profession": (20, 3, ["", "", "", "", "", ""]),
                "cohesion": (23, 3, ["", "", "", "", "", ""]),
                "initiative": (26, 2, ["", "", "", ""]),
                "health": (28, 3, ["", "", "", "", "", ""]),
            }
        )
        self.voltage_layout = VoltageLayout(
            {
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
            }
        )


@dataclass
class OrderType:

    id: str
    label: str
    raw: dict


class OrderTable:

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

    def __init__(
        self, sim, player_side="red", content=None, map_name="valley_01"
    ):
        self.sim = sim
        self.player_side = player_side
        self.content = content or Content()
        self.map_name = map_name
        self.player_gender = "male"
        self.commander_trait = None

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

        self.auto_plans = {}
        self.plan_exempt = set()
        self.needs = NeedsSystem(self, self.supplies)
        for det in self.sim.all_detachments:
            self._remember_start(det)
        self.geometry = FrontGeometry(self)

        self.groups = {i: [] for i in range(1, 7)}

    def _remember_start(self, det):
        if not hasattr(det, "ui_order"):
            det.ui_order = (
                "holding_defense" if det.side == self.player_side else "attack"
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
        geometry = getattr(self, "geometry", None)
        if geometry is not None:
            return geometry.projected_force(det)
        return max(0.0, float(getattr(det, "force", 0.0)))

    def casualty_fraction(self, idx):
        det = self.det_at(idx)
        if det is None:
            return 0.0
        start = max(1.0, self._start_force(det))
        losses = float(getattr(det, "losses", 0.0))
        return max(0.0, min(1.0, losses / start))

    def division_loss_percent(self):
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
            avg = sum(
                c.needs.get("fatigue", 0.0) for c in det.characters
            ) / max(1, len(det.characters))
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
        return (
            self.engine.order_table.index_of(det.ui_order)
            if self.engine
            else 0
        )

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
                    self.engine.order_table.orders
                ):
                    value = self.engine.order_table.orders[value].get(
                        "id", "attack"
                    )
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
            det.ui_supply = max(
                0.0, min(1.5, getattr(det, "ui_supply", 0.82) + float(delta))
            )
        else:
            det.morale = max(0.0, min(100.0, det.morale + float(delta) * 10.0))

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

    def to_snapshot(self):
        dets = []
        for det in self.units:
            dets.append(
                {
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
                }
            )
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
            "needs": (
                self.needs.get_save_snapshot()
                if getattr(self, "needs", None)
                else {}
            ),
            "geometry": (
                self.geometry.snapshot()
                if getattr(self, "geometry", None)
                else {}
            ),
            "logistics": (
                self.logistics.get_save_snapshot()
                if getattr(self, "logistics", None)
                else {}
            ),
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
        self.campaign_role = snapshot.get("campaign_role", self.campaign_role)
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

            det.ui_order = item.get(
                "ui_order", getattr(det, "ui_order", "holding_defense")
            )
            det.ui_supply = float(
                item.get("ui_supply", getattr(det, "ui_supply", 0.82))
            )
            det.ui_fortification = float(
                item.get(
                    "ui_fortification", getattr(det, "ui_fortification", 0.0)
                )
            )
            det.losses = float(item.get("losses", getattr(det, "losses", 0.0)))
            det.retreating = bool(item.get("retreating", det.retreating))
            det.panicked = bool(item.get("panicked", det.panicked))
            det.broken = bool(item.get("broken", det.broken))
            det.surrendered = bool(
                item.get("surrendered", getattr(det, "surrendered", False))
            )
            for character, values in zip(
                det.characters, item.get("needs", [])
            ):
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

                needs_snapshot = {"supplies": snapshot.get("supplies") or {}}

            if needs_snapshot:
                self.needs.load_from_snapshot(needs_snapshot)
        if getattr(self, "logistics", None) is not None and snapshot.get(
            "logistics"
        ):
            self.logistics.load_from_snapshot(snapshot.get("logistics"))
        if getattr(self, "geometry", None) is not None:
            self.geometry.load_snapshot(snapshot.get("geometry"))

            self.geometry.refresh_sectors()
            self.geometry.recompute()
        groups = snapshot.get("groups")
        if isinstance(groups, dict):
            loaded = {i: [] for i in range(1, 7)}
            alive = {
                det.name
                for det in self.units
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
            det.name for det in self.units if not getattr(det, "broken", False)
        }
        self.plan_exempt = {
            str(name)
            for name in snapshot.get("plan_exempt", [])
            if str(name) in alive_names
        }
