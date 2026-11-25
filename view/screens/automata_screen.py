"""Экран automata-кампании: состояние, действия и отрисовка.

Отрисовка вынесена в ``automata_screen_draw``, общие константы и
текстовые помощники — в ``automata_screen_support``.
"""

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
from .automata_screen_draw import AutomataDrawMixin
from .automata_screen_support import *  # noqa: F401,F403


class AutomataScreen(AutomataDrawMixin, BaseScreen):

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
