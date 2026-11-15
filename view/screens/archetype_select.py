"""Выбор стартового архетипа персонажа.

Архетип не заменяет мандат роли: роль отвечает за власть и фракцию,
архетип — за социальный слой, стартовые работы, акценты потребностей и
черты. Экран читает ``configs/characters/archetypes.json`` и не содержит
списка архетипов в коде.
"""

from __future__ import annotations

import pygame

from campaign.identity import IdentityError, load_archetypes_catalog

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import draw_fitted
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.archetype_select")

VISIBLE_ROWS = 6
BUTTON_WIDTH = 330
BUTTON_HEIGHT = 50
ROW_GAP = 62
LIST_X = 80
LIST_Y = 180
PREVIEW_RECT = (440, 160, 750, 420)
TEXT = (224, 229, 238)
MUTED = (150, 162, 180)
DIM = (108, 120, 138)
ACCENT = (80, 150, 220)

_FILTER_MODES = (
    ("all", "Все"),
    ("street", "Улица"),
    ("school", "Школа"),
    ("temple", "Храм"),
    ("court", "Двор"),
    ("market", "Рынок"),
    ("army", "Армия"),
)


class ArchetypeSelectScreen(BaseScreen):
    """Список архетипов с фильтром по социальному слою."""

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((60, 60, 1160, 600))
        self.filter_mode = "all"
        self.filter_order = [item[0] for item in _FILTER_MODES]
        self.scroll_offset = 0
        self.all_archetypes = []
        self.message = ""
        try:
            catalog = load_archetypes_catalog()
        except IdentityError as exc:
            catalog = None
            self.message = str(exc)
        if catalog is not None:
            self.all_archetypes = catalog.playable()
        self.archetypes = list(self.all_archetypes)
        selected = str(
            getattr(app, "selected_archetype_id", "") or ""
        )
        self.selected_id = (
            selected
            if any(item.id == selected for item in self.archetypes)
            else (self.archetypes[0].id if self.archetypes else None)
        )
        self._rebuild_buttons()
        self.filter_button = Button(
            (90, 116, 260, 32),
            "Фильтр: Все",
            app.font_small,
            self.next_filter,
        )
        self.clear_button = Button(
            (270, 610, 190, 40),
            "Без архетипа",
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
        logger.info(
            "Экран архетипов: всего=%d, фильтр=%s",
            len(self.all_archetypes),
            self.filter_mode,
        )

    def _rebuild_buttons(self):
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
                    self.app.font_body,
                    self._make_select_handler(index),
                )
            )

    def _make_select_handler(self, row_index):
        def handler():
            visible = self._visible()
            if row_index < len(visible):
                self.select(visible[row_index].id)
        return handler

    def _filtered(self):
        if self.filter_mode == "all":
            return list(self.all_archetypes)
        return [
            item
            for item in self.all_archetypes
            if item.social_layer == self.filter_mode
        ]

    def _visible(self):
        start = self.scroll_offset
        return self.archetypes[start:start + VISIBLE_ROWS]

    @property
    def current(self):
        if self.selected_id is None:
            return None
        return next(
            (
                item
                for item in self.archetypes
                if item.id == self.selected_id
            ),
            None,
        )

    def _clamp_scroll(self):
        max_offset = max(0, len(self.archetypes) - VISIBLE_ROWS)
        self.scroll_offset = max(0, min(self.scroll_offset, max_offset))

    def _scroll_to_selected(self):
        if self.selected_id is None:
            return
        index = next(
            (
                position
                for position, item in enumerate(self.archetypes)
                if item.id == self.selected_id
            ),
            None,
        )
        if index is None:
            return
        if index < self.scroll_offset:
            self.scroll_offset = index
        elif index >= self.scroll_offset + VISIBLE_ROWS:
            self.scroll_offset = index - VISIBLE_ROWS + 1
        self._clamp_scroll()

    def next_filter(self):
        try:
            index = self.filter_order.index(self.filter_mode)
        except ValueError:
            index = -1
        self.set_filter(
            self.filter_order[(index + 1) % len(self.filter_order)]
        )

    def set_filter(self, mode):
        if mode not in self.filter_order:
            return
        self.filter_mode = mode
        self.archetypes = self._filtered()
        self.scroll_offset = 0
        if not self.archetypes:
            self.selected_id = None
        elif self.current is None:
            self.selected_id = self.archetypes[0].id
        self._clamp_scroll()
        self.filter_button.label = "Фильтр: %s" % dict(
            _FILTER_MODES
        ).get(self.filter_mode, self.filter_mode)

    def select(self, archetype_id):
        if not any(item.id == archetype_id for item in self.archetypes):
            return
        self.selected_id = archetype_id
        self._scroll_to_selected()

    def select_next(self):
        if not self.archetypes:
            return
        ids = [item.id for item in self.archetypes]
        try:
            index = ids.index(self.selected_id)
        except ValueError:
            index = -1
        self.select(ids[(index + 1) % len(ids)])

    def select_previous(self):
        if not self.archetypes:
            return
        ids = [item.id for item in self.archetypes]
        try:
            index = ids.index(self.selected_id)
        except ValueError:
            index = 0
        self.select(ids[(index - 1) % len(ids)])

    def scroll_up(self):
        self.scroll_offset -= 1
        self._clamp_scroll()

    def scroll_down(self):
        self.scroll_offset += 1
        self._clamp_scroll()

    def clear(self):
        self.app.selected_archetype_id = ""
        self.app.selected_archetype_label = ""
        logger.info("Архетип сброшен")
        self.app.manager.pop()

    def apply(self):
        item = self.current
        self.app.selected_archetype_id = item.id if item else ""
        self.app.selected_archetype_label = item.label if item else ""
        logger.info(
            "Выбран архетип: %s",
            self.app.selected_archetype_id or "—",
        )
        self.app.manager.pop()

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_DOWN, pygame.K_s):
                self.select_next()
                return
            if event.key in (pygame.K_UP, pygame.K_w):
                self.select_previous()
                return
            if event.key == pygame.K_PAGEDOWN:
                self.scroll_down()
                return
            if event.key == pygame.K_PAGEUP:
                self.scroll_up()
                return
            if event.key == pygame.K_TAB:
                self.next_filter()
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.apply()
                return
            if event.key == pygame.K_ESCAPE:
                self.app.manager.pop()
                return
        if event.type == pygame.MOUSEWHEEL:
            if event.y > 0:
                self.scroll_up()
            elif event.y < 0:
                self.scroll_down()
            return
        if self.filter_button.handle_event(event):
            return
        visible = self._visible()
        for index, button in enumerate(self.buttons):
            if index >= len(visible):
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
            self.app.font_small.render("АРХЕТИП", True, MUTED),
            (x + 20, y + 16),
        )
        screen.blit(
            self.app.font_body.render(item.label, True, TEXT),
            (x + 20, y + 42),
        )
        draw_fitted(
            screen,
            [
                self.app.font_body,
                self.app.font_small,
                self.app.font_tiny,
            ],
            item.description or "Описание не задано.",
            (x + 20, y + 84, width - 40, height - 190),
            TEXT,
        )
        lines = [
            "Слой: %s" % (item.social_layer or "—"),
            "Сцены: %s" % (
                ", ".join(item.scenes) if item.scenes else "—"
            ),
            "Работы: %s" % (
                ", ".join(item.start_offices)
                if item.start_offices
                else "—"
            ),
            "Акценты: %s" % (
                ", ".join(item.priority_needs)
                if item.priority_needs
                else "—"
            ),
        ]
        for index, text in enumerate(lines):
            screen.blit(
                self.app.font_tiny.render(text, True, DIM),
                (x + 20, y + height - 96 + index * 18),
            )

    def _draw_scrollbar(self, screen):
        if len(self.archetypes) <= VISIBLE_ROWS:
            return
        track_x = LIST_X + BUTTON_WIDTH + 12
        track_y = LIST_Y
        track_h = VISIBLE_ROWS * ROW_GAP
        pygame.draw.rect(
            screen,
            (40, 48, 64),
            (track_x, track_y, 6, track_h),
            border_radius=3,
        )
        total = len(self.archetypes)
        thumb_h = max(24, int(track_h * VISIBLE_ROWS / total))
        max_offset = max(1, total - VISIBLE_ROWS)
        thumb_y = track_y + int(
            (track_h - thumb_h) * (self.scroll_offset / max_offset)
        )
        pygame.draw.rect(
            screen,
            ACCENT,
            (track_x, thumb_y, 6, thumb_h),
            border_radius=3,
        )

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_title.render(
            "Стартовый архетип", True, (220, 220, 230)
        )
        screen.blit(title, title.get_rect(center=(640, 94)))
        subtitle = self.app.font_small.render(
            "Кем был герой до власти? TAB — фильтр, ↑/↓ — выбор.",
            True,
            MUTED,
        )
        screen.blit(subtitle, subtitle.get_rect(center=(640, 132)))
        self.filter_button.draw(screen)
        if self.message:
            message = self.app.font_small.render(
                self.message, True, (220, 140, 140)
            )
            screen.blit(message, message.get_rect(center=(640, 350)))
        elif not self.archetypes:
            message = self.app.font_small.render(
                "Пока нет доступных архетипов", True, MUTED
            )
            screen.blit(message, message.get_rect(center=(640, 350)))
        visible = self._visible()
        for index, item in enumerate(visible):
            button = self.buttons[index]
            button.label = item.label
            button.draw(screen)
            if item.id == self.selected_id:
                pygame.draw.rect(
                    screen,
                    ACCENT,
                    button.rect,
                    2,
                    border_radius=8,
                )
        self._draw_scrollbar(screen)
        self._draw_preview(screen)
        note = self.app.font_tiny.render(
            "Каталог: configs/characters/archetypes.json",
            True,
            DIM,
        )
        screen.blit(note, note.get_rect(center=(640, 660)))
        self.clear_button.draw(screen)
        self.back_button.draw(screen)
        self.continue_button.draw(screen)


__all__ = ["ArchetypeSelectScreen", "VISIBLE_ROWS"]
