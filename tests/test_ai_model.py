"""ИИ кампании: BDI лидера, доктрина, органы и общий планировщик.

Веса работ не пишутся в Python: базовый ``ai_priority`` умножается на
множители из ``automata_defaults.json::ai_model``. Эти тесты проверяют,
что данные лидера и фракции действительно меняют выбор, а реальное
время занимает слоты процессами, а не мгновенными работами.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.defaults import default_dict
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
SIDE = "red"
RIVAL = "blue"


@pytest.fixture(scope="module")
def preset():
    return CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    ).generate(seed=11)


@pytest.fixture
def campaign(preset):
    return AutomataCampaign(preset, seed=11)


def _leader(campaign):
    return campaign.faction(SIDE).characters[0]


def _set_intention(campaign, target, essence):
    leader = _leader(campaign)
    leader.bdi.intentions = [
        leader.bdi.config.validate_intention(
            {"target": target, "essence": essence}
        )
    ]


def _weight(campaign, action_id):
    action = campaign.faction(SIDE).action(action_id)
    assert action is not None
    return campaign._ai_action_weight(SIDE, action)


def test_ai_model_is_loaded_from_defaults(campaign):
    defaults = default_dict("ai_model")
    assert campaign.ai_model["needs"]["weight"] == pytest.approx(
        defaults["needs"]["weight"]
    )
    assert campaign.ai_model["beliefs"]["rules"]
    assert campaign.ai_model["organs"]["repair_essences"]


def test_doctrine_reaches_runtime_from_faction_data(campaign):
    faction = campaign.faction(SIDE)
    assert faction.record["doctrine"]["forms"]["coercion"] > 0
    assert faction.record["doctrine"]["essences"]["legitimize"] > 0


def test_leader_intention_and_needs_shift_action_weights(campaign):
    leader = _leader(campaign)
    leader.needs["fear"] = 1.0
    leader.needs["knowledge"] = 0.1
    _set_intention(campaign, "faction.republic", "coerce")

    fear_weight = _weight(campaign, "siege_operation")
    knowledge_weight = _weight(campaign, "abwehr_sabotage")
    assert fear_weight > knowledge_weight

    leader.needs["fear"] = 0.1
    leader.needs["knowledge"] = 1.0
    _set_intention(campaign, "faction.republic", "analyze")

    assert _weight(campaign, "abwehr_sabotage") > _weight(
        campaign, "siege_operation"
    )


def test_leader_beliefs_boost_and_penalize_actions(campaign):
    action = campaign.faction(SIDE).action("siege_operation")
    with_beliefs = campaign._ai_action_weight(SIDE, action)

    _leader(campaign).bdi.beliefs = []
    without_beliefs = campaign._ai_action_weight(SIDE, action)
    assert without_beliefs < with_beliefs

    allied = {
        "id": "probe_ally",
        "label": "Проверить союзника",
        "target": "amber",
        "ai_priority": 1.0,
        "template": {"form": "coercion"},
        "chance": {"defense": "cohesion"},
    }
    campaign.faction(SIDE).record["assets"]["cohesion"] = 0.5
    _leader(campaign).bdi.believe(
        "faction.empire", "allied_with", "faction.corporation"
    )
    with_alliance = campaign._ai_action_weight(SIDE, allied)
    _leader(campaign).bdi.forget("faction.empire", "allied_with")
    without_alliance = campaign._ai_action_weight(SIDE, allied)
    assert with_alliance < without_alliance


def test_faction_doctrine_changes_action_weight(campaign):
    action = {
        "id": "doctrine_probe",
        "label": "Проверка доктрины",
        "target": RIVAL,
        "ai_priority": 1.0,
        "template": {"form": "coercion"},
        "chance": {"defense": "cohesion"},
    }
    faction = campaign.faction(SIDE)
    baseline = campaign._ai_action_weight(SIDE, action)
    faction.record["doctrine"]["forms"]["coercion"] = 0.9
    boosted = campaign._ai_action_weight(SIDE, action)
    assert boosted > baseline


def test_damaged_organ_lowers_weight_without_blocking_repair(campaign):
    faction = campaign.faction(SIDE)
    action = faction.action("siege_operation")
    organ = faction.organ(action["organ_id"])
    healthy = campaign._ai_action_weight(SIDE, action)
    organ.integrity = 0.1
    damaged = campaign._ai_action_weight(SIDE, action)
    assert damaged < healthy

    campaign.ai_model["organs"]["repair_essences"] = ["besiege"]
    repaired = campaign._ai_action_weight(SIDE, action)
    assert repaired > damaged


def test_auto_action_can_skip_actions_already_in_slots(campaign):
    campaign.action_process["duration_scale"] = 1000.0
    action_id = campaign.available_actions(SIDE)[0]
    assert campaign.start_action(SIDE, action_id)["ok"] is True

    weights = campaign.ai_action_weights(SIDE, exclude_active=True)
    assert action_id not in weights
    assert campaign.auto_action(SIDE, exclude_active=True) != action_id


def test_realtime_ai_occupies_slots_with_processes(campaign):
    campaign.action_process["duration_scale"] = 10000.0
    campaign.advance_time(campaign.ai_interval_seconds)

    for side, faction in campaign.factions.items():
        if side == campaign.player_side or faction.dissolved:
            continue
        active = campaign.active_processes(side)
        assert active, side
        assert all(item["status"] == "active" for item in active)
        assert campaign.slot_state(side)["used"] == len(active)
    assert not campaign.active_processes(campaign.player_side)
