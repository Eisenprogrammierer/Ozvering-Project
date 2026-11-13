"""
core/modalities.py

Система модальностей среды.

Реестр модальностей загружается из configs/content/modalities.json.
При отсутствии конфига используется встроенный fallback-реестр
из 32 модальностей, сгруппированных по 8 категориям.

Модальность — тип внешнего воздействия на сущность. Каждая сущность
имеет профиль восприимчивости (susceptibility_profile) и матрицу
влияния (influence_matrix), определяющие силу и направление
воздействия модальности на индикаторы битовой маски.

Система обрабатывает события среды в tick-based режиме:
накопление воздействия с учётом затухания; мгновенное срабатывание
при превышении порога; накопительное срабатывание при превышении
порога накопления; автоматическое истечение событий по длительности.

Пропускает сущности с уровнем детализации выше LOD 0 для подсистемы
modalities. События загрузки реестра, добавления событий, срабатывания
порогов и истечения записываются в журнал operation_ozverin.log в корне
проекта и дублируются в консоль.
"""

import logging
import math
import os

from .config_loader import load_json

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "operation_ozverin.log",
)


def _build_logger(name: str) -> logging.Logger:
    """
    Создаёт и возвращает именованный журнал.

    Журнал пишет в operation_ozverin.log в корне проекта (уровень DEBUG)
    и дублирует сообщения в консоль (уровень INFO). Обработчики
    добавляются один раз; повторный вызов возвращает тот же журнал.

    Args:
        name: Имя журнала.

    Returns:
        logging.Logger: Настроенный журнал.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


logger = _build_logger("core.modalities")

DEFAULT_MODALITY_REGISTRY = {
    "extreme_heat": "thermal",
    "fire": "thermal",
    "extreme_cold": "thermal",
    "thermal_shock": "thermal",
    "wind": "kinetic",
    "storm": "kinetic",
    "blast": "kinetic",
    "avalanche": "kinetic",
    "landslide": "kinetic",
    "impact": "kinetic",
    "flood": "hydro",
    "drought": "hydro",
    "acid_rain": "hydro",
    "toxins": "chemical",
    "corrosion": "chemical",
    "salination": "chemical",
    "radiation": "electromagnetic",
    "emp": "electromagnetic",
    "lightning": "electromagnetic",
    "pathogen": "biological",
    "parasite": "biological",
    "healing": "biological",
    "fertility": "biological",
    "blinding_light": "sensory",
    "deafening_noise": "sensory",
    "fog": "sensory",
    "sensory_overload": "sensory",
    "magic": "misc",
    "cyber": "misc",
    "psionic": "misc",
    "temporal": "misc",
    "gravitational": "misc",
}


def _load_modality_registry() -> dict:
    """
    Загружает реестр модальностей из JSON-конфига.

    Читает configs/content/modalities.json. Если файл существует
    и содержит непустой словарь "modalities", возвращает его
    содержимое в виде отображения имени модальности на категорию.
    В противном случае возвращает копию встроенного fallback-реестра
    DEFAULT_MODALITY_REGISTRY.

    Returns:
        dict: Отображение имени модальности на категорию.
    """
    data = load_json("configs/content/modalities.json", None)
    if (
        isinstance(data, dict)
        and isinstance(data.get("modalities"), dict)
        and data["modalities"]
    ):
        logger.info(
            "Реестр модальностей загружен из конфига: %d",
            len(data["modalities"]),
        )
        return {
            str(k): str(v)
            for k, v in data["modalities"].items()
        }
    logger.info(
        "Реестр модальностей: использован встроенный fallback: %d",
        len(DEFAULT_MODALITY_REGISTRY),
    )
    return dict(DEFAULT_MODALITY_REGISTRY)


MODALITY_REGISTRY = _load_modality_registry()


class SusceptibilityProfile:
    """
    Профиль восприимчивости сущности к модальностям среды.

    Хранит словарь чувствительности, где ключ — имя модальности,
    значение — коэффициент восприимчивости в диапазоне [0, 1].
    Значение 0.0 означает полную невосприимчивость, 1.0 —
    максимальную чувствительность.

    Attributes:
        profile (dict): Словарь восприимчивости по модальностям.
    """

    def __init__(self, profile_dict):
        """
        Инициализирует профиль восприимчивости.

        Args:
            profile_dict (dict | None): Словарь восприимчивости.
                Если None, инициализируется пустым словарём.
        """
        self.profile = profile_dict or {}

    def get_susceptibility(self, modality):
        """
        Возвращает коэффициент восприимчивости к указанной модальности.

        Args:
            modality (str): Имя модальности.

        Returns:
            float: Коэффициент восприимчивости. 0.0, если модальность
                отсутствует в профиле.
        """
        return float(self.profile.get(modality, 0.0))

    def get_rules_for(self, modality):
        """
        Возвращает правила влияния для указанной модальности.

        Зарезервированный метод для будущего расширения.
        В текущей реализации всегда возвращает пустой словарь.

        Args:
            modality (str): Имя модальности.

        Returns:
            dict: Пустой словарь.
        """
        return {}


class ModalitySystem:
    """
    Система обработки событий среды.

    Управляет активными событиями среды, накапливает воздействие
    модальностей на сущности и применяет дискретные переключения
    битов при превышении порогов.

    Жизненный цикл события:
    1. Событие добавляется через add_event().
    2. При каждом tick() проверяется наступление события
       (tick_started <= current_tick).
    3. Если событие активно, для каждой сущности вычисляется
       воздействие: intensity * susceptibility.
    4. Воздействие накапливается с учётом затухания (decay_beta).
    5. При превышении мгновенного порога или порога накопления
       соответствующий бит сегмента переключается.
    6. После истечения длительности событие удаляется.

    Пропускает сущности с уровнем детализации выше LOD 0 для
    подсистемы modalities.

    Attributes:
        state: Состояние игрового мира (WorldState).
        active_events (list): Список активных событий среды.
        accumulated (dict): Накопленные воздействия.
            Ключ: (entity_index, modality_name), значение: float.
    """

    def __init__(self, state):
        """
        Инициализирует систему модальностей.

        Args:
            state: Состояние игрового мира (WorldState).
        """
        self.state = state
        self.active_events = []
        self.accumulated = {}
        logger.info(
            "ModalitySystem инициализирована: сущностей=%d, модальностей=%d",
            state.count,
            len(MODALITY_REGISTRY),
        )

    def _is_modalities_active(self, idx: int) -> bool:
        """
        Проверяет, активна ли подсистема modalities для сущности.

        Args:
            idx: Индекс сущности.

        Returns:
            bool: True, если подсистема modalities активна.
        """
        lod_manager = getattr(self.state, "lod_manager", None)
        if lod_manager is None:
            return True
        return lod_manager.is_active(idx, "modalities")

    def add_event(self, event):
        """
        Добавляет событие среды в список активных.

        Args:
            event (dict): Описание события. Ожидаемые поля:
                - modality (str): имя модальности;
                - intensity (float): сила воздействия;
                - x, y (int, опционально): координаты центра;
                - radius (float, опционально): радиус действия;
                - duration (int): длительность в тиках;
                - tick_started (int): тик начала действия.
        """
        self.active_events.append(event)
        logger.info(
            "Событие среды добавлено: modality=%s intensity=%.2f "
            "duration=%s tick_started=%s",
            event.get("modality"),
            event.get("intensity", 0.0),
            event.get("duration", 1),
            event.get("tick_started"),
        )

    def get_profile(self, idx):
        """
        Возвращает профиль восприимчивости для сущности по индексу.

        Args:
            idx (int): Индекс сущности в WorldState.

        Returns:
            SusceptibilityProfile: Профиль восприимчивости.
        """
        cfg = self.state.class_configs[self.state.class_ids[idx]]
        return SusceptibilityProfile(cfg.susceptibility_profile)

    def tick(self, rng=None):
        """
        Выполняет один такт обработки событий среды.

        Пропускает сущности, для которых подсистема modalities
        неактивна на текущем уровне LOD.

        Порядок действий:
        1. Затухание накопленных воздействий по decay_beta; значения
           ниже 0.001 удаляются из накопителя.
        2. Для каждого активного события, у которого наступил тик
           начала, вычисляется воздействие на каждую сущность в
           радиусе; воздействие накапливается с затуханием; при
           превышении мгновенного или накопительного порога
           переключается бит целевого сегмента.
        3. События, не истёкшие по длительности, переносятся в
           следующий такт; истёкшие удаляются.

        Args:
            rng: Генератор случайных чисел. В текущей реализации
                не используется, зарезервирован для стохастических
                эффектов.
        """
        st = self.state
        for key in list(self.accumulated.keys()):
            idx, modality = key
            cfg = st.class_configs[st.class_ids[idx]]
            infl = cfg.influence_matrix.get(modality, {})
            decay_beta = infl.get("decay_beta", 1.0)
            self.accumulated[key] *= decay_beta
            if self.accumulated[key] < 0.001:
                logger.debug(
                    "Накопление сброшено: сущность=%d modality=%s",
                    idx,
                    modality,
                )
                del self.accumulated[key]
        next_events = []
        for event in self.active_events:
            modality = event.get("modality")
            intensity = event.get("intensity", 0.0)
            radius = event.get("radius", float("inf"))
            x, y = event.get("x"), event.get("y")
            duration = event.get("duration", 1)
            tick_started = event.get("tick_started", st.current_tick)
            if st.current_tick < tick_started:
                next_events.append(event)
                continue
            if st.current_tick >= tick_started + duration:
                logger.info(
                    "Событие среды истекло: modality=%s tick=%d",
                    modality,
                    st.current_tick,
                )
                continue
            for idx in range(st.count):
                if st.bdi_dead[idx]:
                    continue
                if not self._is_modalities_active(idx):
                    continue
                if (
                    "condition" in st.class_configs[st.class_ids[idx]].segment_layout.segments
                    and st.read_segment(idx, "condition") == 0
                ):
                    continue
                if x is not None and y is not None:
                    dx = st.coords[idx, 0] - x
                    dy = st.coords[idx, 1] - y
                    if math.hypot(dx, dy) > radius:
                        continue
                profile = self.get_profile(idx)
                susceptibility = profile.get_susceptibility(modality)
                if susceptibility <= 0.0:
                    continue
                impact = intensity * susceptibility
                cfg = st.class_configs[st.class_ids[idx]]
                infl = cfg.influence_matrix.get(modality, {})
                target = infl.get("target_indicator", "condition")
                inst_thr = infl.get("instant_threshold", 0.8)
                acc_thr = infl.get("accumulation_threshold", 0.5)
                decay_beta = infl.get("decay_beta", 0.9)
                key = (idx, modality)
                old_acc = self.accumulated.get(key, 0.0)
                new_acc = old_acc * decay_beta + impact
                self.accumulated[key] = new_acc
                if impact >= inst_thr or new_acc >= acc_thr:
                    cur = st.read_segment(idx, target)
                    if cur > 0:
                        st.write_segment(idx, target, cur - 1)
                        self.accumulated[key] = 0.0
                        logger.info(
                            "Модальность %s сработала на сущности %d: "
                            "сегмент %s %d -> %d",
                            modality,
                            idx,
                            target,
                            cur,
                            cur - 1,
                        )
            if st.current_tick < tick_started + duration - 1:
                next_events.append(event)
        self.active_events = next_events