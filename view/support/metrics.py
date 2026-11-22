"""Качественные описания игровых метрик для интерфейса.

Точные значения остаются в снимках, журнале кампании и debug-логах.
Игрок видит словесный уровень: это не скрывает механику, но убирает
ощущение лабораторной шкалы из политического и личного контекста.

Общие шкалы и пороги живут в :mod:`campaign.qualitative`, чтобы
интерфейс и диалоговый синтез говорили одинаково.
"""

from __future__ import annotations

from campaign.qualitative import (
    amount_phrase,
    chance_phrase,
    cost_phrase,
    delta_phrase,
    effect_phrase,
    efficiency_phrase,
    level_word,
    metric_lines,
    metric_phrase,
    metric_word,
    progress_phrase,
    relation_phrase,
    relation_word,
    share_phrase,
)

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
    "metric_word",
    "progress_phrase",
    "relation_phrase",
    "relation_word",
    "share_phrase",
]
