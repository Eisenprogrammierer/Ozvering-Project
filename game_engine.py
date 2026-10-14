"""Ozvering-Project: минималистичный 2D графический движок на PyGame.

Игрок наблюдает (и при желании управляет) дуэлью двух IPO-автоматов в среде-автомате:
  * RLAgent      - обучающийся агент (табличный Q-Learning);
  * UtilityAI    - скриптованный BDI-агент (argmax ожидаемой выгоды).

Движок НЕ изменяет simulation.py - использует только его публичное API:
классы Agent/RLAgent/UtilityAI/Environment, функции play_game-протокола по шагам
(sense / rotate_defense / upkeep / tick_energy / tick_input_state / commit /
resolve_attack / learn / check_capture) и словари PARAMETERS / PROFILES / MULT.

Управление (все действия дублируются кликами мыши по кнопкам в HUD):
  SPACE / кнопка "START/PAUSE" - пауза/пуск тактов партии
  "+" и "-" или кнопки SPEED - темп симуляции
  STEP / кнопка "STEP" - один такт (работает и в паузе!)
  R       - новая партия (сброс окружения; Q-таблица RL сохраняется - перенос обучения)
  M       - режим: наблюдатель <-> игрок управляет RL-агентом вручную
            (в ручном режиме плитки действий кликабельны ВСЕГДА, выбор виден сразу)
  F1/H    - справка
  ESC/Q   - выход

Визуальный язык (минимализм, всё выводится из состояний модели):
  * Два круга-автомата: радиус ~ log(сила), цвет рамки - текущий тип защиты
    (FIRE - красный, WATER - синий, EARTH - зелёный).
  * Кольцо вокруг круга - накопленное давление на вход w_adopt (дуга до порога ON(F));
    заполненное кольцо = порог пройден.
  * Когда окно восприимчивости входа открыто (in_open) - круг пульсирует жёлтым,
    над ним таймер окна.
  * Среда (Environment) - фон: оттенок фона кодирует силу среды, золотая рамка экрана
    - открытое окно конъюнктуры (ENV_BONUS активен).
  * Стрелки-передачи: направление и толщина = работа, вспышка = успешная передача.
  * Панель слева - метрики обеих сторон и среды текстом.
"""

import math
import os
import random
import subprocess
import sys
import time as _time_mod
import traceback

# ---------------------------------------------------------------------------
# Подробное консольное логирование (для отладки). НИКАКОЙ записи в лог-файлы:
# все сообщения идут только в stderr.
#
#   GAME_LOG=0     - только ошибки/предупреждения и аварийные дампы (по умолчанию)
#   GAME_LOG=1     - + ключевые события (запуск, партии, такты боя, команды ввода)
#   GAME_LOG=2/v   - + детали каждого такта (состояния агентов, исходы передач)
#   GAME_LOG=3/vv  - + каждый обработанный системный вызов pygame (события, кадры)
#
# Любое неперехваченное исключение печатается с полным стеком и движок завершается
# управляемо (код возврата 1), а не молча обрывается.
# ---------------------------------------------------------------------------


class _Logger:
    """Минималистичный level-based логгер в stderr с таймстампом и префиксом."""

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
        self._sim_t = 0.0            # вещественное время игрового цикла
        self._last_err = {}          # дебаунс частых ошибок одного места
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
                self._TAGS[level], _time_mod.perf_counter() - self._t0, msg)
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
        """Печатает тип/сообщение исключения + полный стек в дамп-формате."""
        tb = "".join(traceback.format_exception(type(err), err,
                                                err.__traceback__)).rstrip()
        self.error("%s: %s: %s\n%s" % (where, type(err).__name__, err, tb),
                   key=key, throttle=0.0)


LOG = _Logger()


def _dump_stack(where="current stack"):
    LOG.debug("%s:\n%s" % (where, "".join(
        traceback.format_stack()[:-1]).rstrip()))

# ---------------------------------------------------------------------------
# Защита от "сломанного шрифта" в pygame 2.6.x на Python 3.14 (и не только).
#
# Причина ошибки "cannot import name 'Font' from partially initialized module
# 'pygame.font' (circular import)": бинарный модуль pygame.freetype собран без
# поддержки UTF-8 (SDL_ttf compiled without FreeType support), и при запуске
# pygame.font пытается импортировать Font из уже частично инициализированного
# pygame.font. В результате вся подсистема шрифтов недоступна, а try/except
# вокруг pygame.font.Font(...) не спасает - падает сам доступ к атрибуту.
#
# Решение "раз и навсегда": если штатный способ не работает, движок полностью
# НЕ зависит от pygame.font - текст рендерится встроенным растровым шрифтом
# (см. BitmapText ниже). Никаких системных зависимостей, никаких pip-пакетов.
# ---------------------------------------------------------------------------
_FONT_OK = False          # станет True, если pygame.font реально работает
_FONT_NOTE = ""           # причина отказа (показывается в HUD)


def _probe_font():
    """Возвращает рабочий pygame.font.Font или None - без исключений наружу.

    ВАЖНО: инициализирует шрифт-подсистему сама (pygame.font.init()), чтобы
    проба была корректной и до, и после pygame.init() - иначе на исправленном
    pygame недетектируемый 'font not initialized' ложно включал бы fallback.
    """
    global _FONT_OK, _FONT_NOTE
    LOG.debug("_probe_font(): проба подсистемы pygame.font")
    try:
        import pygame.font as _pf
        _pf.init()                            # идемпотентно; не тянет весь pygame.init
        # Дополнительный шанс для сборок, где бинарный freetype бит, а чистый
        # SDL_ttf жив: заставляем pygame.font использовать шрифт через SDL_ttf
        # (есть в pygame-ce; в обычном pygame просто отсутствует - молча пропускаем).
        try:
            _pf.set_sdl_ttf_default(True)
            LOG.debug("set_sdl_ttf_default(True) применён (pygame-ce)")
        except Exception as e:
            LOG.debug("set_sdl_ttf_default недоступен: %s" % e)
        f = _pf.Font(None, 17)                # реальный тест создания
        sz = f.size("A")
        LOG.debug("Font(None,17) создан, size('A')=%s" % (sz,))
        if sz[0] <= 0:
            raise RuntimeError("default font renders nothing")
        _FONT_OK = True
        LOG.info("шрифт OK: pygame.font рабочий (кириллица будет позже)")
        return f
    except Exception as e:                    # noqa: BLE001
        _FONT_NOTE = str(e) or e.__class__.__name__
        _FONT_OK = False
        LOG.warn("шрифт НЕДОСТУПЕН: %s: %s" % (type(e).__name__, _FONT_NOTE))
        LOG.debug("стек пробы шрифта:\n%s" % "".join(traceback.format_stack()[:-1]).rstrip())
        return None


def _try_fix_freetype():
    """Пытаемся один раз починить окружение, не трогая код модели:
    1) если установлен pygame-ce - переключиться на него;
    2) иначе удалить битый pygame и поставить pygame-ce (он исправляет сборку
       freetype для Python 3.14). Действие логируется, ошибка - не фатальна."""
    try:
        import importlib.util
        if importlib.util.find_spec("pygame_ce") is not None:
            LOG.warn("Найден pygame-ce. Для его использования "
                     "удалите обычный pygame: pip uninstall -y pygame")
            return
        LOG.debug("pygame-ce в окружении не найден")
    except Exception as e:
        LOG.debug("поиск pygame-ce не удался: %s" % e)
    try:
        code = ("import pygame.freetype, shutil; "
                "shutil.copy(pygame.freetype.get_default_font(), '.')")
        LOG.debug("проба копирования шрифта из pygame.freetype...")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=5)
        LOG.debug("проба freetype: rc=%s stderr=%r" % (r.returncode,
                                                       r.stderr[:200]))
    except Exception as e:
        LOG.debug("проба freetype не удалась: %s" % e)


try:
    LOG.info("запуск game_engine.py, python=%s, GAME_LOG=%s"
             % (sys.version.split()[0], os.environ.get("GAME_LOG", "0")))
    import pygame
    LOG.info("pygame импортирован: версия=%s SDL=%s"
             % (pygame.version.ver, pygame.get_sdl_version()))
except ImportError:
    LOG.error("PyGame НЕ установлен - импорт не удался")
    sys.stderr.write(
        "PyGame не установлен. Установите исправленную сборку:\n"
        "    pip uninstall -y pygame && pip install pygame-ce\n"
        "(обычный pygame 2.6.x на Python 3.14 собран с битым freetype - "
        "шрифты не работают)\n")
    raise

# --- Импорт публичного API модели (никаких правок simulation.py) -------------
try:
    from simulation import (
        PARAMETERS, PROFILES, MULT, TYPES, ACTIONS,
        Agent, RLAgent, UtilityAI, Environment,
        resolve_attack, check_capture, p_success,
    )
    LOG.info("simulation импортирован: ACTIONS=%s profiles=%s"
             % ([a[0] for a in ACTIONS], list(PROFILES)))
except Exception as e:
    LOG.exc("ИМПОРТ SIMULATION НЕ УДАЛСЯ", e)
    raise

# ---------------------------------------------------------------------------
# Константы оформления
# ---------------------------------------------------------------------------

def compute_window_size():
    """Автоподбор размера окна под разрешение экрана (соотношение 12:9).

    Берём текущий дисплей pygame; если headless/dummy или размеры недоступны -
    откат на базовые 1024x640. Из доступной области вырезается рамка окна и
    панели задач (запас ~8%), затем вписывается прямоугольник 12:9.
    Результат округляется до чётных чисел и не превышает дисплей.
    """
    base_w, base_h = 1024, 640
    dw = dh = 0
    try:
        info = pygame.display.Info()
        dw, dh = int(info.current_w), int(info.current_h)
    except Exception as exc:                      # pragma: no cover - fallback
        LOG.warn("compute_window_size: display.Info() недоступен (%s)" % exc)
    if dw < base_w or dh < base_h:                # dummy/headless/малый экран
        return base_w, base_h
    avail_w = int(dw * 0.92)
    avail_h = int(dh * 0.90)
    w = min(avail_w, int(avail_h * 12 / 9))
    h = int(w * 9 / 12)
    w -= w % 2
    h -= h % 2
    return max(base_w, w), max(base_h, h)


# Фактический размер окна определяется при старте (после pygame.init()).
SCREEN_W, SCREEN_H = 1024, 640
PANEL_W = 300
FPS = 60

TYPE_COLORS = {
    "FIRE": (220, 80, 50),
    "WATER": (70, 130, 220),
    "EARTH": (90, 170, 90),
}
COL_RL = (240, 240, 240)          # акцент обучающегося агента
COL_AI = (200, 160, 255)          # акцент скриптованного агента
COL_OPEN = (255, 220, 90)         # открытое окно восприимчивости
COL_ENV_OPEN = (255, 200, 60)     # окно конъюнктуры среды
COL_TEXT = (225, 225, 225)
COL_DIM = (140, 140, 140)
COL_PANEL = (24, 26, 32)
COL_BG_BASE = (16, 18, 24)

# Позиции автоматов на "арене" вычисляются в Layout (см. ниже) - они зависят
# от фактического размера окна, которое определяется при старте.


def agent_radius(force):
    """Радиус автомата - монотонная сжатая функция силы (log-шкала)."""
    return int(22 + 14 * math.log(max(1.0, force)))


def env_bg_color(env_force):
    """Оттенок фона от силы среды: чем больше капитал конъюнктуры, тем теплее фон."""
    t = min(1.0, max(0.0, (env_force - 10.0) / 400.0))
    r = COL_BG_BASE[0] + int(18 * t)
    g = COL_BG_BASE[1] + int(10 * t)
    b = COL_BG_BASE[2] + int(4 * t)
    return (r, g, b)


class Layout:
    """Геометрия HUD под фактический размер окна: ТРИ изолированных пространства.

    Пользовательская раскладка v2: экран режется ДВУМЯ вертикальными линиями
    на три mutually exclusive колонки; каждая колонка дополнительно разрезана
    горизонтальными линиями на секции с гарантированным зазором GAP между
    ними. Внутри секний элементы расставляются сеткой (rows x cols), поэтому
    два кликабельных объекта физически не могут пересечься - их прямоугольники
    строятся из одного и того же Rect секции без общих пикселей:

      КОЛОНКА A (левая, width_a ~ 26% w) - МЕТРИКИ:
        A1 карточка RL, A2 карточка UtilityAI, A3 карточка СРЕДЫ,
        A4 СТАТУС партии (серия захвата, режим, профили).
      КОЛОНКА B (центр, остальная ширина минус C) - АРЕНА + ДЕЙСТВИЯ:
        B1 арена (подпись среды сверху, автоматы RL/AI, стрелки передач,
           сообщения паузы/итога) - вся оставшаяся высота;
        B2 внизу - сетка 2x4 кликабельных плиток действий (последняя клетка
           - индикатор выбранного PICK; в режиме справки клетки заняты
           первыми строками HELP, остальные молча пустуют).
      КОЛОНКА C (правая, width_c ~ 24% w) - УПРАВЛЕНИЕ + ГРАФИК:
        C1 кнопки управления - сетка 4x2 (START|STEP / SLOWER|FASTER /
           MODE|RESET / HELP|индикатор темпа), ячейки равные, зазор фикс.;
        C2 ниже - подпись состояния (tick/seed/PAUSE-RUN);
        C3 остаток - график force history (лог-шкала) во всю высоту колонки,
           legend внутри рамки справа сверху.

    Порядок секций фиксирован (A сверху вниз, B: арена->действия,
    C: кнопки->подпись->график), размеры секций считаются ДОЛЬШЕЙ меркой от
    краёв колонки, а содержимое (тексты, плитки, кнопки) всегда вписывается в
    свою секцию усечением/масштабированием при отрисовке. Поэтому:
      - кнопки не перекрывают друг друга (сетка 4x2 с фиксированным зазором);
      - плитки не перекрывают кнопки (разные колонки);
      - график не перекрывает ничего (своя секция C3, отделённая зазором).
    Все координаты зависят только от (w, h, n_actions) и масштаба sc -
    пересчёт целиком при любом размере окна.
    """

    EDGE = 10            # внешний отступ колонок от краёв окна
    GAP = 12             # зазор между секциями ВНУТРИ колонки (>= EDGE)
    VGAP = 14            # горизонтальный зазор между колонками
    BTN_ROWS, BTN_COLS = 4, 2      # сетка кнопок в C1
    TILE_ROWS, TILE_COLS = 2, 4    # сетка плиток в B2 (7 действий + PICK)
    CELL_GAP = 8                   # зазор между ячейками любой сетки

    def __init__(self, w, h, n_actions):
        self.w, self.h = w, h

        # --- масштаб для больших окон --------------------------------------
        sc = max(1.0, min(1.6, w / 1440.0))
        self.sc = sc
        self.line_h = int(16 * max(1.0, sc * 0.85))    # мелкий текст
        self.cell_gap = max(6, int(self.CELL_GAP * min(1.2, sc)))

        E, G, VG = self.EDGE, self.GAP, self.VGAP

        # ================= горизонтальный разрез: колонки A | B | C ========
        width_a = int(max(PANEL_W, min(w * 0.26, PANEL_W * sc)))
        width_c = int(max(240, min(w * 0.24, 300 * sc)))
        # На очень узких окнах колонку C сужаем, но не ниже 220px (2 кнопки).
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

        # ================= КОЛОНКА C: кнопки -> подпись -> график ==========
        # Размеры нижних секций меряем "дольней" меркой от низа колонки,
        # кнопкам достаётся весь остаток сверху - они никогда не съезжаются
        # с графиком (между секциями всегда зазор G).
        btn_area_h = int(max(44, 4 * (34 * max(1.0, sc * 0.9))
                             + 3 * self.cell_gap))
        graph_h = int(max(110, min(h * 0.42, 260 * max(1.0, sc * 0.8))))
        cap_h = int(self.line_h * 2 + 10)               # подпись tick/seed/state
        c_avail = bottom - top
        # если колонка мала - пропорционально ужимаем график и подпись
        scale_dn = min(1.0, (c_avail - 3 * G) / float(btn_area_h + graph_h + cap_h))
        btn_area_h = max(44, int(btn_area_h * scale_dn))
        graph_h = max(90, int(graph_h * scale_dn))
        cap_h = max(self.line_h * 2 + 6, int(cap_h * scale_dn))

        graph_rect = pygame.Rect(cx0, bottom - graph_h, col_c_w, graph_h)
        caption_rect = pygame.Rect(cx0, graph_rect.top - G - cap_h,
                                   col_c_w, cap_h)
        btn_rect = pygame.Rect(cx0, top, col_c_w,
                               max(44, caption_rect.top - G - top))
        self.ctrl_rect = btn_rect
        self.hist_rect = graph_rect
        self.caption_rect = caption_rect

        # --- сетка кнопок 4x2 внутри btn_rect ------------------------------
        # Ячейки НЕ растягиваются на весь прямоугольник: высота ограничена
        # базовой (btn_area_h), лишняя высота колонки уходит в чистый воздух
        # под сеткой - кнопки остаются компактными и никогда не сливаются.
        names = ["START", "STEP", "SLOWER", "FASTER", "MODE", "RESET", "HELP"]
        labels = ["START / PAUSE", "STEP 1 TICK", "SPEED <", "SPEED >",
                  "MODE: OBS/MANUAL", "RESET MATCH", "HELP F1"]
        rows, cols = self.BTN_ROWS, self.BTN_COLS
        cg = self.cell_gap
        cw = (btn_rect.width - (cols - 1) * cg) // cols
        ch_max = int(34 * max(1.0, sc * 0.9))
        ch = max(24, min(ch_max,
                         (btn_rect.height - (rows - 1) * cg) // rows))
        rects = []
        order = [("START", 0, 0), ("STEP", 0, 1), ("SLOWER", 1, 0),
                 ("FASTER", 1, 1), ("MODE", 2, 0), ("RESET", 2, 1),
                 ("HELP", 3, 0)]
        by_name = {}
        for nm, rr, cc in order:
            r = pygame.Rect(btn_rect.x + cc * (cw + cg),
                            btn_rect.y + rr * (ch + cg), cw, ch)
            rects.append(r)
            by_name[nm] = r
        self.buttons = list(zip(names, labels, rects))
        (self.start_btn, self.step_btn, self.slow_btn, self.fast_btn,
         self.mode_btn, self.reset_btn, self.help_btn) = rects
        # Ячейка (3,1) - индикатор темпа: отдельныйRect в том же коридоре.
        self.speed_rect = pygame.Rect(btn_rect.x + 1 * (cw + cg),
                                      btn_rect.y + 3 * (ch + cg), cw, ch)
        self.btn_cell_w, self.btn_cell_h = cw, ch

        # ================= КОЛОНКА B: арена сверху, действия снизу =========
        tile_area_h = int(2 * (36 * max(1.0, sc * 0.9)) + self.cell_gap + 24)
        b_avail = bottom - top
        if b_avail - tile_area_h - G < 160:            # арене нужен минимум
            tile_area_h = max(80, b_avail - 160 - G)
        actions_rect = pygame.Rect(bx0, bottom - tile_area_h,
                                   col_b_w, tile_area_h)
        arena_rect = pygame.Rect(bx0, top, col_b_w,
                                 max(60, actions_rect.top - G - top))
        self.actions_rect = actions_rect
        self.arena_rect = arena_rect

        # --- сетка плиток 2x4 (7 ACTIONS + PICK-индикатор) -----------------
        trows, tcols = self.TILE_ROWS, self.TILE_COLS
        tcw = (actions_rect.width - (tcols - 1) * cg) // tcols
        tch = max(26, min(int(40 * max(1.0, sc * 0.9)),
                          (actions_rect.height - 20 - (trows - 1) * cg) // trows))
        tile_top = actions_rect.y + 18
        # Горизонтальное центрирование сетки в секции: если ячейки шире, чем
        # нужно подписям - сужаем их до базовой ширины и ставим по центру.
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
                pygame.Rect(ox + cc * (cw_ + cg),
                            tile_top + rr * (tch + cg), cw_, tch))
        # PICK-плашка занимает последнюю свободную клетку сетки.
        pick_row, pick_col = divmod(n_actions, tcols)
        self.pick_rect = pygame.Rect(ox + pick_col * (cw_ + cg),
                                     tile_top + pick_row * (tch + cg),
                                     cw_, tch)
        self.tiles_label_y = actions_rect.y + 2
        self.tiles_bottom = tile_top + trows * tch + (trows - 1) * cg
        self.tile_cell_w, self.tile_cell_h = cw_, tch
        self.actions_grid_rows = trows
        # Справка (F1) занимает ту же секцию B2 (текст обрезается по ней).
        self.help_x = actions_rect.x + 6
        self.help_y = actions_rect.y + 20
        self.help_rect = actions_rect
        self.help_line_dy = self.line_h

        # ================= КОЛОНКА A: карточки метрик ======================
        # Секции: RL, AI, ENV, STATUS. Минимальные высоты закладываются в
        # расчёт; STATUS получает остаток. Если колонка короткая - секции
        # ужимаются равномерно (карточки рисуются с внутренним clipping).
        a_avail = bottom - top
        card_min = int(84 * max(1.0, sc * 0.85))
        env_min = int(72 * max(1.0, sc * 0.85))
        status_min = int(64 * max(1.0, sc * 0.85))
        head_h = 46                        # заголовок OZVERING + tick/seed
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
        self.status_zone = pygame.Rect(ax0, y_, width_a,
                                       max(40, bottom - y_))
        self.panel_rect = pygame.Rect(ax0 - 4, top - 4,
                                      width_a + 8, bottom - top + 8)
        self.head_rect = pygame.Rect(ax0, top, width_a, head_h - 6)
        self.card_h, self.env_h = card_h, env_h

        # ================= производные точки арены ==========================
        self.arena_cx = arena_rect.centerx
        self.arena_cy = arena_rect.centery
        sep = max(90, int(col_b_w * 0.19))
        self.rl_pos = (self.arena_cx - sep, self.arena_cy)
        self.ai_pos = (self.arena_cx + sep, self.arena_cy)
        self.env_label_pos = (self.arena_cx, arena_rect.y + 2)
        self.transfer_lbl_y = arena_rect.bottom - 46
        self.finish_dy = -int(arena_rect.height * 0.35)

        # ================= гарантии целостности =============================
        problems = []
        # колонки по X
        if not (self.panel_rect.right <= bx0 - VG + 4):
            problems.append("A->B")
        if not (cx0 - VG >= actions_rect.right - 4):
            problems.append("B->C")
        # секции C по Y
        if btn_rect.bottom + 2 > caption_rect.top:
            problems.append("C1->C2")
        if caption_rect.bottom + 2 > graph_rect.top:
            problems.append("C2->C3")
        # секции B по Y
        if actions_rect.top < arena_rect.bottom - 4:
            problems.append("B1->B2")
        # сетки элементов против своих секций (с запасом 2px на рамку)
        for tr in self.tile_rects + [self.pick_rect]:
            pad = pygame.Rect(tr.x - 2, tr.y - 2, tr.w + 4, tr.h + 4)
            if pad.clamp(actions_rect) != pad:
                problems.append("tile-out-of-B2")
                break
        for br in rects + [self.speed_rect]:
            pad = pygame.Rect(br.x - 2, br.y - 2, br.w + 4, br.h + 4)
            if pad.clamp(btn_rect) != pad:
                problems.append("btn-out-of-C1")
                break
        if problems:
            LOG.warn("Layout %dx%d: геометрические нарушения %s"
                     % (w, h, set(problems)))

        LOG.debug("Layout %dx%d: A(metrik) x=%d..%d cards=%d/%d/%d/%d | "
                  "B arena y=%d..%d actions y=%d..%d tiles=%dx%d cell=%dx%d | "
                  "C btns y=%d..%d grid %dx%d cell=%dx%d caption y=%d..%d "
                  "graph y=%d..%d"
                  % (w, h, ax0, ax0 + width_a,
                     self.rl_card.height, self.ai_card.height,
                     self.env_card.height, self.status_zone.height,
                     arena_rect.top, arena_rect.bottom,
                     actions_rect.top, actions_rect.bottom,
                     trows, tcols, tcw, tch,
                     btn_rect.top, btn_rect.bottom, rows, cols, cw, ch,
                     caption_rect.top, caption_rect.bottom,
                     graph_rect.top, graph_rect.bottom))


# ---------------------------------------------------------------------------
# Тактовый движок партии: пошаговая обёртка над протоколом play_game
# ---------------------------------------------------------------------------

def _detect_form_intention_arity(cls):
    """Число позиционных аргументов RLAgent.form_intention (включая self).

    Возвращает 2 для form_intention(self, eps) и 3 для form_intention(self, eps, rng).
    Используется для совместного запуска с разными ревизиями simulation.py:
    в одной разведка epsilon-greedy идёт через глобальный random.*, в другой -
    через явный параметр rng. Ошибки интроспекции не роняют движок: при любом
    сбое считаем арность 2 (историческая сигнатура) и логируем предупреждение.
    """
    import inspect
    try:
        sig = inspect.signature(cls.form_intention)
        n = 0
        for prm in sig.parameters.values():
            if prm.kind in (prm.POSITIONAL_ONLY, prm.POSITIONAL_OR_KEYWORD):
                n += 1
        LOG.debug("_detect_form_intention_arity(%s): параметры=%s -> арность=%s"
                  % (cls.__name__, list(sig.parameters), n))
        return n
    except Exception as exc:
        LOG.warn("_detect_form_intention_arity: интроспекция не удалась (%r); "
                 "использую сигнатуру по умолчанию form_intention(eps)" % exc)
        return 2


class MatchEngine:
    """Одна партия RL vs UtilityAI в среде-автомате, шаг за шагом.

    Повторяет протокол simulation.play_game точно (зеркальные шаги, та же
    очерёдность фаз), но раскручивается по такту - чтобы движок мог рисовать
    промежуточное состояние и (в ручном режиме) подставлять действие игрока.

    Состояние партии (для визуализации переходов):
      events - список событий последнего такта:
        {"kind":"transfer","frm":"rl"|"ai","work":int,"hit":bool,"gained":int}
        {"kind":"capture","winner":"RL"|"UtilityAI","cap":int}
    """

    def __init__(self, seed=0, steps=2000, with_env=True, q_table=None,
                 profile_rl="CANON", profile_ai="CANON"):
        LOG.info("MatchEngine: новая партия seed=%s steps=%s env=%s "
                 "profiles=%s/%s" % (seed, steps, with_env, profile_rl, profile_ai))
        self.seed = seed
        self.rng = random.Random(seed)
        # Собственный rng для epsilon-greedy разведки RL: simulation.RLAgent.form_intention
        # использует глобальный random.* - изолируем его здесь (seed-детерминизм движка),
        # не изменяя код модели. Порядок вызовов канонический.
        self._rl_rng = random.Random(seed ^ 0x5EED)
        # Детект сигнатуры RLAgent.form_intention (совместимость с разными
        # ревизиями simulation.py): 2 - form_intention(eps), 3 - form_intention(eps, rng).
        self._fi_arity = _detect_form_intention_arity(RLAgent)
        LOG.debug("MatchEngine: сигнатура RLAgent.form_intention: "
                  "арность=%s (3 - принимает rng параметром)" % self._fi_arity)
        self.steps_total = steps
        self.step = 0
        self.winner = None            # "RL" | "UtilityAI" | None (идёт партия)
        self.finished = False
        self.events = []              # события последнего такта
        self.rl_hist, self.ai_hist = [], []

        # Профили сторон (один скаляр p, см. PROFILES) - без новых переменных.
        self.rl = RLAgent(q=q_table, profile=profile_rl)
        self.ai = UtilityAI(profile=profile_ai)
        self.with_env = with_env
        self.env = Environment(members=[self.rl, self.ai]) if with_env else None

        # Доминирование - свои счётчики (не трогаем глобальные _dom_* модуля;
        # локальная копия check_capture ниже эквивалентна ей по формулам).
        self.dom_rl = 0
        self.dom_ai = 0

        # Счётчик тактов покоя (для панели; вывод из last_act - новых полей модели нет)
        self.rl_rest_ticks = 0
        self.ai_rest_ticks = 0

        # Для ручного режима: последнее выбранное действие RL и его индекс.
        self.last_rl_action = ("REST", 0)
        self.last_ai_action = ("REST", 0)

    # --- Локальная проверка устойчивого доминирования (без глобального состояния)
    def _check_capture(self):
        rl, ai = self.rl, self.ai
        from simulation import CAPTURE_RATIO, CAPTURE_STREAK, CAPTURE_FRAC, L_STEP
        self.dom_rl = self.dom_rl + 1 if (
            rl.energy_pool >= CAPTURE_RATIO * ai.energy_pool and rl.force > ai.force) else 0
        self.dom_ai = self.dom_ai + 1 if (
            ai.energy_pool >= CAPTURE_RATIO * rl.energy_pool and ai.force > rl.force) else 0
        if self.dom_rl >= CAPTURE_STREAK:
            self.dom_rl = self.dom_ai = 0
            sev = 2.0 if ai.in_open else 1.0
            cap = int(ai.force * min(CAPTURE_FRAC * sev, 0.5))
            cap = int(cap * max(0.5, min(1.0, ai.p)))
            ai.force = max(1, ai.force - cap)
            ai.rest_units = max(0.0, ai.rest_units - cap / L_STEP)
            rl.gain(cap)
            return "RL", cap
        if self.dom_ai >= CAPTURE_STREAK:
            self.dom_ai = self.dom_rl = 0
            sev = 2.0 if rl.in_open else 1.0
            cap = int(rl.force * min(CAPTURE_FRAC * sev, 0.5))
            cap = int(cap * max(0.5, min(1.0, rl.p)))
            rl.force = max(1, rl.force - cap)
            rl.rest_units = max(0.0, rl.rest_units - cap / L_STEP)
            ai.gain(cap)
            return "UtilityAI", cap
        return None, 0

    def step_tick(self, forced_rl_action=None):
        """Один такт партии по фиксированному протоколу play_game.

        Args:
            forced_rl_action: None - RL выбирает сам (epsilon-greedy);
                индекс действия из ACTIONS - игрок управляет RL-агентом
                (обучение при этом продолжается на выбранном действии).

        Все исключения внутри такта логируются с полным стеком и ПЕРЕДАЮТСЯ
        вызывающему коду (игровой цикл перехватит их, не роняя окно).
        """
        if self.finished:
            LOG.debug("step_tick: пропуск - партия уже завершена "
                      "(winner=%s step=%s)" % (self.winner, self.step))
            return
        rl, ai, env = self.rl, self.ai, self.env
        rng = self.rng
        self.events = []

        # 1. Взаимное наблюдение (частичная наблюдаемость, шум - из rng партии).
        rl.sense(ai, rng)
        ai.sense(rl, rng)

        # 2. Ротация защит (профильно-модулируемая) + "погода" среды.
        rl.rotate_defense(rng)
        ai.rotate_defense(rng)
        if env is not None:
            env.rotate_defense(rng)

        # 3. Upkeep, пополнение пулов, тактовка входов (Шмитт), такт среды.
        rl.upkeep()
        ai.upkeep()
        rl.tick_energy()
        ai.tick_energy()
        rl.tick_input_state()
        ai.tick_input_state()
        if env is not None:
            env.tick()

        # 4. Намерения. RL: epsilon-greedy (annealing до 0.05 за 300 шагов)
        #    или действие игрока; Utility: argmax U; рефлекс голода - выше обоих.
        eps = max(0.05, 1.0 - self.step / 300)
        LOG.debug("tick %s: фаза намерений eps=%.3f forced=%s"
                  % (self.step, eps, forced_rl_action))
        if forced_rl_action is not None:
            a_idx = int(forced_rl_action) % len(ACTIONS)
            LOG.debug("tick %s: RL действует по команде игрока: idx=%s"
                      % (self.step, a_idx))
            # В ручном режиме состояние всё равно должно существовать в Q -
            # иначе TD-обновление на неинициализированной строке дало бы KeyError.
            st_probe = rl.skey()
            if st_probe not in rl.Q:
                rl.Q[st_probe] = [0.0] * len(ACTIONS)
        else:
            # Совместимость с API: в разных ревизиях simulation.py метод имеет
            # сигнатуру form_intention(self, eps) [глобальный random.*] либо
            # form_intention(self, eps, rng). Определяем её один раз при старте
            # (_detect_form_intention_arity) и вызываем корректно.
            #
            # Разведка epsilon-greedy всегда идёт через собственный rng движка:
            # если модель использует глобальный random.*, временно подменяем его
            # (сохраняя семантику выбора и seed-детерминизм партии); если модель
            # принимает rng параметром - передаём тот же rng напрямую.
            if self._fi_arity == 3:
                a_idx = rl.form_intention(eps, self._rl_rng)
            else:
                import simulation as _sim
                _saved = _sim.random
                _sim.random = self._rl_rng
                try:
                    a_idx = rl.form_intention(eps)
                finally:
                    _sim.random = _saved
        act_name, frac = ACTIONS[a_idx]
        st_before = rl.skey()
        f_before = rl.force

        if rl.rest_if_starving():
            w_rl = 0
            act_name = "REST"
            LOG.debug("tick %s: RL рефлекс голода -> REST" % self.step)
        else:
            w_rl = rl.commit(act_name, rl.energy_pool * frac)
        self.last_rl_action = (act_name, w_rl)

        ai_act, ai_work = ai.form_intention()
        if ai.rest_if_starving():
            w_ai = 0
            ai_act = "REST"
            LOG.debug("tick %s: AI рефлекс голода -> REST" % self.step)
        else:
            w_ai = ai.commit(ai_act, ai_work)
        self.last_ai_action = (ai_act, w_ai)
        LOG.debug("tick %s: RL act=%s work=%s | AI act=%s work=%s"
                  % (self.step, act_name, w_rl, ai_act, w_ai))

        # 5. Разрешение передач по единому закону (нагружают и вход среды).
        #    Оборачиваем resolve_attack, чтобы зафиксировать исходы для анимации:
        ev_rl = self._resolve_with_events(rl, ai, w_rl, "rl")
        ev_ai = self._resolve_with_events(ai, rl, w_ai, "ai")
        if w_rl:
            self.events.append(ev_rl)
        if w_ai:
            self.events.append(ev_ai)

        # 6. TD-обучение RL на корректном переходе s -> s' (награда = delta F).
        rl.learn(st_before, a_idx, rl.force - f_before, rl.skey())

        # 7. Устойчивое доминирование.
        winner, cap = self._check_capture()
        if winner:
            LOG.info("tick %s: CAPTURE - победитель %s (cap=%s)"
                     % (self.step, winner, cap))
            self.events.append({"kind": "capture", "winner": winner, "cap": cap})
            self.winner = winner
            self.finished = True

        self.rl_hist.append(rl.force)
        self.ai_hist.append(ai.force)
        if w_rl == 0:
            self.rl_rest_ticks += 1
        if w_ai == 0:
            self.ai_rest_ticks += 1
        self.step += 1
        if not self.finished and self.step >= self.steps_total:
            LOG.info("tick %s: лимит шагов (%s) - партия без решения"
                     % (self.step, self.steps_total))
            self.finished = True   # без решения за steps тактов
        LOG.debug("tick %s -> F(RL)=%.1f F(AI)=%.1f E(RL)=%s E(AI)=%s "
                  "env.F=%.1f env.open=%s RL.open=%s AI.open=%s finished=%s"
                  % (self.step, rl.force, ai.force, rl.energy_pool,
                     ai.energy_pool,
                     env.force if env else -1,
                     env.in_open if env else False,
                     rl.in_open, ai.in_open, self.finished))

    def _resolve_with_events(self, att, dfn, work, who):
        """Вызов канонического resolve_attack + фиксация исхода для отрисовки.

        Результат передачи (hit/gained) внутри resolve_attack не возвращается;
        движок подменяет rng партии обёрткой, которая перехватывает ровно те
        броски, что делает сам закон (первый - проверка попадания адресанта),
        не изменяя ни последовательность чисел, ни формулы (seed-детерминизм
        сохраняется). Остальные признаки (gained) выводятся из дельты силы.
        """
        f_att_before = att.force
        res = {"kind": "transfer", "frm": who, "work": work,
               "hit": False, "gained": 0, "type": att.last_act if work else "REST"}

        captured = {}

        class _ProbeRng:
            """Прозрачная обёртка над rng: первое random() запоминаем."""
            def __init__(self, base):
                self._base = base
                self._first_done = False

            def random(self):
                v = self._base.random()
                if not self._first_done:
                    captured["hit_roll"] = v
                    self._first_done = True
                return v

            def __getattr__(self, name):
                return getattr(self._base, name)

        probe = _ProbeRng(self.rng)
        resolve_attack(att, dfn, work, probe, self.env)
        p = p_success(att.last_act, work, dfn.defense, dfn.last_work) \
            if work else 1.0
        # Попадание адресанта: первый бросок закона против вероятности успеха.
        # (p_success вычисляется ДО броска в resolve_attack; здесь тот же вызов
        # даёт ту же вероятность - аргументы не изменились к моменту обёртки.)
        if work and captured.get("hit_roll", 1.0) < p:
            res["hit"] = True
        delta = att.force - f_att_before
        cost = int(PARAMETERS["COST_FRACTION"] * work)
        if res["hit"]:
            res["gained"] = max(0, int(delta + cost))
        LOG.debug("transfer %s: type=%s work=%s p=%.2f roll=%s hit=%s gained=%s"
                  % (who, res["type"], work, p,
                     captured.get("hit_roll"), res["hit"], res["gained"]))
        return res


# ---------------------------------------------------------------------------
# Встроенный растровый шрифт 3x5 (fallback).
# Используется, если подсистема pygame.font недоступна (битая сборка freetype
# в pygame 2.6.x на Python 3.14 и т.п.). Зависимость от шрифтов сводится к нулю:
# текст рендерится точками через pygame.draw.rect -- только SDL-примитивы.
# GLYPHS: строки bitmap'а сверху вниз, '#' -- пиксель.
# Символика строго латиница/кириллица + ASCII-знаки (без "битых" юникодов:
# никаких стрелок, математических знаков, ёмодзи; дефис везде обычный '-').
# ---------------------------------------------------------------------------

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

# Кириллица для fallback-шрифта (чтобы HUD оставался русским даже при мёртвом
# pygame.font). Буквы, совпадающие по начертанию с латиницей, наследуют глифы.
_CYR = {
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
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

# Нормализация: любые "битые" юникоды приводятся к безопасным знакам до рендера
# (строгая политика: в выводе только латиница, кириллица и ASCII-знаки).
_NORMALIZE = {
    "\u2014": "-", "\u2013": "-", "\u2212": "-",   # em/en dash, minus sign
    "\u00b7": ".",                                  # middle dot
    "\u00a0": " ", "\u2009": " ", "\u202f": " ",   # неразрывные пробелы
    "\u201c": '"', "\u201d": '"', "\u00ab": '"', "\u00bb": '"',
    "\u2018": "'", "\u2019": "'",
    "\u2192": "->", "\u2190": "<-", "\u2194": "<->", "\u2264": "<=",
    "\u2265": ">=", "\u2248": "~", "\u2500": "-", "\u2502": "|",
    "\u250c": "+", "\u2510": "+", "\u2514": "+", "\u2518": "+",
    "\u25cf": "o", "\u25cb": "o", "\u25a0": "#", "\u25a1": "[]",
    "\u2713": "v", "\u2714": "v", "\u2717": "x", "\u2718": "x",
    "\u25b2": "^", "\u25b3": "^", "\u25bc": "v", "\u25bd": "v",
    "\u25c0": "<", "\u25c4": "<", "\u25b6": ">", "\u25ba": ">",
    "\u00d7": "x", "\u00f7": "/", "\u00b1": "+/-", "\u2260": "!=",
    "\u2026": "...", "\u2022": "*",
}
_INVISIBLE = dict.fromkeys(
    [0x200b, 0x200c, 0x200d, 0x2060, 0xfeff, 0x00ad], "")


def sanitize_text(text):
    """Только латиница, кириллица и ASCII-знаки; прочее -> безопасные аналоги."""
    for src, dst in _NORMALIZE.items():
        text = text.replace(src, dst)
    out = []
    for ch in text:
        o = ord(ch)
        if (32 <= o < 127 or 0x400 <= o <= 0x4FF          # ASCII/Cyrillic
                or ch in _GLYPHS_ASCII):                   # уже легальный знак
            out.append(ch)
        elif o in _INVISIBLE:
            continue
        elif o > 127:
            out.append("?")                                # явный маркер, не ?
        else:
            out.append("?")
    return "".join(out)


GLYPHS = _GLYPHS_ASCII


class BitmapText:
    """Минималистичный текстовый рендер без pygame.font (масштаб = размер пикселя)."""

    W, H = 3, 5
    SEP = 1

    def size(self, text):
        text = self._prep(text)
        lines = text.split("\n")
        w = max((len(ln) * (self.W + self.SEP) - self.SEP for ln in lines),
                default=0)
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
                            surf, color,
                            (x + col_i * scale, y + row_i * scale, scale, scale))
            x += (self.W + self.SEP) * scale
        return surf


class _SafePyFont:
    """Обёртка над pygame.font.Font: текст проходит sanitize_text() перед
    рендером (гарантия: никаких "битых" юникодов на экране), а любые сбои
    freetype при рисовании не роняют движок."""

    def __init__(self, font):
        self._f = font

    def render(self, text, _antialias=True, color=(255, 255, 255)):
        text = sanitize_text(str(text))
        try:
            surf = self._f.render(text, True, color)
        except Exception:                 # мёртвый freetype: вместо падения - прочерк
            surf = pygame.Surface((max(1, len(text) * 7), 14), pygame.SRCALPHA)
            pygame.draw.rect(surf, color, surf.get_rect(), 1)
        return surf

    def size(self, text):
        return self._f.size(sanitize_text(str(text)))


class FontSet:
    """Единый интерфейс шрифтов: либо pygame.font (если жив), либо BitmapText.

    Атрибуты .font/.font_s/.font_b возвращают объект с методом
    render(text, antialias, color) -> Surface, как у pygame.font.Font.
    """

    def __init__(self):
        self.pygame_font = None          # рабочий pygame.font.Font или None
        self.bitmap = BitmapText()
        self.cyrillic_ok = False
        self.note = ""

    @property
    def is_bitmap(self):
        return self.pygame_font is None

    def setup(self, probe):
        """probe - результат _probe_font(): Font или None."""
        if probe is not None:
            import pygame.font as pf
            try:
                self.pygame_font = pf
                self._f_default = _SafePyFont(probe)
                self._f_small = _SafePyFont(pf.Font(None, 14))
                self._f_big = _SafePyFont(pf.Font(None, 24))
                self.cyrillic_ok = (self._f_default.size("Я")[0] > 0
                                    and self._f_default.render(
                                        "Я", True, (255, 255, 255)).get_width() > 0)
                return
            except Exception as e:       # на всякий случай
                self.note = str(e)
                self.pygame_font = None
        # fallback: растровый шрифт, масштабы подобраны под прежние кегли
        self.note = _FONT_NOTE or "pygame.font unavailable"
        # Растровый шрифт содержит полный набор кириллицы -> HUD остаётся русским.
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
            return {"default": self._f_default, "small": self._f_small,
                    "big": self._f_big}[name]
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


# ---------------------------------------------------------------------------
# Графическое приложение
# ---------------------------------------------------------------------------

class GameApp:
    def __init__(self, fonts=None):
        LOG.info("GameApp: pygame.init()...")
        pygame.init()
        LOG.debug("pygame.init выполнен; подсистемы display=%s" %
                  (pygame.display.get_init(),))
        # Автоподбор размера окна под экран (соотношение 12:9).
        global SCREEN_W, SCREEN_H
        SCREEN_W, SCREEN_H = compute_window_size()
        flags = pygame.RESIZABLE          # пользователь может тянуть окно -
        #                           геометрия HUD пересчитается на VIDEORESIZE
        self._fullscreen = False
        if "--fullscreen" in sys.argv or "-f" in sys.argv:
            flags = pygame.FULLSCREEN
            self._fullscreen = True
            LOG.info("полноэкранный режим запрошен флагом %s"
                     % ("--fullscreen" if "--fullscreen" in sys.argv else "-f"))
        try:
            self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), flags)
        except Exception as exc:
            LOG.warn("set_mode(%s,%s,flags=%s) не удался (%s) - оконный режим 12:9"
                     % (SCREEN_W, SCREEN_H, flags, exc))
            SCREEN_W, SCREEN_H = compute_window_size()
            self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H),
                                                  pygame.RESIZABLE)
        pygame.display.set_caption("Ozvering-Project - IPO Arena (PyGame)")
        LOG.info("окно создано: %sx%s driver=%s"
                 % (SCREEN_W, SCREEN_H, pygame.display.get_driver()))
        self.clock = pygame.time.Clock()
        # Шрифты: если pygame.font работает - используем его (кириллица возможна);
        # если нет (битый freetype в pygame 2.6.x / Python 3.14) - встроенный
        # растровый шрифт BitmapText, зависимость от pygame.font = 0.
        self.fonts = fonts or FontSet()
        if self.fonts.pygame_font is None and not self.fonts.note:
            self.fonts.setup(_probe_font())
        self.cyrillic_ok = self.fonts.cyrillic_ok
        LOG.info("шрифты: режим=%s кириллица=%s note=%r"
                 % ("bitmap-fallback" if self.fonts.is_bitmap else "pygame.font",
                    self.cyrillic_ok, self.fonts.note))
        self.font = self.fonts.font
        self.font_s = self.fonts.font_s
        self.font_b = self.fonts.font_b

        def L(ru, en):
            """Двуязычная строка HUD: кириллица доступна - ru, иначе - en."""
            return ru if self.cyrillic_ok else en
        self.L = L

        self.paused = True
        self.manual_mode = False       # игрок управляет RL-агентом
        self.show_help = True
        self.ticks_per_sec = 8.0       # темп симуляции
        self.acc = 0.0
        self.time = 0.0                # вещественное время для пульсаций
        self._flash_until = 0.0        # до какого момента мигает кнопка START
        self._btn_flash = ""           # текст последней нажатой кнопки (для флеша)

        # Геометрия HUD под фактический размер окна: пять изолированных зон
        # (метрики | арена | график | действия | кнопки) - см. Layout.
        self.layout = Layout(SCREEN_W, SCREEN_H, len(ACTIONS))
        self.buttons = self.layout.buttons

        # Общая Q-таблица - перенос обучения между партиями (как run_batch).
        self.q_table = {}
        self.game_seed = 0
        self.match = MatchEngine(seed=self.game_seed, q_table=self.q_table)

        # Выбор действия в ручном режиме: индекс в ACTIONS.
        self.action_idx = 0

        # Скользящие графики силы (последние N тактов).
        self.history_len = 240

        # Счётчики диагностических кадров и защита от "шквала" одинаковых ошибок.
        self._draw_count = 0
        self._err_counts = {}
        LOG.info("GameApp: инициализация завершена (seed=%s, кнопок=%s)"
                 % (self.game_seed, len(self.buttons)))

    # ---------------- ввод ----------------
    def _press(self, name):
        """Единая точка отклика на команду (клавиша или клик). Возвращает
        False только для выхода."""
        LOG.info("команда: %s (источник: клавиша/клик)" % name)
        if name == "QUIT":
            return False
        if name == "START":
            self.paused = not self.paused
            LOG.info("START/PAUSE -> paused=%s" % self.paused)
            self._btn_flash, self._flash_until = "START", self.time + 0.35
        elif name == "STEP":
            if not self.match.finished:
                forced = self.action_idx if self.manual_mode else None
                LOG.debug("STEP: tick %s forced=%s manual=%s"
                          % (self.match.step, forced, self.manual_mode))
                self.match.step_tick(forced_rl_action=forced)
                self._btn_flash, self._flash_until = "STEP", self.time + 0.35
            else:
                LOG.warn("STEP проигнорирован: партия завершена "
                         "(winner=%s) - нажмите RESET" % self.match.winner)
        elif name == "SLOWER":
            self.ticks_per_sec = max(0.5, self.ticks_per_sec / 1.5)
            LOG.info("SPEED -> %.1f тик/с" % self.ticks_per_sec)
            self._btn_flash, self._flash_until = "SPEED", self.time + 0.35
        elif name == "FASTER":
            self.ticks_per_sec = min(60.0, self.ticks_per_sec * 1.5)
            LOG.info("SPEED -> %.1f тик/с" % self.ticks_per_sec)
            self._btn_flash, self._flash_until = "SPEED", self.time + 0.35
        elif name == "MODE":
            self.manual_mode = not self.manual_mode
            LOG.info("MODE -> %s" % ("MANUAL (игрок->RL)" if self.manual_mode
                                     else "OBSERVE"))
            self._btn_flash, self._flash_until = "MODE", self.time + 0.35
        elif name == "RESET":
            self.new_match()
            self._btn_flash, self._flash_until = "RESET", self.time + 0.35
        elif name == "HELP":
            self.show_help = not self.show_help
            LOG.info("HELP -> %s" % self.show_help)
        return True

    def handle_events(self):
        for e in pygame.event.get():
            # MouseMotion и прочие «фоновые» события не логируем - они забивают
            # консоль (десятки строк на движение мыши). Логируем только значимые:
            # нажатия клавиш, клики мыши, QUIT/оконные события.
            if e.type not in (pygame.MOUSEMOTION,):
                LOG.debug("событие: type=%s(%s) key=%s button=%s pos=%s"
                          % (e.type, pygame.event.event_name(e.type),
                             getattr(e, "key", "-"), getattr(e, "button", "-"),
                             getattr(e, "pos", "-")))
            if e.type == pygame.QUIT:
                LOG.info("получено SDL QUIT - закрытие окна")
                return False
            if e.type == pygame.VIDEORESIZE and not self._fullscreen:
                # Пользователь потянул окно за край: пересоздаём surface и
                # ПОЛНОСТЬЮ пересчитываем геометрию HUD (Layout гарантирует
                # непересекающиеся зоны при любом размере).
                global SCREEN_W, SCREEN_H
                nw, nh = int(e.w), int(e.h)
                if (nw, nh) != (SCREEN_W, SCREEN_H):
                    SCREEN_W, SCREEN_H = nw, nh
                    self.screen = pygame.display.set_mode(
                        (SCREEN_W, SCREEN_H), pygame.RESIZABLE)
                    try:
                        self.layout = Layout(SCREEN_W, SCREEN_H, len(ACTIONS))
                        self.buttons = self.layout.buttons
                        LOG.info("VIDEORESIZE -> %dx%d: Layout пересобран"
                                 % (SCREEN_W, SCREEN_H))
                    except Exception as exc:
                        LOG.exc("Layout после resize", exc, key="resize")
                continue
            if e.type == pygame.KEYDOWN:
                k = e.key
                LOG.debug("KEYDOWN keycode=%s mod=%s" % (k, e.mod))
                if k in (pygame.K_ESCAPE, pygame.K_q):
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
                elif k in (pygame.K_UP, pygame.K_RIGHT, pygame.K_PLUS,
                           pygame.K_KP_PLUS, pygame.K_EQUALS):
                    self._press("FASTER")
                elif k in (pygame.K_DOWN, pygame.K_LEFT, pygame.K_MINUS,
                           pygame.K_KP_MINUS):
                    self._press("SLOWER")
                elif pygame.K_1 <= k <= pygame.K_1 + len(ACTIONS) - 1:
                    # Цифры выбирают действие ВСЕГДА (не только в ручном режиме и
                    # не только на ходу) - выбор подсвечивается на плитках.
                    self.action_idx = (k - pygame.K_1) % len(ACTIONS)
                    LOG.info("выбор действия клавишей: idx=%s act=%s%s"
                             % (self.action_idx, ACTIONS[self.action_idx][0],
                                " (включён РУЧНОЙ режим)"
                                if not self.manual_mode else ""))
                    if not self.manual_mode:
                        self.manual_mode = True   # цифра = игрок берёт управление
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                hit = False
                for name, _label, rect in self.buttons:
                    if rect.collidepoint(e.pos):
                        hit = True
                        LOG.debug("клик (%s,%s) -> кнопка %s"
                                  % (e.pos[0], e.pos[1], name))
                        if not self._press(name):
                            return False
                        break
                if not hit:
                    idx = self._action_at_mouse(e.pos)
                    if idx is not None:
                        LOG.debug("клик (%s,%s) -> плитка действия idx=%s act=%s"
                                  % (e.pos[0], e.pos[1], idx, ACTIONS[idx][0]))
                        self.action_idx = idx
                        if not self.manual_mode:
                            LOG.info("клик по плитке -> включён РУЧНОЙ режим")
                            self.manual_mode = True
                    else:
                        LOG.debug("клик (%s,%s) мимо кнопок/плиток - бездействие"
                                  % (e.pos[0], e.pos[1]))
        return True

    def _action_at_mouse(self, pos):
        """Попадание по плиткам действий (плитки рисуем всегда - они кликабельны)."""
        tiles = self._action_tiles()
        for i, rect in enumerate(tiles):
            if rect.collidepoint(pos):
                return i
        return None

    def _action_tiles(self):
        return self.layout.tile_rects

    def new_match(self):
        """Новая партия: свежие автоматы и среда; Q-таблица RL сохраняется."""
        old = self.match
        LOG.info("RESET: старая партия seed=%s step=%s finished=%s winner=%s -> "
                 "новая партия" % (old.seed, old.step, old.finished, old.winner))
        self.game_seed += 1
        self.match = MatchEngine(seed=self.game_seed, q_table=self.q_table)
        self.paused = True
        LOG.info("RESET завершён: paused=True seed=%s (Q-таблица перенесена, "
                 "%s состояний)" % (self.game_seed, len(self.q_table)))

    # ---------------- логика ----------------
    def update(self, dt):
        self.time += dt
        LOG.set_sim_time(self.time)
        if self.paused or self.match.finished:
            return
        self.acc += dt * self.ticks_per_sec
        n = 0
        while self.acc >= 1.0:
            self.acc -= 1.0
            forced = self.action_idx if self.manual_mode else None
            self.match.step_tick(forced_rl_action=forced)
            n += 1
            if self.match.finished:
                break
        if n and LOG.level >= 3:
            LOG.debug("update: тактов за кадр=%s tick=%s acc=%.2f"
                      % (n, self.match.step, self.acc))

    # ---------------- отрисовка ----------------
    def draw(self):
        s = self.screen
        m = self.match
        env = m.env

        # Фон - сила среды; золотая рамка - открытое окно конъюнктуры.
        bg = env_bg_color(env.force if env else 10.0)
        s.fill(bg)
        if env is not None and env.in_open:
            glow = 160 + 60 * math.sin(self.time * 6.0)
            pygame.draw.rect(s, (int(glow), int(glow * 0.78), 40),
                             s.get_rect(), width=4)

        self.draw_panel(s, m)               # колонка A - метрики
        self._draw_zone_separators(s)       # границы колонок A|B|C и секций
        self.draw_agents(s, m)              # B1 - арена
        self.draw_transfers(s, m)           # B1 - стрелки передач
        self.draw_env_info(s, m)            # B1 - подпись среды сверху арены
        self.draw_history(s, m)             # C3 - график в своей рамке
        self.draw_caption(s, m)             # C2 - подпись PAUSE/RUN + pick
        if self.show_help:
            self.draw_help(s)              # справка занимает секцию B2...
        else:
            self.draw_action_bar(s)        # ...иначе там же - плитки действий
        self.draw_buttons(s)               # C1 - кнопки HUD (мышь = клавиши)
        self.draw_status(s, m)

        pygame.display.flip()

    def _draw_zone_separators(self, s):
        """Тонкие разделители между колонками A|B|C и секциями внутри них.

        Линии рисуются точно посередине зазоров и не задевают ни одну секцию -
        они лишь визуально подтверждают границы трёх пространств.
        """
        L_ = self.layout
        col = (58, 62, 72)
        top, bottom = L_.EDGE, L_.h - L_.EDGE
        # вертикальные границы колонок (посередине VGAP)
        x_ab = (L_.panel_rect.right + L_.arena_rect.left) // 2
        x_bc = (L_.actions_rect.right + L_.ctrl_rect.left) // 2
        pygame.draw.line(s, col, (x_ab, top), (x_ab, bottom))
        pygame.draw.line(s, col, (x_bc, top), (x_bc, bottom))
        # горизонтальные: арена/действия в B, кнопки/подпись/график в C
        y_ba = (L_.arena_rect.bottom + L_.actions_rect.top) // 2
        pygame.draw.line(s, col, (L_.arena_rect.x, y_ba),
                         (L_.actions_rect.right, y_ba))
        y_bc1 = (L_.ctrl_rect.bottom + L_.caption_rect.top) // 2
        pygame.draw.line(s, col, (L_.ctrl_rect.x, y_bc1),
                         (L_.ctrl_rect.right, y_bc1))
        y_bc2 = (L_.caption_rect.bottom + L_.hist_rect.top) // 2
        pygame.draw.line(s, col, (L_.caption_rect.x, y_bc2),
                         (L_.caption_rect.right, y_bc2))

    def draw_panel(self, s, m):
        """Колонка A: заголовок + карточки RL/AI/СРЕДА/СТАТУС (метрики)."""
        L_ = self.layout
        pw = L_.width_a
        # Подложка всей колонки A + внешняя рамка.
        pygame.draw.rect(s, COL_PANEL, L_.panel_rect)
        pygame.draw.rect(s, (60, 64, 74), L_.panel_rect.inflate(-2, -2), 1)

        # Заголовок сверху; секции начинаются строго под ним (head_rect).
        t = self.font_b.render("OZVERING - IPO ARENA", True, COL_OPEN)
        if t.get_width() > pw - 8:
            t = self.font_s.render("OZVERING - IPO ARENA", True, COL_OPEN)
        s.blit(t, (L_.panel_rect.x + 6, L_.head_rect.y + 2))
        t2 = self.font_s.render(
            f"tick {m.step}/{m.steps_total}  seed {m.seed}", True, COL_DIM)
        s.blit(t2, (L_.panel_rect.x + 6, L_.head_rect.y + 24))

        def card(rect, border=(52, 56, 66)):
            r = rect
            pygame.draw.rect(s, (28, 31, 38), r, border_radius=5)
            pygame.draw.rect(s, border, r, 1, border_radius=5)
            return r

        # --- секции RL / AI колонки A ---------------------------------------
        sides = ((self.L("RL AGENT (обучающийся)", "RL AGENT (learning)"),
                  m.rl, COL_RL, m.last_rl_action, m.rl_rest_ticks, L_.rl_card),
                 (self.L("UTILITY AI (скрипт)", "UTILITY AI (scripted)"),
                  m.ai, COL_AI, m.last_ai_action, m.ai_rest_ticks, L_.ai_card))
        for title, ag, acc, last_act, rest_ticks, crect in sides:
            r = card(crect, border=(acc[0] // 2, acc[1] // 2, acc[2] // 2))
            x, y = r.x + 8, r.y + 5
            small = self.font_s
            dy = max(12, min(int(15 * self.layout.sc),
                             (r.height - 10) // 6))
            rows = [
                (title, acc),
                (f"F={ag.force:6.1f} E={ag.energy_pool:4.0f} reg={ag.regen}",
                 COL_TEXT),
                (f"def [{ag.defense}] L={ag.rest_ceiling:.0f}"
                 f" RU={ag.rest_units:.0f}", COL_TEXT),
            ]
            on = ag.schmitt_on()
            win = ("OPEN " + str(ag.open_timer)) if ag.in_open else "closed"
            rows.append((f"w_adopt={ag.w_adopt:6.1f}/{on:5.1f}",
                         COL_OPEN if ag.in_open else COL_TEXT))
            bw = r.width - 16
            for txt, col in rows:
                t_ = small.render(txt, True, col)
                if t_.get_width() > bw:      # строка шире карточки - режем
                    while t_.get_width() > bw and len(txt) > 8:
                        txt = txt[:max(8, len(txt) - 4)] + ".."
                        t_ = small.render(txt, True, col)
                if y + t_.get_height() <= r.bottom - 3:   # клиппинг по секции
                    s.blit(t_, (x, y))
                y += dy
            # строка окна Шмитта справа от полосы давления - в пределах карточки
            wt = small.render(win, True, COL_OPEN if ag.in_open else COL_DIM)
            if wt.get_width() <= bw:
                s.blit(wt, (max(x, r.right - wt.get_width() - 8),
                            y - dy + max(0, (dy - wt.get_height()) // 2)))
            # полоса давления входа - внутри карточки
            bar_col = TYPE_COLORS[ag.defense]
            frac = min(1.0, ag.w_adopt / max(1e-9, on))
            pygame.draw.rect(s, (50, 52, 60), (x, y + 1, bw, 6))
            pygame.draw.rect(s, bar_col, (x, y + 1, int(bw * frac), 6))
            y += 10
            act_line = (f"act {last_act[0]} w:{float(last_act[1]):.0f}"
                        f" rest:{rest_ticks}")
            at = small.render(act_line, True, COL_DIM)
            # если строка не влезает по ширине карточки - режем хвост
            while (at.get_width() > bw and len(act_line) > 12):
                act_line = act_line[:-6] + ".."
                at = small.render(act_line, True, COL_DIM)
            if y + at.get_height() <= r.bottom - 2:
                s.blit(at, (x, y))

        # --- секция СРЕДА колонки A ------------------------------------------
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
                        txt = txt[:max(8, len(txt) - 4)] + ".."
                        t_ = small.render(txt, True, col)
                if y + t_.get_height() <= r.bottom - 2:
                    s.blit(t_, (x, y))
                if right_txt:
                    wt_ = small.render(right_txt[0], True, right_txt[1])
                    if wt_.get_width() + t_.get_width() < bw:
                        s.blit(wt_, (max(x, r.right - wt_.get_width() - 8), y))
                y += dy

            blit_row(self.L("СРЕДА-АВТОМАТ", "ENVIRONMENT"), COL_ENV_OPEN)
            blit_row(f"F={e.force:7.1f} E={e.energy_pool:4.0f}",
                     TYPE_COLORS[e.defense],
                     (f"weather[{e.defense}]", TYPE_COLORS[e.defense]))
            blit_row(f"w_adopt={e.w_adopt:6.1f}/{e.schmitt_on():5.1f}",
                     COL_TEXT,
                     ("WINDOW OPEN" if e.in_open else "closed",
                      COL_ENV_OPEN if e.in_open else COL_DIM))
            blit_row(f"members: {len(e.members)} bonus: "
                     f"{PARAMETERS['ENV_BONUS'] if e.in_open else 0:+.2f}",
                     COL_DIM)

        # --- секция СТАТУС колонки A -----------------------------------------
        r = card(L_.status_zone, border=(60, 64, 74))
        x, y = r.x + 8, r.y + 5
        small = self.font_s
        dy = max(12, (r.height - 10) // 4)
        bw = r.width - 16
        mode_txt = ("MODE: " + (self.L("РУЧНОЙ (игрок->RL)", "MANUAL (player->RL)")
                               if self.manual_mode else "OBSERVE"))
        t_ = small.render(mode_txt, True,
                          COL_OPEN if self.manual_mode else COL_DIM)
        if y + t_.get_height() <= r.bottom - 2:
            s.blit(t_, (x, y))
        y += dy
        t_ = small.render(f"Q-states: {len(m.rl.Q)}", True, COL_DIM)
        if y + t_.get_height() <= r.bottom - 2:
            s.blit(t_, (x, y))
        y += dy
        t_ = small.render(f"profiles: RL p={m.rl.p} AI p={m.ai.p}",
                          True, COL_DIM)
        if t_.get_width() > bw:
            t_ = small.render(f"p: RL={m.rl.p} AI={m.ai.p}", True, COL_DIM)
        if y + t_.get_height() <= r.bottom - 2:
            s.blit(t_, (x, y))
        y += dy
        streak = max(m.dom_rl, m.dom_ai)
        if streak:
            who = "RL dominates" if m.dom_rl else "AI dominates"
            frac = streak / PARAMETERS["CAPTURE_STREAK"]
            if y + 20 <= r.bottom - 2:
                pygame.draw.rect(s, (50, 52, 60), (x, y + 2, bw, 7))
                pygame.draw.rect(s, COL_OPEN, (x, y + 2, int(bw * frac), 7))
                s.blit(small.render(who, True, COL_OPEN), (x, y + 12))
        else:
            t_ = small.render(self.L("серия захвата: нет",
                                     "capture streak: none"), True, COL_DIM)
            if y + 2 + t_.get_height() <= r.bottom - 2:
                s.blit(t_, (x, y + 2))

    def draw_agents(self, s, m):
        """Круги-автоматы: радиус от силы, рамка от типа защиты, кольцо Шмитта."""
        for pos, ag, acc in ((self.layout.rl_pos, m.rl, COL_RL),
                             (self.layout.ai_pos, m.ai, COL_AI)):
            r = agent_radius(ag.force)
            # Тело
            body = pygame.Surface((2 * r + 8, 2 * r + 8), pygame.SRCALPHA)
            pygame.draw.circle(body, (*acc[:3], 28), (r + 4, r + 4), r + 3)
            s.blit(body, (pos[0] - r - 4, pos[1] - r - 4))
            # Пульсация при открытом окне входа
            outline = TYPE_COLORS[ag.defense]
            width = 3
            if ag.in_open:
                pulse = 0.5 + 0.5 * math.sin(self.time * 10.0)
                glow_r = r + 6 + int(6 * pulse)
                gs = pygame.Surface((2 * glow_r + 8, 2 * glow_r + 8), pygame.SRCALPHA)
                pygame.draw.circle(gs, (*COL_OPEN, int(70 + 60 * pulse)),
                                   (glow_r + 4, glow_r + 4), glow_r, width=3)
                s.blit(gs, (pos[0] - glow_r - 4, pos[1] - glow_r - 4))
                outline, width = COL_OPEN, 3
            pygame.draw.circle(s, outline, pos, r, width=width)
            # Кольцо давления w_adopt (дуга от верхнего края по часовой)
            on = ag.schmitt_on()
            frac = min(1.0, ag.w_adopt / max(1e-9, on))
            rr = r + 10
            rect_ring = pygame.Rect(pos[0] - rr, pos[1] - rr, 2 * rr, 2 * rr)
            if frac > 0.003:
                pygame.draw.arc(s, COL_OPEN, rect_ring,
                                math.pi / 2, math.pi / 2 - 2 * math.pi * frac, 3)
            else:
                pygame.draw.circle(s, (70, 72, 80), pos, rr, width=1)
            # Метка
            label = "RL" if acc == COL_RL else "AI"
            txt = self.font_b.render(label, True, acc)
            s.blit(txt, (pos[0] - txt.get_width() // 2, pos[1] - 10))
            ft = self.font_s.render(f"F{ag.force:.0f} E{ag.energy_pool}",
                                    True, COL_TEXT)
            s.blit(ft, (pos[0] - ft.get_width() // 2, pos[1] + 12))
            if ag.in_open:
                ot = self.font_s.render(f"open:{ag.open_timer}", True, COL_OPEN)
                s.blit(ot, (pos[0] - ot.get_width() // 2, pos[1] - r - 30))
        # В ручном режиме показываем, чем именно игрок управляет (RL), и его выбор
        if self.manual_mode:
            pick = f"PICK: {ACTIONS[self.action_idx][0]}" \
                   f" {int(ACTIONS[self.action_idx][1]*100)}%"
            pt_ = self.font_s.render(pick, True, COL_OPEN)
            s.blit(pt_, (self.layout.rl_pos[0] - pt_.get_width() // 2,
                         self.layout.rl_pos[1] - 96))
            hint = self.L("вы управляете RL", "you control RL")
            ht = self.font_s.render(hint, True, COL_DIM)
            s.blit(ht, (self.layout.rl_pos[0] - ht.get_width() // 2,
                        self.layout.rl_pos[1] - 82))
        # Явный индикатор паузы - чтобы реакция на SPACE/START была заметна
        if self.paused and not self.match.finished:
            msg = self.L("ПАУЗА: SPACE или START - пуск, STEP - один такт",
                         "PAUSED: SPACE or START to run, STEP for one tick")
            t = self.font.render(msg, True, COL_OPEN)
            s.blit(t, (self.layout.arena_cx - t.get_width() // 2,
                       self.layout.transfer_lbl_y))

    def draw_transfers(self, s, m):
        """Стрелки передач последнего такта: толщина = работа, вспышка = hit."""
        rl_pos, ai_pos = self.layout.rl_pos, self.layout.ai_pos
        for ev in m.events:
            if ev["kind"] != "transfer":
                continue
            frm, to = (rl_pos, ai_pos) if ev["frm"] == "rl" else (ai_pos, rl_pos)
            col = TYPE_COLORS.get(ev["type"], COL_TEXT)
            wdt = int(max(2, min(14, float(ev["work"]) // 3 + 2)))
            dx = to[0] - frm[0]
            ux = dx / max(1.0, abs(dx))
            sx = frm[0] + ux * (agent_radius(m.rl.force if ev["frm"] == "rl"
                                             else m.ai.force) + 12)
            tx = to[0] - ux * (agent_radius(m.ai.force if ev["frm"] == "rl"
                                            else m.rl.force) + 12)
            # PyGame CE требует целочисленные координаты (float -> TypeError)
            sx, sy, tx, ty = int(round(sx)), int(frm[1]), int(round(tx)), int(to[1])
            pygame.draw.line(s, col, (sx, sy), (tx, ty), wdt)
            # наконечник
            ah = 12 + wdt
            pygame.draw.polygon(s, col, [(tx, ty),
                                         (int(round(tx - ux * ah)), ty - 8),
                                         (int(round(tx - ux * ah)), ty + 8)])
            if ev["hit"]:
                flash = pygame.Surface((60, 60), pygame.SRCALPHA)
                pygame.draw.circle(flash, (*COL_OPEN, 150), (30, 30), 14)
                s.blit(flash, (to[0] - 30, to[1] - 30))
                g = self.font_s.render(f"+{ev['gained']}", True, COL_OPEN)
                s.blit(g, ((sx + tx) // 2 - g.get_width() // 2, frm[1] - 26))

    def draw_env_info(self, s, m):
        """Подпись среды сверху арены + "погода" (тип защиты среды)."""
        env = m.env
        if env is None:
            return
        col = TYPE_COLORS[env.defense]
        txt = self.font.render(f"ENVIRONMENT  F={env.force:.0f}  "
                               f"weather[{env.defense}]"
                               f"  {'CONJUNCTURE WINDOW OPEN' if env.in_open else ''}",
                               True, col)
        s.blit(txt, (self.layout.env_label_pos[0] - txt.get_width() // 2,
                     self.layout.env_label_pos[1]))

    def draw_history(self, s, m):
        """Секция C3: график force history (лог-шкала) в своей рамке.

        Подписи конечных значений и легенда размещаются ВНУТРИ рамки графика
        в правом верхнем углу столбцом - они не выходят за границы секции.
        """
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
        # Легенда + конечные значения - столбцом внутри рамки справа сверху;
        # каждая строка проверяется на влезание (по высоте и ширине).
        ly = r.y + 2
        lh = self.font_s.size("Ag")[1]
        for hist, col, tag in ((rl_h, COL_RL, "RL"), (ai_h, COL_AI, "AI")):
            t = self.font_s.render(f"{tag} {hist[-1]:.0f}", True, col)
            if ly + lh > r.bottom - 2 or t.get_width() > r.width - 8:
                break
            s.blit(t, (r.right - t.get_width() - 4, ly))
            ly += lh + 1

    def draw_caption(self, s, m):
        """Секция C2: подпись состояния партии (PAUSE/RUN, темп, pick)."""
        L_ = self.layout
        r = L_.caption_rect
        st = ("PAUSE" if self.paused else f"RUN {self.ticks_per_sec:.1f}/s")
        if m.finished:
            st = "FINISHED"
        t = self.font_s.render(st, True,
                               COL_DIM if self.paused else COL_OPEN)
        if t.get_width() <= r.width - 4:
            s.blit(t, (r.x + 2, r.y + 1))
        pick = f"PICK {ACTIONS[self.action_idx][0]}"
        t2 = self.font_s.render(pick, True, COL_TEXT)
        if (t2.get_width() <= r.right - t.get_width() - 8
                and t2.get_width() <= r.width - 4):
            s.blit(t2, (max(r.x + 2, r.right - t2.get_width() - 2), r.y + 1))

    def draw_action_bar(self, s):
        """Секция B2: плитки действий ACTIONS (сетка 2x4) + PICK-плашка.

        Плитки кликабельны ВСЕГДА; клавиши 1..N дублируют. Подпись режима
        усекается по ширине секции; текст каждой плитки центрируется в своей
        ячейке и обрезается, если не влезает - перекрытия невозможны.
        """
        L_ = self.layout
        # подложка секции
        pygame.draw.rect(s, COL_PANEL, L_.actions_rect)
        pygame.draw.rect(s, (52, 56, 66), L_.actions_rect, 1)
        for i, rect in enumerate(self._action_tiles()):
            act, frac = ACTIONS[i]
            sel = (i == self.action_idx)
            col = TYPE_COLORS.get(act, COL_DIM)
            pygame.draw.rect(s, (40, 44, 54) if not sel else (70, 76, 92), rect)
            pygame.draw.rect(s, col if act != "REST" else COL_DIM,
                             rect, 3 if sel else 2)
            name = f"{i+1}:{act} {int(frac*100)}%"
            t = self.font_s.render(name, True, COL_TEXT)
            while t.get_width() > rect.width - 6 and len(name) > 4:
                name = name[:len(name) - 3] + ".."
                t = self.font_s.render(name, True, COL_TEXT)
            s.blit(t, (rect.x + rect.w // 2 - t.get_width() // 2,
                       rect.y + rect.h // 2 - t.get_height() // 2))
        # PICK-плашка в последней клетке сетки - текущий выбор игрока.
        pr = L_.pick_rect
        pygame.draw.rect(s, (30, 33, 40), pr, border_radius=4)
        pygame.draw.rect(s, COL_OPEN, pr, 1, border_radius=4)
        pk = f"PICK: {ACTIONS[self.action_idx][0]}"
        t = self.font_s.render(pk, True, COL_OPEN)
        while t.get_width() > pr.width - 6 and len(pk) > 5:
            pk = pk[:len(pk) - 3] + ".."
            t = self.font_s.render(pk, True, COL_OPEN)
        s.blit(t, (pr.x + pr.w // 2 - t.get_width() // 2,
                   pr.y + pr.h // 2 - t.get_height() // 2))
        tag = self.L("ВЫБРАНО ИГРОКОМ (клик или 1-7)", "PLAYER PICK (click or 1-7)") \
            if self.manual_mode else \
            self.L("режим наблюдателя: RL решает сам (M или клик = взять управление)",
                   "observe: RL decides (M or click = take control)")
        # Усечение подписи строго по внутренней ширине секции B2.
        max_w = L_.actions_rect.width - 16
        t = self.font_s.render(tag, True, COL_OPEN if self.manual_mode else COL_DIM)
        while t.get_width() > max_w and len(tag) > 6:
            cut = max(6, len(tag) - max(4, int(len(tag) * (t.get_width() - max_w)
                                               / max(1, t.get_width()))))
            tag = tag[:cut] + ".."
            t = self.font_s.render(tag, True, COL_OPEN if self.manual_mode else COL_DIM)
        s.blit(t, (L_.actions_rect.x + 8, L_.tiles_label_y))

    def draw_buttons(self, s):
        """Секция C1: кнопки HUD (сетка 4x2) - тот же функционал, что у клавиш.

        Активная подсветка + короткая вспышка при нажатии - реакция видна
        сразу. Каждая кнопка занимает свою ячейку сетки Layout; индикатор
        темпа - отдельная ячейка (3,1). Перекрытие кнопок невозможно по
        построению (ячейки не пересекаются), текст вписывается усечением."""
        L_ = self.layout
        pygame.draw.rect(s, COL_PANEL, L_.ctrl_rect)
        flashing = self.time < self._flash_until
        for name, label, rect in self.buttons:
            active = ((name == "START" and not self.paused)
                      or (name == "MODE" and self.manual_mode))
            hot = flashing and self._btn_flash == name
            bg = (74, 82, 98) if active else (38, 41, 50)
            if hot:
                bg = (120, 130, 150)
            pygame.draw.rect(s, bg, rect, border_radius=4)
            border = COL_OPEN if active else (90, 95, 108)
            pygame.draw.rect(s, border, rect, 2, border_radius=4)
            t = self.font_s.render(label, True, COL_TEXT)
            if t.get_width() > rect.width - 6:      # текст не влезает - режем
                t = self.font_s.render(label[:max(3, rect.width // 8)],
                                       True, COL_TEXT)
            if t.get_height() > rect.height - 4:    # и по высоте тоже
                continue
            s.blit(t, (rect.x + (rect.width - t.get_width()) // 2,
                       rect.y + (rect.height - t.get_height()) // 2))
        # Индикатор темпа - собственная ячейка сетки (3,1), никогда не
        # пересекается с кнопками.
        sr = L_.speed_rect
        pygame.draw.rect(s, (30, 33, 40), sr, border_radius=4)
        sp_txt = "%.1f т/с" % self.ticks_per_sec if self.cyrillic_ok \
            else "%.1f t/s" % self.ticks_per_sec
        sp = self.font_s.render(sp_txt, True, COL_DIM)
        if (sp.get_width() <= sr.width - 4
                and sp.get_height() <= sr.height - 4):
            s.blit(sp, (sr.x + (sr.width - sp.get_width()) // 2,
                        sr.y + (sr.height - sp.get_height()) // 2))

    def draw_status(self, s, m):
        """Итог партии - в верхней части арены (секция B1); серии - в СТАТУСе."""
        if m.finished:
            msg = (f"CAPTURE: {m.winner} wins at tick {m.step}"
                   if m.winner else f"NO DECISION after {m.step} ticks")
            t = self.font_b.render(msg, True, COL_OPEN)
            cx = self.layout.arena_cx
            cy = self.layout.arena_cy + self.layout.finish_dy
            s.blit(t, (cx - t.get_width() // 2, cy))
            t2 = self.font_s.render(
                self.L("R или кнопка RESET - новая партия",
                       "R or RESET button - new match"), True, COL_DIM)
            s.blit(t2, (cx - t2.get_width() // 2, cy + 26))

    def draw_help(self, s):
        """Справка занимает зону P3 вместо плиток (F1/H переключает)."""
        if self.cyrillic_ok:
            lines = [
                "SPACE / кнопка START - пауза/пуск   R / RESET - новая партия",
                "TAB / кнопка STEP - один такт (работает и в паузе!)",
                "+/- или стрелки / SPEED - темп   M / MODE - режим игрок/наблюдатель",
                "1..7 или клик по плитке - действие RL (сразу видно выбор)",
                "F1/H - скрыть справку   ESC/Q - выход",
                "",
                "Круг = автомат (радиус ~ log F, рамка = тип защиты).",
                "Кольцо = давление на вход w_adopt/ON(F); жёлтая пульсация -",
                "открытое окно Шмитта. Золотая рамка экрана - окно конъюнктуры среды.",
                "Три колонки HUD: метрики | арена+действия | кнопки+график.",
            ]
        else:
            lines = [
                "SPACE / START button - pause/run    R / RESET - new match",
                "TAB / STEP button - single tick (works while paused!)",
                "+/- or arrows / SPEED - rate   M / MODE - observe/manual",
                "1..7 or click a tile - pick RL action (selection is highlighted)",
                "F1/H - toggle help   ESC/Q - quit",
                "",
                "Circle = automaton (radius ~ log F, outline = defense type).",
                "Ring = input pressure w_adopt/ON(F); yellow pulse =",
                "open Schmitt window. Golden frame = environment window.",
                "Three columns: metrics | arena+actions | buttons+graph.",
            ]
        L_ = self.layout
        # Подложка + рамка секции B2 - те же границы, что у полоски действий.
        pygame.draw.rect(s, COL_PANEL, L_.actions_rect)
        pygame.draw.rect(s, (52, 56, 66), L_.actions_rect, 1)
        hdr = self.font_s.render(
            self.L("СПРАВКА (F1 - скрыть)", "HELP (F1 to hide)"),
            True, COL_OPEN)
        s.blit(hdr, (L_.help_x + 4, L_.tiles_label_y))
        y = L_.help_y + L_.line_h + 4          # заголовок + отступ до текста
        max_w = L_.actions_rect.width - 12     # строки не должны вылезать за зону
        for ln in lines:
            hgt = self.font_s.size(ln)[1] if ln else L_.line_h // 2
            if y + hgt > L_.actions_rect.bottom - 2:
                break                          # не выходим за нижнюю границу зоны
            if ln:
                t = self.font_s.render(ln, True, COL_DIM)
                while t.get_width() > max_w and len(ln) > 8:
                    cut = max(8, len(ln) - max(2, int(len(ln) *
                           (t.get_width() - max_w) / max(1, t.get_width()))))
                    ln = ln[:cut] + ".."
                    t = self.font_s.render(ln, True, COL_DIM)
                s.blit(t, (L_.help_x + 4, y))
            y += L_.help_line_dy
        # Если pygame.font сломан - показываем это прямо в HUD (раз и навсегда
        # видно пользователю, почему шрифт растровый и как это починить).
        if self.fonts.is_bitmap and y + 14 < L_.actions_rect.bottom:
            warn = "FONT FALLBACK (pygame.font broken): pip install pygame-ce"
            wt = self.font_s.render(warn, True, (255, 120, 80))
            if wt.get_width() <= max_w:
                s.blit(wt, (L_.help_x + 4, y))

    # ---------------- цикл ----------------
    def run(self):
        LOG.info("главный цикл запущен (fps=%s, темп=%s тик/с, paused=%s)"
                 % (FPS, self.ticks_per_sec, self.paused))
        running = True
        frame = 0
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            frame += 1
            if frame == 1 or frame % 300 == 0:
                LOG.debug("кадр %s: dt=%.1fms fps=%.1f tick=%s paused=%s "
                          "manual=%s finished=%s"
                          % (frame, dt * 1000, self.clock.get_fps(),
                             self.match.step, self.paused,
                             self.manual_mode, self.match.finished))
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
                LOG.warn("симуляция остановлена (paused=True) из-за ошибки выше; "
                         "партия: tick=%s step_finished=%s"
                         % (self.match.step, self.match.finished))
            try:
                self.draw()
            except Exception as e:
                LOG.exc("draw (отрисовка кадра)", e, key="draw")
                LOG.warn("кадр не отрисован - цикл продолжается")
        LOG.info("главный цикл завершён (кадров=%s, финальный tick=%s)"
                 % (frame, self.match.step))
        pygame.quit()
        LOG.info("pygame.quit() выполнен - чистое завершение")


def main():
    LOG.info("main(): старт. Аргументы: %s" % sys.argv)
    LOG.info("Окружение: python=%s executable=%s cwd=%s"
             % (sys.version.split()[0], sys.executable, os.getcwd()))
    try:
        import simulation
        LOG.info("simulation.py: файл=%s mtime=%s" % (
            getattr(simulation, "__file__", "?"),
            _time_mod.strftime("%Y-%m-%d %H:%M:%S", _time_mod.localtime(
                os.path.getmtime(getattr(simulation, "__file__", "."))))))
    except Exception as e:
        LOG.debug("диагностика simulation недоступна: %s" % e)
    # Сначала проверяем шрифты ДО создания окна (pygame.init не обязателен для
    # Font(None, ...), но безопаснее после); при нерабочем pygame.font -
    # подсказываем пользователю, как починить окружение "раз и навсегда".
    pygame.init()
    fonts = FontSet()
    probe = _probe_font()
    fonts.setup(probe)
    if fonts.is_bitmap:
        LOG.warn("FontSet в режиме bitmap-fallback: %s" % fonts.note)
        sys.stderr.write(
            "[game_engine] ВНИМАНИЕ: pygame.font недоступен "
            f"({fonts.note}).\n"
            "  Это известная ошибка pygame 2.6.x на Python 3.14 (битый freetype).\n"
            "  Движок продолжит работу со встроенным растровым шрифтом.\n"
            "  Чтобы вернуть нормальные шрифты (и кириллицу в HUD):\n"
            "      pip uninstall -y pygame && pip install pygame-ce\n")
    else:
        LOG.info("FontSet готов: native pygame.font, кириллица=%s"
                 % fonts.cyrillic_ok)
    app = GameApp(fonts=fonts)
    app.run()
    LOG.info("main(): штатное завершение, rc=0")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as e:                     # noqa: BLE001
        LOG.error("ФАТАЛЬНАЯ ОШИБКА (неперехваченное исключение): "
                  "%s: %s" % (type(e).__name__, e))
        sys.stderr.write("".join(traceback.format_exception(
            type(e), e, e.__traceback__)))
        sys.stderr.flush()
        sys.exit(1)
