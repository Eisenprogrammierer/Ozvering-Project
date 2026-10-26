"""Основной экран игры: аудиенция, голосование совета и итоги недели."""

from __future__ import annotations

import pygame

from ui import theme
from ui.scene import Scene
from ui.widgets import Button

from .. import ui
from ..ui import AdvisorRow, OptionCard


class CouncilScene(Scene):
    name = "council"

    def on_enter(self, **kwargs):
        self.selected = None
        self.report = None
        self.vote_data = None
        self.option_cards = []
        self.advisor_rows = []
        self.left_rect = pygame.Rect(0, 0, 0, 0)
        self.right_rect = pygame.Rect(0, 0, 0, 0)
        self.center_rect = pygame.Rect(0, 0, 0, 0)
        self.banner_rect = pygame.Rect(0, 0, 0, 0)
        self._redirect = None
        self._prepare()

    def _prepare(self):
        game = self.app.game
        if game is None:
            self._redirect = "menu"
            return
        if game.phase == "ended":
            self._redirect = "ending"
            return
        if game.phase == "report":
            self.report = game.last_result
            self.selected = None
            return
        petition = game.current_petition
        if petition is None:
            self._redirect = "ending"
            return
        options = petition.get("options", [])
        valid = {item.get("id") for item in options}
        if self.selected not in valid:
            self.selected = options[0].get("id") if options else None
        self._refresh_vote()

    def _refresh_vote(self):
        game = self.app.game
        self.vote_data = None
        if game is None or self.selected is None:
            return
        option = game.option(self.selected)
        if option is not None:
            self.vote_data = game.council_vote(option)

    def update(self, dt):
        if self._redirect == "menu":
            self._redirect = None
            self.app.go("menu")
        elif self._redirect == "ending":
            self._redirect = None
            self.app.go("ending")

    # ------------------------------------------------------------------
    # Раскладка
    # ------------------------------------------------------------------
    def layout(self, w, h):
        self.widgets = []
        self.option_cards = []
        self.advisor_rows = []
        self._w, self._h = w, h

        self.widgets.append(Button("ХРОНИКА", self._chronicle,
                                   (w - theme.EDGE - 168, 12, 78, 26)))
        self.widgets.append(Button("ПАУЗА", self._pause,
                                   (w - theme.EDGE - 84, 12, 78, 26)))

        game = self.app.game
        if game is None or self._redirect:
            return

        top = 84
        bottom = h - 68
        if self.report is not None or game.phase == "report":
            bw = 220
            label = "ДАЛЬШЕ" if game.status == "active" else "К ФИНАЛУ"
            self.widgets.append(Button(label, self._continue,
                                       ((w - bw) // 2, h - 62, bw, 44)))
            return

        gap = theme.GAP
        left_w = min(250, max(210, int(w * 0.23)))
        right_w = min(300, max(250, int(w * 0.28)))
        self.left_rect = pygame.Rect(theme.EDGE, top, left_w, bottom - top)
        self.right_rect = pygame.Rect(w - theme.EDGE - right_w, top,
                                      right_w, bottom - top)
        center_x = self.left_rect.right + gap
        center_w = self.right_rect.left - gap - center_x
        self.center_rect = pygame.Rect(center_x, top, center_w, bottom - top)

        petition = game.current_petition
        options = petition.get("options", []) if petition else []
        self.banner_rect = pygame.Rect(self.center_rect.left,
                                       self.center_rect.top,
                                       self.center_rect.width, 88)
        options_top = self.center_rect.top + 190
        action_y = self.center_rect.bottom - 44
        area = max(120, action_y - options_top - gap)
        count = max(1, len(options))
        card_h = int((area - gap * (count - 1)) / count)
        card_h = max(62, min(98, card_h))
        for index, option in enumerate(options):
            support = game.option_support(option)
            card = OptionCard(
                option, index, support, self._select,
                (self.center_rect.left, options_top + index * (card_h + gap),
                 self.center_rect.width, card_h),
                selected=(option.get("id") == self.selected),
            )
            self.option_cards.append(card)
            self.widgets.append(card)

        option = game.option(self.selected) if self.selected else None
        support = game.option_support(option) if option else 0.0
        bw = (self.center_rect.width - 2 * gap) // 3
        self.widgets.append(Button(
            "Провести", self._decree,
            (self.center_rect.left, action_y, bw, 38),
            enabled=option is not None and support >= game.threshold))
        self.widgets.append(Button(
            "Настоять", self._force,
            (self.center_rect.left + bw + gap, action_y, bw, 38),
            enabled=option is not None))
        self.widgets.append(Button(
            "Отложить", self._defer,
            (self.center_rect.left + 2 * (bw + gap), action_y, bw, 38),
            enabled=option is not None))

        self.advisor_rows = []
        if option is not None and self.vote_data is not None:
            for advisor_id, advisor in game.advisors.items():
                row = AdvisorRow(
                    advisor,
                    (self.right_rect.left + 8,
                     self.right_rect.top + 56 + len(self.advisor_rows) * 62,
                     self.right_rect.width - 16, 56),
                    vote=self.vote_data["votes"].get(advisor_id),
                    stance=self.vote_data["stances"].get(advisor_id),
                )
                self.advisor_rows.append(row)

    # ------------------------------------------------------------------
    # Действия
    # ------------------------------------------------------------------
    def _select(self, option_id):
        self.selected = option_id
        self._refresh_vote()
        self.layout(*self.app.size)

    def _decree(self):
        self._resolve("decree")

    def _force(self):
        self._resolve("force")

    def _defer(self):
        self._resolve("defer")

    def _resolve(self, mode):
        game = self.app.game
        if game is None or self.selected is None:
            return
        try:
            game.resolve(self.selected, mode)
        except Exception as exc:
            self.app.save.settings["last_realm_error"] = str(exc)
            self.app.save.save_settings()
            return
        self.app.autosave()
        self.on_enter()
        self.layout(*self.app.size)

    def _continue(self):
        game = self.app.game
        if game is None:
            return
        phase = game.continue_after_report()
        if phase == "ended":
            self.app.go("ending")
            return
        self.on_enter()
        self.layout(*self.app.size)

    def _chronicle(self):
        self.app.push("chronicle")

    def _pause(self):
        self.app.push("pause")

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._pause()
                return True
            if event.key == pygame.K_c:
                self._chronicle()
                return True
            if self.report is not None or (
                    self.app.game and self.app.game.phase == "report"):
                if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self._continue()
                    return True
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._decree()
                return True
            elif event.key == pygame.K_f:
                self._force()
                return True
            elif event.key == pygame.K_d:
                self._defer()
                return True
            elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                index = event.key - pygame.K_1
                if index < len(self.option_cards):
                    self._select(self.option_cards[index].option["id"])
                return True
        return super().handle_event(event)

    # ------------------------------------------------------------------
    # Отрисовка
    # ------------------------------------------------------------------
    def draw(self, s):
        s.fill(theme.BG)
        w, h = s.get_size()
        game = self.app.game
        if game is None:
            return
        report = self.report or (game.last_result
                                 if game.phase == "report" else None)
        title = "ИТОГИ НЕДЕЛИ" if report else "АУДИЕНЦИЯ"
        theme.text(s, self.app.fonts.font_b, title, (theme.EDGE, 14),
                   ui.PARCHMENT)
        week = min(game.week, game.max_weeks)
        if report:
            week = report.get("week", week)
        theme.text(s, self.app.fonts.font_s,
                   "НЕДЕЛЯ %d / %d" % (week, game.max_weeks),
                   (w - theme.EDGE, 48), theme.TEXT_DIM, right=True)
        pygame.draw.line(s, theme.BORDER, (theme.EDGE, 68),
                         (w - theme.EDGE, 68), 1)

        if report:
            self._draw_report(s, report)
        else:
            self._draw_council(s)
        for wdg in self.widgets:
            wdg.draw(s, self.app.fonts)
        self._draw_footer(s, w, h)

    def _draw_footer(self, s, w, h):
        hint = ("1–3 — выбрать · Enter — провести · F — настоять · "
                "D — отложить · C — хроника · Esc — пауза")
        if self.report is not None or (
                self.app.game and self.app.game.phase == "report"):
            hint = "Enter / Space — дальше · C — хроника · Esc — пауза"
        theme.text(s, self.app.fonts.font_s, hint,
                   (w // 2, h - 18), theme.TEXT_MUTED, center=True)

    def _draw_council(self, s):
        game = self.app.game
        petition = game.current_petition
        if petition is None:
            return
        self._draw_leader(s)
        self._draw_council_panel(s)
        self._draw_petition(s, petition)

    def _draw_leader(self, s):
        game = self.app.game
        rect = self.left_rect
        theme.panel(s, rect, fill=theme.BG_ALT, border=theme.BORDER, radius=6)
        portrait = pygame.Rect(rect.left + 18, rect.top + 14,
                               rect.width - 36, 112)
        self.app.assets.draw_portrait(s, portrait, "portrait_leader",
                                      self.app.fonts)
        theme.text(s, self.app.fonts.font_s, "НОМИНАЛЬНЫЙ ЛИДЕР",
                   (rect.centerx, portrait.bottom + 8), theme.TEXT_MUTED,
                   center=True)
        theme.text(s, self.app.fonts.font, game.mandate_title(),
                   (rect.centerx, portrait.bottom + 26), ui.PARCHMENT,
                   center=True)
        y = portrait.bottom + 52
        for key in ("authority", "legitimacy", "unity", "unrest"):
            ui.draw_stat(s, self.app.fonts, key, game.stats[key],
                         (rect.left + 14, y, rect.width - 28, 28))
            y += 36
        for key in ("treasury", "stores"):
            ui.draw_stat(s, self.app.fonts, key, game.stats[key],
                         (rect.left + 14, y, rect.width - 28, 28),
                         max_value=200)
            y += 36
        y = rect.bottom - 75
        theme.text(s, self.app.fonts.font_s, "ЦЕНА РЕШЕНИЯ",
                   (rect.left + 14, y), theme.TEXT_MUTED)
        y += 18
        for label, effects in (
            ("Провести", self.app.content.game.get("decree_bonus", {})),
            ("Настоять", self.app.content.game.get("force_penalty", {})),
            ("Отложить", self.app.content.game.get("defer_penalty", {})),
        ):
            for line in theme.wrap(
                    self.app.fonts.font_s,
                    "%s: %s" % (label, ui.effect_text(effects)),
                    rect.width - 28):
                if y + 14 > rect.bottom - 4:
                    break
                theme.text(s, self.app.fonts.font_s, line,
                           (rect.left + 14, y), theme.TEXT_DIM)
                y += 14

    def _draw_council_panel(self, s):
        game = self.app.game
        rect = self.right_rect
        theme.panel(s, rect, fill=theme.BG_ALT, border=theme.BORDER, radius=6)
        theme.text(s, self.app.fonts.font_s, "СОВЕТ",
                   (rect.left + 12, rect.top + 10), ui.STEEL)
        option = game.option(self.selected) if self.selected else None
        if option is not None and self.vote_data is not None:
            support = self.vote_data["support"]
            theme.text(
                s, self.app.fonts.font_s,
                "Поддержка: %d%% (порог %d%%)"
                % (round(support * 100), round(game.threshold * 100)),
                (rect.left + 12, rect.top + 28),
                ui.support_color(support),
            )
        else:
            theme.text(s, self.app.fonts.font_s, "Выберите вариант",
                       (rect.left + 12, rect.top + 28), theme.TEXT_MUTED)
        for row in self.advisor_rows:
            row.draw(s, self.app.fonts, self.app.assets)
        if not self.advisor_rows:
            y = rect.top + 56
            for advisor in game.advisors.values():
                row = AdvisorRow(
                    advisor, (rect.left + 8, y, rect.width - 16, 56)
                )
                row.draw(s, self.app.fonts, self.app.assets)
                y += 62

    def _draw_petition(self, s, petition):
        game = self.app.game
        center = self.center_rect
        self.app.assets.draw(s, self.banner_rect, "scene_council",
                             self.app.fonts, caption="СЦЕНА")
        theme.text(s, self.app.fonts.font, petition.get("title", ""),
                   (center.left, self.banner_rect.bottom + 10), ui.PARCHMENT)
        y = self.banner_rect.bottom + 36
        max_y = self.center_rect.top + 180
        for line in theme.wrap(self.app.fonts.font_s,
                               petition.get("body", ""), center.width - 4):
            if y + 15 > max_y:
                break
            theme.text(s, self.app.fonts.font_s, line, (center.left, y),
                       theme.TEXT_DIM)
            y += 15


    def _draw_report(self, s, report):
        w, h = s.get_size()
        panel = pygame.Rect(theme.EDGE, 82, w - 2 * theme.EDGE, h - 82 - 70)
        theme.panel(s, panel, fill=theme.BG_ALT, border=theme.BORDER, radius=6)
        status = report.get("status", "active")
        status_color = {"won": theme.OK, "lost": theme.DANGER}.get(
            status, theme.TEXT_DIM)
        theme.text(s, self.app.fonts.font, "НЕДЕЛЯ %d" % report.get("week", 1),
                   (panel.left + 16, panel.top + 12), ui.PARCHMENT)
        theme.text(s, self.app.fonts.font_s,
                   {"won": "УСПЕХ", "lost": "ПОРАЖЕНИЕ"}.get(status, "ЗАВЕРШЕНО"),
                   (panel.right - 16, panel.top + 14), status_color, right=True)

        split = panel.left + int(panel.width * 0.48)
        left_w = split - panel.left - 30
        right_w = panel.right - split - 20
        y = panel.top + 44
        y = self._block(s, "РЕШЕНИЕ", "%s — %s" % (
            report.get("petition_title", ""),
            report.get("option_label", ""),
        ), panel.left + 16, y, left_w, ui.PARCHMENT)
        y = self._block(s, "СПОСОБ", ui.MODE_LABELS.get(
            report.get("mode"), report.get("mode", "")),
            panel.left + 16, y, left_w, theme.TEXT)
        y = self._block(s, "ПОДДЕРЖКА", "%d%%" % round(
            report.get("support", 0.0) * 100),
            panel.left + 16, y, left_w,
            ui.support_color(report.get("support", 0.0)))
        y = self._block(s, "ЭФФЕКТ РЕШЕНИЯ", ui.effect_text(
            report.get("decision_effects")), panel.left + 16, y, left_w,
            theme.TEXT)
        y = self._block(s, "ДОВЕРИЕ", ui.trust_text(
            report.get("trust_effects"), self.app.game.advisors),
            panel.left + 16, y, left_w, theme.TEXT)
        notes = report.get("notes") or []
        if notes:
            y = self._block(s, "ЗАМЕТКИ", " ".join(notes[:4]),
                            panel.left + 16, y, left_w, theme.TEXT_MUTED)

        y2 = panel.top + 44
        y2 = self._block(s, "СОДЕРЖАНИЕ", ui.effect_text(
            report.get("upkeep_effects")), split, y2, right_w, theme.TEXT)
        y2 = self._block(s, "ДРЕЙФ", ui.effect_text(
            report.get("drift_effects")), split, y2, right_w, theme.TEXT)
        event = report.get("event")
        if event:
            y2 = self._block(s, "СОБЫТИЕ", event.get("title", ""),
                             split, y2, right_w, theme.ACCENT)
            y2 = self._block(s, "", event.get("text", ""), split, y2,
                             right_w, theme.TEXT_DIM)
            y2 = self._block(s, "ЭФФЕКТ СОБЫТИЯ", ui.effect_text(
                report.get("event_effects")), split, y2, right_w, theme.TEXT)
        y2 = self._block(s, "СОСТОЯНИЕ ПОСЛЕ", ui.effect_text(
            report.get("stats_after")), split, y2, right_w, theme.TEXT)
        ending = report.get("ending")
        if ending:
            y2 = self._block(s, "ИТОГ", ending.get("title", ""),
                             split, y2, right_w,
                             theme.OK if ending.get("win") else theme.DANGER)
            y2 = self._block(s, "", ending.get("body", ""), split, y2,
                             right_w, theme.TEXT_MUTED)

    def _block(self, s, title, text, x, y, width, color):
        if title:
            theme.text(s, self.app.fonts.font_s, title, (x, y),
                       theme.TEXT_MUTED)
            y += 17
        for line in theme.wrap(self.app.fonts.font_s, text, width):
            if y + 15 > self._h - 78:
                return y
            theme.text(s, self.app.fonts.font_s, line, (x, y), color)
            y += 15
        return y + 8
