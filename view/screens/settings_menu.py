import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.settings_menu")


class SettingsMenuScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((340, 110, 600, 500))
        self.settings = {
            "Звук": True,
            "Полный экран": False,
            "Анимации боя": True,
        }
        self._rebuild()
        logger.info("Экран настроек инициализирован")

    def _rebuild(self):
        self.buttons = []
        y = 200
        for name, val in self.settings.items():
            label = f"{name}: {'вкл' if val else 'выкл'}"
            self.buttons.append(
                Button(
                    (400, y, 480, 45),
                    label,
                    self.app.font_body,
                    lambda n=name: self.toggle(n),
                )
            )
            y += 60
        self.buttons.append(
            Button(
                (540, 560, 200, 40),
                "Назад",
                self.app.font_body,
                self.app.manager.pop,
            )
        )

    def toggle(self, name):
        self.settings[name] = not self.settings[name]
        logger.info(
            "Настройка переключена: %s -> %s",
            name,
            "вкл" if self.settings[name] else "выкл",
        )
        self._rebuild()

    def handle_event(self, event):
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_body.render("Настройки", True, (220, 220, 230))
        screen.blit(title, title.get_rect(center=(640, 145)))
        for b in self.buttons:
            b.draw(screen)
