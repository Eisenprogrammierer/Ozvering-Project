"""Личные потребности командира и способы их удовлетворения.

Слева — все 16 потребностей персонажа игрока, их значения и подсказка,
какое действие или событие их снижает. Справа — личные действия командира
с эффектами, стоимостью и кулдауном. Подразделения в этом экране не
выбираются и не «кормятся» вручную: их самообеспечение выполняет
``LogisticsSystem`` автоматически.

Экран не вводит новой математики: он вызывает ``NeedsSystem.apply_player``
и показывает её состояние.
"""

from __future__ import annotations

import pygame

from .overlays import OverlayScreen
from .widgets import Button
from .text_layout import wrap_text
from view.support.needs import (
    ACTION_ORDER, NEED_LABELS, NEED_SOURCES, PLAYER_NEED_ACTIONS,
    SUPPLY_LABELS,
)
from view.support.log_journal import get_logger

logger = get_logger("view.needs_ui")

NEED_ORDER = [
    "hunger", "thirst", "fatigue", "health",
    "fear", "anxiety", "loneliness", "reproduction",
    "knowledge", "creativity", "boredom", "status",
    "spirituality", "skill", "love", "friendship",
]


def _effect_text(effects):
    parts = []
    for need, value in (effects or {}).items():
        label = NEED_LABELS.get(need, need)
        sign = "+" if value >= 0 else ""
        parts.append("%s %s%.2f" % (label, sign, value))
    return ", ".join(parts)


class NeedsOverlay(OverlayScreen):
    """Все личные потребности командира и действия по ним."""

    def __init__(self, app, rts):
        super().__init__(app, (220, 40, 840, 640))
        self.rts = rts
        self.feedback = ""
        self._action_buttons = []
        self._build_actions()
        panel = self.panel.rect
        self.logistics_btn = Button(
            (panel.right - 330, panel.bottom - 38, 170, 28),
            "Логистика", self.app.font_tiny, self.open_logistics,
        )
        self.close_btn.text = "X"

    def _selected_idx(self):
        """Оставлено для совместимости; действия больше не адресованы юниту."""
        selected = getattr(self.rts, "selected", [])
        if selected:
            return selected[0]
        return self.app.engine.state.player_idx

    def _build_actions(self):
        panel = self.panel.rect
        x = panel.x + 440
        y = panel.y + 178
        for action_id in ACTION_ORDER:
            btn = Button(
                (x, y, 372, 30),
                PLAYER_NEED_ACTIONS[action_id]["label"],
                self.app.font_tiny,
                lambda aid=action_id: self.apply(aid),
            )
            self._action_buttons.append((action_id, btn))
            y += 44

    def apply(self, action_id):
        result = self.app.engine.state.needs.apply_player(action_id)
        if result.get("ok"):
            self.feedback = "%s — выполнено" % (
                PLAYER_NEED_ACTIONS[action_id]["label"]
            )
        else:
            self.feedback = result.get("reason", "Недоступно")
        logger.info("Личная потребность: %s -> %s", action_id, self.feedback)

    def open_logistics(self):
        from .overlays import LogisticsOverlay
        self.app.manager.push(LogisticsOverlay(self.app))

    def handle_event(self, event):
        for _action_id, btn in self._action_buttons:
            if btn.handle_event(event):
                return
        if self.logistics_btn.handle_event(event):
            return
        if self.close_btn.handle_event(event):
            return

    def draw(self, screen):
        self.draw_base(screen, "ВАШИ ПОТРЕБНОСТИ · КОМАНДИР")
        panel = self.panel.rect
        st = self.app.engine.state
        needs_system = st.needs
        needs = needs_system.player_needs_summary()
        screen.blit(self.app.font_small.render(
            "Личные потребности командира · мораль %.0f" %
            getattr(needs_system.commander, "morale", 0.0),
            True, (215, 225, 235),
        ), (panel.x + 20, panel.y + 42))
        screen.blit(self.app.font_tiny.render(
            "0 — потребность удовлетворена, 1 — критическая. "
            "Подразделения обеспечивают себя сами.",
            True, (150, 165, 180),
        ), (panel.x + 20, panel.y + 64))

        # Левая колонка: 16 личных потребностей в две колонки.
        x0 = panel.x + 18
        y0 = panel.y + 92
        col_w = 198
        row_h = 58
        for i, need in enumerate(NEED_ORDER):
            col = i // 8
            row = i % 8
            x = x0 + col * (col_w + 8)
            y = y0 + row * row_h
            value = max(0.0, min(1.0, needs.get(need, 0.0)))
            color = ((96, 190, 120) if value < 0.35 else
                     (224, 164, 74) if value < 0.65 else (224, 88, 88))
            screen.blit(self.app.font_tiny.render(
                NEED_LABELS.get(need, need), True, (210, 220, 230)
            ), (x, y))
            screen.blit(self.app.font_tiny.render(
                "%d" % round(value * 100), True, color
            ), (x + col_w - 24, y))
            bar = pygame.Rect(x, y + 14, col_w - 2, 6)
            pygame.draw.rect(screen, (38, 46, 55), bar)
            pygame.draw.rect(
                screen, color,
                (bar.x, bar.y, int(bar.width * value), bar.height),
            )
            source_lines = wrap_text(
                self.app.font_tiny, NEED_SOURCES.get(need, ""), col_w - 2
            )
            for j, line in enumerate(source_lines[:2]):
                screen.blit(self.app.font_tiny.render(
                    line, True, (132, 148, 162)
                ), (x, y + 24 + j * 12))

        # Правая колонка: личные действия командира.
        rx = panel.x + 440
        screen.blit(self.app.font_small.render(
            "ЛИЧНЫЕ ДЕЙСТВИЯ", True, (205, 218, 230)
        ), (rx, panel.y + 92))
        resources = " · ".join(
            "%s %d" % (SUPPLY_LABELS.get(k, k), int(v))
            for k, v in st.supplies.items()
            if k in ("food", "water", "medicine", "influence")
        )
        screen.blit(self.app.font_tiny.render(
            resources, True, (165, 178, 190)
        ), (rx, panel.y + 112))
        status = needs_system.status_player()
        for action_id, btn in self._action_buttons:
            action_state = status.get(action_id, {})
            ax = btn.rect
            enabled = bool(action_state.get("ok"))
            pygame.draw.rect(screen, (25, 34, 44) if enabled else (25, 28, 32),
                             ax, border_radius=4)
            pygame.draw.rect(screen, (55, 76, 94) if enabled else (43, 48, 54),
                             ax, 1, border_radius=4)
            label = PLAYER_NEED_ACTIONS[action_id]["label"]
            screen.blit(self.app.font_tiny.render(
                label, True, (220, 228, 235) if enabled else (105, 112, 120)
            ), (ax.x + 7, ax.y + 3))
            if not enabled:
                reason = action_state.get("reason", "")
                if reason:
                    screen.blit(self.app.font_tiny.render(
                        reason[:40], True, (190, 120, 120)
                    ), (ax.right - 150, ax.y + 3))
            effects = _effect_text(PLAYER_NEED_ACTIONS[action_id].get("effects"))
            cost = PLAYER_NEED_ACTIONS[action_id].get("cost", {})
            cost_text = ", ".join(
                "%s:%d" % (SUPPLY_LABELS.get(k, k)[:4], v)
                for k, v in cost.items()
            )
            rare = cost_text + (" · " if cost_text else "")
            lines = wrap_text(
                self.app.font_tiny, rare + effects, ax.width - 16
            )
            if lines:
                screen.blit(self.app.font_tiny.render(
                    lines[0], True, (150, 166, 179)
                ), (ax.x + 7, ax.y + 16))
            cooldown = action_state.get("cooldown", 0)
            if cooldown:
                screen.blit(self.app.font_tiny.render(
                    "перезарядка %d мин" % max(1, int(cooldown) // 60),
                    True, (200, 160, 90),
                ), (ax.right - 110, ax.y + 16))

        if self.feedback:
            screen.blit(self.app.font_tiny.render(
                self.feedback, True, (224, 185, 95)
            ), (rx, panel.bottom - 62))
        screen.blit(self.app.font_tiny.render(
            "Это только ваши потребности. Подразделения снабжаются "
            "автоматически через логистику.",
            True, (140, 155, 168),
        ), (panel.x + 20, panel.bottom - 70))
        self.logistics_btn.draw(screen)
        self.close_btn.draw(screen)
