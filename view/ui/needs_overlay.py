from __future__ import annotations

import pygame

from .overlays import OverlayScreen
from .widgets import Button
from .text_layout import draw_fitted, wrap_text
from view.support.needs import (
    ACTION_ORDER,
    NEED_LABELS,
    NEED_SOURCES,
    PLAYER_NEED_ACTIONS,
    SUPPLY_LABELS,
)
from view.support.log_journal import get_logger

logger = get_logger("view.needs_ui")

NEED_ORDER = [
    "hunger",
    "thirst",
    "fatigue",
    "health",
    "fear",
    "anxiety",
    "loneliness",
    "reproduction",
    "knowledge",
    "creativity",
    "boredom",
    "status",
    "spirituality",
    "skill",
    "love",
    "friendship",
]


def _effect_text(effects):
    parts = []
    for need, value in (effects or {}).items():
        label = NEED_LABELS.get(need, need)
        sign = "+" if value >= 0 else ""
        parts.append("%s %s%.2f" % (label, sign, value))
    return ", ".join(parts)


class NeedsOverlay(OverlayScreen):

    def __init__(self, app, rts):
        super().__init__(app, (220, 40, 840, 640))
        self.rts = rts
        self.feedback = ""
        self._action_buttons = []
        self._build_actions()
        panel = self.panel.rect
        self.logistics_btn = Button(
            (panel.right - 330, panel.bottom - 38, 170, 28),
            "Логистика",
            self.app.font_tiny,
            self.open_logistics,
        )
        self.close_btn.text = "X"

    def _selected_idx(self):
        selected = getattr(self.rts, "selected", [])
        if selected:
            return selected[0]
        return self.app.engine.state.player_idx

    def _build_actions(self):
        panel = self.panel.rect
        x = panel.x + 440
        y = panel.y + 148
        for action_id in ACTION_ORDER:
            btn = Button(
                (x, y, 372, 34),
                PLAYER_NEED_ACTIONS[action_id]["label"],
                self.app.font_tiny,
                lambda aid=action_id: self.apply(aid),
            )
            self._action_buttons.append((action_id, btn))
            y += 42

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
        trait = needs_system.trait_info
        status_text = (
            "Личные потребности командира · мораль %.0f · черта: %s"
            % (
                getattr(needs_system.commander, "morale", 0.0),
                trait.get("label", "—"),
            )
        )
        draw_fitted(
            screen,
            [self.app.font_small, self.app.font_tiny],
            status_text,
            pygame.Rect(panel.x + 20, panel.y + 42, panel.width - 190, 18),
            (215, 225, 235),
            valign="center",
        )
        draw_fitted(
            screen,
            [self.app.font_tiny],
            trait.get("summary", ""),
            pygame.Rect(panel.x + 20, panel.y + 62, panel.width - 40, 16),
            (150, 165, 180),
            valign="center",
        )
        if getattr(needs_system, "player_dead", False):
            draw_fitted(
                screen,
                [self.app.font_tiny],
                "КОМАНДИР ПОГИБ",
                pygame.Rect(panel.right - 150, panel.y + 42, 130, 18),
                (224, 88, 88),
                align="right",
                valign="center",
            )
        draw_fitted(
            screen,
            [self.app.font_tiny],
            "0 — потребность удовлетворена, 1 — критическая. "
            "Подразделения обеспечивают себя сами.",
            pygame.Rect(panel.x + 20, panel.y + 80, panel.width - 40, 14),
            (140, 155, 168),
        )

        x0 = panel.x + 18
        y0 = panel.y + 100
        col_w = 198
        row_h = 56
        for i, need in enumerate(NEED_ORDER):
            col = i // 8
            row = i % 8
            x = x0 + col * (col_w + 8)
            y = y0 + row * row_h
            value = max(0.0, min(1.0, needs.get(need, 0.0)))
            color = (
                (96, 190, 120)
                if value < 0.35
                else (224, 164, 74) if value < 0.65 else (224, 88, 88)
            )
            draw_fitted(
                screen,
                [self.app.font_tiny],
                NEED_LABELS.get(need, need),
                pygame.Rect(x, y, col_w - 34, 14),
                (210, 220, 230),
            )
            screen.blit(
                self.app.font_tiny.render(
                    "%d" % round(value * 100), True, color
                ),
                (x + col_w - 24, y),
            )
            bar = pygame.Rect(x, y + 14, col_w - 2, 6)
            pygame.draw.rect(screen, (38, 46, 55), bar)
            pygame.draw.rect(
                screen,
                color,
                (bar.x, bar.y, int(bar.width * value), bar.height),
            )
            source_lines = wrap_text(
                self.app.font_tiny, NEED_SOURCES.get(need, ""), col_w - 2
            )
            for j, line in enumerate(source_lines[:2]):
                draw_fitted(
                    screen,
                    [self.app.font_tiny],
                    line,
                    pygame.Rect(x, y + 24 + j * 12, col_w - 2, 12),
                    (132, 148, 162),
                )

        rx = panel.x + 440
        screen.blit(
            self.app.font_small.render(
                "ЛИЧНЫЕ ДЕЙСТВИЯ", True, (205, 218, 230)
            ),
            (rx, panel.y + 98),
        )
        resources = " · ".join(
            "%s %d" % (SUPPLY_LABELS.get(k, k), int(v))
            for k, v in st.supplies.items()
            if k in ("food", "water", "medicine", "influence")
        )
        draw_fitted(
            screen,
            [self.app.font_tiny],
            resources,
            pygame.Rect(rx, panel.y + 118, 372, 14),
            (165, 178, 190),
        )
        status = needs_system.status_player()
        for action_id, btn in self._action_buttons:
            action_state = status.get(action_id, {})
            ax = btn.rect
            enabled = bool(action_state.get("ok"))
            pygame.draw.rect(
                screen,
                (25, 34, 44) if enabled else (25, 28, 32),
                ax,
                border_radius=4,
            )
            pygame.draw.rect(
                screen,
                (55, 76, 94) if enabled else (43, 48, 54),
                ax,
                1,
                border_radius=4,
            )
            label = action_state.get("label", action_id)
            draw_fitted(
                screen,
                [self.app.font_tiny],
                label,
                pygame.Rect(ax.x + 7, ax.y + 2, ax.width - 122, 14),
                (220, 228, 235) if enabled else (105, 112, 120),
                valign="center",
            )
            cooldown = action_state.get("cooldown", 0)
            if cooldown:
                right_text = "перезарядка %d мин" % max(1, int(cooldown) // 60)
                right_color = (200, 160, 90)
            elif not enabled:
                right_text = action_state.get("reason", "")
                right_color = (190, 120, 120)
            else:
                right_text = ""
                right_color = (150, 166, 179)
            if right_text:
                draw_fitted(
                    screen,
                    [self.app.font_tiny],
                    right_text,
                    pygame.Rect(ax.right - 112, ax.y + 2, 105, 14),
                    right_color,
                    align="right",
                    valign="center",
                )
            effects = _effect_text(action_state.get("effects"))
            cost = action_state.get("cost", {})
            cost_text = ", ".join(
                "%s:%d" % (SUPPLY_LABELS.get(k, k)[:4], v)
                for k, v in cost.items()
            )
            rare = cost_text + (" · " if cost_text else "")
            draw_fitted(
                screen,
                [self.app.font_tiny],
                rare + effects,
                pygame.Rect(ax.x + 7, ax.y + 16, ax.width - 14, 16),
                (150, 166, 179),
            )

        if self.feedback:
            draw_fitted(
                screen,
                [self.app.font_tiny],
                self.feedback,
                pygame.Rect(rx, panel.bottom - 100, 372, 16),
                (224, 185, 95),
            )
        draw_fitted(
            screen,
            [self.app.font_tiny],
            "Это только ваши потребности. Подразделения снабжаются "
            "автоматически через логистику.",
            pygame.Rect(panel.x + 20, panel.bottom - 70, panel.width - 40, 16),
            (140, 155, 168),
        )
        self.logistics_btn.draw(screen)
        self.close_btn.draw(screen)
