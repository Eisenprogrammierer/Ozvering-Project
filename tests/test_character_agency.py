"""Автономия персонажей: личные цели, исполнители и память приказов.

Персонаж — не только вклад в вес работы лидера. У него есть собственная
цель, доверие и обида. Цель двигает выбор фракции, исполнитель влияет на
силу эффекта, а приказ оставляет след в памяти. Всё это данные
``ai_model.character_agency`` и переживает сохранение.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
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


def _goal(essence, need=""):
    return {
        "kind": "probe",
        "label": "проверить себя",
        "need": need,
        "essence": essence,
        "target_kind": "self",
        "target": "",
        "target_name": "",
        "started": 0,
        "revised": 0,
    }


def _probe_action(essence="coerce"):
    return {
        "id": "agency_probe",
        "label": "Проверка автономии",
        "target": RIVAL,
        "ai_priority": 1.0,
        "template": {"form": "coercion"},
        "hints": {"essence": essence},
        "chance": {"defense": "cohesion"},
    }


def _quiet(campaign, characters):
    for character in characters:
        character.desires = {}
        character.bdi.intentions = []
        character.campaign_agency = {
            "trust": 0.5,
            "grievance": 0.0,
            "initiative": 0.0,
            "assignments": 0,
            "orders": 0,
            "last_order": "",
            "memory": [],
        }


def test_goals_and_memory_are_initialized_from_data(campaign):
    faction = campaign.faction(SIDE)
    assert campaign.ai_model["character_agency"]["enabled"] is True
    assert faction.characters
    for character in faction.characters:
        goal = character.campaign_goal
        assert goal["kind"]
        assert goal["essence"]
        assert "trust" in character.campaign_agency
        snapshot = faction.character_snapshot(character)
        assert snapshot["goal"]["kind"] == goal["kind"]
        assert snapshot["agency"]["trust"] == pytest.approx(0.5)


def test_personal_goal_changes_action_weight(campaign):
    faction = campaign.faction(SIDE)
    others = faction.characters[1:6]
    _quiet(campaign, others)
    for character in others:
        character.campaign_goal = _goal("rest")
    member = others[0]
    baseline = campaign._ai_action_weight(SIDE, _probe_action("coerce"))

    member.campaign_goal = _goal("coerce")
    boosted = campaign._ai_action_weight(SIDE, _probe_action("coerce"))
    assert boosted > baseline

    member.campaign_goal = _goal("rest")
    assert campaign._ai_action_weight(
        SIDE, _probe_action("coerce")
    ) == pytest.approx(baseline)


def test_grievance_sabotages_the_same_work(campaign):
    faction = campaign.faction(SIDE)
    _quiet(campaign, faction.characters[1:6])
    member = faction.characters[1]
    member.campaign_goal = _goal("coerce")
    baseline = campaign._ai_action_weight(SIDE, _probe_action("coerce"))

    member.campaign_agency = {
        "trust": 0.2,
        "grievance": 0.9,
        "initiative": 0.0,
        "assignments": 0,
        "orders": 0,
        "last_order": "",
        "memory": [],
    }
    assert campaign._ai_action_weight(
        SIDE, _probe_action("coerce")
    ) < baseline


def test_executor_is_chosen_by_goal_and_organ(campaign):
    faction = campaign.faction(SIDE)
    action = faction.action("siege_operation")
    assert action is not None
    essence = campaign._action_essences(action)[0]
    model = campaign.ai_model["character_agency"]
    model["competence_weight"] = 0.0
    model["executor_organ_bonus"] = 0.0
    model["need_weight"] = 0.0
    model["intention_weight"] = 0.0
    model["target_weight"] = 0.0
    model["trust_weight"] = 0.0
    model["grievance_weight"] = 0.0
    model["initiative_weight"] = 0.0
    candidates = [
        character
        for character in faction.characters
        if not getattr(character, "campaign_is_player", False)
        and not getattr(character, "dead", False)
    ]
    _quiet(campaign, candidates)
    for character in candidates:
        character.campaign_goal = _goal("rest")
    target = candidates[-1]
    target.campaign_goal = _goal(essence)

    assert campaign._choose_executor(SIDE, action) is target


def test_order_leaves_trust_or_grievance_and_decays(campaign):
    faction = campaign.faction(SIDE)
    character = faction.characters[1]
    character.campaign_goal = _goal("seek_safety", need="fear")
    before = campaign._agency_state(character, faction)
    supported = campaign._remember_order(
        character,
        {"id": "hold", "effects": {"needs": {"fear": -0.05}}},
        faction,
    )
    assert supported["harmony"] > 0.0
    assert supported["trust"] > before["trust"]

    conflicted = campaign._remember_order(
        character,
        {"id": "expose", "effects": {"needs": {"fear": 0.08}}},
        faction,
    )
    assert conflicted["grievance"] > supported["grievance"]

    character.campaign_agency = {
        **character.campaign_agency,
        "trust": 0.9,
        "grievance": 0.8,
        "initiative": 1.0,
    }
    campaign.turn = 100
    campaign._tick_character_autonomy(faction)
    state = campaign._agency_state(character, faction)
    assert state["trust"] < 0.9
    assert state["grievance"] < 0.8
    assert state["initiative"] < 1.0


def test_process_uses_executor_and_effect_factor(campaign):
    campaign.action_process["duration_scale"] = 10.0
    action_id = campaign.available_actions(SIDE)[0]
    started = campaign.start_action(SIDE, action_id, duration=10.0)
    assert started["ok"] is True
    process = started["process"]
    assert process["executor_id"]
    assert process["executor_name"]

    campaign.advance_time(11.0)
    finished = next(
        item
        for item in campaign.processes
        if item["id"] == process["id"]
    )
    assert finished["status"] == "done"
    result = finished["result"]
    assert result["executor_id"] == process["executor_id"]
    assert 0.7 <= result["executor_factor"] <= 1.25


def test_goal_and_agency_survive_snapshot(campaign, preset):
    faction = campaign.faction(SIDE)
    character = faction.characters[1]
    character.campaign_goal = _goal("seek_status", need="status")
    character.campaign_agency = {
        "trust": 0.14,
        "grievance": 0.66,
        "initiative": 0.4,
        "assignments": 3,
        "orders": 2,
        "last_order": "hold",
        "memory": [
            {"turn": 1, "order_id": "hold", "harmony": 0.5},
        ],
    }
    snapshot = json.loads(json.dumps(campaign.save_snapshot()))
    clone = AutomataCampaign(preset, seed=11)
    clone.load_snapshot(snapshot)
    restored = clone.character(SIDE, character.campaign_id)
    assert restored is not None
    assert restored.campaign_goal["kind"] == "probe"
    assert restored.campaign_goal["essence"] == "seek_status"
    assert restored.campaign_agency["trust"] == pytest.approx(0.14)
    assert restored.campaign_agency["grievance"] == pytest.approx(0.66)
    assert restored.campaign_agency["last_order"] == "hold"
