"""Общие константы и помощники экрана дневного мира.

Выделены из ``view.screens.world_screen``, чтобы миксины
экрана не образовывали циклический импорт с фасадом."""

from __future__ import annotations

import pygame
from campaign.clock import CampaignClock, background_pause_reason
from campaign.free_clock import FreeClock
from campaign.relations import asymmetry_rows
from campaign.world import CHARACTER_CIRCLES, ORGANIZATION_CATEGORIES
from ..support import world_text
from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import wrap_text
from ..ui.world_art import WorldArt
from view.support.log_journal import get_logger


logger = get_logger("view.world")
WIDTH, HEIGHT = 1280, 720
HEADER_H = 92
MAIN_TAB_Y = 96
MAIN_TAB_H = 34
SUB_TAB_Y = 136
SUB_TAB_H = 28
CONTENT_Y = 170
CONTENT_BOTTOM = 660
LEFT_RECT = pygame.Rect(16, CONTENT_Y, 342, CONTENT_BOTTOM - CONTENT_Y)
MID_RECT = pygame.Rect(366, CONTENT_Y, 448, CONTENT_BOTTOM - CONTENT_Y)
CONTENT_RECT = pygame.Rect(
    16, CONTENT_Y, MID_RECT.right - LEFT_RECT.left, CONTENT_BOTTOM - CONTENT_Y
)
RIGHT_RECT = pygame.Rect(822, CONTENT_Y, 442, CONTENT_BOTTOM - CONTENT_Y)
BOTTOM_RECT = pygame.Rect(16, 668, 1248, 36)
LIST_ROW_H = 64
ACTION_ROW_H = 44
PANEL_BG = (16, 21, 31, 235)
PANEL_BG_SOFT = (20, 26, 38, 210)
PANEL_BORDER = (58, 70, 92)
TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
BAD = (226, 112, 112)
WARN = (230, 184, 96)
MAIN_TABS = (
    ("characters", "ПЕРСОНАЖИ"),
    ("organizations", "ОРГАНИЗАЦИИ"),
    ("norms", "НОРМЫ"),
    ("personality", "ЛИЧНОСТЬ"),
)
SUB_TABS = {
    "characters": (
        ("close", "Ближний круг"),
        ("companion", "Попутчики"),
        ("acquaintance", "Знакомства"),
    ),
    "organizations": (
        ("allied", "Союзные"),
        ("hostile", "Враждебные"),
        ("neutral", "Нейтральные"),
    ),
    "norms": (
        ("active", "Действующие"),
    ),
    "personality": (
        ("stats", "Характеристики"),
        ("skills", "Древо навыков"),
        ("items", "Предметы"),
    ),
}
