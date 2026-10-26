"""Пауза поверх аудиенции."""

from __future__ import annotations

import pygame

from ui import theme
from ui.scene import Scene
from ui.widgets import Button


class PauseScene(Scene):
    name = "pause"
    overlay = True

    def layout(self, w, h):
        self.widgets = []
        bw = 300
        bh = 40
        gap = 8
        total = bh * 5 + gap * 4
        x = (w - bw) // 2
        y = (h - total) // 2 - 10
        self.panel_rect = pygame.Rect(x - 18, y - 52, bw + 36, total + 80)
        labels = [
            ("Продолжить", self.app.pop),
            ("Сохранить", lambda: self.app.open_saves("save")),
            ("Загрузить", lambda: self.app.open_saves("load")),
            ("Настройки", self.app.open_settings),
            ("В главное меню", self._menu),
        ]
        for label, callback in labels:
            self.widgets.append(Button(label, callback, (x, y, bw, bh)))
            y += bh + gap

    def _menu(self):
        self.app.go("menu")

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.pop()
            return True
        return super().handle_event(event)

    def draw(self, s):
        veil = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 165))
        s.blit(veil, (0, 0))
        theme.panel(s, self.panel_rect, fill=theme.BG_ALT,
                    border=theme.BORDER, radius=8)
        theme.text(s, self.app.fonts.font_b, "ПАУЗА",
                   (self.panel_rect.centerx, self.panel_rect.top + 18),
                   theme.ACCENT, center=True)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
