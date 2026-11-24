"""Общая отрисовка: шапка, вкладки, списки, журнал, низ."""

from __future__ import annotations

from .world_screen_support import (
    ACCENT,
    ACTION_ROW_H,
    BAD,
    BOTTOM_RECT,
    CONTENT_RECT,
    DIM,
    GOOD,
    HEADER_H,
    HEIGHT,
    LEFT_RECT,
    LIST_ROW_H,
    MAIN_TABS,
    MAIN_TAB_Y,
    MID_RECT,
    MUTED,
    PANEL_BG,
    PANEL_BORDER,
    RIGHT_RECT,
    SUB_TABS,
    SUB_TAB_H,
    SUB_TAB_Y,
    TEXT,
    WARN,
    WIDTH,
    pygame,
    world_text,
    wrap_text,
)


class WorldScreenDrawMixin:

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
        max_force = max(1e-9, float(condition.get("max_force", 1.0)))
        max_energy = max(1e-9, float(condition.get("max_energy", 1.0)))
        detail += " · F %d%% · E %d%%" % (
            int(round(100.0 * float(condition.get("force", 0.0)) / max_force)),
            int(
                round(
                    100.0
                    * float(condition.get("energy", 0.0))
                    / max_energy
                )
            ),
        )
        detail += " · H %d" % int(round(condition["health"]))
        if condition["sickness"] > 0.0:
            detail += " · болезнь %d%%" % int(
                round(condition["sickness"] * 100)
            )
        if condition.get("wound", 0.0) > 0.0:
            detail += " · рана %d%%" % int(
                round(condition["wound"] * 100)
            )
        screen.blit(
            self.app.font_tiny.render(
                self._clip_text(self.app.font_tiny, detail, 470),
                True,
                MUTED,
            ),
            (560, 38),
        )
        if self.free_mode:
            day = "день %d · %s · %s · действия %d / %d" % (
                self.engine.day,
                self.clock.time_label(),
                self.clock.speed_label(),
                self.engine.actions_left,
                self.engine.actions_per_day,
            )
        elif self.engine.infinite:
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
        if (
            not self.free_mode
            and not getattr(self.app, "active", True)
            and not self.clock.paused
        ):
            day += " · фон"
        pending = len(getattr(self.engine, "intents", ()) or ())
        if pending:
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
        tab_w = (WIDTH - 36 - gap * (len(MAIN_TABS) - 1)) // len(MAIN_TABS)
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
            elif kind == "norm":
                selected = entry["id"] == self.selected_norm_id
            else:
                selected = entry["id"] == self.selected_target_id
            fill = (38, 62, 88) if selected else (20, 26, 37)
            pygame.draw.rect(screen, fill, rect, border_radius=5)
            if selected:
                pygame.draw.rect(screen, ACCENT, rect, 1, border_radius=5)
            if kind == "character":
                self._draw_character_card(screen, rect, entry, selected)
            elif kind == "norm":
                self._draw_norm_card(screen, rect, entry, selected)
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

    def _draw_norm_card(self, screen, rect, norm, selected):
        badge = pygame.Rect(rect.x + 6, rect.y + 6, 44, 44)
        pygame.draw.rect(screen, (28, 36, 50), badge, border_radius=4)
        pygame.draw.rect(screen, PANEL_BORDER, badge, 1, border_radius=4)
        glyph = self.app.font_body.render("§", True, WARN)
        screen.blit(glyph, glyph.get_rect(center=badge.center))
        name_color = TEXT if selected else (205, 214, 228)
        screen.blit(
            self.app.font_small.render(
                self._clip_text(
                    self.app.font_small,
                    norm.get("label", norm["id"]),
                    rect.width - 66,
                ),
                True,
                name_color,
            ),
            (rect.x + 58, rect.y + 5),
        )
        detail = " · ".join(
            str(item)
            for item in (
                self.engine.domain_label(norm.get("domain", "")),
                norm.get("status", ""),
            )
            if item
        )
        screen.blit(
            self.app.font_tiny.render(
                self._clip_text(self.app.font_tiny, detail, rect.width - 66),
                True,
                MUTED,
            ),
            (rect.x + 58, rect.y + 23),
        )
        scope = str(norm.get("scope") or "")
        if scope:
            screen.blit(
                self.app.font_tiny.render(
                    self._clip_text(self.app.font_tiny, scope, 180),
                    True,
                    DIM,
                ),
                (rect.x + 58, rect.y + 41),
            )

    def _draw_action_list(self, screen, options, top, bottom, rect=None):
        self.action_rows = []
        panel = rect or MID_RECT
        if not options:
            screen.blit(
                self.app.font_tiny.render("нет доступных действий", True, DIM),
                (panel.x + 12, top + 8),
            )
            return
        visible = max(1, (bottom - top) // ACTION_ROW_H)
        start = min(self.action_scroll, max(0, len(options) - visible))
        for index, option in enumerate(options[start : start + visible]):
            rect = pygame.Rect(
                panel.x + 8,
                top + index * ACTION_ROW_H,
                panel.width - 16,
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
                (panel.x + 12, panel.bottom - 14),
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

    def _draw_log(self, screen, y):
        screen.blit(
            self.app.font_tiny.render("ЖУРНАЛ МИРА", True, WARN),
            (RIGHT_RECT.x + 14, y),
        )
        y += 17
        entries = self.engine.log_view(limit=5)
        for item in entries:
            prefix = "! " if item.get("critical") else ""
            text = "Д%d: %s%s" % (
                item.get("day", 0),
                prefix,
                item.get("text", ""),
            )
            line = self._clip_text(
                self.app.font_tiny, text, RIGHT_RECT.width - 28
            )
            color = BAD if item.get("critical") else DIM
            screen.blit(
                self.app.font_tiny.render(line, True, color),
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

    @staticmethod
    def _clock_flag(value):
        """Флаг часов: свойство `FreeClock` или метод `CampaignClock`."""

        return bool(value() if callable(value) else value)

    def _draw_bottom(self, screen):
        pygame.draw.rect(screen, (11, 15, 22), BOTTOM_RECT, border_radius=6)
        pygame.draw.rect(screen, PANEL_BORDER, BOTTOM_RECT, 1, border_radius=6)
        hint = (
            "Вкладки — разделы · карточки — люди и структуры · "
            "колесо — прокрутка · A — автопилот · прогноз качественный."
        )
        if self.free_mode:
            hint = (
                "Время идёт само · −/+ — скорость (не ниже 1x) · "
                "карточки — люди и структуры · колесо — прокрутка."
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
            if self.free_mode:
                self._draw_button(
                    screen,
                    self._speed_down_rect(),
                    "−",
                    self._clock_flag(self.clock.can_slow_down),
                )
                label = "%s · %s" % (
                    self.clock.speed_label(),
                    self.clock.time_label(),
                )
                surface = self.app.font_small.render(label, True, TEXT)
                screen.blit(
                    surface,
                    surface.get_rect(center=self._speed_label_rect().center),
                )
                self._draw_button(
                    screen,
                    self._speed_up_rect(),
                    "+",
                    self._clock_flag(self.clock.can_speed_up),
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
        elif self.main_tab == "norms":
            self._draw_norm_content(screen)
        else:
            self._draw_personality_content(screen)
        if self.main_tab == "personality":
            self._draw_personality_right(screen)
        else:
            self._draw_forecast(screen)
        self._draw_bottom(screen)
