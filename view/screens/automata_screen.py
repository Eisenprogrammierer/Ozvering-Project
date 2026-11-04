from __future__ import annotations

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import wrap_text
from view.support.log_journal import get_logger

logger = get_logger("view.automata")

WIDTH, HEIGHT = 1280, 720
TOP_H = 104
LEFT_RECT = pygame.Rect(24, TOP_H, 344, 520)
MID_RECT = pygame.Rect(388, TOP_H, 420, 520)
RIGHT_RECT = pygame.Rect(828, TOP_H, 428, 520)
BOTTOM_RECT = pygame.Rect(24, 646, 1232, 54)
ACTION_ROW_H = 62
PANEL_BG = (18, 23, 33, 238)
PANEL_BORDER = (58, 70, 92)
TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
BAD = (226, 112, 112)
WARN = (230, 184, 96)
ASSET_LABELS = {
    "legitimacy": "законность",
    "influence": "влияние",
    "cohesion": "сплочённость",
    "supply": "снабжение",
    "fear": "страх",
    "morale": "мораль",
    "energy": "энергия",
}


def _panel(surface, rect):
    shape = pygame.Surface(rect.size, pygame.SRCALPHA)
    shape.fill(PANEL_BG)
    surface.blit(shape, rect.topleft)
    pygame.draw.rect(surface, PANEL_BORDER, rect, 2, border_radius=8)


def _asset_line(assets, keys=None):
    items = []
    for key, value in assets.items():
        if keys is not None and key not in keys:
            continue
        label = ASSET_LABELS.get(key, key)
        items.append("%s %.2f" % (label, float(value)))
    return " · ".join(items)


def _target_name(campaign, action):
    target = str(action.get("target") or "rival")
    if target == "self":
        return "себя"
    if target == "rival":
        faction = campaign.faction(campaign.rival_of(campaign.player_side))
    elif target in ("any", "all", "all_rivals", "other"):
        return "любую фракцию"
    elif target == "strongest":
        return "сильнейшего"
    elif target == "weakest":
        return "слабейшего"
    else:
        faction = campaign.faction(target)
        if faction is None:
            for item in campaign.factions.values():
                if target in (item.id, item.name):
                    faction = item
                    break
    return getattr(faction, "name", target)


class AutomataScreen(BaseScreen):

    show_time_hud = False
    escape_action = "none"

    def __init__(self, app, campaign):
        super().__init__(app)
        self.campaign = campaign
        self.selected_action_id = None
        self.action_scroll = 0
        self.log_scroll = 0
        self.message = ""
        self.last_result = None
        self._sync_storyline()
        logger.info(
            "Экран автоматов: фракций=%d, ход=%d/%d, игрок=%s",
            len(campaign.factions),
            campaign.turn,
            campaign.max_turns,
            campaign.player_side,
        )

    # ------------------------------------------------------------------
    # Состояние и сюжет
    # ------------------------------------------------------------------
    def _sync_storyline(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return
        snapshot = self.campaign.snapshot()
        interp.state["automata"] = snapshot
        interp.set_variable("automata_turn", snapshot["turn"])
        interp.set_variable("automata_max_turns", snapshot["max_turns"])
        interp.set_variable("automata_outcome", snapshot["outcome"])
        for side, faction in snapshot["factions"].items():
            interp.set_variable(
                "automata_%s_legitimacy" % side,
                faction["assets"].get("legitimacy", 0.0),
            )
            interp.set_variable(
                "automata_%s_cohesion" % side,
                faction["assets"].get("cohesion", 0.0),
            )

    def _player(self):
        return self.campaign.faction(self.campaign.player_side)

    def _options(self):
        return self.campaign.action_options(self.campaign.player_side)

    def _visible_actions(self):
        return max(1, (MID_RECT.height - 78) // ACTION_ROW_H)

    def _action_rows(self):
        options = self._options()
        visible = self._visible_actions()
        start = max(0, min(self.action_scroll, len(options) - visible))
        rows = []
        for index, option in enumerate(options[start : start + visible]):
            rect = pygame.Rect(
                MID_RECT.x + 10,
                MID_RECT.y + 58 + index * ACTION_ROW_H,
                MID_RECT.width - 20,
                ACTION_ROW_H - 6,
            )
            rows.append((rect, option))
        return rows

    def _faction_rows(self):
        rows = []
        for index, faction in enumerate(self.campaign.factions.values()):
            rect = pygame.Rect(
                LEFT_RECT.x + 10,
                LEFT_RECT.y + 48 + index * 112,
                LEFT_RECT.width - 20,
                104,
            )
            rows.append((rect, faction))
        return rows

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------
    def _execute_selected(self):
        if self.selected_action_id is None:
            self.message = "Сначала выберите работу."
            return
        if self.campaign.finished:
            return
        # Одна работа за ход: «Выполнить» проводит выбранную работу и
        # завершает ход вместе с ответом остальных автоматов. Раньше работа
        # применялась вне цикла хода, и игрок мог выполнить несколько работ
        # подряд, пока не кончатся ресурсы.
        action_id = self.selected_action_id
        option = next(
            (item for item in self._options() if item["id"] == action_id),
            None,
        )
        if option is None or not option.get("enabled"):
            self.message = (
                option.get("reason") if option else "Работа недоступна."
            )
            logger.info("Работа отклонена: %s (%s)", action_id, self.message)
            return
        self.campaign.advance(player_action=action_id)
        self.selected_action_id = None
        self._sync_storyline()
        self.last_result = next(
            (
                item
                for item in reversed(self.campaign.log)
                if item.get("turn") == self.campaign.turn
                and item.get("actor_side") == self.campaign.player_side
            ),
            None,
        )
        if self.last_result is None:
            self.message = "Работа не выполнена: проверьте цену и перезарядку."
            logger.info("Работа отклонена: %s", action_id)
        else:
            self.message = ""
            logger.info(
                "Работа автомата: %s → %s; успех=%s; шанс=%.3f; ход=%d",
                self.last_result.get("actor_name", "?"),
                self.last_result.get("target_name", "?"),
                self.last_result.get("success"),
                float(self.last_result.get("chance", 0.0)),
                self.campaign.turn,
            )
        if self.campaign.finished:
            self._check_storyline_outcome()

    def _end_turn(self):
        if self.campaign.finished:
            return
        action_id = self.selected_action_id
        if action_id is None:
            action_id = self.campaign.auto_action(
                self.campaign.player_side, turn=self.campaign.turn + 1
            )
        result = self.campaign.advance(player_action=action_id)
        self.selected_action_id = None
        self.last_result = (
            self.campaign.log[-1] if self.campaign.log else None
        )
        self.message = ""
        self._sync_storyline()
        logger.info(
            "Ход автоматов завершён: %d/%d, исход=%s",
            result["turn"],
            result["max_turns"],
            result["outcome"],
        )
        if self.campaign.finished:
            self._check_storyline_outcome()

    def _check_storyline_outcome(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None or self.campaign.outcome is None:
            return
        if interp.check_lose_conditions():
            self.app.finish_storyline_outcome("lose")
        elif interp.check_win_conditions():
            self.app.finish_storyline_outcome("win")

    def _accept_outcome(self):
        if not self.campaign.finished:
            return
        outcome = self.campaign.outcome
        if outcome not in ("win", "lose"):
            outcome = "lose"
        self.app.finish_storyline_outcome(outcome)
        logger.info("Принят исход кампании автоматов: %s", outcome)

    # ------------------------------------------------------------------
    # Ввод
    # ------------------------------------------------------------------
    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if MID_RECT.collidepoint(pos):
                total = len(self._options())
                self.action_scroll = max(
                    0,
                    min(
                        max(0, total - self._visible_actions()),
                        self.action_scroll - event.y,
                    ),
                )
            elif RIGHT_RECT.collidepoint(pos):
                self.log_scroll = max(0, self.log_scroll - event.y)
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        pos = event.pos
        if self._execute_rect().collidepoint(pos):
            self._execute_selected()
            return
        if self._end_turn_rect().collidepoint(pos):
            self._end_turn()
            return
        if self.campaign.finished and self._finish_rect().collidepoint(pos):
            self._accept_outcome()
            return
        for rect, option in self._action_rows():
            if rect.collidepoint(pos):
                if option.get("enabled"):
                    self.selected_action_id = option["id"]
                    self.message = ""
                    logger.debug("Выбрана работа: %s", option["id"])
                else:
                    self.message = str(
                        option.get("reason") or "Работа недоступна."
                    )
                return

    # ------------------------------------------------------------------
    # Геометрия кнопок
    # ------------------------------------------------------------------
    def _execute_rect(self):
        return pygame.Rect(
            MID_RECT.x + 10,
            BOTTOM_RECT.y + 7,
            250,
            40,
        )

    def _end_turn_rect(self):
        return pygame.Rect(
            MID_RECT.x + 274,
            BOTTOM_RECT.y + 7,
            250,
            40,
        )

    def _finish_rect(self):
        return pygame.Rect(
            BOTTOM_RECT.right - 280,
            BOTTOM_RECT.y + 7,
            270,
            40,
        )

    def _draw_button(self, surface, rect, label, enabled=True, accent=False):
        if not enabled:
            color = (46, 50, 62)
        elif accent:
            color = (142, 96, 54)
        else:
            color = (46, 86, 138)
        pygame.draw.rect(surface, color, rect, border_radius=7)
        pygame.draw.rect(surface, PANEL_BORDER, rect, 2, border_radius=7)
        text = self.app.font_small.render(label, True, TEXT)
        surface.blit(text, text.get_rect(center=rect.center))

    # ------------------------------------------------------------------
    # Отрисовка
    # ------------------------------------------------------------------
    def draw(self, screen):
        player = self._player()
        title = self.campaign.title
        screen.blit(
            self.app.font_title.render(title, True, TEXT), (24, 12)
        )
        status = "ход %d / %d" % (
            self.campaign.turn,
            self.campaign.max_turns,
        )
        if self.campaign.outcome:
            status += " · исход: %s" % self.campaign.outcome
        screen.blit(
            self.app.font_small.render(status, True, MUTED), (24, 52)
        )
        if player is not None:
            subtitle = "%s · %s" % (player.name, player.record.get("role_title", "лидер"))
            screen.blit(
                self.app.font_small.render(subtitle, True, ACCENT), (24, 74)
            )

        _panel(screen, LEFT_RECT)
        screen.blit(
            self.app.font_small.render("ФРАКЦИИ-АВТОМАТЫ", True, MUTED),
            (LEFT_RECT.x + 12, LEFT_RECT.y + 12),
        )
        for rect, faction in self._faction_rows():
            is_player = faction.side == self.campaign.player_side
            border = ACCENT if is_player else PANEL_BORDER
            pygame.draw.rect(screen, (24, 30, 43), rect, border_radius=6)
            pygame.draw.rect(screen, border, rect, 2, border_radius=6)
            label = faction.name
            if is_player:
                label += " · вы"
            screen.blit(
                self.app.font_small.render(label, True, TEXT),
                (rect.x + 10, rect.y + 8),
            )
            lines = wrap_text(
                self.app.font_tiny,
                _asset_line(faction.assets),
                rect.width - 20,
            )
            y = rect.y + 32
            for line in lines[:3]:
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (rect.x + 10, y),
                )
                y += 18
            if faction.organization_snapshot:
                share = float(
                    faction.organization_snapshot.get("willing_share", 0.0)
                )
                active = int(
                    faction.organization_snapshot.get("active_count", 0)
                )
                initial = int(
                    faction.organization_snapshot.get("initial_count", 0)
                )
                info = "организация: %d/%d, воля %.2f" % (
                    active,
                    initial,
                    share,
                )
                screen.blit(
                    self.app.font_tiny.render(info, True, DIM),
                    (rect.x + 10, rect.bottom - 22),
                )

        _panel(screen, MID_RECT)
        screen.blit(
            self.app.font_small.render("РАБОТЫ ВАШЕЙ ФРАКЦИИ", True, MUTED),
            (MID_RECT.x + 12, MID_RECT.y + 12),
        )
        screen.blit(
            self.app.font_tiny.render(
                "Клик — выбрать, затем «Выполнить».", True, DIM
            ),
            (MID_RECT.x + 12, MID_RECT.y + 36),
        )
        options = self._options()
        if not options:
            screen.blit(
                self.app.font_small.render(
                    "Нет доступных работ: организация распалась.", True, BAD
                ),
                (MID_RECT.x + 12, MID_RECT.y + 68),
            )
        for rect, option in self._action_rows():
            action = option["action"]
            selected = option["id"] == self.selected_action_id
            enabled = bool(option.get("enabled"))
            background = (34, 48, 68) if selected else (24, 30, 43)
            pygame.draw.rect(screen, background, rect, border_radius=6)
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                2,
                border_radius=6,
            )
            color = TEXT if enabled else DIM
            screen.blit(
                self.app.font_small.render(
                    str(action.get("label") or option["id"]), True, color
                ),
                (rect.x + 10, rect.y + 7),
            )
            target = _target_name(self.campaign, action)
            cost = action.get("cost") or {}
            cost_text = ", ".join(
                "%s −%.2f" % (ASSET_LABELS.get(key, key), float(value))
                for key, value in cost.items()
            )
            detail = "цель: %s" % target
            if cost_text:
                detail += " · цена: %s" % cost_text
            if not enabled:
                detail += " · %s" % option.get("reason", "недоступно")
            screen.blit(
                self.app.font_tiny.render(detail, True, DIM),
                (rect.x + 10, rect.y + 33),
            )

        _panel(screen, RIGHT_RECT)
        screen.blit(
            self.app.font_small.render("ЖУРНАЛ РАБОТ", True, MUTED),
            (RIGHT_RECT.x + 12, RIGHT_RECT.y + 12),
        )
        y = RIGHT_RECT.y + 40
        if self.message:
            for line in wrap_text(
                self.app.font_tiny, self.message, RIGHT_RECT.width - 24
            )[:3]:
                screen.blit(
                    self.app.font_tiny.render(line, True, WARN),
                    (RIGHT_RECT.x + 12, y),
                )
                y += 18
            y += 8
        if self.last_result:
            result = self.last_result
            outcome_color = GOOD if result.get("success") else BAD
            header = "%s → %s · %s" % (
                result.get("actor_name", "?"),
                result.get("target_name", "?"),
                result.get("label", "работа"),
            )
            for line in wrap_text(
                self.app.font_small, header, RIGHT_RECT.width - 24
            )[:3]:
                screen.blit(
                    self.app.font_small.render(line, True, TEXT),
                    (RIGHT_RECT.x + 12, y),
                )
                y += 22
            chance = "шанс %.3f · бросок %.3f · %s" % (
                float(result.get("chance", 0.0)),
                float(result.get("roll", 0.0)),
                "успех" if result.get("success") else "провал",
            )
            screen.blit(
                self.app.font_tiny.render(chance, True, outcome_color),
                (RIGHT_RECT.x + 12, y),
            )
            y += 20
            text = str(result.get("text") or "")
            for line in wrap_text(
                self.app.font_tiny, text, RIGHT_RECT.width - 24
            )[:5]:
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (RIGHT_RECT.x + 12, y),
                )
                y += 17
            y += 8
        recent = self.campaign.events[-8:]
        if recent:
            screen.blit(
                self.app.font_tiny.render("ПОСЛЕДНИЕ СОБЫТИЯ", True, DIM),
                (RIGHT_RECT.x + 12, y),
            )
            y += 18
        for event in recent:
            text = str(event.get("text") or "")
            for line in wrap_text(
                self.app.font_tiny, text, RIGHT_RECT.width - 24
            )[:3]:
                if y > RIGHT_RECT.bottom - 22:
                    break
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (RIGHT_RECT.x + 12, y),
                )
                y += 15
            y += 2

        _panel(screen, BOTTOM_RECT)
        self._draw_button(
            screen,
            self._execute_rect(),
            "Выполнить выбранное",
            enabled=self.selected_action_id is not None
            and not self.campaign.finished,
        )
        self._draw_button(
            screen,
            self._end_turn_rect(),
            "Завершить ход",
            enabled=not self.campaign.finished,
            accent=True,
        )
        if self.campaign.finished:
            self._draw_button(
                screen,
                self._finish_rect(),
                "Принять исход",
                accent=True,
            )
        else:
            hint = "Выбрано: %s" % (
                self.selected_action_id or "ход по приоритету ИИ"
            )
            screen.blit(
                self.app.font_tiny.render(hint, True, DIM),
                (self._finish_rect().x, BOTTOM_RECT.y + 20),
            )
