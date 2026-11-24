from __future__ import annotations

import time

import pygame

from campaign.faction_state import derived_assets
from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import fit_line, wrap_text
from view.support.log_journal import get_logger
from view.support.metrics import (
    amount_phrase,
    chance_phrase,
    cost_phrase,
    effect_phrase,
    efficiency_phrase,
    metric_phrase,
    progress_phrase,
    relation_phrase,
    share_phrase,
)

logger = get_logger("view.automata")

WIDTH, HEIGHT = 1280, 720
TOP_H = 104
LEFT_RECT = pygame.Rect(24, TOP_H, 344, 520)
MID_RECT = pygame.Rect(388, TOP_H, 420, 520)
RIGHT_RECT = pygame.Rect(828, TOP_H, 428, 520)
BOTTOM_RECT = pygame.Rect(24, 646, 1232, 54)
CHAT_RECT = pygame.Rect(1136, 14, 120, 40)
ACTION_ROW_H = 52
DESCRIPTION_H = 184
OPTIONS_TTL = 0.35
FACTION_TTL = 0.50
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
try:
    from campaign.defaults import default_dict

    ASSET_LABELS = default_dict("asset_labels")
except Exception:  # pragma: no cover - UI не должен падать без конфига
    pass


def _relation_line(campaign, faction):
    rival = campaign.faction(campaign.rival_of(faction.side))
    if rival is None or rival.id == faction.id:
        return ""
    view = campaign.relation_view(faction.id, rival.id)
    labels = view.get("labels") or {}
    parts = []
    for axis, value in (view.get("outgoing") or {}).items():
        if abs(float(value)) < 0.01:
            continue
        parts.append(
            relation_phrase(labels.get(axis, axis), float(value))
        )
    if not parts:
        return "с %s: нейтрально" % rival.name
    return "с %s: %s" % (rival.name, " · ".join(parts[:2]))


def _panel(surface, rect):
    shape = pygame.Surface(rect.size, pygame.SRCALPHA)
    shape.fill(PANEL_BG)
    surface.blit(shape, rect.topleft)
    pygame.draw.rect(surface, PANEL_BORDER, rect, 2, border_radius=8)


def _asset_labels(faction):
    labels = dict(ASSET_LABELS)
    labels.update(
        (getattr(faction, "record", {}) or {}).get("asset_labels") or {}
    )
    return labels


def _asset_line(assets, keys=None, labels=None):
    labels = labels or ASSET_LABELS
    items = []
    for key, value in assets.items():
        if keys is not None and key not in keys:
            continue
        label = labels.get(key, key)
        items.append(metric_phrase(label, float(value)))
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


def _effect_to_text(effect):
    """Плоский словарь эффекта в «ключ ±0.00 · ключ ±0.00»."""
    if not isinstance(effect, dict) or not effect:
        return ""
    parts = []
    for key, value in effect.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            parts.append("%s %s" % (ASSET_LABELS.get(key, key), value))
            continue
        label = ASSET_LABELS.get(key, key)
        parts.append(effect_phrase(label, number))
    return " · ".join(parts)


def _projection_text(projections):
    """Проекции ``{self: {...}, target: {...}}`` в читаемую строку."""
    if not isinstance(projections, dict) or not projections:
        return ""
    parts = []
    self_part = _effect_to_text(projections.get("self"))
    target_part = _effect_to_text(projections.get("target"))
    if self_part:
        parts.append("вы: %s" % self_part)
    if target_part:
        parts.append("цель: %s" % target_part)
    return "; ".join(parts)


def _preview_report(campaign, action):
    """Симулировать обработчик на текущем снимке для превью эффекта.

    Строит ``WorkPlan`` через ``build_work`` и зовёт ``handlers.receive``
    с ``success=True`` и ``success=False``. Возвращает
    ``(plan, report_ok, report_fail)`` или ``None``, если ``template`` нет
    (legacy-контент). Ничего не применяет.
    """
    actor = campaign.faction(campaign.player_side)
    if actor is None:
        return None
    target_side = campaign._target_side(
        campaign.player_side, action
    )
    target = campaign.faction(target_side)
    if target is None:
        return None
    try:
        from campaign.work import build_work
        from campaign.handlers import receive as handler_receive
    except Exception:
        return None
    try:
        plan = build_work(action, actor, target, campaign)
    except Exception:
        plan = None
    if plan is None:
        return None
    work = plan.to_work()
    reports = {}
    for success in (True, False):
        try:
            reports[success] = handler_receive(
                work, plan, actor, target, campaign, success=success
            )
        except Exception:
            reports[success] = None
    if reports.get(True) is None and reports.get(False) is None:
        return None
    return plan, reports.get(True), reports.get(False)


class AutomataScreen(BaseScreen):

    show_time_hud = False
    escape_action = "none"

    def __init__(self, app, campaign):
        super().__init__(app)
        self.campaign = campaign
        self.campaign.ensure_clock()
        self.selected_action_id = None
        self.action_scroll = 0
        self.log_scroll = 0
        self.message = ""
        self.last_result = None
        self._options_cache = None
        self._options_cache_at = 0.0
        self._faction_cache = {}
        self._faction_cache_at = 0.0
        self._chronicle_cache = None
        self._chronicle_key = None
        self._sync_storyline()
        logger.info(
            "Экран автоматов: фракций=%d, цикл=%d, слоты=%d, игрок=%s",
            len(campaign.factions),
            campaign.turn,
            campaign.action_slots,
            campaign.player_side,
        )

    def _sync_storyline(self):
        interp = getattr(self.app, "storyline_interpreter", None)
        if interp is None:
            return
        snapshot = self.campaign.snapshot()
        interp.state["automata"] = snapshot
        interp.set_variable("automata_turn", snapshot["turn"])
        interp.set_variable(
            "automata_max_turns",
            snapshot.get("cycle_limit", snapshot.get("max_turns")),
        )
        interp.set_variable(
            "automata_actions_left", snapshot["actions_left"]
        )
        interp.set_variable(
            "automata_actions_per_turn",
            snapshot.get(
                "actions_per_cycle", snapshot.get("actions_per_turn")
            ),
        )
        interp.set_variable(
            "automata_slots", snapshot.get("action_slots", 2)
        )
        interp.set_variable(
            "automata_slots_used",
            len(
                self.campaign.active_processes(
                    self.campaign.player_side
                )
            ),
        )
        interp.set_variable("automata_outcome", snapshot["outcome"])
        interp.set_variable("automata_elapsed", snapshot["elapsed"])
        interp.set_variable("automata_speed", snapshot["speed"])
        for side, faction in snapshot["factions"].items():
            for key, value in (faction.get("assets") or {}).items():
                interp.set_variable(
                    "automata_%s_%s" % (side, key), value
                )

    def update(self, dt):
        """Реальное время: кампания идёт, пока открыт её экран."""
        if self.campaign.finished:
            return
        before = self.campaign.turn
        used_before = self.campaign.slot_state(
            self.campaign.player_side
        )["used"]
        self.campaign.advance_realtime(dt, snapshot=False)
        used_after = self.campaign.slot_state(
            self.campaign.player_side
        )["used"]
        if (
            self.campaign.turn != before
            or used_after != used_before
            or self.campaign.finished
        ):
            self._invalidate_options()
            self._faction_cache.clear()
            self._sync_storyline()
        if self.campaign.finished:
            self._check_storyline_outcome()

    def _goal_text(self):
        """Цель и пороги из ``scenario.outcome`` в одну строку."""

        rules = getattr(self.campaign, "outcome_rules", None) or {}
        parts = []
        rival = self.campaign.rival
        basis = str(rules.get("score_basis") or "assets")
        basis_label = (
            "прогрессу" if basis == "progress" else "взвешенной оценке"
        )
        if rival is not None and rules.get("score_margin") is not None:
            parts.append(
                "цель: превзойти %s по %s" % (rival.name, basis_label)
            )
        after = rules.get("score_after")
        if after:
            parts.append("проверка после %d циклов" % int(after))
        defeat = (rules.get("defeat") or {}).get(
            self.campaign.player_side
        ) or {}
        labels = _asset_labels(self._player())
        limits = [
            "%s ≤ %.2f" % (labels.get(str(key), key), float(value))
            for key, value in defeat.items()
        ]
        if limits:
            parts.append("провал: %s" % ", ".join(limits))
        return " · ".join(parts)

    def _course_label(self):
        """Курс правящей подфракции — вычисляется из её доли и активов."""

        from campaign.chronicle import subfaction_goal

        player = self._player()
        if player is None:
            return ""
        return subfaction_goal(player)

    def _risk_text(self):
        """Предупреждение, если актив подошёл к порогу поражения."""

        from campaign.chronicle import risk_warning

        return risk_warning(self.campaign)

    def _progress_text(self):
        rules = getattr(self.campaign, "outcome_rules", None) or {}
        if rules.get("score_margin") is None:
            return ""
        player = self.campaign.player
        rival = self.campaign.rival
        if player is None or rival is None:
            return ""
        return "прогресс: вы %.2f · %s %.2f" % (
            player.progress(),
            rival.name,
            rival.progress(),
        )

    def _draw_progress_bar(self, screen):
        """Полоса баланса прогресса: без текста, только состояние."""

        rules = getattr(self.campaign, "outcome_rules", None) or {}
        if rules.get("score_margin") is None:
            return
        from campaign.chronicle import score_share

        share = score_share(self.campaign)
        width = 820
        height = 3
        x, y = 430, 100
        pygame.draw.rect(
            screen, PANEL_BORDER, (x, y, width, height), border_radius=2
        )
        filled = int(round(width * share))
        if filled > 0:
            pygame.draw.rect(
                screen, ACCENT, (x, y, filled, height), border_radius=2
            )
        pygame.draw.line(
            screen, MUTED, (x + width // 2, y - 2), (x + width // 2, y + 7)
        )

    def _player(self):
        return self.campaign.faction(self.campaign.player_side)

    def _invalidate_options(self):
        self._options_cache = None
        self._options_cache_at = 0.0

    def _options(self, force=False):
        """Список работ с коротким кешем.

        Производные активы фракции считаются по BDI всех персонажей,
        поэтому запрашивать их несколько раз за кадр слишком дорого.
        Кеш на треть секунды сохраняет отзывчивость кнопок и убирает
        сотни лишних пересчётов в секунду.
        """
        now = time.monotonic()
        if (
            not force
            and self._options_cache is not None
            and now - self._options_cache_at < OPTIONS_TTL
        ):
            return self._options_cache
        options = self.campaign.action_options(
            self.campaign.player_side
        )
        self._options_cache = options
        self._options_cache_at = now
        return options

    def _faction_summary(self, faction):
        """Словесная карточка фракции с кешем на полсекунды."""
        now = time.monotonic()
        cached = self._faction_cache.get(faction.side)
        if (
            cached is not None
            and now - self._faction_cache_at < FACTION_TTL
        ):
            return cached
        assets = derived_assets(faction)
        support = ""
        if faction.organization_snapshot:
            support = "поддержка: %s" % share_phrase(
                float(
                    faction.organization_snapshot.get(
                        "willing_share", 0.0
                    )
                )
            )
        subfactions = self._subfaction_line(faction)
        if subfactions:
            support = (
                "%s · %s" % (support, subfactions)
                if support
                else subfactions
            )
        summary = {
            "assets": _asset_line(
                assets, labels=_asset_labels(faction)
            ),
            "relation": _relation_line(self.campaign, faction),
            "support": support,
        }
        self._faction_cache[faction.side] = summary
        self._faction_cache_at = now
        return summary

    def _subfaction_line(self, faction):
        """Доминирующие внутренние фракции — из данных, без имён в коде."""

        items = []
        for sub in getattr(faction, "subfactions", ()) or ():
            share = float(getattr(sub, "share", 0.0) or 0.0)
            if share < 0.05:
                continue
            items.append((share, str(getattr(sub, "label", "") or sub.id)))
        items.sort(reverse=True)
        return " · ".join(
            "%s %d%%" % (label, round(share * 100.0))
            for share, label in items[:2]
            if label
        )

    def _visible_actions(self):
        return max(
            1,
            (MID_RECT.height - 58 - DESCRIPTION_H - 14)
            // ACTION_ROW_H,
        )

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
                ACTION_ROW_H - 4,
            )
            rows.append((rect, option))
        return rows

    def _selected_option(self):
        if self.selected_action_id is None:
            return None
        return next(
            (
                item
                for item in self._options()
                if item["id"] == self.selected_action_id
            ),
            None,
        )

    def _description_rect(self):
        return pygame.Rect(
            MID_RECT.x + 10,
            MID_RECT.bottom - DESCRIPTION_H - 8,
            MID_RECT.width - 20,
            DESCRIPTION_H,
        )

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

    def _execute_selected(self):
        if self.selected_action_id is None:
            self.message = "Сначала выберите работу."
            return
        if self.campaign.finished:
            return
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
        result = self.campaign.start_action(
            self.campaign.player_side, action_id
        )
        self._invalidate_options()
        self._sync_storyline()
        if not result.get("ok"):
            self.message = result.get("reason") or "Работа не начата."
            logger.info("Работа отклонена: %s (%s)", action_id, self.message)
            return
        process = result.get("process") or {}
        self.selected_action_id = None
        self.last_result = result
        self.message = (
            "Работа начата: %s · %s."
            % (
                process.get("label") or action_id,
                self.campaign.duration_label(
                    float(process.get("duration", 0.0))
                ),
            )
        )
        logger.info(
            "Работа автомата начата: %s → %s; слоты=%d/%d; "
            "длительность=%.1f с; цикл=%d",
            process.get("label") or action_id,
            process.get("target_name", "?"),
            result.get("slots", {}).get("used", 0),
            result.get("slots", {}).get("slots", 0),
            float(process.get("duration", 0.0)),
            self.campaign.turn,
        )
        if self.campaign.finished:
            self._check_storyline_outcome()

    def _increase_speed(self):
        if self.campaign.finished:
            return
        before = self.campaign.speed
        self.campaign.speed_up()
        if self.campaign.speed != before:
            self.message = (
                "Скорость времени: %s."
                % self.campaign.speed_label()
            )
        else:
            self.message = (
                "Достигнута максимальная скорость: %s."
                % self.campaign.speed_label()
            )
        logger.info(
            "Скорость кампании: %s (время %s)",
            self.campaign.speed_label(),
            self.campaign.time_label(),
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
        logger.info(
            "Скорость кампании: %s (время %s)",
            self.campaign.speed_label(),
            self.campaign.time_label(),
        )

    def _end_turn(self):
        """Legacy-помощник для старых вызовов вне интерфейса."""
        if self.campaign.finished:
            return
        self.campaign.end_turn()
        self.selected_action_id = None
        self.last_result = (
            self.campaign.log[-1] if self.campaign.log else None
        )
        self._sync_storyline()
        if not self.campaign.finished:
            # Legacy-помощник сохраняет старую семантику «завершить ход»:
            # следующий цикл начинается сразу. Игровые экраны его не зовут.
            self.campaign.begin_turn()
            self.message = (
                "Цикл завершён. Цикл %d; доступно действий: %d."
                % (self.campaign.turn, self.campaign.actions_left)
            )
        else:
            self.message = "Кампания завершена."
        logger.info(
            "Цикл автоматов завершён: цикл=%d, действий=%d/%d, исход=%s",
            self.campaign.turn,
            self.campaign.actions_left,
            self.campaign.actions_per_cycle,
            self.campaign.outcome,
        )
        self._sync_storyline()
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
                # Колесо вверх (+y) уводит ленту в прошлое: смещение
                # считает, сколько свежих записей пропустить.
                total = len(self._story_feed())
                limit = max(0, total - 1)
                self.log_scroll = max(
                    0,
                    min(limit, self.log_scroll + int(event.y)),
                )
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        pos = event.pos
        if self._chat_rect().collidepoint(pos):
            self._open_chat()
            return
        if self._processes_rect().collidepoint(pos):
            self._open_processes()
            return
        if self._reports_rect().collidepoint(pos):
            self._open_reports()
            return
        if self._emulation_rect().collidepoint(pos):
            self._open_emulation()
            return
        if self._execute_rect().collidepoint(pos):
            self._execute_selected()
            return
        if self._speed_up_rect().collidepoint(pos):
            self._increase_speed()
            return
        if self._slow_down_rect().collidepoint(pos):
            self._decrease_speed()
            return
        if self._network_rect().collidepoint(pos):
            self._open_network()
            return
        if self._codex_rect().collidepoint(pos):
            self._open_codex()
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

    def _execute_rect(self):
        return pygame.Rect(
            MID_RECT.x + 10,
            BOTTOM_RECT.y + 7,
            200,
            40,
        )

    def _speed_up_rect(self):
        return pygame.Rect(
            MID_RECT.x + 220,
            BOTTOM_RECT.y + 7,
            130,
            40,
        )

    def _slow_down_rect(self):
        return pygame.Rect(
            MID_RECT.x + 360,
            BOTTOM_RECT.y + 7,
            130,
            40,
        )

    def _network_rect(self):
        return pygame.Rect(
            BOTTOM_RECT.x + 864,
            BOTTOM_RECT.y + 7,
            80,
            40,
        )

    def _codex_rect(self):
        return pygame.Rect(
            BOTTOM_RECT.x + 954,
            BOTTOM_RECT.y + 7,
            80,
            40,
        )

    def _chat_rect(self):
        """Кнопка «СВЯЗЬ»: свободная область сверху справа."""
        return CHAT_RECT

    def _processes_rect(self):
        """Кнопка отдельного списка текущих процессов."""
        return pygame.Rect(820, 14, 150, 40)

    def _reports_rect(self):
        """Кнопка очереди докладов источников."""
        return pygame.Rect(660, 14, 150, 40)

    def _emulation_rect(self):
        """Кнопка запуска эмуляции времени."""
        return pygame.Rect(980, 14, 146, 40)

    def _open_reports(self):
        from .campaign_reports import ReportsOverlay

        logger.info("Открытие очереди докладов кампании")
        self.app.manager.push(ReportsOverlay(self.app, self.campaign))

    def _open_processes(self):
        from .campaign_overlays import ProcessesOverlay

        logger.info("Открытие списка процессов кампании")
        self.app.manager.push(ProcessesOverlay(self.app, self.campaign))

    def _open_emulation(self):
        from .campaign_overlays import TimeEmulationOverlay

        logger.info("Открытие эмуляции времени")
        self.app.manager.push(TimeEmulationOverlay(self.app, self.campaign))

    def _open_network(self):
        from .automata_network import AutomataNetworkScreen

        self.app.manager.push(
            AutomataNetworkScreen(self.app, self.campaign)
        )

    def _open_codex(self):
        from .campaign_codex import CampaignCodexScreen

        self.app.manager.push(CampaignCodexScreen(self.app))

    def _open_chat(self):
        """Открыть чат: выбор собеседника и стиля — внутри экрана чата."""

        from .dialogue_chat import DialogueChatScreen

        logger.info("Открытие чата из экрана автоматов")
        self.app.manager.push(DialogueChatScreen(self.app))

    def _finish_rect(self):
        return pygame.Rect(
            BOTTOM_RECT.right - 188,
            BOTTOM_RECT.y + 7,
            180,
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
        text = self.app.font_small.render(
            fit_line(self.app.font_small, label, rect.width - 16),
            True,
            TEXT if enabled else DIM,
        )
        surface.blit(text, text.get_rect(center=rect.center))

    def _draw_preview(self, screen, rect, action, preview, y):
        """Отрисовать превью эффекта в блоке «Выбранная работа».

        Если ``preview`` есть — показывает ожидаемый отчёт обработчика
        на текущем снимке: форму, объём и эффект. Иначе — честную
        пометку, что контент без ``template`` и превью legacy.
        """
        if preview is None:
            line = (
                "эффект: legacy-контент без template "
                "(превью приблизительно)"
            )
            for text in wrap_text(
                self.app.font_tiny, line, rect.width - 20
            )[:1]:
                screen.blit(
                    self.app.font_tiny.render(text, True, DIM),
                    (rect.x + 10, y),
                )
            return y + 14
        plan, report_ok, report_fail = preview
        header = "форма: %s · объём: %s" % (
            plan.form,
            amount_phrase(plan.amount),
        )
        if report_ok is not None:
            header += " · %s" % efficiency_phrase(
                report_ok.efficiency or 0.0
            )
        screen.blit(
            self.app.font_tiny.render(header, True, ACCENT),
            (rect.x + 10, y),
        )
        y += 16
        ok_text = _projection_text(
            report_ok.projections if report_ok is not None else {}
        )
        if not ok_text and report_ok is not None:
            ok_text = _effect_to_text(report_ok.effect)
        if ok_text:
            for text in wrap_text(
                self.app.font_tiny,
                "при успехе: %s" % ok_text,
                rect.width - 20,
            )[:2]:
                screen.blit(
                    self.app.font_tiny.render(text, True, GOOD),
                    (rect.x + 10, y),
                )
                y += 14
        fail_text = _projection_text(
            report_fail.projections if report_fail is not None else {}
        )
        if not fail_text and report_fail is not None:
            fail_text = _effect_to_text(report_fail.effect)
        if fail_text:
            for text in wrap_text(
                self.app.font_tiny,
                "при провале: %s" % fail_text,
                rect.width - 20,
            )[:2]:
                screen.blit(
                    self.app.font_tiny.render(text, True, BAD),
                    (rect.x + 10, y),
                )
                y += 14
        if not ok_text and not fail_text:
            screen.blit(
                self.app.font_tiny.render(
                    "эффект: обработчик не дал проекций", True, DIM
                ),
                (rect.x + 10, y),
            )
            y += 14
        return y

    def _chronicle_entries(self):
        """Эпизоды хроники, собранные из журнала симуляции."""

        records = getattr(self.campaign, "narrative", []) or []
        if not records:
            return []
        last = records[-1]
        key = (len(records), last.get("turn"), last.get("elapsed"))
        if self._chronicle_cache is not None and self._chronicle_key == key:
            return self._chronicle_cache
        from campaign.chronicle import chronicle, labels_for

        player = self._player()
        labels = labels_for(
            (getattr(player, "record", {}) or {}) if player else {}
        )
        entries = chronicle(records, limit=6, labels=labels)
        for entry in entries:
            entry["effects"] = {}
            entry["visible"] = True
            entry["requires_choice"] = False
        self._chronicle_cache = entries
        self._chronicle_key = key
        return entries

    def _story_feed(self, limit=None):
        """Хроника и вести для главного экрана, без требующих выбора.

        Хроника собирается из ``campaign.narrative``: это факты
        симуляции, а не заранее написанные сцены. Фоновые доклады и
        новости добавляются к ней, дубликаты схлопываются.
        """
        feed = list(self._chronicle_entries())
        for entry in self.campaign.story_events:
            if entry.get("visible") is False:
                continue
            if entry.get("requires_choice"):
                continue
            if str(entry.get("category") or "") == "report":
                continue
            release_at = entry.get("release_at")
            if release_at is not None:
                try:
                    if float(self.campaign.elapsed) + 1e-9 < float(release_at):
                        continue
                except (TypeError, ValueError):
                    pass
            feed.append(entry)
        feed.sort(
            key=lambda item: (
                int(item.get("turn") or 0),
                str(item.get("id") or ""),
            )
        )
        unique = []
        seen = set()
        for entry in feed:
            key = (
                str(entry.get("category") or ""),
                str(entry.get("title") or ""),
                str(entry.get("text") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(entry)
        if limit is None or int(limit) <= 0:
            return unique
        return unique[-int(limit):]

    def draw(self, screen):
        player = self._player()
        title = self.campaign.title
        screen.blit(
            self.app.font_title.render(title, True, TEXT), (24, 12)
        )
        status = "время %s · скорость %s · цикл %d · слоты %d/%d" % (
            self.campaign.time_label(),
            self.campaign.speed_label(),
            self.campaign.turn,
            self.campaign.slot_state()["used"],
            self.campaign.action_slots,
        )
        if self.campaign.outcome:
            status += " · исход: %s" % self.campaign.outcome
        screen.blit(
            self.app.font_small.render(status, True, MUTED), (24, 52)
        )
        if player is not None:
            subtitle = "%s · %s" % (
                player.name,
                player.record.get("role_title", "лидер"),
            )
            screen.blit(
                self.app.font_small.render(subtitle, True, ACCENT), (24, 74)
            )
        goal = self._goal_text()
        if goal:
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(self.app.font_tiny, goal, 820), True, MUTED
                ),
                (430, 33),
            )
        course = self._course_label()
        if course:
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(self.app.font_tiny, course, 820), True, ACCENT
                ),
                (430, 52),
            )
        progress = self._progress_text()
        if progress:
            screen.blit(
                self.app.font_tiny.render(progress, True, DIM),
                (430, 70),
            )
        risk = self._risk_text()
        if risk:
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(self.app.font_tiny, risk, 820), True, WARN
                ),
                (430, 86),
            )
        self._draw_progress_bar(screen)

        self._draw_button(
            screen,
            self._chat_rect(),
            "СВЯЗЬ",
            enabled=True,
            accent=True,
        )
        ongoing = self.campaign.ongoing_processes(
            self.campaign.player_side
        )
        self._draw_button(
            screen,
            self._processes_rect(),
            (
                "В РАБОТЕ · %d" % len(ongoing)
                if ongoing
                else "В РАБОТЕ"
            ),
            enabled=True,
            accent=bool(ongoing),
        )
        reports = self.campaign.pending_reports(self.campaign.player_side)
        intercepts = self.campaign.available_interceptions(
            self.campaign.player_side
        )
        attention = len(reports) + len(intercepts)
        self._draw_button(
            screen,
            self._reports_rect(),
            "ДОКЛАДЫ · %d" % attention if attention else "ДОКЛАДЫ",
            enabled=True,
            accent=bool(attention),
        )
        self._draw_button(
            screen,
            self._emulation_rect(),
            "ЭМУЛЯЦИЯ",
            enabled=not self.campaign.finished,
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
            summary = self._faction_summary(faction)
            screen.blit(
                self.app.font_small.render(
                    fit_line(
                        self.app.font_small, label, rect.width - 20
                    ),
                    True,
                    TEXT,
                ),
                (rect.x + 10, rect.y + 8),
            )
            lines = wrap_text(
                self.app.font_tiny,
                summary["assets"],
                rect.width - 20,
            )
            y = rect.y + 32
            for line in lines[:2]:
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (rect.x + 10, y),
                )
                y += 18
            relation = summary["relation"]
            if relation:
                screen.blit(
                    self.app.font_tiny.render(
                        fit_line(
                            self.app.font_tiny,
                            relation,
                            rect.width - 20,
                        ),
                        True,
                        DIM,
                    ),
                    (rect.x + 10, rect.y + 68),
                )
            if summary["support"]:
                screen.blit(
                    self.app.font_tiny.render(
                        fit_line(
                            self.app.font_tiny,
                            summary["support"],
                            rect.width - 20,
                        ),
                        True,
                        DIM,
                    ),
                    (rect.x + 10, rect.bottom - 22),
                )

        _panel(screen, MID_RECT)
        screen.blit(
            self.app.font_small.render("РАБОТЫ ВАШЕЙ ФРАКЦИИ", True, MUTED),
            (MID_RECT.x + 12, MID_RECT.y + 12),
        )
        screen.blit(
            self.app.font_tiny.render(
                "Клик — выбрать, затем «Начать». Работа идёт во времени.",
                True,
                DIM,
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
                    fit_line(
                        self.app.font_small,
                        str(action.get("label") or option["id"]),
                        rect.width - 20,
                    ),
                    True,
                    color,
                ),
                (rect.x + 10, rect.y + 4),
            )
            target = _target_name(self.campaign, action)
            cost = option.get("cost") or action.get("cost") or {}
            cost_text = ", ".join(
                cost_phrase(ASSET_LABELS.get(key, key), float(value))
                for key, value in cost.items()
            )
            organ = str(action.get("organ") or action.get("organ_id") or "")
            detail = "цель: %s" % target
            if organ:
                detail = "орган: %s · %s" % (organ, detail)
            course = option.get("course") or {}
            if course.get("aligned"):
                detail += " · курс: %s" % str(
                    course.get("label") or course.get("id") or ""
                )
            if cost_text:
                detail += " · цена: %s" % cost_text
            active_process = self.campaign.process_for_action(
                self.campaign.player_side, option["id"]
            )
            if active_process is not None:
                duration = max(
                    1e-6, float(active_process.get("duration", 0.0))
                )
                left = max(0.0, float(active_process.get("remaining", 0.0)))
                progress = 1.0 - min(1.0, left / duration)
                detail += " · %s" % progress_phrase(progress)
            if not enabled:
                detail += " · %s" % option.get("reason", "недоступно")
            for line_number, line in enumerate(
                wrap_text(self.app.font_tiny, detail, rect.width - 20)[:2]
            ):
                screen.blit(
                    self.app.font_tiny.render(line, True, DIM),
                    (rect.x + 10, rect.y + 23 + line_number * 11),
                )

        description_rect = self._description_rect()
        pygame.draw.rect(
            screen, (16, 21, 31), description_rect, border_radius=6
        )
        pygame.draw.rect(
            screen, PANEL_BORDER, description_rect, 2, border_radius=6
        )
        screen.blit(
            self.app.font_tiny.render(
                "ВЫБРАННАЯ РАБОТА", True, MUTED
            ),
            (description_rect.x + 10, description_rect.y + 8),
        )
        selected_option = self._selected_option()
        if selected_option is None:
            hint = (
                "Выберите работу в списке — здесь появятся её описание, "
                "орган-исполнитель, цель и ожидаемый эффект."
            )
            for line_number, line in enumerate(
                wrap_text(
                    self.app.font_tiny,
                    hint,
                    description_rect.width - 20,
                )[:3]
            ):
                screen.blit(
                    self.app.font_tiny.render(line, True, DIM),
                    (
                        description_rect.x + 10,
                        description_rect.y + 30 + line_number * 16,
                    ),
                )
        else:
            action = selected_option["action"]
            organ_id = str(action.get("organ_id") or "")
            organ = (
                self._player().organ(organ_id)
                if self._player() is not None
                else None
            )
            meta = "цель: %s" % _target_name(
                self.campaign, action
            )
            if organ is not None:
                meta = "орган: %s · %s · %s" % (
                    organ.name,
                    metric_phrase("целостность", organ.integrity),
                    meta,
                )
            screen.blit(
                self.app.font_small.render(
                    fit_line(
                        self.app.font_small,
                        str(action.get("label") or selected_option["id"]),
                        description_rect.width - 20,
                    ),
                    True,
                    TEXT,
                ),
                (description_rect.x + 10, description_rect.y + 24),
            )
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(
                        self.app.font_tiny,
                        meta,
                        description_rect.width - 20,
                    ),
                    True,
                    ACCENT,
                ),
                (description_rect.x + 10, description_rect.y + 44),
            )
            description = str(
                action.get("description")
                or "Описание работы не задано."
            )
            y_text = description_rect.y + 62
            for line in wrap_text(
                self.app.font_tiny,
                description,
                description_rect.width - 20,
            )[:3]:
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (description_rect.x + 10, y_text),
                )
                y_text += 14
            preview = None
            try:
                preview = _preview_report(self.campaign, action)
            except Exception:
                preview = None
            self._draw_preview(
                screen, description_rect, action, preview, y_text + 4
            )

        _panel(screen, RIGHT_RECT)
        pending = self.campaign.pending_decisions(
            self.campaign.player_side
        )
        heading = "СОБЫТИЯ"
        if pending:
            heading += " · ЖДЁТ РЕШЕНИЯ"
        screen.blit(
            self.app.font_small.render(heading, True, MUTED),
            (RIGHT_RECT.x + 12, RIGHT_RECT.y + 12),
        )
        y = RIGHT_RECT.y + 40
        if pending:
            first = pending[0]
            demand = "Требует решения: %s — %s" % (
                first.get("source_name") or "источник",
                first.get("title") or "сообщение",
            )
            for line in wrap_text(
                self.app.font_tiny, demand, RIGHT_RECT.width - 24
            )[:2]:
                screen.blit(
                    self.app.font_tiny.render(line, True, WARN),
                    (RIGHT_RECT.x + 12, y),
                )
                y += 16
            screen.blit(
                self.app.font_tiny.render(
                    "Откройте «ДОКЛАДЫ» и примите решение.",
                    True,
                    WARN,
                ),
                (RIGHT_RECT.x + 12, y),
            )
            y += 22
        if self.message:
            for line in wrap_text(
                self.app.font_tiny, self.message, RIGHT_RECT.width - 24
            )[:2]:
                screen.blit(
                    self.app.font_tiny.render(line, True, WARN),
                    (RIGHT_RECT.x + 12, y),
                )
                y += 16
            y += 6
        if self.last_result:
            result = self.last_result
            outcome_color = GOOD if result.get("success") else BAD
            header = "%s -> %s · %s" % (
                result.get("actor_name", "?"),
                result.get("target_name", "?"),
                result.get("label", "работа"),
            )
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(
                        self.app.font_tiny, header, RIGHT_RECT.width - 24
                    ),
                    True,
                    TEXT,
                ),
                (RIGHT_RECT.x + 12, y),
            )
            y += 16
            outcome = "%s · %s" % (
                "успех" if result.get("success") else "провал",
                chance_phrase(result.get("chance", 0.0)),
            )
            screen.blit(
                self.app.font_tiny.render(outcome, True, outcome_color),
                (RIGHT_RECT.x + 12, y),
            )
            y += 16
            text = str(result.get("text") or "")
            for line in wrap_text(
                self.app.font_tiny, text, RIGHT_RECT.width - 24
            )[:2]:
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (RIGHT_RECT.x + 12, y),
                )
                y += 15
            y += 8

        briefing = self.campaign.staff_briefing(
            self.campaign.player_side
        )
        if briefing.get("lines") and y < RIGHT_RECT.bottom - 120:
            header = "ШТАБ · %s" % (
                briefing.get("chief") or "начальник штаба"
            )
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(
                        self.app.font_tiny,
                        header,
                        RIGHT_RECT.width - 24,
                    ),
                    True,
                    DIM,
                ),
                (RIGHT_RECT.x + 12, y),
            )
            y += 16
            for line in briefing.get("lines")[:3]:
                for wrapped in wrap_text(
                    self.app.font_tiny,
                    str(line),
                    RIGHT_RECT.width - 24,
                )[:1]:
                    screen.blit(
                        self.app.font_tiny.render(wrapped, True, MUTED),
                        (RIGHT_RECT.x + 12, y),
                    )
                    y += 14
            y += 4

        feed = self._story_feed()
        total = len(feed)
        offset = min(self.log_scroll, max(0, total - 1))
        self.log_scroll = offset
        shown = total - offset
        header = "ЛЕНТА"
        if total:
            header += " · %d/%d" % (shown, total)
            if offset:
                header += " · колесо ↑ — старее"
        screen.blit(
            self.app.font_tiny.render(
                fit_line(
                    self.app.font_tiny, header, RIGHT_RECT.width - 24
                ),
                True,
                DIM,
            ),
            (RIGHT_RECT.x + 12, y),
        )
        y += 18
        if not feed:
            for line in wrap_text(
                self.app.font_tiny,
                "Пока событий нет. Источники пришлют вести, когда "
                "появится повод.",
                RIGHT_RECT.width - 24,
            )[:3]:
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (RIGHT_RECT.x + 12, y),
                )
                y += 15
        for entry in reversed(feed[:shown]):
            if y > RIGHT_RECT.bottom - 24:
                break
            label = str(
                entry.get("title")
                or entry.get("category")
                or "Событие"
            )
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(
                        self.app.font_tiny, label, RIGHT_RECT.width - 24
                    ),
                    True,
                    ACCENT,
                ),
                (RIGHT_RECT.x + 12, y),
            )
            y += 15
            for line in wrap_text(
                self.app.font_tiny,
                str(entry.get("text") or ""),
                RIGHT_RECT.width - 24,
            )[:2]:
                if y > RIGHT_RECT.bottom - 20:
                    break
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (RIGHT_RECT.x + 12, y),
                )
                y += 14
            y += 6

        _panel(screen, BOTTOM_RECT)
        self._draw_button(
            screen,
            self._execute_rect(),
            "Начать · 1 слот",
            enabled=self.selected_action_id is not None
            and self.campaign.slot_state()["free"] > 0
            and not self.campaign.finished,
        )
        self._draw_button(
            screen,
            self._speed_up_rect(),
            (
                "Максимум"
                if not self.campaign.can_speed_up()
                else "Ускорить · %s" % self.campaign.speed_label()
            ),
            enabled=not self.campaign.finished
            and self.campaign.can_speed_up(),
            accent=self.campaign.can_speed_up(),
        )
        self._draw_button(
            screen,
            self._slow_down_rect(),
            (
                "Медленнее · %s" % self.campaign.speed_label()
                if self.campaign.can_slow_down()
                else "Минимум · %s" % self.campaign.speed_label()
            ),
            enabled=not self.campaign.finished
            and self.campaign.can_slow_down(),
        )
        self._draw_button(
            screen,
            self._network_rect(),
            "Сеть",
            enabled=True,
        )
        self._draw_button(
            screen,
            self._codex_rect(),
            "Кодекс",
            enabled=True,
        )
        if self.campaign.finished:
            self._draw_button(
                screen,
                self._finish_rect(),
                "Принять исход",
                accent=True,
            )
        else:
            active = self.campaign.active_processes(self.campaign.player_side)
            settling = self.campaign.settling_processes(
                self.campaign.player_side
            )
            slots = self.campaign.slot_state()
            if active:
                hint = "В работе %d · эффектов %d · слоты %d/%d" % (
                    len(active),
                    len(settling),
                    slots["used"],
                    slots["slots"],
                )
            elif settling:
                hint = (
                    "Эффектов %d · свободно слотов %d"
                    % (len(settling), slots["free"])
                )
            else:
                hint = "Свободно слотов %d · выбрано: %s" % (
                    slots["free"],
                    self.selected_action_id or "ничего",
                )
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(
                        self.app.font_tiny,
                        hint,
                        self._execute_rect().x - BOTTOM_RECT.x - 20,
                    ),
                    True,
                    DIM,
                ),
                (BOTTOM_RECT.x + 10, BOTTOM_RECT.y + 20),
            )
