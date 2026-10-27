import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import wrap_text
from view.support.log_journal import get_logger

logger = get_logger("view.strategy")

WIDTH, HEIGHT = 1280, 720
TOP_H = 108
LEFT_RECT = pygame.Rect(24, TOP_H + 8, 378, 516)
MID_RECT = pygame.Rect(424, TOP_H + 8, 380, 516)
RIGHT_RECT = pygame.Rect(826, TOP_H + 8, 430, 516)
BOTTOM_RECT = pygame.Rect(24, 650, 1232, 52)
ENTITY_ROW_H = 44
ACTION_ROW_H = 54
PANEL_BG = (20, 24, 34, 238)
PANEL_BORDER = (58, 70, 92)
TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
BAD = (226, 112, 112)
WARN = (230, 184, 96)
TYPE_COLORS = {
    "character": (100, 166, 230),
    "organization": (228, 188, 104),
    "asset": (118, 202, 156),
    "institution": (190, 140, 226),
}


class StrategyScreen(BaseScreen):

    show_time_hud = False
    escape_action = "none"

    def __init__(self, app, engine):
        super().__init__(app)
        self.engine = engine
        self.entities = engine.sorted_entities()
        self.selected_entity_id = (
            self.entities[0]["id"] if self.entities else None
        )
        self.selected_action_id = None
        self.entity_scroll = 0
        self.action_scroll = 0
        self.last_result = engine.last_result
        self.message = ""
        self._sync_storyline()
        logger.info(
            "Стратегический экран: сущностей=%d, действий=%d, день=%d",
            len(self.entities),
            len(engine.actions),
            engine.day,
        )

    def _sync_storyline(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return
        interp.state["strategy"] = self.engine.to_dict()
        interp.set_variable("strategy_day", self.engine.day)
        interp.set_variable("strategy_days", self.engine.days)
        interp.set_variable("strategy_actions_left", self.engine.actions_left)
        for key in self.engine.resource_defs:
            interp.set_variable("strategy_%s" % key, self.engine.resource(key))

    def _entity_visible_count(self):
        return max(1, (LEFT_RECT.height - 44) // ENTITY_ROW_H)

    def _action_visible_count(self):
        return max(1, (MID_RECT.height - 132) // ACTION_ROW_H)

    def _max_entity_scroll(self):
        return max(0, len(self.entities) - self._entity_visible_count())

    def _action_options(self):
        if not self.selected_entity_id:
            return []
        return self.engine.action_options(self.selected_entity_id)

    def _max_action_scroll(self):
        return max(
            0, len(self._action_options()) - self._action_visible_count()
        )

    def _entity_rows(self):
        visible = self._entity_visible_count()
        start = min(self.entity_scroll, self._max_entity_scroll())
        rows = []
        for index, entity in enumerate(self.entities[start : start + visible]):
            rect = pygame.Rect(
                LEFT_RECT.x + 8,
                LEFT_RECT.y + 42 + index * ENTITY_ROW_H,
                LEFT_RECT.width - 16,
                ENTITY_ROW_H - 4,
            )
            rows.append((rect, entity))
        return rows

    def _action_rows(self):
        options = self._action_options()
        visible = self._action_visible_count()
        start = min(self.action_scroll, self._max_action_scroll())
        rows = []
        for index, option in enumerate(options[start : start + visible]):
            rect = pygame.Rect(
                MID_RECT.x + 8,
                MID_RECT.y + 124 + index * ACTION_ROW_H,
                MID_RECT.width - 16,
                ACTION_ROW_H - 4,
            )
            rows.append((rect, option))
        return rows

    def _select_entity(self, entity_id):
        if entity_id == self.selected_entity_id:
            return
        self.selected_entity_id = entity_id
        self.selected_action_id = None
        self.action_scroll = 0
        self.last_result = None
        logger.debug("Выбрана сущность: %s", entity_id)

    def _select_action(self, action_id):
        self.selected_action_id = action_id
        self.last_result = None
        logger.debug("Выбрано действие: %s", action_id)

    def _execute_selected(self):
        action_id = self.selected_action_id
        if not action_id or not self.selected_entity_id:
            return
        result = self.engine.execute(action_id, self.selected_entity_id)
        if not result.get("ok"):
            self.message = str(result.get("reason") or "Действие недоступно")
            return
        self.last_result = result
        self.selected_action_id = None
        self.message = ""
        self._sync_storyline()
        logger.info(
            "Стратегическое действие: %s; итог=%s",
            result.get("action"),
            result.get("outcome"),
        )

    def _end_day(self):
        result = self.engine.end_day()
        if not result.get("ok"):
            self.message = str(result.get("reason") or "")
            return
        self.last_result = self.engine.last_result
        self.selected_action_id = None
        self.message = ""
        self._sync_storyline()
        logger.info("Завершён день, теперь день=%d", self.engine.day)

    def _accept_outcome(self):
        if self.engine.outcome not in ("win", "lose"):
            return
        self.app.finish_storyline_outcome(self.engine.outcome)
        logger.info("Принят исход кампании: %s", self.engine.outcome)

    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if LEFT_RECT.collidepoint(pos):
                self.entity_scroll = max(
                    0,
                    min(
                        self._max_entity_scroll(),
                        self.entity_scroll - event.y,
                    ),
                )
            elif MID_RECT.collidepoint(pos):
                self.action_scroll = max(
                    0,
                    min(
                        self._max_action_scroll(),
                        self.action_scroll - event.y,
                    ),
                )
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        pos = event.pos
        if self.engine.finished and self._finish_rect().collidepoint(pos):
            self._accept_outcome()
            return
        if self._end_day_rect().collidepoint(pos):
            self._end_day()
            return
        if self._execute_rect().collidepoint(pos):
            self._execute_selected()
            return
        for rect, entity in self._entity_rows():
            if rect.collidepoint(pos):
                self._select_entity(entity["id"])
                return
        for rect, option in self._action_rows():
            if rect.collidepoint(pos):
                if option.get("enabled"):
                    self._select_action(option["id"])
                else:
                    self.message = str(option.get("reason") or "Недоступно")
                return

    def _finish_rect(self):
        return pygame.Rect(RIGHT_RECT.right - 210, BOTTOM_RECT.y + 6, 210, 40)

    def _end_day_rect(self):
        return pygame.Rect(BOTTOM_RECT.right - 210, BOTTOM_RECT.y + 6, 210, 40)

    def _execute_rect(self):
        return pygame.Rect(
            RIGHT_RECT.x + 16,
            RIGHT_RECT.bottom - 52,
            RIGHT_RECT.width - 32,
            38,
        )

    def _draw_top(self, screen):
        title = self.app.font_title.render(
            str(self.engine.config.get("title") or "Хартия"), True, TEXT
        )
        screen.blit(title, (24, 10))
        subtitle = self.app.font_small.render(
            str(self.engine.config.get("subtitle") or ""), True, MUTED
        )
        screen.blit(subtitle, (24, 44))
        player = self.engine.player_character or {}
        faction = {}
        if self.app.campaign_preset is not None:
            faction = self.app.campaign_preset.player_faction or {}
        name = player.get("name") or "Действующее лицо"
        role = (
            player.get("post")
            or player.get("role")
            or faction.get("role_title")
            or "мандат"
        )
        who = "%s · %s" % (name, role)
        screen.blit(
            self.app.font_body.render(who, True, (205, 218, 236)),
            (650, 14),
        )
        org = self.app.font_small.render(
            "%s · %s"
            % (
                faction.get("name") or "Коалиция",
                player.get("side", faction.get("side", "—")).upper(),
            ),
            True,
            MUTED,
        )
        screen.blit(org, (650, 40))
        day = "День %d / %d · Действия %d / %d" % (
            self.engine.day,
            self.engine.days,
            self.engine.actions_left,
            self.engine.actions_per_day,
        )
        day_surf = self.app.font_small.render(day, True, WARN)
        screen.blit(day_surf, (WIDTH - 24 - day_surf.get_width(), 18))
        status = "Хартия: %.0f%%" % (100.0 * self.engine.resource("charter"))
        status_surf = self.app.font_small.render(status, True, GOOD)
        screen.blit(status_surf, (WIDTH - 24 - status_surf.get_width(), 42))
        x = 24
        chip_w = (WIDTH - 48) // 5
        for key, definition in self.engine.resource_defs.items():
            rect = pygame.Rect(x, 68, chip_w - 8, 26)
            pygame.draw.rect(screen, (16, 20, 28), rect, border_radius=4)
            value = self.engine.resource(key)
            bar = pygame.Rect(rect.x + 2, rect.bottom - 4, rect.width - 4, 2)
            pygame.draw.rect(screen, (44, 54, 68), bar)
            pygame.draw.rect(
                screen,
                TYPE_COLORS["asset"],
                pygame.Rect(bar.x, bar.y, int(bar.width * value), 2),
            )
            text = "%s %.0f%%" % (
                definition.get("label", key),
                100.0 * value,
            )
            screen.blit(
                self.app.font_tiny.render(text, True, TEXT),
                (rect.x + 6, rect.y + 4),
            )
            x += chip_w

    def _draw_panel(self, screen, rect, title, count=None):
        surf = pygame.Surface(rect.size, pygame.SRCALPHA)
        surf.fill(PANEL_BG)
        screen.blit(surf, rect.topleft)
        pygame.draw.rect(screen, PANEL_BORDER, rect, 2, border_radius=8)
        label = str(title)
        if count is not None:
            label += "  ·  %d" % count
        screen.blit(
            self.app.font_body.render(label, True, (208, 218, 232)),
            (rect.x + 12, rect.y + 10),
        )
        pygame.draw.line(
            screen,
            PANEL_BORDER,
            (rect.x + 8, rect.y + 36),
            (rect.right - 8, rect.y + 36),
        )

    def _draw_entities(self, screen):
        self._draw_panel(screen, LEFT_RECT, "КТО ДОСТУПЕН", len(self.entities))
        for rect, entity in self._entity_rows():
            selected = entity["id"] == self.selected_entity_id
            if selected:
                pygame.draw.rect(screen, (38, 62, 88), rect, border_radius=5)
            else:
                pygame.draw.rect(screen, (25, 31, 42), rect, border_radius=5)
            color = TYPE_COLORS.get(entity.get("type"), ACCENT)
            pygame.draw.rect(
                screen, color, (rect.x + 4, rect.y + 6, 4, rect.height - 12)
            )
            name = str(entity.get("name") or entity["id"])
            screen.blit(
                self.app.font_small.render(name, True, TEXT),
                (rect.x + 16, rect.y + 4),
            )
            detail = "%s · %s" % (
                self.engine.entity_type_label(entity.get("type")),
                entity.get("role")
                or self.engine.subtype_label(entity.get("subtype", "")),
            )
            screen.blit(
                self.app.font_tiny.render(detail, True, MUTED),
                (rect.x + 16, rect.y + 24),
            )
            if entity.get("is_player"):
                screen.blit(
                    self.app.font_tiny.render("вы", True, GOOD),
                    (rect.right - 28, rect.y + 4),
                )
        if self.entity_scroll < self._max_entity_scroll():
            hint = self.app.font_tiny.render("колесо — прокрутка", True, DIM)
            screen.blit(hint, (LEFT_RECT.x + 12, LEFT_RECT.bottom - 18))

    def _draw_entity_details(self, screen, entity):
        top = MID_RECT.y + 42
        screen.blit(
            self.app.font_small.render(
                str(entity.get("name") or ""), True, TEXT
            ),
            (MID_RECT.x + 12, top),
        )
        subtitle = "%s · %s" % (
            self.engine.entity_type_label(entity.get("type")),
            entity.get("role")
            or self.engine.subtype_label(entity.get("subtype", "")),
        )
        screen.blit(
            self.app.font_tiny.render(subtitle, True, MUTED),
            (MID_RECT.x + 12, top + 18),
        )
        stats = entity.get("stats") or {}
        x = MID_RECT.x + 12
        y = top + 40
        for key, value in stats.items():
            label = self.engine.stat_label(key)
            screen.blit(
                self.app.font_tiny.render(
                    "%s %.0f%%" % (label, 100.0 * float(value)),
                    True,
                    (180, 194, 214),
                ),
                (x, y),
            )
            x += 120
        if entity.get("hidden_agenda"):
            if entity.get("revealed"):
                text = "Интерес: %s" % entity["hidden_agenda"]
                color = WARN
            else:
                text = "Скрытый интерес ещё не раскрыт."
                color = DIM
            for index, line in enumerate(
                wrap_text(self.app.font_tiny, text, MID_RECT.width - 24)[:2]
            ):
                screen.blit(
                    self.app.font_tiny.render(line, True, color),
                    (MID_RECT.x + 12, y + 18 + index * 14),
                )

    def _draw_actions(self, screen):
        self._draw_panel(screen, MID_RECT, "ЧТО МОЖНО СДЕЛАТЬ")
        entity = self.engine.entity(self.selected_entity_id)
        if entity is None:
            screen.blit(
                self.app.font_small.render(
                    "Выберите, кто доступен, в левой колонке.",
                    True,
                    MUTED,
                ),
                (MID_RECT.x + 12, MID_RECT.y + 60),
            )
            return
        self._draw_entity_details(screen, entity)
        options = self._action_options()
        if not options:
            screen.blit(
                self.app.font_small.render(
                    "Для этой цели нет доступных действий.", True, MUTED
                ),
                (MID_RECT.x + 12, MID_RECT.y + 140),
            )
        for rect, option in self._action_rows():
            action = option["action"]
            selected = option["id"] == self.selected_action_id
            enabled = bool(option.get("enabled"))
            if selected:
                pygame.draw.rect(screen, (38, 62, 88), rect, border_radius=5)
            else:
                pygame.draw.rect(screen, (25, 31, 42), rect, border_radius=5)
            color = TEXT if enabled else DIM
            screen.blit(
                self.app.font_small.render(
                    str(action.get("label") or option["id"]), True, color
                ),
                (rect.x + 10, rect.y + 4),
            )
            cost = ", ".join(
                "%s −%.0f%%"
                % (
                    self.engine.resource_labels.get(key, key),
                    100.0 * float(value),
                )
                for key, value in (action.get("cost") or {}).items()
            )
            detail = cost or "без прямой платы"
            if not enabled and option.get("reason"):
                detail = str(option["reason"])
            screen.blit(
                self.app.font_tiny.render(
                    detail, True, MUTED if enabled else BAD
                ),
                (rect.x + 10, rect.y + 27),
            )
        if self.action_scroll < self._max_action_scroll():
            hint = self.app.font_tiny.render(
                "колесо — прокрутка действий", True, DIM
            )
            screen.blit(hint, (MID_RECT.x + 12, MID_RECT.bottom - 18))

    def _draw_text_block(self, screen, y, heading, text, color, max_lines=5):
        screen.blit(
            self.app.font_small.render(heading, True, color),
            (RIGHT_RECT.x + 14, y),
        )
        y += 19
        if not text:
            return y
        lines = wrap_text(self.app.font_tiny, str(text), RIGHT_RECT.width - 28)
        for line in lines[:max_lines]:
            screen.blit(
                self.app.font_tiny.render(line, True, (184, 194, 210)),
                (RIGHT_RECT.x + 14, y),
            )
            y += 14
        return y + 5

    def _draw_effects_line(self, screen, y, effects):
        if not effects:
            return y
        text = " · ".join(str(item) for item in effects)
        return self._draw_text_block(screen, y, "Эффект", text, GOOD, 2)

    def _draw_consequences(self, screen):
        self._draw_panel(screen, RIGHT_RECT, "ПОСЛЕДСТВИЯ")
        y = RIGHT_RECT.y + 48
        action = self.engine.actions.get(self.selected_action_id)
        target = self.engine.entity(self.selected_entity_id)
        if action is not None and target is not None:
            preview = self.engine.preview(action["id"], target["id"])
            y = self._draw_text_block(
                screen,
                y,
                "Цель",
                "%s · %s"
                % (
                    self.engine.entity_label(target["id"]),
                    self.engine.entity_type_label(target.get("type")),
                ),
                TEXT,
                2,
            )
            y = self._draw_text_block(
                screen,
                y,
                "Плата",
                ", ".join(preview.get("cost") or ["без прямой платы"]),
                WARN,
                2,
            )
            y = self._draw_text_block(
                screen,
                y,
                "Ожидаемо",
                ", ".join(
                    preview.get("immediate") or ["без немедленного эффекта"]
                ),
                GOOD,
                2,
            )
            success = preview.get("success_text") or ""
            if success:
                y = self._draw_text_block(
                    screen,
                    y,
                    "Успех — %.0f%%"
                    % (100.0 * preview.get("success_chance", 0.0)),
                    success,
                    GOOD,
                    3,
                )
                y = self._draw_effects_line(
                    screen, y, preview.get("success_effects")
                )
            failure = preview.get("failure_text") or ""
            if failure:
                y = self._draw_text_block(
                    screen,
                    y,
                    "Провал — %.0f%%"
                    % (100.0 * preview.get("failure_chance", 0.0)),
                    failure,
                    BAD,
                    3,
                )
                y = self._draw_effects_line(
                    screen, y, preview.get("failure_effects")
                )
            if preview.get("delayed_text"):
                y = self._draw_text_block(
                    screen,
                    y,
                    "Отложенный след",
                    preview["delayed_text"],
                    WARN,
                    3,
                )
            if preview.get("ends_game") == "win":
                y = self._draw_text_block(
                    screen,
                    y,
                    "Финал",
                    "Успех выносит Хартию на подписание и завершает кампанию.",
                    GOOD,
                    2,
                )
            if preview.get("obligations"):
                y = self._draw_text_block(
                    screen,
                    y,
                    "Новое обязательство",
                    " ".join(preview["obligations"]),
                    WARN,
                    2,
                )
            if not preview.get("enabled"):
                screen.blit(
                    self.app.font_tiny.render(
                        "Недоступно: %s" % preview.get("reason", ""),
                        True,
                        BAD,
                    ),
                    (RIGHT_RECT.x + 14, min(y, RIGHT_RECT.bottom - 92)),
                )
            self._draw_button(
                screen,
                self._execute_rect(),
                action.get("label", "Совершить"),
                preview.get("enabled"),
                accent=True,
            )
            return
        result = self.last_result
        if result:
            outcome = result.get("outcome", "")
            color = {"success": GOOD, "failure": BAD, "win": GOOD}.get(
                outcome, WARN
            )
            y = self._draw_text_block(
                screen,
                y,
                "Итог · %s" % result.get("action_label", ""),
                result.get("text", ""),
                color,
                5,
            )
            if result.get("changes"):
                text = " · ".join(
                    "%s %s%.0f%%"
                    % (label, "+" if value > 0 else "", 100.0 * value)
                    for label, value in result["changes"]
                )
                y = self._draw_text_block(screen, y, "Сдвиги", text, MUTED, 2)
        else:
            y = self._draw_text_block(
                screen,
                y,
                "Как это работает",
                "Выберите, кто доступен. Затем выберите действие. Здесь "
                "появятся его цена, ожидаемый эффект, вероятность успеха, "
                "возможный провал и отложенный след.",
                MUTED,
                5,
            )
        if self.message:
            y = self._draw_text_block(
                screen, y, "Замечание", self.message, BAD, 2
            )
        log = self.engine.log[-5:]
        if log:
            screen.blit(
                self.app.font_tiny.render("Журнал", True, DIM),
                (RIGHT_RECT.x + 14, min(y + 4, RIGHT_RECT.bottom - 90)),
            )
            y = min(y + 20, RIGHT_RECT.bottom - 70)
            for item in log[-3:]:
                text = "Д%d: %s" % (item.get("day", 0), item.get("text", ""))
                lines = wrap_text(
                    self.app.font_tiny, text, RIGHT_RECT.width - 28
                )
                for line in lines[:1]:
                    screen.blit(
                        self.app.font_tiny.render(line, True, DIM),
                        (RIGHT_RECT.x + 14, y),
                    )
                    y += 14

    def _draw_button(self, screen, rect, label, enabled=True, accent=False):
        pos = pygame.mouse.get_pos()
        hover = enabled and rect.collidepoint(pos)
        if not enabled:
            fill = (30, 34, 42)
            color = DIM
        elif accent:
            fill = (56, 112, 170) if not hover else (72, 136, 202)
            color = TEXT
        else:
            fill = (46, 58, 72) if not hover else (62, 82, 102)
            color = TEXT
        pygame.draw.rect(screen, fill, rect, border_radius=6)
        pygame.draw.rect(screen, PANEL_BORDER, rect, 1, border_radius=6)
        surf = self.app.font_small.render(str(label), True, color)
        if surf.get_width() > rect.width - 16:
            scale = (rect.width - 16) / surf.get_width()
            surf = pygame.transform.smoothscale(
                surf,
                (max(1, int(surf.get_width() * scale)), surf.get_height()),
            )
        screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_bottom(self, screen):
        pygame.draw.rect(screen, (14, 18, 26), BOTTOM_RECT, border_radius=7)
        pygame.draw.rect(screen, PANEL_BORDER, BOTTOM_RECT, 1, border_radius=7)
        hint = (
            "Три поля: кто доступен · что можно сделать · каковы последствия. "
            "ЛКМ — выбор, колесо — прокрутка."
        )
        screen.blit(
            self.app.font_tiny.render(hint, True, MUTED),
            (BOTTOM_RECT.x + 14, BOTTOM_RECT.y + 8),
        )
        obligations = len(self.engine.obligations)
        if obligations:
            screen.blit(
                self.app.font_tiny.render(
                    "Обязательств: %d" % obligations, True, WARN
                ),
                (BOTTOM_RECT.x + 14, BOTTOM_RECT.y + 26),
            )
        if self.engine.finished:
            label = (
                "Принять развязку"
                if self.engine.outcome
                else "Кампания завершена"
            )
            self._draw_button(
                screen, self._finish_rect(), label, True, accent=True
            )
        else:
            self._draw_button(
                screen,
                self._end_day_rect(),
                "Завершить день",
                self.engine.actions_left >= 0,
            )

    def draw(self, screen):
        screen.fill((12, 15, 22))
        self._draw_top(screen)
        self._draw_entities(screen)
        self._draw_actions(screen)
        self._draw_consequences(screen)
        self._draw_bottom(screen)


__all__ = ["StrategyScreen"]
