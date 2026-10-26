"""Финальный экран партии."""

from __future__ import annotations

import pygame

from ui import theme
from ui.scene import Scene
from ui.widgets import Button

from .. import ui


class EndingScene(Scene):
    name = "ending"

    def on_enter(self, **kwargs):
        game = self.app.game
        self.ending = (game.ending if game else None) or {
            "title": "Партия окончена",
            "body": "Фракция не пережила эту неделю.",
            "win": False,
        }

    def layout(self, w, h):
        self.widgets = []
        bw = 190
        gap = theme.GAP
        total = bw * 3 + gap * 2
        x = (w - total) // 2
        y = h - 68
        self.widgets.append(Button("Новая партия", self._new,
                                   (x, y, bw, 44)))
        self.widgets.append(Button("Хроника", self._chronicle,
                                   (x + bw + gap, y, bw, 44)))
        self.widgets.append(Button("В меню", self._menu,
                                   (x + 2 * (bw + gap), y, bw, 44)))

    def _new(self):
        self.app.go("mandate")

    def _chronicle(self):
        self.app.push("chronicle")

    def _menu(self):
        self.app.go("menu")

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._menu()
            return True
        return super().handle_event(event)

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        game = self.app.game
        win = bool(self.ending.get("win"))
        color = theme.OK if win else theme.DANGER
        theme.text(s, self.app.fonts.font_s,
                   "УСТАВ ЗАПЕЧАТАН" if win else "ФРАКЦИЯ ПОТЕРЯНА",
                   (w // 2, 26), color, center=True)
        theme.text(s, self.app.fonts.font_b, self.ending.get("title", ""),
                   (w // 2, 54), ui.PARCHMENT, center=True)
        image = pygame.Rect(0, 0, min(360, int(w * 0.32)), 150)
        image.midtop = (w // 2, 106)
        key = "ending_%s" % self.ending.get("id", "lost")
        if key not in ("ending_recognized", "ending_fragile",
                       "ending_puppet", "ending_lost"):
            key = "ending_lost"
        self.app.assets.draw(s, image, key, self.app.fonts, caption="ФИНАЛ")
        y = image.bottom + 18
        for line in theme.wrap(self.app.fonts.font,
                               self.ending.get("body", ""),
                               min(720, w - 2 * theme.EDGE)):
            theme.text(s, self.app.fonts.font, line, (w // 2, y),
                       theme.TEXT, center=True)
            y += self.app.fonts.font.size("Ag")[1] + 5
        if game is not None:
            y = max(y + 10, h - 150)
            stats = " · ".join(
                "%s %d" % (ui.STAT_LABELS[key], game.stats[key])
                for key in ("authority", "legitimacy", "unity", "unrest",
                            "treasury", "stores")
            )
            theme.text(s, self.app.fonts.font_s, stats, (w // 2, y),
                       theme.TEXT_DIM, center=True)
            theme.text(s, self.app.fonts.font_s,
                       "Мандат: %s · недель: %d · решений: %d"
                       % (game.mandate_title(), game.week - 1,
                          len(game.history)),
                       (w // 2, y + 22), theme.TEXT_MUTED, center=True)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
