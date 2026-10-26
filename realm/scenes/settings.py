"""Настройки «Престола»: полный экран и автосохранение."""

from __future__ import annotations

import pygame

from ui import theme
from ui.scene import Scene
from ui.widgets import Button, Toggle


class SettingsScene(Scene):
    name = "settings"

    def on_enter(self, **kwargs):
        self.settings = self.app.save.settings

    def layout(self, w, h):
        self.widgets = []
        col_w = min(620, w - 2 * theme.EDGE)
        x = (w - col_w) // 2
        y = int(h * 0.22)
        row_h = 46
        gap = theme.GAP
        self.widgets.append(Toggle(
            "Полный экран", self.settings.get("fullscreen", False),
            lambda value: self.app.set_fullscreen(value)))
        self.widgets[-1].set_rect((x, y, col_w, row_h))
        y += row_h + gap
        self.widgets.append(Toggle(
            "Автосохранение после каждой недели",
            self.settings.get("autosave", True),
            lambda value: self.app.save.set_setting("autosave", value)))
        self.widgets[-1].set_rect((x, y, col_w, row_h))
        y += row_h + gap + 16
        bw = 220
        self.widgets.append(Button("Назад", self.app.pop,
                                   ((w - bw) // 2, y, bw, 42)))

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.pop()
            return True
        return super().handle_event(event)

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        theme.text(s, self.app.fonts.font_b, "НАСТРОЙКИ", (w // 2, 34),
                   theme.ACCENT, center=True)
        theme.text(s, self.app.fonts.font_s,
                   "saves/realm/settings.json · значения сохраняются сразу",
                   (w // 2, int(h * 0.16)), theme.TEXT_MUTED, center=True)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
