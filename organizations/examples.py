from __future__ import annotations

from dataclasses import dataclass

from .model import Member, OrganizationSolver, Population
from .needs import NEEDS


@dataclass
class Scenario:
    slug: str
    title: str
    population: Population
    note: str = ""


def _needs(hot, base=0.2):
    values = {need: base for need in NEEDS}
    values.update(hot or {})
    return values


def _build_population(
    count, hot, complete_weight, leader_hot=None, low_every=10
):
    members = []
    leader = Member(
        id="leader",
        name="Лидер",
        needs=_needs(leader_hot if leader_hot is not None else hot),
        energy=2.0,
        force=20.0,
    )
    members.append(leader)
    for index in range(1, count):
        member_id = "m%03d" % index
        if low_every and index % low_every == 0:
            member = Member(
                id=member_id,
                name="Участник %03d" % index,
                needs={},
                energy=0.5,
                force=1.0,
            )
        else:
            member = Member(
                id=member_id,
                name="Участник %03d" % index,
                needs=_needs(hot),
                energy=1.0,
                force=1.0,
            )
        members.append(member)
    return Population.complete(members, weight=complete_weight)


def fear_state():
    return Scenario(
        slug="state_fear",
        title="Страх и большой масштаб → государство",
        population=_build_population(
            count=900,
            hot={"fear": 0.85, "anxiety": 0.70, "status": 0.50},
            leader_hot={"fear": 0.95, "status": 0.80},
            complete_weight=0.85,
        ),
    )


def spirituality_church():
    return Scenario(
        slug="church_spirituality",
        title="Духовность и большой масштаб → церковь",
        population=_build_population(
            count=900,
            hot={"spirituality": 0.90, "loneliness": 0.40},
            leader_hot={"spirituality": 1.00},
            complete_weight=0.80,
            low_every=20,
        ),
    )


def status_gang():
    return Scenario(
        slug="gang_status",
        title="Статус и малый масштаб → банда",
        population=_build_population(
            count=80,
            hot={"status": 0.90, "fear": 0.50},
            leader_hot={"status": 1.00, "fear": 0.70},
            complete_weight=0.90,
        ),
    )


def subsistence_artel():
    return Scenario(
        slug="trade_artel_hunger",
        title="Голод, жажда и малый масштаб → торговая артель",
        population=_build_population(
            count=120,
            hot={"hunger": 0.80, "thirst": 0.75, "skill": 0.60},
            leader_hot={"hunger": 0.90, "thirst": 0.85, "skill": 0.80},
            complete_weight=0.85,
        ),
    )


def get_scenarios():
    return [
        fear_state(),
        spirituality_church(),
        status_gang(),
        subsistence_artel(),
    ]


def analyze_scenario(scenario, parameters=None):
    return OrganizationSolver(parameters).analyze(scenario.population)


def analyze_all(parameters=None):
    return [
        (scenario, analyze_scenario(scenario, parameters))
        for scenario in get_scenarios()
    ]


__all__ = [
    "Scenario",
    "analyze_all",
    "analyze_scenario",
    "fear_state",
    "get_scenarios",
    "spirituality_church",
    "status_gang",
    "subsistence_artel",
]
