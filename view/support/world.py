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


def _distance(a, b):
    """Манхэттенское расстояние между клетками поля."""
    return abs(int(a[0]) - int(b[0])) + abs(int(a[1]) - int(b[1]))


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
                "needs": [dict(c.needs) for c in det.characters],
            })
        return {
            "seed": self.sim.seed,
            "turn": self.sim.turn,
            "max_turns": self.sim.max_turns,
            "player_side": self.player_side,
            "player_gender": self.player_gender,
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
        # Один войсковой такт = 5 игровых минут. Часы при этом идут по
        # минутам; интервал настраивается временем кампании.
        self.combat_seconds = 300

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

    def _advance_ai(self):
        """Движение войск к противнику, если приказ этого требует.

        Явно выбранная цель (``set_focus_target``) имеет приоритет над
        ближайшим врагом. В зоне соприкосновения отделение не залезает на
        клетку противника, а останавливается и ведёт огонь. Скорость зависит
        от приказа: марш-бросок — 2 клетки, обычное движение — 1.
        """
        radius = getattr(self.state.sim, "engage_range", None)
        attack_orders = ("aggressive_attack", "attack", "cautious_attack")
        for det in self.state.units:
            if getattr(det, "broken", False) or det.force <= 1:
                continue
            if getattr(det, "retreating", False):
                continue
            target = self._targets.get(det.name)
            order = getattr(det, "ui_order", "holding_defense")
            if target is not None:
                if order in attack_orders or order == "forced_march":
                    enemy = (self._enemy_by_name(
                        self._focus_targets.get(det.name)
                    ) or self._nearest_enemy(det))
                    if enemy is not None:
                        target = tuple(enemy.position)
                        self._targets[det.name] = target
                        distance = _distance(det.position, target)
                        if (radius is not None and
                                distance <= max(1, int(radius))):
                            # Уже в зоне огня: держим дистанцию, не слипаемся.
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
