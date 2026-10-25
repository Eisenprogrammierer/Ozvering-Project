"""Интерактивная 2-D изометрическая карта кампании (RTS-слой).

Экран заменяет прежний командный пункт. Он получает состояние из
``warfare.WarfareSimulation`` через ``CampaignEngine`` и показывает:

* изометрическую сетку 24×24 с плавно интерполированными иконками юнитов;
* выделение рамкой, приказы движения/атаки/обороны/отдыха;
* боевые частицы — трассеры, вспышки выстрелов и дуги ближнего боя;
* реальное время с паузой и множителем скорости (один такт = 30 минут);
* RPG-панель 16 потребностей выбранного подразделения и действия по их
  удовлетворению (довольствие, вода, отдых, медицина, воодушевление,
  общение);
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
from ..ui.text_layout import draw_fitted
from ..support.needs import ACTION_ORDER, NEED_ACTIONS, SUPPLY_LABELS
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
TICK_REAL_SECONDS = 1.8
DAY_COLORS = {
    "bg": (13, 18, 24),
    "panel": (17, 24, 32),
    "panel2": (21, 30, 40),
    "line": (48, 66, 82),
    "text": (222, 230, 236),
    "muted": (144, 158, 170),
    "accent": (86, 154, 226),
    "player": (72, 138, 224),
    "enemy": (211, 78, 78),
    "ally_dark": (36, 77, 130),
    "enemy_dark": (127, 46, 52),
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
        self.selected = []
        self.speed = 1
        self.paused = False
        self.finished = False
        self._tick_accum = 0.0
        self._render_pos = {}
        self._particles = []
        self._rng = random.Random(1701)
        self._drag_start = None
        self._drag_rect = None
        self._hover_idx = None
        self._action_feedback = ""
        self._feedback_timer = 0.0
        self._terrain = self._build_terrain()
        self._build_buttons()
        self._sync_render_positions(snap=True)
        player = self._player_indices()
        if player:
            self.selected = [player[0]]
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

    def _project(self, cell):
        gx, gy = float(cell[0]), float(cell[1])
        return (
            ISO_ORIGIN[0] + (gx - gy) * TILE_W / 2.0,
            ISO_ORIGIN[1] + (gx + gy) * TILE_H / 2.0,
        )

    def _unproject(self, pos):
        dx = float(pos[0]) - ISO_ORIGIN[0]
        dy = float(pos[1]) - ISO_ORIGIN[1]
        gx = (dx / (TILE_W / 2.0) + dy / (TILE_H / 2.0)) / 2.0
        gy = (dy / (TILE_H / 2.0) - dx / (TILE_W / 2.0)) / 2.0
        return gx, gy

    def _cell_from_mouse(self, pos):
        gx, gy = self._unproject(pos)
        return (
            max(0, min(GRID, int(round(gx)))),
            max(0, min(GRID, int(round(gy)))),
        )

    # --- кнопки ---------------------------------------------------------
    def _build_buttons(self):
        self.btn_pause = Button(
            (1102, 9, 94, 36), "Пауза", self.app.font_small, self.toggle_pause
        )
        self.btn_speed1 = Button(
            (1202, 9, 24, 36), "1x", self.app.font_tiny,
            lambda: self.set_speed(1)
        )
        self.btn_speed2 = Button(
            (1228, 9, 24, 36), "2x", self.app.font_tiny,
            lambda: self.set_speed(2)
        )
        self.btn_speed4 = Button(
            (1254, 9, 24, 36), "4x", self.app.font_tiny,
            lambda: self.set_speed(4)
        )
        # Кнопки скорости рисуются вручную, но Button даёт единый hover/click.
        self.btn_hold = Button(
            (12, 438, 208, 34), "Держать позиции", self.app.font_small,
            self.command_hold
        )
        self.btn_attack = Button(
            (12, 478, 208, 34), "Атака ближайшего", self.app.font_small,
            self.command_attack_nearest
        )
        self.btn_rest = Button(
            (12, 518, 208, 34), "Отдых", self.app.font_small,
            self.command_rest
        )
        self.btn_stop = Button(
            (12, 558, 208, 34), "Стоп / отойти", self.app.font_small,
            self.command_stop
        )
        self.btn_orders = Button(
            (12, 618, 100, 30), "Приказы", self.app.font_tiny,
            self.open_orders
        )
        self.btn_journal = Button(
            (120, 618, 100, 30), "Журнал", self.app.font_tiny,
            self.open_journal
        )
        self.btn_logistics = Button(
            (12, 652, 100, 30), "Логистика", self.app.font_tiny,
            self.open_logistics
        )
        self.btn_radio = Button(
            (120, 652, 100, 30), "Рация", self.app.font_tiny,
            self.open_radio
        )
        self._action_rects = {}
        for i, action_id in enumerate(ACTION_ORDER):
            col = i % 2
            row = i // 2
            self._action_rects[action_id] = pygame.Rect(
                RIGHT_X + 10 + col * 130, 508 + row * 35, 124, 30
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

    def _player_indices(self):
        return [
            i for i, det in enumerate(self.state.units)
            if det.side == getattr(self.state, "player_side", "red")
        ]

    def _unit_at(self, pos):
        """Индекс подразделения под курсором (или None)."""
        best = None
        best_y = -10**9
        for i, det in enumerate(self.state.units):
            p = self._render_pos.get(det.name)
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
        ]

    def _prune_selection(self):
        """Убрать из выделения уничтоженные/исчезнувшие подразделения."""
        valid = set(self._player_indices())
        self.selected = [i for i in self.selected if i in valid]

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
        count = 0
        for det in self._selected_dets():
            enemy = self._nearest_enemy(det)
            if enemy is None:
                continue
            idx = self.state.units.index(det)
            self.engine.assign_order(idx, "aggressive_attack")
            self.engine.set_cell_target(idx, enemy.position)
            det.ui_order = "aggressive_attack"
            count += 1
        self._feedback("Атака: %d" % count, 1.2)

    def _issue_ground(self, cell):
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine.assign_order(idx, "move")
            self.engine.set_cell_target(idx, cell)
        if self.selected:
            self._feedback("Движение в %d:%d" % cell, 1.0)

    def _issue_attack(self, enemy_idx):
        enemy = self.state.det_at(enemy_idx)
        for det in self._selected_dets():
            idx = self.state.units.index(det)
            self.engine.assign_order(idx, "aggressive_attack")
            self.engine.set_cell_target(idx, enemy.position)
            det.ui_order = "aggressive_attack"
        if enemy is not None:
            self._feedback("Цель: %s" % enemy.name, 1.4)

    def open_orders(self):
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
        self._particles = [p for p in self._particles if p.update(dt)]
        if self.paused or self.finished:
            return
        ts = getattr(self.app, "time_system", None)
        if ts is None:
            return
        if ts.pending_mandatory_scene is not None:
            return
        interval = TICK_REAL_SECONDS / max(1, self.speed)
        self._tick_accum += dt
        guard = 0
        while self._tick_accum >= interval and guard < 4:
            guard += 1
            self._tick_accum -= interval
            ts.advance(1800)
            self._after_tick()
            if (ts.pending_mandatory_scene is not None or
                    self.state.sim.finished or self.app.pending_storyline_outcome):
                break

    def _after_tick(self):
        if self.state.sim.finished:
            self.finished = True
            self.paused = True
            self._feedback("Операция завершена", 4.0)
        self._spawn_battle_particles()
        if self.state.tick_events:
            self._feedback(self.state.tick_events[-1].get("message", ""), 3.0)

    def _spawn_battle_particles(self):
        for pair in getattr(self.engine, "engagements", []):
            a = next((d for d in self.state.units
                      if d.name == pair.get("attacker")), None)
            b = next((d for d in self.state.units
                      if d.name == pair.get("defender")), None)
            if a is None or b is None:
                continue
            pa = self._render_pos.get(a.name)
            pb = self._render_pos.get(b.name)
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

    def _sync_render_positions(self, dt=0.0, snap=False):
        for det in self.state.units:
            target = self._project(det.position)
            if det.name not in self._render_pos or snap:
                self._render_pos[det.name] = target
                continue
            x, y = self._render_pos[det.name]
            dx = target[0] - x
            dy = target[1] - y
            if abs(dx) + abs(dy) > 220:
                self._render_pos[det.name] = target
            else:
                k = min(1.0, max(0.0, dt * 9.0))
                self._render_pos[det.name] = (x + dx * k, y + dy * k)

    # --- события --------------------------------------------------------
    def handle_event(self, event):
        for b in (
            self.btn_pause, self.btn_speed1, self.btn_speed2,
            self.btn_speed4, self.btn_hold, self.btn_attack, self.btn_rest,
            self.btn_stop, self.btn_orders, self.btn_journal,
            self.btn_logistics, self.btn_radio,
        ):
            if b.handle_event(event):
                return
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_SPACE, pygame.K_p):
                self.toggle_pause()
            elif event.key == pygame.K_1:
                self.set_speed(1)
            elif event.key == pygame.K_2:
                self.set_speed(2)
            elif event.key in (pygame.K_3, pygame.K_4):
                self.set_speed(4)
            elif event.key == pygame.K_h:
                self.command_hold()
            elif event.key == pygame.K_r:
                self.command_rest()
            elif event.key == pygame.K_a:
                self.command_attack_nearest()
            elif event.key == pygame.K_s:
                self.command_stop()
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
                if self._handle_ui_click(event.pos):
                    return
                hit = self._unit_at(event.pos)
                if hit is not None:
                    if hit in self._player_indices():
                        if getattr(event, "mod", 0) & pygame.KMOD_SHIFT:
                            if hit in self.selected:
                                self.selected.remove(hit)
                            else:
                                self.selected.append(hit)
                        else:
                            self.selected = [hit]
                    else:
                        self.selected = []
                    return
                if MAP_RECT.collidepoint(event.pos):
                    self._drag_start = event.pos
                    self._drag_rect = pygame.Rect(event.pos, (0, 0))
            elif event.button == 3 and MAP_RECT.collidepoint(event.pos):
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
                    p = self._render_pos.get(self.state.units[i].name)
                    if p and rect.collidepoint(p):
                        chosen.append(i)
                if chosen:
                    self.selected = chosen
                else:
                    self.selected = []
            return

    def _handle_ui_click(self, pos):
        """Клик по списку юнитов и кнопкам действий потребностей."""
        # Список подразделений.
        for row, idx in enumerate(self._player_indices()):
            rect = pygame.Rect(12, 94 + row * 40, 208, 36)
            if rect.collidepoint(pos):
                self.selected = [idx]
                return True
        # Действия потребностей.
        if not self.selected:
            return False
        idx = self.selected[0]
        for action_id, rect in self._action_rects.items():
            if rect.collidepoint(pos):
                result = self.state.needs.apply(idx, action_id)
                if result.get("ok"):
                    self._feedback(
                        NEED_ACTIONS[action_id]["label"] + ": выполнено", 1.5
                    )
                else:
                    self._feedback(result.get("reason", "Недоступно"), 1.5)
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
        # Кнопки скорости рисуются вручную, чтобы уместить 4 режима.
        self.btn_pause.draw(screen)
        for x, label, value in (
            (1202, "1x", 1), (1228, "2x", 2), (1254, "4x", 4),
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
        self.btn_speed1.rect = pygame.Rect(1202, 9, 24, 36)
        self.btn_speed2.rect = pygame.Rect(1228, 9, 24, 36)
        self.btn_speed4.rect = pygame.Rect(1254, 9, 24, 36)

    def _draw_left(self, screen):
        panel = pygame.Rect(0, TOP_H, LEFT_W, HEIGHT - TOP_H)
        pygame.draw.rect(screen, DAY_COLORS["panel"], panel)
        pygame.draw.line(screen, DAY_COLORS["line"],
                         (LEFT_W - 1, TOP_H), (LEFT_W - 1, HEIGHT))
        screen.blit(self.app.font_small.render(
            "ПОДРАЗДЕЛЕНИЯ", True, DAY_COLORS["muted"]), (14, 70)
        )
        for row, idx in enumerate(self._player_indices()):
            det = self.state.det_at(idx)
            if det is None:
                continue
            rect = pygame.Rect(12, 94 + row * 40, 208, 36)
            selected = idx in self.selected
            pygame.draw.rect(
                screen,
                DAY_COLORS["ally_dark"] if selected else DAY_COLORS["panel2"],
                rect, border_radius=5,
            )
            pygame.draw.rect(
                screen,
                DAY_COLORS["accent"] if selected else DAY_COLORS["line"],
                rect, 1, border_radius=5,
            )
            name = self.app.font_small.render(
                det.name, True, DAY_COLORS["text"]
            )
            screen.blit(name, (rect.x + 8, rect.y + 3))
            ratio = det.force / max(1.0, self.state._start_force(det))
            bar = pygame.Rect(rect.x + 8, rect.y + 22, 130, 5)
            pygame.draw.rect(screen, (40, 46, 54), bar)
            pygame.draw.rect(screen, DAY_COLORS["good"],
                             (bar.x, bar.y, int(bar.width * ratio), bar.height))
            mini = self.app.font_tiny.render(
                "%d" % round(det.force), True, DAY_COLORS["muted"]
            )
            screen.blit(mini, (rect.right - 30, rect.y + 18))
        screen.blit(self.app.font_small.render(
            "ПРИКАЗЫ", True, DAY_COLORS["muted"]), (14, 414)
        )
        for b in (self.btn_hold, self.btn_attack, self.btn_rest, self.btn_stop):
            b.draw(screen)
        screen.blit(self.app.font_small.render(
            "ШТАБ", True, DAY_COLORS["muted"]), (14, 596)
        )
        for b in (self.btn_orders, self.btn_journal, self.btn_logistics,
                  self.btn_radio):
            b.draw(screen)
        hint = self.app.font_tiny.render(
            "ПКМ — движение/атака\nЛКМ — выбор, рамка",
            True, DAY_COLORS["muted"],
        )
        screen.blit(hint, (14, 688))

    def _draw_map(self, screen):
        screen.blit(self._terrain, MAP_RECT.topleft, MAP_RECT)
        pygame.draw.rect(screen, DAY_COLORS["line"], MAP_RECT, 1)
        clip_before = screen.get_clip()
        screen.set_clip(MAP_RECT)
        # Линии приказов выбранных юнитов.
        for det in self._selected_dets():
            target = self.engine._targets.get(det.name)
            if target is None:
                continue
            p0 = self._render_pos.get(det.name)
            p1 = self._project(target)
            if p0 and p1:
                pygame.draw.line(screen, (226, 190, 99), p0, p1, 1)
                pygame.draw.circle(screen, (226, 190, 99),
                                   (int(p1[0]), int(p1[1])), 4, 1)
        # Частицы под юнитами, чтобы трассеры не перекрывали подписи.
        for particle in self._particles:
            particle.draw(screen)
        ordered = sorted(
            self.state.units,
            key=lambda d: self._render_pos.get(d.name, (0, 0))[1],
        )
        for det in ordered:
            self._draw_unit(screen, det)
        if self._drag_rect is not None and self._drag_rect.width > 2:
            pygame.draw.rect(screen, (120, 190, 255), self._drag_rect, 1)
            fill = pygame.Surface(self._drag_rect.size, pygame.SRCALPHA)
            fill.fill((90, 160, 240, 35))
            screen.blit(fill, self._drag_rect.topleft)
        screen.set_clip(clip_before)
        self._draw_map_legend(screen)
        self._draw_event_ticker(screen)
        if self._hover_idx is not None:
            self._draw_tooltip(screen, self._hover_idx)

    def _draw_unit(self, screen, det):
        p = self._render_pos.get(det.name)
        if p is None:
            return
        x, y = int(p[0]), int(p[1])
        selected = self.state.units.index(det) in self.selected
        is_player = det.side == getattr(self.state, "player_side", "red")
        color = DAY_COLORS["player"] if is_player else DAY_COLORS["enemy"]
        dark = DAY_COLORS["ally_dark"] if is_player else DAY_COLORS["enemy_dark"]
        # Тень.
        shadow = pygame.Rect(0, 0, 34, 12)
        shadow.center = (x, y + 7)
        pygame.draw.ellipse(screen, (8, 12, 14), shadow)
        if selected:
            pygame.draw.ellipse(screen, DAY_COLORS["gold"],
                                (x - 20, y - 12, 40, 24), 2)
            pygame.draw.ellipse(screen, (255, 220, 120),
                                (x - 16, y - 9, 32, 18), 1)
        # Жетон-плейсхолдер.
        body = pygame.Rect(x - 13, y - 16, 26, 20)
        pygame.draw.rect(screen, dark, body, border_radius=4)
        pygame.draw.rect(screen, color, body, 2, border_radius=4)
        pygame.draw.line(screen, color, (x - 7, y - 12), (x + 7, y - 2), 2)
        pygame.draw.line(screen, color, (x + 7, y - 12), (x - 7, y - 2), 2)
        if det.retreating or det.broken:
            pygame.draw.line(screen, (210, 210, 210), (x - 10, y - 14),
                             (x + 10, y - 4), 2)
        label_color = DAY_COLORS["text"] if is_player else (255, 194, 194)
        label = self.app.font_tiny.render(det.name, True, label_color)
        screen.blit(label, (x - label.get_width() // 2, y - 34))
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

    def _draw_map_legend(self, screen):
        legend = pygame.Rect(LEFT_W + 18, 606, 520, 48)
        bg = pygame.Surface(legend.size, pygame.SRCALPHA)
        bg.fill((8, 12, 18, 190))
        screen.blit(bg, legend.topleft)
        pygame.draw.rect(screen, DAY_COLORS["line"], legend, 1, border_radius=4)
        pygame.draw.circle(screen, DAY_COLORS["player"],
                           (legend.x + 18, legend.y + 16), 6)
        screen.blit(self.app.font_tiny.render(
            "ваши войска", True, DAY_COLORS["muted"]),
            (legend.x + 30, legend.y + 8))
        pygame.draw.circle(screen, DAY_COLORS["enemy"],
                           (legend.x + 128, legend.y + 16), 6)
        screen.blit(self.app.font_tiny.render(
            "противник", True, DAY_COLORS["muted"]),
            (legend.x + 140, legend.y + 8))
        screen.blit(self.app.font_tiny.render(
            "ПКМ по земле — идти; ПКМ по врагу — атака; ESC — пауза",
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
            return
        det = self.state.det_at(self.selected[0])
        if det is None:
            return
        y = 96
        screen.blit(self.app.font_body.render(
            det.name, True, DAY_COLORS["text"]), (RIGHT_X + 12, y))
        y += 28
        order_label = self.state.get_segment_label(self.selected[0], "order")
        in_combat = any(
            det.name in (pair.get("attacker"), pair.get("defender"))
            for pair in getattr(self.engine, "engagements", [])
        )
        info = (
            "Сила %.0f · мораль %.0f · дисциплина %.0f%%\n"
            "Приказ: %s · %s"
        ) % (
            det.force, det.morale, det.discipline * 100,
            order_label, "в бою" if in_combat else "вне боя",
        )
        draw_fitted(
            screen, [self.app.font_tiny],
            info, pygame.Rect(RIGHT_X + 12, y, RIGHT_W - 24, 44),
            DAY_COLORS["muted"], spacing=1.05,
        )
        self._draw_needs(screen, det, 178)
        self._draw_supplies(screen, 376)
        self._draw_actions(screen, det)

    def _draw_needs(self, screen, det, top):
        screen.blit(self.app.font_small.render(
            "ПОТРЕБНОСТИ (неудовлетворённость)", True,
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
        for i, (key, label) in enumerate(SUPPLY_LABELS.items()):
            x = RIGHT_X + 12 + (i % 2) * 130
            y = top + (i // 2) * 22
            surf = self.app.font_tiny.render(
                "%s: %d" % (label, int(supplies.get(key, 0))),
                True, DAY_COLORS["text"],
            )
            screen.blit(surf, (x, y))

    def _draw_actions(self, screen, det):
        screen.blit(self.app.font_small.render(
            "ДЕЙСТВИЯ", True, DAY_COLORS["muted"]), (RIGHT_X + 12, 482))
        status = self.state.needs.status(self.selected[0])
        for action_id in ACTION_ORDER:
            rect = self._action_rects[action_id]
            state = status.get(action_id, {})
            enabled = bool(state.get("ok"))
            bg = DAY_COLORS["panel2"] if enabled else (27, 31, 36)
            pygame.draw.rect(screen, bg, rect, border_radius=4)
            pygame.draw.rect(
                screen, DAY_COLORS["line"] if enabled else (44, 48, 54),
                rect, 1, border_radius=4,
            )
            label = NEED_ACTIONS[action_id]["short"]
            surf = self.app.font_tiny.render(
                label, True,
                DAY_COLORS["text"] if enabled else (100, 108, 116),
            )
            screen.blit(surf, (rect.x + 6, rect.y + 3))
            if not enabled:
                reason = state.get("reason", "")
                if reason:
                    tiny = self.app.font_tiny.render(
                        reason[:18], True, (130, 102, 102)
                    )
                    screen.blit(tiny, (rect.x + 6, rect.y + 15))
            cost = NEED_ACTIONS[action_id].get("cost", {})
            if enabled and cost:
                cost_text = ", ".join(
                    "%s:%d" % (SUPPLY_LABELS.get(k, k)[:3], v)
                    for k, v in cost.items()
                )
                cost_surf = self.app.font_tiny.render(
                    cost_text, True, DAY_COLORS["muted"]
                )
                screen.blit(cost_surf, (rect.right - cost_surf.get_width() - 4,
                                        rect.y + 15))

    def _draw_tooltip(self, screen, idx):
        det = self.state.det_at(idx)
        if det is None:
            return
        p = self._render_pos.get(det.name, (0, 0))
        lines = [
            det.name,
            "сила %.0f / %0.f" % (det.force, self.state._start_force(det)),
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
