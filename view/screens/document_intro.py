"""
view/screens/document_intro.py

Экран интро с документом в руках.

Отображает изображение рук, держащих бумагу, со стилизованным текстом
приказа. Безопасная зона текста задаётся отдельно для каждого ассета
рук (таблица HANDS_TEXT_RECTS), чтобы текст лежал строго на бумаге и
не задевал пальцы ни в одном варианте рук. Текст центрируется
построчно и автоматически подбирает кегль, чтобы целиком уместиться
в безопасной зоне. Переносы строк из конфига уважаются.

Кнопка «Прочитать внимательно» открывает читалку с прокруткой
(колесо мыши, стрелки, PageUp/PageDown).

Поведение ESC: при открытой читалке закрывает только её, при
закрытой — игнорируется.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль.
"""

import os

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button, Panel
from ..ui.asset_loader import AssetLoader
from view.support.log_journal import get_logger

logger = get_logger("view.document_intro")

BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
FONT_PATH = os.path.normpath(
    os.path.join(BASE_DIR, "assets", "fonts", "DejaVuSansMono.ttf")
)
INK_COLOR = (35, 30, 25)
PAPER_ANGLE = 4.0
PAPER_FONT_SIZES = (12, 11, 10, 9, 8)
HANDS_TEXT_RECTS = {
    "items/hands_paper_female": pygame.Rect(500, 45, 265, 565),
    "items/hands_paper_male": pygame.Rect(500, 45, 225, 565),
}
DEFAULT_TEXT_RECT = pygame.Rect(400, 45, 230, 565)
READER_TEXT_RECT = pygame.Rect(180, 170, 880, 390)
READER_SCROLL_STEP = 3
READER_PAGE_STEP = 12


def _load_font(size):
    """
    Загружает моноширинный шрифт заданного размера с фолбэком.

    Пытается загрузить DejaVuSansMono.ttf из assets/fonts/.
    При ошибке или отсутствии файла возвращает встроенный
    шрифт pygame того же размера.

    Args:
        size (int): Размер шрифта в пикселях.

    Returns:
        pygame.font.Font: Загруженный или встроенный шрифт.
    """
    if os.path.exists(FONT_PATH):
        try:
            return pygame.font.Font(FONT_PATH, size)
        except Exception:
            pass
    return pygame.font.Font(None, size)


class DocumentIntroScreen(BaseScreen):
    """
    Экран интро с документом в руках.

    Текст приказа размещается в безопасной зоне, подобранной под
    конкретный ассет рук, центрируется построчно и подбирает кегль,
    чтобы целиком уместиться на бумаге, не задевая пальцы.

    Attributes:
        doc (dict): Данные документа (title, content_stylized,
            content_plain, hands_asset).
        on_finish (callable): Callback завершения («К делу»).
        hands_img (pygame.Surface): Изображение рук с бумагой.
        text_rect (pygame.Rect): Безопасная зона текста на бумаге.
        btn_read (Button): Кнопка открытия/закрытия читалки.
        btn_proceed (Button): Кнопка перехода к делу.
        show_reader (bool): Флаг отображения читалки.
        reader_scroll (int): Смещение прокрутки читалки в строках.
    """

    escape_action = "custom"

    def __init__(self, app, document_data, on_finish_callback):
        """
        Инициализирует экран интро с документом.

        Загружает ассет рук, подбирает безопасную зону текста,
        предварительно рендерит текст на бумаге с оптимальным кеглем,
        создаёт кнопки управления и инициализирует состояние читалки.

        Args:
            app: Экземпляр приложения (App).
            document_data (dict): Данные документа с ключами title,
                content_stylized, content_plain, hands_asset.
            on_finish_callback (callable): Функция, вызываемая при
                нажатии кнопки «К делу».
        """
        super().__init__(app)
        self.doc = document_data
        self.on_finish = on_finish_callback
        hands_asset = document_data.get("hands_asset", "items/hands_paper")
        self.hands_img = AssetLoader.load(hands_asset, (1280, 720))
        self.text_rect = HANDS_TEXT_RECTS.get(hands_asset, DEFAULT_TEXT_RECT)
        self.btn_read = Button(
            (440, 620, 340, 50),
            "Прочитать внимательно",
            app.font_body,
            self.toggle_reader,
        )
        self.btn_proceed = Button(
            (800, 620, 200, 50),
            "К делу",
            app.font_body,
            self.proceed,
        )
        self.show_reader = False
        self.reader_panel = Panel((140, 100, 1000, 500))
        self.reader_scroll = 0
        self._reader_lines = None
        self._paper_font, self._paper_lines, self._paper_line_height = (
            self._prepare_paper_text()
        )
        logger.info(
            "Экран интро документа: title=%s, asset=%s, строк на бумаге=%d, "
            "кегль=%d, зона=%s",
            self.doc.get("title", "ПРИКАЗ"),
            hands_asset,
            len(self._paper_lines),
            self._paper_font.get_height(),
            tuple(self.text_rect),
        )

    def toggle_reader(self):
        """Переключает видимость читалки и сбрасывает прокрутку."""
        self.show_reader = not self.show_reader
        self.reader_scroll = 0
        logger.debug(
            "Читалка: %s", "открыта" if self.show_reader else "закрыта"
        )

    def proceed(self):
        """Завершает интро и вызывает callback перехода к делу."""
        logger.info(
            "Переход к делу: title=%s", self.doc.get("title", "ПРИКАЗ")
        )
        if self.on_finish:
            self.on_finish()

    def on_escape(self):
        """Обрабатывает ESC: закрывает только открытую читалку."""
        if self.show_reader:
            self.show_reader = False
            logger.debug("ESC: читалка закрыта")

    @staticmethod
    def _wrap_text(text, font, max_width):
        """
        Переносит текст по ширине с уважением переносов строк.

        Пустые строки конфига дают пустые строки на бумаге.
        Символы \\n в тексте интерпретируются как переносы строк.

        Args:
            text (str): Исходный текст.
            font (pygame.font.Font): Шрифт для измерения ширины.
            max_width (int): Максимальная ширина строки в пикселях.

        Returns:
            list[str]: Список строк после переноса.
        """
        text = str(text).replace("\\n", "\n")
        lines = []
        for paragraph in text.split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                lines.append("")
                continue
            current = ""
            for word in paragraph.split():
                test = (current + " " + word).strip()
                if current and font.size(test)[0] > max_width:
                    lines.append(current)
                    current = word
                else:
                    current = test
            lines.append(current)
        return lines

    def _prepare_paper_text(self):
        """
        Подбирает наибольший кегль, при котором весь текст приказа
        умещается в безопасной зоне бумаги текущего ассета рук.

        Перебирает размеры шрифта от большего к меньшему из
        PAPER_FONT_SIZES. Возвращает первый размер, при котором
        общая высота текста не превышает высоту безопасной зоны.
        Если ни один размер не подходит, использует наименьший.

        Returns:
            tuple: Кортеж (шрифт, список строк, высота строки).
        """
        raw = self.doc.get("content_stylized", "")
        rect = self.text_rect
        for size in PAPER_FONT_SIZES:
            font = _load_font(size)
            lines = self._wrap_text(raw, font, rect.width)
            line_height = font.get_height() + 3
            if line_height * len(lines) <= rect.height:
                return font, lines, line_height
        font = _load_font(PAPER_FONT_SIZES[-1])
        lines = self._wrap_text(raw, font, rect.width)
        line_height = font.get_height() + 3
        return font, lines, line_height

    def _reader_lines_cached(self):
        """
        Возвращает кэшированный список строк читалки.

        При первом вызове разбивает content_plain по ширине
        READER_TEXT_RECT и кэширует результат. Последующие вызовы
        возвращают кэш без повторного вычисления.

        Returns:
            list[str]: Список строк текста для читалки.
        """
        if self._reader_lines is None:
            self._reader_lines = self._wrap_text(
                self.doc.get("content_plain", ""),
                self.app.font_body,
                READER_TEXT_RECT.width - 30,
            )
        return self._reader_lines

    def _reader_visible_lines(self):
        """
        Возвращает число строк, видимых в окне читалки.

        Вычисляется как целая часть от деления высоты текстовой
        области читалки на высоту строки текущего шрифта.

        Returns:
            int: Количество видимых строк (минимум 1).
        """
        line_height = self.app.font_body.get_height() + 6
        return max(1, READER_TEXT_RECT.height // line_height)

    def _scroll_reader(self, delta):
        """
        Смещает прокрутку читалки с клампом по границам текста.

        Args:
            delta (int): Смещение в строках (положительное — вниз,
                отрицательное — вверх).
        """
        lines = self._reader_lines_cached()
        max_scroll = max(0, len(lines) - self._reader_visible_lines())
        self.reader_scroll = max(
            0, min(max_scroll, self.reader_scroll + delta)
        )

    def handle_event(self, event):
        """
        Обрабатывает события pygame для экрана.

        При открытой читалке принимает прокрутку колесом мыши,
        кнопками 4/5 и клавишами вверх/вниз/PageUp/PageDown.
        Иначе обрабатывает кнопки «Прочитать внимательно» и «К делу»;
        ENTER эквивалентен нажатию «К делу».

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.show_reader:
            if event.type == pygame.MOUSEWHEEL:
                self._scroll_reader(-event.y * READER_SCROLL_STEP)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 4:
                self._scroll_reader(-READER_SCROLL_STEP)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 5:
                self._scroll_reader(READER_SCROLL_STEP)
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_UP:
                    self._scroll_reader(-READER_SCROLL_STEP)
                elif event.key == pygame.K_DOWN:
                    self._scroll_reader(READER_SCROLL_STEP)
                elif event.key == pygame.K_PAGEUP:
                    self._scroll_reader(-READER_PAGE_STEP)
                elif event.key == pygame.K_PAGEDOWN:
                    self._scroll_reader(READER_PAGE_STEP)
            return
        self.btn_read.handle_event(event)
        self.btn_proceed.handle_event(event)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
            self.proceed()

    def draw(self, screen):
        """
        Отрисовывает экран интро с документом.

        Порядок: руки с бумагой, текст приказа по центру безопасной
        зоны с подобранным кеглем и поворотом под наклон бумаги,
        кнопки, поверх — читалка с прокруткой и ползунком, если
        она открыта.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        screen.blit(self.hands_img, (0, 0))
        rect = self.text_rect
        font = self._paper_font
        lines = self._paper_lines
        line_height = self._paper_line_height
        temp = pygame.Surface(
            (rect.width, max(line_height * len(lines), 1)),
            pygame.SRCALPHA,
        )
        y = 0
        for line in lines:
            if line:
                surf = font.render(line, True, INK_COLOR)
                temp.blit(
                    surf, ((rect.width - surf.get_width()) // 2, y)
                )
            y += line_height
        rotated = pygame.transform.rotate(temp, PAPER_ANGLE)
        rw, rh = rotated.get_size()
        screen.blit(rotated, (rect.centerx - rw // 2, rect.top))
        self.btn_read.draw(screen)
        self.btn_proceed.draw(screen)
        if self.show_reader:
            self._draw_reader(screen)

    def _draw_reader(self, screen):
        """
        Рисует читалку: затемнение, панель, заголовок, прокручиваемый
        текст с обрезкой по видимой области и ползунок.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        overlay = pygame.Surface((1280, 720), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 230))
        screen.blit(overlay, (0, 0))
        self.reader_panel.draw(screen)
        title_surf = self.app.font_body.render(
            self.doc.get("title", "ПРИКАЗ"), True, (220, 200, 180)
        )
        screen.blit(title_surf, (180, 130))
        lines = self._reader_lines_cached()
        line_height = self.app.font_body.get_height() + 6
        visible = self._reader_visible_lines()
        max_scroll = max(0, len(lines) - visible)
        self.reader_scroll = max(0, min(self.reader_scroll, max_scroll))
        screen.set_clip(READER_TEXT_RECT)
        y = READER_TEXT_RECT.top
        for line in lines[self.reader_scroll:self.reader_scroll + visible]:
            screen.blit(
                self.app.font_body.render(line, True, (200, 200, 200)),
                (READER_TEXT_RECT.left, y),
            )
            y += line_height
        screen.set_clip(None)
        track = pygame.Rect(
            READER_TEXT_RECT.right + 10,
            READER_TEXT_RECT.top,
            6,
            READER_TEXT_RECT.height,
        )
        pygame.draw.rect(screen, (60, 60, 70), track, border_radius=3)
        if max_scroll > 0:
            thumb_h = max(
                20, int(track.height * visible / max(1, len(lines)))
            )
            thumb_y = track.top + int(
                (track.height - thumb_h) * self.reader_scroll / max_scroll
            )
            pygame.draw.rect(
                screen,
                (120, 140, 200),
                pygame.Rect(track.x, thumb_y, track.width, thumb_h),
                border_radius=3,
            )
        hint = self.app.font_small.render(
            "Колесо мыши / стрелки — прокрутка, ESC — закрыть",
            True,
            (150, 150, 150),
        )
        screen.blit(hint, (180, 570))