import pygame

from campaign.clock import CampaignClock, background_pause_reason
from campaign.world import CHARACTER_CIRCLES, ORGANIZATION_CATEGORIES
from ..support import world_text
from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import wrap_text
from ..ui.world_art import WorldArt
from view.support.log_journal import get_logger

logger = get_logger("view.world")

WIDTH, HEIGHT = 1280, 720
HEADER_H = 92
MAIN_TAB_Y = 96
MAIN_TAB_H = 34
SUB_TAB_Y = 136
SUB_TAB_H = 28
CONTENT_Y = 170
CONTENT_BOTTOM = 660
LEFT_RECT = pygame.Rect(16, CONTENT_Y, 342, CONTENT_BOTTOM - CONTENT_Y)
MID_RECT = pygame.Rect(366, CONTENT_Y, 448, CONTENT_BOTTOM - CONTENT_Y)
CONTENT_RECT = pygame.Rect(
    16, CONTENT_Y, MID_RECT.right - LEFT_RECT.left, CONTENT_BOTTOM - CONTENT_Y
)
RIGHT_RECT = pygame.Rect(822, CONTENT_Y, 442, CONTENT_BOTTOM - CONTENT_Y)
BOTTOM_RECT = pygame.Rect(16, 668, 1248, 36)
LIST_ROW_H = 64
ACTION_ROW_H = 44
PANEL_BG = (16, 21, 31, 235)
PANEL_BG_SOFT = (20, 26, 38, 210)
PANEL_BORDER = (58, 70, 92)
TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
BAD = (226, 112, 112)
WARN = (230, 184, 96)

MAIN_TABS = (
    ("characters", "ПЕРСОНАЖИ"),
    ("organizations", "ОРГАНИЗАЦИИ"),
    ("personality", "ЛИЧНОСТЬ"),
)
SUB_TABS = {
    "characters": (
        ("close", "Ближний круг"),
        ("companion", "Попутчики"),
        ("acquaintance", "Знакомства"),
    ),
    "organizations": (
        ("allied", "Союзные"),
        ("hostile", "Враждебные"),
        ("neutral", "Нейтральные"),
    ),
    "personality": (
        ("stats", "Характеристики"),
        ("skills", "Древо навыков"),
        ("items", "Предметы"),
    ),
}


class WorldScreen(BaseScreen):

    show_time_hud = False
    escape_action = "none"

    def __init__(self, app, engine):
        super().__init__(app)
        self.engine = engine
        self.art = WorldArt(engine.config.get("id", "world"))
        self.main_tab = "organizations"
        self.subtab_index = {
            "characters": 0,
            "organizations": 0,
            "personality": 0,
        }
        self.selected_target_id = self._initial_target_id(engine)
        self.selected_character_id = None
        self.selected_skill_id = None
        self.selected_item_id = None
        self.action_context = "organization"
        self.selected_action_id = None
        self.list_scroll = 0
        self.action_scroll = 0
        self.message = ""
        self.last_result = engine.last_result
        # Live-режим обучаемого агента (P0.4): среда оборачивает тот же
        # `WorldEngine`, что и ручное управление. Автопилот делает один
        # шаг политики за интервал, поэтому UI остаётся отзывчивым, а
        # журнал/сейв видят те же действия, что и игрок.
        self.autopilot = False
        self.autopilot_policy = None
        self.campaign_env = None
        self.autopilot_timer = 0.0
        self.autopilot_interval = 0.45
        # Фоновые/оффлайн-часы (§7 №31). Экран только переводит реальные
        # секунды в дни и вызывает `advance_days`; правила мира не меняются.
        self.clock = CampaignClock(
            seconds_per_day=engine.seconds_per_day,
            max_catchup_days=engine.max_offline_days,
            paused=True,
        )
        self.main_tab_rects = []
        self.subtab_rects = []
        self.entity_rows = []
        self.action_rows = []
        self.skill_rows = []
        self.item_rows = []
        self._overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self._overlay.fill((7, 10, 16, 150))
        self._sync_storyline()
        logger.info(
            "Экран мира: день=%d, узлов=%d, действий=%d, персонажей=%d",
            engine.day,
            len(engine.nodes),
            len(engine.actions),
            len(engine.characters),
        )

    @staticmethod
    def _initial_target_id(engine):
        if not engine.attached:
            return engine.player_node_id or (
                engine.node_order[0] if engine.node_order else ""
            )
        for node in engine.organization_groups().get("allied", ()):
            if node["id"] == engine.player_node_id:
                continue
            options = engine.action_options(node["id"])
            if any(
                option.get("enabled")
                and not (option.get("action") or {}).get("career")
                for option in options
            ):
                return node["id"]
        return engine.player_node_id or (
            engine.node_order[0] if engine.node_order else ""
        )

    def _sync_storyline(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return
        interp.state["world"] = self.engine.to_dict()
        interp.set_variable("world_day", self.engine.day)
        interp.set_variable("world_days", self.engine.days)
        interp.set_variable("world_actions_left", self.engine.actions_left)
        interp.set_variable("world_outcome", self.engine.outcome or "")
        interp.set_variable("world_ending", self.engine.ending or "")
        interp.set_variable("world_infinite", self.engine.infinite)
        interp.set_variable("world_dismissed", self.engine.dismissed)
        for key, value in self.engine.player_resources.items():
            interp.set_variable("world_%s" % key, value)

    def _active_group_id(self, tab=None):
        tab = tab or self.main_tab
        index = self.subtab_index.get(tab, 0)
        options = SUB_TABS.get(tab) or ()
        if not options:
            return ""
        return options[min(index, len(options) - 1)][0]

    def _active_organizations(self):
        category = self._active_group_id("organizations")
        return self.engine.organization_groups().get(category, [])

    def _active_characters(self):
        circle = self._active_group_id("characters")
        return self.engine.characters_by_circle(circle)

    def _visible_entity_rows(self):
        return max(1, (LEFT_RECT.height - 56) // LIST_ROW_H)

    def _visible_action_rows(self):
        return max(1, (MID_RECT.height - 220) // ACTION_ROW_H)

    def _max_entity_scroll(self, rows=None):
        if rows is None:
            rows = self._entity_rows()
        return max(0, len(rows) - self._visible_entity_rows())

    def _max_action_scroll(self):
        return max(
            0,
            len(self._action_options()) - self._visible_action_rows(),
        )

    def _entity_rows(self):
        if self.main_tab == "characters":
            return self._active_characters()
        if self.main_tab == "organizations":
            return self._active_organizations()
        return []

    def _action_options(self):
        if self.action_context == "character":
            if not self.selected_character_id:
                return []
            options = self.engine.character_action_options(
                self.selected_character_id
            )
        elif self.action_context == "organization":
            if not self.selected_target_id:
                return []
            options = self.engine.action_options(self.selected_target_id)
        else:
            return []
        return sorted(
            options, key=lambda option: 0 if option.get("enabled") else 1
        )

    def _option_chance(self, option):
        action = option.get("action") or {}
        success = action.get("success") or {}
        return float(
            option.get("chance")
            or success.get("chance")
            or action.get("success_chance", 0.6)
        )

    def _select_target(self, node_id):
        if (
            node_id == self.selected_target_id
            and self.action_context == "organization"
        ):
            return
        self.main_tab = "organizations"
        self.action_context = "organization"
        self.selected_target_id = node_id
        self.selected_character_id = None
        self.selected_action_id = None
        self.action_scroll = 0
        self.last_result = None
        self.message = ""
        logger.debug("Цель мира выбрана: %s", node_id)

    def _select_character(self, character_id):
        if (
            character_id == self.selected_character_id
            and self.action_context == "character"
        ):
            return
        self.main_tab = "characters"
        self.action_context = "character"
        self.selected_character_id = character_id
        self.selected_action_id = None
        self.action_scroll = 0
        self.last_result = None
        self.message = ""
        logger.debug("Собеседник выбран: %s", character_id)

    def _select_skill(self, skill_id):
        self.main_tab = "personality"
        self.subtab_index["personality"] = 1
        self.action_context = "personality"
        self.selected_skill_id = skill_id
        self.selected_item_id = None
        self.selected_action_id = None
        self.last_result = None
        self.message = ""

    def _select_item(self, item_id):
        self.main_tab = "personality"
        self.subtab_index["personality"] = 2
        self.action_context = "personality"
        self.selected_item_id = item_id
        self.selected_skill_id = None
        self.selected_action_id = None
        self.last_result = None
        self.message = ""

    def _select_action(self, option):
        if not option.get("enabled"):
            self.message = str(
                world_text.reason_text(option.get("reason"))
                or "Действие недоступно"
            )
            return
        self.selected_action_id = option["id"]
        self.last_result = None
        self.message = ""
        logger.debug("Действие мира выбрано: %s", option["id"])

    def _execute_selected(self):
        if not self.selected_action_id:
            return
        action_id = self.selected_action_id
        if self.action_context == "character":
            result = self.engine.execute_character_action(
                action_id, self.selected_character_id
            )
        else:
            previous_node = self.engine.player_node_id
            result = self.engine.execute(action_id, self.selected_target_id)
        if not result.get("ok"):
            self.message = str(result.get("reason") or "Действие недоступно")
            return
        self.last_result = result
        self.selected_action_id = None
        self.message = ""
        if self.action_context == "organization":
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

    # ------------------------------------------------------------------
    # Live-режим обучаемого агента (P0.4)
    # ------------------------------------------------------------------

    def _autopilot_env(self):
        """Лениво подключить `CampaignEnv` к живому движку экрана."""
        from campaign.env import CampaignEnv

        if self.campaign_env is None:
            self.campaign_env = CampaignEnv(engine=self.engine)
        elif self.campaign_env.engine is not self.engine:
            self.campaign_env.attach(self.engine)
        return self.campaign_env

    def _autopilot_policy_instance(self):
        if self.autopilot_policy is None:
            checkpoint = str(getattr(self.app, "checkpoint", "") or "")
            if checkpoint:
                from agents import load_policy

                try:
                    self.autopilot_policy = load_policy(
                        checkpoint, seed=int(self.engine.seed)
                    )
                    logger.info(
                        "Автопилот: чекпойнт загружен (%s)", checkpoint
                    )
                except Exception as error:  # noqa: BLE001 — игра не падает
                    logger.warning(
                        "Автопилот: чекпойнт %s не загружен (%r); "
                        "используется новая BDI",
                        checkpoint,
                        error,
                    )
                    self.autopilot_policy = None
            if self.autopilot_policy is None:
                from agents import BDIPolicy

                self.autopilot_policy = BDIPolicy(
                    seed=int(self.engine.seed)
                )
        return self.autopilot_policy

    def _toggle_autopilot(self):
        if self.engine.finished or not self.engine.attached:
            self.autopilot = False
            self.message = "Автопилот недоступен: кампания не активна."
            return
        self.autopilot = not self.autopilot
        self.autopilot_timer = 0.0
        self.selected_action_id = None
        if self.autopilot:
            self._autopilot_env()
            self._autopilot_policy_instance()
            self.message = "Автопилот включён: политика BDI."
        else:
            self.message = "Автопилот выключен."
        logger.info("Автопилот кампании: %s", self.autopilot)

    def _autopilot_step(self):
        """Один шаг политики на живом движке; возвращает info или None."""
        if not self.autopilot:
            return None
        engine = self.engine
        if engine.finished or not engine.attached:
            self.autopilot = False
            return None
        env = self._autopilot_env()
        try:
            _obs, _reward, done, truncated, info = env.advance(
                self._autopilot_policy_instance(), explore=False
            )
        except RuntimeError as error:
            self.autopilot = False
            self.message = "Автопилот остановлен: %s" % error
            return None
        result = info.get("result") or {}
        if result.get("ok"):
            self.last_result = engine.last_result
            self.selected_action_id = None
        self._sync_storyline()
        if done or truncated:
            self.autopilot = False
            if done:
                self.message = "Автопилот: кампания завершена."
            else:
                self.message = "Автопилот: достигнут горизонт дней."
        return info

    def update(self, dt):
        """Фоновая симуляция при свёрнутом/неактивном окне (§7 №31).

        Пока окно активно, дни идут только по кнопке «Завершить день».
        В фоне реальные секунды копятся в `CampaignClock` и переводятся в
        ограниченный догон `WorldEngine.advance_days()`. Критическое
        состояние (смерть, болезнь, завершённый сюжет, отсутствие
        должности) ставит часы на паузу.
        """
        engine = self.engine
        if engine.finished or not engine.attached:
            self.autopilot = False
            self.clock.reset_accumulator()
            self.clock.pause()
            self.clock.pause_reason = (
                "finished" if engine.finished else "unattached"
            )
            return
        if self.autopilot:
            # Автопилот работает и в активном окне: интервал — реальные
            # секунды, а не игровые дни, поэтому смена скорости часов его
            # не ускоряет.
            self.autopilot_timer += max(0.0, float(dt))
            if self.autopilot_timer >= self.autopilot_interval:
                self.autopilot_timer = 0.0
                self._autopilot_step()
            if engine.finished or not engine.attached:
                return
        if getattr(self.app, "active", True):
            self.clock.reset_accumulator()
            self.clock.resume()
            self.clock.pause_reason = ""
            return
        reason = background_pause_reason(engine)
        if reason:
            self.clock.reset_accumulator()
            self.clock.pause()
            self.clock.pause_reason = reason
            return
        self.clock.resume()
        self.clock.pause_reason = ""
        days = self.clock.advance(dt)
        if days <= 0:
            return
        results = engine.advance_days(
            days, max_days=self.clock.max_catchup_days
        )
        if not results:
            return
        self.last_result = engine.last_result
        self.selected_action_id = None
        self.message = "Фон: прошло дней — %d." % len(results)
        self._sync_storyline()
        logger.info(
            "Фоновый догон: %d дн.; день=%d, завершено=%s",
            len(results),
            engine.day,
            engine.finished,
        )

    def _choose_office(self):
        open_selection = getattr(self.app, "open_office_selection", None)
        if open_selection is None:
            self.message = "Выбор должности недоступен."
            return
        open_selection(self.engine)
        logger.info("Открыт выбор новой должности после смены роли")

    def _accept_outcome(self):
        if self.engine.outcome in ("win", "lose"):
            self.app.finish_storyline_outcome(self.engine.outcome)
            logger.info("Принят исход мира: %s", self.engine.outcome)
            return
        if self.engine.ending == "neutral":
            # Нарративный финал без победы/поражения (§7 №30): сюжет не
            # получает win/lose, глава просто остаётся завершённой.
            self.message = "Глава завершена: история продолжается в мире."
            logger.info("Принят нейтральный финал мира")

    def _set_main_tab(self, tab):
        if tab not in SUB_TABS:
            return
        self.main_tab = tab
        self.list_scroll = 0
        self.action_scroll = 0
        self.selected_action_id = None
        self.last_result = None
        self.message = ""
        if tab == "personality":
            self.action_context = "personality"
            self.selected_skill_id = None
            self.selected_item_id = None
            return
        self._apply_group_selection()

    def _set_subtab(self, index):
        options = SUB_TABS.get(self.main_tab) or ()
        if not (0 <= index < len(options)):
            return
        self.subtab_index[self.main_tab] = index
        self.list_scroll = 0
        self.action_scroll = 0
        self.selected_action_id = None
        self.last_result = None
        self.message = ""
        if self.main_tab == "personality":
            self.action_context = "personality"
            if index == 1:
                self.selected_item_id = None
            elif index == 2:
                self.selected_skill_id = None
            else:
                self.selected_skill_id = None
                self.selected_item_id = None
            return
        self._apply_group_selection()

    def _apply_group_selection(self):
        if self.main_tab == "characters":
            self.action_context = "character"
            rows = self._active_characters()
            ids = {item["id"] for item in rows}
            if rows and self.selected_character_id not in ids:
                self.selected_character_id = rows[0]["id"]
            if not rows:
                self.selected_character_id = None
            return
        if self.main_tab == "organizations":
            self.action_context = "organization"
            rows = self._active_organizations()
            ids = {item["id"] for item in rows}
            if rows and self.selected_target_id not in ids:
                self.selected_target_id = rows[0]["id"]
            if not rows:
                self.selected_target_id = None
            self.selected_character_id = None

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_a:
            self._toggle_autopilot()
            return
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if LEFT_RECT.collidepoint(pos) and self.main_tab != "personality":
                rows = self._entity_rows()
                self.list_scroll = max(
                    0,
                    min(
                        self._max_entity_scroll(rows),
                        self.list_scroll - event.y,
                    ),
                )
            elif MID_RECT.collidepoint(pos) and self.main_tab != "personality":
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
        if not self.engine.attached:
            if self._office_rect().collidepoint(pos):
                self._choose_office()
            return
        if self._autopilot_rect().collidepoint(pos):
            self._toggle_autopilot()
            return
        if self._end_day_rect().collidepoint(pos):
            self._end_day()
            return
        for rect, tab in self.main_tab_rects:
            if rect.collidepoint(pos):
                self._set_main_tab(tab)
                return
        for rect, index in self.subtab_rects:
            if rect.collidepoint(pos):
                self._set_subtab(index)
                return
        if self._execute_rect().collidepoint(pos):
            self._execute_selected()
            return
        for rect, kind, entity_id in self.entity_rows:
            if not rect.collidepoint(pos):
                continue
            if kind == "character":
                self._select_character(entity_id)
            else:
                self._select_target(entity_id)
            return
        for rect, option in self.action_rows:
            if rect.collidepoint(pos):
                self._select_action(option)
                return
        for rect, skill_id in self.skill_rows:
            if rect.collidepoint(pos):
                self._select_skill(skill_id)
                return
        for rect, item_id in self.item_rows:
            if rect.collidepoint(pos):
                self._select_item(item_id)
                return

    def _finish_rect(self):
        return pygame.Rect(BOTTOM_RECT.right - 210, BOTTOM_RECT.y + 3, 200, 30)

    def _end_day_rect(self):
        return pygame.Rect(BOTTOM_RECT.right - 210, BOTTOM_RECT.y + 3, 200, 30)

    def _autopilot_rect(self):
        return pygame.Rect(
            BOTTOM_RECT.right - 430, BOTTOM_RECT.y + 3, 210, 30
        )

    def _office_rect(self):
        return pygame.Rect(BOTTOM_RECT.right - 210, BOTTOM_RECT.y + 3, 200, 30)

    def _execute_rect(self):
        return pygame.Rect(
            RIGHT_RECT.x + 14,
            RIGHT_RECT.y + 330,
            RIGHT_RECT.width - 28,
            38,
        )

    def _draw_panel(self, screen, rect, title, count=None, accent=ACCENT):
        surf = pygame.Surface(rect.size, pygame.SRCALPHA)
        surf.fill(PANEL_BG)
        screen.blit(surf, rect.topleft)
        pygame.draw.rect(screen, PANEL_BORDER, rect, 2, border_radius=8)
        label = str(title)
        if count is not None:
            label += "  ·  %d" % count
        screen.blit(
            self.app.font_small.render(label, True, (208, 218, 232)),
            (rect.x + 12, rect.y + 9),
        )
        pygame.draw.line(
            screen,
            PANEL_BORDER,
            (rect.x + 8, rect.y + 34),
            (rect.right - 8, rect.y + 34),
        )
        pygame.draw.line(
            screen,
            accent,
            (rect.x + 12, rect.y + 34),
            (rect.x + 60, rect.y + 34),
            2,
        )

    def _clip_text(self, font, text, max_width):
        text = str(text or "")
        if font.size(text)[0] <= max_width:
            return text
        suffix = "..."
        while text and font.size(text + suffix)[0] > max_width:
            text = text[:-1]
        return text.rstrip() + suffix

    def _draw_bar(self, screen, rect, value, color):
        value = max(0.0, min(1.0, float(value)))
        pygame.draw.rect(screen, (35, 43, 55), rect, border_radius=2)
        fill = pygame.Rect(
            rect.x, rect.y, max(1, int(rect.width * value)), rect.height
        )
        pygame.draw.rect(screen, color, fill, border_radius=2)

    @staticmethod
    def _relation_color(value):
        if value >= 0.12:
            return GOOD
        if value <= -0.12:
            return BAD
        return MUTED

    @staticmethod
    def _chance_color(chance):
        if chance >= 0.78:
            return GOOD
        if chance >= 0.46:
            return WARN
        return BAD

    def _draw_header(self, screen):
        band = pygame.Surface((WIDTH, HEADER_H), pygame.SRCALPHA)
        band.fill((7, 10, 16, 220))
        screen.blit(band, (0, 0))
        pygame.draw.line(
            screen, PANEL_BORDER, (0, HEADER_H), (WIDTH, HEADER_H)
        )
        title = self.app.font_title.render(
            str(self.engine.config.get("title") or "Мир"), True, TEXT
        )
        screen.blit(title, (18, 9))
        subtitle = self.app.font_tiny.render(
            self._clip_text(
                self.app.font_tiny,
                self.engine.config.get("subtitle") or "",
                540,
            ),
            True,
            MUTED,
        )
        screen.blit(subtitle, (20, 43))
        office = self.engine.player_office()
        name = str(self.engine.profile.get("name") or "Действующее лицо")
        if self.engine.attached:
            line = self._clip_text(
                self.app.font_body,
                "%s · %s" % (name, office.get("title", "—")),
                470,
            )
        else:
            line = self._clip_text(
                self.app.font_body,
                "%s · вне службы" % name,
                470,
            )
        screen.blit(self.app.font_body.render(line, True, TEXT), (560, 10))
        if self.engine.attached:
            detail = "%s · %s · полномочия: %s" % (
                office.get("node_name", "—"),
                office.get("level_label", "—"),
                world_text.scale_label(office.get("authority", 0.0)),
            )
        else:
            detail = "Должность не занята · выберите новую роль"
        condition = self.engine.player_condition()
        detail += " · H %d" % int(round(condition["health"]))
        if condition["sickness"] > 0.0:
            detail += " · болезнь %d%%" % int(
                round(condition["sickness"] * 100)
            )
        screen.blit(
            self.app.font_tiny.render(
                self._clip_text(self.app.font_tiny, detail, 470),
                True,
                MUTED,
            ),
            (560, 38),
        )
        if self.engine.infinite:
            day = "день %d · действия %d / %d" % (
                self.engine.day,
                self.engine.actions_left,
                self.engine.actions_per_day,
            )
            if self.engine.horizon_passed:
                day += " · история продолжается"
        else:
            day = "день %d / %d · действия %d / %d" % (
                self.engine.day,
                self.engine.days,
                self.engine.actions_left,
                self.engine.actions_per_day,
            )
        if not getattr(self.app, "active", True) and not self.clock.paused:
            day += " · фон"
        pending = len(getattr(self.engine, "intents", ()) or ())
        if pending:
            # Очередь намерений видна игроку: отложенные события — часть
            # мира, а не скрытый таймер.
            day += " · планов %d" % pending
        day_surf = self.app.font_small.render(day, True, WARN)
        screen.blit(day_surf, (WIDTH - 18 - day_surf.get_width(), 12))
        hint = "вкладки · карточки · прогноз"
        hint_surf = self.app.font_tiny.render(hint, True, DIM)
        screen.blit(hint_surf, (WIDTH - 18 - hint_surf.get_width(), 38))
        chip_w = (WIDTH - 36 - 3 * 8) // 4
        x = 18
        for key in ("standing", "influence", "favor", "evidence"):
            rect = pygame.Rect(x, 64, chip_w, 18)
            pygame.draw.rect(screen, (13, 17, 24), rect, border_radius=3)
            value = float(self.engine.player_resources.get(key, 0.0))
            bar = pygame.Rect(rect.x + 3, rect.bottom - 5, rect.width - 6, 2)
            self._draw_bar(screen, bar, value, (118, 202, 156))
            text = "%s · %s" % (
                self.engine.stat_label(key),
                world_text.resource_label(value),
            )
            screen.blit(
                self.app.font_tiny.render(text, True, TEXT),
                (rect.x + 6, rect.y + 2),
            )
            x += chip_w + 8

    def _draw_main_tabs(self, screen):
        gap = 8
        tab_w = (WIDTH - 36 - gap * 2) // 3
        self.main_tab_rects = []
        for index, (tab_id, label) in enumerate(MAIN_TABS):
            rect = pygame.Rect(
                18 + index * (tab_w + gap), MAIN_TAB_Y, tab_w, 34
            )
            selected = tab_id == self.main_tab
            fill = (49, 88, 134) if selected else (19, 25, 35)
            pygame.draw.rect(screen, fill, rect, border_radius=5)
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                1,
                border_radius=5,
            )
            surf = self.app.font_small.render(
                label, True, TEXT if selected else MUTED
            )
            screen.blit(surf, surf.get_rect(center=rect.center))
            self.main_tab_rects.append((rect, tab_id))

    def _draw_subtabs(self, screen):
        options = SUB_TABS.get(self.main_tab) or ()
        gap = 6
        tab_w = (CONTENT_RECT.width - gap * (len(options) - 1)) // max(
            1, len(options)
        )
        self.subtab_rects = []
        for index, (_key, label) in enumerate(options):
            rect = pygame.Rect(
                CONTENT_RECT.x + index * (tab_w + gap),
                SUB_TAB_Y,
                tab_w,
                SUB_TAB_H,
            )
            selected = self.subtab_index.get(self.main_tab, 0) == index
            fill = (37, 57, 79) if selected else (16, 21, 29)
            pygame.draw.rect(screen, fill, rect, border_radius=4)
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                1,
                border_radius=4,
            )
            surf = self.app.font_tiny.render(
                label, True, TEXT if selected else MUTED
            )
            screen.blit(surf, surf.get_rect(center=rect.center))
            self.subtab_rects.append((rect, index))

    def _draw_entity_list(self, screen, title, rows, kind):
        self._draw_panel(
            screen,
            LEFT_RECT,
            title,
            len(rows),
        )
        self.entity_rows = []
        visible = self._visible_entity_rows()
        start = min(self.list_scroll, self._max_entity_scroll(rows))
        y = LEFT_RECT.y + 42
        if not rows:
            screen.blit(
                self.app.font_tiny.render("здесь пока никого нет", True, DIM),
                (LEFT_RECT.x + 12, y + 8),
            )
            return
        for entry in rows[start : start + visible]:
            rect = pygame.Rect(
                LEFT_RECT.x + 6,
                y,
                LEFT_RECT.width - 12,
                LIST_ROW_H - 6,
            )
            if kind == "character":
                selected = entry["id"] == self.selected_character_id
            else:
                selected = entry["id"] == self.selected_target_id
            fill = (38, 62, 88) if selected else (20, 26, 37)
            pygame.draw.rect(screen, fill, rect, border_radius=5)
            if selected:
                pygame.draw.rect(screen, ACCENT, rect, 1, border_radius=5)
            if kind == "character":
                self._draw_character_card(screen, rect, entry, selected)
            else:
                self._draw_organization_card(screen, rect, entry, selected)
            self.entity_rows.append((rect, kind, entry["id"]))
            y += LIST_ROW_H
        if self.list_scroll < self._max_entity_scroll(rows):
            screen.blit(
                self.app.font_tiny.render(
                    "колесо — прокрутка списка", True, DIM
                ),
                (LEFT_RECT.x + 12, LEFT_RECT.bottom - 16),
            )

    def _draw_character_card(self, screen, rect, character, selected):
        portrait = self.art.portrait(character["id"], (44, 50))
        screen.blit(portrait, (rect.x + 6, rect.y + 4))
        pygame.draw.rect(
            screen, PANEL_BORDER, (rect.x + 6, rect.y + 4, 44, 50), 1
        )
        name_color = TEXT if selected else (205, 214, 228)
        screen.blit(
            self.app.font_small.render(
                self._clip_text(
                    self.app.font_small, character["name"], rect.width - 66
                ),
                True,
                name_color,
            ),
            (rect.x + 58, rect.y + 4),
        )
        screen.blit(
            self.app.font_tiny.render(
                self._clip_text(
                    self.app.font_tiny, character["role"], rect.width - 66
                ),
                True,
                MUTED,
            ),
            (rect.x + 58, rect.y + 22),
        )
        affinity = float(character.get("affinity", 0.0))
        tag = " · ".join(character.get("tags") or ())
        if tag:
            screen.blit(
                self.app.font_tiny.render(
                    self._clip_text(self.app.font_tiny, tag, 150),
                    True,
                    DIM,
                ),
                (rect.x + 58, rect.y + 38),
            )
        label = world_text.relation_label(affinity)
        surf = self.app.font_tiny.render(
            label, True, self._relation_color(affinity)
        )
        screen.blit(surf, (rect.right - 8 - surf.get_width(), rect.y + 4))
        bar = pygame.Rect(rect.right - 84, rect.y + 42, 70, 4)
        self._draw_bar(
            screen, bar, (affinity + 1.0) / 2.0, self._relation_color(affinity)
        )

    def _draw_organization_card(self, screen, rect, node, selected):
        icon = self.art.organization_icon(node, (44, 44))
        screen.blit(icon, (rect.x + 6, rect.y + 5))
        pygame.draw.rect(
            screen, PANEL_BORDER, (rect.x + 6, rect.y + 5, 44, 44), 1
        )
        name_color = TEXT if selected else (205, 214, 228)
        screen.blit(
            self.app.font_small.render(
                self._clip_text(
                    self.app.font_small, node["name"], rect.width - 66
                ),
                True,
                name_color,
            ),
            (rect.x + 58, rect.y + 5),
        )
        detail = "%s · %s" % (
            self.engine.domain_label(node["domain"]),
            self.engine.node_level_label(node),
        )
        screen.blit(
            self.app.font_tiny.render(
                self._clip_text(self.app.font_tiny, detail, rect.width - 66),
                True,
                MUTED,
            ),
            (rect.x + 58, rect.y + 23),
        )
        relation = self.engine.relation(self.engine.player_node_id, node["id"])
        rel_surf = self.app.font_tiny.render(
            world_text.relation_label(relation),
            True,
            self._relation_color(relation),
        )
        screen.blit(
            rel_surf, (rect.right - 8 - rel_surf.get_width(), rect.y + 41)
        )
        if node["id"] == self.engine.player_node_id:
            screen.blit(
                self.app.font_tiny.render("вы", True, GOOD),
                (rect.x + 58, rect.y + 41),
            )
        elif node.get("kind") == "asset":
            screen.blit(
                self.app.font_tiny.render("имущество", True, DIM),
                (rect.x + 58, rect.y + 41),
            )

    def _draw_organization_content(self, screen):
        group_id = self._active_group_id("organizations")
        rows = self._active_organizations()
        title = "%s организации" % ORGANIZATION_CATEGORIES.get(
            group_id, group_id
        )
        self._draw_entity_list(screen, title.upper(), rows, "organization")
        self._draw_organization_detail(screen)

    def _draw_organization_detail(self, screen):
        self._draw_panel(screen, MID_RECT, "СТРУКТУРА И ДЕЙСТВИЯ")
        self.action_rows = []
        node = self.engine.node(self.selected_target_id)
        if node is None:
            if self._active_organizations():
                text = "Выберите организацию слева."
            else:
                text = (
                    "В этой категории пока никого нет. Выберите другую "
                    "подвкладку или измените отношения со структурами."
                )
            self._draw_wrapped(
                screen,
                text,
                MID_RECT.x + 12,
                MID_RECT.y + 48,
                MID_RECT.width - 24,
                DIM,
                max_lines=3,
            )
            return
        icon = self.art.organization_icon(node, (58, 58))
        screen.blit(icon, (MID_RECT.x + 12, MID_RECT.y + 44))
        pygame.draw.rect(
            screen,
            PANEL_BORDER,
            (MID_RECT.x + 12, MID_RECT.y + 44, 58, 58),
            1,
        )
        x = MID_RECT.x + 82
        screen.blit(
            self.app.font_body.render(
                self._clip_text(self.app.font_body, node["name"], 330),
                True,
                TEXT,
            ),
            (x, MID_RECT.y + 44),
        )
        detail = "%s · %s · %s" % (
            self.engine.domain_label(node["domain"]),
            self.engine.node_level_label(node),
            self.engine.polities.get(node.get("polity"), {}).get(
                "label", node.get("polity") or "—"
            ),
        )
        screen.blit(
            self.app.font_tiny.render(
                self._clip_text(self.app.font_tiny, detail, 340),
                True,
                ACCENT,
            ),
            (x, MID_RECT.y + 67),
        )
        relation = self.engine.relation(self.engine.player_node_id, node["id"])
        screen.blit(
            self.app.font_tiny.render(
                "к вам: %s" % world_text.relation_label(relation),
                True,
                self._relation_color(relation),
            ),
            (x, MID_RECT.y + 84),
        )
        desc = wrap_text(self.app.font_tiny, node.get("description", ""), 330)
        for index, line in enumerate(desc[:2]):
            screen.blit(
                self.app.font_tiny.render(line, True, MUTED),
                (x, MID_RECT.y + 100 + index * 13),
            )
        stats = node.get("stats") or {}
        stat_keys = (
            "power",
            "wealth",
            "legitimacy",
            "cohesion",
            "reach",
            "capacity",
        )
        sx = MID_RECT.x + 12
        sy = MID_RECT.y + 132
        for index, key in enumerate(stat_keys):
            column = index % 2
            row = index // 2
            px = sx + column * 206
            py = sy + row * 18
            value = float(stats.get(key, 0.0))
            screen.blit(
                self.app.font_tiny.render(
                    self.engine.stat_label(key), True, DIM
                ),
                (px, py),
            )
            bar = pygame.Rect(px + 100, py + 4, 82, 4)
            self._draw_bar(screen, bar, value, (112, 164, 208))
        action_top = MID_RECT.y + 196
        screen.blit(
            self.app.font_tiny.render(
                "ДЕЙСТВИЯ · доступные и закрытые", True, WARN
            ),
            (MID_RECT.x + 12, action_top - 18),
        )
        options = self._action_options()
        self._draw_action_list(
            screen, options, action_top, MID_RECT.bottom - 8
        )

    def _draw_character_content(self, screen):
        group_id = self._active_group_id("characters")
        rows = self._active_characters()
        title = CHARACTER_CIRCLES.get(group_id, group_id)
        self._draw_entity_list(screen, title.upper(), rows, "character")
        self._draw_character_detail(screen)

    def _draw_character_detail(self, screen):
        self._draw_panel(screen, MID_RECT, "ЧЕЛОВЕК И РАЗГОВОР")
        self.action_rows = []
        character = self.engine.character(self.selected_character_id)
        if character is None:
            if self._active_characters():
                text = "Выберите человека слева."
            else:
                text = "В этом круге пока никого нет."
            self._draw_wrapped(
                screen,
                text,
                MID_RECT.x + 12,
                MID_RECT.y + 48,
                MID_RECT.width - 24,
                DIM,
                max_lines=3,
            )
            return
        portrait = self.art.portrait(character["id"], (86, 104))
        screen.blit(portrait, (MID_RECT.x + 12, MID_RECT.y + 44))
        pygame.draw.rect(
            screen,
            PANEL_BORDER,
            (MID_RECT.x + 12, MID_RECT.y + 44, 86, 104),
            1,
        )
        x = MID_RECT.x + 112
        screen.blit(
            self.app.font_body.render(
                self._clip_text(self.app.font_body, character["name"], 310),
                True,
                TEXT,
            ),
            (x, MID_RECT.y + 44),
        )
        screen.blit(
            self.app.font_tiny.render(
                self._clip_text(
                    self.app.font_tiny, character.get("role", ""), 310
                ),
                True,
                ACCENT,
            ),
            (x, MID_RECT.y + 67),
        )
        tags = " · ".join(character.get("tags") or ())
        if tags:
            screen.blit(
                self.app.font_tiny.render(tags, True, WARN),
                (x, MID_RECT.y + 84),
            )
        desc = wrap_text(
            self.app.font_tiny,
            character.get("description", ""),
            310,
        )
        for index, line in enumerate(desc[:3]):
            screen.blit(
                self.app.font_tiny.render(line, True, MUTED),
                (x, MID_RECT.y + 100 + index * 13),
            )
        affinity = float(character.get("affinity", 0.0))
        trust = float(character.get("trust", 0.0))
        for index, (label, value) in enumerate(
            (("расположение", affinity), ("доверие", trust))
        ):
            y = MID_RECT.y + 136 + index * 18
            screen.blit(
                self.app.font_tiny.render(label, True, DIM),
                (x, y),
            )
            self._draw_bar(
                screen,
                pygame.Rect(x + 92, y + 4, 120, 4),
                (value + 1.0) / 2.0,
                self._relation_color(value),
            )
            screen.blit(
                self.app.font_tiny.render(
                    world_text.relation_label(value), True, MUTED
                ),
                (x + 220, y),
            )
        action_top = MID_RECT.y + 182
        screen.blit(
            self.app.font_tiny.render(
                "РАЗГОВОР · доступные и закрытые", True, WARN
            ),
            (MID_RECT.x + 12, action_top - 18),
        )
        options = self._action_options()
        self._draw_action_list(
            screen, options, action_top, MID_RECT.bottom - 8
        )

    def _draw_action_list(self, screen, options, top, bottom):
        self.action_rows = []
        if not options:
            screen.blit(
                self.app.font_tiny.render("нет доступных действий", True, DIM),
                (MID_RECT.x + 12, top + 8),
            )
            return
        visible = max(1, (bottom - top) // ACTION_ROW_H)
        start = min(self.action_scroll, max(0, len(options) - visible))
        for index, option in enumerate(options[start : start + visible]):
            rect = pygame.Rect(
                MID_RECT.x + 8,
                top + index * ACTION_ROW_H,
                MID_RECT.width - 16,
                ACTION_ROW_H - 4,
            )
            selected = option["id"] == self.selected_action_id
            enabled = bool(option.get("enabled"))
            fill = (38, 62, 88) if selected else (20, 26, 37)
            pygame.draw.rect(screen, fill, rect, border_radius=4)
            if selected:
                pygame.draw.rect(screen, ACCENT, rect, 1, border_radius=4)
            label = str(option.get("label") or option["id"])
            screen.blit(
                self.app.font_small.render(
                    self._clip_text(
                        self.app.font_small, label, rect.width - 20
                    ),
                    True,
                    TEXT if enabled else DIM,
                ),
                (rect.x + 9, rect.y + 3),
            )
            if enabled:
                action = option.get("action") or {}
                detail = "%s · успех: %s" % (
                    world_text.cost_summary(action, self.engine.stat_labels),
                    world_text.chance_label(self._option_chance(option)),
                )
                color = self._chance_color(self._option_chance(option))
            else:
                detail = world_text.reason_text(option.get("reason"))
                color = BAD
            screen.blit(
                self.app.font_tiny.render(
                    self._clip_text(
                        self.app.font_tiny, detail, rect.width - 20
                    ),
                    True,
                    color,
                ),
                (rect.x + 9, rect.y + 22),
            )
            self.action_rows.append((rect, option))
        if len(options) > visible:
            screen.blit(
                self.app.font_tiny.render(
                    "колесо — прокрутка действий", True, DIM
                ),
                (MID_RECT.x + 12, MID_RECT.bottom - 14),
            )

    def _draw_wrapped(
        self,
        screen,
        text,
        x,
        y,
        width,
        color,
        font=None,
        max_lines=3,
        line_h=13,
    ):
        font = font or self.app.font_tiny
        lines = wrap_text(font, str(text or ""), width)
        for line in lines[:max_lines]:
            screen.blit(font.render(line, True, color), (x, y))
            y += line_h
        return y

    def _draw_forecast_action(self, screen, y, preview):
        action = preview.get("action") or {}
        target = preview.get("target_label") or "—"
        screen.blit(
            self.app.font_body.render(
                self._clip_text(
                    self.app.font_body,
                    action.get("label", "Действие"),
                    RIGHT_RECT.width - 28,
                ),
                True,
                TEXT,
            ),
            (RIGHT_RECT.x + 14, y),
        )
        y += 24
        y = self._draw_wrapped(
            screen,
            "цель: %s" % target,
            RIGHT_RECT.x + 14,
            y,
            RIGHT_RECT.width - 28,
            MUTED,
            max_lines=1,
        )
        y = self._draw_wrapped(
            screen,
            world_text.cost_summary(action, self.engine.stat_labels),
            RIGHT_RECT.x + 14,
            y + 2,
            RIGHT_RECT.width - 28,
            WARN,
            max_lines=1,
        )
        if not preview.get("enabled"):
            y = self._draw_wrapped(
                screen,
                "недоступно: %s"
                % world_text.reason_text(preview.get("reason")),
                RIGHT_RECT.x + 14,
                y + 8,
                RIGHT_RECT.width - 28,
                BAD,
                max_lines=2,
            )
            return y
        chance = float(preview.get("success_chance", 0.0))
        color = self._chance_color(chance)
        screen.blit(
            self.app.font_small.render(
                "успех: %s" % world_text.chance_label(chance),
                True,
                color,
            ),
            (RIGHT_RECT.x + 14, y + 8),
        )
        y += 28
        y = self._draw_wrapped(
            screen,
            preview.get("success_text", ""),
            RIGHT_RECT.x + 14,
            y,
            RIGHT_RECT.width - 28,
            (190, 205, 220),
            max_lines=2,
        )
        effects = world_text.format_effect_map(
            preview.get("success_effects_map"),
            self.engine.stat_labels,
            preview.get("target_label", ""),
        )
        if effects:
            y = self._draw_wrapped(
                screen,
                " · ".join(effects[:4]),
                RIGHT_RECT.x + 14,
                y + 2,
                RIGHT_RECT.width - 28,
                GOOD,
                max_lines=3,
            )
        failure_chance = float(preview.get("failure_chance", 0.0))
        screen.blit(
            self.app.font_tiny.render(
                "если не выйдет: %s" % world_text.chance_label(failure_chance),
                True,
                BAD if failure_chance >= 0.46 else MUTED,
            ),
            (RIGHT_RECT.x + 14, y + 8),
        )
        y += 24
        y = self._draw_wrapped(
            screen,
            preview.get("failure_text", ""),
            RIGHT_RECT.x + 14,
            y,
            RIGHT_RECT.width - 28,
            (190, 180, 180),
            max_lines=2,
        )
        failure_effects = world_text.format_effect_map(
            preview.get("failure_effects_map"),
            self.engine.stat_labels,
            preview.get("target_label", ""),
        )
        if failure_effects:
            y = self._draw_wrapped(
                screen,
                " · ".join(failure_effects[:4]),
                RIGHT_RECT.x + 14,
                y + 2,
                RIGHT_RECT.width - 28,
                BAD,
                max_lines=2,
            )
        return y

    def _draw_forecast_result(self, screen, y, result):
        outcome = result.get("outcome", "")
        color = {"success": GOOD, "failure": BAD, "win": GOOD}.get(
            outcome, WARN
        )
        screen.blit(
            self.app.font_body.render(
                world_text.outcome_label(outcome), True, color
            ),
            (RIGHT_RECT.x + 14, y),
        )
        y += 24
        y = self._draw_wrapped(
            screen,
            "действие: %s" % result.get("action_label", ""),
            RIGHT_RECT.x + 14,
            y,
            RIGHT_RECT.width - 28,
            MUTED,
            max_lines=1,
        )
        y = self._draw_wrapped(
            screen,
            result.get("text", ""),
            RIGHT_RECT.x + 14,
            y + 2,
            RIGHT_RECT.width - 28,
            (190, 205, 220),
            max_lines=4,
        )
        summary = world_text.summarize_changes(result.get("changes"))
        if summary:
            y = self._draw_wrapped(
                screen,
                summary,
                RIGHT_RECT.x + 14,
                y + 4,
                RIGHT_RECT.width - 28,
                WARN,
                max_lines=4,
            )
        return y

    def _draw_forecast(self, screen):
        self._draw_panel(screen, RIGHT_RECT, "ПРОГНОЗ")
        y = RIGHT_RECT.y + 44
        if self.selected_action_id and self.action_context in (
            "organization",
            "character",
        ):
            if self.action_context == "character":
                preview = self.engine.character_preview(
                    self.selected_action_id, self.selected_character_id
                )
            else:
                preview = self.engine.preview(
                    self.selected_action_id, self.selected_target_id
                )
            if preview is not None:
                self._draw_forecast_action(screen, y, preview)
        elif self.last_result:
            self._draw_forecast_result(screen, y, self.last_result)
        else:
            if (
                self.action_context == "character"
                and self.selected_character_id
            ):
                character = (
                    self.engine.character(self.selected_character_id) or {}
                )
                text = (
                    "Выбран человек: %s. Выберите разговор слева. "
                    "Шанс и последствия показаны качественно, без "
                    "точных процентов."
                ) % character.get("name", "—")
            elif (
                self.action_context == "organization"
                and self.selected_target_id
            ):
                node = self.engine.node(self.selected_target_id) or {}
                text = (
                    "Выбрана структура: %s. Выберите действие слева. "
                    "Шанс и последствия показаны качественно, без "
                    "точных процентов."
                ) % node.get("name", "—")
            elif self.main_tab == "organizations" and not (
                self._active_organizations()
            ):
                text = (
                    "В этой категории пока нет организаций. Выберите "
                    "другую подвкладку или измените отношения со "
                    "структурами."
                )
            elif self.main_tab == "characters" and not (
                self._active_characters()
            ):
                text = "В этом круге пока никого нет."
            else:
                text = (
                    "Выберите человека или организацию, затем действие. "
                    "Шанс и последствия показаны качественно, без "
                    "точных процентов."
                )
            y = self._draw_wrapped(
                screen,
                text,
                RIGHT_RECT.x + 14,
                y,
                RIGHT_RECT.width - 28,
                MUTED,
                max_lines=6,
            )
            self._draw_wrapped(
                screen,
                "Серые действия остаются видны вместе с причиной отказа.",
                RIGHT_RECT.x + 14,
                y + 6,
                RIGHT_RECT.width - 28,
                DIM,
                max_lines=3,
            )
        if self.message:
            self._draw_wrapped(
                screen,
                self.message,
                RIGHT_RECT.x + 14,
                RIGHT_RECT.y + 300,
                RIGHT_RECT.width - 28,
                BAD,
                max_lines=2,
            )
        self._draw_button(
            screen,
            self._execute_rect(),
            "Совершить",
            bool(self.selected_action_id),
            accent=True,
        )
        self._draw_log(screen, RIGHT_RECT.y + 382)

    def _draw_personality_content(self, screen):
        self.entity_rows = []
        self.action_rows = []
        self.skill_rows = []
        self.item_rows = []
        sub = self._active_group_id("personality")
        if sub == "skills":
            self._draw_skill_tree(screen)
        elif sub == "items":
            self._draw_items(screen)
        else:
            self._draw_characteristics(screen)

    def _draw_characteristics(self, screen):
        self._draw_panel(screen, CONTENT_RECT, "ХАРАКТЕРИСТИКИ")
        profile = self.engine.profile
        portrait = self.art.portrait("player", (96, 116))
        screen.blit(portrait, (CONTENT_RECT.x + 16, CONTENT_RECT.y + 46))
        pygame.draw.rect(
            screen,
            PANEL_BORDER,
            (CONTENT_RECT.x + 16, CONTENT_RECT.y + 46, 96, 116),
            1,
        )
        x = CONTENT_RECT.x + 128
        y = CONTENT_RECT.y + 46
        name = str(profile.get("name") or "Новый герой")
        screen.blit(self.app.font_body.render(name, True, TEXT), (x, y))
        y += 24
        summary = " · ".join(
            str(item)
            for item in (
                profile.get("origin"),
                profile.get("vocation"),
                profile.get("reputation"),
            )
            if item
        )
        y = self._draw_wrapped(
            screen,
            summary,
            x,
            y,
            CONTENT_RECT.width - 150,
            MUTED,
            max_lines=1,
        )
        y = self._draw_wrapped(
            screen,
            "семья: %s · образование: %s"
            % (profile.get("family", "—"), profile.get("education", "—")),
            x,
            y + 3,
            CONTENT_RECT.width - 150,
            MUTED,
            max_lines=1,
        )
        y = self._draw_wrapped(
            screen,
            "покровитель: %s · недостаток: %s"
            % (profile.get("patron", "—"), profile.get("flaw", "—")),
            x,
            y + 3,
            CONTENT_RECT.width - 150,
            MUTED,
            max_lines=1,
        )
        values = ", ".join(profile.get("values") or ())
        traits = ", ".join(profile.get("traits") or ())
        y = self._draw_wrapped(
            screen,
            "ценности: %s" % values,
            x,
            y + 6,
            CONTENT_RECT.width - 150,
            WARN,
            max_lines=1,
        )
        self._draw_wrapped(
            screen,
            "черты: %s" % traits,
            x,
            y + 2,
            CONTENT_RECT.width - 150,
            (184, 196, 214),
            max_lines=2,
        )
        office = self.engine.player_office()
        card = pygame.Rect(
            CONTENT_RECT.x + 16,
            CONTENT_RECT.y + 188,
            CONTENT_RECT.width - 32,
            70,
        )
        pygame.draw.rect(screen, PANEL_BG_SOFT, card, border_radius=6)
        pygame.draw.rect(screen, PANEL_BORDER, card, 1, border_radius=6)
        screen.blit(
            self.app.font_small.render("ДОЛЖНОСТЬ", True, WARN),
            (card.x + 12, card.y + 8),
        )
        screen.blit(
            self.app.font_body.render(office.get("title", "—"), True, TEXT),
            (card.x + 12, card.y + 27),
        )
        screen.blit(
            self.app.font_tiny.render(
                "%s · %s · полномочия: %s"
                % (
                    office.get("node_name", "—"),
                    office.get("level_label", "—"),
                    world_text.scale_label(office.get("authority", 0.0)),
                ),
                True,
                MUTED,
            ),
            (card.x + 12, card.y + 50),
        )
        screen.blit(
            self.app.font_tiny.render("пригодность к сферам", True, WARN),
            (CONTENT_RECT.x + 16, CONTENT_RECT.y + 276),
        )
        aptitudes = profile.get("aptitudes") or {}
        index = 0
        for domain in self.engine.config.get("domains") or ():
            value = float(aptitudes.get(domain["id"], 0.0))
            column = index % 3
            row = index // 3
            px = CONTENT_RECT.x + 16 + column * 255
            py = CONTENT_RECT.y + 296 + row * 34
            screen.blit(
                self.app.font_tiny.render(
                    self.engine.domain_label(domain["id"]), True, DIM
                ),
                (px, py),
            )
            self._draw_bar(
                screen,
                pygame.Rect(px, py + 15, 150, 4),
                value,
                (112, 164, 208),
            )
            screen.blit(
                self.app.font_tiny.render(
                    world_text.scale_label(value), True, MUTED
                ),
                (px + 156, py),
            )
            index += 1
        return

    def _draw_skill_tree(self, screen):
        self._draw_panel(screen, CONTENT_RECT, "ДРЕВО НАВЫКОВ")
        branches = self.engine.skill_tree()
        if not branches:
            screen.blit(
                self.app.font_tiny.render(
                    "древо навыков ещё не описано", True, DIM
                ),
                (CONTENT_RECT.x + 16, CONTENT_RECT.y + 52),
            )
            return
        root_x = CONTENT_RECT.centerx
        root_y = CONTENT_RECT.y + 62
        pygame.draw.circle(screen, (46, 68, 92), (root_x, root_y), 28, 2)
        root = self.app.font_tiny.render("ПРАКТИКА", True, TEXT)
        screen.blit(root, root.get_rect(center=(root_x, root_y)))
        column_w = 240
        gap = 20
        total = column_w * len(branches) + gap * (len(branches) - 1)
        left = CONTENT_RECT.centerx - total // 2
        for branch_index, branch in enumerate(branches):
            bx = left + branch_index * (column_w + gap)
            branch_center = bx + column_w // 2
            pygame.draw.line(
                screen,
                (62, 82, 106),
                (root_x, root_y + 28),
                (branch_center, CONTENT_RECT.y + 112),
                2,
            )
            screen.blit(
                self.app.font_small.render(
                    branch.get("label", ""), True, WARN
                ),
                (bx, CONTENT_RECT.y + 104),
            )
            screen.blit(
                self.app.font_tiny.render(
                    self._clip_text(
                        self.app.font_tiny,
                        branch.get("description", ""),
                        column_w,
                    ),
                    True,
                    DIM,
                ),
                (bx, CONTENT_RECT.y + 122),
            )
            skill_y = CONTENT_RECT.y + 142
            for skill_index, skill in enumerate(branch.get("skills") or ()):
                rect = pygame.Rect(bx, skill_y, column_w, 66)
                selected = skill["id"] == self.selected_skill_id
                fill = (38, 62, 88) if selected else (20, 26, 37)
                pygame.draw.rect(screen, fill, rect, border_radius=5)
                pygame.draw.rect(
                    screen,
                    ACCENT if selected else PANEL_BORDER,
                    rect,
                    1,
                    border_radius=5,
                )
                icon = self.art.skill_icon(skill["id"], (30, 30))
                screen.blit(icon, (rect.x + 6, rect.y + 8))
                screen.blit(
                    self.app.font_small.render(
                        skill.get("label", skill["id"]), True, TEXT
                    ),
                    (rect.x + 44, rect.y + 6),
                )
                rank = world_text.skill_rank(skill.get("value", 0.0))
                screen.blit(
                    self.app.font_tiny.render(rank, True, ACCENT),
                    (rect.x + 44, rect.y + 24),
                )
                self._draw_bar(
                    screen,
                    pygame.Rect(rect.x + 44, rect.y + 40, 120, 4),
                    skill.get("value", 0.0),
                    (112, 164, 208),
                )
                next_rank = world_text.skill_next_rank(skill.get("value", 0.0))
                if next_rank:
                    screen.blit(
                        self.app.font_tiny.render(
                            "след.: %s" % next_rank, True, DIM
                        ),
                        (rect.x + 44, rect.y + 50),
                    )
                self.skill_rows.append((rect, skill["id"]))
                if skill_index < len(branch.get("skills") or ()) - 1:
                    pygame.draw.line(
                        screen,
                        (62, 82, 106),
                        (branch_center, rect.bottom),
                        (branch_center, rect.bottom + 10),
                        2,
                    )
                skill_y += 76

    def _draw_items(self, screen):
        self._draw_panel(screen, CONTENT_RECT, "НАЛИЧНЫЕ ПРЕДМЕТЫ")
        items = self.engine.player_items()
        if not items:
            screen.blit(
                self.app.font_tiny.render(
                    "при вас нет личных предметов", True, DIM
                ),
                (CONTENT_RECT.x + 16, CONTENT_RECT.y + 52),
            )
            return
        card_w = (CONTENT_RECT.width - 48) // 2
        card_h = 112
        for index, item in enumerate(items):
            column = index % 2
            row = index // 2
            rect = pygame.Rect(
                CONTENT_RECT.x + 16 + column * (card_w + 16),
                CONTENT_RECT.y + 48 + row * (card_h + 12),
                card_w,
                card_h,
            )
            selected = item["id"] == self.selected_item_id
            fill = (38, 62, 88) if selected else (20, 26, 37)
            pygame.draw.rect(screen, fill, rect, border_radius=6)
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                1,
                border_radius=6,
            )
            icon = self.art.item_icon(item, (60, 60))
            screen.blit(icon, (rect.x + 10, rect.y + 12))
            pygame.draw.rect(
                screen,
                PANEL_BORDER,
                (rect.x + 10, rect.y + 12, 60, 60),
                1,
            )
            screen.blit(
                self.app.font_small.render(
                    self._clip_text(
                        self.app.font_small,
                        item.get("label", item["id"]),
                        rect.width - 90,
                    ),
                    True,
                    TEXT,
                ),
                (rect.x + 82, rect.y + 12),
            )
            desc = wrap_text(
                self.app.font_tiny,
                item.get("description", ""),
                rect.width - 94,
            )
            for line_index, line in enumerate(desc[:3]):
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (rect.x + 82, rect.y + 34 + line_index * 13),
                )
            self.item_rows.append((rect, item["id"]))

    def _draw_personality_right(self, screen):
        self._draw_panel(screen, RIGHT_RECT, "ЛИЧНОСТЬ")
        y = RIGHT_RECT.y + 44
        if self.selected_skill_id:
            skill = None
            for branch in self.engine.skill_tree():
                for item in branch.get("skills") or ():
                    if item["id"] == self.selected_skill_id:
                        skill = item
                        break
                if skill:
                    break
            if skill:
                icon = self.art.skill_icon(skill["id"], (48, 48))
                screen.blit(icon, (RIGHT_RECT.x + 14, y))
                pygame.draw.rect(
                    screen,
                    PANEL_BORDER,
                    (RIGHT_RECT.x + 14, y, 48, 48),
                    1,
                )
                screen.blit(
                    self.app.font_body.render(
                        skill.get("label", skill["id"]), True, TEXT
                    ),
                    (RIGHT_RECT.x + 76, y),
                )
                screen.blit(
                    self.app.font_tiny.render(
                        "ранг: %s"
                        % world_text.skill_rank(skill.get("value", 0.0)),
                        True,
                        ACCENT,
                    ),
                    (RIGHT_RECT.x + 76, y + 22),
                )
                y += 60
                y = self._draw_wrapped(
                    screen,
                    skill.get("description", ""),
                    RIGHT_RECT.x + 14,
                    y,
                    RIGHT_RECT.width - 28,
                    (190, 205, 220),
                    max_lines=4,
                )
                next_rank = world_text.skill_next_rank(skill.get("value", 0.0))
                if next_rank:
                    y = self._draw_wrapped(
                        screen,
                        "следующий порог: %s" % next_rank,
                        RIGHT_RECT.x + 14,
                        y + 6,
                        RIGHT_RECT.width - 28,
                        WARN,
                        max_lines=1,
                    )
                self._draw_bar(
                    screen,
                    pygame.Rect(
                        RIGHT_RECT.x + 14, y + 8, RIGHT_RECT.width - 28, 6
                    ),
                    skill.get("value", 0.0),
                    (112, 164, 208),
                )
                y += 26
        elif self.selected_item_id:
            item = None
            for candidate in self.engine.player_items():
                if candidate["id"] == self.selected_item_id:
                    item = candidate
                    break
            if item:
                icon = self.art.item_icon(item, (72, 72))
                screen.blit(icon, (RIGHT_RECT.x + 14, y))
                pygame.draw.rect(
                    screen,
                    PANEL_BORDER,
                    (RIGHT_RECT.x + 14, y, 72, 72),
                    1,
                )
                screen.blit(
                    self.app.font_body.render(
                        item.get("label", item["id"]), True, TEXT
                    ),
                    (RIGHT_RECT.x + 98, y),
                )
                screen.blit(
                    self.app.font_tiny.render("личный предмет", True, ACCENT),
                    (RIGHT_RECT.x + 98, y + 24),
                )
                y += 88
                y = self._draw_wrapped(
                    screen,
                    item.get("description", ""),
                    RIGHT_RECT.x + 14,
                    y,
                    RIGHT_RECT.width - 28,
                    (190, 205, 220),
                    max_lines=5,
                )
        else:
            office = self.engine.player_office()
            screen.blit(
                self.app.font_body.render(
                    self.engine.profile.get("name", "Новый герой"),
                    True,
                    TEXT,
                ),
                (RIGHT_RECT.x + 14, y),
            )
            y += 24
            y = self._draw_wrapped(
                screen,
                "%s · %s"
                % (office.get("title", "—"), office.get("node_name", "—")),
                RIGHT_RECT.x + 14,
                y,
                RIGHT_RECT.width - 28,
                MUTED,
                max_lines=2,
            )
            screen.blit(
                self.app.font_tiny.render("ЛИЧНЫЕ РЕСУРСЫ", True, WARN),
                (RIGHT_RECT.x + 14, y + 10),
            )
            y += 28
            for key in ("standing", "influence", "favor", "evidence"):
                value = float(self.engine.player_resources.get(key, 0.0))
                screen.blit(
                    self.app.font_tiny.render(
                        self.engine.stat_label(key), True, DIM
                    ),
                    (RIGHT_RECT.x + 14, y),
                )
                self._draw_bar(
                    screen,
                    pygame.Rect(RIGHT_RECT.x + 120, y + 4, 110, 4),
                    value,
                    (118, 202, 156),
                )
                screen.blit(
                    self.app.font_tiny.render(
                        world_text.resource_label(value), True, MUTED
                    ),
                    (RIGHT_RECT.x + 238, y),
                )
                y += 19
            y += 6
            y = self._draw_wrapped(
                screen,
                "Характеристики показывают, на что вы опираетесь. "
                "Навыки растут через действия и службу.",
                RIGHT_RECT.x + 14,
                y,
                RIGHT_RECT.width - 28,
                MUTED,
                max_lines=3,
            )
            if self.message:
                y = self._draw_wrapped(
                    screen,
                    self.message,
                    RIGHT_RECT.x + 14,
                    y + 4,
                    RIGHT_RECT.width - 28,
                    BAD,
                    max_lines=2,
                )
        if self.message and self.selected_skill_id:
            self._draw_wrapped(
                screen,
                self.message,
                RIGHT_RECT.x + 14,
                RIGHT_RECT.y + 300,
                RIGHT_RECT.width - 28,
                BAD,
                max_lines=2,
            )
        self._draw_log(screen, RIGHT_RECT.y + 382)

    def _draw_log(self, screen, y):
        screen.blit(
            self.app.font_tiny.render("ЖУРНАЛ МИРА", True, WARN),
            (RIGHT_RECT.x + 14, y),
        )
        y += 17
        entries = self.engine.log[-5:]
        for item in entries:
            text = "Д%d: %s" % (item.get("day", 0), item.get("text", ""))
            line = self._clip_text(
                self.app.font_tiny, text, RIGHT_RECT.width - 28
            )
            screen.blit(
                self.app.font_tiny.render(line, True, DIM),
                (RIGHT_RECT.x + 14, y),
            )
            y += 13
            if y > RIGHT_RECT.bottom - 16:
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
                (
                    max(1, int(surf.get_width() * scale)),
                    surf.get_height(),
                ),
            )
        screen.blit(surf, surf.get_rect(center=rect.center))

    def _draw_bottom(self, screen):
        pygame.draw.rect(screen, (11, 15, 22), BOTTOM_RECT, border_radius=6)
        pygame.draw.rect(screen, PANEL_BORDER, BOTTOM_RECT, 1, border_radius=6)
        hint = (
            "Вкладки — разделы · карточки — люди и структуры · "
            "колесо — прокрутка · A — автопилот · прогноз качественный."
        )
        screen.blit(
            self.app.font_tiny.render(hint, True, MUTED),
            (BOTTOM_RECT.x + 12, BOTTOM_RECT.y + 11),
        )
        if self.engine.finished:
            if self.engine.outcome in ("win", "lose"):
                label = "Принять развязку"
            elif self.engine.ending == "neutral":
                label = "Глава завершена"
            else:
                label = "Кампания завершена"
            self._draw_button(
                screen, self._finish_rect(), label, True, accent=True
            )
        elif not self.engine.attached:
            self._draw_button(
                screen,
                self._office_rect(),
                "Выбрать должность",
                True,
                accent=True,
            )
        else:
            self._draw_button(
                screen,
                self._autopilot_rect(),
                "Автопилот: вкл" if self.autopilot else "Автопилот: выкл",
                True,
                accent=self.autopilot,
            )
            self._draw_button(
                screen,
                self._end_day_rect(),
                "Завершить день",
                True,
            )

    def draw(self, screen):
        screen.fill((10, 13, 19))
        screen.blit(self.art.background((WIDTH, HEIGHT)), (0, 0))
        screen.blit(self._overlay, (0, 0))
        self._draw_header(screen)
        self._draw_main_tabs(screen)
        self._draw_subtabs(screen)
        if self.main_tab == "characters":
            self._draw_character_content(screen)
        elif self.main_tab == "organizations":
            self._draw_organization_content(screen)
        else:
            self._draw_personality_content(screen)
        if self.main_tab == "personality":
            self._draw_personality_right(screen)
        else:
            self._draw_forecast(screen)
        self._draw_bottom(screen)


__all__ = ["WorldScreen"]
