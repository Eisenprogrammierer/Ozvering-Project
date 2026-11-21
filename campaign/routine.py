"""Суточная рутина BDI участников кампании.

Стратегическая кампания считает время сутками: один организационный такт
— один день. Тактический BDI в ``warfare`` живёт получасовыми тактами,
поэтому его темп нельзя механически растянуть на сутки: за 48 тактов
спилловер потребностей превращает любой голод в эпидемию, а мораль
падает на десятки пунктов за день.

Потребности растут в единицах ``needs_unit_seconds = 21600`` (четыре
такта BDI за сутки), а мораль считается раз в сутки
(``morale_seconds_per_unit = 86400``). Персонаж ест, пьёт, спит и
получает уход в меру снабжения и готовности организации. Рутина не
«обнуляет» желания: она подтягивает их к бытовой норме, поэтому шкалы
остаются читаемыми, а не липнут к нулю.

Модуль не трогает активы фракции. Он двигает только BDI персонажа:
потребности, мораль, силу и энергию. Активы остаются производными.
"""

from __future__ import annotations

from typing import Mapping

BDI_UNIT_SECONDS = 1800.0
"""Такт тактического BDI: базовая скорость роста потребностей."""

DEFAULTS = {
    "enabled": True,
    "day_seconds": 86400.0,
    "needs_unit_seconds": 21600.0,
    "segment_seconds": 21600.0,
    "sleep_share": 0.34,
    "sleep_needs": ["fatigue", "boredom"],
    "supply_floor": 0.25,
    "support_floor": 0.4,
    "coverage_reference": 0.72,
    "coverage_buffer": 1.08,
    "support_relief_scale": 0.22,
    "morale_stress_scale": 0.6,
    "morale_drift_scale": 0.5,
    "morale_bonus": 0.5,
    "rate": 0.35,
    "work_energy": 0.04,
    "energy_recovery": 0.9,
    "force_recovery": 0.8,
    "target_ratio": 0.7,
    "targets": {
        "hunger": 0.24,
        "thirst": 0.2,
        "fatigue": 0.18,
        "health": 0.12,
        "fear": 0.5,
        "anxiety": 0.48,
        "loneliness": 0.22,
        "boredom": 0.3,
    },
    "satisfy": [
        "hunger",
        "thirst",
        "fatigue",
        "health",
        "fear",
        "anxiety",
        "loneliness",
        "boredom",
    ],
}


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, low=0.0, high=1.0):
    value = _number(value, low)
    return max(low, min(high, value))


def _config(config):
    result = dict(DEFAULTS)
    if isinstance(config, Mapping):
        result.update(
            {
                str(key): value
                for key, value in config.items()
            }
        )
    return result


def service_level(support, supply, config=None):
    """Доля суточной нормы, которую реально закрывает организация.

    ``support`` — готовность людей (``willing_share``), ``supply`` —
    производный актив снабжения. Даже при пустых складах остаётся
    минимальный бытовой фон ``supply_floor``: люди не исчезают, но жить
    становится заметно хуже.
    """
    config = _config(config)
    supply_floor = _clamp(config.get("supply_floor", 0.25))
    support_floor = _clamp(config.get("support_floor", 0.4))
    supply_factor = supply_floor + (1.0 - supply_floor) * _clamp(supply)
    support_factor = (
        support_floor + (1.0 - support_floor) * _clamp(support)
    )
    return _clamp(support_factor * supply_factor)


def _need_definitions(character):
    bdi = getattr(character, "bdi", None)
    config = getattr(bdi, "config", None)
    definitions = getattr(config, "needs", None)
    if isinstance(definitions, Mapping):
        return definitions
    return {}


def _routine_keys(character, config):
    """Потребности, которые закрывает обычный день.

    Пустой список означает «все». По умолчанию закрываются базовые нужды:
    еда, вода, сон, здоровье, безопасность и общение. Высшие желания —
    статус, знания, творчество, мастерство — остаются мотиваторами
    действий и организации: их не выдаёт паёк.
    """
    configured = config.get("satisfy") or ()
    keys = [str(key) for key in configured]
    if not keys:
        keys = [str(key) for key in _need_definitions(character)]
    return keys


def _target_for(key, definition, config):
    """Бытовая норма потребности: ниже порога, но не ноль."""
    targets = config.get("targets") or {}
    if key in targets:
        return _clamp(targets.get(key))
    ratio = _clamp(config.get("target_ratio", 0.7))
    threshold = _clamp(getattr(definition, "threshold", 0.7))
    return _clamp(threshold * ratio)


def daily_growth(character, config=None):
    """Сколько каждая потребность прибавляет за сутки без рутины.

    Значения BDI заданы для получасового такта, поэтому для аудита они
    пересчитываются в суточные. Рутина на них не опирается напрямую: она
    тянет потребность к бытовой норме, а не к нулю.
    """
    config = _config(config)
    day = max(1.0, _number(config.get("day_seconds"), 86400.0))
    unit = max(
        1.0,
        _number(config.get("needs_unit_seconds"), 21600.0),
    )
    factor = day / unit
    result = {}
    for key, definition in _need_definitions(character).items():
        growth = _number(getattr(definition, "growth", 0.0))
        if str(key) == "boredom":
            growth += 0.003
        result[str(key)] = max(0.0, growth * factor)
    return result


def routine_effects(character, service, config=None):
    """Сколько организация закрывает за сутки при данном сервисе.

    Для каждой потребности берётся только превышение над бытовой нормой:
    сытая армия не «удовлетворяет голод до нуля», а поддерживает его на
    рабочем уровне. При плохом снабжении покрытие падает, и превышение
    над нормой растёт само.
    """
    config = _config(config)
    reference = max(1e-6, _number(config.get("coverage_reference"), 0.72))
    buffer = max(0.0, _number(config.get("coverage_buffer"), 1.08))
    coverage = max(0.0, _clamp(service) / reference * buffer)
    rate = max(0.0, _number(config.get("rate"), 0.35))
    needs = getattr(character, "needs", {}) or {}
    definitions = _need_definitions(character)
    keys = _routine_keys(character, config)
    effects = {}
    for key in keys:
        definition = definitions.get(key)
        if definition is None:
            continue
        target = _target_for(key, definition, config)
        excess = max(0.0, _number(needs.get(key), 0.0) - target)
        amount = excess * rate * coverage
        if amount > 0.0:
            effects[key] = amount
    return effects


def _state(character):
    return {
        "morale": round(_number(getattr(character, "morale", 0.0)), 6),
        "force": round(_number(getattr(character, "force", 0.0)), 6),
        "energy": round(
            _number(getattr(character, "energy_pool", 0.0)), 6
        ),
        "needs": {
            str(key): round(_number(value), 6)
            for key, value in dict(
                getattr(character, "needs", {}) or {}
            ).items()
        },
    }


def run_day(character, seconds, *, support, supply, config=None, rng=None):
    """Прожить ``seconds`` суточной рутины и вернуть срез для аудита.

    Сутки дробятся на отрезки, чтобы срабатывали пороги и спилловер BDI.
    Ночь помечается как отдых: сон ускоряет восстановление усталости и
    заживление состояний. Приём пищи и уход распределены по отрезкам
    пропорционально их длительности, поэтому потребности не прыгают от
    нуля к единице.
    """
    config = _config(config)
    if not config.get("enabled", True):
        return None
    tick = getattr(character, "tick_needs", None)
    if not callable(tick):
        return None
    day = max(1.0, _number(config.get("day_seconds"), 86400.0))
    total = max(0.0, _number(seconds))
    if total <= 0.0:
        return None
    segment = max(
        BDI_UNIT_SECONDS, _number(config.get("segment_seconds"), 21600.0)
    )
    needs_unit = max(
        BDI_UNIT_SECONDS,
        _number(config.get("needs_unit_seconds"), 21600.0),
    )
    service = service_level(support, supply, config)
    coverage = max(0.0, service) / max(
        1e-6, _number(config.get("coverage_reference"), 0.72)
    ) * max(0.0, _number(config.get("coverage_buffer"), 1.08))
    rate = max(0.0, _number(config.get("rate"), 0.35))
    definitions = _need_definitions(character)
    keys = _routine_keys(character, config)
    sleep_share = _clamp(config.get("sleep_share", 0.34))
    sleep_needs = tuple(
        str(key) for key in (config.get("sleep_needs") or ())
    ) or None
    relief = _clamp(config.get("support_relief_scale", 0.22))
    stress_scale = max(
        0.0, _number(config.get("morale_stress_scale"), 0.6)
    )
    drift_scale = max(
        0.0, _number(config.get("morale_drift_scale"), 0.5)
    )
    morale_bonus = max(0.0, _number(config.get("morale_bonus"), 0.5))
    work_energy = max(0.0, _number(config.get("work_energy"), 0.04))
    energy_recovery = max(
        0.0, _number(config.get("energy_recovery"), 0.9)
    )
    force_recovery = max(
        0.0, _number(config.get("force_recovery"), 0.8)
    )
    state = getattr(character, "state", {}) or {}
    max_force = max(
        1e-9, _number(state.get("max_force"), 1.0)
    )
    max_energy = max(
        1e-9, _number(state.get("max_energy"), 3.0)
    )
    before = _state(character)
    rested_seconds = 0.0
    simulated = 0.0
    restored = {}
    while total - simulated > 1e-9:
        if bool(getattr(character, "is_dead", False)):
            break
        chunk = min(segment, total - simulated)
        share = chunk / day
        phase = ((simulated % day) + chunk / 2.0) / day
        rested = phase >= 1.0 - sleep_share
        needs = getattr(character, "needs", {}) or {}
        chunk_effects = {}
        for key in keys:
            definition = definitions.get(key)
            if definition is None:
                continue
            target = _target_for(key, definition, config)
            excess = max(0.0, _number(needs.get(key), 0.0) - target)
            amount = excess * rate * coverage * share
            if amount > 0.0:
                chunk_effects[key] = amount
                restored[key] = restored.get(key, 0.0) + amount
        satisfy = getattr(character, "satisfy", None)
        if chunk_effects and callable(satisfy):
            satisfy(
                chunk_effects,
                morale_bonus=morale_bonus * service * share,
            )
        tick(
            seconds=chunk,
            supported=support * relief,
            rested=rested,
            resting_needs=sleep_needs,
            seconds_per_unit=needs_unit,
            morale_seconds_per_unit=day,
            morale_stress_mul=stress_scale,
            morale_drift_mul=drift_scale,
            rng=rng if rng is not None else getattr(character, "rng", None),
        )
        if work_energy and not rested:
            character.energy_pool = max(
                0.0,
                _number(getattr(character, "energy_pool", 0.0))
                - work_energy * share,
            )
        # Сон и уход возвращают силы и энергию тем быстрее, чем больше
        # запас хода и чем лучше закрыта норма. Плохое снабжение оставляет
        # людей на голодном пайке: разрыв с максимумом не сокращается.
        if force_recovery:
            force = _number(getattr(character, "force", 0.0))
            gap = max(0.0, max_force - force)
            character.force = min(
                max_force, force + force_recovery * service * gap * share
            )
        if energy_recovery and rested:
            energy = _number(getattr(character, "energy_pool", 0.0))
            gap = max(0.0, max_energy - energy)
            character.energy_pool = min(
                max_energy, energy + energy_recovery * service * gap * share
            )
        simulated += chunk
        if rested:
            rested_seconds += chunk
    return {
        "seconds": round(total, 3),
        "service": round(service, 6),
        "support": round(_clamp(support), 6),
        "supply": round(_clamp(supply), 6),
        "rate": round(rate, 6),
        "effects": {
            str(key): round(value, 6)
            for key, value in restored.items()
        },
        "rested_seconds": round(rested_seconds, 3),
        "before": before,
        "after": _state(character),
    }


__all__ = [
    "BDI_UNIT_SECONDS",
    "DEFAULTS",
    "daily_growth",
    "routine_effects",
    "run_day",
    "service_level",
]
