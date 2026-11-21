"""Окно докладов: источник, сообщение и выбор игрока.

Доклад приходит от персонажа с BDI, а не от всеведущего рассказчика.
Окно показывает только то, что игрок слышит: имя и должность источника,
качественную полосу актива и словесную уверенность. Точные числа
остаются в аудите.

Текст переносится внутри карточки, а кнопки выбора стоят ниже тела
сообщения: длинный доклад не залезает за них.
"""

from __future__ import annotations

import pygame

from ..ui.overlays import OverlayScreen
from ..ui.text_layout import fit_line, wrap_text

REPORT_RECT = (250, 66, 780, 588)

TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
WARN = (230, 184, 96)
BAD = (226, 112, 112)
PANEL_ROW = (24, 31, 44)
PANEL_BORDER = (58, 70, 92)

CHOICE_H = 38
CHOICE_GAP = 12
BODY_GAP = 16


class ReportsOverlay(OverlayScreen):
    """Очередь формальных докладов с решениями игрока."""

    def __init__(self, app, campaign, side=None):
        super().__init__(app, REPORT_RECT)
        self.campaign = campaign
        self.side = str(side or campaign.player_side)
        self.index = 0
        self.message = ""
        self.last_result = None

    # --- данные -----------------------------------------------------
    def _pending(self):
        return list(self.campaign.pending_reports(self.side))

    def _intercepts(self):
        return [
            item
            for item in self.campaign.interceptions(self.side)
            if str(item.get("status") or "") in ("sealed", "open")
        ]

    def _history(self):
        reports = getattr(self.campaign.dispatch, "reports", ()) or ()
        return [
            report
            for report in reports
            if str(report.get("side") or "") == self.side
            and str(report.get("status") or "") in ("resolved", "expired")
        ]

    @staticmethod
    def _is_intercept(item):
        return str(item.get("kind") or "") == "intercept"

    def _queue(self):
        """Сначала доклады, затем перехваты: они не спорят за решение."""
        return self._pending() + self._intercepts()

    def _current(self):
        queue = self._queue()
        if queue:
            self.index = max(0, min(self.index, len(queue) - 1))
            return queue[self.index], queue
        history = self._history()
        return (history[-1] if history else None), []

    def _now(self):
        return float(getattr(self.campaign, "elapsed", 0.0) or 0.0)

    # --- геометрия --------------------------------------------------
    def _body_rect(self):
        panel = self.panel.rect
        top = panel.y + 166
        bottom = panel.bottom - 72 - CHOICE_H - BODY_GAP
        return pygame.Rect(
            panel.x + 20,
            top,
            panel.width - 40,
            max(1, bottom - top),
        )

    def _body_lines(self, report):
        return self._report_lines(report)

    def _report_lines(self, report):
        text = str(report.get("text") or "")
        rect = self._body_rect()
        line_h = self.app.font_small.get_height() + 5
        limit = max(0, rect.height // line_h)
        lines = wrap_text(self.app.font_small, text, rect.width)
        for key in ("chain_line", "promise_line", "request_line"):
            value = str(report.get(key) or "")
            if not value:
                continue
            lines.append("")
            lines.extend(
                wrap_text(self.app.font_small, value, rect.width)
            )
        counter_line = str(report.get("counter_line") or "")
        if counter_line:
            lines.append("")
            lines.extend(
                wrap_text(self.app.font_small, counter_line, rect.width)
            )
        return lines[:limit]

    def _intercept_lines(self, item):
        rect = self._body_rect()
        line_h = self.app.font_small.get_height() + 5
        limit = max(0, rect.height // line_h)
        lines = []
        status = str(item.get("status") or "")
        if status == "sealed":
            available_at = float(item.get("available_at") or 0.0)
            if self._now() + 1e-9 < available_at:
                lines.extend(
                    wrap_text(
                        self.app.font_small,
                        str(item.get("in_transit_text") or ""),
                        rect.width,
                    )
                )
            else:
                lines.extend(
                    wrap_text(
                        self.app.font_small,
                        str(item.get("sealed_text") or ""),
                        rect.width,
                    )
                )
            lines.append("")
            lines.append("Передача: %s." % item.get("faction_name"))
            lines.append("Источник и содержание скрыты.")
            return lines[:limit]

        text = str(item.get("text") or "")
        lines.extend(wrap_text(self.app.font_small, text, rect.width))
        lines.append("")
        lines.append(
            "Источник: %s · %s"
            % (
                item.get("source_name") or item.get("source_unknown"),
                item.get("source_post") or "без должности",
            )
        )
        lines.append(
            "Полоса: «%s» · уверенность: %s"
            % (
                item.get("band_label") or "неизвестна",
                item.get("confidence_label") or "неизвестна",
            )
        )
        decision = str(item.get("decision_text") or "")
        lines.append("")
        lines.append(
            "Решение фракции: %s"
            % (item.get("choice_label") or item.get("choice") or "—")
        )
        if decision:
            lines.extend(
                wrap_text(self.app.font_small, decision, rect.width)
            )
        if item.get("motive_revealed") and item.get("motive"):
            lines.append("Мотив: %s" % item.get("motive"))
        counter_text = str(item.get("counter_text") or "")
        if counter_text:
            lines.append("")
            lines.extend(
                wrap_text(self.app.font_small, counter_text, rect.width)
            )
        return lines[:limit]

    def _choice_rects(self, report):
        choices = list(report.get("choices") or ())
        return self._button_rects(len(choices))

    def _counter_rects(self, options):
        return self._button_rects(len(options))

    def _button_rects(self, count):
        if not count:
            return []
        panel = self.panel.rect
        inner = panel.width - 40
        gap = CHOICE_GAP * (count - 1)
        width = max(80, (inner - gap) // count)
        top = panel.bottom - 58
        rects = []
        for position in range(count):
            left = panel.x + 20 + position * (width + CHOICE_GAP)
            rects.append(pygame.Rect(left, top, width, CHOICE_H))
        return rects

    def _intercept_rect(self):
        panel = self.panel.rect
        return pygame.Rect(
            panel.x + 20,
            panel.bottom - 58,
            panel.width - 40,
            CHOICE_H,
        )

    def _nav_rects(self):
        panel = self.panel.rect
        return (
            pygame.Rect(panel.right - 132, panel.y + 8, 34, 34),
            pygame.Rect(panel.right - 92, panel.y + 8, 34, 34),
        )

    # --- ввод -------------------------------------------------------
    def handle_event(self, event):
        if self.close_btn.handle_event(event):
            return
        if event.type == pygame.MOUSEWHEEL:
            _report, queue = self._current()
            if queue:
                self.index = max(
                    0,
                    min(len(queue) - 1, self.index - event.y),
                )
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        report, queue = self._current()
        if report is None:
            return
        prev_rect, next_rect = self._nav_rects()
        if queue and prev_rect.collidepoint(event.pos):
            self.index = max(0, self.index - 1)
            self.message = ""
            return
        if queue and next_rect.collidepoint(event.pos):
            self.index = min(len(queue) - 1, self.index + 1)
            self.message = ""
            return
        if self._is_intercept(report):
            if str(report.get("status") or "") == "open":
                self._use_counter(report, event.pos)
            else:
                self._open_intercept(report)
            return
        if str(report.get("status") or "") != "pending":
            return
        for rect, choice in zip(
            self._choice_rects(report), report.get("choices") or ()
        ):
            if not rect.collidepoint(event.pos):
                continue
            choice_id = str(choice.get("id") or "")
            result = self.campaign.resolve_report(
                report.get("id"), choice_id
            )
            if result.get("ok"):
                self.last_result = result
                self.message = str(result.get("text") or "")
            else:
                self.message = str(
                    result.get("reason") or "Выбор не принят."
                )
            queue = self._queue()
            if queue:
                self.index = min(self.index, len(queue) - 1)
            return

    def _open_intercept(self, item):
        if str(item.get("status") or "") != "sealed":
            return
        if self._now() + 1e-9 < float(item.get("available_at") or 0.0):
            self.message = "Шифр ещё в пути."
            self.last_result = None
            return
        result = self.campaign.open_intercept(item.get("id"))
        if result.get("ok"):
            self.last_result = result
            self.message = str(result.get("text") or "")
        else:
            self.last_result = None
            self.message = str(
                result.get("reason") or "Перехват не вскрыт."
            )

    def _use_counter(self, item, pos):
        options = self.campaign.intercept_counters(item.get("id"))
        for rect, option in zip(
            self._counter_rects(options), options
        ):
            if not rect.collidepoint(pos):
                continue
            if not option.get("available"):
                self.last_result = None
                self.message = str(
                    option.get("reason") or "Контрмера недоступна."
                )
                return
            result = self.campaign.use_intercept(
                item.get("id"), option.get("id")
            )
            if result.get("ok"):
                self.last_result = result
                self.message = str(result.get("text") or "")
            else:
                self.last_result = None
                self.message = str(
                    result.get("reason") or "Контрмера не принята."
                )
            return

    # --- рисование --------------------------------------------------
    def _choice_label(self, report, choice):
        label = str(choice.get("label") or choice.get("id"))
        try:
            cost = int(report.get("verify_cost") or 0)
        except (TypeError, ValueError):
            cost = 0
        if str(choice.get("id") or "") == "verify" and cost:
            label = "%s · %d" % (label, cost)
        return label

    def _draw_choice(self, screen, rect, label, enabled=True):
        pygame.draw.rect(
            screen,
            (46, 86, 138) if enabled else (32, 39, 53),
            rect,
            border_radius=6,
        )
        pygame.draw.rect(screen, PANEL_BORDER, rect, 2, border_radius=6)
        surface = self.app.font_small.render(
            fit_line(self.app.font_small, label, rect.width - 16),
            True,
            TEXT if enabled else DIM,
        )
        screen.blit(
            surface,
            (
                rect.centerx - surface.get_width() // 2,
                rect.centery - surface.get_height() // 2,
            ),
        )

    def draw(self, screen):
        self.draw_base(screen, "ДОКЛАДЫ")
        panel = self.panel.rect
        item, queue = self._current()

        if item is None:
            screen.blit(
                self.app.font_small.render(
                    "Докладов пока нет.", True, MUTED
                ),
                (panel.x + 20, panel.y + 54),
            )
            screen.blit(
                self.app.font_tiny.render(
                    "Источники пришлют сообщение, когда появится повод.",
                    True,
                    DIM,
                ),
                (panel.x + 20, panel.y + 78),
            )
            return

        intercept = self._is_intercept(item)
        status = self._status_label(item)
        if queue:
            status += " · %d из %d" % (self.index + 1, len(queue))
        screen.blit(
            self.app.font_small.render(
                fit_line(
                    self.app.font_small,
                    status,
                    panel.width - 220,
                ),
                True,
                self._status_color(item),
            ),
            (panel.x + 20, panel.y + 52),
        )

        source = self._source_label(item)
        screen.blit(
            self.app.font_small.render(
                fit_line(self.app.font_small, source, panel.width - 40),
                True,
                ACCENT,
            ),
            (panel.x + 20, panel.y + 76),
        )
        meta = self._meta_label(item)
        screen.blit(
            self.app.font_tiny.render(meta, True, DIM),
            (panel.x + 20, panel.y + 100),
        )
        screen.blit(
            self.app.font_body.render(
                fit_line(
                    self.app.font_body,
                    item.get("title") or "Доклад",
                    panel.width - 40,
                ),
                True,
                TEXT,
            ),
            (panel.x + 20, panel.y + 124),
        )

        body = self._body_rect()
        pygame.draw.rect(screen, PANEL_ROW, body, border_radius=6)
        pygame.draw.rect(screen, PANEL_BORDER, body, 1, border_radius=6)
        y = body.y + 10
        lines = (
            self._intercept_lines(item)
            if intercept
            else self._report_lines(item)
        )
        for line in lines:
            screen.blit(
                self.app.font_small.render(line, True, TEXT),
                (body.x + 12, y),
            )
            y += self.app.font_small.get_height() + 5

        note = self._note_label(item)
        if self.message:
            note = self.message
        if note:
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(
                        self.app.font_tiny,
                        note,
                        panel.width - 40,
                    ),
                    True,
                    GOOD if self.last_result else WARN,
                ),
                (panel.x + 20, panel.bottom - 82),
            )

        if queue:
            prev_rect, next_rect = self._nav_rects()
            for rect, label, enabled in (
                (prev_rect, "‹", self.index > 0),
                (next_rect, "›", self.index < len(queue) - 1),
            ):
                pygame.draw.rect(
                    screen,
                    (32, 39, 53) if enabled else (26, 31, 42),
                    rect,
                    border_radius=6,
                )
                pygame.draw.rect(
                    screen, PANEL_BORDER, rect, 1, border_radius=6
                )
                surface = self.app.font_body.render(
                    label, True, TEXT if enabled else DIM
                )
                screen.blit(
                    surface,
                    (
                        rect.centerx - surface.get_width() // 2,
                        rect.centery - surface.get_height() // 2,
                    ),
                )

        if intercept:
            if self._can_open(item):
                price = int(item.get("price") or 0)
                label = "Вскрыть"
                if price:
                    label = "%s · %d" % (label, price)
                self._draw_choice(screen, self._intercept_rect(), label)
            elif str(item.get("status") or "") == "open" and not item.get(
                "counter"
            ):
                options = self.campaign.intercept_counters(item.get("id"))
                for rect, option in zip(
                    self._counter_rects(options), options
                ):
                    label = str(option.get("label") or option.get("id"))
                    price = int(option.get("price") or 0)
                    if price:
                        label = "%s · %d" % (label, price)
                    self._draw_choice(
                        screen,
                        rect,
                        label,
                        enabled=bool(option.get("available")),
                    )
            return

        if str(item.get("status") or "") == "pending":
            for rect, choice in zip(
                self._choice_rects(item), item.get("choices") or ()
            ):
                self._draw_choice(
                    screen,
                    rect,
                    self._choice_label(item, choice),
                )

    def _status_label(self, item):
        status = str(item.get("status") or "")
        if not self._is_intercept(item):
            return "ожидает решения" if status == "pending" else "закрыт"
        if status == "open":
            if item.get("counter"):
                return "перехват · контрмера принята"
            return "перехват · вскрыт"
        if self._now() + 1e-9 < float(item.get("available_at") or 0.0):
            return "перехват · в пути"
        return "перехват · шифр не вскрыт"

    def _status_color(self, item):
        if self._is_intercept(item):
            return WARN if item.get("status") == "sealed" else DIM
        return WARN if item.get("status") == "pending" else DIM

    def _source_label(self, item):
        if self._is_intercept(item):
            if item.get("status") == "sealed":
                return "Источник неизвестен · перехват"
            return "%s · %s" % (
                item.get("source_name") or "Источник",
                item.get("source_post") or "без должности",
            )
        return "%s · %s" % (
            item.get("source_name") or "Источник",
            item.get("source_post") or "без должности",
        )

    def _meta_label(self, item):
        if self._is_intercept(item):
            if item.get("status") == "sealed":
                return "канал: перехват · содержание скрыто"
            return "канал: %s · уверенность: %s" % (
                item.get("channel_label") or "доклад",
                item.get("confidence_label") or "неизвестна",
            )
        return "канал: %s · уверенность: %s" % (
            item.get("channel_label") or "доклад",
            item.get("confidence_label") or "неизвестна",
        )

    def _note_label(self, item):
        if self._is_intercept(item):
            if item.get("counter"):
                return str(
                    item.get("counter_text") or "Контрмера принята."
                )
            if item.get("status") == "open":
                return "Перехват вскрыт. Выберите контрмеру."
            if self._now() + 1e-9 < float(item.get("available_at") or 0.0):
                return "Ожидайте доставки."
            return "Донесение можно вскрыть за действие."
        if str(item.get("status") or "") == "pending":
            return ""
        resolved = item.get("resolved") or {}
        revealed = resolved.get("revealed_truth", True)
        truth = item.get("true_band_label") if revealed else None
        line = (
            "истинное положение: «%s»" % truth
            if truth
            else "Истина не установлена: слух остался слухом."
        )
        if resolved.get("motive_revealed") and resolved.get("motive"):
            line += " · мотив: %s" % resolved.get("motive")
        return line

    def _can_open(self, item):
        return (
            self._is_intercept(item)
            and str(item.get("status") or "") == "sealed"
            and self._now() + 1e-9
            >= float(item.get("available_at") or 0.0)
        )


__all__ = ["ReportsOverlay", "REPORT_RECT"]
