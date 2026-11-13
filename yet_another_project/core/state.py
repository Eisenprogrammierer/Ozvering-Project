"""
core/state.py

Состояние игрового мира: классы сущностей, битовые маски, напряжения,
координаты, фракции, человекочитаемые имена сущностей, BDI-структуры
и поля уровня детализации (LOD).

Класс WorldState хранит двойные буферы масок и напряжений для
реализации аксиомы изоляции такта: чтение выполняется из текущего
буфера, запись — в следующий. Коммит переносит следующий буфер
в текущий. Сущности представлены массивами фиксированной ёмкости,
что обеспечивает O(1)-доступ по индексу и предсказуемое потребление
памяти.

Модуль также определяет датаклассы SegmentLayout, VoltageLayout и
ClassConfig, описывающие структуру битовой маски, каналы напряжений
и конфигурацию класса сущности соответственно. Эти структуры
загружаются из JSON-конфигов через config_loader и не изменяются
в рантайме.

События добавления сущностей, записи сегментов и напряжений,
коммита тиков и создания убеждений фиксируются в журнале
operation_ozverin.log и дублируются в консоль.
"""
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
from .log_journal import get_logger

logger = get_logger("core.state")

class LODManager:
    """
    Менеджер уровней детализации (LOD).
    Определяет, активна ли подсистема для конкретной сущности
    на текущем тике в зависимости от её уровня детализации.
    Уровень 0 означает полную активность всех подсистем.
    Уровень 1 означает снижение частоты обновления для правил
    и модальностей, но сохранение активности BDI и боя.
    Уровень 2 и выше означает заморозку (frozen) и отключение
    большинства подсистем для экономии вычислительных ресурсов.
    """
    def __init__(self, state):
        """
        Инициализирует менеджер LOD.
        Args:
            state: Состояние игрового мира (WorldState).
        """
        self.state = state

    def is_active(self, idx: int, subsystem: str) -> bool:
        """
        Проверяет, активна ли указанная подсистема для сущности.
        Args:
            idx (int): Индекс сущности в WorldState.
            subsystem (str): Имя подсистемы ("bdi", "rules",
                "modalities", "combat").
        Returns:
            bool: True, если подсистема должна быть активна
                на текущем тике для данной сущности.
        """
        if idx < 0 or idx >= self.state.count:
            return False
        level = int(self.state.lod_level[idx])
        if level == 0:
            return True
        if level == 1:
            if subsystem in ("rules", "modalities"):
                return (self.state.current_tick % 2) == 0
            if subsystem == "bdi":
                return False
            return True
        if level >= 2:
            return False
        return True

@dataclass
class SegmentLayout:
    """
    Разметка сегментов битовой маски.
    Хранит словарь сегментов, где каждый сегмент описывается
    кортежем (начальный_бит, длина, список_состояний).
    Предоставляет методы для получения позиции сегмента
    и его максимального значения.
    Attributes:
        segments: Словарь {имя_сегмента: (start_bit, length, states)}.
    """
    segments: Dict[str, Tuple[int, int, List[str]]] = field(
        default_factory=dict
    )

    def get(self, name: str) -> Tuple[int, int]:
        """
        Возвращает позицию и длину сегмента по имени.
        Args:
            name: Имя сегмента.
        Returns:
            tuple[int, int]: Кортеж (начальный_бит, длина).
                Возвращает (0, 0), если сегмент не найден.
        """
        if name not in self.segments:
            return (0, 0)
        start, length, _ = self.segments[name]
        return (start, length)

    def max_value(self, name: str) -> int:
        """
        Возвращает максимальное значение сегмента.
        Вычисляется как (2^length - 1). Для отсутствующего
        сегмента или сегмента нулевой длины возвращает 0.
        Args:
            name: Имя сегмента.
        Returns:
            int: Максимальное значение сегмента.
        """
        _, length = self.get(name)
        return (1 << length) - 1 if length > 0 else 0

@dataclass
class VoltageLayout:
    """
    Разметка каналов напряжений.
    Хранит отображение имён каналов на индексы в массиве
    напряжений, параметры каждого канала (метка, начальное
    значение, минимум, максимум, пороги Шмитта, коэффициент
    затухания), конфигурацию триггеров Шмитта и общее
    количество каналов.
    Attributes:
        channel_index: Отображение {имя_канала: индекс}.
        channel_params: Параметры каналов в виде кортежей из 7 элементов.
        schmitt: Конфигурация триггеров Шмитта по именам каналов.
        num_channels: Общее количество каналов напряжений.
    """
    channel_index: Dict[str, int] = field(default_factory=dict)
    channel_params: Dict[
        str,
        Tuple[str, float, float, float, Optional[float], Optional[float], float],
    ] = field(default_factory=dict)
    schmitt: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    num_channels: int = 0

@dataclass
class ClassConfig:
    """
    Конфигурация класса сущности.
    Объединяет разметку битовой маски, каналы напряжений,
    правила валидации и метаморфозы, боевую модель,
    BDI-настройки, профиль восприимчивости к модальностям
    среды, матрицу влияния модальностей и веса целевой функции.
    Загружается из JSON-конфига через config_loader.load_class_config
    и не изменяется в рантайме. Все экземпляры одного класса
    разделяют один и тот же объект ClassConfig.
    Attributes:
        class_name: Уникальное имя класса.
        label: Человекочитаемое название класса.
        segment_layout: Разметка битовой маски.
        voltage_layout: Каналы напряжений.
        validation_rules: Правила валидации состояний.
        metamorphosis_rules: Правила метаморфоз и решений игрока.
        combat_model: Боевая модель класса.
        bdi: BDI-настройки персонажа.
        susceptibility_profile: Восприимчивость к модальностям среды.
        influence_matrix: Матрица влияния модальностей на сегменты.
        objective_weights: Веса каналов для целевой функции.
    """
    class_name: str
    label: str
    segment_layout: SegmentLayout
    voltage_layout: VoltageLayout
    validation_rules: List[dict] = field(default_factory=list)
    metamorphosis_rules: List[dict] = field(default_factory=list)
    combat_model: Dict[str, Any] = field(default_factory=dict)
    bdi: Dict[str, Any] = field(default_factory=dict)
    susceptibility_profile: Dict[str, float] = field(default_factory=dict)
    influence_matrix: Dict[str, Any] = field(default_factory=dict)
    objective_weights: Dict[str, float] = field(default_factory=dict)

class WorldState:
    """
    Глобальное состояние игрового мира.
    Хранит двойные буферы битовых масок и напряжений для всех
    сущностей, массивы координат, фракций, направлений, карты
    высот и биомов, BDI-структуры (убеждения, намерения),
    поля уровня детализации (LOD), виртуальные структуры дивизий
    и начальную численность личного состава.
    Ёмкость мира фиксирована при создании. Добавление сущностей
    сверх ёмкости вызывает RuntimeError. Все операции записи
    работают со следующим буфером (*_next), все операции чтения
    по умолчанию работают с текущим буфером (*_current).
    Метод commit_tick() переносит следующий буфер в текущий,
    завершая такт симуляции.
    Attributes:
        capacity: Максимальная ёмкость по числу сущностей.
        count: Текущее число сущностей.
        max_voltage_channels: Максимальное число каналов напряжений.
        masks_current: Текущий буфер битовых масок.
        masks_next: Следующий буфер битовых масок.
        voltages_current: Текущий буфер напряжений.
        voltages_next: Следующий буфер напряжений.
        entity_ids: Идентификаторы сущностей.
        labels: Человекочитаемые имена сущностей.
        class_ids: Индексы классов сущностей.
        parent_ids: Индексы родительских сущностей.
        class_configs: Конфигурации классов.
        current_tick: Текущий номер тика.
        event_log: Глобальный лог событий.
        tick_events: События текущего тика.
        order_ids: Отображение ID приказов на индексы.
        combat_power: Боевая мощь по 6 проекциям.
        coords: Координаты сущностей (x, y).
        factions: Фракции сущностей.
        player_idx: Индекс сущности игрока.
        player_gender: Пол персонажа игрока.
        map_name: Имя загруженной карты.
        engagements: Активные боестолкновения.
        environment_events: События среды до передачи в ModalitySystem.
        bdi_dead: Флаги смерти BDI-персонажей.
        active_intentions: Активные намерения BDI.
        intentions: Списки намерений BDI по сущностям.
        intention_progress: Прогресс выполнения намерений.
        headings: Направления сущностей (0–5).
        heights: Карта высот.
        biomes: Карта биомов.
        objective: Целевая функция сущностей.
        beliefs: Убеждения BDI по идентификаторам.
        beliefs_by_holder: Индексы убеждений по владельцам.
        belief_seq: Счётчик идентификаторов убеждений.
        bdi: Экземпляр BDI-системы.
        order_progress: Прогресс выполнения приказов.
        orders_queue: Очереди приказов по сущностям.
        order_last: Последние назначенные приказы.
        order_morale_accum: Накопители морали от приказов.
        lod_level: Уровни детализации сущностей.
        lod_frozen: Флаги заморозки сущностей.
        lod_skip_counter: Счётчики пропусков тиков LOD.
        lod_last_decay_tick: Последние тики применения decay.
        lod_manager: Менеджер уровней детализации.
        divisional_structures: Виртуальные структуры дивизий.
        initial_manpower: Начальная численность личного состава.
    """
    def __init__(
        self, capacity: int = 1024, max_voltage_channels: int = 16
    ):
        """
        Инициализирует состояние мира.
        Создаёт двойные буферы масок и напряжений заданной ёмкости,
        инициализирует все вспомогательные массивы и списки.
        Логирует параметры инициализации.
        Args:
            capacity: Максимальная ёмкость по числу сущностей.
            max_voltage_channels: Максимальное число каналов напряжений.
        """
        self.capacity = capacity
        self.count = 0
        self.max_voltage_channels = max_voltage_channels
        self.masks_current = np.zeros(capacity, dtype=np.uint64)
        self.masks_next = np.zeros(capacity, dtype=np.uint64)
        self.voltages_current = np.zeros(
            (capacity, max_voltage_channels), dtype=np.float64
        )
        self.voltages_next = np.zeros(
            (capacity, max_voltage_channels), dtype=np.float64
        )
        self.entity_ids: List[str] = []
        self.labels: List[str] = [""] * capacity
        self.class_ids: List[int] = []
        self.parent_ids: List[int] = []
        self.class_configs: List[ClassConfig] = []
        self.current_tick = 0
        self.event_log: List[Dict] = []
        self.tick_events: List[Dict] = []
        self.order_ids: Dict[str, int] = {}
        self.combat_power = np.zeros(
            (capacity, 6), dtype=np.float64
        )
        self.coords = np.zeros((capacity, 2), dtype=np.int32)
        self.factions = ["neutral"] * capacity
        self.player_idx = 0
        self.player_gender = "male"
        self.map_name = None
        self.engagements: List[Any] = []
        self.environment_events: List[Dict] = []
        self.bdi_dead = np.zeros(capacity, dtype=bool)
        self.active_intentions: List[Optional[Dict]] = [None] * capacity
        self.intentions: List[List[Dict]] = [[] for _ in range(capacity)]
        self.intention_progress = np.zeros(capacity, dtype=np.float64)
        self.headings = np.zeros(capacity, dtype=np.int32)
        self.heights: Optional[np.ndarray] = None
        self.biomes: Optional[np.ndarray] = None
        self.objective = np.zeros(capacity, dtype=np.float64)
        self.beliefs: Dict[int, Dict[str, Any]] = {}
        self.beliefs_by_holder: List[List[int]] = [
            [] for _ in range(capacity)
        ]
        self.belief_seq = 0
        self.bdi: Optional[Any] = None
        self.order_progress = np.zeros(capacity, dtype=np.float64)
        self.orders_queue: List[List[int]] = [[] for _ in range(capacity)]
        self.order_last = np.full(capacity, -1, dtype=np.int64)
        self.order_morale_accum = np.zeros(capacity, dtype=np.float64)
        self.lod_level = np.zeros(capacity, dtype=np.int8)
        self.lod_frozen = np.zeros(capacity, dtype=bool)
        self.lod_skip_counter = np.zeros(capacity, dtype=np.int32)
        self.lod_last_decay_tick = np.zeros(capacity, dtype=np.int32)
        self.lod_manager = LODManager(self)
        self.divisional_structures: Dict[str, Any] = {}
        self.initial_manpower = np.zeros(capacity, dtype=np.float64)
        logger.debug(
            "WorldState инициализирован: capacity=%d, "
            "max_voltage_channels=%d",
            capacity,
            max_voltage_channels,
        )

    def add_entity(
        self, entity_id: str, class_id: int, parent_id: int = -1
    ) -> int:
        """
        Добавляет новую сущность в мир.
        Размещает сущность в следующем свободном слоте массивов.
        Если у класса есть сегмент condition, инициализирует его
        максимальным значением. Выбрасывает RuntimeError при
        переполнении ёмкости.
        Args:
            entity_id: Уникальный строковый идентификатор сущности.
            class_id: Индекс класса в списке class_configs.
            parent_id: Индекс родительской сущности (-1 для корневых).
        Returns:
            int: Индекс добавленной сущности.
        Raises:
            RuntimeError: Если count >= capacity.
        """
        if self.count >= self.capacity:
            logger.error(
                "add_entity: переполнение capacity=%d при добавлении %s",
                self.capacity,
                entity_id,
            )
            raise RuntimeError("WorldState capacity exceeded")
        idx = self.count
        self.entity_ids.append(entity_id)
        self.class_ids.append(class_id)
        self.parent_ids.append(parent_id)
        self.count += 1
        if class_id < len(self.class_configs):
            config = self.class_configs[class_id]
            if "condition" in config.segment_layout.segments:
                max_val = config.segment_layout.max_value("condition")
                self.write_segment(idx, "condition", max_val)
        logger.info(
            "add_entity: %s (class_id=%d, parent_id=%d) -> idx=%d",
            entity_id,
            class_id,
            parent_id,
            idx,
        )
        return idx

    def label_of(self, idx: int) -> str:
        """
        Возвращает человекочитаемое имя сущности.
        Приоритет: поле labels[idx], затем entity_ids[idx],
        затем "?" для некорректных индексов.
        Args:
            idx: Индекс сущности.
        Returns:
            str: Человекочитаемое имя сущности.
        """
        if 0 <= idx < self.capacity and self.labels[idx]:
            return self.labels[idx]
        if 0 <= idx < len(self.entity_ids):
            return self.entity_ids[idx]
        return "?"

    def read_segment(self, idx: int, seg_name: str) -> int:
        """
        Читает значение сегмента из текущего буфера.
        Извлекает биты сегмента из masks_current[idx] с помощью
        сдвига и маскирования. Возвращает 0 для отсутствующего
        сегмента или сегмента нулевой длины.
        Args:
            idx: Индекс сущности.
            seg_name: Имя сегмента.
        Returns:
            int: Значение сегмента.
        """
        config = self.class_configs[self.class_ids[idx]]
        start, length = config.segment_layout.get(seg_name)
        if length <= 0:
            return 0
        mask = (1 << length) - 1
        return int((self.masks_current[idx] >> start) & mask)

    def read_segment_next(self, idx: int, seg_name: str) -> int:
        """
        Читает значение сегмента из следующего буфера.
        Аналогично read_segment, но читает из masks_next.
        Используется для проверки результатов записи в рамках
        текущего такта до коммита.
        Args:
            idx: Индекс сущности.
            seg_name: Имя сегмента.
        Returns:
            int: Значение сегмента в следующем буфере.
        """
        config = self.class_configs[self.class_ids[idx]]
        start, length = config.segment_layout.get(seg_name)
        if length <= 0:
            return 0
        mask = (1 << length) - 1
        return int((self.masks_next[idx] >> start) & mask)

    def write_segment(self, idx: int, seg_name: str, value: int):
        """
        Записывает значение сегмента в следующий буфер.
        Очищает биты сегмента в masks_next[idx] и устанавливает
        новое значение с маскированием по длине сегмента.
        Операция безопасна: значения автоматически обрезаются
        до допустимого диапазона. Для отсутствующего сегмента
        или сегмента нулевой длины операция пропускается.
        Args:
            idx: Индекс сущности.
            seg_name: Имя сегмента.
            value: Новое значение сегмента.
        """
        config = self.class_configs[self.class_ids[idx]]
        start, length = config.segment_layout.get(seg_name)
        if length <= 0:
            return
        mask = np.uint64((1 << length) - 1)
        val = np.uint64(value) & mask
        self.masks_next[idx] &= ~(mask << np.uint64(start))
        self.masks_next[idx] |= val << np.uint64(start)
        logger.debug(
            "write_segment: idx=%d seg=%s value=%d",
            idx,
            seg_name,
            value,
        )

    def read_segment_array(self, seg_name: str) -> List[int]:
        """
        Читает значения сегмента для всех сущностей из текущего буфера.
        Args:
            seg_name: Имя сегмента.
        Returns:
            list[int]: Список значений сегмента для каждой сущности
                в порядке их индексов от 0 до count-1.
        """
        return [self.read_segment(i, seg_name) for i in range(self.count)]

    def get_segment_label(self, idx: int, seg_name: str) -> str:
        """
        Возвращает текстовую метку состояния сегмента.
        Если значение сегмента попадает в диапазон списка состояний,
        возвращает соответствующую строку. Иначе возвращает
        строковое представление числового значения.
        Args:
            idx: Индекс сущности.
            seg_name: Имя сегмента.
        Returns:
            str: Текстовая метка состояния или строковое число.
        """
        config = self.class_configs[self.class_ids[idx]]
        start, length = config.segment_layout.get(seg_name)
        if length <= 0:
            return "0"
        value = self.read_segment(idx, seg_name)
        states = config.segment_layout.segments.get(
            seg_name, (0, 0, [])
        )[2]
        if isinstance(states, list) and 0 <= value < len(states):
            return states[value]
        return str(value)

    def read_voltage(self, idx: int, channel: str) -> float:
        """
        Читает значение канала напряжения из текущего буфера.
        Args:
            idx: Индекс сущности.
            channel: Имя канала напряжения.
        Returns:
            float: Значение напряжения. Возвращает 0.0, если
                канал не найден в конфигурации класса.
        """
        config = self.class_configs[self.class_ids[idx]]
        ch_idx = config.voltage_layout.channel_index.get(channel)
        if ch_idx is None:
            return 0.0
        return float(self.voltages_current[idx, ch_idx])

    def read_voltage_next(self, idx: int, channel: str) -> float:
        """
        Читает значение канала напряжения из следующего буфера.
        Args:
            idx: Индекс сущности.
            channel: Имя канала напряжения.
        Returns:
            float: Значение напряжения в следующем буфере.
                Возвращает 0.0, если канал не найден.
        """
        config = self.class_configs[self.class_ids[idx]]
        ch_idx = config.voltage_layout.channel_index.get(channel)
        if ch_idx is None:
            return 0.0
        return float(self.voltages_next[idx, ch_idx])

    def set_voltage_next(
        self, idx: int, channel: str, value: float
    ):
        """
        Устанавливает значение канала в следующем буфере с клампом.
        Значение ограничивается диапазоном [min, max] из параметров
        канала. Для отсутствующего канала операция пропускается.
        Args:
            idx: Индекс сущности.
            channel: Имя канала напряжения.
            value: Новое значение напряжения.
        """
        config = self.class_configs[self.class_ids[idx]]
        ch_idx = config.voltage_layout.channel_index.get(channel)
        if ch_idx is None:
            return
        params = config.voltage_layout.channel_params[channel]
        _, _, min_v, max_v, _, _, _ = params
        self.voltages_next[idx, ch_idx] = max(
            min_v, min(max_v, value)
        )
        logger.debug(
            "set_voltage_next: idx=%d channel=%s value=%.4f",
            idx,
            channel,
            value,
        )

    def add_voltage(self, idx: int, channel: str, delta: float):
        """
        Добавляет дельту к каналу напряжения в следующем буфере.
        Результат клампится в диапазоне [min, max] из параметров
        канала. Для отсутствующего канала операция пропускается.
        Args:
            idx: Индекс сущности.
            channel: Имя канала напряжения.
            delta: Изменение напряжения (может быть отрицательным).
        """
        config = self.class_configs[self.class_ids[idx]]
        ch_idx = config.voltage_layout.channel_index.get(channel)
        if ch_idx is None:
            return
        params = config.voltage_layout.channel_params[channel]
        _, _, min_v, max_v, _, _, _ = params
        current = self.voltages_next[idx, ch_idx]
        new_val = current + delta
        self.voltages_next[idx, ch_idx] = max(
            min_v, min(max_v, new_val)
        )
        logger.debug(
            "add_voltage: idx=%d channel=%s delta=%.4f -> %.4f",
            idx,
            channel,
            delta,
            self.voltages_next[idx, ch_idx],
        )

    def set_heading(self, idx: int, heading: int):
        """
        Устанавливает направление сущности.
        Допустимые значения: 0 (север), 1 (восток), 2 (юг),
        3 (запад), 4 (верх), 5 (низ). Некорректные значения
        приводятся к 0.
        Args:
            idx: Индекс сущности.
            heading: Направление (0–5).
        """
        if heading < 0 or heading > 5:
            heading = 0
        self.headings[idx] = heading

    def log_event(
        self, idx: int, message: str, meta: dict = None
    ):
        """
        Записывает событие в глобальный лог и лог текущего тика.
        Событие содержит номер тика, идентификатор сущности,
        сообщение и опциональные метаданные. Одновременно
        записывается в event_log (полная история) и tick_events
        (события текущего тика, очищаются внешним кодом).
        Args:
            idx: Индекс сущности, связанной с событием.
            message: Текст события.
            meta: Опциональный словарь метаданных.
        """
        entry = {
            "tick": self.current_tick,
            "entity_id": self.entity_ids[idx],
            "message": message,
        }
        if meta:
            entry.update(meta)
        self.event_log.append(entry)
        self.tick_events.append(entry)
        logger.info(
            "[tick=%d] %s: %s",
            entry["tick"],
            entry["entity_id"],
            message,
        )

    def commit_tick(self):
        """
        Фиксирует такт симуляции.
        Копирует содержимое следующего буфера в текущий для
        масок и напряжений. После коммита текущий буфер отражает
        результаты всех операций записи, выполненных в течение
        такта. Вызывается движком в конце каждого шага симуляции.
        """
        self.masks_current[:] = self.masks_next
        self.voltages_current[:] = self.voltages_next
        logger.debug("commit_tick: tick=%d", self.current_tick)

    def add_belief(
        self,
        holder_idx: int,
        relation: str,
        object_ref: Any,
        modality: str,
        temporality: str = "present",
        confidence: float = 0.5,
        source: str = "observation",
    ) -> int:
        """
        Добавляет убеждение в BDI-систему.
        Создаёт новое убеждение с уникальным идентификатором,
        связывает его с владельцем и возвращает идентификатор.
        Для некорректного holder_idx возвращает -1 без создания
        убеждения.
        Args:
            holder_idx: Индекс сущности-владельца убеждения.
            relation: Тип отношения (can_satisfy, threatens, safe и т.д.).
            object_ref: Ссылка на объект убеждения.
            modality: Модальность убеждения.
            temporality: Временная характеристика (past, present, future, conditional).
            confidence: Начальная уверенность [0, 1].
            source: Источник убеждения (observation, report и т.д.).
        Returns:
            int: Идентификатор созданного убеждения или -1 при ошибке.
        """
        if holder_idx < 0 or holder_idx >= self.capacity:
            return -1
        belief_id = self.belief_seq
        self.belief_seq += 1
        self.beliefs[belief_id] = {
            "id": belief_id,
            "holder": holder_idx,
            "relation": relation,
            "object_ref": object_ref,
            "modality": modality,
            "temporality": temporality,
            "confidence": float(confidence),
            "source": source,
            "active": True,
            "tick_created": self.current_tick,
        }
        self.beliefs_by_holder[holder_idx].append(belief_id)
        return belief_id

    def compute_objective(self, idx: int) -> float:
        """
        Вычисляет целевую функцию сущности в диапазоне [0, 1].
        Если в конфигурации класса заданы objective_weights,
        вычисляет взвешенную сумму нормализованных значений
        указанных каналов. Иначе усредняет нормализованные
        значения всех каналов напряжений. Нормализация:
        (value - min) / (max - min), клампится в [0, 1].
        Args:
            idx: Индекс сущности.
        Returns:
            float: Значение целевой функции в диапазоне [0, 1].
                Возвращает 0.0, если нет доступных каналов.
        """
        config = self.class_configs[self.class_ids[idx]]
        weights = config.objective_weights or {}
        total_weight = 0.0
        weighted_sum = 0.0
        if weights:
            for channel, weight in weights.items():
                ch_idx = config.voltage_layout.channel_index.get(
                    channel
                )
                if ch_idx is None:
                    continue
                params = config.voltage_layout.channel_params.get(
                    channel
                )
                if params is None:
                    continue
                _, _, min_v, max_v, _, _, _ = params
                if max_v - min_v > 1e-9:
                    value = (
                        self.read_voltage_next(idx, channel) - min_v
                    ) / (max_v - min_v)
                else:
                    value = 0.5
                value = max(0.0, min(1.0, value))
                weighted_sum += value * weight
                total_weight += weight
            return (
                weighted_sum / total_weight
                if total_weight > 0
                else 0.0
            )
        total = 0.0
        count = 0
        for channel, ch_idx in config.voltage_layout.channel_index.items():
            params = config.voltage_layout.channel_params.get(channel)
            if params is None:
                continue
            _, _, min_v, max_v, _, _, _ = params
            if max_v - min_v > 1e-9:
                value = (
                    self.read_voltage_next(idx, channel) - min_v
                ) / (max_v - min_v)
            else:
                value = 0.5
            value = max(0.0, min(1.0, value))
            total += value
            count += 1
        return total / count if count > 0 else 0.0