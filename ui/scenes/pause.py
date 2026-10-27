import pygame

from .. import theme, widgets
from ..scene import Scene


class PauseScene(Scene):
    name = "pause"
    overlay = True

    def layout(self, w, h):
        self.widgets = []
        items = [
            (self.app.t("Продолжить", "Resume"), self._resume),
            (
                self.app.t("Сохранить", "Save"),
                lambda: self.app.push("saves", mode="save"),
            ),
            (
                self.app.t("Настройки", "Settings"),
                lambda: self.app.push("settings"),
            ),
            (self.app.t("Главное меню", "Main menu"), self._menu),
        ]
        btn_w = min(360, w - 2 * theme.EDGE)
        title_h = 40
        info_h = 28
        panel_h = (
            theme.EDGE
            + title_h
            + theme.GAP
            + len(items) * theme.BTN_H
            + (len(items) - 1) * theme.GAP
            + theme.GAP
            + info_h
            + theme.EDGE
        )
        self.panel = pygame.Rect(0, 0, btn_w + 2 * theme.EDGE, panel_h)
        self.panel.center = (w // 2, h // 2)
        x = self.panel.left + theme.EDGE
        y = self.panel.top + theme.EDGE + title_h + theme.GAP
        for label, callback in items:
            self.widgets.append(
                widgets.Button(label, callback, (x, y, btn_w, theme.BTN_H))
            )
            y += theme.BTN_H + theme.GAP

    def _resume(self):
        self.app.pop()

    def _menu(self):
        game = self.app.manager.find("game")
        if game is not None and self.app.save.settings.get("autosave", True):
            self.app.save.autosave(game.save_data())
        self.app.go("menu")

    def draw(self, s):
        w, h = s.get_size()
        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 165))
        s.blit(dim, (0, 0))
        theme.panel(s, self.panel, fill=theme.PANEL, border=theme.ACCENT)
        theme.text(
            s,
            self.app.fonts.font_b,
            self.app.t("Пауза", "Paused"),
            (self.panel.centerx, self.panel.top + theme.EDGE + 18),
            theme.ACCENT,
            center=True,
        )
        game = self.app.manager.find("game")
        if game is not None and game.view is not None:
            m = game.view.match
            line = self.app.t(
                "такт %s из %s" % (m.step, getattr(m, "steps", "?")),
                "tick %s of %s" % (m.step, getattr(m, "steps", "?")),
            )
            theme.text(
                s,
                self.app.fonts.font_s,
                line,
                (self.panel.centerx, self.panel.bottom - 22),
                theme.TEXT_DIM,
                center=True,
            )
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
