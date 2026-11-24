"""Общие константы, цвета и частицы экрана RTS.

Выделены из ``view.screens.rts_screen``, чтобы миксины экрана
не образовывали циклический импорт с фасадом."""

from __future__ import annotations

import math
import random
import pygame
from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button
from ..ui.text_layout import draw_fitted, wrap_text
from ..support.needs import SUPPLY_LABELS
from ..support.geometry import (
    BREACH_PRESSURE_TICKS,
    SECTOR_LABELS,
    SECTOR_SHORT,
)
from view.support.log_journal import get_logger
from view.support.storyline import loss_limit_percent


logger = get_logger("view.rts")
WIDTH, HEIGHT = 1280, 720
TOP_H = 58
LEFT_W = 236
RIGHT_X = 1004
RIGHT_W = WIDTH - RIGHT_X
MAP_RECT = pygame.Rect(LEFT_W, TOP_H, RIGHT_X - LEFT_W, HEIGHT - TOP_H)
GRID = 24
TILE_W = 32.0
TILE_H = 16.0
ISO_ORIGIN = (620, 112)
REAL_SECONDS_PER_GAME_MINUTE = 0.35
MIN_ZOOM = 0.70
MAX_ZOOM = 1.80
ZOOM_STEP = 0.15
SIDE_NAMES = {"red": "КРАСНЫЕ", "blue": "СИНИЕ"}
SIDE_COLORS = {"red": (211, 78, 78), "blue": (72, 138, 224)}
DAY_COLORS = {
    "bg": (13, 18, 24),
    "panel": (17, 24, 32),
    "panel2": (21, 30, 40),
    "line": (48, 66, 82),
    "text": (222, 230, 236),
    "muted": (144, 158, 170),
    "accent": (86, 154, 226),
    "player": (211, 78, 78),
    "enemy": (72, 138, 224),
    "ally_dark": (127, 46, 52),
    "enemy_dark": (36, 77, 130),
    "gold": (224, 185, 95),
    "good": (88, 190, 118),
    "warn": (224, 164, 74),
    "bad": (224, 88, 88),
}
NEED_SHORT = {
    "hunger": "Голод",
    "thirst": "Жажда",
    "fatigue": "Устал.",
    "health": "Здор.",
    "fear": "Страх",
    "anxiety": "Трев.",
    "loneliness": "Один.",
    "reproduction": "Репр.",
    "knowledge": "Знания",
    "creativity": "Творч.",
    "boredom": "Скука",
    "status": "Статус",
    "spirituality": "Духов.",
    "skill": "Умение",
    "love": "Любовь",
    "friendship": "Дружба",
}
NEED_ORDER = tuple(NEED_SHORT)


class Particle:

    __slots__ = (
        "kind",
        "x",
        "y",
        "tx",
        "ty",
        "vx",
        "vy",
        "life",
        "max_life",
        "color",
        "size",
        "angle",
    )

    def __init__(
        self,
        kind,
        x,
        y,
        tx=None,
        ty=None,
        life=0.3,
        color=(255, 220, 150),
        size=2,
        vx=0.0,
        vy=0.0,
        angle=0.0,
    ):
        self.kind = kind
        self.x = float(x)
        self.y = float(y)
        self.tx = float(tx if tx is not None else x)
        self.ty = float(ty if ty is not None else y)
        self.vx = float(vx)
        self.vy = float(vy)
        self.life = float(life)
        self.max_life = max(0.001, float(life))
        self.color = color
        self.size = size
        self.angle = angle

    def update(self, dt):
        self.life -= dt
        if self.kind in ("spark", "dust"):
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.vy += 80.0 * dt
        return self.life > 0

    def draw(self, surface):
        t = max(0.0, min(1.0, self.life / self.max_life))
        if self.kind == "tracer":
            progress = 1.0 - t
            px = self.x + (self.tx - self.x) * progress
            py = self.y + (self.ty - self.y) * progress

            tail = 0.22
            sx = self.x + (self.tx - self.x) * max(0.0, progress - tail)
            sy = self.y + (self.ty - self.y) * max(0.0, progress - tail)
            pygame.draw.line(
                surface, (255, 214, 130), (sx, sy), (px, py), max(1, self.size)
            )
            pygame.draw.circle(
                surface, (255, 244, 200), (int(px), int(py)), max(1, self.size)
            )
        elif self.kind == "muzzle":
            radius = int(7 + 10 * (1.0 - t))
            pygame.draw.circle(
                surface, self.color, (int(self.x), int(self.y)), radius, 2
            )
            for i in range(5):
                a = self.angle + i * math.tau / 5
                ex = self.x + math.cos(a) * radius * 1.7
                ey = self.y + math.sin(a) * radius * 1.7
                pygame.draw.line(
                    surface, self.color, (self.x, self.y), (ex, ey), 1
                )
        elif self.kind == "melee":
            radius = int(14 + 10 * (1.0 - t))
            rect = pygame.Rect(0, 0, radius * 2, radius * 2)
            rect.center = (int(self.x), int(self.y))
            pygame.draw.arc(
                surface, self.color, rect, self.angle, self.angle + 1.8, 3
            )
            pygame.draw.arc(
                surface,
                (255, 255, 255),
                rect,
                self.angle + 0.2,
                self.angle + 1.3,
                1,
            )
        elif self.kind == "spark":
            pygame.draw.circle(
                surface,
                self.color,
                (int(self.x), int(self.y)),
                max(1, int(self.size * t)),
            )
        elif self.kind == "dust":
            pygame.draw.circle(
                surface,
                self.color,
                (int(self.x), int(self.y)),
                max(1, int(self.size * t)),
            )
