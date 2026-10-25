"""
view/screens/main_menu.py

Экран главного меню.

Отображает фоновое изображение, заголовок игры и кнопки навигации:
Новая игра, Продолжить, Сохранения, Настройки, Выход.
Кнопка «Продолжить» отключается, если в saves/ нет ни одного
сохранения: она не реагирует на клики и рисуется приглушённой.
ESC в главном меню намеренно отключён (escape_action = "none"),
чтобы игрок не мог случайно выйти из меню.

События экрана записываются в журнал operation_ozverin.log в корне
проекта и дублируются в консоль.
"""

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button
from ..ui.asset_loader import AssetLoader
from view.support.save_system import list_saves
from view.support.log_journal import get_logger

logger = get_logger("view.main_menu")


class MainMenuScreen(BaseScreen):
    """
    Экран главного меню игры.

    Является корневым экраном, из которого игрок может начать
    новую игру, продолжить сохранение, открыть настройки или выйти.
    ESC на данном экране игнорируется.

    Attributes:
        bg (pygame.Surface): Фоновое изображение главного меню.
        buttons (list[Button]): Список кнопок меню.
        btn_continue (Button): Кнопка «Продолжить»; отключена,
            если сохранений нет.
    """

    escape_action = "none"

    def __init__(self, app):
        """
        Инициализирует главное меню.

        Загружает фоновое изображение и создаёт пять кнопок:
        Новая игра, Продолжить, Сохранения, Настройки, Выход.
        Кнопка «Продолжить» доступна только при наличии сохранений.

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app)
        self.bg = AssetLoader.load("menus/main_menu_bg", (1280, 720))
        has_saves = bool(list_saves())
        self.btn_continue = Button(
            (500, 345, 280, 50), "Продолжить", app.font_body, app.continue_game
        )
        self.btn_continue.enabled = has_saves
        self.buttons = [
            Button((500, 280, 280, 50), "Новая игра", app.font_body, app.new_game),
            self.btn_continue,
            Button((500, 410, 280, 50), "Сохранения", app.font_body, app.open_saves),
            Button((500, 475, 280, 50), "Настройки", app.font_body, app.open_settings),
            Button((500, 540, 280, 50), "Выход", app.font_body, app.quit),
        ]
        logger.info(
            "Главное меню инициализировано: сохранений=%s",
            "есть" if has_saves else "нет",
        )

    def handle_event(self, event):
        """
        Обрабатывает события pygame для главного меню.

        Событие последовательно передаётся всем кнопкам меню.
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
        Отрисовывает главное меню.

        Порядок отрисовки:
        1. Фоновое изображение.
        2. Заголовок игры по центру верхней части экрана.
        3. Кнопки меню.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        screen.blit(self.bg, (0, 0))
        title = self.app.font_title.render("ОПЕРАЦИЯ «ОЗВЕРИН»", True, (220, 220, 230))
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