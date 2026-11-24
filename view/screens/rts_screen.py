"""Экран легаси-RTS.

Класс ``RTSScreen`` собран из миксинов по швам: карта и
камера, приказы, тик, события и отрисовка. Публичный API
экрана не менялся."""

from __future__ import annotations

from .rts_screen_support import (
    BREACH_PRESSURE_TICKS,
    BaseScreen,
    Button,
    DAY_COLORS,
    GRID,
    HEIGHT,
    ISO_ORIGIN,
    LEFT_W,
    MAP_RECT,
    MAX_ZOOM,
    MIN_ZOOM,
    NEED_ORDER,
    NEED_SHORT,
    Particle,
    REAL_SECONDS_PER_GAME_MINUTE,
    RIGHT_W,
    RIGHT_X,
    SECTOR_LABELS,
    SECTOR_SHORT,
    SIDE_COLORS,
    SIDE_NAMES,
    SUPPLY_LABELS,
    TILE_H,
    TILE_W,
    TOP_H,
    WIDTH,
    ZOOM_STEP,
    draw_fitted,
    get_logger,
    logger,
    loss_limit_percent,
    math,
    pygame,
    random,
    wrap_text,
)

from .rts_screen_core import RTSScreenCoreMixin
from .rts_screen_commands import RTSScreenCommandsMixin
from .rts_screen_update import RTSScreenUpdateMixin
from .rts_screen_events import RTSScreenEventsMixin
from .rts_screen_draw import RTSScreenDrawMixin


class RTSScreen(
    RTSScreenCoreMixin,
    RTSScreenCommandsMixin,
    RTSScreenUpdateMixin,
    RTSScreenEventsMixin,
    RTSScreenDrawMixin,
    BaseScreen,
):

    show_time_hud = True

    hide_time_hud = True

    escape_action = "custom"

    def __init__(self, app):
        super().__init__(app)
        self.state = app.engine.state
        self.engine = app.engine
        interp = getattr(app, "storyline_interpreter", None)
        if interp is not None:
            get_variable = getattr(interp, "get_variable", None)
            if callable(get_variable):
                trait = get_variable("trait", None)
            else:
                trait = (getattr(interp, "variables", {}) or {}).get("trait")
            if trait:
                self.state.needs.set_commander_trait(trait)
        self.selected = []
        self.speed = 1
        self.paused = False
        self.finished = False
        self.zoom = 1.0
        self._zoom_anchor = self._base_project((GRID / 2.0, GRID / 2.0))
        self._zoom_cache = {}
        self._tick_accum = 0.0
        self._render_pos = {}
        self._render_anim = {}
        self._display_pos = {}
        self._moving = {}
        self._particles = []
        self._rng = random.Random(1701)
        self._drag_start = None
        self._drag_rect = None
        self._hover_idx = None
        self._target_enemy = None
        self._action_feedback = ""
        self._feedback_timer = 0.0

        self.groups = getattr(self.state, "groups", None)
        if not isinstance(self.groups, dict):
            self.groups = {i: [] for i in range(1, 7)}
            self.state.groups = self.groups
        self.active_group = None
        self._group_rects = [
            (number, pygame.Rect(42 + (number - 1) * 28, 285, 25, 14))
            for number in range(1, 7)
        ]
        self._last_loss_milestone = 0
        self._loss_warned_50 = False
        self._loss_warned_75 = False
        self._commander_rect = pygame.Rect(
            RIGHT_X + 10, 476, RIGHT_W - 20, 210
        )
        self._terrain = self._build_terrain()
        self._build_buttons()
        self._sync_render_positions(snap=True)
        self._update_display_positions()
        player = self._player_indices()
        if player:
            self.selected = [player[0]]
        self._feedback(
            "Противник наступает. Ctrl+A — все; C — осторожная атака; "
            "ПКМ по врагу — цель.",
            8.0,
        )
        logger.info(
            "RTS-экран открыт: отделений=%d, игрок=%s",
            self.state.count,
            self.selected,
        )
