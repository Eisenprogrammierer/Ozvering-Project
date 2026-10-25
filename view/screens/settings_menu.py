"""
view/screens/settings_menu.py

Экран настроек игры.

Отображает переключаемые параметры (звук, полный экран, анимации боя)
в виде кнопок с текущим состоянием. Каждое переключение перестраивает
список кнопок. Кнопка «Назад» закрывает экран.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль.
"""

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.settings_menu")


class SettingsMenuScreen(BaseScreen):
    """
    Экран настроек.

    Хранит словарь настроек и список кнопок. Каждое переключение
    значения перестраивает список кнопок для отображения нового
    состояния.

    Attributes:
        panel (Panel): Фоновая панель экрана.
        settings (dict): Словарь настроек вида {имя: bool}.
        buttons (list[Button]): Кнопки параметров и кнопка «Назад».
    """

    def __init__(self, app):
        """
        Инициализирует экран настроек.

        Создаёт фоновую панель, задаёт начальные значения настроек
        и строит список кнопок.

        Args:
            app: Экземпляр приложения (App).
        """
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
        """
        Перестраивает список кнопок по текущим значениям настроек.

        Для каждой настройки создаётся кнопка с текстом
        «Имя: вкл» или «Имя: выкл». В конце добавляется кнопка «Назад».
        """
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
        """
        Переключает значение указанной настройки на противоположное.

        После переключения перестраивает список кнопок.

        Args:
            name (str): Имя настройки для переключения.
        """
        self.settings[name] = not self.settings[name]
        logger.info(
            "Настройка переключена: %s -> %s",
            name,
            "вкл" if self.settings[name] else "выкл",
        )
        self._rebuild()

    def handle_event(self, event):
        """
        Обрабатывает события pygame для данного экрана.

        Событие последовательно передаётся всем кнопкам настроек.
        Если одна из кнопок обработала событие, дальнейшая обработка
        прекращается.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        """
        Отрисовывает экран настроек.

        Порядок отрисовки:
        1. Фоновая панель.
        2. Заголовок «Настройки».
        3. Кнопки параметров и кнопка «Назад».

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        self.panel.draw(screen)
        title = self.app.font_body.render(
            "Настройки", True, (220, 220, 230)
        )
        screen.blit(title, title.get_rect(center=(640, 145)))
        for b in self.buttons:
            b.draw(screen)