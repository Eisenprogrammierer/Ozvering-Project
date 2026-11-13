"""
core/terrain.py

Модуль местности для боевой системы.

Вычисляет оборонительный модификатор входящего урона на основе
биома под обороняющимся юнитом и разницы высот между обороняющимся
и атакующим юнитами. Данные читаются из configs/content/terrain.json
с кэшированием и значениями по умолчанию. События загрузки конфига,
сброса кэша и вычисления модификатора фиксируются в журнале
operation_ozverin.log в корне проекта и дублируются в консоль.

Поддерживаемые биомы:
1 — Вода
2 — Равнина
3 — Холмы
4 — Горы
5 — Лес
6 — Пустыня
7 — Болото
8 — Тундра
9 — Городская застройка
10 — Сельская застройка
"""

import logging
import os
from typing import Optional

import numpy as np

from .config_loader import load_json

DEFAULT_BIOME_DEFENSE = {
    1: 1.20,
    2: 1.00,
    3: 0.85,
    4: 0.70,
    5: 0.80,
    6: 1.05,
    7: 1.10,
    8: 1.05,
    9: 0.75,
    10: 0.90,
}
DEFAULT_HEIGHT_ADVANTAGE_THRESHOLD = 0.15
DEFAULT_HEIGHT_ADVANTAGE_MODIFIER = 0.85
DEFAULT_HEIGHT_DISADVANTAGE_MODIFIER = 1.10
DEFAULT_TERRAIN_MODIFIER_MIN = 0.5
DEFAULT_TERRAIN_MODIFIER_MAX = 1.5

_CONFIG = None


def _build_logger():
    """
    Создаёт и возвращает журнал модуля местности.

    Журнал записывает сообщения уровня DEBUG и выше в файл
    operation_ozverin.log в корне проекта и дублирует сообщения
    уровня INFO и выше в консоль. Повторный вызов возвращает уже
    настроенный журнал без дублирования обработчиков.

    Returns:
        logging.Logger: Настроенный журнал модуля.
    """
    logger = logging.getLogger("core.terrain")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    log_path = os.path.join(root, "operation_ozverin.log")
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


logger = _build_logger()


def _get_config() -> dict:
    """
    Возвращает конфигурацию местности.

    При первом обращении загружает данные из configs/content/terrain.json
    и кэширует результат. Если файл отсутствует или повреждён,
    используются значения по умолчанию. При загрузке из JSON к словарю
    biome_defense добавляются биомы 9 (городская застройка) и 10
    (сельская застройка) со значениями по умолчанию, если они
    отсутствуют в конфиге.

    Returns:
        dict: Конфигурация местности с нормализованными ключами
            в biome_defense (int -> float).
    """
    global _CONFIG
    if _CONFIG is None:
        raw = load_json("configs/content/terrain.json", {}) or {}
        cfg = dict(raw)
        logger.info("Конфиг местности загружен, ключей: %d", len(cfg))
        biome_raw = cfg.get("biome_defense", DEFAULT_BIOME_DEFENSE)
        try:
            parsed = {
                int(k): float(v)
                for k, v in biome_raw.items()
            }
        except Exception:
            parsed = dict(DEFAULT_BIOME_DEFENSE)
            logger.warning("Биомы не распознаны, применён fallback по умолчанию")
        added = []
        if 9 not in parsed:
            parsed[9] = DEFAULT_BIOME_DEFENSE[9]
            added.append(9)
        if 10 not in parsed:
            parsed[10] = DEFAULT_BIOME_DEFENSE[10]
            added.append(10)
        if added:
            logger.info("biome_defense дополнен биомами: %s", added)
        cfg["biome_defense"] = parsed
        _CONFIG = cfg
        logger.debug("Конфиг местности закэширован")
    return _CONFIG


def reset_config_cache():
    """
    Сбрасывает кэш конфигурации местности.

    Устанавливает внутренний кэш в None, после чего следующее
    обращение к _get_config выполняет повторную загрузку файла.
    """
    global _CONFIG
    _CONFIG = None
    logger.info("Кэш конфигурации местности сброшен")


def terrain_defense_modifier(
    heights: Optional[np.ndarray],
    biomes: Optional[np.ndarray],
    x: int,
    y: int,
    enemy_x: int,
    enemy_y: int,
) -> float:
    """
    Возвращает оборонительный модификатор местности для юнита в точке (x, y).

    Вычисляет множитель входящего урона как произведение модификатора
    биома под юнитом и модификатора разницы высот. Результат
    ограничивается диапазоном [terrain_modifier_min, terrain_modifier_max].

    Args:
        heights: Карта высот (2D-массив float). Может быть None.
        biomes: Карта биомов (2D-массив int). Может быть None.
        x: Координата X обороняющегося юнита.
        y: Координата Y обороняющегося юнита.
        enemy_x: Координата X атакующего юнита.
        enemy_y: Координата Y атакующего юнита.

    Returns:
        float: Множитель входящего урона.
            Меньше 1.0, если местность защищает обороняющегося;
            равно 1.0, если нейтрально или карты нет;
            больше 1.0, если местность ухудшает позицию.
    """
    if heights is None or biomes is None:
        logger.debug("Местность (%d, %d): карты нет, модификатор 1.0", x, y)
        return 1.0
    try:
        rows, cols = heights.shape
        biome_rows, biome_cols = biomes.shape
    except Exception:
        logger.debug("Местность (%d, %d): карты без формы, модификатор 1.0", x, y)
        return 1.0
    if rows != biome_rows or cols != biome_cols:
        logger.debug(
            "Местность (%d, %d): размер карт не совпадает, модификатор 1.0",
            x, y,
        )
        return 1.0
    if not (0 <= x < cols and 0 <= y < rows):
        logger.debug("Местность (%d, %d): вне границ, модификатор 1.0", x, y)
        return 1.0
    if not (0 <= enemy_x < cols and 0 <= enemy_y < rows):
        logger.debug(
            "Местность (%d, %d): противник вне границ, модификатор 1.0",
            x, y,
        )
        return 1.0
    cfg = _get_config()
    biome_defense = cfg.get("biome_defense", DEFAULT_BIOME_DEFENSE)
    height_advantage_threshold = float(
        cfg.get(
            "height_advantage_threshold",
            DEFAULT_HEIGHT_ADVANTAGE_THRESHOLD,
        )
    )
    height_advantage_modifier = float(
        cfg.get(
            "height_advantage_modifier",
            DEFAULT_HEIGHT_ADVANTAGE_MODIFIER,
        )
    )
    height_disadvantage_modifier = float(
        cfg.get(
            "height_disadvantage_modifier",
            DEFAULT_HEIGHT_DISADVANTAGE_MODIFIER,
        )
    )
    terrain_modifier_min = float(
        cfg.get(
            "terrain_modifier_min",
            DEFAULT_TERRAIN_MODIFIER_MIN,
        )
    )
    terrain_modifier_max = float(
        cfg.get(
            "terrain_modifier_max",
            DEFAULT_TERRAIN_MODIFIER_MAX,
        )
    )
    biome = int(biomes[y, x])
    modifier = float(biome_defense.get(biome, 1.0))
    own_height = float(heights[y, x])
    enemy_height = float(heights[enemy_y, enemy_x])
    height_diff = own_height - enemy_height
    if height_diff > height_advantage_threshold:
        modifier *= height_advantage_modifier
        logger.debug(
            "Местность (%d, %d): преимущество по высоте, множитель %.2f",
            x, y, modifier,
        )
    elif height_diff < -height_advantage_threshold:
        modifier *= height_disadvantage_modifier
        logger.debug(
            "Местность (%d, %d): невыгодная высота, множитель %.2f",
            x, y, modifier,
        )
    modifier = max(terrain_modifier_min, min(terrain_modifier_max, modifier))
    logger.debug(
        "Местность (%d, %d): биом %d, итоговый модификатор %.2f",
        x, y, biome, modifier,
    )
    return modifier