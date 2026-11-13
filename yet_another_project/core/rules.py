"""
core/rules.py

Интерпретатор правил из JSON-конфигов: Шмитт, валидация, метаморфозы.

Все правила загружаются из конфигов классов и исполняются движком
на каждом тике или по запросу игрока. Движок не содержит захардкоженной
логики — только интерпретацию декларативных правил.

Поддерживаемые условия: all_of, any_of, segment_equals, segment_at_least,
segment_at_most, voltage_below, voltage_above, biome_equals.
Поддерживаемые действия: set_segment, revert, decay_segment, grow_segment,
decay_all_segments, grow_all_segments, add_voltage.

Строковые значения set_segment и segment_equals разрешаются через
таблицу приказов (для сегмента order) или через список состояний
сегмента. Пропускает сущности с уровнем детализации выше LOD 0 для
подсистемы rules.

События интерпретатора записываются в журнал operation_ozverin.log и
дублируются в консоль средствами core.log_journal.
"""

from .log_journal import get_logger

logger = get_logger("core.rules")


class RuleEngine:
    """
    Статический интерпретатор правил поведения сущностей.

    Методы чтения буферов, проверки условий, исполнения действий,
    применения триггеров Шмитта, валидации и метаморфоз.
    Публичные методы применения правил проверяют активность подсистемы
    rules через lod_manager перед выполнением.
    """

    @staticmethod
    def _is_rules_active(state, idx: int) -> bool:
        """
        Проверяет, активна ли подсистема rules для сущности на текущем LOD.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.

        Returns:
            bool: True, если подсистема rules активна.
        """
        lod_manager = getattr(state, "lod_manager", None)
        if lod_manager is None:
            return True
        return lod_manager.is_active(idx, "rules")

    @staticmethod
    def _read_segment(
        state, idx: int, seg: str, use_next: bool = False
    ) -> int:
        """
        Читает значение сегмента битовой маски сущности.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            seg: Имя сегмента.
            use_next: Если True, читает из next-буфера, иначе из current.

        Returns:
            int: Значение сегмента.
        """
        if not use_next:
            return state.read_segment(idx, seg)
        config = state.class_configs[state.class_ids[idx]]
        start, length = config.segment_layout.get(seg)
        if length <= 0:
            return 0
        mask = (1 << length) - 1
        return int((state.masks_next[idx] >> start) & mask)

    @staticmethod
    def _read_voltage(
        state, idx: int, channel: str, use_next: bool = False
    ) -> float:
        """
        Читает значение канала напряжения сущности.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            channel: Имя канала.
            use_next: Если True, читает из next-буфера, иначе из current.

        Returns:
            float: Значение напряжения.
        """
        if use_next:
            return state.read_voltage_next(idx, channel)
        return state.read_voltage(idx, channel)

    @staticmethod
    def _set_voltage_next(state, idx: int, channel: str, value: float):
        """
        Устанавливает значение канала напряжения в next-буфере с клампом.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            channel: Имя канала.
            value: Новое значение.
        """
        if hasattr(state, "set_voltage_next"):
            state.set_voltage_next(idx, channel, value)
            return
        config = state.class_configs[state.class_ids[idx]]
        ch_idx = config.voltage_layout.channel_index.get(channel)
        if ch_idx is None:
            return
        params = config.voltage_layout.channel_params[channel]
        _, _, min_v, max_v, _, _, _ = params
        state.voltages_next[idx, ch_idx] = max(
            float(min_v), min(float(max_v), float(value))
        )

    @staticmethod
    def _resolve_segment_value(
        state, idx: int, segment: str, value
    ) -> int:
        """
        Разрешает значение сегмента из числа или строки.

        Строка для сегмента order ищется в таблице приказов, для прочих
        сегментов — в списке состояний сегмента. Неразрешённая строка
        даёт 0.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            segment: Имя сегмента.
            value: Число или строковая метка.

        Returns:
            int: Числовое значение сегмента.
        """
        if isinstance(value, str):
            if segment == "order":
                return int(state.order_ids.get(value, 0))
            config = state.class_configs[state.class_ids[idx]]
            entry = config.segment_layout.segments.get(segment)
            if entry is not None:
                states = entry[2]
                if isinstance(states, list) and value in states:
                    return states.index(value)
            return 0
        return int(value)

    @staticmethod
    def check(state, idx: int, cond: dict) -> bool:
        """
        Проверяет условие против current-буфера.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            cond: Словарь условия.

        Returns:
            bool: Результат проверки.
        """
        return RuleEngine._check(state, idx, cond, use_next=False)

    @staticmethod
    def check_next(state, idx: int, cond: dict) -> bool:
        """
        Проверяет условие против next-буфера.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            cond: Словарь условия.

        Returns:
            bool: Результат проверки.
        """
        return RuleEngine._check(state, idx, cond, use_next=True)

    @staticmethod
    def _check(
        state, idx: int, cond: dict, use_next: bool = False
    ) -> bool:
        """
        Внутренний рекурсивный обработчик условий.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            cond: Словарь условия.
            use_next: Если True, читает из next-буфера.

        Returns:
            bool: Результат проверки.
        """
        t = cond.get("type", "")
        if t == "all_of":
            return all(
                RuleEngine._check(state, idx, c, use_next)
                for c in cond.get("conditions", [])
            )
        if t == "any_of":
            return any(
                RuleEngine._check(state, idx, c, use_next)
                for c in cond.get("conditions", [])
            )
        if t == "segment_equals":
            value = RuleEngine._resolve_segment_value(
                state, idx, cond["segment"], cond["value"]
            )
            return (
                RuleEngine._read_segment(
                    state, idx, cond["segment"], use_next
                )
                == value
            )
        if t == "segment_at_least":
            return RuleEngine._read_segment(
                state, idx, cond["segment"], use_next
            ) >= int(cond["value"])
        if t == "segment_at_most":
            return RuleEngine._read_segment(
                state, idx, cond["segment"], use_next
            ) <= int(cond["value"])
        if t in ("voltage_below", "voltage_above"):
            v = RuleEngine._read_voltage(
                state, idx, cond["voltage"], use_next
            )
            if "threshold_voltage" in cond:
                thr = RuleEngine._read_voltage(
                    state, idx, cond["threshold_voltage"], use_next
                )
            else:
                thr = float(cond.get("threshold", 0.0))
            return v < thr if t == "voltage_below" else v > thr
        if t == "biome_equals":
            biomes = getattr(state, "biomes", None)
            coords = getattr(state, "coords", None)
            if biomes is None or coords is None:
                return False
            try:
                rows, cols = biomes.shape
            except Exception:
                return False
            x = int(coords[idx, 0])
            y = int(coords[idx, 1])
            if not (0 <= x < cols and 0 <= y < rows):
                return False
            return int(biomes[y, x]) == int(cond.get("biome", -1))
        return False

    @staticmethod
    def apply_schmitt(state, idx: int):
        """
        Применяет триггеры Шмитта для всех каналов сущности.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
        """
        if not RuleEngine._is_rules_active(state, idx):
            return
        config = state.class_configs[state.class_ids[idx]]
        layout = config.voltage_layout
        for ch_name, meta in layout.schmitt.items():
            target = meta["target_segment"]
            _, _, _, _, t_low, t_high, _ = layout.channel_params[ch_name]
            if t_low is None or t_high is None:
                continue
            v = state.read_voltage_next(idx, ch_name)
            cur = state.read_segment(idx, target)
            max_val = config.segment_layout.max_value(target)
            switched = False
            if meta.get("direction", "improve") == "degrade":
                if v >= t_high and cur > 0:
                    state.write_segment(idx, target, cur - 1)
                    switched = True
                elif v <= t_low and cur < max_val:
                    state.write_segment(idx, target, cur + 1)
                    switched = True
            else:
                if v >= t_high and cur < max_val:
                    state.write_segment(idx, target, cur + 1)
                    switched = True
                elif v <= t_low and cur > 0:
                    state.write_segment(idx, target, cur - 1)
                    switched = True
            if switched:
                RuleEngine._set_voltage_next(state, idx, ch_name, 0.0)
                logger.debug(
                    "Шмитт: idx=%d канал=%s сегмент=%s переключён",
                    idx,
                    ch_name,
                    target,
                )

    @staticmethod
    def _execute(
        state, idx: int, rule: dict, rng, use_next: bool = False
    ) -> bool:
        """
        Исполняет действие, описанное в правиле.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            rule: Словарь правила с полем action.
            rng: Генератор случайных чисел.
            use_next: Если True, читает сегменты из next-буфера.

        Returns:
            bool: True, если действие было исполнено.
        """
        action = rule.get("action", "")
        rate = float(
            rule.get(
                "rate",
                rule.get("decay_rate", rule.get("growth_rate", 1.0)),
            )
        )
        config = state.class_configs[state.class_ids[idx]]
        if action == "set_segment":
            value = RuleEngine._resolve_segment_value(
                state, idx, rule["segment"], rule["value"]
            )
            state.write_segment(idx, rule["segment"], value)
            logger.debug(
                "Действие: idx=%d set_segment %s=%s",
                idx,
                rule["segment"],
                value,
            )
            return True
        if action == "revert":
            target = rule.get("target") or rule.get("target_segment")
            if target:
                cur = RuleEngine._read_segment(
                    state, idx, target, use_next
                )
                if cur > 0:
                    state.write_segment(idx, target, cur - 1)
                    logger.debug(
                        "Действие: idx=%d revert %s", idx, target
                    )
                    return True
            return False
        if action == "decay_segment":
            cur = RuleEngine._read_segment(
                state, idx, rule["segment"], use_next
            )
            if cur > 0 and rng.random() < rate:
                state.write_segment(idx, rule["segment"], cur - 1)
                logger.debug(
                    "Действие: idx=%d decay_segment %s",
                    idx,
                    rule["segment"],
                )
                return True
            return False
        if action == "grow_segment":
            cur = RuleEngine._read_segment(
                state, idx, rule["segment"], use_next
            )
            mx = config.segment_layout.max_value(rule["segment"])
            if cur < mx and rng.random() < rate:
                state.write_segment(idx, rule["segment"], cur + 1)
                logger.debug(
                    "Действие: idx=%d grow_segment %s",
                    idx,
                    rule["segment"],
                )
                return True
            return False
        if action == "decay_all_segments":
            fired = False
            for seg in config.segment_layout.segments:
                if seg == "reserved":
                    continue
                cur = RuleEngine._read_segment(state, idx, seg, use_next)
                if cur > 0 and rng.random() < rate:
                    state.write_segment(idx, seg, cur - 1)
                    fired = True
            if fired:
                logger.debug("Действие: idx=%d decay_all_segments", idx)
            return fired
        if action == "grow_all_segments":
            fired = False
            for seg in config.segment_layout.segments:
                if seg == "reserved":
                    continue
                cur = RuleEngine._read_segment(state, idx, seg, use_next)
                mx = config.segment_layout.max_value(seg)
                if cur < mx and rng.random() < rate:
                    state.write_segment(idx, seg, cur + 1)
                    fired = True
            if fired:
                logger.debug("Действие: idx=%d grow_all_segments", idx)
            return fired
        if action == "add_voltage":
            state.add_voltage(
                idx, rule["voltage"], float(rule["delta"])
            )
            logger.debug(
                "Действие: idx=%d add_voltage %s %+f",
                idx,
                rule["voltage"],
                float(rule["delta"]),
            )
            return True
        return False

    @staticmethod
    def apply_validation(state, idx: int, rng):
        """
        Применяет правила валидации для сущности.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            rng: Генератор случайных чисел.
        """
        if not RuleEngine._is_rules_active(state, idx):
            return
        config = state.class_configs[state.class_ids[idx]]
        for rule in config.validation_rules:
            if rule.get("trigger", "on_tick") not in (
                "on_tick",
                "on_indicator_change",
            ):
                continue
            if not RuleEngine.check_next(
                state, idx, rule.get("condition", {})
            ):
                continue
            executed = RuleEngine._execute(
                state, idx, rule, rng, use_next=True
            )
            if executed:
                logger.debug(
                    "Валидация: idx=%d правило=%s сработало",
                    idx,
                    rule.get("id"),
                )
                if rule.get("message"):
                    state.log_event(idx, rule["message"])

    @staticmethod
    def apply_metamorphosis(
        state,
        idx: int,
        rng,
        trigger: str = "on_tick",
        decision_name: str = None,
    ):
        """
        Применяет правила метаморфозы для сущности.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            rng: Генератор случайных чисел.
            trigger: Тип триггера ("on_tick" или "on_player_decision").
            decision_name: Имя решения игрока (для on_player_decision).
        """
        if not RuleEngine._is_rules_active(state, idx):
            return
        config = state.class_configs[state.class_ids[idx]]
        for rule in config.metamorphosis_rules:
            if rule.get("trigger", "on_tick") != trigger:
                continue
            if (
                trigger == "on_player_decision"
                and rule.get("decision_name") != decision_name
            ):
                continue
            if RuleEngine.check(state, idx, rule.get("condition", {})):
                RuleEngine._execute(
                    state, idx, rule.get("on_success", {}), rng, use_next=False
                )
                if rule.get("message_success"):
                    state.log_event(idx, rule["message_success"])
                logger.info(
                    "Метаморфоза: idx=%d правило=%s успех",
                    idx,
                    rule.get("id"),
                )
            elif trigger == "on_player_decision":
                if rule.get("message_failure"):
                    state.log_event(idx, rule.get("message_failure"))
                logger.info(
                    "Метаморфоза: idx=%d правило=%s провал",
                    idx,
                    rule.get("id"),
                )

    @staticmethod
    def try_decision(state, idx: int, decision_name: str, rng):
        """
        Обрабатывает решение игрока.

        Args:
            state: Состояние мира (WorldState).
            idx: Индекс сущности.
            decision_name: Имя решения игрока.
            rng: Генератор случайных чисел.
        """
        logger.info(
            "Решение игрока: idx=%d решение=%s", idx, decision_name
        )
        RuleEngine.apply_metamorphosis(
            state,
            idx,
            rng,
            trigger="on_player_decision",
            decision_name=decision_name,
        )