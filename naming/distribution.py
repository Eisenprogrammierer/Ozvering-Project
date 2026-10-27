from __future__ import annotations

import math
from typing import Dict, Optional

MIN_WORDS = 1
MAX_WORDS = 10
MODE_WORDS = 2
LOCATION = 1.60
SCALE = 0.75


def _logistic_pdf(value, location=LOCATION, scale=SCALE):
    z = (float(value) - float(location)) / float(scale)
    if z > 60.0:
        return 0.0
    if z < -60.0:
        return 0.0

    exp_neg = math.exp(-z)
    return exp_neg / ((1.0 + exp_neg) ** 2)


def word_count_weights(
    min_words=MIN_WORDS, max_words=MAX_WORDS, location=LOCATION, scale=SCALE
):
    low = max(1, int(min_words))
    high = min(MAX_WORDS, int(max_words))
    if high < low:
        raise ValueError("max_words должен быть не меньше min_words")
    raw = {
        count: _logistic_pdf(count, location, scale)
        for count in range(low, high + 1)
    }
    total = sum(raw.values())
    if total <= 0.0:
        raise ValueError("не удалось построить распределение длины названия")
    return {count: value / total for count, value in raw.items()}


def sample_word_count(rng, weights: Optional[Dict[int, float]] = None):
    weights = weights or word_count_weights()
    point = rng.random()
    cumulative = 0.0
    last = None
    for count in sorted(weights):
        last = count
        cumulative += weights[count]
        if point <= cumulative:
            return count
    return last if last is not None else 1


def word_count_summary(weights=None):
    weights = weights or word_count_weights()
    return {
        "min": min(weights),
        "mode": max(weights, key=lambda count: (weights[count], -count)),
        "max": max(weights),
        "p_ge_6": sum(value for count, value in weights.items() if count >= 6),
    }


__all__ = [
    "MIN_WORDS",
    "MAX_WORDS",
    "MODE_WORDS",
    "LOCATION",
    "SCALE",
    "word_count_weights",
    "sample_word_count",
    "word_count_summary",
]
