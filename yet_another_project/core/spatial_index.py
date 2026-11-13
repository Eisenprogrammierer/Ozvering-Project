"""
core/spatial_index.py

Пространственный индекс для быстрого поиска сущностей по координатам.

Реализует сеточный индекс (grid index) с фиксированным размером ячейки
для ускорения пространственных запросов: поиск в радиусе, поиск
ближайших соседей, перечисление сущностей в прямоугольной области.
Поддерживает инкрементальное обновление при перемещении сущностей
без полной перестройки индекса.

Класс SpatialIndex хранит сущности в словаре ячеек, где ключ —
кортеж (cell_x, cell_y). Каждая ячейка содержит множество индексов
сущностей. Методы поиска возвращают индексы сущностей, удовлетворяющих
пространственному критерию, без фильтрации по типу или фракции —
фильтрация выполняется вызывающим кодом.

События модуля записываются в журнал operation_ozverin.log и
дублируются в консоль средствами core.log_journal.
"""

from typing import Dict, List, Set, Tuple

from .log_journal import get_logger

logger = get_logger("core.spatial_index")

DEFAULT_CELL_SIZE = 16


class SpatialIndex:
    """
    Сеточный пространственный индекс.

    Ускоряет пространственные запросы за счёт разбиения мира на
    ячейки фиксированного размера. Поддерживает добавление,
    удаление, перемещение сущностей и три типа запросов:
    по радиусу, по прямоугольнику и k ближайших соседей.

    Attributes:
        cell_size: Размер ячейки сетки в клетках мира.
        grid: Словарь {(cell_x, cell_y): set(entity_indices)}.
    """

    def __init__(self, cell_size: int = DEFAULT_CELL_SIZE):
        """
        Инициализирует пространственный индекс.

        Args:
            cell_size: Размер ячейки сетки в клетках мира.
                По умолчанию 16.
        """
        self.cell_size = max(1, int(cell_size))
        self.grid: Dict[Tuple[int, int], Set[int]] = {}
        logger.debug(
            "SpatialIndex инициализирован: cell_size=%d", self.cell_size
        )

    def _cell_coords(self, x: int, y: int) -> Tuple[int, int]:
        """
        Вычисляет координаты ячейки для заданных мировых координат.

        Использует целочисленное деление с округлением вниз.

        Args:
            x: Мировая координата X.
            y: Мировая координата Y.

        Returns:
            tuple[int, int]: Координаты ячейки (cell_x, cell_y).
        """
        return (x // self.cell_size, y // self.cell_size)

    def add(self, idx: int, x: int, y: int):
        """
        Добавляет сущность в индекс по координатам.

        Если сущность уже присутствует в какой-либо ячейке,
        сначала удаляет её оттуда.

        Args:
            idx: Индекс сущности в WorldState.
            x: Мировая координата X.
            y: Мировая координата Y.
        """
        self.remove(idx)
        cell = self._cell_coords(x, y)
        if cell not in self.grid:
            self.grid[cell] = set()
        self.grid[cell].add(idx)

    def remove(self, idx: int):
        """
        Удаляет сущность из индекса.

        Проходит по всем ячейкам и удаляет idx из каждого множества.
        Пустые ячейки удаляются из словаря.

        Args:
            idx: Индекс сущности в WorldState.
        """
        empty_cells = []
        for cell, indices in self.grid.items():
            indices.discard(idx)
            if not indices:
                empty_cells.append(cell)
        for cell in empty_cells:
            del self.grid[cell]

    def move(self, idx: int, old_x: int, old_y: int, new_x: int, new_y: int):
        """
        Обновляет позицию сущности в индексе.

        Если старая и новая ячейки совпадают, операция пропускается.
        Иначе удаляет сущность из старой ячейки и добавляет в новую.

        Args:
            idx: Индекс сущности в WorldState.
            old_x: Предыдущая мировая координата X.
            old_y: Предыдущая мировая координата Y.
            new_x: Новая мировая координата X.
            new_y: Новая мировая координата Y.
        """
        old_cell = self._cell_coords(old_x, old_y)
        new_cell = self._cell_coords(new_x, new_y)
        if old_cell == new_cell:
            return
        if old_cell in self.grid:
            self.grid[old_cell].discard(idx)
            if not self.grid[old_cell]:
                del self.grid[old_cell]
        if new_cell not in self.grid:
            self.grid[new_cell] = set()
        self.grid[new_cell].add(idx)

    def query_radius(
        self, x: int, y: int, radius: int
    ) -> List[int]:
        """
        Возвращает индексы сущностей в круге заданного радиуса.

        Определяет диапазон ячеек, покрывающих квадрат, описанный
        вокруг круга, и проверяет расстояние Чебышёва до каждой
        сущности в этих ячейках.

        Args:
            x: Центр круга, мировая координата X.
            y: Центр круга, мировая координата Y.
            radius: Радиус поиска в клетках мира.

        Returns:
            list[int]: Список индексов сущностей в радиусе.
        """
        result = []
        r_cells = radius // self.cell_size + 1
        cx, cy = self._cell_coords(x, y)
        for dx in range(-r_cells, r_cells + 1):
            for dy in range(-r_cells, r_cells + 1):
                cell = (cx + dx, cy + dy)
                if cell not in self.grid:
                    continue
                for idx in self.grid[cell]:
                    result.append(idx)
        return result

    def query_rect(
        self,
        min_x: int,
        min_y: int,
        max_x: int,
        max_y: int,
    ) -> List[int]:
        """
        Возвращает индексы сущностей в прямоугольной области.

        Определяет диапазон ячеек, пересекающихся с прямоугольником,
        и собирает все индексы из этих ячеек. Точная проверка
        попадания в прямоугольник не выполняется — вызывающий код
        должен фильтровать результаты при необходимости.

        Args:
            min_x: Левая граница прямоугольника.
            min_y: Верхняя граница прямоугольника.
            max_x: Правая граница прямоугольника.
            max_y: Нижняя граница прямоугольника.

        Returns:
            list[int]: Список индексов сущностей в прямоугольнике.
        """
        result = []
        min_cell = self._cell_coords(min_x, min_y)
        max_cell = self._cell_coords(max_x, max_y)
        for cx in range(min_cell[0], max_cell[0] + 1):
            for cy in range(min_cell[1], max_cell[1] + 1):
                cell = (cx, cy)
                if cell in self.grid:
                    result.extend(self.grid[cell])
        return result

    def query_nearest(
        self, x: int, y: int, k: int = 1
    ) -> List[int]:
        """
        Возвращает k ближайших сущностей к заданной точке.

        Расширяет поисковое кольцо ячеек до тех пор, пока не будет
        найдено достаточно кандидатов. Затем сортирует кандидатов
        по расстоянию Чебышёва и возвращает k ближайших.

        Args:
            x: Мировая координата X точки запроса.
            y: Мировая координата Y точки запроса.
            k: Количество ближайших сущностей. По умолчанию 1.

        Returns:
            list[int]: Список индексов k ближайших сущностей,
                отсортированный по возрастанию расстояния.
        """
        if k <= 0:
            return []
        candidates = []
        cx, cy = self._cell_coords(x, y)
        ring = 0
        while len(candidates) < k:
            found_new = False
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if abs(dx) != ring and abs(dy) != ring:
                        continue
                    cell = (cx + dx, cy + dy)
                    if cell in self.grid:
                        candidates.extend(self.grid[cell])
                        found_new = True
            if not found_new and ring > 256:
                break
            ring += 1
        candidates.sort(key=lambda idx: max(abs(x), abs(y)))
        return candidates[:k]

    def clear(self):
        """Очищает весь пространственный индекс."""
        self.grid.clear()
        logger.debug("SpatialIndex очищен")

    def rebuild(self, state):
        """
        Полностью перестраивает индекс из состояния мира.

        Очищает текущий индекс и добавляет все живые военные
        подразделения из WorldState по их текущим координатам.

        Args:
            state: Состояние игрового мира (WorldState).
        """
        self.clear()
        for idx in range(state.count):
            cfg = state.class_configs[state.class_ids[idx]]
            if cfg.class_name != "military_unit":
                continue
            if "condition" in cfg.segment_layout.segments:
                if state.read_segment(idx, "condition") == 0:
                    continue
            x = int(state.coords[idx, 0])
            y = int(state.coords[idx, 1])
            self.add(idx, x, y)
        logger.info(
            "SpatialIndex перестроен: ячеек=%d", len(self.grid)
        )