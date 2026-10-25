"""Простейшая геометрия направлений для секторов обзора."""

import math


def direction_between(x1, y1, x2, y2):
    """Вернуть направление 0..3 (север/восток/юг/запад) или None."""
    dx = float(x2) - float(x1)
    dy = float(y2) - float(y1)
    if dx == 0 and dy == 0:
        return None
    # Экранные координаты: y растёт вниз.
    angle = math.degrees(math.atan2(dx, -dy)) % 360.0
    return int(round(angle / 90.0)) % 4
