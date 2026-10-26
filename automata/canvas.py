"""Холст редактора: узлы, рёбра, камера, выбор и создание переходов.

Холст не знает о сценах и истории: он меняет переданную модель и сообщает
сцене о действиях через колбэки. Благодаря этому геометрию и ввод можно
тестировать отдельно от окна и инспектора.
"""

from __future__ import annotations

import math
import time

import pygame

from ui import theme

from . import ui
from .model import AutomatonError

NODE_W = 172
NODE_H = 72
GRID = 24
SNAP = 8
MIN_ZOOM = 0.35
MAX_ZOOM = 2.2


def _distance_to_segment(point, a, b):
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / float(dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _bezier(p0, p1, p2, p3, steps=26):
    points = []
    for i in range(steps + 1):
        t = i / float(steps)
        u = 1.0 - t
        x = (u ** 3) * p0[0] + 3 * (u ** 2) * t * p1[0] \
            + 3 * u * (t ** 2) * p2[0] + (t ** 3) * p3[0]
        y = (u ** 3) * p0[1] + 3 * (u ** 2) * t * p1[1] \
            + 3 * u * (t ** 2) * p2[1] + (t ** 3) * p3[1]
        points.append((x, y))
    return points


def _ellipsis(font, text, width):
    text = str(text)
    if width <= 0:
        return ""
    if font.size(text)[0] <= width:
        return text
    cut = text
    while cut and font.size(cut + "…")[0] > width:
        cut = cut[:-1]
    return (cut + "…") if cut else "…"


class AutomatonCanvas:
    """Интерактивный холст одного автомата."""

    def __init__(self, automaton, on_select=None, on_change=None,
                 on_status=None):
        self.automaton = automaton
        self.on_select = on_select
        self.on_change = on_change
        self.on_status = on_status
        self.rect = pygame.Rect(0, 0, 1, 1)
        self.origin = pygame.Vector2(80, 80)
        self.zoom = 1.0
        self.grid = True
        self.selected_kind = None
        self.selected_id = None
        self.hover_kind = None
        self.hover_id = None
        self.connect_mode = False
        self.pending_source = None
        self._mode = None
        self._pan_last = None
        self._drag_state = None
        self._drag_start = None
        self._drag_origin = None
        self._drag_moved = False
        self._last_click = (0.0, (0, 0))
        self._did_fit = False

    # --- геометрия ------------------------------------------------------
    def set_rect(self, rect, fit=False):
        self.rect = pygame.Rect(rect)
        if fit or not self._did_fit:
            self.fit()
            self._did_fit = True

    def to_screen(self, x, y):
        return pygame.Vector2(
            self.rect.left + self.origin.x + float(x) * self.zoom,
            self.rect.top + self.origin.y + float(y) * self.zoom,
        )

    def to_world(self, pos):
        return ((pos[0] - self.rect.left - self.origin.x) / self.zoom,
                (pos[1] - self.rect.top - self.origin.y) / self.zoom)

    def node_rect(self, state):
        point = self.to_screen(state.x, state.y)
        return pygame.Rect(
            int(round(point.x)), int(round(point.y)),
            max(14, int(round(NODE_W * self.zoom))),
            max(14, int(round(NODE_H * self.zoom))),
        )

    def fit(self):
        if not self.automaton.states:
            self.zoom = 1.0
            self.origin.update(
                self.rect.width / 2 - NODE_W / 2,
                self.rect.height / 2 - NODE_H / 2)
            return
        bounds = self.automaton.bounds()
        min_x, min_y, max_x, max_y = bounds
        width = (max_x - min_x) + NODE_W
        height = (max_y - min_y) + NODE_H
        available_w = max(120, self.rect.width - 120)
        available_h = max(100, self.rect.height - 120)
        self.zoom = max(MIN_ZOOM, min(
            1.2, available_w / float(width), available_h / float(height)))
        self.origin.update(
            (self.rect.width - width * self.zoom) / 2 - min_x * self.zoom,
            (self.rect.height - height * self.zoom) / 2 - min_y * self.zoom,
        )

    def zoom_at(self, screen_pos, factor):
        world = self.to_world(screen_pos)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        self.origin.update(
            screen_pos[0] - self.rect.left - world[0] * self.zoom,
            screen_pos[1] - self.rect.top - world[1] * self.zoom,
        )
        self._status("Масштаб %d%%" % round(self.zoom * 100))

    # --- выбор ----------------------------------------------------------
    def select(self, kind, item_id):
        if (kind, item_id) != (self.selected_kind, self.selected_id):
            self.selected_kind, self.selected_id = kind, item_id
            if self.on_select is not None:
                self.on_select(kind, item_id)

    def selected_state(self):
        if self.selected_kind == "state":
            return self.automaton.state(self.selected_id)
        return None

    def selected_transition(self):
        if self.selected_kind == "transition":
            return self.automaton.transition(self.selected_id)
        return None

    def _status(self, message):
        if self.on_status is not None:
            self.on_status(message)

    def _changed(self, message, commit=True):
        if self.on_change is not None:
            self.on_change(message, commit)

    # --- операции -------------------------------------------------------
    def set_connect_mode(self, active):
        self.connect_mode = bool(active)
        self.pending_source = None
        self._status(
            "Режим связи: кликните исходное, затем целевое состояние"
            if self.connect_mode else "Режим связи выключен")
        if self.on_select is not None:
            self.on_select(self.selected_kind, self.selected_id)

    def add_state_at(self, screen_pos=None):
        if screen_pos is None:
            screen_pos = self.rect.center
        world = self.to_world(screen_pos)
        x = int(round((world[0] - NODE_W / 2) / SNAP) * SNAP)
        y = int(round((world[1] - NODE_H / 2) / SNAP) * SNAP)
        # Не ставим новый узел поверх существующего (проверяем весь прямоугольник).
        new_rect = pygame.Rect(
            int(round(self.rect.left + self.origin.x + x * self.zoom)),
            int(round(self.rect.top + self.origin.y + y * self.zoom)),
            max(14, int(round(NODE_W * self.zoom))),
            max(14, int(round(NODE_H * self.zoom))),
        )
        while any(self.node_rect(state).colliderect(new_rect)
                  for state in self.automaton.states):
            x += SNAP * 3
            y += SNAP * 3
            new_rect.move_ip(round(SNAP * 3 * self.zoom),
                             round(SNAP * 3 * self.zoom))
        name = "Состояние %d" % (len(self.automaton.states) + 1)
        state = self.automaton.add_state(
            name=name, x=x, y=y, initial=not self.automaton.states)
        self.select("state", state.id)
        self._changed("Добавлено состояние %s" % state.id)
        return state

    def delete_selected(self):
        if self.selected_kind == "state":
            state = self.automaton.state(self.selected_id)
            if state is None:
                return False
            self.automaton.remove_state(state.id)
            if self.pending_source == state.id:
                self.pending_source = None
            self.select(None, None)
            self._changed("Удалено состояние %s" % state.id)
            return True
        if self.selected_kind == "transition":
            transition = self.automaton.transition(self.selected_id)
            if transition is None:
                return False
            self.automaton.remove_transition(transition.id)
            self.select(None, None)
            self._changed("Удалён переход %s" % transition.id)
            return True
        return False

    def _create_transition(self, source_id, target_id):
        try:
            transition = self.automaton.add_transition(source_id, target_id)
        except AutomatonError as exc:
            self._status(str(exc))
            return None
        self.select("transition", transition.id)
        self._changed("Добавлен переход %s → %s" % (source_id, target_id))
        return transition

    # --- попадания ------------------------------------------------------
    def _hit_node(self, pos):
        for state in reversed(self.automaton.states):
            if self.node_rect(state).collidepoint(pos):
                return state
        return None

    def _edge_geometry(self, transition):
        """Вернуть (points, label_pos) в экранных координатах."""
        source = self.automaton.state(transition.source)
        target = self.automaton.state(transition.target)
        if source is None or target is None:
            return ([], None)
        if source.id == target.id:
            rect = self.node_rect(source)
            loops = [t for t in self.automaton.transitions
                     if t.source == source.id and t.target == source.id]
            index = loops.index(transition) if transition in loops else 0
            scale = max(0.5, min(1.6, self.zoom))
            height = (74 + index * 30) * scale
            spread = 72 * scale
            inset = 20 * scale
            cx = rect.centerx
            top = rect.top + 4
            p0 = (cx - inset, top)
            p1 = (cx - spread, top - height)
            p2 = (cx + spread, top - height)
            p3 = (cx + inset, top)
            points = _bezier(p0, p1, p2, p3)
            return points, (cx, top - height - 12)

        key = tuple(sorted((source.id, target.id)))
        group = [t for t in self.automaton.transitions
                 if tuple(sorted((t.source, t.target))) == key]
        index = group.index(transition) if transition in group else 0
        offset = (index - (len(group) - 1) / 2.0) * 22.0

        r1 = self.node_rect(source)
        r2 = self.node_rect(target)
        c1 = pygame.Vector2(r1.center)
        c2 = pygame.Vector2(r2.center)
        direction = c2 - c1
        if direction.length_squared() == 0:
            direction = pygame.Vector2(1, 0)
        normal = pygame.Vector2(-direction.y, direction.x).normalize()
        c1 += normal * offset
        c2 += normal * offset

        start = c1
        end = c2
        hit_target = r2.clipline(c1, c2)
        if hit_target:
            candidates = [pygame.Vector2(hit_target[0]),
                          pygame.Vector2(hit_target[1])]
            candidates.sort(key=lambda p: (p - c1).length_squared())
            end = candidates[0]
        hit_source = r1.clipline(c1, end)
        if hit_source:
            candidates = [pygame.Vector2(hit_source[0]),
                          pygame.Vector2(hit_source[1])]
            candidates.sort(key=lambda p: (p - end).length_squared())
            start = candidates[0]

        midpoint = (start + end) / 2.0
        if len(group) > 1:
            # Разносим подписи вдоль ребра. Для обратного перехода берём
            # зеркальную долю, чтобы пара подписей не сходилась в центре.
            fraction = 0.28 + 0.44 * (index / float(len(group) - 1))
            if transition.source != key[0]:
                fraction = 1.0 - fraction
            midpoint = start + (end - start) * fraction
        return [(start.x, start.y), (end.x, end.y)], (midpoint.x, midpoint.y)

    def _hit_edge(self, pos):
        best = None
        best_distance = 9.0
        for transition in self.automaton.transitions:
            points, _label = self._edge_geometry(transition)
            for index in range(len(points) - 1):
                distance = _distance_to_segment(
                    pos, points[index], points[index + 1])
                if distance < best_distance:
                    best_distance = distance
                    best = transition
        return best

    # --- события --------------------------------------------------------
    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            if not self.rect.collidepoint(pygame.mouse.get_pos()):
                return False
            factor = 1.14 ** event.y
            self.zoom_at(pygame.mouse.get_pos(), factor)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN:
            if not self.rect.collidepoint(event.pos):
                return False
            if event.button in (2, 3):
                self._mode = "pan"
                self._pan_last = event.pos
                return True
            if event.button == 1:
                return self._mouse_down(event.pos)
            return False
        if event.type == pygame.MOUSEMOTION:
            return self._mouse_motion(event)
        if event.type == pygame.MOUSEBUTTONUP:
            if event.button in (2, 3) and self._mode == "pan":
                self._mode = None
                self._pan_last = None
                return True
            if event.button == 1 and self._mode == "node":
                self._mode = None
                state = self._drag_state
                moved = self._drag_moved
                self._drag_state = None
                self._drag_start = None
                self._drag_origin = None
                self._drag_moved = False
                if moved and state is not None:
                    self._changed("Перемещено состояние %s" % state, True)
                return True
            return False
        if event.type == pygame.KEYDOWN:
            return self._key_down(event)
        return False

    def _mouse_down(self, pos):
        now = time.monotonic()
        last_time, last_pos = self._last_click
        double = (now - last_time < 0.32
                  and abs(pos[0] - last_pos[0]) < 6
                  and abs(pos[1] - last_pos[1]) < 6)
        self._last_click = (now, pos)

        state = self._hit_node(pos)
        if self.connect_mode:
            if state is None:
                self.pending_source = None
                self._status("Режим связи: выберите исходное состояние")
                return True
            if self.pending_source is None:
                self.pending_source = state.id
                self.select("state", state.id)
                self._status("Источник: %s — выберите целевое состояние"
                             % state.id)
                return True
            source = self.pending_source
            self.pending_source = None
            self._create_transition(source, state.id)
            return True

        if double and state is None:
            self.add_state_at(pos)
            return True
        if state is not None:
            self.select("state", state.id)
            self._mode = "node"
            self._drag_state = state.id
            self._drag_start = pos
            self._drag_origin = (state.x, state.y)
            self._drag_moved = False
            return True
        transition = self._hit_edge(pos)
        if transition is not None:
            self.select("transition", transition.id)
            return True
        self.select(None, None)
        return True

    def _mouse_motion(self, event):
        if self._mode == "pan" and self._pan_last is not None:
            dx = event.pos[0] - self._pan_last[0]
            dy = event.pos[1] - self._pan_last[1]
            self.origin.x += dx
            self.origin.y += dy
            self._pan_last = event.pos
            return True
        if self._mode == "node" and self._drag_state is not None:
            dx = (event.pos[0] - self._drag_start[0]) / self.zoom
            dy = (event.pos[1] - self._drag_start[1]) / self.zoom
            x = self._drag_origin[0] + dx
            y = self._drag_origin[1] + dy
            state = self.automaton.state(self._drag_state)
            if state is not None:
                self.automaton.move_state(
                    state.id,
                    int(round(x / SNAP) * SNAP),
                    int(round(y / SNAP) * SNAP))
                self._drag_moved = True
                self._changed("Перемещение…", False)
            return True
        if not self.rect.collidepoint(event.pos):
            self.hover_kind = None
            self.hover_id = None
            return False
        state = self._hit_node(event.pos)
        if state is not None:
            self.hover_kind, self.hover_id = "state", state.id
            return False
        transition = self._hit_edge(event.pos)
        if transition is not None:
            self.hover_kind, self.hover_id = "transition", transition.id
            return False
        self.hover_kind = self.hover_id = None
        return False

    def _key_down(self, event):
        key = event.key
        if key == pygame.K_ESCAPE:
            if self.connect_mode or self.pending_source:
                self.connect_mode = False
                self.pending_source = None
                self._status("Режим связи выключен")
                if self.on_select is not None:
                    self.on_select(self.selected_kind, self.selected_id)
                return True
            if self.selected_kind is not None:
                self.select(None, None)
                return True
            return False
        if key in (pygame.K_DELETE, pygame.K_BACKSPACE):
            return self.delete_selected()
        if key == pygame.K_f:
            self.fit()
            self._status("Автомат вписан в окно")
            return True
        if key == pygame.K_g:
            self.grid = not self.grid
            self._status("Сетка %s" % ("включена" if self.grid else "выключена"))
            return True
        if key in (pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.zoom_at(self.rect.center, 1.14)
            return True
        if key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.zoom_at(self.rect.center, 1 / 1.14)
            return True
        if key in (pygame.K_LEFT, pygame.K_RIGHT,
                   pygame.K_UP, pygame.K_DOWN):
            state = self.selected_state()
            if state is None:
                return False
            step = 10 if event.mod & pygame.KMOD_SHIFT else 1
            dx = (-step if key == pygame.K_LEFT
                  else step if key == pygame.K_RIGHT else 0)
            dy = (-step if key == pygame.K_UP
                  else step if key == pygame.K_DOWN else 0)
            self.automaton.move_state(state.id, state.x + dx, state.y + dy)
            self._changed("Перемещено состояние %s" % state.id, True)
            return True
        return False

    # --- отрисовка ------------------------------------------------------
    def draw(self, screen, fonts):
        pygame.draw.rect(screen, ui.CANVAS_BG, self.rect)
        if self.grid:
            self._draw_grid(screen)
        if not self.automaton.states:
            ui.draw_empty(
                screen, fonts, self.rect.inflate(-80, -80),
                "Пустой холст",
                "Добавьте состояние кнопкой «+ Состояние» или двойным кликом")
            return
        for transition in self.automaton.transitions:
            self._draw_edge(screen, fonts, transition)
        for state in self.automaton.states:
            self._draw_node(screen, fonts, state)

    def _draw_grid(self, screen):
        spacing = GRID * self.zoom
        while spacing < 10:
            spacing *= 2
        offset_x = (self.rect.left + self.origin.x) % spacing
        offset_y = (self.rect.top + self.origin.y) % spacing
        x = self.rect.left + offset_x
        index_x = int((self.rect.left + self.origin.x) / spacing)
        while x < self.rect.right:
            color = ui.GRID_MAJOR if index_x % 5 == 0 else ui.GRID
            pygame.draw.line(screen, color, (x, self.rect.top),
                             (x, self.rect.bottom))
            x += spacing
            index_x += 1
        y = self.rect.top + offset_y
        index_y = int((self.rect.top + self.origin.y) / spacing)
        while y < self.rect.bottom:
            color = ui.GRID_MAJOR if index_y % 5 == 0 else ui.GRID
            pygame.draw.line(screen, color, (self.rect.left, y),
                             (self.rect.right, y))
            y += spacing
            index_y += 1

    def _draw_edge(self, screen, fonts, transition):
        points, label_pos = self._edge_geometry(transition)
        if len(points) < 2:
            return
        selected = (self.selected_kind == "transition"
                    and self.selected_id == transition.id)
        hovered = (self.hover_kind == "transition"
                   and self.hover_id == transition.id)
        color = ui.SELECT if selected else (
            ui.EDGE_HI if hovered else ui.EDGE)
        width = 3 if (selected or hovered) else 2
        pygame.draw.lines(screen, color, False,
                          [(int(round(x)), int(round(y)))
                           for x, y in points], width)
        self._arrow(screen, points[-2], points[-1], color)

        if self.zoom < 0.45 or label_pos is None:
            return
        event = transition.event or ""
        guard = transition.guard or ""
        if not event and not guard:
            return
        font = fonts.font_s
        available = max(40, int(140 * self.zoom))
        text = _ellipsis(font, event, available)
        lines = [text] if text else []
        if guard and self.zoom >= 0.7:
            lines.append(_ellipsis(font, guard, available))
        if not lines:
            return
        rendered = [font.render(line, True, theme.TEXT if selected else
                                theme.TEXT_DIM) for line in lines]
        width_px = max(image.get_width() for image in rendered) + 10
        height_px = sum(image.get_height() for image in rendered) + 6
        box = pygame.Rect(0, 0, width_px, height_px)
        box.center = (int(round(label_pos[0])), int(round(label_pos[1])))
        theme.panel(screen, box,
                    fill=ui.CANVAS_BG,
                    border=ui.SELECT if selected else theme.BORDER,
                    radius=4)
        y = box.top + 3
        for image in rendered:
            screen.blit(image, (box.centerx - image.get_width() // 2, y))
            y += image.get_height()

    def _draw_node(self, screen, fonts, state):
        rect = self.node_rect(state)
        selected = (self.selected_kind == "state"
                    and self.selected_id == state.id)
        hovered = (self.hover_kind == "state" and self.hover_id == state.id)
        pending = (self.pending_source == state.id)
        fill = ui.NODE_HI if (selected or hovered) else ui.NODE
        border = ui.SELECT if (selected or pending) else (
            ui.EDGE_HI if hovered else ui.NODE_BORDER)

        shadow = rect.move(3, 3)
        pygame.draw.rect(screen, (0, 0, 0), shadow, border_radius=7)
        theme.panel(screen, rect, fill=fill, border=border,
                    radius=7, width=3 if selected else 1)
        if state.final:
            inner = rect.inflate(-8, -8)
            if inner.width > 4 and inner.height > 4:
                pygame.draw.rect(screen, ui.FINAL, inner,
                                 width=2, border_radius=5)
        if state.initial:
            self._draw_initial_marker(screen, rect)

        # Бейджи S/F. На мелком масштабе они отнимают место у названия,
        # а роль начального/финального уже показывают маркер и рамка.
        badges = []
        if self.zoom >= 0.85:
            if state.initial:
                badges.append(("S", ui.INITIAL))
            if state.final:
                badges.append(("F", ui.FINAL))
        badge_x = rect.right - 8
        for letter, color in reversed(badges):
            box = pygame.Rect(0, 0, 18, 16)
            box.topright = (badge_x, rect.top + 7)
            theme.panel(screen, box, fill=ui.CANVAS_BG, border=color, radius=3)
            theme.text(screen, fonts.font_s, letter, box.center, color,
                       center=True)
            badge_x -= 21

        old_clip = screen.get_clip()
        screen.set_clip(rect.inflate(-12, -4))
        title = state.name or state.id
        title_width = max(24, rect.width - 20 - 21 * len(badges))
        if self.zoom < 0.8 or rect.height < 50:
            theme.text(screen, fonts.font_s, _ellipsis(
                fonts.font_s, title, title_width), rect.center,
                ui.NODE_TEXT, center=True)
        else:
            theme.text(screen, fonts.font, _ellipsis(
                fonts.font, title, title_width),
                (rect.left + 12, rect.top + 12), ui.NODE_TEXT)
            if state.name and state.name != state.id:
                theme.text(screen, fonts.font_s, state.id,
                           (rect.left + 12, rect.top + 36), ui.NODE_DIM)
            if rect.height >= 70:
                outgoing = len(self.automaton.outgoing(state.id))
                incoming = len(self.automaton.incoming(state.id))
                if outgoing or incoming:
                    extra = "%d→ · →%d" % (outgoing, incoming)
                    theme.text(screen, fonts.font_s, extra,
                               (rect.right - 12, rect.bottom - 18),
                               ui.NODE_DIM, right=True)
        screen.set_clip(old_clip)

    def _draw_initial_marker(self, screen, rect):
        if self.zoom < 0.5:
            return
        radius = max(4, int(6 * self.zoom))
        center = (rect.left - radius - 8, rect.centery)
        pygame.draw.circle(screen, ui.INITIAL, center, radius)
        pygame.draw.line(screen, ui.INITIAL, (center[0] + radius, center[1]),
                         (rect.left - 2, center[1]), 2)

    def _arrow(self, screen, previous, tip, color):
        start = pygame.Vector2(previous)
        end = pygame.Vector2(tip)
        direction = end - start
        if direction.length_squared() == 0:
            return
        direction = direction.normalize()
        normal = pygame.Vector2(-direction.y, direction.x)
        length = 12.0
        left = end - direction * length + normal * 5.0
        right = end - direction * length - normal * 5.0
        pygame.draw.polygon(screen, color, [end, left, right])
