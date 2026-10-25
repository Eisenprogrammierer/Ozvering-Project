"""
view/screens/dialogue.py

Экран диалога.

Отображает диалоговый узел из контентной конфигурации
(app.content.dialogues): имя говорящего, текст и список вариантов
выбора. Выбор применяет эффект через EffectInterpreter, переходит
к следующему узлу диалога или закрывает экран и расходует игровое
время через действие dialogue_choice. События узла и выбора
записываются в журнал operation_ozverin.log и дублируются в консоль.
"""

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from ..ui.text_layout import draw_fitted
from view.support.log_journal import get_logger

logger = get_logger("view.dialogue")


class DialogueScreen(BaseScreen):
    """
    Экран диалога.

    Загружает диалоговый узел по идентификатору из
    app.content.dialogues, отображает имя говорящего, текст и кнопки
    выбора. При выборе варианта применяется эффект (если задан),
    расходуется игровое время и происходит переход к следующему узлу
    или закрытие экрана.

    Attributes:
        node_id (str): Идентификатор текущего диалогового узла.
        speaker (str): Имя говорящего.
        text (str): Текст диалога.
        choices (list[dict]): Список вариантов выбора.
        panel (Panel): Фоновая панель диалога.
        buttons (list[Button]): Кнопки вариантов выбора.
    """

    def __init__(self, app, node_id):
        """
        Инициализирует экран диалога.

        Загружает узел диалога из app.content.dialogues по node_id,
        извлекает speaker, text и choices, создаёт кнопку для каждого
        варианта выбора. Если choices отсутствуют, создаётся дефолтная
        кнопка «Продолжить».

        Args:
            app: Экземпляр приложения (App).
            node_id (str): Идентификатор диалогового узла.
        """
        super().__init__(app)
        self.node_id = node_id
        node = app.content.dialogues[node_id]
        self.speaker = node.get("speaker", "")
        self.text = node.get("text", "")
        self.choices = node.get("choices", [{"text": "Продолжить"}])
        self.panel = Panel((140, 360, 1000, 340))
        self.buttons = []
        start_y = 540
        available = self.panel.rect.bottom - 20 - start_y
        step = min(46, max(30, available // max(1, len(self.choices))))
        height = min(42, step - 4)
        y = start_y
        for i, c in enumerate(self.choices):
            self.buttons.append(
                Button(
                    (200, y, 880, height),
                    c["text"],
                    app.font_small,
                    lambda i=i: self.choose(i),
                )
            )
            y += step
        logger.info(
            "Диалог открыт: узел=%s, говорящий=%s, вариантов=%d",
            node_id,
            self.speaker or "-",
            len(self.choices),
        )

    def choose(self, i):
        """
        Обрабатывает выбор варианта диалога.

        Применяет эффект выбора через EffectInterpreter (если задан),
        затем переходит к следующему узлу диалога (если указан next)
        или закрывает экран. После навигации расходует игровое время
        через действие dialogue_choice.

        Args:
            i (int): Индекс выбранного варианта.
        """
        choice = self.choices[i]
        from view.support.effects import EffectInterpreter

        EffectInterpreter.apply(
            self.app.engine.state, choice.get("effect", {})
        )
        next_id = choice.get("next")
        logger.info(
            "Диалог %s: выбран вариант %d (%s), переход=%s",
            self.node_id,
            i,
            choice.get("text", ""),
            next_id or "закрытие",
        )
        if next_id:
            self.app.manager.push(DialogueScreen(self.app, next_id))
        else:
            self.app.manager.pop()
        self.app.execute_player_action("dialogue_choice")

    def handle_event(self, event):
        """
        Обрабатывает события pygame для данного экрана.

        Событие последовательно передаётся всем кнопкам выбора.
        Если одна из кнопок обработала событие, дальнейшая обработка
        прекращается.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        for b in self.buttons:
            if b.handle_event(event):
                return

    def _wrap(self, text, font, max_w):
        """
        Выполняет перенос текста по заданной максимальной ширине.

        Разбивает входную строку на список строк, каждая из которых
        не превышает max_w пикселей при отрисовке заданным шрифтом.

        Args:
            text (str): Исходный текст.
            font (pygame.font.Font): Шрифт для измерения ширины.
            max_w (int): Максимальная ширина строки в пикселях.

        Returns:
            list[str]: Список перенесённых строк.
        """
        lines, line = [], ""
        for w in text.split():
            test = (line + " " + w).strip()
            if font.size(test)[0] > max_w:
                lines.append(line)
                line = w
            else:
                line = test
        lines.append(line)
        return lines

    def draw(self, screen):
        """
        Отрисовывает экран диалога.

        Порядок отрисовки:
        1. Фоновая панель.
        2. Имя говорящего.
        3. Текст диалога (не более 4 строк, с переносом по ширине).
        4. Кнопки вариантов выбора.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        self.panel.draw(screen)
        sp = self.app.font_body.render(
            self.speaker, True, (80, 140, 220)
        )
        screen.blit(sp, (180, 382))
        draw_fitted(
            screen,
            [self.app.font_body, self.app.font_small, self.app.font_tiny],
            self.text,
            pygame.Rect(180, 416, 920, 104),
            (220, 220, 230),
        )
        for b in self.buttons:
            b.draw(screen)