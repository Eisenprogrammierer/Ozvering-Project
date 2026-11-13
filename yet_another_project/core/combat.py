"""
core/combat.py

Боевая система: расчёт силы, разрешение столкновений, потери,
отступление и паника. Поддерживает LOD, фазы боя, марковские цепи,
геометрию проекций и модификаторы местности.

Класс CombatSystem вычисляет количественную и качественную силу
подразделений, пересчитывает боевую мощь по приказам с учётом
модификатора боеприпасов из логистики, разрешает боестолкновения
с учётом геометрии проекций, локального превосходства и баланса
атаки/обороны, применяет потери, расходует снабжение, проверяет
отступление и панику.

Потери моделируются как доля начальной численности в сутки и
зависят от проекции входящего удара по защитнику:
- фронтальная проекция (спокойный фронт без прорывов) даёт
  1-3% потерь в сутки в зависимости от давления противника;
- фланговая, тыловая, верхняя или нижняя проекция (прорыв,
  охват, окружение) даёт 20-35% потерь в сутки;
- атакующий при фронтальном штурме теряет до 6% в сутки, при
  добивании небоеспособного защитника - минимальные потери.
Давление (соотношение боевой мощи сторон) интерполирует суточную
долю внутри диапазона режима. Суммарные потери юнита за одно
разрешение боя ограничены потолком loss_tick_cap, чтобы полное
окружение выдавливало подразделение за сутки, а не испаряло за
час. Канал U_casualties синхронизирован с накопленной долей
потерь от начальной численности, поэтому условие поражения при
потерях >= 45% срабатывает корректно.

Старшие уровни иерархии (батальон, полк, дивизия) получают потери
из собственных боестолкновений, создаваемых полевым ИИ на каждом
уровне; каскадное дублирование потерь на родителей отменено, чтобы
исключить двойной счёт.

Обмен потерями корректируется множителями фаз боя
(attacker_loss_multiplier / defender_loss_multiplier) и
модификатором местности. Автоотход при тяжёлых потерях применяется
только к автономным (противнику) подразделениям; части игрока
держат позицию до последнего или до приказа командира.

Бой расходует снабжение (боеприпасы и топливо) через хук
logistics.consume_combat, поэтому без управления потоками
снабжения боевая мощь деградирует.

Учитывает виртуальные структуры дивизий (DivisionalStructure)
для тактических потерь по секторам и модификаторы черт персонажа.
"""

import random

import numpy as np

from .combat_geometry import (
    PROJ_FRONT,
    incoming_projection,
    normalize_projection,
)
from .config_loader import load_json
from .log_journal import get_logger
from .terrain import terrain_defense_modifier
from .traits import get_supply_loss_on_casualties

logger = get_logger("core.combat")


class MarkovPhaseModel:
    """
    Марковская цепь для фаз боя.

    Отслеживает переходы между фазами, обновляет матрицу переходов
    экспоненциальным сглаживанием и предсказывает распределение
    вероятностей следующих фаз для корректировки множителей потерь.

    Attributes:
        phase_ids: Список идентификаторов фаз.
        n: Количество фаз.
        index: Отображение id фазы на индекс матрицы.
        transition_matrix: Матрица переходов n×n.
        transition_memory: Коэффициент памяти переходов [0, 1].
        total_transitions: Общее число зарегистрированных переходов.
    """

    def __init__(self, phase_ids, transition_memory=0.9):
        """
        Инициализирует марковскую модель фаз боя.

        Создаёт равномерную матрицу переходов размером n×n, где
        n — количество фаз. При n == 0 матрица остаётся пустой.

        Args:
            phase_ids: Итерируемый объект идентификаторов фаз.
            transition_memory: Коэффициент памяти переходов.
                Чем ближе к 1.0, тем медленнее обновляется матрица.
                По умолчанию 0.9.
        """
        self.phase_ids = list(phase_ids)
        self.n = len(self.phase_ids)
        self.index = {pid: i for i, pid in enumerate(self.phase_ids)}
        if self.n > 0:
            self.transition_matrix = [
                [1.0 / self.n for _ in range(self.n)]
                for _ in range(self.n)
            ]
        else:
            self.transition_matrix = []
        self.transition_memory = float(transition_memory)
        self.total_transitions = 0

    def record_transition(self, from_id, to_id):
        """
        Регистрирует переход между фазами и обновляет матрицу сглаживанием.

        Строка from_id обновляется по формуле:
            row[k] += alpha * (target - row[k])
        где alpha = 1.0 - transition_memory, target = 1.0 для k == j
        и 0.0 иначе. После обновления строка нормализуется.

        Пропускает вызов, если n == 0, либо from_id/to_id равны None,
        либо отсутствуют в индексе фаз.

        Args:
            from_id: Идентификатор исходной фазы.
            to_id: Идентификатор целевой фазы.
        """
        if self.n == 0:
            return
        if from_id is None or to_id is None:
            return
        if from_id not in self.index or to_id not in self.index:
            return
        i = self.index[from_id]
        j = self.index[to_id]
        self.total_transitions += 1
        alpha = 1.0 - self.transition_memory
        row = self.transition_matrix[i]
        for k in range(self.n):
            target = 1.0 if k == j else 0.0
            row[k] += alpha * (target - row[k])
        row_sum = sum(row)
        if row_sum > 0:
            for k in range(self.n):
                row[k] /= row_sum

    def predict(self, current_id):
        """
        Возвращает распределение вероятностей следующих фаз.

        Читает строку матрицы переходов для current_id и формирует
        словарь {phase_id: probability}. Возвращает пустой словарь,
        если n == 0 или current_id отсутствует в индексе.

        Args:
            current_id: Идентификатор текущей фазы.

        Returns:
            dict[str, float]: Вероятности перехода в каждую фазу.
        """
        if self.n == 0:
            return {}
        if current_id is None or current_id not in self.index:
            return {}
        i = self.index[current_id]
        return {
            self.phase_ids[j]: float(self.transition_matrix[i][j])
            for j in range(self.n)
        }

    def expected_multiplier(self, current_id, phase_multipliers):
        """
        Вычисляет ожидаемый множитель потерь по предсказанию.

        Умножает вероятность каждой фазы на соответствующий множитель
        из phase_multipliers и суммирует. Возвращает 1.0, если
        предсказание пусто или сумма неположительна.

        Args:
            current_id: Идентификатор текущей фазы.
            phase_multipliers: Словарь {phase_id: multiplier}.

        Returns:
            float: Ожидаемый множитель потерь.
        """
        probs = self.predict(current_id)
        if not probs:
            return 1.0
        expected = 0.0
        for pid, prob in probs.items():
            expected += prob * float(phase_multipliers.get(pid, 1.0))
        return expected if expected > 0 else 1.0


class CombatSystem:
    """
    Боевая система.

    Вычисляет количественную и качественную силу, пересчитывает боевую
    мощь по приказам с учётом модификатора боеприпасов из логистики,
    разрешает боестолкновения с учётом геометрии проекций и суточной
    модели потерь, проверяет отступление и панику.

    Поддерживает тактические потери через DivisionalStructure
    и модификаторы снабжения при потерях через черты персонажа.

    Attributes:
        state: Состояние игрового мира (WorldState).
        ot: Таблица приказов (OrderTable).
        engagements: Список активных боестолкновений после разрешения.
        defaults: Глобальные боевые параметры из combat_defaults.json.
        loss_scale: Устаревший базовый масштаб потерь (не используется
            в суточной модели, хранится для совместимости конфигураций).
        _loss_daily_calm_min: Минимальная суточная доля потерь
            защитника на фронте без прорыва.
        _loss_daily_calm_max: Максимальная суточная доля потерь
            защитника на фронте без прорыва.
        _loss_daily_break_min: Минимальная суточная доля потерь
            защитника при прорыве во фланги и тылы.
        _loss_daily_break_max: Максимальная суточная доля потерь
            защитника при прорыве во фланги и тылы.
        _loss_daily_assault_max: Максимальная суточная доля потерь
            атакующего при фронтальном штурме.
        _loss_tick_cap: Потолок потерь за одно разрешение боя,
            доля от начальной численности.
        _tick_loss: Накопленные потери сущностей за текущее
            разрешение боя для контроля потолка.
    """

    def __init__(self, state, order_table):
        """
        Инициализирует боевую систему.

        Загружает глобальные параметры из configs/content/combat_defaults.json,
        создаёт массив combat_power в состоянии, если его нет,
        и логирует ключевые параметры инициализации.

        Args:
            state: Состояние игрового мира (WorldState).
            order_table: Таблица приказов (OrderTable).
        """
        self.state = state
        self.ot = order_table
        self.engagements = []
        self.defaults = load_json(
            "configs/content/combat_defaults.json", {}
        ) or {}
        self.loss_scale = float(self.defaults.get("loss_scale", 0.012))
        self._loss_daily_calm_min = float(
            self.defaults.get("loss_daily_calm_min", 0.01)
        )
        self._loss_daily_calm_max = float(
            self.defaults.get("loss_daily_calm_max", 0.03)
        )
        self._loss_daily_break_min = float(
            self.defaults.get("loss_daily_break_min", 0.20)
        )
        self._loss_daily_break_max = float(
            self.defaults.get("loss_daily_break_max", 0.35)
        )
        self._loss_daily_assault_max = float(
            self.defaults.get("loss_daily_assault_max", 0.06)
        )
        self._loss_tick_cap = float(
            self.defaults.get("loss_tick_cap", 0.02)
        )
        self._tick_loss = {}
        self._ensure_combat_power()
        logger.info(
            "CombatSystem инициализирована: спокойный фронт=%.0f-%.0f%%/сут, "
            "прорыв=%.0f-%.0f%%/сут, потолок за бой=%.0f%%",
            100.0 * self._loss_daily_calm_min,
            100.0 * self._loss_daily_calm_max,
            100.0 * self._loss_daily_break_min,
            100.0 * self._loss_daily_break_max,
            100.0 * self._loss_tick_cap,
        )

    def _ensure_combat_power(self):
        """
        Создаёт массив combat_power в состоянии, если его нет.

        Инициализирует state.combat_power нулевым массивом формы
        (capacity, 6) типа float64 для хранения боевой мощи по
        шести проекциям каждой сущности.
        """
        st = self.state
        if not hasattr(st, "combat_power") or st.combat_power is None:
            st.combat_power = np.zeros((st.capacity, 6), dtype=np.float64)

    def _model(self, idx):
        """
        Возвращает боевую модель сущности.

        Читает combat_model из конфигурации класса сущности.
        Возвращает пустой словарь, если модель не задана.

        Args:
            idx: Индекс сущности в WorldState.

        Returns:
            dict: Боевая модель сущности.
        """
        cfg = self.state.class_configs[self.state.class_ids[idx]]
        return cfg.combat_model or {}

    def _default_param(self, key, fallback):
        """
        Возвращает глобальный параметр по умолчанию.

        Читает значение из self.defaults по ключу key.
        Если ключ отсутствует, возвращает fallback.

        Args:
            key: Имя параметра.
            fallback: Значение по умолчанию.

        Returns:
            Значение параметра или fallback.
        """
        return self.defaults.get(key, fallback)

    def _channel_role(self, role, fallback):
        """
        Возвращает имя канала по его роли.

        Читает отображение ролей из defaults["channels"].
        Если роль не найдена, возвращает fallback.

        Args:
            role: Роль канала (например, "manpower", "casualties").
            fallback: Имя канала по умолчанию.

        Returns:
            str: Имя канала напряжения.
        """
        channels = self.defaults.get("channels", {}) or {}
        return channels.get(role, fallback)

    def _combat_param(self, idx, key, fallback):
        """
        Возвращает боевой параметр сущности или глобальный дефолт.

        Сначала ищет ключ в combat_model конкретной сущности.
        Если не найден, читает из глобальных defaults.
        Если и там нет, возвращает fallback.

        Args:
            idx: Индекс сущности.
            key: Имя параметра.
            fallback: Значение по умолчанию.

        Returns:
            Значение параметра.
        """
        model = self._model(idx)
        if key in model:
            return model[key]
        return self._default_param(key, fallback)

    def _has_segment(self, idx, seg_name):
        """
        Проверяет наличие сегмента в маске сущности.

        Args:
            idx: Индекс сущности.
            seg_name: Имя сегмента.

        Returns:
            bool: True, если сегмент существует в классе сущности.
        """
        cfg = self.state.class_configs[self.state.class_ids[idx]]
        return seg_name in cfg.segment_layout.segments

    def _is_dead(self, idx):
        """
        Проверяет, уничтожена ли сущность.

        Сущность считается уничтоженной, если у неё есть сегмент
        condition и его значение равно 0.

        Args:
            idx: Индекс сущности.

        Returns:
            bool: True, если сущность уничтожена.
        """
        if not self._has_segment(idx, "condition"):
            return False
        return self.state.read_segment(idx, "condition") == 0

    def _safe_order_index(self, order_idx):
        """
        Безопасно приводит индекс приказа к допустимому диапазону.

        Преобразует входное значение в int, ограничивает диапазоном
        [0, len(can_fight)). При ошибке преобразования или выходе
        за границы возвращает 0.

        Args:
            order_idx: Индекс приказа (int или приводимое к int).

        Returns:
            int: Корректный индекс приказа.
        """
        n = len(self.ot.can_fight)
        if n == 0:
            return 0
        try:
            order_idx = int(order_idx)
        except Exception:
            order_idx = 0
        if order_idx < 0 or order_idx >= n:
            return 0
        return order_idx

    def _get_projection(self, a_idx, d_idx, explicit_proj):
        """
        Определяет проекцию удара: явную или геометрическую.

        Если explicit_proj задан и не равен "auto", нормализует его.
        Иначе вычисляет входящую проекцию защитника на основе
        координат и направления взгляда через combat_geometry.

        Args:
            a_idx: Индекс атакующего.
            d_idx: Индекс защитника.
            explicit_proj: Явно заданная проекция или "auto".

        Returns:
            int: Индекс проекции (0–5).
        """
        if explicit_proj and explicit_proj != "auto":
            return normalize_projection(explicit_proj)
        return incoming_projection(
            self.state.coords[a_idx, 0],
            self.state.coords[a_idx, 1],
            self.state.coords[d_idx, 0],
            self.state.coords[d_idx, 1],
            self.state.headings[d_idx],
        )

    def _lod_level(self, idx):
        """
        Возвращает уровень LOD сущности или 0 при отсутствии массива.

        Args:
            idx: Индекс сущности.

        Returns:
            int: Уровень детализации (0, 1 или 2).
        """
        lod_arr = getattr(self.state, "lod_level", None)
        if lod_arr is None:
            return 0
        return int(lod_arr[idx])

    def quant_strength(self, idx: int) -> float:
        """
        Вычисляет количественную боевую силу подразделения.

        Суммирует произведения значений каналов напряжений на веса
        из weapon_weights боевой модели. Если weapon_weights пуст
        или отсутствует, возвращает 0.0.

        Формула: quant_strength = Σ voltage[channel] * weight[channel]

        Args:
            idx: Индекс сущности.

        Returns:
            float: Количественная боевая сила.
        """
        st = self.state
        config = st.class_configs[st.class_ids[idx]]
        model = config.combat_model or {}
        weights = model.get("weapon_weights", {})
        total = 0.0
        for channel, weight in weights.items():
            val = st.read_voltage(idx, channel)
            total += val * weight
        return total

    def qual_factor(self, idx: int) -> float:
        """
        Вычисляет качественный фактор подразделения.

        Усредняет нормализованные значения сегментов качества:
        experience, morale, professionalism, discipline, cohesion,
        supply, fatigue. Каждое значение делится на максимум сегмента.

        Возвращает 0.0, если ни один сегмент качества не определён.

        Args:
            idx: Индекс сущности.

        Returns:
            float: Качественный фактор в диапазоне [0, 1].
        """
        st = self.state
        segs = [
            "experience", "morale", "professionalism",
            "discipline", "cohesion", "supply", "fatigue",
        ]
        total = 0.0
        count = 0
        for seg in segs:
            val = st.read_segment(idx, seg)
            max_val = st.class_configs[
                st.class_ids[idx]
            ].segment_layout.max_value(seg)
            if max_val > 0:
                total += val / max_val
                count += 1
        return total / count if count > 0 else 0.0

    def recompute_power(self):
        """
        Пересчитывает боевую мощь всех сущностей по приказам.

        Для каждой сущности: если приказ позволяет вести бой
        (can_fight=True), вычисляет combat_power как произведение
        качественного фактора, количественной силы и firepower
        приказа по каждой проекции, умноженное на модификатор
        боеприпасов из логистики. Если can_fight=False, обнуляет
        все проекции.
        """
        self._ensure_combat_power()
        st = self.state
        logistics = getattr(st, "logistics_system", None)
        for idx in range(st.count):
            order = self._safe_order_index(st.read_segment(idx, "order"))
            if not self.ot.can_fight[order]:
                st.combat_power[idx, :] = 0.0
                continue
            q = self.qual_factor(idx)
            quant = self.quant_strength(idx)
            base = q * quant
            ammo_mod = 1.0
            if logistics is not None:
                ammo_mod = logistics.get_ammo_modifier(idx)
            st.combat_power[idx, :] = base * self.ot.fire[order] * ammo_mod

    def _daily_fraction(
        self, strike_attacker, strike_defender, frac_min, frac_max
    ):
        """
        Вычисляет суточную долю потерь по давлению противника.

        Давление - это отношение боевой мощи атакующей стороны к
        мощи обороняющейся. При давлении 0.5 и ниже доля равна
        минимуму диапазона, при давлении 2.0 и выше - максимуму,
        между ними - линейная интерполяция.

        Args:
            strike_attacker: Боевая мощь атакующей стороны.
            strike_defender: Боевая мощь обороняющейся стороны.
            frac_min: Минимальная суточная доля потерь.
            frac_max: Максимальная суточная доля потерь.

        Returns:
            float: Суточная доля потерь в диапазоне [frac_min, frac_max].
        """
        pressure = strike_attacker / max(1.0, strike_defender)
        t = max(0.0, min(1.0, (pressure - 0.5) / 1.5))
        return frac_min + (frac_max - frac_min) * t

    def _get_battle_phases(self, a_idx, d_idx):
        """
        Возвращает список фаз боя для пары сторон.

        Приоритет отдаётся боевой модели атакующего. Если у него
        фазы не заданы, используются фазы защитника.

        Args:
            a_idx: Индекс атакующего.
            d_idx: Индекс защитника.

        Returns:
            list[dict]: Список описаний фаз боя.
        """
        model_a = self._model(a_idx)
        model_d = self._model(d_idx)
        phases = model_a.get("battle_phases")
        if phases:
            return phases
        return model_d.get("battle_phases") or []

    def _get_markov_config(self, a_idx, d_idx):
        """
        Возвращает конфигурацию марковской цепи для пары сторон.

        Приоритет отдаётся боевой модели атакующего.

        Args:
            a_idx: Индекс атакующего.
            d_idx: Индекс защитника.

        Returns:
            dict: Конфигурация марковской цепи.
        """
        model_a = self._model(a_idx)
        model_d = self._model(d_idx)
        cfg = model_a.get("markov")
        if cfg:
            return cfg
        return model_d.get("markov") or {}

    def _phase_condition_met(self, phase, data, a_idx, d_idx):
        """
        Проверяет условие входа в фазу боя.

        Поддерживает типы условий: always, and, or, time_at_least,
        attacker_losses_at_least, defender_losses_at_least,
        incoming_projection_in. Рекурсивно обрабатывает вложенные
        условия для and/or.

        Args:
            phase: Описание фазы с полем entry_condition.
            data: Словарь данных столкновения (_time_seconds,
                _attacker_losses, _defender_losses, _last_defender_projection).
            a_idx: Индекс атакующего.
            d_idx: Индекс защитника.

        Returns:
            bool: True, если условие выполнено.
        """
        condition = phase.get("entry_condition")
        if not condition:
            return True
        t = condition.get("type", "always")
        if t == "always":
            return True
        if t == "and":
            return all(
                self._phase_condition_met(c, data, a_idx, d_idx)
                for c in condition.get("conditions", [])
            )
        if t == "or":
            return any(
                self._phase_condition_met(c, data, a_idx, d_idx)
                for c in condition.get("conditions", [])
            )
        if t == "time_at_least":
            return data.get("_time_seconds", 0.0) >= float(
                condition.get("seconds", 0.0)
            )
        if t == "attacker_losses_at_least":
            return data.get("_attacker_losses", 0.0) >= float(
                condition.get("value", 0.0)
            )
        if t == "defender_losses_at_least":
            return data.get("_defender_losses", 0.0) >= float(
                condition.get("value", 0.0)
            )
        if t == "incoming_projection_in":
            projections = condition.get("projections", [])
            current = data.get("_last_defender_projection", PROJ_FRONT)
            normalized = set()
            for p in projections:
                normalized.add(normalize_projection(p))
            return current in normalized
        return False

    def _curve_multiplier(self, curve, phase_time_seconds, default=1.0):
        """
        Вычисляет множитель потерь по кривой внутри фазы.

        Между точками кривой применяется линейная интерполяция.
        До первой точки возвращается множитель первой точки,
        после последней — множитель последней точки.
        Если кривая пуста, возвращается default.

        Args:
            curve: Список точек {"at_seconds": float, "multiplier": float}.
            phase_time_seconds: Время внутри текущей фазы в секундах.
            default: Множитель по умолчанию при пустой кривой.

        Returns:
            float: Интерполированный множитель.
        """
        if not curve:
            return float(default)
        points = sorted(
            curve, key=lambda p: float(p.get("at_seconds", 0.0))
        )
        if not points:
            return float(default)
        t = float(phase_time_seconds)
        if t <= float(points[0].get("at_seconds", 0.0)):
            return float(points[0].get("multiplier", default))
        if t >= float(points[-1].get("at_seconds", 0.0)):
            return float(points[-1].get("multiplier", default))
        for i in range(len(points) - 1):
            p0 = points[i]
            p1 = points[i + 1]
            t0 = float(p0.get("at_seconds", 0.0))
            t1 = float(p1.get("at_seconds", 0.0))
            if t0 <= t <= t1:
                m0 = float(p0.get("multiplier", default))
                m1 = float(p1.get("multiplier", default))
                if t1 <= t0:
                    return m1
                alpha = (t - t0) / (t1 - t0)
                return m0 + alpha * (m1 - m0)
        return float(default)

    def _update_phase(self, data, a_idx, d_idx, dt_seconds):
        """
        Обновляет фазу боя и возвращает множители потерь.

        Определяет текущую фазу по условиям входа, обновляет таймеры,
        регистрирует переходы в марковской цепи (если включена),
        вычисляет множители по кривым и корректирует их предсказанием
        марковской цепи.

        Args:
            data: Словарь данных столкновения (мутируется in-place).
            a_idx: Индекс атакующего.
            d_idx: Индекс защитника.
            dt_seconds: Длительность шага в секундах.

        Returns:
            dict: {"attacker_loss_multiplier": float,
                   "defender_loss_multiplier": float}.
        """
        if dt_seconds is None:
            return {
                "attacker_loss_multiplier": 1.0,
                "defender_loss_multiplier": 1.0,
            }
        phases = self._get_battle_phases(a_idx, d_idx)
        if not phases:
            return {
                "attacker_loss_multiplier": 1.0,
                "defender_loss_multiplier": 1.0,
            }
        data["_time_seconds"] = (
            data.get("_time_seconds", 0.0) + float(dt_seconds)
        )
        selected = None
        for phase in phases:
            if self._phase_condition_met(phase, data, a_idx, d_idx):
                selected = phase
                break
        if selected is None:
            selected = phases[-1]
        phase_id = selected.get("id", "phase")
        old_phase_id = data.get("_phase_id")
        markov_cfg = self._get_markov_config(a_idx, d_idx)
        markov_enabled = bool(markov_cfg.get("enabled", False))
        if markov_enabled and "_markov" not in data:
            phase_ids = [
                p.get("id", f"phase_{i}") for i, p in enumerate(phases)
            ]
            data["_markov"] = MarkovPhaseModel(
                phase_ids,
                float(markov_cfg.get("transition_memory", 0.9)),
            )
        if old_phase_id != phase_id:
            data["_phase_id"] = phase_id
            data["_phase_time_seconds"] = 0.0
            history = data.setdefault("_phase_history", [])
            history.append({
                "phase_id": phase_id,
                "at_seconds": data.get("_time_seconds", 0.0),
            })
            if (
                markov_enabled
                and old_phase_id is not None
                and "_markov" in data
            ):
                data["_markov"].record_transition(old_phase_id, phase_id)
        data["_phase_time_seconds"] = (
            data.get("_phase_time_seconds", 0.0) + float(dt_seconds)
        )
        attacker_mult = self._curve_multiplier(
            selected.get("attacker_curve"),
            data["_phase_time_seconds"],
            selected.get("attacker_multiplier", 1.0),
        )
        defender_mult = self._curve_multiplier(
            selected.get("defender_curve"),
            data["_phase_time_seconds"],
            selected.get("defender_multiplier", 1.0),
        )
        if markov_enabled and "_markov" in data:
            markov = data["_markov"]
            prediction_weight = float(
                markov_cfg.get("prediction_weight", 0.3)
            )
            if markov.total_transitions > 0:
                attacker_phase_mults = {}
                defender_phase_mults = {}
                for phase in phases:
                    pid = phase.get("id", "phase")
                    attacker_phase_mults[pid] = float(
                        phase.get("attacker_multiplier", 1.0)
                    )
                    defender_phase_mults[pid] = float(
                        phase.get("defender_multiplier", 1.0)
                    )
                expected_attacker = markov.expected_multiplier(
                    phase_id, attacker_phase_mults
                )
                expected_defender = markov.expected_multiplier(
                    phase_id, defender_phase_mults
                )
                attacker_mult = (
                    (1.0 - prediction_weight) * attacker_mult
                    + prediction_weight * expected_attacker
                )
                defender_mult = (
                    (1.0 - prediction_weight) * defender_mult
                    + prediction_weight * expected_defender
                )
        return {
            "attacker_loss_multiplier": float(attacker_mult),
            "defender_loss_multiplier": float(defender_mult),
        }

    def resolve_engagements(self, engagements, rng, dt_seconds=None):
        """
        Разрешает все активные боестолкновения по суточной модели потерь.

        Сбрасывает потолок потерь разрешения, затем обрабатывает каждое
        столкновение. Пропускает engagements между двумя сторонами
        LOD 2. Для engagements между двумя сторонами LOD 1 использует
        упрощённый режим без фаз и марковских цепей. Если атакующий не
        может воевать (can_fight=False), столкновение пропускается
        полностью. Если защитник не может воевать, потери по нему
        применяются, но ответный удар не наносится.

        Потери защитника вычисляются как доля его начальной
        численности: суточная доля режима (фронт 1-3%, прорыв во
        фланги и тылы 20-35%) делится на 24 часа, умножается на
        длительность шага, модификатор местности, множитель фазы и
        случайный разброс. Потери атакующего считаются аналогично по
        шкале фронтального штурма (до 6% в сутки). Суммарные потери
        юнита за разрешение ограничены потолком loss_tick_cap.

        После разрешения обновляет self.engagements списком
        оставшихся столкновений (с уменьшенным duration).

        Args:
            engagements: Список столкновений (кортежи или словари).
            rng: Генератор случайных чисел.
            dt_seconds: Длительность шага в секундах для масштабирования.
        """
        if rng is None:
            rng = random.Random()
        self._ensure_combat_power()
        self._tick_loss = {}
        st = self.state
        id_to_idx = {eid: i for i, eid in enumerate(st.entity_ids)}
        new_engagements = []
        dt_hours = (
            max(0.0, float(dt_seconds) / 3600.0) if dt_seconds else 1.0
        )
        if dt_hours <= 0.0:
            dt_hours = 1.0
        logger.debug(
            "resolve_engagements: столкновений=%d", len(engagements)
        )
        for eng in engagements:
            if isinstance(eng, dict):
                data = eng
                is_tuple = False
            else:
                try:
                    a_id, d_id, proj = eng
                except Exception:
                    continue
                data = {
                    "attacker": a_id,
                    "defender": d_id,
                    "projection": proj,
                    "duration": 1,
                    "_tuple": True,
                }
                is_tuple = True
            a_id = data.get("attacker")
            d_id = data.get("defender")
            proj = data.get("projection", "auto")
            try:
                duration = int(data.get("duration", 1))
            except Exception:
                duration = 1
            a = id_to_idx.get(a_id)
            d = id_to_idx.get(d_id)
            if a is None or d is None:
                continue
            if self._is_dead(a) or self._is_dead(d):
                continue
            lod_a = self._lod_level(a)
            lod_d = self._lod_level(d)
            if lod_a == 2 and lod_d == 2:
                if not is_tuple and duration > 1:
                    data["duration"] = duration - 1
                    new_engagements.append(data)
                continue
            simplified = lod_a >= 1 and lod_d >= 1
            if not is_tuple and duration > 1:
                data["duration"] = duration - 1
                new_engagements.append(data)
            oa = self._safe_order_index(st.read_segment(a, "order"))
            od = self._safe_order_index(st.read_segment(d, "order"))
            can_fight_a = bool(self.ot.can_fight[oa])
            can_fight_d = bool(self.ot.can_fight[od])
            if not can_fight_a:
                continue
            p = self._get_projection(a, d, proj)
            data["_last_defender_projection"] = p
            if simplified:
                phase = {
                    "attacker_loss_multiplier": 1.0,
                    "defender_loss_multiplier": 1.0,
                }
            else:
                phase = self._update_phase(data, a, d, dt_seconds)
            attacker_loss_mult = float(
                phase.get("attacker_loss_multiplier", 1.0)
            )
            defender_loss_mult = float(
                phase.get("defender_loss_multiplier", 1.0)
            )
            terrain_mod = terrain_defense_modifier(
                st.heights, st.biomes,
                st.coords[d, 0], st.coords[d, 1],
                st.coords[a, 0], st.coords[a, 1],
            )
            initial_d = max(1.0, float(st.initial_manpower[d]))
            initial_a = max(1.0, float(st.initial_manpower[a]))
            strike_a = st.combat_power[a, 0]
            if strike_a == 0.0:
                self.recompute_power()
                strike_a = st.combat_power[a, 0]
            strike_d = st.combat_power[d, p] if can_fight_d else 0.0
            breakthrough = p != PROJ_FRONT
            if breakthrough:
                daily_d = self._daily_fraction(
                    strike_a,
                    max(1.0, strike_d),
                    self._loss_daily_break_min,
                    self._loss_daily_break_max,
                )
            else:
                daily_d = self._daily_fraction(
                    strike_a,
                    max(1.0, strike_d),
                    self._loss_daily_calm_min,
                    self._loss_daily_calm_max,
                )
            loss_d = (
                (daily_d / 24.0)
                * dt_hours
                * initial_d
                * terrain_mod
                * defender_loss_mult
                * rng.uniform(0.8, 1.2)
            )
            self._apply_losses(d, loss_d)
            loss_a = 0.0
            if can_fight_d:
                daily_a = self._daily_fraction(
                    strike_d,
                    max(1.0, strike_a),
                    self._loss_daily_calm_min,
                    self._loss_daily_assault_max,
                )
                loss_a = (
                    (daily_a / 24.0)
                    * dt_hours
                    * initial_a
                    * attacker_loss_mult
                    * rng.uniform(0.8, 1.2)
                )
                self._apply_losses(a, loss_a)
            data["_defender_losses"] = (
                data.get("_defender_losses", 0.0) + loss_d
            )
            if can_fight_d:
                data["_attacker_losses"] = (
                    data.get("_attacker_losses", 0.0) + loss_a
                )
            logger.debug(
                "Столкновение %s -> %s: потери защитника=%.1f, "
                "атакующего=%.1f, прорыв=%s",
                a_id, d_id, loss_d, loss_a, breakthrough,
            )
            self._check_retreat(d, p, rng)
            if can_fight_d:
                self._check_retreat(a, 0, rng)
        self.engagements = new_engagements

    def apply_tactical_losses(
        self,
        defender_idx: int,
        attack_sector: str,
        total_loss: float,
    ):
        """
        Применяет тактические потери с учётом виртуальной структуры дивизии.

        Использует DivisionalStructure для распределения потерь по ротам
        указанного сектора, затем агрегирует результаты обратно в дивизию.
        Учитывает модификатор потерь снабжения при casualties через черты.

        Если DivisionalStructure для сущности не найдена, применяет
        потери напрямую через _apply_losses.

        Args:
            defender_idx: Индекс защищающейся сущности.
            attack_sector: Название сектора атаки
                ("front", "left", "right", "rear", "center").
            total_loss: Общие потери личного состава.
        """
        from core.divisional_structure import Sector

        st = self.state
        entity_id = st.entity_ids[defender_idx]
        divisional_structures = getattr(st, "divisional_structures", None)
        if divisional_structures is None or entity_id not in divisional_structures:
            self._apply_losses(defender_idx, total_loss)
            return
        structure = divisional_structures[entity_id]
        sector_map = {
            "front": Sector.FRONT,
            "left": Sector.LEFT,
            "right": Sector.RIGHT,
            "rear": Sector.REAR,
            "center": Sector.CENTER,
        }
        sector = sector_map.get(attack_sector, Sector.FRONT)
        sector_modifiers = {
            Sector.FRONT: {"morale_penalty": 0.05, "equipment_loss": 0.1},
            Sector.LEFT: {"morale_penalty": 0.1, "equipment_loss": 0.15},
            Sector.RIGHT: {"morale_penalty": 0.1, "equipment_loss": 0.15},
            Sector.REAR: {"morale_penalty": 0.2, "equipment_loss": 0.05},
            Sector.CENTER: {"morale_penalty": 0.08, "equipment_loss": 0.12},
        }
        mods = sector_modifiers.get(sector, {"morale_penalty": 0.05, "equipment_loss": 0.1})
        result = structure.apply_sector_losses(
            sector=sector,
            total_loss=total_loss,
            morale_penalty=mods["morale_penalty"],
            equipment_loss_ratio=mods["equipment_loss"],
            rng=self.state.engine.rng if hasattr(self.state, "engine") else None,
        )
        aggregated = structure.aggregate_to_division()
        config = st.class_configs[st.class_ids[defender_idx]]
        ch_man = config.voltage_layout.channel_index.get("U_manpower")
        if ch_man is not None:
            st.voltages_next[defender_idx, ch_man] = aggregated["U_manpower"]
        ch_cas = config.voltage_layout.channel_index.get("U_casualties")
        if ch_cas is not None:
            st.voltages_next[defender_idx, ch_cas] = aggregated["U_casualties"]
        ch_morale = config.voltage_layout.channel_index.get("U_morale")
        if ch_morale is not None:
            st.voltages_next[defender_idx, ch_morale] = aggregated["morale"]
        for equip_type, equip_amount in aggregated["equipment"].items():
            ch_equip = config.voltage_layout.channel_index.get(equip_type)
            if ch_equip is not None:
                st.voltages_next[defender_idx, ch_equip] = equip_amount
        loss_coeff = get_supply_loss_on_casualties(
            self.state.engine.app if hasattr(self.state, "engine") else None
        )
        if loss_coeff > 0 and aggregated["U_casualties"] > 0:
            logistics = getattr(st, "logistics_system", None)
            if logistics is not None:
                supply = logistics.ls.unit_supply.get(defender_idx)
                if supply is not None:
                    casualty_effect = aggregated["U_casualties"] * loss_coeff
                    for cls in list(supply.actual.keys()):
                        supply.actual[cls] = max(
                            0.0, supply.actual[cls] * (1.0 - casualty_effect)
                        )
        logger.info(
            "Тактические потери: %s, сектор=%s, потери=%d, роты затронуты=%d",
            st.label_of(defender_idx),
            attack_sector,
            int(result["manpower_loss"]),
            result["sector_companies_affected"],
        )

    def _equipment_channels(self, idx):
        """
        Возвращает список каналов техники для сущности.

        Если в combat_model задан явный список equipment_channels,
        фильтрует его по существующим каналам. Иначе собирает все
        каналы с префиксом equipment_channel_prefix, исключая
        manpower, casualties и experience.

        Args:
            idx: Индекс сущности.

        Returns:
            list[str]: Список имён каналов техники.
        """
        config = self.state.class_configs[self.state.class_ids[idx]]
        model = config.combat_model or {}
        explicit = model.get("equipment_channels")
        if isinstance(explicit, list):
            return [
                ch for ch in explicit
                if ch in config.voltage_layout.channel_index
            ]
        prefix = str(
            self.defaults.get("equipment_channel_prefix", "U_")
        )
        excluded = set(
            self.defaults.get("equipment_excluded_channels", [])
        )
        excluded.add(self._channel_role("manpower", "U_manpower"))
        excluded.add(self._channel_role("casualties", "U_casualties"))
        excluded.add(
            self._channel_role("experience", "U_experience_progress")
        )
        result = []
        for ch_name in config.voltage_layout.channel_index:
            if ch_name in excluded:
                continue
            if ch_name.startswith(prefix):
                result.append(ch_name)
        return result

    def _apply_losses(self, idx, loss):
        """
        Применяет потери к одной сущности с потолком за разрешение боя.

        Суммарные потери сущности за одно разрешение боя
        ограничиваются долей loss_tick_cap от начальной численности,
        чтобы полное окружение выдавливало подразделение за сутки
        (20% и более), а не испаряло его за один час. Уменьшает
        manpower и пропорционально увеличивает casualties как
        накопленную долю от начальной численности, увеличивает
        experience, уменьшает каналы техники пропорционально
        equipment_loss_factor. При обнулении manpower устанавливает
        condition=0. Логирует событие, если потери >= 0.5.

        Args:
            idx: Индекс сущности.
            loss: Величина потерь личного состава.
        """
        if loss <= 0:
            return
        st = self.state
        config = st.class_configs[st.class_ids[idx]]
        initial_mp = max(0.0, float(st.initial_manpower[idx]))
        if initial_mp > 0.0:
            already = float(self._tick_loss.get(idx, 0.0))
            remaining = self._loss_tick_cap * initial_mp - already
            if remaining <= 0.0:
                return
            loss = min(loss, remaining)
            self._tick_loss[idx] = already + loss
        manpower_channel = self._channel_role("manpower", "U_manpower")
        casualties_channel = self._channel_role(
            "casualties", "U_casualties"
        )
        experience_channel = self._channel_role(
            "experience", "U_experience_progress"
        )
        ch_idx = config.voltage_layout.channel_index.get(manpower_channel)
        if ch_idx is not None:
            cur = st.voltages_next[idx, ch_idx]
            manpower_after = max(0.0, cur - loss)
            st.voltages_next[idx, ch_idx] = manpower_after
            if manpower_after <= 0.0:
                if self._has_segment(idx, "condition"):
                    st.write_segment(idx, "condition", 0)
        cas_ch = config.voltage_layout.channel_index.get(
            casualties_channel
        )
        if cas_ch is not None:
            if initial_mp > 0.0:
                added = min(1.0, loss / initial_mp)
                new_cas = min(
                    1.0, st.voltages_next[idx, cas_ch] + added
                )
            else:
                casualty_rate = float(
                    self._combat_param(idx, "casualty_rate", 0.01)
                )
                new_cas = min(
                    1.0,
                    st.voltages_next[idx, cas_ch] + loss * casualty_rate,
                )
            st.voltages_next[idx, cas_ch] = new_cas
            if new_cas >= 1.0:
                if self._has_segment(idx, "condition"):
                    st.write_segment(idx, "condition", 0)
        exp_ch = config.voltage_layout.channel_index.get(
            experience_channel
        )
        if exp_ch is not None:
            exp_cap = float(
                self._combat_param(idx, "experience_gain_cap", 0.2)
            )
            exp_factor = float(
                self._combat_param(
                    idx, "experience_gain_factor", 0.0002
                )
            )
            gain = min(exp_cap, loss * exp_factor)
            current = st.voltages_next[idx, exp_ch]
            st.voltages_next[idx, exp_ch] = min(1.0, current + gain)
        personnel_loss_share = float(
            self._combat_param(idx, "personnel_loss_share", 0.7)
        )
        equipment_loss_factor = float(
            self._combat_param(idx, "equipment_loss_factor", 0.1)
        )
        equipment_loss = loss * (1.0 - personnel_loss_share)
        if equipment_loss > 0:
            for ch_name in self._equipment_channels(idx):
                ch_i = config.voltage_layout.channel_index.get(ch_name)
                if ch_i is None:
                    continue
                cur = st.voltages_next[idx, ch_i]
                if cur > 0:
                    reduction = min(
                        cur, equipment_loss * equipment_loss_factor
                    )
                    st.voltages_next[idx, ch_i] = max(
                        0.0, cur - reduction
                    )
        if loss >= 0.5:
            cas_text = ""
            if cas_ch is not None:
                cas_text = (
                    f", накопленные потери "
                    f"{st.voltages_next[idx, cas_ch]:.0%}"
                )
            st.log_event(
                idx,
                f"{st.label_of(idx)}: -{loss:.0f} л.с.{cas_text}",
            )
            logger.info(
                "%s: -%.0f л.с.%s", st.label_of(idx), loss, cas_text
            )

    def _check_retreat(self, idx, incoming_proj, rng):
        """
        Проверяет, должно ли подразделение отступить.

        Логика отступления:
        1. Паника (morale=0 и casualties>=0.5): принудительный
           марш-бросок и потеря сплочённости, переопределяет любую политику.
        2. Политика retreat из таблицы приказов:
           - "always": отступление при потерях >= 0.5.
           - "on_threat": отступление при потерях >= 0.3.
           - "on_breakthrough": отступление при ударе с фланга/тыла
             и потерях >= 0.3.
           - "never": не отступать.

        Автоотход применяется только к автономным (не игрока)
        подразделениям при casualties >= 0.5.

        Args:
            idx: Индекс сущности.
            incoming_proj: Проекция входящего удара (для on_breakthrough).
            rng: Генератор случайных чисел (зарезервирован).
        """
        st = self.state
        config = st.class_configs[st.class_ids[idx]]
        if "order" not in config.segment_layout.segments:
            return
        if len(self.ot.retreat) == 0:
            return
        order = self._safe_order_index(st.read_segment(idx, "order"))
        retreat_policy = self.ot.retreat[order]
        casualties_channel = self._channel_role(
            "casualties", "U_casualties"
        )
        casualties_ch = config.voltage_layout.channel_index.get(
            casualties_channel
        )
        casualties = (
            st.voltages_next[idx, casualties_ch]
            if casualties_ch is not None
            else 0.0
        )
        morale = (
            st.read_segment(idx, "morale")
            if self._has_segment(idx, "morale")
            else 1
        )
        movement_idx = self.ot.id_to_index.get("movement")
        forced_march_idx = self.ot.id_to_index.get(
            "forced_march", movement_idx
        )
        if movement_idx is None:
            return
        if forced_march_idx is None:
            forced_march_idx = movement_idx
        if morale == 0 and casualties >= 0.5:
            st.write_segment(idx, "order", forced_march_idx)
            if self._has_segment(idx, "cohesion"):
                cur_coh = st.read_segment_next(idx, "cohesion")
                if cur_coh > 0:
                    st.write_segment(idx, "cohesion", cur_coh - 1)
            logger.info(
                "%s: паника, переход в марш-бросок", st.label_of(idx)
            )
            return
        if retreat_policy == "always" and casualties >= 0.5:
            st.write_segment(idx, "order", movement_idx)
            logger.info(
                "%s: отступление по политике always", st.label_of(idx)
            )
        elif retreat_policy == "on_threat" and casualties >= 0.3:
            st.write_segment(idx, "order", movement_idx)
            logger.info(
                "%s: отступление по политике on_threat",
                st.label_of(idx),
            )
        elif retreat_policy == "on_breakthrough":
            from .combat_geometry import PROJ_LEFT, PROJ_RIGHT, PROJ_REAR

            if (
                incoming_proj in (PROJ_LEFT, PROJ_RIGHT, PROJ_REAR)
                and casualties >= 0.3
            ):
                st.write_segment(idx, "order", movement_idx)
                logger.info(
                    "%s: отступление по политике on_breakthrough",
                    st.label_of(idx),
                )