"""
view/screens/saves_menu.py

Экран меню сохранений.

Отображает список доступных файлов сохранений из директории saves,
отсортированный по имени, не более MAX_VISIBLE_SAVES записей.
Позволяет выбрать сохранение для загрузки, создать новое сохранение
и удалить существующее. При отсутствии сохранений отображает
сообщение «Пока пусто».

Операции меню фиксируются в журнале operation_ozverin.log в корне
проекта и дублируются в консоль.
"""

import os

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.save_system import list_saves, delete_save
from view.support.log_journal import get_logger

logger = get_logger("view.saves_menu")

SAVES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "saves")
)
MAX_VISIBLE_SAVES = 7


class SavesMenuScreen(BaseScreen):
    """
    Экран меню сохранений.

    Строит фоновую панель, кнопки списка сохранений (не более
    MAX_VISIBLE_SAVES), кнопки удаления для каждой записи, кнопку
    нового сохранения и кнопку «Назад».

    Attributes:
        panel (Panel): Фоновая панель меню.
        buttons (list[Button]): Кнопки списка, удаления,
            нового сохранения и «Назад».
        empty (bool): Флаг отсутствия сохранений.
    """

    def __init__(self, app):
        """
        Инициализирует экран меню сохранений.

        Сканирует файлы сохранений через list_saves, создаёт кнопки
        для первых MAX_VISIBLE_SAVES записей, кнопки удаления,
        кнопку нового сохранения и кнопку «Назад».

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app)
        self.panel = Panel((340, 90, 600, 540))
        self.buttons = []
        saves = list_saves()
        self.empty = not saves
        logger.info("Меню сохранений открыто: сохранений=%d", len(saves))
        y = 160
        for entry in saves[:MAX_VISIBLE_SAVES]:
            label = entry["name"]
            if entry["timestamp"]:
                label = f"{entry['name']}  ({entry['timestamp'][:16]})"
            self.buttons.append(
                Button(
                    (380, y, 440, 40),
                    label,
                    app.font_small,
                    lambda n=entry["name"]: self.load(n),
                )
            )
            self.buttons.append(
                Button(
                    (830, y, 70, 40),
                    "X",
                    app.font_small,
                    lambda n=entry["name"]: self.delete(n),
                )
            )
            y += 48
        self.buttons.append(
            Button(
                (380, 530, 260, 40),
                "Новое сохранение",
                app.font_small,
                self.new_save,
            )
        )
        self.buttons.append(
            Button(
                (660, 530, 200, 40),
                "Назад",
                app.font_body,
                app.manager.pop,
            )
        )

    def load(self, name):
        """
        Обрабатывает выбор файла сохранения для загрузки.

        Вызывает app.load_game для восстановления состояния.

        Args:
            name (str): Имя выбранного файла сохранения.
        """
        logger.info("Загрузка сохранения: %s", name)
        self.app.load_game(name)

    def delete(self, name):
        """
        Обрабатывает удаление файла сохранения.

        Удаляет файл через delete_save и перестраивает экран
        для отображения обновлённого списка.

        Args:
            name (str): Имя удаляемого файла сохранения.
        """
        logger.info("Удаление сохранения: %s", name)
        delete_save(name)
        self.app.manager.pop()
        self.app.open_saves()

    def new_save(self):
        """
        Обрабатывает создание нового сохранения.

        Формирует имя слота на основе текущего игрового дня и
        времени, вызывает app.save_game и перестраивает экран.
        Если time_system отсутствует, операция не выполняется.
        """
        ts = getattr(self.app, "time_system", None)
        if ts is None:
            return
        slot_name = f"save_day{ts.day}_{ts.seconds_of_day:.0f}"
        logger.info("Создание нового сохранения: %s", slot_name)
        self.app.save_game(slot_name)
        self.app.manager.pop()
        self.app.open_saves()

    def handle_event(self, event):
        """
        Обрабатывает события pygame для данного экрана.

        Событие последовательно передаётся всем кнопкам меню.
        Если одна из кнопок обработала событие, дальнейшая
        обработка прекращается.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        """
        Отрисовывает экран меню сохранений.

        Порядок отрисовки:
        1. Фоновая панель.
        2. Заголовок «Сохранения».
        3. При отсутствии сохранений — сообщение «Пока пусто».
        4. Кнопки списка сохранений, кнопки удаления, кнопка
           нового сохранения и кнопка «Назад».

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        self.panel.draw(screen)
        title = self.app.font_body.render(
            "Сохранения", True, (220, 220, 230)
        )
        screen.blit(title, title.get_rect(center=(640, 125)))
        if self.empty:
            msg = self.app.font_small.render(
                "Пока пусто", True, (150, 150, 160)
            )
            screen.blit(msg, msg.get_rect(center=(640, 300)))
        for b in self.buttons:
            b.draw(screen)