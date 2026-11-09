"""Предикторы, коэффициенты и маржа успеха кампании (§7.6 №33–35).

Успех действия в кампании не является отдельной формулой: он использует ту
же логистику ядра `success_probability`, что арена, а кампанийная оболочка
добавляет к ней отношения и авторский шанс действия. Модуль фиксирует три
вещи, которых не хватало для ответа на №33–35:

* **предикторы** — именованный список слагаемых логита;
* **коэффициенты** — значения по умолчанию и переопределения из контента
  действия (`success.coefficients` или `success_coefficients`);
* **маржа** — детерминированная разница `chance - roll`, которая
  записывается в результат, но не меняет бинарный исход.

Третьи автоматы не входят отдельным слагаемым: они влияют через
`authority`, `relations` и `resistance` цели. Это осознанно — иначе одно и
то же влияние учитывалось бы дважды.
"""

from __future__ import annotations

from core41.model import (
    DEFAULT_SUCCESS_COEFFICIENTS,
    SUCCESS_COEFFICIENT_KEYS,
)

SUCCESS_PREDICTORS = (
    {
        "key": "intercept",
        "label": "базовый порог",
        "source": "константа",
        "direction": +1,
    },
    {
        "key": "skill",
        "label": "навык · работоспособность · здоровье",
        "source": "атакующий",
        "direction": +1,
    },
    {
        "key": "authority",
        "label": "полномочия/сила позиции",
        "source": "атакующий",
        "direction": +1,
    },
    {
        "key": "resistance",
        "label": "сопротивление формы",
        "source": "защитник",
        "direction": -1,
    },
    {
        "key": "open",
        "label": "открытое окно",
        "source": "контекст",
        "direction": +1,
    },
    {
        "key": "env",
        "label": "давление среды",
        "source": "среда",
        "direction": +1,
    },
    {
        "key": "intel",
        "label": "свежая слабая точка",
        "source": "разведка",
        "direction": +1,
    },
    {
        "key": "amount",
        "label": "объём работы / прочность цели",
        "source": "работа и защитник",
        "direction": -1,
    },
)


def resolve_success_coefficients(action):
    """Собрать коэффициенты действия поверх значений по умолчанию.

    Контент может положить объект в `success.coefficients` (предпочтительно)
    или в `action["success_coefficients"]` (совместимый короткий путь).
    Неизвестные ключи и нечисловые значения игнорируются: опечатка в
    контенте не должна ломать бросок. Значения ограничены `[-10, 10]`,
    чтобы одно действие не могло превратить логистику в константу.
    """
    action = action or {}
    raw = action.get("success_coefficients")
    if raw is None:
        raw = (action.get("success") or {}).get("coefficients")
    coefficients = dict(DEFAULT_SUCCESS_COEFFICIENTS)
    if not isinstance(raw, dict):
        return coefficients
    for key in SUCCESS_COEFFICIENT_KEYS:
        if key not in raw:
            continue
        try:
            value = float(raw[key])
        except (TypeError, ValueError):
            continue
        coefficients[key] = max(-10.0, min(10.0, value))
    return coefficients


def success_margin(chance, roll):
    """Маржа исхода: `chance - roll`.

    Положительная маржа — успех, отрицательная — провал; абсолютная
    величина показывает, насколько бросок был далёк от порога. Это
    диагностика и материал для калибровки, а не второй способ определить
    успех: ветка выбирается строго по `roll < chance`.
    """
    return float(chance) - float(roll)


def success_margin_view(chance, roll):
    margin = success_margin(chance, roll)
    return {
        "chance": float(chance),
        "roll": float(roll),
        "margin": margin,
        "outcome": "success" if margin > 0.0 else "failure",
        "distance": abs(margin),
    }


__all__ = [
    "SUCCESS_PREDICTORS",
    "resolve_success_coefficients",
    "success_margin",
    "success_margin_view",
]
