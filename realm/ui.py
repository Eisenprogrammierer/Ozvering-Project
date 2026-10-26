"""Виджеты и помощники рисования для «Престола».

Сценный слой переиспользует общие ``ui.theme``/``ui.widgets``/``ui.scene``,
но у новой игры своя палитра акцентов и карточки решений. Здесь нет логики
партии — только представление.
"""

from __future__ import annotations

import pygame

from ui import theme
from ui.widgets import Widget

# Дополнительные цвета: тёплый тронный акцент и холодная «канцелярия».
ROYAL = (164, 126, 214)
PARCHMENT = (222, 205, 167)
STEEL = (124, 154, 184)
BLOOD = (196, 86, 80)

STAT_LABELS = {
    "authority": "ВЛАСТЬ",
    "legitimacy": "ПРИЗНАНИЕ",
    "unrest": "СМУТА",
    "unity": "ЕДИНСТВО",
    "treasury": "КАЗНА",
    "stores": "ЗАПАСЫ",
}
STAT_COLORS = {
    "authority": ROYAL,
    "legitimacy": (116, 190, 150),
    "unrest": BLOOD,
    "unity": STEEL,
    "treasury": (226, 186, 92),
    "stores": (170, 190, 116),
}
MODE_LABELS = {
    "decree": "Проведено советом",
    "force": "Настоял своей властью",
    "defer": "Отложено",
}


def support_color(value):
    if value >= 0.5:
        return theme.OK
    if value >= 0.35:
        return theme.WARN
    return theme.DANGER


def trust_color(value):
    if value >= 65:
        return theme.OK
    if value >= 40:
        return theme.WARN
    return theme.DANGER


def stat_color(key):
    return STAT_COLORS.get(key, theme.TEXT_DIM)


def draw_bar(screen, rect, value, maximum=100, color=theme.ACCENT, bg=None):
    """Горизонтальная полоса значения."""
    rect = pygame.Rect(rect)
    pygame.draw.rect(screen, bg or theme.BG_ALT, rect, border_radius=4)
    ratio = 0.0 if not maximum else max(0.0, min(1.0, value / maximum))
    if ratio > 0:
        fill = pygame.Rect(rect.left, rect.top,
                           max(1, int(rect.width * ratio)), rect.height)
        pygame.draw.rect(screen, color, fill, border_radius=4)
    pygame.draw.rect(screen, theme.BORDER, rect, width=1, border_radius=4)


def draw_stat(screen, fonts, key, value, rect, max_value=100):
    rect = pygame.Rect(rect)
    color = stat_color(key)
    theme.text(screen, fonts.font_s, STAT_LABELS.get(key, key.upper()),
               (rect.left, rect.top), theme.TEXT_DIM)
    theme.text(screen, fonts.font_s, str(value), (rect.right, rect.top),
               color, right=True)
    draw_bar(screen, (rect.left, rect.top + 18, rect.width, 8), value,
             max_value, color)


def effect_text(effects):
    parts = []
    for key, value in (effects or {}).items():
        if not value:
            continue
        label = STAT_LABELS.get(key, key.upper())
        parts.append("%s %+d" % (label, int(value)))
    return ", ".join(parts) if parts else "без изменений"


def trust_text(effects, advisors):
    parts = []
    for key, value in (effects or {}).items():
        if not value:
            continue
        name = advisors.get(key, {}).get("name", key)
        parts.append("%s %+d" % (name, int(value)))
    return ", ".join(parts) if parts else "без изменений"


def wrap_lines(font, text, width):
    return theme.wrap(font, text, width)


def draw_text_block(screen, fonts, text, rect, color=theme.TEXT,
                    font=None, line_gap=3):
    """Нарисовать перенесённый текст и вернуть нижнюю границу."""
    rect = pygame.Rect(rect)
    font = font or fonts.font
    y = rect.top
    for line in theme.wrap(font, text, rect.width):
        if y + font.size("Ag")[1] > rect.bottom:
            break
        theme.text(screen, font, line, (rect.left, y), color)
        y += font.size("Ag")[1] + line_gap
    return y


class OptionCard(Widget):
    """Карточка варианта решения: кликабельна, показывает поддержку совета."""

    def __init__(self, option, index, support, on_click, rect=None,
                 selected=False, enabled=True):
        super().__init__(rect)
        self.option = option
        self.index = index
        self.support = float(support)
        self.on_click = on_click
        self.selected = bool(selected)
        self.enabled = bool(enabled)

    def handle(self, e):
        if not self.enabled:
            return False
        if e.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(e.pos)
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 \
                and self.rect.collidepoint(e.pos):
            if self.on_click is not None:
                self.on_click(self.option["id"])
            return True
        return False

    def draw(self, s, fonts):
        border = theme.BORDER
        fill = theme.BG_ALT if not self.selected else theme.PANEL_HI
        if self.hover:
            fill = theme.mix(fill, ROYAL, 0.12)
            border = theme.mix(border, ROYAL, 0.55)
        if self.selected:
            border = ROYAL
        theme.panel(s, self.rect, fill=fill, border=border, radius=6)

        badge = pygame.Rect(self.rect.left + 10, self.rect.top + 10, 28, 24)
        theme.panel(s, badge, fill=theme.PANEL if not self.selected else ROYAL,
                    border=theme.BORDER, radius=5)
        theme.text(s, fonts.font_s, str(self.index + 1), badge.center,
                   theme.TEXT, center=True)

        support_rect = pygame.Rect(self.rect.right - 76, self.rect.top + 10,
                                   64, 24)
        color = support_color(self.support)
        theme.panel(s, support_rect, fill=theme.BG_ALT, border=color, radius=5)
        theme.text(s, fonts.font_s, "%d%%" % round(self.support * 100),
                   (support_rect.centerx, support_rect.centery - 1),
                   color, center=True)

        text_x = badge.right + 10
        text_w = support_rect.left - text_x - 8
        theme.text(s, fonts.font, self.option.get("label", "?"),
                   (text_x, self.rect.top + 10), theme.TEXT)
        y = self.rect.top + 34
        for line in theme.wrap(fonts.font_s,
                               self.option.get("summary", ""), text_w):
            if y + 16 > self.rect.bottom - 6:
                break
            theme.text(s, fonts.font_s, line, (text_x, y), theme.TEXT_DIM)
            y += 16


class AdvisorRow(Widget):
    """Строка советника: имя, роль, доверие и прогноз голоса."""

    def __init__(self, advisor, rect=None, vote=None, stance=None):
        super().__init__(rect)
        self.advisor = advisor
        self.vote = vote
        self.stance = stance

    def draw(self, s, fonts, assets=None):
        theme.panel(s, self.rect, fill=theme.BG_ALT, border=theme.BORDER,
                    radius=5)
        side = min(42, self.rect.height - 10)
        portrait = pygame.Rect(self.rect.left + 8,
                               self.rect.centery - side // 2, side, side)
        if assets is not None:
            assets.draw_portrait(s, portrait,
                                 self.advisor.get("portrait", "portrait"),
                                 fonts)
        else:
            theme.draw_placeholder(s, portrait,
                                   self.advisor.get("portrait", "portrait"),
                                   fonts, caption="ПОРТРЕТ")
        text_x = portrait.right + 8
        theme.text(s, fonts.font_s, self.advisor.get("name", "?"),
                   (text_x, self.rect.top + 6), theme.TEXT)
        theme.text(s, fonts.font_s, self.advisor.get("role", ""),
                   (text_x, self.rect.top + 22), theme.TEXT_MUTED)
        trust = int(self.advisor.get("trust", 0))
        draw_bar(s, (text_x, self.rect.top + 38,
                     max(20, self.rect.width - (text_x - self.rect.left) - 30),
                     5), trust, 100, trust_color(trust))
        if self.vote is not None:
            mark = "✓" if self.vote else "×"
            color = theme.OK if self.vote else theme.DANGER
            theme.text(s, fonts.font_b, mark,
                       (self.rect.right - 14, self.rect.top + 6), color,
                       right=True)
        if self.stance is not None:
            theme.text(s, fonts.font_s, "%+.2f" % self.stance,
                       (self.rect.right - 8, self.rect.bottom - 16),
                       theme.TEXT_MUTED, right=True)


def draw_header(screen, fonts, title, right="", subtitle=""):
    w = screen.get_width()
    theme.text(screen, fonts.font_b, title, (theme.EDGE, 16), theme.ACCENT)
    if right:
        theme.text(screen, fonts.font, right, (w - theme.EDGE, 20),
                   theme.TEXT_DIM, right=True)
    if subtitle:
        theme.text(screen, fonts.font_s, subtitle, (theme.EDGE, 48),
                   theme.TEXT_MUTED)
    pygame.draw.line(screen, theme.BORDER, (theme.EDGE, 70),
                     (w - theme.EDGE, 70), 1)
