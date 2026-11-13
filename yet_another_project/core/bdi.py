"""
core/bdi.py

BDI-система для персонажей.

Реализует архитектуру интеллектуальных агентов Beliefs-Desires-Intentions
для сущностей класса character. Управляет циклом обновления убеждений
с затуханием уверенности и ревизией противоречий, динамикой
потребностей с взаимным давлением и уроном здоровью, генерацией
намерений на основе давлений потребностей и доступных приказов,
выполнением активных намерений и проверкой смерти персонажа.

Убеждения хранятся как взвешенные факты-триплеты (relation, object_ref,
modality). Ревизия обнаруживает дубликаты и конфликтующие пары
(can_satisfy против cannot_satisfy, threatens против safe) и
деактивирует убеждение с меньшей уверенностью, помечая его полем
overridden_by.

Намерения включают безопасные и рискованные действия, поиск,
социальные запросы, отчаянные попытки, избегание, бегство,
бездействие и приказы из таблицы приказов через bdi_relevance.
Финальный выбор делает игрок или внешний Utility AI.

BDI пропускает сущности с уровнем детализации выше LOD 0.
Материализация при переходе из замороженного состояния обновляет
убеждения, применяет динамику потребностей за пропущенное время
и генерирует намерения однократно.

События системы фиксируются в журнале operation_ozverin.log и
дублируются в консоль средствами core.log_journal.
"""
from pathlib import Path
import json
from .log_journal import get_logger

logger = get_logger("core.bdi")

DEFAULT_CONFIDENCE_DECAY = {
    "past": 0.995,
    "present": 0.985,
    "future": 0.95,
    "conditional": 0.94,
}

class BDISystem:
    """
    BDI-система для персонажей.
    Управляет циклом Beliefs-Desires-Intentions, выполняет ревизию
    противоречивых убеждений и учитывает доступные приказы как
    потенциальные намерения через bdi_relevance. Пропускает сущности
    с уровнем детализации выше LOD 0.
    Attributes:
        state: Состояние игрового мира (WorldState).
        global_cfg: Глобальная конфигурация BDI из bdi.json.
        order_table: Таблица приказов (OrderTable) или None.
    """
    def __init__(
        self,
        state,
        global_config_path: str = "configs/content/bdi.json",
    ):
        """
        Инициализирует BDI-систему.
        Загружает глобальную конфигурацию из JSON-файла. При отсутствии
        файла или ошибке парсинга использует пустой словарь, что
        приводит к применению встроенных значений по умолчанию.
        Args:
            state: Состояние игрового мира (WorldState).
            global_config_path: Путь к глобальной конфигурации BDI.
        """
        self.state = state
        self.global_cfg = self._load_global_config(global_config_path)
        self.order_table = None

    def _load_global_config(self, path: str) -> dict:
        """
        Загружает глобальную конфигурацию BDI из JSON-файла.
        Args:
            path: Путь к JSON-файлу конфигурации.
        Returns:
            dict: Словарь конфигурации или пустой словарь при ошибке.
        """
        p = Path(path)
        if not p.exists():
            return {}
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Не удалось прочитать %s: %s", path, e)
            return {}

    def _bdi_cfg(self, idx: int) -> dict:
        """
        Возвращает BDI-конфигурацию для сущности по индексу.
        Читает поле bdi из ClassConfig сущности. Если поле отсутствует
        или пусто, возвращает пустой словарь.
        Args:
            idx: Индекс сущности.
        Returns:
            dict: BDI-конфигурация или пустой словарь.
        """
        st = self.state
        config = st.class_configs[st.class_ids[idx]]
        return getattr(config, "bdi", {}) or {}

    def _needs_cfg(self, idx: int) -> dict:
        """
        Возвращает конфигурацию потребностей для сущности.
        Читает подсловарь needs из BDI-конфигурации сущности.
        Args:
            idx: Индекс сущности.
        Returns:
            dict: Конфигурация потребностей или пустой словарь.
        """
        return self._bdi_cfg(idx).get("needs", {}) or {}

    def _coupling_cfg(self, idx: int) -> dict:
        """
        Возвращает конфигурацию взаимного давления потребностей.
        Читает подсловарь need_coupling из BDI-конфигурации сущности.
        Args:
            idx: Индекс сущности.
        Returns:
            dict: Конфигурация coupling или пустой словарь.
        """
        return self._bdi_cfg(idx).get("need_coupling", {}) or {}

    def _is_character(self, idx: int) -> bool:
        """
        Проверяет, является ли сущность персонажем.
        Сущность считается персонажем, если её class_name равен
        "character" или если в BDI-конфигурации установлен флаг
        is_character.
        Args:
            idx: Индекс сущности.
        Returns:
            bool: True, если сущность является персонажем.
        """
        st = self.state
        config = st.class_configs[st.class_ids[idx]]
        bdi_cfg = getattr(config, "bdi", {}) or {}
        return config.class_name == "character" or bdi_cfg.get(
            "is_character", False
        )

    def _character_indices(self):
        """
        Генератор индексов сущностей-персонажей.
        Yields:
            int: Индекс сущности-персонажа.
        """
        st = self.state
        for i in range(st.count):
            if self._is_character(i):
                yield i

    def _has_channel(self, idx: int, channel: str) -> bool:
        """
        Проверяет наличие канала напряжения у сущности.
        Args:
            idx: Индекс сущности.
            channel: Имя канала.
        Returns:
            bool: True, если канал существует в voltage_layout.
        """
        if not channel:
            return False
        st = self.state
        config = st.class_configs[st.class_ids[idx]]
        return channel in config.voltage_layout.channel_index

    def _channel_for_need(self, idx: int, need_name: str) -> str:
        """
        Возвращает имя канала, связанного с потребностью.
        Args:
            idx: Индекс сущности.
            need_name: Имя потребности.
        Returns:
            str: Имя канала или пустая строка.
        """
        meta = self._needs_cfg(idx).get(need_name, {})
        return meta.get("channel", "")

    def _category_for_need(self, idx: int, need_name: str) -> int:
        """
        Возвращает числовую категорию потребности.
        Категория определяется позицией потребности в словаре needs.
        Потребность "none" всегда имеет категорию 0.
        Args:
            idx: Индекс сущности.
            need_name: Имя потребности.
        Returns:
            int: Числовая категория потребности.
        """
        if need_name == "none":
            return 0
        needs = self._needs_cfg(idx)
        keys = list(needs.keys())
        if need_name not in keys:
            return 0
        return keys.index(need_name) + 1

    def _set_intention_segment(self, idx: int, category: int):
        """
        Записывает категорию активного намерения в сегмент intention.
        Значение клампится в диапазон [0, max_value] сегмента.
        Если сегмент intention отсутствует или имеет нулевую длину,
        операция пропускается.
        Args:
            idx: Индекс сущности.
            category: Числовая категория намерения.
        """
        st = self.state
        config = st.class_configs[st.class_ids[idx]]
        start, length = config.segment_layout.get("intention")
        if length <= 0:
            return
        max_val = config.segment_layout.max_value("intention")
        value = max(0, min(max_val, int(category)))
        st.write_segment(idx, "intention", value)

    def tick(self, rng):
        """
        Совместимый тик длительностью 1 час (3600 секунд).
        Делегирует выполнение в tick_seconds с фиксированной
        длительностью 3600 секунд.
        Args:
            rng: Генератор случайных чисел.
        """
        self.tick_seconds(3600.0, rng)

    def tick_seconds(self, dt_seconds: float, rng):
        """
        Основной тик BDI с масштабом времени.
        Пропускает мёртвых персонажей и сущности с уровнем
        детализации выше LOD 0. Для каждого активного персонажа
        последовательно выполняет: обновление убеждений, выполнение
        активного намерения, динамику потребностей, проверку смерти,
        вычисление целевой функции и генерацию намерений.
        Args:
            dt_seconds: Длительность шага в секундах.
            rng: Генератор случайных чисел.
        """
        dt_scale = max(0.0, dt_seconds / 3600.0)
        st = self.state
        for idx in self._character_indices():
            if st.bdi_dead[idx]:
                continue
            lod_manager = getattr(st, "lod_manager", None)
            if lod_manager is not None and not lod_manager.is_active(idx, "bdi"):
                continue
            self.update_beliefs(idx, dt_scale)
            self.execute_active(idx, rng, dt_scale)
            self.apply_need_dynamics(idx, dt_scale)
            self.check_death(idx)
            if not st.bdi_dead[idx]:
                st.objective[idx] = st.compute_objective(idx)
            self.generate_intentions(idx)

    def materialize_bdi(self, idx: int, skipped_hours: int):
        """
        Материализует BDI-персонажа при переходе из LOD 2 в LOD 0.
        Сбрасывает старое активное намерение и прогресс, обновляет
        убеждения с масштабом пропущенных тиков, применяет динамику
        потребностей за пропущенное время и генерирует новые намерения.
        Не выполняет старые намерения, так как они считаются stale.
        Пропускает неперсонажные и мёртвые сущности.
        Args:
            idx: Индекс материализуемой сущности.
            skipped_hours: Количество пропущенных тиков в часах.
        """
        st = self.state
        if not self._is_character(idx):
            return
        if st.bdi_dead[idx]:
            return
        st.active_intentions[idx] = None
        st.intention_progress[idx] = 0.0
        if skipped_hours > 0:
            self.update_beliefs(idx, dt_scale=float(skipped_hours))
            self.apply_need_dynamics(idx, dt_scale=float(skipped_hours))
            self.generate_intentions(idx)
        logger.debug(
            "BDI материализация: %s, пропущено_часов=%d",
            st.label_of(idx),
            skipped_hours,
        )

    def update_beliefs(self, idx: int, dt_scale: float = 1.0):
        """
        Обновляет убеждения персонажа.
        Применяет экспоненциальное затухание уверенности по
        временности убеждения и запускает ревизию противоречий.
        Коэффициенты затухания читаются из глобальной конфигурации;
        при отсутствии используются значения DEFAULT_CONFIDENCE_DECAY.
        Убеждения с уверенностью <= 0.02 деактивируются.
        Args:
            idx: Индекс сущности.
            dt_scale: Масштаб времени (1.0 = 1 час).
        """
        st = self.state
        decay_map = self.global_cfg.get(
            "confidence_decay", DEFAULT_CONFIDENCE_DECAY
        )
        for belief_id in st.beliefs_by_holder[idx]:
            belief = st.beliefs[belief_id]
            if not belief.get("active", False):
                continue
            temporality = belief.get("temporality", "present")
            decay = float(decay_map.get(temporality, 0.985))
            belief["confidence"] *= decay ** dt_scale
            if belief["confidence"] <= 0.02:
                belief["active"] = False
        self.revise_beliefs(idx)

    def revise_beliefs(self, idx: int):
        """
        Выполняет ревизию убеждений персонажа.
        Обнаруживает и разрешает три типа противоречий:
        1. Дубликаты с одинаковыми relation, object_ref и modality —
           деактивируется убеждение с меньшей уверенностью.
        2. Конфликт can_satisfy и cannot_satisfy для одной модальности
           и объекта — деактивируется убеждение с меньшей уверенностью.
        3. Конфликт threatens и safe для одного объекта — деактивируется
           убеждение с меньшей уверенностью.
        Деактивированное убеждение помечается полем overridden_by
        с идентификатором победившего убеждения.
        Args:
            idx: Индекс сущности.
        """
        st = self.state
        belief_ids = st.beliefs_by_holder[idx]
        if len(belief_ids) < 2:
            return
        active_beliefs = []
        for bid in belief_ids:
            belief = st.beliefs.get(bid)
            if belief is not None and belief.get("active", False):
                active_beliefs.append(belief)
        if len(active_beliefs) < 2:
            return
        revised = 0
        seen = {}
        for belief in active_beliefs:
            key = (
                belief.get("relation"),
                belief.get("object_ref"),
                belief.get("modality"),
            )
            if key in seen:
                existing = seen[key]
                if belief["confidence"] > existing["confidence"]:
                    existing["active"] = False
                    existing["overridden_by"] = belief["id"]
                    seen[key] = belief
                else:
                    belief["active"] = False
                    belief["overridden_by"] = existing["id"]
                revised += 1
            else:
                seen[key] = belief
        can_beliefs = {}
        cannot_beliefs = {}
        for belief in active_beliefs:
            if not belief.get("active", False):
                continue
            rel = belief.get("relation")
            obj = belief.get("object_ref")
            mod = belief.get("modality")
            if rel == "can_satisfy":
                key = (obj, mod)
                if (
                    key not in can_beliefs
                    or belief["confidence"] > can_beliefs[key]["confidence"]
                ):
                    can_beliefs[key] = belief
            elif rel == "cannot_satisfy":
                key = (obj, mod)
                if (
                    key not in cannot_beliefs
                    or belief["confidence"] > cannot_beliefs[key]["confidence"]
                ):
                    cannot_beliefs[key] = belief
        for key, can_b in can_beliefs.items():
            if key in cannot_beliefs:
                cannot_b = cannot_beliefs[key]
                if (
                    not can_b.get("active", False)
                    or not cannot_b.get("active", False)
                ):
                    continue
                if cannot_b["confidence"] >= can_b["confidence"]:
                    can_b["active"] = False
                    can_b["overridden_by"] = cannot_b["id"]
                else:
                    cannot_b["active"] = False
                    cannot_b["overridden_by"] = can_b["id"]
                revised += 1
        threatens = {}
        safe = {}
        for belief in active_beliefs:
            if not belief.get("active", False):
                continue
            rel = belief.get("relation")
            obj = belief.get("object_ref")
            if rel == "threatens":
                if (
                    obj not in threatens
                    or belief["confidence"] > threatens[obj]["confidence"]
                ):
                    threatens[obj] = belief
            elif rel == "safe":
                if (
                    obj not in safe
                    or belief["confidence"] > safe[obj]["confidence"]
                ):
                    safe[obj] = belief
        for obj, threat_b in threatens.items():
            if obj in safe:
                safe_b = safe[obj]
                if (
                    not threat_b.get("active", False)
                    or not safe_b.get("active", False)
                ):
                    continue
                if safe_b["confidence"] >= threat_b["confidence"]:
                    threat_b["active"] = False
                    threat_b["overridden_by"] = safe_b["id"]
                else:
                    safe_b["active"] = False
                    safe_b["overridden_by"] = threat_b["id"]
                revised += 1
        if revised > 0:
            logger.info(
                "Ревизия убеждений: %s, деактивировано=%d",
                st.label_of(idx),
                revised,
            )

    def perceive(
        self,
        holder_idx: int,
        relation: str,
        object_ref,
        modality: str,
        temporality: str = "present",
        confidence: float = 0.5,
        source: str = "observation",
    ) -> int:
        """
        Внешний API для поступления убеждений.
        Создаёт новое убеждение через WorldState.add_belief и
        возвращает его идентификатор.
        Args:
            holder_idx: Индекс владельца убеждения.
            relation: Отношение убеждения (can_satisfy, threatens,
                safe, trusted, ally и т.д.).
            object_ref: Ссылка на объект убеждения.
            modality: Модальность убеждения.
            temporality: Временная характеристика (past, present,
                future, conditional). По умолчанию "present".
            confidence: Начальная уверенность [0, 1]. По умолчанию 0.5.
            source: Источник убеждения. По умолчанию "observation".
        Returns:
            int: Идентификатор созданного убеждения или -1 при ошибке.
        """
        return self.state.add_belief(
            holder_idx=holder_idx,
            relation=relation,
            object_ref=object_ref,
            modality=modality,
            temporality=temporality,
            confidence=confidence,
            source=source,
        )

    def _best_belief(
        self,
        idx: int,
        relation: str = None,
        modality: str = None,
        object_ref=None,
        min_confidence: float = 0.05,
    ):
        """
        Ищет лучшее активное убеждение по фильтрам.
        Возвращает убеждение с максимальной уверенностью среди
        активных убеждений, удовлетворяющих всем заданным фильтрам.
        Args:
            idx: Индекс сущности.
            relation: Фильтр по отношению или None.
            modality: Фильтр по модальности или None.
            object_ref: Фильтр по объекту или None.
            min_confidence: Минимальная уверенность. По умолчанию 0.05.
        Returns:
            dict | None: Лучшее убеждение или None, если не найдено.
        """
        st = self.state
        best = None
        best_conf = -1.0
        for belief_id in st.beliefs_by_holder[idx]:
            belief = st.beliefs[belief_id]
            if not belief.get("active", False):
                continue
            conf = float(belief.get("confidence", 0.0))
            if conf < min_confidence:
                continue
            if relation is not None and belief.get("relation") != relation:
                continue
            if modality is not None and belief.get("modality") != modality:
                continue
            if (
                object_ref is not None
                and belief.get("object_ref") != object_ref
            ):
                continue
            if conf > best_conf:
                best = belief
                best_conf = conf
        return best

    def apply_need_dynamics(self, idx: int, dt_scale: float = 1.0):
        """
        Применяет динамику потребностей персонажа.
        Для каждой потребности ниже критического порога вычисляет
        дефицит, наносит урон здоровью, применяет штрафы к связанным
        потребностям через need_coupling и накапливает стресс.
        Args:
            idx: Индекс сущности.
            dt_scale: Масштаб времени (1.0 = 1 час).
        """
        st = self.state
        needs = self._needs_cfg(idx)
        coupling = self._coupling_cfg(idx)
        if not needs:
            return
        penalties = {}
        health_damage = 0.0
        total_deficit = 0.0
        for need_name, meta in needs.items():
            channel = meta.get("channel")
            if not self._has_channel(idx, channel):
                continue
            value = st.read_voltage_next(idx, channel)
            critical = float(meta.get("critical", 0.25))
            if value >= critical:
                continue
            deficit = (critical - value) / max(critical, 1e-6)
            deficit = max(0.0, min(1.0, deficit))
            total_deficit += deficit
            health_damage += (
                float(meta.get("health_damage", 0.0)) * deficit * dt_scale
            )
            for target_need, factor in coupling.get(need_name, {}).items():
                if target_need not in needs:
                    continue
                penalties[target_need] = (
                    penalties.get(target_need, 0.0)
                    + float(factor) * deficit * dt_scale
                )
        for target_need, penalty in penalties.items():
            channel = needs[target_need].get("channel")
            if self._has_channel(idx, channel):
                st.add_voltage(idx, channel, -penalty)
        if health_damage > 0.0 and self._has_channel(idx, "U_health"):
            st.add_voltage(idx, "U_health", -health_damage)
        if (
            total_deficit > 0.0
            and self._has_channel(idx, "U_stress_accumulated")
        ):
            st.add_voltage(
                idx, "U_stress_accumulated", total_deficit * 0.01 * dt_scale
            )

    def check_death(self, idx: int):
        """
        Проверяет, погиб ли персонаж.
        Персонаж считается погибшим, если канал U_health существует
        и его значение <= 0.0, или если сегмент health существует
        и его значение равно 0. Если ни канала, ни сегмента нет,
        персонаж не может умереть. При смерти устанавливает bdi_dead,
        очищает намерения и применяет death_effect из BDI-конфигурации.
        Args:
            idx: Индекс сущности.
        """
        st = self.state
        config = st.class_configs[st.class_ids[idx]]
        has_health_channel = self._has_channel(idx, "U_health")
        health_voltage = (
            st.read_voltage_next(idx, "U_health")
            if has_health_channel
            else 1.0
        )
        has_health_segment = "health" in config.segment_layout.segments
        health_segment = (
            st.read_segment_next(idx, "health")
            if has_health_segment
            else 1
        )
        dead = False
        if has_health_channel and health_voltage <= 0.0:
            dead = True
        if has_health_segment and health_segment == 0:
            dead = True
        if not has_health_channel and not has_health_segment:
            dead = False
        if not dead:
            return
        if has_health_segment:
            st.write_segment(idx, "health", 0)
        if has_health_channel:
            st.set_voltage_next(idx, "U_health", 0.0)
        st.bdi_dead[idx] = True
        st.active_intentions[idx] = None
        st.intentions[idx] = []
        st.intention_progress[idx] = 0.0
        st.log_event(idx, "Персонаж погиб", {"bdi": "death"})
        logger.info("Персонаж %s погиб", st.label_of(idx))
        effect = self._bdi_cfg(idx).get("death_effect")
        if effect:
            self._apply_death_effect(idx, effect)

    def _generate_order_intentions(
        self, idx: int, pressures: dict, current_objective: float
    ):
        """
        Формирует намерения на основе доступных приказов с bdi_relevance.
        Приказ рассматривается как кандидат, если он связан с
        потребностью через bdi_relevance, давление этой потребности
        превышает 0.01, условие приказа выполнено и ресурсы доступны.
        Score вычисляется из давления, облегчения, риска, модификатора
        целевой функции и текущего значения objective.
        Args:
            idx: Индекс сущности.
            pressures: Словарь давлений потребностей.
            current_objective: Текущее значение целевой функции.
        Returns:
            list: Список словарей намерений-приказов.
        """
        st = self.state
        ot = getattr(self, "order_table", None)
        if ot is None:
            return []
        cfg = st.class_configs[st.class_ids[idx]]
        if "order" not in cfg.segment_layout.segments:
            return []
        from .rules import RuleEngine
        result = []
        for order_idx in range(len(ot.orders)):
            rel = ot.bdi_relevances[order_idx]
            if not rel:
                continue
            need = rel.get("need")
            pressure = pressures.get(need, 0.0) if need else 0.0
            if need and pressure <= 0.01:
                continue
            cond = ot.conditions[order_idx]
            if cond and not RuleEngine.check(st, idx, cond):
                continue
            cost = ot.resource_costs[order_idx]
            affordable = True
            for channel, amount in cost.items():
                if st.read_voltage_next(idx, channel) < float(amount):
                    affordable = False
                    break
            if not affordable:
                continue
            relief = float(rel.get("relief", 0.2))
            risk = float(rel.get("risk", 0.0))
            obj_mod = float(ot.objective_modifiers[order_idx])
            if need:
                score = (
                    pressure * relief
                    - 0.85 * risk
                    + obj_mod * 0.1
                    + (1.0 - current_objective) * 0.05
                )
            else:
                score = relief * 0.1 - 0.85 * risk + obj_mod * 0.1
            order_data = ot.orders[order_idx]
            order_id = order_data.get("id", str(order_idx))
            result.append({
                "id": f"order_{order_id}",
                "label": order_data.get("label", order_id),
                "need": need or "none",
                "category": 0,
                "kind": "order",
                "object_ref": None,
                "belief_ids": [],
                "effects": {},
                "risks": {"safety": risk} if risk > 0 else {},
                "costs": dict(cost),
                "score": float(score),
                "conflicts": [],
                "duration": 1,
                "temporality": "present",
                "current_objective": current_objective,
                "pressure": float(pressure),
                "relief": relief,
                "risk": risk,
                "set_order": order_idx,
            })
        return result

    def generate_intentions(self, idx: int):
        """
        Генерирует список намерений персонажа.
        Вычисляет давления потребностей, ищет лучшие убеждения
        для каждого типа намерения, формирует намерения-приказы
        через _generate_order_intentions, добавляет бездействие
        и помечает конфликты между намерениями. Результат
        записывается в state.intentions[idx].
        Args:
            idx: Индекс сущности.
        """
        st = self.state
        needs = self._needs_cfg(idx)
        pressures = {}
        for need_name, meta in needs.items():
            channel = meta.get("channel")
            if not self._has_channel(idx, channel):
                pressures[need_name] = 0.0
                continue
            value = st.read_voltage_next(idx, channel)
            critical = float(meta.get("critical", 0.25))
            if value >= critical:
                pressures[need_name] = 0.0
            else:
                pressures[need_name] = max(
                    0.0,
                    min(1.0, (critical - value) / max(critical, 1e-6)),
                )
        intentions = []
        threat = self._best_belief(idx, relation="threatens")
        safe_global = self._best_belief(idx, relation="safe")
        current_objective = (
            st.objective[idx] if idx < len(st.objective) else 0.5
        )
        if needs:
            for need_name, pressure in pressures.items():
                if pressure <= 0.01:
                    continue
                meta = needs[need_name]
                need_label = meta.get("label", need_name)
                can = self._best_belief(
                    idx, relation="can_satisfy", modality=need_name
                )
                cannot = self._best_belief(
                    idx, relation="cannot_satisfy", modality=need_name
                )
                if cannot is not None:
                    can_conf = can["confidence"] if can is not None else 0.0
                    cannot_conf = cannot.get("confidence", 0.0)
                    if cannot_conf >= can_conf:
                        can = None
                trusted = (
                    self._best_belief(idx, relation="trusted")
                    or self._best_belief(idx, relation="ally")
                )
                if can is not None:
                    risk = (
                        threat["confidence"] if threat is not None else 0.0
                    )
                    if risk > 0.35:
                        intentions.append(self._make_intention(
                            idx=idx,
                            intention_id=f"satisfy_risky_{need_name}",
                            need=need_name,
                            belief=can,
                            pressure=pressure,
                            relief=0.35,
                            risk=risk,
                            kind="risky_action",
                            pressures=pressures,
                            label=(
                                f"Удовлетворить потребность "
                                f"«{need_label}» с риском"
                            ),
                            current_objective=current_objective,
                        ))
                    else:
                        intentions.append(self._make_intention(
                            idx=idx,
                            intention_id=f"satisfy_safe_{need_name}",
                            need=need_name,
                            belief=can,
                            pressure=pressure,
                            relief=0.35,
                            risk=0.05,
                            kind="safe_action",
                            pressures=pressures,
                            label=(
                                f"Удовлетворить потребность "
                                f"«{need_label}» безопасно"
                            ),
                            current_objective=current_objective,
                        ))
                if can is None:
                    risk = 0.15
                    if threat is not None:
                        risk += threat["confidence"] * 0.35
                    intentions.append(self._make_intention(
                        idx=idx,
                        intention_id=f"seek_{need_name}",
                        need=need_name,
                        belief=None,
                        pressure=pressure,
                        relief=0.12,
                        risk=risk,
                        kind="search",
                        pressures=pressures,
                        label=f"Искать способ удовлетворить «{need_label}»",
                        current_objective=current_objective,
                    ))
                if trusted is not None or pressures.get("social", 0.0) > 0.1:
                    intentions.append(self._make_intention(
                        idx=idx,
                        intention_id=f"ask_help_{need_name}",
                        need=need_name,
                        belief=trusted,
                        pressure=pressure,
                        relief=0.22,
                        risk=0.08,
                        kind="social",
                        pressures=pressures,
                        label=f"Попросить помощи с «{need_label}»",
                        current_objective=current_objective,
                    ))
                if pressure > 0.75:
                    intentions.append(self._make_intention(
                        idx=idx,
                        intention_id=f"desperate_{need_name}",
                        need=need_name,
                        belief=can,
                        pressure=pressure,
                        relief=0.50,
                        risk=0.35,
                        kind="desperate",
                        pressures=pressures,
                        label=(
                            f"Отчаянная попытка удовлетворить «{need_label}»"
                        ),
                        current_objective=current_objective,
                    ))
            safety_pressure = pressures.get("safety", 0.0)
            if threat is not None or safety_pressure > 0.05:
                safe_place = (
                    self._best_belief(idx, relation="safe", modality="safety")
                    or safe_global
                )
                pressure = max(safety_pressure, 0.1)
                intentions.append(self._make_intention(
                    idx=idx,
                    intention_id="stay_safe",
                    need="safety",
                    belief=safe_place,
                    pressure=pressure,
                    relief=0.15,
                    risk=0.0,
                    kind="avoid",
                    pressures=pressures,
                    label="Остаться в безопасности",
                    current_objective=current_objective,
                ))
            if threat is not None and threat.get("confidence", 0.0) > 0.6:
                intentions.append(self._make_intention(
                    idx=idx,
                    intention_id="flee",
                    need="safety",
                    belief=None,
                    pressure=safety_pressure,
                    relief=0.25,
                    risk=0.10,
                    kind="flight",
                    pressures=pressures,
                    label="Бежать в безопасное место",
                    current_objective=current_objective,
                ))
        intentions.extend(
            self._generate_order_intentions(idx, pressures, current_objective)
        )
        intentions.append({
            "id": "idle",
            "label": "Бездействие",
            "need": "none",
            "category": 0,
            "kind": "idle",
            "object_ref": None,
            "belief_ids": [],
            "effects": {},
            "risks": {},
            "costs": {},
            "score": 0.0,
            "conflicts": [],
            "duration": 1,
            "temporality": "present",
            "current_objective": current_objective,
            "pressure": 0.0,
            "relief": 0.0,
            "risk": 0.0,
        })
        self._mark_conflicts(intentions)
        st.intentions[idx] = intentions
        logger.debug(
            "Сгенерировано намерений для %s: %d",
            st.label_of(idx),
            len(intentions),
        )

    def _make_intention(
        self,
        idx: int,
        intention_id: str,
        need: str,
        belief,
        pressure: float,
        relief: float,
        risk: float,
        kind: str,
        pressures: dict,
        label: str = None,
        current_objective: float = 0.5,
    ) -> dict:
        """
        Формирует словарь намерения.
        Вычисляет эффекты на каналы напряжений, score на основе
        давления, облегчения, риска и других факторов, duration
        по типу намерения и риски безопасности.
        Args:
            idx: Индекс сущности.
            intention_id: Идентификатор намерения.
            need: Имя потребности.
            belief: Убеждение, связанное с намерением, или None.
            pressure: Давление потребности.
            relief: Ожидаемое облегчение.
            risk: Риск намерения.
            kind: Тип намерения (safe_action, risky_action, search,
                social, desperate, avoid, flight, idle, order).
            pressures: Словарь давлений всех потребностей.
            label: Человекочитаемая метка намерения или None.
            current_objective: Текущее значение целевой функции.
        Returns:
            dict: Словарь намерения с полями id, label, need,
                category, kind, object_ref, belief_ids, effects,
                risks, costs, score, conflicts, duration,
                temporality, current_objective, pressure, relief, risk.
        """
        st = self.state
        needs = self._needs_cfg(idx)
        meta = needs.get(need, {})
        channel = meta.get("channel")
        category = self._category_for_need(idx, need)
        effects = {}
        if channel and self._has_channel(idx, channel):
            effects[channel] = float(relief)
        if kind == "social":
            social_channel = needs.get("social", {}).get("channel")
            if social_channel and self._has_channel(idx, social_channel):
                effects[social_channel] = (
                    effects.get(social_channel, 0.0) + 0.04
                )
        if risk > 0.0:
            safety_channel = needs.get("safety", {}).get("channel")
            if (
                safety_channel
                and self._has_channel(idx, safety_channel)
                and need != "safety"
            ):
                effects[safety_channel] = (
                    effects.get(safety_channel, 0.0) - 0.25 * float(risk)
                )
            if self._has_channel(idx, "U_stress_accumulated"):
                effects["U_stress_accumulated"] = (
                    effects.get("U_stress_accumulated", 0.0) + 0.15 * float(risk)
                )
        if kind == "flight":
            fatigue_channel = needs.get("fatigue", {}).get("channel")
            if fatigue_channel and self._has_channel(idx, fatigue_channel):
                effects[fatigue_channel] = (
                    effects.get(fatigue_channel, 0.0) - 0.03
                )
        if kind == "avoid":
            calm_channel = needs.get("calm", {}).get("channel")
            if calm_channel and self._has_channel(idx, calm_channel):
                effects[calm_channel] = (
                    effects.get(calm_channel, 0.0) + 0.05
                )
        other_pressure = 0.0
        if pressures:
            other_pressure = sum(
                float(v) for k, v in pressures.items() if k != need
            )
        if kind == "idle":
            score = 0.0
        elif kind == "avoid":
            score = float(pressure) * float(relief) - 0.35 * other_pressure
        else:
            score = (
                float(pressure) * float(relief)
                - 0.85 * max(0.0, float(risk))
            )
        if kind == "social":
            score += pressures.get("social", 0.0) * 0.05
        if kind == "desperate":
            score += float(pressure) * 0.10
        score += (1.0 - current_objective) * 0.1
        belief_ids = []
        object_ref = None
        if belief is not None:
            belief_ids = [belief.get("id")]
            object_ref = belief.get("object_ref")
        duration_map = {
            "safe_action": 1,
            "risky_action": 1,
            "search": 2,
            "social": 1,
            "desperate": 1,
            "avoid": 1,
            "flight": 1,
            "idle": 1,
        }
        risks = {}
        if risk > 0.0:
            risks["safety"] = float(risk)
        return {
            "id": intention_id,
            "label": label or intention_id,
            "need": need,
            "category": category,
            "kind": kind,
            "object_ref": object_ref,
            "belief_ids": belief_ids,
            "effects": effects,
            "risks": risks,
            "costs": {},
            "score": float(score),
            "conflicts": [],
            "duration": int(duration_map.get(kind, 1)),
            "temporality": "present",
            "current_objective": current_objective,
            "pressure": float(pressure),
            "relief": float(relief),
            "risk": float(risk),
        }

    def _mark_conflicts(self, intentions: list):
        """
        Помечает конфликты между намерениями.
        Конфликт возникает, когда намерение A имеет риск по
        безопасности > 0.2 и намерение B связано с безопасностью
        (avoid/flight), или когда A является активным действием
        (не связанным с безопасностью) и B связано с безопасностью.
        Args:
            intentions: Список словарей намерений (мутируется in-place).
        """
        for a in intentions:
            conflicts = set()
            for b in intentions:
                if a is b:
                    continue
                if (
                    a.get("risks", {}).get("safety", 0.0) > 0.2
                    and b.get("need") == "safety"
                    and b.get("kind") in ("avoid", "flight")
                ):
                    conflicts.add(b["id"])
                if (
                    a.get("need") != "safety"
                    and a.get("kind") in (
                        "safe_action",
                        "risky_action",
                        "search",
                        "desperate",
                        "social",
                        "order",
                    )
                    and b.get("need") == "safety"
                    and b.get("kind") in ("avoid", "flight")
                ):
                    conflicts.add(b["id"])
            a["conflicts"] = sorted(conflicts)

    def execute_active(self, idx: int, rng, dt_scale: float = 1.0):
        """
        Выполняет активное намерение персонажа.
        Намерения-приказы (с полем set_order) применяют установку
        сегмента order немедленно и завершаются. Обычные намерения
        применяют эффекты на каналы напряжений пропорционально
        dt_scale / duration и увеличивают прогресс. При достижении
        duration намерение завершается и сбрасывается.
        Args:
            idx: Индекс сущности.
            rng: Генератор случайных чисел (зарезервирован).
            dt_scale: Масштаб времени (1.0 = 1 час).
        """
        st = self.state
        active = st.active_intentions[idx]
        if active is None:
            return
        if active.get("set_order") is not None:
            st.write_segment(idx, "order", int(active["set_order"]))
            st.log_event(
                idx,
                f"Приказ выбран: {active.get('label', active.get('id', '?'))}",
                {"bdi": "order_selected", "order": active.get("set_order")},
            )
            logger.info("%s: приказ выбран через BDI", st.label_of(idx))
            st.active_intentions[idx] = None
            st.intention_progress[idx] = 0.0
            self._set_intention_segment(idx, 0)
            return
        duration = max(1, int(active.get("duration", 1)))
        effects = active.get("effects", {})
        for channel, delta in effects.items():
            if self._has_channel(idx, channel):
                st.add_voltage(
                    idx, channel, float(delta) * dt_scale / float(duration)
                )
        st.intention_progress[idx] += dt_scale
        if st.intention_progress[idx] >= duration:
            st.log_event(
                idx,
                (
                    f"Завершено действие: "
                    f"{active.get('label', active.get('id', '?'))}"
                ),
                {
                    "bdi": "intention_complete",
                    "intention_id": active.get("id"),
                },
            )
            logger.info("%s: действие BDI завершено", st.label_of(idx))
            st.active_intentions[idx] = None
            st.intention_progress[idx] = 0.0
            self._set_intention_segment(idx, 0)

    def set_active_intention(self, idx: int, intention_id) -> bool:
        """
        Назначает активное намерение извне.
        Принимает либо словарь намерения, либо строковый ID для
        поиска в списке намерений сущности. Записывает намерение
        в active_intentions, сбрасывает прогресс, обновляет
        сегмент intention и логирует событие.
        Args:
            idx: Индекс сущности.
            intention_id: Словарь намерения или строковый ID.
        Returns:
            bool: True, если намерение успешно назначено.
        """
        st = self.state
        target = None
        if isinstance(intention_id, dict):
            target = intention_id
        else:
            for intention in st.intentions[idx]:
                if intention.get("id") == intention_id:
                    target = intention
                    break
        if target is None:
            return False
        st.active_intentions[idx] = target
        st.intention_progress[idx] = 0.0
        self._set_intention_segment(idx, target.get("category", 0))
        st.log_event(
            idx,
            (
                f"Выбрано намерение: "
                f"{target.get('label', target.get('id', '?'))}"
            ),
            {"bdi": "intention_selected", "intention_id": target.get("id")},
        )
        return True

    def utility_select(self, idx: int, margin: float = 0.05):
        """
        Вспомогательный Utility-выбор намерения.
        Возвращает намерение с максимальным score. Если активное
        намерение существует и разница в score не превышает margin,
        сохраняет текущее (инерция выбора).
        Args:
            idx: Индекс сущности.
            margin: Порог превосходства для смены активного намерения.
        Returns:
            dict | None: Выбранное намерение или None, если список пуст.
        """
        st = self.state
        intentions = st.intentions[idx]
        if not intentions:
            return None
        best = max(intentions, key=lambda x: x.get("score", 0.0))
        active = st.active_intentions[idx]
        if active is None:
            return best
        if best.get("score", 0.0) > active.get("score", 0.0) + margin:
            return best
        return active

    def _apply_death_effect(self, idx: int, effect: dict):
        """
        Применяет эффект гибели офицера.
        Снижает указанные сегменты всех военных юнитов той же
        фракции на заданную величину. Логирует сообщение из
        эффекта, если оно задано.
        Args:
            idx: Индекс погибшей сущности.
            effect: Словарь эффекта с полем decay_segments и
                опциональным полем log.
        """
        st = self.state
        faction = st.factions[idx]
        decay = effect.get("decay_segments", {})
        affected = 0
        for i in range(st.count):
            if i == idx or st.factions[i] != faction:
                continue
            cfg = st.class_configs[st.class_ids[i]]
            if cfg.class_name != "military_unit":
                continue
            for seg, amount in decay.items():
                if seg in cfg.segment_layout.segments:
                    cur = st.read_segment_next(i, seg)
                    st.write_segment(i, seg, max(0, cur - int(amount)))
            affected += 1
        if effect.get("log"):
            st.log_event(idx, effect["log"])
        logger.info(
            "Эффект гибели офицера: idx=%d, затронуто=%d", idx, affected
        )