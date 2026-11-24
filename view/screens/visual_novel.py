import pygame

from view.support.log_journal import get_logger
from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button
from ..ui.asset_loader import AssetLoader
from ..ui.text_layout import draw_fitted

logger = get_logger("view.visual_novel")


class VisualNovelScreen(BaseScreen):

    escape_action = "custom"

    def __init__(self, app, slides, on_finish_callback, on_choice=None):
        super().__init__(app)
        self.slides = slides
        self.current_slide = 0
        self.on_finish = on_finish_callback
        self.on_choice = on_choice
        self.hint = ""
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
        self._choice_buttons = []
        self._sync_choice_buttons()
        logger.info(
            "Визуальная новелла инициализирована: слайдов=%d", len(slides)
        )

    def _current(self):
        if 0 <= self.current_slide < len(self.slides):
            return self.slides[self.current_slide]
        return {}

    def _choices(self):
        choices = self._current().get("choices") or []
        if not isinstance(choices, (list, tuple)):
            return []
        return [item for item in choices if isinstance(item, dict)]

    def _sync_choice_buttons(self):
        self._choice_buttons = []
        for index, choice in enumerate(self._choices()[:3]):
            label = str(choice.get("label") or choice.get("text") or "")
            if not label:
                continue
            rect = (170, 520 + index * 52, 940, 44)
            self._choice_buttons.append(
                Button(
                    rect,
                    label,
                    self.app.font_small,
                    lambda idx=index: self.choose(idx),
                )
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
        if self._choices():
            self.hint = "Сначала выберите вариант."
            return
        self.current_slide += 1
        logger.debug(
            "Слайд переключён: %d/%d",
            self.current_slide,
            len(self.slides),
        )
        if self.current_slide >= len(self.slides):
            self._finish()
            return
        self.hint = ""
        self._sync_choice_buttons()

    def choose(self, index):
        """Выбрать вариант текущего слайда.

        Сама сцена не знает смысла выбора: она передаёт словарь данных
        приложению и переходит дальше. Эффекты, переменные и запись в
        ленту — ответственность интерпретатора.
        """

        choices = self._choices()
        if index < 0 or index >= len(choices):
            return False
        choice = choices[index]
        logger.info(
            "Выбор в новелле: слайд=%d, вариант=%d, label=%s",
            self.current_slide,
            index,
            choice.get("label") or choice.get("text") or "",
        )
        if self.on_choice is not None:
            try:
                self.on_choice(choice)
            except Exception as exc:  # pragma: no cover - защита UI
                logger.exception("Выбор сцены не применён: %s", exc)
                self.hint = "Выбор не применён: %s" % exc
                return False
        self.current_slide += 1
        if self.current_slide >= len(self.slides):
            self._finish()
        else:
            self.hint = ""
            self._sync_choice_buttons()
        return True

    def skip(self):
        if self._choices():
            self.hint = "Пропуск недоступен: сначала выберите вариант."
            return
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
                if not any(
                    button.rect.collidepoint(event.pos)
                    for button in self._choice_buttons
                ):
                    self.next_slide()
        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                self.next_slide()
            elif pygame.K_1 <= event.key <= pygame.K_3:
                self.choose(event.key - pygame.K_1)
        for button in self._choice_buttons:
            button.handle_event(event)
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
        choices = self._choices()
        if self.current_slide < len(self.slides):
            text = self._current().get("text", "")
            text_rect = (
                pygame.Rect(70, 452, 1140, 56)
                if choices
                else pygame.Rect(70, 458, 1140, 168)
            )
            draw_fitted(
                screen,
                [self.app.font_body, self.app.font_small, self.app.font_tiny],
                text,
                text_rect,
                (230, 230, 230),
                shadow=True,
            )
        for button in self._choice_buttons:
            button.draw(screen)
        if choices:
            hint = self.hint or "Выберите вариант: 1–%d" % len(choices)
            surf = self.app.font_tiny.render(hint, True, (170, 170, 170))
            screen.blit(surf, (170, 682))
        else:
            self.btn_next.draw(screen)
            self.btn_skip.draw(screen)
            prog = self.app.font_small.render(
                f"{self.current_slide + 1} / {len(self.slides)}",
                True,
                (170, 170, 170),
            )
            screen.blit(prog, (640 - prog.get_width() // 2, 682))

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
