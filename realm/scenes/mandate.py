"""Выбор мандата номинального лидера."""

from __future__ import annotations

import pygame

from ui import theme
from ui.scene import Scene
from ui.widgets import Button, Widget

from .. import ui


class MandateCard(Widget):
    def __init__(self, mandate, rect, on_click, selected=False):
        super().__init__(rect)
        self.mandate = mandate
        self.on_click = on_click
        self.selected = selected

    def handle(self, e):
        if e.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(e.pos)
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 \
                and self.rect.collidepoint(e.pos):
            if self.on_click is not None:
                self.on_click(self.mandate["id"])
            return True
        return False

    def draw(self, s, fonts):
        border = ui.ROYAL if self.selected else theme.BORDER
        fill = theme.PANEL_HI if self.selected else theme.BG_ALT
        if self.hover and not self.selected:
            fill = theme.mix(fill, ui.ROYAL, 0.10)
            border = theme.mix(border, ui.ROYAL, 0.55)
        theme.panel(s, self.rect, fill=fill, border=border, radius=8)

        image = pygame.Rect(self.rect.left + 12, self.rect.top + 12,
                            self.rect.width - 24, 104)
        self.app_assets.draw(s, image, self.mandate.get("portrait", "mandate"),
                             fonts, caption="МАНДАТ")

        y = image.bottom + 10
        theme.text(s, fonts.font_b, self.mandate.get("title", "?"),
                   (self.rect.left + 14, y), ui.PARCHMENT)
        y += 30
        theme.text(s, fonts.font_s, self.mandate.get("subtitle", ""),
                   (self.rect.left + 14, y), theme.TEXT_MUTED)
        y += 24
        for line in theme.wrap(fonts.font_s, self.mandate.get("body", ""),
                               self.rect.width - 28):
            if y + 16 > self.rect.bottom - 92:
                break
            theme.text(s, fonts.font_s, line, (self.rect.left + 14, y),
                       theme.TEXT_DIM)
            y += 16
        y = self.rect.bottom - 84
        effects = ui.effect_text(self.mandate.get("effects", {}))
        theme.text(s, fonts.font_s, effects, (self.rect.left + 14, y),
                   ui.STEEL)
        y += 18
        for line in theme.wrap(fonts.font_s,
                               self.mandate.get("summary", ""),
                               self.rect.width - 28):
            if y + 15 > self.rect.bottom - 8:
                break
            theme.text(s, fonts.font_s, line, (self.rect.left + 14, y),
                       theme.TEXT_MUTED)
            y += 15
        if self.selected:
            mark = pygame.Rect(self.rect.right - 34, self.rect.top + 8, 24, 24)
            pygame.draw.circle(s, ui.ROYAL, mark.center, 10)
            theme.text(s, fonts.font_s, "✓", mark.center, theme.BG, center=True)


class MandateScene(Scene):
    name = "mandate"

    def on_enter(self, **kwargs):
        self.selected = None
        self.cards = []

    def layout(self, w, h):
        self.widgets = []
        self.cards = []
        top = 132
        bottom = h - 88
        gap = theme.GAP
        card_w = (w - 2 * theme.EDGE - 2 * gap) // 3
        card_h = bottom - top
        for index, mandate in enumerate(self.app.content.mandates):
            x = theme.EDGE + index * (card_w + gap)
            card = MandateCard(mandate, (x, top, card_w, card_h),
                               self._select, mandate["id"] == self.selected)
            card.app_assets = self.app.assets
            self.cards.append(card)
            self.widgets.append(card)

        bw = 220
        self.widgets.append(Button(
            "Начать", self._start, (w // 2 - bw - 10, h - 66, bw, 44),
            enabled=self.selected is not None))
        self.widgets.append(Button(
            "Назад", self.app.back, (w // 2 + 10, h - 66, bw, 44)))

    def _select(self, mandate_id):
        self.selected = mandate_id
        self.layout(*self.app.size)

    def _start(self):
        if self.selected:
            self.app.start_new_game(self.selected)

    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        theme.text(s, self.app.fonts.font_b, "МАНДАТ", (theme.EDGE, 22),
                   ui.PARCHMENT)
        theme.text(s, self.app.fonts.font_s,
                   "С чего начинается ваша номинальная власть?",
                   (theme.EDGE, 58), theme.TEXT_DIM)
        theme.text(s, self.app.fonts.font_s,
                   "Мандат меняет стартовые ресурсы и отношение совета. "
                   "Дальше — восемь аудиенций.",
                   (theme.EDGE, 82), theme.TEXT_MUTED)
        theme.text(s, self.app.fonts.font_s,
                   "Выберите карточку, затем нажмите «Начать».",
                   (w - theme.EDGE, 58), theme.TEXT_MUTED, right=True)
        for card in self.cards:
            card.draw(s, self.app.fonts)
        for wdg in self.widgets:
            if isinstance(wdg, MandateCard):
                continue
            wdg.draw(s, self.app.fonts)
