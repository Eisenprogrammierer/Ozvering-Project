"""
core/lod.py

Менеджер уровня детализации (LOD).

Назначает уровни детализации сущностям на основе геометрической
близости к игроку по расстоянию Чебышёва и организационной
близости дочерних сущностей. Управляет периодическим пересчётом
уровней с гистерезисом для предотвращения осцилляции на границах
зон, проверкой активности подсистем и материализацией сущностей
при переходе из замороженного состояния в активное. Пересчёт
использует пространственный индекс на основе сетки чанков для
ограничения числа вычислений расстояния сущностями в зоне
интереса. Перед каждым пересчётом индекс перестраивается из
текущих координат для гарантии актуальности. Материализация
применяет накопленное затухание напряжений, динамику потребностей
BDI и регенерацию намерений. События модуля записываются в журнал
operation_ozverin.log и дублируются в консоль средствами
core.log_journal.
"""

from .config_loader import load_json
from .log_journal import get_logger
from .spatial_index import SpatialIndex

logger = get_logger("core.lod")

LOD_FULL = 0
LOD_HEURISTIC = 1
LOD_STATISTICAL = 2

DEFAULT_LOD_CONFIG = {
    "lod_radii": [15, 40],
    "hysteresis_band": 5,
    "lod1_interval_steps": 4,
    "spatial_chunk_size": 32,
    "lod_config": {
        "bdi": {"lod0": True, "lod1": False, "lod2": False},
        "combat": {"lod0": True, "lod1": True, "lod2": False},
        "field_ai": {"lod0": True, "lod1": True, "lod2": False},
        "rules": {"lod0": True, "lod1": False, "lod2": False},
        "modalities": {"lod0": True, "lod1": True, "lod2": False},
        "decay": {"lod0": True, "lod1": True, "lod2": False},
    },
    "recalc_interval_steps": 10,
    "player_children_always_lod0": True,
}


class LODManager:
    """
    Менеджер уровня детализации.

    Назначает уровни LOD сущностям по расстоянию Чебышёва
    до игрока с учётом гистерезиса, использует пространственный
    индекс для ограничения зоны пересчёта, учитывает
    организационную близость дочерних сущностей, управляет
    проверкой активности подсистем и выполняет материализацию
    замороженных сущностей с вызовом материализации BDI для
    персонажей. Перед каждым пересчётом пространственный индекс
    перестраивается из текущих координат для гарантии актуальности.

    Attributes:
        state: Состояние игрового мира (WorldState).
        lod_radii: Радиусы уровней LOD.
        hysteresis_band: Ширина полосы гистерезиса.
        lod_config: Карта активности подсистем по уровням.
        recalc_interval_steps: Интервал пересчёта в шагах.
        player_children_always_lod0: Флаг принудительного
            LOD 0 для дочерних сущностей игрока.
        lod1_interval_steps: Интервал обработки LOD 1.
        spatial_chunk_size: Размер чанка пространственного
            индекса.
        spatial_index: Пространственный индекс сущностей.
        step_counter: Счётчик шагов с последнего пересчёта.
    """

    def __init__(self, state, config_path="configs/content/lod.json"):
        """
        Инициализирует менеджер LOD.

        Загружает конфигурацию из JSON-файла, создаёт
        пространственный индекс и заполняет его начальными
        позициями сущностей. Инициализирует все сущности
        уровнем LOD 0. При отсутствии файла конфигурации
        используются встроенные значения.

        Args:
            state: Состояние игрового мира (WorldState).
            config_path: Путь к JSON-файлу конфигурации LOD.
        """
        self.state = state
        self.config = load_json(config_path, dict(DEFAULT_LOD_CONFIG))
        self.lod_radii = list(self.config.get("lod_radii", [15, 40]))
        self.hysteresis_band = int(self.config.get("hysteresis_band", 5))
        self.lod_config = dict(
            self.config.get("lod_config", DEFAULT_LOD_CONFIG["lod_config"])
        )
        self.recalc_interval_steps = int(
            self.config.get("recalc_interval_steps", 10)
        )
        self.player_children_always_lod0 = bool(
            self.config.get("player_children_always_lod0", True)
        )
        self.lod1_interval_steps = int(
            self.config.get("lod1_interval_steps", 4)
        )
        self.spatial_chunk_size = int(
            self.config.get("spatial_chunk_size", 32)
        )
        self.step_counter = 0
        self.spatial_index = SpatialIndex(cell_size=self.spatial_chunk_size)
        if state.count > 0:
            self.spatial_index.rebuild(state)
        for idx in range(state.count):
            state.lod_level[idx] = LOD_FULL
            state.lod_frozen[idx] = False
        logger.info(
            "LODManager инициализирован: сущностей=%d, радиусы=%s, "
            "гистерезис=%d, интервал=%d, чанк=%d",
            state.count,
            self.lod_radii,
            self.hysteresis_band,
            self.recalc_interval_steps,
            self.spatial_chunk_size,
        )

    def notify_moved(self, idx):
        """
        Уведомляет пространственный индекс о перемещении сущности.

        Вызывается из полевого ИИ после изменения координат
        для поддержания актуальности индекса между пересчётами.

        Args:
            idx: Индекс перемещённой сущности.
        """
        st = self.state
        x = int(st.coords[idx, 0])
        y = int(st.coords[idx, 1])
        self.spatial_index.remove(idx)
        self.spatial_index.add(idx, x, y)

    def recalculate(self):
        """
        Переназначает уровни LOD всем сущностям с гистерезисом.

        Перед пересчётом перестраивает пространственный индекс
        из текущих координат для гарантии актуальности. Затем
        запрашивает сущности в зоне интереса (радиус r1 плюс
        полоса гистерезиса) и вычисляет точное расстояние
        Чебышёва только для них. Сущности, попавшие в чанки
        зоны, но находящиеся фактически вне радиуса, получают
        LOD_STATISTICAL. Сущности вне зоны интереса массово
        получают LOD_STATISTICAL. Дочерние сущности игрока
        принудительно получают LOD 0 при включённом флаге
        конфигурации. При переходе сущности из замороженного
        состояния в активное вызывается материализация.

        Returns:
            None
        """
        st = self.state
        if st.count == 0:
            return
        self.spatial_index.rebuild(st)
        px = int(st.coords[st.player_idx, 0])
        py = int(st.coords[st.player_idx, 1])
        r0 = self.lod_radii[0] if len(self.lod_radii) > 0 else 15
        r1 = self.lod_radii[1] if len(self.lod_radii) > 1 else 40
        band = self.hysteresis_band
        query_radius = r1 + band
        near_indices = self.spatial_index.query_radius(px, py, query_radius)
        near_set = set(near_indices)
        for idx in near_indices:
            dx = abs(int(st.coords[idx, 0]) - px)
            dy = abs(int(st.coords[idx, 1]) - py)
            dist = max(dx, dy)
            if dist > query_radius:
                old_level = int(st.lod_level[idx])
                if old_level != LOD_STATISTICAL:
                    st.lod_level[idx] = LOD_STATISTICAL
                    logger.debug(
                        "LOD: idx=%d вне зоны (dist=%d > %d), "
                        "назначен LOD_STATISTICAL",
                        idx,
                        dist,
                        query_radius,
                    )
                continue
            old_level = int(st.lod_level[idx])
            if old_level == LOD_FULL:
                if dist > r0 + band:
                    new_level = (
                        LOD_HEURISTIC if dist <= r1 else LOD_STATISTICAL
                    )
                else:
                    new_level = LOD_FULL
            elif old_level == LOD_HEURISTIC:
                if dist < r0 - band:
                    new_level = LOD_FULL
                elif dist > r1 + band:
                    new_level = LOD_STATISTICAL
                else:
                    new_level = LOD_HEURISTIC
            else:
                if dist < r1 - band:
                    new_level = (
                        LOD_HEURISTIC if dist > r0 else LOD_FULL
                    )
                else:
                    new_level = LOD_STATISTICAL
            st.lod_level[idx] = new_level
        for idx in range(st.count):
            if idx not in near_set:
                old_level = int(st.lod_level[idx])
                if old_level != LOD_STATISTICAL:
                    st.lod_level[idx] = LOD_STATISTICAL
        if self.player_children_always_lod0:
            for idx in range(st.count):
                if st.parent_ids[idx] == st.player_idx:
                    st.lod_level[idx] = LOD_FULL
        for idx in range(st.count):
            was_frozen = bool(st.lod_frozen[idx])
            is_frozen = st.lod_level[idx] == LOD_STATISTICAL
            st.lod_frozen[idx] = is_frozen
            if was_frozen and not is_frozen:
                self.materialize(idx)
        logger.debug(
            "LOD пересчитан: сущностей=%d, в зоне=%d, "
            "радиусы=[%d, %d], гистерезис=%d",
            st.count,
            len(near_indices),
            r0,
            r1,
            band,
        )

    def is_active(self, idx, subsystem):
        """
        Проверяет, активна ли подсистема для сущности на текущем LOD.

        Args:
            idx: Индекс сущности.
            subsystem: Имя подсистемы (bdi, combat, field_ai,
                rules, modalities, decay).

        Returns:
            bool: True, если подсистема активна для данного
                уровня LOD.
        """
        level = int(self.state.lod_level[idx])
        cfg = self.lod_config.get(subsystem, {})
        key = f"lod{level}"
        return bool(cfg.get(key, True))

    def should_recalculate(self):
        """
        Проверяет, нужно ли выполнить пересчёт LOD на текущем шаге.

        Returns:
            bool: True, если прошло достаточно шагов с последнего
                пересчёта.
        """
        return self.step_counter >= self.recalc_interval_steps

    def advance_step(self):
        """
        Увеличивает счётчик шагов и выполняет пересчёт при
        необходимости. Счётчик обнуляется после пересчёта.

        Returns:
            bool: True, если пересчёт был выполнен.
        """
        self.step_counter += 1
        if self.should_recalculate():
            self.recalculate()
            self.step_counter = 0
            logger.debug("LOD: пересчёт выполнен, счётчик сброшен")
            return True
        return False

    def materialize(self, idx):
        """
        Материализует сущность при переходе из LOD 2 в LOD 0 или 1.

        Применяет накопленное экспоненциальное затухание напряжений
        за пропущенные тики одним умножением alpha^skipped_hours.
        Обновляет метку последнего тика decay. Если состояние мира
        содержит BDI-систему, вызывает материализацию BDI для
        персонажей с передачей количества пропущенных тиков,
        включая динамику потребностей и регенерацию намерений.

        Args:
            idx: Индекс материализуемой сущности.
        """
        st = self.state
        last_tick = int(st.lod_last_decay_tick[idx])
        current_tick = int(st.current_tick)
        skipped_hours = max(0, current_tick - last_tick)
        if skipped_hours > 0:
            config = st.class_configs[st.class_ids[idx]]
            for ch_name, ch_idx in config.voltage_layout.channel_index.items():
                params = config.voltage_layout.channel_params[ch_name]
                alpha = float(params[6])
                min_v = float(params[2])
                max_v = float(params[3])
                if alpha <= 0.0:
                    st.voltages_next[idx, ch_idx] = min_v
                elif alpha < 1.0:
                    factor = alpha ** skipped_hours
                    old = float(st.voltages_next[idx, ch_idx])
                    new_val = old * factor
                    st.voltages_next[idx, ch_idx] = max(
                        min_v, min(max_v, new_val)
                    )
            st.lod_last_decay_tick[idx] = current_tick
        bdi = getattr(st, "bdi", None)
        if bdi is not None and hasattr(bdi, "materialize_bdi"):
            bdi.materialize_bdi(idx, skipped_hours)
        logger.debug(
            "LOD материализация: idx=%d, пропущено_часов=%d",
            idx,
            skipped_hours,
        )