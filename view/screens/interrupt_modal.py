"""
view/screens/interrupt_modal.py

Модальное окно прерывания.

Отображается, когда текущее действие игрока прерывается срочным событием.
Предоставляет два варианта реакции: принять прерывание или игнорировать его.
Экран не закрывается по ESC (escape_action = "none").

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль средствами core.log_journal.
"""

import pygame

from view.support.log_journal import get_logger
from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel

logger = get_logger("view.interrupt_modal")


class InterruptModal(BaseScreen):
    """
    Модальное окно срочного прерывания.

    Блокирует взаимодействие с нижележащими экранами до тех пор,
    пока игрок не примет решение. ESC отключён (escape_action = "none").

    Attributes:
        interrupt: Объект прерывания (InterruptEvent) или None.
        panel (Panel): Фоновая панель окна.
        btn_accept (Button): Кнопка принятия прерывания.
        btn_ignore (Button): Кнопка игнорирования прерывания.
    """

    escape_action = "none"

    def __init__(self, app, interrupt):
        """
        Инициализирует модальное окно прерывания.

        Создаёт панель и две кнопки: «Принять» и «Игнорировать».

        Args:
            app: Экземпляр приложения (App).
            interrupt: Объект прерывания (InterruptEvent).
                Может быть None; в этом случае draw()
                отрисует только панель без содержимого.
        """
        super().__init__(app)
        self.interrupt = interrupt
        self.panel = Panel((290, 180, 700, 360))
        self.btn_accept = Button(
            (340, 460, 260, 50),
            "Принять",
            app.font_body,
            self.accept,
        )
        self.btn_ignore = Button(
            (680, 460, 260, 50),
            "Игнорировать",
            app.font_body,
            self.ignore,
        )
        if interrupt is not None:
            logger.info(
                "Модальное прерывание открыто: id=%s title=%s priority=%s",
                getattr(interrupt, "id", "?"),
                getattr(interrupt, "title", "?"),
                getattr(interrupt, "priority", 0),
            )
        else:
            logger.info("Модальное прерывание открыто без объекта прерывания")

    def accept(self):
        """
        Обработчик принятия прерывания.

        Уведомляет time_system о принятии прерывания и закрывает окно.
        Если time_system или объект прерывания отсутствуют,
        окно закрывается без дополнительных действий.
        """
        ts = getattr(self.app, "time_system", None)
        if ts is not None and self.interrupt is not None:
            ts.accept_interrupt(self.interrupt.id)
            logger.info("Прерывание принято: id=%s", self.interrupt.id)
        self.app.manager.pop()

    def ignore(self):
        """
        Обработчик игнорирования прерывания.

        Уведомляет time_system об игнорировании прерывания и закрывает окно.
        Если time_system или объект прерывания отсутствуют,
        окно закрывается без дополнительных действий.
        """
        ts = getattr(self.app, "time_system", None)
        if ts is not None and self.interrupt is not None:
            ts.ignore_interrupt(self.interrupt.id)
            logger.info("Прерывание проигнорировано: id=%s", self.interrupt.id)
        self.app.manager.pop()

    @staticmethod
    def _wrap_text(text, font, max_width):
        """
        Разбивает текст на строки по заданной максимальной ширине.

        Args:
            text (str): Исходный текст.
            font (pygame.font.Font): Шрифт для измерения ширины.
            max_width (int): Максимальная ширина строки в пикселях.

        Returns:
            list[str]: Список строк, каждая из которых не превышает max_width.
        """
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            if font.size(test_line)[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    def handle_event(self, event):
        """
        Обрабатывает события pygame для данного экрана.

        Событие передаётся кнопкам «Принять» и «Игнорировать».
        Если одна из кнопок обработала событие, дальнейшая обработка
        прекращается.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.btn_accept.handle_event(event):
            return
        if self.btn_ignore.handle_event(event):
            return

    def draw(self, screen):
        """
        Отрисовывает модальное окно прерывания.

        Порядок отрисовки:
        1. Полупрозрачное затемнение всего экрана.
        2. Фоновая панель.
        3. Если объект прерывания отсутствует — выход.
        4. Заголовок прерывания.
        5. Текст прерывания (с переносом по ширине).
        6. Приоритет прерывания.
        7. Кнопки «Принять» и «Игнорировать».

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        if self.interrupt is None:
            return
        title_surf = self.app.font_body.render(
            self.interrupt.title, True, (255, 180, 100)
        )
        screen.blit(title_surf, (330, 210))
        y = 270
        for line in self._wrap_text(self.interrupt.text, self.app.font_small, 620):
            line_surf = self.app.font_small.render(line, True, (220, 220, 230))
            screen.blit(line_surf, (330, y))
            y += 24
        priority_text = f"Приоритет: {self.interrupt.priority}"
        priority_surf = self.app.font_small.render(
            priority_text, True, (160, 160, 180)
        )
        screen.blit(priority_surf, (330, 400))
        self.btn_accept.draw(screen)
        self.btn_ignore.draw(screen)