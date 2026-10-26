"""Системные автоматы: среда, драматург и тексты событий.

Пакет не импортирует pygame и не меняет канон ``simulation.py`` /
``warfare.py``. Он даёт два самостоятельных автомата:

* ``EnvironmentCatalog`` / ``EnvironmentRuntime`` — природные особенности
  поля боя, с которыми можно взаимодействовать как с обычными целями;
* ``Playwright`` — эпизодический соблазнитель, который оценивает
  драматические действия по неопределённости, связности, новизне и ставкам.

Третий слой — ``EventCatalog`` / ``EventTextGenerator`` — наполняет шаблоны
событий именами персонажей и организаций.
"""

from __future__ import annotations

from .core import SystemAutomaton, SystemError
from .environment import (
    EnvironmentAction,
    EnvironmentCatalog,
    EnvironmentError,
    EnvironmentFeature,
    EnvironmentInteraction,
    EnvironmentOutcome,
    EnvironmentRuntime,
    EnvironmentShift,
    EnvironmentState,
    EnvironmentTransition,
    default_catalog as default_environment,
)
from .events import (
    EventCatalog,
    EventError,
    EventTemplate,
    EventTextGenerator,
    GameEvent,
    default_catalog as default_events,
)
from .playwright import (
    DramaActor,
    DramaPush,
    DramaScore,
    DramaticAction,
    DramaticTemplate,
    Playwright,
    PlaywrightConfig,
    PlaywrightError,
    default_config as default_playwright,
)

__all__ = [
    "SystemAutomaton", "SystemError",
    "EnvironmentAction", "EnvironmentCatalog", "EnvironmentError",
    "EnvironmentFeature", "EnvironmentInteraction", "EnvironmentOutcome",
    "EnvironmentRuntime", "EnvironmentShift", "EnvironmentState",
    "EnvironmentTransition", "default_environment",
    "EventCatalog", "EventError", "EventTemplate", "EventTextGenerator",
    "GameEvent", "default_events",
    "DramaActor", "DramaPush", "DramaScore", "DramaticAction",
    "DramaticTemplate", "Playwright", "PlaywrightConfig", "PlaywrightError",
    "default_playwright",
]
