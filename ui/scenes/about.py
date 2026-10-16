"""Экран «об игре»: сведения о проекте и подсказки по управлению."""

import pygame

from .. import content, theme, widgets
from ..scene import Scene


class AboutScene(Scene):
    name = "about"

    def layout(self, w, h):
        self.widgets = []
        bw = min(220, w - 2 * theme.EDGE)
        self.widgets.append(widgets.Button(
            self.app.t("Назад", "Back"), self.app.back,
            ((w - bw) // 2, h - theme.EDGE - theme.BTN_H, bw, theme.BTN_H)))
        self.img_rect = pygame.Rect(theme.EDGE, int(h * 0.22),
                                    int(w * 0.28), int(h * 0.42))
        self.text_x = int(w * 0.36)
        self.text_w = w - self.text_x - theme.EDGE

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        theme.draw_title(s, self.app.fonts, self.app.t("Об игре", "About"),
                         w // 2, int(h * 0.06))
        theme.draw_placeholder(s, self.img_rect, "about_logo", self.app.fonts,
                               caption="LOGO")
        line_h = self.app.fonts.font.size("Ag")[1] + 4
        y = int(h * 0.22)
        for pair in content.ABOUT_LINES:
            for line in theme.wrap(self.app.fonts.font, self.app.t(*pair),
                                   self.text_w):
                theme.text(s, self.app.fonts.font, line, (self.text_x, y),
                           theme.TEXT)
                y += line_h
            y += 10
        y += 8
        theme.text(s, self.app.fonts.font_b,
                   self.app.t("Управление", "Controls"),
                   (self.text_x, y), theme.ACCENT2)
        y += line_h + 8
        small_h = self.app.fonts.font_s.size("Ag")[1] + 4
        for pair in content.HELP_LINES:
            for line in theme.wrap(self.app.fonts.font_s, self.app.t(*pair),
                                   self.text_w):
                theme.text(s, self.app.fonts.font_s, line, (self.text_x, y),
                           theme.TEXT_DIM)
                y += small_h
            y += 6
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
