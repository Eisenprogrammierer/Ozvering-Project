"""Экран дневного мира.

Класс ``WorldScreen`` собран из миксинов по швам: состояние и
выбор, события, общая отрисовка, карточки и прогноз, личность.
Публичный API экрана не менялся."""

from __future__ import annotations

from .world_screen_support import (
    ACCENT,
    ACTION_ROW_H,
    BAD,
    BOTTOM_RECT,
    BaseScreen,
    CHARACTER_CIRCLES,
    CONTENT_BOTTOM,
    CONTENT_RECT,
    CONTENT_Y,
    CampaignClock,
    DIM,
    FreeClock,
    GOOD,
    HEADER_H,
    HEIGHT,
    LEFT_RECT,
    LIST_ROW_H,
    MAIN_TABS,
    MAIN_TAB_H,
    MAIN_TAB_Y,
    MID_RECT,
    MUTED,
    ORGANIZATION_CATEGORIES,
    PANEL_BG,
    PANEL_BG_SOFT,
    PANEL_BORDER,
    RIGHT_RECT,
    SUB_TABS,
    SUB_TAB_H,
    SUB_TAB_Y,
    TEXT,
    WARN,
    WIDTH,
    WorldArt,
    asymmetry_rows,
    background_pause_reason,
    get_logger,
    logger,
    pygame,
    world_text,
    wrap_text,
)

from .world_screen_core import WorldScreenCoreMixin
from .world_screen_events import WorldScreenEventsMixin
from .world_screen_draw import WorldScreenDrawMixin
from .world_screen_detail import WorldScreenDetailMixin
from .world_screen_personality import WorldScreenPersonalityMixin


class WorldScreen(
    WorldScreenCoreMixin,
    WorldScreenEventsMixin,
    WorldScreenDrawMixin,
    WorldScreenDetailMixin,
    WorldScreenPersonalityMixin,
    BaseScreen,
):

    show_time_hud = False

    escape_action = "none"

    def __init__(self, app, engine, free_clock=None):
        super().__init__(app)
        self.engine = engine
        self.art = WorldArt(engine.config.get("id", "world"))
        self.free_mode = bool(getattr(engine, "realtime", False))
        self.main_tab = "organizations"
        self.subtab_index = {
            "characters": 0,
            "organizations": 0,
            "norms": 0,
            "personality": 0,
        }
        self.selected_target_id = self._initial_target_id(engine)
        self.selected_character_id = None
        self.selected_norm_id = None
        self.selected_skill_id = None
        self.selected_item_id = None
        self.action_context = "organization"
        self.selected_action_id = None
        self.selected_action_context = ""
        self.selected_action_option = None
        self.list_scroll = 0
        self.action_scroll = 0
        self.message = ""
        self.last_result = engine.last_result
        self.autopilot = False
        self.autopilot_policy = None
        self.autopilot_note = ""
        self.campaign_env = None
        self.autopilot_timer = 0.0
        self.autopilot_interval = 0.45
        self.clock = CampaignClock(
            seconds_per_day=engine.seconds_per_day,
            max_catchup_days=engine.max_offline_days,
            paused=True,
        )
        if self.free_mode:
            self.clock = free_clock or FreeClock(
                seconds_per_day=engine.seconds_per_day,
                max_catchup_days=engine.max_offline_days,
                speeds=getattr(engine, "time_speeds", None),
            )
        self.main_tab_rects = []
        self.subtab_rects = []
        self.entity_rows = []
        self.action_rows = []
        self.skill_rows = []
        self.item_rows = []
        self._overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self._overlay.fill((7, 10, 16, 150))
        self._sync_storyline()
        logger.info(
            "Экран мира: день=%d, узлов=%d, действий=%d, персонажей=%d",
            engine.day,
            len(engine.nodes),
            len(engine.actions),
            len(engine.characters),
        )


__all__ = ["WorldScreen"]
