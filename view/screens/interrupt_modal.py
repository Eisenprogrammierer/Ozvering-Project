import pygame

from view.support.log_journal import get_logger
from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from ..ui.text_layout import draw_fitted

logger = get_logger("view.interrupt_modal")


class InterruptModal(BaseScreen):

    escape_action = "none"

    def __init__(self, app, interrupt):
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
        ts = getattr(self.app, "time_system", None)
        if ts is not None and self.interrupt is not None:
            ts.accept_interrupt(self.interrupt.id)
            logger.info("Прерывание принято: id=%s", self.interrupt.id)
        self.app.manager.pop()

    def ignore(self):
        ts = getattr(self.app, "time_system", None)
        if ts is not None and self.interrupt is not None:
            ts.ignore_interrupt(self.interrupt.id)
            logger.info("Прерывание проигнорировано: id=%s", self.interrupt.id)
        self.app.manager.pop()

    @staticmethod
    def _wrap_text(text, font, max_width):
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
        if self.btn_accept.handle_event(event):
            return
        if self.btn_ignore.handle_event(event):
            return

    def draw(self, screen):
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 160))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        if self.interrupt is None:
            return
        draw_fitted(
            screen,
            [self.app.font_body, self.app.font_small],
            self.interrupt.title,
            pygame.Rect(330, 205, 620, 55),
            (255, 180, 100),
        )
        draw_fitted(
            screen,
            [self.app.font_small, self.app.font_tiny],
            self.interrupt.text,
            pygame.Rect(330, 270, 620, 112),
            (220, 220, 230),
        )
        priority_text = f"Приоритет: {self.interrupt.priority}"
        priority_surf = self.app.font_small.render(
            priority_text, True, (160, 160, 180)
        )
        screen.blit(priority_surf, (330, 400))
        self.btn_accept.draw(screen)
        self.btn_ignore.draw(screen)
