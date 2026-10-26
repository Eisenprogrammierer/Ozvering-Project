"""
view/screens/storyline_select.py

Экран выбора сюжета.

Сканирует директорию configs/storylines/ через list_storylines,
отображает выбранную роль, список доступных сюжетов с названиями и
кнопку «Назад». При выборе сюжета загружает его конфигурацию и запускает
процесс создания персонажа через app.start_storyline; тот же вызов
генерирует кампанийный пресет по роли.

События сканирования и выбора сюжета записываются в журнал
operation_ozverin.log в корне проекта и дублируются в консоль.
"""

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.storyline import list_storylines
from view.support.log_journal import get_logger

logger = get_logger("view.storyline_select")

MAX_VISIBLE_STORYLINES = 5


class StorylineSelectScreen(BaseScreen):
    """
    Экран выбора сюжета.

    Отображает фоновую панель, заголовок, до пяти кнопок сюжетов
    и кнопку «Назад». При отсутствии сюжетов показывает сообщение
    «Пока пусто».

    Attributes:
        panel (Panel): Фоновая панель экрана.
        buttons (list[Button]): Кнопки списка сюжетов и кнопка «Назад».
        empty (bool): Флаг отсутствия доступных сюжетов.
    """

    def __init__(self, app):
        """
        Инициализирует экран выбора сюжета.

        Сканирует доступные сюжеты, создаёт кнопки для первых пяти
        записей и кнопку «Назад».

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app)
        self.panel = Panel((290, 70, 700, 580))
        self.buttons = []
        storylines = list_storylines()
        self.empty = not storylines
        self.role = getattr(app, "selected_role", None)
        logger.info(
            "Экран выбора сюжета: доступно сюжетов=%d, роль=%s",
            len(storylines), getattr(self.role, "id", "—"),
        )
        y = 170
        for entry in storylines[:MAX_VISIBLE_STORYLINES]:
            label = entry["title"]
            self.buttons.append(
                Button(
                    (340, y, 600, 60),
                    label,
                    app.font_body,
                    lambda sid=entry["storyline_id"]: self.select(sid),
                )
            )
            y += 70
        self.buttons.append(
            Button(
                (540, 600, 200, 40),
                "Назад",
                app.font_body,
                app.manager.pop,
            )
        )

    def select(self, storyline_id):
        """
        Обрабатывает выбор сюжета.

        Загружает конфигурацию сюжета по идентификатору и запускает
        процесс создания персонажа. Если конфигурация не загружена,
        запуск не выполняется.

        Args:
            storyline_id (str): Идентификатор выбранного сюжета.
        """
        from view.support.storyline import load_storyline

        logger.info("Выбран сюжет: %s", storyline_id)
        storyline = load_storyline(storyline_id)
        if storyline is None:
            logger.warning("Сюжет не загружен: %s", storyline_id)
            return
        logger.info("Сюжет запущен: %s", storyline_id)
        self.app.start_storyline(storyline)

    def handle_event(self, event):
        """
        Обрабатывает события pygame для данного экрана.

        Событие последовательно передаётся всем кнопкам.
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
        Отрисовывает экран выбора сюжета.

        Порядок отрисовки:
        1. Фоновая панель.
        2. Заголовок «Выбор сюжета».
        3. Если сюжетов нет — сообщение «Пока пусто».
        4. Кнопки списка сюжетов и кнопка «Назад».

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        self.panel.draw(screen)
        title = self.app.font_title.render(
            "Выбор сюжета", True, (220, 220, 230)
        )
        screen.blit(title, title.get_rect(center=(640, 110)))
        if self.role is not None:
            role_line = self.app.font_small.render(
                "Роль: %s" % self.role.label, True, (130, 165, 215)
            )
            screen.blit(role_line, role_line.get_rect(center=(640, 142)))
        if self.empty:
            msg = self.app.font_small.render(
                "Пока пусто", True, (150, 150, 160)
            )
            screen.blit(msg, msg.get_rect(center=(640, 350)))
        for b in self.buttons:
            b.draw(screen)