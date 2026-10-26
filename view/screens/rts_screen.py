"""Интерактивная 2-D изометрическая карта кампании (RTS-слой).

Экран заменяет прежний командный пункт. Он получает состояние из
``warfare.WarfareSimulation`` через ``CampaignEngine`` и показывает:

* изометрическую сетку 24×24 с плавно интерполированными иконками юнитов
  и разведением перекрывающихся жетонов при плотном контакте;
* выделение рамкой, приказы движения/атаки/обороны/отдыха;
* явную цель для сосредоточенного огня (клик по врагу или ПКМ);
* боевые частицы — трассеры, вспышки выстрелов и дуги ближнего боя;
* реальное время с паузой и множителем скорости (x1/x2/x4/x8; часы идут
  по минутам, войсковой такт — раз в 5 игровых минут);
* масштабирование карты колесом мыши, клавишами +/- и кнопками;
* информационную панель потребностей выбранного подразделения
  (самообеспечение) и отдельную панель личных потребностей командира;
* быстрый доступ к приказам адъютанта, журналу, логистике и рации.

Графика юнитов — намеренные плейсхолдеры: цветные жетоны, полосы силы и
морали. Позже их можно заменить спрайтами без изменения логики экрана.
"""

from __future__ import annotations

import math
import random

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button
from ..ui.text_layout import draw_fitted, wrap_text
from ..support.needs import SUPPLY_LABELS
from ..support.geometry import (
    BREACH_PRESSURE_TICKS, SECTOR_LABELS, SECTOR_SHORT,
)
from view.support.log_journal import get_logger

logger = get_logger("view.rts")

WIDTH, HEIGHT = 1280, 720
TOP_H = 58
LEFT_W = 236
RIGHT_X = 1004
RIGHT_W = WIDTH - RIGHT_X
MAP_RECT = pygame.Rect(LEFT_W, TOP_H, RIGHT_X - LEFT_W, HEIGHT - TOP_H)
GRID = 24
TILE_W = 32.0
TILE_H = 16.0
ISO_ORIGIN = (620, 112)
# Реальное время: одна игровая минута за 0.35 с при x1. Часы идут по минутам,
# а войсковой такт (5 игровых минут) случается примерно раз в 1.75 с.
REAL_SECONDS_PER_GAME_MINUTE = 0.35
MIN_ZOOM = 0.70
MAX_ZOOM = 1.80
ZOOM_STEP = 0.15
# Красные — сторона игрока, синие — противник. Цвета жетонов совпадают с
# названиями сторон, чтобы не возникало путаницы «красные, но нарисованы
# синим».
SIDE_NAMES = {"red": "КРАСНЫЕ", "blue": "СИНИЕ"}
SIDE_COLORS = {"red": (211, 78, 78), "blue": (72, 138, 224)}
DAY_COLORS = {
    "bg": (13, 18, 24),
    "panel": (17, 24, 32),
    "panel2": (21, 30, 40),
    "line": (48, 66, 82),
    "text": (222, 230, 236),
    "muted": (144, 158, 170),
    "accent": (86, 154, 226),
    "player": (211, 78, 78),
    "enemy": (72, 138, 224),
    "ally_dark": (127, 46, 52),
    "enemy_dark": (36, 77, 130),
    "gold": (224, 185, 95),
    "good": (88, 190, 118),
    "warn": (224, 164, 74),
    "bad": (224, 88, 88),
}

NEED_SHORT = {
    "hunger": "Голод", "thirst": "Жажда", "fatigue": "Устал.",
    "health": "Здор.", "fear": "Страх", "anxiety": "Трев.",
    "loneliness": "Один.", "reproduction": "Репр.",
    "knowledge": "Знания", "creativity": "Творч.", "boredom": "Скука",
    "status": "Статус", "spirituality": "Духов.", "skill": "Умение",
    "love": "Любовь", "friendship": "Дружба",
}
NEED_ORDER = tuple(NEED_SHORT)


class Particle:
    """Простейшая боевая частица."""

    __slots__ = ("kind", "x", "y", "tx", "ty", "vx", "vy", "life", "max_life",
                 "color", "size", "angle")

    def __init__(self, kind, x, y, tx=None, ty=None, life=0.3,
                 color=(255, 220, 150), size=2, vx=0.0, vy=0.0, angle=0.0):
        self.kind = kind
        self.x = float(x)
        self.y = float(y)
        self.tx = float(tx if tx is not None else x)
        self.ty = float(ty if ty is not None else y)
        self.vx = float(vx)
        self.vy = float(vy)
        self.life = float(life)
        self.max_life = max(0.001, float(life))
        self.color = color
        self.size = size
        self.angle = angle

    def update(self, dt):
        self.life -= dt
        if self.kind in ("spark", "dust"):
            self.x += self.vx * dt
            self.y += self.vy * dt
            self.vy += 80.0 * dt
        return self.life > 0

    def draw(self, surface):
        t = max(0.0, min(1.0, self.life / self.max_life))
        if self.kind == "tracer":
            progress = 1.0 - t
            px = self.x + (self.tx - self.x) * progress
            py = self.y + (self.ty - self.y) * progress
            # Короткий светящийся отрезок создаёт ощущение летящей пули.
            tail = 0.22
            sx = self.x + (self.tx - self.x) * max(0.0, progress - tail)
            sy = self.y + (self.ty - self.y) * max(0.0, progress - tail)
            pygame.draw.line(surface, (255, 214, 130), (sx, sy), (px, py),
                             max(1, self.size))
            pygame.draw.circle(surface, (255, 244, 200),
                               (int(px), int(py)), max(1, self.size))
        elif self.kind == "muzzle":
            radius = int(7 + 10 * (1.0 - t))
            pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)),
                               radius, 2)
            for i in range(5):
                a = self.angle + i * math.tau / 5
                ex = self.x + math.cos(a) * radius * 1.7
                ey = self.y + math.sin(a) * radius * 1.7
                pygame.draw.line(surface, self.color, (self.x, self.y),
                                 (ex, ey), 1)
        elif self.kind == "melee":
            radius = int(14 + 10 * (1.0 - t))
            rect = pygame.Rect(0, 0, radius * 2, radius * 2)
            rect.center = (int(self.x), int(self.y))
            pygame.draw.arc(surface, self.color, rect,
                            self.angle, self.angle + 1.8, 3)
            pygame.draw.arc(surface, (255, 255, 255), rect,
                            self.angle + 0.2, self.angle + 1.3, 1)
        elif self.kind == "spark":
            pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)),
                               max(1, int(self.size * t)))
        elif self.kind == "dust":
            pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)),
                               max(1, int(self.size * t)))


class RTSScreen(BaseScreen):
    """Основной игровой экран кампании."""

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
        # Группы рот хранятся в состоянии, чтобы пережить пересоздание
        # экрана и сохранение кампании. В списке — имена, не индексы.
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
            self.state.count, self.selected,
        )

    # --- геометрия и отрисовка карты ------------------------------------
    def _build_terrain(self):
        """Один раз нарисовать изометрическую подложку."""
        surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        # Мягкий фон вокруг карты.
        pygame.draw.rect(surf, (12, 18, 23), MAP_RECT)
        for gy in range(GRID + 1):
            for gx in range(GRID + 1):
                x, y = self._project((gx, gy))
                points = [
                    (x, y),
                    (x + TILE_W / 2, y + TILE_H / 2),
                    (x, y + TILE_H),
                    (x - TILE_W / 2, y + TILE_H / 2),
                ]
                base = 46 + ((gx * 13 + gy * 7) % 11)
                color = (base - 16, base + 6, base - 8)
                pygame.draw.polygon(surf, color, points)
                pygame.draw.polygon(surf, (30, 43, 50), points, 1)
        # Условная река — визуальный ориентир, не влияющий на движение.
        river = []
        for gy in range(GRID + 1):
            gx = 17.0 + 1.1 * math.sin(gy * 0.42)
            river.append(self._project((gx, gy)))
        if len(river) > 1:
            pygame.draw.lines(surf, (38, 92, 126), False, river, 9)
            pygame.draw.lines(surf, (55, 122, 158), False, river, 3)
        return surf

    def _base_project(self, cell):
        gx, gy = float(cell[0]), float(cell[1])
        return (
            ISO_ORIGIN[0] + (gx - gy) * TILE_W / 2.0,
            ISO_ORIGIN[1] + (gx + gy) * TILE_H / 2.0,
        )

    def _project(self, cell):
        """Спроецировать клетку на экран с учётом текущего масштаба."""
        bx, by = self._base_project(cell)
        ax, ay = self._zoom_anchor
        return (
            ax + (bx - ax) * self.zoom,
            ay + (by - ay) * self.zoom,
        )

    def _unproject(self, pos):
        ax, ay = self._zoom_anchor
        bx = ax + (float(pos[0]) - ax) / max(0.01, self.zoom)
        by = ay + (float(pos[1]) - ay) / max(0.01, self.zoom)
        dx = bx - ISO_ORIGIN[0]
        dy = by - ISO_ORIGIN[1]
        gx = (dx / (TILE_W / 2.0) + dy / (TILE_H / 2.0)) / 2.0
        gy = (dy / (TILE_H / 2.0) - dx / (TILE_W / 2.0)) / 2.0
        return gx, gy

    def _scaled_terrain(self):
        """Кэш масштабированной подложки карты."""
        key = round(float(self.zoom), 3)
        cached = self._zoom_cache.get(key)
        if cached is not None:
            return cached
        ax, ay = self._zoom_anchor
        scaled_w = max(1, int(WIDTH * self.zoom))
        scaled_h = max(1, int(HEIGHT * self.zoom))
        scaled = pygame.transform.smoothscale(
            self._terrain, (scaled_w, scaled_h)
        )
        # Масштабирование вокруг точки карты, а не вокруг угла окна.
        offset = (int(ax - ax * self.zoom), int(ay - ay * self.zoom))
        self._zoom_cache[key] = (scaled, offset)
        if len(self._zoom_cache) > 12:
            self._zoom_cache.pop(next(iter(self._zoom_cache)))
        return scaled, offset

    def set_zoom(self, value):
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, float(value)))
        if abs(new_zoom - self.zoom) < 0.001:
            return
        self.zoom = new_zoom
        self._sync_render_positions(snap=True)
        self._update_display_positions()
        self._feedback("Масштаб %d%%" % round(self.zoom * 100), 1.0)

    def zoom_in(self):
        self.set_zoom(self.zoom + ZOOM_STEP)

    def zoom_out(self):
        self.set_zoom(self.zoom - ZOOM_STEP)

    def zoom_reset(self):
        self.set_zoom(1.0)

    def _cell_from_mouse(self, pos):
        gx, gy = self._unproject(pos)
        return (
            max(0, min(GRID, int(round(gx)))),
            max(0, min(GRID, int(round(gy)))),
        )

    # --- кнопки ---------------------------------------------------------
    def _build_buttons(self):
        self.btn_pause = Button(
            (1040, 9, 94, 36), "Пауза", self.app.font_small, self.toggle_pause
        )
        self.btn_speed1 = Button(
            (1140, 9, 24, 36), "1x", self.app.font_tiny,
            lambda: self.set_speed(1)
        )
        self.btn_speed2 = Button(
            (1166, 9, 24, 36), "2x", self.app.font_tiny,
            lambda: self.set_speed(2)
        )
        self.btn_speed4 = Button(
            (1192, 9, 24, 36), "4x", self.app.font_tiny,
            lambda: self.set_speed(4)
        )
        self.btn_speed8 = Button(
            (1218, 9, 24, 36), "8x", self.app.font_tiny,
            lambda: self.set_speed(8)
        )
        # Автоплан — полоса над обычными приказами. Он действует на всю
        # армию, а приказы ниже по-прежнему работают с выделением.
        self.btn_plan_hold = Button(
            (12, 314, 66, 22), "Оборона", self.app.font_tiny,
            self.command_plan_hold
        )
        self.btn_plan_advance = Button(
            (80, 314, 72, 22), "Наступление", self.app.font_tiny,
            self.command_plan_advance
        )
        self.btn_plan_off = Button(
            (154, 314, 66, 22), "Снять", self.app.font_tiny,
            self.command_plan_off
        )
        # Кнопки скорости рисуются вручную, но Button даёт единый hover/click.
        self.btn_hold = Button(
            (12, 382, 208, 22), "Держать позиции", self.app.font_tiny,
            self.command_hold
        )
        self.btn_attack = Button(
            (12, 407, 208, 22), "Атака ближайшего", self.app.font_tiny,
            self.command_attack_nearest
        )
        self.btn_cautious = Button(
            (12, 432, 208, 22), "Осторожная атака", self.app.font_tiny,
            self.command_cautious_attack
        )
        self.btn_withdraw = Button(
            (12, 457, 208, 22), "Отход / отступить", self.app.font_tiny,
            self.command_withdraw
        )
        self.btn_march = Button(
            (12, 482, 208, 22), "Марш-бросок к цели", self.app.font_tiny,
            self.command_force_march
        )
        self.btn_rest = Button(
            (12, 507, 208, 22), "Отдых", self.app.font_tiny,
            self.command_rest
        )
        self.btn_stop = Button(
            (12, 532, 208, 22), "Стоп / занять оборону", self.app.font_tiny,
            self.command_stop
        )
        self.btn_orders = Button(
            (12, 574, 64, 28), "Приказы", self.app.font_tiny,
            self.open_orders
        )
        self.btn_needs = Button(
            (80, 574, 70, 28), "Нужды", self.app.font_tiny,
            self.open_needs
        )
        self.btn_journal = Button(
            (154, 574, 66, 28), "Журнал", self.app.font_tiny,
            self.open_journal
        )
        self.btn_logistics = Button(
            (12, 608, 100, 28), "Логистика", self.app.font_tiny,
            self.open_logistics
        )
        self.btn_radio = Button(
            (120, 608, 100, 28), "Рация", self.app.font_tiny,
            self.open_radio
        )

    # --- управление -----------------------------------------------------
    def toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.text = "Продолжить" if self.paused else "Пауза"
        self._feedback("Пауза" if self.paused else "Продолжение", 1.2)

    def set_speed(self, speed):
        self.speed = int(speed)
        self.paused = False
        self.btn_pause.text = "Пауза"
        self._feedback("Скорость x%d" % self.speed, 1.0)

    def on_escape(self):
        self.toggle_pause()

    def _feedback(self, text, seconds=2.0):
        self._action_feedback = str(text).replace("↔", "<->")
        self._feedback_timer = float(seconds)

    def _loss_limit_percent(self):
        """Порог поражения по потерям дивизии из сюжетного конфига."""
        def find(condition):
            if not isinstance(condition, dict):
                return None
            if condition.get("type") == "manpower_loss_above":
                try:
                    return max(1, int(round(
                        100.0 * float(condition.get("value", 0.2))
                    )))
                except (TypeError, ValueError):
                    return None
            for child in condition.get("conditions", []) or []:
                found = find(child)
                if found is not None:
                    return found
            return None

        interp = getattr(self.app, "storyline_interpreter", None)
        storyline = getattr(interp, "storyline", {}) if interp else {}
        for condition in (storyline or {}).get("lose_conditions", []) or []:
            found = find(condition)
            if found is not None:
                return found
        return 45

    def select_all_units(self):
        """Выделить все живые подразделения игрока (Ctrl+A / клик по «ВСЕ»)."""
        self.selected = self._player_indices()
        self.active_group = None
        if self.selected:
            self._feedback("Выбраны все: %d" % len(self.selected), 1.3)
        else:
            self._feedback("Живых подразделений не осталось", 1.3)

    def _group_indices(self, number):
        """Живые индексы отделений, записанных в группу ``number``."""
        names = set(self.groups.get(number, ()))
        return [
            i for i in self._player_indices()
            if self.state.units[i].name in names
        ]

    def assign_group(self, number):
        """Записать текущее выделение в группу (Ctrl+1…6)."""
        number = int(number)
        if number not in self.groups:
            return
        names = [det.name for det in self._selected_dets()]
        if not names:
            self._feedback("Сначала выберите роты для группы %d" % number, 1.6)
            return
        self.groups[number] = names
        self.active_group = number
        self._feedback(
            "Группа %d: %d рот" % (number, len(names)), 1.5
        )

    def select_group(self, number):
        """Выбрать группу под общий приказ (Shift/Alt+1…6)."""
        number = int(number)
        indices = self._group_indices(number)
        if not indices:
            self._feedback("Группа %d пуста" % number, 1.2)
            return
        self.selected = indices
        self.active_group = number
        self._feedback(
            "Группа %d: %d рот — общий приказ" % (number, len(indices)), 1.5
        )

    def _player_indices(self):
        return [
            i for i, det in enumerate(self.state.units)
            if det.side == getattr(self.state, "player_side", "red")
            and not getattr(det, "broken", False)
        ]

    def _unit_at(self, pos):
        """Индекс подразделения под курсором (или None)."""
        best = None
        best_y = -10**9
        for i, det in enumerate(self.state.units):
            if getattr(det, "broken", False):
                continue
            p = self._display_pos.get(det.name)
            if p is None:
                continue
            rect = pygame.Rect(0, 0, 42, 34)
            rect.center = (int(p[0]), int(p[1]) - 5)
            if rect.collidepoint(pos) and p[1] > best_y:
                best = i
                best_y = p[1]
        return best

    def _selected_dets(self):
        return [
            det for i, det in enumerate(self.state.units)
            if i in self.selected and det.side ==
            getattr(self.state, "player_side", "red")
            and not getattr(det, "broken", False)
        ]

    def _prune_selection(self):
        """Убрать из выделения уничтоженные/исчезнувшие подразделения."""
        valid = set(self._player_indices())
        self.selected = [i for i in self.selected if i in valid]
        if self._target_enemy is not None:
            enemy = self.state.det_at(self._target_enemy)
            if (enemy is None or getattr(enemy, "broken", False) or
                    enemy.side == getattr(self.state, "player_side", "red")):
                self._target_enemy = None

    def _target_enemy_det(self):
        if self._target_enemy is None:
            return None
        enemy = self.state.det_at(self._target_enemy)
        if (enemy is None or getattr(enemy, "broken", False) or
                enemy.side == getattr(self.state, "player_side", "red")):
            self._target_enemy = None
            return None
        return enemy

    def _set_target_enemy(self, idx):
        enemy = self.state.det_at(idx)
        if (enemy is None or getattr(enemy, "broken", False) or
                enemy.side == getattr(self.state, "player_side", "red")):
            return None
        self._target_enemy = idx
        return enemy

    def _nearest_enemy(self, det):
        enemies = [
            d for d in self.state.units
            if d.side != getattr(self.state, "player_side", "red")
            and not d.broken
        ]
        if not enemies:
            return None
        return min(
            enemies,
            key=lambda d: abs(d.position[0] - det.position[0]) +
            abs(d.position[1] - det.position[1]),
        )

    def command_plan_hold(self):
        """Армейский план: занять и держать рубеж."""
        if not self.engine.set_auto_plan("hold"):
            self._feedback("Нет живых рот для плана", 1.4)
            return
        self._feedback(
            "Автоплан: оборона — Shift+ПКМ задаёт рубеж", 2.2
        )

    def command_plan_advance(self):
        """Армейский план: наступать на выбранную цель."""
        target_det = self._target_enemy_det()
        target = tuple(target_det.position) if target_det is not None else None
        if not self.engine.set_auto_plan("advance", target=target):
            self._feedback("Нет живых рот для плана", 1.4)
            return
        where = ("на %s" % target_det.name if target_det is not None
                 else "к противнику")
        self._feedback(
            "Автоплан: наступление %s — Shift+ПКМ меняет направление" %
            where, 2.2,
        )

    def command_plan_off(self):
        self.engine.clear_auto_plan()
        self._feedback("Автоплан снят", 1.4)

    def _issue_plan_target(self, cell):
        """Shift+ПКМ: перенести рубеж или направление плана."""
        plan = self.engine.plan_for()
        if not plan.active:
            self._feedback(
                "Сначала включите автоплан: G — оборона, T — наступление",
                2.0,
            )
            return
        mode = plan.mode
        if not self.engine.set_auto_plan(
                mode, target=cell, keep_exemptions=True):
            self._feedback("Не удалось изменить план", 1.4)
            return
        if mode == "hold":
            self._feedback("Рубеж плана: %d:%d" % cell, 1.6)
        else:
            self._feedback("Направление плана: %d:%d" % cell, 1.6)

    def command_hold(self):
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine._targets.pop(det.name, None)
            self.engine.assign_order(idx, "holding_defense")
        self._feedback("Держать позиции", 1.3)

    def command_rest(self):
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine._targets.pop(det.name, None)
            self.engine.assign_order(idx, "rest")
        self._feedback("Отдых", 1.3)

    def command_stop(self):
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine._targets.pop(det.name, None)
            self.engine.assign_order(idx, "defense")
        self._feedback("Стоп", 1.0)

    def command_attack_nearest(self):
        """Атаковать выбранную цель, иначе — ближайшего для каждого."""
        target = self._target_enemy_det()
        if target is not None:
            self._issue_attack(self._target_enemy)
            return
        count = 0
        for det in self._selected_dets():
            enemy = self._nearest_enemy(det)
            if enemy is None:
                continue
            idx = self.state.units.index(det)
            self.engine.clear_focus_target(idx)
            self.engine.assign_order(idx, "aggressive_attack")
            if enemy is not None:
                self.engine.set_focus_target(idx, enemy)
            count += 1
        self._feedback("Атака: %d" % count, 1.2)

    def command_cautious_attack(self):
        count = 0
        target = self._target_enemy_det()
        for det in self._selected_dets():
            enemy = target or self._nearest_enemy(det)
            if enemy is None:
                continue
            idx = self.state.units.index(det)
            self.engine.assign_order(idx, "cautious_attack")
            self.engine.set_focus_target(idx, enemy)
            count += 1
        if target is not None:
            self._feedback("Осторожно по цели: %s" % target.name, 1.3)
        else:
            self._feedback("Осторожная атака: %d" % count, 1.2)

    def command_withdraw(self):
        count = 0
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine.clear_focus_target(idx)
            self.engine.assign_order(idx, "withdrawal")
            count += 1
        self._feedback("Отход: %d" % count, 1.3)

    def command_force_march(self):
        count = 0
        for det in self._selected_dets():
            enemy = self._target_enemy_det() or self._nearest_enemy(det)
            if enemy is None:
                continue
            idx = self.state.units.index(det)
            self.engine.assign_order(idx, "forced_march")
            self.engine.set_cell_target(idx, enemy.position)
            self.engine.set_focus_target(idx, enemy)
            det.ui_order = "forced_march"
            count += 1
        self._feedback("Марш-бросок: %d" % count, 1.2)

    def _issue_ground(self, cell):
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine.clear_focus_target(idx)
            self.engine.assign_order(idx, "move")
            self.engine.set_cell_target(idx, cell)
        if self.selected:
            self._feedback("Движение в %d:%d" % cell, 1.0)

    def _issue_attack(self, enemy_idx):
        """Сосредоточить огонь выделенных подразделений на одной цели."""
        enemy = self._set_target_enemy(enemy_idx)
        if enemy is None:
            self._feedback("Цель уже уничтожена", 1.2)
            return
        count = 0
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            if not self.engine.set_focus_target(idx, enemy):
                continue
            self.engine.assign_order(idx, "aggressive_attack")
            # assign_order сохраняет явную цель, но повторно фиксируем её,
            # чтобы позиция движения точно указывала на выбранного врага.
            self.engine.set_focus_target(idx, enemy)
            count += 1
        if count:
            self._feedback(
                "Сосредоточенный огонь: %s (%d)" % (enemy.name, count), 1.8
            )
        else:
            self._feedback("Сначала выберите свои подразделения", 1.4)

    def command_focus_hover(self):
        """Сконцентрировать огонь на враге под курсором (клавиша F)."""
        if self._hover_idx is None:
            self._feedback("Наведите курсор на врага", 1.2)
            return
        if self._hover_idx in self._player_indices():
            self._feedback("Под курсором своё подразделение", 1.2)
            return
        self._issue_attack(self._hover_idx)

    def open_orders(self):
        from ..ui.orders_overlay import UnitOrdersOverlay
        self.app.manager.push(UnitOrdersOverlay(self.app, self))

    def open_needs(self):
        from ..ui.needs_overlay import NeedsOverlay
        self.app.manager.push(NeedsOverlay(self.app, self))

    def open_adjutant_orders(self):
        from .adjutant_orders import AdjutantOrdersScreen
        self.app.manager.push(AdjutantOrdersScreen(self.app))

    def open_journal(self):
        from ..ui.overlays import NotebookOverlay
        self.app.manager.push(NotebookOverlay(self.app))

    def open_logistics(self):
        from ..ui.overlays import LogisticsOverlay
        self.app.manager.push(LogisticsOverlay(self.app))

    def open_radio(self):
        from ..ui.overlays import RadioOverlay
        self.app.manager.push(RadioOverlay(self.app))

    # --- такт и частицы -------------------------------------------------
    def update(self, dt):
        self._prune_selection()
        self._feedback_timer = max(0.0, self._feedback_timer - dt)
        self._sync_render_positions(dt)
        self._update_display_positions(dt)
        self._particles = [p for p in self._particles if p.update(dt)]
        if self.paused or self.finished:
            return
        ts = getattr(self.app, "time_system", None)
        if ts is None:
            return
        if ts.pending_mandatory_scene is not None:
            return
        interval = REAL_SECONDS_PER_GAME_MINUTE / max(1, self.speed)
        self._tick_accum += dt
        guard = 0
        while self._tick_accum >= interval and guard < 240:
            guard += 1
            self._tick_accum -= interval
            before_turn = self.state.sim.turn
            ts.advance(60)
            if self.state.sim.turn != before_turn:
                self._after_tick()
            if (ts.pending_mandatory_scene is not None or
                    self.state.sim.finished or self.app.pending_storyline_outcome):
                break

    def _after_tick(self):
        if self.state.sim.finished:
            self.finished = True
            self.paused = True
            self._feedback("Операция завершена", 4.0)
            self._trigger_battle_outcome()
        elif hasattr(self.app, "check_storyline_end_of_day"):
            # Порог потерь теперь проверяется не только вечером, но и после
            # каждого войскового такта: поражение наступает сразу.
            self.app.check_storyline_end_of_day()
        self._spawn_battle_particles()
        if self.state.tick_events:
            self._feedback(self.state.tick_events[-1].get("message", ""), 3.0)
        if not self.state.sim.finished:
            self._report_loss_status()

    def _report_loss_status(self):
        """Показать и записать в журнал приближение к порогу поражения."""
        loss = self.state.division_loss_percent()
        limit = self._loss_limit_percent()
        milestone = (int(loss) // 5) * 5
        if milestone > self._last_loss_milestone:
            self._last_loss_milestone = milestone
            logger.info(
                "Потери дивизии: %.1f%% (порог поражения %d%%)", loss, limit
            )
        if limit <= 0:
            return
        ratio = loss / float(limit)
        if ratio >= 0.5 and not self._loss_warned_50:
            self._loss_warned_50 = True
            self._feedback(
                "Потери дивизии: %.1f%% из %d%% — берегите людей" %
                (loss, limit), 4.0,
            )
        if ratio >= 0.75 and not self._loss_warned_75:
            self._loss_warned_75 = True
            self._feedback(
                "КРИТИЧНО: потери %.1f%% из %d%% до поражения" %
                (loss, limit), 5.0,
            )

    def _trigger_battle_outcome(self):
        """Передать исход боя в общий сюжетный обработчик победы/поражения."""
        if getattr(self.app, "storyline_interpreter", None) is None:
            return
        winner = getattr(self.state.sim, "winner", None)
        player_side = getattr(self.state, "player_side", "red")
        outcome = "win" if winner == player_side else "lose"
        if hasattr(self.app, "finish_storyline_outcome"):
            self.app.finish_storyline_outcome(outcome)
        else:
            self.app.pending_storyline_outcome = outcome

    def _spawn_battle_particles(self):
        for pair in getattr(self.engine, "engagements", []):
            a = next((d for d in self.state.units
                      if d.name == pair.get("attacker")), None)
            b = next((d for d in self.state.units
                      if d.name == pair.get("defender")), None)
            if a is None or b is None:
                continue
            pa = self._display_pos.get(a.name) or self._render_pos.get(a.name)
            pb = self._display_pos.get(b.name) or self._render_pos.get(b.name)
            if pa is None or pb is None:
                continue
            distance = abs(a.position[0] - b.position[0]) + abs(
                a.position[1] - b.position[1]
            )
            angle = math.atan2(pb[1] - pa[1], pb[0] - pa[0])
            if distance <= 2:
                self._particles.append(Particle(
                    "melee", pb[0] - 4, pb[1] - 6, life=0.30,
                    color=(255, 230, 170), size=3,
                    angle=angle - 0.8,
                ))
                self._particles.append(Particle(
                    "melee", pb[0] + 4, pb[1] + 2, life=0.24,
                    color=(255, 190, 120), size=2,
                    angle=angle + 1.0,
                ))
                for _ in range(4):
                    self._particles.append(Particle(
                        "spark", pb[0], pb[1] - 4,
                        life=self._rng.uniform(0.25, 0.55),
                        color=(255, 210, 120), size=self._rng.randint(2, 4),
                        vx=self._rng.uniform(-70, 70),
                        vy=self._rng.uniform(-90, -20),
                    ))
            else:
                self._particles.append(Particle(
                    "muzzle", pa[0], pa[1] - 6, life=0.18,
                    color=(255, 220, 130), size=2, angle=angle,
                ))
                for _ in range(2):
                    self._particles.append(Particle(
                        "tracer", pa[0], pa[1] - 6, pb[0], pb[1] - 4,
                        life=self._rng.uniform(0.22, 0.38),
                        color=(255, 220, 140), size=2,
                    ))
                self._particles.append(Particle(
                    "spark", pb[0], pb[1] - 4, life=0.3,
                    color=(255, 170, 90), size=3,
                ))

    def _combat_interval_real(self):
        """Сколько реальных секунд длится один 5-минутный войсковой такт."""
        ts = getattr(self.app, "time_system", None)
        game_seconds = (
            getattr(ts, "combat_tick_seconds", 300) if ts is not None else 300
        )
        game_minutes = float(game_seconds) / 60.0
        return max(
            0.12,
            REAL_SECONDS_PER_GAME_MINUTE * game_minutes /
            max(1, int(self.speed)),
        )

    def _sync_render_positions(self, dt=0.0, snap=False):
        """Плавно провести жетоны между клетками боевой сетки.

        Ядро двигает отделение на клетку за такт. Рендер растягивает этот
        переход на весь реальный интервал такта, поэтому движение выглядит
        непрерывным, а не рывком раз в несколько секунд.
        """
        duration = self._combat_interval_real()
        for det in self.state.units:
            target = self._project(det.position)
            current = self._render_pos.get(det.name)
            if snap or current is None:
                self._render_pos[det.name] = target
                self._render_anim[det.name] = {
                    "from": target, "to": target, "elapsed": duration,
                    "duration": duration,
                }
                self._moving[det.name] = False
                continue
            anim = self._render_anim.get(det.name)
            if anim is None:
                anim = {
                    "from": current, "to": current, "elapsed": duration,
                    "duration": duration,
                }
            if (abs(target[0] - anim["to"][0]) > 0.5 or
                    abs(target[1] - anim["to"][1]) > 0.5):
                # Новая клетка — начинаем новый отрезок из текущей точки.
                anim = {
                    "from": current, "to": target, "elapsed": 0.0,
                    "duration": duration,
                }
                self._render_anim[det.name] = anim
            else:
                anim["elapsed"] = min(
                    anim["duration"], anim["elapsed"] + max(0.0, dt)
                )
            progress = min(
                1.0, anim["elapsed"] / max(0.001, anim["duration"])
            )
            self._render_pos[det.name] = (
                anim["from"][0] + (target[0] - anim["from"][0]) * progress,
                anim["from"][1] + (target[1] - anim["from"][1]) * progress,
            )
            anim["to"] = target
            # Неподвижный жетон не должен «плавать» из-за соседей: при
            # разведении перекрытий он остаётся якорем, а двигаются только
            # те жетоны, которые действительно идут.
            self._moving[det.name] = (
                anim["elapsed"] < anim["duration"] - 1e-4 and
                math.dist(anim["from"], anim["to"]) > 0.5
            )

    def _update_display_positions(self, dt=0.0):
        """Развести жетоны, чтобы плотный контакт не превращался в кашу.

        Покоящиеся жетоны служат якорями. Для идущих добавляется короткое
        сглаживание: даже если соседи на секунду переставили их местами,
        картинка не дёргается, а плавно догоняет новую точку.
        """
        entries = []
        follow = 0.0
        if dt > 0.0:
            follow = 1.0 - math.exp(-max(0.0, float(dt)) * 20.0)
        for i, det in enumerate(self.state.units):
            if getattr(det, "broken", False):
                continue
            p = self._render_pos.get(det.name)
            if p is None:
                continue
            moving = bool(self._moving.get(det.name, False))
            previous = self._display_pos.get(det.name)
            if previous is not None and dt > 0.0:
                if moving:
                    # Идущий жетон плавно догоняет свою клетку. Покойный
                    # остаётся там, где был: смена флага «движется/стоит» на
                    # границе такта не должна переставлять его на другой бок.
                    x = previous[0] + (float(p[0]) - previous[0]) * follow
                    y = previous[1] + (float(p[1]) - previous[1]) * follow
                else:
                    x, y = float(previous[0]), float(previous[1])
            else:
                x, y = float(p[0]), float(p[1])
            entries.append([det.name, x, y, i, moving])
        # Детерминированно раздвигаем пары, перекрывающиеся по площади жетона.
        # Неподвижный жетон имеет приоритет: его не толкают идущие соседи,
        # иначе весь строй начинает мелко дрожать на месте.
        min_dist = 30.0
        left = MAP_RECT.left + 18
        right = MAP_RECT.right - 18
        top = MAP_RECT.top + 38
        # Ниже начинаются легенда и лента событий: не прячем туда жетоны.
        bottom = min(MAP_RECT.bottom - 24, 598)

        def clamp(item):
            item[1] = max(left, min(right, item[1]))
            item[2] = max(top, min(bottom, item[2]))

        for item in entries:
            clamp(item)
        for _ in range(14):
            moved = False
            for a in range(len(entries)):
                for b in range(a + 1, len(entries)):
                    ax, ay = entries[a][1], entries[a][2]
                    bx, by = entries[b][1], entries[b][2]
                    dx, dy = bx - ax, by - ay
                    distance = math.hypot(dx, dy)
                    if distance >= min_dist:
                        continue
                    if distance < 0.01:
                        angle = ((entries[a][3] * 2.399) % math.tau)
                        dx, dy = math.cos(angle), math.sin(angle)
                        distance = 1.0
                    overlap = min_dist - distance
                    ux, uy = dx / distance, dy / distance
                    a_moving = entries[a][4]
                    b_moving = entries[b][4]
                    if a_moving and b_moving:
                        wa, wb = 0.5, 0.5
                    elif a_moving:
                        wa, wb = 1.0, 0.0
                    elif b_moving:
                        wa, wb = 0.0, 1.0
                    else:
                        # В анимированном кадре два покоящихся жетона не
                        # трогаем: их экранная точка не должна «плыть» из-за
                        # соседей. При принудительной пересборке (dt=0, смена
                        # масштаба/загрузка) разводим и их.
                        if dt > 0.0:
                            continue
                        wa, wb = 0.5, 0.5
                    entries[a][1] -= ux * overlap * wa
                    entries[a][2] -= uy * overlap * wa
                    entries[b][1] += ux * overlap * wb
                    entries[b][2] += uy * overlap * wb
                    clamp(entries[a])
                    clamp(entries[b])
                    moved = True
            if not moved:
                break
        if dt > 0.0:
            # Последний низкочастотный фильтр: даже если разведение жетонов
            # на границе такта пересобралось, скачок не проходит в кадр
            # целиком, а плавно распределяется во времени.
            smooth = 1.0 - math.exp(-max(0.0, float(dt)) * 12.0)
            for item in entries:
                previous = self._display_pos.get(item[0])
                if previous is None:
                    continue
                item[1] = previous[0] + (item[1] - previous[0]) * smooth
                item[2] = previous[1] + (item[2] - previous[1]) * smooth
        self._display_pos = {
            name: (x, y) for name, x, y, _idx, _moving in entries
        }

    # --- события --------------------------------------------------------
    def handle_event(self, event):
        for b in (
            self.btn_pause, self.btn_speed1, self.btn_speed2,
            self.btn_speed4, self.btn_speed8, self.btn_plan_hold,
            self.btn_plan_advance, self.btn_plan_off, self.btn_hold,
            self.btn_attack, self.btn_cautious, self.btn_withdraw,
            self.btn_march, self.btn_rest, self.btn_stop, self.btn_orders,
            self.btn_needs, self.btn_journal, self.btn_logistics,
            self.btn_radio,
        ):
            if b.handle_event(event):
                return
        if event.type == pygame.KEYDOWN:
            group_number = {
                pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3,
                pygame.K_4: 4, pygame.K_5: 5, pygame.K_6: 6,
            }.get(event.key)
            if group_number is not None:
                mods = getattr(event, "mod", 0)
                if mods & pygame.KMOD_CTRL:
                    self.assign_group(group_number)
                    return
                if mods & (pygame.KMOD_SHIFT | pygame.KMOD_ALT):
                    self.select_group(group_number)
                    return
            if event.key in (pygame.K_SPACE, pygame.K_p):
                self.toggle_pause()
            elif event.key == pygame.K_1:
                self.set_speed(1)
            elif event.key == pygame.K_2:
                self.set_speed(2)
            elif event.key == pygame.K_3:
                self.set_speed(4)
            elif event.key == pygame.K_4:
                self.set_speed(8)
            elif event.key == pygame.K_h:
                self.command_hold()
            elif event.key == pygame.K_g:
                self.command_plan_hold()
            elif event.key == pygame.K_t:
                self.command_plan_advance()
            elif event.key == pygame.K_y:
                self.command_plan_off()
            elif event.key == pygame.K_r:
                self.command_rest()
            elif event.key == pygame.K_a:
                if getattr(event, "mod", 0) & pygame.KMOD_CTRL:
                    self.select_all_units()
                else:
                    self.command_attack_nearest()
            elif event.key == pygame.K_c:
                self.command_cautious_attack()
            elif event.key == pygame.K_w:
                self.command_withdraw()
            elif event.key == pygame.K_m:
                self.command_force_march()
            elif event.key == pygame.K_s:
                self.command_stop()
            elif event.key == pygame.K_o:
                self.open_orders()
            elif event.key == pygame.K_n:
                self.open_needs()
            elif event.key in (pygame.K_PLUS, pygame.K_EQUALS,
                               pygame.K_KP_PLUS):
                self.zoom_in()
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.zoom_out()
            elif event.key == pygame.K_0:
                self.zoom_reset()
            elif event.key == pygame.K_f:
                self.command_focus_hover()
            return
        if event.type == pygame.MOUSEWHEEL:
            if MAP_RECT.collidepoint(pygame.mouse.get_pos()):
                if event.y > 0:
                    self.zoom_in()
                elif event.y < 0:
                    self.zoom_out()
                return
        if event.type == pygame.MOUSEMOTION:
            self._hover_idx = self._unit_at(event.pos)
            if self._drag_start is not None:
                x, y = self._drag_start
                self._drag_rect = pygame.Rect(
                    min(x, event.pos[0]), min(y, event.pos[1]),
                    abs(event.pos[0] - x), abs(event.pos[1] - y),
                )
            return
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                if self._handle_ui_click(
                        event.pos, getattr(event, "mod", 0)):
                    return
                hit = self._unit_at(event.pos)
                if hit is not None:
                    if hit in self._player_indices():
                        self.active_group = None
                        if getattr(event, "mod", 0) & pygame.KMOD_SHIFT:
                            if hit in self.selected:
                                self.selected.remove(hit)
                            else:
                                self.selected.append(hit)
                        else:
                            self.selected = [hit]
                    else:
                        # Клик по врагу запоминает цель, не сбрасывая своих.
                        enemy = self._set_target_enemy(hit)
                        if enemy is not None:
                            self._feedback(
                                "Цель: %s — ПКМ или «Атака»" % enemy.name,
                                1.5,
                            )
                    return
                if MAP_RECT.collidepoint(event.pos):
                    self._drag_start = event.pos
                    self._drag_rect = pygame.Rect(event.pos, (0, 0))
            elif event.button == 3:
                for number, rect in self._group_rects:
                    if rect.collidepoint(event.pos):
                        self.assign_group(number)
                        return
                if MAP_RECT.collidepoint(event.pos):
                    mods = (getattr(event, "mod", 0) or
                            pygame.key.get_mods())
                    if mods & pygame.KMOD_SHIFT:
                        self._issue_plan_target(
                            self._cell_from_mouse(event.pos)
                        )
                        return
                    hit = self._unit_at(event.pos)
                    if hit is not None and hit not in self._player_indices():
                        self._issue_attack(hit)
                    else:
                        self._issue_ground(self._cell_from_mouse(event.pos))
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._drag_rect is not None:
                rect = self._drag_rect.copy()
                self._drag_start = None
                self._drag_rect = None
                if rect.width < 6 and rect.height < 6:
                    return
                chosen = []
                for i in self._player_indices():
                    p = self._display_pos.get(self.state.units[i].name)
                    if p and rect.collidepoint(p):
                        chosen.append(i)
                if chosen:
                    self.selected = chosen
                else:
                    self.selected = []
                self.active_group = None
            return

    def _handle_ui_click(self, pos, mods=0):
        """Клик по списку юнитов, группам, масштабу и потребностям."""
        # Компактная строка групп под списком рот. Ctrl+клик записывает
        # текущее выделение, обычный клик — выбирает группу.
        if not mods:
            mods = pygame.key.get_mods()
        for number, rect in self._group_rects:
            if rect.collidepoint(pos):
                if mods & pygame.KMOD_CTRL:
                    self.assign_group(number)
                else:
                    self.select_group(number)
                return True
        # Заголовок списка и кнопка «ВСЕ» выделяют всю группировку.
        if pygame.Rect(12, 64, 208, 22).collidepoint(pos):
            self.select_all_units()
            return True
        # Список подразделений: две колонки по восемь строк.
        row = min(7, max(0, (pos[1] - 94) // 24))
        col = None
        if pygame.Rect(12, 94, 100, 192).collidepoint(pos):
            col = 0
        elif pygame.Rect(120, 94, 100, 192).collidepoint(pos):
            col = 1
        if col is not None:
            players = self._player_indices()
            list_pos = row * 2 + col
            if list_pos < len(players):
                self.selected = [players[list_pos]]
                return True
        # Масштаб карты.
        if pygame.Rect(930, 9, 28, 36).collidepoint(pos):
            self.zoom_out()
            return True
        if pygame.Rect(962, 9, 28, 36).collidepoint(pos):
            self.zoom_in()
            return True
        if pygame.Rect(994, 9, 40, 36).collidepoint(pos):
            self.zoom_reset()
            return True
        # Панель личных потребностей только открывает оверлей; действий за
        # подразделения здесь больше нет.
        if self._commander_rect.collidepoint(pos):
            self.open_needs()
            return True
        return False

    # --- отрисовка ------------------------------------------------------
    def draw(self, screen):
        screen.fill(DAY_COLORS["bg"])
        self._draw_top(screen)
        self._draw_left(screen)
        self._draw_map(screen)
        self._draw_right(screen)
        self._draw_feedback(screen)

    def _draw_top(self, screen):
        pygame.draw.rect(screen, (9, 13, 18), (0, 0, WIDTH, TOP_H))
        pygame.draw.line(screen, DAY_COLORS["line"], (0, TOP_H - 1),
                         (WIDTH, TOP_H - 1))
        title = self.app.font_title.render("ДОЛИНА-01", True, DAY_COLORS["text"])
        screen.blit(title, (16, 9))
        sub = self.app.font_tiny.render(
            "ТАКТИЧЕСКАЯ КАРТА · RTS / RPG", True, DAY_COLORS["muted"]
        )
        screen.blit(sub, (18, 38))
        ts = getattr(self.app, "time_system", None)
        if ts is not None:
            time_text = ts.get_time_string()
            clock = self.app.font_body.render(time_text, True, DAY_COLORS["gold"])
            screen.blit(clock, (270, 15))
            turn = self.app.font_tiny.render(
                "такт %d · %s" % (
                    self.state.current_tick,
                    "ПАУЗА" if self.paused else "x%d" % self.speed,
                ),
                True,
                DAY_COLORS["muted"],
            )
            screen.blit(turn, (272, 40))
        # Кто чей: баннер стороны игрока всегда перед глазами. Здесь же
        # виден порог поражения по потерям дивизии, чтобы он не стал
        # неожиданностью посреди боя.
        side = getattr(self.state, "player_side", "red")
        enemy_side = "blue" if side == "red" else "red"
        side_color = SIDE_COLORS.get(side, DAY_COLORS["player"])
        loss = self.state.division_loss_percent()
        loss_limit = self._loss_limit_percent()
        loss_ratio = loss / max(1.0, float(loss_limit))
        loss_color = (
            DAY_COLORS["bad"] if loss_ratio >= 0.85 else
            DAY_COLORS["warn"] if loss_ratio >= 0.6 else
            DAY_COLORS["muted"]
        )
        banner = pygame.Rect(470, 8, 450, 40)
        pygame.draw.rect(screen, (27, 24, 28), banner, border_radius=5)
        pygame.draw.rect(screen, side_color, banner, 2, border_radius=5)
        pygame.draw.circle(screen, side_color,
                           (banner.x + 16, banner.y + 20), 8)
        screen.blit(self.app.font_small.render(
            "ВЫ КОМАНДУЕТЕ: %s" % SIDE_NAMES.get(side, side.upper()),
            True, DAY_COLORS["text"]), (banner.x + 32, banner.y + 3))
        sub_x = banner.x + 32
        sub_y = banner.y + 22
        side_text = "противник: %s · " % SIDE_NAMES.get(
            enemy_side, enemy_side.upper()
        )
        side_surf = self.app.font_tiny.render(
            side_text, True, DAY_COLORS["muted"]
        )
        screen.blit(side_surf, (sub_x, sub_y))
        loss_surf = self.app.font_tiny.render(
            "потери дивизии: %.1f%% / %d%%" % (loss, loss_limit),
            True, loss_color,
        )
        screen.blit(loss_surf, (sub_x + side_surf.get_width(), sub_y))
        # Масштаб карты.
        for x, label in (
            (930, "−"),
            (962, "+"),
            (994, "1:1"),
        ):
            rect = pygame.Rect(x, 9, 28 if label != "1:1" else 40, 36)
            pygame.draw.rect(screen, DAY_COLORS["panel2"], rect,
                             border_radius=4)
            pygame.draw.rect(screen, DAY_COLORS["line"], rect, 1,
                             border_radius=4)
            surf = self.app.font_small.render(label, True, DAY_COLORS["text"])
            screen.blit(surf, surf.get_rect(center=rect.center))
        screen.blit(self.app.font_tiny.render(
            "%d%%" % round(self.zoom * 100), True, DAY_COLORS["muted"]),
            (930, 47))
        # Кнопки скорости рисуются вручную, чтобы уместить 4 режима.
        self.btn_pause.draw(screen)
        for x, label, value in (
            (1140, "1x", 1), (1166, "2x", 2),
            (1192, "4x", 4), (1218, "8x", 8),
        ):
            rect = pygame.Rect(x, 9, 24, 36)
            active = self.speed == value and not self.paused
            color = DAY_COLORS["accent"] if active else DAY_COLORS["panel2"]
            pygame.draw.rect(screen, color, rect, border_radius=4)
            pygame.draw.rect(screen, DAY_COLORS["line"], rect, 1,
                             border_radius=4)
            surf = self.app.font_tiny.render(label, True, DAY_COLORS["text"])
            screen.blit(surf, surf.get_rect(center=rect.center))
        # Кнопки-скорости обрабатываются отдельно; Button в списке событий
        # не нужен, но оставляем их совместимыми с hover-подсветкой.
        self.btn_speed1.rect = pygame.Rect(1140, 9, 24, 36)
        self.btn_speed2.rect = pygame.Rect(1166, 9, 24, 36)
        self.btn_speed4.rect = pygame.Rect(1192, 9, 24, 36)
        self.btn_speed8.rect = pygame.Rect(1218, 9, 24, 36)

    def _draw_groups(self, screen):
        """Компактные чипы групп: клик — выбрать, ПКМ/Ctrl — записать."""
        screen.blit(self.app.font_tiny.render(
            "ГР", True, DAY_COLORS["muted"]
        ), (14, 285))
        for number, rect in self._group_rects:
            count = len(self._group_indices(number))
            active = self.active_group == number
            filled = count > 0
            bg = (DAY_COLORS["accent"] if active else
                  DAY_COLORS["ally_dark"] if filled else
                  DAY_COLORS["panel2"])
            pygame.draw.rect(screen, bg, rect, border_radius=3)
            pygame.draw.rect(
                screen,
                DAY_COLORS["gold"] if active else DAY_COLORS["line"],
                rect, 1, border_radius=3,
            )
            text = ("%d·%d" % (number, count)) if filled else str(number)
            surf = self.app.font_tiny.render(
                text, True,
                DAY_COLORS["text"] if filled else DAY_COLORS["muted"],
            )
            screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_left(self, screen):
        panel = pygame.Rect(0, TOP_H, LEFT_W, HEIGHT - TOP_H)
        pygame.draw.rect(screen, DAY_COLORS["panel"], panel)
        pygame.draw.line(screen, DAY_COLORS["line"],
                         (LEFT_W - 1, TOP_H), (LEFT_W - 1, HEIGHT))
        side = getattr(self.state, "player_side", "red")
        screen.blit(self.app.font_small.render(
            "ВАШИ ВОЙСКА · %s" % SIDE_NAMES.get(side, side.upper()),
            True, DAY_COLORS["muted"]), (14, 70)
        )
        all_rect = pygame.Rect(184, 67, 40, 17)
        pygame.draw.rect(screen, DAY_COLORS["panel2"], all_rect,
                         border_radius=3)
        pygame.draw.rect(screen, DAY_COLORS["line"], all_rect, 1,
                         border_radius=3)
        all_surf = self.app.font_tiny.render(
            "ВСЕ", True, DAY_COLORS["text"]
        )
        screen.blit(all_surf, all_surf.get_rect(center=all_rect.center))
        # 16 рот не помещаются в один столбец: список идёт двумя колонками
        # по восемь строк. Сектор обозначен короткой литерой Ф/Л/П/Т.
        players = self._player_indices()
        for pos, idx in enumerate(players):
            det = self.state.det_at(idx)
            if det is None:
                continue
            col = pos % 2
            row = pos // 2
            rect = pygame.Rect(12 + col * 108, 94 + row * 24, 100, 21)
            selected = idx in self.selected
            pygame.draw.rect(
                screen,
                DAY_COLORS["ally_dark"] if selected else DAY_COLORS["panel2"],
                rect, border_radius=4,
            )
            pygame.draw.rect(
                screen,
                DAY_COLORS["accent"] if selected else DAY_COLORS["line"],
                rect, 1, border_radius=4,
            )
            name = self.app.font_tiny.render(
                det.name, True, DAY_COLORS["text"]
            )
            screen.blit(name, (rect.x + 5, rect.y + 1))
            sector = self.state.sector_of(det)
            badge = self.app.font_tiny.render(
                SECTOR_SHORT.get(sector, "?"), True, DAY_COLORS["gold"]
            )
            screen.blit(badge, (rect.right - 12, rect.y + 1))
            ratio = det.force / max(1.0, self.state._start_force(det))
            ratio = max(0.0, min(1.0, ratio))
            bar = pygame.Rect(rect.x + 5, rect.y + 14, 56, 4)
            pygame.draw.rect(screen, (40, 46, 54), bar)
            pygame.draw.rect(screen, DAY_COLORS["good"],
                             (bar.x, bar.y, int(bar.width * ratio), bar.height))
            mini = self.app.font_tiny.render(
                "%d" % round(det.force), True, DAY_COLORS["muted"]
            )
            screen.blit(mini, (rect.x + 67, rect.y + 9))
        self._draw_groups(screen)
        screen.blit(self.app.font_small.render(
            "АВТОПЛАН", True, DAY_COLORS["muted"]), (14, 298)
        )
        plan = self.engine.plan_for()
        for b, mode in (
            (self.btn_plan_hold, "hold"),
            (self.btn_plan_advance, "advance"),
            (self.btn_plan_off, "off"),
        ):
            b.draw(screen)
            active = ((mode == plan.mode and plan.active) or
                      (mode == "off" and not plan.active))
            if active:
                pygame.draw.rect(screen, DAY_COLORS["gold"], b.rect, 2,
                                 border_radius=6)
        status = self.engine.plan_status_text()
        status_lines = wrap_text(
            self.app.font_tiny, status, 204
        )[:2]
        for offset, text in enumerate(status_lines):
            screen.blit(self.app.font_tiny.render(
                text, True,
                DAY_COLORS["gold"] if plan.active else DAY_COLORS["muted"],
            ), (14, 340 + offset * 12))
        screen.blit(self.app.font_small.render(
            "ПРИКАЗЫ", True, DAY_COLORS["muted"]), (14, 366)
        )
        target = self._target_enemy_det()
        self.btn_attack.text = (
            "Атака цели: %s" % target.name if target is not None
            else "Атака ближайшего"
        )
        for b in (self.btn_hold, self.btn_attack, self.btn_cautious,
                  self.btn_withdraw, self.btn_march, self.btn_rest,
                  self.btn_stop):
            b.draw(screen)
        screen.blit(self.app.font_small.render(
            "ШТАБ", True, DAY_COLORS["muted"]), (14, 560)
        )
        for b in (self.btn_orders, self.btn_needs, self.btn_journal,
                  self.btn_logistics, self.btn_radio):
            b.draw(screen)
        hint = self.app.font_tiny.render(
            "ПКМ — приказ; Shift+ПКМ — план\n"
            "G/T/Y — план; A…S — приказы\n"
            "Ctrl+A — все; Shift+1…6 — группа\n"
            "F — огонь; +/− — масштаб",
            True, DAY_COLORS["muted"],
        )
        screen.blit(hint, (14, 660))

    def _draw_map(self, screen):
        clip_before = screen.get_clip()
        screen.set_clip(MAP_RECT)
        terrain, offset = self._scaled_terrain()
        screen.blit(terrain, offset)
        pygame.draw.rect(screen, DAY_COLORS["line"], MAP_RECT, 1)
        self._draw_plan_overlay(screen)
        # Линии приказов выбранных юнитов. Явная цель рисуется красной
        # линией и перекрестием, обычное движение — золотой.
        for det in self._selected_dets():
            target = self.engine._targets.get(det.name)
            focus_name = self.engine.focus_target_name(det)
            focus_det = next(
                (d for d in self.state.units if d.name == focus_name), None
            )
            if target is None and focus_det is None:
                continue
            p0 = self._display_pos.get(det.name)
            if focus_det is not None:
                p1 = self._display_pos.get(focus_det.name)
                line_color = (255, 150, 90)
            else:
                p1 = self._project(target)
                line_color = (226, 190, 99)
            if p0 and p1:
                pygame.draw.line(screen, line_color, p0, p1, 1)
                pygame.draw.circle(screen, line_color,
                                   (int(p1[0]), int(p1[1])), 5, 1)
                if focus_det is not None:
                    pygame.draw.line(screen, line_color,
                                     (int(p1[0]) - 7, int(p1[1]) - 7),
                                     (int(p1[0]) + 7, int(p1[1]) + 7), 1)
                    pygame.draw.line(screen, line_color,
                                     (int(p1[0]) - 7, int(p1[1]) + 7),
                                     (int(p1[0]) + 7, int(p1[1]) - 7), 1)
        # Частицы под юнитами, чтобы трассеры не перекрывали подписи.
        for particle in self._particles:
            particle.draw(screen)
        ordered = sorted(
            [d for d in self.state.units if not getattr(d, "broken", False)],
            key=lambda d: self._display_pos.get(d.name, (0, 0))[1],
        )
        for det in ordered:
            self._draw_unit(screen, det)
        # Линия фронта — поверх жетонов: в плотном контакте под ними её
        # почти не видно, а пунктир не мешает читать подписи.
        self._draw_contact_lines(screen)
        if self._drag_rect is not None and self._drag_rect.width > 2:
            pygame.draw.rect(screen, (120, 190, 255), self._drag_rect, 1)
            fill = pygame.Surface(self._drag_rect.size, pygame.SRCALPHA)
            fill.fill((90, 160, 240, 35))
            screen.blit(fill, self._drag_rect.topleft)
        screen.set_clip(clip_before)
        self._draw_sector_status(screen)
        self._draw_map_legend(screen)
        self._draw_event_ticker(screen)
        if self._hover_idx is not None:
            self._draw_tooltip(screen, self._hover_idx)

    def _draw_plan_overlay(self, screen):
        """Показать рубеж или стрелу наступления на карте."""
        plan = self.engine.plan_for()
        if not plan.active:
            return
        overlay = pygame.Surface(MAP_RECT.size, pygame.SRCALPHA)

        def local(point):
            return (
                int(round(point[0] - MAP_RECT.x)),
                int(round(point[1] - MAP_RECT.y)),
            )

        color = ((232, 194, 98) if plan.mode == "hold"
                 else (92, 176, 242))
        if plan.mode == "hold" and plan.line is not None:
            first = local(self._project(plan.line[0]))
            second = local(self._project(plan.line[1]))
            dx = second[0] - first[0]
            dy = second[1] - first[1]
            length = max(0.01, math.hypot(dx, dy))
            ux, uy = dx / length, dy / length
            start = 0.0
            while start < length:
                end = min(length, start + 10.0)
                pygame.draw.line(
                    overlay, color + (190,),
                    (int(first[0] + ux * start),
                     int(first[1] + uy * start)),
                    (int(first[0] + ux * end),
                     int(first[1] + uy * end)),
                    3,
                )
                start += 17.0
            for point in (first, second):
                pygame.draw.circle(overlay, color + (220,), point, 5, 2)
            mid = (
                int((first[0] + second[0]) / 2),
                int((first[1] + second[1]) / 2),
            )
            label = "РУБЕЖ"
        else:
            units = self.engine._plan_units(
                getattr(self.state, "player_side", "red"),
                include_exempt=True,
            )
            center = self.engine._center_of(units)
            if center is None:
                return
            target = plan.target
            if target is None:
                target = (
                    center[0] + plan.axis[0] * 7.0,
                    center[1] + plan.axis[1] * 7.0,
                )
            first = local(self._project(center))
            second = local(self._project(target))
            dx = second[0] - first[0]
            dy = second[1] - first[1]
            length = max(0.01, math.hypot(dx, dy))
            ux, uy = dx / length, dy / length
            pygame.draw.line(overlay, color + (35,), first, second, 9)
            pygame.draw.line(overlay, color + (190,), first, second, 3)
            head = (int(second[0] - ux * 4), int(second[1] - uy * 4))
            left = (
                int(head[0] - ux * 12 - uy * 8),
                int(head[1] - uy * 12 + ux * 8),
            )
            right = (
                int(head[0] - ux * 12 + uy * 8),
                int(head[1] - uy * 12 - ux * 8),
            )
            pygame.draw.polygon(
                overlay, color + (220,), [second, left, right]
            )
            mid = (
                int((first[0] + second[0]) / 2),
                int((first[1] + second[1]) / 2),
            )
            label = "НАСТУПЛЕНИЕ"
        text = self.app.font_tiny.render(label, True, color)
        pad = pygame.Rect(
            mid[0] - text.get_width() // 2 - 4,
            mid[1] - text.get_height() // 2 - 2,
            text.get_width() + 8, text.get_height() + 4,
        )
        pygame.draw.rect(overlay, (12, 16, 22, 165), pad, border_radius=3)
        overlay.blit(
            text,
            (pad.x + 4, pad.y + 2),
        )
        screen.blit(overlay, MAP_RECT.topleft)

    def _contact_frontline_points(self):
        """Средние точки боёв: по ним рисуется линия соприкосновения."""
        points = []
        seen = set()
        for pair in getattr(self.engine, "engagements", []) or []:
            pa = self._display_pos.get(pair.get("attacker"))
            pb = self._display_pos.get(pair.get("defender"))
            if pa is None or pb is None:
                continue
            mid = ((pa[0] + pb[0]) * 0.5, (pa[1] + pb[1]) * 0.5)
            key = (round(mid[0] / 7.0), round(mid[1] / 7.0))
            if key in seen:
                continue
            seen.add(key)
            points.append(mid)
        points.sort(key=lambda p: (p[1], p[0]))
        return points

    def _draw_contact_lines(self, screen):
        """Показать фактическую линию соприкосновения сторон.

        Это не граница секторов и не приказ: линия строится только по
        реальным парам ``engine.engagements``, поэтому исчезает, когда бой
        прекращается. Тонкие связи между парами показывают, кто именно
        держит фронт, а пунктир — его общий контур.
        """
        points = self._contact_frontline_points()
        if not points:
            return
        overlay = pygame.Surface(MAP_RECT.size, pygame.SRCALPHA)

        def local(point):
            return (
                int(round(point[0] - MAP_RECT.x)),
                int(round(point[1] - MAP_RECT.y)),
            )

        # Слабые связи «атакующий — защитник» показывают, кто именно
        # образует фронт, и не дают линии превратиться в абстрактную черту.
        for pair in getattr(self.engine, "engagements", []) or []:
            pa = self._display_pos.get(pair.get("attacker"))
            pb = self._display_pos.get(pair.get("defender"))
            if pa is None or pb is None:
                continue
            pygame.draw.line(
                overlay, (255, 126, 74, 70),
                local(pa), local(pb), 1,
            )
        # Главная линия — прямая наилучшего приближения по средним точкам
        # боёв. В плотном фронте она читается лучше зигзага по отдельным
        # парам, а тики отмечают реальные места столкновений.
        if len(points) >= 2:
            mx = sum(p[0] for p in points) / len(points)
            my = sum(p[1] for p in points) / len(points)
            sxx = sum((p[0] - mx) ** 2 for p in points)
            syy = sum((p[1] - my) ** 2 for p in points)
            sxy = sum((p[0] - mx) * (p[1] - my) for p in points)
            theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
            ux, uy = math.cos(theta), math.sin(theta)
            projections = [
                (p[0] - mx) * ux + (p[1] - my) * uy for p in points
            ]
            lo, hi = min(projections), max(projections)
            if hi - lo >= 4.0:
                first = (mx + ux * lo, my + uy * lo)
                second = (mx + ux * hi, my + uy * hi)
                a, b = local(first), local(second)
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = max(0.01, math.hypot(dx, dy))
                ux, uy = dx / length, dy / length
                # Мягкое свечение и пунктир поверх жетонов.
                pygame.draw.line(
                    overlay, (255, 115, 70, 38), a, b, 7,
                )
                start = 0.0
                while start < length:
                    end = min(length, start + 9.0)
                    pygame.draw.line(
                        overlay, (255, 178, 110, 185),
                        (int(a[0] + ux * start), int(a[1] + uy * start)),
                        (int(a[0] + ux * end), int(a[1] + uy * end)),
                        2,
                    )
                    start += 15.0
        for point in points:
            x, y = local(point)
            pygame.draw.line(overlay, (255, 195, 128, 210),
                             (x - 4, y), (x + 4, y), 1)
            pygame.draw.line(overlay, (255, 195, 128, 210),
                             (x, y - 4), (x, y + 4), 1)
        screen.blit(overlay, MAP_RECT.topleft)

    def _draw_unit(self, screen, det):
        p = self._display_pos.get(det.name)
        if p is None:
            return
        x, y = int(p[0]), int(p[1])
        det_idx = self.state.units.index(det)
        selected = det_idx in self.selected
        is_target = det_idx == self._target_enemy
        is_player = det.side == getattr(self.state, "player_side", "red")
        color = DAY_COLORS["player"] if is_player else DAY_COLORS["enemy"]
        dark = DAY_COLORS["ally_dark"] if is_player else DAY_COLORS["enemy_dark"]
        # Тень и линия к реальной клетке, если жетон разведён от соседей.
        shadow = pygame.Rect(0, 0, 34, 12)
        shadow.center = (x, y + 7)
        pygame.draw.ellipse(screen, (8, 12, 14), shadow)
        true_pos = self._render_pos.get(det.name)
        if true_pos is not None:
            dx = true_pos[0] - x
            dy = true_pos[1] - y
            if abs(dx) + abs(dy) > 3.0:
                pygame.draw.line(screen, color,
                                 (int(true_pos[0]), int(true_pos[1])),
                                 (x, y), 1)
        if selected:
            pygame.draw.ellipse(screen, DAY_COLORS["gold"],
                                (x - 20, y - 12, 40, 24), 2)
            pygame.draw.ellipse(screen, (255, 220, 120),
                                (x - 16, y - 9, 32, 18), 1)
        if is_target:
            pygame.draw.ellipse(screen, (255, 145, 85),
                                (x - 21, y - 13, 42, 26), 2)
        # Жетон-плейсхолдер.
        body = pygame.Rect(x - 13, y - 16, 26, 20)
        pygame.draw.rect(screen, dark, body, border_radius=4)
        pygame.draw.rect(screen, color, body, 2, border_radius=4)
        pygame.draw.line(screen, color, (x - 7, y - 12), (x + 7, y - 2), 2)
        pygame.draw.line(screen, color, (x + 7, y - 12), (x - 7, y - 2), 2)
        if det.retreating or det.broken:
            pygame.draw.line(screen, (210, 210, 210), (x - 10, y - 14),
                             (x + 10, y - 4), 2)
        if is_target:
            pygame.draw.line(screen, (255, 145, 85),
                             (x - 9, y - 7), (x + 9, y - 7), 1)
        label_color = DAY_COLORS["text"] if is_player else (175, 205, 255)
        label = self.app.font_tiny.render(det.name, True, label_color)
        label_x = x - label.get_width() // 2
        label_y = y - 34
        screen.blit(label, (label_x, label_y))
        if is_player:
            # Небольшой золотой вымпел над своими: сторона читается даже
            # боковым зрением при плотном контакте.
            pygame.draw.polygon(
                screen, DAY_COLORS["gold"],
                [(label_x - 7, label_y + 1), (label_x - 3, label_y + 1),
                 (label_x - 5, label_y + 8)],
            )
        # Полосы: сила, мораль, удовлетворённость базовых потребностей.
        start = self.state._start_force(det)
        force_ratio = det.force / max(1.0, start)
        morale_ratio = det.morale / 100.0
        base_needs = det.needs_summary()
        comfort = 1.0 - sum(
            base_needs.get(n, 0.0) for n in
            ("hunger", "thirst", "fatigue", "health", "fear")
        ) / 5.0
        for j, (value, col) in enumerate((
            (force_ratio, DAY_COLORS["good"]),
            (morale_ratio, DAY_COLORS["accent"]),
            (comfort, DAY_COLORS["gold"]),
        )):
            bar = pygame.Rect(x - 16, y + 9 + j * 4, 32, 3)
            pygame.draw.rect(screen, (35, 40, 46), bar)
            pygame.draw.rect(
                screen, col,
                (bar.x, bar.y, int(max(0.0, min(1.0, value)) * bar.width),
                 bar.height),
            )

    def _draw_sector_status(self, screen):
        """Компактная сводка четырёх проекций: сила, нажим, прорыв."""
        geometry = getattr(self.state, "geometry", None)
        if geometry is None:
            return
        panel = pygame.Rect(LEFT_W + 18, 548, RIGHT_X - LEFT_W - 36, 50)
        bg = pygame.Surface(panel.size, pygame.SRCALPHA)
        bg.fill((8, 12, 18, 205))
        screen.blit(bg, panel.topleft)
        pygame.draw.rect(screen, DAY_COLORS["line"], panel, 1, border_radius=4)
        screen.blit(self.app.font_tiny.render(
            "ПРОЕКЦИИ · сила (вы/пр) · потери/сут",
            True, DAY_COLORS["muted"]),
            (panel.x + 8, panel.y + 2),
        )
        statuses = geometry.statuses()
        card_w = (panel.width - 16) // max(1, len(statuses))
        for i, status in enumerate(statuses):
            x = panel.x + 8 + i * card_w
            y = panel.y + 15
            color = (DAY_COLORS["bad"] if status.breached else
                     DAY_COLORS["warn"] if status.pressure else
                     DAY_COLORS["good"])
            label = self.app.font_tiny.render(
                status.label, True, color
            )
            screen.blit(label, (x, y))
            rate = geometry.sector_daily_rate(
                self.state.player_side, status.sector
            ) * 100.0
            rate_surf = self.app.font_tiny.render(
                "%.1f%%" % rate, True, DAY_COLORS["muted"]
            )
            screen.blit(
                rate_surf,
                (x + card_w - rate_surf.get_width() - 8, y),
            )
            ratio = status.ratio
            if ratio <= 0.0 and status.defender_force > 0:
                ratio = status.attacker_force / max(
                    1.0, status.defender_force
                )
            if status.sector == "rear":
                ratio_text = "тыл"
            elif status.breached:
                ratio_text = "ПРОРЫВ"
            elif status.pressure:
                ratio_text = "нажим %d/%d" % (
                    status.pressure, BREACH_PRESSURE_TICKS
                )
            else:
                ratio_text = "%.2f:1" % ratio
            force_text = self.app.font_tiny.render(
                "%.0f / %.0f  %s" % (
                    status.defender_force, status.attacker_force,
                    ratio_text,
                ),
                True, DAY_COLORS["text"],
            )
            screen.blit(force_text, (x, y + 15))

    def _draw_map_legend(self, screen):
        legend = pygame.Rect(LEFT_W + 18, 606, 520, 48)
        bg = pygame.Surface(legend.size, pygame.SRCALPHA)
        bg.fill((8, 12, 18, 190))
        screen.blit(bg, legend.topleft)
        pygame.draw.rect(screen, DAY_COLORS["line"], legend, 1, border_radius=4)
        side = getattr(self.state, "player_side", "red")
        enemy_side = "blue" if side == "red" else "red"
        pygame.draw.circle(screen, SIDE_COLORS.get(side, DAY_COLORS["player"]),
                           (legend.x + 18, legend.y + 16), 6)
        screen.blit(self.app.font_tiny.render(
            "ВЫ: %s" % SIDE_NAMES.get(side, side.upper()), True,
            DAY_COLORS["text"]), (legend.x + 30, legend.y + 8))
        pygame.draw.circle(screen, SIDE_COLORS.get(
            enemy_side, DAY_COLORS["enemy"]),
            (legend.x + 128, legend.y + 16), 6)
        screen.blit(self.app.font_tiny.render(
            "ПРОТИВНИК: %s" % SIDE_NAMES.get(
                enemy_side, enemy_side.upper()), True, DAY_COLORS["muted"]),
            (legend.x + 140, legend.y + 8))
        screen.blit(self.app.font_tiny.render(
            "ПКМ по врагу — огонь; клик — цель; F — огонь · "
            "оранжевая линия — фронт",
            True, DAY_COLORS["muted"]), (legend.x + 10, legend.y + 29))

    def _draw_event_ticker(self, screen):
        events = self.state.tick_events or self.state.event_log[-3:]
        if not events:
            return
        panel = pygame.Rect(LEFT_W + 18, 662, RIGHT_X - LEFT_W - 36, 44)
        bg = pygame.Surface(panel.size, pygame.SRCALPHA)
        bg.fill((8, 12, 18, 175))
        screen.blit(bg, panel.topleft)
        pygame.draw.rect(screen, DAY_COLORS["line"], panel, 1, border_radius=4)
        for i, event in enumerate(events[-3:]):
            text = str(event.get("message", "")).replace("↔", "<->")
            surf = self.app.font_tiny.render(
                "· " + text[:110], True,
                DAY_COLORS["text"] if i == len(events[-3:]) - 1
                else DAY_COLORS["muted"],
            )
            screen.blit(surf, (panel.x + 8, panel.y + 4 + i * 12))

    def _draw_right(self, screen):
        panel = pygame.Rect(RIGHT_X, TOP_H, RIGHT_W, HEIGHT - TOP_H)
        pygame.draw.rect(screen, DAY_COLORS["panel"], panel)
        pygame.draw.line(screen, DAY_COLORS["line"], (RIGHT_X, TOP_H),
                         (RIGHT_X, HEIGHT))
        screen.blit(self.app.font_small.render(
            "ВЫБРАННОЕ ПОДРАЗДЕЛЕНИЕ", True, DAY_COLORS["muted"]),
            (RIGHT_X + 12, 70))
        if not self.selected:
            draw_fitted(
                screen, [self.app.font_small, self.app.font_tiny],
                "Выберите подразделение на карте или в списке слева.",
                pygame.Rect(RIGHT_X + 12, 100, RIGHT_W - 24, 100),
                DAY_COLORS["muted"],
            )
            self._draw_supplies(screen, 220)
            self._draw_commander_panel(screen)
            return
        det = self.state.det_at(self.selected[0])
        if det is None:
            return
        y = 96
        screen.blit(self.app.font_body.render(
            det.name, True, DAY_COLORS["text"]), (RIGHT_X + 12, y))
        y += 28
        order_label = self.state.get_segment_label(self.selected[0], "order")
        sector = self.state.sector_of(det)
        projected = self.state.projected_force(det)
        geometry = getattr(self.state, "geometry", None)
        daily = (geometry.sector_daily_rate(det.side, sector) * 100.0
                 if geometry else 0.0)
        info = (
            "Сила %.1f / %.0f · проекция %.1f\n"
            "%s · %s · %.1f%%/сут"
        ) % (
            det.force, self.state._start_force(det), projected,
            SECTOR_LABELS.get(sector, sector), order_label, daily,
        )
        draw_fitted(
            screen, [self.app.font_tiny],
            info, pygame.Rect(RIGHT_X + 12, y, RIGHT_W - 24, 44),
            DAY_COLORS["muted"], spacing=1.05,
        )
        self._draw_needs(screen, det, 178)
        self._draw_supplies(screen, 376)
        self._draw_commander_panel(screen)

    def _draw_needs(self, screen, det, top):
        screen.blit(self.app.font_small.render(
            "ПОТРЕБНОСТИ · САМООБЕСПЕЧЕНИЕ", True,
            DAY_COLORS["muted"]), (RIGHT_X + 12, top - 20))
        needs = det.needs_summary()
        col_w = (RIGHT_W - 24) // 2
        row_h = 21
        for i, need in enumerate(NEED_ORDER):
            col = i // 8
            row = i % 8
            x = RIGHT_X + 12 + col * col_w
            y = top + row * row_h
            value = max(0.0, min(1.0, needs.get(need, 0.0)))
            label = self.app.font_tiny.render(
                NEED_SHORT[need], True, DAY_COLORS["muted"]
            )
            screen.blit(label, (x, y))
            bar = pygame.Rect(x + 49, y + 5, col_w - 76, 6)
            pygame.draw.rect(screen, (35, 42, 49), bar)
            color = (DAY_COLORS["good"] if value < 0.35 else
                     DAY_COLORS["warn"] if value < 0.65 else
                     DAY_COLORS["bad"])
            pygame.draw.rect(screen, color,
                             (bar.x, bar.y, int(bar.width * value),
                              bar.height))
            pct = self.app.font_tiny.render(
                "%d" % round(value * 100), True, color
            )
            screen.blit(pct, (bar.right + 4, y))

    def _draw_supplies(self, screen, top):
        screen.blit(self.app.font_small.render(
            "РЕСУРСЫ", True, DAY_COLORS["muted"]), (RIGHT_X + 12, top - 20))
        supplies = getattr(self.state, "supplies", {})
        logistics = getattr(self.state, "logistics", None)
        for i, (key, label) in enumerate(SUPPLY_LABELS.items()):
            x = RIGHT_X + 12 + (i % 2) * 130
            y = top + (i // 2) * 22
            text = "%s: %d" % (label, int(supplies.get(key, 0)))
            if key == "influence" and logistics is not None:
                text += " +%.0f/ч" % logistics.influence_per_hour
            surf = self.app.font_tiny.render(
                text, True, DAY_COLORS["text"],
            )
            screen.blit(surf, (x, y))

    def _draw_commander_panel(self, screen):
        """Личные потребности командира: без действий за подразделения."""
        screen.blit(self.app.font_small.render(
            "ВАШИ ПОТРЕБНОСТИ · КОМАНДИР", True, DAY_COLORS["muted"]),
            (RIGHT_X + 12, 458))
        pygame.draw.rect(screen, DAY_COLORS["panel2"],
                         self._commander_rect, border_radius=5)
        pygame.draw.rect(screen, DAY_COLORS["line"],
                         self._commander_rect, 1, border_radius=5)
        needs = self.state.needs.player_needs_summary()
        keys = ("hunger", "thirst", "fatigue", "fear", "anxiety", "health")
        for i, need in enumerate(keys):
            col = i // 3
            row = i % 3
            x = self._commander_rect.x + 8 + col * 124
            y = self._commander_rect.y + 8 + row * 23
            value = max(0.0, min(1.0, needs.get(need, 0.0)))
            screen.blit(self.app.font_tiny.render(
                NEED_SHORT.get(need, need), True, DAY_COLORS["muted"]),
                (x, y))
            bar = pygame.Rect(x + 48, y + 5, 46, 6)
            pygame.draw.rect(screen, (35, 42, 49), bar)
            color = (DAY_COLORS["good"] if value < 0.35 else
                     DAY_COLORS["warn"] if value < 0.65 else
                     DAY_COLORS["bad"])
            pygame.draw.rect(screen, color,
                             (bar.x, bar.y, int(bar.width * value),
                              bar.height))
            screen.blit(self.app.font_tiny.render(
                "%d" % round(value * 100), True, color),
                (bar.right + 3, y))
        morale = getattr(self.state.needs.commander, "morale", 0.0)
        screen.blit(self.app.font_tiny.render(
            "Мораль командира: %.0f" % morale,
            True, DAY_COLORS["text"]),
            (self._commander_rect.x + 8, self._commander_rect.y + 80))
        screen.blit(self.app.font_tiny.render(
            "Действия — «Нужды» (N). Подразделения",
            True, DAY_COLORS["muted"]),
            (self._commander_rect.x + 8, self._commander_rect.y + 100))
        screen.blit(self.app.font_tiny.render(
            "обеспечивают себя сами через логистику.",
            True, DAY_COLORS["muted"]),
            (self._commander_rect.x + 8, self._commander_rect.y + 113))
        target = self._target_enemy_det()
        target_text = ("Цель огня: %s" % target.name if target is not None
                       else "Цель не выбрана")
        screen.blit(self.app.font_tiny.render(
            target_text, True, (255, 170, 110) if target is not None
            else DAY_COLORS["muted"]),
            (self._commander_rect.x + 8, self._commander_rect.y + 138))
        screen.blit(self.app.font_tiny.render(
            "Нажмите, чтобы открыть личные нужды",
            True, DAY_COLORS["accent"]),
            (self._commander_rect.x + 8, self._commander_rect.y + 164))
        if self.state.needs.player_cooldowns:
            screen.blit(self.app.font_tiny.render(
                "часть действий на кулдауне", True, DAY_COLORS["warn"]),
                (self._commander_rect.x + 8, self._commander_rect.y + 185))

    def _draw_tooltip(self, screen, idx):
        det = self.state.det_at(idx)
        if det is None:
            return
        p = self._display_pos.get(det.name, (0, 0))
        side = getattr(self.state, "player_side", "red")
        side_text = "ВАШ" if det.side == side else "ПРОТИВНИК"
        sector = self.state.sector_of(det)
        lines = [
            det.name,
            side_text,
            "сила %.1f / %.0f · проекция %.1f" % (
                det.force, self.state._start_force(det),
                self.state.projected_force(det),
            ),
            "сектор: %s" % SECTOR_LABELS.get(sector, sector),
            "мораль %.0f" % det.morale,
            "приказ: %s" % self.state.get_segment_label(idx, "order"),
        ]
        width = max(
            self.app.font_tiny.size(line)[0] for line in lines
        ) + 20
        height = 14 * len(lines) + 12
        x = int(p[0]) + 24
        y = int(p[1]) - height - 12
        x = max(MAP_RECT.left + 4, min(x, RIGHT_X - width - 4))
        y = max(TOP_H + 4, y)
        rect = pygame.Rect(x, y, width, height)
        bg = pygame.Surface(rect.size, pygame.SRCALPHA)
        bg.fill((8, 12, 18, 225))
        screen.blit(bg, rect.topleft)
        pygame.draw.rect(screen, DAY_COLORS["line"], rect, 1, border_radius=4)
        for i, line in enumerate(lines):
            col = DAY_COLORS["text"] if i == 0 else DAY_COLORS["muted"]
            screen.blit(self.app.font_tiny.render(line, True, col),
                        (rect.x + 8, rect.y + 5 + i * 14))

    def _draw_feedback(self, screen):
        if not self._action_feedback or self._feedback_timer <= 0:
            return
        text = self._action_feedback[:110]
        font = self.app.font_small
        surf = font.render(text, True, DAY_COLORS["gold"])
        max_width = MAP_RECT.width - 48
        if surf.get_width() > max_width:
            font = self.app.font_tiny
            surf = font.render(text, True, DAY_COLORS["gold"])
        bg = pygame.Rect(0, 0, surf.get_width() + 24, 28)
        bg.center = (MAP_RECT.centerx, TOP_H + 22)
        bg.x = max(MAP_RECT.left + 4, min(bg.x, MAP_RECT.right - bg.width - 4))
        layer = pygame.Surface(bg.size, pygame.SRCALPHA)
        layer.fill((8, 12, 18, 205))
        screen.blit(layer, bg.topleft)
        pygame.draw.rect(screen, DAY_COLORS["line"], bg, 1, border_radius=4)
        screen.blit(surf, (bg.x + 12, bg.y + 6))
