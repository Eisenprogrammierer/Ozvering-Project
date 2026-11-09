"""Редактор личности героя перед стартом кампании автоматов.

Экран не задаёт роль и фракцию — они уже выбраны. Он собирает человека:
имя, происхождение, призвание, ценность, слабость и главную черту
характера. Содержание вариантов лежит в ``configs/characters/identity.json``.
"""

from __future__ import annotations

import random

import pygame

import warfare as W
from campaign.identity import IdentityError, load_identity_catalog
from naming.people import PersonNameGenerator

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import draw_fitted, line_height, wrap_text
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.identity_editor")

SECTION_TABLE = {
    "gender": "genders",
    "origin": "origins",
    "vocation": "vocations",
    "value": "values",
    "flaw": "flaws",
    "trait": "traits",
}
SECTION_ORDER = ("gender", "origin", "vocation", "value", "flaw", "trait")
SECTION_LABELS = {
    "gender": "Пол",
    "origin": "Происхождение",
    "vocation": "Призвание",
    "value": "Ценность",
    "flaw": "Слабость",
    "trait": "Главная черта",
}

PANEL_RECT = pygame.Rect(40, 36, 1200, 648)
NAME_RECT = pygame.Rect(300, 112, 420, 42)
CATEGORY_RECT = pygame.Rect(70, 190, 320, 48)
CATEGORY_GAP = 58
PREVIEW_RECT = pygame.Rect(430, 180, 780, 410)
TEXT = (228, 232, 240)
MUTED = (150, 162, 180)
DIM = (108, 120, 138)
ACCENT = (80, 150, 220)
GOOD = (110, 200, 150)


def _signed(value):
    amount = float(value)
    return ("+" if amount >= 0 else "") + ("%.2f" % amount)


class IdentityEditorScreen(BaseScreen):

    escape_action = "pop"

    def __init__(self, app, storyline=None, faction_id=None, on_start=None):
        super().__init__(app)
        self.storyline = storyline
        self.faction_id = faction_id
        self.on_start = on_start
        self.started = False
        self.selected_section = "origin"
        self.name_focus = True
        self.message = ""
        try:
            self.catalog = load_identity_catalog()
        except IdentityError as exc:
            # Без файла личности экран остаётся читаемым и не роняет
            # кампанию: показываем причину и позволяем вернуться назад.
            logger.error("Личность недоступна: %s", exc)
            self.catalog = None
            self.message = str(exc)
        self.values = {}
        if self.catalog is not None:
            for section in SECTION_ORDER:
                ids = self._ids(section)
                if ids:
                    self.values[section] = ids[0]
        self.name = ""
        if self.catalog is not None:
            self.name = self.catalog.default_name
        self.panel = Panel(PANEL_RECT)
        self.prev_button = Button(
            (PREVIEW_RECT.right - 100, PREVIEW_RECT.y + 10, 36, 30),
            "‹",
            app.font_body,
            lambda: self.cycle(self.selected_section, -1),
        )
        self.next_button = Button(
            (PREVIEW_RECT.right - 56, PREVIEW_RECT.y + 10, 36, 30),
            "›",
            app.font_body,
            lambda: self.cycle(self.selected_section, 1),
        )
        self.random_name_button = Button(
            (740, 112, 190, 42),
            "Случайное имя",
            app.font_small,
            self.random_name,
        )
        self.random_button = Button(
            (70, 618, 220, 40),
            "Случайная личность",
            app.font_small,
            self.randomize,
        )
        self.back_button = Button(
            (306, 618, 160, 40),
            "Назад",
            app.font_body,
            app.manager.pop,
        )
        self.start_button = Button(
            (978, 618, 232, 40),
            "Начать кампанию",
            app.font_body,
            self.start,
        )
        self.buttons = [
            self.prev_button,
            self.next_button,
            self.random_name_button,
            self.random_button,
            self.back_button,
            self.start_button,
        ]
        storyline_name = (storyline or {}).get("title", "")
        logger.info(
            "Редактор личности: сюжет=%s, фракция=%s, вариантов=%d",
            storyline_name or "—",
            faction_id or "по роли",
            len(self.catalog.origins) if self.catalog else 0,
        )

    # ------------------------------------------------------------------
    # Варианты
    # ------------------------------------------------------------------
    def _ids(self, section):
        if self.catalog is None:
            return ()
        if section == "trait":
            return tuple(self.catalog.trait_order)
        table = getattr(self.catalog, SECTION_TABLE[section], {})
        return tuple(table)

    def _option(self, section):
        if self.catalog is None:
            return None
        key = self.values.get(section)
        if section == "trait":
            key = key if key in self.catalog.trait_order else (
                self.catalog.trait_order[0]
            )
            return {
                "id": key,
                "label": self.catalog.trait_label(key),
                "summary": self.catalog.trait_summaries.get(key, ""),
                "text": "Главная черта задаёт ваш способ держать удар и "
                "принимать решения.",
                "needs": {},
                "traits": {key: 0.22},
            }
        table = getattr(self.catalog, SECTION_TABLE[section], {})
        option = table.get(str(key))
        if option is None:
            return None
        return {
            "id": option.id,
            "label": option.label,
            "summary": option.summary,
            "text": option.text,
            "needs": dict(option.needs),
            "traits": dict(option.traits),
        }

    def select_section(self, section):
        if section not in SECTION_ORDER:
            return
        self.selected_section = section
        logger.debug("Раздел личности: %s", section)

    def cycle(self, section, step=1):
        ids = self._ids(section)
        if not ids:
            return
        current = self.values.get(section)
        index = ids.index(current) if current in ids else 0
        self.values[section] = ids[(index + int(step)) % len(ids)]
        self.message = ""

    def _name_policy_key(self):
        if self.faction_id:
            return self.faction_id
        return (self.storyline or {}).get("storyline_id")

    def _name_gender(self):
        return {
            "male": "m",
            "female": "f",
        }.get(str(self.values.get("gender")))

    def random_name(self):
        try:
            generator = PersonNameGenerator(
                seed=random.randrange(1, 10 ** 6)
            )
            policy = generator.policy(self._name_policy_key())
            self.name = generator.generate(
                policy=policy, gender=self._name_gender()
            ).full
        except Exception as exc:
            logger.warning("Не удалось собрать случайное имя: %s", exc)
            self.name = "Новый правитель"
        self.name_focus = False

    def randomize(self):
        for section in SECTION_ORDER:
            ids = self._ids(section)
            if ids:
                self.values[section] = random.choice(ids)
        self.random_name()
        self.message = ""

    # ------------------------------------------------------------------
    # Сборка и запуск
    # ------------------------------------------------------------------
    def build_identity(self):
        if self.catalog is None:
            return {}
        data = dict(self.values)
        data["name"] = self.name.strip()
        return self.catalog.build(data)

    def start(self):
        if self.started:
            return
        identity = self.build_identity()
        if not identity:
            self.message = (
                self.message or "Личность недоступна: проверьте конфиг."
            )
            return
        self.started = True
        logger.info(
            "Личность героя собрана: %s (%s)",
            identity.get("name"),
            identity.get("summary"),
        )
        if self.on_start is not None:
            self.on_start(identity)
            return
        if self.storyline is None:
            self.message = "Сюжет не выбран."
            self.started = False
            return
        self.app.start_storyline(
            self.storyline,
            faction_id=self.faction_id,
            player_identity=identity,
        )

    # ------------------------------------------------------------------
    # Ввод
    # ------------------------------------------------------------------
    def _category_rect(self, index):
        return pygame.Rect(
            CATEGORY_RECT.x,
            CATEGORY_RECT.y + index * CATEGORY_GAP,
            CATEGORY_RECT.width,
            CATEGORY_RECT.height,
        )

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                if self.name_focus:
                    self.name = self.name[:-1]
                return
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.start()
                return
            if event.key in (pygame.K_TAB, pygame.K_ESCAPE):
                return
            if getattr(event, "unicode", ""):
                char = event.unicode
                if char.isprintable() and len(self.name) < 36:
                    self.name += char
                return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            if NAME_RECT.collidepoint(pos):
                self.name_focus = True
                return
            for index, section in enumerate(SECTION_ORDER):
                if self._category_rect(index).collidepoint(pos):
                    self.select_section(section)
                    return
            self.name_focus = False
        for button in self.buttons:
            if button.handle_event(event):
                return

    # ------------------------------------------------------------------
    # Отрисовка
    # ------------------------------------------------------------------
    def _draw_name(self, screen):
        label = self.app.font_small.render("Имя героя", True, MUTED)
        screen.blit(label, (70, NAME_RECT.y + 12))
        pygame.draw.rect(screen, (18, 22, 32), NAME_RECT, border_radius=6)
        pygame.draw.rect(
            screen,
            ACCENT if self.name_focus else (60, 74, 96),
            NAME_RECT,
            2,
            border_radius=6,
        )
        if self.name:
            surf = self.app.font_body.render(self.name, True, TEXT)
            screen.blit(
                surf,
                (
                    NAME_RECT.x + 12,
                    NAME_RECT.centery - surf.get_height() // 2,
                ),
            )
        else:
            hint = self.app.font_small.render(
                "Введите имя...", True, DIM
            )
            screen.blit(
                hint,
                (
                    NAME_RECT.x + 12,
                    NAME_RECT.centery - hint.get_height() // 2,
                ),
            )
        if self.name_focus and (pygame.time.get_ticks() // 500) % 2 == 0:
            width = min(self.app.font_body.size(self.name)[0], NAME_RECT.width - 28)
            x = NAME_RECT.x + 12 + width + 2
            pygame.draw.line(
                screen,
                (180, 210, 240),
                (x, NAME_RECT.y + 10),
                (x, NAME_RECT.bottom - 10),
                2,
            )

    def _draw_categories(self, screen):
        for index, section in enumerate(SECTION_ORDER):
            rect = self._category_rect(index)
            selected = section == self.selected_section
            pygame.draw.rect(
                screen,
                (34, 48, 68) if selected else (24, 30, 43),
                rect,
                border_radius=6,
            )
            pygame.draw.rect(
                screen,
                ACCENT if selected else (58, 70, 92),
                rect,
                2,
                border_radius=6,
            )
            screen.blit(
                self.app.font_tiny.render(
                    SECTION_LABELS[section], True, MUTED
                ),
                (rect.x + 10, rect.y + 6),
            )
            option = self._option(section)
            value = option["label"] if option else "—"
            lines = wrap_text(self.app.font_small, value, rect.width - 20)
            screen.blit(
                self.app.font_small.render(
                    lines[0] if lines else "—",
                    True,
                    TEXT if selected else (205, 210, 220),
                ),
                (rect.x + 10, rect.y + 23),
            )

    def _effect_lines(self, option):
        labels = []
        needs = option.get("needs") or {}
        if needs:
            labels.append(
                "Потребности: "
                + ", ".join(
                    "%s %s" % (W.NEEDS_RU.get(key, key), _signed(value))
                    for key, value in sorted(needs.items())
                )
            )
        traits = option.get("traits") or {}
        if traits:
            labels.append(
                "Черты: "
                + ", ".join(
                    "%s %s" % (self.catalog.trait_label(key), _signed(value))
                    for key, value in sorted(traits.items())
                )
            )
        return labels

    def _draw_preview(self, screen):
        pygame.draw.rect(screen, (16, 21, 31), PREVIEW_RECT, border_radius=8)
        pygame.draw.rect(
            screen, (58, 70, 92), PREVIEW_RECT, 2, border_radius=8
        )
        option = self._option(self.selected_section)
        header = self.app.font_small.render(
            SECTION_LABELS[self.selected_section].upper(), True, MUTED
        )
        screen.blit(header, (PREVIEW_RECT.x + 18, PREVIEW_RECT.y + 14))
        if option is None:
            return
        x = PREVIEW_RECT.x + 18
        width = PREVIEW_RECT.width - 36
        screen.blit(
            self.app.font_body.render(option["label"], True, TEXT),
            (x, PREVIEW_RECT.y + 42),
        )
        summary_rect = pygame.Rect(x, PREVIEW_RECT.y + 76, width, 40)
        draw_fitted(
            screen,
            [self.app.font_small, self.app.font_tiny],
            option.get("summary") or "",
            summary_rect,
            (190, 204, 224),
        )
        text_rect = pygame.Rect(x, PREVIEW_RECT.y + 124, width, 170)
        draw_fitted(
            screen,
            [
                self.app.font_body,
                self.app.font_small,
                self.app.font_tiny,
            ],
            option.get("text") or "",
            text_rect,
            TEXT,
        )
        if self.selected_section == "trait":
            effect_y = PREVIEW_RECT.y + 310
            screen.blit(
                self.app.font_tiny.render(
                    "Черта усиливается на +0.22 к базовому значению.",
                    True,
                    GOOD,
                ),
                (x, effect_y),
            )
            return
        y = PREVIEW_RECT.y + 310
        for line in self._effect_lines(option):
            for wrapped in wrap_text(
                self.app.font_tiny, line, width
            )[:2]:
                screen.blit(
                    self.app.font_tiny.render(wrapped, True, GOOD),
                    (x, y),
                )
                y += line_height(self.app.font_tiny, 1.15)

    def draw(self, screen):
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 170))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        title = self.app.font_title.render(
            "Личность героя", True, (224, 228, 236)
        )
        screen.blit(title, (70, 54))
        subtitle_text = (self.storyline or {}).get("title") or (
            "Кем вы входите в кампанию"
        )
        screen.blit(
            self.app.font_small.render(subtitle_text, True, MUTED),
            (70, 94),
        )
        self._draw_name(screen)
        self._draw_categories(screen)
        self._draw_preview(screen)
        for button in self.buttons:
            button.draw(screen)
        if self.message:
            for index, line in enumerate(
                wrap_text(self.app.font_tiny, self.message, 620)[:2]
            ):
                screen.blit(
                    self.app.font_tiny.render(line, True, (230, 150, 120)),
                    (70, 668 + index * 15),
                )


__all__ = [
    "IdentityEditorScreen",
    "SECTION_LABELS",
    "SECTION_ORDER",
    "SECTION_TABLE",
]
