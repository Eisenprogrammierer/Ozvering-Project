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

    def _history(self):
        reports = getattr(self.campaign.dispatch, "reports", ()) or ()
        return [
            report
            for report in reports
            if str(report.get("side") or "") == self.side
            and str(report.get("status") or "") in ("resolved", "expired")
        ]

    def _current(self):
        pending = self._pending()
        if pending:
            self.index = max(0, min(self.index, len(pending) - 1))
            return pending[self.index], pending
        history = self._history()
        return (history[-1] if history else None), []

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
        text = str(report.get("text") or "")
        rect = self._body_rect()
        line_h = self.app.font_small.get_height() + 5
        limit = max(0, rect.height // line_h)
        lines = wrap_text(self.app.font_small, text, rect.width)
        return lines[:limit]

    def _choice_rects(self, report):
        choices = list(report.get("choices") or ())
        if not choices:
            return []
        panel = self.panel.rect
        inner = panel.width - 40
        gap = CHOICE_GAP * (len(choices) - 1)
        width = max(80, (inner - gap) // len(choices))
        top = panel.bottom - 58
        rects = []
        for position in range(len(choices)):
            left = panel.x + 20 + position * (width + CHOICE_GAP)
            rects.append(pygame.Rect(left, top, width, CHOICE_H))
        return rects

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
            report, pending = self._current()
            if pending:
                self.index = max(
                    0,
                    min(len(pending) - 1, self.index - event.y),
                )
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        report, pending = self._current()
        if report is None:
            return
        prev_rect, next_rect = self._nav_rects()
        if pending and prev_rect.collidepoint(event.pos):
            self.index = max(0, self.index - 1)
            self.message = ""
            return
        if pending and next_rect.collidepoint(event.pos):
            self.index = min(len(pending) - 1, self.index + 1)
            self.message = ""
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
            pending = self._pending()
            if pending:
                self.index = min(self.index, len(pending) - 1)
            return

    # --- рисование --------------------------------------------------
    def _draw_choice(self, screen, rect, label):
        pygame.draw.rect(screen, (46, 86, 138), rect, border_radius=6)
        pygame.draw.rect(screen, PANEL_BORDER, rect, 2, border_radius=6)
        surface = self.app.font_small.render(
            fit_line(self.app.font_small, label, rect.width - 16),
            True,
            TEXT,
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
        report, pending = self._current()

        pending_count = len(pending)
        if report is None:
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

        status = "ожидает решения" if report.get("status") == "pending" else (
            "закрыт"
        )
        if pending_count:
            status += " · %d из %d" % (self.index + 1, pending_count)
        screen.blit(
            self.app.font_small.render(
                fit_line(
                    self.app.font_small,
                    status,
                    panel.width - 220,
                ),
                True,
                WARN if report.get("status") == "pending" else DIM,
            ),
            (panel.x + 20, panel.y + 52),
        )

        source = "%s · %s" % (
            report.get("source_name") or "Источник",
            report.get("source_post") or "без должности",
        )
        screen.blit(
            self.app.font_small.render(
                fit_line(self.app.font_small, source, panel.width - 40),
                True,
                ACCENT,
            ),
            (panel.x + 20, panel.y + 76),
        )
        meta = "канал: %s · уверенность: %s" % (
            report.get("channel_label") or "доклад",
            report.get("confidence_label") or "неизвестна",
        )
        screen.blit(
            self.app.font_tiny.render(meta, True, DIM),
            (panel.x + 20, panel.y + 100),
        )
        screen.blit(
            self.app.font_body.render(
                fit_line(
                    self.app.font_body,
                    report.get("title") or "Доклад",
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
        for line in self._body_lines(report):
            screen.blit(
                self.app.font_small.render(line, True, TEXT),
                (body.x + 12, y),
            )
            y += self.app.font_small.get_height() + 5

        if self.message:
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(
                        self.app.font_tiny,
                        self.message,
                        panel.width - 40,
                    ),
                    True,
                    GOOD if self.last_result else WARN,
                ),
                (panel.x + 20, panel.bottom - 82),
            )
        elif str(report.get("status") or "") != "pending":
            resolved = report.get("resolved") or {}
            truth = report.get("true_band_label")
            line = "истинное положение: «%s»" % truth if truth else ""
            screen.blit(
                self.app.font_tiny.render(
                    fit_line(
                        self.app.font_tiny, line, panel.width - 40
                    ),
                    True,
                    MUTED,
                ),
                (panel.x + 20, panel.bottom - 82),
            )

        if pending:
            prev_rect, next_rect = self._nav_rects()
            for rect, label, enabled in (
                (prev_rect, "‹", self.index > 0),
                (next_rect, "›", self.index < len(pending) - 1),
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

        if str(report.get("status") or "") == "pending":
            for rect, choice in zip(
                self._choice_rects(report), report.get("choices") or ()
            ):
                self._draw_choice(
                    screen, rect, str(choice.get("label") or choice.get("id"))
                )


__all__ = ["ReportsOverlay", "REPORT_RECT"]
