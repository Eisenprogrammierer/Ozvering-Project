import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button
from ..ui.asset_loader import AssetLoader
from view.support.save_system import list_saves
from view.support.log_journal import get_logger

logger = get_logger("view.main_menu")


class MainMenuScreen(BaseScreen):

    escape_action = "none"

    def __init__(self, app):
        super().__init__(app)
        self.bg = AssetLoader.load("menus/main_menu_bg", (1280, 720))
        has_saves = bool(list_saves())
        self.btn_continue = Button(
            (500, 345, 280, 50), "Продолжить", app.font_body, app.continue_game
        )
        self.btn_continue.enabled = has_saves
        self.buttons = [
            Button(
                (500, 280, 280, 50), "Новая игра", app.font_body, app.new_game
            ),
            self.btn_continue,
            Button(
                (500, 410, 280, 50),
                "Сохранения",
                app.font_body,
                app.open_saves,
            ),
            Button(
                (500, 475, 280, 50),
                "Настройки",
                app.font_body,
                app.open_settings,
            ),
            Button((500, 540, 280, 50), "Выход", app.font_body, app.quit),
        ]
        logger.info(
            "Главное меню инициализировано: сохранений=%s",
            "есть" if has_saves else "нет",
        )

    def handle_event(self, event):
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        screen.blit(self.bg, (0, 0))
        title = self.app.font_title.render(
            "ОПЕРАЦИЯ «ОЗВЕРИН»", True, (220, 220, 230)
        )
        screen.blit(title, title.get_rect(center=(640, 170)))
        for b in self.buttons:
            b.draw(screen)
        credit = self.app.font_tiny.render(
            "Music by Kevin MacLeod", True, (150, 145, 135)
        )
        credit.set_alpha(165)
        rect = credit.get_rect(
            bottomright=(screen.get_width() - 16, screen.get_height() - 12)
        )
        screen.blit(credit, rect)
