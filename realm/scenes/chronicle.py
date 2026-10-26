"""Хроника решений игрока."""

from __future__ import annotations

import pygame

from ui import theme
from ui.scene import Scene
from ui.widgets import Button

from .. import ui


class ChronicleScene(Scene):
    name = "chronicle"

    def on_enter(self, **kwargs):
        game = self.app.game
        self.entries = list(game.history) if game else []
        self.rows = []

    def layout(self, w, h):
        self.widgets = []
        self.rows = []
        top = 92
        bottom = h - 68
        row_h = 54
        gap = 6
        max_rows = max(1, (bottom - top + gap) // (row_h + gap))
        entries = self.entries[-max_rows:]
        for index, entry in enumerate(entries):
            self.rows.append((pygame.Rect(theme.EDGE,
                                          top + index * (row_h + gap),
                                          w - 2 * theme.EDGE, row_h),
                              entry))
        bw = 200
        self.widgets.append(Button("Назад", self.app.pop,
                                   ((w - bw) // 2, h - 58, bw, 42)))

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.pop()
            return True
        return super().handle_event(event)

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        theme.text(s, self.app.fonts.font_b, "ХРОНИКА", (theme.EDGE, 18),
                   ui.PARCHMENT)
        game = self.app.game
        subtitle = "Пока решений нет." if not self.entries else (
            "Записей: %d · мандат: %s" % (len(self.entries),
                                          game.mandate_title() if game else "—")
        )
        theme.text(s, self.app.fonts.font_s, subtitle, (theme.EDGE, 56),
                   theme.TEXT_DIM)
        pygame.draw.line(s, theme.BORDER, (theme.EDGE, 78),
                         (w - theme.EDGE, 78), 1)
        for rect, entry in self.rows:
            theme.panel(s, rect, fill=theme.BG_ALT, border=theme.BORDER,
                        radius=5)
            badge = pygame.Rect(rect.left + 10, rect.top + 10, 34, 24)
            theme.panel(s, badge, fill=theme.PANEL, border=theme.BORDER,
                        radius=4)
            theme.text(s, self.app.fonts.font_s, str(entry.get("week", "?")),
                       badge.center, theme.TEXT_DIM, center=True)
            title = "%s — %s" % (entry.get("petition_title", "?"),
                                 entry.get("option_label", "?"))
            theme.text(s, self.app.fonts.font_s, title,
                       (badge.right + 10, rect.top + 7), theme.TEXT)
            mode = ui.MODE_LABELS.get(entry.get("mode"),
                                      entry.get("mode", ""))
            support = "%d%%" % round(entry.get("support", 0.0) * 100)
            effects = ui.effect_text(entry.get("decision_effects"))
            event = entry.get("event") or {}
            second = "%s · совет %s · %s" % (mode, support, effects)
            if event.get("title"):
                second += " · событие: %s" % event["title"]
            theme.text(s, self.app.fonts.font_s, second,
                       (badge.right + 10, rect.top + 28), theme.TEXT_MUTED)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
