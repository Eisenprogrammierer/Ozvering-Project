"""Кодекс кампании: персонажи и автоматы пресета.

Экран не управляет кампанией. Он показывает то, что уже собрано в
``CampaignPreset``: людей, фракции и органы-автоматы. Это делает лор
видимым, не раздувая основной экран работ.
"""

from __future__ import annotations

import pygame

import warfare as W

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import draw_fitted, wrap_text
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.campaign_codex")

WIDTH, HEIGHT = 1280, 720
PANEL_RECT = pygame.Rect(30, 30, 1220, 660)
LIST_RECT = pygame.Rect(56, 170, 390, 450)
DETAIL_RECT = pygame.Rect(466, 170, 758, 450)
ROW_H = 26
TEXT = (226, 231, 239)
MUTED = (150, 162, 180)
DIM = (108, 120, 138)
ACCENT = (80, 150, 220)
GOOD = (110, 200, 150)
WARN = (230, 184, 96)

TABS = (("characters", "Персонажи"), ("automata", "Автоматы"))
KIND_LABELS = {
    "organization": "организация",
    "faction": "фракция",
    "organ": "орган",
}


class CampaignCodexScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel(PANEL_RECT)
        self.preset = getattr(app, "campaign_preset", None)
        self.tab = "characters"
        self.scroll = {"characters": 0, "automata": 0}
        self.selected = {"characters": 0, "automata": 0}
        self.characters = list(
            getattr(self.preset, "characters", ()) or ()
        )
        self.automata = list(getattr(self.preset, "automata", ()) or ())
        self._faction_names = {}
        self._organization_names = {}
        if self.preset is not None:
            for faction in getattr(self.preset, "factions", ()) or ():
                self._faction_names[faction.get("id")] = faction.get("name")
                self._faction_names[faction.get("side")] = faction.get("name")
            for organization in (
                getattr(self.preset, "organizations", ()) or ()
            ):
                self._organization_names[organization.get("id")] = (
                    organization.get("name")
                )
        self.tab_buttons = [
            Button(
                (56 + index * 210, 108, 200, 40),
                label,
                app.font_small,
                lambda value=key: self.set_tab(value),
            )
            for index, (key, label) in enumerate(TABS)
        ]
        self.back_button = Button(
            (1090, 630, 140, 40),
            "Назад",
            app.font_body,
            app.manager.pop,
        )
        self.buttons = self.tab_buttons + [self.back_button]
        logger.info(
            "Кодекс кампании: персонажей=%d, автоматов=%d",
            len(self.characters),
            len(self.automata),
        )

    # ------------------------------------------------------------------
    # Данные и навигация
    # ------------------------------------------------------------------
    @property
    def rows(self):
        return self.characters if self.tab == "characters" else self.automata

    def set_tab(self, tab):
        if tab not in ("characters", "automata"):
            return
        self.tab = tab
        logger.debug("Кодекс: вкладка %s", tab)

    def _visible_rows(self):
        return max(1, (LIST_RECT.height - 12) // ROW_H)

    def select(self, index):
        if index < 0 or index >= len(self.rows):
            return
        self.selected[self.tab] = index

    def scroll_by(self, amount):
        maximum = max(0, len(self.rows) - self._visible_rows())
        self.scroll[self.tab] = max(
            0,
            min(maximum, self.scroll[self.tab] + int(amount)),
        )

    def _row_label(self, index, item):
        if self.tab == "characters":
            faction = self._faction_names.get(item.get("faction_id"), "")
            flags = ""
            if item.get("is_player"):
                flags = " ★"
            elif item.get("is_faction_leader"):
                flags = " ◆"
            text = "%s%s — %s" % (
                item.get("name", "?"),
                flags,
                faction or item.get("side", "?"),
            )
            post = item.get("post")
            if post:
                text += " · %s" % post
            return text
        kind = KIND_LABELS.get(item.get("kind"), item.get("kind", "?"))
        owner = (
            self._faction_names.get(item.get("owner_id"))
            or self._organization_names.get(item.get("owner_id"))
            or item.get("side", "")
        )
        text = "%s · %s" % (item.get("name", "?"), kind)
        if owner:
            text += " · %s" % owner
        return text

    # ------------------------------------------------------------------
    # Ввод
    # ------------------------------------------------------------------
    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            if LIST_RECT.collidepoint(pos):
                self.scroll_by(-event.y)
            elif DETAIL_RECT.collidepoint(pos):
                self.scroll_by(-event.y)
            return
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_DOWN):
                step = -1 if event.key == pygame.K_UP else 1
                self.select(self.selected[self.tab] + step)
                self._ensure_visible()
                return
            if event.key == pygame.K_PAGEUP:
                self.scroll_by(-self._visible_rows())
                return
            if event.key == pygame.K_PAGEDOWN:
                self.scroll_by(self._visible_rows())
                return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            if LIST_RECT.collidepoint(pos):
                row = (pos[1] - LIST_RECT.y - 6) // ROW_H
                index = self.scroll[self.tab] + row
                self.select(index)
                return
        for button in self.buttons:
            if button.handle_event(event):
                return

    def _ensure_visible(self):
        index = self.selected[self.tab]
        start = self.scroll[self.tab]
        visible = self._visible_rows()
        if index < start:
            self.scroll[self.tab] = index
        elif index >= start + visible:
            self.scroll[self.tab] = index - visible + 1

    # ------------------------------------------------------------------
    # Отрисовка
    # ------------------------------------------------------------------
    def _draw_tabs(self, screen):
        for button in self.tab_buttons:
            active = (
                button.text == dict(TABS)[self.tab]
            )
            pygame.draw.rect(
                screen,
                ACCENT if active else (46, 86, 138),
                button.rect,
                border_radius=6,
            )
            pygame.draw.rect(
                screen, (58, 70, 92), button.rect, 2, border_radius=6
            )
            surf = self.app.font_small.render(button.text, True, TEXT)
            screen.blit(surf, surf.get_rect(center=button.rect.center))

    def _draw_list(self, screen):
        pygame.draw.rect(screen, (16, 21, 31), LIST_RECT, border_radius=8)
        pygame.draw.rect(
            screen, (58, 70, 92), LIST_RECT, 2, border_radius=8
        )
        visible = self._visible_rows()
        start = self.scroll[self.tab]
        selected = self.selected[self.tab]
        old_clip = screen.get_clip()
        screen.set_clip(LIST_RECT.inflate(-4, -4))
        for offset in range(visible):
            index = start + offset
            if index >= len(self.rows):
                break
            item = self.rows[index]
            rect = pygame.Rect(
                LIST_RECT.x + 6,
                LIST_RECT.y + 6 + offset * ROW_H,
                LIST_RECT.width - 12,
                ROW_H - 2,
            )
            if index == selected:
                pygame.draw.rect(screen, (34, 48, 68), rect, border_radius=4)
                pygame.draw.rect(
                    screen, ACCENT, rect, 1, border_radius=4
                )
            label = self._row_label(index, item)
            surf = self.app.font_tiny.render(
                label, True, TEXT if index == selected else MUTED
            )
            screen.blit(
                surf,
                (rect.x + 8, rect.centery - surf.get_height() // 2),
            )
        screen.set_clip(old_clip)
        total = len(self.rows)
        if total > visible:
            counter = "%d–%d / %d" % (
                start + 1,
                min(total, start + visible),
                total,
            )
            screen.blit(
                self.app.font_tiny.render(counter, True, DIM),
                (LIST_RECT.x + 10, LIST_RECT.bottom + 12),
            )
            screen.blit(
                self.app.font_tiny.render(
                    "Колесо мыши — прокрутка", True, DIM
                ),
                (LIST_RECT.right - 170, LIST_RECT.bottom + 12),
            )

    def _draw_character(self, screen, character):
        x = DETAIL_RECT.x + 18
        y = DETAIL_RECT.y + 16
        width = DETAIL_RECT.width - 36
        screen.blit(
            self.app.font_small.render("ПЕРСОНАЖ", True, MUTED), (x, y)
        )
        y += 24
        screen.blit(
            self.app.font_body.render(
                character.get("name", "?"), True, TEXT
            ),
            (x, y),
        )
        y += 30
        faction = self._faction_names.get(
            character.get("faction_id"), character.get("side", "?")
        )
        flags = []
        if character.get("is_player"):
            flags.append("игрок")
        if character.get("is_faction_leader"):
            flags.append("лидер фракции")
        meta = "%s · %s" % (faction, character.get("post", "должность"))
        if flags:
            meta += " · " + ", ".join(flags)
        screen.blit(
            self.app.font_tiny.render(meta, True, ACCENT), (x, y)
        )
        y += 22
        biography = str(character.get("biography") or "")
        draw_fitted(
            screen,
            [self.app.font_small, self.app.font_tiny],
            biography,
            (x, y, width, 110),
            (205, 212, 224),
        )
        y += 118
        screen.blit(
            self.app.font_small.render("Черты характера", True, MUTED),
            (x, y),
        )
        y += 22
        personality = dict(character.get("personality") or {})
        top_traits = sorted(
            personality.items(), key=lambda item: float(item[1]), reverse=True
        )[:6]
        trait_text = " · ".join(
            "%s %.2f" % (W.TRAITS_RU.get(key, key), float(value))
            for key, value in top_traits
        )
        for line in wrap_text(self.app.font_tiny, trait_text, width)[:2]:
            screen.blit(
                self.app.font_tiny.render(line, True, TEXT), (x, y)
            )
            y += 16
        y += 8
        screen.blit(
            self.app.font_small.render("Ведущие потребности", True, MUTED),
            (x, y),
        )
        y += 22
        urgency = dict(character.get("urgency") or {})
        top_needs = sorted(
            urgency.items(), key=lambda item: float(item[1]), reverse=True
        )[:5]
        need_text = " · ".join(
            "%s %.2f" % (W.NEEDS_RU.get(key, key), float(value))
            for key, value in top_needs
        )
        for line in wrap_text(self.app.font_tiny, need_text, width)[:2]:
            screen.blit(
                self.app.font_tiny.render(line, True, TEXT), (x, y)
            )
            y += 16

    def _draw_automaton(self, screen, item):
        x = DETAIL_RECT.x + 18
        y = DETAIL_RECT.y + 16
        width = DETAIL_RECT.width - 36
        automaton = dict(item.get("automaton") or {})
        kind = KIND_LABELS.get(item.get("kind"), item.get("kind", "?"))
        screen.blit(
            self.app.font_small.render(
                "АВТОМАТ · %s" % kind.upper(), True, MUTED
            ),
            (x, y),
        )
        y += 24
        screen.blit(
            self.app.font_body.render(
                item.get("name") or automaton.get("name", "?"), True, TEXT
            ),
            (x, y),
        )
        y += 30
        owner = (
            self._faction_names.get(item.get("owner_id"))
            or self._organization_names.get(item.get("owner_id"))
            or item.get("owner_id", "")
        )
        if owner:
            screen.blit(
                self.app.font_tiny.render(
                    "Владелец: %s" % owner, True, ACCENT
                ),
                (x, y),
            )
            y += 20
        description = str(
            automaton.get("description")
            or automaton.get("name")
            or "Описание не задано."
        )
        draw_fitted(
            screen,
            [self.app.font_small, self.app.font_tiny],
            description,
            (x, y, width, 62),
            (205, 212, 224),
        )
        y += 68
        states = list(automaton.get("states") or ())
        transitions = list(automaton.get("transitions") or ())
        screen.blit(
            self.app.font_small.render(
                "Состояния (%d)" % len(states), True, MUTED
            ),
            (x, y),
        )
        y += 22
        names = {str(state.get("id")): state.get("name") for state in states}
        state_text = " · ".join(
            "%s%s"
            % (
                state.get("name", state.get("id", "?")),
                " (старт)" if state.get("initial") else "",
            )
            for state in states
        )
        for line in wrap_text(self.app.font_tiny, state_text, width)[:2]:
            screen.blit(
                self.app.font_tiny.render(line, True, TEXT), (x, y)
            )
            y += 16
        y += 8
        screen.blit(
            self.app.font_small.render(
                "Переходы (%d)" % len(transitions), True, MUTED
            ),
            (x, y),
        )
        y += 22
        for transition in transitions[:5]:
            source = names.get(
                str(transition.get("source")),
                transition.get("source", "?"),
            )
            target = names.get(
                str(transition.get("target")),
                transition.get("target", "?"),
            )
            event = str(transition.get("event") or "")
            line = "%s → %s" % (source, target)
            if event:
                line += ": %s" % event
            for wrapped in wrap_text(
                self.app.font_tiny, line, width
            )[:2]:
                screen.blit(
                    self.app.font_tiny.render(wrapped, True, TEXT),
                    (x, y),
                )
                y += 15
            y += 2
        if len(transitions) > 5:
            screen.blit(
                self.app.font_tiny.render(
                    "…и ещё %d" % (len(transitions) - 5), True, DIM
                ),
                (x, y),
            )

    def _draw_detail(self, screen):
        pygame.draw.rect(screen, (16, 21, 31), DETAIL_RECT, border_radius=8)
        pygame.draw.rect(
            screen, (58, 70, 92), DETAIL_RECT, 2, border_radius=8
        )
        index = self.selected[self.tab]
        if index >= len(self.rows):
            return
        item = self.rows[index]
        old_clip = screen.get_clip()
        screen.set_clip(DETAIL_RECT.inflate(-6, -6))
        if self.tab == "characters":
            self._draw_character(screen, item)
        else:
            self._draw_automaton(screen, item)
        screen.set_clip(old_clip)

    def draw(self, screen):
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 170))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        title = self.app.font_title.render(
            "Кодекс кампании", True, (224, 228, 236)
        )
        screen.blit(title, (56, 54))
        preset_title = (
            getattr(self.preset, "title", "") if self.preset else ""
        )
        if not preset_title:
            preset_title = "Пресет не загружен"
        screen.blit(
            self.app.font_small.render(preset_title, True, MUTED),
            (56, 90),
        )
        self._draw_tabs(screen)
        self._draw_list(screen)
        self._draw_detail(screen)
        counts = "персонажей: %d · автоматов: %d" % (
            len(self.characters),
            len(self.automata),
        )
        screen.blit(
            self.app.font_tiny.render(counts, True, DIM),
            (56, 660),
        )
        self.back_button.draw(screen)


__all__ = ["CampaignCodexScreen", "KIND_LABELS", "TABS"]
