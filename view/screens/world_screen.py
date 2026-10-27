import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import wrap_text
from view.support.log_journal import get_logger

logger = get_logger("view.world")

WIDTH, HEIGHT = 1280, 720
TOP_H = 108
LEFT_RECT = pygame.Rect(24, TOP_H + 8, 378, 516)
MID_RECT = pygame.Rect(424, TOP_H + 8, 390, 516)
RIGHT_RECT = pygame.Rect(826, TOP_H + 8, 430, 516)
BOTTOM_RECT = pygame.Rect(24, 650, 1232, 52)
NODE_ROW_H = 30
ACTION_ROW_H = 50
PANEL_BG = (20, 24, 34, 238)
PANEL_BORDER = (58, 70, 92)
TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
BAD = (226, 112, 112)
WARN = (230, 184, 96)


class WorldScreen(BaseScreen):

    show_time_hud = False
    escape_action = "none"

    def __init__(self, app, engine):
        super().__init__(app)
        self.engine = engine
        self.selected_target_id = engine.player_node_id or (
            engine.node_order[0] if engine.node_order else ""
        )
        self.selected_action_id = None
        self.target_scroll = 0
        self.action_scroll = 0
        self.message = ""
        self.entries = self._build_entries()
        self.target_rows = []
        self.last_result = engine.last_result
        self._sync_storyline()
        logger.info(
            "Экран мира: день=%d, узлов=%d, действий=%d",
            engine.day,
            len(engine.nodes),
            len(engine.actions),
        )

    def _build_entries(self):
        domains = {
            item["id"]: item for item in self.engine.config.get("domains", [])
        }
        polities = self.engine.config.get("polities", [])
        grouped = {}
        for node in self.engine.sorted_nodes():
            grouped.setdefault(node.get("polity", ""), []).append(node)
        entries = []
        for polity in polities:
            polity_id = polity["id"]
            nodes = grouped.pop(polity_id, [])
            if not nodes:
                continue
            entries.append(
                {
                    "kind": "header",
                    "label": polity.get("label", polity_id),
                }
            )
            nodes.sort(
                key=lambda item: (
                    (
                        list(domains).index(item["domain"])
                        if item["domain"] in domains
                        else 99
                    ),
                    int(
                        (domains.get(item["domain"]) or {})
                        .get("level_index", {})
                        .get(item["level"], 99)
                    ),
                    item["name"],
                )
            )
            for node in nodes:
                entries.append({"kind": "node", "node": node})
        for polity_id, nodes in grouped.items():
            if not nodes:
                continue
            entries.append(
                {"kind": "header", "label": polity_id or "Вне политий"}
            )
            for node in nodes:
                entries.append({"kind": "node", "node": node})
        return entries

    def _sync_storyline(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return
        interp.state["world"] = self.engine.to_dict()
        interp.set_variable("world_day", self.engine.day)
        interp.set_variable("world_days", self.engine.days)
        interp.set_variable("world_actions_left", self.engine.actions_left)
        interp.set_variable("world_outcome", self.engine.outcome or "")
        for key, value in self.engine.player_resources.items():
            interp.set_variable("world_%s" % key, value)

    def _visible_target_rows(self):
        return max(1, (LEFT_RECT.height - 50) // NODE_ROW_H)

    def _max_target_scroll(self):
        return max(0, len(self.entries) - self._visible_target_rows())

    def _visible_action_rows(self):
        return max(1, (MID_RECT.height - 154) // ACTION_ROW_H)

    def _action_options(self):
        if not self.selected_target_id:
            return []
        return self.engine.action_options(self.selected_target_id)

    def _max_action_scroll(self):
        return max(
            0, len(self._action_options()) - self._visible_action_rows()
        )

    def _select_target(self, node_id):
        if node_id == self.selected_target_id:
            return
        self.selected_target_id = node_id
        self.selected_action_id = None
        self.action_scroll = 0
        self.last_result = None
        self.message = ""
        logger.debug("Цель мира выбрана: %s", node_id)

    def _select_action(self, option):
        if not option.get("enabled"):
            self.message = str(option.get("reason") or "Действие недоступно")
            return
        self.selected_action_id = option["id"]
        self.last_result = None
        self.message = ""
        logger.debug("Действие мира выбрано: %s", option["id"])

    def _execute_selected(self):
        if not self.selected_action_id:
            return
        action_id = self.selected_action_id
        previous_node = self.engine.player_node_id
        result = self.engine.execute(action_id, self.selected_target_id)
        if not result.get("ok"):
            self.message = str(result.get("reason") or "Действие недоступно")
            return
        self.last_result = result
        self.selected_action_id = None
        self.message = ""
        action = self.engine.actions.get(action_id) or {}
        if (
            action.get("career") in ("promote", "transfer")
            and self.engine.player_node_id != previous_node
        ):
            self.selected_target_id = self.engine.player_node_id
            self.action_scroll = 0
        self._sync_storyline()
        logger.info(
            "Действие мира: %s; итог=%s",
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
        logger.info("Мир завершил день: %d", self.engine.day)

    def _accept_outcome(self):
        if self.engine.outcome not in ("win", "lose"):
            return
        self.app.finish_storyline_outcome(self.engine.outcome)
        logger.info("Принят исход мира: %s", self.engine.outcome)

    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if LEFT_RECT.collidepoint(pos):
                self.target_scroll = max(
                    0,
                    min(
                        self._max_target_scroll(),
                        self.target_scroll - event.y,
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
        if self.engine.finished:
            if self._finish_rect().collidepoint(pos):
                self._accept_outcome()
            return
        if self._end_day_rect().collidepoint(pos):
            self._end_day()
            return
        if self._execute_rect().collidepoint(pos):
            self._execute_selected()
            return
        for rect, entry in self.target_rows:
            if rect.collidepoint(pos):
                node = entry.get("node")
                if node is not None:
                    self._select_target(node["id"])
                return
        for rect, option in self._action_row_rects():
            if rect.collidepoint(pos):
                self._select_action(option)
                return

    def _finish_rect(self):
        return pygame.Rect(BOTTOM_RECT.right - 210, BOTTOM_RECT.y + 6, 210, 40)

    def _end_day_rect(self):
        return pygame.Rect(BOTTOM_RECT.right - 210, BOTTOM_RECT.y + 6, 210, 40)

    def _execute_rect(self):
        return pygame.Rect(
            RIGHT_RECT.x + 16,
            RIGHT_RECT.bottom - 52,
            RIGHT_RECT.width - 32,
            38,
        )

    def _action_row_rects(self):
        options = self._action_options()
        visible = self._visible_action_rows()
        start = min(self.action_scroll, self._max_action_scroll())
        rows = []
        for index, option in enumerate(options[start : start + visible]):
            rect = pygame.Rect(
                MID_RECT.x + 8,
                MID_RECT.y + 142 + index * ACTION_ROW_H,
                MID_RECT.width - 16,
                ACTION_ROW_H - 4,
            )
            rows.append((rect, option))
        return rows

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

    def _clip_text(self, font, text, max_width):
        text = str(text or "")
        if font.size(text)[0] <= max_width:
            return text
        suffix = "..."
        while text and font.size(text + suffix)[0] > max_width:
            text = text[:-1]
        return text.rstrip() + suffix

    def _draw_top(self, screen):
        title = self.app.font_title.render(
            str(self.engine.config.get("title") or "Мир"), True, TEXT
        )
        screen.blit(title, (24, 10))
        subtitle = self.app.font_small.render(
            self._clip_text(
                self.app.font_small,
                self.engine.config.get("subtitle") or "",
                550,
            ),
            True,
            MUTED,
        )
        screen.blit(subtitle, (24, 44))
        office = self.engine.player_office()
        name = str(self.engine.profile.get("name") or "Действующее лицо")
        line = self._clip_text(
            self.app.font_body,
            "%s · %s" % (name, office.get("title", "—")),
            470,
        )
        screen.blit(
            self.app.font_body.render(line, True, (205, 218, 236)),
            (600, 14),
        )
        org = self._clip_text(
            self.app.font_small,
            "%s · %s"
            % (office.get("node_name", "—"), office.get("level_label", "—")),
            470,
        )
        screen.blit(self.app.font_small.render(org, True, MUTED), (600, 40))
        day = "День %d / %d · Действия %d / %d" % (
            self.engine.day,
            self.engine.days,
            self.engine.actions_left,
            self.engine.actions_per_day,
        )
        day_surf = self.app.font_small.render(day, True, WARN)
        screen.blit(day_surf, (WIDTH - 24 - day_surf.get_width(), 18))
        status = "Полномочия %.0f%% · ранг %d" % (
            100.0 * float(office.get("authority", 0.0)),
            int(office.get("rank", 99)),
        )
        status_surf = self.app.font_small.render(status, True, GOOD)
        screen.blit(status_surf, (WIDTH - 24 - status_surf.get_width(), 42))
        x = 24
        chip_w = (WIDTH - 48) // 4
        for key in ("standing", "influence", "favor", "evidence"):
            rect = pygame.Rect(x, 68, chip_w - 8, 26)
            pygame.draw.rect(screen, (16, 20, 28), rect, border_radius=4)
            value = float(self.engine.player_resources.get(key, 0.0))
            bar = pygame.Rect(rect.x + 2, rect.bottom - 4, rect.width - 4, 2)
            pygame.draw.rect(screen, (44, 54, 68), bar)
            pygame.draw.rect(
                screen,
                (118, 202, 156),
                pygame.Rect(bar.x, bar.y, int(bar.width * value), 2),
            )
            text = "%s %.0f%%" % (
                self.engine.stat_label(key),
                100.0 * value,
            )
            screen.blit(
                self.app.font_tiny.render(text, True, TEXT),
                (rect.x + 6, rect.y + 4),
            )
            x += chip_w

    def _draw_targets(self, screen):
        self._draw_panel(
            screen,
            LEFT_RECT,
            "МИР · ВЫБЕРИТЕ ЦЕЛЬ",
            len(self.engine.nodes),
        )
        visible = self._visible_target_rows()
        start = min(self.target_scroll, self._max_target_scroll())
        self.target_rows = []
        y = LEFT_RECT.y + 44
        for entry in self.entries[start : start + visible]:
            if entry.get("kind") == "header":
                screen.blit(
                    self.app.font_tiny.render(
                        str(entry.get("label", "")).upper(), True, WARN
                    ),
                    (LEFT_RECT.x + 12, y + 4),
                )
                y += NODE_ROW_H
                continue
            node = entry["node"]
            rect = pygame.Rect(
                LEFT_RECT.x + 6,
                y + 1,
                LEFT_RECT.width - 12,
                NODE_ROW_H - 2,
            )
            selected = node["id"] == self.selected_target_id
            player = node["id"] == self.engine.player_node_id
            if selected:
                pygame.draw.rect(screen, (38, 62, 88), rect, border_radius=4)
            else:
                pygame.draw.rect(screen, (25, 31, 42), rect, border_radius=4)
            indent = min(16, self.engine.node_depth(node["id"]) * 9)
            color = TEXT if selected else (190, 200, 214)
            label = self._clip_text(
                self.app.font_small,
                node["name"],
                rect.width - 20 - indent,
            )
            screen.blit(
                self.app.font_small.render(label, True, color),
                (rect.x + 8 + indent, rect.y + 2),
            )
            detail = "%s · %s" % (
                self.engine.domain_label(node["domain"]),
                self.engine.node_level_label(node),
            )
            if node.get("kind") == "asset":
                detail = "имущество · " + detail
            detail = self._clip_text(
                self.app.font_tiny,
                detail,
                rect.width - 20 - indent,
            )
            screen.blit(
                self.app.font_tiny.render(detail, True, MUTED),
                (rect.x + 8 + indent, rect.y + 16),
            )
            if player:
                screen.blit(
                    self.app.font_tiny.render("вы", True, GOOD),
                    (rect.right - 28, rect.y + 2),
                )
            self.target_rows.append((rect, entry))
            y += NODE_ROW_H
        if self.target_scroll < self._max_target_scroll():
            screen.blit(
                self.app.font_tiny.render(
                    "колесо — прокрутка мира", True, DIM
                ),
                (LEFT_RECT.x + 12, LEFT_RECT.bottom - 18),
            )

    def _draw_target_details(self, screen):
        node = self.engine.node(self.selected_target_id)
        if node is None:
            return
        x = MID_RECT.x + 12
        y = MID_RECT.y + 44
        screen.blit(
            self.app.font_small.render(str(node["name"]), True, TEXT),
            (x, y),
        )
        detail = "%s · %s · %s" % (
            self.engine.domain_label(node["domain"]),
            self.engine.node_level_label(node),
            self.engine.polities.get(node.get("polity"), {}).get(
                "label", node.get("polity") or "—"
            ),
        )
        screen.blit(
            self.app.font_tiny.render(detail, True, ACCENT), (x, y + 18)
        )
        stats = node.get("stats") or {}
        keys = (
            "power",
            "wealth",
            "legitimacy",
            "cohesion",
            "reach",
            "capacity",
        )
        for index, key in enumerate(keys):
            value = float(stats.get(key, 0.0))
            sx = x + (index % 3) * 120
            sy = y + 38 + (index // 3) * 16
            screen.blit(
                self.app.font_tiny.render(
                    "%s %.0f%%" % (self.engine.stat_label(key), 100.0 * value),
                    True,
                    DIM,
                ),
                (sx, sy),
            )
        screen.blit(
            self.app.font_tiny.render(
                "Отношение к вам: %+.0f%%"
                % (
                    100.0
                    * self.engine.relation(
                        self.engine.player_node_id, node["id"]
                    )
                ),
                True,
                WARN,
            ),
            (x, y + 74),
        )

    def _draw_actions(self, screen):
        self._draw_panel(screen, MID_RECT, "ДЕЙСТВИЯ · ВСЕ, С ПРИЧИНАМИ")
        self._draw_target_details(screen)
        for rect, option in self._action_row_rects():
            action = option["action"]
            selected = option["id"] == self.selected_action_id
            enabled = bool(option.get("enabled"))
            if selected:
                pygame.draw.rect(screen, (38, 62, 88), rect, border_radius=5)
            else:
                pygame.draw.rect(screen, (25, 31, 42), rect, border_radius=5)
            label = str(action.get("label") or option["id"])
            if option.get("self"):
                label += "  ·  личное"
            screen.blit(
                self.app.font_small.render(
                    label, True, TEXT if enabled else DIM
                ),
                (rect.x + 10, rect.y + 3),
            )
            detail = option.get("cost")
            if not enabled and option.get("reason"):
                detail = str(option["reason"])
            detail = self._clip_text(
                self.app.font_tiny, detail, rect.width - 20
            )
            screen.blit(
                self.app.font_tiny.render(
                    detail, True, MUTED if enabled else BAD
                ),
                (rect.x + 10, rect.y + 25),
            )
        if self.action_scroll < self._max_action_scroll():
            screen.blit(
                self.app.font_tiny.render(
                    "колесо — прокрутка действий", True, DIM
                ),
                (MID_RECT.x + 12, MID_RECT.bottom - 18),
            )

    def _draw_text_block(self, screen, y, heading, text, color, max_lines=4):
        screen.blit(
            self.app.font_small.render(heading, True, color),
            (RIGHT_RECT.x + 14, y),
        )
        y += 18
        if not text:
            return y
        lines = wrap_text(self.app.font_tiny, str(text), RIGHT_RECT.width - 28)
        for line in lines[:max_lines]:
            screen.blit(
                self.app.font_tiny.render(line, True, (184, 194, 210)),
                (RIGHT_RECT.x + 14, y),
            )
            y += 13
        return y + 4

    def _draw_effects_line(self, screen, y, effects):
        if not effects:
            return y
        text = " · ".join(str(item) for item in effects)
        return self._draw_text_block(screen, y, "Сдвиги", text, GOOD, 1)

    def _draw_preview(self, screen):
        self._draw_panel(screen, RIGHT_RECT, "ПОСЛЕДСТВИЯ")
        y = RIGHT_RECT.y + 46
        action = self.engine.actions.get(self.selected_action_id)
        target = self.engine.node(self.selected_target_id)
        if action is not None:
            preview = self.engine.preview(
                action["id"], self.selected_target_id
            )
            target_node = preview.get("target")
            target_detail = preview.get("target_label", "—")
            if target_node is not None:
                target_detail = "%s · %s" % (
                    target_node["name"],
                    self.engine.node_level_label(target_node),
                )
            y = self._draw_text_block(
                screen,
                y,
                "Цель",
                target_detail,
                TEXT,
                1,
            )
            y = self._draw_text_block(
                screen,
                y,
                "Плата",
                preview.get("cost") or "без прямой платы",
                WARN,
                1,
            )
            if preview.get("enabled"):
                if preview.get("immediate"):
                    y = self._draw_effects_line(
                        screen, y, preview.get("immediate")
                    )
                success = preview.get("success_text") or ""
                if success:
                    y = self._draw_text_block(
                        screen,
                        y,
                        "Успех — %.0f%%"
                        % (100.0 * float(preview.get("success_chance", 0.0))),
                        success,
                        GOOD,
                        2,
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
                        % (100.0 * float(preview.get("failure_chance", 0.0))),
                        failure,
                        BAD,
                        2,
                    )
                    y = self._draw_effects_line(
                        screen, y, preview.get("failure_effects")
                    )
            else:
                y = self._draw_text_block(
                    screen,
                    y,
                    "Недоступно",
                    preview.get("reason") or "",
                    BAD,
                    2,
                )
            self._draw_button(
                screen,
                self._execute_rect(),
                str(action.get("label", "Совершить")),
                preview.get("enabled"),
                accent=True,
            )
            self._draw_log(screen, RIGHT_RECT.y + 352)
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
                4,
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
                "Слева выберите структуру. В центре видны все действия, "
                "включая недоступные с причиной. Справа — цена, успех, "
                "провал и след. Ваша должность даёт полномочия, но не "
                "отменяет интересы других автоматов.",
                MUTED,
                6,
            )
        if self.message:
            y = self._draw_text_block(
                screen, y, "Замечание", self.message, BAD, 2
            )
        self._draw_log(screen, RIGHT_RECT.y + 322)

    def _draw_log(self, screen, y):
        screen.blit(
            self.app.font_tiny.render("ЖУРНАЛ МИРА", True, WARN),
            (RIGHT_RECT.x + 14, y),
        )
        y += 17
        entries = self.engine.log[-7:]
        for item in entries:
            text = "Д%d: %s" % (item.get("day", 0), item.get("text", ""))
            lines = wrap_text(self.app.font_tiny, text, RIGHT_RECT.width - 28)
            for line in lines[:1]:
                screen.blit(
                    self.app.font_tiny.render(line, True, DIM),
                    (RIGHT_RECT.x + 14, y),
                )
                y += 13
            if y > RIGHT_RECT.bottom - 66:
                break

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
            "Слева — цель · в центре — все действия с причинами · справа — "
            "последствия и журнал. Колесо — прокрутка."
        )
        screen.blit(
            self.app.font_tiny.render(hint, True, MUTED),
            (BOTTOM_RECT.x + 14, BOTTOM_RECT.y + 8),
        )
        screen.blit(
            self.app.font_tiny.render(
                "Личные ресурсы: репутация, влияние, связи, доказательства.",
                True,
                DIM,
            ),
            (BOTTOM_RECT.x + 14, BOTTOM_RECT.y + 26),
        )
        if self.engine.finished:
            label = (
                "Принять развязку"
                if self.engine.outcome in ("win", "lose")
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
                True,
            )

    def draw(self, screen):
        screen.fill((12, 15, 22))
        self._draw_top(screen)
        self._draw_targets(screen)
        self._draw_actions(screen)
        self._draw_preview(screen)
        self._draw_bottom(screen)


__all__ = ["WorldScreen"]
