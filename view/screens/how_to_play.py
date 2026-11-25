"""Экран «Как играть»: цель, управление и первые шаги.

Экран не зависит от активной кампании: он объясняет общий контур
клиента, чтобы новая сессия не требовала чтения документации.
"""

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from view.support.log_journal import get_logger

logger = get_logger("view.how_to_play")

LINES = (
    ("Цель", "Провести своего персонажа через мир: занять должность,"),
    ("", "укрепить связи и не потерять доверие. Кампания автоматов"),
    ("", "показывает борьбу фракций, дневной мир — личную жизнь."),
    ("", ""),
    ("Как играть", "Выберите роль и сюжет. В дневном мире действия"),
    ("", "тратят дневной бюджет, а время идёт само в свободном режиме."),
    ("", "В кампании автоматов ход состоит из работ, докладов и реакций."),
    ("", ""),
    ("Управление", "F11 — полный экран, Esc — назад, Ctrl+T — ход,"),
    ("", "Ctrl+L — журнал, F5 — быстрое сохранение, мышь — выбор."),
    ("", ""),
    ("Совет", "Недоступное действие подписано причиной: не хватает"),
    ("", "влияния, связей, здоровья или времени. Сначала закройте"),
    ("", "базовую потребность, затем беритесь за высокую цель."),
)


class HowToPlayScreen(BaseScreen):

    def __init__(self, app):
        super().__init__(app)
        self.panel = Panel((110, 60, 1060, 600))
        self.back_button = Button(
            (540, 610, 200, 40),
            "Назад",
            app.font_body,
            app.manager.pop,
        )
        logger.info("Открыт экран «Как играть»")

    def handle_event(self, event):
        if self.back_button.handle_event(event):
            return

    def draw(self, screen):
        self.panel.draw(screen)
        title = self.app.font_body.render(
            "Как играть", True, (226, 232, 242)
        )
        screen.blit(title, title.get_rect(center=(640, 100)))
        y = 150
        for head, text in LINES:
            if head:
                label = self.app.font_body.render(
                    head, True, (120, 180, 235)
                )
                screen.blit(label, (150, y))
            line = self.app.font_small.render(
                text, True, (218, 224, 235)
            )
            screen.blit(line, (290, y + 4))
            y += 28
        self.back_button.draw(screen)
