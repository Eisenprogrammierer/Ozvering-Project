"""Отрисовка automata-кампании: хроника, лента и главный кадр.

Вынесено из ``automata_screen.py`` после W4. Миксин ставится до
``BaseScreen`` в MRO, чтобы его ``draw`` перекрывал базовую заглушку.
"""

from __future__ import annotations

import time

import pygame

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
from .automata_screen_support import *  # noqa: F401,F403


logger = get_logger("view.automata.draw")


class AutomataDrawMixin:

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
