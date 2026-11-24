"""Обработка событий и геометрия кнопок."""

from __future__ import annotations

from .world_screen_support import (
    BOTTOM_RECT,
    LEFT_RECT,
    MID_RECT,
    RIGHT_RECT,
    pygame,
)


class WorldScreenEventsMixin:

    def handle_event(self, event):
        if self.free_mode and event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.clock.slow_down()
                return
            if event.key in (
                pygame.K_EQUALS,
                pygame.K_PLUS,
                pygame.K_KP_PLUS,
            ):
                self.clock.speed_up()
                return
        if (
            not self.free_mode
            and event.type == pygame.KEYDOWN
            and event.key == pygame.K_a
        ):
            self._toggle_autopilot()
            return
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if LEFT_RECT.collidepoint(pos) and self.main_tab != "personality":
                rows = self._entity_rows()
                self.list_scroll = max(
                    0,
                    min(
                        self._max_entity_scroll(rows),
                        self.list_scroll - event.y,
                    ),
                )
            elif MID_RECT.collidepoint(pos) and self.main_tab != "personality":
                self.action_scroll = max(
                    0,
                    min(
                        self._max_action_scroll(),
                        self.action_scroll - event.y,
                    ),
                )
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        pos = event.pos
        if self.engine.finished:
            if self._finish_rect().collidepoint(pos):
                self._accept_outcome()
            return
        if not self.engine.attached:
            if self._office_rect().collidepoint(pos):
                self._choose_office()
            return
        if self.free_mode:
            if self._speed_down_rect().collidepoint(pos):
                self.clock.slow_down()
                return
            if self._speed_up_rect().collidepoint(pos):
                self.clock.speed_up()
                return
        if not self.free_mode and self._autopilot_rect().collidepoint(pos):
            self._toggle_autopilot()
            return
        if self._end_day_rect().collidepoint(pos):
            self._end_day()
            return
        for rect, tab in self.main_tab_rects:
            if rect.collidepoint(pos):
                self._set_main_tab(tab)
                return
        for rect, index in self.subtab_rects:
            if rect.collidepoint(pos):
                self._set_subtab(index)
                return
        if self._execute_rect().collidepoint(pos):
            self._execute_selected()
            return
        for rect, kind, entity_id in self.entity_rows:
            if not rect.collidepoint(pos):
                continue
            if kind == "character":
                self._select_character(entity_id)
            elif kind == "norm":
                self._select_norm(entity_id)
            else:
                self._select_target(entity_id)
            return
        for rect, option in self.action_rows:
            if rect.collidepoint(pos):
                self._select_action(option)
                return
        for rect, skill_id in self.skill_rows:
            if rect.collidepoint(pos):
                self._select_skill(skill_id)
                return
        for rect, item_id in self.item_rows:
            if rect.collidepoint(pos):
                self._select_item(item_id)
                return

    def _finish_rect(self):
        return pygame.Rect(BOTTOM_RECT.right - 210, BOTTOM_RECT.y + 3, 200, 30)

    def _end_day_rect(self):
        return pygame.Rect(BOTTOM_RECT.right - 210, BOTTOM_RECT.y + 3, 200, 30)

    def _autopilot_rect(self):
        return pygame.Rect(
            BOTTOM_RECT.right - 430, BOTTOM_RECT.y + 3, 210, 30
        )

    def _speed_down_rect(self):
        return pygame.Rect(
            BOTTOM_RECT.right - 400, BOTTOM_RECT.y + 3, 34, 30
        )

    def _speed_label_rect(self):
        return pygame.Rect(
            BOTTOM_RECT.right - 362, BOTTOM_RECT.y + 3, 220, 30
        )

    def _speed_up_rect(self):
        return pygame.Rect(
            BOTTOM_RECT.right - 138, BOTTOM_RECT.y + 3, 34, 30
        )

    def _office_rect(self):
        return pygame.Rect(BOTTOM_RECT.right - 210, BOTTOM_RECT.y + 3, 200, 30)

    def _execute_rect(self):
        return pygame.Rect(
            RIGHT_RECT.x + 14,
            RIGHT_RECT.y + 330,
            RIGHT_RECT.width - 28,
            38,
        )
