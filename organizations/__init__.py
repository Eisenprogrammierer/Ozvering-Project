"""Аналитические организации-суперсистемы, runtime и генератор JSON-автоматов.

Пакет не импортирует pygame и не меняет канон ``simulation.py``/``warfare.py``.
Модель принимает население, выводит приоритетную потребность, масштаб, уровень
и экономику участия, а затем генерирует автомат для редактора ``automata/``.
``OrganizationRuntime`` опционально подключает тот же разбор к живым
персонажам ``warfare.Character``: социальный такт идёт после боя и меняет
только существующие потребности/мораль, а не добавляет метрики в ``Agent.state``.
"""

from .examples import (
    Scenario,
    analyze_all,
    analyze_scenario,
    fear_state,
    get_scenarios,
    spirituality_church,
    status_gang,
    subsistence_artel,
)
from .generator import build_automaton, save_automaton
from .model import (
    Member,
    MemberAssessment,
    OrganizationAnalysis,
    OrganizationParameters,
    OrganizationSolver,
    Population,
    level_capacity,
    organization_level,
)
from .needs import NEEDS, NEEDS_RU
from .runtime import OrganizationRuntime

__all__ = [
    "Member",
    "MemberAssessment",
    "NEEDS",
    "NEEDS_RU",
    "OrganizationAnalysis",
    "OrganizationParameters",
    "OrganizationRuntime",
    "OrganizationSolver",
    "Population",
    "Scenario",
    "analyze_all",
    "analyze_scenario",
    "build_automaton",
    "fear_state",
    "get_scenarios",
    "level_capacity",
    "organization_level",
    "save_automaton",
    "spirituality_church",
    "status_gang",
    "subsistence_artel",
]
