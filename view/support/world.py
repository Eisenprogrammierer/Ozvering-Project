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
from .world_state import (
    CELL_SIZE,
    MAP_SIZE,
    PLAN_ADVANCE_DISTANCE,
    PLAN_LANE_WIDTH_MAX,
    PLAN_LANE_WIDTH_MIN,
    PLAN_MODES,
    ArmyPlan,
    CampaignState,
    OrderTable,
    _clamp_cell,
    _distance,
    _unit_vector,
)

logger = get_logger("view.world")


class CampaignEngine:

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

        self._focus_targets = {}
        self.state.sim.focus_targets = {}

        self._plan_goals = {}
        self._plan_orders = {}

        self._push_tick = {}
        self._push_budget = {}

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

        for det in state.sim.all_detachments:
            before = force_before.get(det.name)
            cap = float(getattr(det, "start_force", det.force))
            if before is None:

                det.force = min(cap, max(1.0, float(det.force)))
                continue
            det.force = min(cap, max(1.0, float(before)))

        engaged_sides = {item.get("attacker") for item in self.engagements}

        side_by_name = {
            det.name: det.side for det in state.sim.all_detachments
        }
        engaged_sides = {
            side_by_name[name]
            for name in engaged_sides
            if name in side_by_name
        }
        engaged_sides |= {
            side_by_name.get(item.get("defender")) for item in self.engagements
        }
        engaged_sides.discard(None)
        geometry = getattr(state, "geometry", None)
        if geometry is not None:
            geometry.update(engaged_sides=engaged_sides, tick=state.sim.turn)
            geometry.apply_attrition(force_before, engaged_sides)
        else:

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
            engaged = {item.get("attacker") for item in self.engagements} | {
                item.get("defender") for item in self.engagements
            }
            state.needs.on_tick(seconds, engaged)
        if getattr(state, "logistics", None) is not None:
            engaged = {item.get("attacker") for item in self.engagements} | {
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
            other
            for other in self.state.units
            if other.side != det.side and not getattr(other, "broken", False)
        ]
        if not enemies:
            return None
        return min(
            enemies,
            key=lambda other: (
                _distance(det.position, other.position),
                other.name,
            ),
        )

    def _enemy_by_name(self, name):
        if not name:
            return None
        return next(
            (
                det
                for det in self.state.units
                if det.name == name and not getattr(det, "broken", False)
            ),
            None,
        )

    def _sync_focus_targets(self):
        self.state.sim.focus_targets = dict(self._focus_targets)

    def set_focus_target(self, idx, enemy):
        det = self.state.det_at(idx)
        if det is None:
            return False
        if isinstance(enemy, int):
            target = self.state.det_at(enemy)
        elif isinstance(enemy, str):
            target = self._enemy_by_name(enemy)
        else:
            target = enemy
        if (
            target is None
            or target.side == det.side
            or getattr(target, "broken", False)
        ):
            return False
        self._mark_plan_exempt(det)
        self._focus_targets[det.name] = target.name
        self._targets[det.name] = tuple(target.position)
        self._sync_focus_targets()
        return True

    def clear_focus_target(self, idx_or_name=None):
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

    def plan_for(self, side=None):
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
            det
            for det in self.state.units
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
        return self._center_of(
            self._plan_units(self._other_side(side), include_exempt=True)
        )

    def _advance_target(self, side, axis, center=None):
        units = self._plan_units(side, include_exempt=True)
        center = center or self._center_of(units)
        enemy_center = self._opponent_center(side)
        if enemy_center is not None:
            return _clamp_cell(enemy_center)
        if center is not None:
            return _clamp_cell(
                (
                    center[0] + axis[0] * PLAN_ADVANCE_DISTANCE,
                    center[1] + axis[1] * PLAN_ADVANCE_DISTANCE,
                )
            )
        return _clamp_cell((CELL_SIZE // 2, CELL_SIZE // 2))

    def _facing_of(self, side):
        geometry = getattr(self.state, "geometry", None)
        if geometry is not None:
            try:
                return _unit_vector(geometry.facing_of(side))
            except Exception:
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
        return max(PLAN_LANE_WIDTH_MIN, min(PLAN_LANE_WIDTH_MAX, span + 2.0))

    def _default_hold_line(self, units, side=None):
        center = self._center_of(units)
        if center is None:
            return ((0, 0), (CELL_SIZE, 0))
        facing = self._facing_of(side or self.state.player_side)
        right = (-facing[1], facing[0])
        half = self._line_width(units) / 2.0
        return (
            _clamp_cell(
                (center[0] - right[0] * half, center[1] - right[1] * half)
            ),
            _clamp_cell(
                (center[0] + right[0] * half, center[1] + right[1] * half)
            ),
        )

    def _line_through(self, target, units, side=None):
        facing = self._facing_of(side or self.state.player_side)
        right = (-facing[1], facing[0])
        half = self._line_width(units) / 2.0
        cx, cy = float(target[0]), float(target[1])
        return (
            _clamp_cell((cx - right[0] * half, cy - right[1] * half)),
            _clamp_cell((cx + right[0] * half, cy + right[1] * half)),
        )

    def _clear_plan_goals(self, side):
        names = {det.name for det in self.state.units if det.side == side}
        for name in names:
            if name in self._plan_goals:
                self._plan_goals.pop(name, None)
                self._targets.pop(name, None)

    def _deactivate_ui_orders(self, side):
        for idx, order in list(self._ui_orders.items()):
            det = self.state.det_at(idx)
            if det is None or det.side != side:
                continue
            order.state["active"] = False
            self._ui_orders.pop(idx, None)
            self._focus_targets.pop(det.name, None)
        self._sync_focus_targets()

    def _apply_plan_order(self, side, plan):
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
                aggression=0.02,
                discipline=0.16,
                morale=0.9,
                retreat_allowed=True,
                label="автоплан: оборона",
            )
        else:
            signal = W.OrderSignal(
                aggression=0.18,
                discipline=0.05,
                morale=0.9,
                retreat_allowed=True,
                label="автоплан: наступление",
            )
        order = W.Order(
            "Автоплан: %s" % plan.label,
            signal,
            duration=5000,
            targets=units,
            side=side,
        )
        self.state.sim.issue_order(order)
        self._plan_orders[side] = order

    def set_auto_plan(
        self,
        mode,
        target=None,
        line=None,
        side=None,
        axis=None,
        auto=False,
        silent=False,
        keep_exemptions=False,
    ):
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

        if not keep_exemptions:
            self.state.plan_exempt = {
                name
                for name in getattr(self.state, "plan_exempt", set())
                if next(
                    (det.side for det in self.state.units if det.name == name),
                    None,
                )
                != side
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
                mode="hold",
                target=target,
                line=endpoints,
                axis=facing,
                auto=bool(auto),
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
                        (
                            enemy_center[0] - center[0],
                            enemy_center[1] - center[1],
                        ),
                        fallback=facing,
                    )
                    if enemy_center is not None and center is not None
                    else facing
                )
            if target is None:
                target = self._advance_target(side, chosen_axis, center)
            plan = ArmyPlan(
                mode="advance",
                target=target,
                axis=chosen_axis,
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
                    plan.line[0][0],
                    plan.line[0][1],
                    plan.line[1][0],
                    plan.line[1][1],
                )
            self.state.log_event(
                self.state.player_idx,
                "Автоплан: %s%s" % (plan.label, where),
            )
        return True

    def clear_auto_plan(self, side=None, silent=False):
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
                "aggressive_attack",
                "attack",
                "cautious_attack",
                "forced_march",
            ):
                det.ui_order = "holding_defense"
        self.state.auto_plans[side] = ArmyPlan(
            mode="off", axis=self._facing_of(side)
        )
        self.state.plan_exempt = {
            name
            for name in exempt
            if next(
                (det.side for det in self.state.units if det.name == name),
                None,
            )
            != side
        }
        if was_active and not silent:
            self.state.log_event(self.state.player_idx, "Автоплан снят")
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
            first = _clamp_cell(
                (center[0] - right[0] * half, center[1] - right[1] * half)
            )
            second = _clamp_cell(
                (center[0] + right[0] * half, center[1] + right[1] * half)
            )
            vx = float(second[0] - first[0])
            vy = float(second[1] - first[1])
            length = max(1e-6, (vx * vx + vy * vy) ** 0.5)
        ux, uy = vx / length, vy / length
        line_center = (
            (float(first[0]) + float(second[0])) / 2.0,
            (float(first[1]) + float(second[1])) / 2.0,
        )

        for det in units:
            lateral = (det.position[0] - center[0]) * ux + (
                det.position[1] - center[1]
            ) * uy
            lateral = max(-length / 2.0, min(length / 2.0, lateral))
            goal = _clamp_cell(
                (
                    line_center[0] + ux * lateral,
                    line_center[1] + uy * lateral,
                )
            )
            det.ui_order = "holding_defense"

            self._plan_goals[det.name] = goal
            self._targets[det.name] = goal

    def _assign_advance_goals(self, side, plan, units, center):

        axis = plan.axis
        if plan.target is None:

            plan.target = self._advance_target(side, axis, center)
        goal_center = (float(plan.target[0]), float(plan.target[1]))
        right = (-axis[1], axis[0])
        width = self._line_width(units)
        for det in units:
            lateral = (det.position[0] - center[0]) * right[0] + (
                det.position[1] - center[1]
            ) * right[1]
            lateral = max(-width / 2.0, min(width / 2.0, lateral))
            goal = _clamp_cell(
                (
                    goal_center[0] + right[0] * lateral,
                    goal_center[1] + right[1] * lateral,
                )
            )
            det.ui_order = "attack"

            self._plan_goals[det.name] = goal
            self._targets[det.name] = goal

    def _refresh_auto_plan_goals(self):
        for side in (
            self.state.player_side,
            self._other_side(self.state.player_side),
        ):
            self._refresh_plan_for_side(side)

    def _mark_plan_exempt(self, det):
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
        side = side or self.state.player_side
        plan = self.plan_for(side)
        if not plan.active:
            return "не включён"
        exempt = {name for name in getattr(self.state, "plan_exempt", set())}
        total = len(self._plan_units(side, include_exempt=True))
        manual = len(
            [
                det
                for det in self._plan_units(side, include_exempt=True)
                if det.name in exempt
            ]
        )
        if plan.mode == "hold":
            where = "рубеж"
            if plan.line is not None:
                where = "рубеж %d:%d–%d:%d" % (
                    plan.line[0][0],
                    plan.line[0][1],
                    plan.line[1][0],
                    plan.line[1][1],
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
        plans = getattr(self.state, "auto_plans", None)
        if not isinstance(plans, dict):
            plans = {}
            self.state.auto_plans = plans
        player = self.state.player_side
        enemy = self._other_side(player)
        if enemy not in plans:
            enemy_axis = self._facing_of(enemy)
            plans[enemy] = ArmyPlan(
                mode="advance",
                axis=enemy_axis,
                target=self._advance_target(enemy, enemy_axis),
                auto=True,
            )
        if player not in plans:
            plans[player] = ArmyPlan(mode="off")

        for side, plan in plans.items():
            if isinstance(plan, ArmyPlan) and plan.active:
                self._apply_plan_order(side, plan)

    def _step_with_avoidance(self, det, target, blocked, steps=1):
        blocked = set(blocked or ())
        for _ in range(max(1, int(steps))):
            if tuple(det.position) == tuple(target):
                break
            x, y = det.position
            tx, ty = target
            candidates = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]

            candidates.sort(
                key=lambda cell: (
                    _distance(cell, target),
                    0 if cell[1] == y else 1,
                )
            )
            current_distance = _distance(det.position, target)
            chosen = None
            for cell in candidates:
                cell = (
                    max(0, min(CELL_SIZE, cell[0])),
                    max(0, min(CELL_SIZE, cell[1])),
                )
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
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / length_sq))
        cx, cy = ax + vx * t, ay + vy * t
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    def _is_entrenched(self, det):
        plan = self.plan_for(det.side)
        if plan.mode != "hold" or plan.line is None:
            return False
        return (
            self._point_to_segment_distance(
                det.position, plan.line[0], plan.line[1]
            )
            <= 2.0
        )

    def _nearest_forward_enemy(self, det, axis, max_distance=None):
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
        radius = getattr(self.state.sim, "engage_range", 3) or 3
        radius = max(1, int(radius))

        if (
            (det.position[0] - goal[0]) * axis[0]
            + (det.position[1] - goal[1]) * axis[1]
        ) > 0:
            goal = tuple(det.position)
        opponents = [
            other
            for other in self.state.units
            if other.side != det.side
            and not getattr(other, "broken", False)
            and other.force > 1
            and _distance(det.position, other.position) <= radius + 1
            and (
                (other.position[0] - det.position[0]) * axis[0]
                + (other.position[1] - det.position[1]) * axis[1]
            )
            >= -1.0
        ]
        blocked = {
            tuple(other.position)
            for other in self.state.units
            if other.side != det.side and not getattr(other, "broken", False)
        }
        if not opponents:

            self._step_with_avoidance(det, goal, blocked, steps=1)
            return

        index = next(
            (i for i, other in enumerate(self.state.units) if other is det), 0
        )
        if (self.tick_count + index) % 2 != 0:
            return
        allies = [
            other
            for other in self.state.units
            if other.side == det.side
            and other is not det
            and not getattr(other, "broken", False)
            and other.force > 1
            and _distance(det.position, other.position) <= radius + 1
        ]
        own_force = float(det.force) + sum(
            float(other.force) for other in allies
        )
        enemy_force = sum(float(other.force) for other in opponents)
        right = (-axis[1], axis[0])

        sign = 1.0 if index % 2 == 0 else -1.0
        nearest = min(
            opponents,
            key=lambda other: (
                _distance(det.position, other.position),
                other.name,
            ),
        )
        required = 1.15
        if self.plan_for(nearest.side).mode == "hold":
            required = 2.2 if self._is_entrenched(nearest) else 1.7
        if own_force >= enemy_force * required:

            if _distance(det.position, nearest.position) > 1:
                self._step_with_avoidance(
                    det, tuple(nearest.position), blocked, steps=1
                )
                return
            if (
                self._push_budget.get(det.side, 0) > 0
                and self.tick_count - self._push_tick.get(det.side, -999) >= 3
            ):
                sx = int(round(axis[0]))
                sy = int(round(axis[1]))
                if sx == 0 and sy == 0:
                    sx = 1 if axis[0] >= 0 else -1
                old_cell = tuple(nearest.position)
                push_cell = (old_cell[0] + sx, old_cell[1] + sy)
                push_cell = (
                    max(0, min(CELL_SIZE, push_cell[0])),
                    max(0, min(CELL_SIZE, push_cell[1])),
                )
                occupied = {
                    tuple(other.position)
                    for other in self.state.units
                    if other is not nearest
                }
                if push_cell != old_cell and push_cell not in occupied:
                    nearest.position = push_cell
                    det.position = old_cell
                    self._push_tick[det.side] = self.tick_count
                    self._push_budget[det.side] -= 1
                    return
            target = tuple(nearest.position)
            self._step_with_avoidance(det, target, blocked, steps=1)
            return

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
                        det,
                        plan.axis,
                        max_distance=max(4, int(radius or 3) + 2),
                    )
                    blocked = {
                        tuple(other.position)
                        for other in self.state.units
                        if other.side != det.side
                        and not getattr(other, "broken", False)
                    }
                    if forward is not None and _distance(
                        det.position, forward.position
                    ) > max(1, int(radius or 3)):

                        self._step_with_avoidance(
                            det, tuple(forward.position), blocked, steps=1
                        )
                    elif forward is not None:
                        self._contact_maneuver(det, plan_goal, plan.axis)
                    else:

                        advanced_past = (
                            (det.position[0] - plan_goal[0]) * plan.axis[0]
                            + (det.position[1] - plan_goal[1]) * plan.axis[1]
                        ) > 0
                        if not advanced_past:
                            self._step_with_avoidance(
                                det, plan_goal, blocked, steps=1
                            )
                else:

                    blocked = {
                        tuple(other.position)
                        for other in self.state.units
                        if other.side != det.side
                        and not getattr(other, "broken", False)
                    }
                    self._step_with_avoidance(det, plan_goal, blocked, steps=1)
                continue
            target = self._targets.get(det.name)
            if target is not None:
                if order in attack_orders or order == "forced_march":
                    if det.name not in self._plan_goals:
                        enemy = self._enemy_by_name(
                            self._focus_targets.get(det.name)
                        ) or self._nearest_enemy(det)
                        if enemy is not None:
                            target = tuple(enemy.position)
                            self._targets[det.name] = target
                            distance = _distance(det.position, target)
                            if radius is not None and distance <= max(
                                1, int(radius)
                            ):

                                continue
                steps = 2 if order == "forced_march" else 1
                self._step_toward(det, target, steps)
                if det.position == tuple(target):
                    self._targets.pop(det.name, None)
                    det.ui_order = "holding_defense"
                continue
            if order in attack_orders or order == "forced_march":
                enemy = self._enemy_by_name(
                    self._focus_targets.get(det.name)
                ) or self._nearest_enemy(det)
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

                self._focus_targets.pop(name, None)
                self._sync_focus_targets()
                if det.ui_order in (
                    "aggressive_attack",
                    "attack",
                    "cautious_attack",
                ):
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
        except Exception:
            return False

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
        det = self.state.det_at(idx)
        if det is None:
            return False
        try:
            x, y = target
        except Exception:
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
            return W.OrderSignal(
                aggression=0.20,
                morale=1.0,
                retreat_allowed=False,
                label=order_id,
            )
        if order_id == "attack":
            return W.OrderSignal(aggression=0.12, morale=1.0, label=order_id)
        if order_id == "cautious_attack":
            return W.OrderSignal(
                aggression=0.06, discipline=0.06, label=order_id
            )
        if order_id == "holding_defense":
            return W.OrderSignal(
                discipline=0.14,
                morale=0.8,
                retreat_allowed=False,
                label=order_id,
            )
        if order_id == "defense":
            return W.OrderSignal(discipline=0.10, morale=0.4, label=order_id)
        if order_id == "desperate_defense":
            return W.OrderSignal(
                discipline=0.18,
                morale=2.0,
                retreat_allowed=False,
                label=order_id,
            )
        if order_id == "rest":
            return W.OrderSignal(
                aggression=-0.08,
                morale=3.0,
                fear=-0.04,
                needs={"fatigue": 0.18},
                label=order_id,
            )
        if order_id in ("withdrawal", "movement"):
            return W.OrderSignal(
                aggression=-0.10,
                morale=-2.0,
                fear=0.05,
                retreat_allowed=False,
                label=order_id,
            )
        if order_id == "move":
            return W.OrderSignal(aggression=-0.05, label=order_id)
        if order_id == "forced_march":
            return W.OrderSignal(
                aggression=0.02, needs={"fatigue": -0.08}, label=order_id
            )
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
            "UI:%s" % label,
            signal,
            duration=8,
            targets=[det],
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

                enemy = self._enemy_by_name(
                    self._focus_targets.get(det.name)
                ) or self._nearest_enemy(det)
                if enemy is not None:
                    self._targets[det.name] = tuple(enemy.position)
            else:
                self._focus_targets.pop(det.name, None)
                self._sync_focus_targets()
                if order_id not in ("move",):
                    self._targets.pop(det.name, None)
        self.state.log_event(idx, "Приказ: %s" % label)
        return True
