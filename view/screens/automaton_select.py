import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import wrap_text
from view.support.log_journal import get_logger

logger = get_logger("view.automaton_select")

WIDTH, HEIGHT = 1280, 720
LEFT_RECT = pygame.Rect(24, 96, 470, 564)
RIGHT_RECT = pygame.Rect(510, 96, 746, 564)
ROW_H = 32
PANEL_BG = (20, 24, 34, 238)
PANEL_BORDER = (58, 70, 92)
TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
BAD = (226, 112, 112)
WARN = (230, 184, 96)


class AutomatonSelectScreen(BaseScreen):

    escape_action = "none"

    def __init__(self, app, config_path=None, engine=None):
        super().__init__(app)
        from campaign.world import (
            build_player_profile,
            load_biography,
            load_world,
            WorldEngine,
        )

        storyline = {}
        interp = getattr(app, "storyline_interpreter", None)
        if interp is not None:
            storyline = interp.storyline or {}
        # Повторное трудоустройство (§7 №29): экран может работать поверх
        # уже существующего мира. Тогда он не создаёт новый `WorldEngine`,
        # а только выбирает новую должность для того же героя.
        self.reemployment = engine is not None and not engine.finished
        if self.reemployment:
            self.engine = engine
            self.config = engine.config
            self.profile = engine.profile
            self.seed = engine.seed
            self.config_path = config_path
        else:
            self.config_path = (
                config_path or storyline.get("world_path") or None
            )
            self.config = load_world(self.config_path)
            self.profile = getattr(app, "player_profile", None)
            if not self.profile:
                biography = load_biography(
                    storyline.get("biography_path") or None
                )
                variables = interp.variables if interp is not None else {}
                self.profile = build_player_profile(
                    variables,
                    biography=biography,
                    seed=app._campaign_seed(storyline),
                )
                app.player_profile = self.profile
            self.engine = WorldEngine(
                self.config,
                profile=self.profile,
                seed=app._campaign_seed(storyline),
            )
            self.seed = app._campaign_seed(storyline)
        self.selected_node_id = None
        self.selected_office_id = None
        self.message = ""
        self.scroll = 0
        self.entries = self._build_entries()
        self.office_rows = []
        self.office_scroll = 0
        self.node_rows = []
        self._select_initial_node()
        logger.info(
            "Выбор автомата: узлов=%d, профиль=%s",
            len(self.config["nodes"]),
            self.profile.get("name"),
        )

    def _build_entries(self):
        domains = {item["id"]: item for item in self.config.get("domains", [])}
        polities = self.config.get("polities", [])
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
                    "detail": polity.get("kind", ""),
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
                {
                    "kind": "header",
                    "label": polity_id or "Вне политий",
                    "detail": "",
                }
            )
            for node in nodes:
                entries.append({"kind": "node", "node": node})
        return entries

    def _select_initial_node(self):
        if not self.entries:
            return
        for entry in self.entries:
            if entry.get("kind") == "node":
                self._select_node(entry["node"]["id"])
                return

    def _visible_rows(self):
        return max(1, (LEFT_RECT.height - 50) // ROW_H)

    def _max_scroll(self):
        return max(0, len(self.entries) - self._visible_rows())

    def _select_node(self, node_id):
        self.selected_node_id = node_id
        self.selected_office_id = None
        self.office_scroll = 0
        self.message = ""
        self.office_rows = self.engine.office_options(node_id)
        enabled = [item for item in self.office_rows if item.get("enabled")]
        if enabled:
            self.selected_office_id = enabled[0]["id"]
        logger.debug("Выбрана структура: %s", node_id)

    def _select_office(self, office_id):
        for item in self.office_rows:
            if item["id"] == office_id:
                if not item.get("enabled"):
                    self.message = str(item.get("reason") or "Недоступно")
                    return
                self.selected_office_id = office_id
                self.message = ""
                logger.debug("Выбрана должность: %s", office_id)
                return

    def _start(self):
        from campaign.world import WorldEngine

        if not self.selected_node_id or not self.selected_office_id:
            self.message = "Выберите доступную должность."
            return
        if self.reemployment:
            # Смена роли внутри существующего мира: состояние героя,
            # организации, дня и болезни сохраняется (§7 №29).
            result = self.engine.attach(
                self.selected_node_id, self.selected_office_id
            )
            if not result.get("ok"):
                self.message = str(
                    result.get("reason") or "Не удалось занять должность."
                )
                return
            self.engine.dismissed = False
        else:
            self.engine = WorldEngine(
                self.config,
                profile=self.profile,
                node_id=self.selected_node_id,
                office_id=self.selected_office_id,
                seed=self.seed,
            )
            if not self.engine.attached:
                self.message = "Не удалось занять должность."
                return
        self.app.world = self.engine
        self.app.world_config = self.config
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is not None:
            office = self.engine.player_office()
            node = self.engine.node(self.selected_node_id)
            interp.state["world"] = self.engine.to_dict()
            interp.set_variable("player_office", office["title"])
            interp.set_variable("player_node_name", office["node_name"])
            interp.set_variable("player_domain", office["domain_label"])
            interp.set_variable("player_level", office["level_label"])
            interp.set_variable(
                "player_polity",
                (node or {}).get("polity", ""),
            )
            interp.set_variable("world_day", self.engine.day)
            interp.set_variable("world_days", self.engine.days)
            interp.set_variable(
                "world_actions_per_day", self.engine.actions_per_day
            )
            interp.set_variable(
                "world_standing",
                self.engine.player_resources["standing"],
            )
            interp.set_variable("world_dismissed", False)
            if not self.reemployment:
                self.app._play_next_scene()
        if self.reemployment:
            from .world_screen import WorldScreen

            self.app.manager.replace_all(WorldScreen(self.app, self.engine))
        logger.info(
            "Служба начата: %s / %s (повторно=%s)",
            self.selected_node_id,
            self.selected_office_id,
            self.reemployment,
        )

    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if LEFT_RECT.collidepoint(pos):
                self.scroll = max(
                    0, min(self._max_scroll(), self.scroll - event.y)
                )
            elif RIGHT_RECT.collidepoint(pos):
                self.office_scroll = max(
                    0,
                    min(
                        max(0, len(self.office_rows) - 4),
                        self.office_scroll - event.y,
                    ),
                )
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
            self._start()
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        if self._start_rect().collidepoint(event.pos):
            self._start()
            return
        for rect, entry in self.node_rows:
            if rect.collidepoint(event.pos):
                node = entry.get("node")
                if node is not None:
                    self._select_node(node["id"])
                return
        for rect, option in self._office_rows_rects():
            if rect.collidepoint(event.pos):
                self._select_office(option["id"])
                return

    def _start_rect(self):
        return pygame.Rect(
            RIGHT_RECT.x + 16,
            RIGHT_RECT.bottom - 52,
            RIGHT_RECT.width - 32,
            38,
        )

    def _office_rows_rects(self):
        rows = []
        visible = self.office_rows[self.office_scroll : self.office_scroll + 4]
        top = RIGHT_RECT.y + 274
        for index, item in enumerate(visible):
            rect = pygame.Rect(
                RIGHT_RECT.x + 12,
                top + index * 60,
                RIGHT_RECT.width - 24,
                54,
            )
            rows.append((rect, item))
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

    def _draw_tree(self, screen):
        self._draw_panel(
            screen,
            LEFT_RECT,
            "МИР И ЕГО СТРУКТУРЫ",
            len(self.config["nodes"]),
        )
        visible = self._visible_rows()
        start = min(self.scroll, self._max_scroll())
        self.node_rows = []
        y = LEFT_RECT.y + 46
        for entry in self.entries[start : start + visible]:
            if entry.get("kind") == "header":
                screen.blit(
                    self.app.font_tiny.render(
                        str(entry.get("label", "")).upper(), True, WARN
                    ),
                    (LEFT_RECT.x + 12, y + 4),
                )
                y += ROW_H
                continue
            node = entry["node"]
            rect = pygame.Rect(
                LEFT_RECT.x + 6,
                y + 1,
                LEFT_RECT.width - 12,
                ROW_H - 2,
            )
            selected = node["id"] == self.selected_node_id
            if selected:
                pygame.draw.rect(screen, (38, 62, 88), rect, border_radius=4)
            else:
                pygame.draw.rect(screen, (25, 31, 42), rect, border_radius=4)
            indent = min(18, self.engine.node_depth(node["id"]) * 10)
            color = TEXT if selected else (190, 200, 214)
            screen.blit(
                self.app.font_small.render(str(node["name"]), True, color),
                (rect.x + 8 + indent, rect.y + 2),
            )
            detail = "%s · %s" % (
                self.engine.domain_label(node["domain"]),
                self.engine.node_level_label(node),
            )
            if node.get("kind") == "asset":
                detail = "имущество · " + detail
            screen.blit(
                self.app.font_tiny.render(detail, True, MUTED),
                (rect.x + 8 + indent, rect.y + 17),
            )
            self.node_rows.append((rect, entry))
            y += ROW_H
        if self.scroll < self._max_scroll():
            screen.blit(
                self.app.font_tiny.render(
                    "колесо — прокрутка мира", True, DIM
                ),
                (LEFT_RECT.x + 12, LEFT_RECT.bottom - 18),
            )

    def _draw_profile(self, screen):
        x = RIGHT_RECT.x + 16
        y = RIGHT_RECT.y + 48
        screen.blit(
            self.app.font_body.render(
                str(self.profile.get("name") or "Новый герой"), True, TEXT
            ),
            (x, y),
        )
        summary = " · ".join(
            item
            for item in (
                self.profile.get("origin"),
                self.profile.get("vocation"),
                self.profile.get("reputation"),
            )
            if item
        )
        for line in wrap_text(
            self.app.font_tiny, summary, RIGHT_RECT.width - 32
        )[:1]:
            screen.blit(
                self.app.font_tiny.render(line, True, MUTED), (x, y + 22)
            )
        values = ", ".join(self.profile.get("values") or [])
        screen.blit(
            self.app.font_tiny.render("Ценности: %s" % values, True, WARN),
            (x, y + 38),
        )

    def _draw_node(self, screen):
        node = self.engine.node(self.selected_node_id)
        if node is None:
            return
        x = RIGHT_RECT.x + 16
        y = RIGHT_RECT.y + 114
        screen.blit(
            self.app.font_body.render(str(node["name"]), True, TEXT),
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
            self.app.font_tiny.render(detail, True, ACCENT), (x, y + 22)
        )
        desc_lines = wrap_text(
            self.app.font_tiny,
            node.get("description", ""),
            RIGHT_RECT.width - 32,
        )
        for index, line in enumerate(desc_lines[:2]):
            screen.blit(
                self.app.font_tiny.render(line, True, MUTED),
                (x, y + 40 + index * 14),
            )
        stats = node.get("stats") or {}
        sx = x
        sy = y + 74
        for key in ("power", "wealth", "legitimacy", "cohesion", "reach"):
            value = float(stats.get(key, 0.0))
            label = self.engine.stat_label(key)
            screen.blit(
                self.app.font_tiny.render(
                    "%s %.0f%%" % (label, 100.0 * value), True, DIM
                ),
                (sx, sy),
            )
            sx += 126
        screen.blit(
            self.app.font_tiny.render(
                "Интересы: %s"
                % ", ".join(
                    "%s %.0f%%"
                    % (self.engine.domain_label(key), 100.0 * float(value))
                    for key, value in (node.get("interests") or {}).items()
                ),
                True,
                DIM,
            ),
            (x, sy + 18),
        )
        screen.blit(
            self.app.font_small.render("ДОЛЖНОСТИ", True, WARN),
            (x, sy + 44),
        )

    def _draw_offices(self, screen):
        for rect, option in self._office_rows_rects():
            selected = option["id"] == self.selected_office_id
            enabled = bool(option.get("enabled"))
            if selected:
                pygame.draw.rect(screen, (38, 62, 88), rect, border_radius=5)
            else:
                pygame.draw.rect(screen, (25, 31, 42), rect, border_radius=5)
            color = TEXT if enabled else DIM
            screen.blit(
                self.app.font_small.render(
                    str(option.get("label")), True, color
                ),
                (rect.x + 10, rect.y + 4),
            )
            detail = "полномочия %.0f%% · ранг %d" % (
                100.0 * float(option.get("authority", 0.0)),
                int(option.get("rank", 99)),
            )
            if not enabled:
                detail = "недоступно: %s" % (option.get("reason") or "")
            screen.blit(
                self.app.font_tiny.render(
                    detail, True, MUTED if enabled else BAD
                ),
                (rect.x + 10, rect.y + 26),
            )
            if selected:
                screen.blit(
                    self.app.font_tiny.render("выбрано", True, GOOD),
                    (rect.right - 60, rect.y + 4),
                )
        if len(self.office_rows) > 4:
            screen.blit(
                self.app.font_tiny.render(
                    "колесо — прокрутка должностей", True, DIM
                ),
                (RIGHT_RECT.x + 12, RIGHT_RECT.bottom - 74),
            )

    def _draw_button(self, screen, rect, label, enabled=True):
        pos = pygame.mouse.get_pos()
        hover = enabled and rect.collidepoint(pos)
        fill = (46, 58, 72) if enabled else (30, 34, 42)
        if hover:
            fill = (72, 136, 202)
        pygame.draw.rect(screen, fill, rect, border_radius=6)
        pygame.draw.rect(screen, PANEL_BORDER, rect, 1, border_radius=6)
        surf = self.app.font_small.render(
            str(label), True, TEXT if enabled else DIM
        )
        screen.blit(surf, surf.get_rect(center=rect.center))

    def draw(self, screen):
        screen.fill((12, 15, 22))
        title = self.app.font_title.render("Кому вы служите?", True, TEXT)
        screen.blit(title, (24, 12))
        subtitle = self.app.font_small.render(
            "Выберите структуру и должность. Уровень определяет полномочия, "
            "а не право распоряжаться всем автоматом.",
            True,
            MUTED,
        )
        screen.blit(subtitle, (24, 50))
        self._draw_tree(screen)
        self._draw_profile(screen)
        self._draw_node(screen)
        self._draw_offices(screen)
        if self.message:
            screen.blit(
                self.app.font_tiny.render(self.message, True, BAD),
                (RIGHT_RECT.x + 16, RIGHT_RECT.bottom - 68),
            )
        self._draw_button(
            screen,
            self._start_rect(),
            "Принять должность",
            bool(self.selected_node_id and self.selected_office_id),
        )


__all__ = ["AutomatonSelectScreen"]
