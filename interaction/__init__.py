"""Доменно-нейтральный фреймворк взаимодействий.

Пакет не импортирует pygame и не зависит от канона ``simulation.py`` /
``warfare.py``. Сценный слой (``ui.scenes.interaction``) — только один из
возможных рендереров модели.

Три сущности фреймворка:

* ``Target`` — с кем можно взаимодействовать;
* ``ActionSpec`` — что можно сделать с выбранным объектом;
* ``OutcomeSpec`` / ``OutcomeForecast`` — что может произойти, с шумом,
  диапазонами и вплоть до полной неизвестности.

``InteractionModel`` хранит выбор игрока, строит стабильные шумные прогнозы и
детерминированно разыгрывает фактический исход по ``seed``.
"""

from .demo import demo_model, demo_targets
from .model import (
    ActionSpec,
    InteractionModel,
    InteractionResult,
    OutcomeForecast,
    OutcomeSpec,
    Target,
)

__all__ = [
    "ActionSpec",
    "InteractionModel",
    "InteractionResult",
    "OutcomeForecast",
    "OutcomeSpec",
    "Target",
    "demo_model",
    "demo_targets",
]
