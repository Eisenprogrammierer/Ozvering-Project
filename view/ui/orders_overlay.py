from __future__ import annotations

import pygame

from .overlays import OverlayScreen
from .widgets import Button
from .text_layout import wrap_text
from view.support.log_journal import get_logger

logger = get_logger("view.orders")

ORDER_HINTS = {
    "aggressive_attack": "Максимальный удар, повышенная уязвимость. Отход "
    "запрещён.",
    "attack": "Обычное наступление с отходом при угрозе.",
    "cautious_attack": "Осторожное сближение, меньше потерь, ниже темп.",
    "holding_defense": "Держать рубеж и не отходить без приказа.",
    "defense": "Оборона с отходом при прорыве.",
    "desperate_defense": "Стоять насмерть: высокая стойкость, большие потери.",
    "move": "Идти в указанную точку. Цель задаётся правым кликом по карте.",
    "rest": "Восстановить силы, мораль и снизить усталость.",
    "forced_march": "Ускоренный марш к цели ценой усталости.",
    "withdrawal": "Отойти назад, разорвать контакт и сохранить силы.",
}


class UnitOrdersOverlay(OverlayScreen):

    def __init__(self, app, rts):
        super().__init__(app, (250, 64, 780, 592))
        self.rts = rts
        self.buttons = []
        self._order_ids = []
        self._build()
        panel = self.panel.rect
        self.staff_btn = Button(
            (panel.right - 260, panel.bottom - 40, 200, 28),
            "Штабные приказы адъютанта",
            self.app.font_tiny,
            self.rts.open_adjutant_orders,
        )

    def _build(self):
        orders = list(
            getattr(self.app.engine, "order_table", None).orders or []
        )
        seen = {item.get("id") for item in orders}
        if "withdrawal" not in seen:
            orders.append({"id": "withdrawal", "label": "Отход"})
        self._order_ids = [item.get("id") for item in orders]
        panel = self.panel.rect
        col_w = 360
        row_h = 54
        for i, item in enumerate(orders):
            order_id = item.get("id")
            col = i // 5
            row = i % 5
            x = panel.x + 18 + col * (col_w + 18)
            y = panel.y + 64 + row * (row_h + 6)
            label = item.get("label") or order_id
            btn = Button(
                (x, y, col_w, 24),
                label,
                self.app.font_small,
                lambda oid=order_id: self.apply(oid),
            )
            self.buttons.append((btn, ORDER_HINTS.get(order_id, "")))

    def apply(self, order_id):
        rts = self.rts
        targets = rts._selected_dets()
        if not targets:
            rts._feedback("Сначала выберите подразделение", 1.5)
            return
        engine = self.app.engine
        explicit_target = rts._target_enemy_det()
        attack_orders = ("aggressive_attack", "attack", "cautious_attack")
        for det in targets:
            idx = engine.state.units.index(det)
            enemy = explicit_target or rts._nearest_enemy(det)
            engine.assign_order(idx, order_id)
            if order_id in attack_orders and enemy is not None:
                engine.set_focus_target(idx, enemy)
            elif order_id == "forced_march" and enemy is not None:
                engine.set_cell_target(idx, enemy.position)
                engine.set_focus_target(idx, enemy)
                det.ui_order = "forced_march"
        label = engine.order_table.label_of(order_id)
        rts._feedback("Приказ: %s" % label, 1.5)
        logger.info("Приказ из оверлея: %s, целей=%d", order_id, len(targets))
        self.app.manager.pop()

    def handle_event(self, event):
        for btn, _hint in self.buttons:
            if btn.handle_event(event):
                return
        if self.staff_btn.handle_event(event):
            return
        if self.close_btn.handle_event(event):
            return

    def draw(self, screen):
        self.draw_base(screen, "ПРИКАЗЫ ПОДРАЗДЕЛЕНИЯМ")
        panel = self.panel.rect
        selected = self.rts._selected_dets()
        names = ", ".join(det.name for det in selected) or "—"
        screen.blit(
            self.app.font_tiny.render(
                "Выбрано: %s" % names, True, (170, 185, 200)
            ),
            (panel.x + 20, panel.y + 42),
        )
        for btn, hint in self.buttons:
            btn.draw(screen)
            if hint:
                lines = wrap_text(
                    self.app.font_tiny, hint, btn.rect.width - 10
                )
                for j, line in enumerate(lines[:2]):
                    screen.blit(
                        self.app.font_tiny.render(line, True, (145, 158, 172)),
                        (btn.rect.x + 5, btn.rect.y + 27 + j * 12),
                    )
        screen.blit(
            self.app.font_tiny.render(
                "Совет: точку движения можно задать правым кликом по карте.",
                True,
                (150, 165, 180),
            ),
            (panel.x + 20, panel.bottom - 52),
        )
        self.staff_btn.draw(screen)
        self.close_btn.draw(screen)

    def update(self, dt):
        pass
