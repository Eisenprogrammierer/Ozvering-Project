"""Оверлеи кампании: список работ и эмуляция времени.

Оба окна открываются поверх основного экрана и не ломают его
компоновку: длинные подписи процессов больше не спорят с кнопками
управления, а пропуск времени идёт отдельным управляемым шагом.
"""

from __future__ import annotations

import pygame

from ..ui.overlays import OverlayScreen
from ..ui.text_layout import fit_line, wrap_text

PROCESS_RECT = (250, 66, 780, 588)
EMULATION_RECT = (300, 96, 680, 512)

TEXT = (225, 230, 238)
MUTED = (145, 158, 176)
DIM = (105, 116, 134)
ACCENT = (78, 155, 224)
GOOD = (100, 200, 150)
WARN = (230, 184, 96)
PANEL_ROW = (24, 31, 44)
PANEL_ROW_ACTIVE = (30, 42, 60)
PANEL_BORDER = (58, 70, 92)

KIND_LABELS = {
    "action": "работа",
    "organ": "влияние",
    "automaton": "команда",
    "character": "персонал",
}

EMULATION_STEPS = (
    ("hour", "Час", 3600.0),
    ("day", "День", 86400.0),
    ("week", "Неделя", 7 * 86400.0),
    ("month", "Месяц", 30 * 86400.0),
    ("year", "Год", 365 * 86400.0),
)

EMULATION_SLICES = 180
EMULATION_TICKS = 6


def _bar(screen, rect, value, color):
    pygame.draw.rect(screen, (24, 29, 40), rect, border_radius=4)
    width = max(0, min(rect.width, int(rect.width * float(value))))
    if width > 0:
        pygame.draw.rect(
            screen,
            color,
            pygame.Rect(rect.x, rect.y, width, rect.height),
            border_radius=4,
        )
    pygame.draw.rect(screen, PANEL_BORDER, rect, 1, border_radius=4)


class ProcessesOverlay(OverlayScreen):
    """Отдельный список того, что сейчас выполняется и разворачивается."""

    def __init__(self, app, campaign, side=None):
        super().__init__(app, PROCESS_RECT)
        self.campaign = campaign
        self.side = str(side or campaign.player_side)
        self.scroll = 0

    def _records(self):
        active = self.campaign.active_processes(self.side)
        settling = self.campaign.settling_processes(self.side)
        active.sort(
            key=lambda item: (
                float(item.get("finish_at", 0.0)),
                str(item.get("id", "")),
            )
        )
        settling.sort(
            key=lambda item: (
                float(
                    (item.get("effect") or {}).get("finish_at", 0.0)
                ),
                str(item.get("id", "")),
            )
        )
        return [("active", item) for item in active] + [
            ("settling", item) for item in settling
        ]

    def handle_event(self, event):
        if self.close_btn.handle_event(event):
            return
        if event.type == pygame.MOUSEWHEEL:
            total = len(self._records())
            self.scroll = max(
                0, min(max(0, total - 5), self.scroll - event.y)
            )

    def _target(self, record):
        name = (
            record.get("target_name")
            or record.get("target")
            or record.get("target_organ_name")
            or ""
        )
        if name:
            return "цель: %s" % name
        executor = record.get("executor_name") or ""
        if executor:
            return "исполнитель: %s" % executor
        return "без явной цели"

    def _draw_row(self, screen, rect, mode, record):
        pygame.draw.rect(screen, PANEL_ROW_ACTIVE, rect, border_radius=6)
        pygame.draw.rect(screen, PANEL_BORDER, rect, 1, border_radius=6)
        kind = str(record.get("kind") or "action")
        kind_label = KIND_LABELS.get(kind, kind)
        label = (
            record.get("label")
            or record.get("action_id")
            or record.get("interaction_id")
            or "процесс"
        )
        title = "%s · %s" % (kind_label, label)
        screen.blit(
            self.app.font_small.render(
                fit_line(self.app.font_small, title, rect.width - 24),
                True,
                TEXT,
            ),
            (rect.x + 10, rect.y + 7),
        )
        screen.blit(
            self.app.font_tiny.render(
                fit_line(
                    self.app.font_tiny,
                    self._target(record),
                    rect.width - 24,
                ),
                True,
                MUTED,
            ),
            (rect.x + 10, rect.y + 27),
        )
        bar = pygame.Rect(rect.x + 10, rect.bottom - 22, rect.width - 20, 8)
        if mode == "active":
            duration = max(1e-6, float(record.get("duration", 0.0)))
            remaining = max(0.0, float(record.get("remaining", 0.0)))
            progress = 1.0 - min(1.0, remaining / duration)
            detail = "осталось %s · всего %s" % (
                self.campaign.duration_label(remaining),
                self.campaign.duration_label(duration),
            )
            color = ACCENT
        else:
            effect = dict(record.get("effect") or {})
            progress = max(
                0.0, min(1.0, float(effect.get("applied", 0.0)))
            )
            finish_at = float(effect.get("finish_at", 0.0))
            remaining = max(0.0, finish_at - float(self.campaign.elapsed))
            detail = "эффект: %d%% · осталось %s" % (
                int(progress * 100.0),
                self.campaign.duration_label(remaining),
            )
            color = GOOD
        screen.blit(
            self.app.font_tiny.render(
                fit_line(self.app.font_tiny, detail, rect.width - 24),
                True,
                DIM,
            ),
            (rect.x + 10, rect.y + 42),
        )
        _bar(screen, bar, progress, color)

    def draw(self, screen):
        self.draw_base(screen, "В РАБОТЕ")
        panel = self.panel.rect
        slots = self.campaign.slot_state(self.side)
        records = self._records()
        active = [item for mode, item in records if mode == "active"]
        settling = [item for mode, item in records if mode == "settling"]
        status = "слоты %d/%d · активно %d · эффектов %d" % (
            slots["used"],
            slots["slots"],
            len(active),
            len(settling),
        )
        screen.blit(
            self.app.font_small.render(status, True, MUTED),
            (panel.x + 20, panel.y + 48),
        )
        screen.blit(
            self.app.font_tiny.render(
                "Текущее действие занимает слот до завершения процесса; "
                "эффект затем разворачивается во времени.",
                True,
                DIM,
            ),
            (panel.x + 20, panel.y + 70),
        )
        top = panel.y + 94
        visible = records[self.scroll:self.scroll + 5]
        if not visible:
            screen.blit(
                self.app.font_small.render(
                    "Сейчас ничего не выполняется.", True, MUTED
                ),
                (panel.x + 20, top + 12),
            )
            return
        for index, (mode, record) in enumerate(visible):
            rect = pygame.Rect(
                panel.x + 20,
                top + index * 86,
                panel.width - 40,
                78,
            )
            self._draw_row(screen, rect, mode, record)
        if len(records) > 5:
            hint = "колесо мыши · %d из %d" % (
                self.scroll + 1,
                len(records),
            )
            surface = self.app.font_tiny.render(hint, True, DIM)
            screen.blit(
                surface,
                (panel.right - 20 - surface.get_width(), panel.y + 48),
            )


class TimeEmulationOverlay(OverlayScreen):
    """Пропуск игрового времени шагами с возможностью остановки."""

    escape_action = "custom"

    def __init__(self, app, campaign):
        super().__init__(app, EMULATION_RECT)
        self.campaign = campaign
        self.step_index = 1
        self.active = False
        self.paused = False
        self.total = 0.0
        self.remaining = 0.0
        self.simulated = 0.0
        self.events_before = 0
        self.message = ""
        panel = self.panel.rect
        self.start_rect = pygame.Rect(
            panel.x + 20, panel.bottom - 56, 220, 38
        )
        self.close_text_rect = pygame.Rect(
            panel.right - 180, panel.bottom - 56, 160, 38
        )
        self.close_btn.callback = self.close
        self._reset_step()

    @property
    def step(self):
        return EMULATION_STEPS[self.step_index]

    def _step_rects(self):
        panel = self.panel.rect
        gap = 8
        width = (panel.width - 40 - gap * 4) // 5
        return [
            pygame.Rect(
                panel.x + 20 + index * (width + gap),
                panel.y + 142,
                width,
                36,
            )
            for index in range(len(EMULATION_STEPS))
        ]

    def _reset_step(self):
        self.total = float(self.step[2])
        self.remaining = self.total
        self.simulated = 0.0
        self.events_before = len(self.campaign.events)
        self._slice_index = 0
        days = self.total / 86400.0
        ticks = (
            0
            if days < 1.0
            else min(EMULATION_TICKS, max(1, int(round(days))))
        )
        self._tick_every = (
            max(1, (EMULATION_SLICES + ticks - 1) // ticks)
            if ticks
            else 0
        )
        self.paused = False
        self.message = ""

    def start(self):
        """Запустить шаг или продолжить приостановленный."""
        if self.active or self.campaign.finished:
            return
        if self.paused and self.remaining > 1e-9:
            self.active = True
            self.message = "Эмуляция продолжена."
            return
        self._reset_step()
        self.active = True

    def pause(self):
        """Остановить моделирование, сохранив пройденную часть шага."""
        if not self.active:
            return
        self.active = False
        if self.remaining > 1e-9:
            self.paused = True
            self.message = (
                "Пауза на %s. Можно продолжить или закрыть окно."
                % self.campaign.duration_label(self.simulated)
            )
        else:
            self._finish_step()

    def stop(self, reason):
        """Полностью остановить шаг и показать итог."""
        if not self.active:
            return
        self.active = False
        self.paused = False
        self.message = "%s Пропущено: %s." % (
            reason,
            self.campaign.duration_label(self.simulated),
        )

    def _finish_step(self):
        self.active = False
        self.paused = False
        events = max(0, len(self.campaign.events) - self.events_before)
        self.message = "Шаг завершён: %s · новых событий: %d." % (
            self.campaign.duration_label(self.simulated),
            events,
        )

    def close(self):
        if self.active:
            self.stop("Эмуляция остановлена.")
        self.app.manager.pop()

    def on_escape(self):
        self.close()

    def handle_event(self, event):
        if self.close_btn.handle_event(event):
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        pos = event.pos
        if self.close_text_rect.collidepoint(pos):
            self.close()
            return
        if self.start_rect.collidepoint(pos):
            if self.active:
                self.pause()
            else:
                self.start()
            return
        if self.active:
            return
        for index, rect in enumerate(self._step_rects()):
            if rect.collidepoint(pos):
                self.step_index = index
                self._reset_step()
                return

    def update(self, dt):
        if not self.active or self.campaign.finished:
            if self.active and self.campaign.finished:
                self.stop("Кампания завершена.")
            return
        slice_seconds = max(20.0, self.total / float(EMULATION_SLICES))
        step = min(slice_seconds, self.remaining)
        tick = False
        if self._tick_every:
            tick = self._slice_index % self._tick_every == 0
            if self.remaining <= step + 1e-9:
                tick = True
        self._slice_index += 1
        self.campaign.advance_simulation(step, tick=tick)
        self.remaining = max(0.0, self.remaining - step)
        self.simulated += step
        if self.campaign.finished:
            self.stop("Кампания завершена.")
            return
        if self.remaining <= 1e-9:
            self._finish_step()

    def _step_label(self):
        return self.step[1].lower()

    def draw(self, screen):
        self.draw_base(screen, "ЭМУЛЯЦИЯ ВРЕМЕНИ")
        panel = self.panel.rect
        screen.blit(
            self.app.font_tiny.render(
                "Мир идёт сам. Выберите шаг и запустите моделирование — "
                "поставить на паузу можно в любой момент.",
                True,
                MUTED,
            ),
            (panel.x + 20, panel.y + 48),
        )
        screen.blit(
            self.app.font_tiny.render("ШАГ", True, DIM),
            (panel.x + 20, panel.y + 120),
        )
        for index, rect in enumerate(self._step_rects()):
            selected = index == self.step_index
            if self.active:
                fill = (40, 44, 56)
            elif selected:
                fill = (46, 86, 138)
            else:
                fill = (32, 40, 54)
            pygame.draw.rect(screen, fill, rect, border_radius=6)
            pygame.draw.rect(
                screen,
                ACCENT if selected else PANEL_BORDER,
                rect,
                2 if selected else 1,
                border_radius=6,
            )
            text = self.app.font_small.render(
                EMULATION_STEPS[index][1],
                True,
                TEXT if not self.active else DIM,
            )
            screen.blit(text, text.get_rect(center=rect.center))
        progress = (
            1.0 - self.remaining / self.total if self.total > 0 else 0.0
        )
        info_y = panel.y + 202
        screen.blit(
            self.app.font_small.render(
                "Моделируется: %s" % self._step_label(), True, TEXT
            ),
            (panel.x + 20, info_y),
        )
        screen.blit(
            self.app.font_small.render(
                "Пройдено: %s из %s"
                % (
                    self.campaign.duration_label(self.simulated),
                    self.campaign.duration_label(self.total),
                ),
                True,
                MUTED,
            ),
            (panel.x + 20, info_y + 24),
        )
        slots = self.campaign.slot_state(self.campaign.player_side)
        events = max(0, len(self.campaign.events) - self.events_before)
        screen.blit(
            self.app.font_tiny.render(
                "слоты %d/%d · событий за шаг: %d"
                % (slots["used"], slots["slots"], events),
                True,
                DIM,
            ),
            (panel.x + 300, info_y + 24),
        )
        bar = pygame.Rect(panel.x + 20, info_y + 56, panel.width - 40, 12)
        _bar(screen, bar, progress, ACCENT)
        if self.message:
            for line_number, line in enumerate(
                wrap_text(
                    self.app.font_tiny,
                    self.message,
                    panel.width - 40,
                )[:2]
            ):
                screen.blit(
                    self.app.font_tiny.render(line, True, GOOD),
                    (panel.x + 20, info_y + 80 + line_number * 14),
                )
        recent = self.campaign.events[self.events_before:]
        if recent:
            last = str(recent[-1].get("text") or "")
            screen.blit(
                self.app.font_tiny.render(
                    "Последнее событие:", True, DIM
                ),
                (panel.x + 20, info_y + 118),
            )
            for line_number, line in enumerate(
                wrap_text(
                    self.app.font_tiny,
                    last,
                    panel.width - 40,
                )[:2]
            ):
                screen.blit(
                    self.app.font_tiny.render(line, True, MUTED),
                    (panel.x + 20, info_y + 132 + line_number * 13),
                )
        if self.active:
            start_text = "ПАУЗА"
        elif self.paused:
            start_text = "ПРОДОЛЖИТЬ"
        else:
            start_text = "НАЧАТЬ ЭМУЛЯЦИЮ"
        pygame.draw.rect(
            screen,
            (150, 92, 58) if self.active else (46, 86, 138),
            self.start_rect,
            border_radius=7,
        )
        pygame.draw.rect(
            screen, PANEL_BORDER, self.start_rect, 2, border_radius=7
        )
        text = self.app.font_small.render(start_text, True, TEXT)
        screen.blit(text, text.get_rect(center=self.start_rect.center))
        pygame.draw.rect(
            screen, (40, 44, 56), self.close_text_rect, border_radius=7
        )
        pygame.draw.rect(
            screen, PANEL_BORDER, self.close_text_rect, 2, border_radius=7
        )
        text = self.app.font_small.render("Закрыть", True, TEXT)
        screen.blit(text, text.get_rect(center=self.close_text_rect.center))


__all__ = ["ProcessesOverlay", "TimeEmulationOverlay"]
