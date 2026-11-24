"""Карта, проекция, зум, выбор юнитов и группы."""

from __future__ import annotations

from .rts_screen_support import (
    Button,
    GRID,
    HEIGHT,
    ISO_ORIGIN,
    MAP_RECT,
    MAX_ZOOM,
    MIN_ZOOM,
    TILE_H,
    TILE_W,
    WIDTH,
    ZOOM_STEP,
    loss_limit_percent,
    math,
    pygame,
)


class RTSScreenCoreMixin:

    def _build_terrain(self):
        surf = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

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

    def _build_buttons(self):
        self.btn_pause = Button(
            (1040, 9, 94, 36), "Пауза", self.app.font_small, self.toggle_pause
        )
        self.btn_speed1 = Button(
            (1140, 9, 24, 36),
            "1x",
            self.app.font_tiny,
            lambda: self.set_speed(1),
        )
        self.btn_speed2 = Button(
            (1166, 9, 24, 36),
            "2x",
            self.app.font_tiny,
            lambda: self.set_speed(2),
        )
        self.btn_speed4 = Button(
            (1192, 9, 24, 36),
            "4x",
            self.app.font_tiny,
            lambda: self.set_speed(4),
        )
        self.btn_speed8 = Button(
            (1218, 9, 24, 36),
            "8x",
            self.app.font_tiny,
            lambda: self.set_speed(8),
        )

        self.btn_plan_hold = Button(
            (12, 314, 66, 22),
            "Оборона",
            self.app.font_tiny,
            self.command_plan_hold,
        )
        self.btn_plan_advance = Button(
            (80, 314, 72, 22),
            "Наступление",
            self.app.font_tiny,
            self.command_plan_advance,
        )
        self.btn_plan_off = Button(
            (154, 314, 66, 22),
            "Снять",
            self.app.font_tiny,
            self.command_plan_off,
        )

        self.btn_hold = Button(
            (12, 382, 208, 22),
            "Держать позиции",
            self.app.font_tiny,
            self.command_hold,
        )
        self.btn_attack = Button(
            (12, 407, 208, 22),
            "Атака ближайшего",
            self.app.font_tiny,
            self.command_attack_nearest,
        )
        self.btn_cautious = Button(
            (12, 432, 208, 22),
            "Осторожная атака",
            self.app.font_tiny,
            self.command_cautious_attack,
        )
        self.btn_withdraw = Button(
            (12, 457, 208, 22),
            "Отход / отступить",
            self.app.font_tiny,
            self.command_withdraw,
        )
        self.btn_march = Button(
            (12, 482, 208, 22),
            "Марш-бросок к цели",
            self.app.font_tiny,
            self.command_force_march,
        )
        self.btn_rest = Button(
            (12, 507, 208, 22), "Отдых", self.app.font_tiny, self.command_rest
        )
        self.btn_stop = Button(
            (12, 532, 208, 22),
            "Стоп / занять оборону",
            self.app.font_tiny,
            self.command_stop,
        )
        self.btn_orders = Button(
            (12, 574, 64, 28), "Приказы", self.app.font_tiny, self.open_orders
        )
        self.btn_needs = Button(
            (80, 574, 70, 28), "Нужды", self.app.font_tiny, self.open_needs
        )
        self.btn_journal = Button(
            (154, 574, 66, 28), "Журнал", self.app.font_tiny, self.open_journal
        )
        self.btn_logistics = Button(
            (12, 608, 100, 28),
            "Логистика",
            self.app.font_tiny,
            self.open_logistics,
        )
        self.btn_radio = Button(
            (120, 608, 100, 28), "Рация", self.app.font_tiny, self.open_radio
        )

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
        interp = getattr(self.app, "storyline_interpreter", None)
        storyline = getattr(interp, "storyline", {}) if interp else {}
        return loss_limit_percent(storyline)

    def select_all_units(self):
        self.selected = self._player_indices()
        self.active_group = None
        if self.selected:
            self._feedback("Выбраны все: %d" % len(self.selected), 1.3)
        else:
            self._feedback("Живых подразделений не осталось", 1.3)

    def _group_indices(self, number):
        names = set(self.groups.get(number, ()))
        return [
            i
            for i in self._player_indices()
            if self.state.units[i].name in names
        ]

    def assign_group(self, number):
        number = int(number)
        if number not in self.groups:
            return
        names = [det.name for det in self._selected_dets()]
        if not names:
            self._feedback("Сначала выберите роты для группы %d" % number, 1.6)
            return
        self.groups[number] = names
        self.active_group = number
        self._feedback("Группа %d: %d рот" % (number, len(names)), 1.5)

    def select_group(self, number):
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
            i
            for i, det in enumerate(self.state.units)
            if det.side == getattr(self.state, "player_side", "red")
            and not getattr(det, "broken", False)
        ]

    def _unit_at(self, pos):
        best = None
        best_y = -(10**9)
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
            det
            for i, det in enumerate(self.state.units)
            if i in self.selected
            and det.side == getattr(self.state, "player_side", "red")
            and not getattr(det, "broken", False)
        ]

    def _prune_selection(self):
        valid = set(self._player_indices())
        self.selected = [i for i in self.selected if i in valid]
        if self._target_enemy is not None:
            enemy = self.state.det_at(self._target_enemy)
            if (
                enemy is None
                or getattr(enemy, "broken", False)
                or enemy.side == getattr(self.state, "player_side", "red")
            ):
                self._target_enemy = None

    def _target_enemy_det(self):
        if self._target_enemy is None:
            return None
        enemy = self.state.det_at(self._target_enemy)
        if (
            enemy is None
            or getattr(enemy, "broken", False)
            or enemy.side == getattr(self.state, "player_side", "red")
        ):
            self._target_enemy = None
            return None
        return enemy

    def _set_target_enemy(self, idx):
        enemy = self.state.det_at(idx)
        if (
            enemy is None
            or getattr(enemy, "broken", False)
            or enemy.side == getattr(self.state, "player_side", "red")
        ):
            return None
        self._target_enemy = idx
        return enemy

    def _nearest_enemy(self, det):
        enemies = [
            d
            for d in self.state.units
            if d.side != getattr(self.state, "player_side", "red")
            and not d.broken
        ]
        if not enemies:
            return None
        return min(
            enemies,
            key=lambda d: abs(d.position[0] - det.position[0])
            + abs(d.position[1] - det.position[1]),
        )
