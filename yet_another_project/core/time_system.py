"""
core/time_system.py

Система игрового времени, действий игрока, прерываний,
усталости и обязательных сцен.

Данные действий и настроек времени читаются из JSON:
configs/content/time_settings.json
configs/content/time_actions.json

Встроенные fallback-значения используются только при отсутствии
конфигурационных файлов.

При пересечении вечерней границы дня вызывает проверку условий
сюжета через app.check_storyline_end_of_day, если ссылка на
приложение установлена.

Учитывает модификаторы черт персонажа для длительности действий
и скорости накопления усталости.
"""

import math
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from .config_loader import load_json
from .effects import EffectInterpreter
from .traits import get_action_duration_modifier, get_fatigue_modifier

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
DEFAULT_DAY_START_SECONDS = 7 * SECONDS_PER_HOUR
DEFAULT_DAY_END_SECONDS = 22 * SECONDS_PER_HOUR
DEFAULT_NIGHT_END_SECONDS = 6 * SECONDS_PER_HOUR
DEFAULT_FATIGUE_BASE = 0.02
DEFAULT_FATIGUE_K = 16.0
DEFAULT_ACTION_MEMORY_SECONDS = 1800.0
DEFAULT_ORDER_PLANNING_SECONDS_PER_ORDER = 300.0
INTERRUPT_RETENTION_SECONDS = 3 * SECONDS_PER_DAY


def _clamp(value: float, min_value: float, max_value: float) -> float:
    """
    Ограничивает значение в заданном диапазоне.

    Args:
        value: Исходное значение.
        min_value: Минимальная граница.
        max_value: Максимальная граница.

    Returns:
        float: Значение, ограниченное диапазоном [min_value, max_value].
    """
    return max(min_value, min(max_value, value))


@dataclass
class ActionThreshold:
    """
    Частичный порог выполнения действия.

    При достижении указанного прогресса применяется эффект.
    Если действие прервано после достижения порога, эффект
    считается уже выданным и не применяется повторно.

    Attributes:
        at_seconds: Прогресс в секундах, при котором срабатывает порог.
        effect: Эффект, применяемый при достижении порога.
        id: Уникальный идентификатор порога или None.
    """

    at_seconds: float
    effect: Dict[str, Any] = field(default_factory=dict)
    id: Optional[str] = None


@dataclass
class ActionDefinition:
    """
    Определение действия игрока.

    Описывает действие, которое тратит игровое время: базовую
    длительность, категорию, флаги прерываемости и отменяемости,
    память прогресса после прерывания, частичные пороги и эффекты
    на старте, завершении и отмене.

    Реальная длительность вычисляется как base_duration * (1 + fatigue).

    Attributes:
        id: Уникальный идентификатор действия.
        label: Человекочитаемое название действия.
        duration_seconds: Базовая длительность в игровых секундах.
        category: Категория действия (wait, command, recon, dialogue).
        interruptible: Может ли действие быть прервано.
        cancellable: Может ли действие быть отменено.
        repeatable: Можно ли повторить действие.
        memory_seconds: Память прогресса после прерывания.
        thresholds: Список частичных порогов выполнения.
        effects_on_start: Эффекты, применяемые при начале действия.
        effects_on_complete: Эффекты, применяемые при завершении.
        effects_on_cancel: Эффекты, применяемые при отмене.
    """

    id: str
    label: str
    duration_seconds: float
    category: str = "generic"
    interruptible: bool = True
    cancellable: bool = True
    repeatable: bool = True
    memory_seconds: float = DEFAULT_ACTION_MEMORY_SECONDS
    thresholds: List[ActionThreshold] = field(default_factory=list)
    effects_on_start: List[Dict[str, Any]] = field(default_factory=list)
    effects_on_complete: List[Dict[str, Any]] = field(default_factory=list)
    effects_on_cancel: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ActiveAction:
    """
    Активное или приостановленное действие.

    Хранит текущий прогресс выполнения, множество уже выданных
    порогов, абсолютное время начала и флаг приостановки.
    При прерывании переводится в suspended-состояние; прогресс
    убывает экспоненциально согласно memory_seconds определения.

    Attributes:
        definition_id: Идентификатор определения действия.
        progress_seconds: Текущий эффективный прогресс в секундах.
        awarded_thresholds: Множество ID уже выданных порогов.
        started_at_total_seconds: Абсолютное время начала действия.
        suspended: Флаг приостановки действия.
    """

    definition_id: str
    progress_seconds: float = 0.0
    awarded_thresholds: set = field(default_factory=set)
    started_at_total_seconds: float = 0.0
    suspended: bool = False


@dataclass
class InterruptEvent:
    """
    Событие прерывания действия игрока.

    Описывает срочное событие, которое может прервать текущее
    действие. Имеет приоритет, время срабатывания, TTL и
    отдельные эффекты для принятия, игнорирования и истечения.

    Жизненный цикл состояний:
    pending → presented → accepted | ignored → expired.

    Attributes:
        id: Уникальный идентификатор прерывания.
        title: Заголовок прерывания для UI.
        text: Текст описания прерывания.
        priority: Приоритет прерывания (выше = важнее).
        source_entity_id: ID сущности-источника или None.
        trigger_at_seconds: Абсолютное время срабатывания.
        ttl_seconds: Время жизни прерывания после презентации.
        accept_effects: Эффекты при принятии прерывания.
        ignore_effects: Эффекты при игнорировании прерывания.
        expire_effects: Эффекты при истечении прерывания.
        accept_action_id: ID действия, запускаемого при принятии.
        state: Текущее состояние (pending/presented/ignored/accepted/expired).
        presented_at_seconds: Абсолютное время презентации или None.
        expires_at_seconds: Абсолютное время истечения или None.
    """

    id: str
    title: str
    text: str
    priority: int = 1
    source_entity_id: Optional[str] = None
    trigger_at_seconds: float = 0.0
    ttl_seconds: float = 600.0
    accept_effects: List[Dict[str, Any]] = field(default_factory=list)
    ignore_effects: List[Dict[str, Any]] = field(default_factory=list)
    expire_effects: List[Dict[str, Any]] = field(default_factory=list)
    accept_action_id: Optional[str] = None
    state: str = "pending"
    presented_at_seconds: Optional[float] = None
    expires_at_seconds: Optional[float] = None


class GameTimeSystem:
    """
    Система игрового времени.

    Управляет игровым днём, действиями игрока, прерываниями,
    усталостью и обязательными сценами. Учитывает модификаторы
    черт персонажа для длительности действий и скорости накопления
    усталости через функции из core.traits.

    При пересечении вечерней границы дня вызывает проверку условий
    сюжета через app.check_storyline_end_of_day, если ссылка на
    приложение установлена.

    Attributes:
        state: Состояние игрового мира (WorldState).
        engine: Движок мира (TickEngine) или None.
        app: Экземпляр приложения для доступа к чертам и сюжету.
        day: Текущий игровой день.
        seconds_of_day: Текущее время суток в секундах от полуночи.
        pending_mandatory_scene: ID ожидающей обязательной сцены или None.
        active_action: Текущее активное действие или None.
        suspended_actions: Приостановленные действия по ID.
        actions: Зарегистрированные определения действий.
        interrupts: Список активных прерываний.
        night_duty: Флаг ночного дежурства.
        sleeping: Флаг сна.
        slept_last_night: Флаг сна в прошлую ночь.
        sleep_debt_nights: Количество бессонных ночей подряд.
        forced_sleep: Флаг принудительного сна.
        awake_seconds: Накопленное время бодрствования.
    """

    def __init__(
        self,
        state,
        engine=None,
        start_day: int = 1,
        start_seconds_of_day: float = DEFAULT_DAY_START_SECONDS,
    ):
        """
        Инициализирует систему игрового времени.

        Загружает настройки из time_settings.json и действия из
        time_actions.json. При отсутствии конфигов использует
        встроенные значения по умолчанию.

        Args:
            state: Состояние игрового мира (WorldState).
            engine: Движок мира (TickEngine) или None.
            start_day: Начальный игровой день.
            start_seconds_of_day: Начальное время суток в секундах.
        """
        self.state = state
        self.engine = engine
        self.app = None
        self._load_settings()
        self.day = int(start_day)
        self.seconds_of_day = float(start_seconds_of_day)
        self.pending_mandatory_scene: Optional[str] = (
            self.mandatory_scene_morning
        )
        self.active_action: Optional[ActiveAction] = None
        self.suspended_actions: Dict[str, ActiveAction] = {}
        self.actions: Dict[str, ActionDefinition] = {}
        self.interrupts: List[InterruptEvent] = []
        self.night_duty = False
        self.sleeping = False
        self.slept_last_night = False
        self.sleep_debt_nights = 0
        self.forced_sleep = False
        self.awake_seconds = 0.0
        self._fatigue = 0.0
        self._load_actions()

    def _load_settings(self):
        """
        Загружает настройки времени из configs/content/time_settings.json.

        Читает границы дня/ночи, параметры усталости, память действий,
        время планирования приказов и ID обязательных сцен. При
        отсутствии файла или поля использует значения по умолчанию.
        """
        settings = load_json("configs/content/time_settings.json", {}) or {}
        self.day_start_seconds = int(
            settings.get("day_start_seconds", DEFAULT_DAY_START_SECONDS)
        )
        self.day_end_seconds = int(
            settings.get("day_end_seconds", DEFAULT_DAY_END_SECONDS)
        )
        self.night_end_seconds = int(
            settings.get("night_end_seconds", DEFAULT_NIGHT_END_SECONDS)
        )
        self.default_action_memory_seconds = float(
            settings.get(
                "default_action_memory_seconds",
                DEFAULT_ACTION_MEMORY_SECONDS,
            )
        )
        self.order_planning_seconds_per_order = float(
            settings.get(
                "order_planning_seconds_per_order",
                DEFAULT_ORDER_PLANNING_SECONDS_PER_ORDER,
            )
        )
        mandatory = settings.get("mandatory_scenes", {}) or {}
        self.mandatory_scene_morning = str(
            mandatory.get("morning", "morning_inspection")
        )
        self.mandatory_scene_evening = str(
            mandatory.get("evening", "evening_inspection")
        )
        fatigue_cfg = settings.get("fatigue", {}) or {}
        self.fatigue_base = float(
            fatigue_cfg.get("base", DEFAULT_FATIGUE_BASE)
        )
        self.fatigue_k = float(fatigue_cfg.get("k", DEFAULT_FATIGUE_K))

    def _load_actions(self):
        """
        Загружает действия из configs/content/time_actions.json.

        Если файл существует и содержит список действий, регистрирует
        каждое действие. Иначе регистрирует встроенные fallback-действия.
        """
        self.actions = {}
        data = load_json("configs/content/time_actions.json", {}) or {}
        actions = data.get("actions") if isinstance(data, dict) else None
        if isinstance(actions, list) and actions:
            for action_dict in actions:
                self._register_action_from_dict(action_dict)
        else:
            self._register_builtin_actions()

    def _register_action_from_dict(self, d: dict):
        """
        Регистрирует одно действие из словаря конфигурации.

        Пропускает словари без id, label или некорректной длительности.
        Парсит частичные пороги из списка thresholds.

        Args:
            d: Словарь описания действия из JSON.
        """
        if not isinstance(d, dict):
            return
        action_id = d.get("id")
        label = d.get("label")
        if not action_id or not label:
            return
        try:
            duration_seconds = float(d["duration_seconds"])
        except Exception:
            return
        thresholds = []
        for th in d.get("thresholds", []) or []:
            try:
                thresholds.append(
                    ActionThreshold(
                        at_seconds=float(th["at_seconds"]),
                        effect=th.get("effect", {}) or {},
                        id=th.get("id"),
                    )
                )
            except Exception:
                continue
        self.register_action(
            ActionDefinition(
                id=str(action_id),
                label=str(label),
                duration_seconds=duration_seconds,
                category=str(d.get("category", "generic")),
                interruptible=bool(d.get("interruptible", True)),
                cancellable=bool(d.get("cancellable", True)),
                repeatable=bool(d.get("repeatable", True)),
                memory_seconds=float(
                    d.get(
                        "memory_seconds",
                        self.default_action_memory_seconds,
                    )
                ),
                thresholds=thresholds,
                effects_on_start=d.get("effects_on_start", []) or [],
                effects_on_complete=d.get("effects_on_complete", []) or [],
                effects_on_cancel=d.get("effects_on_cancel", []) or [],
            )
        )

    def _register_builtin_actions(self):
        """
        Регистрирует встроенные fallback-действия.

        Вызывается при отсутствии файла time_actions.json или пустом
        списке действий. Регистрирует: wait_5, wait_15, wait_30,
        wait_60, radio_contact, dialogue_choice, binoculars_recon.
        """
        builtin = [
            {
                "id": "wait_5",
                "label": "Ждать 5 минут",
                "duration_seconds": 5 * SECONDS_PER_MINUTE,
                "category": "wait",
            },
            {
                "id": "wait_15",
                "label": "Ждать 15 минут",
                "duration_seconds": 15 * SECONDS_PER_MINUTE,
                "category": "wait",
            },
            {
                "id": "wait_30",
                "label": "Ждать 30 минут",
                "duration_seconds": 30 * SECONDS_PER_MINUTE,
                "category": "wait",
            },
            {
                "id": "wait_60",
                "label": "Ждать 1 час",
                "duration_seconds": SECONDS_PER_HOUR,
                "category": "wait",
            },
            {
                "id": "radio_contact",
                "label": "Связаться по рации",
                "duration_seconds": 5 * SECONDS_PER_MINUTE,
                "category": "command",
            },
            {
                "id": "dialogue_choice",
                "label": "Диалог",
                "duration_seconds": SECONDS_PER_MINUTE,
                "category": "dialogue",
                "memory_seconds": 900.0,
            },
            {
                "id": "binoculars_recon",
                "label": "Наблюдение в бинокль",
                "duration_seconds": 15 * SECONDS_PER_MINUTE,
                "category": "recon",
                "memory_seconds": 1800.0,
                "thresholds": [
                    {
                        "id": "recon_partial_1",
                        "at_seconds": 5 * SECONDS_PER_MINUTE,
                        "effect": {
                            "log": "Разведка: частичные данные уровня 1."
                        },
                    },
                    {
                        "id": "recon_partial_2",
                        "at_seconds": 10 * SECONDS_PER_MINUTE,
                        "effect": {
                            "log": "Разведка: частичные данные уровня 2."
                        },
                    },
                    {
                        "id": "recon_full",
                        "at_seconds": 15 * SECONDS_PER_MINUTE,
                        "effect": {"log": "Разведка: полный отчёт."},
                    },
                ],
            },
        ]
        for action_dict in builtin:
            self._register_action_from_dict(action_dict)

    @property
    def total_seconds(self) -> float:
        """
        Возвращает абсолютное время в секундах от начала игры.

        Вычисляется как (day - 1) * SECONDS_PER_DAY + seconds_of_day.

        Returns:
            float: Абсолютное время в секундах.
        """
        return (self.day - 1) * SECONDS_PER_DAY + self.seconds_of_day

    def get_time_string(self) -> str:
        """
        Возвращает человекочитаемую строку текущего времени.

        Формат: «День N, HH:MM».

        Returns:
            str: Строка времени.
        """
        total = int(self.seconds_of_day)
        hours = total // SECONDS_PER_HOUR
        minutes = (total % SECONDS_PER_HOUR) // SECONDS_PER_MINUTE
        return f"День {self.day}, {hours:02d}:{minutes:02d}"

    def is_night(self) -> bool:
        """
        Проверяет, является ли текущее время ночным.

        Ночь: seconds_of_day >= day_end_seconds или
        seconds_of_day < day_start_seconds.

        Returns:
            bool: True, если сейчас ночь.
        """
        return (
            self.seconds_of_day >= self.day_end_seconds
            or self.seconds_of_day < self.day_start_seconds
        )

    def register_action(self, action: ActionDefinition):
        """
        Регистрирует определение действия.

        Args:
            action: Определение действия для регистрации.
        """
        self.actions[action.id] = action

    def register_order_planning_action(self, orders_count: int) -> str:
        """
        Регистрирует действие планирования приказов.

        Длительность вычисляется как orders_count *
        order_planning_seconds_per_order. Если действие с таким
        ID уже зарегистрировано, повторно не создаётся.

        Args:
            orders_count: Количество планируемых приказов.

        Returns:
            str: ID зарегистрированного действия.
        """
        orders_count = max(1, int(orders_count))
        action_id = f"plan_orders_{orders_count}"
        if action_id not in self.actions:
            self.register_action(
                ActionDefinition(
                    id=action_id,
                    label=f"Спланировать приказы: {orders_count}",
                    duration_seconds=(
                        orders_count * self.order_planning_seconds_per_order
                    ),
                    category="command",
                    memory_seconds=2700.0,
                )
            )
        return action_id

    def get_available_actions(self) -> List[ActionDefinition]:
        """
        Возвращает список всех зарегистрированных действий.

        Returns:
            list[ActionDefinition]: Список определений действий.
        """
        return list(self.actions.values())

    def _player_has_fatigue_channel(self) -> bool:
        """
        Проверяет наличие канала U_fatigue у сущности игрока.

        Returns:
            bool: True, если канал существует.
        """
        if self.state is None:
            return False
        idx = getattr(self.state, "player_idx", 0)
        if idx < 0 or idx >= self.state.count:
            return False
        config = self.state.class_configs[self.state.class_ids[idx]]
        return "U_fatigue" in config.voltage_layout.channel_index

    def get_fatigue(self) -> float:
        """
        Возвращает текущий уровень усталости.

        Если у игрока есть канал U_fatigue, читает из next-буфера.
        Иначе возвращает внутреннее значение _fatigue.

        Returns:
            float: Уровень усталости [0, 1].
        """
        if self._player_has_fatigue_channel():
            idx = self.state.player_idx
            return float(self.state.read_voltage_next(idx, "U_fatigue"))
        return float(self._fatigue)

    def set_fatigue(self, value: float):
        """
        Устанавливает уровень усталости с клампом в [0, 1].

        Если у игрока есть канал U_fatigue, записывает в next-буфер.
        Иначе обновляет внутреннее значение _fatigue.

        Args:
            value: Новое значение усталости.
        """
        value = _clamp(float(value), 0.0, 1.0)
        if self._player_has_fatigue_channel():
            idx = self.state.player_idx
            self.state.set_voltage_next(idx, "U_fatigue", value)
        else:
            self._fatigue = value

    def get_action_cost_multiplier(self) -> float:
        """
        Возвращает множитель стоимости действий на основе усталости.

        Формула: 1.0 + fatigue. Чем выше усталость, тем дольше
        выполняются действия.

        Returns:
            float: Множитель стоимости действий (>= 1.0).
        """
        return 1.0 + self.get_fatigue()

    def _update_fatigue(self, dt_seconds: float):
        """
        Обновляет усталость при бодрствовании.

        Во сне усталость не растёт. Рост экспоненциальный:
        delta = fatigue_base * exp(awake_hours / fatigue_k) * dt_hours.
        Модифицируется чертой персонажа через get_fatigue_modifier.

        Args:
            dt_seconds: Длительность шага в секундах.
        """
        if self.sleeping:
            return
        if dt_seconds <= 0:
            return
        self.awake_seconds += dt_seconds
        dt_hours = dt_seconds / SECONDS_PER_HOUR
        awake_hours = self.awake_seconds / SECONDS_PER_HOUR
        exp_factor = math.exp(
            min(awake_hours / max(1e-6, self.fatigue_k), 10.0)
        )
        fatigue_mult = get_fatigue_modifier(self.app) if self.app else 1.0
        delta = self.fatigue_base * exp_factor * dt_hours * fatigue_mult
        self.set_fatigue(self.get_fatigue() + delta)

    def _sleep_recovery_factor(self, sleep_hours: float) -> float:
        """
        Вычисляет коэффициент восстановления усталости от сна.

        Логистическая кривая: recovery = 1 / (1 + exp(-0.8 * (h - 4))).
        При 4 часах сна восстановление ~50%, при 8 часах ~96%.

        Args:
            sleep_hours: Длительность сна в часах.

        Returns:
            float: Коэффициент восстановления [0, 1].
        """
        return 1.0 / (1.0 + math.exp(-0.8 * (sleep_hours - 4.0)))

    def _decay_suspended_actions(self, dt_seconds: float):
        """
        Применяет затухание прогресса приостановленных действий.

        Прогресс убывает экспоненциально: progress *= exp(-dt / memory).
        Когда прогресс падает ниже 1 секунды, действие обнуляется
        и удаляется из suspended_actions.

        Args:
            dt_seconds: Длительность шага в секундах.
        """
        if dt_seconds <= 0:
            return
        for action_id, active in list(self.suspended_actions.items()):
            if (
                self.active_action is not None
                and self.active_action.definition_id == action_id
            ):
                continue
            definition = self.actions.get(action_id)
            if definition is None:
                self.suspended_actions.pop(action_id, None)
                continue
            memory = float(definition.memory_seconds)
            if memory <= 0.0:
                active.progress_seconds = 0.0
            else:
                active.progress_seconds *= math.exp(-dt_seconds / memory)
            if active.progress_seconds < 1.0:
                active.progress_seconds = 0.0
                active.awarded_thresholds.clear()
                self.suspended_actions.pop(action_id, None)

    def _apply_effects(self, effects: List[Dict[str, Any]]):
        """
        Применяет список эффектов к состоянию мира.

        Пропускает пустые эффекты и вызовы без state.

        Args:
            effects: Список словарей эффектов.
        """
        if not effects:
            return
        if self.state is None:
            return
        for effect in effects:
            if effect:
                EffectInterpreter.apply(self.state, effect)

    def add_interrupt(self, interrupt: InterruptEvent) -> str:
        """
        Добавляет прерывание в список активных.

        Если у прерывания нет ID, генерирует UUID.

        Args:
            interrupt: Объект прерывания.

        Returns:
            str: ID добавленного прерывания.
        """
        if not interrupt.id:
            interrupt.id = str(uuid.uuid4())
        self.interrupts.append(interrupt)
        return interrupt.id

    def schedule_interrupt(
        self,
        trigger_in_seconds: float,
        title: str,
        text: str,
        priority: int = 1,
        ttl_seconds: float = 600.0,
        source_entity_id: Optional[str] = None,
        accept_effects: Optional[List[Dict[str, Any]]] = None,
        ignore_effects: Optional[List[Dict[str, Any]]] = None,
        expire_effects: Optional[List[Dict[str, Any]]] = None,
        accept_action_id: Optional[str] = None,
    ) -> str:
        """
        Планирует прерывание на будущее время.

        Создаёт InterruptEvent с trigger_at_seconds = total_seconds +
        trigger_in_seconds и добавляет в список активных.

        Args:
            trigger_in_seconds: Задержка срабатывания в секундах.
            title: Заголовок прерывания.
            text: Текст описания прерывания.
            priority: Приоритет прерывания.
            ttl_seconds: Время жизни после презентации.
            source_entity_id: ID сущности-источника.
            accept_effects: Эффекты при принятии.
            ignore_effects: Эффекты при игнорировании.
            expire_effects: Эффекты при истечении.
            accept_action_id: ID действия при принятии.

        Returns:
            str: ID запланированного прерывания.
        """
        interrupt = InterruptEvent(
            id=str(uuid.uuid4()),
            title=title,
            text=text,
            priority=int(priority),
            source_entity_id=source_entity_id,
            trigger_at_seconds=self.total_seconds + float(trigger_in_seconds),
            ttl_seconds=float(ttl_seconds),
            accept_effects=accept_effects or [],
            ignore_effects=ignore_effects or [],
            expire_effects=expire_effects or [],
            accept_action_id=accept_action_id,
        )
        return self.add_interrupt(interrupt)

    def _next_pending_interrupt_time(self) -> Optional[float]:
        """
        Возвращает ближайшее время срабатывания ожидающего прерывания.

        Среди всех pending-прерываний находит минимальное
        trigger_at_seconds. Если есть уже наступившие, возвращает
        текущее время.

        Returns:
            float | None: Ближайшее время срабатывания или None.
        """
        now = self.total_seconds
        best = None
        for interrupt in self.interrupts:
            if interrupt.state != "pending":
                continue
            if interrupt.trigger_at_seconds <= now:
                return now
            if best is None or interrupt.trigger_at_seconds < best:
                best = interrupt.trigger_at_seconds
        return best

    def _pop_due_interrupt(self) -> Optional[InterruptEvent]:
        """
        Извлекает наступившее прерывание с наивысшим приоритетом.

        Среди pending-прерываний с trigger_at_seconds <= now выбирает
        прерывание с максимальным приоритетом (при равенстве —
        с минимальным временем). Переводит его в состояние presented.

        Returns:
            InterruptEvent | None: Наступившее прерывание или None.
        """
        now = self.total_seconds
        candidates = [
            i
            for i in self.interrupts
            if i.state == "pending" and i.trigger_at_seconds <= now + 1e-6
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda i: (-int(i.priority), float(i.trigger_at_seconds))
        )
        interrupt = candidates[0]
        interrupt.state = "presented"
        interrupt.presented_at_seconds = now
        return interrupt

    def _process_overdue_ignored_interrupts(self):
        """
        Переводит просроченные ignored-прерывания в expired.

        Для каждого ignored-прерывания с expires_at_seconds <= now
        устанавливает состояние expired и применяет expire_effects.
        """
        now = self.total_seconds
        for interrupt in self.interrupts:
            if interrupt.state != "ignored":
                continue
            if interrupt.expires_at_seconds is None:
                continue
            if now >= interrupt.expires_at_seconds:
                interrupt.state = "expired"
                self._apply_effects(interrupt.expire_effects)

    def _prune_interrupts(self):
        """
        Удаляет завершённые прерывания старше INTERRUPT_RETENTION_SECONDS.

        Оставляет pending, presented и ignored прерывания, а также
        завершённые прерывания, с момента срабатывания которых прошло
        менее INTERRUPT_RETENTION_SECONDS.
        """
        now = self.total_seconds
        self.interrupts = [
            i
            for i in self.interrupts
            if i.state in ("pending", "presented", "ignored")
            or now - i.trigger_at_seconds < INTERRUPT_RETENTION_SECONDS
        ]

    def accept_interrupt(self, interrupt_id: str) -> Dict[str, Any]:
        """
        Принимает прерывание по ID.

        Переводит прерывание в состояние accepted, применяет
        accept_effects. Возвращает результат операции.

        Args:
            interrupt_id: ID прерывания.

        Returns:
            dict: Результат с ok=True и данными прерывания,
                или ok=False с причиной отказа.
        """
        interrupt = self._get_interrupt_by_id(interrupt_id)
        if interrupt is None:
            return {"ok": False, "reason": "interrupt_not_found"}
        if interrupt.state not in ("pending", "presented", "ignored"):
            return {"ok": False, "reason": "interrupt_not_active"}
        interrupt.state = "accepted"
        self._apply_effects(interrupt.accept_effects)
        return {
            "ok": True,
            "interrupt_id": interrupt.id,
            "accept_action_id": interrupt.accept_action_id,
        }

    def ignore_interrupt(self, interrupt_id: str) -> Dict[str, Any]:
        """
        Игнорирует прерывание по ID.

        Переводит прерывание в состояние ignored, устанавливает
        expires_at_seconds, применяет ignore_effects.

        Args:
            interrupt_id: ID прерывания.

        Returns:
            dict: Результат с ok=True и данными прерывания,
                или ok=False с причиной отказа.
        """
        interrupt = self._get_interrupt_by_id(interrupt_id)
        if interrupt is None:
            return {"ok": False, "reason": "interrupt_not_found"}
        if interrupt.state not in ("pending", "presented"):
            return {"ok": False, "reason": "interrupt_not_active"}
        interrupt.state = "ignored"
        interrupt.expires_at_seconds = self.total_seconds + interrupt.ttl_seconds
        self._apply_effects(interrupt.ignore_effects)
        return {
            "ok": True,
            "interrupt_id": interrupt.id,
            "expires_at_seconds": interrupt.expires_at_seconds,
        }

    def _get_interrupt_by_id(
        self, interrupt_id: str
    ) -> Optional[InterruptEvent]:
        """
        Ищет прерывание по ID.

        Args:
            interrupt_id: ID прерывания.

        Returns:
            InterruptEvent | None: Найденное прерывание или None.
        """
        for interrupt in self.interrupts:
            if interrupt.id == interrupt_id:
                return interrupt
        return None

    def _boundaries_between(
        self, old_total: float, new_total: float
    ) -> list:
        """
        Находит границы дня/ночи между двумя абсолютными временами.

        Возвращает список кортежей (absolute_seconds, boundary_type),
        где boundary_type — "morning" или "evening". Список отсортирован
        по времени.

        Args:
            old_total: Предыдущее абсолютное время.
            new_total: Новое абсолютное время.

        Returns:
            list[tuple[float, str]]: Список пересечённых границ.
        """
        events = []
        start_day = int(old_total // SECONDS_PER_DAY)
        end_day = int(new_total // SECONDS_PER_DAY)
        for day in range(start_day, end_day + 1):
            day_start = day * SECONDS_PER_DAY + self.day_start_seconds
            day_end = day * SECONDS_PER_DAY + self.day_end_seconds
            if old_total < day_start <= new_total:
                events.append((day_start, "morning"))
            if old_total < day_end <= new_total:
                events.append((day_end, "evening"))
        events.sort(key=lambda x: x[0])
        return events

    def _next_boundary_time(self, after_total: float) -> float:
        """
        Возвращает абсолютное время следующей границы дня/ночи.

        Args:
            after_total: Точка отсчёта.

        Returns:
            float: Абсолютное время следующей границы.
        """
        day = int(after_total // SECONDS_PER_DAY)
        day_start = day * SECONDS_PER_DAY + self.day_start_seconds
        day_end = day * SECONDS_PER_DAY + self.day_end_seconds
        if after_total < day_start:
            return day_start
        if after_total < day_end:
            return day_end
        return (day + 1) * SECONDS_PER_DAY + self.day_start_seconds

    def _on_evening_boundary(self):
        """
        Обрабатывает пересечение вечерней границы дня.

        Устанавливает pending_mandatory_scene на evening_inspection.
        При 3+ бессонных ночах включает принудительный сон.
        Вызывает app.check_storyline_end_of_day() для проверки
        исходов сюжета.
        """
        self.pending_mandatory_scene = self.mandatory_scene_evening
        if self.sleep_debt_nights >= 3:
            self.forced_sleep = True
        if self.app is not None and hasattr(
            self.app, "check_storyline_end_of_day"
        ):
            self.app.check_storyline_end_of_day()

    def _on_morning_boundary(self):
        """
        Обрабатывает пересечение утренней границы дня.

        Устанавливает pending_mandatory_scene на morning_inspection.
        Если было ночное дежурство без сна, увеличивает долг сна.
        При 3+ бессонных ночах включает принудительный сон.
        Сбрасывает флаги ночного дежурства и сна.
        """
        self.pending_mandatory_scene = self.mandatory_scene_morning
        if self.night_duty and not self.slept_last_night:
            self.sleep_debt_nights += 1
        if self.sleep_debt_nights >= 3:
            self.forced_sleep = True
        self.night_duty = False
        self.slept_last_night = False

    def complete_mandatory_scene(self, scene_id: str) -> Dict[str, Any]:
        """
        Завершает обязательную сцену.

        Снимает pending_mandatory_scene, если ID совпадает.

        Args:
            scene_id: ID завершаемой сцены.

        Returns:
            dict: Результат с ok=True или ok=False с причиной.
        """
        if self.pending_mandatory_scene != scene_id:
            return {
                "ok": False,
                "reason": "no_such_mandatory_scene",
                "pending": self.pending_mandatory_scene,
            }
        self.pending_mandatory_scene = None
        return {"ok": True, "scene_id": scene_id}

    def choose_night_duty(self, duty: bool) -> Dict[str, Any]:
        """
        Обрабатывает выбор ночного дежурства или сна.

        Если ожидает обязательная сцена, возвращает ошибку.
        При 3+ бессонных ночах принудительно заменяет дежурство сном.
        При выборе дежурства устанавливает флаг night_duty.
        При выборе сна вызывает sleep_until_morning.

        Args:
            duty: True для ночного дежурства, False для сна.

        Returns:
            dict: Результат операции.
        """
        if self.pending_mandatory_scene is not None:
            return {
                "ok": False,
                "reason": "mandatory_scene_pending",
                "scene": self.pending_mandatory_scene,
            }
        if self.sleep_debt_nights >= 3:
            duty = False
            self.forced_sleep = True
        self.night_duty = bool(duty)
        if self.night_duty:
            self.sleeping = False
            return {"ok": True, "mode": "night_duty"}
        return self.sleep_until_morning(forced=self.forced_sleep)

    def sleep_until_morning(self, forced: bool = False) -> Dict[str, Any]:
        """
        Продвигает время до утренней границы и восстанавливает усталость.

        Вычисляет целевое время (следующая утренняя граница), продвигает
        мир через _advance_world, применяет восстановление усталости
        по логистической кривой. Принудительный сон снижает
        восстановление на 20%. Сбрасывает awake_seconds и флаги.

        Args:
            forced: Флаг принудительного сна.

        Returns:
            dict: Результат с режимом, часами сна, усталостью и временем.
        """
        day = int(self.total_seconds // SECONDS_PER_DAY)
        current_day_start = day * SECONDS_PER_DAY + self.day_start_seconds
        if self.total_seconds < current_day_start:
            target_total = current_day_start
        else:
            target_total = (day + 1) * SECONDS_PER_DAY + self.day_start_seconds
        sleep_seconds = max(0.0, target_total - self.total_seconds)
        sleep_hours = min(8.0, sleep_seconds / SECONDS_PER_HOUR)
        self.sleeping = True
        self.slept_last_night = True
        self._advance_world(sleep_seconds, force_end=True)
        recovery = self._sleep_recovery_factor(sleep_hours)
        if forced:
            recovery *= 0.8
        fatigue = self.get_fatigue()
        fatigue *= max(0.0, 1.0 - recovery)
        self.set_fatigue(fatigue)
        self.sleeping = False
        self.awake_seconds = 0.0
        self.night_duty = False
        if not forced:
            self.sleep_debt_nights = 0
        self.forced_sleep = False
        return {
            "ok": True,
            "mode": "forced_sleep" if forced else "sleep",
            "sleep_hours": sleep_hours,
            "fatigue": self.get_fatigue(),
            "time": self.get_time_string(),
        }

    def _advance_clock(self, seconds: float):
        """
        Продвигает внутренние часы и обрабатывает границы дня.

        Обновляет day и seconds_of_day. Для каждой пересечённой
        границы вызывает _on_evening_boundary или _on_morning_boundary.

        Args:
            seconds: Количество секунд для продвижения.
        """
        if seconds <= 0:
            return
        old_total = self.total_seconds
        new_total = old_total + float(seconds)
        self.day = int(new_total // SECONDS_PER_DAY) + 1
        self.seconds_of_day = float(new_total % SECONDS_PER_DAY)
        for _, boundary_type in self._boundaries_between(old_total, new_total):
            if boundary_type == "evening":
                self._on_evening_boundary()
            elif boundary_type == "morning":
                self._on_morning_boundary()

    def _advance_world(self, seconds: float, force_end: bool = False):
        """
        Продвигает мир на заданное число секунд.

        Продвигает часы, затухает приостановленные действия, обновляет
        усталость, обрабатывает просроченные прерывания, очищает
        завершённые прерывания. Делегирует продвижение симуляции
        движку через engine.advance_seconds.

        Args:
            seconds: Количество секунд для продвижения.
            force_end: Принудительно разрешить бой и правила
                на последнем шаге.
        """
        if seconds <= 0:
            return
        self._advance_clock(seconds)
        self._decay_suspended_actions(seconds)
        self._update_fatigue(seconds)
        self._process_overdue_ignored_interrupts()
        self._prune_interrupts()
        if self.engine is not None and hasattr(self.engine, "advance_seconds"):
            self.engine.advance_seconds(
                seconds,
                force_combat=force_end,
                force_rules=force_end,
            )

    def _next_stop_time(
        self,
        max_seconds: float,
        interruptible: bool,
    ) -> tuple:
        """
        Вычисляет ближайшую точку остановки продвижения.

        Остановка происходит по одной из причин: конец запрошенного
        времени, граница дня/ночи (обязательная сцена) или прерывание
        (если действие прерываемо).

        Args:
            max_seconds: Максимальное время продвижения.
            interruptible: Может ли действие быть прервано.

        Returns:
            tuple[float, str | None]: (stop_time, reason).
                reason: "mandatory_scene", "interrupt" или None.
        """
        end_time = self.total_seconds + float(max_seconds)
        boundary_time = self._next_boundary_time(self.total_seconds)
        if boundary_time < end_time:
            stop_time = boundary_time
            reason = "mandatory_scene"
        else:
            stop_time = end_time
            reason = None
        if interruptible:
            interrupt_time = self._next_pending_interrupt_time()
            if interrupt_time is not None and interrupt_time < stop_time:
                stop_time = interrupt_time
                reason = "interrupt"
        return stop_time, reason

    def _advance_until_stop(
        self,
        max_seconds: float,
        interruptible: bool,
    ) -> tuple:
        """
        Продвигает мир до ближайшей точки остановки.

        Вычисляет stop_time через _next_stop_time, продвигает мир
        на разницу. При остановке по прерыванию извлекает и возвращает
        прерывание.

        Args:
            max_seconds: Максимальное время продвижения.
            interruptible: Может ли действие быть прервано.

        Returns:
            tuple[str | None, InterruptEvent | None, float]:
                (reason, interrupt, chunk_seconds).
        """
        stop_time, reason = self._next_stop_time(max_seconds, interruptible)
        chunk_seconds = max(0.0, stop_time - self.total_seconds)
        if chunk_seconds > 0.0:
            self._advance_world(chunk_seconds, force_end=(reason is None))
        if reason == "interrupt":
            interrupt = self._pop_due_interrupt()
            return "interrupt", interrupt, chunk_seconds
        return reason, None, chunk_seconds

    def can_start_action(self) -> bool:
        """
        Проверяет, можно ли начать новое действие.

        Действие нельзя начать, если ожидает обязательная сцена
        или уже выполняется активное действие.

        Returns:
            bool: True, если действие можно начать.
        """
        if self.pending_mandatory_scene is not None:
            return False
        if self.active_action is not None:
            return False
        return True

    def execute_action(self, action_id: str) -> Dict[str, Any]:
        """
        Выполняет действие игрока.

        Проверяет возможность старта, создаёт или возобновляет
        ActiveAction, применяет эффекты старта. В цикле продвигает
        мир порциями через _advance_until_stop, начисляя прогресс
        с учётом множителя усталости и черты персонажа. Проверяет
        частичные пороги. При прерывании или обязательной сцене
        приостанавливает действие и возвращает соответствующий статус.
        При завершении применяет эффекты завершения.

        Args:
            action_id: ID действия для выполнения.

        Returns:
            dict: Результат со статусом completed/interrupted/
                mandatory_scene/blocked/error.
        """
        if not self.can_start_action():
            return {
                "status": "blocked",
                "reason": (
                    "mandatory_scene_pending"
                    if self.pending_mandatory_scene is not None
                    else "active_action_exists"
                ),
                "mandatory_scene": self.pending_mandatory_scene,
            }
        action = self.actions.get(action_id)
        if action is None:
            return {
                "status": "error",
                "reason": "unknown_action",
                "action_id": action_id,
            }
        active = self.suspended_actions.get(action_id)
        if active is None or active.progress_seconds <= 0.0:
            active = ActiveAction(
                definition_id=action_id,
                progress_seconds=0.0,
                awarded_thresholds=set(),
                started_at_total_seconds=self.total_seconds,
                suspended=False,
            )
        self._apply_effects(action.effects_on_start)
        self.active_action = active
        duration_mult = (
            get_action_duration_modifier(self.app) if self.app else 1.0
        )
        while active.progress_seconds < action.duration_seconds - 1e-6:
            multiplier = self.get_action_cost_multiplier() * duration_mult
            remaining_progress = action.duration_seconds - active.progress_seconds
            needed_game_seconds = remaining_progress * multiplier
            reason, interrupt, chunk_seconds = self._advance_until_stop(
                needed_game_seconds,
                action.interruptible,
            )
            active.progress_seconds += chunk_seconds / max(1e-6, multiplier)
            self._award_thresholds(action, active)
            if reason == "interrupt":
                active.suspended = True
                self.suspended_actions[action_id] = active
                self.active_action = None
                return {
                    "status": "interrupted",
                    "action_id": action_id,
                    "progress_seconds": active.progress_seconds,
                    "interrupt": interrupt,
                }
            if reason == "mandatory_scene":
                active.suspended = True
                self.suspended_actions[action_id] = active
                self.active_action = None
                return {
                    "status": "mandatory_scene",
                    "action_id": action_id,
                    "progress_seconds": active.progress_seconds,
                    "mandatory_scene": self.pending_mandatory_scene,
                }
            if reason is None:
                break
        active.progress_seconds = action.duration_seconds
        self._award_thresholds(action, active)
        self._apply_effects(action.effects_on_complete)
        self.suspended_actions.pop(action_id, None)
        self.active_action = None
        return {
            "status": "completed",
            "action_id": action_id,
            "time": self.get_time_string(),
        }

    def cancel_active_action(self) -> Dict[str, Any]:
        """
        Отменяет текущее активное действие.

        Применяет эффекты отмены, переводит действие в suspended-состояние.

        Returns:
            dict: Результат с ok=True и action_id, или ok=False.
        """
        if self.active_action is None:
            return {"ok": False, "reason": "no_active_action"}
        action_id = self.active_action.definition_id
        action = self.actions.get(action_id)
        if action is not None:
            self._apply_effects(action.effects_on_cancel)
        self.active_action.suspended = True
        self.suspended_actions[action_id] = self.active_action
        self.active_action = None
        return {"ok": True, "action_id": action_id}

    def _award_thresholds(
        self, action: ActionDefinition, active: ActiveAction
    ):
        """
        Проверяет и применяет достигнутые частичные пороги.

        Для каждого порога, чей at_seconds <= progress и который
        ещё не был выдан, применяет эффект и добавляет ID порога
        в awarded_thresholds.

        Args:
            action: Определение действия с порогами.
            active: Активное действие с текущим прогрессом.
        """
        if not action.thresholds:
            return
        for index, threshold in enumerate(action.thresholds):
            threshold_id = threshold.id or f"{action.id}_threshold_{index}"
            if threshold_id in active.awarded_thresholds:
                continue
            if active.progress_seconds >= threshold.at_seconds - 1e-6:
                active.awarded_thresholds.add(threshold_id)
                self._apply_effects([threshold.effect])

    def wait(self, seconds: float) -> Dict[str, Any]:
        """
        Ожидает заданное количество секунд без действия.

        Продвигает мир порциями через _advance_until_stop.
        При прерывании или обязательной сцене возвращает
        соответствующий статус.

        Args:
            seconds: Количество секунд ожидания.

        Returns:
            dict: Результат со статусом completed/interrupted/
                mandatory_scene/blocked.
        """
        if self.pending_mandatory_scene is not None:
            return {
                "status": "blocked",
                "reason": "mandatory_scene_pending",
                "mandatory_scene": self.pending_mandatory_scene,
            }
        if self.active_action is not None:
            return {"status": "blocked", "reason": "active_action_exists"}
        end_time = self.total_seconds + float(seconds)
        while self.total_seconds < end_time - 1e-6:
            remaining = end_time - self.total_seconds
            reason, interrupt, _ = self._advance_until_stop(
                remaining,
                interruptible=True,
            )
            if reason == "interrupt":
                return {
                    "status": "interrupted",
                    "interrupt": interrupt,
                    "time": self.get_time_string(),
                }
            if reason == "mandatory_scene":
                return {
                    "status": "mandatory_scene",
                    "mandatory_scene": self.pending_mandatory_scene,
                    "time": self.get_time_string(),
                }
            if reason is None:
                break
        return {"status": "completed", "time": self.get_time_string()}

    def can_save(self) -> bool:
        """
        Проверяет, можно ли сохранить игру.

        Сохранение запрещено при активном действии, ожидающей
        обязательной сцене или представленном/игнорированном прерывании.

        Returns:
            bool: True, если сохранение разрешено.
        """
        if self.active_action is not None:
            return False
        if self.pending_mandatory_scene is not None:
            return False
        for interrupt in self.interrupts:
            if interrupt.state in ("presented", "ignored"):
                return False
        return True

    def get_save_snapshot(self) -> Dict[str, Any]:
        """
        Возвращает снимок состояния системы времени для сохранения.

        Включает: день, время суток, awake_seconds, sleep_debt_nights,
        night_duty, forced_sleep, усталость, pending_mandatory_scene,
        прогресс приостановленных действий.

        Returns:
            dict: Снимок состояния для сериализации.
        """
        return {
            "day": self.day,
            "seconds_of_day": self.seconds_of_day,
            "awake_seconds": self.awake_seconds,
            "sleep_debt_nights": self.sleep_debt_nights,
            "night_duty": self.night_duty,
            "forced_sleep": self.forced_sleep,
            "fatigue": self.get_fatigue(),
            "pending_mandatory_scene": self.pending_mandatory_scene,
            "suspended_actions": {
                action_id: {
                    "progress_seconds": active.progress_seconds,
                    "awarded_thresholds": sorted(active.awarded_thresholds),
                }
                for action_id, active in self.suspended_actions.items()
            },
        }

    def load_from_snapshot(self, snapshot: Dict[str, Any]):
        """
        Восстанавливает состояние системы времени из снимка.

        Применяет все поля снимка. Восстанавливает приостановленные
        действия с их прогрессом и выданными порогами. Сбрасывает
        active_action, sleeping и slept_last_night.

        Args:
            snapshot: Словарь снимка состояния из сохранения.
        """
        if not snapshot:
            return
        self.day = int(snapshot.get("day", 1))
        self.seconds_of_day = float(
            snapshot.get("seconds_of_day", DEFAULT_DAY_START_SECONDS)
        )
        self.awake_seconds = float(snapshot.get("awake_seconds", 0.0))
        self.sleep_debt_nights = int(snapshot.get("sleep_debt_nights", 0))
        self.night_duty = bool(snapshot.get("night_duty", False))
        self.forced_sleep = bool(snapshot.get("forced_sleep", False))
        self.set_fatigue(float(snapshot.get("fatigue", 0.0)))
        self.pending_mandatory_scene = snapshot.get("pending_mandatory_scene")
        self.suspended_actions = {}
        suspended = snapshot.get("suspended_actions", {})
        for action_id, data in suspended.items():
            if action_id not in self.actions:
                continue
            self.suspended_actions[action_id] = ActiveAction(
                definition_id=action_id,
                progress_seconds=float(data.get("progress_seconds", 0.0)),
                awarded_thresholds=set(data.get("awarded_thresholds", [])),
                started_at_total_seconds=self.total_seconds,
                suspended=True,
            )
        self.active_action = None
        self.sleeping = False
        self.slept_last_night = False