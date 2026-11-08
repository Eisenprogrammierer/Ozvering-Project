"""Сеть автоматов: иерархия органов и действия внутри неё.

Экран показывает только сеть игрока: корень — фракция, ниже — уровни
органов, связанные через ``parent_id``. Поэтому видна вертикаль
подчинения (например, ``Панцерваффе → Вермахт → Имперская ставка``), а
чужие фракции нельзя выбрать или усилить.

В сети три режима действий:

* ``АВТОМАТЫ`` — выбранный орган отдаёт команду другому автомату
  (согласование, передача резерва, директива подчинённому, запрос
  поддержки у вышестоящего);
* ``ВЛИЯНИЕ`` — игрок усиливает, реформирует, чистит или снабжает орган;
* ``ПЕРСОНАЛ`` — влияние на людей своей фракции.

Работы, влияния и команды автоматов тратят ограниченный бюджет действий.
Кампания идёт в реальном времени; ускорение можно включить и отменить,
но нельзя опуститься ниже ``1×`` или поставить паузу.
"""

from __future__ import annotations

import pygame

from campaign.fractal import organ_depths
from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import wrap_text
from view.support.log_journal import get_logger

logger = get_logger("view.automata_network")

WIDTH, HEIGHT = 1280, 720
GRAPH_RECT = pygame.Rect(24, 96, 812, 430)
DETAIL_RECT = pygame.Rect(24, 536, 812, 112)
SIDE_RECT = pygame.Rect(852, 96, 404, 552)
BOTTOM_RECT = pygame.Rect(24, 660, 1232, 44)

PANEL_BG = (18, 23, 33, 242)
PANEL_BORDER = (58, 70, 92)
TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
BAD = (226, 112, 112)
WARN = (230, 184, 96)
EDGE = (62, 78, 104)
PATH_EDGE = (78, 155, 224)
NODE_W = 148
NODE_H = 40
ROOT_H = 54
NODE_GAP_Y = 10
INTERACTION_ROW_H = 46
CHARACTER_ROW_H = 26
CHARACTER_VISIBLE = 5

KIND_LABELS = {
    "command": "командование",
    "coercion": "принуждение",
    "intelligence": "разведка",
    "information": "информация",
    "maintenance": "обеспечение",
    "legitimacy": "законность",
    "care": "забота",
    "meaning": "смысл",
    "exchange": "обмен",
    "support": "поддержка",
}

NEED_LABELS = {
    "hunger": "голод",
    "thirst": "жажда",
    "fatigue": "усталость",
    "health": "здоровье",
    "fear": "страх",
    "anxiety": "тревога",
    "loneliness": "одиночество",
    "reproduction": "близость",
    "knowledge": "знание",
    "creativity": "творчество",
    "boredom": "скука",
    "status": "статус",
    "spirituality": "вера",
    "skill": "навык",
    "love": "любовь",
    "friendship": "дружба",
}

TRAIT_LABELS = {
    "courage": "смелость",
    "discipline": "дисциплина",
    "aggression": "агрессия",
    "empathy": "эмпатия",
    "curiosity": "любопытство",
    "creativity": "творчество",
    "ambition": "амбиции",
    "spirituality": "вера",
    "sociability": "общительность",
    "loyalty": "лояльность",
    "fanaticism": "фанатизм",
    "endurance": "выносливость",
}


def _panel(surface, rect):
    shape = pygame.Surface(rect.size, pygame.SRCALPHA)
    shape.fill(PANEL_BG)
    surface.blit(shape, rect.topleft)
    pygame.draw.rect(surface, PANEL_BORDER, rect, 2, border_radius=8)


def _integrity_color(value):
    if value >= 0.65:
        return GOOD
    if value >= 0.35:
        return WARN
    return BAD


def _draw_bar(surface, rect, value, color):
    pygame.draw.rect(surface, (32, 39, 52), rect, border_radius=3)
    filled = rect.copy()
    filled.width = int(rect.width * max(0.0, min(1.0, float(value))))
    if filled.width > 0:
        pygame.draw.rect(surface, color, filled, border_radius=3)
    pygame.draw.rect(surface, PANEL_BORDER, rect, 1, border_radius=3)


def _money(cost):
    return ", ".join(
        "%s −%.2f" % (key, float(value))
        for key, value in (cost or {}).items()
    ) or "без цены"


def _signed(value, digits=2):
    return "%+.*f" % (digits, float(value))


class AutomataNetworkScreen(BaseScreen):

    show_time_hud = False
    escape_action = "pop"

    def __init__(self, app, campaign):
        super().__init__(app)
        self.campaign = campaign
        self.mode = "automata"
        self.selected_faction_side = campaign.player_side
        self.campaign.begin_turn()
        faction = self._faction()
        self.selected_organ_id = self._default_organ_id(faction)
        self.selected_interaction_id = None
        self.selected_automaton_interaction_id = None
        self.selected_automaton_target_id = None
        characters = self._characters()
        self.selected_character_id = (
            characters[0]["id"] if characters else None
        )
        self.selected_character_interaction_id = None
        self.character_scroll = 0
        self.message = ""
        self.last_result = None
        self._faction_rect = None
        self._organ_rects = {}
        self._character_rects = {}
        self._interaction_rects = []
        self._apply_rect = pygame.Rect(
            SIDE_RECT.x + 14,
            SIDE_RECT.bottom - 48,
            SIDE_RECT.width - 28,
            38,
        )
        self._back_rect = pygame.Rect(
            BOTTOM_RECT.right - 140, BOTTOM_RECT.y + 4, 130, 36
        )
        self._end_turn_rect = pygame.Rect(
            self._back_rect.x - 170, BOTTOM_RECT.y + 4, 160, 36
        )
        self._slow_down_rect = pygame.Rect(
            self._end_turn_rect.x - 150, BOTTOM_RECT.y + 4, 140, 36
        )
        self._automata_tab_rect = pygame.Rect(
            SIDE_RECT.x + 14, SIDE_RECT.y + 48, 118, 28
        )
        self._organs_tab_rect = pygame.Rect(
            SIDE_RECT.x + 140, SIDE_RECT.y + 48, 118, 28
        )
        self._characters_tab_rect = pygame.Rect(
            SIDE_RECT.x + 266, SIDE_RECT.y + 48, 124, 28
        )
        self._sync_storyline()
        logger.info(
            "Сеть автоматов: фракций=%d, выбран орган %s, действий %d/%d",
            len(campaign.factions),
            self.selected_organ_id,
            campaign.actions_left,
            campaign.actions_per_turn,
        )

    # ------------------------------------------------------------------
    # Состояние
    # ------------------------------------------------------------------
    def _faction(self):
        return self.campaign.faction(self.campaign.player_side)

    def _organs(self):
        faction = self._faction()
        return list(faction.organs) if faction is not None else []

    def _organ(self):
        faction = self._faction()
        if faction is None or self.selected_organ_id is None:
            return None
        return faction.organ(self.selected_organ_id)

    def _default_organ_id(self, faction):
        if faction is None or not faction.organs:
            return None
        for organ in faction.organs:
            if not organ.parent_id:
                return organ.id
        return faction.organs[0].id

    def _characters(self):
        return self.campaign.character_options(self.campaign.player_side)

    def _character(self):
        if self.selected_character_id is None:
            return None
        return self.campaign.character(
            self.campaign.player_side, self.selected_character_id
        )

    def _character_snapshot(self):
        character = self._character()
        if character is None:
            return None
        return self._faction().character_snapshot(character)

    def _interaction_options(self):
        organ = self._organ()
        if organ is None:
            return []
        return self.campaign.organ_interaction_options(
            self.campaign.player_side, organ.id
        )

    def _character_interaction_options(self):
        if self.selected_character_id is None:
            return []
        return self.campaign.character_interaction_options(
            self.campaign.player_side, self.selected_character_id
        )

    def _selected_interaction(self):
        if self.selected_interaction_id is None:
            return None
        return next(
            (
                item
                for item in self._interaction_options()
                if item["id"] == self.selected_interaction_id
            ),
            None,
        )

    def _automaton_interaction_options(self):
        organ = self._organ()
        if organ is None:
            return []
        return self.campaign.automaton_interaction_options(
            self.campaign.player_side, organ.id
        )

    def _selected_automaton_interaction(self):
        if self.selected_automaton_interaction_id is None:
            return None
        return next(
            (
                item
                for item in self._automaton_interaction_options()
                if item["id"] == self.selected_automaton_interaction_id
            ),
            None,
        )

    def _selected_automaton_target(self):
        if self.selected_automaton_target_id is None:
            return None
        option = self._selected_automaton_interaction()
        if option is None:
            return None
        return next(
            (
                target
                for target in option.get("targets", ())
                if target["id"] == self.selected_automaton_target_id
            ),
            None,
        )

    def _automaton_target_ids(self):
        option = self._selected_automaton_interaction()
        if option is None or self.mode != "automata":
            return set()
        return {target["id"] for target in option.get("targets", ())}

    def _selected_character_interaction(self):
        if self.selected_character_interaction_id is None:
            return None
        return next(
            (
                item
                for item in self._character_interaction_options()
                if item["id"] == self.selected_character_interaction_id
            ),
            None,
        )

    def _path_ids(self):
        organ = self._organ()
        if organ is None:
            return set()
        organs = {item.id: item for item in self._organs()}
        result = {organ.id}
        current = organ
        while current is not None and current.parent_id:
            result.add(current.parent_id)
            current = organs.get(current.parent_id)
        return result

    def _sync_storyline(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return
        snapshot = self.campaign.snapshot()
        interp.state["automata"] = snapshot
        interp.set_variable("automata_elapsed", snapshot["elapsed"])
        interp.set_variable("automata_speed", snapshot["speed"])

    def update(self, dt):
        """Реальное время не останавливается при открытой сети."""
        if self.campaign.finished:
            return
        before = self.campaign.turn
        self.campaign.advance_time(dt)
        if self.campaign.turn != before or self.campaign.finished:
            self._sync_storyline()
        if self.campaign.finished:
            self._check_storyline_outcome()

    def _increase_speed(self):
        if self.campaign.finished:
            return
        before = self.campaign.speed
        self.campaign.speed_up()
        if self.campaign.speed != before:
            self.message = "Скорость времени: %s." % self.campaign.speed_label()
        else:
            self.message = (
                "Достигнута максимальная скорость: %s."
                % self.campaign.speed_label()
            )

    def _decrease_speed(self):
        """Отменить одно ускорение, но не опускаться ниже ``1×``."""
        if self.campaign.finished:
            return
        before = self.campaign.speed
        self.campaign.slow_down()
        if self.campaign.speed != before:
            self.message = (
                "Ускорение отменено: скорость %s."
                % self.campaign.speed_label()
            )
        else:
            self.message = (
                "Минимальная скорость: %s." % self.campaign.speed_label()
            )

    def select_faction(self, side):
        """Выбрать можно только свою фракцию."""
        if str(side) != self.campaign.player_side:
            self.message = (
                "В режиме сети можно влиять только на свою фракцию."
            )
            logger.info("Сеть: отклонена чужая фракция %s", side)
            return False
        faction = self._faction()
        if faction is None:
            return False
        self.selected_faction_side = faction.side
        self.selected_organ_id = self._default_organ_id(faction)
        self.selected_interaction_id = None
        self.selected_automaton_interaction_id = None
        self.selected_automaton_target_id = None
        self.message = ""
        self.last_result = None
        return True

    def select_organ(self, organ_id, mode=None):
        faction = self._faction()
        if faction is None or faction.organ(organ_id) is None:
            self.message = "Этот орган не принадлежит вашей фракции."
            return False
        if mode in ("automata", "organs", "characters"):
            self.mode = mode
        elif self.mode not in ("automata", "organs"):
            self.mode = "organs"
        self.selected_organ_id = str(organ_id)
        self.selected_interaction_id = None
        self.selected_automaton_interaction_id = None
        self.selected_automaton_target_id = None
        self.message = ""
        return True

    def select_interaction(self, interaction_id):
        option = next(
            (
                item
                for item in self._interaction_options()
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return False
        self.selected_interaction_id = option["id"]
        self.message = ""
        return True

    def select_automaton_interaction(self, interaction_id):
        option = next(
            (
                item
                for item in self._automaton_interaction_options()
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return False
        if self.selected_automaton_interaction_id == option["id"]:
            self.selected_automaton_interaction_id = None
            self.selected_automaton_target_id = None
            self.message = ""
            return True
        self.selected_automaton_interaction_id = option["id"]
        self.selected_automaton_target_id = None
        if option.get("targets"):
            self.message = (
                "Выберите автомат-цель в графе: %s."
                % ", ".join(
                    target["name"] for target in option["targets"][:3]
                )
            )
        else:
            self.message = option.get("reason") or "Нет доступных целей."
        return True

    def select_automaton_target(self, target_id):
        option = self._selected_automaton_interaction()
        if option is None:
            self.message = "Сначала выберите команду автомата."
            return False
        target = next(
            (
                item
                for item in option.get("targets", ())
                if item["id"] == str(target_id)
            ),
            None,
        )
        if target is None:
            self.message = "Эта цель не подходит для выбранной команды."
            return False
        self.selected_automaton_target_id = target["id"]
        self.message = "Цель: %s. Нажмите «Применить»." % target["name"]
        return True

    def select_character(self, character_id):
        character = self.campaign.character(
            self.campaign.player_side, character_id
        )
        if character is None:
            self.message = "Этот персонаж не принадлежит вашей фракции."
            return False
        self.mode = "characters"
        self.selected_character_id = str(character_id)
        self.selected_character_interaction_id = None
        self.message = ""
        return True

    def select_character_interaction(self, interaction_id):
        option = next(
            (
                item
                for item in self._character_interaction_options()
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return False
        self.selected_character_interaction_id = option["id"]
        self.message = ""
        return True

    def _budget_message(self):
        return (
            "Действия восстанавливаются со временем (%d за цикл)."
            % self.campaign.actions_per_turn
        )

    def _apply_result(self, result):
        self._sync_storyline()
        if not result or not result.get("ok"):
            self.message = (
                result.get("reason") if result else "Действие не выполнено."
            )
            return result
        self.message = ""
        self.last_result = result
        if result.get("kind") == "automaton" or "source_organ_id" in result:
            self.message = (
                "%s → %s: %s; цель %.0f%% → %.0f%%; действий осталось %d"
                % (
                    result.get("source_organ_name", "автомат"),
                    result.get("target_organ_name", "цель"),
                    result.get("label", "команда"),
                    float(result.get("target_integrity_before", 0.0))
                    * 100.0,
                    float(result.get("target_integrity_after", 0.0))
                    * 100.0,
                    self.campaign.actions_left,
                )
            )
        elif result.get("kind") == "character" or "character_name" in result:
            self.message = (
                "%s: %s; мораль %.0f → %.0f; действий осталось %d"
                % (
                    result.get("character_name", "персонаж"),
                    result.get("label", "действие"),
                    float(result.get("morale_before", 0.0)),
                    float(result.get("morale_after", 0.0)),
                    self.campaign.actions_left,
                )
            )
        else:
            self.message = (
                "%s: целостность %.0f%% → %.0f%%; действий осталось %d"
                % (
                    result.get("label", "взаимодействие"),
                    float(result.get("integrity_before", 0.0)) * 100.0,
                    float(result.get("integrity_after", 0.0)) * 100.0,
                    self.campaign.actions_left,
                )
            )
        if self.campaign.finished:
            self._check_storyline_outcome()
        return result

    def apply_interaction(self):
        organ = self._organ()
        if organ is None:
            self.message = "Сначала выберите орган."
            return None
        if self.selected_interaction_id is None:
            self.message = "Сначала выберите взаимодействие."
            return None
        option = self._selected_interaction()
        if option is None or not option.get("enabled"):
            self.message = (
                option.get("reason")
                if option
                else "Взаимодействие недоступно."
            )
            return None
        if self.campaign.finished:
            self.message = "Кампания уже завершена."
            return None
        if self.campaign.actions_left <= 0 and self.campaign.action_budget()[
            "active"
        ]:
            self.message = self._budget_message()
            return None
        self.campaign.begin_turn()
        result = self.campaign.perform_organ_interaction(
            self.campaign.player_side,
            organ.id,
            self.selected_interaction_id,
        )
        result = dict(result)
        result["kind"] = "organ"
        self.selected_interaction_id = None
        logger.info(
            "Сеть: %s → %s; целостность %s → %s; ход %d; действий %d",
            result.get("organ_name", "?"),
            result.get("interaction_id", "?"),
            result.get("integrity_before"),
            result.get("integrity_after"),
            self.campaign.turn,
            self.campaign.actions_left,
        )
        return self._apply_result(result)

    def apply_automaton_interaction(self):
        organ = self._organ()
        if organ is None:
            self.message = "Сначала выберите автомат-источник."
            return None
        if self.selected_automaton_interaction_id is None:
            self.message = "Сначала выберите команду автомата."
            return None
        if self.selected_automaton_target_id is None:
            self.message = "Выберите автомат-цель в графе."
            return None
        option = self._selected_automaton_interaction()
        if option is None or not option.get("enabled"):
            self.message = (
                option.get("reason")
                if option
                else "Команда недоступна."
            )
            return None
        if self.campaign.finished:
            self.message = "Кампания уже завершена."
            return None
        if self.campaign.actions_left <= 0 and self.campaign.action_budget()[
            "active"
        ]:
            self.message = self._budget_message()
            return None
        self.campaign.begin_turn()
        result = self.campaign.perform_automaton_interaction(
            self.campaign.player_side,
            organ.id,
            self.selected_automaton_target_id,
            self.selected_automaton_interaction_id,
        )
        result = dict(result)
        result["kind"] = "automaton"
        self.selected_automaton_interaction_id = None
        self.selected_automaton_target_id = None
        logger.info(
            "Сеть: автомат %s → %s (%s); цель %s → %s; ход %d; действий %d",
            result.get("source_organ_name", "?"),
            result.get("target_organ_name", "?"),
            result.get("interaction_id", "?"),
            result.get("target_integrity_before"),
            result.get("target_integrity_after"),
            self.campaign.turn,
            self.campaign.actions_left,
        )
        return self._apply_result(result)

    def apply_character_interaction(self):
        character = self._character()
        if character is None:
            self.message = "Сначала выберите персонажа."
            return None
        if self.selected_character_interaction_id is None:
            self.message = "Сначала выберите действие."
            return None
        option = self._selected_character_interaction()
        if option is None or not option.get("enabled"):
            self.message = (
                option.get("reason")
                if option
                else "Действие недоступно."
            )
            return None
        if self.campaign.finished:
            self.message = "Кампания уже завершена."
            return None
        if self.campaign.actions_left <= 0 and self.campaign.action_budget()[
            "active"
        ]:
            self.message = self._budget_message()
            return None
        self.campaign.begin_turn()
        result = self.campaign.perform_character_interaction(
            self.campaign.player_side,
            self.selected_character_id,
            self.selected_character_interaction_id,
        )
        result = dict(result)
        result["kind"] = "character"
        self.selected_character_interaction_id = None
        logger.info(
            "Сеть: персонаж %s → %s; мораль %s → %s; ход %d; действий %d",
            result.get("character_name", "?"),
            result.get("interaction_id", "?"),
            result.get("morale_before"),
            result.get("morale_after"),
            self.campaign.turn,
            self.campaign.actions_left,
        )
        return self._apply_result(result)

    def apply_current(self):
        if self.mode == "characters":
            return self.apply_character_interaction()
        if self.mode == "automata":
            return self.apply_automaton_interaction()
        return self.apply_interaction()

    def end_turn(self):
        if self.campaign.finished:
            return None
        self.campaign.end_turn()
        if self.campaign.finished:
            self.message = "Кампания завершена."
            self._check_storyline_outcome()
            self._sync_storyline()
            return None
        self.campaign.begin_turn()
        self.last_result = None
        self.selected_interaction_id = None
        self.selected_automaton_interaction_id = None
        self.selected_automaton_target_id = None
        self.selected_character_interaction_id = None
        self.message = (
            "Ход завершён. Начат ход %d; действий: %d."
            % (self.campaign.turn, self.campaign.actions_left)
        )
        self._sync_storyline()
        logger.info(
            "Сеть: ход завершён, начат ход %d, действий %d",
            self.campaign.turn,
            self.campaign.actions_left,
        )
        return None

    def _check_storyline_outcome(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None or self.campaign.outcome is None:
            return
        if interp.check_lose_conditions():
            self.app.finish_storyline_outcome("lose")
        elif interp.check_win_conditions():
            self.app.finish_storyline_outcome("win")

    # ------------------------------------------------------------------
    # Раскладка
    # ------------------------------------------------------------------
    def _layout(self):
        self._organ_rects = {}
        self._faction_rect = None
        faction = self._faction()
        if faction is None:
            return
        depths = organ_depths(faction.organs)
        max_depth = max(depths.values(), default=0)
        columns = max_depth + 2
        available = GRAPH_RECT.width - 32
        min_gap = 12
        gap = max(
            min_gap,
            min(
                36,
                int(
                    (available - columns * NODE_W)
                    / float(max(1, columns - 1))
                ),
            ),
        )
        total_width = columns * NODE_W + (columns - 1) * gap
        start_x = GRAPH_RECT.x + (GRAPH_RECT.width - total_width) // 2
        tree_top = GRAPH_RECT.y + 62
        tree_bottom = GRAPH_RECT.bottom - 12
        level_nodes = {}
        for organ in faction.organs:
            level_nodes.setdefault(depths.get(organ.id, 0), []).append(organ)
        for level, organs in level_nodes.items():
            organs.sort(key=lambda item: item.name)
            column = level + 1
            x = start_x + column * (NODE_W + gap)
            total_height = (
                len(organs) * NODE_H + (len(organs) - 1) * NODE_GAP_Y
            )
            available_height = tree_bottom - tree_top
            if total_height > available_height:
                step = max(
                    NODE_H,
                    (available_height - NODE_H)
                    // max(1, len(organs) - 1),
                )
            else:
                step = NODE_H + NODE_GAP_Y
            block = NODE_H + (len(organs) - 1) * step
            y = tree_top + max(0, (available_height - block) // 2)
            for organ in organs:
                self._organ_rects[organ.id] = pygame.Rect(
                    x, y, NODE_W, NODE_H
                )
                y += step
        root_x = start_x
        root_y = (tree_top + tree_bottom) // 2 - ROOT_H // 2
        self._faction_rect = pygame.Rect(
            root_x, root_y, NODE_W, ROOT_H
        )

    def organ_rect(self, organ_id):
        if not self._organ_rects:
            self._layout()
        return self._organ_rects.get(str(organ_id))

    def _interaction_rows(self):
        if self.mode == "characters":
            interaction_top = SIDE_RECT.y + 244
            options = self._character_interaction_options()[:4]
        elif self.mode == "automata":
            interaction_top = SIDE_RECT.y + 104
            options = self._automaton_interaction_options()[:4]
        else:
            interaction_top = SIDE_RECT.y + 104
            options = self._interaction_options()[:4]
        rows = []
        for index, option in enumerate(options):
            rect = pygame.Rect(
                SIDE_RECT.x + 14,
                interaction_top + index * INTERACTION_ROW_H,
                SIDE_RECT.width - 28,
                INTERACTION_ROW_H - 6,
            )
            rows.append((rect, option))
        return rows

    def _character_rows(self):
        characters = self._characters()
        visible = characters[
            self.character_scroll : self.character_scroll + CHARACTER_VISIBLE
        ]
        rows = []
        top = SIDE_RECT.y + 104
        for index, character in enumerate(visible):
            rect = pygame.Rect(
                SIDE_RECT.x + 14,
                top + index * CHARACTER_ROW_H,
                SIDE_RECT.width - 28,
                CHARACTER_ROW_H - 2,
            )
            rows.append((rect, character))
        return rows

    # ------------------------------------------------------------------
    # Ввод
    # ------------------------------------------------------------------
    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL and self.mode == "characters":
            pos = pygame.mouse.get_pos()
            list_rect = pygame.Rect(
                SIDE_RECT.x + 14,
                SIDE_RECT.y + 104,
                SIDE_RECT.width - 28,
                CHARACTER_VISIBLE * CHARACTER_ROW_H,
            )
            if list_rect.collidepoint(pos):
                total = len(self._characters())
                self.character_scroll = max(
                    0,
                    min(
                        max(0, total - CHARACTER_VISIBLE),
                        self.character_scroll - event.y,
                    ),
                )
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        self._layout()
        pos = event.pos
        if self._back_rect.collidepoint(pos):
            self.app.manager.pop()
            return
        if self._end_turn_rect.collidepoint(pos):
            self._increase_speed()
            return
        if self._slow_down_rect.collidepoint(pos):
            self._decrease_speed()
            return
        if self._automata_tab_rect.collidepoint(pos):
            self.mode = "automata"
            self.selected_automaton_interaction_id = None
            self.selected_automaton_target_id = None
            self.message = ""
            return
        if self._organs_tab_rect.collidepoint(pos):
            self.mode = "organs"
            self.selected_automaton_interaction_id = None
            self.selected_automaton_target_id = None
            self.message = ""
            return
        if self._characters_tab_rect.collidepoint(pos):
            self.mode = "characters"
            self.selected_automaton_interaction_id = None
            self.selected_automaton_target_id = None
            self.message = ""
            return
        for organ_id, rect in self._organ_rects.items():
            if rect.collidepoint(pos):
                if (
                    self.mode == "automata"
                    and self.selected_automaton_interaction_id is not None
                ):
                    self.select_automaton_target(organ_id)
                else:
                    self.select_organ(organ_id)
                return
        for rect, character in self._character_rows():
            if rect.collidepoint(pos):
                self.select_character(character["id"])
                return
        for rect, option in self._interaction_rows():
            if rect.collidepoint(pos):
                if option.get("enabled"):
                    if self.mode == "characters":
                        self.select_character_interaction(option["id"])
                    elif self.mode == "automata":
                        self.select_automaton_interaction(option["id"])
                    else:
                        self.select_interaction(option["id"])
                else:
                    self.message = str(
                        option.get("reason") or "Недоступно."
                    )
                return
        if self._apply_rect.collidepoint(pos):
            self.apply_current()

    # ------------------------------------------------------------------
    # Отрисовка графа
    # ------------------------------------------------------------------
    def _draw_edge(self, screen, start, end, color, width):
        middle_x = (start[0] + end[0]) // 2
        pygame.draw.lines(
            screen,
            color,
            False,
            [start, (middle_x, start[1]), (middle_x, end[1]), end],
            width,
        )

    def _draw_graph(self, screen):
        _panel(screen, GRAPH_RECT)
        screen.blit(
            self.app.font_small.render(
                "ИЕРАРХИЯ АВТОМАТОВ · ТОЛЬКО ВАША ФРАКЦИЯ", True, MUTED
            ),
            (GRAPH_RECT.x + 14, GRAPH_RECT.y + 12),
        )
        if self.mode == "automata" and self._selected_automaton_interaction():
            hint = "ВЫБЕРИТЕ АВТОМАТ-ЦЕЛЬ В ГРАФЕ"
            surf = self.app.font_tiny.render(hint, True, WARN)
            screen.blit(surf, (GRAPH_RECT.right - surf.get_width() - 14, GRAPH_RECT.y + 14))
        faction = self._faction()
        if faction is None or self._faction_rect is None:
            return
        depths = organ_depths(faction.organs)
        max_depth = max(depths.values(), default=0)
        for depth in range(max_depth + 1):
            rects = [
                rect
                for organ_id, rect in self._organ_rects.items()
                if depths.get(organ_id, 0) == depth
            ]
            if not rects:
                continue
            x = min(rect.x for rect in rects)
            label = "УРОВЕНЬ %d" % (depth + 1)
            screen.blit(
                self.app.font_tiny.render(label, True, DIM),
                (x + 2, GRAPH_RECT.y + 40),
            )

        path = self._path_ids()
        target_ids = self._automaton_target_ids()
        organs = {item.id: item for item in faction.organs}
        for organ in faction.organs:
            source = self._faction_rect
            if organ.parent_id and organ.parent_id in organs:
                source = self._organ_rects.get(organ.parent_id)
            target = self._organ_rects.get(organ.id)
            if source is None or target is None:
                continue
            highlighted = (
                organ.id in path and organ.parent_id in path
            )
            self._draw_edge(
                screen,
                (source.right, source.centery),
                (target.left, target.centery),
                PATH_EDGE if highlighted else EDGE,
                3 if highlighted else 1,
            )

        # Корень — сама фракция.
        pygame.draw.rect(
            screen, (34, 48, 68), self._faction_rect, border_radius=8
        )
        pygame.draw.rect(
            screen, ACCENT, self._faction_rect, 2, border_radius=8
        )
        for line_number, line in enumerate(
            wrap_text(
                self.app.font_small,
                faction.name,
                self._faction_rect.width - 14,
            )[:2]
        ):
            screen.blit(
                self.app.font_small.render(line, True, TEXT),
                (
                    self._faction_rect.x + 7,
                    self._faction_rect.y + 8 + line_number * 18,
                ),
            )
        screen.blit(
            self.app.font_tiny.render(
                "корень · вы", True, ACCENT
            ),
            (
                self._faction_rect.x + 7,
                self._faction_rect.bottom - 18,
            ),
        )

        for organ in faction.organs:
            rect = self._organ_rects.get(organ.id)
            if rect is None:
                continue
            selected = organ.id == self.selected_organ_id
            on_path = organ.id in path
            is_target = organ.id == self.selected_automaton_target_id
            is_candidate = organ.id in target_ids
            fill = (34, 48, 68) if selected else (
                (27, 38, 54) if on_path else (22, 28, 40)
            )
            pygame.draw.rect(screen, fill, rect, border_radius=6)
            if is_target:
                border_color = GOOD
                border_width = 3
            elif is_candidate:
                border_color = WARN
                border_width = 2
            else:
                border_color = ACCENT if selected else (
                    (84, 118, 158) if on_path else PANEL_BORDER
                )
                border_width = 2
            pygame.draw.rect(
                screen,
                border_color,
                rect,
                border_width,
                border_radius=6,
            )
            for line_number, line in enumerate(
                wrap_text(
                    self.app.font_tiny,
                    organ.name,
                    rect.width - 12,
                )[:2]
            ):
                screen.blit(
                    self.app.font_tiny.render(
                        line, True, TEXT if selected else MUTED
                    ),
                    (rect.x + 6, rect.y + 4 + line_number * 11),
                )
            bar = pygame.Rect(
                rect.x + 6, rect.bottom - 11, rect.width - 36, 6
            )
            _draw_bar(
                screen,
                bar,
                organ.integrity,
                _integrity_color(organ.integrity),
            )
            screen.blit(
                self.app.font_tiny.render(
                    "%.0f%%" % (organ.integrity * 100.0), True, DIM
                ),
                (rect.right - 29, rect.bottom - 17),
            )

    # ------------------------------------------------------------------
    # Отрисовка деталей и боковой панели
    # ------------------------------------------------------------------
    def _draw_detail(self, screen):
        _panel(screen, DETAIL_RECT)
        if self.mode == "characters":
            self._draw_character_detail(screen)
            return
        organ = self._organ()
        if organ is None:
            screen.blit(
                self.app.font_small.render(
                    "ОРГАН НЕ ВЫБРАН", True, MUTED
                ),
                (DETAIL_RECT.x + 16, DETAIL_RECT.y + 14),
            )
            return
        organs = {item.id: item for item in self._organs()}
        chain = [organ.name]
        current = organ
        while current is not None and current.parent_id:
            parent = organs.get(current.parent_id)
            if parent is None:
                break
            chain.append(parent.name)
            current = parent
        chain.append(self._faction().name)
        screen.blit(
            self.app.font_small.render(
                "ОРГАН · %s"
                % KIND_LABELS.get(organ.kind, organ.kind).upper(),
                True,
                MUTED,
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 10),
        )
        screen.blit(
            self.app.font_body.render(organ.name, True, TEXT),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 30),
        )
        chain_text = "подчинение: " + " → ".join(chain)
        screen.blit(
            self.app.font_tiny.render(
                chain_text, True, ACCENT
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 58),
        )
        status = "%s · целостность %.0f%%" % (
            organ.status(),
            organ.integrity * 100.0,
        )
        screen.blit(
            self.app.font_tiny.render(
                status, True, _integrity_color(organ.integrity)
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 76),
        )
        bar = pygame.Rect(
            DETAIL_RECT.x + 250, DETAIL_RECT.y + 78, 200, 9
        )
        _draw_bar(
            screen,
            bar,
            organ.integrity,
            _integrity_color(organ.integrity),
        )
        screen.blit(
            self.app.font_tiny.render(
                "Работы: "
                + (
                    " · ".join(
                        str(
                            (
                                self._faction().action(action_id)
                                if self._faction()
                                else {}
                            ).get("label")
                            or action_id
                        )
                        for action_id in organ.action_ids
                    )
                    or "нет прямых работ"
                ),
                True,
                MUTED,
            ),
            (DETAIL_RECT.x + 470, DETAIL_RECT.y + 72),
        )

    def _draw_character_detail(self, screen):
        snapshot = self._character_snapshot()
        if snapshot is None:
            screen.blit(
                self.app.font_small.render(
                    "ПЕРСОНАЖ НЕ ВЫБРАН", True, MUTED
                ),
                (DETAIL_RECT.x + 16, DETAIL_RECT.y + 14),
            )
            return
        screen.blit(
            self.app.font_small.render(
                "ПЕРСОНАЖ · %s"
                % (
                    "лидер фракции"
                    if snapshot.get("is_leader")
                    else snapshot.get("post") or "участник"
                ).upper(),
                True,
                MUTED,
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 10),
        )
        screen.blit(
            self.app.font_body.render(
                snapshot["name"], True, TEXT
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 30),
        )
        organ_id = snapshot.get("organ_id") or ""
        organ = self._faction().organ(organ_id)
        organ_text = (
            "орган: %s" % organ.name
            if organ is not None
            else "орган: не назначен"
        )
        screen.blit(
            self.app.font_tiny.render(
                "%s · %s"
                % (
                    snapshot.get("post") or "без должности",
                    organ_text,
                ),
                True,
                ACCENT if organ is not None else MUTED,
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 58),
        )
        morale = float(snapshot.get("morale", 0.0))
        screen.blit(
            self.app.font_tiny.render(
                "мораль %.0f" % morale, True, _integrity_color(morale / 100.0)
            ),
            (DETAIL_RECT.x + 16, DETAIL_RECT.y + 78),
        )
        bar = pygame.Rect(DETAIL_RECT.x + 100, DETAIL_RECT.y + 80, 180, 9)
        _draw_bar(
            screen, bar, morale / 100.0, _integrity_color(morale / 100.0)
        )
        needs = sorted(
            snapshot.get("needs", {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:3]
        text = "потребности: " + " · ".join(
            "%s %.2f" % (NEED_LABELS.get(key, key), value)
            for key, value in needs
        )
        screen.blit(
            self.app.font_tiny.render(text, True, MUTED),
            (DETAIL_RECT.x + 300, DETAIL_RECT.y + 72),
        )
        traits = sorted(
            snapshot.get("personality", {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:2]
        screen.blit(
            self.app.font_tiny.render(
                "черты: "
                + " · ".join(
                    "%s %.2f" % (TRAIT_LABELS.get(key, key), value)
                    for key, value in traits
                ),
                True,
                DIM,
            ),
            (DETAIL_RECT.x + 300, DETAIL_RECT.y + 90),
        )

    def _draw_tabs(self, screen):
        for rect, mode, label in (
            (self._automata_tab_rect, "automata", "АВТОМАТЫ"),
            (self._organs_tab_rect, "organs", "ВЛИЯНИЕ"),
            (self._characters_tab_rect, "characters", "ПЕРСОНАЛ"),
        ):
            selected = self.mode == mode
            pygame.draw.rect(
                screen,
                (34, 48, 68) if selected else (24, 30, 43),
                rect,
                border_radius=6,
            )
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                2,
                border_radius=6,
            )
            text = self.app.font_tiny.render(
                label, True, TEXT if selected else MUTED
            )
            screen.blit(text, text.get_rect(center=rect.center))

    def _draw_character_list(self, screen):
        characters = self._characters()
        if not characters:
            screen.blit(
                self.app.font_tiny.render(
                    "В вашей фракции нет персонажей.", True, DIM
                ),
                (SIDE_RECT.x + 14, SIDE_RECT.y + 104),
            )
            return
        for rect, character in self._character_rows():
            selected = character["id"] == self.selected_character_id
            pygame.draw.rect(
                screen,
                (34, 48, 68) if selected else (22, 28, 40),
                rect,
                border_radius=4,
            )
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                1,
                border_radius=4,
            )
            label = character["name"]
            if character.get("is_leader"):
                label += " · лидер"
            screen.blit(
                self.app.font_tiny.render(
                    label, True, TEXT if selected else MUTED
                ),
                (rect.x + 6, rect.y + 2),
            )
            screen.blit(
                self.app.font_tiny.render(
                    "%s · мораль %.0f"
                    % (
                        character.get("post") or "участник",
                        float(character.get("morale", 0.0)),
                    ),
                    True,
                    DIM,
                ),
                (rect.x + 6, rect.y + 13),
            )
        if len(characters) > CHARACTER_VISIBLE:
            screen.blit(
                self.app.font_tiny.render(
                    "колесо мыши: прокрутка %d/%d"
                    % (
                        self.character_scroll + 1,
                        max(0, len(characters) - CHARACTER_VISIBLE + 1),
                    ),
                    True,
                    DIM,
                ),
                (
                    SIDE_RECT.x + 14,
                    SIDE_RECT.y + 104
                    + CHARACTER_VISIBLE * CHARACTER_ROW_H
                    - 2,
                ),
            )

    def _draw_side(self, screen):
        _panel(screen, SIDE_RECT)
        screen.blit(
            self.app.font_small.render(
                "УПРАВЛЕНИЕ СВОЕЙ СЕТЬЮ", True, MUTED
            ),
            (SIDE_RECT.x + 14, SIDE_RECT.y + 12),
        )
        screen.blit(
            self.app.font_tiny.render(
                "%s · время %s · %s · действия %d/%d"
                % (
                    self._faction().name if self._faction() else "—",
                    self.campaign.time_label(),
                    self.campaign.speed_label(),
                    self.campaign.actions_left,
                    self.campaign.actions_per_turn,
                ),
                True,
                TEXT,
            ),
            (SIDE_RECT.x + 14, SIDE_RECT.y + 30),
        )
        self._draw_tabs(screen)
        if self.mode == "characters":
            self._draw_character_list(screen)
        else:
            organ = self._organ()
            screen.blit(
                self.app.font_tiny.render(
                    organ.name if organ else "Выберите орган в графе.",
                    True,
                    TEXT,
                ),
                (SIDE_RECT.x + 14, SIDE_RECT.y + 82),
            )
        rows = self._interaction_rows()
        if not rows:
            screen.blit(
                self.app.font_tiny.render(
                    "Нет доступных действий.", True, DIM
                ),
                (
                    SIDE_RECT.x + 14,
                    SIDE_RECT.y + (244 if self.mode == "characters" else 104),
                ),
            )
        for rect, option in rows:
            if self.mode == "characters":
                selected_id = self.selected_character_interaction_id
            elif self.mode == "automata":
                selected_id = self.selected_automaton_interaction_id
            else:
                selected_id = self.selected_interaction_id
            selected = option["id"] == selected_id
            enabled = bool(option.get("enabled"))
            pygame.draw.rect(
                screen,
                (34, 48, 68) if selected else (24, 30, 43),
                rect,
                border_radius=6,
            )
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                2,
                border_radius=6,
            )
            screen.blit(
                self.app.font_small.render(
                    option["label"],
                    True,
                    TEXT if enabled else DIM,
                ),
                (rect.x + 8, rect.y + 3),
            )
            detail = _money(option.get("cost", {}))
            if self.mode == "characters" and option.get("morale"):
                detail += " · мораль %s" % _signed(
                    option.get("morale", 0.0), 0
                )
            if self.mode == "automata":
                detail += " · целей: %d" % len(option.get("targets", ()))
            if not enabled:
                detail += " · %s" % option.get("reason", "недоступно")
            screen.blit(
                self.app.font_tiny.render(detail, True, DIM),
                (rect.x + 8, rect.y + 22),
            )

        y = (
            rows[-1][0].bottom + 6
            if rows
            else SIDE_RECT.y + (244 if self.mode == "characters" else 104)
        )
        if self.mode == "automata":
            target = self._selected_automaton_target()
            option = self._selected_automaton_interaction()
            if target is not None:
                target_text = "Цель: %s · %.0f%%" % (
                    target["name"],
                    float(target.get("integrity", 0.0)) * 100.0,
                )
                color = GOOD
            elif option is not None:
                target_text = (
                    "Цель не выбрана: нажмите автомат в графе."
                )
                color = WARN
            else:
                target_text = (
                    "Выберите команду, затем автомат-цель в графе."
                )
                color = DIM
            screen.blit(
                self.app.font_tiny.render(target_text, True, color),
                (SIDE_RECT.x + 14, y),
            )
            y += 15
        if self.message:
            for line in wrap_text(
                self.app.font_tiny, self.message, SIDE_RECT.width - 28
            )[:2]:
                screen.blit(
                    self.app.font_tiny.render(line, True, WARN),
                    (SIDE_RECT.x + 14, y),
                )
                y += 14
        if self.last_result:
            result = self.last_result
            if "source_organ_id" in result:
                text = "%s → %s: %.0f%%" % (
                    result.get("source_organ_name", "автомат"),
                    result.get("target_organ_name", "цель"),
                    float(result.get("target_integrity_after", 0.0))
                    * 100.0,
                )
            elif "character_name" in result:
                text = "%s → мораль %.0f" % (
                    result.get("character_name", "персонаж"),
                    float(result.get("morale_after", 0.0)),
                )
            else:
                text = "%s → %.0f%%" % (
                    result.get("organ_name", "орган"),
                    float(result.get("integrity_after", 0.0)) * 100.0,
                )
            screen.blit(
                self.app.font_tiny.render(text, True, GOOD),
                (SIDE_RECT.x + 14, y),
            )

        if self.mode == "characters":
            selected = self._selected_character_interaction()
        elif self.mode == "automata":
            selected = self._selected_automaton_interaction()
        else:
            selected = self._selected_interaction()
        if selected is not None:
            y = SIDE_RECT.bottom - 88
            for line in wrap_text(
                self.app.font_tiny,
                selected.get("description") or "",
                SIDE_RECT.width - 28,
            )[:3]:
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (SIDE_RECT.x + 14, y),
                )
                y += 13

    def _draw_bottom(self, screen):
        _panel(screen, BOTTOM_RECT)
        budget = "время %s · %s · цикл %d · действия %d/%d" % (
            self.campaign.time_label(),
            self.campaign.speed_label(),
            self.campaign.turn,
            self.campaign.actions_left,
            self.campaign.actions_per_turn,
        )
        if self.campaign.outcome:
            budget += " · исход: %s" % self.campaign.outcome
        screen.blit(
            self.app.font_tiny.render(budget, True, MUTED),
            (BOTTOM_RECT.x + 10, BOTTOM_RECT.y + 15),
        )
        pygame.draw.rect(
            screen,
            (46, 86, 138) if self.campaign.can_speed_up() else (40, 44, 56),
            self._end_turn_rect,
            border_radius=7,
        )
        pygame.draw.rect(
            screen, PANEL_BORDER, self._end_turn_rect, 2, border_radius=7
        )
        speed_text = (
            "Ускорить · %s" % self.campaign.speed_label()
            if self.campaign.can_speed_up()
            else "Максимум"
        )
        text = self.app.font_small.render(speed_text, True, TEXT)
        screen.blit(text, text.get_rect(center=self._end_turn_rect.center))
        can_slow = self.campaign.can_slow_down()
        pygame.draw.rect(
            screen,
            (46, 86, 138) if can_slow else (40, 44, 56),
            self._slow_down_rect,
            border_radius=7,
        )
        pygame.draw.rect(
            screen,
            PANEL_BORDER,
            self._slow_down_rect,
            2,
            border_radius=7,
        )
        slow_text = (
            "Медленнее · %s" % self.campaign.speed_label()
            if can_slow
            else "Минимум · %s" % self.campaign.speed_label()
        )
        text = self.app.font_small.render(
            slow_text, True, TEXT if can_slow else DIM
        )
        screen.blit(
            text, text.get_rect(center=self._slow_down_rect.center)
        )
        pygame.draw.rect(
            screen, (46, 86, 138), self._back_rect, border_radius=7
        )
        pygame.draw.rect(
            screen, PANEL_BORDER, self._back_rect, 2, border_radius=7
        )
        text = self.app.font_small.render("Назад", True, TEXT)
        screen.blit(text, text.get_rect(center=self._back_rect.center))

    def _draw_apply(self, screen):
        pygame.draw.rect(
            screen, (46, 86, 138), self._apply_rect, border_radius=7
        )
        pygame.draw.rect(
            screen, PANEL_BORDER, self._apply_rect, 2, border_radius=7
        )
        if self.mode == "characters":
            enabled = self.selected_character_interaction_id is not None
        elif self.mode == "automata":
            enabled = (
                self.selected_automaton_interaction_id is not None
                and self.selected_automaton_target_id is not None
            )
        else:
            enabled = self.selected_interaction_id is not None
        if not self.campaign.finished and enabled:
            label = "Применить · 1 действие"
            color = TEXT
        elif self.mode == "automata" and self.selected_automaton_interaction_id:
            label = "Выберите цель в графе"
            color = DIM
        else:
            label = "Выберите действие"
            color = DIM
        text = self.app.font_small.render(label, True, color)
        screen.blit(text, text.get_rect(center=self._apply_rect.center))

    def draw(self, screen):
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 190))
        screen.blit(dim, (0, 0))
        screen.blit(
            self.app.font_title.render("Сеть автоматов", True, TEXT),
            (24, 24),
        )
        status = "время %s · скорость %s · цикл %d · действия %d/%d" % (
            self.campaign.time_label(),
            self.campaign.speed_label(),
            self.campaign.turn,
            self.campaign.actions_left,
            self.campaign.actions_per_turn,
        )
        if self.campaign.outcome:
            status += " · исход: %s" % self.campaign.outcome
        screen.blit(
            self.app.font_small.render(status, True, MUTED), (24, 62)
        )
        self._layout()
        self._draw_graph(screen)
        self._draw_detail(screen)
        self._draw_side(screen)
        self._draw_apply(screen)
        self._draw_bottom(screen)


__all__ = ["AutomataNetworkScreen"]
