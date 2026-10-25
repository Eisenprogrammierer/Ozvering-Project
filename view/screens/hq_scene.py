"""
view/screens/hq_scene.py

Сцена командного пункта (КП).

Отображает фон штаба, зависящий от пола персонажа игрока:
при player_gender == "female" используется фон с адъютантом-мужчиной,
иначе — с адъютантом-женщиной. Предметы стола (документы, блокнот,
бинокль, рация) имеют два визуальных состояния (закрытое/открытое)
и подсвечиваются при наведении курсора с всплывающей подписью.
Открытое состояние предмета сохраняется, пока соответствующий
оверлей присутствует в стеке экранов.

Адъютант является интерактивной зоной (хотспотом), открывающей
экран приказов. Карта в углу экрана также является хотспотом.

Кнопки управления: «Главное меню» (с автосохранением), «Действия»,
«Ждать 30 мин», «Логистика».

ESC обрабатывается через escape_action="custom" и эквивалентен
переходу в главное меню. show_time_hud=True включает отображение
HUD игрового времени поверх сцены КП.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль средствами core.log_journal.
"""

import pygame

from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button
from ..ui.asset_loader import AssetLoader
from ..ui.overlays import BinocularsOverlay, RadioOverlay
from view.support.log_journal import get_logger

logger = get_logger("view.hq_scene")

ADJUTANT_RECT = (170, 120, 290, 370)

DESK_ITEMS = [
    ("documents", "Документы", (370, 530, 90, 48),
     "items/folder_closed", "items/folder_middle"),
    ("notebook", "Блокнот", (555, 510, 95, 70),
     "items/notebook_closed", "items/notebook_open"),
    ("binoculars", "Бинокль", (655, 508, 90, 62),
     "items/binoculars_closed", "items/binoculars_open"),
    ("radio", "Рация", (760, 508, 95, 62),
     "items/radio_closed", "items/radio_open"),
]

MALE_DESK_PANEL_RECT = pygame.Rect(240, 616, 700, 100)

MALE_DESK_SLOTS = [
    ("documents", "Документы", (252, 626, 160, 80),
     "items/folder_closed", "items/folder_middle"),
    ("notebook", "Блокнот", (424, 626, 160, 80),
     "items/notebook_closed", "items/notebook_open"),
    ("binoculars", "Бинокль", (596, 626, 160, 80),
     "items/binoculars_closed", "items/binoculars_open"),
    ("radio", "Рация", (768, 626, 160, 80),
     "items/radio_closed", "items/radio_open"),
]

MAP_CORNER_SIZE = (380, 285)
MAP_CORNER_POS = (960, 485)
MAP_SPOT_RECT = (960, 485, 320, 235)

EQUIPMENT_LABELS = {
    "U_tanks": "танки",
    "U_sp_guns": "САУ",
    "U_at_guns": "ПТ-САУ",
    "U_artillery": "орудия",
    "U_mlrs": "РСЗО",
    "U_otrk": "ОТРК",
    "U_sam": "ЗРК",
}


class Hotspot:
    """
    Интерактивная зона (хотспот) на экране.

    Отслеживает наведение курсора и клик левой кнопкой мыши.
    При наведении рисует рамку и всплывающую подпись над зоной.
    Если подпись не помещается сверху, размещается снизу.

    Attributes:
        rect (pygame.Rect): Прямоугольная область хотспота.
        label (str): Текст всплывающей подписи.
        callback (callable): Функция, вызываемая при клике.
        font (pygame.font.Font): Шрифт для подписи.
        hovered (bool): Флаг наведения курсора.
    """

    def __init__(self, rect, label, callback, font):
        """
        Инициализирует хотспот.

        Args:
            rect (tuple): Координаты и размеры (x, y, w, h).
            label (str): Текст всплывающей подписи.
            callback (callable): Функция, вызываемая при клике.
            font (pygame.font.Font): Шрифт для подписи.
        """
        self.rect = pygame.Rect(rect)
        self.label = label
        self.callback = callback
        self.font = font
        self.hovered = False

    def handle_event(self, event):
        """
        Обрабатывает события pygame для хотспота.

        Отслеживает MOUSEMOTION для подсветки и MOUSEBUTTONDOWN
        для вызова callback.

        Args:
            event (pygame.event.Event): Событие pygame.

        Returns:
            bool: True, если клик был обработан.
        """
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.callback()
                return True
        return False

    def draw(self, screen):
        """
        Отрисовывает хотспот: рамку и всплывающую подпись при наведении.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        if not self.hovered:
            return
        pygame.draw.rect(screen, (210, 210, 230), self.rect, 2, border_radius=8)
        label = self.font.render(self.label, True, (235, 235, 245))
        bg = pygame.Surface(
            (label.get_width() + 16, label.get_height() + 10),
            pygame.SRCALPHA
        )
        bg.fill((10, 10, 15, 190))
        x = self.rect.centerx - bg.get_width() // 2
        y = self.rect.top - bg.get_height() - 8
        if y < 0:
            y = self.rect.bottom + 8
        screen.blit(bg, (x, y))
        screen.blit(label, (x + 8, y + 5))


class DeskItem:
    """
    Предмет стола КП с двумя визуальными состояниями.

    Загружает закрытый и открытый ассеты. Открытое состояние
    отображается, пока соответствующий оверлей присутствует
    в стеке экранов. При наведении рисует рамку и подпись.

    Attributes:
        item_id (str): Идентификатор предмета.
        rect (pygame.Rect): Прямоугольная область предмета.
        label (str): Текст подписи.
        callback (callable): Функция, вызываемая при клике.
        font (pygame.font.Font): Шрифт для подписи.
        img_closed (pygame.Surface): Закрытый ассет.
        img_open (pygame.Surface): Открытый ассет.
        hovered (bool): Флаг наведения курсора.
    """

    def __init__(self, item_id, rect, label, callback, font, closed_asset, open_asset):
        """
        Инициализирует предмет стола.

        Args:
            item_id (str): Идентификатор предмета.
            rect (tuple): Координаты и размеры (x, y, w, h).
            label (str): Текст подписи.
            callback (callable): Функция, вызываемая при клике.
            font (pygame.font.Font): Шрифт для подписи.
            closed_asset (str): Путь к закрытому ассету.
            open_asset (str): Путь к открытому ассету.
        """
        self.item_id = item_id
        self.rect = pygame.Rect(rect)
        self.label = label
        self.callback = callback
        self.font = font
        self.img_closed = AssetLoader.load(closed_asset, self.rect.size)
        self.img_open = AssetLoader.load(open_asset, self.rect.size)
        self.hovered = False

    def handle_event(self, event):
        """
        Обрабатывает события pygame для предмета стола.

        Args:
            event (pygame.event.Event): Событие pygame.

        Returns:
            bool: True, если клик был обработан.
        """
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.callback()
                return True
        return False

    def draw(self, screen, is_open):
        """
        Отрисовывает предмет стола в текущем состоянии.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
            is_open (bool): True для открытого состояния.
        """
        img = self.img_open if is_open else self.img_closed
        screen.blit(img, self.rect.topleft)
        if not self.hovered:
            return
        pygame.draw.rect(screen, (210, 210, 230), self.rect, 2, border_radius=8)
        label = self.font.render(self.label, True, (235, 235, 245))
        bg = pygame.Surface(
            (label.get_width() + 16, label.get_height() + 10),
            pygame.SRCALPHA
        )
        bg.fill((10, 10, 15, 190))
        x = self.rect.centerx - bg.get_width() // 2
        y = self.rect.top - bg.get_height() - 8
        if y < 0:
            y = self.rect.bottom + 8
        screen.blit(bg, (x, y))
        screen.blit(label, (x + 8, y + 5))


class HQSceneScreen(BaseScreen):
    """
    Экран сцены командного пункта.

    Отображает фон штаба, зависящий от пола персонажа игрока,
    предметы стола с двумя состояниями, хотспоты карты и адъютанта,
    кнопки управления. show_time_hud=True включает HUD времени.
    ESC эквивалентен переходу в главное меню с автосохранением.

    Attributes:
        bg (pygame.Surface): Фон штаба.
        desk_panel (pygame.Rect | None): Панель стола (для мужского фона).
        desk_items (list[DeskItem]): Предметы стола.
        map_img (pygame.Surface): Изображение карты в углу.
        map_spot (Hotspot): Хотспот карты.
        adjutant_spot (Hotspot): Хотспот адъютанта.
        btn_menu (Button): Кнопка «Главное меню».
        btn_actions (Button): Кнопка «Действия».
        btn_wait (Button): Кнопка «Ждать 30 мин».
        btn_logistics (Button): Кнопка «Логистика».
    """

    escape_action = "custom"
    show_time_hud = True

    def __init__(self, app):
        """
        Инициализирует сцену КП.

        Выбирает фон по полу игрока, создаёт предметы стола,
        хотспоты и кнопки управления.

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app)
        gender = getattr(app.engine.state, "player_gender", "male")
        bg_name = (
            "scenes/hq_adjutant_male"
            if gender == "female"
            else "scenes/hq_adjutant_female"
        )
        self.bg = AssetLoader.load(bg_name, (1280, 720))
        if bg_name == "scenes/hq_adjutant_male":
            self.desk_panel = MALE_DESK_PANEL_RECT
            layout = MALE_DESK_SLOTS
        else:
            self.desk_panel = None
            layout = DESK_ITEMS
        self.btn_menu = Button(
            (20, 20, 150, 40),
            "Главное меню",
            app.font_small,
            self.go_to_main_menu
        )
        self.btn_actions = Button(
            (20, 640, 170, 36),
            "Действия",
            app.font_small,
            self.open_actions
        )
        self.btn_wait = Button(
            (20, 680, 170, 36),
            "Ждать 30 мин",
            app.font_small,
            self.wait_half_hour
        )
        self.btn_logistics = Button(
            (20, 600, 170, 36),
            "Логистика",
            app.font_small,
            self.open_logistics
        )
        self.desk_items = []
        for item_id, label, rect, closed_asset, open_asset in layout:
            self.desk_items.append(
                DeskItem(
                    item_id,
                    rect,
                    label,
                    self._make_opener(item_id),
                    app.font_small,
                    closed_asset,
                    open_asset,
                )
            )
        self.map_img = AssetLoader.load("items/map", MAP_CORNER_SIZE)
        self.map_spot = Hotspot(
            MAP_SPOT_RECT,
            "Карта",
            self.open_map,
            app.font_small
        )
        self.adjutant_spot = Hotspot(
            ADJUTANT_RECT,
            "Обратиться к адъютанту",
            self.open_adjutant,
            app.font_small
        )
        logger.info(
            "Сцена КП инициализирована: фон=%s, предметов=%d",
            bg_name,
            len(self.desk_items),
        )

    def _make_opener(self, item_id):
        """
        Создаёт callback для открытия оверлея по идентификатору предмета.

        Args:
            item_id (str): Идентификатор предмета стола.

        Returns:
            callable: Функция, открывающая соответствующий оверлей.
        """
        def opener():
            if item_id == "notebook":
                self.open_notebook()
            elif item_id == "binoculars":
                self.open_binoculars()
            elif item_id == "radio":
                self.open_radio()
            elif item_id == "map":
                self.open_map()
            elif item_id == "documents":
                self.open_documents()
        return opener

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
        Формирует строку автодонесения о подразделении.

        Включает личный состав, потери, технику и текущий приказ.

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
            parts.append(f"потери {st.read_voltage(idx, 'U_casualties'):.0%}")
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

    def go_to_main_menu(self):
        """
        Переходит в главное меню с автосохранением.

        Исключения автосохранения подавляются, чтобы не блокировать
        выход в меню.
        """
        logger.info("КП: переход в главное меню")
        try:
            self.app.save_game("autosave")
        except Exception as e:
            logger.error("Ошибка автосохранения: %s", e)
        from .main_menu import MainMenuScreen
        self.app.manager.replace_all(MainMenuScreen(self.app))

    def on_escape(self):
        """Обрабатывает ESC как переход в главное меню."""
        logger.info("КП: обработан ESC")
        self.go_to_main_menu()

    def open_actions(self):
        """Открывает меню действий игрока."""
        logger.info("КП: открытие меню действий")
        self.app.open_action_menu()

    def wait_half_hour(self):
        """Выполняет действие ожидания 30 минут через TimeSystem."""
        ts = getattr(self.app, "time_system", None)
        if ts is None:
            return
        if "wait_30" not in ts.actions:
            return
        logger.info("КП: ожидание 30 минут")
        self.app.execute_player_action("wait_30")

    def open_logistics(self):
        """Открывает оверлей логистики."""
        logger.info("КП: открытие оверлея логистики")
        from ..ui.overlays import LogisticsOverlay
        self.app.manager.push(LogisticsOverlay(self.app))

    def open_notebook(self):
        """Открывает оверлей блокнота."""
        logger.info("КП: открытие оверлея блокнота")
        from ..ui.overlays import NotebookOverlay
        self.app.manager.push(NotebookOverlay(self.app))

    def open_binoculars(self):
        """Открывает оверлей бинокля."""
        logger.info("КП: открытие бинокля")
        from ..ui.overlays import BinocularsOverlay
        self.app.manager.push(BinocularsOverlay(self.app))

    def open_radio(self):
        """
        Запускает связь по рации.

        Выполняет действие radio_contact, после завершения которого
        открывает оверлей рации.
        """
        logger.info("КП: запуск связи по рации")
        self.app.execute_player_action(
            "radio_contact",
            on_completed=lambda: self.app.manager.push(
                RadioOverlay(self.app)
            ),
        )

    def open_map(self):
        """Открывает экран карты."""
        logger.info("КП: открытие экрана карты")
        from .map_screen import MapScreen
        self.app.manager.push(MapScreen(self.app))

    def open_adjutant(self):
        """Открывает экран приказов адъютанту."""
        logger.info("КП: открытие экрана приказов адъютанту")
        from .adjutant_orders import AdjutantOrdersScreen
        self.app.manager.push(AdjutantOrdersScreen(self.app))

    def open_documents(self):
        """
        Открывает экран документов с автодонесением.

        Генерирует оперативную сводку по всем военным юнитам
        и добавляет её в начало списка документов.
        """
        logger.info("КП: открытие экрана документов")
        from .documents import DocumentsScreen
        st = self.app.engine.state
        report = {
            "title": "ОПЕРАТИВНАЯ СВОДКА (автодонесение)",
            "lines": [
                self._unit_report_line(st, i)
                for i in range(st.count)
                if st.class_configs[st.class_ids[i]].class_name == "military_unit"
            ],
        }
        docs = [report] + list(self.app.content.documents)
        self.app.manager.push(DocumentsScreen(self.app, docs))

    def handle_event(self, event):
        """
        Обрабатывает события pygame для сцены КП.

        Порядок обработки: кнопки управления → предметы стола →
        хотспот карты → хотспот адъютанта.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.btn_menu.handle_event(event):
            return
        if self.btn_actions.handle_event(event):
            return
        if self.btn_wait.handle_event(event):
            return
        if self.btn_logistics.handle_event(event):
            return
        for item in self.desk_items:
            if item.handle_event(event):
                return
        if self.map_spot.handle_event(event):
            return
        self.adjutant_spot.handle_event(event)

    def draw(self, screen):
        """
        Отрисовывает сцену КП.

        Порядок: фон → панель стола (если есть) → предметы стола →
        карта в углу → хотспоты → кнопки управления.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        screen.blit(self.bg, (0, 0))
        if self.desk_panel is not None:
            pygame.draw.rect(screen, (28, 24, 20), self.desk_panel)
            pygame.draw.rect(screen, (90, 80, 60), self.desk_panel, 2, border_radius=6)
        for item in self.desk_items:
            item.draw(screen, self._is_item_open(item.item_id))
        if self.map_img:
            screen.blit(self.map_img, MAP_CORNER_POS)
        self.map_spot.draw(screen)
        self.adjutant_spot.draw(screen)
        self.btn_menu.draw(screen)
        self.btn_actions.draw(screen)
        self.btn_wait.draw(screen)
        self.btn_logistics.draw(screen)

    def _is_item_open(self, item_id):
        """
        Проверяет, открыт ли предмет стола по наличию оверлея в стеке.

        Args:
            item_id (str): Идентификатор предмета.

        Returns:
            bool: True, если соответствующий оверлей в стеке.
        """
        open_classes = {
            "documents": "DocumentsScreen",
            "notebook": "NotebookOverlay",
            "binoculars": "BinocularsOverlay",
            "radio": "RadioOverlay",
        }
        class_name = open_classes.get(item_id)
        if class_name is None:
            return False
        return any(
            type(s).__name__ == class_name
            for s in self.app.manager.stack
        )