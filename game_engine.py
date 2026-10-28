import math
import os
import subprocess
import sys
import time as _time_mod
import traceback


class _Logger:

    LEVELS = {"ERROR": 0, "WARN": 1, "INFO": 2, "DEBUG": 3}
    _TAGS = {0: "ERROR", 1: "WARN ", 2: "INFO ", 3: "DEBUG"}

    def __init__(self):
        try:
            raw = os.environ.get("GAME_LOG", "0").strip().lower()
        except Exception:
            raw = "0"
        if raw in ("v", "verbose"):
            lvl = 2
        elif raw in ("vv", "very_verbose", "all"):
            lvl = 3
        else:
            try:
                lvl = int(raw)
            except ValueError:
                lvl = 0
        self.level = max(0, min(3, lvl))
        self._t0 = _time_mod.perf_counter()
        self._sim_t = 0.0
        self._last_err = {}
        self._stream = None

    @property
    def stream(self):
        if self._stream is None:
            self._stream = sys.stderr
        return self._stream

    def set_sim_time(self, t):
        self._sim_t = t

    def log(self, level, msg, key=None, throttle=5.0):
        if level < self.level:
            return
        if key is not None and level == 0:
            now = _time_mod.perf_counter()
            if now - self._last_err.get(key, -1e9) < throttle:
                return
            self._last_err[key] = now
        try:
            line = "[game_engine %s] t=%7.3f | %s" % (
                self._TAGS[level],
                _time_mod.perf_counter() - self._t0,
                msg,
            )
            self.stream.write(line + "\n")
            self.stream.flush()
        except Exception:
            pass

    def error(self, msg, key=None, throttle=5.0):
        self.log(0, msg, key, throttle)

    def warn(self, msg):
        self.log(1, msg)

    def info(self, msg):
        self.log(2, msg)

    def debug(self, msg):
        self.log(3, msg)

    def exc(self, where, err, key=None):
        tb = "".join(
            traceback.format_exception(type(err), err, err.__traceback__)
        ).rstrip()
        self.error(
            "%s: %s: %s\n%s" % (where, type(err).__name__, err, tb),
            key=key,
            throttle=0.0,
        )


LOG = _Logger()


def _dump_stack(where="current stack"):
    LOG.debug(
        "%s:\n%s" % (where, "".join(traceback.format_stack()[:-1]).rstrip())
    )


_FONT_OK = False
_FONT_NOTE = ""


def _probe_font():
    global _FONT_OK, _FONT_NOTE
    LOG.debug("_probe_font(): проба подсистемы pygame.font")
    try:
        import pygame.font as _pf

        _pf.init()

        try:
            _pf.set_sdl_ttf_default(True)
            LOG.debug("set_sdl_ttf_default(True) применён (pygame-ce)")
        except Exception as e:
            LOG.debug("set_sdl_ttf_default недоступен: %s" % e)
        f = _pf.Font(None, 17)
        sz = f.size("A")
        LOG.debug("Font(None,17) создан, size('A')=%s" % (sz,))
        if sz[0] <= 0:
            raise RuntimeError("default font renders nothing")
        _FONT_OK = True
        LOG.info("шрифт OK: pygame.font рабочий (кириллица будет позже)")
        return f
    except Exception as e:
        _FONT_NOTE = str(e) or e.__class__.__name__
        _FONT_OK = False
        LOG.warn("шрифт НЕДОСТУПЕН: %s: %s" % (type(e).__name__, _FONT_NOTE))
        LOG.debug(
            "стек пробы шрифта:\n%s"
            % "".join(traceback.format_stack()[:-1]).rstrip()
        )
        return None


def _try_fix_freetype():
    try:
        import importlib.util

        if importlib.util.find_spec("pygame_ce") is not None:
            LOG.warn(
                "Найден pygame-ce. Для его использования "
                "удалите обычный pygame: pip uninstall -y pygame"
            )
            return
        LOG.debug("pygame-ce в окружении не найден")
    except Exception as e:
        LOG.debug("поиск pygame-ce не удался: %s" % e)
    try:
        code = (
            "import pygame.freetype, shutil; "
            "shutil.copy(pygame.freetype.get_default_font(), '.')"
        )
        LOG.debug("проба копирования шрифта из pygame.freetype...")
        r = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, timeout=5
        )
        LOG.debug(
            "проба freetype: rc=%s stderr=%r" % (r.returncode, r.stderr[:200])
        )
    except Exception as e:
        LOG.debug("проба freetype не удалась: %s" % e)


try:
    LOG.info(
        "запуск game_engine.py, python=%s, GAME_LOG=%s"
        % (sys.version.split()[0], os.environ.get("GAME_LOG", "0"))
    )
    import pygame

    LOG.info(
        "pygame импортирован: версия=%s SDL=%s"
        % (pygame.version.ver, pygame.get_sdl_version())
    )
except ImportError:
    LOG.error("PyGame НЕ установлен - импорт не удался")
    sys.stderr.write(
        "PyGame не установлен. Установите исправленную сборку:\n"
        "    pip uninstall -y pygame && pip install pygame-ce\n"
        "(обычный pygame 2.6.x на Python 3.14 собран с битым freetype - "
        "шрифты не работают)\n"
    )
    raise


try:
    from core41 import (
        ArenaMatch,
        CORE_ACTIONS as ACTIONS,
        CAPTURE_STREAK,
        DEFAULT_SPEED,
        HEALTH_CRITICAL,
        SICKNESS_MAX,
        SimulationClock,
        normalize_speed,
    )

    LOG.info(
        "core41 runtime импортирован: ACTIONS=%s"
        % ([a[0] for a in ACTIONS],)
    )
except Exception as e:
    LOG.exc("ИМПОРТ CORE41 RUNTIME НЕ УДАЛСЯ", e)
    raise

from agents import BDIPolicy, QTablePolicy, load_policy


def compute_window_size():
    base_w, base_h = 1024, 640
    dw = dh = 0
    try:
        info = pygame.display.Info()
        dw, dh = int(info.current_w), int(info.current_h)
    except Exception as exc:
        LOG.warn("compute_window_size: display.Info() недоступен (%s)" % exc)
    if dw < base_w or dh < base_h:
        return base_w, base_h
    avail_w = int(dw * 0.92)
    avail_h = int(dh * 0.90)
    w = min(avail_w, int(avail_h * 12 / 9))
    h = int(w * 9 / 12)
    w -= w % 2
    h -= h % 2
    return max(base_w, w), max(base_h, h)


def init_pygame_minimal():
    try:
        pygame.display.init()
    except Exception as exc:
        LOG.warn("pygame.display.init(): %s" % exc)
    try:
        import pygame.font as _pf

        _pf.init()
    except Exception as exc:
        LOG.debug("pygame.font.init(): %s" % exc)


def quit_pygame():
    try:
        pygame.display.quit()
    except Exception as exc:
        LOG.warn("pygame.display.quit(): %s" % exc)
    try:
        import pygame.font as _pf

        _pf.quit()
    except Exception as exc:
        LOG.debug("pygame.font.quit(): %s" % exc)


SCREEN_W, SCREEN_H = 1024, 640
PANEL_W = 300
FPS = 60
CRITICAL_HEALTH = HEALTH_CRITICAL


DEFENSE_COLORS = {
    "force": (220, 80, 50),
    "info": (70, 130, 220),
    "REST": (140, 140, 140),
    "FIRE": (220, 80, 50),
    "WATER": (70, 130, 220),
    "EARTH": (90, 170, 90),
}
ACTION_LABELS = {
    "force": "УДАР",
    "info": "ДАВЛЕНИЕ",
    "REST": "ПОКОЙ",
    "FIRE": "АТАКА-1",
    "WATER": "АТАКА-2",
    "EARTH": "АТАКА-3",
}
DEFENSE_LABELS = {
    "force": "F",
    "info": "I",
    "REST": "-",
    "FIRE": "A",
    "WATER": "B",
    "EARTH": "C",
}


def action_label(action):
    return ACTION_LABELS.get(action, str(action))


def defense_label(defense):
    return DEFENSE_LABELS.get(defense, "—")


COL_RL = (240, 240, 240)
COL_AI = (200, 160, 255)
COL_OPEN = (255, 220, 90)
COL_ENV_OPEN = (255, 200, 60)
COL_TEXT = (225, 225, 225)
COL_DIM = (140, 140, 140)
COL_PANEL = (24, 26, 32)
COL_BG_BASE = (16, 18, 24)


def agent_radius(force):
    return int(22 + 14 * math.log(max(1.0, force)))


def env_bg_color(env_force):
    t = min(1.0, max(0.0, (env_force - 10.0) / 400.0))
    r = COL_BG_BASE[0] + int(18 * t)
    g = COL_BG_BASE[1] + int(10 * t)
    b = COL_BG_BASE[2] + int(4 * t)
    return (r, g, b)


class Layout:

    EDGE = 10
    GAP = 12
    VGAP = 14
    BTN_ROWS, BTN_COLS = 4, 2
    TILE_ROWS, TILE_COLS = 2, 4
    CELL_GAP = 8

    def __init__(self, w, h, n_actions):
        self.w, self.h = w, h

        sc = max(1.0, min(1.6, w / 1440.0))
        self.sc = sc
        self.line_h = int(16 * max(1.0, sc * 0.85))
        self.cell_gap = max(6, int(self.CELL_GAP * min(1.2, sc)))

        E, G, VG = self.EDGE, self.GAP, self.VGAP

        width_a = int(max(PANEL_W, min(w * 0.26, PANEL_W * sc)))
        width_c = int(max(240, min(w * 0.24, 300 * sc)))

        if width_a + width_c + 3 * VG + 2 * E > w:
            width_c = max(220, w - width_a - 3 * VG - 2 * E)
        ax0 = E
        bx0 = ax0 + width_a + VG
        cx0 = bx0 + (w - 2 * E - 3 * VG - width_a - width_c) + VG
        col_b_w = cx0 - VG - bx0
        col_c_w = w - E - cx0
        self.width_a, self.width_c = width_a, col_c_w

        top = E
        bottom = h - E

        btn_area_h = int(
            max(44, 4 * (34 * max(1.0, sc * 0.9)) + 3 * self.cell_gap)
        )
        graph_h = int(max(110, min(h * 0.42, 260 * max(1.0, sc * 0.8))))
        cap_h = int(self.line_h * 2 + 10)
        c_avail = bottom - top

        scale_dn = min(
            1.0, (c_avail - 3 * G) / float(btn_area_h + graph_h + cap_h)
        )
        btn_area_h = max(44, int(btn_area_h * scale_dn))
        graph_h = max(90, int(graph_h * scale_dn))
        cap_h = max(self.line_h * 2 + 6, int(cap_h * scale_dn))

        graph_rect = pygame.Rect(cx0, bottom - graph_h, col_c_w, graph_h)
        caption_rect = pygame.Rect(
            cx0, graph_rect.top - G - cap_h, col_c_w, cap_h
        )
        btn_rect = pygame.Rect(
            cx0, top, col_c_w, max(44, caption_rect.top - G - top)
        )
        self.ctrl_rect = btn_rect
        self.hist_rect = graph_rect
        self.caption_rect = caption_rect

        names = [
            "START",
            "STEP",
            "SLOWER",
            "FASTER",
            "MODE",
            "RESET",
            "HELP",
            "QUIT",
        ]
        labels = [
            "START / PAUSE",
            "STEP 1 TICK",
            "SPEED <",
            "SPEED >",
            "MODE: OBS/MANUAL",
            "RESET MATCH",
            "HELP F1",
            "QUIT (ESC)",
        ]
        rows, cols = self.BTN_ROWS, self.BTN_COLS
        cg = self.cell_gap
        cw = (btn_rect.width - (cols - 1) * cg) // cols
        ch_max = int(34 * max(1.0, sc * 0.9))
        ch = max(24, min(ch_max, (btn_rect.height - (rows - 1) * cg) // rows))
        rects = []
        order = [
            ("START", 0, 0),
            ("STEP", 0, 1),
            ("SLOWER", 1, 0),
            ("FASTER", 1, 1),
            ("MODE", 2, 0),
            ("RESET", 2, 1),
            ("HELP", 3, 0),
            ("QUIT", 3, 1),
        ]
        by_name = {}
        for nm, rr, cc in order:
            r = pygame.Rect(
                btn_rect.x + cc * (cw + cg),
                btn_rect.y + rr * (ch + cg),
                cw,
                ch,
            )
            rects.append(r)
            by_name[nm] = r
        self.buttons = list(zip(names, labels, rects))
        (
            self.start_btn,
            self.step_btn,
            self.slow_btn,
            self.fast_btn,
            self.mode_btn,
            self.reset_btn,
            self.help_btn,
            self.quit_btn,
        ) = rects

        self.btn_cell_w, self.btn_cell_h = cw, ch

        tile_area_h = int(2 * (36 * max(1.0, sc * 0.9)) + self.cell_gap + 24)
        b_avail = bottom - top
        if b_avail - tile_area_h - G < 160:
            tile_area_h = max(80, b_avail - 160 - G)
        actions_rect = pygame.Rect(
            bx0, bottom - tile_area_h, col_b_w, tile_area_h
        )
        arena_rect = pygame.Rect(
            bx0, top, col_b_w, max(60, actions_rect.top - G - top)
        )
        self.actions_rect = actions_rect
        self.arena_rect = arena_rect

        trows, tcols = self.TILE_ROWS, self.TILE_COLS
        tcw = (actions_rect.width - (tcols - 1) * cg) // tcols
        tch = max(
            26,
            min(
                int(40 * max(1.0, sc * 0.9)),
                (actions_rect.height - 20 - (trows - 1) * cg) // trows,
            ),
        )
        tile_top = actions_rect.y + 18

        tw_max = int(150 * max(1.0, sc * 0.9))
        if tcw > tw_max:
            total_w = tcols * tw_max + (tcols - 1) * cg
            ox = actions_rect.x + max(0, (actions_rect.width - total_w) // 2)
            cw_ = tw_max
        else:
            ox, cw_ = actions_rect.x, tcw
        self.tile_rects = []
        for i in range(n_actions):
            rr, cc = divmod(i, tcols)
            self.tile_rects.append(
                pygame.Rect(
                    ox + cc * (cw_ + cg), tile_top + rr * (tch + cg), cw_, tch
                )
            )

        pick_row, pick_col = divmod(n_actions, tcols)
        self.pick_rect = pygame.Rect(
            ox + pick_col * (cw_ + cg),
            tile_top + pick_row * (tch + cg),
            cw_,
            tch,
        )
        self.tiles_label_y = actions_rect.y + 2
        self.tiles_bottom = tile_top + trows * tch + (trows - 1) * cg
        self.tile_cell_w, self.tile_cell_h = cw_, tch
        self.actions_grid_rows = trows

        self.help_x = actions_rect.x + 6
        self.help_y = actions_rect.y + 20
        self.help_rect = actions_rect
        self.help_line_dy = self.line_h

        a_avail = bottom - top
        card_min = int(84 * max(1.0, sc * 0.85))
        env_min = int(72 * max(1.0, sc * 0.85))
        status_min = int(64 * max(1.0, sc * 0.85))
        head_h = 46
        body_top = top + head_h
        body_h = max(120, bottom - body_top)
        need = 2 * card_min + env_min + status_min + 3 * G
        k = min(1.0, body_h / float(need))
        card_h = max(60, int(card_min * k))
        env_h = max(56, int(env_min * k))
        st_h = max(56, int(status_min * k))
        y_ = body_top
        self.rl_card = pygame.Rect(ax0, y_, width_a, card_h)
        y_ += card_h + G
        self.ai_card = pygame.Rect(ax0, y_, width_a, card_h)
        y_ += card_h + G
        self.env_card = pygame.Rect(ax0, y_, width_a, env_h)
        y_ += env_h + G
        self.status_zone = pygame.Rect(ax0, y_, width_a, max(40, bottom - y_))
        self.panel_rect = pygame.Rect(
            ax0 - 4, top - 4, width_a + 8, bottom - top + 8
        )
        self.head_rect = pygame.Rect(ax0, top, width_a, head_h - 6)
        self.card_h, self.env_h = card_h, env_h

        self.arena_cx = arena_rect.centerx
        self.arena_cy = arena_rect.centery
        sep = max(90, int(col_b_w * 0.19))
        self.rl_pos = (self.arena_cx - sep, self.arena_cy)
        self.ai_pos = (self.arena_cx + sep, self.arena_cy)
        self.env_label_pos = (self.arena_cx, arena_rect.y + 2)
        self.transfer_lbl_y = arena_rect.bottom - 46
        self.finish_dy = -int(arena_rect.height * 0.35)

        problems = []

        if not (self.panel_rect.right <= bx0 - VG + 4):
            problems.append("A->B")
        if not (cx0 - VG >= actions_rect.right - 4):
            problems.append("B->C")

        if btn_rect.bottom + 2 > caption_rect.top:
            problems.append("C1->C2")
        if caption_rect.bottom + 2 > graph_rect.top:
            problems.append("C2->C3")

        if actions_rect.top < arena_rect.bottom - 4:
            problems.append("B1->B2")

        for tr in self.tile_rects + [self.pick_rect]:
            pad = pygame.Rect(tr.x - 2, tr.y - 2, tr.w + 4, tr.h + 4)
            if pad.clamp(actions_rect) != pad:
                problems.append("tile-out-of-B2")
                break
        for br in rects:
            pad = pygame.Rect(br.x - 2, br.y - 2, br.w + 4, br.h + 4)
            if pad.clamp(btn_rect) != pad:
                problems.append("btn-out-of-C1")
                break
        if problems:
            LOG.warn(
                "Layout %dx%d: геометрические нарушения %s"
                % (w, h, set(problems))
            )

        LOG.debug(
            "Layout %dx%d: A(metrik) x=%d..%d cards=%d/%d/%d/%d | "
            "B arena y=%d..%d actions y=%d..%d tiles=%dx%d cell=%dx%d | "
            "C btns y=%d..%d grid %dx%d cell=%dx%d caption y=%d..%d "
            "graph y=%d..%d"
            % (
                w,
                h,
                ax0,
                ax0 + width_a,
                self.rl_card.height,
                self.ai_card.height,
                self.env_card.height,
                self.status_zone.height,
                arena_rect.top,
                arena_rect.bottom,
                actions_rect.top,
                actions_rect.bottom,
                trows,
                tcols,
                tcw,
                tch,
                btn_rect.top,
                btn_rect.bottom,
                rows,
                cols,
                cw,
                ch,
                caption_rect.top,
                caption_rect.bottom,
                graph_rect.top,
                graph_rect.bottom,
            )
        )


def parse_health_factors(text):
    factors = {}
    for part in str(text or "").split(","):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if not name:
            continue
        factors[name] = float(value)
    return factors


def _ai_policy(checkpoint, seed):
    if checkpoint:
        try:
            policy = load_policy(checkpoint, seed=seed)
            LOG.info("AI checkpoint загружен: %s" % checkpoint)
            return policy
        except Exception as exc:
            LOG.warn(
                "AI checkpoint %s не загружен (%r) - используется новая BDI"
                % (checkpoint, exc)
            )
    return BDIPolicy(seed=seed)


class MatchEngine:

    def __init__(
        self,
        seed=0,
        steps=2000,
        with_env=True,
        q_table=None,
        profile_rl="CANON",
        profile_ai="CANON",
        checkpoint="",
        health_factors=None,
        sickness=0.0,
    ):
        LOG.info(
            "MatchEngine: core41 runtime seed=%s steps=%s profiles=%s/%s"
            % (seed, steps, profile_rl, profile_ai)
        )
        self.seed = int(seed)
        self.steps_total = int(steps)
        self.with_env = bool(with_env)
        self.checkpoint = checkpoint or ""
        self.health_factors = dict(health_factors or {})
        self.sickness = max(0.0, min(SICKNESS_MAX, float(sickness)))
        self.core = ArenaMatch(
            seed=self.seed,
            steps=self.steps_total,
            rl_policy=QTablePolicy(seed=self.seed, table=q_table),
            ai_policy=_ai_policy(self.checkpoint, self.seed ^ 0xB01),
            profile_rl=profile_rl,
            profile_ai=profile_ai,
            health_factors_rl=self.health_factors,
            health_factors_ai=self.health_factors,
            sickness_rl=self.sickness,
            sickness_ai=self.sickness,
        )
        self.rl = self.core.rl
        self.ai = self.core.ai
        self.env = None

    @property
    def step(self):
        return self.core.step

    @property
    def winner(self):
        return self.core.winner

    @property
    def finished(self):
        return self.core.finished

    @property
    def events(self):
        return self.core.events

    @property
    def rl_hist(self):
        return self.core.rl_hist

    @property
    def ai_hist(self):
        return self.core.ai_hist

    @property
    def dom_rl(self):
        return self.core.dom_rl

    @property
    def dom_ai(self):
        return self.core.dom_ai

    @property
    def rl_rest_ticks(self):
        return self.core.rl_rest_ticks

    @property
    def ai_rest_ticks(self):
        return self.core.ai_rest_ticks

    @property
    def last_rl_action(self):
        return self.core.last_rl_action

    @property
    def last_ai_action(self):
        return self.core.last_ai_action

    def step_tick(self, forced_rl_action=None):
        if self.finished:
            LOG.debug(
                "step_tick: пропуск - партия уже завершена "
                "(winner=%s step=%s)" % (self.winner, self.step)
            )
            return
        self.core.step_tick(forced_rl_action=forced_rl_action)
        LOG.debug(
            "tick %s -> F(RL)=%.1f F(AI)=%.1f E(RL)=%.1f E(AI)=%.1f "
            "H(RL)=%.1f H(AI)=%.1f S(RL)=%.2f S(AI)=%.2f "
            "open(RL)=%s open(AI)=%s finished=%s"
            % (
                self.step,
                self.rl.force,
                self.ai.force,
                self.rl.energy_pool,
                self.ai.energy_pool,
                self.rl.health,
                self.ai.health,
                self.rl.sickness,
                self.ai.sickness,
                self.rl.in_open,
                self.ai.in_open,
                self.finished,
            )
        )


_GLYPHS_ASCII = {
    " ": ("...", "...", "...", "...", "..."),
    "!": ("#..", "#..", "#..", "...", "#.."),
    '"': ("##.", "##.", "...", "...", "..."),
    "%": ("#.#", ".#.", "#.#", ".#.", "#.#"),
    "(": ("..#", ".#.", ".#.", ".#.", "..#"),
    ")": ("#..", ".#.", ".#.", ".#.", "#.."),
    "*": ("#.#", ".#.", "###", ".#.", "#.#"),
    "+": ("...", ".#.", "###", ".#.", "..."),
    ",": ("...", "...", "...", ".#.", "#.."),
    "-": ("...", "...", "###", "...", "..."),
    ".": ("...", "...", "...", "...", "#.."),
    "/": ("..#", "..#", ".#.", "#..", "#.."),
    ":": ("...", ".#.", "...", ".#.", "..."),
    ";": ("...", ".#.", "...", ".#.", "#.."),
    "<": ("..#", ".#.", "#..", ".#.", "..#"),
    ">": ("#..", ".#.", "..#", ".#.", "#.."),
    "=": ("...", "###", "...", "###", "..."),
    "?": ("###", "..#", ".##", "...", ".#."),
    "[": ("###", "#..", "#..", "#..", "###"),
    "]": ("###", "..#", "..#", "..#", "###"),
    "_": ("...", "...", "...", "...", "###"),
    "|": ("#..", "#..", "#..", "#..", "#.."),
    "0": ("###", "#.#", "#.#", "#.#", "###"),
    "1": (".#.", "##.", ".#.", ".#.", "###"),
    "2": ("###", "..#", ".##", "#..", "###"),
    "3": ("###", "..#", ".##", "..#", "###"),
    "4": ("#.#", "#.#", "###", "..#", "..#"),
    "5": ("###", "#..", "###", "..#", "###"),
    "6": ("###", "#..", "###", "#.#", "###"),
    "7": ("###", "..#", "..#", ".#.", ".#."),
    "8": ("###", "#.#", "###", "#.#", "###"),
    "9": ("###", "#.#", "###", "..#", "###"),
    "A": ("###", "#.#", "###", "#.#", "#.#"),
    "B": ("###", "#.#", "##.", "#.#", "###"),
    "C": ("###", "#..", "#..", "#..", "###"),
    "D": ("##.", "#.#", "#.#", "#.#", "##."),
    "E": ("###", "#..", "###", "#..", "###"),
    "F": ("###", "#..", "###", "#..", "#.."),
    "G": ("###", "#..", "#.#", "#.#", "###"),
    "H": ("#.#", "#.#", "###", "#.#", "#.#"),
    "I": ("###", ".#.", ".#.", ".#.", "###"),
    "J": ("..#", "..#", "..#", "#.#", "###"),
    "K": ("#.#", "#.#", "##.", "#.#", "#.#"),
    "L": ("#..", "#..", "#..", "#..", "###"),
    "M": ("#.#", "###", "###", "#.#", "#.#"),
    "N": ("#.#", "###", "###", "###", "#.#"),
    "O": ("###", "#.#", "#.#", "#.#", "###"),
    "P": ("###", "#.#", "###", "#..", "#.."),
    "Q": ("###", "#.#", "#.#", "###", "..#"),
    "R": ("###", "#.#", "##.", "#.#", "#.#"),
    "S": ("###", "#..", "###", "..#", "###"),
    "T": ("###", ".#.", ".#.", ".#.", ".#."),
    "U": ("#.#", "#.#", "#.#", "#.#", "###"),
    "V": ("#.#", "#.#", "#.#", "#.#", ".#."),
    "W": ("#.#", "#.#", "###", "###", "#.#"),
    "X": ("#.#", "#.#", ".#.", "#.#", "#.#"),
    "Y": ("#.#", "#.#", ".#.", ".#.", ".#."),
    "Z": ("###", "..#", ".#.", "#..", "###"),
}


_CYR = {
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
    "Б": ("###", "#..", "##.", "#.#", "###"),
    "Г": ("###", "#..", "#..", "#..", "#.."),
    "Д": ("..#", ".##", "#.#", "#.#", "###"),
    "Ж": ("#.#", "###", ".#.", "###", "#.#"),
    "З": ("###", "..#", ".##", "..#", "###"),
    "И": ("#.#", "#.#", "###", "#.#", "#.#"),
    "Й": ("#.#", "#.#", "###", "#.#", "#.#"),
    "Л": (".##", ".#.", ".#.", "#.#", "###"),
    "П": ("###", "#.#", "#.#", "#.#", "#.."),
    "Ф": (".#.", "###", "#.#", "#.#", "###"),
    "Ц": ("#.#", "#.#", "#.#", "#.#", "###"),
    "Ч": ("#.#", "#.#", "###", "..#", "..#"),
    "Ш": ("#.#", "###", "###", "###", "#.#"),
    "Щ": ("#.#", "###", "###", "#.#", "###"),
    "Ъ": ("#..", "##.", "#.#", "#.#", "###"),
    "Ы": ("#.#", "#.#", "###", "#.#", "###"),
    "Ь": ("###", "#..", "###", "#.#", "###"),
    "Э": ("###", "..#", "#.#", "..#", "###"),
    "Ю": ("#.#", "###", "#.#", "#.#", "###"),
    "Я": ("###", ".#.", "###", "#.#", "###"),
    "Ё": ("###", "#.#", "###", "#..", "###"),
}
for _k, _v in _CYR.items():
    _GLYPHS_ASCII[_k] = _GLYPHS_ASCII[_v] if isinstance(_v, str) else _v
del _k, _v


_NORMALIZE = {
    "\u2014": "-",
    "\u2013": "-",
    "\u2212": "-",
    "\u00b7": ".",
    "\u00a0": " ",
    "\u2009": " ",
    "\u202f": " ",
    "\u201c": '"',
    "\u201d": '"',
    "\u00ab": '"',
    "\u00bb": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u2192": "->",
    "\u2190": "<-",
    "\u2194": "<->",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2248": "~",
    "\u2500": "-",
    "\u2502": "|",
    "\u250c": "+",
    "\u2510": "+",
    "\u2514": "+",
    "\u2518": "+",
    "\u25cf": "o",
    "\u25cb": "o",
    "\u25a0": "#",
    "\u25a1": "[]",
    "\u2713": "v",
    "\u2714": "v",
    "\u2717": "x",
    "\u2718": "x",
    "\u25b2": "^",
    "\u25b3": "^",
    "\u25bc": "v",
    "\u25bd": "v",
    "\u25c0": "<",
    "\u25c4": "<",
    "\u25b6": ">",
    "\u25ba": ">",
    "\u00d7": "x",
    "\u00f7": "/",
    "\u00b1": "+/-",
    "\u2260": "!=",
    "\u2026": "...",
    "\u2022": "*",
}
_INVISIBLE = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD], ""
)


def sanitize_text(text):
    for src, dst in _NORMALIZE.items():
        text = text.replace(src, dst)
    out = []
    for ch in text:
        o = ord(ch)
        if 32 <= o < 127 or 0x400 <= o <= 0x4FF or ch in _GLYPHS_ASCII:
            out.append(ch)
        elif o in _INVISIBLE:
            continue
        elif o > 127:
            out.append("?")
        else:
            out.append("?")
    return "".join(out)


GLYPHS = _GLYPHS_ASCII


class BitmapText:

    W, H = 3, 5
    SEP = 1

    def size(self, text):
        text = self._prep(text)
        lines = text.split("\n")
        w = max(
            (len(ln) * (self.W + self.SEP) - self.SEP for ln in lines),
            default=0,
        )
        h = len(lines) * (self.H + 2) - 2
        return max(w, 1), max(h, 1)

    @staticmethod
    def _prep(text):
        text = sanitize_text(text).upper()
        return "".join(ch if ch in GLYPHS else "?" for ch in text)

    def render(self, text, _antialias=True, color=(255, 255, 255), scale=1):
        text = self._prep(text)
        w, h = self.size(text)
        surf = pygame.Surface((w * scale, h * scale), pygame.SRCALPHA)
        x = 0
        y = 0
        for ch in text:
            if ch == "\n":
                x = 0
                y += self.H + 2
                continue
            g = GLYPHS[ch]
            for row_i, row in enumerate(g):
                for col_i, px in enumerate(row):
                    if px == "#":
                        pygame.draw.rect(
                            surf,
                            color,
                            (
                                x + col_i * scale,
                                y + row_i * scale,
                                scale,
                                scale,
                            ),
                        )
            x += (self.W + self.SEP) * scale
        return surf


class _SafePyFont:

    def __init__(self, font):
        self._f = font

    def render(self, text, _antialias=True, color=(255, 255, 255)):
        text = sanitize_text(str(text))
        try:
            surf = self._f.render(text, True, color)
        except Exception:
            surf = pygame.Surface((max(1, len(text) * 7), 14), pygame.SRCALPHA)
            pygame.draw.rect(surf, color, surf.get_rect(), 1)
        return surf

    def size(self, text):
        return self._f.size(sanitize_text(str(text)))


class FontSet:

    def __init__(self):
        self.pygame_font = None
        self.bitmap = BitmapText()
        self.cyrillic_ok = False
        self.note = ""

    @property
    def is_bitmap(self):
        return self.pygame_font is None

    def setup(self, probe):
        if probe is not None:
            import pygame.font as pf

            try:
                self.pygame_font = pf
                self._f_default = _SafePyFont(probe)
                self._f_small = _SafePyFont(pf.Font(None, 14))
                self._f_big = _SafePyFont(pf.Font(None, 24))
                self.cyrillic_ok = (
                    self._f_default.size("Я")[0] > 0
                    and self._f_default.render(
                        "Я", True, (255, 255, 255)
                    ).get_width()
                    > 0
                )
                return
            except Exception as e:
                self.note = str(e)
                self.pygame_font = None

        self.note = _FONT_NOTE or "pygame.font unavailable"

        self.cyrillic_ok = True

    class _Scaled:
        def __init__(self, base, scale):
            self.base = base
            self.scale = scale

        def render(self, text, _antialias=True, color=(255, 255, 255)):
            return self.base.render(text, True, color, scale=self.scale)

        def size(self, text):
            return tuple(v * self.scale for v in self.base.size(text))

    def _pick(self, name):
        if self.pygame_font is not None:
            return {
                "default": self._f_default,
                "small": self._f_small,
                "big": self._f_big,
            }[name]
        scale = {"default": 3, "small": 2, "big": 4}[name]
        return FontSet._Scaled(self.bitmap, scale)

    @property
    def font(self):
        return self._pick("default")

    @property
    def font_s(self):
        return self._pick("small")

    @property
    def font_b(self):
        return self._pick("big")


class GameApp:

    def __init__(
        self,
        fonts=None,
        screen=None,
        on_escape=None,
        seed=0,
        steps=2000,
        with_env=True,
        profile_rl="CANON",
        profile_ai="CANON",
        checkpoint="",
        health_factors=None,
        sickness=0.0,
        speed=DEFAULT_SPEED,
        auto_pause=True,
    ):
        LOG.info("GameApp: init_pygame_minimal() (video+font, без аудио)...")
        init_pygame_minimal()
        LOG.debug(
            "pygame минимально инициализирован; display=%s mixer=%s"
            % (pygame.display.get_init(), pygame.mixer.get_init())
        )
        global SCREEN_W, SCREEN_H
        self._owns_window = screen is None
        self.on_escape = on_escape
        self._fullscreen = False
        if self._owns_window:

            SCREEN_W, SCREEN_H = compute_window_size()
            flags = pygame.RESIZABLE

            if "--fullscreen" in sys.argv or "-f" in sys.argv:
                flags = pygame.FULLSCREEN
                self._fullscreen = True
                LOG.info(
                    "полноэкранный режим запрошен флагом %s"
                    % ("--fullscreen" if "--fullscreen" in sys.argv else "-f")
                )
            try:
                self.screen = pygame.display.set_mode(
                    (SCREEN_W, SCREEN_H), flags
                )
            except Exception as exc:
                LOG.warn(
                    "set_mode(%s,%s,flags=%s) не удался (%s) - оконный режим "
                    "12:9" % (SCREEN_W, SCREEN_H, flags, exc)
                )
                SCREEN_W, SCREEN_H = compute_window_size()
                self.screen = pygame.display.set_mode(
                    (SCREEN_W, SCREEN_H), pygame.RESIZABLE
                )
            pygame.display.set_caption("Ozvering-Project - IPO Arena (PyGame)")
            LOG.info(
                "окно создано: %sx%s driver=%s"
                % (SCREEN_W, SCREEN_H, pygame.display.get_driver())
            )
        else:

            self.screen = screen
            SCREEN_W, SCREEN_H = screen.get_size()
            LOG.info(
                "GameApp встроен в сценный слой: surface=%sx%s"
                % (SCREEN_W, SCREEN_H)
            )
        self.clock = pygame.time.Clock()

        self.fonts = fonts or FontSet()
        if self.fonts.pygame_font is None and not self.fonts.note:
            self.fonts.setup(_probe_font())
        self.cyrillic_ok = self.fonts.cyrillic_ok
        LOG.info(
            "шрифты: режим=%s кириллица=%s note=%r"
            % (
                "bitmap-fallback" if self.fonts.is_bitmap else "pygame.font",
                self.cyrillic_ok,
                self.fonts.note,
            )
        )
        self.font = self.fonts.font
        self.font_s = self.fonts.font_s
        self.font_b = self.fonts.font_b

        def L(ru, en):
            return ru if self.cyrillic_ok else en

        self.L = L

        self.clock = SimulationClock(speed=speed, auto_pause=auto_pause)
        self._critical_low = set()
        self.paused = True
        self.manual_mode = False
        self.show_help = True
        self.time = 0.0
        self._flash_until = 0.0
        self._btn_flash = ""

        self.layout = Layout(SCREEN_W, SCREEN_H, len(ACTIONS))
        self.buttons = self.layout.buttons

        self.q_table = {}
        self.game_seed = seed
        self.steps = steps
        self.with_env = with_env
        self.profile_rl = profile_rl
        self.profile_ai = profile_ai
        self.checkpoint = checkpoint or ""
        self.health_factors = dict(health_factors or {})
        self.sickness = max(0.0, min(SICKNESS_MAX, float(sickness)))
        self.match = MatchEngine(
            seed=self.game_seed,
            steps=steps,
            with_env=with_env,
            q_table=self.q_table,
            profile_rl=profile_rl,
            profile_ai=profile_ai,
            checkpoint=self.checkpoint,
            health_factors=self.health_factors,
            sickness=self.sickness,
        )

        self.action_idx = 0

        self.history_len = 240

        self._draw_count = 0
        self._err_counts = {}
        LOG.info(
            "GameApp: инициализация завершена (seed=%s, кнопок=%s)"
            % (self.game_seed, len(self.buttons))
        )

    @property
    def paused(self):
        return self.clock.paused

    @paused.setter
    def paused(self, value):
        self.clock.set_paused(value)

    @property
    def ticks_per_sec(self):
        return self.clock.ticks_per_sec

    @property
    def speed(self):
        return self.clock.speed

    @speed.setter
    def speed(self, value):
        self.clock.set_speed(value)

    def set_speed(self, value):
        speed = self.clock.set_speed(value)
        LOG.info("SPEED -> %s" % self.clock.label)
        self._btn_flash, self._flash_until = "SPEED", self.time + 0.35
        return speed

    def _maybe_auto_pause(self):
        if not self.clock.auto_pause:
            return False
        if self.match.finished:
            self.clock.pause("match_finished")
            LOG.info(
                "AUTO-PAUSE: партия завершена (winner=%s)"
                % self.match.winner
            )
            return True
        for side in ("rl", "ai"):
            agent = getattr(self.match, side)
            if agent.health > CRITICAL_HEALTH:
                self._critical_low.discard(side)
                continue
            if side in self._critical_low:
                continue
            self._critical_low.add(side)
            self.clock.pause("critical_health")
            LOG.warn(
                "AUTO-PAUSE: %s health=%.1f <= %.1f"
                % (side, agent.health, CRITICAL_HEALTH)
            )
            return True
        return False

    def _press(self, name):
        LOG.info("команда: %s (источник: клавиша/клик)" % name)
        if name == "QUIT":
            return False
        if name == "START":
            self.clock.toggle_pause()
            LOG.info(
                "START/PAUSE -> paused=%s speed=%s"
                % (self.paused, self.clock.label)
            )
            self._btn_flash, self._flash_until = "START", self.time + 0.35
        elif name == "STEP":
            if not self.match.finished:
                forced = self.action_idx if self.manual_mode else None
                LOG.debug(
                    "STEP: tick %s forced=%s manual=%s"
                    % (self.match.step, forced, self.manual_mode)
                )
                self.match.step_tick(forced_rl_action=forced)
                self._btn_flash, self._flash_until = "STEP", self.time + 0.35
            else:
                LOG.warn(
                    "STEP проигнорирован: партия завершена "
                    "(winner=%s) - нажмите RESET" % self.match.winner
                )
        elif name == "SLOWER":
            self.clock.slower()
            LOG.info(
                "SPEED -> %s (selected %sx)"
                % (self.clock.label, int(self.clock.selected_speed))
            )
            self._btn_flash, self._flash_until = "SPEED", self.time + 0.35
        elif name == "FASTER":
            self.clock.faster()
            LOG.info(
                "SPEED -> %s (selected %sx)"
                % (self.clock.label, int(self.clock.selected_speed))
            )
            self._btn_flash, self._flash_until = "SPEED", self.time + 0.35
        elif name == "MODE":
            self.manual_mode = not self.manual_mode
            LOG.info(
                "MODE -> %s"
                % ("MANUAL (игрок->RL)" if self.manual_mode else "OBSERVE")
            )
            self._btn_flash, self._flash_until = "MODE", self.time + 0.35
        elif name == "RESET":
            self.new_match()
            self._btn_flash, self._flash_until = "RESET", self.time + 0.35
        elif name == "HELP":
            self.show_help = not self.show_help
            LOG.info("HELP -> %s" % self.show_help)
        return True

    def handle_events(self, events=None):
        if events is None:
            events = list(pygame.event.get())
        for e in events:

            if e.type not in (pygame.MOUSEMOTION,):
                LOG.debug(
                    "событие: type=%s(%s) key=%s button=%s pos=%s"
                    % (
                        e.type,
                        pygame.event.event_name(e.type),
                        getattr(e, "key", "-"),
                        getattr(e, "button", "-"),
                        getattr(e, "pos", "-"),
                    )
                )
            if e.type == pygame.QUIT:
                LOG.info("получено SDL QUIT - закрытие окна")
                return False
            if e.type == pygame.VIDEORESIZE and not self._fullscreen:

                if not self._owns_window:

                    self.on_resize(*self.screen.get_size())
                    continue
                global SCREEN_W, SCREEN_H
                nw, nh = int(e.w), int(e.h)
                if (nw, nh) != (SCREEN_W, SCREEN_H):
                    SCREEN_W, SCREEN_H = nw, nh
                    self.screen = pygame.display.set_mode(
                        (SCREEN_W, SCREEN_H), pygame.RESIZABLE
                    )
                    try:
                        self.layout = Layout(SCREEN_W, SCREEN_H, len(ACTIONS))
                        self.buttons = self.layout.buttons
                        LOG.info(
                            "VIDEORESIZE -> %dx%d: Layout пересобран"
                            % (SCREEN_W, SCREEN_H)
                        )
                    except Exception as exc:
                        LOG.exc("Layout после resize", exc, key="resize")
                continue
            if e.type == pygame.KEYDOWN:
                k = e.key
                LOG.debug("KEYDOWN keycode=%s mod=%s" % (k, e.mod))
                if k in (pygame.K_ESCAPE, pygame.K_q):
                    if self.on_escape is not None:
                        LOG.info("клавиша ESC -> on_escape (сценный слой)")
                        self.on_escape()
                        return True
                    LOG.info("клавиша ESC/Q -> выход")
                    return False
                elif k == pygame.K_SPACE:
                    if not self._press("START"):
                        return False
                elif k == pygame.K_r:
                    self._press("RESET")
                elif k == pygame.K_m:
                    self._press("MODE")
                elif k in (pygame.K_F1, pygame.K_h):
                    self._press("HELP")
                elif k == pygame.K_TAB:
                    self._press("STEP")
                elif k in (
                    pygame.K_UP,
                    pygame.K_RIGHT,
                    pygame.K_PLUS,
                    pygame.K_KP_PLUS,
                    pygame.K_EQUALS,
                ):
                    self._press("FASTER")
                elif k in (
                    pygame.K_DOWN,
                    pygame.K_LEFT,
                    pygame.K_MINUS,
                    pygame.K_KP_MINUS,
                ):
                    self._press("SLOWER")
                elif pygame.K_1 <= k <= pygame.K_1 + len(ACTIONS) - 1:

                    self.action_idx = (k - pygame.K_1) % len(ACTIONS)
                    LOG.info(
                        "выбор действия клавишей: idx=%s act=%s%s"
                        % (
                            self.action_idx,
                            ACTIONS[self.action_idx][0],
                            (
                                " (включён РУЧНОЙ режим)"
                                if not self.manual_mode
                                else ""
                            ),
                        )
                    )
                    if not self.manual_mode:
                        self.manual_mode = True
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                hit = False
                for name, _label, rect in self.buttons:
                    if rect.collidepoint(e.pos):
                        hit = True
                        LOG.debug(
                            "клик (%s,%s) -> кнопка %s"
                            % (e.pos[0], e.pos[1], name)
                        )
                        if not self._press(name):
                            return False
                        break
                if not hit:
                    idx = self._action_at_mouse(e.pos)
                    if idx is not None:
                        LOG.debug(
                            "клик (%s,%s) -> плитка действия idx=%s act=%s"
                            % (e.pos[0], e.pos[1], idx, ACTIONS[idx][0])
                        )
                        self.action_idx = idx
                        if not self.manual_mode:
                            LOG.info("клик по плитке -> включён РУЧНОЙ режим")
                            self.manual_mode = True
                    else:
                        LOG.debug(
                            "клик (%s,%s) мимо кнопок/плиток - бездействие"
                            % (e.pos[0], e.pos[1])
                        )
        return True

    def _action_at_mouse(self, pos):
        tiles = self._action_tiles()
        for i, rect in enumerate(tiles):
            if rect.collidepoint(pos):
                return i
        return None

    def _action_tiles(self):
        return self.layout.tile_rects

    def new_match(self, seed=None):
        old = self.match
        if seed is None:
            self.game_seed += 1
        else:
            self.game_seed = int(seed)
        LOG.info(
            "RESET: старая партия seed=%s step=%s finished=%s winner=%s -> "
            "новая партия seed=%s"
            % (old.seed, old.step, old.finished, old.winner, self.game_seed)
        )
        self.match = MatchEngine(
            seed=self.game_seed,
            steps=self.steps,
            with_env=self.with_env,
            q_table=self.q_table,
            profile_rl=self.profile_rl,
            profile_ai=self.profile_ai,
            checkpoint=self.checkpoint,
            health_factors=self.health_factors,
            sickness=self.sickness,
        )
        self.paused = True
        self._critical_low.clear()
        self.clock.reset_counters()
        LOG.info(
            "RESET завершён: paused=True seed=%s (Q-таблица перенесена, "
            "%s состояний)" % (self.game_seed, len(self.q_table))
        )

    def start_match(self, seed=0, resume_tick=0):
        self.new_match(seed=seed)
        n = 0
        while n < int(resume_tick) and not self.match.finished:
            self.match.step_tick()
            n += 1
        self.clock.reset_counters()
        self.clock.ticks = n
        LOG.info(
            "start_match: seed=%s -> tick=%s finished=%s winner=%s"
            % (seed, self.match.step, self.match.finished, self.match.winner)
        )

    def progress(self):
        m = self.match
        return {
            "seed": m.seed,
            "tick": m.step,
            "winner": m.winner,
            "finished": bool(m.finished),
            "steps": self.steps,
            "with_env": bool(self.with_env),
            "profile_rl": self.profile_rl,
            "profile_ai": self.profile_ai,
            "sickness": self.sickness,
            "speed": self.clock.selected_speed,
            "paused": self.paused,
        }

    def on_resize(self, w, h):
        global SCREEN_W, SCREEN_H
        SCREEN_W, SCREEN_H = int(w), int(h)
        try:
            self.layout = Layout(SCREEN_W, SCREEN_H, len(ACTIONS))
            self.buttons = self.layout.buttons
            LOG.info(
                "on_resize -> %dx%d: Layout пересобран" % (SCREEN_W, SCREEN_H)
            )
        except Exception as exc:
            LOG.exc("Layout после on_resize", exc, key="resize")

    def update(self, dt):
        self.time += dt
        LOG.set_sim_time(self.time)
        if self.paused or self.match.finished:
            return
        due = self.clock.advance(dt)
        n = 0
        while n < due:
            forced = self.action_idx if self.manual_mode else None
            self.match.step_tick(forced_rl_action=forced)
            n += 1
            if self._maybe_auto_pause() or self.match.finished:
                break
        if n and LOG.level >= 3:
            LOG.debug(
                "update: тактов за кадр=%s tick=%s acc=%.2f speed=%s"
                % (n, self.match.step, self.clock.acc, self.clock.label)
            )

    def draw(self, surface=None):
        s = self.screen if surface is None else surface
        m = self.match
        env = m.env

        bg = env_bg_color(env.force if env else 10.0)
        s.fill(bg)
        if env is not None and env.in_open:
            glow = 160 + 60 * math.sin(self.time * 6.0)
            pygame.draw.rect(
                s, (int(glow), int(glow * 0.78), 40), s.get_rect(), width=4
            )

        self.draw_panel(s, m)
        self._draw_zone_separators(s)
        self.draw_agents(s, m)
        self.draw_transfers(s, m)
        self.draw_env_info(s, m)
        self.draw_history(s, m)
        self.draw_caption(s, m)
        if self.show_help:
            self.draw_help(s)
        else:
            self.draw_action_bar(s)
        self.draw_buttons(s)
        self.draw_status(s, m)

        if surface is None:
            pygame.display.flip()

    def _draw_zone_separators(self, s):
        L_ = self.layout
        col = (58, 62, 72)
        top, bottom = L_.EDGE, L_.h - L_.EDGE

        x_ab = (L_.panel_rect.right + L_.arena_rect.left) // 2
        x_bc = (L_.actions_rect.right + L_.ctrl_rect.left) // 2
        pygame.draw.line(s, col, (x_ab, top), (x_ab, bottom))
        pygame.draw.line(s, col, (x_bc, top), (x_bc, bottom))

        y_ba = (L_.arena_rect.bottom + L_.actions_rect.top) // 2
        pygame.draw.line(
            s, col, (L_.arena_rect.x, y_ba), (L_.actions_rect.right, y_ba)
        )
        y_bc1 = (L_.ctrl_rect.bottom + L_.caption_rect.top) // 2
        pygame.draw.line(
            s, col, (L_.ctrl_rect.x, y_bc1), (L_.ctrl_rect.right, y_bc1)
        )
        y_bc2 = (L_.caption_rect.bottom + L_.hist_rect.top) // 2
        pygame.draw.line(
            s, col, (L_.caption_rect.x, y_bc2), (L_.caption_rect.right, y_bc2)
        )

    def draw_panel(self, s, m):
        L_ = self.layout
        pw = L_.width_a

        pygame.draw.rect(s, COL_PANEL, L_.panel_rect)
        pygame.draw.rect(s, (60, 64, 74), L_.panel_rect.inflate(-2, -2), 1)

        t = self.font_b.render("OZVERING - IPO ARENA", True, COL_OPEN)
        if t.get_width() > pw - 8:
            t = self.font_s.render("OZVERING - IPO ARENA", True, COL_OPEN)
        s.blit(t, (L_.panel_rect.x + 6, L_.head_rect.y + 2))
        t2 = self.font_s.render(
            f"tick {m.step}/{m.steps_total}  seed {m.seed}", True, COL_DIM
        )
        s.blit(t2, (L_.panel_rect.x + 6, L_.head_rect.y + 24))

        def card(rect, border=(52, 56, 66)):
            r = rect
            pygame.draw.rect(s, (28, 31, 38), r, border_radius=5)
            pygame.draw.rect(s, border, r, 1, border_radius=5)
            return r

        sides = (
            (
                self.L("RL AGENT (обучающийся)", "RL AGENT (learning)"),
                m.rl,
                COL_RL,
                m.last_rl_action,
                m.rl_rest_ticks,
                L_.rl_card,
            ),
            (
                self.L(
                    "BDI AI (обучающийся)", "BDI AI (learning)"
                ),
                m.ai,
                COL_AI,
                m.last_ai_action,
                m.ai_rest_ticks,
                L_.ai_card,
            ),
        )
        for title, ag, acc, last_act, rest_ticks, crect in sides:
            r = card(crect, border=(acc[0] // 2, acc[1] // 2, acc[2] // 2))
            x, y = r.x + 8, r.y + 5
            small = self.font_s
            dy = max(12, min(int(15 * self.layout.sc), (r.height - 10) // 6))
            rows = [
                (title, acc),
                (
                    f"F={ag.force:6.1f} E={ag.energy_pool:4.0f} "
                    f"H={ag.health:4.0f}",
                    COL_TEXT,
                ),
                (
                    f"def [{ag.defense}] L={ag.rest_ceiling:.0f}"
                    f" RU={ag.rest_units:.0f}",
                    COL_TEXT,
                ),
            ]
            if ag.sickness > 0.0:
                rows.append(
                    (f"sick {ag.sickness:.2f}", (230, 170, 90))
                )
            on = ag.schmitt_on()
            win = ("OPEN " + str(ag.open_timer)) if ag.in_open else "closed"
            rows.append(
                (
                    f"w_adopt={ag.w_adopt:6.1f}/{on:5.1f}",
                    COL_OPEN if ag.in_open else COL_TEXT,
                )
            )
            bw = r.width - 16
            for txt, col in rows:
                t_ = small.render(txt, True, col)
                if t_.get_width() > bw:
                    while t_.get_width() > bw and len(txt) > 8:
                        txt = txt[: max(8, len(txt) - 4)] + ".."
                        t_ = small.render(txt, True, col)
                if y + t_.get_height() <= r.bottom - 3:
                    s.blit(t_, (x, y))
                y += dy

            wt = small.render(win, True, COL_OPEN if ag.in_open else COL_DIM)
            if wt.get_width() <= bw:
                s.blit(
                    wt,
                    (
                        max(x, r.right - wt.get_width() - 8),
                        y - dy + max(0, (dy - wt.get_height()) // 2),
                    ),
                )

            bar_col = DEFENSE_COLORS[ag.defense]
            frac = min(1.0, ag.w_adopt / max(1e-9, on))
            pygame.draw.rect(s, (50, 52, 60), (x, y + 1, bw, 6))
            pygame.draw.rect(s, bar_col, (x, y + 1, int(bw * frac), 6))
            y += 10
            act_line = (
                f"act {last_act[0]} w:{float(last_act[1]):.0f}"
                f" rest:{rest_ticks}"
            )
            at = small.render(act_line, True, COL_DIM)

            while at.get_width() > bw and len(act_line) > 12:
                act_line = act_line[:-6] + ".."
                at = small.render(act_line, True, COL_DIM)
            if y + at.get_height() <= r.bottom - 2:
                s.blit(at, (x, y))

        if m.env is not None:
            e = m.env
            r = card(L_.env_card, border=(110, 95, 40))
            x, y = r.x + 8, r.y + 5
            small = self.font_s
            dy = max(12, (r.height - 10) // 4)
            bw = r.width - 16

            def blit_row(txt, col, right_txt=None):
                nonlocal y
                t_ = small.render(txt, True, col)
                if t_.get_width() > bw:
                    while t_.get_width() > bw and len(txt) > 8:
                        txt = txt[: max(8, len(txt) - 4)] + ".."
                        t_ = small.render(txt, True, col)
                if y + t_.get_height() <= r.bottom - 2:
                    s.blit(t_, (x, y))
                if right_txt:
                    wt_ = small.render(right_txt[0], True, right_txt[1])
                    if wt_.get_width() + t_.get_width() < bw:
                        s.blit(wt_, (max(x, r.right - wt_.get_width() - 8), y))
                y += dy

            blit_row(self.L("СРЕДА-АВТОМАТ", "ENVIRONMENT"), COL_ENV_OPEN)
            blit_row(
                f"F={e.force:7.1f} E={e.energy_pool:4.0f}",
                DEFENSE_COLORS[e.defense],
                (
                    f"phase[{defense_label(e.defense)}]",
                    DEFENSE_COLORS[e.defense],
                ),
            )
            blit_row(
                f"w_adopt={e.w_adopt:6.1f}/{e.schmitt_on():5.1f}",
                COL_TEXT,
                (
                    "WINDOW OPEN" if e.in_open else "closed",
                    COL_ENV_OPEN if e.in_open else COL_DIM,
                ),
            )
            blit_row(
                f"members: {len(e.members)} bonus: {0.0:+.2f}",
                COL_DIM,
            )
        else:
            r = card(L_.env_card, border=(60, 64, 74))
            x, y = r.x + 8, r.y + 5
            dy = max(12, (r.height - 10) // 3)
            for txt, col in (
                (
                    self.L("СРЕДА: без актора", "ENVIRONMENT: none"),
                    COL_DIM,
                ),
                (
                    self.L(
                        "core41: две стороны, один такт",
                        "core41: two sides, one tick",
                    ),
                    COL_DIM,
                ),
                (
                    f"steps={m.step}/{m.steps_total}",
                    COL_DIM,
                ),
            ):
                t_ = self.font_s.render(txt, True, col)
                if y + t_.get_height() <= r.bottom - 2:
                    s.blit(t_, (x, y))
                y += dy

        r = card(L_.status_zone, border=(60, 64, 74))
        x, y = r.x + 8, r.y + 5
        small = self.font_s
        dy = max(12, (r.height - 10) // 4)
        bw = r.width - 16
        mode_txt = "MODE: " + (
            self.L("РУЧНОЙ (игрок->RL)", "MANUAL (player->RL)")
            if self.manual_mode
            else "OBSERVE"
        )
        t_ = small.render(
            mode_txt, True, COL_OPEN if self.manual_mode else COL_DIM
        )
        if y + t_.get_height() <= r.bottom - 2:
            s.blit(t_, (x, y))
        y += dy
        t_ = small.render(f"Q-states: {len(m.rl.Q)}", True, COL_DIM)
        if y + t_.get_height() <= r.bottom - 2:
            s.blit(t_, (x, y))
        y += dy
        t_ = small.render(
            f"profiles: {m.rl.profile}/{m.ai.profile}", True, COL_DIM
        )
        if t_.get_width() > bw:
            t_ = small.render(
                f"{m.rl.profile[:3]}/{m.ai.profile[:3]}", True, COL_DIM
            )
        if y + t_.get_height() <= r.bottom - 2:
            s.blit(t_, (x, y))
        y += dy
        streak = max(m.dom_rl, m.dom_ai)
        if streak:
            who = "RL dominates" if m.dom_rl else "AI dominates"
            frac = streak / CAPTURE_STREAK
            if y + 20 <= r.bottom - 2:
                pygame.draw.rect(s, (50, 52, 60), (x, y + 2, bw, 7))
                pygame.draw.rect(s, COL_OPEN, (x, y + 2, int(bw * frac), 7))
                s.blit(small.render(who, True, COL_OPEN), (x, y + 12))
        else:
            t_ = small.render(
                self.L("серия захвата: нет", "capture streak: none"),
                True,
                COL_DIM,
            )
            if y + 2 + t_.get_height() <= r.bottom - 2:
                s.blit(t_, (x, y + 2))

    def draw_agents(self, s, m):
        for pos, ag, acc in (
            (self.layout.rl_pos, m.rl, COL_RL),
            (self.layout.ai_pos, m.ai, COL_AI),
        ):
            r = agent_radius(ag.force)

            body = pygame.Surface((2 * r + 8, 2 * r + 8), pygame.SRCALPHA)
            pygame.draw.circle(body, (*acc[:3], 28), (r + 4, r + 4), r + 3)
            s.blit(body, (pos[0] - r - 4, pos[1] - r - 4))

            outline = DEFENSE_COLORS[ag.defense]
            width = 3
            if ag.in_open:
                pulse = 0.5 + 0.5 * math.sin(self.time * 10.0)
                glow_r = r + 6 + int(6 * pulse)
                gs = pygame.Surface(
                    (2 * glow_r + 8, 2 * glow_r + 8), pygame.SRCALPHA
                )
                pygame.draw.circle(
                    gs,
                    (*COL_OPEN, int(70 + 60 * pulse)),
                    (glow_r + 4, glow_r + 4),
                    glow_r,
                    width=3,
                )
                s.blit(gs, (pos[0] - glow_r - 4, pos[1] - glow_r - 4))
                outline, width = COL_OPEN, 3
            pygame.draw.circle(s, outline, pos, r, width=width)

            on = ag.schmitt_on()
            frac = min(1.0, ag.w_adopt / max(1e-9, on))
            rr = r + 10
            rect_ring = pygame.Rect(pos[0] - rr, pos[1] - rr, 2 * rr, 2 * rr)
            if frac > 0.003:
                pygame.draw.arc(
                    s,
                    COL_OPEN,
                    rect_ring,
                    math.pi / 2,
                    math.pi / 2 - 2 * math.pi * frac,
                    3,
                )
            else:
                pygame.draw.circle(s, (70, 72, 80), pos, rr, width=1)

            label = "RL" if acc == COL_RL else "AI"
            txt = self.font_b.render(label, True, acc)
            s.blit(txt, (pos[0] - txt.get_width() // 2, pos[1] - 10))
            ft = self.font_s.render(
                f"F{ag.force:.0f} E{ag.energy_pool}", True, COL_TEXT
            )
            s.blit(ft, (pos[0] - ft.get_width() // 2, pos[1] + 12))
            if ag.in_open:
                ot = self.font_s.render(
                    f"open:{ag.open_timer}", True, COL_OPEN
                )
                s.blit(ot, (pos[0] - ot.get_width() // 2, pos[1] - r - 30))

        if self.manual_mode:
            pick = (
                f"PICK: {action_label(ACTIONS[self.action_idx][0])}"
                f" {int(ACTIONS[self.action_idx][1] * 100)}%"
            )
            pt_ = self.font_s.render(pick, True, COL_OPEN)
            s.blit(
                pt_,
                (
                    self.layout.rl_pos[0] - pt_.get_width() // 2,
                    self.layout.rl_pos[1] - 96,
                ),
            )
            hint = self.L("вы управляете RL", "you control RL")
            ht = self.font_s.render(hint, True, COL_DIM)
            s.blit(
                ht,
                (
                    self.layout.rl_pos[0] - ht.get_width() // 2,
                    self.layout.rl_pos[1] - 82,
                ),
            )

        if self.paused and not self.match.finished:
            msg = self.L(
                "ПАУЗА: SPACE или START - пуск, STEP - один такт",
                "PAUSED: SPACE or START to run, STEP for one tick",
            )
            t = self.font.render(msg, True, COL_OPEN)
            s.blit(
                t,
                (
                    self.layout.arena_cx - t.get_width() // 2,
                    self.layout.transfer_lbl_y,
                ),
            )

    def draw_transfers(self, s, m):
        rl_pos, ai_pos = self.layout.rl_pos, self.layout.ai_pos
        for ev in m.events:
            if ev["kind"] != "transfer":
                continue
            frm, to = (
                (rl_pos, ai_pos) if ev["frm"] == "rl" else (ai_pos, rl_pos)
            )
            col = DEFENSE_COLORS.get(ev["type"], COL_TEXT)
            wdt = int(max(2, min(14, float(ev["work"]) // 3 + 2)))
            dx = to[0] - frm[0]
            ux = dx / max(1.0, abs(dx))
            sx = frm[0] + ux * (
                agent_radius(m.rl.force if ev["frm"] == "rl" else m.ai.force)
                + 12
            )
            tx = to[0] - ux * (
                agent_radius(m.ai.force if ev["frm"] == "rl" else m.rl.force)
                + 12
            )

            sx, sy, tx, ty = (
                int(round(sx)),
                int(frm[1]),
                int(round(tx)),
                int(to[1]),
            )
            pygame.draw.line(s, col, (sx, sy), (tx, ty), wdt)

            ah = 12 + wdt
            pygame.draw.polygon(
                s,
                col,
                [
                    (tx, ty),
                    (int(round(tx - ux * ah)), ty - 8),
                    (int(round(tx - ux * ah)), ty + 8),
                ],
            )
            if ev["hit"]:
                flash = pygame.Surface((60, 60), pygame.SRCALPHA)
                pygame.draw.circle(flash, (*COL_OPEN, 150), (30, 30), 14)
                s.blit(flash, (to[0] - 30, to[1] - 30))
                g = self.font_s.render(f"+{ev['gained']}", True, COL_OPEN)
                s.blit(g, ((sx + tx) // 2 - g.get_width() // 2, frm[1] - 26))

    def draw_env_info(self, s, m):
        env = m.env
        if env is None:
            return
        col = DEFENSE_COLORS[env.defense]
        txt = self.font.render(
            f"ENVIRONMENT  F={env.force:.0f}  "
            f"phase[{defense_label(env.defense)}]"
            f"  {'CONJUNCTURE WINDOW OPEN' if env.in_open else ''}",
            True,
            col,
        )
        s.blit(
            txt,
            (
                self.layout.env_label_pos[0] - txt.get_width() // 2,
                self.layout.env_label_pos[1],
            ),
        )

    def draw_history(self, s, m):
        n = self.history_len
        rl_h = m.rl_hist[-n:]
        ai_h = m.ai_hist[-n:]
        L_ = self.layout
        r = L_.hist_rect
        pygame.draw.rect(s, (20, 22, 28), r)
        pygame.draw.rect(s, (60, 64, 74), r, 1)
        lbl = self.font_s.render("force history (log)", True, COL_DIM)
        if lbl.get_width() <= r.width - 8:
            s.blit(lbl, (r.x + 4, r.y + 2))
        if len(rl_h) < 2:
            return
        gx, gy, gw, gh = r.x, r.y, r.w, r.h

        def pt(hist, i):
            v = math.log(max(1.0, hist[i]))
            x = gx + i * gw / max(1, len(hist) - 1)
            ymax = math.log(max(2.0, max(max(rl_h), max(ai_h))))
            y = gy + gh - (v / ymax) * (gh - 6) - 3
            return int(round(x)), int(round(y))

        for hist, col in ((rl_h, COL_RL), (ai_h, COL_AI)):
            pts = [pt(hist, i) for i in range(len(hist))]
            pygame.draw.lines(s, col, False, pts, 2)

        ly = r.y + 2
        lh = self.font_s.size("Ag")[1]
        for hist, col, tag in ((rl_h, COL_RL, "RL"), (ai_h, COL_AI, "AI")):
            t = self.font_s.render(f"{tag} {hist[-1]:.0f}", True, col)
            if ly + lh > r.bottom - 2 or t.get_width() > r.width - 8:
                break
            s.blit(t, (r.right - t.get_width() - 4, ly))
            ly += lh + 1

    def draw_caption(self, s, m):
        L_ = self.layout
        r = L_.caption_rect
        if self.paused:
            st = "PAUSE %s" % self.clock.selected_label
        else:
            st = "RUN %s  %.1fs/tick" % (
                self.clock.label,
                self.clock.seconds_per_tick or 0.0,
            )
        if m.finished:
            st = "FINISHED %s" % self.clock.selected_label
        t = self.font_s.render(st, True, COL_DIM if self.paused else COL_OPEN)
        if t.get_width() <= r.width - 4:
            s.blit(t, (r.x + 2, r.y + 1))
        pick = f"PICK {action_label(ACTIONS[self.action_idx][0])}"
        t2 = self.font_s.render(pick, True, COL_TEXT)
        if (
            t2.get_width() <= r.right - t.get_width() - 8
            and t2.get_width() <= r.width - 4
        ):
            s.blit(t2, (max(r.x + 2, r.right - t2.get_width() - 2), r.y + 1))

    def draw_action_bar(self, s):
        L_ = self.layout

        pygame.draw.rect(s, COL_PANEL, L_.actions_rect)
        pygame.draw.rect(s, (52, 56, 66), L_.actions_rect, 1)
        for i, rect in enumerate(self._action_tiles()):
            act, frac = ACTIONS[i]
            sel = i == self.action_idx
            col = DEFENSE_COLORS.get(act, COL_DIM)
            pygame.draw.rect(
                s, (40, 44, 54) if not sel else (70, 76, 92), rect
            )
            pygame.draw.rect(
                s, col if act != "REST" else COL_DIM, rect, 3 if sel else 2
            )
            name = f"{i + 1}:{action_label(act)} {int(frac * 100)}%"
            t = self.font_s.render(name, True, COL_TEXT)
            while t.get_width() > rect.width - 6 and len(name) > 4:
                name = name[: len(name) - 3] + ".."
                t = self.font_s.render(name, True, COL_TEXT)
            s.blit(
                t,
                (
                    rect.x + rect.w // 2 - t.get_width() // 2,
                    rect.y + rect.h // 2 - t.get_height() // 2,
                ),
            )

        pr = L_.pick_rect
        pygame.draw.rect(s, (30, 33, 40), pr, border_radius=4)
        pygame.draw.rect(s, COL_OPEN, pr, 1, border_radius=4)
        pk = f"PICK: {action_label(ACTIONS[self.action_idx][0])}"
        t = self.font_s.render(pk, True, COL_OPEN)
        while t.get_width() > pr.width - 6 and len(pk) > 5:
            pk = pk[: len(pk) - 3] + ".."
            t = self.font_s.render(pk, True, COL_OPEN)
        s.blit(
            t,
            (
                pr.x + pr.w // 2 - t.get_width() // 2,
                pr.y + pr.h // 2 - t.get_height() // 2,
            ),
        )
        tag = (
            self.L(
                "ВЫБРАНО ИГРОКОМ (клик или 1-5)", "PLAYER PICK (click or 1-5)"
            )
            if self.manual_mode
            else self.L(
                "режим наблюдателя: RL решает сам (M или клик = взять "
                "управление)",
                "observe: RL decides (M or click = take control)",
            )
        )

        max_w = L_.actions_rect.width - 16
        t = self.font_s.render(
            tag, True, COL_OPEN if self.manual_mode else COL_DIM
        )
        while t.get_width() > max_w and len(tag) > 6:
            cut = max(
                6,
                len(tag)
                - max(
                    4,
                    int(
                        len(tag)
                        * (t.get_width() - max_w)
                        / max(1, t.get_width())
                    ),
                ),
            )
            tag = tag[:cut] + ".."
            t = self.font_s.render(
                tag, True, COL_OPEN if self.manual_mode else COL_DIM
            )
        s.blit(t, (L_.actions_rect.x + 8, L_.tiles_label_y))

    def draw_buttons(self, s):
        L_ = self.layout
        pygame.draw.rect(s, COL_PANEL, L_.ctrl_rect)
        flashing = self.time < self._flash_until
        for name, label, rect in self.buttons:
            active = (name == "START" and not self.paused) or (
                name == "MODE" and self.manual_mode
            )
            hot = flashing and self._btn_flash == name
            if name == "QUIT":
                bg = (86, 48, 48)
            elif active:
                bg = (74, 82, 98)
            else:
                bg = (38, 41, 50)
            if hot:
                bg = (120, 130, 150)
            pygame.draw.rect(s, bg, rect, border_radius=4)
            border = (
                (170, 90, 90)
                if name == "QUIT"
                else (COL_OPEN if active else (90, 95, 108))
            )
            pygame.draw.rect(s, border, rect, 2, border_radius=4)
            t = self.font_s.render(label, True, COL_TEXT)
            if t.get_width() > rect.width - 6:
                t = self.font_s.render(
                    label[: max(3, rect.width // 8)], True, COL_TEXT
                )
            if t.get_height() > rect.height - 4:
                continue
            s.blit(
                t,
                (
                    rect.x + (rect.width - t.get_width()) // 2,
                    rect.y + (rect.height - t.get_height()) // 2,
                ),
            )

    def draw_status(self, s, m):
        if m.finished:
            msg = (
                f"CAPTURE: {m.winner} wins at tick {m.step}"
                if m.winner
                else f"NO DECISION after {m.step} ticks"
            )
            t = self.font_b.render(msg, True, COL_OPEN)
            cx = self.layout.arena_cx
            cy = self.layout.arena_cy + self.layout.finish_dy
            s.blit(t, (cx - t.get_width() // 2, cy))
            t2 = self.font_s.render(
                self.L(
                    "R или кнопка RESET - новая партия",
                    "R or RESET button - new match",
                ),
                True,
                COL_DIM,
            )
            s.blit(t2, (cx - t2.get_width() // 2, cy + 26))

    def draw_help(self, s):
        if self.cyrillic_ok:
            lines = [
                "SPACE / кнопка START - пауза/пуск   R / RESET - новая партия",
                "TAB / кнопка STEP - один такт (работает и в паузе!)",
                "+/- или стрелки / SPEED - скорость: 1x/2x/4x/8x/16x",
                "M / MODE - режим игрок/наблюдатель",
                "1..5 или клик по плитке - действие RL (сразу видно выбор)",
                "F1/H - скрыть справку   ESC/Q или кнопка QUIT - выход",
                "",
                "Круг = автомат (радиус ~ log F, рамка = форма работы).",
                "Кольцо = давление на вход w_adopt/ON(F); жёлтая пульсация -",
                "открытое окно Шмитта.",
                "Три колонки HUD: метрики | арена+действия | кнопки+график.",
            ]
        else:
            lines = [
                "SPACE / START button - pause/run    R / RESET - new match",
                "TAB / STEP button - single tick (works while paused!)",
                "+/- or arrows / SPEED - 1x/2x/4x/8x/16x",
                "M / MODE - observe/manual",
                "1..5 or click a tile - pick RL action (selection is "
                "highlighted)",
                "F1/H - toggle help   ESC/Q or QUIT button - quit",
                "",
                "Circle = automaton (radius ~ log F, outline = work form).",
                "Ring = input pressure w_adopt/ON(F); yellow pulse =",
                "open Schmitt window.",
                "Three columns: metrics | arena+actions | buttons+graph.",
            ]
        L_ = self.layout

        pygame.draw.rect(s, COL_PANEL, L_.actions_rect)
        pygame.draw.rect(s, (52, 56, 66), L_.actions_rect, 1)
        hdr = self.font_s.render(
            self.L("СПРАВКА (F1 - скрыть)", "HELP (F1 to hide)"),
            True,
            COL_OPEN,
        )
        s.blit(hdr, (L_.help_x + 4, L_.tiles_label_y))
        y = L_.help_y + L_.line_h + 4
        max_w = L_.actions_rect.width - 12
        for ln in lines:
            hgt = self.font_s.size(ln)[1] if ln else L_.line_h // 2
            if y + hgt > L_.actions_rect.bottom - 2:
                break
            if ln:
                t = self.font_s.render(ln, True, COL_DIM)
                while t.get_width() > max_w and len(ln) > 8:
                    cut = max(
                        8,
                        len(ln)
                        - max(
                            2,
                            int(
                                len(ln)
                                * (t.get_width() - max_w)
                                / max(1, t.get_width())
                            ),
                        ),
                    )
                    ln = ln[:cut] + ".."
                    t = self.font_s.render(ln, True, COL_DIM)
                s.blit(t, (L_.help_x + 4, y))
            y += L_.help_line_dy

        if self.fonts.is_bitmap and y + 14 < L_.actions_rect.bottom:
            warn = "FONT FALLBACK (pygame.font broken): pip install pygame-ce"
            wt = self.font_s.render(warn, True, (255, 120, 80))
            if wt.get_width() <= max_w:
                s.blit(wt, (L_.help_x + 4, y))

    def run(self):
        LOG.info(
            "главный цикл запущен (fps=%s, темп=%s тик/с, paused=%s)"
            % (FPS, self.ticks_per_sec, self.paused)
        )
        running = True
        frame = 0
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            frame += 1
            if frame == 1 or frame % 300 == 0:
                LOG.debug(
                    "кадр %s: dt=%.1fms fps=%.1f tick=%s paused=%s "
                    "manual=%s finished=%s"
                    % (
                        frame,
                        dt * 1000,
                        self.clock.get_fps(),
                        self.match.step,
                        self.paused,
                        self.manual_mode,
                        self.match.finished,
                    )
                )
            try:
                running = self.handle_events()
            except Exception as e:
                LOG.exc("handle_events", e, key="events")
                LOG.warn("ошибка обработки ввода - цикл продолжается")
            try:
                self.update(dt)
            except Exception as e:
                LOG.exc("update (шаг симуляции)", e, key="update")
                self.paused = True
                LOG.warn(
                    "симуляция остановлена (paused=True) из-за ошибки выше; "
                    "партия: tick=%s step_finished=%s"
                    % (self.match.step, self.match.finished)
                )
            active = True
            try:
                active = bool(pygame.display.get_active())
            except Exception:
                active = True
            if active:
                try:
                    self.draw()
                except Exception as e:
                    LOG.exc("draw (отрисовка кадра)", e, key="draw")
                    LOG.warn("кадр не отрисован - цикл продолжается")
        LOG.info(
            "главный цикл завершён (кадров=%s, финальный tick=%s)"
            % (frame, self.match.step)
        )
        quit_pygame()
        LOG.info("подсистемы pygame закрыты - чистое завершение")


def main():
    LOG.info("main(): старт. Аргументы: %s" % sys.argv)
    LOG.info(
        "Окружение: python=%s executable=%s cwd=%s"
        % (sys.version.split()[0], sys.executable, os.getcwd())
    )
    checkpoint = ""
    if "--checkpoint" in sys.argv:
        index = sys.argv.index("--checkpoint")
        if index + 1 < len(sys.argv):
            checkpoint = sys.argv[index + 1]
        LOG.info("main(): AI checkpoint=%r" % checkpoint)
    health_factors = {}
    if "--health-factors" in sys.argv:
        index = sys.argv.index("--health-factors")
        if index + 1 < len(sys.argv):
            health_factors = parse_health_factors(sys.argv[index + 1])
        LOG.info("main(): health_factors=%r" % health_factors)
    sickness = 0.0
    if "--sickness" in sys.argv:
        index = sys.argv.index("--sickness")
        if index + 1 < len(sys.argv):
            try:
                sickness = max(
                    0.0,
                    min(SICKNESS_MAX, float(sys.argv[index + 1])),
                )
            except ValueError:
                sickness = 0.0
        LOG.info("main(): sickness=%.2f" % sickness)
    speed = DEFAULT_SPEED
    if "--speed" in sys.argv:
        index = sys.argv.index("--speed")
        if index + 1 < len(sys.argv):
            try:
                speed = normalize_speed(sys.argv[index + 1])
            except ValueError:
                speed = DEFAULT_SPEED
        LOG.info("main(): speed=%s" % speed)
    auto_pause = "--no-auto-pause" not in sys.argv

    init_pygame_minimal()
    fonts = FontSet()
    probe = _probe_font()
    fonts.setup(probe)
    if fonts.is_bitmap:
        LOG.warn("FontSet в режиме bitmap-fallback: %s" % fonts.note)
        sys.stderr.write(
            "[game_engine] ВНИМАНИЕ: pygame.font недоступен "
            f"({fonts.note}).\n"
            "  Это известная ошибка pygame 2.6.x на Python 3.14 (битый "
            "freetype).\n"
            "  Движок продолжит работу со встроенным растровым шрифтом.\n"
            "  Чтобы вернуть нормальные шрифты (и кириллицу в HUD):\n"
            "      pip uninstall -y pygame && pip install pygame-ce\n"
        )
    else:
        LOG.info(
            "FontSet готов: native pygame.font, кириллица=%s"
            % fonts.cyrillic_ok
        )
    app = GameApp(
        fonts=fonts,
        checkpoint=checkpoint,
        health_factors=health_factors,
        sickness=sickness,
        speed=speed,
        auto_pause=auto_pause,
    )
    app.run()
    LOG.info("main(): штатное завершение, rc=0")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:
        LOG.error(
            "ФАТАЛЬНАЯ ОШИБКА (неперехваченное исключение): "
            "%s: %s" % (type(e).__name__, e)
        )
        sys.stderr.write(
            "".join(traceback.format_exception(type(e), e, e.__traceback__))
        )
        sys.stderr.flush()
        sys.exit(1)
