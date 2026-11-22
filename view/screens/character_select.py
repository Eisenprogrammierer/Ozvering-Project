"""Выбор управляемого персонажа внутри фракции (P2).

Экран не создаёт новую игру и не меняет баланс: он собирает пресет из
той же роли и того же seed, что и запуск, и показывает доступных
персонажей стороны игрока. По умолчанию игрок — лидер, но можно выбрать
любого `Character`; лидер фракции при этом остаётся лидером.
"""

from __future__ import annotations

import os

import pygame

from campaign import CampaignPresetGenerator
from warfare import NEEDS_RU
from view.support.log_journal import get_logger
from view.support.metrics import metric_word
from view.support.storyline import load_storyline

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import draw_fitted
from ..ui.widgets import Button, Panel

logger = get_logger("view.character_select")

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

VISIBLE_ROWS = 7
BUTTON_WIDTH = 360
BUTTON_HEIGHT = 54
ROW_GAP = 66
LIST_X = 80
LIST_Y = 172
PREVIEW_RECT = (470, 160, 720, 420)
TEXT = (224, 229, 238)
MUTED = (150, 162, 180)
DIM = (108, 120, 138)
ACCENT = (80, 150, 220)


class CharacterSelectScreen(BaseScreen):
    """Список персонажей стороны игрока с выбором аватара."""

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((60, 60, 1160, 600))
        self.role = getattr(app, "selected_role", None)
        self.storyline = None
        if self.role is not None and self.role.storyline_id:
            self.storyline = load_storyline(self.role.storyline_id)
        self.message = ""
        self.characters = []
        self.preset = None
        self._load_characters()
        selected = str(
            getattr(app, "selected_player_character_id", "") or ""
        )
        self.selected_id = (
            selected
            if any(item.get("id") == selected for item in self.characters)
            else (self.characters[0].get("id") if self.characters else None)
        )
        self.buttons = []
        for index in range(VISIBLE_ROWS):
            self.buttons.append(
                Button(
                    (
                        LIST_X,
                        LIST_Y + index * ROW_GAP,
                        BUTTON_WIDTH,
                        BUTTON_HEIGHT,
                    ),
                    "",
                    app.font_body,
                    self._make_select_handler(index),
                )
            )
        self.clear_button = Button(
            (270, 610, 190, 40),
            "Сбросить",
            app.font_small,
            self.clear,
        )
        self.back_button = Button(
            (80, 610, 160, 40),
            "Назад",
            app.font_body,
            app.manager.pop,
        )
        self.continue_button = Button(
            (1010, 610, 190, 40),
            "Продолжить",
            app.font_body,
            self.apply,
        )

    def _template_path(self):
        path = (self.storyline or {}).get("campaign_template")
        if path and not os.path.isabs(path):
            path = os.path.normpath(os.path.join(BASE_DIR, path))
        return path or None

    def _load_characters(self):
        if self.role is None or self.app.role_catalog is None:
            self.message = "Роль не выбрана."
            return
        if (self.storyline or {}).get("world_path"):
            self.message = (
                "В дневном мире герой создаётся в редакторе личности."
            )
            return
        try:
            self.preset = CampaignPresetGenerator(
                catalog=self.app.role_catalog,
                template_path=self._template_path(),
            ).generate(
                role_id=self.role.id,
                seed=self.app._campaign_seed(self.storyline or {}),
                player_faction_id=getattr(
                    self.app, "selected_faction_id", None
                ),
            )
        except Exception as exc:
            logger.error("Не удалось собрать пресет для выбора героя: %s", exc)
            self.message = "Не удалось собрать список героев."
            return
        self.characters = self.preset.available_player_characters()
        if not self.characters:
            self.message = "У фракции нет доступных персонажей."

    def _make_select_handler(self, row_index):
        def handler():
            if row_index < len(self.characters):
                self.select(self.characters[row_index].get("id"))
        return handler

    @property
    def current(self):
        if self.selected_id is None:
            return None
        return next(
            (
                item
                for item in self.characters
                if item.get("id") == self.selected_id
            ),
            None,
        )

    def select(self, character_id):
        if not any(
            item.get("id") == character_id for item in self.characters
        ):
            return
        self.selected_id = character_id

    def select_next(self):
        if not self.characters:
            return
        ids = [item.get("id") for item in self.characters]
        try:
            index = ids.index(self.selected_id)
        except ValueError:
            index = -1
        self.select(ids[(index + 1) % len(ids)])

    def select_previous(self):
        if not self.characters:
            return
        ids = [item.get("id") for item in self.characters]
        try:
            index = ids.index(self.selected_id)
        except ValueError:
            index = 0
        self.select(ids[(index - 1) % len(ids)])

    def clear(self):
        self.app.selected_player_character_id = ""
        self.app.selected_player_character_label = ""
        logger.info("Выбор героя сброшен: играет лидер")
        self.app.manager.pop()

    def apply(self):
        item = self.current
        if item is None:
            self.app.selected_player_character_id = ""
            self.app.selected_player_character_label = ""
        else:
            self.app.selected_player_character_id = str(item.get("id"))
            self.app.selected_player_character_label = str(
                item.get("name") or ""
            )
        logger.info(
            "Выбран герой: %s",
            self.app.selected_player_character_id or "лидер",
        )
        self.app.manager.pop()

    def _draw_preview(self, screen):
        pygame.draw.rect(
            screen, (16, 21, 31), PREVIEW_RECT, border_radius=8
        )
        pygame.draw.rect(
            screen, (58, 70, 92), PREVIEW_RECT, 2, border_radius=8
        )
        item = self.current
        if item is None:
            return
        x, y, width, height = PREVIEW_RECT
        screen.blit(
            self.app.font_small.render("ГЕРОЙ", True, MUTED),
            (x + 20, y + 16),
        )
        screen.blit(
            self.app.font_body.render(
                str(item.get("name") or "Без имени"), True, TEXT
            ),
            (x + 20, y + 42),
        )
        post = str(item.get("post") or "без должности")
        screen.blit(
            self.app.font_small.render(post, True, ACCENT),
            (x + 20, y + 78),
        )
        draw_fitted(
            screen,
            [
                self.app.font_small,
                self.app.font_tiny,
            ],
            "Архетип: %s" % (item.get("archetype") or "—"),
            (x + 20, y + 110, width - 40, 60),
            MUTED,
        )
        needs = item.get("needs") or {}
        top = sorted(
            (
                (float(value), str(key))
                for key, value in needs.items()
                if isinstance(value, (int, float))
            ),
            reverse=True,
        )[:4]
        need_text = ", ".join(
            "%s %s"
            % (
                NEEDS_RU.get(key, key),
                metric_word(NEEDS_RU.get(key, key), value),
            )
            for value, key in top
        )
        lines = [
            "Потребности: %s" % (need_text or "—"),
            "Лидер фракции: %s"
            % ("да" if item.get("is_faction_leader") else "нет"),
        ]
        for index, text in enumerate(lines):
            screen.blit(
                self.app.font_tiny.render(text, True, DIM),
                (x + 20, y + height - 56 + index * 20),
            )

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_DOWN, pygame.K_s):
                self.select_next()
                return
            if event.key in (pygame.K_UP, pygame.K_w):
                self.select_previous()
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.apply()
                return
            if event.key == pygame.K_ESCAPE:
                self.app.manager.pop()
                return
        for index, button in enumerate(self.buttons):
            if index >= len(self.characters):
                continue
            if button.handle_event(event):
                return
        for button in (
            self.clear_button,
            self.back_button,
            self.continue_button,
        ):
            if button.handle_event(event):
                return

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_title.render(
            "Кем играть?", True, (220, 220, 230)
        )
        screen.blit(title, title.get_rect(center=(640, 94)))
        subtitle = self.app.font_small.render(
            "Лидер остаётся лидером; вы выбираете, за кого видите мир.",
            True,
            MUTED,
        )
        screen.blit(subtitle, subtitle.get_rect(center=(640, 132)))
        if self.message:
            message = self.app.font_small.render(
                self.message, True, (220, 140, 140)
            )
            screen.blit(message, message.get_rect(center=(640, 350)))
        for index, item in enumerate(self.characters[:VISIBLE_ROWS]):
            button = self.buttons[index]
            button.text = "%s — %s" % (
                item.get("name") or "Без имени",
                item.get("post") or "без должности",
            )
            button.draw(screen)
            if item.get("id") == self.selected_id:
                pygame.draw.rect(
                    screen,
                    ACCENT,
                    button.rect,
                    2,
                    border_radius=8,
                )
        self._draw_preview(screen)
        self.clear_button.draw(screen)
        self.back_button.draw(screen)
        self.continue_button.draw(screen)


__all__ = ["CharacterSelectScreen", "VISIBLE_ROWS"]
