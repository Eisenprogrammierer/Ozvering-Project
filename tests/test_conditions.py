"""Контракт единого движка условий.

Условия — читающая часть ядра: они не меняют состояние, а только отвечают,
доступно ли действие. Тесты держат старый формат активов и типизированные
клаузы (потребности, черты, убеждения, органы, флаги, история).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.conditions import asset_reason, check_conditions, compare
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]


def _campaign(seed=7):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    )
    return AutomataCampaign(generator.generate(seed=seed))


def _context(campaign):
    faction = campaign.faction("red")
    return campaign._condition_context(faction, campaign.faction("blue"))


def test_compare_operations():
    assert compare(0.5, ">=", 0.5)
    assert compare(0.5, "<=", 0.5)
    assert not compare(0.5, ">", 0.5)
    assert compare("worker", "in", ("worker", "peasant"))
    assert compare("noble", "not in", ("worker", "peasant"))
    assert not compare(0.1, "==", 0.2)


def test_legacy_asset_requirements_keep_formatting():
    reason = asset_reason(
        "нужно",
        {"legitimacy": 0.3},
        {"legitimacy": {"min": 0.5}},
        {"legitimacy": "законность"},
    )
    assert reason == "нужно: законность ≥ 0.50"
    strict = asset_reason(
        "цель",
        {"cohesion": 0.5},
        {"cohesion": {"gt": 0.5}},
        {"cohesion": "сплочённость"},
    )
    assert strict == "цель: сплочённость > 0.50"


def test_typed_conditions_read_state_without_writing_it():
    campaign = _campaign()
    context = _context(campaign)
    character = context["character"]
    faction = context["faction"]
    character.needs["fear"] = 0.8
    character.personality.values["loyalty"] = 0.2
    character.bdi.believe(
        character.campaign_id, "is_legitimate", value=0.7
    )
    faction.flags["amnesty_offered"] = True
    organ = faction.organs[0]
    organ.integrity = 0.9

    assert check_conditions(
        [
            {"kind": "need", "key": "fear", "op": ">=", "value": 0.7},
            {
                "kind": "trait",
                "key": "loyalty",
                "op": "<=",
                "value": 0.3,
            },
            {"kind": "belief", "predicate": "is_legitimate"},
            {
                "kind": "belief",
                "predicate": "is_legitimate",
                "op": ">=",
                "value": 0.6,
            },
            {
                "kind": "organ",
                "id": organ.id,
                "op": ">=",
                "value": 0.8,
            },
            {"kind": "flag", "key": "amnesty_offered"},
        ],
        context,
    ) == ""

    assert check_conditions(
        [{"kind": "need", "key": "fear", "op": "<", "value": 0.2}],
        context,
    )


def test_groups_any_all_and_not():
    context = {"turn": 3}
    assert check_conditions(
        {
            "any": [
                {"kind": "turn", "op": ">=", "value": 10},
                {"kind": "turn", "op": ">=", "value": 2},
            ]
        },
        context,
    ) == ""
    assert (
        check_conditions(
            {
                "all": [
                    {"kind": "turn", "op": ">=", "value": 10},
                    {"kind": "turn", "op": ">=", "value": 2},
                ]
            },
            context,
        )
        != ""
    )
    assert (
        check_conditions(
            {"not": {"kind": "turn", "op": ">=", "value": 2}}, context
        )
        != ""
    )


def test_action_requirements_accept_when_clause():
    campaign = _campaign()
    faction = campaign.faction("red")
    leader = faction.characters[0]
    leader.needs["fear"] = 0.9
    action = {
        "id": "probe",
        "requires": {
            "when": [
                {"kind": "need", "key": "fear", "op": ">=", "value": 0.5}
            ]
        },
    }
    assert campaign._action_requirement_reason(faction, action) == ""
    leader.needs["fear"] = 0.1
    assert (
        "нужно: fear"
        in campaign._action_requirement_reason(faction, action)
    )


def test_unknown_condition_kind_is_loud():
    assert "неизвестное условие" in check_conditions(
        [{"kind": "whatever"}], {}
    )


def test_checks_do_not_mutate_state():
    campaign = _campaign()
    context = _context(campaign)
    character = context["character"]
    before_needs = dict(character.needs)
    before_beliefs = list(character.bdi.beliefs)
    check_conditions(
        [
            {"kind": "need", "key": "fear", "op": ">=", "value": 0.5},
            {"kind": "belief", "predicate": "is_legitimate"},
        ],
        context,
    )
    assert character.needs == before_needs
    assert character.bdi.beliefs == before_beliefs
