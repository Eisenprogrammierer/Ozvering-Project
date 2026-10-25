"""
view/screens/map_screen.py

Экран карты.

Отображает топографическую основу из .npz-карты, маркеры подразделений
в виде NATO-подобных значков, повёрнутых на 360 градусов по направлению
на ближайшего противника (при отсутствии противника — по heading
подразделения). Значки разводятся по слотам детерминированным
алгоритмом разрешения коллизий, поэтому не налегают друг на друга;
та же разводка используется для выбора подразделения кликом и для
линий боестолкновений. Две соприкасающиеся линии фронта с небольшим
зазором: красная — сторона игрока, синяя — сторона противника.
Короткий клик выбирает подразделение, протягивание мышью рисует
стрелку приказа; утверждённый приказ применяется к выбранному
подразделению и всем его подчинённым (групповой приказ).
Линии фронта кэшируются и пересчитываются только при изменении
номера текущего тика. Для приказа «move» целевая точка стрелки
сохраняется через engine.set_move_target для каждого юнита группы,
чтобы обеспечить движение к заданной точке.

События экрана записываются в журнал operation_ozverin.log и
дублируются в консоль.
"""

import math
import os

import pygame

from ..ui.asset_loader import AssetLoader
from ..ui.screen_manager import BaseScreen
from ..ui.widgets import Button
from view.support.log_journal import get_logger

logger = get_logger("view.map_screen")

MAP_RECT = pygame.Rect(40, 40, 900, 640)
LEGEND_RECT = pygame.Rect(40, 686, 900, 30)
UNIT_ICON_SIZE = (26, 16)
SLOT_PAD_X = 8
SLOT_PAD_Y = 8
KNOWN_FACTIONS = ("player", "enemy", "neutral")
ORDERS_PER_PAGE = 8
INFO_MAX_WIDTH = 312
FRONT_BLOCK = 4
FRONT_RADIUS = 24.0
FRONT_GAP_HALF = 1.0
FRONT_CHAIKIN_ITERATIONS = 4
FRONT_LINE_WIDTH = 2
FRONT_COLOR_PLAYER = (225, 70, 70)
FRONT_COLOR_ENEMY = (70, 130, 225)
ENGAGEMENT_COLOR = (255, 80, 80)
CLICK_RADIUS = 10
PICK_RADIUS = 18
SLOT_SEARCH_RADIUS = 7
HEADING_ANGLES = {
    0: 0.0,
    1: 90.0,
    2: 180.0,
    3: 270.0,
    4: 0.0,
    5: 180.0,
}
SIZE_TO_ICON = {
    0: "company",
    1: "company",
    2: "battalion",
    3: "regiment",
    4: "brigade",
    5: "division",
    6: "division",
    7: "division",
}
BIOME_PALETTE = {
    1: (90, 130, 190),
    2: (170, 200, 140),
    3: (140, 170, 110),
    4: (120, 110, 100),
    5: (90, 140, 90),
    6: (200, 190, 140),
    7: (110, 130, 110),
    8: (200, 210, 220),
    9: (130, 115, 115),
    10: (175, 160, 120),
}
BIOME_LEGEND = (
    (1, "Вода"),
    (2, "Равнина"),
    (3, "Холмы"),
    (4, "Горы"),
    (5, "Лес"),
    (6, "Пустыня"),
    (7, "Болото"),
    (8, "Тундра"),
    (9, "Город"),
    (10, "Село"),
)


class MapScreen(BaseScreen):
    """
    Экран карты с рисованием приказов, легендой биомов, выбором
    подразделения кликом и двухполосной линией фронта.

    Значки подразделений разводятся по слотам без наложений;
    разводка детерминирована и одинакова для отрисовки, выбора
    кликом и линий боестолкновений.

    Attributes:
        order_types (list): Список типов приказов из контента.
        heights (numpy.ndarray): Карта высот.
        biomes (numpy.ndarray): Карта биомов.
        rows (int): Количество строк карты.
        cols (int): Количество столбцов карты.
        base (pygame.Surface): Отрендеренная базовая карта.
        orders (list): Список нарисованных приказов (type_index, points).
        drawing (list | None): Текущий рисуемый приказ или None.
        current_type (int): Индекс выбранного типа приказа.
        selected_unit (int): Позиция выбранного юнита в player_units.
        player_units (list): Список индексов юнитов игрока.
        order_buttons (list): Кнопки выбора типа приказа страницы.
        action_buttons (list): Кнопки утверждения и выхода.
        unit_icons (dict): Кэш базовых значков (faction, size).
        rot_icons (dict): Кэш повёрнутых значков (faction, size, угол).
        order_page (int): Индекс текущей страницы списка приказов.
        _front_cache (tuple | None): Кэш (линии игрока, линии противника).
        _front_cache_tick (int): Номер тика кэша линий фронта.
        _layout_cache (dict | None): Кэш разводки значков idx -> (x, y).
        _layout_cache_tick (int): Номер тика кэша разводки.
    """

    def __init__(self, app):
        """
        Инициализирует экран карты.

        Загружает карту, строит базовую топографию, создаёт кнопки
        управления приказами и инициализирует кэши значков, линий
        фронта и разводки слотов.

        Args:
            app: Экземпляр приложения (App).
        """
        super().__init__(app)
        self.order_types = app.content.order_types
        from view.support.scenario import load_map

        st = app.engine.state
        map_name = getattr(st, "map_name", None) or "valley_01"
        self.heights, self.biomes = load_map(map_name)
        self.rows, self.cols = self.heights.shape
        self.base = self._render_base()
        self.orders = []
        self.drawing = None
        self._press_pos = None
        self.current_type = 0
        self.selected_unit = 0
        self.unit_icons = {}
        self.rot_icons = {}
        self.order_page = 0
        self._front_cache = None
        self._front_cache_tick = -1
        self._layout_cache = None
        self._layout_cache_tick = -1
        self.player_units = [
            i
            for i in range(st.count)
            if st.class_configs[st.class_ids[i]].class_name == "military_unit"
            and st.factions[i] == "player"
        ]
        self.order_prev_btn = Button(
            (960, 120, 130, 28), "< Прик.", app.font_small, self.prev_order_page
        )
        self.order_next_btn = Button(
            (1110, 120, 130, 28), "Прик. >", app.font_small, self.next_order_page
        )
        self._build_order_buttons()
        self.action_buttons = [
            Button(
                (960, 520, 280, 40),
                "Утвердить приказы",
                app.font_body,
                self.confirm,
            ),
            Button((960, 570, 280, 40), "Назад", app.font_body, app.manager.pop),
        ]
        logger.info(
            "Экран карты: карта=%s, размер=%dx%d, юнитов игрока=%d, приказов=%d",
            map_name,
            self.cols,
            self.rows,
            len(self.player_units),
            len(self.order_types),
        )

    def _get_unit_size(self, manpower):
        """
        Определяет размер тактической единицы по фактической численности.

        Args:
            manpower (float): Фактическая численность личного состава.

        Returns:
            str: Размер единицы (company, battalion, regiment, brigade, division).
        """
        if manpower < 300:
            return "company"
        if manpower < 1000:
            return "battalion"
        if manpower < 3000:
            return "regiment"
        if manpower < 7000:
            return "brigade"
        return "division"

    def _unit_size_name(self, st, idx, config):
        """
        Возвращает имя размера значка для сущности.

        Приоритет — сегмент size конкретной сущности; при его
        отсутствии — фактическая численность U_manpower.

        Args:
            st: Состояние игрового мира (WorldState).
            idx (int): Индекс сущности.
            config: Конфигурация класса сущности.

        Returns:
            str: Имя размера (company..division).
        """
        if "size" in config.segment_layout.segments:
            size_idx = st.read_segment(idx, "size")
            name = SIZE_TO_ICON.get(size_idx)
            if name is not None:
                return name
        ch_man = config.voltage_layout.channel_index.get("U_manpower")
        if ch_man is not None:
            manpower = float(st.read_voltage(idx, "U_manpower"))
        else:
            manpower = 0.0
        return self._get_unit_size(manpower)

    def _tactical_of(self, st, idx):
        """
        Возвращает тактическое обозначение подразделения.

        Args:
            st: Состояние игрового мира (WorldState).
            idx (int): Индекс сущности.

        Returns:
            str: Обозначение вида «III-I-127».
        """
        tids = getattr(st, "tactical_ids", None)
        if tids is not None and idx < len(tids) and tids[idx]:
            return tids[idx]
        config = st.class_configs[st.class_ids[idx]]
        label = st.label_of(idx)
        ch_man = config.voltage_layout.channel_index.get("U_manpower")
        manpower = (
            float(st.read_voltage(idx, "U_manpower")) if ch_man is not None else 0.0
        )
        label_l = label.lower()
        echelon = None
        for kw, rom in (
            ("дивизия", "V"),
            ("бригада", "IV"),
            ("полк", "III"),
            ("батальон", "II"),
            ("рота", "I"),
        ):
            if kw in label_l:
                echelon = rom
                break
        if echelon is None:
            if manpower >= 7000:
                echelon = "V"
            elif manpower >= 3000:
                echelon = "IV"
            elif manpower >= 1000:
                echelon = "III"
            elif manpower >= 300:
                echelon = "II"
            else:
                echelon = "I"
        branch = "I"
        for kw, rom in (
            ("танк", "II"),
            ("арт", "III"),
            ("развед", "IV"),
            ("штаб", "V"),
            ("пехот", "I"),
            ("мотострел", "I"),
        ):
            if kw in label_l:
                branch = rom
                break
        digits = ""
        for ch in label:
            if ch.isdigit():
                digits += ch
        number = int(digits) if digits else 0
        return f"{echelon}-{branch}-{number}"

    def _display_name(self, st, idx):
        """
        Возвращает ролевое имя подразделения: тактический индекс плюс
        роль внутри дивизии (хвост метки после метки корня). Для
        корневой сущности возвращает человекочитаемую метку.

        Args:
            st: Состояние игрового мира (WorldState).
            idx (int): Индекс сущности.

        Returns:
            str: Ролевое имя для интерфейса.
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
            tail = label[len(root_label) :].strip()
        tid = self._tactical_of(st, idx)
        if tail:
            return f"{tid} · {tail}"
        return label

    def _subordinate_indices(self, st, root_idx):
        """
        Возвращает множество индексов подчинённых сущностей корня.

        Args:
            st: Состояние игрового мира (WorldState).
            root_idx (int): Индекс корневой сущности.

        Returns:
            set[int]: Множество индексов подчинённых.
        """
        result = set()
        stack = [root_idx]
        while stack:
            cur = stack.pop()
            for i in range(st.count):
                if st.parent_ids[i] == cur and i not in result:
                    result.add(i)
                    stack.append(i)
        return result

    def _is_dead_unit(self, st, idx):
        """
        Проверяет, уничтожено ли подразделение.

        Args:
            st: Состояние игрового мира (WorldState).
            idx (int): Индекс сущности.

        Returns:
            bool: True, если подразделение уничтожено.
        """
        cfg = st.class_configs[st.class_ids[idx]]
        if "condition" in cfg.segment_layout.segments:
            if st.read_segment(idx, "condition") == 0:
                return True
        ch = cfg.voltage_layout.channel_index.get("U_manpower")
        if ch is not None and st.read_voltage(idx, "U_manpower") <= 0:
            return True
        return False

    @staticmethod
    def _wrap_width(text, font, max_w, max_lines=2):
        """
        Переносит текст по ширине, не более max_lines строк.

        Args:
            text (str): Исходный текст.
            font (pygame.font.Font): Шрифт для измерения ширины.
            max_w (int): Максимальная ширина строки в пикселях.
            max_lines (int): Максимальное число строк.

        Returns:
            list[str]: Список строк.
        """
        lines, line = [], ""
        for w in text.split():
            test = (line + " " + w).strip()
            if font.size(test)[0] > max_w:
                lines.append(line)
                line = w
            else:
                line = test
        lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            lines[-1] = last[:-3] + "..." if len(last) > 3 else last + "..."
        return lines

    def _order_page_count(self):
        """
        Возвращает число страниц списка приказов.

        Returns:
            int: Число страниц (не меньше 1).
        """
        return max(1, (len(self.order_types) + ORDERS_PER_PAGE - 1) // ORDERS_PER_PAGE)

    def _build_order_buttons(self):
        """Перестраивает кнопки приказов для текущей страницы."""
        self.order_buttons = []
        start = self.order_page * ORDERS_PER_PAGE
        end = min(start + ORDERS_PER_PAGE, len(self.order_types))
        y = 156
        for i in range(start, end):
            ot = self.order_types[i]
            btn = Button(
                (960, y, 280, 30),
                ot["label"],
                self.app.font_small,
                lambda i=i: self.set_type(i),
            )
            btn.order_index = i
            self.order_buttons.append(btn)
            y += 34

    def prev_order_page(self):
        """Переключает список приказов на предыдущую страницу."""
        if self.order_page > 0:
            self.order_page -= 1
            self._build_order_buttons()
            logger.debug("Список приказов: страница %d", self.order_page + 1)

    def next_order_page(self):
        """Переключает список приказов на следующую страницу."""
        if self.order_page < self._order_page_count() - 1:
            self.order_page += 1
            self._build_order_buttons()
            logger.debug("Список приказов: страница %d", self.order_page + 1)

    def set_type(self, i):
        """
        Устанавливает текущий тип приказа для рисования.

        Args:
            i (int): Индекс типа приказа в списке order_types.
        """
        self.current_type = i
        logger.debug("Выбран тип приказа: %s", self.order_types[i]["id"])

    def confirm(self):
        """
        Утверждает последний нарисованный приказ для выбранного
        подразделения и всех его подчинённых (групповой приказ).

        Если приказ имеет тип «move» и последняя нарисованная стрелка
        содержит точки, то для каждого подразделения в группе
        устанавливается целевая точка через engine.set_move_target,
        чтобы обеспечить движение к указанной точке.

        После применения приказов экран карты закрывается, и при
        наличии time_system запускается действие планирования приказов.
        """
        st = self.app.engine.state
        if not self.player_units or not self.orders:
            self.app.manager.pop()
            return
        planned = len(self.orders)
        target_idx = self.player_units[self.selected_unit % len(self.player_units)]
        last_order_type_idx = self.orders[-1][0]
        order_id = self.order_types[last_order_type_idx]["id"]
        order_label = self.order_types[last_order_type_idx]["label"]
        group = [target_idx]
        group += sorted(self._subordinate_indices(st, target_idx))
        assigned = 0
        # Определим целевую точку для приказа «move», если она есть
        move_target = None
        if order_id == "move" and self.orders:
            last_order_points = self.orders[-1][1]
            if last_order_points and len(last_order_points) >= 2:
                # последняя точка стрелки
                move_target = last_order_points[-1]
                # преобразуем экранные координаты в координаты карты
                # но в движок нужно передать координаты в клетках карты
                # мы храним точки в экранных координатах, нужно перевести
                # используем обратное преобразование
                cw = MAP_RECT.width / self.cols
                ch = MAP_RECT.height / self.rows
                mx = (move_target[0] - MAP_RECT.x) / cw - 0.5
                my = (move_target[1] - MAP_RECT.y) / ch - 0.5
                move_target = (int(round(mx)), int(round(my)))
                # ограничим границами
                move_target = (
                    max(0, min(self.cols - 1, move_target[0])),
                    max(0, min(self.rows - 1, move_target[1])),
                )
        for idx in group:
            if self._is_dead_unit(st, idx):
                continue
            if self.app.engine.assign_order(idx, order_id):
                assigned += 1
                if order_id == "move" and move_target is not None:
                    self.app.engine.set_move_target(idx, move_target)
        st.log_event(
            target_idx,
            f"{st.label_of(target_idx)}: приказ «{order_label}» "
            f"применён к группе из {assigned} подразделений",
        )
        if order_id == "move" and move_target is not None:
            logger.info(
                "%s: приказ «%s» применён к группе из %d подразделений, цель=(%d, %d)",
                st.label_of(target_idx),
                order_label,
                assigned,
                move_target[0],
                move_target[1],
            )
        else:
            logger.info(
                "%s: приказ «%s» применён к группе из %d подразделений",
                st.label_of(target_idx),
                order_label,
                assigned,
            )
        self.app.manager.pop()
        ts = getattr(self.app, "time_system", None)
        if ts is not None:
            action_id = ts.register_order_planning_action(planned)
            self.app.execute_player_action(action_id)

    def _load_unit_icon(self, faction, size):
        """
        Загружает NATO-подобный значок подразделения нужного размера
        из assets/images/<faction>/<size>.

        Args:
            faction (str): Фракция подразделения.
            size (str): Размер тактической единицы.

        Returns:
            pygame.Surface | None: Значок подразделения или None.
        """
        base = os.path.join(AssetLoader.IMAGES_DIR, faction, size)
        for ext in ("", ".png", ".jpg", ".jpeg"):
            if os.path.exists(base + ext):
                return AssetLoader.load(f"{faction}/{size}", UNIT_ICON_SIZE)
        return None

    def _unit_icon(self, faction, size):
        """
        Возвращает базовый значок подразделения из кэша, при отсутствии
        загружает и кэширует его.

        Args:
            faction (str): Фракция подразделения.
            size (str): Размер тактической единицы.

        Returns:
            pygame.Surface | None: Значок подразделения или None.
        """
        key = (faction, size)
        if key not in self.unit_icons:
            self.unit_icons[key] = self._load_unit_icon(faction, size)
        return self.unit_icons[key]

    def _rotated_icon(self, faction, size, icon, angle):
        """
        Возвращает значок, повёрнутый на заданный угол по часовой
        стрелке, из кэша повёрнутых значков; при отсутствии поворачивает
        и кэширует. Угол округляется до целого градуса для ключа кэша.

        Args:
            faction (str): Фракция подразделения.
            size (str): Размер тактической единицы.
            icon (pygame.Surface): Базовый значок, направленный на север.
            angle (float): Угол по часовой стрелке от севера в градусах.

        Returns:
            pygame.Surface: Повёрнутый значок.
        """
        key = (faction, size, int(round(angle)) % 360)
        if key not in self.rot_icons:
            self.rot_icons[key] = pygame.transform.rotate(icon, -angle)
        return self.rot_icons[key]

    def _unit_angle(self, st, idx):
        """
        Возвращает непрерывный угол направления значка в градусах
        (0 — север, по часовой стрелке). Направление вычисляется как
        геометрический курс на ближайшего живого противника; при
        отсутствии противника используется heading подразделения.

        Args:
            st: Состояние игрового мира (WorldState).
            idx (int): Индекс сущности.

        Returns:
            float: Угол в градусах [0, 360).
        """
        x = float(st.coords[idx, 0])
        y = float(st.coords[idx, 1])
        best_d = None
        best_v = None
        for j in range(st.count):
            if j == idx or st.factions[j] == st.factions[idx]:
                continue
            if self._is_dead_unit(st, j):
                continue
            dx = float(st.coords[j, 0]) - x
            dy = float(st.coords[j, 1]) - y
            d = dx * dx + dy * dy
            if best_d is None or d < best_d:
                best_d = d
                best_v = (dx, dy)
        if best_v is None:
            return HEADING_ANGLES.get(int(st.headings[idx]), 0.0)
        dx, dy = best_v
        return math.degrees(math.atan2(dx, -dy)) % 360.0

    @staticmethod
    def _resolve_slot(px, py, occupied, grid_cols, grid_rows, slot_w, slot_h):
        """
        Подбирает свободный экранный слот для значка подразделения.

        Желаемый слот вычисляется из истинных координат; если слот
        занят, ищется ближайший свободный слот кольцевым обходом,
        поэтому значки не налегают друг на друга.

        Args:
            px (int): Желаемая координата X центра значка.
            py (int): Желаемая координата Y центра значка.
            occupied (set): Множество занятых слотов (gx, gy).
            grid_cols (int): Число слотов по горизонтали.
            grid_rows (int): Число слотов по вертикали.
            slot_w (int): Ширина слота в пикселях.
            slot_h (int): Высота слота в пикселях.

        Returns:
            tuple[int, int]: Координаты выбранного слота (gx, gy).
        """
        gx = (px - MAP_RECT.x) // slot_w
        gy = (py - MAP_RECT.y) // slot_h
        gx = min(max(gx, 0), grid_cols - 1)
        gy = min(max(gy, 0), grid_rows - 1)
        if (gx, gy) not in occupied:
            occupied.add((gx, gy))
            return gx, gy
        for radius in range(1, SLOT_SEARCH_RADIUS + 1):
            candidates = []
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    nx = gx + dx
                    ny = gy + dy
                    if 0 <= nx < grid_cols and 0 <= ny < grid_rows:
                        if (nx, ny) not in occupied:
                            candidates.append((dx * dx + dy * dy, nx, ny))
            if candidates:
                candidates.sort()
                _, nx, ny = candidates[0]
                occupied.add((nx, ny))
                return nx, ny
        occupied.add((gx, gy))
        return gx, gy

    def _get_layout(self, st):
        """
        Возвращает детерминированную разводку значков: отображение
        индекса сущности на экранные координаты центра значка.

        Результат кэшируется по номеру текущего тика; порядок обхода
        сущностей фиксирован, поэтому разводка одинакова для отрисовки,
        выбора кликом и линий боестолкновений.

        Args:
            st: Состояние игрового мира (WorldState).

        Returns:
            dict[int, tuple[int, int]]: Разводка значков.
        """
        current_tick = st.current_tick
        if (
            self._layout_cache is not None
            and self._layout_cache_tick == current_tick
        ):
            return self._layout_cache
        cw = MAP_RECT.width / self.cols
        ch = MAP_RECT.height / self.rows
        slot_w = UNIT_ICON_SIZE[0] + SLOT_PAD_X
        slot_h = UNIT_ICON_SIZE[1] + SLOT_PAD_Y
        grid_cols = max(1, MAP_RECT.width // slot_w)
        grid_rows = max(1, MAP_RECT.height // slot_h)
        occupied = set()
        layout = {}
        for i in range(st.count):
            config = st.class_configs[st.class_ids[i]]
            if config.class_name != "military_unit":
                continue
            if self._is_dead_unit(st, i):
                continue
            x, y = st.coords[i]
            if not (0 <= x < self.cols and 0 <= y < self.rows):
                continue
            px = MAP_RECT.x + int((x + 0.5) * cw)
            py = MAP_RECT.y + int((y + 0.5) * ch)
            gx, gy = self._resolve_slot(
                px, py, occupied, grid_cols, grid_rows, slot_w, slot_h
            )
            cx = MAP_RECT.x + gx * slot_w + slot_w // 2
            cy = MAP_RECT.y + gy * slot_h + slot_h // 2
            layout[i] = (cx, cy)
        self._layout_cache = layout
        self._layout_cache_tick = current_tick
        return layout

    def _select_at(self, pos):
        """
        Выбирает ближайшее подразделение игрока по разводке значков.

        Если в радиусе подбора нет значков, выбор не меняется.

        Args:
            pos (tuple[int, int]): Экранные координаты клика.
        """
        st = self.app.engine.state
        layout = self._get_layout(st)
        best_slot = None
        best_d = float("inf")
        for slot, idx in enumerate(self.player_units):
            point = layout.get(idx)
            if point is None:
                continue
            d = math.hypot(point[0] - pos[0], point[1] - pos[1])
            if d < best_d:
                best_d = d
                best_slot = slot
        if best_slot is not None and best_d <= PICK_RADIUS:
            self.selected_unit = best_slot
            logger.info(
                "Выбрано подразделение: %s",
                st.label_of(self.player_units[best_slot]),
            )

    def _front_field(self, st):
        """
        Строит скалярное поле разности расстояний до ближайших своих
        и противника для узлов сетки. Значение определено только в
        зоне контакта; отрицательные значения — сторона игрока,
        положительные — сторона противника.

        Args:
            st: Состояние игрового мира (WorldState).

        Returns:
            tuple[list[list[float | None]], int] | tuple[None, None]:
            Кортеж (поле, размер блока) или (None, None).
        """
        players = []
        enemies = []
        for i in range(st.count):
            cfg = st.class_configs[st.class_ids[i]]
            if cfg.class_name != "military_unit":
                continue
            if self._is_dead_unit(st, i):
                continue
            pos = (float(st.coords[i, 0]), float(st.coords[i, 1]))
            if st.factions[i] == "player":
                players.append(pos)
            elif st.factions[i] == "enemy":
                enemies.append(pos)
        if not players or not enemies:
            return None, None
        block = FRONT_BLOCK
        gw = self.cols // block + 2
        gh = self.rows // block + 2
        field = []
        for gy in range(gh):
            cy = gy * block
            row = []
            for gx in range(gw):
                cx = gx * block
                dp = min(math.hypot(cx - ux, cy - uy) for ux, uy in players)
                de = min(math.hypot(cx - ux, cy - uy) for ux, uy in enemies)
                if min(dp, de) <= FRONT_RADIUS:
                    row.append(dp - de)
                else:
                    row.append(None)
            field.append(row)
        return field, block

    @staticmethod
    def _marching_segments(field, block):
        """Извлекает отрезки нулевого уровня поля методом marching squares."""

        def safe_div(a, b):
            d = a - b
            if d == 0:
                return 0.5
            return a / d

        gh = len(field)
        gw = len(field[0]) if gh else 0
        segments = []
        for gy in range(gh - 1):
            for gx in range(gw - 1):
                v0 = field[gy][gx]
                v1 = field[gy][gx + 1]
                v2 = field[gy + 1][gx + 1]
                v3 = field[gy + 1][gx]
                if None in (v0, v1, v2, v3):
                    continue
                case = (v0 > 0) << 3 | (v1 > 0) << 2 | (v2 > 0) << 1 | (v3 > 0)
                if case in (0, 15):
                    continue
                x0 = gx * block
                y0 = gy * block
                top = (x0 + block * safe_div(v0, v1), y0)
                right = (x0 + block, y0 + block * safe_div(v1, v2))
                bottom = (x0 + block * safe_div(v3, v2), y0 + block)
                left = (x0, y0 + block * safe_div(v0, v3))
                center = (v0 + v1 + v2 + v3) / 4.0
                pairs = {
                    1: [(left, bottom)],
                    2: [(bottom, right)],
                    3: [(left, right)],
                    4: [(top, right)],
                    6: [(top, bottom)],
                    7: [(top, left)],
                    8: [(top, left)],
                    9: [(top, bottom)],
                    11: [(top, right)],
                    12: [(left, right)],
                    13: [(bottom, right)],
                    14: [(left, bottom)],
                    5: [(top, left), (right, bottom)]
                    if center > 0
                    else [(top, right), (left, bottom)],
                    10: [(top, right), (left, bottom)]
                    if center > 0
                    else [(top, left), (right, bottom)],
                }
                segments.extend(pairs[case])
        return segments

    @staticmethod
    def _close_points(a, b):
        """
        Проверяет совпадение точек с точностью до 0.01 клетки.

        Args:
            a (tuple[float, float]): Первая точка.
            b (tuple[float, float]): Вторая точка.

        Returns:
            bool: True, если точки совпадают.
        """
        return abs(a[0] - b[0]) < 0.01 and abs(a[1] - b[1]) < 0.01

    def _chain_segments(self, segments):
        """
        Сшивает отрезки нулевого уровня в полилинии по совпадающим концам.

        Args:
            segments (list): Список отрезков.

        Returns:
            list[list[tuple[float, float]]]: Список полилиний.
        """
        remaining = [list(s) for s in segments]
        polylines = []
        while remaining:
            seg = remaining.pop()
            line = [seg[0], seg[1]]
            grew = True
            while grew:
                grew = False
                for i, other in enumerate(remaining):
                    if self._close_points(other[0], line[-1]):
                        line.append(other[1])
                        remaining.pop(i)
                        grew = True
                        break
                    if self._close_points(other[1], line[-1]):
                        line.append(other[0])
                        remaining.pop(i)
                        grew = True
                        break
                if grew:
                    continue
                for i, other in enumerate(remaining):
                    if self._close_points(other[1], line[0]):
                        line.insert(0, other[0])
                        remaining.pop(i)
                        grew = True
                        break
                    if self._close_points(other[0], line[0]):
                        line.insert(0, other[1])
                        remaining.pop(i)
                        grew = True
                        break
            polylines.append(line)
        return polylines

    @staticmethod
    def _chaikin(points, iterations=FRONT_CHAIKIN_ITERATIONS):
        """
        Сглаживает полилинию итерациями угла обрезания Чайкина.

        Args:
            points (list[tuple[float, float]]): Исходная полилиния.
            iterations (int): Число итераций сглаживания.

        Returns:
            list[tuple[float, float]]: Сглаженная полилиния.
        """
        for _ in range(iterations):
            if len(points) < 3:
                return points
            refined = [points[0]]
            for i in range(len(points) - 1):
                x0, y0 = points[i]
                x1, y1 = points[i + 1]
                refined.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
                refined.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
            refined.append(points[-1])
            points = refined
        return points

    def _front_polylines(self, st, cw, ch):
        """
        Строит две сглаженные полосы линии фронта в экранных
        координатах: красную на стороне игрока и синюю на стороне
        противника, с зазором между ними.

        Args:
            st: Состояние игрового мира (WorldState).
            cw (float): Ширина клетки карты в пикселях.
            ch (float): Высота клетки карты в пикселях.

        Returns:
            tuple[list, list]: Кортеж (полилинии игрока, полилинии
            противника) в экранных координатах.
        """
        field, block = self._front_field(st)
        if field is None:
            return [], []
        result = []
        for level in (-FRONT_GAP_HALF, FRONT_GAP_HALF):
            shifted = [
                [v - level if v is not None else None for v in row] for row in field
            ]
            segments = self._marching_segments(shifted, block)
            polylines = self._chain_segments(segments)
            smoothed = []
            for line in polylines:
                if len(line) < 3:
                    continue
                line = self._chaikin(line)
                smoothed.append(
                    [(MAP_RECT.x + x * cw, MAP_RECT.y + y * ch) for x, y in line]
                )
            result.append(smoothed)
        return result[0], result[1]

    @staticmethod
    def _dashed_line(screen, start, end, color, step=8, width=2):
        """
        Рисует пунктирную линию между двумя точками.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
            start (tuple[int, int]): Начальная точка.
            end (tuple[int, int]): Конечная точка.
            color (tuple): Цвет линии (R, G, B).
            step (int): Длина штриха в пикселях.
            width (int): Толщина линии.
        """
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 0:
            return
        n = max(1, int(length // step))
        for i in range(0, n, 2):
            p0 = (start[0] + dx * i / n, start[1] + dy * i / n)
            p1 = (start[0] + dx * (i + 1) / n, start[1] + dy * (i + 1) / n)
            pygame.draw.line(screen, color, p0, p1, width)

    def _draw_engagements(self, screen, layout):
        """
        Рисует линии боестолкновений по разводке значков: красный
        пунктир между сцепившимися подразделениями и крест в середине.

        Встречные бои одной пары рисуются один раз.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
            layout (dict): Разводка значков idx -> (x, y).
        """
        st = self.app.engine.state
        id_to_idx = {eid: i for i, eid in enumerate(st.entity_ids)}
        drawn = set()
        for eng in self.app.engine.engagements:
            if isinstance(eng, dict):
                a_id = eng.get("attacker")
                d_id = eng.get("defender")
            else:
                try:
                    a_id, d_id, _ = eng
                except Exception:
                    continue
            a = id_to_idx.get(a_id)
            d = id_to_idx.get(d_id)
            if a is None or d is None:
                continue
            pa = layout.get(a)
            pd = layout.get(d)
            if pa is None or pd is None:
                continue
            pair = (min(a, d), max(a, d))
            if pair in drawn:
                continue
            drawn.add(pair)
            self._dashed_line(screen, pa, pd, ENGAGEMENT_COLOR)
            mx = int((pa[0] + pd[0]) // 2)
            my = int((pa[1] + pd[1]) // 2)
            pygame.draw.line(
                screen, ENGAGEMENT_COLOR, (mx - 5, my - 5), (mx + 5, my + 5), 2
            )
            pygame.draw.line(
                screen, ENGAGEMENT_COLOR, (mx - 5, my + 5), (mx + 5, my - 5), 2
            )

    def _render_base(self):
        """
        Рендерит базовую топографическую карту по биомам.

        Returns:
            pygame.Surface: Поверхность с отрендеренной картой.
        """
        surf = pygame.Surface(MAP_RECT.size)
        cw = MAP_RECT.width / self.cols
        ch = MAP_RECT.height / self.rows
        for y in range(self.rows):
            for x in range(self.cols):
                biome_id = int(self.biomes[y, x])
                c = BIOME_PALETTE.get(biome_id, (170, 200, 140))
                pygame.draw.rect(
                    surf, c, (int(x * cw), int(y * ch), int(cw) + 1, int(ch) + 1)
                )
        for gx in range(0, MAP_RECT.width, 90):
            pygame.draw.line(surf, (120, 110, 90), (gx, 0), (gx, MAP_RECT.height), 1)
        for gy in range(0, MAP_RECT.height, 90):
            pygame.draw.line(surf, (120, 110, 90), (0, gy), (MAP_RECT.width, gy), 1)
        return surf

    def _draw_arrow(self, screen, points, color, dashed):
        """
        Рисует стрелку приказа по заданным точкам.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
            points (list): Список точек (x, y) стрелки.
            color (tuple): Цвет стрелки (R, G, B).
            dashed (bool): Если True, линия рисуется пунктиром.
        """
        if not points or len(points) < 2:
            return
        if dashed:
            for i in range(len(points) - 1):
                if i % 2 == 0:
                    pygame.draw.line(screen, color, points[i], points[i + 1], 3)
        else:
            pygame.draw.lines(screen, color, False, points, 3)
        a, b = points[-2], points[-1]
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        p1 = (b[0] - 14 * math.cos(ang - 0.5), b[1] - 14 * math.sin(ang - 0.5))
        p2 = (b[0] - 14 * math.cos(ang + 0.5), b[1] - 14 * math.sin(ang + 0.5))
        pygame.draw.polygon(screen, color, [b, p1, p2])

    def _draw_legend(self, screen):
        """
        Рисует панель легенды биомов под картой.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        panel = pygame.Surface(
            (LEGEND_RECT.width, LEGEND_RECT.height), pygame.SRCALPHA
        )
        panel.fill((20, 18, 14, 210))
        screen.blit(panel, LEGEND_RECT.topleft)
        pygame.draw.rect(screen, (90, 80, 60), LEGEND_RECT, 2, border_radius=4)
        x = LEGEND_RECT.x + 10
        cy = LEGEND_RECT.centery
        for biome_id, label in BIOME_LEGEND:
            color = BIOME_PALETTE[biome_id]
            pygame.draw.rect(screen, color, (x, cy - 6, 12, 12))
            pygame.draw.rect(screen, (60, 55, 45), (x, cy - 6, 12, 12), 1)
            text = self.app.font_small.render(label, True, (200, 200, 210))
            screen.blit(text, (x + 16, cy - text.get_height() // 2))
            x += 16 + text.get_width() + 14

    def handle_event(self, event):
        """
        Обрабатывает события pygame для экрана карты.

        Короткий клик выбирает подразделение игрока, протягивание
        мышью рисует стрелку приказа. Кнопки панелей обрабатываются
        в первую очередь.

        Args:
            event (pygame.event.Event): Событие pygame.
        """
        if self.order_prev_btn.handle_event(event):
            return
        if self.order_next_btn.handle_event(event):
            return
        for b in self.order_buttons:
            if b.handle_event(event):
                return
        for b in self.action_buttons:
            if b.handle_event(event):
                return
        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and MAP_RECT.collidepoint(event.pos)
        ):
            self._press_pos = event.pos
            self.drawing = [event.pos]
        elif event.type == pygame.MOUSEMOTION and self.drawing:
            dx = event.pos[0] - self.drawing[-1][0]
            dy = event.pos[1] - self.drawing[-1][1]
            if math.hypot(dx, dy) > 12:
                self.drawing.append(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.drawing:
            press = self._press_pos or self.drawing[0]
            drag = math.hypot(event.pos[0] - press[0], event.pos[1] - press[1])
            if len(self.drawing) >= 2 and drag > CLICK_RADIUS:
                self.orders.append((self.current_type, self.drawing[:]))
            else:
                self._select_at(press)
            self.drawing = None
            self._press_pos = None

    def draw(self, screen):
        """
        Отрисовывает экран карты.

        Порядок: базовая топография, легенда биомов, две полосы линии
        фронта, значки подразделений по слотам без наложений, подсветка
        выбранного подразделения и его подчинённых, линии боестолкновений,
        нарисованные приказы, текущий рисуемый приказ, кнопки управления
        и информация о цели приказа.

        Args:
            screen (pygame.Surface): Поверхность для отрисовки.
        """
        screen.fill((30, 25, 20))
        screen.blit(self.base, MAP_RECT.topleft)
        pygame.draw.rect(screen, (90, 80, 60), MAP_RECT, 3)
        self._draw_legend(screen)
        st = self.app.engine.state
        cw = MAP_RECT.width / self.cols
        ch = MAP_RECT.height / self.rows
        current_tick = st.current_tick
        if self._front_cache is None or self._front_cache_tick != current_tick:
            self._front_cache = self._front_polylines(st, cw, ch)
            self._front_cache_tick = current_tick
            logger.debug("Кэш линии фронта пересчитан: tick=%d", current_tick)
        player_lines, enemy_lines = self._front_cache
        for line in player_lines:
            if len(line) >= 2:
                pts = [(int(x), int(y)) for x, y in line]
                pygame.draw.lines(
                    screen, FRONT_COLOR_PLAYER, False, pts, FRONT_LINE_WIDTH
                )
        for line in enemy_lines:
            if len(line) >= 2:
                pts = [(int(x), int(y)) for x, y in line]
                pygame.draw.lines(
                    screen, FRONT_COLOR_ENEMY, False, pts, FRONT_LINE_WIDTH
                )
        layout = self._get_layout(st)
        icon_rects = {}
        for idx, (cx, cy) in layout.items():
            config = st.class_configs[st.class_ids[idx]]
            faction = st.factions[idx] if idx < len(st.factions) else "neutral"
            if faction not in KNOWN_FACTIONS:
                faction = "neutral"
            size = self._unit_size_name(st, idx, config)
            angle = self._unit_angle(st, idx)
            icon = self._unit_icon(faction, size)
            if icon is not None:
                rot = self._rotated_icon(faction, size, icon, angle)
                icon_rect = rot.get_rect(center=(cx, cy))
                screen.blit(rot, icon_rect)
            else:
                if faction == "player":
                    color = (80, 120, 220)
                elif faction == "enemy":
                    color = (220, 80, 80)
                else:
                    color = (200, 200, 200)
                icon_rect = pygame.Rect(cx - 7, cy - 4, 14, 8)
                pygame.draw.rect(screen, color, icon_rect, 2)
                pygame.draw.circle(screen, color, (cx, cy), 2)
            icon_rects[idx] = icon_rect
        target_idx = None
        if self.player_units:
            target_idx = self.player_units[
                self.selected_unit % len(self.player_units)
            ]
        if target_idx is not None:
            highlight = self._subordinate_indices(st, target_idx)
            for i in highlight:
                if i in icon_rects:
                    pygame.draw.rect(
                        screen, (255, 220, 80), icon_rects[i].inflate(4, 4), 1
                    )
            if target_idx in icon_rects:
                pygame.draw.rect(
                    screen, (255, 255, 255), icon_rects[target_idx].inflate(8, 8), 2
                )
        self._draw_engagements(screen, layout)
        for t, pts in self.orders:
            ot = self.order_types[t]
            color = tuple(ot.get("color", [220, 220, 220]))
            dashed = bool(ot.get("dashed", False))
            self._draw_arrow(screen, pts, color, dashed)
        if self.drawing and len(self.drawing) >= 2:
            ot = self.order_types[self.current_type]
            color = tuple(ot.get("color", [220, 220, 220]))
            dashed = bool(ot.get("dashed", False))
            self._draw_arrow(screen, self.drawing, color, dashed)
        self.order_prev_btn.draw(screen)
        self.order_next_btn.draw(screen)
        for b in self.order_buttons:
            b.draw(screen)
            if getattr(b, "order_index", -1) == self.current_type:
                pygame.draw.rect(screen, (220, 220, 230), b.rect, 2, border_radius=6)
        cur_ot = self.order_types[self.current_type] if self.order_types else {}
        meta_bits = []
        if int(cur_ot.get("duration", 0)) > 0:
            meta_bits.append(f"Длит: {cur_ot.get('duration')}")
        cost = cur_ot.get("resource_cost") or {}
        if cost:
            cost_str = ", ".join(f"{k}:{v}" for k, v in cost.items())
            meta_bits.append(f"Цена: {cost_str}")
        if meta_bits:
            meta_surf = self.app.font_small.render(
                " | ".join(meta_bits), True, (200, 180, 120)
            )
            screen.blit(meta_surf, (960, 490))
        for b in self.action_buttons:
            b.draw(screen)
        if target_idx is not None:
            group_size = 1 + len(self._subordinate_indices(st, target_idx))
            info_text = (
                f"Цель приказа: {self._display_name(st, target_idx)} "
                f"(в группе: {group_size})"
            )
        else:
            info_text = "Нет доступных юнитов игрока"
        y = 88
        for line in self._wrap_width(info_text, self.app.font_small, INFO_MAX_WIDTH):
            screen.blit(
                self.app.font_small.render(line, True, (200, 200, 210)),
                (960, y),
            )
            y += 18
        hint = "Клик — выбор подразделения, протяжка — стрелка приказа"
        for line in self._wrap_width(hint, self.app.font_small, INFO_MAX_WIDTH):
            screen.blit(
                self.app.font_small.render(line, True, (140, 140, 150)),
                (960, y),
            )
            y += 18