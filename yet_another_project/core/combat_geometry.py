"""
core/combat_geometry.py

Чистая геометрия боя.

Обрабатывает направления и проекции: front, left, right, rear,
bottom, top. Координатная договорённость: x растёт вправо,
y растёт вниз; север = уменьшение y, юг = увеличение y,
восток = увеличение x, запад = уменьшение x.

Проекции определяют, в какую часть сущности приходится воздействие.
Направления определяют ориентацию сущности в мире. Все функции
модуля являются чистыми и не читают состояние игры. Модуль не
содержит адаптеров входных алфавитов и преобразований сигналов
между сущностями.

События модуля записываются в журнал operation_ozverin.log в корне
проекта и дублируются в консоль.
"""

import logging
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[1] / "operation_ozverin.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

logger = logging.getLogger("core.combat_geometry")
if not logger.handlers:
    logger.setLevel(logging.DEBUG)
    _file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(_file_handler)
    _console_handler = logging.StreamHandler()
    _console_handler.setLevel(logging.INFO)
    _console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(_console_handler)
    logger.propagate = False

PROJ_FRONT = 0
PROJ_LEFT = 1
PROJ_RIGHT = 2
PROJ_REAR = 3
PROJ_BOTTOM = 4
PROJ_TOP = 5

PROJ_INDEX = {
    "front": PROJ_FRONT,
    "left": PROJ_LEFT,
    "right": PROJ_RIGHT,
    "rear": PROJ_REAR,
    "bottom": PROJ_BOTTOM,
    "top": PROJ_TOP,
}

PROJ_NAMES = {
    PROJ_FRONT: "front",
    PROJ_LEFT: "left",
    PROJ_RIGHT: "right",
    PROJ_REAR: "rear",
    PROJ_BOTTOM: "bottom",
    PROJ_TOP: "top",
}

HEADING_NORTH = 0
HEADING_EAST = 1
HEADING_SOUTH = 2
HEADING_WEST = 3
HEADING_UP = 4
HEADING_DOWN = 5

HEADING_INDEX = {
    "north": HEADING_NORTH,
    "east": HEADING_EAST,
    "south": HEADING_SOUTH,
    "west": HEADING_WEST,
    "up": HEADING_UP,
    "down": HEADING_DOWN,
}

HEADING_NAMES = {
    HEADING_NORTH: "north",
    HEADING_EAST: "east",
    HEADING_SOUTH: "south",
    HEADING_WEST: "west",
    HEADING_UP: "up",
    HEADING_DOWN: "down",
}


def normalize_projection(value):
    """
    Нормализует значение проекции к целочисленному индексу.

    Принимает целое число или строковое имя проекции. Целые числа
    ограничиваются диапазоном [0, 5]. Неизвестные строки возвращают
    PROJ_FRONT.

    Args:
        value: Целое число или строковое имя проекции.

    Returns:
        int: Индекс проекции в диапазоне [0, 5].
    """
    if isinstance(value, int):
        result = max(PROJ_FRONT, min(PROJ_TOP, value))
    else:
        result = PROJ_INDEX.get(str(value), PROJ_FRONT)
    logger.debug("normalize_projection value=%r -> %s", value, result)
    return result


def normalize_heading(value):
    """
    Нормализует значение направления к целочисленному индексу.

    Принимает целое число или строковое имя направления. Целые числа
    вне диапазона [0, 5] возвращают HEADING_NORTH. Неизвестные строки
    возвращают HEADING_NORTH.

    Args:
        value: Целое число или строковое имя направления.

    Returns:
        int: Индекс направления в диапазоне [0, 5].
    """
    if isinstance(value, int):
        if HEADING_NORTH <= value <= HEADING_DOWN:
            result = value
        else:
            result = HEADING_NORTH
    else:
        result = HEADING_INDEX.get(str(value), HEADING_NORTH)
    logger.debug("normalize_heading value=%r -> %s", value, result)
    return result


def direction_between(src_x: int, src_y: int, dst_x: int, dst_y: int):
    """
    Возвращает направление из точки src в точку dst.

    Направление определяется по доминирующей оси: если горизонтальное
    смещение больше вертикального, возвращается HEADING_EAST или
    HEADING_WEST; иначе HEADING_NORTH или HEADING_SOUTH. Вертикальные
    направления HEADING_UP и HEADING_DOWN не возвращаются.

    Args:
        src_x: Координата X исходной точки.
        src_y: Координата Y исходной точки.
        dst_x: Координата X целевой точки.
        dst_y: Координата Y целевой точки.

    Returns:
        int | None: Направление (HEADING_NORTH, HEADING_EAST,
            HEADING_SOUTH или HEADING_WEST) или None, если точки
            совпадают.
    """
    dx = dst_x - src_x
    dy = dst_y - src_y
    if dx == 0 and dy == 0:
        logger.debug(
            "direction_between src=(%s, %s) dst=(%s, %s) -> None",
            src_x, src_y, dst_x, dst_y,
        )
        return None
    if abs(dx) > abs(dy):
        result = HEADING_EAST if dx > 0 else HEADING_WEST
    else:
        result = HEADING_SOUTH if dy > 0 else HEADING_NORTH
    logger.debug(
        "direction_between src=(%s, %s) dst=(%s, %s) -> %s",
        src_x, src_y, dst_x, dst_y, result,
    )
    return result


def relative_projection(heading: int, source_dir: int) -> int:
    """
    Возвращает проекцию, с которой приходит источник, относительно
    направления взгляда цели.

    Если источник находится сверху или снизу, возвращаются PROJ_TOP
    или PROJ_BOTTOM соответственно. Для горизонтальных направлений
    проекция вычисляется как разница между направлением источника и
    направлением взгляда цели по модулю 4. Если цель смотрит
    вертикально (HEADING_UP или HEADING_DOWN), горизонтальные
    источники проецируются на PROJ_FRONT.

    Args:
        heading: Направление, куда смотрит цель (HEADING_*).
        source_dir: Направление, откуда приходит воздействие
            (HEADING_* или None).

    Returns:
        int: Проекция (PROJ_*).
    """
    if source_dir is None:
        result = PROJ_FRONT
    elif source_dir == HEADING_UP:
        result = PROJ_TOP
    elif source_dir == HEADING_DOWN:
        result = PROJ_BOTTOM
    elif heading in (HEADING_UP, HEADING_DOWN):
        result = PROJ_FRONT
    else:
        diff = (source_dir - heading) % 4
        if diff == 0:
            result = PROJ_FRONT
        elif diff == 1:
            result = PROJ_RIGHT
        elif diff == 2:
            result = PROJ_REAR
        else:
            result = PROJ_LEFT
    logger.debug(
        "relative_projection heading=%s source_dir=%s -> %s",
        heading, source_dir, result,
    )
    return result


def incoming_projection(
    attacker_x: int,
    attacker_y: int,
    defender_x: int,
    defender_y: int,
    defender_heading: int,
) -> int:
    """
    Возвращает проекцию defender'а, в которую прилетает атака.

    Вычисляет направление от defender'а к attacker'у и определяет,
    какая проекция defender'а обращена в эту сторону.

    Args:
        attacker_x: Координата X атакующего.
        attacker_y: Координата Y атакующего.
        defender_x: Координата X защитника.
        defender_y: Координата Y защитника.
        defender_heading: Направление, куда смотрит защитник (HEADING_*).

    Returns:
        int: Проекция защитника (PROJ_*), в которую приходится удар.
    """
    source_dir = direction_between(
        defender_x, defender_y,
        attacker_x, attacker_y,
    )
    result = relative_projection(defender_heading, source_dir)
    logger.info(
        "incoming_projection attacker=(%s, %s) defender=(%s, %s) "
        "defender_heading=%s -> %s",
        attacker_x, attacker_y, defender_x, defender_y,
        defender_heading, result,
    )
    return result


def outgoing_projection(
    attacker_x: int,
    attacker_y: int,
    defender_x: int,
    defender_y: int,
    attacker_heading: int,
) -> int:
    """
    Возвращает проекцию атакующего, направленную в сторону defender'а.

    Вычисляет направление от attacker'а к defender'у и определяет,
    какая проекция атакующего обращена в эту сторону. Это та проекция,
    которой атакующий фактически наносит удар.

    Args:
        attacker_x: Координата X атакующего.
        attacker_y: Координата Y атакующего.
        defender_x: Координата X защитника.
        defender_y: Координата Y защитника.
        attacker_heading: Направление, куда смотрит атакующий (HEADING_*).

    Returns:
        int: Проекция атакующего (PROJ_*), которой наносится удар.
    """
    target_dir = direction_between(
        attacker_x, attacker_y,
        defender_x, defender_y,
    )
    result = relative_projection(attacker_heading, target_dir)
    logger.info(
        "outgoing_projection attacker=(%s, %s) defender=(%s, %s) "
        "attacker_heading=%s -> %s",
        attacker_x, attacker_y, defender_x, defender_y,
        attacker_heading, result,
    )
    return result