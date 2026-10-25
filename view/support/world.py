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
from .log_journal import get_logger

logger = get_logger("view.world")

MAP_SIZE = 256
CELL_SIZE = 24


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


class UnitSupply:
    """Совместимый снимок снабжения одного отделения."""

    def __init__(self, value):
        value = max(0.0, min(1.5, float(value)))
        self.norm = {k: 100.0 for k in ("I", "II", "III", "IV", "V", "VI", "VII")}
        self.actual = {
            "I": 100.0 * value, "II": 100.0 * value,
            "III": 100.0 * value, "IV": 100.0 * value,
            "V": 100.0 * value, "VI": 100.0 * value,
            "VII": 100.0 * value,
        }


class CampaignLogistics:
    """Презентационная логистика: ресурсы без отдельного симулятора."""

    resource_defs = {
        "I": {"label": "Боеприпасы"},
        "II": {"label": "Продовольствие"},
        "III": {"label": "Топливо"},
        "IV": {"label": "Медикаменты"},
        "V": {"label": "Инженерное имущество"},
        "VI": {"label": "Транспорт"},
        "VII": {"label": "Связь"},
    }

    def __init__(self, state):
        self.state = state

    @property
    def unit_supply(self):
        return {
            i: UnitSupply(self.state.read_voltage(i, "U_supply"))
            for i in range(self.state.count)
        }


class CampaignLogisticsSystem:
    """Модификаторы снабжения, которые читает оверлей логистики."""

    def __init__(self, state):
        self.state = state

    def _supply(self, idx):
        return max(0.0, min(1.5, self.state.read_voltage(idx, "U_supply")))

    def get_ammo_modifier(self, idx):
        return max(0.1, min(1.3, self._supply(idx)))

    def get_defense_modifier(self, idx):
        return max(0.0, 0.2 * self._supply(idx))

    def get_offense_modifier(self, idx):
        return max(0.0, 0.15 * self._supply(idx))


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
        self.event_log = []
        self.tick_events = []
        self.engagements = []
        self.class_configs = {3: ClassConfig()}
        self.logistics = CampaignLogistics(self)
        self.logistics_system = None
        self.engine = None
        self._event_cursor = 0
        self._initial_forces = {}
        for det in self.sim.all_detachments:
            self._remember_start(det)
            if not hasattr(det, "ui_order"):
                det.ui_order = "holding_defense"
            if not hasattr(det, "ui_supply"):
                det.ui_supply = 0.82

    # --- базовые представления ------------------------------------------
    def _remember_start(self, det):
        if not hasattr(det, "ui_order"):
            det.ui_order = "holding_defense"
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
            return max(0.0, det.force * 500.0)
        if channel == "U_casualties":
            ratio = det.force / max(1.0, self._start_force(det))
            return max(0.0, min(1.0, 1.0 - ratio))
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
                "role": det.role,
                "doctrine": det.doctrine,
                "ui_order": getattr(det, "ui_order", "holding_defense"),
                "ui_supply": getattr(det, "ui_supply", 0.82),
                "retreating": det.retreating,
                "panicked": det.panicked,
                "broken": det.broken,
            })
        return {
            "seed": self.sim.seed,
            "turn": self.sim.turn,
            "max_turns": self.sim.max_turns,
            "player_side": self.player_side,
            "player_gender": self.player_gender,
            "detachments": dets,
            "event_log": self.event_log[-250:],
        }

    def apply_snapshot(self, snapshot):
        if not snapshot:
            return
        self.player_side = snapshot.get("player_side", self.player_side)
        self.player_gender = snapshot.get("player_gender", self.player_gender)
        self.sim.turn = int(snapshot.get("turn", self.sim.turn))
        by_name = {det.name: det for det in self.units}
        for item in snapshot.get("detachments", []):
            det = by_name.get(item.get("name"))
            if det is None:
                continue
            det.force = float(item.get("force", det.force))
            det.morale = float(item.get("morale", det.morale))
            det.position = tuple(item.get("position", det.position))
            det.ui_order = item.get("ui_order", getattr(det, "ui_order",
                                                        "holding_defense"))
            det.ui_supply = float(item.get("ui_supply",
                                          getattr(det, "ui_supply", 0.82)))
            det.retreating = bool(item.get("retreating", det.retreating))
            det.panicked = bool(item.get("panicked", det.panicked))
            det.broken = bool(item.get("broken", det.broken))
        self.event_log = list(snapshot.get("event_log", []))[-250:]
        self.tick_events = []
        self._event_cursor = len(getattr(self.sim, "events", []))


class CampaignEngine:
    """Минимальный движок для UI: такт, приказы и цели перемещения."""

    def __init__(self, state):
        self.state = state
        state.engine = self
        self.tick_count = state.sim.turn
        self.order_table = OrderTable(state.content)
        self.rng = state.sim.rng
        self.engagements = []
        self.logistics = CampaignLogisticsSystem(state)
        state.logistics_system = self.logistics
        self.time_system = None
        self._targets = {}
        self._ui_orders = {}

    def tick(self):
        state = self.state
        state.begin_tick()
        pairs = state.sim._pair_engagements()
        self.engagements = [
            {"attacker": a.name, "defender": b.name} for a, b in pairs
        ]
        self._advance_targets()
        state.sim.tick()
        self.tick_count = state.sim.turn
        state.sync_events()
        if state.sim.finished:
            state.log_event(
                state.player_idx,
                "Итог операции: %s" % (state.sim.winner or "—"),
            )
        return not state.sim.finished

    def _advance_targets(self):
        for name, target in list(self._targets.items()):
            det = next((d for d in self.state.units if d.name == name), None)
            if det is None or det.broken:
                self._targets.pop(name, None)
                continue
            x, y = det.position
            tx, ty = target
            if (x, y) == (tx, ty):
                self._targets.pop(name, None)
                continue
            if x != tx:
                x += 1 if tx > x else -1
            elif y != ty:
                y += 1 if ty > y else -1
            det.position = (max(0, min(CELL_SIZE, x)),
                            max(0, min(CELL_SIZE, y)))

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
        self._targets[det.name] = (
            max(0, min(CELL_SIZE, cell_x)),
            max(0, min(CELL_SIZE, cell_y)),
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
                                 label=order_id)
        if order_id == "move":
            return W.OrderSignal(aggression=-0.05, label=order_id)
        if order_id == "forced_march":
            return W.OrderSignal(aggression=0.02, needs={"fatigue": -0.08},
                                 label=order_id)
        return W.OrderSignal(aggression=0.05, label=order_id)

    def assign_order(self, idx, order_id):
        det = self.state.det_at(idx)
        if det is None:
            return False
        order_id = str(order_id)
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
        if order_id in ("withdrawal", "movement"):
            det.retreating = True
        self.state.log_event(idx, "Приказ: %s" % label)
        return True
