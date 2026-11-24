"""Общие константы и помощники экрана сети автоматов.

Выделены из ``view.screens.automata_network``, чтобы миксины
экрана не образовывали циклический импорт с фасадом."""

from __future__ import annotations

"""Сеть автоматов: сетка связанных органов и действия внутри неё.

Экран показывает только сеть игрока. Органы — равноправные узлы,
связанные данными ``links``; это не дерево подчинения. Поэтому видна
сеть кластеров (например, ``Панцерваффе ↔ Вермахт ↔ Имперская ставка``),
а чужие фракции нельзя выбрать или усилить.

В сети три режима действий:

* ``АВТОМАТЫ`` — выбранный узел отдаёт команду связанному автомату
  (согласование, передача резерва, директива соседу, запрос поддержки);
* ``ВЛИЯНИЕ`` — игрок усиливает, реформирует, чистит или снабжает узел;
* ``ПЕРСОНАЛ`` — влияние на людей своей фракции.

Работы, влияния и команды автоматов занимают один из двух слотов.
Запаса действий нет: пока слот занят, новое дело не начать.
Кампания идёт в реальном времени; ускорение можно включить и отменить,
но нельзя опуститься ниже ``1×`` или поставить паузу.
"""


import math
import pygame
from campaign.fractal import organ_degrees, organ_links
from ..ui.portraits import draw_portrait
from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import fit_line, wrap_text
from view.support.log_journal import get_logger
from view.support.metrics import (
    cost_phrase,
    delta_phrase,
    effect_phrase,
    metric_phrase,
    share_phrase,
)


logger = get_logger("view.automata_network")
WIDTH, HEIGHT = 1280, 720
GRAPH_RECT = pygame.Rect(24, 96, 812, 416)
DETAIL_RECT = pygame.Rect(24, 522, 812, 126)
SIDE_RECT = pygame.Rect(852, 96, 404, 552)
BOTTOM_RECT = pygame.Rect(24, 660, 1232, 44)
PANEL_BG = (18, 23, 33, 242)
PANEL_BORDER = (58, 70, 92)
TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
BAD = (226, 112, 112)
WARN = (230, 184, 96)
EDGE = (62, 78, 104)
PATH_EDGE = (78, 155, 224)
NODE_W = 148
NODE_H = 58
ROOT_H = 54
NODE_GAP_Y = 10
INTERACTION_ROW_H = 54
CHARACTER_ROW_H = 26
CHARACTER_VISIBLE = 5
KIND_LABELS = {
    "command": "командование",
    "coercion": "принуждение",
    "intelligence": "разведка",
    "information": "информация",
    "maintenance": "обеспечение",
    "legitimacy": "законность",
    "care": "забота",
    "meaning": "смысл",
    "exchange": "обмен",
    "support": "поддержка",
}
NEED_LABELS = {
    "hunger": "голод",
    "thirst": "жажда",
    "fatigue": "усталость",
    "health": "здоровье",
    "fear": "страх",
    "anxiety": "тревога",
    "loneliness": "одиночество",
    "reproduction": "близость",
    "knowledge": "знание",
    "creativity": "творчество",
    "boredom": "скука",
    "status": "статус",
    "spirituality": "вера",
    "skill": "навык",
    "love": "любовь",
    "friendship": "дружба",
}
TRAIT_LABELS = {
    "courage": "смелость",
    "discipline": "дисциплина",
    "aggression": "агрессия",
    "empathy": "эмпатия",
    "curiosity": "любопытство",
    "creativity": "творчество",
    "ambition": "амбиции",
    "spirituality": "вера",
    "sociability": "общительность",
    "loyalty": "лояльность",
    "fanaticism": "фанатизм",
    "endurance": "выносливость",
}


def _panel(surface, rect):
    shape = pygame.Surface(rect.size, pygame.SRCALPHA)
    shape.fill(PANEL_BG)
    surface.blit(shape, rect.topleft)
    pygame.draw.rect(surface, PANEL_BORDER, rect, 2, border_radius=8)


def _integrity_color(value):
    if value >= 0.65:
        return GOOD
    if value >= 0.35:
        return WARN
    return BAD


def _integrity_word(value):
    value = max(0.0, min(1.0, float(value)))
    if value >= 0.82:
        return "крепок"
    if value >= 0.58:
        return "в порядке"
    if value >= 0.32:
        return "держится"
    if value >= 0.12:
        return "повреждён"
    return "разрушен"


def _draw_bar(surface, rect, value, color):
    pygame.draw.rect(surface, (32, 39, 52), rect, border_radius=3)
    filled = rect.copy()
    filled.width = int(rect.width * max(0.0, min(1.0, float(value))))
    if filled.width > 0:
        pygame.draw.rect(surface, color, filled, border_radius=3)
    pygame.draw.rect(surface, PANEL_BORDER, rect, 1, border_radius=3)


def _money(cost):
    return ", ".join(
        cost_phrase(key, float(value))
        for key, value in (cost or {}).items()
    ) or "без цены"
