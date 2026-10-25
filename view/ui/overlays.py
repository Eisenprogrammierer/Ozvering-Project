"""
view/ui/overlays.py

Оверлеи: блокнот, бинокль, рация, логистика, лог тика.

Блокнот отображает контент вкладок и живых донесений в виде текста
на страницах открытого блокнота: строки заполняют левую страницу,
затем правую; при переполнении обоих листов создаётся следующий
разворот. Текст выводится на прозрачной поверхности, наклоняется
под углом листа и накладывается внутрь белого листа с внутренними
полями. Навигация осуществляется стрелками листания, закрытие —
кнопкой и ESC.

Бинокль ведёт поэтапную разведку сектора: донесение уточняется по
стадиям, а погрешность оценки умножается на усталость наблюдателя
и черту персонажа (report_noise_mult). Текст донесения переносится
по ширине панели и клипсуется внутри неё, не налезая на кнопки.

Рация поддерживает пагинацию списка подразделений, отображает
ролевые имена и выводит журнал связи в отдельной зоне.

События записываются в журнал operation_ozverin.log и дублируются
в консоль.
"""

import random
import zlib

import pygame

from .screen_manager import BaseScreen
from .widgets import Button, Panel
from .asset_loader import AssetLoader
from view.support.traits import get_report_noise_modifier
from view.support.log_journal import get_logger

logger = get_logger("view.overlays")

RADIO_OPEN_SIZE = (300, 380)
RADIO_OPEN_POS = (670, 230)
RADIO_LOG_RECT = pygame.Rect(320, 505, 320, 100)
RADIO_PAGE_SIZE = 7

NOTEBOOK_RECT = pygame.Rect(-60, -20, 1400, 760)
LEFT_PAGE_RECT = pygame.Rect(160, 90, 410, 530)
RIGHT_PAGE_RECT = pygame.Rect(630, 90, 410, 530)
LEFT_PAGE_ANGLE = -1.5
RIGHT_PAGE_ANGLE = -1.5
INK_COLOR = (35, 30, 25)
ARROW_COLOR = (95, 85, 75)
TEXT_BOTTOM_MARGIN = 48

EQUIPMENT_LABELS = {
    "U_tanks": "танки",
    "U_sp_guns": "САУ",
    "U_at_guns": "ПТ-САУ",
    "U_artillery": "орудия",
    "U_mlrs": "РСЗО",
    "U_otrk": "ОТРК",
    "U_sam": "ЗРК",
}


def _wrap_text(text, font, max_width):
    """
    Разбивает текст на строки по максимальной ширине.

    Args:
        text (str): Исходный текст.
        font (pygame.font.Font): Шрифт для измерения ширины.
        max_width (int): Максимальная ширина строки в пикселях.

    Returns:
        list[str]: Список строк, каждая из которых не превышает
            max_width пикселей.
    """
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


class OverlayScreen(BaseScreen):
    """
    Базовый оверлей с панелью и кнопкой закрытия.

    Attributes:
        panel (Panel): Фоновая панель оверлея.
        close_btn (Button): Кнопка закрытия.
    """

    def __init__(self, app, rect):
        """
        Инициализирует базовый оверлей.

        Args:
            app: Экземпляр приложения (App).
            rect (tuple): Прямоугольник панели (x, y, w, h).
        """
        super().__init__(app)
        self.panel = Panel(rect)
        self.close_btn = Button(
            (rect[0] + rect[2] - 46, rect[1] + 8, 38, 34),
            "X",
            app.font_body,
            app.manager.pop,
        )

    def draw_base(self, screen, title):
        """
        Рисует затемнение, панель, заголовок и кнопку закрытия.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
            title (str): Заголовок оверлея.
        """
        dim = pygame.Surface((1280, 720), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        screen.blit(dim, (0, 0))
        self.panel.draw(screen)
        t = self.app.font_body.render(title, True, (220, 220, 230))
        screen.blit(t, (self.panel.rect.x + 20, self.panel.rect.y + 14))
        self.close_btn.draw(screen)


class NotebookOverlay(OverlayScreen):
    """
    Оверлей открытого блокнота.

    Контент вкладок и живой сводки донесений раскладывается по
    разворотам увеличенного блокнота: текст заполняет левую
    страницу, затем правую; при переполнении обоих листов
    создаётся следующий разворот. Текст выводится на прозрачной
    поверхности, наклоняется под углом листа и накладывается
    внутрь белого листа с внутренними полями. Навигация
    осуществляется стрелками листания, закрытие — кнопкой.

    Attributes:
        notebook_img (pygame.Surface): Изображение открытого блокнота.
        spreads (list[tuple]): Список разворотов (левые, правые строки).
        page (int): Индекс текущего разворота.
        prev_rect (pygame.Rect): Зона клика для перехода назад.
        next_rect (pygame.Rect): Зона клика для перехода вперёд.
    """

    def __init__(self, app):
        """
        Инициализирует блокнот.

        Загружает изображение блокнота, формирует единый поток
        текста из вкладок и живой сводки, раскладывает его по
        разворотам страниц и создаёт элементы навигации.

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app, tuple(NOTEBOOK_RECT))
        tabs_data = [dict(t) for t in app.content.notebook.get("tabs", [])]
        tabs_data.append(self._build_live_tab(app))
        self.content_lines = []
        for i, tab in enumerate(tabs_data):
            if i > 0:
                self.content_lines.append(("separator", ""))
            label = tab.get("label", "")
            if label:
                self.content_lines.append(("heading", label))
            for line in tab.get("lines", []):
                self.content_lines.append(("line", line))

        self.notebook_img = AssetLoader.load(
            "items/notebook_open", NOTEBOOK_RECT.size
        )
        self.spreads = self._build_spreads()
        self.page = 0
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
        logger.info(
            "Блокнот открыт: вкладок=%d, строк=%d, разворотов=%d",
            len(tabs_data),
            len(self.content_lines),
            len(self.spreads),
        )

    def _order_label(self, st, idx):
        """
        Возвращает название текущего приказа сущности.

        Args:
            st: Состояние игрового мира (WorldState).
            idx (int): Индекс сущности.

        Returns:
            str: Название приказа или «—».
        """
        cfg = st.class_configs[st.class_ids[idx]]
        if "order" not in cfg.segment_layout.segments:
            return "—"
        val = st.read_segment(idx, "order")
        ot = getattr(self.app.engine, "order_table", None)
        if ot is not None and 0 <= val < len(ot.orders):
            return ot.orders[val]["label"]
        return st.get_segment_label(idx, "order")

    def _unit_report_line(self, st, idx):
        """
        Формирует строку донесения о подразделении.

        Args:
            st: Состояние игрового мира (WorldState).
            idx (int): Индекс сущности.

        Returns:
            str: Строка донесения.
        """
        head = st.label_of(idx)
        if st.factions[idx] != st.factions[st.player_idx]:
            head += " (противник)"
        parts = []
        cfg = st.class_configs[st.class_ids[idx]]
        if "U_manpower" in cfg.voltage_layout.channel_index:
            parts.append(f"л.с. {st.read_voltage(idx, 'U_manpower'):.0f}")
        if "U_casualties" in cfg.voltage_layout.channel_index:
            parts.append(
                f"потери {st.read_voltage(idx, 'U_casualties'):.0%}"
            )
        for ch, name in EQUIPMENT_LABELS.items():
            if ch in cfg.voltage_layout.channel_index:
                v = st.read_voltage(idx, ch)
                if v > 0:
                    parts.append(f"{name}: {v:.0f}")
        if "order" in cfg.segment_layout.segments:
            parts.append(f"приказ: {self._order_label(st, idx)}")
        if parts:
            return f"{head} — {', '.join(parts)}"
        return head

    def _build_live_tab(self, app):
        """
        Строит живую вкладку донесений.

        Args:
            app: Экземпляр приложения (App).

        Returns:
            dict: Вкладка с донесениями о всех военных юнитах.
        """
        st = app.engine.state
        lines = ["Сводка на момент открытия:"]
        for i in range(st.count):
            cfg = st.class_configs[st.class_ids[i]]
            if cfg.class_name != "military_unit":
                continue
            lines.append(self._unit_report_line(st, i))
        return {"id": "live", "label": "Донесения", "lines": lines}

    def _line_height(self, kind):
        """
        Возвращает высоту строки для заданного типа текста.

        Args:
            kind (str): Тип текста ("heading", "separator" или "line").

        Returns:
            int: Высота строки в пикселях.
        """
        if kind == "heading":
            return self.app.font_body.get_height() + 10
        if kind == "separator":
            return 16
        return self.app.font_small.get_height() + 6

    def _build_spreads(self):
        """
        Строит список разворотов из потока строк контента.

        Текст переносится по ширине узкой из двух страниц, заполняет
        левую страницу, затем правую. При переполнении обоих листов
        создаётся следующий разворот. Текст не заходит в нижнюю зону
        страниц, где расположены стрелки листания.

        Returns:
            list[tuple[list, list]]: Список разворотов. Каждый
                разворот — кортеж (строки левой страницы, строки
                правой страницы). Каждая строка — кортеж (kind, text).
        """
        page_w = min(LEFT_PAGE_RECT.width, RIGHT_PAGE_RECT.width)
        left_h = LEFT_PAGE_RECT.height - TEXT_BOTTOM_MARGIN
        right_h = RIGHT_PAGE_RECT.height - TEXT_BOTTOM_MARGIN
        spreads = []
        left = []
        right = []
        side = "left"
        y = 0
        for kind, text in self.content_lines:
            if kind == "separator":
                entries = [("separator", "")]
            elif kind == "heading":
                entries = [
                    ("heading", w)
                    for w in _wrap_text(text, self.app.font_body, page_w)
                ]
            else:
                entries = [
                    ("line", w)
                    for w in _wrap_text(text, self.app.font_small, page_w)
                ]
            for entry_kind, entry_text in entries:
                h = self._line_height(entry_kind)
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
                    left.append((entry_kind, entry_text))
                else:
                    right.append((entry_kind, entry_text))
                y += h
        if left or right:
            spreads.append((left, right))
        if not spreads:
            spreads.append(([], []))
        return spreads

    def _blit_page(self, screen, lines, page_rect, angle):
        """
        Отрисовывает страницу с текстом на наклонённой поверхности.

        Создаёт прозрачную поверхность, размещает на ней текст,
        поворачивает на заданный угол и накладывает на экран
        по центру целевого прямоугольника страницы.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
            lines (list[tuple]): Список строк (kind, text).
            page_rect (pygame.Rect): Прямоугольник страницы.
            angle (float): Угол поворота в градусах.
        """
        if not lines:
            return
        line_heights = [self._line_height(k) for k, _ in lines]
        height = sum(line_heights)
        temp = pygame.Surface(
            (page_rect.width, max(height, 1)), pygame.SRCALPHA
        )
        y = 0
        for (kind, text), lh in zip(lines, line_heights):
            if kind == "heading":
                surf = self.app.font_body.render(text, True, INK_COLOR)
                temp.blit(surf, (0, y))
            elif kind == "separator":
                pygame.draw.line(
                    temp,
                    (120, 100, 70),
                    (0, y + lh // 2),
                    (page_rect.width, y + lh // 2),
                    1,
                )
            else:
                surf = self.app.font_small.render(text, True, INK_COLOR)
                temp.blit(surf, (0, y))
            y += lh
        rotated = pygame.transform.rotate(temp, angle)
        dest = rotated.get_rect()
        dest.center = (
            page_rect.centerx,
            page_rect.y + dest.height // 2 + 6,
        )
        screen.blit(rotated, dest)

    def _draw_arrow(self, screen, rect, direction):
        """
        Рисует стрелку навигации в заданном прямоугольнике.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
            rect (pygame.Rect): Прямоугольник, в котором рисуется стрелка.
            direction (str): Направление стрелки ("prev" или "next").
        """
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
        """Переходит на предыдущий разворот."""
        if self.page > 0:
            self.page -= 1
            logger.info("Блокнот: переход на разворот %d", self.page + 1)

    def next_page(self):
        """Переходит на следующий разворот."""
        if self.page < len(self.spreads) - 1:
            self.page += 1
            logger.info("Блокнот: переход на разворот %d", self.page + 1)

    def handle_event(self, event):
        """
        Обрабатывает события: закрытие, прокрутка колесом мыши
        и клики по стрелкам листания.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.close_btn.handle_event(event):
            return
        if event.type == pygame.MOUSEWHEEL:
            if event.y < 0:
                self.next_page()
            elif event.y > 0:
                self.prev_page()
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.next_rect.collidepoint(event.pos):
                self.next_page()
            elif self.prev_rect.collidepoint(event.pos):
                self.prev_page()

    def draw(self, screen):
        """
        Отрисовывает открытый блокнот.

        Порядок отрисовки: затемнение фона, увеличенное изображение
        открытого блокнота, левая и правая страницы текущего
        разворота, индикатор номера разворота внизу правой страницы,
        стрелки навигации в нижних углах страниц, кнопка закрытия.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        overlay = pygame.Surface((1280, 720), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        screen.blit(overlay, (0, 0))
        screen.blit(self.notebook_img, NOTEBOOK_RECT.topleft)
        left_lines, right_lines = self.spreads[self.page]
        self._blit_page(screen, left_lines, LEFT_PAGE_RECT, LEFT_PAGE_ANGLE)
        self._blit_page(
            screen, right_lines, RIGHT_PAGE_RECT, RIGHT_PAGE_ANGLE
        )
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


class BinocularsOverlay(BaseScreen):
    """
    Бинокль с выбором сектора и стадиями наблюдения.

    Донесение уточняется по стадиям: стадия 0 — начало наблюдения;
    стадия 1 — качественная оценка (много/немало, тип с возможной
    ошибкой); стадия 2 — вилка числа рот и тенденция приказа
    противника (соседние приказы могут путаться); стадия 3 —
    численная оценка с небольшой погрешностью. Погрешность
    умножается на усталость наблюдателя и черту персонажа
    (report_noise_mult). Текст донесения переносится по ширине
    панели и клипсуется внутри неё, не налезая на кнопки.

    Attributes:
        SECTORS (tuple): Названия секторов.
        PANEL_RECT (pygame.Rect): Область панели донесения.
        TEXT_RECT (pygame.Rect): Область текста внутри панели.
        LINE_HEIGHT (int): Высота строки текста.
        STAGE_WAIT_SECONDS (int): Время ожидания между стадиями.
        TYPE_LABELS (dict): Подписи типов целей.
        ORDER_SCALE (tuple): Шкала приказов по агрессивности.
        TENDENCY_LABELS (dict): Подписи тенденций приказов.
        current (int): Индекс текущего сектора.
        stage (int): Текущая стадия наблюдения (0–3).
        sector_buttons (list[Button]): Кнопки выбора сектора.
        close_btn (Button): Кнопка закрытия.
        panel (Panel): Панель донесения.
        btn_stop (Button): Кнопка прекращения наблюдения.
        btn_continue (Button): Кнопка продолжения/завершения.
    """

    SECTORS = ("front", "left", "right")
    PANEL_RECT = pygame.Rect(260, 410, 760, 230)
    TEXT_RECT = pygame.Rect(282, 430, 716, 148)
    LINE_HEIGHT = 24
    STAGE_WAIT_SECONDS = 300
    TYPE_LABELS = {
        "tanks": "танки",
        "infantry": "пехота",
        "fortifications": "фортификации",
    }
    ORDER_SCALE = (
        "aggressive_attack",
        "attack",
        "cautious_attack",
        "holding_defense",
        "defense",
        "desperate_defense",
    )
    TENDENCY_LABELS = {
        "attack": "маневрируют",
        "move": "в движении",
        "defense": "держат оборону",
        "rest": "в районах отдыха",
    }

    def __init__(self, app):
        """
        Инициализирует бинокль.

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app)
        self.current = 0
        self.stage = 0
        self.names = ["Фронт", "Левый фланг", "Правый фланг"]
        self.sector_buttons = [
            Button(
                (280, 650, 200, 40),
                self.names[0],
                app.font_small,
                lambda: self.set_view(0),
            ),
            Button(
                (540, 650, 200, 40),
                self.names[1],
                app.font_small,
                lambda: self.set_view(1),
            ),
            Button(
                (800, 650, 200, 40),
                self.names[2],
                app.font_small,
                lambda: self.set_view(2),
            ),
        ]
        self.close_btn = Button(
            (1235, 12, 40, 34), "X", app.font_body, self.cancel_and_close
        )
        self.panel = Panel(self.PANEL_RECT)
        self.btn_stop = Button(
            (
                self.PANEL_RECT.x + 22,
                self.PANEL_RECT.bottom - 52,
                240,
                42,
            ),
            "Прекратить",
            app.font_body,
            self.cancel_and_close,
        )
        self.btn_continue = Button(
            (
                self.PANEL_RECT.right - 262,
                self.PANEL_RECT.bottom - 52,
                240,
                42,
            ),
            "Продолжить",
            app.font_body,
            self.advance_observation,
        )
        logger.info("Бинокль открыт")

    def set_view(self, i):
        """
        Переключает сектор и сбрасывает стадию наблюдения.

        Args:
            i (int): Индекс сектора (0–2).
        """
        self.current = i
        self.stage = 0
        self.btn_continue.text = "Продолжить"

    def cancel_and_close(self):
        """Отменяет наблюдение и закрывает оверлей."""
        ts = getattr(self.app, "time_system", None)
        if (
            ts is not None
            and ts.active_action
            and ts.active_action.definition_id == "binoculars_recon"
        ):
            ts.cancel_active_action()
        self.app.manager.pop()

    def advance_observation(self):
        """Продвигает стадию наблюдения, тратя игровое время."""
        if self.stage >= 3:
            self.app.manager.pop()
            return
        ts = getattr(self.app, "time_system", None)
        if ts is not None:
            ts.wait(self.STAGE_WAIT_SECONDS)
        self.stage += 1
        if self.stage >= 3:
            self.btn_continue.text = "Завершить"

    def _fatigue(self):
        """
        Возвращает текущую усталость наблюдателя (0..1).

        Returns:
            float: Усталость наблюдателя.
        """
        ts = getattr(self.app, "time_system", None)
        if ts is None:
            return 0.0
        return float(ts.get_fatigue())

    def _noise_mult(self):
        """
        Возвращает множитель погрешности наблюдателя.

        Черта персонажа (report_noise_mult), умноженная на фактор
        усталости. Ограничен, чтобы отчёт не становился абсурдным.

        Returns:
            float: Множитель погрешности [0.25, 3.0].
        """
        trait_mult = get_report_noise_modifier(self.app)
        mult = trait_mult * (1.0 + 1.5 * self._fatigue())
        return max(0.25, min(3.0, mult))

    def _noise_rng(self, sector):
        """
        Детерминированный генератор шума для сектора и дня.

        Args:
            sector (str): Название сектора.

        Returns:
            random.Random: Генератор случайных чисел.
        """
        ts = getattr(self.app, "time_system", None)
        day = ts.day if ts is not None else 1
        seed = zlib.crc32(f"{sector}:{day}".encode("utf-8"))
        return random.Random(seed)

    def _is_dead(self, idx):
        """
        Проверяет, уничтожено ли подразделение.

        Args:
            idx (int): Индекс сущности.

        Returns:
            bool: True, если подразделение уничтожено.
        """
        st = self.app.engine.state
        cfg = st.class_configs[st.class_ids[idx]]
        if "condition" in cfg.segment_layout.segments:
            if st.read_segment(idx, "condition") == 0:
                return True
        ch = cfg.voltage_layout.channel_index.get("U_manpower")
        if ch is not None and st.read_voltage(idx, "U_manpower") <= 0:
            return True
        return False

    def _voltage(self, idx, channel):
        """
        Возвращает напряжение канала или 0, если канала нет.

        Args:
            idx (int): Индекс сущности.
            channel (str): Имя канала.

        Returns:
            float: Значение напряжения.
        """
        st = self.app.engine.state
        cfg = st.class_configs[st.class_ids[idx]]
        if channel not in cfg.voltage_layout.channel_index:
            return 0.0
        return float(st.read_voltage(idx, channel))

    def _order_id(self, idx):
        """
        Возвращает строковый ID текущего приказа сущности.

        Args:
            idx (int): Индекс сущности.

        Returns:
            str: ID приказа или "rest".
        """
        st = self.app.engine.state
        cfg = st.class_configs[st.class_ids[idx]]
        if "order" not in cfg.segment_layout.segments:
            return "rest"
        val = st.read_segment(idx, "order")
        ot = getattr(self.app.engine, "order_table", None)
        if ot is not None and 0 <= val < len(ot.orders):
            return ot.orders[val]["id"]
        return "rest"

    def _order_label(self, order_id):
        """
        Возвращает человекочитаемое название приказа.

        Args:
            order_id (str): ID приказа.

        Returns:
            str: Название приказа.
        """
        ot = getattr(self.app.engine, "order_table", None)
        if ot is not None:
            idx = ot.id_to_index.get(order_id)
            if idx is not None:
                return ot.orders[idx]["label"]
        return order_id

    def _sector_enemies(self, sector):
        """
        Возвращает индексы живых противников в секторе.

        Args:
            sector (str): Название сектора.

        Returns:
            list[int]: Индексы противников в секторе.
        """
        from view.support.geometry import direction_between

        st = self.app.engine.state
        p = st.player_idx
        result = []
        for i in range(st.count):
            if i == p:
                continue
            cfg = st.class_configs[st.class_ids[i]]
            if cfg.class_name != "military_unit":
                continue
            if st.factions[i] == st.factions[p]:
                continue
            if self._is_dead(i):
                continue
            d = direction_between(
                st.coords[p, 0],
                st.coords[p, 1],
                st.coords[i, 0],
                st.coords[i, 1],
            )
            if d is None:
                continue
            rel = (d - st.headings[p]) % 4
            s = {0: "front", 1: "right", 3: "left"}.get(rel)
            if s == sector:
                result.append(i)
        return result

    def _sector_stats(self, sector):
        """
        Агрегирует силы противника в секторе по ротам (size == 1).

        Иерархия не даёт двойного счёта: учитываются только
        сущности с сегментом size == 1 (роты).

        Args:
            sector (str): Название сектора.

        Returns:
            dict: Статистика сектора с ключами companies,
                manpower, tanks, guns, orders.
        """
        st = self.app.engine.state
        stats = {
            "companies": 0,
            "manpower": 0.0,
            "tanks": 0.0,
            "guns": 0.0,
            "orders": {},
        }
        for i in self._sector_enemies(sector):
            cfg = st.class_configs[st.class_ids[i]]
            if "size" in cfg.segment_layout.segments:
                if st.read_segment(i, "size") != 1:
                    continue
            stats["companies"] += 1
            stats["manpower"] += self._voltage(i, "U_manpower")
            stats["tanks"] += self._voltage(i, "U_tanks")
            stats["guns"] += sum(
                self._voltage(i, ch)
                for ch in (
                    "U_sp_guns",
                    "U_at_guns",
                    "U_artillery",
                    "U_mlrs",
                )
            )
            oid = self._order_id(i)
            stats["orders"][oid] = stats["orders"].get(oid, 0.0) + 1
        return stats

    def _dominant_order(self, stats):
        """
        Возвращает приказ с наибольшим числом рот.

        Args:
            stats (dict): Статистика сектора.

        Returns:
            str: ID доминирующего приказа или "rest".
        """
        orders = stats["orders"]
        if not orders:
            return "rest"
        return max(orders, key=orders.get)

    def _tendency_of(self, order_id):
        """
        Возвращает ключ тенденции приказа.

        Args:
            order_id (str): ID приказа.

        Returns:
            str: Ключ тенденции (attack, move, defense, rest).
        """
        if order_id in (
            "aggressive_attack",
            "attack",
            "cautious_attack",
        ):
            return "attack"
        if order_id in ("move", "forced_march"):
            return "move"
        if order_id in (
            "holding_defense",
            "defense",
            "desperate_defense",
        ):
            return "defense"
        return "rest"

    def _noised_order(self, rng, mult, order_id):
        """
        Возвращает приказ с шумом.

        С вероятностью, растущей от множителя наблюдателя, приказ
        сдвигается на соседний по шкале агрессии (агрессивная
        путается с умеренной, но не с осторожной).

        Args:
            rng (random.Random): Генератор случайных чисел.
            mult (float): Множитель погрешности.
            order_id (str): Исходный ID приказа.

        Returns:
            str: Возможно изменённый ID приказа.
        """
        if order_id not in self.ORDER_SCALE:
            return order_id
        if rng.random() >= min(0.5, 0.25 * mult):
            return order_id
        idx = self.ORDER_SCALE.index(order_id)
        idx += rng.choice((-1, 1))
        idx = max(0, min(len(self.ORDER_SCALE) - 1, idx))
        return self.ORDER_SCALE[idx]

    def _true_type(self, stats):
        """
        Возвращает истинный доминирующий тип цели в секторе.

        Args:
            stats (dict): Статистика сектора.

        Returns:
            str: Тип цели (tanks, fortifications, infantry).
        """
        if stats["tanks"] >= 10:
            return "tanks"
        if (
            stats["guns"] >= 8
            and self._tendency_of(self._dominant_order(stats))
            == "defense"
        ):
            return "fortifications"
        return "infantry"

    def _report_lines(self, sector):
        """
        Формирует строки донесения для текущей стадии наблюдения.

        Погрешность растёт от множителя наблюдателя (черта и
        усталость); в конце выводится строка поправки.

        Args:
            sector (str): Название сектора.

        Returns:
            list[str]: Строки донесения.
        """
        stats = self._sector_stats(sector)
        if self.stage == 0:
            return ["Наблюдение начато. Продолжайте смотреть."]
        if stats["companies"] == 0:
            return ["Противник в секторе не обнаружен."]
        rng = self._noise_rng(sector)
        mult = self._noise_mult()
        fatigue = self._fatigue()
        lines = []
        if self.stage == 1:
            size_word = (
                "много" if stats["manpower"] >= 1200 else "немного"
            )
            true_type = self._true_type(stats)
            p_error = min(0.45, 0.15 * mult)
            if rng.random() < p_error:
                guessed = rng.choice(
                    [t for t in self.TYPE_LABELS if t != true_type]
                )
            else:
                guessed = true_type
            lines.append(
                f"Противник замечен. Похоже, его {size_word}."
            )
            lines.append(
                f"Видимо, это {self.TYPE_LABELS[guessed]}."
            )
        elif self.stage == 2:
            companies = max(1.0, stats["manpower"] / 450.0)
            spread = 0.25 * mult
            lo = max(1, int(companies * max(0.5, 1.0 - spread)))
            hi = max(lo, int(round(companies * (1.0 + spread))))
            noised = self._noised_order(
                rng, mult, self._dominant_order(stats)
            )
            tendency = self.TENDENCY_LABELS[
                self._tendency_of(noised)
            ]
            lines.append(
                f"{lo}-{hi} рот "
                f"({self.TYPE_LABELS[self._true_type(stats)]}), "
                f"{tendency}."
            )
            if stats["tanks"] > 0:
                rough = max(
                    0,
                    int(
                        stats["tanks"]
                        * rng.uniform(
                            max(0.5, 1 - 0.4 * mult),
                            1 + 0.4 * mult,
                        )
                    ),
                )
                lines.append(f"Бронетехника: примерно {rough} машин.")
        else:
            mp_err = min(0.5, 0.10 * mult)
            tech_err = min(0.5, 0.15 * mult)
            mp = max(
                0,
                int(
                    round(
                        stats["manpower"]
                        * rng.uniform(1 - mp_err, 1 + mp_err)
                        / 10
                    )
                    * 10
                ),
            )
            lines.append(f"Насчитано: л.с. ~ {mp}.")
            if stats["tanks"] > 0:
                tanks = max(
                    0,
                    int(
                        round(
                            stats["tanks"]
                            * rng.uniform(1 - tech_err, 1 + tech_err)
                        )
                    ),
                )
                lines.append(f"Танки ~ {tanks}.")
            if stats["guns"] > 0:
                guns = max(
                    0,
                    int(
                        round(
                            stats["guns"]
                            * rng.uniform(1 - tech_err, 1 + tech_err)
                        )
                    ),
                )
                lines.append(f"Орудия/САУ ~ {guns}.")
            lines.append(
                f"Приказ противника: "
                f"{self._order_label(self._dominant_order(stats))}."
            )
        lines.append(
            f"Поправка наблюдателя: x{mult:.2f} "
            f"(усталость {fatigue:.0%})."
        )
        return lines

    def _view_asset(self):
        """
        Подбирает ассет вида по оценке наблюдателя.

        На ранних стадиях тип может быть определён с ошибкой,
        на поздних — точно; количество — по численности.

        Returns:
            str | None: Путь к ассету или None.
        """
        sector = self.SECTORS[self.current]
        stats = self._sector_stats(sector)
        if stats["companies"] == 0:
            return None
        rng = self._noise_rng(sector)
        true_type = self._true_type(stats)
        if self.stage <= 1:
            p_error = min(0.45, 0.15 * self._noise_mult())
            if rng.random() < p_error:
                shown = rng.choice(
                    [t for t in self.TYPE_LABELS if t != true_type]
                )
            else:
                shown = true_type
        else:
            shown = true_type
        qty = "many" if stats["manpower"] >= 1200 else "few"
        return f"views/{shown}_{qty}"

    def handle_event(self, event):
        """
        Обрабатывает события кнопок бинокля.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.close_btn.handle_event(event):
            return
        if self.btn_stop.handle_event(event):
            return
        if self.btn_continue.handle_event(event):
            return
        for b in self.sector_buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        """
        Рисует бинокль.

        Ассет вида, панель донесения, текст донесения с переносом
        и клипсой внутри панели (не налезает на кнопки), кнопки
        управления и сектора.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        screen.fill((0, 0, 0))
        asset = self._view_asset()
        if asset:
            img = AssetLoader.load(asset, (1080, 720))
            screen.blit(img, ((1280 - 1080) // 2, 0))
        else:
            caption = self.app.font_body.render(
                "В секторе никого не видно.", True, (160, 160, 170)
            )
            screen.blit(caption, caption.get_rect(center=(640, 340)))
        self.panel.draw(screen)
        lines = self._report_lines(self.SECTORS[self.current])
        screen.set_clip(self.TEXT_RECT)
        y = self.TEXT_RECT.top
        for raw in lines:
            if y > self.TEXT_RECT.bottom - self.LINE_HEIGHT:
                break
            for wrapped in _wrap_text(
                raw, self.app.font_small, self.TEXT_RECT.width
            ):
                if y > self.TEXT_RECT.bottom - self.LINE_HEIGHT:
                    break
                screen.blit(
                    self.app.font_small.render(
                        wrapped, True, (230, 230, 235)
                    ),
                    (self.TEXT_RECT.left, y),
                )
                y += self.LINE_HEIGHT
        screen.set_clip(None)
        self.btn_stop.draw(screen)
        self.btn_continue.draw(screen)
        for b in self.sector_buttons:
            b.draw(screen)
        self.close_btn.draw(screen)


class LogisticsOverlay(OverlayScreen):
    """
    Оверлей логистики.

    Отображает снабжение подразделения игрока и активные
    модификаторы от логистических операций.

    Attributes:
        close_btn (Button): Кнопка закрытия.
    """

    def __init__(self, app):
        """
        Инициализирует оверлей логистики.

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app, (240, 60, 800, 600))
        self.close_btn = Button(
            (240 + 800 - 46, 60 + 8, 38, 34),
            "X",
            app.font_body,
            app.manager.pop,
        )

    def handle_event(self, event):
        """
        Обрабатывает события: только закрытие.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.close_btn.handle_event(event):
            return

    def draw(self, screen):
        """
        Рисует логистику.

        Показывает запасы по классам ресурсов и активные
        модификаторы боеприпасов, защиты и атаки.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        self.draw_base(screen, "Логистика")
        st = self.app.engine.state
        ls = getattr(st, "logistics", None)
        if ls is None:
            msg = self.app.font_body.render(
                "Логистическая система не активна.",
                True,
                (200, 100, 100),
            )
            screen.blit(msg, (300, 300))
            self.close_btn.draw(screen)
            return
        y = 120
        idx = st.player_idx
        supply = ls.unit_supply.get(idx)
        if supply:
            title = self.app.font_body.render(
                "Снабжение подразделения:", True, (220, 220, 230)
            )
            screen.blit(title, (280, y))
            y += 40
            for cls in ["I", "II", "III", "IV", "V", "VI", "VII"]:
                norm = supply.norm.get(cls, 0.0)
                actual = supply.actual.get(cls, 0.0)
                label = ls.resource_defs.get(cls, {}).get(
                    "label", cls
                )
                text = f"{label}: {actual:.0f} / {norm:.0f}"
                surf = self.app.font_small.render(
                    text, True, (200, 200, 210)
                )
                screen.blit(surf, (300, y))
                y += 25
            y += 20
        sys = getattr(self.app.engine, "logistics", None)
        if sys:
            ammo = sys.get_ammo_modifier(idx)
            def_mod = sys.get_defense_modifier(idx)
            off_mod = sys.get_offense_modifier(idx)
            title2 = self.app.font_body.render(
                "Активные модификаторы:", True, (220, 220, 230)
            )
            screen.blit(title2, (280, y))
            y += 40
            mods_text = (
                f"Боеприпасы: {ammo:.0%} | "
                f"Защита: +{def_mod:.0%} | "
                f"Атака: +{off_mod:.0%}"
            )
            surf2 = self.app.font_small.render(
                mods_text, True, (200, 200, 210)
            )
            screen.blit(surf2, (300, y))
        self.close_btn.draw(screen)


class RadioOverlay(OverlayScreen):
    """
    Рация с пагинацией списка подразделений.

    Отображает ролевые имена и выводит журнал связи в отдельной
    зоне.

    Attributes:
        units (list[tuple]): Список (индекс, entity_id) юнитов игрока.
        selected (int): Индекс выбранного юнита в списке units.
        page (int): Текущая страница списка.
        log (str): Текст журнала связи.
        radio_img (pygame.Surface): Изображение открытой рации.
        btn_connect (Button): Кнопка установки связи.
        btn_prev (Button): Кнопка предыдущей страницы.
        btn_next (Button): Кнопка следующей страницы.
        buttons (list[Button]): Кнопки юнитов текущей страницы.
    """

    def __init__(self, app):
        """
        Инициализирует рацию.

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app, (290, 90, 700, 540))
        st = app.engine.state
        self.units = [
            (i, st.entity_ids[i])
            for i in range(st.count)
            if st.class_configs[st.class_ids[i]].class_name
            == "military_unit"
            and st.factions[i] == "player"
        ]
        self.selected = 0
        self.page = 0
        self.log = "Выберите подразделение."
        self.radio_img = AssetLoader.load(
            "items/radio_open", RADIO_OPEN_SIZE
        )
        self.btn_connect = Button(
            (660, 160, 280, 38),
            "Связаться",
            app.font_small,
            self.connect,
        )
        self.btn_prev = Button(
            (320, 478, 135, 24),
            "< стр.",
            app.font_small,
            self.prev_page,
        )
        self.btn_next = Button(
            (465, 478, 135, 24),
            "стр. >",
            app.font_small,
            self.next_page,
        )
        self.buttons = []
        self._build_unit_buttons()

    def _page_count(self):
        """
        Возвращает число страниц списка подразделений.

        Returns:
            int: Число страниц (не менее 1).
        """
        return max(
            1, (len(self.units) + RADIO_PAGE_SIZE - 1) // RADIO_PAGE_SIZE
        )

    def _display_name(self, st, idx):
        """
        Строит ролевое имя: тактический индекс плюс роль внутри
        дивизии.

        Args:
            st: Состояние игрового мира (WorldState).
            idx (int): Индекс сущности.

        Returns:
            str: Ролевое имя (не более 30 символов).
        """
        label = st.label_of(idx)
        root = idx
        guard = 0
        while st.parent_ids[root] != -1 and guard < 16:
            root = st.parent_ids[root]
            guard += 1
        root_label = st.label_of(root)
        tail = ""
        if root != idx and label.startswith(root_label):
            tail = label[len(root_label):].strip()
        tids = getattr(st, "tactical_ids", None)
        tid = tids[idx] if tids is not None and idx < len(tids) else ""
        if tail:
            name = f"{tid} · {tail}" if tid else tail
        else:
            name = label
        if len(name) > 30:
            name = name[:27] + "..."
        return name

    def _build_unit_buttons(self):
        """Строит кнопки подразделений текущей страницы."""
        st = self.app.engine.state
        self.buttons = []
        start = self.page * RADIO_PAGE_SIZE
        for n, (idx, eid) in enumerate(
            self.units[start:start + RADIO_PAGE_SIZE]
        ):
            self.buttons.append(
                Button(
                    (320, 160 + n * 46, 280, 38),
                    self._display_name(st, idx),
                    self.app.font_small,
                    lambda n=start + n: self.select(n),
                )
            )

    def prev_page(self):
        """Листает страницы списка назад."""
        if self.page > 0:
            self.page -= 1
            self._build_unit_buttons()

    def next_page(self):
        """Листает страницы списка вперёд."""
        if self.page < self._page_count() - 1:
            self.page += 1
            self._build_unit_buttons()

    def select(self, i):
        """
        Выбирает подразделение по индексу.

        Args:
            i (int): Индекс в списке units.
        """
        self.selected = i

    def connect(self):
        """Устанавливает связь и формирует сводку."""
        if not self.units:
            self.log = "Нет доступных подразделений."
            return
        idx, eid = self.units[self.selected]
        st = self.app.engine.state
        cfg = st.class_configs[st.class_ids[idx]]
        parts = [self._display_name(st, idx)]
        if "U_manpower" in cfg.voltage_layout.channel_index:
            parts.append(
                f"л.с. {st.read_voltage(idx, 'U_manpower'):.0f}"
            )
        if "U_casualties" in cfg.voltage_layout.channel_index:
            parts.append(
                f"потери {st.read_voltage(idx, 'U_casualties'):.0%}"
            )
        for ch, name in EQUIPMENT_LABELS.items():
            if ch in cfg.voltage_layout.channel_index:
                v = st.read_voltage(idx, ch)
                if v > 0:
                    parts.append(f"{name}: {v:.0f}")
        if "order" in cfg.segment_layout.segments:
            parts.append(f"приказ: {self._order_label(st, idx)}")
        events = [
            e["message"]
            for e in st.event_log
            if e["entity_id"] == eid
        ][:2]
        self.log = ", ".join(parts)
        if events:
            self.log += " || " + " / ".join(events)

    def _order_label(self, st, idx):
        """
        Возвращает название текущего приказа сущности.

        Args:
            st: Состояние игрового мира (WorldState).
            idx (int): Индекс сущности.

        Returns:
            str: Название приказа или «—».
        """
        cfg = st.class_configs[st.class_ids[idx]]
        if "order" not in cfg.segment_layout.segments:
            return "—"
        val = st.read_segment(idx, "order")
        ot = getattr(self.app.engine, "order_table", None)
        if ot is not None and 0 <= val < len(ot.orders):
            return ot.orders[val]["label"]
        return st.get_segment_label(idx, "order")

    def handle_event(self, event):
        """
        Обрабатывает события кнопок рации.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.close_btn.handle_event(event):
            return
        if self.btn_connect.handle_event(event):
            return
        if self.btn_prev.handle_event(event):
            return
        if self.btn_next.handle_event(event):
            return
        for b in self.buttons:
            if b.handle_event(event):
                return

    def draw(self, screen):
        """
        Рисует рацию.

        Список юнитов, кнопки пагинации, кнопка связи,
        изображение рации, журнал связи в отдельной зоне.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        self.draw_base(screen, "Рация")
        for b in self.buttons:
            b.draw(screen)
        self.btn_prev.draw(screen)
        self.btn_next.draw(screen)
        info = f"{self.page + 1}/{self._page_count()}"
        info_surf = self.app.font_small.render(
            info, True, (150, 150, 160)
        )
        screen.blit(info_surf, (610, 482))
        self.btn_connect.draw(screen)
        if self.radio_img:
            screen.blit(self.radio_img, RADIO_OPEN_POS)
        y = RADIO_LOG_RECT.top
        for line in _wrap_text(
            self.log, self.app.font_small, RADIO_LOG_RECT.width
        ):
            if y > RADIO_LOG_RECT.bottom - 14:
                break
            screen.blit(
                self.app.font_small.render(
                    line, True, (140, 220, 140)
                ),
                (RADIO_LOG_RECT.left, y),
            )
            y += 18
        self.close_btn.draw(screen)


class TurnLogOverlay(OverlayScreen):
    """
    Оверлей лога последнего тика.

    Отображает последние 30 событий текущего тика.

    Attributes:
        close_btn (Button): Кнопка закрытия.
    """

    def __init__(self, app):
        """
        Инициализирует оверлей лога тика.

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app, (240, 60, 800, 600))

    def handle_event(self, event):
        """
        Обрабатывает события: только закрытие.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.close_btn.handle_event(event):
            return

    def draw(self, screen):
        """
        Рисует лог тика.

        Показывает последние 30 событий или сообщение об
        отсутствии событий.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        self.draw_base(screen, "Лог последнего тика")
        y = 130
        if not self.app.engine.state.tick_events:
            screen.blit(
                self.app.font_small.render(
                    "Нет событий.", True, (180, 180, 190)
                ),
                (270, y),
            )
            return
        for event in self.app.engine.state.tick_events[-30:]:
            tick = event.get("tick", "?")
            message = event.get("message", "")
            line = f"[{tick}] {message}"
            if len(line) > 96:
                line = line[:93] + "..."
            screen.blit(
                self.app.font_small.render(
                    line, True, (210, 210, 220)
                ),
                (270, y),
            )
            y += 22
            if y > 620:
                break