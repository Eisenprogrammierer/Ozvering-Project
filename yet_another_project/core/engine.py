"""
core/engine.py

Движок мира: координирует игровой цикл, обработку тиков, боевую систему,
BDI-агентов, модальности среды, правила валидации, расширенную систему
приказов, полевой ИИ, логистическую систему и уровень детализации (LOD).

Класс TickEngine является центральным координатором всех подсистем.
Поддерживает два режима работы: старый (tick) для пошаговой симуляции
и новый (advance_seconds) для непрерывного продвижения времени при
выполнении действий игрока. В старом режиме один вызов tick() равен
одному условному часу. В новом режиме запрошенное время разбивается
на шаги по simulation_step_seconds, каждый из которых применяет
затухание, BDI, модальности, бой и правила с учётом масштаба времени.

При инициализации создаёт таблицу приказов, боевую систему, систему
модальностей, полевой ИИ, менеджер LOD и опционально BDI-систему
и логистическую систему. События среды из state.environment_events
передаются в ModalitySystem и очищаются. Тайминги читаются из
configs/content/engine_timing.json. Начальная численность
(initial_manpower) реконструируется для агрегатных сущностей как
сумма начальной численности дочерних, чтобы потери всех уровней
корректно отражались в процентах.

Приказы игрока исполняются встроенным исполнителем с оперативной
скоростью (ускорение PLAYER_SPEED_BOOST от скорости приказа): юниты
фракции игрока с атакующим приказом выдвигаются к ближайшему
противнику и вступают в бой при контакте, юниты с приказом
перемещения или марш-броска отводятся от противника в радиусе
вывода, юниты с приказом «move» двигаются к заранее установленной
целевой точке (задаётся через set_move_target). Исполнитель является
единственным источником перемещения юнитов игрока; полевой ИИ
управляет только автономными подразделениями.

События инициализации, выполнения тиков, назначения приказов и
ошибок фиксируются в журнале operation_ozverin.log и дублируются
в консоль средствами core.log_journal.
"""

import random

from .config_loader import load_json
from .rules import RuleEngine
from .orders import OrderTable
from .combat import CombatSystem
from .modalities import ModalitySystem
from .field_ai import FieldAI
from .lod import LODManager
from .log_journal import get_logger

logger = get_logger("core.engine")

SUPPLY_CHANNEL_MARKERS = ("supply", "supply_flow")

ATTACK_ORDER_IDS = ("aggressive_attack", "attack", "cautious_attack")
RETREAT_ORDER_IDS = ("movement", "forced_march")
MOVE_ORDER_ID = "move"
PLAYER_SPEED_BOOST = 3.0
PLAYER_MAX_STEPS_PER_CALL = 6
PLAYER_DISENGAGE_RADIUS = 6


class TickEngine:
    """
    Движок игрового мира.

    Координирует все подсистемы симуляции: затухание напряжений,
    BDI-агентов, модальности среды, полевой ИИ, боевую систему,
    правила валидации и метаморфоз, логистику и обработку приказов.
    Поддерживает два режима: пошаговый tick() и непрерывный
    advance_seconds(). Приказы игрока исполняются встроенным
    исполнителем с оперативной скоростью: атакующие приказы ведут
    юнит к противнику и создают боестолкновение при контакте,
    приказы перемещения выводят юнит из-под удара, приказ «move»
    перемещает юнит к заранее установленной целевой точке.

    Attributes:
        state: Состояние игрового мира (WorldState).
        rng: Генератор случайных чисел.
        tick_count: Текущий номер тика.
        order_table: Таблица приказов (OrderTable).
        combat: Боевая система (CombatSystem).
        engagements: Список активных боестолкновений.
        field_ai: Полевой ИИ (FieldAI).
        bdi: BDI-система или None.
        modalities: Система модальностей среды (ModalitySystem).
        time_system: Система игрового времени или None.
        lod_manager: Менеджер уровня детализации (LODManager).
        logistics: Логистическая система или None.
        player_move_accum: Накопители дробного перемещения юнитов
            игрока исполнителя приказов.
        move_targets: Словарь {индекс_сущности: (x, y)} целевых
            координат для приказа «move».
    """

    def __init__(
        self,
        state,
        seed: int = 42,
        orders_path: str = "configs/content/orders.json",
    ):
        """
        Инициализирует движок мира.

        Создаёт таблицу приказов, боевую систему, систему модальностей,
        полевой ИИ, менеджер LOD. При наличии BDI-конфигураций в классах
        и готовности состояния создаёт BDI-систему. При наличии
        логистического состояния в state создаёт логистическую систему.
        Передаёт события среды из state.environment_events в
        ModalitySystem и очищает их. Синхронизирует order_last и
        начальную численность для всех сущностей.

        Args:
            state: Состояние игрового мира (WorldState).
            seed: Зерно генератора случайных чисел.
            orders_path: Путь к JSON-файлу таблицы приказов.
        """
        self.state = state
        self.rng = random.Random(seed)
        self.tick_count = 0
        self._load_timing_config()
        self.order_table = OrderTable(orders_path)
        state.order_ids = self.order_table.id_to_index
        self.combat = CombatSystem(state, self.order_table)
        self.engagements = []
        self.field_ai = FieldAI(state, self.order_table, self.rng)
        self.field_ai.engine = self
        self.bdi = getattr(state, "bdi", None)
        if self.bdi is None:
            try:
                has_bdi = any(
                    getattr(cfg, "bdi", None) for cfg in state.class_configs
                )
            except Exception:
                has_bdi = False
            state_ready_for_bdi = (
                hasattr(state, "beliefs")
                and hasattr(state, "beliefs_by_holder")
                and hasattr(state, "add_belief")
            )
            if has_bdi and state_ready_for_bdi:
                from .bdi import BDISystem

                state.bdi = BDISystem(state)
                self.bdi = state.bdi
        if self.bdi is not None:
            self.bdi.order_table = self.order_table
        self.modalities = ModalitySystem(state)
        for event in state.environment_events:
            self.modalities.add_event(event)
        state.environment_events = []
        self.time_system = None
        self.lod_manager = LODManager(state)
        state.lod_manager = self.lod_manager
        self.logistics = None
        if getattr(state, "logistics", None) is not None:
            from .logistics import LogisticsSystem

            state.logistics_system = LogisticsSystem(state, state.logistics)
            self.logistics = state.logistics_system
        self.player_move_accum = {}
        self.move_targets = {}
        self._ensure_initial_manpower()
        self._sync_order_last()
        logger.info(
            "TickEngine инициализирован: сущностей=%d, приказов=%d, логистика=%s",
            state.count,
            len(self.order_table.orders),
            "активна" if self.logistics is not None else "отсутствует",
        )

    def _load_timing_config(self):
        """
        Загружает конфигурацию таймингов из engine_timing.json.

        Читает configs/content/engine_timing.json через безопасный
        загрузчик. Устанавливает интервалы для симуляции, BDI, боя,
        правил и событий среды. При отсутствии файла используются
        значения по умолчанию.
        """
        timing = load_json("configs/content/engine_timing.json", {}) or {}
        self._simulation_step_seconds = float(
            timing.get("simulation_step_seconds", 300.0)
        )
        self._bdi_substep_seconds = float(
            timing.get("bdi_substep_seconds", 300.0)
        )
        self._bdi_interval_seconds = float(
            timing.get("bdi_interval_seconds", 3600.0)
        )
        self._combat_interval_seconds = float(
            timing.get("combat_interval_seconds", 3600.0)
        )
        self._rules_interval_seconds = float(
            timing.get("rules_interval_seconds", 3600.0)
        )
        self._env_interval_seconds = float(
            timing.get("env_interval_seconds", 3600.0)
        )

    def _ensure_initial_manpower(self):
        """
        Реконструирует начальную численность для всех сущностей.

        Листовые сущности (без дочерних) получают initial_manpower
        из текущего значения канала U_manpower, если оно ещё не
        задано. Агрегатные сущности (батальон, полк, дивизия)
        получают сумму начальной численности дочерних сущностей.
        Без этого проценты потерь старших уровней считаются от
        нулевой базы и не отражают реальное состояние соединения,
        из-за чего условия сюжета о потерях не срабатывают.
        """
        st = self.state
        children_map = {}
        for idx in range(st.count):
            parent = st.parent_ids[idx]
            children_map.setdefault(parent, []).append(idx)
        for idx in range(st.count):
            if st.initial_manpower[idx] > 0.0:
                continue
            cfg = st.class_configs[st.class_ids[idx]]
            if (
                "U_manpower" in cfg.voltage_layout.channel_index
                and not children_map.get(idx)
            ):
                st.initial_manpower[idx] = max(
                    0.0, st.read_voltage(idx, "U_manpower")
                )
        for _ in range(8):
            changed = False
            for idx in range(st.count):
                if st.initial_manpower[idx] > 0.0:
                    continue
                kids = [
                    k
                    for k in children_map.get(idx, [])
                    if st.initial_manpower[k] > 0.0
                ]
                if kids:
                    st.initial_manpower[idx] = sum(
                        st.initial_manpower[k] for k in kids
                    )
                    changed = True
            if not changed:
                break
        logger.debug("initial_manpower синхронизирована для всех сущностей")

    def _sync_order_last(self):
        """
        Синхронизирует order_last для всех сущностей.

        Для каждой сущности с сегментом order записывает текущее
        значение приказа в order_last. Для сущностей без сегмента
        order устанавливает order_last в 0.
        """
        st = self.state
        for idx in range(st.count):
            cfg = st.class_configs[st.class_ids[idx]]
            if "order" in cfg.segment_layout.segments:
                st.order_last[idx] = st.read_segment(idx, "order")
            else:
                st.order_last[idx] = 0

    def _get_day(self):
        """
        Возвращает текущий игровой день.

        Читает day из time_system если доступна. Иначе вычисляет
        как tick_count // 24 + 1.

        Returns:
            int: Текущий игровой день.
        """
        ts = getattr(self, "time_system", None)
        if ts is not None and hasattr(ts, "day"):
            return int(ts.day)
        return self.tick_count // 24 + 1

    def tick(self):
        """
        Выполняет один тик старого режима (условный час).

        Последовательность фаз:
        1. Продвижение LOD-менеджера.
        2. Затухание напряжений для активных сущностей.
        3. BDI-тик (если BDI активна).
        4. Тик модальностей среды.
        5. Тик полевого ИИ.
        6. Исполнение приказов игрока (выдвижение, вывод, бой, движение к цели).
        7. Пересчёт боевой мощи и разрешение столкновений.
        8. Применение правил: Шмитт, валидация, метаморфозы.
        9. Тик логистики (если активна).
        10. Обработка приказов.
        11. Коммит буферов.
        12. Сброс накопителей нового режима.
        """
        self.tick_count += 1
        st = self.state
        st.current_tick = self.tick_count
        st.tick_events = []
        self.lod_manager.advance_step()
        logger.debug(
            "tick: номер=%d, сущностей=%d", self.tick_count, st.count
        )
        for idx in range(st.count):
            self._apply_decay(idx)
        if getattr(self, "bdi", None) is not None:
            self.bdi.tick(self.rng)
        if getattr(self, "modalities", None) is not None:
            self.modalities.tick()
        self.field_ai.tick(1.0)
        self._execute_player_orders(1.0)
        self.combat.recompute_power()
        if self.engagements:
            self.combat.resolve_engagements(self.engagements, self.rng)
            self.engagements = self.combat.engagements
        for idx in range(st.count):
            RuleEngine.apply_schmitt(st, idx)
            RuleEngine.apply_validation(st, idx, self.rng)
            RuleEngine.apply_metamorphosis(st, idx, self.rng, trigger="on_tick")
        if self.logistics is not None:
            self.logistics.tick(1.0, self._get_day())
        self._process_orders()
        st.commit_tick()
        self._reset_dt_accumulators()

    def _is_supply_channel(self, ch_name):
        """
        Проверяет, является ли канал каналом снабжения.

        Каналы снабжения исключаются из затухания, так как их
        значения управляются логистической системой.

        Args:
            ch_name: Имя канала напряжения.

        Returns:
            bool: True, если канал является каналом снабжения.
        """
        lower = ch_name.lower()
        return any(marker in lower for marker in SUPPLY_CHANNEL_MARKERS)

    def _apply_decay(self, idx):
        """
        Применяет затухание напряжений для одной сущности в старом режиме.

        Пропускает сущности, для которых decay неактивен на текущем LOD.
        Пропускает каналы снабжения. Для каждого остального канала
        умножает напряжение на decay_alpha и клампует в [min, max].

        Args:
            idx: Индекс сущности.
        """
        if not self.lod_manager.is_active(idx, "decay"):
            return
        st = self.state
        config = st.class_configs[st.class_ids[idx]]
        for ch_name, ch_idx in config.voltage_layout.channel_index.items():
            if self._is_supply_channel(ch_name):
                continue
            _, initial, min_v, max_v, t_low, t_high, alpha = (
                config.voltage_layout.channel_params[ch_name]
            )
            old = st.voltages_next[idx, ch_idx]
            st.voltages_next[idx, ch_idx] = max(
                min_v, min(max_v, alpha * old)
            )

    def _reset_dt_accumulators(self):
        """
        Сбрасывает накопители нового режима в нулевые значения.

        Вызывается после каждого тика старого режима, чтобы два
        режима не смешивались.
        """
        self._bdi_accum_seconds = 0.0
        self._combat_accum_seconds = 0.0
        self._rules_accum_seconds = 0.0
        self._env_accum_seconds = 0.0

    def advance_seconds(
        self, seconds: float, force_combat: bool = False, force_rules: bool = False
    ):
        """
        Продвигает симуляцию на заданное число секунд в новом режиме.

        Разбивает запрошенное время на шаги по simulation_step_seconds.
        Каждый шаг выполняет _tick_seconds. После всех шагов выполняет
        коммит буферов. Последний шаг может принудительно запустить
        бой и правила через флаги force_combat и force_rules.

        Args:
            seconds: Количество секунд для продвижения.
            force_combat: Принудительно разрешить бой на последнем шаге.
            force_rules: Принудительно применить правила на последнем шаге.
        """
        if seconds <= 0:
            return
        logger.debug("advance_seconds: seconds=%.1f", seconds)
        remaining = float(seconds)
        step = max(1.0, self._simulation_step_seconds)
        if not hasattr(self, "_bdi_accum_seconds"):
            self._reset_dt_accumulators()
        while remaining > 1e-6:
            chunk = min(step, remaining)
            last_chunk = remaining <= chunk + 1e-6
            self._tick_seconds(
                chunk,
                force_combat=force_combat and last_chunk,
                force_rules=force_rules and last_chunk,
            )
            remaining -= chunk
        self.state.commit_tick()

    def _tick_seconds(
        self, dt_seconds: float, force_combat: bool = False, force_rules: bool = False
    ):
        """
        Выполняет один шаг симуляции нового режима.

        Последовательность:
        1. Продвижение LOD-менеджера.
        2. Затухание с масштабом времени (alpha ^ dt_hours).
        3. BDI с накоплением: tick_seconds каждые bdi_substep_seconds
           или tick каждые bdi_interval_seconds.
        4. Модальности среды каждые env_interval_seconds.
        5. Полевой ИИ с dt_hours.
        6. Исполнение приказов игрока с dt_hours.
        7. Бой каждые combat_interval_seconds или принудительно.
        8. Правила каждые rules_interval_seconds или принудительно.
        9. Логистика с dt_hours.
        10. Обработка приказов.

        Коммит буферов выполняется один раз в advance_seconds после
        всех шагов, чтобы избежать двойного коммита и смешивания
        состояний между шагами.

        Args:
            dt_seconds: Длительность шага в секундах.
            force_combat: Принудительно разрешить бой.
            force_rules: Принудительно применить правила.
        """
        st = self.state
        dt_hours = dt_seconds / 3600.0
        if not hasattr(self, "_bdi_accum_seconds"):
            self._reset_dt_accumulators()
        self.lod_manager.advance_step()
        self._apply_decay_seconds(dt_hours)
        if self.bdi is not None:
            if hasattr(self.bdi, "tick_seconds"):
                self._bdi_accum_seconds += dt_seconds
                if self._bdi_accum_seconds >= self._bdi_substep_seconds:
                    self.bdi.tick_seconds(self._bdi_accum_seconds, self.rng)
                    self._bdi_accum_seconds = 0.0
            else:
                self._bdi_accum_seconds += dt_seconds
                if self._bdi_accum_seconds >= self._bdi_interval_seconds:
                    self.bdi.tick(self.rng)
                    self._bdi_accum_seconds = 0.0
        self._env_accum_seconds += dt_seconds
        while self._env_accum_seconds >= self._env_interval_seconds:
            self.tick_count += 1
            st.current_tick = self.tick_count
            self.modalities.tick()
            self._env_accum_seconds -= self._env_interval_seconds
        self.field_ai.tick(dt_hours)
        self._execute_player_orders(dt_hours)
        self._combat_accum_seconds += dt_seconds
        if (
            self._combat_accum_seconds >= self._combat_interval_seconds
            or force_combat
        ):
            self.combat.recompute_power()
            if self.engagements:
                self.combat.resolve_engagements(
                    self.engagements,
                    self.rng,
                    dt_seconds=self._combat_accum_seconds,
                )
                self.engagements = self.combat.engagements
            self._combat_accum_seconds = 0.0
        self._rules_accum_seconds += dt_seconds
        if (
            self._rules_accum_seconds >= self._rules_interval_seconds
            or force_rules
        ):
            for idx in range(st.count):
                RuleEngine.apply_schmitt(st, idx)
                RuleEngine.apply_validation(st, idx, self.rng)
                RuleEngine.apply_metamorphosis(
                    st, idx, self.rng, trigger="on_tick"
                )
            self._rules_accum_seconds = 0.0
        if self.logistics is not None:
            self.logistics.tick(dt_hours, self._get_day())
        self._process_orders()

    def _apply_decay_seconds(self, dt_hours: float):
        """
        Применяет затухание напряжений с масштабом времени.

        Для каждого канала вычисляет factor = alpha ^ dt_hours.
        При alpha == 1.0 напряжение не меняется. При alpha <= 0.0
        напряжение обнуляется. Иначе умножает на factor и клампует.
        Пропускает каналы снабжения и неактивные на текущем LOD сущности.

        Args:
            dt_hours: Длительность шага в часах.
        """
        if dt_hours <= 0.0:
            return
        st = self.state
        for idx in range(st.count):
            if not self.lod_manager.is_active(idx, "decay"):
                continue
            config = st.class_configs[st.class_ids[idx]]
            for ch_name, ch_idx in config.voltage_layout.channel_index.items():
                if self._is_supply_channel(ch_name):
                    continue
                _, initial, min_v, max_v, t_low, t_high, alpha = (
                    config.voltage_layout.channel_params[ch_name]
                )
                old = st.voltages_next[idx, ch_idx]
                if alpha == 1.0:
                    new_val = old
                elif alpha <= 0.0:
                    new_val = 0.0
                else:
                    factor = alpha ** dt_hours
                    new_val = old * factor
                st.voltages_next[idx, ch_idx] = max(
                    min_v, min(max_v, new_val)
                )

    def _resolve_order_index(self, order_ref):
        """
        Преобразует ссылку на приказ в индекс таблицы приказов.

        Если order_ref уже int, возвращает его. Иначе ищет строковый
        ID в order_table.id_to_index.

        Args:
            order_ref: Индекс (int) или строковый ID приказа.

        Returns:
            int | None: Индекс приказа или None, если не найден.
        """
        if isinstance(order_ref, int):
            return order_ref
        return self.order_table.id_to_index.get(str(order_ref))

    def _can_afford(self, idx, cost):
        """
        Проверяет, может ли сущность оплатить стоимость приказа.

        Для каждого канала в словаре cost проверяет, что текущее
        напряжение в next-буфере не меньше требуемой суммы.

        Args:
            idx: Индекс сущности.
            cost: Словарь {канал: сумма} стоимости приказа.

        Returns:
            bool: True, если ресурсов достаточно.
        """
        st = self.state
        for channel, amount in cost.items():
            if st.read_voltage_next(idx, channel) < float(amount):
                return False
        return True

    def _pay_order_cost(self, idx, order_idx):
        """
        Списывает стоимость приказа с каналов напряжения сущности.

        Для каждого канала в resource_costs приказа добавляет
        отрицательную дельту через add_voltage.

        Args:
            idx: Индекс сущности.
            order_idx: Индекс приказа в таблице приказов.
        """
        st = self.state
        cost = self.order_table.resource_costs[order_idx]
        logger.debug(
            "Списание стоимости: %s, приказ=%d, cost=%s",
            st.label_of(idx),
            order_idx,
            cost,
        )
        for channel, amount in cost.items():
            st.add_voltage(idx, channel, -float(amount))

    def _order_allowed(self, idx, order_idx):
        """
        Проверяет, разрешено ли назначение приказа сущности игроком.

        Используется только при явном назначении приказа через
        assign_order (от игрока). Проверяет: допустимость индекса,
        выполнение условия приказа через RuleEngine.check,
        достаточность ресурсов, приоритет относительно текущего
        выполняемого приказа (нельзя прервать приказ более высокого
        приоритета приказом более низкого).

        Для приказов, назначенных полевым ИИ или правилами через
        прямую запись сегмента, эта проверка не применяется — они
        принимаются в _process_orders без ограничений приоритета.

        Args:
            idx: Индекс сущности.
            order_idx: Индекс приказа в таблице приказов.

        Returns:
            bool: True, если приказ разрешён.
        """
        st = self.state
        ot = self.order_table
        if order_idx < 0 or order_idx >= len(ot.orders):
            return False
        cond = ot.conditions[order_idx]
        if cond and not RuleEngine.check(st, idx, cond):
            return False
        cost = ot.resource_costs[order_idx]
        if cost and not self._can_afford(idx, cost):
            return False
        cur_progress = float(st.order_progress[idx])
        cur_order = int(st.order_last[idx])
        if 0 <= cur_order < len(ot.orders):
            cur_dur = int(ot.durations[cur_order])
            if cur_dur > 0 and 0.0 < cur_progress < cur_dur:
                if int(ot.priorities[order_idx]) < int(ot.priorities[cur_order]):
                    return False
        return True

    def _resolve_order_targets(self, idx, targets):
        """
        Разрешает цели эффекта приказа в список entity_id.

        Поддерживает специальные цели: "self" (сама сущность),
        "enemies" (все враги), "allies" (все союзники кроме себя).
        Остальные строки интерпретируются как явные entity_id.
        Удаляет дубликаты, сохраняя порядок.

        Args:
            idx: Индекс сущности, назначающей приказ.
            targets: Список целей из эффекта приказа.

        Returns:
            list[str]: Список разрешённых entity_id без дубликатов.
        """
        st = self.state
        resolved = []
        src_faction = st.factions[idx]
        for t in targets:
            if t == "self":
                resolved.append(st.entity_ids[idx])
            elif t == "enemies":
                for i in range(st.count):
                    if st.factions[i] != src_faction:
                        resolved.append(st.entity_ids[i])
            elif t == "allies":
                for i in range(st.count):
                    if st.factions[i] == src_faction and i != idx:
                        resolved.append(st.entity_ids[i])
            else:
                resolved.append(t)
        seen = []
        for r in resolved:
            if r not in seen:
                seen.append(r)
        return seen

    def _apply_order_effect(self, idx, order_idx, phase):
        """
        Применяет эффект приказа в указанной фазе.

        Читает on_start_effects или on_complete_effects из таблицы
        приказов. Если эффект задан, разрешает цели и применяет
        через EffectInterpreter. Если цели не указаны, по умолчанию
        используется сама сущность.

        Args:
            idx: Индекс сущности.
            order_idx: Индекс приказа в таблице приказов.
            phase: Фаза эффекта ("start" или "complete").
        """
        st = self.state
        ot = self.order_table
        if phase == "start":
            effect = ot.on_start_effects[order_idx]
        else:
            effect = ot.on_complete_effects[order_idx]
        if not effect:
            return
        logger.debug(
            "Эффект приказа: %s, приказ=%d, фаза=%s",
            st.label_of(idx),
            order_idx,
            phase,
        )
        effect = dict(effect)
        targets = effect.get("targets")
        if not targets:
            effect["targets"] = [st.entity_ids[idx]]
        else:
            effect["targets"] = self._resolve_order_targets(idx, targets)
        from .effects import EffectInterpreter

        EffectInterpreter.apply(st, effect)

    def _apply_morale(self, idx, delta):
        """
        Применяет изменение морали от приказа.

        Если у сущности есть канал U_morale, добавляет дельту напрямую.
        Иначе использует сегмент morale с накопителем order_morale_accum:
        при накоплении >= 1.0 увеличивает сегмент на 1, при <= -1.0
        уменьшает на 1.

        Args:
            idx: Индекс сущности.
            delta: Изменение морали (положительное или отрицательное).
        """
        st = self.state
        cfg = st.class_configs[st.class_ids[idx]]
        if "U_morale" in cfg.voltage_layout.channel_index:
            st.add_voltage(idx, "U_morale", delta)
            return
        if "morale" in cfg.segment_layout.segments:
            st.order_morale_accum[idx] += delta
            if st.order_morale_accum[idx] >= 1.0:
                cur = st.read_segment_next(idx, "morale")
                mx = cfg.segment_layout.max_value("morale")
                if cur < mx:
                    st.write_segment(idx, "morale", cur + 1)
                st.order_morale_accum[idx] -= 1.0
            elif st.order_morale_accum[idx] <= -1.0:
                cur = st.read_segment_next(idx, "morale")
                if cur > 0:
                    st.write_segment(idx, "morale", cur - 1)
                st.order_morale_accum[idx] += 1.0

    def _next_order_after(self, idx, order_idx):
        """
        Возвращает следующий приказ после завершения текущего.

        Сначала проверяет очередь приказов сущности. Если очередь
        пуста, читает fallback_order из таблицы приказов.

        Args:
            idx: Индекс сущности.
            order_idx: Индекс завершённого приказа.

        Returns:
            int | None: Индекс следующего приказа или None.
        """
        st = self.state
        queue = st.orders_queue[idx]
        if queue:
            return int(queue.pop(0))
        fb = int(self.order_table.fallback_orders[order_idx])
        if fb >= 0:
            return fb
        return None

    def _mobility_of(self, idx):
        """
        Возвращает коэффициент мобильности сущности из боевой модели.

        Args:
            idx: Индекс сущности.

        Returns:
            float: Коэффициент мобильности (по умолчанию 1.0).
        """
        cfg = self.state.class_configs[self.state.class_ids[idx]]
        model = cfg.combat_model or {}
        return float(model.get("mobility", 1.0))

    def _nearest_enemy_idx(self, idx):
        """
        Возвращает индекс ближайшего живого противника.

        Перебирает сущности чужих фракций класса military_unit,
        исключает уничтоженные (condition == 0) и выбирает ближайшую
        по расстоянию Чебышёва. Возвращает None, если противников нет.

        Args:
            idx: Индекс сущности игрока.

        Returns:
            int | None: Индекс ближайшего противника или None.
        """
        st = self.state
        px = int(st.coords[idx, 0])
        py = int(st.coords[idx, 1])
        best = None
        best_dist = None
        for i in range(st.count):
            if st.factions[i] == st.factions[idx]:
                continue
            cfg = st.class_configs[st.class_ids[i]]
            if cfg.class_name != "military_unit":
                continue
            if self.combat._is_dead(i):
                continue
            dist = max(
                abs(int(st.coords[i, 0]) - px),
                abs(int(st.coords[i, 1]) - py),
            )
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = i
        return best

    def _chebyshev(self, a, b):
        """
        Возвращает расстояние Чебышёва между двумя сущностями.

        Args:
            a: Индекс первой сущности.
            b: Индекс второй сущности.

        Returns:
            int: Расстояние Чебышёва.
        """
        st = self.state
        return max(
            abs(int(st.coords[a, 0]) - int(st.coords[b, 0])),
            abs(int(st.coords[a, 1]) - int(st.coords[b, 1])),
        )

    def _world_bounds(self):
        """
        Возвращает границы карты (высота, ширина) в клетках.

        Returns:
            tuple[int, int]: Границы (rows, cols).
        """
        st = self.state
        if st.heights is not None:
            return st.heights.shape
        return (256, 256)

    def _move_player_unit(self, idx, enemy, order, dt_hours, away):
        """
        Перемещает юнит игрока исполнителем приказов.

        Скорость равна скорости приказа, умноженной на мобильность
        и оперативное ускорение PLAYER_SPEED_BOOST, чтобы реакция
        войск игрока ощущалась в течение часов, а не суток.
        Дробная часть движения накапливается. За один вызов
        выполняется не более PLAYER_MAX_STEPS_PER_CALL шагов.
        При away=False юнит движется к противнику, при away=True —
        от противника (вывод из-под удара). Направление (heading)
        обновляется по оси движения, LOD-менеджер уведомляется.

        Args:
            idx: Индекс перемещаемой сущности.
            enemy: Индекс противника.
            order: Индекс приказа в таблице приказов.
            dt_hours: Длительность шага в часах.
            away: Флаг движения от противника.
        """
        st = self.state
        speed = (
            float(self.order_table.move_speed[order])
            * self._mobility_of(idx)
            * PLAYER_SPEED_BOOST
        )
        if speed <= 0.0:
            return
        self.player_move_accum[idx] = (
            self.player_move_accum.get(idx, 0.0) + speed * dt_hours
        )
        steps = int(self.player_move_accum[idx])
        if steps <= 0:
            return
        steps = min(steps, PLAYER_MAX_STEPS_PER_CALL)
        self.player_move_accum[idx] -= steps
        rows, cols = self._world_bounds()
        for _ in range(steps):
            px = int(st.coords[idx, 0])
            py = int(st.coords[idx, 1])
            dx = int(st.coords[enemy, 0]) - px
            dy = int(st.coords[enemy, 1]) - py
            if away:
                dx = -dx
                dy = -dy
            if dx == 0 and dy == 0:
                break
            if abs(dx) >= abs(dy):
                nx = max(0, min(cols - 1, px + (1 if dx > 0 else -1)))
                st.coords[idx, 0] = nx
                st.headings[idx] = 1 if dx > 0 else 3
            else:
                ny = max(0, min(rows - 1, py + (1 if dy > 0 else -1)))
                st.coords[idx, 1] = ny
                st.headings[idx] = 0 if dy < 0 else 2
        self.lod_manager.notify_moved(idx)
        logger.debug(
            "Игрок: %s перемещение шагов=%d, приказ=%s, вывод=%s",
            st.label_of(idx),
            steps,
            self.order_table.orders[order]["id"],
            away,
        )

    def _move_player_unit_to_target(self, idx, target, order, dt_hours):
        """
        Перемещает юнит игрока к заданной целевой точке (для приказа «move»).

        Скорость вычисляется аналогично _move_player_unit, но направление
        определяется разностью координат с целевой точкой. При достижении
        цели (расстояние <= 1) цель удаляется из move_targets.

        Args:
            idx: Индекс перемещаемой сущности.
            target: Кортеж (x, y) целевой точки в клетках карты.
            order: Индекс приказа в таблице приказов.
            dt_hours: Длительность шага в часах.
        """
        st = self.state
        speed = (
            float(self.order_table.move_speed[order])
            * self._mobility_of(idx)
            * PLAYER_SPEED_BOOST
        )
        if speed <= 0.0:
            return
        self.player_move_accum[idx] = (
            self.player_move_accum.get(idx, 0.0) + speed * dt_hours
        )
        steps = int(self.player_move_accum[idx])
        if steps <= 0:
            return
        steps = min(steps, PLAYER_MAX_STEPS_PER_CALL)
        self.player_move_accum[idx] -= steps
        rows, cols = self._world_bounds()
        tx, ty = target
        for _ in range(steps):
            px = int(st.coords[idx, 0])
            py = int(st.coords[idx, 1])
            dx = tx - px
            dy = ty - py
            if abs(dx) <= 1 and abs(dy) <= 1:
                st.coords[idx, 0] = tx
                st.coords[idx, 1] = ty
                self.move_targets.pop(idx, None)
                logger.debug("Игрок: %s достиг цели (%d, %d)", st.label_of(idx), tx, ty)
                break
            if abs(dx) >= abs(dy):
                nx = max(0, min(cols - 1, px + (1 if dx > 0 else -1)))
                st.coords[idx, 0] = nx
                st.headings[idx] = 1 if dx > 0 else 3
            else:
                ny = max(0, min(rows - 1, py + (1 if dy > 0 else -1)))
                st.coords[idx, 1] = ny
                st.headings[idx] = 0 if dy < 0 else 2
        self.lod_manager.notify_moved(idx)

    def _has_engagement(self, a_id, d_id):
        """
        Проверяет, существует ли уже столкновение данной пары.

        Args:
            a_id: entity_id атакующего.
            d_id: entity_id защитника.

        Returns:
            bool: True, если пара уже присутствует в engagements.
        """
        for eng in self.engagements:
            if isinstance(eng, dict):
                if (
                    eng.get("attacker") == a_id
                    and eng.get("defender") == d_id
                ):
                    return True
        return False

    def _execute_player_orders(self, dt_hours):
        """
        Исполняет приказы подразделений игрока с оперативной скоростью.

        Для каждой живой сущности фракции игрока с сегментом order:
        - атакующий приказ (aggressive_attack, attack, cautious_attack):
          при контакте (дистанция <= 1) создаёт боестолкновение, иначе
          ведёт юнит к ближайшему противнику;
        - приказ перемещения или марш-броска (movement, forced_march):
          при противнике в радиусе PLAYER_DISENGAGE_RADIUS выводит
          юнит от противника, позволяя реально отводить побитые части;
        - приказ «move»: если для юнита установлена целевая точка
          (в self.move_targets), двигает юнит к этой точке; после
          достижения цели точка удаляется.
        Исполнитель является единственным источником перемещения
        юнитов игрока: полевой ИИ автономных подразделений их больше
        не двигает. Читает сегмент order из next-буфера через
        read_segment_next, чтобы приказы, записанные map_screen через
        assign_order в течение паузы (до commit_tick), подхватывались
        немедленно, а не только после окончания advance_seconds.
        Каждый вызов логируется в DEBUG с числом обработанных юнитов,
        чтобы в логе всегда было видно, что исполнитель отработал.

        Args:
            dt_hours: Длительность шага в часах.
        """
        st = self.state
        ot = self.order_table
        player_faction = st.factions[st.player_idx]
        processed = 0
        moved = 0
        engaged = 0
        for idx in range(st.count):
            if st.factions[idx] != player_faction:
                continue
            cfg = st.class_configs[st.class_ids[idx]]
            if "order" not in cfg.segment_layout.segments:
                continue
            if self.combat._is_dead(idx):
                continue
            order = int(st.read_segment_next(idx, "order"))
            if order < 0 or order >= len(ot.orders):
                continue
            order_id = ot.orders[order].get("id")
            processed += 1
            if order_id in ATTACK_ORDER_IDS:
                target = self._nearest_enemy_idx(idx)
                if target is None:
                    continue
                dist = self._chebyshev(idx, target)
                if dist <= 1:
                    a_id = st.entity_ids[idx]
                    d_id = st.entity_ids[target]
                    if not self._has_engagement(a_id, d_id):
                        self.engagements.append({
                            "attacker": a_id,
                            "defender": d_id,
                            "projection": "auto",
                            "duration": 1,
                        })
                        engaged += 1
                        logger.info(
                            "Игрок: %s вступает в бой с %s",
                            st.label_of(idx),
                            st.label_of(target),
                        )
                else:
                    self._move_player_unit(
                        idx, target, order, dt_hours, away=False
                    )
                    moved += 1
            elif order_id in RETREAT_ORDER_IDS:
                target = self._nearest_enemy_idx(idx)
                if target is None:
                    continue
                dist = self._chebyshev(idx, target)
                if dist <= PLAYER_DISENGAGE_RADIUS:
                    self._move_player_unit(
                        idx, target, order, dt_hours, away=True
                    )
                    moved += 1
            elif order_id == MOVE_ORDER_ID:
                target = self.move_targets.get(idx)
                if target is not None:
                    self._move_player_unit_to_target(idx, target, order, dt_hours)
                    moved += 1
                else:
                    logger.debug(
                        "Игрок: %s имеет приказ move, но цель не установлена",
                        st.label_of(idx),
                    )
        logger.debug(
            "_execute_player_orders: обработано=%d, перемещено=%d, "
            "вступило в бой=%d",
            processed, moved, engaged,
        )

    def _process_orders(self):
        """
        Обрабатывает приказы всех сущностей на текущем тике.

        Для каждой сущности с сегментом order:
        1. При смене приказа (изменение извне: FieldAI, правила или
           игрок через прямую запись сегмента) принимает новый приказ,
           сбрасывает прогресс и обновляет order_last. Проверка
           приоритета не применяется, чтобы не откатывать легитимные
           приказы полевого ИИ. Недопустимые индексы (вне диапазона)
           откатываются к предыдущему корректному приказу.
        2. Списывает стоимость и применяет on_start-эффект только
           при фактической смене приказа.
        3. Применяет мораль и модификатор целевой функции.
        4. Продвигает прогресс приказа с длительностью. При завершении
           применяет on_complete-эффект и переключает на следующий
           приказ из очереди или fallback.
        5. Для приказов без длительности (duration == 0) и для
           завершённых приказов дренирует очередь: поставленный в
           очередь приказ применяется на следующем тике. Без этого
           приказы игрока, положенные в очередь, никогда не
           выполнялись бы, так как приказ с duration == 0 не
           завершается естественным путём.
        """
        st = self.state
        ot = self.order_table
        n_orders = len(ot.orders)
        for idx in range(st.count):
            cfg = st.class_configs[st.class_ids[idx]]
            if "order" not in cfg.segment_layout.segments:
                continue
            cur = st.read_segment_next(idx, "order")
            last = int(st.order_last[idx])
            if last < 0:
                st.order_last[idx] = cur
                continue
            if last != cur:
                if cur < 0 or cur >= n_orders:
                    revert_to = last if 0 <= last < n_orders else 0
                    st.write_segment(idx, "order", revert_to)
                    st.order_last[idx] = revert_to
                    st.order_progress[idx] = 0.0
                    logger.info(
                        "Приказ восстановлен (некорректный индекс): %s, приказ=%d",
                        st.label_of(idx),
                        revert_to,
                    )
                    continue
                self._pay_order_cost(idx, cur)
                self._apply_order_effect(idx, cur, "start")
                st.order_progress[idx] = 0.0
                st.order_last[idx] = cur
                last = cur
            if cur < 0 or cur >= n_orders:
                continue
            morale = float(ot.morale_effects[cur])
            if morale != 0.0:
                self._apply_morale(idx, morale)
            obj_mod = float(ot.objective_modifiers[cur])
            if obj_mod != 0.0:
                st.objective[idx] = max(
                    0.0, min(1.0, float(st.objective[idx]) + obj_mod)
                )
            duration = int(ot.durations[cur])
            if duration > 0 and st.order_progress[idx] >= 0.0:
                st.order_progress[idx] += 1.0
                if st.order_progress[idx] >= duration:
                    self._apply_order_effect(idx, cur, "complete")
                    logger.info(
                        "Приказ завершён: %s, приказ=%d",
                        st.label_of(idx),
                        cur,
                    )
                    nxt = self._next_order_after(idx, cur)
                    if nxt is not None and 0 <= nxt < n_orders and nxt != cur:
                        st.write_segment(idx, "order", nxt)
                        st.order_progress[idx] = 0.0
                    else:
                        st.order_progress[idx] = -1.0
            else:
                queue = st.orders_queue[idx]
                if queue:
                    nxt = int(queue.pop(0))
                    if 0 <= nxt < n_orders and nxt != cur:
                        self._pay_order_cost(idx, nxt)
                        self._apply_order_effect(idx, nxt, "start")
                        st.write_segment(idx, "order", nxt)
                        st.order_progress[idx] = 0.0
                        st.order_last[idx] = nxt
                        logger.info(
                            "Приказ из очереди применён: %s, приказ=%d",
                            st.label_of(idx),
                            nxt,
                        )

    def assign_order(self, idx, order_ref):
        """
        Назначает приказ сущности от имени игрока.

        Разрешает индекс приказа, проверяет наличие сегмента order,
        допустимость приказа (включая проверку приоритета через
        _order_allowed), списывает стоимость, применяет on_start-эффект,
        записывает приказ в сегмент, сбрасывает прогресс и помечает
        сущность как получившую приказ игрока для полевого ИИ.

        Args:
            idx: Индекс сущности.
            order_ref: Индекс (int) или строковый ID приказа.

        Returns:
            bool: True, если приказ успешно назначен.
        """
        st = self.state
        ot = self.order_table
        order_idx = self._resolve_order_index(order_ref)
        if order_idx is None or order_idx < 0 or order_idx >= len(ot.orders):
            return False
        cfg = st.class_configs[st.class_ids[idx]]
        if "order" not in cfg.segment_layout.segments:
            return False
        if not self._order_allowed(idx, order_idx):
            logger.info(
                "Приказ отклонён: %s, приказ=%s",
                st.label_of(idx),
                ot.orders[order_idx]["label"],
            )
            return False
        self._pay_order_cost(idx, order_idx)
        self._apply_order_effect(idx, order_idx, "start")
        st.write_segment(idx, "order", order_idx)
        st.order_progress[idx] = 0.0
        st.order_last[idx] = order_idx
        self.field_ai.mark_player_ordered(idx)
        logger.info(
            "Приказ назначен: %s, приказ=%s",
            st.label_of(idx),
            ot.orders[order_idx]["label"],
        )
        return True

    def enqueue_order(self, idx, order_ref):
        """
        Добавляет приказ в очередь сущности.

        Приказ будет выполнен после завершения текущего и всех
        ранее добавленных в очередь приказов. Для приказов без
        длительности очередь дренируется в _process_orders на
        следующем тике.

        Args:
            idx: Индекс сущности.
            order_ref: Индекс (int) или строковый ID приказа.

        Returns:
            bool: True, если приказ успешно добавлен в очередь.
        """
        order_idx = self._resolve_order_index(order_ref)
        if order_idx is None or order_idx < 0:
            return False
        self.state.orders_queue[idx].append(order_idx)
        logger.debug(
            "Приказ добавлен в очередь: %s, приказ=%d",
            self.state.label_of(idx),
            order_idx,
        )
        return True

    def set_order_queue(self, idx, order_refs):
        """
        Заменяет очередь приказов сущности.

        Очищает текущую очередь и добавляет новые приказы
        в указанном порядке.

        Args:
            idx: Индекс сущности.
            order_refs: Список индексов (int) или строковых ID приказов.
        """
        self.state.orders_queue[idx] = []
        for ref in order_refs:
            self.enqueue_order(idx, ref)
        logger.debug(
            "Очередь приказов заменена: %s, размер=%d",
            self.state.label_of(idx),
            len(self.state.orders_queue[idx]),
        )

    def set_move_target(self, idx, target):
        """
        Устанавливает целевую точку для приказа «move» для указанной сущности.

        Если target равен None, цель удаляется. Иначе сохраняется как (x, y).

        Args:
            idx: Индекс сущности.
            target: Кортеж (x, y) или None.
        """
        if target is None:
            self.move_targets.pop(idx, None)
        else:
            self.move_targets[idx] = (int(target[0]), int(target[1]))
        logger.debug(
            "Установлена цель для %s: %s",
            self.state.label_of(idx),
            self.move_targets.get(idx),
        )

    def clear_move_target(self, idx):
        """
        Удаляет целевую точку для указанной сущности.

        Args:
            idx: Индекс сущности.
        """
        self.move_targets.pop(idx, None)