"""
view/screens/action_menu.py

Экран-оверлей меню выбора действий игрока.

Отображает только действия ожидания из GameTimeSystem.
Остальные действия вынесены в интерактивные предметы стола КП
и в данном меню не дублируются.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль средствами core.log_journal.
"""

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.action_menu")


class ActionMenuOverlay(BaseScreen):
    """
    Оверлей меню действий.

    Показывает исключительно действия категории wait.
    При выборе действия закрывает себя и запускает действие
    через app.execute_player_action.

    Attributes:
        panel (Panel): Фоновая панель меню.
        buttons (list[Button]): Кнопки действий и кнопка закрытия.
    """

    def __init__(self, app):
        """
        Инициализирует меню действий.

        Читает доступные действия из time_system, фильтрует по
        категории wait и создаёт кнопку для каждого действия.
        Если time_system отсутствует или действий нет, создаётся
        только кнопка закрытия.

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app)
        self.panel = Panel((340, 100, 600, 520))
        self.buttons = []
        ts = getattr(app, "time_system", None)
        if ts is None:
            logger.warning(
                "Меню действий: time_system отсутствует"
            )
            self.buttons.append(
                Button(
                    (540, 570, 200, 40),
                    "Закрыть",
                    app.font_body,
                    app.manager.pop,
                )
            )
            return
        actions = [
            a for a in ts.get_available_actions()
            if a.category == "wait"
        ]
        y = 160
        for action in actions:
            minutes = int(action.duration_seconds / 60)
            label = f"{action.label} ({minutes} мин)"
            self.buttons.append(
                Button(
                    (380, y, 520, 38),
                    label,
                    app.font_small,
                    lambda aid=action.id: self.choose_action(aid),
                )
            )
            y += 44
        self.buttons.append(
            Button(
                (540, 570, 200, 40),
                "Закрыть",
                app.font_body,
                app.manager.pop,
            )
        )
        logger.info(
            "Меню действий открыто: действий=%d", len(actions)
        )

    def choose_action(self, action_id):
        """
        Запускает выбранное действие и закрывает меню.

        Удаляет оверлей из стека экранов и передаёт ID действия
        в app.execute_player_action для выполнения через
        GameTimeSystem.

        Args:
            action_id (str): ID действия из time_actions.json.
        """
        logger.info("Выбрано действие: %s", action_id)
        self.app.manager.pop()
        self.app.execute_player_action(action_id)

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
        Отрисовывает меню действий.

        Порядок отрисовки: затемнение фона, панель, заголовок
        «Действия», кнопки действий и кнопка закрытия.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        title = self.app.font_body.render(
            "Действия", True, (220, 220, 230)
        )
        screen.blit(title, (380, 120))
        for b in self.buttons:
            b.draw(screen)