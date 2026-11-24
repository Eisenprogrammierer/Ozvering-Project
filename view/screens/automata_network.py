"""Экран сети органов и автоматов.

Класс ``AutomataNetworkScreen`` собран из миксинов по швам:
состояние, выбор, взаимодействия, события и отрисовка.
Публичный API экрана не менялся."""

from __future__ import annotations

from .automata_network_support import (
    ACCENT,
    BAD,
    BOTTOM_RECT,
    BaseScreen,
    CHARACTER_ROW_H,
    CHARACTER_VISIBLE,
    DETAIL_RECT,
    DIM,
    EDGE,
    GOOD,
    GRAPH_RECT,
    HEIGHT,
    INTERACTION_ROW_H,
    KIND_LABELS,
    MUTED,
    NEED_LABELS,
    NODE_GAP_Y,
    NODE_H,
    NODE_W,
    PANEL_BG,
    PANEL_BORDER,
    PATH_EDGE,
    ROOT_H,
    SIDE_RECT,
    TEXT,
    TRAIT_LABELS,
    WARN,
    WIDTH,
    _draw_bar,
    _integrity_color,
    _integrity_word,
    _money,
    _panel,
    cost_phrase,
    delta_phrase,
    draw_portrait,
    effect_phrase,
    fit_line,
    get_logger,
    logger,
    math,
    metric_phrase,
    organ_degrees,
    organ_links,
    pygame,
    share_phrase,
    wrap_text,
)

from .automata_network_core import AutomataNetworkCoreMixin
from .automata_network_selection import AutomataNetworkSelectionMixin
from .automata_network_actions import AutomataNetworkActionsMixin
from .automata_network_events import AutomataNetworkEventsMixin
from .automata_network_draw import AutomataNetworkDrawMixin


class AutomataNetworkScreen(
    AutomataNetworkCoreMixin,
    AutomataNetworkSelectionMixin,
    AutomataNetworkActionsMixin,
    AutomataNetworkEventsMixin,
    AutomataNetworkDrawMixin,
    BaseScreen,
):

    show_time_hud = False

    escape_action = "pop"

    def __init__(self, app, campaign):
        super().__init__(app)
        self.campaign = campaign
        self.mode = "automata"
        self.selected_faction_side = campaign.player_side
        self.campaign.ensure_clock()
        faction = self._faction()
        self.selected_organ_id = self._default_organ_id(faction)
        self.selected_interaction_id = None
        self.selected_automaton_interaction_id = None
        self.selected_automaton_target_id = None
        characters = self._characters()
        self.selected_character_id = (
            characters[0]["id"] if characters else None
        )
        self.selected_character_interaction_id = None
        self.character_scroll = 0
        self.message = ""
        self.last_result = None
        self._seen_process_result = None
        self._faction_rect = None
        self._organ_rects = {}
        self._character_rects = {}
        self._interaction_rects = []
        self._apply_rect = pygame.Rect(
            SIDE_RECT.x + 14,
            SIDE_RECT.bottom - 48,
            SIDE_RECT.width - 28,
            38,
        )
        self._back_rect = pygame.Rect(
            BOTTOM_RECT.right - 140, BOTTOM_RECT.y + 4, 130, 36
        )
        self._speed_up_rect = pygame.Rect(
            self._back_rect.x - 170, BOTTOM_RECT.y + 4, 160, 36
        )
        self._slow_down_rect = pygame.Rect(
            self._speed_up_rect.x - 150, BOTTOM_RECT.y + 4, 140, 36
        )
        self._automata_tab_rect = pygame.Rect(
            SIDE_RECT.x + 14, SIDE_RECT.y + 48, 118, 28
        )
        self._organs_tab_rect = pygame.Rect(
            SIDE_RECT.x + 140, SIDE_RECT.y + 48, 118, 28
        )
        self._characters_tab_rect = pygame.Rect(
            SIDE_RECT.x + 266, SIDE_RECT.y + 48, 124, 28
        )
        self._sync_storyline()
        slots = campaign.slot_state(campaign.player_side)
        logger.info(
            "Сеть автоматов: фракций=%d, выбран орган %s, слоты %d/%d",
            len(campaign.factions),
            self.selected_organ_id,
            slots["used"],
            slots["slots"],
        )


__all__ = ["AutomataNetworkScreen"]
