import pygame

from view.support.log_journal import get_logger
from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button
from ..ui.asset_loader import AssetLoader
from ..ui.text_layout import draw_fitted

logger = get_logger("view.visual_novel")


class VisualNovelScreen(BaseScreen):

    escape_action = "custom"

    def __init__(self, app, slides, on_finish_callback):
        super().__init__(app)
        self.slides = slides
        self.current_slide = 0
        self.on_finish = on_finish_callback
        self.images = []
        for slide in slides:
            img_name = slide.get("image")
            if img_name:
                self.images.append(AssetLoader.load(img_name, (1280, 720)))
            else:
                surf = pygame.Surface((1280, 720))
                surf.fill((0, 0, 0))
                self.images.append(surf)
        self.btn_next = Button(
            (1100, 640, 120, 40), "Далее", app.font_body, self.next_slide
        )
        self.btn_skip = Button(
            (50, 640, 100, 40), "Пропустить", app.font_small, self.skip
        )
        logger.info(
            "Визуальная новелла инициализирована: слайдов=%d", len(slides)
        )

    def _finish(self):
        logger.info(
            "Визуальная новелла завершена на слайде %d/%d",
            self.current_slide,
            len(self.slides),
        )
        if self.on_finish:
            self.on_finish()

    def next_slide(self):
        self.current_slide += 1
        logger.debug(
            "Слайд переключён: %d/%d",
            self.current_slide,
            len(self.slides),
        )
        if self.current_slide >= len(self.slides):
            self._finish()

    def skip(self):
        logger.info(
            "Визуальная новелла пропущена на слайде %d/%d",
            self.current_slide,
            len(self.slides),
        )
        self._finish()

    def on_escape(self):
        self.skip()

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.btn_next.rect.collidepoint(
                event.pos
            ) and not self.btn_skip.rect.collidepoint(event.pos):
                self.next_slide()
        elif event.type == pygame.KEYDOWN and event.key in (
            pygame.K_SPACE,
            pygame.K_RETURN,
        ):
            self.next_slide()
        self.btn_next.handle_event(event)
        self.btn_skip.handle_event(event)

    def draw(self, screen):
        if self.images and self.current_slide < len(self.images):
            screen.blit(self.images[self.current_slide], (0, 0))
        else:
            screen.fill((0, 0, 0))
        overlay = pygame.Surface((1280, 280), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 195))
        screen.blit(overlay, (0, 440))
        if self.current_slide < len(self.slides):
            text = self.slides[self.current_slide].get("text", "")
            draw_fitted(
                screen,
                [self.app.font_body, self.app.font_small, self.app.font_tiny],
                text,
                pygame.Rect(70, 458, 1140, 168),
                (230, 230, 230),
                shadow=True,
            )
        prog = self.app.font_small.render(
            f"{self.current_slide + 1} / {len(self.slides)}",
            True,
            (170, 170, 170),
        )
        screen.blit(prog, (640 - prog.get_width() // 2, 682))
        self.btn_next.draw(screen)
        self.btn_skip.draw(screen)

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
