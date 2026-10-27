import pygame

from interaction import demo_model
from .. import theme, widgets
from ..scene import Scene

TONE_COLORS = {
    "positive": theme.OK,
    "negative": theme.DANGER,
    "danger": theme.DANGER,
    "warning": theme.WARN,
    "neutral": theme.ACCENT2,
    "unknown": theme.TEXT_MUTED,
}


class InteractionScene(Scene):

    name = "interaction"

    def __init__(self, app):
        super().__init__(app)
        self.model = None
        self.target_offset = 0
        self.action_offset = 0
        self.outcome_offset = 0
        self.hover_target = None
        self.hover_action = None
        self.target_rows = []
        self.action_rows = []
        self.outcome_rows = []
        self.target_row_h = 62
        self.action_row_h = 62
        self.outcome_row_h = 62
        self.target_max_rows = 0
        self.action_max_rows = 0
        self.outcome_max_rows = 0
        self.panels = {}
        self.target_body = pygame.Rect(0, 0, 0, 0)
        self.action_body = pygame.Rect(0, 0, 0, 0)
        self.outcome_body = pygame.Rect(0, 0, 0, 0)
        self.header_rect = pygame.Rect(0, 0, 0, 0)
        self.footer_rect = pygame.Rect(0, 0, 0, 0)

    def on_enter(self, **kwargs):
        custom = kwargs.get("model")
        if custom is not None:
            self.model = custom
        elif self.model is None or kwargs.get("new"):
            seed = kwargs.get("seed")
            self.model = demo_model(
                seed=self.app.new_seed() if seed is None else seed
            )
        if custom is not None or kwargs.get("new"):
            self.target_offset = 0
            self.action_offset = 0
            self.outcome_offset = 0
            self.hover_target = None
            self.hover_action = None

    def on_resize(self, w, h):
        self.layout(w, h)

    def layout(self, w, h):
        if self.model is None:
            self.model = demo_model(seed=self.app.new_seed())
        self.widgets = []
        edge = theme.EDGE
        gap = theme.GAP
        self.header_rect = pygame.Rect(edge, 8, max(1, w - 2 * edge), 54)
        footer_h = 70
        self.footer_rect = pygame.Rect(
            edge, max(0, h - edge - footer_h), max(1, w - 2 * edge), footer_h
        )
        body_top = self.header_rect.bottom + gap
        body_bottom = self.footer_rect.top - gap
        body_h = max(90, body_bottom - body_top)
        content_w = max(180, w - 2 * edge)
        col_gap = gap
        usable = max(120, content_w - 2 * col_gap)
        target_w = max(132, int(usable * 0.28))
        action_w = max(150, int(usable * 0.32))
        outcome_w = max(150, usable - target_w - action_w)

        total = target_w + action_w + outcome_w
        if total > usable:
            scale = usable / float(total)
            target_w = max(1, int(target_w * scale))
            action_w = max(1, int(action_w * scale))
            outcome_w = max(1, usable - target_w - action_w)
        x = edge
        self.panels = {
            "targets": pygame.Rect(x, body_top, target_w, body_h),
            "actions": pygame.Rect(
                x + target_w + col_gap, body_top, action_w, body_h
            ),
            "outcomes": pygame.Rect(
                x + target_w + action_w + 2 * col_gap,
                body_top,
                outcome_w,
                body_h,
            ),
        }
        self._build_rows()
        self._build_buttons(w, h)

    def _body_of(self, rect):
        return pygame.Rect(
            rect.left + 8,
            rect.top + 46,
            max(1, rect.width - 16),
            max(1, rect.height - 54),
        )

    def _row_height(self, body, count, minimum=46, maximum=72):
        if count <= 0:
            return 62
        return max(minimum, min(maximum, body.height // count))

    def _visible(self, items, offset, row_h, body):
        max_rows = max(1, body.height // max(1, row_h))
        offset = max(0, min(int(offset), max(0, len(items) - max_rows)))
        return items[offset : offset + max_rows], offset, max_rows

    def _build_rows(self):
        self.target_body = self._body_of(self.panels["targets"])
        self.action_body = self._body_of(self.panels["actions"])
        self.outcome_body = self._body_of(self.panels["outcomes"])

        targets = self.model.available_targets()
        self.target_row_h = self._row_height(
            self.target_body, len(targets), minimum=44
        )
        visible, self.target_offset, self.target_max_rows = self._visible(
            targets, self.target_offset, self.target_row_h, self.target_body
        )
        self.target_rows = []
        y = self.target_body.top
        for item in visible:
            rect = pygame.Rect(
                self.target_body.left,
                y,
                self.target_body.width,
                max(1, self.target_row_h - 4),
            )
            self.target_rows.append((rect, item))
            y += self.target_row_h

        actions = (
            self.model.actions_for() if self.model.selected_target_id else []
        )
        self.action_row_h = self._row_height(
            self.action_body, len(actions), minimum=44
        )
        visible, self.action_offset, self.action_max_rows = self._visible(
            actions, self.action_offset, self.action_row_h, self.action_body
        )
        self.action_rows = []
        y = self.action_body.top
        for item in visible:
            rect = pygame.Rect(
                self.action_body.left,
                y,
                self.action_body.width,
                max(1, self.action_row_h - 4),
            )
            self.action_rows.append((rect, item))
            y += self.action_row_h

        forecasts = self.model.forecasts()
        self.outcome_row_h = self._row_height(
            self.outcome_body, len(forecasts), minimum=46
        )
        visible, self.outcome_offset, self.outcome_max_rows = self._visible(
            forecasts,
            self.outcome_offset,
            self.outcome_row_h,
            self.outcome_body,
        )
        self.outcome_rows = []
        y = self.outcome_body.top
        for item in visible:
            rect = pygame.Rect(
                self.outcome_body.left,
                y,
                self.outcome_body.width,
                max(1, self.outcome_row_h - 4),
            )
            self.outcome_rows.append((rect, item))
            y += self.outcome_row_h

    def _build_buttons(self, w, h):
        footer = self.footer_rect
        gap = theme.GAP
        btn_h = max(28, min(38, footer.height // 2))
        btn_w = max(82, min(160, (footer.width - 2 * gap) // 3))
        y = footer.bottom - btn_h - 8
        x = footer.right - btn_w
        self.back_button = widgets.Button(
            self.app.t("В меню", "Menu"), self._menu, (x, y, btn_w, btn_h)
        )
        x -= btn_w + gap
        self.reset_button = widgets.Button(
            self.app.t("Сбросить", "Reset"),
            self._reset,
            (x, y, btn_w, btn_h),
            enabled=bool(
                self.model.selected_target_id or self.model.last_result
            ),
        )
        x -= btn_w + gap
        self.execute_button = widgets.Button(
            self.app.t("Выполнить", "Execute"),
            self._execute,
            (x, y, btn_w, btn_h),
            enabled=bool(self.model.selected_action_id),
        )
        self.widgets = [
            self.execute_button,
            self.reset_button,
            self.back_button,
        ]

    def _refresh(self):
        self.layout(*self.app.size)

    def _menu(self):
        self.app.go("menu")

    def _select_target(self, target_id):
        if self.model.select_target(target_id):
            self.action_offset = 0
            self.outcome_offset = 0
            self._refresh()
            return True
        return False

    def _select_action(self, action_id):
        if self.model.select_action(action_id):
            self.outcome_offset = 0
            self._refresh()
            return True
        return False

    def _execute(self):
        if not self.model.selected_action_id:
            return False
        self.model.resolve()
        self._refresh()
        return True

    def _reset(self):
        self.model.clear_selection()
        self.target_offset = 0
        self.action_offset = 0
        self.outcome_offset = 0
        self._refresh()

    def _hit(self, rows, pos):
        for rect, item in rows:
            if rect.collidepoint(pos):
                return item
        return None

    def handle_event(self, e):
        if super().handle_event(e):
            return True
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                self.app.go("menu")
                return True
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._execute()
            if e.key == pygame.K_r:
                self._reset()
                return True
        if e.type == pygame.MOUSEMOTION:
            self.hover_target = self._hit(self.target_rows, e.pos)
            self.hover_action = self._hit(self.action_rows, e.pos)
            return False
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            target = self._hit(self.target_rows, e.pos)
            if target is not None:
                return self._select_target(target.id)
            action = self._hit(self.action_rows, e.pos)
            if action is not None:
                return self._select_action(action.id)
        if e.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if self.panels["targets"].collidepoint(pos):
                self.target_offset -= int(e.y)
                self._refresh()
                return True
            if self.panels["actions"].collidepoint(pos):
                self.action_offset -= int(e.y)
                self._refresh()
                return True
            if self.panels["outcomes"].collidepoint(pos):
                self.outcome_offset -= int(e.y)
                self._refresh()
                return True
        return False

    def _ellipsize(self, font, value, max_w):
        value = str(value)
        if max_w <= 0 or font.size(value)[0] <= max_w:
            return value
        suffix = "…"
        lo, hi = 0, len(value)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.size(value[:mid] + suffix)[0] <= max_w:
                lo = mid
            else:
                hi = mid - 1
        return value[:lo] + suffix

    @staticmethod
    def _line_height(font):
        height = getattr(font, "get_height", None)
        if height is not None:
            return height()
        return max(1, font.size("Ag")[1])

    def _draw_hint(self, s, rect, value):
        font = self.app.fonts.font_s
        lines = theme.wrap(font, value, max(20, rect.width - 20))
        line_h = self._line_height(font) + 3
        y = rect.top + max(0, (rect.height - line_h * len(lines)) // 2)
        for line in lines:
            theme.text(
                s, font, line, (rect.centerx, y), theme.TEXT_MUTED, center=True
            )
            y += line_h

    def _draw_header(self, s, rect, title, context=""):
        font = self.app.fonts.font_s
        title = self._ellipsize(font, title, rect.width - 24)
        theme.text(
            s, font, title, (rect.left + 12, rect.top + 8), theme.ACCENT
        )
        if context:
            context = self._ellipsize(font, context, rect.width - 24)
            theme.text(
                s,
                font,
                context,
                (rect.left + 12, rect.top + 26),
                theme.TEXT_DIM,
            )
        pygame.draw.line(
            s,
            theme.BORDER,
            (rect.left + 10, rect.top + 44),
            (rect.right - 10, rect.top + 44),
        )

    def _draw_row(
        self,
        s,
        rect,
        label,
        description="",
        selected=False,
        hover=False,
        tone=None,
    ):
        fill = theme.PANEL
        if hover:
            fill = theme.mix(fill, theme.PANEL_HI, 0.7)
        if selected:
            fill = theme.mix(theme.PANEL_HI, theme.ACCENT, 0.12)
        border = theme.ACCENT if selected else theme.BORDER
        if hover and not selected:
            border = theme.TEXT_MUTED
        theme.panel(s, rect, fill=fill, border=border, radius=4)
        color = TONE_COLORS.get(tone, theme.TEXT_MUTED)
        if selected or tone:
            pygame.draw.rect(
                s,
                color if tone else theme.ACCENT,
                (rect.left + 1, rect.top + 6, 3, max(1, rect.height - 12)),
                border_radius=2,
            )
        font = self.app.fonts.font_s
        x = rect.left + 10
        max_w = rect.width - 20
        y = rect.top + 5
        label = self._ellipsize(font, label, max_w)
        theme.text(
            s,
            font,
            label,
            (x, y),
            theme.TEXT if not selected else theme.ACCENT,
        )
        if description:
            y += self._line_height(font) + 1
            desc = self._ellipsize(font, description, max_w)
            theme.text(s, font, desc, (x, y), theme.TEXT_DIM)

    def _draw_outcome_row(self, s, rect, forecast, hover=False):
        tone = TONE_COLORS.get(forecast.tone, theme.TEXT_MUTED)
        border = theme.BORDER
        theme.panel(s, rect, fill=theme.PANEL, border=border, radius=4)
        pygame.draw.rect(
            s,
            tone,
            (rect.left + 1, rect.top + 6, 3, max(1, rect.height - 12)),
            border_radius=2,
        )
        font = self.app.fonts.font_s
        x = rect.left + 10
        max_w = rect.width - 20
        label = self._ellipsize(font, forecast.short_label, max_w)
        theme.text(s, font, label, (x, rect.top + 4), tone)
        prob = self._ellipsize(font, forecast.probability_text, max_w)
        line_h = self._line_height(font)
        theme.text(s, font, prob, (x, rect.top + 4 + line_h), theme.TEXT_DIM)
        if rect.height >= 58 and forecast.description:
            desc = self._ellipsize(font, forecast.description, max_w)
            theme.text(
                s, font, desc, (x, rect.top + 4 + 2 * line_h), theme.TEXT_MUTED
            )

    def draw(self, s):
        if self.model is None:
            self.model = demo_model(seed=self.app.new_seed())
            self.layout(*s.get_size())
        s.fill(theme.BG)
        fonts = self.app.fonts
        theme.text(
            s,
            fonts.font_b,
            self.app.t("Взаимодействие", "Interaction"),
            (theme.EDGE, 8),
            theme.ACCENT,
        )
        theme.text(
            s,
            fonts.font_s,
            self.app.t(
                "Объект → действие → шумный прогноз → фактический исход.",
                "Target -> action -> noisy forecast -> actual result.",
            ),
            (theme.EDGE, 38),
            theme.TEXT_DIM,
        )

        target_panel = self.panels["targets"]
        action_panel = self.panels["actions"]
        outcome_panel = self.panels["outcomes"]
        for rect in (target_panel, action_panel, outcome_panel):
            theme.panel(s, rect, fill=theme.BG_ALT, border=theme.BORDER)

        target = self.model.target()
        action = self.model.action()
        self._draw_header(
            s,
            target_panel,
            self.app.t("С кем взаимодействовать", "Who to interact with"),
            self.app.t("доступные объекты", "available targets"),
        )
        self._draw_header(
            s,
            action_panel,
            self.app.t("Что можно сделать", "What can be done"),
            (
                target.label
                if target is not None
                else self.app.t(
                    "сначала выберите объект", "choose a target first"
                )
            ),
        )
        self._draw_header(
            s,
            outcome_panel,
            self.app.t("Что может произойти", "What may happen"),
            (
                ("%s → %s" % (target.label, action.label))
                if target is not None and action is not None
                else self.app.t(
                    "сначала выберите действие", "choose an action first"
                )
            ),
        )

        if not self.target_rows:
            self._draw_hint(
                s,
                self.target_body,
                self.app.t("Нет доступных объектов.", "No available targets."),
            )
        for rect, item in self.target_rows:
            self._draw_row(
                s,
                rect,
                item.label,
                item.description,
                selected=item.id == self.model.selected_target_id,
                hover=self.hover_target is item,
                tone="unknown" if "неизвестно" in item.tags else "neutral",
            )

        if not self.model.selected_target_id:
            self._draw_hint(
                s,
                self.action_body,
                self.app.t(
                    "Действия появятся после выбора объекта.",
                    "Actions appear after selecting a target.",
                ),
            )
        elif not self.action_rows:
            self._draw_hint(
                s,
                self.action_body,
                self.app.t(
                    "Для этого объекта нет доступных действий.",
                    "This target has no available actions.",
                ),
            )
        for rect, item in self.action_rows:
            self._draw_row(
                s,
                rect,
                item.label,
                item.description,
                selected=item.id == self.model.selected_action_id,
                hover=self.hover_action is item,
            )

        if not self.model.selected_action_id:
            self._draw_hint(
                s,
                self.outcome_body,
                self.app.t(
                    "Возможные исходы появятся после выбора действия. "
                    "Они всегда неточны.",
                    "Possible outcomes appear after choosing an action. "
                    "They are always uncertain.",
                ),
            )
        elif not self.outcome_rows:
            self._draw_hint(
                s,
                self.outcome_body,
                self.app.t(
                    "Для этого действия нет описанных исходов.",
                    "This action has no described outcomes.",
                ),
            )
        for rect, item in self.outcome_rows:
            self._draw_outcome_row(s, rect, item)

        self._draw_footer(s)

    def _draw_footer(self, s):
        footer = self.footer_rect
        theme.panel(s, footer, fill=theme.BG_ALT, border=theme.BORDER)
        result = self.model.last_result
        if result is not None:
            message = self.app.t(
                "Исход: %s — %s" % (result.label, result.description),
                "Result: %s - %s" % (result.label, result.description),
            )
            color = TONE_COLORS.get(result.tone, theme.TEXT)
        elif self.model.selected_action_id:
            message = self.app.t(
                "Прогноз намеренно шумный: диапазоны и уверенность — оценка, "
                "не гарантия.",
                "The forecast is deliberately noisy: ranges and confidence "
                "are estimates, not guarantees.",
            )
            color = theme.TEXT_DIM
        elif self.model.selected_target_id:
            message = self.app.t(
                "Объект выбран. Теперь выберите действие.",
                "Target selected. Now choose an action.",
            )
            color = theme.TEXT_DIM
        else:
            message = self.app.t(
                "Выберите, с кем взаимодействовать; затем — что сделать.",
                "Choose who to interact with, then what to do.",
            )
            color = theme.TEXT_MUTED
        font = self.app.fonts.font_s
        message = self._ellipsize(font, message, footer.width - 24)
        theme.text(s, font, message, (footer.left + 12, footer.top + 8), color)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
