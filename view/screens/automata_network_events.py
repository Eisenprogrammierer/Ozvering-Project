"""Обработка событий экрана."""

from __future__ import annotations

from .automata_network_support import (
    CHARACTER_ROW_H,
    CHARACTER_VISIBLE,
    SIDE_RECT,
    pygame,
)


class AutomataNetworkEventsMixin:

    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL and self.mode == "characters":
            pos = pygame.mouse.get_pos()
            list_rect = pygame.Rect(
                SIDE_RECT.x + 14,
                SIDE_RECT.y + 104,
                SIDE_RECT.width - 28,
                CHARACTER_VISIBLE * CHARACTER_ROW_H,
            )
            if list_rect.collidepoint(pos):
                total = len(self._characters())
                self.character_scroll = max(
                    0,
                    min(
                        max(0, total - CHARACTER_VISIBLE),
                        self.character_scroll - event.y,
                    ),
                )
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        self._layout()
        pos = event.pos
        if self._back_rect.collidepoint(pos):
            self.app.manager.pop()
            return
        if self._speed_up_rect.collidepoint(pos):
            self._increase_speed()
            return
        if self._slow_down_rect.collidepoint(pos):
            self._decrease_speed()
            return
        if self._automata_tab_rect.collidepoint(pos):
            self.mode = "automata"
            self.selected_automaton_interaction_id = None
            self.selected_automaton_target_id = None
            self.message = ""
            return
        if self._organs_tab_rect.collidepoint(pos):
            self.mode = "organs"
            self.selected_automaton_interaction_id = None
            self.selected_automaton_target_id = None
            self.message = ""
            return
        if self._characters_tab_rect.collidepoint(pos):
            self.mode = "characters"
            self.selected_automaton_interaction_id = None
            self.selected_automaton_target_id = None
            self._sync_character_selection()
            self.message = ""
            return
        for organ_id, rect in self._organ_rects.items():
            if rect.collidepoint(pos):
                if (
                    self.mode == "automata"
                    and self.selected_automaton_interaction_id is not None
                ):
                    self.select_automaton_target(organ_id)
                else:
                    self.select_organ(organ_id)
                return
        # Строки персонажей и строки действий начинаются с одной и той же
        # высоты в правой панели. Поэтому клики по персонажам принимаются
        # только в режиме «ПЕРСОНАЛ», иначе «Усилить орган» и команды
        # автоматов перехватывались невидимым списком людей.
        if self.mode == "characters":
            for rect, character in self._character_rows():
                if rect.collidepoint(pos):
                    self.select_character(character["id"])
                    return
        for rect, option in self._interaction_rows():
            if rect.collidepoint(pos):
                if option.get("enabled"):
                    if self.mode == "characters":
                        self.select_character_interaction(option["id"])
                    elif self.mode == "automata":
                        self.select_automaton_interaction(option["id"])
                    else:
                        self.select_interaction(option["id"])
                else:
                    self.message = str(
                        option.get("reason") or "Недоступно."
                    )
                return
        if self._apply_rect.collidepoint(pos):
            self.apply_current()
