"""Отрисовка карты, панелей, отрядов и подсказок."""

from __future__ import annotations

from .rts_screen_support import (
    BREACH_PRESSURE_TICKS,
    DAY_COLORS,
    HEIGHT,
    LEFT_W,
    MAP_RECT,
    NEED_ORDER,
    NEED_SHORT,
    RIGHT_W,
    RIGHT_X,
    SECTOR_LABELS,
    SECTOR_SHORT,
    SIDE_COLORS,
    SIDE_NAMES,
    SUPPLY_LABELS,
    TOP_H,
    WIDTH,
    draw_fitted,
    math,
    pygame,
    wrap_text,
)


class RTSScreenDrawMixin:

    def draw(self, screen):
        screen.fill(DAY_COLORS["bg"])
        self._draw_top(screen)
        self._draw_left(screen)
        self._draw_map(screen)
        self._draw_right(screen)
        self._draw_feedback(screen)

    def _draw_top(self, screen):
        pygame.draw.rect(screen, (9, 13, 18), (0, 0, WIDTH, TOP_H))
        pygame.draw.line(
            screen, DAY_COLORS["line"], (0, TOP_H - 1), (WIDTH, TOP_H - 1)
        )
        title = self.app.font_title.render(
            "ДОЛИНА-01", True, DAY_COLORS["text"]
        )
        screen.blit(title, (16, 9))
        sub = self.app.font_tiny.render(
            "ТАКТИЧЕСКАЯ КАРТА · RTS / RPG", True, DAY_COLORS["muted"]
        )
        screen.blit(sub, (18, 38))
        ts = getattr(self.app, "time_system", None)
        if ts is not None:
            time_text = ts.get_time_string()
            clock = self.app.font_body.render(
                time_text, True, DAY_COLORS["gold"]
            )
            screen.blit(clock, (270, 15))
            turn = self.app.font_tiny.render(
                "такт %d · %s"
                % (
                    self.state.current_tick,
                    "ПАУЗА" if self.paused else "x%d" % self.speed,
                ),
                True,
                DAY_COLORS["muted"],
            )
            screen.blit(turn, (272, 40))

        side = getattr(self.state, "player_side", "red")
        enemy_side = "blue" if side == "red" else "red"
        side_color = SIDE_COLORS.get(side, DAY_COLORS["player"])
        loss = self.state.division_loss_percent()
        loss_limit = self._loss_limit_percent()
        loss_ratio = loss / max(1.0, float(loss_limit))
        loss_color = (
            DAY_COLORS["bad"]
            if loss_ratio >= 0.85
            else (
                DAY_COLORS["warn"]
                if loss_ratio >= 0.6
                else DAY_COLORS["muted"]
            )
        )
        banner = pygame.Rect(470, 8, 450, 40)
        pygame.draw.rect(screen, (27, 24, 28), banner, border_radius=5)
        pygame.draw.rect(screen, side_color, banner, 2, border_radius=5)
        pygame.draw.circle(
            screen, side_color, (banner.x + 16, banner.y + 20), 8
        )
        screen.blit(
            self.app.font_small.render(
                "ВЫ КОМАНДУЕТЕ: %s" % SIDE_NAMES.get(side, side.upper()),
                True,
                DAY_COLORS["text"],
            ),
            (banner.x + 32, banner.y + 3),
        )
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
            True,
            loss_color,
        )
        screen.blit(loss_surf, (sub_x + side_surf.get_width(), sub_y))

        for x, label in (
            (930, "−"),
            (962, "+"),
            (994, "1:1"),
        ):
            rect = pygame.Rect(x, 9, 28 if label != "1:1" else 40, 36)
            pygame.draw.rect(
                screen, DAY_COLORS["panel2"], rect, border_radius=4
            )
            pygame.draw.rect(
                screen, DAY_COLORS["line"], rect, 1, border_radius=4
            )
            surf = self.app.font_small.render(label, True, DAY_COLORS["text"])
            screen.blit(surf, surf.get_rect(center=rect.center))
        screen.blit(
            self.app.font_tiny.render(
                "%d%%" % round(self.zoom * 100), True, DAY_COLORS["muted"]
            ),
            (930, 47),
        )

        self.btn_pause.draw(screen)
        for x, label, value in (
            (1140, "1x", 1),
            (1166, "2x", 2),
            (1192, "4x", 4),
            (1218, "8x", 8),
        ):
            rect = pygame.Rect(x, 9, 24, 36)
            active = self.speed == value and not self.paused
            color = DAY_COLORS["accent"] if active else DAY_COLORS["panel2"]
            pygame.draw.rect(screen, color, rect, border_radius=4)
            pygame.draw.rect(
                screen, DAY_COLORS["line"], rect, 1, border_radius=4
            )
            surf = self.app.font_tiny.render(label, True, DAY_COLORS["text"])
            screen.blit(surf, surf.get_rect(center=rect.center))

        self.btn_speed1.rect = pygame.Rect(1140, 9, 24, 36)
        self.btn_speed2.rect = pygame.Rect(1166, 9, 24, 36)
        self.btn_speed4.rect = pygame.Rect(1192, 9, 24, 36)
        self.btn_speed8.rect = pygame.Rect(1218, 9, 24, 36)

    def _draw_groups(self, screen):
        screen.blit(
            self.app.font_tiny.render("ГР", True, DAY_COLORS["muted"]),
            (14, 285),
        )
        for number, rect in self._group_rects:
            count = len(self._group_indices(number))
            active = self.active_group == number
            filled = count > 0
            bg = (
                DAY_COLORS["accent"]
                if active
                else (
                    DAY_COLORS["ally_dark"] if filled else DAY_COLORS["panel2"]
                )
            )
            pygame.draw.rect(screen, bg, rect, border_radius=3)
            pygame.draw.rect(
                screen,
                DAY_COLORS["gold"] if active else DAY_COLORS["line"],
                rect,
                1,
                border_radius=3,
            )
            text = ("%d·%d" % (number, count)) if filled else str(number)
            surf = self.app.font_tiny.render(
                text,
                True,
                DAY_COLORS["text"] if filled else DAY_COLORS["muted"],
            )
            screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_left(self, screen):
        panel = pygame.Rect(0, TOP_H, LEFT_W, HEIGHT - TOP_H)
        pygame.draw.rect(screen, DAY_COLORS["panel"], panel)
        pygame.draw.line(
            screen,
            DAY_COLORS["line"],
            (LEFT_W - 1, TOP_H),
            (LEFT_W - 1, HEIGHT),
        )
        side = getattr(self.state, "player_side", "red")
        screen.blit(
            self.app.font_small.render(
                "ВАШИ ВОЙСКА · %s" % SIDE_NAMES.get(side, side.upper()),
                True,
                DAY_COLORS["muted"],
            ),
            (14, 70),
        )
        all_rect = pygame.Rect(184, 67, 40, 17)
        pygame.draw.rect(
            screen, DAY_COLORS["panel2"], all_rect, border_radius=3
        )
        pygame.draw.rect(
            screen, DAY_COLORS["line"], all_rect, 1, border_radius=3
        )
        all_surf = self.app.font_tiny.render("ВСЕ", True, DAY_COLORS["text"])
        screen.blit(all_surf, all_surf.get_rect(center=all_rect.center))

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
                rect,
                border_radius=4,
            )
            pygame.draw.rect(
                screen,
                DAY_COLORS["accent"] if selected else DAY_COLORS["line"],
                rect,
                1,
                border_radius=4,
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
            pygame.draw.rect(
                screen,
                DAY_COLORS["good"],
                (bar.x, bar.y, int(bar.width * ratio), bar.height),
            )
            mini = self.app.font_tiny.render(
                "%d" % round(det.force), True, DAY_COLORS["muted"]
            )
            screen.blit(mini, (rect.x + 67, rect.y + 9))
        self._draw_groups(screen)
        screen.blit(
            self.app.font_small.render("АВТОПЛАН", True, DAY_COLORS["muted"]),
            (14, 298),
        )
        plan = self.engine.plan_for()
        for b, mode in (
            (self.btn_plan_hold, "hold"),
            (self.btn_plan_advance, "advance"),
            (self.btn_plan_off, "off"),
        ):
            b.draw(screen)
            active = (mode == plan.mode and plan.active) or (
                mode == "off" and not plan.active
            )
            if active:
                pygame.draw.rect(
                    screen, DAY_COLORS["gold"], b.rect, 2, border_radius=6
                )
        status = self.engine.plan_status_text()
        status_lines = wrap_text(self.app.font_tiny, status, 204)[:2]
        for offset, text in enumerate(status_lines):
            screen.blit(
                self.app.font_tiny.render(
                    text,
                    True,
                    DAY_COLORS["gold"] if plan.active else DAY_COLORS["muted"],
                ),
                (14, 340 + offset * 12),
            )
        screen.blit(
            self.app.font_small.render("ПРИКАЗЫ", True, DAY_COLORS["muted"]),
            (14, 366),
        )
        target = self._target_enemy_det()
        self.btn_attack.text = (
            "Атака цели: %s" % target.name
            if target is not None
            else "Атака ближайшего"
        )
        for b in (
            self.btn_hold,
            self.btn_attack,
            self.btn_cautious,
            self.btn_withdraw,
            self.btn_march,
            self.btn_rest,
            self.btn_stop,
        ):
            b.draw(screen)
        screen.blit(
            self.app.font_small.render("ШТАБ", True, DAY_COLORS["muted"]),
            (14, 560),
        )
        for b in (
            self.btn_orders,
            self.btn_needs,
            self.btn_journal,
            self.btn_logistics,
            self.btn_radio,
        ):
            b.draw(screen)
        hint = self.app.font_tiny.render(
            "ПКМ — приказ; Shift+ПКМ — план\n"
            "G/T/Y — план; A…S — приказы\n"
            "Ctrl+A — все; Shift+1…6 — группа\n"
            "F — огонь; +/− — масштаб",
            True,
            DAY_COLORS["muted"],
        )
        screen.blit(hint, (14, 660))

    def _draw_map(self, screen):
        clip_before = screen.get_clip()
        screen.set_clip(MAP_RECT)
        terrain, offset = self._scaled_terrain()
        screen.blit(terrain, offset)
        pygame.draw.rect(screen, DAY_COLORS["line"], MAP_RECT, 1)
        self._draw_plan_overlay(screen)

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
                pygame.draw.circle(
                    screen, line_color, (int(p1[0]), int(p1[1])), 5, 1
                )
                if focus_det is not None:
                    pygame.draw.line(
                        screen,
                        line_color,
                        (int(p1[0]) - 7, int(p1[1]) - 7),
                        (int(p1[0]) + 7, int(p1[1]) + 7),
                        1,
                    )
                    pygame.draw.line(
                        screen,
                        line_color,
                        (int(p1[0]) - 7, int(p1[1]) + 7),
                        (int(p1[0]) + 7, int(p1[1]) - 7),
                        1,
                    )

        for particle in self._particles:
            particle.draw(screen)
        ordered = sorted(
            [d for d in self.state.units if not getattr(d, "broken", False)],
            key=lambda d: self._display_pos.get(d.name, (0, 0))[1],
        )
        for det in ordered:
            self._draw_unit(screen, det)

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
        plan = self.engine.plan_for()
        if not plan.active:
            return
        overlay = pygame.Surface(MAP_RECT.size, pygame.SRCALPHA)

        def local(point):
            return (
                int(round(point[0] - MAP_RECT.x)),
                int(round(point[1] - MAP_RECT.y)),
            )

        color = (232, 194, 98) if plan.mode == "hold" else (92, 176, 242)
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
                    overlay,
                    color + (190,),
                    (int(first[0] + ux * start), int(first[1] + uy * start)),
                    (int(first[0] + ux * end), int(first[1] + uy * end)),
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
            pygame.draw.polygon(overlay, color + (220,), [second, left, right])
            mid = (
                int((first[0] + second[0]) / 2),
                int((first[1] + second[1]) / 2),
            )
            label = "НАСТУПЛЕНИЕ"
        text = self.app.font_tiny.render(label, True, color)
        pad = pygame.Rect(
            mid[0] - text.get_width() // 2 - 4,
            mid[1] - text.get_height() // 2 - 2,
            text.get_width() + 8,
            text.get_height() + 4,
        )
        pygame.draw.rect(overlay, (12, 16, 22, 165), pad, border_radius=3)
        overlay.blit(
            text,
            (pad.x + 4, pad.y + 2),
        )
        screen.blit(overlay, MAP_RECT.topleft)

    def _contact_frontline_points(self):
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
        points = self._contact_frontline_points()
        if not points:
            return
        overlay = pygame.Surface(MAP_RECT.size, pygame.SRCALPHA)

        def local(point):
            return (
                int(round(point[0] - MAP_RECT.x)),
                int(round(point[1] - MAP_RECT.y)),
            )

        for pair in getattr(self.engine, "engagements", []) or []:
            pa = self._display_pos.get(pair.get("attacker"))
            pb = self._display_pos.get(pair.get("defender"))
            if pa is None or pb is None:
                continue
            pygame.draw.line(
                overlay,
                (255, 126, 74, 70),
                local(pa),
                local(pb),
                1,
            )

        if len(points) >= 2:
            mx = sum(p[0] for p in points) / len(points)
            my = sum(p[1] for p in points) / len(points)
            sxx = sum((p[0] - mx) ** 2 for p in points)
            syy = sum((p[1] - my) ** 2 for p in points)
            sxy = sum((p[0] - mx) * (p[1] - my) for p in points)
            theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
            ux, uy = math.cos(theta), math.sin(theta)
            projections = [(p[0] - mx) * ux + (p[1] - my) * uy for p in points]
            lo, hi = min(projections), max(projections)
            if hi - lo >= 4.0:
                first = (mx + ux * lo, my + uy * lo)
                second = (mx + ux * hi, my + uy * hi)
                a, b = local(first), local(second)
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = max(0.01, math.hypot(dx, dy))
                ux, uy = dx / length, dy / length

                pygame.draw.line(
                    overlay,
                    (255, 115, 70, 38),
                    a,
                    b,
                    7,
                )
                start = 0.0
                while start < length:
                    end = min(length, start + 9.0)
                    pygame.draw.line(
                        overlay,
                        (255, 178, 110, 185),
                        (int(a[0] + ux * start), int(a[1] + uy * start)),
                        (int(a[0] + ux * end), int(a[1] + uy * end)),
                        2,
                    )
                    start += 15.0
        for point in points:
            x, y = local(point)
            pygame.draw.line(
                overlay, (255, 195, 128, 210), (x - 4, y), (x + 4, y), 1
            )
            pygame.draw.line(
                overlay, (255, 195, 128, 210), (x, y - 4), (x, y + 4), 1
            )
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
        dark = (
            DAY_COLORS["ally_dark"] if is_player else DAY_COLORS["enemy_dark"]
        )

        shadow = pygame.Rect(0, 0, 34, 12)
        shadow.center = (x, y + 7)
        pygame.draw.ellipse(screen, (8, 12, 14), shadow)
        true_pos = self._render_pos.get(det.name)
        if true_pos is not None:
            dx = true_pos[0] - x
            dy = true_pos[1] - y
            if abs(dx) + abs(dy) > 3.0:
                pygame.draw.line(
                    screen,
                    color,
                    (int(true_pos[0]), int(true_pos[1])),
                    (x, y),
                    1,
                )
        if selected:
            pygame.draw.ellipse(
                screen, DAY_COLORS["gold"], (x - 20, y - 12, 40, 24), 2
            )
            pygame.draw.ellipse(
                screen, (255, 220, 120), (x - 16, y - 9, 32, 18), 1
            )
        if is_target:
            pygame.draw.ellipse(
                screen, (255, 145, 85), (x - 21, y - 13, 42, 26), 2
            )

        body = pygame.Rect(x - 13, y - 16, 26, 20)
        pygame.draw.rect(screen, dark, body, border_radius=4)
        pygame.draw.rect(screen, color, body, 2, border_radius=4)
        pygame.draw.line(screen, color, (x - 7, y - 12), (x + 7, y - 2), 2)
        pygame.draw.line(screen, color, (x + 7, y - 12), (x - 7, y - 2), 2)
        if det.retreating or det.broken:
            pygame.draw.line(
                screen, (210, 210, 210), (x - 10, y - 14), (x + 10, y - 4), 2
            )
        if is_target:
            pygame.draw.line(
                screen, (255, 145, 85), (x - 9, y - 7), (x + 9, y - 7), 1
            )
        label_color = DAY_COLORS["text"] if is_player else (175, 205, 255)
        label = self.app.font_tiny.render(det.name, True, label_color)
        label_x = x - label.get_width() // 2
        label_y = y - 34
        screen.blit(label, (label_x, label_y))
        if is_player:

            pygame.draw.polygon(
                screen,
                DAY_COLORS["gold"],
                [
                    (label_x - 7, label_y + 1),
                    (label_x - 3, label_y + 1),
                    (label_x - 5, label_y + 8),
                ],
            )

        start = self.state._start_force(det)
        force_ratio = det.force / max(1.0, start)
        morale_ratio = det.morale / 100.0
        base_needs = det.needs_summary()
        comfort = (
            1.0
            - sum(
                base_needs.get(n, 0.0)
                for n in ("hunger", "thirst", "fatigue", "health", "fear")
            )
            / 5.0
        )
        for j, (value, col) in enumerate(
            (
                (force_ratio, DAY_COLORS["good"]),
                (morale_ratio, DAY_COLORS["accent"]),
                (comfort, DAY_COLORS["gold"]),
            )
        ):
            bar = pygame.Rect(x - 16, y + 9 + j * 4, 32, 3)
            pygame.draw.rect(screen, (35, 40, 46), bar)
            pygame.draw.rect(
                screen,
                col,
                (
                    bar.x,
                    bar.y,
                    int(max(0.0, min(1.0, value)) * bar.width),
                    bar.height,
                ),
            )

    def _draw_sector_status(self, screen):
        geometry = getattr(self.state, "geometry", None)
        if geometry is None:
            return
        panel = pygame.Rect(LEFT_W + 18, 548, RIGHT_X - LEFT_W - 36, 50)
        bg = pygame.Surface(panel.size, pygame.SRCALPHA)
        bg.fill((8, 12, 18, 205))
        screen.blit(bg, panel.topleft)
        pygame.draw.rect(screen, DAY_COLORS["line"], panel, 1, border_radius=4)
        screen.blit(
            self.app.font_tiny.render(
                "ПРОЕКЦИИ · сила (вы/пр) · потери/сут",
                True,
                DAY_COLORS["muted"],
            ),
            (panel.x + 8, panel.y + 2),
        )
        statuses = geometry.statuses()
        card_w = (panel.width - 16) // max(1, len(statuses))
        for i, status in enumerate(statuses):
            x = panel.x + 8 + i * card_w
            y = panel.y + 15
            color = (
                DAY_COLORS["bad"]
                if status.breached
                else (
                    DAY_COLORS["warn"]
                    if status.pressure
                    else DAY_COLORS["good"]
                )
            )
            label = self.app.font_tiny.render(status.label, True, color)
            screen.blit(label, (x, y))
            rate = (
                geometry.sector_daily_rate(
                    self.state.player_side, status.sector
                )
                * 100.0
            )
            rate_surf = self.app.font_tiny.render(
                "%.1f%%" % rate, True, DAY_COLORS["muted"]
            )
            screen.blit(
                rate_surf,
                (x + card_w - rate_surf.get_width() - 8, y),
            )
            ratio = status.ratio
            if ratio <= 0.0 and status.defender_force > 0:
                ratio = status.attacker_force / max(1.0, status.defender_force)
            if status.sector == "rear":
                ratio_text = "тыл"
            elif status.breached:
                ratio_text = "ПРОРЫВ"
            elif status.pressure:
                ratio_text = "нажим %d/%d" % (
                    status.pressure,
                    BREACH_PRESSURE_TICKS,
                )
            else:
                ratio_text = "%.2f:1" % ratio
            force_text = self.app.font_tiny.render(
                "%.0f / %.0f  %s"
                % (
                    status.defender_force,
                    status.attacker_force,
                    ratio_text,
                ),
                True,
                DAY_COLORS["text"],
            )
            screen.blit(force_text, (x, y + 15))

    def _draw_map_legend(self, screen):
        legend = pygame.Rect(LEFT_W + 18, 606, 520, 48)
        bg = pygame.Surface(legend.size, pygame.SRCALPHA)
        bg.fill((8, 12, 18, 190))
        screen.blit(bg, legend.topleft)
        pygame.draw.rect(
            screen, DAY_COLORS["line"], legend, 1, border_radius=4
        )
        side = getattr(self.state, "player_side", "red")
        enemy_side = "blue" if side == "red" else "red"
        pygame.draw.circle(
            screen,
            SIDE_COLORS.get(side, DAY_COLORS["player"]),
            (legend.x + 18, legend.y + 16),
            6,
        )
        screen.blit(
            self.app.font_tiny.render(
                "ВЫ: %s" % SIDE_NAMES.get(side, side.upper()),
                True,
                DAY_COLORS["text"],
            ),
            (legend.x + 30, legend.y + 8),
        )
        pygame.draw.circle(
            screen,
            SIDE_COLORS.get(enemy_side, DAY_COLORS["enemy"]),
            (legend.x + 128, legend.y + 16),
            6,
        )
        screen.blit(
            self.app.font_tiny.render(
                "ПРОТИВНИК: %s"
                % SIDE_NAMES.get(enemy_side, enemy_side.upper()),
                True,
                DAY_COLORS["muted"],
            ),
            (legend.x + 140, legend.y + 8),
        )
        screen.blit(
            self.app.font_tiny.render(
                "ПКМ по врагу — огонь; клик — цель; F — огонь · "
                "оранжевая линия — фронт",
                True,
                DAY_COLORS["muted"],
            ),
            (legend.x + 10, legend.y + 29),
        )

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
                "· " + text[:110],
                True,
                (
                    DAY_COLORS["text"]
                    if i == len(events[-3:]) - 1
                    else DAY_COLORS["muted"]
                ),
            )
            screen.blit(surf, (panel.x + 8, panel.y + 4 + i * 12))

    def _draw_right(self, screen):
        panel = pygame.Rect(RIGHT_X, TOP_H, RIGHT_W, HEIGHT - TOP_H)
        pygame.draw.rect(screen, DAY_COLORS["panel"], panel)
        pygame.draw.line(
            screen, DAY_COLORS["line"], (RIGHT_X, TOP_H), (RIGHT_X, HEIGHT)
        )
        screen.blit(
            self.app.font_small.render(
                "ВЫБРАННОЕ ПОДРАЗДЕЛЕНИЕ", True, DAY_COLORS["muted"]
            ),
            (RIGHT_X + 12, 70),
        )
        if not self.selected:
            draw_fitted(
                screen,
                [self.app.font_small, self.app.font_tiny],
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
        screen.blit(
            self.app.font_body.render(det.name, True, DAY_COLORS["text"]),
            (RIGHT_X + 12, y),
        )
        y += 28
        order_label = self.state.get_segment_label(self.selected[0], "order")
        sector = self.state.sector_of(det)
        projected = self.state.projected_force(det)
        geometry = getattr(self.state, "geometry", None)
        context = geometry.combat_context(det) if geometry else None
        daily = context.daily_rate * 100.0 if context else 0.0
        context_label = context.label if context else "—"
        info = (
            "Сила %.1f / %.0f · проекция %.1f\n" "%s · %s · %s · %.1f%%/сут"
        ) % (
            det.force,
            self.state._start_force(det),
            projected,
            SECTOR_LABELS.get(sector, sector),
            order_label,
            context_label,
            daily,
        )
        draw_fitted(
            screen,
            [self.app.font_tiny],
            info,
            pygame.Rect(RIGHT_X + 12, y, RIGHT_W - 24, 44),
            DAY_COLORS["muted"],
            spacing=1.05,
        )
        self._draw_needs(screen, det, 178)
        self._draw_supplies(screen, 376)
        self._draw_commander_panel(screen)

    def _draw_needs(self, screen, det, top):
        screen.blit(
            self.app.font_small.render(
                "ПОТРЕБНОСТИ · САМООБЕСПЕЧЕНИЕ", True, DAY_COLORS["muted"]
            ),
            (RIGHT_X + 12, top - 20),
        )
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
            color = (
                DAY_COLORS["good"]
                if value < 0.35
                else DAY_COLORS["warn"] if value < 0.65 else DAY_COLORS["bad"]
            )
            pygame.draw.rect(
                screen,
                color,
                (bar.x, bar.y, int(bar.width * value), bar.height),
            )
            pct = self.app.font_tiny.render(
                "%d" % round(value * 100), True, color
            )
            screen.blit(pct, (bar.right + 4, y))

    def _draw_supplies(self, screen, top):
        screen.blit(
            self.app.font_small.render("РЕСУРСЫ", True, DAY_COLORS["muted"]),
            (RIGHT_X + 12, top - 20),
        )
        supplies = getattr(self.state, "supplies", {})
        logistics = getattr(self.state, "logistics", None)
        for i, (key, label) in enumerate(SUPPLY_LABELS.items()):
            x = RIGHT_X + 12 + (i % 2) * 130
            y = top + (i // 2) * 22
            text = "%s: %d" % (label, int(supplies.get(key, 0)))
            if key == "influence" and logistics is not None:
                text += " +%.0f/ч" % logistics.influence_per_hour
            surf = self.app.font_tiny.render(
                text,
                True,
                DAY_COLORS["text"],
            )
            screen.blit(surf, (x, y))

    def _draw_commander_panel(self, screen):
        screen.blit(
            self.app.font_small.render(
                "ВАШИ ПОТРЕБНОСТИ · КОМАНДИР", True, DAY_COLORS["muted"]
            ),
            (RIGHT_X + 12, 458),
        )
        pygame.draw.rect(
            screen, DAY_COLORS["panel2"], self._commander_rect, border_radius=5
        )
        pygame.draw.rect(
            screen,
            DAY_COLORS["line"],
            self._commander_rect,
            1,
            border_radius=5,
        )
        needs = self.state.needs.player_needs_summary()
        keys = ("hunger", "thirst", "fatigue", "fear", "anxiety", "health")
        for i, need in enumerate(keys):
            col = i // 3
            row = i % 3
            x = self._commander_rect.x + 8 + col * 124
            y = self._commander_rect.y + 8 + row * 23
            value = max(0.0, min(1.0, needs.get(need, 0.0)))
            screen.blit(
                self.app.font_tiny.render(
                    NEED_SHORT.get(need, need), True, DAY_COLORS["muted"]
                ),
                (x, y),
            )
            bar = pygame.Rect(x + 48, y + 5, 46, 6)
            pygame.draw.rect(screen, (35, 42, 49), bar)
            color = (
                DAY_COLORS["good"]
                if value < 0.35
                else DAY_COLORS["warn"] if value < 0.65 else DAY_COLORS["bad"]
            )
            pygame.draw.rect(
                screen,
                color,
                (bar.x, bar.y, int(bar.width * value), bar.height),
            )
            screen.blit(
                self.app.font_tiny.render(
                    "%d" % round(value * 100), True, color
                ),
                (bar.right + 3, y),
            )
        morale = getattr(self.state.needs.commander, "morale", 0.0)
        screen.blit(
            self.app.font_tiny.render(
                "Мораль командира: %.0f" % morale, True, DAY_COLORS["text"]
            ),
            (self._commander_rect.x + 8, self._commander_rect.y + 80),
        )
        screen.blit(
            self.app.font_tiny.render(
                "Действия — «Нужды» (N). Подразделения",
                True,
                DAY_COLORS["muted"],
            ),
            (self._commander_rect.x + 8, self._commander_rect.y + 100),
        )
        screen.blit(
            self.app.font_tiny.render(
                "обеспечивают себя сами через логистику.",
                True,
                DAY_COLORS["muted"],
            ),
            (self._commander_rect.x + 8, self._commander_rect.y + 113),
        )
        target = self._target_enemy_det()
        target_text = (
            "Цель огня: %s" % target.name
            if target is not None
            else "Цель не выбрана"
        )
        screen.blit(
            self.app.font_tiny.render(
                target_text,
                True,
                (255, 170, 110) if target is not None else DAY_COLORS["muted"],
            ),
            (self._commander_rect.x + 8, self._commander_rect.y + 138),
        )
        screen.blit(
            self.app.font_tiny.render(
                "Нажмите, чтобы открыть личные нужды",
                True,
                DAY_COLORS["accent"],
            ),
            (self._commander_rect.x + 8, self._commander_rect.y + 164),
        )
        if self.state.needs.player_cooldowns:
            screen.blit(
                self.app.font_tiny.render(
                    "часть действий на кулдауне", True, DAY_COLORS["warn"]
                ),
                (self._commander_rect.x + 8, self._commander_rect.y + 185),
            )

    def _draw_tooltip(self, screen, idx):
        det = self.state.det_at(idx)
        if det is None:
            return
        p = self._display_pos.get(det.name, (0, 0))
        side = getattr(self.state, "player_side", "red")
        side_text = "ВАШ" if det.side == side else "ПРОТИВНИК"
        sector = self.state.sector_of(det)
        geometry = getattr(self.state, "geometry", None)
        context = geometry.combat_context(det) if geometry else None
        lines = [
            det.name,
            side_text,
            "сила %.1f / %.0f · проекция %.1f"
            % (
                det.force,
                self.state._start_force(det),
                self.state.projected_force(det),
            ),
            "сектор: %s" % SECTOR_LABELS.get(sector, sector),
            "обстановка: %s" % (context.label if context else "—"),
            *(
                ["капитуляция через %d тактов" % context.surrender_in]
                if context is not None and context.encircled
                else []
            ),
            "мораль %.0f" % det.morale,
            "приказ: %s" % self.state.get_segment_label(idx, "order"),
        ]
        width = max(self.app.font_tiny.size(line)[0] for line in lines) + 20
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
            screen.blit(
                self.app.font_tiny.render(line, True, col),
                (rect.x + 8, rect.y + 5 + i * 14),
            )

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
