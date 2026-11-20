"""Качественные описания игровых метрик для интерфейса.

Точные значения остаются в снимках, журнале кампании и debug-логах.
Игрок видит словесный уровень: это не скрывает механику, но убирает
ощущение лабораторной шкалы из политического и личного контекста.
"""

from __future__ import annotations

LEVEL_WORDS = {
    0: "почти отсутствует",
    1: ("низкий", "низкая", "низкое"),
    2: ("умеренный", "умеренная", "умеренное"),
    3: ("высокий", "высокая", "высокое"),
    4: ("очень высокий", "очень высокая", "очень высокое"),
}

_MASCULINE = (
    "страх",
    "голод",
    "статус",
    "навык",
    "смысл",
    "обмен",
    "объём",
    "кпд",
    "успех",
    "риск",
    "запас",
)
_FEMININE_ENDINGS = ("ость", "есть", "ция", "а", "я", "ь")
_NEUTER_ENDINGS = ("ие", "ье", "о", "е")


def _clamp(value, low=0.0, high=1.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


def _ratio(value, low=0.0, high=1.0):
    if high <= low:
        return 0.0
    return _clamp((float(value) - low) / (high - low))


def _level(value, low=0.0, high=1.0):
    ratio = _ratio(value, low, high)
    if ratio < 0.12:
        return 0
    if ratio < 0.32:
        return 1
    if ratio < 0.58:
        return 2
    if ratio < 0.82:
        return 3
    return 4


def _gender(label):
    text = str(label or "").strip().lower()
    if text in _MASCULINE:
        return 0
    if text.endswith(_FEMININE_ENDINGS):
        return 1
    if text.endswith(_NEUTER_ENDINGS):
        return 2
    return 0


def level_word(value, low=0.0, high=1.0):
    """Словесный уровень без числа."""
    rank = _level(value, low, high)
    if rank == 0:
        return LEVEL_WORDS[0]
    return LEVEL_WORDS[rank]


def metric_phrase(label, value, low=0.0, high=1.0):
    """``законность: высокая`` вместо ``законность 0.72``."""
    rank = _level(value, low, high)
    if rank == 0:
        return "%s: %s" % (label, LEVEL_WORDS[0])
    word = LEVEL_WORDS[rank][_gender(label)]
    return "%s: %s" % (label, word)


def relation_phrase(label, value):
    """Отношение от ``-1`` до ``1`` в словесной шкале."""
    return metric_phrase(label, _clamp(value, -1.0, 1.0), -1.0, 1.0)


def _past(gender, rise):
    if rise:
        return ("вырос", "выросла", "выросло")[gender]
    return ("снизился", "снизилась", "снизилось")[gender]


def delta_phrase(label, before, after, scale=1.0):
    """Направление изменения: ``мораль заметно выросла``."""
    try:
        delta = float(after) - float(before)
    except (TypeError, ValueError):
        return "%s: без изменений" % label
    step = abs(delta) / max(1e-9, float(scale))
    if step < 0.01:
        return "%s: без изменений" % label
    gender = _gender(label)
    if step < 0.08:
        adverb = "слегка"
    elif step < 0.25:
        adverb = "заметно"
    else:
        adverb = "сильно"
    return "%s %s %s" % (label, adverb, _past(gender, delta > 0.0))


def effect_phrase(label, value):
    """Ожидаемый эффект: ``влияние заметно растёт``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "%s меняется" % label
    magnitude = abs(number)
    if magnitude < 1e-6:
        return "%s без изменений" % label
    if magnitude < 0.03:
        adverb = "едва"
    elif magnitude < 0.10:
        adverb = "слегка"
    elif magnitude < 0.25:
        adverb = "заметно"
    else:
        adverb = "сильно"
    verb = "растёт" if number > 0.0 else "снижается"
    return "%s %s %s" % (label, adverb, verb)


def cost_phrase(label, value):
    """Цена без точной дроби: ``влияние: умеренно``."""
    magnitude = abs(float(value or 0.0))
    if magnitude < 0.03:
        word = "почти ничего"
    elif magnitude < 0.10:
        word = "немного"
    elif magnitude < 0.25:
        word = "умеренно"
    else:
        word = "много"
    return "%s: %s" % (label, word)


def chance_phrase(value):
    """Вероятность успеха словами."""
    ratio = _clamp(value)
    if ratio < 0.20:
        return "маловероятно"
    if ratio < 0.45:
        return "скорее маловероятно"
    if ratio < 0.60:
        return "возможно"
    if ratio < 0.80:
        return "вероятно"
    return "почти наверняка"


def efficiency_phrase(value):
    return metric_phrase("КПД", value)


def amount_phrase(value):
    """Объём работы без абсолютного числа."""
    ratio = _clamp(value)
    if ratio < 0.06:
        return "небольшой"
    if ratio < 0.18:
        return "заметный"
    if ratio < 0.45:
        return "существенный"
    return "масштабный"


def progress_phrase(value):
    ratio = _clamp(value)
    if ratio < 0.10:
        return "только начата"
    if ratio < 0.45:
        return "идёт"
    if ratio < 0.80:
        return "близка к завершению"
    return "почти завершена"


def share_phrase(value):
    ratio = _clamp(value)
    if ratio < 0.10:
        return "единицы"
    if ratio < 0.35:
        return "меньшинство"
    if ratio < 0.60:
        return "примерно половина"
    if ratio < 0.85:
        return "большинство"
    return "почти все"


def metric_lines(values, labels=None, limit=None):
    """Список фраз для словаря метрик, без чисел."""
    labels = labels or {}
    items = list((values or {}).items())
    if limit is not None:
        items = items[:limit]
    return [
        metric_phrase(labels.get(key, key), value)
        for key, value in items
    ]


__all__ = [
    "amount_phrase",
    "chance_phrase",
    "cost_phrase",
    "delta_phrase",
    "effect_phrase",
    "efficiency_phrase",
    "level_word",
    "metric_lines",
    "metric_phrase",
    "progress_phrase",
    "relation_phrase",
    "share_phrase",
]
