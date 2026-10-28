import pygame

from .. import theme, widgets
from ..battlefield import (
    ATTACK_ORDERS,
    DIALOGUES,
    GRID_H,
    GRID_W,
    BattlefieldModel,
    chebyshev,
    grid_to_screen,
    screen_to_grid,
)
from ..scene import Scene


class BattlefieldScene(Scene):
    name = "battlefield"

    def __init__(self, app):
        super().__init__(app)
        self.model = None
        self.move_mode = True
        self.show_help = False
        self.hover_tile = None
        self._message_until = 0
        self.choice_buttons = []

    def on_enter(self, seed=None, new=False, player_profile="CANON", **kwargs):
        if self.model is None or new:
            use_seed = int(seed if seed is not None else self.app.new_seed())
            self.model = BattlefieldModel(
                seed=use_seed,
                player_profile=player_profile,
                checkpoint=getattr(self.app, "checkpoint", ""),
                health_factors=getattr(self.app, "health_factors", {}),
                sickness=getattr(self.app, "sickness", None) or 0.0,
            )
            self.move_mode = True
            self.show_help = False
            self.hover_tile = None
            self._message_until = 0
        self.layout(*self.app.size)

    def on_exit(self, **kwargs):
        self.show_help = False

    def layout(self, w, h):
        self.widgets = []
        self.choice_buttons = []
        edge = theme.EDGE
        top_h = 54
        self.top_rect = pygame.Rect(edge, 10, w - 2 * edge, top_h)
        body_top = self.top_rect.bottom + 10
        body_h = h - body_top - edge
        field_w = int((w - 2 * edge - theme.GAP) * 0.66)
        self.field_rect = pygame.Rect(edge, body_top, field_w, body_h)
        self.side_rect = pygame.Rect(
            self.field_rect.right + theme.GAP,
            body_top,
            w - self.field_rect.right - theme.GAP - edge,
            body_h,
        )

        self.origin = (
            self.field_rect.centerx - (GRID_W - GRID_H) * 68 / 4.0,
            self.field_rect.centery - (GRID_W + GRID_H - 2) * 34 / 4.0 - 24,
        )

        self.dialog_rect = pygame.Rect(
            self.field_rect.left + 18,
            self.field_rect.bottom - 184,
            self.field_rect.width - 36,
            168,
        )

        self._layout_top_buttons()
        self._layout_side_buttons()
        self._layout_dialog_buttons()

    def _button(self, label, callback, rect, enabled=True):
        self.widgets.append(
            widgets.Button(label, callback, rect, enabled=enabled)
        )

    def _layout_top_buttons(self):
        t = self.app.t
        bw, bh = 120, 34
        y = self.top_rect.top + (self.top_rect.height - bh) // 2
        self._button(
            t("МЕНЮ", "MENU"),
            lambda: self.app.push("pause"),
            (self.top_rect.right - bw - 12, y, bw, bh),
        )
        self._button(
            t("ПОМОЩЬ", "HELP"),
            self._toggle_help,
            (self.top_rect.right - 2 * bw - 20, y, bw, bh),
        )

    def _layout_side_buttons(self):
        if self.model is None:
            return
        t = self.app.t
        m = self.model
        x = self.side_rect.left + 16
        width = self.side_rect.width - 32
        gap = 8
        y = self.side_rect.top + 196
        bw = (width - 2 * gap) // 3
        enabled = (not m.winner) and m.contact and m.command_points >= 1
        self._button(
            t("АТАКА", "ATTACK"),
            lambda: self._order("ATTACK"),
            (x, y, width, 36),
            enabled=enabled,
        )
        y += 44
        self._button(
            t("ПОКОЙ", "REST"),
            lambda: self._order("REST"),
            (x, y, bw, 36),
            enabled=not m.winner,
        )
        self._button(
            t("ДЕРЖАТЬ", "HOLD"),
            lambda: self._order("HOLD"),
            (x + bw + gap, y, bw, 36),
            enabled=not m.winner,
        )
        self._button(
            t("ХОД", "END TURN"),
            self._end_turn,
            (x + 2 * (bw + gap), y, bw, 36),
            enabled=not m.winner,
        )
        y += 44
        move_label = (
            t("ДВИЖЕНИЕ: ВКЛ", "MOVE: ON")
            if self.move_mode
            else t("ДВИЖЕНИЕ: ВЫКЛ", "MOVE: OFF")
        )
        self._button(
            move_label,
            self._toggle_move,
            (x, y, width, 32),
            enabled=not m.winner,
        )

        if m.roleplay.active is None and m.roleplay.queue:
            self._button(
                t("СОВЕТ", "COUNCIL"),
                self._council,
                (x, self.side_rect.bottom - 44, width, 32),
            )

    def _layout_dialog_buttons(self):
        if self.model is None or self.model.roleplay.active is None:
            return
        dialogue = DIALOGUES[self.model.roleplay.active]
        n = len(dialogue.choices)
        if not n:
            return
        bw = (self.dialog_rect.width - 32 - (n - 1) * 8) // n
        y = self.dialog_rect.bottom - 46
        x = self.dialog_rect.left + 16
        for i, choice in enumerate(dialogue.choices):
            button = widgets.Button(
                self.app.t(*choice.label),
                (lambda idx=i: self._choose(idx)),
                (x + i * (bw + 8), y, bw, 32),
            )
            self.widgets.append(button)
            self.choice_buttons.append(button)

    def _rebuild(self):
        self.layout(*self.app.size)

    def _notify(self, ru, en):
        self.model.set_message(ru, en)
        self._message_until = pygame.time.get_ticks() + 3200

    def _order(self, order):
        ok, ru, en = self.model.issue_order(order)
        self._notify(ru, en)
        self.move_mode = False
        self._rebuild()

    def _move_to(self, tile):
        ok, ru, en = self.model.move_unit("player", tile[0], tile[1])
        self._notify(ru, en)
        self._rebuild()

    def _end_turn(self):
        self.model.end_turn()
        self._notify("Ход завершён.", "Turn ended.")
        self._rebuild()

    def _choose(self, index):
        self.model.roleplay.choose(index)
        self._rebuild()

    def _council(self):
        self.model.roleplay.next()
        self._rebuild()

    def _toggle_move(self):
        self.move_mode = not self.move_mode
        self._rebuild()

    def _toggle_help(self):
        self.show_help = not self.show_help

    def _select(self, tile):
        uid = self.model.unit_at(tile[0], tile[1])
        if uid:
            self.model.selected = uid
            self._rebuild()
            return True
        if self.move_mode:
            self._move_to(tile)
            return True
        return False

    def handle_event(self, e):
        if self.show_help:
            if e.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                self.show_help = False
                return True
            return False
        if super().handle_event(e):
            return True

        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                if self.show_help:
                    self.show_help = False
                else:
                    self.app.push("pause")
                return True
            if e.key == pygame.K_F1:
                self.show_help = not self.show_help
                return True
            if e.key == pygame.K_SPACE:
                self._end_turn()
                return True
            if e.key == pygame.K_1:
                self._order(ATTACK_ORDERS[0])
                return True
            if e.key == pygame.K_r:
                self._order("REST")
                return True
            if e.key == pygame.K_h:
                self._order("HOLD")
                return True
            if e.key == pygame.K_m:
                self._toggle_move()
                return True
            if e.key == pygame.K_TAB:
                self.model.selected = (
                    "enemy" if self.model.selected == "player" else "player"
                )
                self._rebuild()
                return True

        if e.type == pygame.MOUSEMOTION:
            if self.field_rect.collidepoint(e.pos):
                self.hover_tile = screen_to_grid(
                    e.pos[0], e.pos[1], self.origin
                )
            else:
                self.hover_tile = None
            return False

        if e.type == pygame.MOUSEBUTTONDOWN and self.field_rect.collidepoint(
            e.pos
        ):
            tile = screen_to_grid(e.pos[0], e.pos[1], self.origin)
            if tile is None:
                return False
            if e.button == 1:
                return self._select(tile)
            if e.button == 3:
                self._move_to(tile)
                return True
        return False

    def update(self, dt):
        if (
            self._message_until
            and pygame.time.get_ticks() > self._message_until
        ):
            self._message_until = 0
            self.model.set_message("", "")

    def draw(self, s):
        s.fill(theme.BG)
        self._draw_top(s)
        self._draw_field(s)
        self._draw_side(s)
        self._draw_dialog(s)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
        self._draw_message(s)
        if self.show_help:
            self._draw_help(s)

    def _draw_top(self, s):
        t = self.app.t
        theme.panel(s, self.top_rect, fill=theme.BG_ALT, border=theme.BORDER)
        theme.text(
            s,
            self.app.fonts.font_b,
            t("ПОЛЕ БОЯ", "BATTLEFIELD"),
            (self.top_rect.left + 16, self.top_rect.top + 10),
            theme.ACCENT,
        )
        m = self.model
        owner = {
            None: t("свободна", "free"),
            "player": t("наша", "ours"),
            "enemy": t("враг", "enemy"),
        }[m.objective_owner]
        stats = t(
            "ход %d   CP %d/%d   цель: %s   %s"
            % (
                m.turn,
                m.command_points,
                m.max_command_points,
                owner,
                (
                    t("контакт", "contact")
                    if m.contact
                    else t("манёвр", "manoeuvre")
                ),
            ),
            "turn %d   CP %d/%d   objective: %s   %s"
            % (
                m.turn,
                m.command_points,
                m.max_command_points,
                owner,
                "contact" if m.contact else "manoeuvre",
            ),
        )
        theme.text(
            s,
            self.app.fonts.font_s,
            stats,
            (self.top_rect.left + 180, self.top_rect.centery),
            theme.TEXT_DIM,
        )

    def _draw_field(self, s):
        t = self.app.t
        theme.panel(s, self.field_rect, fill=theme.BG_ALT, border=theme.BORDER)
        s.set_clip(self.field_rect)
        targets = (
            set(self.model.move_targets("player")) if self.move_mode else set()
        )
        for row in range(GRID_H):
            for col in range(GRID_W):
                cx, cy = grid_to_screen(col, row, self.origin)
                cx, cy = int(cx), int(cy)
                points = [
                    (cx, cy - 17),
                    (cx + 34, cy),
                    (cx, cy + 17),
                    (cx - 34, cy),
                ]
                fill = (
                    theme.BG_ALT
                    if (col + row) % 2 == 0
                    else theme.mix(theme.BG_ALT, theme.PANEL, 0.22)
                )
                if (col, row) == self.model.objective:
                    fill = theme.mix(theme.PANEL, theme.ACCENT, 0.18)
                if self.hover_tile == (col, row):
                    fill = theme.mix(fill, theme.ACCENT2, 0.25)
                pygame.draw.polygon(s, fill, points)
                pygame.draw.lines(s, theme.BORDER, True, points, 1)
                if (col, row) in targets:
                    inner = [
                        (cx, cy - 12),
                        (cx + 24, cy),
                        (cx, cy + 12),
                        (cx - 24, cy),
                    ]
                    pygame.draw.lines(s, theme.ACCENT2, True, inner, 1)

        ox, oy = grid_to_screen(*self.model.objective, self.origin)
        ox, oy = int(ox), int(oy)
        pygame.draw.circle(s, theme.ACCENT, (ox, oy), 8, 2)
        theme.text(
            s,
            self.app.fonts.font_s,
            t("ЦЕЛЬ", "OBJ"),
            (ox, oy + 18),
            theme.ACCENT,
            center=True,
        )

        if self.model.contact:
            a = tuple(
                int(v)
                for v in grid_to_screen(
                    *self.model.player_unit.pos, self.origin
                )
            )
            b = tuple(
                int(v)
                for v in grid_to_screen(
                    *self.model.enemy_unit.pos, self.origin
                )
            )
            pygame.draw.line(s, theme.DANGER, a, b, 2)
        self._draw_unit(s, self.model.player_unit)
        self._draw_unit(s, self.model.enemy_unit)
        s.set_clip(None)

    def _draw_unit(self, s, unit):
        cx, cy = grid_to_screen(unit.col, unit.row, self.origin)
        cx, cy = int(cx), int(cy)
        is_player = unit.side == "player"
        color = theme.ACCENT2 if is_player else theme.DANGER
        selected = self.model.selected == unit.uid
        pygame.draw.ellipse(s, (0, 0, 0), (cx - 26, cy - 2, 52, 20))
        pygame.draw.ellipse(s, color, (cx - 28, cy - 2, 56, 20), 1)
        if selected:
            pygame.draw.ellipse(s, theme.ACCENT, (cx - 32, cy - 4, 64, 24), 2)
        body = pygame.Rect(int(cx - 22), int(cy - 50), 44, 44)
        theme.panel(
            s,
            body,
            fill=theme.mix(theme.PANEL, color, 0.18),
            border=color,
            radius=6,
        )
        theme.text(
            s,
            self.app.fonts.font_s,
            "АВ" if is_player else "ТН",
            body.center,
            theme.TEXT,
            center=True,
        )
        theme.text(
            s,
            self.app.fonts.font_s,
            unit.name,
            (cx, body.top - 14),
            color,
            center=True,
        )

        bar = pygame.Rect(int(cx - 24), body.top - 8, 48, 6)
        theme.panel(s, bar, fill=theme.BG_ALT, border=theme.BORDER, radius=2)
        ratio = max(0.0, min(1.0, unit.commander.force_ratio))
        fill = pygame.Rect(
            bar.left + 1,
            bar.top + 1,
            int((bar.width - 2) * ratio),
            bar.height - 2,
        )
        if fill.width > 0:
            pygame.draw.rect(s, color, fill, border_radius=2)

    def _draw_side(self, s):
        t = self.app.t
        m = self.model
        side = self.side_rect
        theme.panel(s, side, fill=theme.BG_ALT, border=theme.BORDER)
        theme.text(
            s,
            self.app.fonts.font_b,
            t("КОМАНДНЫЙ ПУНКТ", "COMMAND POST"),
            (side.left + 16, side.top + 10),
            theme.ACCENT,
        )

        unit = m.selected_unit
        cmd = unit.commander
        portrait = pygame.Rect(side.left + 16, side.top + 36, 120, 140)
        theme.draw_placeholder(
            s,
            portrait,
            cmd.portrait,
            self.app.fonts,
            caption=t("ПОРТРЕТ", "PORTRAIT"),
        )
        info_x = portrait.right + 12
        info_w = side.right - info_x - 16
        y = portrait.top
        theme.text(s, self.app.fonts.font, cmd.name, (info_x, y), theme.TEXT)
        y += 22
        theme.text(
            s,
            self.app.fonts.font_s,
            t(
                "выбран: %s"
                % ("авангард" if unit.side == "player" else "тень"),
                "selected: %s"
                % ("vanguard" if unit.side == "player" else "shadow"),
            ),
            (info_x, y),
            theme.ACCENT2 if unit.side == "player" else theme.DANGER,
        )
        y += 18
        theme.text(
            s,
            self.app.fonts.font_s,
            t("профиль: %s" % cmd.profile, "profile: %s" % cmd.profile),
            (info_x, y),
            theme.TEXT_DIM,
        )
        y += 18
        theme.text(
            s,
            self.app.fonts.font_s,
            t("строй: %s" % cmd.stance, "stance: %s" % cmd.stance),
            (info_x, y),
            theme.TEXT_DIM,
        )
        y += 22
        self._bar(
            s,
            pygame.Rect(info_x, y, info_w, 14),
            cmd.force_ratio,
            theme.ACCENT2 if unit.side == "player" else theme.DANGER,
            t("сила %d" % cmd.force, "force %d" % cmd.force),
        )
        y += 20
        energy_ratio = min(1.0, cmd.energy / max(1.0, cmd.max_energy))
        self._bar(
            s,
            pygame.Rect(info_x, y, info_w, 14),
            energy_ratio,
            theme.OK,
            t("пул %d" % cmd.energy, "pool %d" % cmd.energy),
        )
        y += 20
        self._bar(
            s,
            pygame.Rect(info_x, y, info_w, 14),
            cmd.health_ratio,
            theme.WARN,
            t("здоровье %d" % cmd.health, "health %d" % cmd.health),
        )
        y += 20
        self._bar(
            s,
            pygame.Rect(info_x, y, info_w, 14),
            cmd.morale / 100.0,
            theme.ACCENT,
            t("мораль %d" % cmd.morale, "morale %d" % cmd.morale),
        )
        y += 24
        if unit.side == "player":
            traits = m.roleplay.traits
            traits_text = t(
                ", ".join(x[0] for x in traits) or "—",
                ", ".join(x[1] for x in traits) or "—",
            )
        else:
            traits_text = t("скрыты", "hidden")
        theme.text(
            s,
            self.app.fonts.font_s,
            t("черты: %s" % traits_text, "traits: %s" % traits_text),
            (side.left + 16, portrait.bottom + 10),
            theme.TEXT_MUTED,
        )

        theme.text(
            s,
            self.app.fonts.font_s,
            t("ПРИКАЗЫ", "ORDERS"),
            (side.left + 16, side.top + 178),
            theme.ACCENT2,
        )
        theme.text(
            s,
            self.app.fonts.font_s,
            t("ЖУРНАЛ", "LOG"),
            (side.left + 16, side.bottom - 172),
            theme.ACCENT2,
        )
        y = side.bottom - 150
        for turn, ru, en in m.last_log(4):
            line = "%02d  %s" % (turn, t(ru, en))
            for wrapped in theme.wrap(
                self.app.fonts.font_s, line, side.width - 32
            )[:2]:
                theme.text(
                    s,
                    self.app.fonts.font_s,
                    wrapped,
                    (side.left + 16, y),
                    theme.TEXT_DIM,
                )
                y += 16
            y += 2

    def _bar(self, s, rect, ratio, color, label):
        theme.panel(s, rect, fill=theme.PANEL, border=theme.BORDER, radius=3)
        inner = rect.inflate(-4, -4)
        fill = pygame.Rect(
            inner.left,
            inner.top,
            int(inner.width * max(0.0, min(1.0, ratio))),
            inner.height,
        )
        if fill.width > 0:
            pygame.draw.rect(s, color, fill, border_radius=2)
        theme.text(
            s,
            self.app.fonts.font_s,
            label,
            (rect.right + 6, rect.centery),
            theme.TEXT_DIM,
        )

        if (
            rect.right + 6 + self.app.fonts.font_s.size(str(label))[0]
            > self.side_rect.right
        ):
            theme.text(
                s,
                self.app.fonts.font_s,
                label,
                (rect.left + 6, rect.centery - 7),
                theme.TEXT,
            )

    def _draw_dialog(self, s):
        m = self.model
        if m.roleplay.active is None:
            return
        t = self.app.t
        dialogue = DIALOGUES[m.roleplay.active]
        theme.panel(
            s,
            self.dialog_rect,
            fill=theme.PANEL,
            border=theme.ACCENT,
            radius=8,
        )
        theme.text(
            s,
            self.app.fonts.font_s,
            t(*dialogue.speaker),
            (self.dialog_rect.left + 16, self.dialog_rect.top + 10),
            theme.ACCENT,
        )
        y = self.dialog_rect.top + 32
        for line in theme.wrap(
            self.app.fonts.font_s,
            t(*dialogue.text),
            self.dialog_rect.width - 32,
        )[:3]:
            theme.text(
                s,
                self.app.fonts.font_s,
                line,
                (self.dialog_rect.left + 16, y),
                theme.TEXT,
            )
            y += 17

    def _draw_message(self, s):
        ru, en = self.model.message
        if not ru and not en:
            return
        text = self.app.t(ru, en)
        font = self.app.fonts.font_s
        width = min(self.field_rect.width - 40, font.size(text)[0] + 28)
        rect = pygame.Rect(0, 0, width, 28)
        rect.midtop = (self.field_rect.centerx, self.field_rect.top + 10)
        theme.panel(s, rect, fill=theme.PANEL, border=theme.ACCENT2)
        theme.text(s, font, text, rect.center, theme.TEXT, center=True)

    def _draw_help(self, s):
        w, h = s.get_size()
        dim = pygame.Surface((w, h), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 170))
        s.blit(dim, (0, 0))
        rect = pygame.Rect(0, 0, min(560, w - 40), 320)
        rect.center = (w // 2, h // 2)
        theme.panel(s, rect, fill=theme.PANEL, border=theme.ACCENT)
        t = self.app.t
        theme.text(
            s,
            self.app.fonts.font_b,
            t("УПРАВЛЕНИЕ", "CONTROLS"),
            (rect.centerx, rect.top + 18),
            theme.ACCENT,
            center=True,
        )
        lines = [
            t(
                "ЛКМ — выбрать юнит / клетку; ПКМ — приказ движения",
                "LMB - select unit/tile; RMB - move order",
            ),
            t(
                "1 — атака; R — покой; H — держать",
                "1 - attack; R - rest; H - hold",
            ),
            t(
                "M — режим движения; Space — завершить ход; Tab — выбор "
                "стороны",
                "M - move mode; Space - end turn; Tab - switch side",
            ),
            t("ESC — пауза; F1 — эта справка", "ESC - pause; F1 - this help"),
            t(
                "Контакт = соседняя клетка. Бой считает модель IPO.",
                "Contact = adjacent tile. Combat is resolved by the IPO "
                "model.",
            ),
        ]
        y = rect.top + 62
        for line in lines:
            for wrapped in theme.wrap(
                self.app.fonts.font_s, line, rect.width - 40
            ):
                theme.text(
                    s,
                    self.app.fonts.font_s,
                    wrapped,
                    (rect.left + 20, y),
                    theme.TEXT,
                )
                y += 18
            y += 8
