"""Вступительная новелла «Престола»."""

from __future__ import annotations

import pygame

from ui import theme
from ui.scene import Scene
from ui.widgets import Button

from .. import ui


class IntroScene(Scene):
    name = "intro"

    def on_enter(self, index=0, **kwargs):
        self.pages = list(self.app.content.story.get("intro", []))
        self.index = max(0, min(int(index), max(0, len(self.pages) - 1)))
        if not self.pages:
            self.app.go("council")
            return
        self.image_rect = pygame.Rect(0, 0, 0, 0)

    def layout(self, w, h):
        self.widgets = []
        pad = theme.EDGE
        top = 112
        img_w = int(w * 0.34)
        img_h = min(int(h * 0.46), 320)
        self.image_rect = pygame.Rect(pad, top, img_w, img_h)
        self.text_x = self.image_rect.right + pad * 2
        self.text_w = w - self.text_x - pad
        self.body_top = top + 54

        bw, bh = 170, theme.BTN_H
        total = bw * 3 + theme.GAP * 2
        x = (w - total) // 2
        y = h - 72
        last = self.index >= len(self.pages) - 1
        self.widgets.append(Button("Назад", self._prev,
                                   (x, y, bw, bh), enabled=self.index > 0))
        self.widgets.append(Button("Начать" if last else "Далее", self._next,
                                   (x + bw + theme.GAP, y, bw, bh)))
        self.widgets.append(Button("Пропустить", self._finish,
                                   (x + 2 * (bw + theme.GAP), y, bw, bh)))

    def _prev(self):
        if self.index > 0:
            self.index -= 1
            self.layout(*self.app.size)

    def _next(self):
        if self.index < len(self.pages) - 1:
            self.index += 1
            self.layout(*self.app.size)
        else:
            self._finish()

    def _finish(self):
        self.app.go("council")

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        page = self.pages[self.index]
        theme.text(s, self.app.fonts.font_s, "ПРОЛОГ",
                   (theme.EDGE, 24), theme.TEXT_MUTED)
        self.app.assets.draw(s, self.image_rect, page.get("image", "scene"),
                             self.app.fonts, caption="СЦЕНА")
        theme.text(s, self.app.fonts.font_b, page.get("title", ""),
                   (self.text_x, 112), ui.PARCHMENT)
        y = self.body_top
        for line in theme.wrap(self.app.fonts.font,
                               page.get("body", ""), self.text_w):
            theme.text(s, self.app.fonts.font, line, (self.text_x, y),
                       theme.TEXT)
            y += self.app.fonts.font.size("Ag")[1] + 5
        indicator = "%d / %d" % (self.index + 1, len(self.pages))
        theme.text(s, self.app.fonts.font_s, indicator,
                   (w // 2, h - 92), theme.TEXT_MUTED, center=True)
        theme.text(s, self.app.fonts.font_s,
                   "Совет уже ждёт. Карты поля боя в этой игре нет.",
                   (w // 2, h - 112), theme.TEXT_MUTED, center=True)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
