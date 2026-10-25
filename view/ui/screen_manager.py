"""
view/ui/screen_manager.py

Стек экранов с централизованной обработкой ESC через атрибут
escape_action каждого экрана.

BaseScreen — базовый класс для всех экранов и оверлеев.
ScreenManager — менеджер стека экранов, обрабатывающий события,
обновление и отрисовку.

Операции над стеком (push, pop, replace_all, обработка ESC)
записываются в журнал operation_ozverin.log в корне проекта
и дублируются в консоль.
"""

import os
import logging

LOG_FILENAME = "operation_ozverin.log"


def _build_logger(name):
    """
    Создаёт и возвращает журнал с файловым и консольным обработчиками.

    Файловый обработчик пишет в operation_ozverin.log в корне проекта
    с уровнем DEBUG, консольный — с уровнем INFO.
    Обработчики навешиваются один раз на имя журнала.

    Args:
        name (str): Имя журнала.

    Returns:
        logging.Logger: Настроенный журнал.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    log_path = os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ),
        LOG_FILENAME,
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


logger = _build_logger("view.screen_manager")


class BaseScreen:
    """
    Базовый класс для всех экранов и оверлеев.

    Каждый экран определяет поведение ESC через атрибут escape_action:
    - "pop"    — ESC закрывает экран (оверлеи, меню, диалоги);
    - "none"   — ESC игнорируется (главное меню);
    - "custom" — экран сам обрабатывает ESC в методе on_escape().

    Классовый атрибут show_time_hud управляет отрисовкой HUD
    игрового времени: HUD отображается только тогда, когда в стеке
    экранов присутствует хотя бы один экран с show_time_hud == True
    (игровые сцены), и скрывается в меню, новеллах, сюжетах
    и прочих неигровых экранах.

    Attributes:
        app: Экземпляр приложения (App).
        escape_action (str): Поведение при нажатии ESC.
        show_time_hud (bool): Флаг отображения HUD игрового времени.
    """

    escape_action = "pop"
    show_time_hud = False

    def __init__(self, app):
        """
        Инициализирует экран.

        Args:
            app: Экземпляр приложения (App).
        """
        self.app = app

    def handle_event(self, event):
        """
        Обрабатывает событие pygame.

        Вызывается ScreenManager.handle_event для текущего экрана.
        По умолчанию ничего не делает. Подклассы переопределяют
        этот метод для обработки ввода.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        pass

    def on_escape(self):
        """
        Вызывается только при escape_action == "custom".

        Позволяет экрану самостоятельно определить поведение ESC.
        По умолчанию ничего не делает. Подклассы переопределяют
        этот метод при необходимости.
        """
        pass

    def update(self, dt):
        """
        Обновляет состояние экрана.

        Вызывается ScreenManager.update каждый кадр.
        По умолчанию ничего не делает. Подклассы переопределяют
        этот метод для анимаций и логики.

        Args:
            dt (float): Время, прошедшее с последнего кадра, в секундах.
        """
        pass

    def draw(self, screen):
        """
        Отрисовывает экран на поверхности.

        Вызывается ScreenManager.draw для каждого экрана в стеке.
        По умолчанию ничего не делает. Подклассы переопределяют
        этот метод для отрисовки.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        pass


class ScreenManager:
    """
    Менеджер стека экранов.

    Управляет стеком экранов: добавление, удаление, замена.
    Обрабатывает события, обновление и отрисовку, делегируя их
    экранам в стеке. Отрисовка происходит для всех экранов в стеке,
    а события и обновление — только для текущего (верхнего) экрана.

    Attributes:
        stack (list): Стек экранов. Последний элемент — текущий экран.
    """

    def __init__(self):
        """Инициализирует менеджер с пустым стеком экранов."""
        self.stack = []

    @property
    def current(self):
        """
        Возвращает текущий (верхний) экран в стеке.

        Returns:
            BaseScreen | None: Текущий экран или None, если стек пуст.
        """
        return self.stack[-1] if self.stack else None

    def push(self, screen):
        """
        Добавляет экран на вершину стека.

        Новый экран становится текущим. Предыдущий экран остаётся
        в стеке и будет отрисован под новым.

        Args:
            screen (BaseScreen): Экран для добавления.
        """
        self.stack.append(screen)
        logger.info(
            "push: %s (глубина стека %d)",
            type(screen).__name__,
            len(self.stack),
        )

    def pop(self):
        """
        Удаляет верхний экран из стека.

        Если в стеке только один экран, он не удаляется.

        Returns:
            BaseScreen | None: Удалённый экран или None, если стек
                содержит один или ноль экранов.
        """
        if len(self.stack) > 1:
            removed = self.stack.pop()
            logger.info(
                "pop: %s (глубина стека %d)",
                type(removed).__name__,
                len(self.stack),
            )
            return removed
        logger.debug("pop: стек содержит один экран, удаление пропущено")
        return None

    def replace_all(self, screen):
        """
        Заменяет весь стек одним экраном.

        Все текущие экраны удаляются, и переданный экран становится
        единственным в стеке.

        Args:
            screen (BaseScreen): Экран, заменяющий весь стек.
        """
        self.stack = [screen]
        logger.info("replace_all: %s", type(screen).__name__)

    def handle_escape(self):
        """
        Обрабатывает нажатие ESC для текущего экрана.

        Поведение определяется атрибутом escape_action текущего экрана:
        - "none"   — ничего не происходит;
        - "custom" — вызывается метод on_escape() текущего экрана;
        - "pop"    — верхний экран удаляется из стека (если стек
          содержит более одного экрана).
        """
        current = self.current
        if current is None:
            return
        action = getattr(current, "escape_action", "pop")
        if action == "none":
            logger.debug(
                "ESC: игнорируется экраном %s", type(current).__name__
            )
            return
        if action == "custom":
            logger.info(
                "ESC: custom-обработка экраном %s", type(current).__name__
            )
            current.on_escape()
            return
        if len(self.stack) > 1:
            removed = self.stack.pop()
            logger.info(
                "ESC: pop %s (глубина стека %d)",
                type(removed).__name__,
                len(self.stack),
            )

    def handle_event(self, event):
        """
        Передаёт событие pygame текущему экрану.

        Если стек пуст, событие игнорируется.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.current:
            self.current.handle_event(event)

    def update(self, dt):
        """
        Обновляет состояние текущего экрана.

        Если стек пуст, обновление не происходит.

        Args:
            dt (float): Время, прошедшее с последнего кадра, в секундах.
        """
        if self.current:
            self.current.update(dt)

    def draw(self, screen):
        """
        Отрисовывает все экраны в стеке.

        Экраны отрисовываются в порядке от нижнего к верхнему,
        что обеспечивает корректное наложение оверлеев.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        for s in self.stack:
            s.draw(screen)

    def has_time_hud_screen(self):
        """
        Проверяет, присутствует ли в стеке экран, требующий
        отображения HUD игрового времени.

        Returns:
            bool: True, если хотя бы один экран в стеке имеет
                атрибут show_time_hud со значением True.
        """
        return any(getattr(s, "show_time_hud", False) for s in self.stack)