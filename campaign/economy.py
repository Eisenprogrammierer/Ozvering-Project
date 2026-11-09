"""Экономика кампании на одной универсальной энергии (§7.4 №21–26).

Модуль фиксирует пять вещей, которых не хватало после §2.6:

* **цену работы** — сколько `E` нужно заплатить, чтобы доставить эффект,
  и куда уходят потери (`conversion_quote`, `price_for_effect`);
* **поддержание** — суточный сток энергии и денег, зависящий от уровня,
  силы и ран (`maintenance_cost`), плюс отходы и ремонт;
* **масштаб** — цена и эффект зависят от уровня, силы и сопротивления
  цели, а не являются фиксированными долями (`scaled_cost`,
  `scaled_effect`);
* **бедность** — состояние «действий нет / энергии мало» и три клапана:
  отдых, помощь, кредит (`poverty_status`, `help_quote`, `credit_quote`);
* **природу** — не-BDI автомат, который совершает работу из сезонного
  источника и возвращает часть её в экономику (`nature_yield`).

Деньги, информация и политический капитал не становятся вторым видом
энергии. `resource_kind()` и `exchange_quote()` описывают их как
проекции/права/сигналы: только деньги имеют явный рыночный обработчик
обмена с `E`, и обмен всегда идёт с потерей.
"""

from __future__ import annotations

from core41.environment import SEASONS
from core41.model import (
    ENERGY_STORAGE_SHARE,
    conversion_efficiency,
    conversion_report,
)


ENERGY_SCALE = 100.0

MARKET_BUY_EFFICIENCY = 0.60
MARKET_SELL_EFFICIENCY = 0.75

DEFAULT_MAINTENANCE = {
    "base": 0.0,
    "per_level": 0.0,
    "per_force": 0.0,
    "per_wound": 0.0,
}

MAINTENANCE_STARVE_HEALTH = 0.50
MAINTENANCE_STARVE_FORCE = 0.004

DEFAULT_COST_SCALING = {
    "level": 0.0,
    "force": 0.0,
    "resistance": 0.0,
    "domain": 0.0,
}
DEFAULT_EFFECT_SCALING = {
    "resistance": 0.0,
    "max_suppression": 0.90,
}

REPAIR_WOUND_ENERGY = 20.0
REPAIR_HEALTH_ENERGY = 0.50

POVERTY_ENERGY_RATIO = 0.25

REST_HEALTH_PER_ACTION = 6.0
REST_FORCE_PER_ACTION = 0.04
REST_WOUND_PER_ACTION = 0.02

HELP_MIN_TRUST = 0.20
HELP_SOURCE_SHARE = 0.50
HELP_OBLIGATION_SHARE = 0.75
CREDIT_DAYS = 7
CREDIT_INTEREST = 0.10
CREDIT_SOURCE_SHARE = 0.75

NATURE_BASE_WORK = 6.0
NATURE_EFFICIENCY = 0.65
NATURE_FERTILITY_WEIGHT = 0.50
NATURE_LABOR_WEIGHT = 0.50
NATURE_WEALTH_SHARE = 1.0
NATURE_SEASON_LENGTH = 90

RESOURCE_PROJECTIONS = {
    "energy": {
        "kind": "energy",
        "role": "универсальная энергия и бюджет действий",
        "convertible": False,
    },
    "wealth": {
        "kind": "money",
        "role": "сохранённая энергия/право на неё",
        "convertible": True,
    },
    "influence": {
        "kind": "political",
        "role": "политическое право/состояние, а не E",
        "convertible": False,
    },
    "favor": {
        "kind": "political",
        "role": "связи и услуги, ближе к обязательству",
        "convertible": False,
    },
    "standing": {
        "kind": "political",
        "role": "алиас F: сила позиции",
        "convertible": False,
    },
    "evidence": {
        "kind": "information",
        "role": "сигнал/свидетельство, а не энергия",
        "convertible": False,
    },
    "information": {
        "kind": "information",
        "role": "сигнал; обработка стоит E",
        "convertible": False,
    },
}


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _config(raw, defaults):
    result = dict(defaults)
    if isinstance(raw, dict):
        for key in result:
            if key in raw:
                result[key] = _as_float(raw[key], result[key])
    return result


def conversion_quote(
    amount, form="info", *, efficiency=None, storage_share=None
):
    """Разложить оплаченную работу на доставку, потери и энтропию.

    `amount` — сколько `E` заплачено. `arrived` — работа, дошедшая до цели;
    `stored` — полезный запас получателя; `loss` — не дошло до цели;
    `entropy` — рассеялось внутри. Отчёт аддитивен:
    `loss + entropy + stored == amount`.
    """
    amount = max(0.0, _as_float(amount))
    if efficiency is None:
        efficiency = conversion_efficiency(form)
    efficiency = _clamp(efficiency)
    if storage_share is None:
        storage_share = ENERGY_STORAGE_SHARE
    storage_share = _clamp(storage_share)
    arrived = amount * efficiency
    stored = arrived * storage_share
    report = conversion_report(amount, form, stored, efficiency=efficiency)
    report["waste"] = report["loss"] + report["entropy"]
    report["form"] = str(form)
    return report


def price_for_effect(effect, form="info", *, efficiency=None):
    """Сколько `E` нужно заплатить, чтобы доставить `effect` по каналу.

    Это обратная сторона `conversion_quote`: цена растёт как
    `effect / efficiency`, поэтому плохой канал не делает работу дешёвой.
    """
    if efficiency is None:
        efficiency = conversion_efficiency(form)
    efficiency = max(1e-9, _clamp(efficiency))
    return max(0.0, _as_float(effect)) / efficiency


def conversion_chain(amount, forms):
    """Провести работу через несколько обработчиков и собрать потери.

    Каждый следующий шаг получает только `arrived` предыдущего. Цепочка
    не создаёт работу из воздуха: сумма `loss + entropy + stored` последнего
    шага плюс потери предыдущих равна исходному `amount`.
    """
    reports = []
    current = max(0.0, _as_float(amount))
    total_loss = 0.0
    total_entropy = 0.0
    for form in forms or ():
        report = conversion_quote(current, form)
        reports.append(report)
        total_loss += report["loss"]
        total_entropy += report["entropy"]
        current = report["arrived"]
    return {
        "amount": max(0.0, _as_float(amount)),
        "steps": reports,
        "final": current,
        "loss": total_loss,
        "entropy": total_entropy,
        "waste": total_loss + total_entropy,
    }


def maintenance_cost(level=0.0, force=0.0, wound=0.0, *, config=None):
    """Суточная цена поддержания в `E`.

    Чем выше уровень, сила и рана, тем дороже держать автомат в строю.
    Нулевая конфигурация сохраняет прежний баланс: поддержание — это
    явный сток, который включает контент, а не скрытый налог.
    """
    weights = _config(config, DEFAULT_MAINTENANCE)
    return max(
        0.0,
        weights["base"]
        + weights["per_level"] * max(0.0, _as_float(level))
        + weights["per_force"] * max(0.0, _as_float(force))
        + weights["per_wound"] * max(0.0, _as_float(wound)),
    )


def waste_quote(amount, form="info", *, efficiency=None):
    """Отходы одной конверсии: всё, что не стало полезным запасом."""
    report = conversion_quote(amount, form, efficiency=efficiency)
    return {
        "loss": report["loss"],
        "entropy": report["entropy"],
        "waste": report["waste"],
        "stored": report["stored"],
    }


def repair_quote(wound=0.0, health_missing=0.0, *, config=None):
    """Цена ремонта раны и недостающего здоровья в `E`.

    Ремонт — отдельный сток, а не бесплатное восстановление: он требует
    энергии и времени. `wound` — доля шкалы, `health_missing` — пункты `H`.
    """
    weights = _config(
        config,
        {
            "wound": REPAIR_WOUND_ENERGY,
            "health": REPAIR_HEALTH_ENERGY,
        },
    )
    wound = _clamp(wound)
    health_missing = max(0.0, _as_float(health_missing))
    return {
        "wound": wound,
        "health": health_missing,
        "energy": wound * weights["wound"]
        + health_missing * weights["health"],
        "wound_repaired": wound,
        "health_restored": health_missing,
    }


def scaled_cost(
    base,
    *,
    level=0.0,
    force=0.0,
    resistance=0.0,
    domain_factor=1.0,
    config=None,
):
    """Цена растёт с уровнем, силой и сопротивлением цели.

    Формула линейна и аддитивна, поэтому её легко объяснить в UI и
    откалибровать: `base · (1 + Σ weight · factor)`.
    """
    weights = _config(config, DEFAULT_COST_SCALING)
    multiplier = (
        1.0
        + weights["level"] * max(0.0, _as_float(level))
        + weights["force"] * max(0.0, _as_float(force))
        + weights["resistance"] * max(0.0, _as_float(resistance))
        + weights["domain"]
        * max(0.0, _as_float(domain_factor) - 1.0)
    )
    return max(0.0, _as_float(base) * multiplier)


def scaled_effect(
    base_effect,
    *,
    delivered=0.0,
    amount=0.0,
    resistance=0.0,
    config=None,
):
    """Эффект зависит от доставленной работы и сопротивления цели.

    `delivered / amount` — доля работы, дошедшая до обработчика;
    `resistance` подавляет эффект, но не более чем на
    `max_suppression` (по умолчанию 0.90), чтобы сопротивление не
    обнуляло любое действие.
    """
    weights = _config(config, DEFAULT_EFFECT_SCALING)
    amount = max(1e-9, _as_float(amount))
    ratio = _clamp(_as_float(delivered) / amount)
    suppression = min(
        max(0.0, weights["max_suppression"]),
        max(0.0, weights["resistance"]) * max(0.0, _as_float(resistance)),
    )
    return _as_float(base_effect) * ratio * (1.0 - suppression)


def poverty_status(
    energy,
    max_energy,
    actions_left,
    *,
    threshold=None,
):
    """Мягкий статус бедности: сигнал, а не запрет действия.

    Игрок не запирается: `END_DAY` всегда доступен, а отдых/помощь/кредит
    дают выход. Важно лишь то, что ни один клапан не делает действие
    бесплатным — каждый переносит цену во время, отношения или долг.
    """
    max_energy = max(1e-9, _as_float(max_energy))
    energy_ratio = _clamp(_as_float(energy) / max_energy)
    if threshold is None:
        threshold = POVERTY_ENERGY_RATIO
    threshold = _clamp(threshold)
    strained = energy_ratio <= threshold
    exhausted = int(actions_left) <= 0
    return {
        "energy_ratio": energy_ratio,
        "threshold": threshold,
        "deficit": max(0.0, threshold * max_energy - _as_float(energy)),
        "strained": strained,
        "exhausted": exhausted,
        "needs_relief": strained or exhausted,
        "relief": (
            ["rest", "help", "credit"]
            if (strained or exhausted)
            else []
        ),
    }


def rest_quote(actions, energy_per_action, health, max_health, wound=0.0):
    """Отдых: потратить оставшиеся действия на `H`, `F` и рану.

    Отдых не возвращает действия — он их тратит. Поэтому он не делает
    игру бесплатной: цена отдыха — время и неиспользованные возможности.
    """
    actions = max(0, int(actions))
    energy_spent = actions * max(0.0, _as_float(energy_per_action))
    wound = _clamp(wound)
    health_missing = max(0.0, _as_float(max_health) - _as_float(health))
    health_gain = min(
        health_missing,
        REST_HEALTH_PER_ACTION * actions * (1.0 - 0.5 * wound),
    )
    return {
        "actions": actions,
        "energy_spent": energy_spent,
        "health": health_gain,
        "force": REST_FORCE_PER_ACTION * actions,
        "wound": min(wound, REST_WOUND_PER_ACTION * actions),
    }


def help_quote(
    trust,
    source_wealth,
    *,
    requested=None,
    max_energy=ENERGY_SCALE,
    source_share=HELP_SOURCE_SHARE,
):
    """Помощь: источник с доверием даёт `E` в обмен на обязательство."""
    trust = _as_float(trust)
    if trust < HELP_MIN_TRUST:
        return {
            "allowed": False,
            "reason": "недостаточно доверия для помощи",
            "trust": trust,
            "amount": 0.0,
            "wealth_cost": 0.0,
            "obligation": 0.0,
        }
    wealth = max(0.0, _as_float(source_wealth))
    capacity = money_to_energy(
        wealth * _clamp(source_share),
        max_energy=max_energy,
    )
    amount = capacity if requested is None else min(
        capacity, max(0.0, _as_float(requested))
    )
    if amount <= 1e-9:
        return {
            "allowed": False,
            "reason": "у источника нет запаса",
            "trust": trust,
            "amount": 0.0,
            "wealth_cost": 0.0,
            "obligation": 0.0,
        }
    return {
        "allowed": True,
        "reason": "",
        "trust": trust,
        "amount": amount,
        "wealth_cost": energy_price_in_money(amount, max_energy=max_energy),
        "obligation": _clamp(
            amount / max(1e-9, _as_float(max_energy))
            * HELP_OBLIGATION_SHARE,
            0.01,
            1.0,
        ),
    }


def credit_quote(
    source_wealth,
    *,
    requested=None,
    max_energy=ENERGY_SCALE,
    source_share=CREDIT_SOURCE_SHARE,
    interest=CREDIT_INTEREST,
):
    """Кредит: источник даёт `E` сейчас, долг — позже с процентом."""
    wealth = max(0.0, _as_float(source_wealth))
    capacity = money_to_energy(
        wealth * _clamp(source_share),
        max_energy=max_energy,
    )
    amount = capacity if requested is None else min(
        capacity, max(0.0, _as_float(requested))
    )
    if amount <= 1e-9:
        return {
            "allowed": False,
            "reason": "у кредитора нет свободного запаса",
            "amount": 0.0,
            "wealth_cost": 0.0,
            "obligation": 0.0,
            "interest": max(0.0, _as_float(interest)),
        }
    interest = max(0.0, _as_float(interest))
    return {
        "allowed": True,
        "reason": "",
        "amount": amount,
        "wealth_cost": energy_price_in_money(amount, max_energy=max_energy),
        "obligation": _clamp(
            amount / max(1e-9, _as_float(max_energy)) * (1.0 + interest),
            0.01,
            1.0,
        ),
        "interest": interest,
    }


def resource_kind(name):
    """Вид ресурса: `energy`, `money`, `political`, `information`."""
    return (RESOURCE_PROJECTIONS.get(str(name)) or {}).get("kind", "unknown")


def resource_projection(name):
    projection = RESOURCE_PROJECTIONS.get(str(name))
    return dict(projection) if projection else {}


def money_to_energy(wealth, *, max_energy=ENERGY_SCALE, efficiency=None):
    """Деньги → `E` через рыночный обработчик, с потерей."""
    efficiency = (
        MARKET_BUY_EFFICIENCY if efficiency is None else _clamp(efficiency)
    )
    return (
        max(0.0, _as_float(wealth))
        * max(0.0, _as_float(max_energy))
        * efficiency
    )


def energy_price_in_money(energy, *, max_energy=ENERGY_SCALE, efficiency=None):
    """Сколько денег стоит покупка `energy` единиц `E`."""
    efficiency = (
        MARKET_BUY_EFFICIENCY if efficiency is None else _clamp(efficiency)
    )
    return max(0.0, _as_float(energy)) / max(
        1e-9, max(0.0, _as_float(max_energy)) * efficiency
    )


def energy_to_money(energy, *, max_energy=ENERGY_SCALE, efficiency=None):
    """`E` → деньги через продажу, с потерей."""
    efficiency = (
        MARKET_SELL_EFFICIENCY if efficiency is None else _clamp(efficiency)
    )
    return (
        max(0.0, _as_float(energy))
        / max(1e-9, max(0.0, _as_float(max_energy)))
        * efficiency
    )


def exchange_quote(source, target, amount, *, max_energy=ENERGY_SCALE):
    """Обмен ресурсов: явный обработчик или отказ.

    Прямого обмена `influence`/`favor`/`evidence` с `E` нет: это права,
    состояния и сигналы. Они меняют цену, успех или отношения, но не
    превращаются в энергию сами по себе.
    """
    source = str(source)
    target = str(target)
    amount = max(0.0, _as_float(amount))
    if source == target:
        return {
            "ok": True,
            "source": source,
            "target": target,
            "amount": amount,
            "result": amount,
            "efficiency": 1.0,
        }
    if source == "wealth" and target == "energy":
        result = money_to_energy(amount, max_energy=max_energy)
        return {
            "ok": True,
            "source": source,
            "target": target,
            "amount": amount,
            "result": result,
            "efficiency": MARKET_BUY_EFFICIENCY,
        }
    if source == "energy" and target == "wealth":
        result = energy_to_money(amount, max_energy=max_energy)
        return {
            "ok": True,
            "source": source,
            "target": target,
            "amount": amount,
            "result": result,
            "efficiency": MARKET_SELL_EFFICIENCY,
        }
    return {
        "ok": False,
        "source": source,
        "target": target,
        "amount": amount,
        "result": 0.0,
        "efficiency": 0.0,
        "reason": "нет обработчика обмена %s → %s" % (source, target),
    }


def season_multiplier(day, *, length=NATURE_SEASON_LENGTH):
    """Сезонный множитель по дню кампании (та же схема, что у арены)."""
    length = max(1, int(length))
    index = (max(0, int(day)) // length) % len(SEASONS)
    return float(SEASONS[index][1])


def season_name(day, *, length=NATURE_SEASON_LENGTH):
    length = max(1, int(length))
    index = (max(0, int(day)) // length) % len(SEASONS)
    return str(SEASONS[index][0])


def nature_yield(
    *,
    season=1.0,
    fertility=0.5,
    labor=0.0,
    damage=0.0,
    max_work=NATURE_BASE_WORK,
    efficiency=NATURE_EFFICIENCY,
):
    """Работа природы и её вклад в экономику узла.

    Природа — не-BDI автомат: у неё есть источник (сезон/плодородие),
    работа (рост/урожай), потери и сток (ущерб). Игрок может вложить
    труд (`labor`) и получить часть работы; враждебная работа (`damage`)
    уменьшает её. Возвращается та же аддитивная раскладка, что у любой
    другой работы.
    """
    base = max(0.0, _as_float(max_work))
    potential = base * max(0.0, _as_float(season)) * (
        1.0 + NATURE_FERTILITY_WEIGHT * _clamp(fertility)
    )
    labor_work = max(0.0, _as_float(labor)) * base * NATURE_LABOR_WEIGHT
    damage_work = max(0.0, _as_float(damage)) * base
    work = max(0.0, potential + labor_work - damage_work)
    report = conversion_quote(work, "force", efficiency=efficiency)
    report["season"] = max(0.0, _as_float(season))
    report["fertility"] = _clamp(fertility)
    report["labor"] = max(0.0, _as_float(labor))
    report["damage"] = max(0.0, _as_float(damage))
    report["wealth"] = (
        report["arrived"] / max(1e-9, base) * NATURE_WEALTH_SHARE
    )
    return report


def balance(sources, sinks):
    """Свести источники и стоки в одну таблицу.

    `sources`/`sinks` — словари `название → величина`. Возвращаются суммы
    и `net`; отрицательный `net` означает, что запас/поддержание уходит в
    дефицит, а не что действие стало бесплатным.
    """
    source_map = {
        str(key): _as_float(value, 0.0)
        for key, value in (sources or {}).items()
    }
    sink_map = {
        str(key): _as_float(value, 0.0)
        for key, value in (sinks or {}).items()
    }
    source_total = sum(source_map.values())
    sink_total = sum(sink_map.values())
    return {
        "sources": source_map,
        "sinks": sink_map,
        "source_total": source_total,
        "sink_total": sink_total,
        "net": source_total - sink_total,
    }


__all__ = [
    "CREDIT_DAYS",
    "CREDIT_INTEREST",
    "CREDIT_SOURCE_SHARE",
    "DEFAULT_COST_SCALING",
    "DEFAULT_EFFECT_SCALING",
    "DEFAULT_MAINTENANCE",
    "ENERGY_SCALE",
    "HELP_MIN_TRUST",
    "HELP_OBLIGATION_SHARE",
    "HELP_SOURCE_SHARE",
    "MARKET_BUY_EFFICIENCY",
    "MARKET_SELL_EFFICIENCY",
    "MAINTENANCE_STARVE_FORCE",
    "MAINTENANCE_STARVE_HEALTH",
    "NATURE_BASE_WORK",
    "NATURE_EFFICIENCY",
    "NATURE_SEASON_LENGTH",
    "NATURE_WEALTH_SHARE",
    "POVERTY_ENERGY_RATIO",
    "REPAIR_HEALTH_ENERGY",
    "REPAIR_WOUND_ENERGY",
    "RESOURCE_PROJECTIONS",
    "balance",
    "conversion_chain",
    "conversion_quote",
    "credit_quote",
    "energy_price_in_money",
    "energy_to_money",
    "exchange_quote",
    "help_quote",
    "maintenance_cost",
    "money_to_energy",
    "nature_yield",
    "poverty_status",
    "price_for_effect",
    "repair_quote",
    "resource_kind",
    "resource_projection",
    "rest_quote",
    "scaled_cost",
    "scaled_effect",
    "season_multiplier",
    "season_name",
    "waste_quote",
]
