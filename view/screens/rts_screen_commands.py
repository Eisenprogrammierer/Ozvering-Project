"""Приказы, планы и открытие оверлеев."""

from __future__ import annotations


class RTSScreenCommandsMixin:

    def command_plan_hold(self):
        if not self.engine.set_auto_plan("hold"):
            self._feedback("Нет живых рот для плана", 1.4)
            return
        self._feedback("Автоплан: оборона — Shift+ПКМ задаёт рубеж", 2.2)

    def command_plan_advance(self):
        target_det = self._target_enemy_det()
        target = tuple(target_det.position) if target_det is not None else None
        if not self.engine.set_auto_plan("advance", target=target):
            self._feedback("Нет живых рот для плана", 1.4)
            return
        where = (
            "на %s" % target_det.name
            if target_det is not None
            else "к противнику"
        )
        self._feedback(
            "Автоплан: наступление %s — Shift+ПКМ меняет направление" % where,
            2.2,
        )

    def command_plan_off(self):
        self.engine.clear_auto_plan()
        self._feedback("Автоплан снят", 1.4)

    def _issue_plan_target(self, cell):
        plan = self.engine.plan_for()
        if not plan.active:
            self._feedback(
                "Сначала включите автоплан: G — оборона, T — наступление",
                2.0,
            )
            return
        mode = plan.mode
        if not self.engine.set_auto_plan(
            mode, target=cell, keep_exemptions=True
        ):
            self._feedback("Не удалось изменить план", 1.4)
            return
        if mode == "hold":
            self._feedback("Рубеж плана: %d:%d" % cell, 1.6)
        else:
            self._feedback("Направление плана: %d:%d" % cell, 1.6)

    def command_hold(self):
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine._targets.pop(det.name, None)
            self.engine.assign_order(idx, "holding_defense")
        self._feedback("Держать позиции", 1.3)

    def command_rest(self):
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine._targets.pop(det.name, None)
            self.engine.assign_order(idx, "rest")
        self._feedback("Отдых", 1.3)

    def command_stop(self):
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine._targets.pop(det.name, None)
            self.engine.assign_order(idx, "defense")
        self._feedback("Стоп", 1.0)

    def command_attack_nearest(self):
        target = self._target_enemy_det()
        if target is not None:
            self._issue_attack(self._target_enemy)
            return
        count = 0
        for det in self._selected_dets():
            enemy = self._nearest_enemy(det)
            if enemy is None:
                continue
            idx = self.state.units.index(det)
            self.engine.clear_focus_target(idx)
            self.engine.assign_order(idx, "aggressive_attack")
            if enemy is not None:
                self.engine.set_focus_target(idx, enemy)
            count += 1
        self._feedback("Атака: %d" % count, 1.2)

    def command_cautious_attack(self):
        count = 0
        target = self._target_enemy_det()
        for det in self._selected_dets():
            enemy = target or self._nearest_enemy(det)
            if enemy is None:
                continue
            idx = self.state.units.index(det)
            self.engine.assign_order(idx, "cautious_attack")
            self.engine.set_focus_target(idx, enemy)
            count += 1
        if target is not None:
            self._feedback("Осторожно по цели: %s" % target.name, 1.3)
        else:
            self._feedback("Осторожная атака: %d" % count, 1.2)

    def command_withdraw(self):
        count = 0
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine.clear_focus_target(idx)
            self.engine.assign_order(idx, "withdrawal")
            count += 1
        self._feedback("Отход: %d" % count, 1.3)

    def command_force_march(self):
        count = 0
        for det in self._selected_dets():
            enemy = self._target_enemy_det() or self._nearest_enemy(det)
            if enemy is None:
                continue
            idx = self.state.units.index(det)
            self.engine.assign_order(idx, "forced_march")
            self.engine.set_cell_target(idx, enemy.position)
            self.engine.set_focus_target(idx, enemy)
            det.ui_order = "forced_march"
            count += 1
        self._feedback("Марш-бросок: %d" % count, 1.2)

    def _issue_ground(self, cell):
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine.clear_focus_target(idx)
            self.engine.assign_order(idx, "move")
            self.engine.set_cell_target(idx, cell)
        if self.selected:
            self._feedback("Движение в %d:%d" % cell, 1.0)

    def _issue_attack(self, enemy_idx):
        enemy = self._set_target_enemy(enemy_idx)
        if enemy is None:
            self._feedback("Цель уже уничтожена", 1.2)
            return
        count = 0
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            if not self.engine.set_focus_target(idx, enemy):
                continue
            self.engine.assign_order(idx, "aggressive_attack")

            self.engine.set_focus_target(idx, enemy)
            count += 1
        if count:
            self._feedback(
                "Сосредоточенный огонь: %s (%d)" % (enemy.name, count), 1.8
            )
        else:
            self._feedback("Сначала выберите свои подразделения", 1.4)

    def command_focus_hover(self):
        if self._hover_idx is None:
            self._feedback("Наведите курсор на врага", 1.2)
            return
        if self._hover_idx in self._player_indices():
            self._feedback("Под курсором своё подразделение", 1.2)
            return
        self._issue_attack(self._hover_idx)

    def open_orders(self):
        from ..ui.orders_overlay import UnitOrdersOverlay

        self.app.manager.push(UnitOrdersOverlay(self.app, self))

    def open_needs(self):
        from ..ui.needs_overlay import NeedsOverlay

        self.app.manager.push(NeedsOverlay(self.app, self))

    def open_adjutant_orders(self):
        from .adjutant_orders import AdjutantOrdersScreen

        self.app.manager.push(AdjutantOrdersScreen(self.app))

    def open_journal(self):
        from ..ui.overlays import NotebookOverlay

        self.app.manager.push(NotebookOverlay(self.app))

    def open_logistics(self):
        from ..ui.overlays import LogisticsOverlay

        self.app.manager.push(LogisticsOverlay(self.app))

    def open_radio(self):
        from ..ui.overlays import RadioOverlay

        self.app.manager.push(RadioOverlay(self.app))
