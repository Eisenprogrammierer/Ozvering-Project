"""Общие примитивы приложения: логгер, шрифты, адаптеры
сохранений и хост арены.

Выделены из ``view.app``, чтобы миксины приложения не
образовывали циклический импорт с фасадом."""

from __future__ import annotations

import os
import sys
import time
import pygame

from .support.log_journal import get_logger

SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60
BG_COLOR = (15, 15, 25)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


from .ui.screen_manager import BaseScreen


class _ArenaHostScreen(BaseScreen):
    """Хост дуэль-арены внутри менеджера экранов (ось B2).

    Оборачивает готовый `game_engine.GameApp` (создан с `screen=` нашего
    окна и `on_escape=self.app.manager.pop`) и проксирует ему кадры:
    события → `handle_events`, время → `update(dt)`, отрисовка → `draw()`.
    Собственного ввода не имеет; ESC обрабатывает сам движок.
    """

    escape_action = "none"
    hide_time_hud = True

    def __init__(self, app, arena):
        super().__init__(app)
        self.arena = arena

    def handle_event(self, event):
        try:
            self.arena.handle_events([event])
        except Exception as exc:
            logger.warning("Арена: ошибка события %s: %s", event.type, exc)

    def update(self, dt):
        try:
            self.arena.update(dt)
        except Exception as exc:
            logger.warning("Арена: ошибка update: %s", exc)

    def draw(self, screen):
        try:
            self.arena.draw(screen)
        except Exception as exc:
            logger.warning("Арена: ошибка draw: %s", exc)


class _AutomataSaveState:
    """Минимальный адаптер снимка автоматов к формату сохранения."""

    def __init__(self, snapshot):
        self.snapshot = dict(snapshot or {})

    def to_snapshot(self):
        return {"automata": self.snapshot}


class _WorldSaveState:
    """Адаптер свободного режима: состояние живёт в ``storyline.state``.

    ``WorldEngine`` не требует военной кампании, поэтому сохранение не
    должно требовать ``CampaignState``. Контейнер кампании помечает режим,
    а полный снимок мира лежит в ``storyline.state.world``.
    """

    def to_snapshot(self):
        return {"mode": "world"}


logger = get_logger("view.app")


def _find_first_valid_ttf():
    fonts_dir = os.path.normpath(
        os.path.join(BASE_DIR, "..", "assets", "fonts")
    )
    if not os.path.isdir(fonts_dir):
        return None
    for filename in sorted(os.listdir(fonts_dir)):
        if filename.lower().endswith(".ttf"):
            path = os.path.join(fonts_dir, filename)
            try:
                font = pygame.font.Font(path, 12)
                if font.render("Test", True, (255, 255, 255)) is not None:
                    return path
            except Exception:
                continue
    return None


pygame.font.init()


FONT_PATH = _find_first_valid_ttf()


def load_font(size):
    if FONT_PATH:
        try:
            return pygame.font.Font(FONT_PATH, size)
        except Exception:
            pass
    logger.warning("Шрифт не найден или не работает, использую встроенный")
    return pygame.font.Font(None, size)
