"""
core/config_loader.py

Загрузка JSON-конфигов классов сущностей и универсальных
конфигурационных файлов.

Модуль предоставляет две основные функции:
load_json — безопасное чтение произвольного JSON-файла с fallback;
load_class_config — парсинг JSON-описания класса сущности
в структуру ClassConfig (битовая маска, каналы напряжений,
правила валидации, метаморфозы, боевая модель, BDI,
восприимчивость к модальностям, матрица влияния, целевые веса).

События загрузки записываются в журнал operation_ozverin.log
в корне проекта и дублируются в консоль.
"""

import json
import logging
import os
from pathlib import Path

from .state import ClassConfig, SegmentLayout, VoltageLayout

LOG_FILENAME = "operation_ozverin.log"


def _build_logger(name):
    """
    Создаёт и возвращает именованный журнал с файловым и консольным
    обработчиками. Файловый обработчик пишет в operation_ozverin.log
    в корне проекта с уровнем DEBUG, консольный — с уровнем INFO.
    Обработчики навешиваются один раз; повторный вызов возвращает
    уже настроенный журнал без дублирования.

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
    logger.propagate = False
    return logger


logger = _build_logger("core.config_loader")


def load_json(path, default=None):
    """
    Безопасно читает JSON-файл.

    Если файл не существует или содержит некорректный JSON,
    возвращает значение по умолчанию без выброса исключения.
    Отсутствие файла и ошибки парсинга фиксируются в журнале
    на уровне WARNING, успешное чтение — на уровне DEBUG.

    Args:
        path: Путь к JSON-файлу (str или Path).
        default: Значение, возвращаемое при ошибке или отсутствии файла.

    Returns:
        Распарсенные данные JSON или default.
    """
    p = Path(path)
    if not p.exists():
        logger.warning("JSON не найден: %s", p)
        return default
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Не удалось прочитать %s: %s", p, e)
        return default
    logger.debug("JSON загружен: %s", p)
    return data


def load_class_config(path) -> "ClassConfig | None":
    """
    Загружает конфигурацию класса сущности из JSON-файла.

    Читает файл, разбирает сегменты битовой маски (сегменты со
    строковым полем states пропускаются), каналы напряжений с
    параметрами и триггерами Шмитта, собирает и возвращает
    экземпляр ClassConfig. Ошибка чтения или парсинга фиксируется
    в журнале на уровне WARNING и возвращает None.

    Args:
        path: Путь к JSON-файлу класса.

    Returns:
        Экземпляр ClassConfig или None при ошибке чтения/парсинга.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("Не удалось прочитать %s: %s", path, e)
        return None

    segments = {}
    for name, seg in data.get("bitmask", {}).get("segments", {}).items():
        states = seg.get("states", [])
        if isinstance(states, str):
            continue
        bits = seg.get("bits", [0, 0])
        segments[name] = (bits[0], bits[1] - bits[0] + 1, states)

    index, params, schmitt = {}, {}, {}
    for i, (name, ch) in enumerate(data.get("voltage_channels", {}).items()):
        index[name] = i
        params[name] = (
            ch.get("label", name),
            float(ch.get("initial", 0.0)),
            float(ch.get("min", 0.0)),
            float(ch.get("max", 1.0)),
            ch.get("threshold_low"),
            ch.get("threshold_high"),
            float(ch.get("decay_alpha", 1.0)),
        )
        target = ch.get("target_segment") or ch.get("target_indicator")
        if target:
            schmitt[name] = {
                "target_segment": target,
                "direction": ch.get("direction", "improve"),
            }

    class_name = data.get("class", Path(path).stem)
    logger.info(
        "Конфиг класса загружен: %s (сегментов=%d, каналов=%d)",
        class_name,
        len(segments),
        len(index),
    )
    return ClassConfig(
        class_name=class_name,
        label=data.get("label", "?"),
        segment_layout=SegmentLayout(segments=segments),
        voltage_layout=VoltageLayout(
            channel_index=index,
            channel_params=params,
            schmitt=schmitt,
            num_channels=len(index),
        ),
        validation_rules=data.get("validation_rules", []),
        metamorphosis_rules=data.get("metamorphosis_rules", []),
        combat_model=data.get("combat_model", {}),
        bdi=data.get("bdi", {}),
        susceptibility_profile=data.get("susceptibility_profile", {}),
        influence_matrix=data.get("influence_matrix", {}),
        objective_weights=data.get("objective_weights", {}),
    )