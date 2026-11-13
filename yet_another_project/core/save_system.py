"""
core/save_system.py

Система сохранений и загрузок игрового состояния.

Отвечает за сериализацию и десериализацию состояния мира,
системы времени, BDI-убеждений, логистического состояния
и состояния сюжета в JSON-файлы в директории saves/.

Формат сохранения включает версию, временную метку,
путь к сценарию, состояние мира, состояние системы времени
и состояние сюжета.

При загрузке мир пересобирается из сценария, поверх которого
применяется сохранённое состояние. Если в сохранении отсутствует
блок logistics (старые версии), собранное при пересборке мира
логистическое состояние сохраняется, а не обнуляется.

Ограничения формата:
- динамические сущности, порождённые в рантайме, не сохраняются
  (мир пересобирается из сценария);
- активные намерения BDI не сохраняются и регенерируются
  на следующем BDI-тике после загрузки;
- внутренние поля боестолкновений (марковские цепи, накопители)
  не сохраняются; сохраняются только публичные поля engagements.

События сохранения, загрузки, удаления и сериализации
фиксируются в журнале operation_ozverin.log и дублируются в консоль.
"""

import json
import logging
import os
from datetime import datetime

SAVES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "saves")
)
SAVE_VERSION = 5
LOG_FILENAME = "operation_ozverin.log"
ENGAGEMENT_PUBLIC_KEYS = ("attacker", "defender", "projection", "duration")


def _build_logger(name):
    """
    Возвращает именованный журнал с файловым и консольным обработчиками.

    Файловый обработчик пишет в operation_ozverin.log в корне проекта
    с уровнем DEBUG, консольный — с уровнем INFO.
    Обработчики создаются один раз при первом запросе журнала.

    Args:
        name: Имя журнала.

    Returns:
        logging.Logger: Настроенный журнал.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    log_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        LOG_FILENAME,
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


logger = _build_logger("core.save_system")


def _ensure_saves_dir():
    """
    Создаёт директорию сохранений, если она не существует.
    """
    os.makedirs(SAVES_DIR, exist_ok=True)


def _save_path(slot_name):
    """
    Возвращает полный путь к файлу сохранения по имени слота.

    Args:
        slot_name: Имя слота сохранения без расширения.

    Returns:
        str: Абсолютный путь к JSON-файлу сохранения.
    """
    return os.path.join(SAVES_DIR, f"{slot_name}.json")


def _safe_serialize_value(value):
    """
    Безопасно сериализует произвольное значение для JSON.

    Примитивные типы возвращаются как есть. Списки и словари
    сериализуются рекурсивно. Остальные типы преобразуются в строку.

    Args:
        value: Произвольное значение для сериализации.

    Returns:
        Значение, безопасное для сериализации в JSON.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_serialize_value(v) for k, v in value.items()}
    return str(value)


def _sanitize_engagements(engagements):
    """
    Приводит боестолкновения к JSON-безопасному виду.

    Словарные столкновения урезаются до публичных полей
    (attacker, defender, projection, duration); внутренние
    поля боя, включая объекты марковских цепей, отбрасываются.
    Кортежные и списочные столкновения сохраняются как списки.

    Args:
        engagements: Список боестолкновений произвольного формата.

    Returns:
        list: Список JSON-безопасных столкновений.
    """
    result = []
    for eng in engagements or []:
        if isinstance(eng, dict):
            result.append({
                key: eng[key]
                for key in ENGAGEMENT_PUBLIC_KEYS
                if key in eng
            })
        else:
            try:
                result.append(list(eng))
            except Exception:
                continue
    return result


def _serialize_beliefs(state):
    """
    Сериализует все BDI-убеждения состояния мира.

    Каждое убеждение сохраняется под строковым ключом
    (идентификатор убеждения). Поле object_ref сериализуется
    через _safe_serialize_value для обеспечения совместимости
    с произвольными типами ссылок.

    Args:
        state: Состояние игрового мира (WorldState).

    Returns:
        dict: Словарь убеждений со строковыми ключами.
    """
    result = {}
    for belief_id, belief in state.beliefs.items():
        safe_belief = {}
        for key, value in belief.items():
            if key == "object_ref":
                safe_belief[key] = _safe_serialize_value(value)
            else:
                safe_belief[key] = value
        result[str(belief_id)] = safe_belief
    return result


def _deserialize_beliefs(state, data):
    """
    Восстанавливает BDI-убеждения из сериализованных данных.

    Заполняет state.beliefs, state.beliefs_by_holder и
    state.belief_seq. Убеждения с некорректными данными
    пропускаются. Списки убеждений по владельцам
    восстанавливаются для всех ячеек capacity.

    Args:
        state: Состояние игрового мира (WorldState).
        data: Словарь с сериализованными данными BDI.
    """
    state.belief_seq = int(data.get("belief_seq", 0))
    state.beliefs = {}
    beliefs_data = data.get("beliefs", {})
    for belief_id_str, belief in beliefs_data.items():
        try:
            belief_id = int(belief_id_str)
        except (ValueError, TypeError):
            continue
        if not isinstance(belief, dict):
            continue
        state.beliefs[belief_id] = belief
    beliefs_by_holder = data.get("beliefs_by_holder", [])
    for i in range(state.capacity):
        if (
            i < len(beliefs_by_holder)
            and isinstance(beliefs_by_holder[i], list)
        ):
            state.beliefs_by_holder[i] = [
                int(bid) for bid in beliefs_by_holder[i]
                if isinstance(bid, (int, float))
            ]
        else:
            state.beliefs_by_holder[i] = []


def serialize_world_state(state):
    """
    Сериализует состояние мира в словарь.

    Сохраняет маски, напряжения, координаты, фракции, направления,
    пол персонажа игрока, целевую функцию, флаги смерти BDI,
    прогресс намерений, боестолкновения в JSON-безопасном виде,
    полное состояние BDI-убеждений и логистическое состояние.
    Активные намерения BDI не сохраняются.
    Конфигурации классов и карты не сериализуются, так как
    загружаются из файлов при восстановлении.

    Args:
        state: Состояние игрового мира (WorldState).

    Returns:
        dict: Словарь с сериализованными данными мира.
    """
    logger.debug(
        "Сериализация мира: сущностей=%d, убеждений=%d",
        state.count,
        len(state.beliefs),
    )
    logistics_snapshot = None
    logistics_obj = getattr(state, "logistics", None)
    if logistics_obj is not None and hasattr(logistics_obj, "to_dict"):
        logistics_snapshot = logistics_obj.to_dict()
    return {
        "count": state.count,
        "current_tick": state.current_tick,
        "entity_ids": list(state.entity_ids[:state.count]),
        "class_ids": list(state.class_ids[:state.count]),
        "parent_ids": list(state.parent_ids[:state.count]),
        "masks_current": [
            int(state.masks_current[i])
            for i in range(state.count)
        ],
        "voltages_current": [
            [
                float(state.voltages_current[i, j])
                for j in range(state.max_voltage_channels)
            ]
            for i in range(state.count)
        ],
        "coords": [
            [int(state.coords[i, 0]), int(state.coords[i, 1])]
            for i in range(state.count)
        ],
        "factions": list(state.factions[:state.count]),
        "player_idx": state.player_idx,
        "player_gender": getattr(state, "player_gender", "male"),
        "headings": [
            int(state.headings[i])
            for i in range(state.count)
        ],
        "map_name": state.map_name,
        "objective": [
            float(state.objective[i])
            for i in range(state.count)
        ],
        "bdi_dead": [
            bool(state.bdi_dead[i])
            for i in range(state.count)
        ],
        "intention_progress": [
            float(state.intention_progress[i])
            for i in range(state.count)
        ],
        "initial_manpower": [
            float(state.initial_manpower[i])
            for i in range(state.count)
        ],
        "engagements": _sanitize_engagements(state.engagements),
        "beliefs": _serialize_beliefs(state),
        "beliefs_by_holder": [
            list(state.beliefs_by_holder[i])
            for i in range(state.count)
        ],
        "belief_seq": state.belief_seq,
        "logistics": logistics_snapshot,
    }


def deserialize_world_state(state, data):
    """
    Применяет сериализованные данные к состоянию мира.

    Заполняет текущий и следующий буферы масок и напряжений,
    координаты, направления, фракции, пол персонажа игрока,
    целевую функцию, флаги смерти, прогресс намерений,
    боестолкновения, полное состояние BDI-убеждений и
    логистическое состояние. Если блок logistics в сохранении
    отсутствует, уже собранное логистическое состояние мира
    сохраняется без изменений.

    Количество восстанавливаемых сущностей ограничивается
    минимумом из сохранённого и текущего count.

    Args:
        state: Состояние игрового мира (WorldState).
        data: Словарь с сериализованными данными мира.
    """
    state.current_tick = int(data.get("current_tick", 0))
    state.player_idx = int(data.get("player_idx", 0))
    state.player_gender = data.get("player_gender", "male")
    count = min(int(data.get("count", 0)), state.count)
    masks = data.get("masks_current", [])
    voltages = data.get("voltages_current", [])
    coords = data.get("coords", [])
    factions = data.get("factions", [])
    headings = data.get("headings", [])
    objectives = data.get("objective", [])
    bdi_dead = data.get("bdi_dead", [])
    intention_progress = data.get("intention_progress", [])
    for i in range(count):
        if i < len(masks):
            state.masks_current[i] = masks[i]
            state.masks_next[i] = masks[i]
        if i < len(voltages):
            for j in range(
                min(len(voltages[i]), state.max_voltage_channels)
            ):
                state.voltages_current[i, j] = voltages[i][j]
                state.voltages_next[i, j] = voltages[i][j]
        if i < len(coords):
            state.coords[i, 0] = coords[i][0]
            state.coords[i, 1] = coords[i][1]
        if i < len(factions):
            state.factions[i] = factions[i]
        if i < len(headings):
            state.headings[i] = headings[i]
        if i < len(objectives):
            state.objective[i] = objectives[i]
        if i < len(bdi_dead):
            state.bdi_dead[i] = bdi_dead[i]
        if i < len(intention_progress):
            state.intention_progress[i] = intention_progress[i]
    init_mp = data.get("initial_manpower")
    if isinstance(init_mp, list):
        for i in range(count):
            if i < len(init_mp):
                state.initial_manpower[i] = float(init_mp[i])
    else:
        for i in range(count):
            cfg = state.class_configs[state.class_ids[i]]
            ch = cfg.voltage_layout.channel_index.get("U_manpower")
            if ch is not None:
                state.initial_manpower[i] = float(
                    state.voltages_current[i, ch]
                )
    state.engagements = data.get("engagements", [])
    _deserialize_beliefs(state, data)
    logistics_data = data.get("logistics")
    if logistics_data is not None:
        from core.logistics import LogisticsState
        state.logistics = LogisticsState.from_dict(logistics_data)
    logger.debug(
        "Десериализация мира: восстановлено сущностей=%d, убеждений=%d",
        count,
        len(state.beliefs),
    )


def save_game(
    state,
    time_system,
    slot_name,
    scenario_path="scenarios/mvp.json",
    storyline_snapshot=None,
):
    """
    Сохраняет текущее игровое состояние в файл.

    Создаёт JSON-файл в директории saves/ с версией формата,
    временной меткой, путём к сценарию, сериализованным
    состоянием мира (включая BDI-убеждения, пол персонажа
    и логистику), снимком системы времени и снимком сюжета.

    Args:
        state: Состояние игрового мира (WorldState).
        time_system: Система игрового времени (GameTimeSystem).
        slot_name: Имя слота сохранения без расширения.
        scenario_path: Путь к файлу сценария.
        storyline_snapshot: Снимок состояния сюжета или None.

    Returns:
        str: Абсолютный путь к созданному файлу сохранения.
    """
    _ensure_saves_dir()
    snapshot = {
        "version": SAVE_VERSION,
        "timestamp": datetime.now().isoformat(),
        "scenario_path": scenario_path,
        "time_system": time_system.get_save_snapshot(),
        "world_state": serialize_world_state(state),
        "storyline": storyline_snapshot,
    }
    path = _save_path(slot_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    logger.info(
        "Сохранение записано: %s (версия %d, слот %s)",
        path,
        SAVE_VERSION,
        slot_name,
    )
    return path


def load_game(slot_name):
    """
    Загружает сохранение из файла.

    Читает JSON-файл сохранения и возвращает словарь с данными.
    Поддерживает файлы версий 1-5: отсутствующие поля
    получают значения по умолчанию.

    Args:
        slot_name: Имя слота сохранения без расширения.

    Returns:
        dict | None: Словарь с данными сохранения или None,
            если файл не найден или повреждён.
    """
    path = _save_path(slot_name)
    if not os.path.exists(path):
        logger.warning("Сохранение не найдено: %s", path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.warning("Сохранение повреждено: %s", path)
        return None
    logger.info(
        "Сохранение загружено: %s (версия %s)",
        path,
        data.get("version", 1),
    )
    return data


def list_saves():
    """
    Возвращает список доступных сохранений.

    Сканирует директорию saves/ и читает метаданные
    каждого JSON-файла. Повреждённые файлы пропускаются.

    Returns:
        list[dict]: Список словарей с полями name, timestamp,
            scenario, version для каждого сохранения,
            отсортированный по имени файла.
    """
    _ensure_saves_dir()
    saves = []
    for f in sorted(os.listdir(SAVES_DIR)):
        if not f.endswith(".json"):
            continue
        path = os.path.join(SAVES_DIR, f)
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            saves.append({
                "name": f[:-5],
                "timestamp": data.get("timestamp", ""),
                "scenario": data.get("scenario_path", ""),
                "version": data.get("version", 1),
            })
        except Exception:
            continue
    logger.debug("Найдено сохранений: %d", len(saves))
    return saves


def delete_save(slot_name):
    """
    Удаляет файл сохранения.

    Args:
        slot_name: Имя слота сохранения без расширения.

    Returns:
        bool: True, если файл существовал и был удалён,
            False иначе.
    """
    path = _save_path(slot_name)
    if os.path.exists(path):
        os.remove(path)
        logger.info("Сохранение удалено: %s", path)
        return True
    logger.debug("Сохранение для удаления не найдено: %s", path)
    return False