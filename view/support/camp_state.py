"""Выбор варианта утреннего лагеря по потерям дивизии.

Пороги не задаются абсолютными процентами: предел поражения меняется
вместе с сюжетом. Поэтому весь диапазон ``0..предел`` делится на три
полосы, и каждый фон ``camp_fresh`` / ``camp_wounded`` / ``camp_critical``
остаётся достижимым при любом разумном лимите.
"""

# Доли от предела поражения. При текущем лимите 25% это привычные
# границы 10% и 20%, но при лимите 20% или 45% полосы сдвигаются вместе
# с ним, а не остаются жёстко зашитыми.
CAMP_FRESH_RATIO = 0.40
CAMP_WOUNDED_RATIO = 0.80


def camp_state_for_loss(loss_percent, loss_limit_percent):
    """Вернуть ``fresh``, ``wounded`` или ``critical`` для потерь.

    ``loss_percent`` — округлённые потери дивизии в процентах,
    ``loss_limit_percent`` — порог поражения из сюжета. Если лимит
    некорректен, используется безопасное значение 1, чтобы не делить на
    ноль; для кампании это нештатная ситуация.
    """
    limit = max(1, int(loss_limit_percent))
    ratio = max(0.0, float(loss_percent)) / float(limit)
    if ratio < CAMP_FRESH_RATIO:
        return "fresh"
    if ratio <= CAMP_WOUNDED_RATIO:
        return "wounded"
    return "critical"
