import os
import logging

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button
from ..ui.asset_loader import AssetLoader

FOLDER_RECT = pygame.Rect(240, 60, 800, 600)
LEFT_PAGE_RECT = pygame.Rect(395, 150, 200, 340)
RIGHT_PAGE_RECT = pygame.Rect(660, 165, 210, 375)
LEFT_PAGE_ANGLE = -7.0
RIGHT_PAGE_ANGLE = -7.0
INK_COLOR = (35, 30, 25)
ARROW_COLOR = (95, 85, 75)
TEXT_BOTTOM_MARGIN = 48

_LOG_NAME = "ozverin"


def _ensure_journal():
    root_logger = logging.getLogger(_LOG_NAME)
    if not root_logger.handlers:
        root_logger.setLevel(logging.INFO)
        root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..")
        )
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        file_handler = logging.FileHandler(
            os.path.join(root, "operation_ozverin.log"), encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        root_logger.addHandler(stream_handler)
    return root_logger


_ensure_journal()

logger = logging.getLogger(_LOG_NAME + ".documents")


class DocumentsScreen(BaseScreen):

    def __init__(self, app, documents):
        super().__init__(app)
        self.documents = documents
        self.page = 0
        self.folder_img = AssetLoader.load(
            "items/folder_middle", FOLDER_RECT.size
        )
        self.spreads = self._build_spreads()
        self.prev_rect = pygame.Rect(
            LEFT_PAGE_RECT.x + 18,
            LEFT_PAGE_RECT.bottom - 42,
            24,
            20,
        )
        self.next_rect = pygame.Rect(
            RIGHT_PAGE_RECT.right - 42,
            RIGHT_PAGE_RECT.bottom - 42,
            24,
            20,
        )
        self.close_btn = Button(
            (1100, 20, 150, 40),
            "Закрыть",
            app.font_small,
            self.close_menu,
        )
        logger.info(
            "DocumentsScreen инициализирован: документов=%d, разворотов=%d",
            len(self.documents),
            len(self.spreads),
        )

    def _line_height(self, kind):
        if kind == "heading":
            return self.app.font_body.get_height() + 10
        return self.app.font_small.get_height() + 6

    def _wrap_text(self, text, font, max_width):
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

    def _build_spreads(self):
        left_w = LEFT_PAGE_RECT.width
        right_w = RIGHT_PAGE_RECT.width
        left_h = LEFT_PAGE_RECT.height - TEXT_BOTTOM_MARGIN
        right_h = RIGHT_PAGE_RECT.height - TEXT_BOTTOM_MARGIN
        spreads = []
        for doc in self.documents:
            left = []
            right = []
            side = "left"
            y = 0
            lines = []
            for w in self._wrap_text(
                doc.get("title", "БЕЗ НАЗВАНИЯ"),
                self.app.font_body,
                left_w,
            ):
                lines.append(("heading", w))
            for raw in doc.get("lines", []):
                for w in self._wrap_text(raw, self.app.font_small, left_w):
                    lines.append(("line", w))
            for kind, text in lines:
                h = self._line_height(kind)
                limit = left_h if side == "left" else right_h
                if y + h > limit:
                    if side == "left":
                        side = "right"
                        y = 0
                    else:
                        spreads.append((left, right))
                        left = []
                        right = []
                        side = "left"
                        y = 0
                if side == "left":
                    left.append((kind, text))
                else:
                    right.append((kind, text))
                y += h
            if left or right:
                spreads.append((left, right))
        if not spreads:
            spreads.append(([], []))
        return spreads

    def _blit_page(self, screen, lines, page_rect, angle):
        if not lines:
            return
        line_heights = [self._line_height(k) for k, _ in lines]
        height = sum(line_heights)
        temp = pygame.Surface(
            (page_rect.width, max(height, 1)), pygame.SRCALPHA
        )
        y = 0
        for (kind, text), lh in zip(lines, line_heights):
            font = (
                self.app.font_body
                if kind == "heading"
                else self.app.font_small
            )
            temp.blit(font.render(text, True, INK_COLOR), (0, y))
            y += lh
        rotated = pygame.transform.rotate(temp, angle)
        dest = rotated.get_rect()
        dest.center = (page_rect.centerx, page_rect.y + dest.height // 2 + 12)
        screen.blit(rotated, dest)

    def _draw_arrow(self, screen, rect, direction):
        if direction == "next":
            points = [
                (rect.left + 4, rect.top + 2),
                (rect.left + 4, rect.bottom - 2),
                (rect.right - 2, rect.centery),
            ]
        else:
            points = [
                (rect.right - 4, rect.top + 2),
                (rect.right - 4, rect.bottom - 2),
                (rect.left + 2, rect.centery),
            ]
        pygame.draw.polygon(screen, ARROW_COLOR, points)

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            logger.info(
                "DocumentsScreen: переход на разворот %d", self.page + 1
            )

    def next_page(self):
        if self.page < len(self.spreads) - 1:
            self.page += 1
            logger.info(
                "DocumentsScreen: переход на разворот %d", self.page + 1
            )

    def close_menu(self):
        logger.info("DocumentsScreen: закрыт")
        self.app.manager.pop()

    def handle_event(self, event):
        if self.close_btn.handle_event(event):
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.next_rect.collidepoint(event.pos):
                self.next_page()
            elif self.prev_rect.collidepoint(event.pos):
                self.prev_page()

    def draw(self, screen):
        overlay = pygame.Surface((1280, 720), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        screen.blit(overlay, (0, 0))
        screen.blit(self.folder_img, FOLDER_RECT.topleft)
        left_lines, right_lines = self.spreads[self.page]
        self._blit_page(screen, left_lines, LEFT_PAGE_RECT, LEFT_PAGE_ANGLE)
        self._blit_page(screen, right_lines, RIGHT_PAGE_RECT, RIGHT_PAGE_ANGLE)
        info = f"{self.page + 1} / {len(self.spreads)}"
        info_surf = self.app.font_small.render(info, True, INK_COLOR)
        screen.blit(
            info_surf,
            (
                RIGHT_PAGE_RECT.centerx - info_surf.get_width() // 2,
                RIGHT_PAGE_RECT.bottom - 36,
            ),
        )
        self._draw_arrow(screen, self.prev_rect, "prev")
        self._draw_arrow(screen, self.next_rect, "next")
        self.close_btn.draw(screen)
