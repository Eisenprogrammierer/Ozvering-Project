"""Простые виджеты сценного слоя: кнопки, переключатели, слайдеры, подписи.

Виджеты мышино-ориентированы (клик = клавиша); клавиатурная навигация — задел
на будущее. Каждый виджет знает свой ``rect`` и умеет ``handle(e)`` / ``draw``.
"""

import pygame

from . import theme


class Widget:
    """Базовый виджет."""

    def __init__(self, rect=None):
        self.rect = pygame.Rect(rect or (0, 0, 0, 0))
        self.visible = True
        self.enabled = True
        self.hover = False

    def set_rect(self, rect):
        self.rect = pygame.Rect(rect)
        return self

    def handle(self, e):
        return False

    def draw(self, s, fonts):        # pragma: no cover - переопределяется
        pass


class Button(Widget):
    """Кнопка с подписью и колбэком."""

    def __init__(self, label, callback=None, rect=None, enabled=True, key=None):
        super().__init__(rect)
        self.label = label
        self.callback = callback
        self.key = key
        self.enabled = enabled
        self._pressed = False

    def handle(self, e):
        if not (self.visible and self.enabled):
            return False
        if e.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(e.pos)
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 \
                and self.rect.collidepoint(e.pos):
            self._pressed = True
            return True
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            fired = self._pressed and self.rect.collidepoint(e.pos)
            self._pressed = False
            self.hover = self.rect.collidepoint(e.pos)
            if fired:
                if self.callback is not None:
                    self.callback()
                return True
        return False

    def draw(self, s, fonts):
        if not self.visible:
            return
        fill = theme.PANEL_HI if self.enabled else theme.PANEL
        border = theme.BORDER
        if self.enabled and self.hover:
            fill = theme.mix(fill, theme.ACCENT, 0.20)
            border = theme.ACCENT
        if self.enabled and self._pressed:
            fill = theme.mix(fill, (0, 0, 0), 0.22)
        theme.panel(s, self.rect, fill=fill, border=border)
        theme.text(s, fonts.font, self.label, self.rect.center,
                   theme.TEXT if self.enabled else theme.TEXT_MUTED, center=True)


class Toggle(Widget):
    """Строка «подпись — флажок [x]/[ ]»."""

    def __init__(self, label, value=False, on_change=None, rect=None):
        super().__init__(rect)
        self.label = label
        self.value = bool(value)
        self.on_change = on_change

    def set_value(self, value):
        self.value = bool(value)

    def handle(self, e):
        if not (self.visible and self.enabled):
            return False
        if e.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(e.pos)
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 \
                and self.rect.collidepoint(e.pos):
            self.value = not self.value
            if self.on_change is not None:
                self.on_change(self.value)
            return True
        return False

    def draw(self, s, fonts):
        if not self.visible:
            return
        theme.panel(s, self.rect,
                    fill=theme.mix(theme.PANEL, theme.PANEL_HI, 0.35),
                    border=theme.ACCENT if self.hover else theme.BORDER)
        box = pygame.Rect(0, 0, 22, 22)
        box.midright = (self.rect.right - 12, self.rect.centery)
        theme.panel(s, box, fill=theme.BG_ALT, border=theme.BORDER, radius=4)
        if self.value:
            pygame.draw.line(s, theme.OK, (box.left + 4, box.centery),
                             (box.centerx - 1, box.bottom - 5), 3)
            pygame.draw.line(s, theme.OK, (box.centerx - 1, box.bottom - 5),
                             (box.right - 4, box.top + 4), 3)
        img = fonts.font.render(str(self.label), True, theme.TEXT)
        s.blit(img, img.get_rect(midleft=(self.rect.left + 12, self.rect.centery)))


class Slider(Widget):
    """Горизонтальный слайдер значения ``0..1``."""

    def __init__(self, label, value=0.5, on_change=None, rect=None, fmt=None):
        super().__init__(rect)
        self.label = label
        self.value = max(0.0, min(1.0, float(value)))
        self.on_change = on_change
        self.fmt = fmt or (lambda v: "%d%%" % int(round(v * 100)))
        self._drag = False

    def set_value(self, value):
        self.value = max(0.0, min(1.0, float(value)))

    def _track(self):
        # полоса занимает правые ~55% строки
        x0 = self.rect.left + int(self.rect.width * 0.45)
        return pygame.Rect(x0, self.rect.centery - 5,
                           self.rect.right - 12 - x0, 10)

    def _set_from_x(self, x):
        track = self._track()
        v = (x - track.left) / max(1, track.width)
        self.set_value(v)
        if self.on_change is not None:
            self.on_change(self.value)

    def handle(self, e):
        if not (self.visible and self.enabled):
            return False
        track = self._track()
        if e.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(e.pos)
            if self._drag:
                self._set_from_x(e.pos[0])
                return True
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 \
                and self.rect.collidepoint(e.pos):
            self._drag = True
            self._set_from_x(e.pos[0])
            return True
        if e.type == pygame.MOUSEBUTTONUP and e.button == 1 and self._drag:
            self._drag = False
            self._set_from_x(e.pos[0])
            return True
        return False

    def draw(self, s, fonts):
        if not self.visible:
            return
        theme.panel(s, self.rect,
                    fill=theme.mix(theme.PANEL, theme.PANEL_HI, 0.35),
                    border=theme.ACCENT if self._drag else theme.BORDER)
        img = fonts.font.render(str(self.label), True, theme.TEXT)
        s.blit(img, (self.rect.left + 12,
                     self.rect.centery - img.get_height() // 2))
        track = self._track()
        pygame.draw.rect(s, theme.BG_ALT, track, border_radius=5)
        knob_x = track.left + int(track.width * self.value)
        filled = pygame.Rect(track.left, track.top, knob_x - track.left, track.height)
        pygame.draw.rect(s, theme.ACCENT2, filled, border_radius=5)
        pygame.draw.circle(s, theme.TEXT, (knob_x, track.centery), 8)
        theme.text(s, fonts.font_s, self.fmt(self.value),
                   (self.rect.right - 12, self.rect.centery), theme.TEXT_DIM,
                   right=True)


class Label(Widget):
    """Статическая подпись (для единообразного списка виджетов)."""

    def __init__(self, value, rect=None, color=theme.TEXT, font="font",
                 align="left"):
        super().__init__(rect)
        self.value = value
        self.color = color
        self.font_attr = font
        self.align = align

    def draw(self, s, fonts):
        if not self.visible:
            return
        font = getattr(fonts, self.font_attr)
        img = font.render(str(self.value), True, self.color)
        if self.align == "center":
            s.blit(img, img.get_rect(center=self.rect.center))
        elif self.align == "right":
            s.blit(img, img.get_rect(midright=self.rect.midright))
        else:
            s.blit(img, img.get_rect(midleft=self.rect.midleft))


class Placeholder(Widget):
    """Плейсхолдер изображения (рамка с подписью), без обработки ввода."""

    def __init__(self, key, rect=None, caption="IMG"):
        super().__init__(rect)
        self.key = key
        self.caption = caption

    def draw(self, s, fonts):
        if self.visible:
            theme.draw_placeholder(s, self.rect, self.key, fonts,
                                   caption=self.caption)
