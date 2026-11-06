import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.text_layout import draw_fitted
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.role_select")

MAX_VISIBLE_ROLES = 4
BUTTON_WIDTH = 330
BUTTON_HEIGHT = 54
ROW_GAP = 66
FIRST_ROW_Y = 172
LIST_X = 90
PREVIEW_RECT = (460, 160, 730, 420)
TEXT = (224, 229, 238)
MUTED = (150, 162, 180)
DIM = (108, 120, 138)
ACCENT = (80, 150, 220)


def _mode_text(role):
    return "%s · %s" % (
        {
            "nominal": "гражданский мандат",
            "civilian_mandate": "гражданский мандат",
            "official": "должностное лицо",
        }.get(role.leadership, role.leadership),
        {
            "coalition": "коалиция",
            "automaton": "автомат",
        }.get(role.faction_kind, role.faction_kind),
    )


class RoleSelectScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((60, 60, 1160, 600))
        self.buttons = []
        catalog = getattr(app, "role_catalog", None)
        self.roles = [] if catalog is None else [
            role
            for role in catalog.available_roles()
            if "legacy" not in role.tags
        ]
        self.roles = self.roles[:MAX_VISIBLE_ROLES]
        self.empty = not self.roles
        self.selected_id = self.roles[0].id if self.roles else None
        logger.info(
            "Экран выбора роли: доступно ролей=%d",
            len(self.roles),
        )
        for index, role in enumerate(self.roles):
            self.buttons.append(
                Button(
                    (
                        LIST_X,
                        FIRST_ROW_Y + index * ROW_GAP,
                        BUTTON_WIDTH,
                        BUTTON_HEIGHT,
                    ),
                    role.label,
                    app.font_body,
                    lambda rid=role.id: self.select(rid),
                )
            )
        self.continue_button = Button(
            (1010, 610, 190, 40),
            "Продолжить",
            app.font_body,
            self.continue_to_storyline,
        )
        self.back_button = Button(
            (90, 610, 160, 40),
            "Назад",
            app.font_body,
            app.manager.pop,
        )
        self.buttons.extend((self.continue_button, self.back_button))

    @property
    def current_role(self):
        if self.selected_id is None:
            return None
        return next(
            (
                role
                for role in self.roles
                if role.id == self.selected_id
            ),
            None,
        )

    def select(self, role_id):
        if self.app.role_catalog is None:
            logger.warning("Выбор роли недоступен: каталог пуст")
            return
        try:
            role = self.app.role_catalog.select(role_id)
        except Exception as exc:
            logger.error("Роль %s недоступна: %s", role_id, exc)
            return
        self.selected_id = role.id
        logger.info("Выбрана роль (предпросмотр): %s (%s)", role.id, role.label)

    def continue_to_storyline(self):
        role = self.current_role
        if role is None:
            logger.warning("Продолжение невозможно: роль не выбрана")
            return
        self.app.selected_role = role
        self.app.selected_faction_id = None
        self.app.campaign_preset = None
        logger.info("Подтверждена роль: %s (%s)", role.id, role.label)
        if role.storyline_id:
            from view.support.storyline import load_storyline

            storyline = load_storyline(role.storyline_id)
            if storyline is None:
                logger.error(
                    "Сюжет роли не найден: %s (роль %s)",
                    role.storyline_id,
                    role.id,
                )
                return
            if storyline.get("identity_editor"):
                from .identity_editor import IdentityEditorScreen

                self.app.manager.push(
                    IdentityEditorScreen(self.app, storyline)
                )
                return
            self.app.start_storyline(storyline)
            return
        if role.faction_choice:
            from .faction_select import FactionSelectScreen

            self.app.manager.push(FactionSelectScreen(self.app))
            return
        from .storyline_select import StorylineSelectScreen

        self.app.manager.push(StorylineSelectScreen(self.app))

    def handle_event(self, event):
        for button in self.buttons:
            if button.handle_event(event):
                return

    def _draw_preview(self, screen):
        x, y, width, height = PREVIEW_RECT
        pygame.draw.rect(screen, (16, 21, 31), (x, y, width, height), border_radius=8)
        pygame.draw.rect(
            screen, (58, 70, 92), (x, y, width, height), 2, border_radius=8
        )
        role = self.current_role
        if role is None:
            return
        screen.blit(
            self.app.font_small.render("РОЛЬ", True, MUTED), (x + 20, y + 16)
        )
        screen.blit(
            self.app.font_body.render(role.label, True, TEXT),
            (x + 20, y + 42),
        )
        screen.blit(
            self.app.font_tiny.render(_mode_text(role), True, ACCENT),
            (x + 20, y + 70),
        )
        # Полное описание без обрезки: шрифт уменьшается, пока текст не
        # поместится в отведённую область.
        draw_fitted(
            screen,
            [
                self.app.font_body,
                self.app.font_small,
                self.app.font_tiny,
            ],
            role.description,
            (x + 20, y + 104, width - 40, height - 150),
            TEXT,
        )
        if role.tags:
            screen.blit(
                self.app.font_tiny.render(
                    "Теги: %s" % ", ".join(role.tags), True, DIM
                ),
                (x + 20, y + height - 30),
            )

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_title.render("Выбор роли", True, (220, 220, 230))
        screen.blit(title, title.get_rect(center=(640, 94)))
        subtitle = self.app.font_small.render(
            "Кем вы входите в кампанию? Описание роли показано полностью.",
            True,
            MUTED,
        )
        screen.blit(subtitle, subtitle.get_rect(center=(640, 128)))
        if self.empty:
            msg = self.app.font_small.render(
                "Пока нет доступных ролей", True, (150, 150, 160)
            )
            screen.blit(msg, msg.get_rect(center=(640, 350)))
        for index, role in enumerate(self.roles):
            button = self.buttons[index]
            button.draw(screen)
            if role.id == self.selected_id:
                pygame.draw.rect(
                    screen,
                    ACCENT,
                    button.rect.inflate(6, 6),
                    2,
                    border_radius=8,
                )
        self._draw_preview(screen)
        note = self.app.font_tiny.render(
            "Каталог ролей: configs/roles/*.json", True, DIM
        )
        screen.blit(note, note.get_rect(center=(640, 660)))
        self.back_button.draw(screen)
        self.continue_button.draw(screen)


__all__ = ["RoleSelectScreen", "MAX_VISIBLE_ROLES"]
