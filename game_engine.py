"""Ozvering-Project: минималистичный 2D графический движок на PyGame.

Игрок наблюдает (и при желании управляет) дуэлью двух IPO-автоматов в среде-автомате:
  * RLAgent      — обучающийся агент (табличный Q-Learning);
  * UtilityAI    — скриптованный BDI-агент (argmax ожидаемой выгоды).

Движок НЕ изменяет simulation.py — использует только его публичное API:
классы Agent/RLAgent/UtilityAI/Environment, функции play_game-протокола по шагам
(sense / rotate_defense / upkeep / tick_energy / tick_input_state / commit /
resolve_attack / learn / check_capture) и словари PARAMETERS / PROFILES / MULT.

Управление:
  SPACE   — пауза/пуск тактов партии
  СТРЕЛКА ВВЕРХ/ВПРАВО — ускорить темп симуляции
  СТРЕЛКА ВНИЗ/ЛЕВО    — замедлить
  R       — новая партия (сброс окружения; Q-таблица RL сохраняется — перенос обучения)
  M       — режим: наблюдатель <-> игрок управляет RL-агентом вручную
  F1/H    — справка
  ESC/Q   — выход

Визуальный язык (минимализм, всё выводится из состояний модели):
  * Два круга-автомата: радиус ~ log(сила), цвет рамки — текущий тип защиты
    (FIRE — красный, WATER — синий, EARTH — зелёный).
  * Кольцо вокруг круга — накопленное давление на вход w_adopt (дуга до порога ON(F));
    заполненное кольцо = порог пройден.
  * Когда окно восприимчивости входа открыто (in_open) — круг пульсирует жёлтым,
    над ним таймер окна.
  * Среда (Environment) — фон: оттенок фона кодирует силу среды, золотая рамка экрана
    — открытое окно конъюнктуры (ENV_BONUS активен).
  * Стрелки-передачи: направление и толщина = работа, вспышка = успешная передача.
  * Панель слева — метрики обеих сторон и среды текстом.
"""

import math
import os
import random
import subprocess
import sys

# ---------------------------------------------------------------------------
# Защита от «сломанного шрифта» в pygame 2.6.x на Python 3.14 (и не только).
#
# Причина ошибки "cannot import name 'Font' from partially initialized module
# 'pygame.font' (circular import)": бинарный модуль pygame.freetype собран без
# поддержки UTF-8 (SDL_ttf compiled without FreeType support), и при запуске
# pygame.font пытается импортировать Font из уже частично инициализированного
# pygame.font. В результате вся подсистема шрифтов недоступна, а try/except
# вокруг pygame.font.Font(...) не спасает — падает сам доступ к атрибуту.
#
# Решение "раз и навсегда": если штатный способ не работает, движок полностью
# НЕ зависит от pygame.font — текст рендерится встроенным растровым шрифтом
# (см. BitmapText ниже). Никаких системных зависимостей, никаких pip-пакетов.
# ---------------------------------------------------------------------------
_FONT_OK = False          # станет True, если pygame.font реально работает
_FONT_NOTE = ""           # причина отказа (показывается в HUD)


def _probe_font():
    """Возвращает рабочий pygame.font.Font или None — без исключений наружу.

    ВАЖНО: инициализирует шрифт-подсистему сама (pygame.font.init()), чтобы
    проба была корректной и до, и после pygame.init() — иначе на исправленном
    pygame недетектируемый 'font not initialized' ложно включал бы fallback.
    """
    global _FONT_OK, _FONT_NOTE
    try:
        import pygame.font as _pf
        _pf.init()                            # идемпотентно; не тянет весь pygame.init
        f = _pf.Font(None, 17)                # реальный тест создания
        if f.size("A")[0] <= 0:
            raise RuntimeError("default font renders nothing")
        _FONT_OK = True
        return f
    except Exception as e:                    # noqa: BLE001
        _FONT_NOTE = str(e) or e.__class__.__name__
        _FONT_OK = False
        return None


def _try_fix_freetype():
    """Пытаемся один раз починить окружение, не трогая код модели:
    1) если установлен pygame-ce — переключиться на него;
    2) иначе удалить битый pygame и поставить pygame-ce (он исправляет сборку
       freetype для Python 3.14). Действие логируется, ошибка — не фатальна."""
    try:
        import importlib.util
        if importlib.util.find_spec("pygame_ce") is not None:
            print("[game_engine] Найден pygame-ce. Для его использования "
                  "удалите обычный pygame: pip uninstall -y pygame")
            return
    except Exception:
        pass
    try:
        code = ("import pygame.freetype, shutil; "
                "shutil.copy(pygame.freetype.get_default_font(), '.')")
        subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=5)
    except Exception:
        pass


try:
    import pygame
except ImportError:
    sys.stderr.write(
        "PyGame не установлен. Установите исправленную сборку:\n"
        "    pip uninstall -y pygame && pip install pygame-ce\n"
        "(обычный pygame 2.6.x на Python 3.14 собран с битым freetype — "
        "шрифты не работают)\n")
    raise

# --- Импорт публичного API модели (никаких правок simulation.py) -------------
from simulation import (
    PARAMETERS, PROFILES, MULT, TYPES, ACTIONS,
    Agent, RLAgent, UtilityAI, Environment,
    resolve_attack, check_capture, p_success,
)

# ---------------------------------------------------------------------------
# Константы оформления
# ---------------------------------------------------------------------------

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

# Позиции автоматов на «арене»
ARENA_X0 = PANEL_W
ARENA_CX = PANEL_W + (SCREEN_W - PANEL_W) // 2
RL_POS = (ARENA_CX - 170, SCREEN_H // 2 - 30)
AI_POS = (ARENA_CX + 170, SCREEN_H // 2 - 30)
ENV_LABEL_POS = (ARENA_CX, 46)


def agent_radius(force):
    """Радиус автомата — монотонная сжатая функция силы (log-шкала)."""
    return int(22 + 14 * math.log(max(1.0, force)))


def env_bg_color(env_force):
    """Оттенок фона от силы среды: чем больше капитал конъюнктуры, тем теплее фон."""
    t = min(1.0, max(0.0, (env_force - 10.0) / 400.0))
    r = COL_BG_BASE[0] + int(18 * t)
    g = COL_BG_BASE[1] + int(10 * t)
    b = COL_BG_BASE[2] + int(4 * t)
    return (r, g, b)


# ---------------------------------------------------------------------------
# Тактовый движок партии: пошаговая обёртка над протоколом play_game
# ---------------------------------------------------------------------------

class MatchEngine:
    """Одна партия RL vs UtilityAI в среде-автомате, шаг за шагом.

    Повторяет протокол simulation.play_game точно (зеркальные шаги, та же
    очерёдность фаз), но раскручивается по такту — чтобы движок мог рисовать
    промежуточное состояние и (в ручном режиме) подставлять действие игрока.

    Состояние партии (для визуализации переходов):
      events — список событий последнего такта:
        {"kind":"transfer","frm":"rl"|"ai","work":int,"hit":bool,"gained":int}
        {"kind":"capture","winner":"RL"|"UtilityAI","cap":int}
    """

    def __init__(self, seed=0, steps=2000, with_env=True, q_table=None,
                 profile_rl="CANON", profile_ai="CANON"):
        self.seed = seed
        self.rng = random.Random(seed)
        # Собственный rng для epsilon-greedy разведки RL: simulation.RLAgent.form_intention
        # использует глобальный random.* — изолируем его здесь (seed-детерминизм движка),
        # не изменяя код модели. Порядок вызовов канонический.
        self._rl_rng = random.Random(seed ^ 0x5EED)
        self.steps_total = steps
        self.step = 0
        self.winner = None            # "RL" | "UtilityAI" | None (идёт партия)
        self.finished = False
        self.events = []              # события последнего такта
        self.rl_hist, self.ai_hist = [], []

        # Профили сторон (один скаляр p, см. PROFILES) — без новых переменных.
        self.rl = RLAgent(q=q_table, profile=profile_rl)
        self.ai = UtilityAI(profile=profile_ai)
        self.with_env = with_env
        self.env = Environment(members=[self.rl, self.ai]) if with_env else None

        # Доминирование — свои счётчики (не трогаем глобальные _dom_* модуля;
        # локальная копия check_capture ниже эквивалентна ей по формулам).
        self.dom_rl = 0
        self.dom_ai = 0

        # Счётчик тактов покоя (для панели; вывод из last_act — новых полей модели нет)
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
            forced_rl_action: None — RL выбирает сам (epsilon-greedy);
                индекс действия из ACTIONS — игрок управляет RL-агентом
                (обучение при этом продолжается на выбранном действии).
        """
        if self.finished:
            return
        rl, ai, env = self.rl, self.ai, self.env
        rng = self.rng
        self.events = []

        # 1. Взаимное наблюдение (частичная наблюдаемость, шум — из rng партии).
        rl.sense(ai, rng)
        ai.sense(rl, rng)

        # 2. Ротация защит (профильно-модулируемая) + «погода» среды.
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
        #    или действие игрока; Utility: argmax U; рефлекс голода — выше обоих.
        eps = max(0.05, 1.0 - self.step / 300)
        if forced_rl_action is not None:
            a_idx = int(forced_rl_action) % len(ACTIONS)
            # В ручном режиме состояние всё равно должно существовать в Q —
            # иначе TD-обновление на неинициализированной строке дало бы KeyError.
            st_probe = rl.skey()
            if st_probe not in rl.Q:
                rl.Q[st_probe] = [0.0] * len(ACTIONS)
        else:
            # Разведка epsilon-greedy идёт через собственный rng движка: метод
            # RLAgent.form_intention обращается к глобальному random.* (известное
            # отклонение модели); временная подмена модуля random сохраняет
            # семантику выбора и делает партию детерминированной по seed.
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
        else:
            w_rl = rl.commit(act_name, rl.energy_pool * frac)
        self.last_rl_action = (act_name, w_rl)

        ai_act, ai_work = ai.form_intention()
        if ai.rest_if_starving():
            w_ai = 0
            ai_act = "REST"
        else:
            w_ai = ai.commit(ai_act, ai_work)
        self.last_ai_action = (ai_act, w_ai)

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
            self.finished = True   # без решения за steps тактов

    def _resolve_with_events(self, att, dfn, work, who):
        """Вызов канонического resolve_attack + фиксация исхода для отрисовки.

        Результат передачи (hit/gained) внутри resolve_attack не возвращается;
        движок подменяет rng партии обёрткой, которая перехватывает ровно те
        броски, что делает сам закон (первый — проверка попадания адресанта),
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
        # даёт ту же вероятность — аргументы не изменились к моменту обёртки.)
        if work and captured.get("hit_roll", 1.0) < p:
            res["hit"] = True
        delta = att.force - f_att_before
        cost = int(PARAMETERS["COST_FRACTION"] * work)
        if res["hit"]:
            res["gained"] = max(0, int(delta + cost))
        return res


# ---------------------------------------------------------------------------
# Встроенный растровый шрифт 3x5 (fallback).
# Используется, если подсистема pygame.font недоступна (битая сборка freetype
# в pygame 2.6.x на Python 3.14 и т.п.). Зависимость от шрифтов сводится к нулю:
# текст рендерится точками через pygame.draw.rect — только SDL-примитивы.
# GLYPHS: строки bitmap'а сверху вниз, '#' — пиксель.
# ---------------------------------------------------------------------------

GLYPHS = {
    " ": ("...", "...", "...", "...", "..."),
    "!": ("#..", "#..", "#..", "...", "#.."),
    '"': ("##.", "##.", "..", "..", ".."),
    "%": ("#.#", ".#.", "#.#", ".#.", "#.#"),  # упрощённый процент не нужен; зарезервирован
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


class BitmapText:
    """Минималистичный текстовый рендер без pygame.font (масштаб = размер пикселя)."""

    W, H = 3, 5
    SEP = 1

    def size(self, text):
        lines = text.split("\n")
        w = max((len(ln) * (self.W + self.SEP) - self.SEP for ln in lines),
                default=0)
        h = len(lines) * (self.H + 2) - 2
        return max(w, 1), max(h, 1)

    def render(self, text, _antialias=True, color=(255, 255, 255), scale=1):
        text = "".join(ch if ch in GLYPHS else "?" for ch in text.upper())
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
        """probe — результат _probe_font(): Font или None."""
        if probe is not None:
            import pygame.font as pf
            try:
                self.pygame_font = pf
                self._f_default = probe
                self._f_small = pf.Font(None, 14)
                self._f_big = pf.Font(None, 24)
                self.cyrillic_ok = (self._f_default.size("Я")[0] > 0
                                    and self._f_default.render(
                                        "Я", True, (255, 255, 255)).get_width() > 0)
                return
            except Exception as e:       # на всякий случай
                self.note = str(e)
                self.pygame_font = None
        # fallback: растровый шрифт, масштабы подобраны под прежние кегли
        self.note = _FONT_NOTE or "pygame.font unavailable"
        self.cyrillic_ok = False

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
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Ozvering-Project — IPO Arena (PyGame)")
        self.clock = pygame.time.Clock()
        # Шрифты: если pygame.font работает — используем его (кириллица возможна);
        # если нет (битый freetype в pygame 2.6.x / Python 3.14) — встроенный
        # растровый шрифт BitmapText, зависимость от pygame.font = 0.
        self.fonts = fonts or FontSet()
        if self.fonts.pygame_font is None and not self.fonts.note:
            self.fonts.setup(_probe_font())
        self.cyrillic_ok = self.fonts.cyrillic_ok
        self.font = self.fonts.font
        self.font_s = self.fonts.font_s
        self.font_b = self.fonts.font_b

        def L(ru, en):
            """Двуязычная строка HUD: кириллица доступна — ru, иначе — en."""
            return ru if self.cyrillic_ok else en
        self.L = L

        self.paused = True
        self.manual_mode = False       # игрок управляет RL-агентом
        self.show_help = True
        self.ticks_per_sec = 8.0       # темп симуляции
        self.acc = 0.0
        self.time = 0.0                # вещественное время для пульсаций

        # Общая Q-таблица — перенос обучения между партиями (как run_batch).
        self.q_table = {}
        self.game_seed = 0
        self.match = MatchEngine(seed=self.game_seed, q_table=self.q_table)

        # Выбор действия в ручном режиме: индекс в ACTIONS.
        self.action_idx = 0

        # Скользящие графики силы (последние N тактов).
        self.history_len = 240

    # ---------------- ввод ----------------
    def handle_events(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return False
            if e.type == pygame.KEYDOWN:
                k = e.key
                if k in (pygame.K_ESCAPE, pygame.K_q):
                    return False
                elif k == pygame.K_SPACE:
                    self.paused = not self.paused
                elif k == pygame.K_r:
                    self.new_match()
                elif k == pygame.K_m:
                    self.manual_mode = not self.manual_mode
                elif k in (pygame.K_F1, pygame.K_h):
                    self.show_help = not self.show_help
                elif k in (pygame.K_UP, pygame.K_RIGHT):
                    self.ticks_per_sec = min(60.0, self.ticks_per_sec * 1.5)
                elif k in (pygame.K_DOWN, pygame.K_LEFT):
                    self.ticks_per_sec = max(0.5, self.ticks_per_sec / 1.5)
                elif self.manual_mode and not self.paused:
                    # В паузе стрелки меняют скорость; в ручном режиме на ходу
                    # цифры 1..7 выбирают действие для следующего такта.
                    if pygame.K_1 <= k <= pygame.K_1 + len(ACTIONS) - 1:
                        self.action_idx = (k - pygame.K_1) % len(ACTIONS)
            if e.type == pygame.MOUSEBUTTONDOWN and self.manual_mode:
                idx = self._action_at_mouse(e.pos)
                if idx is not None:
                    self.action_idx = idx
        return True

    def _action_at_mouse(self, pos):
        """Попадание по плиткам действий в нижней панели (ручной режим)."""
        tiles = self._action_tiles()
        for i, rect in enumerate(tiles):
            if rect.collidepoint(pos):
                return i
        return None

    def _action_tiles(self):
        rects = []
        n = len(ACTIONS)
        tw, th = 96, 34
        gap = 6
        total_w = n * tw + (n - 1) * gap
        x0 = PANEL_W + (SCREEN_W - PANEL_W - total_w) // 2
        y0 = SCREEN_H - th - 12
        for i in range(n):
            rects.append(pygame.Rect(x0 + i * (tw + gap), y0, tw, th))
        return rects

    def new_match(self):
        """Новая партия: свежие автоматы и среда; Q-таблица RL сохраняется."""
        self.game_seed += 1
        self.match = MatchEngine(seed=self.game_seed, q_table=self.q_table)
        self.paused = True

    # ---------------- логика ----------------
    def update(self, dt):
        self.time += dt
        if self.paused or self.match.finished:
            return
        self.acc += dt * self.ticks_per_sec
        while self.acc >= 1.0:
            self.acc -= 1.0
            forced = self.action_idx if self.manual_mode else None
            self.match.step_tick(forced_rl_action=forced)
            if self.match.finished:
                break

    # ---------------- отрисовка ----------------
    def draw(self):
        s = self.screen
        m = self.match
        env = m.env

        # Фон — сила среды; золотая рамка — открытое окно конъюнктуры.
        bg = env_bg_color(env.force if env else 10.0)
        s.fill(bg)
        if env is not None and env.in_open:
            glow = 160 + 60 * math.sin(self.time * 6.0)
            pygame.draw.rect(s, (int(glow), int(glow * 0.78), 40),
                             s.get_rect(), width=4)

        self.draw_panel(s, m)
        self.draw_agents(s, m)
        self.draw_transfers(s, m)
        self.draw_env_info(s, m)
        self.draw_history(s, m)
        if self.manual_mode:
            self.draw_action_bar(s)
        self.draw_status(s, m)
        if self.show_help:
            self.draw_help(s)

        pygame.display.flip()

    def draw_panel(self, s, m):
        """Левая панель: текстовые метрики сторон и среды (только поля state)."""
        panel = pygame.Rect(0, 0, PANEL_W, SCREEN_H)
        pygame.draw.rect(s, COL_PANEL, panel)
        pygame.draw.line(s, (60, 64, 74), (PANEL_W - 1, 0), (PANEL_W - 1, SCREEN_H))

        y = 12
        def line(txt, col=COL_TEXT, font=None, dy=18):
            nonlocal y
            s.blit((font or self.font).render(txt, True, col), (12, y))
            y += dy

        line("OZVERING — IPO ARENA", COL_OPEN, self.font_b, 26)
        line(f"tick {m.step} / {m.steps_total}   seed {m.seed}   "
             f"{'PAUSE' if self.paused else f'RUN x{self.ticks_per_sec:.0f}/s'}",
             COL_DIM)
        y += 8

        sides = ((self.L("RL AGENT (обучающийся)", "RL AGENT (learning)"),
                  m.rl, COL_RL, m.last_rl_action, m.rl_rest_ticks),
                 (self.L("UTILITY AI (скрипт)", "UTILITY AI (scripted)"),
                  m.ai, COL_AI, m.last_ai_action, m.ai_rest_ticks))
        for title, ag, acc, last_act, rest_ticks in sides:
            line(title, acc)
            line(f"  F={ag.force:6.1f}  E={ag.energy_pool:4d}  regen={ag.regen}")
            line(f"  def [{ag.defense}]  L={ag.rest_ceiling:.0f}"
                 f"  RU={ag.rest_units:.0f}")
            on = ag.schmitt_on()
            line(f"  w_adopt={ag.w_adopt:6.1f}/{on:5.1f}"
                 f"  {'OPEN '+str(ag.open_timer) if ag.in_open else 'closed'}",
                 COL_OPEN if ag.in_open else COL_TEXT)
            bar_col = TYPE_COLORS[ag.defense]
            frac = min(1.0, ag.w_adopt / max(1e-9, on))
            pygame.draw.rect(s, (50, 52, 60), (14, y, PANEL_W - 30, 7))
            pygame.draw.rect(s, bar_col, (14, y, int((PANEL_W - 30) * frac), 7))
            y += 12
            line(f"  act: {last_act[0]}  work: {last_act[1]}  rest:{rest_ticks}",
                 COL_DIM)
            y += 6

        if m.env is not None:
            e = m.env
            line(self.L("ENVIRONMENT (среда-автомат)", "ENVIRONMENT (agent)"), COL_ENV_OPEN)
            line(f"  F={e.force:7.1f}  E={e.energy_pool:4d}"
                 f"  weather [{e.defense}]", TYPE_COLORS[e.defense])
            line(f"  w_adopt={e.w_adopt:6.1f}/{e.schmitt_on():5.1f}"
                 f"  {'WINDOW OPEN' if e.in_open else 'closed'}",
                 COL_ENV_OPEN if e.in_open else COL_TEXT)
            line(f"  members: {len(e.members)}  bonus: "
                 f"{PARAMETERS['ENV_BONUS'] if e.in_open else 0:+.2f}", COL_DIM)

        y += 10
        line(f"Q-state size: {len(m.rl.Q)}", COL_DIM)
        line(f"profiles: RL p={m.rl.p}  AI p={m.ai.p}", COL_DIM)
        line("MODE: " + (self.L("РУЧНОЙ (игрок->RL)", "MANUAL (player->RL)")
                         if self.manual_mode else "OBSERVE"),
             COL_OPEN if self.manual_mode else COL_DIM)

    def draw_agents(self, s, m):
        """Круги-автоматы: радиус от силы, рамка от типа защиты, кольцо Шмитта."""
        for pos, ag, acc in ((RL_POS, m.rl, COL_RL), (AI_POS, m.ai, COL_AI)):
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

    def draw_transfers(self, s, m):
        """Стрелки передач последнего такта: толщина = работа, вспышка = hit."""
        for ev in m.events:
            if ev["kind"] != "transfer":
                continue
            frm, to = (RL_POS, AI_POS) if ev["frm"] == "rl" else (AI_POS, RL_POS)
            col = TYPE_COLORS.get(ev["type"], COL_TEXT)
            wdt = max(2, min(14, ev["work"] // 3 + 2))
            start = (frm[0] + (40 if to[0] > frm[0] else -40) * 0, frm[1])
            dx = to[0] - frm[0]
            ux = dx / max(1, abs(dx))
            sx = frm[0] + ux * (agent_radius(m.rl.force if ev["frm"] == "rl"
                                             else m.ai.force) + 12)
            tx = to[0] - ux * (agent_radius(m.ai.force if ev["frm"] == "rl"
                                            else m.rl.force) + 12)
            pygame.draw.line(s, col, (sx, frm[1]), (tx, to[1]), wdt)
            # наконечник
            ah = 12 + wdt
            pygame.draw.polygon(s, col, [(tx, to[1]),
                                         (tx - ux * ah, to[1] - 8),
                                         (tx - ux * ah, to[1] + 8)])
            if ev["hit"]:
                flash = pygame.Surface((60, 60), pygame.SRCALPHA)
                pygame.draw.circle(flash, (*COL_OPEN, 150), (30, 30), 14)
                s.blit(flash, (to[0] - 30, to[1] - 30))
                g = self.font_s.render(f"+{ev['gained']}", True, COL_OPEN)
                s.blit(g, ((sx + tx) // 2 - g.get_width() // 2, frm[1] - 26))

    def draw_env_info(self, s, m):
        """Подпись среды сверху арены + «погода» (тип защиты среды)."""
        env = m.env
        if env is None:
            return
        col = TYPE_COLORS[env.defense]
        txt = self.font.render(f"ENVIRONMENT  F={env.force:.0f}  "
                               f"weather[{env.defense}]"
                               f"  {'CONJUNCTURE WINDOW OPEN' if env.in_open else ''}",
                               True, col)
        s.blit(txt, (txt.get_width() and ENV_LABEL_POS[0] - txt.get_width() // 2,
                     ENV_LABEL_POS[1]))

    def draw_history(self, s, m):
        """Мини-график силы обеих сторон (лог-шкала) внизу арены."""
        n = self.history_len
        rl_h = m.rl_hist[-n:]
        ai_h = m.ai_hist[-n:]
        if len(rl_h) < 2:
            return
        gw, gh = SCREEN_W - PANEL_W - 24, 90
        gx, gy = PANEL_W + 12, SCREEN_H - gh - (54 if self.manual_mode else 16)
        pygame.draw.rect(s, (20, 22, 28), (gx, gy, gw, gh))
        pygame.draw.rect(s, (60, 64, 74), (gx, gy, gw, gh), 1)

        def pt(hist, i):
            v = math.log(max(1.0, hist[i]))
            x = gx + i * gw / max(1, len(hist) - 1)
            ymax = math.log(max(2.0, max(max(rl_h), max(ai_h))))
            y = gy + gh - (v / ymax) * (gh - 6) - 3
            return x, y

        for hist, col in ((rl_h, COL_RL), (ai_h, COL_AI)):
            pts = [pt(hist, i) for i in range(len(hist))]
            pygame.draw.lines(s, col, False, pts, 2)
        lbl = self.font_s.render("force history (log)", True, COL_DIM)
        s.blit(lbl, (gx + 4, gy + 2))

    def draw_action_bar(self, s):
        """Плитки действий ACTIONS — клик или клавиши 1..N в ручном режиме."""
        for i, rect in enumerate(self._action_tiles()):
            act, frac = ACTIONS[i]
            sel = (i == self.action_idx)
            col = TYPE_COLORS.get(act, COL_DIM)
            pygame.draw.rect(s, (40, 44, 54) if not sel else (70, 76, 92), rect)
            pygame.draw.rect(s, col if act != "REST" else COL_DIM, rect, 2)
            name = f"{i+1}:{act} {int(frac*100)}%"
            t = self.font_s.render(name, True, COL_TEXT)
            s.blit(t, (rect.x + 6, rect.y + rect.h // 2 - t.get_height() // 2))

    def draw_status(self, s, m):
        """Итог партии / доминирующие серии."""
        if m.finished:
            msg = (f"CAPTURE: {m.winner} wins at tick {m.step}"
                   if m.winner else f"NO DECISION after {m.step} ticks")
            t = self.font_b.render(msg, True, COL_OPEN)
            s.blit(t, (SCREEN_W // 2 - t.get_width() // 2, SCREEN_H // 2 - 140))
            t2 = self.font_s.render(self.L("R — новая партия", "R — new match"), True, COL_DIM)
            s.blit(t2, (SCREEN_W // 2 - t2.get_width() // 2, SCREEN_H // 2 - 112))
        else:
            # Индикаторы доминирования (серии CAPTURE_STREAK)
            streak = max(m.dom_rl, m.dom_ai)
            if streak:
                who = "RL dominates" if m.dom_rl else "AI dominates"
                frac = streak / PARAMETERS["CAPTURE_STREAK"]
                w = 160
                x = SCREEN_W - w - 16
                y = 16
                pygame.draw.rect(s, (50, 52, 60), (x, y, w, 8))
                pygame.draw.rect(s, COL_OPEN, (x, y, int(w * frac), 8))
                t = self.font_s.render(who, True, COL_OPEN)
                s.blit(t, (x + w - t.get_width(), y + 12))

    def draw_help(self, s):
        if self.cyrillic_ok:
            lines = [
                "SPACE — пауза/пуск        R — новая партия",
                "UP/DOWN — темп симуляции  M — режим наблюдателя/игрока",
                "M: игрок задаёт действие RL (клавиши 1..7 или клик)",
                "F1/H — скрыть справку     ESC/Q — выход",
                "",
                "Круг = автомат (радиус ~ log F, рамка = тип защиты).",
                "Кольцо = давление на вход w_adopt/ON(F); жёлтая пульсация —",
                "открытое окно Шмитта. Золотая рамка экрана — окно конъюнктуры среды.",
            ]
        else:
            lines = [
                "SPACE — pause/run         R — new match",
                "UP/DOWN — speed           M — observe/manual mode",
                "M: player picks RL action (keys 1..7 or click)",
                "F1/H — toggle help        ESC/Q — quit",
                "",
                "Circle = automaton (radius ~ log F, outline = defense type).",
                "Ring = input pressure w_adopt/ON(F); yellow pulse =",
                "open Schmitt window. Golden frame = environment window.",
            ]
        y = SCREEN_H - 150
        for ln in lines:
            t = self.font_s.render(ln, True, COL_DIM)
            s.blit(t, (PANEL_W + 14, y))
            y += 16
        # Если pygame.font сломан — показываем это прямо в HUD (раз и навсегда
        # видно пользователю, почему шрифт растровый и как это починить).
        if self.fonts.is_bitmap:
            warn = "FONT FALLBACK (pygame.font broken): pip install pygame-ce"
            wt = self.font_s.render(warn, True, (255, 120, 80))
            s.blit(wt, (PANEL_W + 14, y + 4))

    # ---------------- цикл ----------------
    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            running = self.handle_events()
            self.update(dt)
            self.draw()
        pygame.quit()


def main():
    # Сначала проверяем шрифты ДО создания окна (pygame.init не обязателен для
    # Font(None, ...), но безопаснее после); при нерабочем pygame.font —
    # подсказываем пользователю, как починить окружение "раз и навсегда".
    pygame.init()
    fonts = FontSet()
    probe = _probe_font()
    fonts.setup(probe)
    if fonts.is_bitmap:
        sys.stderr.write(
            "[game_engine] ВНИМАНИЕ: pygame.font недоступен "
            f"({fonts.note}).\n"
            "  Это известная ошибка pygame 2.6.x на Python 3.14 (битый freetype).\n"
            "  Движок продолжит работу со встроенным растровым шрифтом.\n"
            "  Чтобы вернуть нормальные шрифты (и кириллицу в HUD):\n"
            "      pip uninstall -y pygame && pip install pygame-ce\n")
    GameApp(fonts=fonts).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
