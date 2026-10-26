"""Экран «Об игре»."""

from __future__ import annotations

import pygame

from ui import theme
from ui.scene import Scene
from ui.widgets import Button

from .. import ui


class AboutScene(Scene):
    name = "about"

    def on_enter(self, **kwargs):
        self.lines = list(self.app.content.story.get("about", []))
        self.help = list(self.app.content.story.get("help", []))

    def layout(self, w, h):
        self.widgets = []
        bw = 200
        self.widgets.append(Button("Назад", lambda: self.app.back("menu"),
                                   ((w - bw) // 2, h - 62, bw, 42)))

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.back("menu")
            return True
        return super().handle_event(event)

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        theme.text(s, self.app.fonts.font_b, "ОБ ИГРЕ", (theme.EDGE, 18),
                   ui.PARCHMENT)
        theme.text(s, self.app.fonts.font_s,
                   "Отдельная игра в репозитории: realm/ · без карты и приказов",
                   (theme.EDGE, 56), theme.TEXT_DIM)
        pygame.draw.line(s, theme.BORDER, (theme.EDGE, 80),
                         (w - theme.EDGE, 80), 1)
        y = 96
        for text in self.lines:
            for line in theme.wrap(self.app.fonts.font, text,
                                   w - 2 * theme.EDGE):
                theme.text(s, self.app.fonts.font, line,
                           (theme.EDGE, y), theme.TEXT)
                y += self.app.fonts.font.size("Ag")[1] + 5
            y += 8
        if self.help:
            y += 10
            theme.text(s, self.app.fonts.font_s, "УПРАВЛЕНИЕ",
                       (theme.EDGE, y), ui.STEEL)
            y += 22
            for text in self.help:
                for line in theme.wrap(self.app.fonts.font_s, text,
                                       w - 2 * theme.EDGE):
                    theme.text(s, self.app.fonts.font_s, line,
                               (theme.EDGE, y), theme.TEXT_MUTED)
                    y += 16
                y += 3
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
