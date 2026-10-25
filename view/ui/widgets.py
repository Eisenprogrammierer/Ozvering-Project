"""
view/ui/widgets.py

Базовые виджеты пользовательского интерфейса: кнопки, панели, вкладки.

Используются всеми экранами и оверлеями игры. Кнопка отслеживает
наведение курсора и клик левой кнопкой мыши, поддерживает полную
непрозрачность и полупрозрачность через параметр alpha. Панель
рисует полупрозрачный фон с рамкой и служит подложкой для оверлеев.
Вкладка отображает список вкладок равной ширины и переключает
активную по клику, подсвечивая её акцентным цветом.

События взаимодействия (клики кнопок, переключение вкладок)
записываются в журнал operation_ozverin.log и дублируются в консоль.
"""

import pygame

from view.support.log_journal import get_logger

logger = get_logger("view.widgets")

COLOR_TEXT = (220, 220, 230)
COLOR_ACCENT = (80, 140, 220)
COLOR_BTN = (50, 90, 160)
COLOR_BTN_HOVER = (70, 120, 200)
COLOR_BORDER = (60, 60, 90)
COLOR_PANEL = (25, 25, 40, 230)


class Button:
    """
    Кнопка пользовательского интерфейса.

    Отслеживает наведение курсора и клик левой кнопкой мыши.
    При клике в пределах области вызывает callback и возвращает True.
    Поддерживает полную непрозрачность и полупрозрачность через
    параметр alpha. При alpha < 255 рисует полупрозрачную поверхность
    с рамкой вместо сплошного прямоугольника.

    Attributes:
        rect (pygame.Rect): Прямоугольная область кнопки.
        text (str): Текст на кнопке.
        font (pygame.font.Font): Шрифт для отрисовки текста.
        callback (callable | None): Функция, вызываемая при клике.
        alpha (int): Прозрачность кнопки (0–255).
        hovered (bool): Флаг наведения курсора на кнопку.
    """

    def __init__(self, rect, text, font, callback=None, alpha=255):
        """
        Инициализирует кнопку.

        Args:
            rect (tuple): Координаты и размеры кнопки (x, y, width, height).
            text (str): Текст на кнопке.
            font (pygame.font.Font): Шрифт для отрисовки текста.
            callback (callable | None): Функция, вызываемая при клике.
            alpha (int): Прозрачность кнопки (0–255). По умолчанию 255.
        """
        self.rect = pygame.Rect(rect)
        self.text = text
        self.font = font
        self.callback = callback
        self.alpha = alpha
        self.hovered = False

    def draw(self, screen):
        """
        Отрисовывает кнопку на экране.

        При alpha >= 255 рисует сплошной прямоугольник с подсветкой
        при наведении. При alpha < 255 рисует полупрозрачную
        поверхность с рамкой. Текст центрируется внутри кнопки.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        if self.alpha >= 255:
            color = COLOR_BTN_HOVER if self.hovered else COLOR_BTN
            pygame.draw.rect(screen, color, self.rect, border_radius=6)
        else:
            surf = pygame.Surface(self.rect.size, pygame.SRCALPHA)
            fill = (70, 120, 200, 160) if self.hovered else (20, 20, 30, 110)
            surf.fill(fill)
            screen.blit(surf, self.rect.topleft)
        pygame.draw.rect(screen, COLOR_BORDER, self.rect, 2, border_radius=6)
        surf = self.font.render(self.text, True, COLOR_TEXT)
        # Длинная подпись не должна вылезать за кнопку и перекрывать соседние
        # элементы. Если текста слишком много, аккуратно уменьшаем его.
        max_w = max(1, self.rect.width - 12)
        max_h = max(1, self.rect.height - 6)
        if surf.get_width() > max_w or surf.get_height() > max_h:
            scale = min(max_w / max(1, surf.get_width()),
                        max_h / max(1, surf.get_height()), 1.0)
            surf = pygame.transform.smoothscale(
                surf, (max(1, int(surf.get_width() * scale)),
                       max(1, int(surf.get_height() * scale)))
            )
        screen.blit(surf, surf.get_rect(center=self.rect.center))

    def handle_event(self, event):
        """
        Обрабатывает события pygame для кнопки.

        Отслеживает наведение курсора (MOUSEMOTION) и клик левой
        кнопкой мыши (MOUSEBUTTONDOWN). При клике в пределах области
        вызывает callback и возвращает True, иначе False.

        Args:
            event (pygame.event.Event): Событие pygame.

        Returns:
            bool: True, если клик был обработан, иначе False.
        """
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos) and self.callback:
                logger.info("Клик по кнопке: %s", self.text)
                self.callback()
                return True
        return False


class Panel:
    """
    Панель с полупрозрачным фоном и рамкой.

    Служит фоновой подложкой для оверлеев и экранов. Рисует
    полупрозрачный прямоугольник с закруглённой рамкой.

    Attributes:
        rect (pygame.Rect): Прямоугольная область панели.
    """

    def __init__(self, rect):
        """
        Инициализирует панель.

        Args:
            rect (tuple): Координаты и размеры панели (x, y, width, height).
        """
        self.rect = pygame.Rect(rect)

    def draw(self, screen):
        """
        Отрисовывает панель на экране.

        Рисует полупрозрачный фон и рамку по границам панели
        с закруглением 8 пикселей.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        surf = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        surf.fill(COLOR_PANEL)
        screen.blit(surf, self.rect.topleft)
        pygame.draw.rect(screen, COLOR_BORDER, self.rect, 2, border_radius=8)


class TabBar:
    """
    Панель вкладок.

    Отображает список вкладок равной ширины и переключает активную
    по клику. Активная вкладка подсвечивается акцентным цветом,
    неактивные — стандартным цветом кнопки.

    Attributes:
        rect (pygame.Rect): Прямоугольная область панели вкладок.
        tabs (list[str]): Список названий вкладок.
        font (pygame.font.Font): Шрифт для отрисовки текста вкладок.
        active (int): Индекс активной вкладки.
    """

    def __init__(self, rect, tabs, font, active=0):
        """
        Инициализирует панель вкладок.

        Args:
            rect (tuple): Координаты и размеры панели (x, y, width, height).
            tabs (list[str]): Список названий вкладок.
            font (pygame.font.Font): Шрифт для отрисовки текста.
            active (int): Индекс активной вкладки по умолчанию.
        """
        self.rect = pygame.Rect(rect)
        self.tabs = tabs
        self.font = font
        self.active = active

    def draw(self, screen):
        """
        Отрисовывает панель вкладок на экране.

        Каждая вкладка занимает равную долю ширины панели.
        Активная вкладка подсвечивается акцентным цветом,
        текст центрируется внутри каждой вкладки.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        w = self.rect.width // len(self.tabs)
        for i, name in enumerate(self.tabs):
            r = pygame.Rect(self.rect.x + i * w, self.rect.y, w, self.rect.height)
            color = COLOR_ACCENT if i == self.active else COLOR_BTN
            pygame.draw.rect(screen, color, r, border_radius=4)
            surf = self.font.render(name, True, COLOR_TEXT)
            screen.blit(surf, surf.get_rect(center=r.center))

    def handle_event(self, event):
        """
        Обрабатывает события pygame для панели вкладок.

        При клике левой кнопкой мыши определяет вкладку под курсором
        и устанавливает её активной. Логирует переключение.

        Args:
            event (pygame.event.Event): Событие pygame.

        Returns:
            bool: True, если клик по вкладке был обработан, иначе False.
        """
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            w = self.rect.width // len(self.tabs)
            for i in range(len(self.tabs)):
                r = pygame.Rect(
                    self.rect.x + i * w, self.rect.y, w, self.rect.height
                )
                if r.collidepoint(event.pos):
                    self.active = i
                    logger.info("Переключена вкладка: %s", self.tabs[i])
                    return True
        return False