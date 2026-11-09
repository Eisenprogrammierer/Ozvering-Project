import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import draw_fitted
from ..ui.widgets import Button, Panel
from view.support.storyline import list_storylines
from view.support.log_journal import get_logger

logger = get_logger("view.storyline_select")

MAX_VISIBLE_STORYLINES = 5
TEXT = (224, 229, 238)
MUTED = (150, 162, 180)
DIM = (108, 120, 138)
ACCENT = (80, 150, 220)

LIST_X = 80
LIST_Y = 180
LIST_W = 330
ROW_H = 58
ROW_GAP = 68
PREVIEW_RECT = (440, 160, 750, 420)


class StorylineSelectScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((60, 60, 1160, 600))
        self.role = getattr(app, "selected_role", None)
        storylines = list_storylines()[:MAX_VISIBLE_STORYLINES]
        self.storylines = storylines
        self.empty = not storylines
        self.selected_id = (
            storylines[0]["storyline_id"] if storylines else None
        )
        self.buttons = []
        for index, entry in enumerate(storylines):
            self.buttons.append(
                Button(
                    (
                        LIST_X,
                        LIST_Y + index * ROW_GAP,
                        LIST_W,
                        ROW_H,
                    ),
                    entry["title"],
                    app.font_body,
                    lambda sid=entry["storyline_id"]: self.select(sid),
                )
            )
        self.continue_button = Button(
            (1010, 610, 190, 40),
            "Продолжить",
            app.font_body,
            self.continue_to_storyline,
        )
        self.back_button = Button(
            (80, 610, 160, 40),
            "Назад",
            app.font_body,
            app.manager.pop,
        )
        self.buttons.extend((self.continue_button, self.back_button))
        logger.info(
            "Экран выбора сюжета: доступно сюжетов=%d, роль=%s",
            len(storylines),
            getattr(self.role, "id", "—"),
        )

    @property
    def current_entry(self):
        if self.selected_id is None:
            return None
        return next(
            (
                entry
                for entry in self.storylines
                if entry["storyline_id"] == self.selected_id
            ),
            None,
        )

    def select(self, storyline_id):
        if not any(
            entry["storyline_id"] == storyline_id
            for entry in self.storylines
        ):
            return
        self.selected_id = storyline_id
        logger.info("Выбран сюжет (предпросмотр): %s", storyline_id)

    def continue_to_storyline(self):
        from view.support.storyline import load_storyline

        if self.selected_id is None:
            return
        logger.info("Подтверждён сюжет: %s", self.selected_id)
        storyline = load_storyline(self.selected_id)
        if storyline is None:
            logger.warning("Сюжет не загружен: %s", self.selected_id)
            return
        if storyline.get("identity_editor"):
            from .identity_editor import IdentityEditorScreen

            self.app.manager.push(
                IdentityEditorScreen(self.app, storyline)
            )
            return
        logger.info("Сюжет запущен: %s", self.selected_id)
        self.app.start_storyline(storyline)

    def handle_event(self, event):
        for button in self.buttons:
            if button.handle_event(event):
                return

    def _draw_preview(self, screen):
        x, y, width, height = PREVIEW_RECT
        pygame.draw.rect(
            screen,
            (16, 21, 31),
            (x, y, width, height),
            border_radius=8,
        )
        pygame.draw.rect(
            screen, (58, 70, 92), (x, y, width, height), 2, border_radius=8
        )
        entry = self.current_entry
        if entry is None:
            return
        screen.blit(
            self.app.font_small.render("СЮЖЕТ", True, MUTED),
            (x + 20, y + 16),
        )
        screen.blit(
            self.app.font_body.render(entry["title"], True, TEXT),
            (x + 20, y + 42),
        )
        draw_fitted(
            screen,
            [
                self.app.font_body,
                self.app.font_small,
                self.app.font_tiny,
            ],
            entry.get("description") or "Описание не задано.",
            (x + 20, y + 84, width - 40, height - 130),
            TEXT,
        )
        screen.blit(
            self.app.font_tiny.render(
                "Сюжет: %s" % entry["storyline_id"], True, DIM
            ),
            (x + 20, y + height - 30),
        )

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_title.render(
            "Выбор сюжета", True, (220, 220, 230)
        )
        screen.blit(title, title.get_rect(center=(640, 94)))
        if self.role is not None:
            role_line = self.app.font_small.render(
                "Роль: %s" % self.role.label, True, ACCENT
            )
            screen.blit(role_line, role_line.get_rect(center=(640, 128)))
        if self.empty:
            msg = self.app.font_small.render(
                "Пока пусто", True, (150, 150, 160)
            )
            screen.blit(msg, msg.get_rect(center=(640, 350)))
        for index, entry in enumerate(self.storylines):
            rect = pygame.Rect(
                LIST_X,
                LIST_Y + index * ROW_GAP,
                LIST_W,
                ROW_H,
            )
            selected = entry["storyline_id"] == self.selected_id
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
            lines = entry["title"].split("\n")
            screen.blit(
                self.app.font_small.render(
                    lines[0][:40], True, TEXT
                ),
                (rect.x + 12, rect.y + 18),
            )
        self._draw_preview(screen)
        self.back_button.draw(screen)
        self.continue_button.draw(screen)


__all__ = ["StorylineSelectScreen", "MAX_VISIBLE_STORYLINES"]
