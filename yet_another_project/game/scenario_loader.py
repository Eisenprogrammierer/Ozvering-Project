"""
game/scenario_loader.py

Сборка WorldState из JSON-конфигов классов и JSON-сценария.

Загружает пресеты из configs/presets/, карту высот и биомов из
scenarios/maps/<name>.npz, размещает сущности из placements сценария,
применяет сегменты и напряжения из пресетов, устанавливает индекс
игрока, боестолкновения, события среды, имя карты и логистическое
состояние. Если сценарий не содержит блока logistics, используется
fallback-блок: база в тылу игрока, передовой склад рядом с игроком,
маршрут между ними, транспорт и начальное снабжение по умолчанию.

Поддерживает общую линию фронта (блок front): дивизии развёртываются
вдоль неё по секторам. Обороняющаяся сторона (role=defender)
растягивается в три линии на весь фронт; нападающая сторона
(role=attacker) держит экранирующий пояс по всему фронту и
сосредоточивает ударные полки в точке прорыва (breakthrough).

При размещении сущности человекочитаемое имя из пресета записывается
в state.labels, а тактическое обозначение формата
«РИМСКАЯ-РИМСКАЯ-арабская» (эшелон-род войск-номер) — в state.tactical_ids.

Загрузка устойчива к битым конфигам: отсутствующие и повреждённые
файлы не роняют игру, а логируются предупреждением; ключи и строковые
значения нормализуются (обрезаются пробелы), чтобы файлы с лишними
пробелами в ключах не приводили к тихому пропуску сущностей;
отсутствующий player_entity_id не вызывает исключения, а заменяется
fallback-индексом. События модуля записываются в журнал
operation_ozverin.log в корне проекта и дублируются в консоль.
"""

import json
import logging
import math
import os
import re
from pathlib import Path

import numpy as np

from core.config_loader import load_class_config
from core.logistics import load_logistics_state
from core.state import WorldState

STUB_ROWS = 256
STUB_COLS = 256
DEFENDER_LINE_DEPTHS = (2.0, 12.0, 22.0)
DEFENDER_RESERVE_SPREAD = 0.5
ATTACKER_SCREEN_DEPTH = 3.0
ATTACKER_MASS_DEPTHS = (8.0, 14.0)
ATTACKER_CLUSTER_WIDTH = 0.06
DEFAULT_FRONT = {"from": [128, 4], "to": [128, 252], "normal": [-1, 0]}

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "operation_ozverin.log",
)


def _get_logger(name):
    """
    Возвращает журнал с файловым и консольным обработчиками.

    Файловый обработчик пишет в operation_ozverin.log в корне проекта
    с уровнем DEBUG, консольный выводит сообщения уровня INFO и выше.
    Обработчики навешиваются один раз на имя журнала.

    Args:
        name: Имя журнала.

    Returns:
        logging.Logger: Настроенный журнал.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
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


logger = _get_logger("game.scenario_loader")

ECHELON_BY_KEYWORD = (
    ("дивизия", "V"),
    ("бригада", "IV"),
    ("полк", "III"),
    ("батальон", "II"),
    ("рота", "I"),
)

BRANCH_BY_KEYWORD = (
    ("танк", "II"),
    ("арт", "III"),
    ("развед", "IV"),
    ("штаб", "V"),
    ("пехот", "I"),
    ("мотострел", "I"),
)


def make_tactical_id(label, manpower=0.0):
    """
    Формирует тактическое обозначение формата «Э-Р-№».

    Первая римская цифра — эшелон (тип подразделения), вторая римская
    цифра — род войск, арабская — номер из метки. Эшелон определяется
    по ключевому слову в метке, при отсутствии — по штатной
    численности. Род войск — по ключевому слову, по умолчанию пехота
    (I). Номер — первое число из метки.

    Args:
        label: Человекочитаемое имя подразделения.
        manpower: Штатная численность для fallback-эшелона.

    Returns:
        str: Обозначение вида «III-I-127».
    """
    label_l = label.lower()
    echelon = None
    for kw, rom in ECHELON_BY_KEYWORD:
        if kw in label_l:
            echelon = rom
            break
    if echelon is None:
        if manpower >= 7000:
            echelon = "V"
        elif manpower >= 3000:
            echelon = "IV"
        elif manpower >= 1000:
            echelon = "III"
        elif manpower >= 300:
            echelon = "II"
        else:
            echelon = "I"
    branch = "I"
    for kw, rom in BRANCH_BY_KEYWORD:
        if kw in label_l:
            branch = rom
            break
    m = re.search(r"\d+", label)
    number = int(m.group()) if m else 0
    return f"{echelon}-{branch}-{number}"


def _normalize(value):
    """
    Рекурсивно нормализует данные JSON: обрезает пробелы у строковых
    значений и у ключей словарей, чтобы файлы с лишними пробелами в
    ключах и значениях читались корректно.

    Args:
        value: Произвольное значение из JSON.

    Returns:
        Нормализованное значение той же структуры.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return {str(k).strip(): _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def load_presets(presets_dir="configs/presets") -> dict:
    """
    Загружает все пресеты из указанной директории.

    Читает каждый JSON-файл, нормализует пробелы и складывает данные
    в словарь с ключом по полю preset_id или по имени файла без
    расширения. Повреждённые файлы пропускаются с предупреждением,
    а не роняют загрузку.

    Args:
        presets_dir: Путь к директории с пресетами.

    Returns:
        dict: Словарь пресетов по идентификаторам.
    """
    presets = {}
    for f in sorted(Path(presets_dir).glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
        except Exception as e:
            logger.warning("Не удалось прочитать пресет %s: %s", f, e)
            continue
        if not isinstance(data, dict):
            logger.warning("Пресет %s не является объектом, пропущен", f)
            continue
        data = _normalize(data)
        preset_id = data.get("preset_id") or f.stem
        presets[preset_id] = data
    logger.info("Загружено пресетов: %d", len(presets))
    return presets


def load_map(map_name):
    """
    Загружает карту высот и биомов из scenarios/maps/<name>.npz.

    При отсутствии файла возвращает детерминированную заглушку
    256x256 со случайными высотами и биомом равнины (2).

    Args:
        map_name: Имя карты без расширения.

    Returns:
        tuple[numpy.ndarray, numpy.ndarray]: Кортеж (heights, biomes).
    """
    path = Path("scenarios/maps") / f"{map_name}.npz"
    if not path.exists():
        logger.warning("Карта не найдена: %s — установлена заглушка", path)
        rng = np.random.default_rng(1)
        return (
            rng.random((STUB_ROWS, STUB_COLS)).astype(np.float32),
            np.full((STUB_ROWS, STUB_COLS), 2, np.int8),
        )
    data = np.load(path)
    logger.info("Карта загружена: %s", map_name)
    return data["heights"], data["biomes"]


def _load_scenario(scenario_path):
    """
    Безопасно читает сценарий мира. Отсутствующий файл, ошибка
    парсинга или не-объект возвращают пустой словарь с предупреждением,
    а не исключение, чтобы битый конфиг не ронял игру.

    Args:
        scenario_path: Путь к JSON-файлу сценария.

    Returns:
        dict: Нормализованные данные сценария или пустой словарь.
    """
    path = Path(scenario_path)
    if not path.exists():
        logger.warning(
            "Сценарий не найден: %s — используется пустой сценарий", path
        )
        return {}
    try:
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception as e:
        logger.warning(
            "Не удалось прочитать сценарий %s: %s — используется пустой сценарий",
            path,
            e,
        )
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "Сценарий %s не является объектом — используется пустой сценарий",
            path,
        )
        return {}
    return _normalize(data)


def _default_logistics_block(state) -> dict:
    """
    Формирует fallback-блок логистики для сценариев без собственного
    блока logistics. База снабжения размещается в тылу игрока,
    передовой склад — в точке игрока, маршрут соединяет их, транспорт
    и начальное снабжение задаются по умолчанию.

    Args:
        state: Состояние игрового мира (WorldState).

    Returns:
        dict: Блок логистики в формате сценария.
    """
    px = int(state.coords[state.player_idx, 0])
    py = int(state.coords[state.player_idx, 1])
    return {
        "bases": [
            {
                "id": "base_main",
                "x": max(0, px - 10),
                "y": min(255, py + 10),
                "faction": "player",
                "classes": ["I", "II", "III", "IV", "V", "VI", "VII"],
                "intake_rate": {
                    "I": 500.0,
                    "II": 50.0,
                    "III": 20.0,
                    "IV": 10.0,
                    "V": 5.0,
                    "VI": 200.0,
                    "VII": 5.0,
                },
                "supply_radius": 15.0,
                "stockpile": {
                    "I": 5000.0,
                    "II": 500.0,
                    "III": 200.0,
                    "IV": 100.0,
                    "V": 50.0,
                    "VI": 1000.0,
                    "VII": 50.0,
                },
            }
        ],
        "depots": [
            {
                "id": "depot_front",
                "x": px,
                "y": py,
                "faction": "player",
                "capacity": 2000.0,
                "supply_radius": 15.0,
                "protection": 0.5,
                "stockpile": {
                    "I": 1000.0,
                    "II": 100.0,
                    "III": 50.0,
                    "IV": 25.0,
                    "V": 10.0,
                    "VI": 200.0,
                    "VII": 10.0,
                },
            }
        ],
        "routes": [
            {
                "id": "route_main",
                "from_node": "base_main",
                "to_node": "depot_front",
                "route_type": "dirt",
                "throughput": 20.0,
                "wear": 0.0,
                "repair_difficulty": 1.0,
                "length": 10.0,
            }
        ],
        "vehicles": [
            {"type": "jeep", "count": 2},
            {"type": "apc", "count": 1},
            {"type": "truck", "count": 2},
        ],
        "default_water_source": True,
        "initial_unit_supply": {
            "I": 1000.0,
            "II": 10.0,
            "III": 5.0,
            "IV": 5.0,
            "V": 5.0,
            "VI": 50.0,
            "VII": 2.0,
        },
    }


def _front_basis(front):
    """
    Вычисляет базис линии фронта: начала, конца и нормали.

    Нормаль указывает в сторону нападающей стороны; при отсутствии
    поля normal берётся левая перпендикулярная к направлению фронта.

    Args:
        front: Словарь фронта с полями from, to и опциональным normal.

    Returns:
        tuple: ((x0, y0), (x1, y1), (nx, ny)).
    """
    f0 = (float(front["from"][0]), float(front["from"][1]))
    f1 = (float(front["to"][0]), float(front["to"][1]))
    n = front.get("normal")
    if n is not None:
        nx, ny = float(n[0]), float(n[1])
        length = math.hypot(nx, ny)
        if length > 1e-9:
            nx, ny = nx / length, ny / length
        else:
            nx, ny = -1.0, 0.0
    else:
        lx, ly = f1[0] - f0[0], f1[1] - f0[1]
        length = math.hypot(lx, ly) or 1.0
        nx, ny = -ly / length, lx / length
    return f0, f1, (nx, ny)


def _heading_from_vec(vx, vy):
    """
    Возвращает индекс направления (0-5) по доминирующей оси вектора.

    Args:
        vx: Компонента X.
        vy: Компонента Y.

    Returns:
        int: Индекс направления.
    """
    if abs(vx) > abs(vy):
        return 1 if vx > 0 else 3
    return 0 if vy < 0 else 2


def _front_point(f0, f1, t, nx, ny, offset):
    """
    Возвращает точку фронта с параметром t, смещённую по нормали.

    Args:
        f0: Начало фронта.
        f1: Конец фронта.
        t: Параметр вдоль фронта [0, 1].
        nx: Компонента X нормали.
        ny: Компонента Y нормали.
        offset: Смещение по нормали (со знаком).

    Returns:
        tuple: Координаты (x, y).
    """
    px = f0[0] + (f1[0] - f0[0]) * t + nx * offset
    py = f0[1] + (f1[1] - f0[1]) * t + ny * offset
    return px, py


def _division_channels(preset, share):
    """
    Возвращает каналы пресета, умноженные на долю.

    Args:
        preset: Пресет дивизии.
        share: Доля значений каналов.

    Returns:
        dict: Каналы с уменьшенными значениями.
    """
    return {ch: val * share for ch, val in preset.get("voltages", {}).items()}


def _spawn_subunit(
    state,
    class_id,
    entity_id,
    label,
    parent_idx,
    x,
    y,
    faction,
    size,
    preset,
    channels,
    heading,
    bounds,
):
    """
    Создаёт подъюнит с наследованием сегментов и каналов пресета.

    Args:
        state: Состояние игрового мира (WorldState).
        class_id: Индекс класса сущности.
        entity_id: Уникальный ID новой сущности.
        label: Человекочитаемое имя.
        parent_idx: Индекс родительской сущности.
        x: Координата X.
        y: Координата Y.
        faction: Фракция.
        size: Значение сегмента size (эшелон).
        preset: Пресет дивизии для наследования сегментов.
        channels: Словарь каналов напряжений новой сущности.
        heading: Направление (0-5).
        bounds: Границы карты (rows, cols).

    Returns:
        int: Индекс созданной сущности.
    """
    idx = state.add_entity(entity_id, class_id, parent_idx)
    state.labels[idx] = label
    cx = max(0, min(bounds[1] - 1, int(round(x))))
    cy = max(0, min(bounds[0] - 1, int(round(y))))
    state.coords[idx, 0] = cx
    state.coords[idx, 1] = cy
    state.factions[idx] = faction
    state.set_heading(idx, heading)
    for seg, val in preset.get("segments", {}).items():
        state.write_segment(idx, seg, int(val))
    state.write_segment(idx, "size", size)
    config = state.class_configs[class_id]
    for ch, val in channels.items():
        ch_idx = config.voltage_layout.channel_index.get(ch)
        if ch_idx is not None:
            state.voltages_next[idx, ch_idx] = float(val)
    state.tactical_ids[idx] = make_tactical_id(
        label, channels.get("U_manpower", 0.0)
    )
    return idx


def _company_position(
    role, r, b, c, t0, t1, center, width, base_spacing, bt
):
    """
    Вычисляет параметр t вдоль фронта и глубину для роты.

    Обороняющаяся сторона: полки образуют три линии (две линии
    по всему сектору и резерв в центре). Нападающая сторона:
    первый полк экранирует весь сектор, остальные сосредоточены
    в точке прорыва.

    Args:
        role: Роль стороны ("defender" или "attacker").
        r: Индекс полка (0-2).
        b: Индекс батальона (0-2).
        c: Индекс роты (0-2).
        t0: Начало сектора.
        t1: Конец сектора.
        center: Центр сектора.
        width: Ширина сектора.
        base_spacing: Базовый шаг рот по фронту.
        bt: Точка прорыва (параметр t).

    Returns:
        tuple: (t, depth).
    """
    if role == "defender":
        spread = 1.0 if r < 2 else DEFENDER_RESERVE_SPREAD
        depth = DEFENDER_LINE_DEPTHS[r]
        bat_center = center + ((b + 0.5) / 3.0 - 0.5) * width * spread
        t = bat_center + (c - 1) * base_spacing * spread
        return t, depth
    if r == 0:
        bat_center = center + ((b + 0.5) / 3.0 - 0.5) * width
        t = bat_center + (c - 1) * base_spacing
        return t, ATTACKER_SCREEN_DEPTH
    depth = ATTACKER_MASS_DEPTHS[r - 1]
    bat_center = bt + (b - 1) * ATTACKER_CLUSTER_WIDTH * 2.0
    t = bat_center + (c - 1) * (ATTACKER_CLUSTER_WIDTH * 2.0 / 3.0)
    return t, depth


def _expand_division(state, idx, preset, bounds, placement, front):
    """
    Развёртывает дивизию в полки, батальоны и роты вдоль линии фронта.

    Обороняющаяся сторона растягивается в три линии на весь свой
    сектор; нападающая сторона держит экранирующий пояс по всему
    сектору и сосредоточивает два полка в точке прорыва.

    Args:
        state: Состояние игрового мира (WorldState).
        idx: Индекс дивизии.
        preset: Пресет дивизии.
        bounds: Границы карты (rows, cols).
        placement: Словарь размещения дивизии.
        front: Словарь линии фронта.

    Returns:
        int: Количество созданных подъюнитов.
    """
    role = str(placement.get("role", "defender"))
    sector = placement.get("sector", [0.0, 1.0])
    t0 = float(sector[0])
    t1 = float(sector[1])
    width = max(1e-4, t1 - t0)
    center = (t0 + t1) / 2.0
    bt = float(placement.get("breakthrough", center))
    f0, f1, (nx, ny) = _front_basis(front)
    side = 1.0 if role == "attacker" else -1.0
    if role == "defender":
        face = (nx, ny)
    else:
        face = (-nx, -ny)
    heading = _heading_from_vec(face[0], face[1])
    state.set_heading(idx, heading)
    base_spacing = width / 9.0
    div_id = state.entity_ids[idx]
    created = 0
    for r in range(3):
        reg_channels = _division_channels(preset, 1.0 / 3.0)
        reg_t, reg_depth = _company_position(
            role, r, 1, 1, t0, t1, center, width, base_spacing, bt
        )
        reg_x, reg_y = _front_point(f0, f1, reg_t, nx, ny, side * reg_depth)
        reg_idx = _spawn_subunit(
            state,
            state.class_ids[idx],
            f"{div_id}_regiment_{r + 1}",
            f"{state.labels[idx]} {r + 1}-й полк",
            idx,
            reg_x,
            reg_y,
            state.factions[idx],
            3,
            preset,
            reg_channels,
            heading,
            bounds,
        )
        created += 1
        for b in range(3):
            bat_channels = _division_channels(preset, 1.0 / 9.0)
            bat_t, bat_depth = _company_position(
                role, r, b, 1, t0, t1, center, width, base_spacing, bt
            )
            bat_x, bat_y = _front_point(
                f0, f1, bat_t, nx, ny, side * bat_depth
            )
            bat_idx = _spawn_subunit(
                state,
                state.class_ids[idx],
                f"{div_id}_regiment_{r + 1}_battalion_{b + 1}",
                f"{state.labels[idx]} {r + 1}-й полк {b + 1}-й батальон",
                reg_idx,
                bat_x,
                bat_y,
                state.factions[idx],
                2,
                preset,
                bat_channels,
                heading,
                bounds,
            )
            created += 1
            for c in range(3):
                comp_channels = _division_channels(preset, 1.0 / 27.0)
                comp_t, comp_depth = _company_position(
                    role, r, b, c, t0, t1, center, width, base_spacing, bt
                )
                comp_x, comp_y = _front_point(
                    f0, f1, comp_t, nx, ny, side * comp_depth
                )
                _spawn_subunit(
                    state,
                    state.class_ids[idx],
                    f"{div_id}_regiment_{r + 1}_battalion_{b + 1}_company_{c + 1}",
                    f"{state.labels[idx]} {r + 1}-й полк {b + 1}-й батальон {c + 1}-я рота",
                    bat_idx,
                    comp_x,
                    comp_y,
                    state.factions[idx],
                    1,
                    preset,
                    comp_channels,
                    heading,
                    bounds,
                )
                created += 1
    if role == "defender":
        hq_depth = DEFENDER_LINE_DEPTHS[2] + 6.0
        hq_t = center
    else:
        hq_depth = 18.0
        hq_t = bt
    hq_x, hq_y = _front_point(f0, f1, hq_t, nx, ny, side * hq_depth)
    hx = max(0, min(bounds[1] - 1, int(round(hq_x))))
    hy = max(0, min(bounds[0] - 1, int(round(hq_y))))
    state.coords[idx, 0] = hx
    state.coords[idx, 1] = hy
    logger.info(
        "Дивизия %s развёрнута: роль=%s, сектор=[%.2f, %.2f], подъюнитов=%d",
        div_id,
        role,
        t0,
        t1,
        created,
    )
    return created


def build_world(
    scenario_path="scenarios/mvp.json",
    classes_dir="configs/classes",
    capacity=256,
) -> WorldState:
    """
    Собирает полный игровой мир из конфигов классов и сценария.

    Загружает конфиги классов, сценарий и пресеты, вычисляет число
    каналов напряжений, создаёт WorldState, размещает сущности из
    placements, применяет сегменты и напряжения из пресетов,
    развёртывает дивизии вдоль линии фронта по секторам и ролям,
    задаёт индекс игрока, боестолкновения, события среды, имя карты
    и логистическое состояние. При отсутствии блока logistics
    применяет fallback-блок. Битые и отсутствующие конфиги не роняют
    сборку: размещения без entity_id или с неизвестным классом
    пропускаются с предупреждением, отсутствующий player_entity_id
    заменяется индексом первой сущности.

    Args:
        scenario_path: Путь к JSON-файлу сценария.
        classes_dir: Путь к директории конфигов классов.
        capacity: Ёмкость состояния мира по сущностям.

    Returns:
        WorldState: Собранное состояние игрового мира.
    """
    class_configs = []
    for f in sorted(Path(classes_dir).glob("*.json")):
        cfg = load_class_config(f)
        if cfg:
            class_configs.append(cfg)
    logger.info("Загружено конфигов классов: %d", len(class_configs))
    scenario = _load_scenario(scenario_path)
    presets = load_presets()
    max_voltage_channels = 32
    for cfg in class_configs:
        max_voltage_channels = max(
            max_voltage_channels,
            cfg.voltage_layout.num_channels,
        )
    state = WorldState(
        capacity=capacity,
        max_voltage_channels=max_voltage_channels,
    )
    state.class_configs = class_configs
    state.tactical_ids = [""] * capacity
    name_to_id = {c.class_name: i for i, c in enumerate(class_configs)}
    id_to_idx = {}
    division_placements = []
    for pl in scenario.get("placements", []):
        if not isinstance(pl, dict):
            logger.warning(
                "Размещение не является объектом в %s, пропущено",
                scenario_path,
            )
            continue
        entity_id = pl.get("entity_id")
        if not entity_id:
            logger.warning(
                "Размещение без entity_id в %s, пропущено", scenario_path
            )
            continue
        preset = presets.get(pl.get("preset"), {})
        class_name = preset.get("class", pl.get("class"))
        cid = name_to_id.get(class_name)
        if cid is None:
            logger.warning("Неизвестный класс: %s", class_name)
            continue
        idx = state.add_entity(
            entity_id,
            cid,
            id_to_idx.get(pl.get("parent_id"), -1),
        )
        id_to_idx[entity_id] = idx
        state.labels[idx] = (
            preset.get("label")
            or pl.get("label")
            or entity_id
        )
        state.coords[idx, 0] = int(pl.get("x", 0))
        state.coords[idx, 1] = int(pl.get("y", 0))
        state.factions[idx] = pl.get("faction", "neutral")
        for seg, val in preset.get("segments", {}).items():
            state.write_segment(idx, seg, int(val))
        manpower = 0.0
        for ch, val in preset.get("voltages", {}).items():
            ch_idx = state.class_configs[cid].voltage_layout.channel_index.get(
                ch
            )
            if ch_idx is not None:
                state.voltages_next[idx, ch_idx] = float(val)
            if ch == "U_manpower":
                manpower = float(val)
        state.tactical_ids[idx] = make_tactical_id(state.labels[idx], manpower)
        size_value = int(preset.get("segments", {}).get("size", 0))
        if size_value >= 5:
            division_placements.append((idx, preset, pl))
    state.map_name = scenario.get("map") or "valley_01"
    state.heights, state.biomes = load_map(state.map_name)
    bounds = (STUB_ROWS, STUB_COLS)
    if state.heights is not None:
        bounds = state.heights.shape
    if division_placements:
        front = scenario.get("front")
        if not isinstance(front, dict) or "from" not in front or "to" not in front:
            front = dict(DEFAULT_FRONT)
            logger.warning(
                "Сценарий %s без блока front — использован фронт по умолчанию",
                scenario_path,
            )
        role_groups = {}
        for _, _, pl in division_placements:
            role = str(pl.get("role", "defender"))
            role_groups.setdefault(role, []).append(pl)
        for role, pls in role_groups.items():
            n = len(pls)
            for i, pl in enumerate(pls):
                if "sector" not in pl:
                    pl["sector"] = [i / n, (i + 1) / n]
        for idx, preset, pl in division_placements:
            _expand_division(state, idx, preset, bounds, pl, front)
    state.commit_tick()
    for idx in range(state.count):
        cfg = state.class_configs[state.class_ids[idx]]
        ch = cfg.voltage_layout.channel_index.get("U_manpower")
        if ch is not None:
            state.initial_manpower[idx] = float(
                state.voltages_current[idx, ch]
            )
    player_id = scenario.get("player_entity_id")
    if player_id is not None and player_id in id_to_idx:
        state.player_idx = id_to_idx[player_id]
    else:
        if player_id is not None:
            logger.warning(
                "player_entity_id '%s' не найден в placements сценария %s — "
                "игроком назначена первая сущность",
                player_id,
                scenario_path,
            )
        else:
            logger.warning(
                "player_entity_id не задан в сценарии %s — "
                "игроком назначена первая сущность",
                scenario_path,
            )
        state.player_idx = 0
    state.engagements = scenario.get("engagements", [])
    state.environment_events = scenario.get("environment_events", [])
    logistics_block = scenario.get("logistics")
    if logistics_block is None:
        logistics_block = _default_logistics_block(state)
        logger.info("Логистика: блок сценария отсутствует, применён fallback")
    state.logistics = load_logistics_state(logistics_block, state)
    logger.info(
        "Мир собран: сущностей=%d, игрок=%d, карта=%s",
        state.count,
        state.player_idx,
        state.map_name,
    )
    return state