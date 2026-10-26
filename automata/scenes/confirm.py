"""Модальное подтверждение действия (удаление, несохранённые правки)."""

from __future__ import annotations

import pygame

from ui import theme, widgets
from ui.scene import Scene


class ConfirmScene(Scene):
    name = "confirm"
    overlay = True

    def on_enter(self, title="Подтверждение", message="", actions=None,
                 danger=False, note="", **kwargs):
        self.title = title
        self.message = message
        self.actions = list(actions or [("Закрыть", None)])
        self.danger = bool(danger)
        self.note = note

    def layout(self, w, h):
        self.widgets = []
        panel_w = min(640, w - 80)
        lines = theme.wrap(self.app.fonts.font, self.message, panel_w - 48)
        panel_h = 110 + max(1, len(lines)) * 22 + 60
        self.panel_rect = pygame.Rect(0, 0, panel_w, panel_h)
        self.panel_rect.center = (w // 2, h // 2)

        count = len(self.actions)
        button_w = min(190, (panel_w - 60 - (count - 1) * 10) // count)
        total = count * button_w + (count - 1) * 10
        x = self.panel_rect.centerx - total // 2
        y = self.panel_rect.bottom - 52
        for label, callback in self.actions:
            self.widgets.append(widgets.Button(
                label, (lambda cb=callback: self._fire(cb)),
                (x, y, button_w, 34)))
            x += button_w + 10

    def _fire(self, callback):
        self.app.pop()
        if callback is not None:
            callback()

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.app.pop()
            return True
        return super().handle_event(event)

    def draw(self, s):
        shade = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 155))
        s.blit(shade, (0, 0))
        theme.panel(s, self.panel_rect, fill=theme.BG_ALT,
                    border=theme.DANGER if self.danger else theme.BORDER,
                    radius=8)
        theme.text(s, self.app.fonts.font_b, self.title,
                   (self.panel_rect.left + 24, self.panel_rect.top + 18),
                   theme.DANGER if self.danger else theme.ACCENT)
        y = self.panel_rect.top + 56
        for line in theme.wrap(self.app.fonts.font, self.message,
                               self.panel_rect.width - 48):
            theme.text(s, self.app.fonts.font, line,
                       (self.panel_rect.left + 24, y), theme.TEXT)
            y += 22
        if self.note:
            theme.text(s, self.app.fonts.font_s, self.note,
                       (self.panel_rect.left + 24, y + 4),
                       theme.TEXT_MUTED)
        for widget in self.widgets:
            widget.draw(s, self.app.fonts)
