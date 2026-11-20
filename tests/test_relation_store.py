"""Отношения кампании: хранилище, эффекты, условия и работы (G-11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.conditions import check_conditions
from campaign.effects import apply_effects
from campaign.preset import CampaignPresetGenerator
from campaign.relations import (
    RELATION_EFFECT_LIMIT,
    RelationStore,
    relation_effect,
)
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
SIDE = "red"
RIVAL = "blue"


class FakeFaction:
    def __init__(self, faction_id="actor"):
        self.id = faction_id
        self.relations = RelationStore.from_config(
            {
                "axes": ["affinity", "trust", "fear", "respect"],
                "forms": {"information": "info", "coercion": "force"},
            }
        )


@pytest.fixture(scope="module")
def preset():
    return CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    ).generate(seed=11)


@pytest.fixture
def campaign(preset):
    return AutomataCampaign(preset, seed=11)


def test_store_keeps_directions_and_clamps_values():
    store = RelationStore()
    changes = store.add("red", "blue", {"trust": 0.4, "fear": -0.2})
    assert changes == pytest.approx({"trust": 0.4, "fear": -0.2})
    assert store.value("red", "blue", "trust") == pytest.approx(0.4)
    assert store.value("blue", "red", "trust") == pytest.approx(0.0)

    store.add("red", "blue", {"trust": 2.0})
    assert store.value("red", "blue", "trust") == pytest.approx(1.0)
    store.set("blue", "red", {"respect": -3.0})
    assert store.value("blue", "red", "respect") == pytest.approx(-1.0)


def test_store_config_maps_forms_and_computes_effect():
    store = RelationStore.from_config(
        {
            "axes": ["trust", "fear"],
            "forms": {"information": "info"},
            "effect_weights": {"info": {"trust": 0.2}},
            "effect_limit": 0.1,
        }
    )
    store.add("red", "blue", {"trust": 0.8})
    assert store.form_for("information") == "info"
    assert store.effect("red", "blue", "information") == pytest.approx(
        0.1
    )
    assert store.effect("red", "blue", "unknown") == 0.0
    assert relation_effect({"trust": 1.0}, "info") > 0.0


def test_effects_write_relations_and_conditions_read_them():
    faction = FakeFaction("faction_empire")
    applied = apply_effects(
        faction,
        {"relations": {"faction_republic": {"trust": 0.3}}},
    )
    assert applied["relations"][0]["source"] == "faction_empire"
    assert applied["relations"][0]["target"] == "faction_republic"
    assert faction.relations.value(
        "faction_empire", "faction_republic", "trust"
    ) == pytest.approx(0.3)

    reason = check_conditions(
        [
            {
                "kind": "relation",
                "key": "faction_republic",
                "axis": "trust",
                "op": ">=",
                "value": 0.3,
            }
        ],
        {"faction": faction, "relation_store": faction.relations},
    )
    assert reason == ""
    reason = check_conditions(
        [
            {
                "kind": "relation",
                "key": "faction_republic",
                "axis": "fear",
                "op": ">=",
                "value": 0.3,
            }
        ],
        {"faction": faction, "relation_store": faction.relations},
    )
    assert "отношение" in reason


def test_work_chance_and_ai_weight_use_target_relation(campaign):
    actor = campaign.faction(SIDE)
    target = campaign.faction(RIVAL)
    action = next(
        item
        for item in actor.actions
        if item.get("id") == "imperial_edict"
    )
    side = campaign._target_side(SIDE, action)
    target_faction = campaign.faction(side)

    base = campaign._resolve_action(
        actor,
        action,
        "imperial_edict",
        side,
        target_faction,
        charge_cost=False,
    )
    campaign.relations.set(
        target_faction.id,
        actor.id,
        {"trust": 1.0, "affinity": 0.5},
    )
    boosted = campaign._resolve_action(
        actor,
        action,
        "imperial_edict",
        side,
        target_faction,
        charge_cost=False,
    )
    weight_before = campaign._ai_action_weight(SIDE, action)
    campaign.relations.set(
        target_faction.id,
        actor.id,
        {"trust": -1.0, "fear": -1.0},
    )
    weight_after = campaign._ai_action_weight(SIDE, action)

    assert boosted["relation_shift"] > 0.0
    assert boosted["relation_shift"] <= RELATION_EFFECT_LIMIT
    assert boosted["chance"] > base["chance"]
    assert weight_before > weight_after


def test_character_interaction_writes_character_to_faction(campaign):
    faction = campaign.faction(SIDE)
    character = faction.characters[1]
    started = campaign.perform_character_interaction(
        SIDE, character.campaign_id, "promote"
    )
    assert started["ok"]
    assert started.get("started")
    campaign.advance_time(started["duration"] + 1)
    result = campaign.last_character_result
    assert result["ok"]
    assert result["relations"]
    trust = campaign.relations.value(
        character.campaign_id, faction.id, "trust"
    )
    assert trust > 0.0
    view = campaign.relation_view(character.campaign_id)
    assert view["matrix"][faction.id]["trust"] == pytest.approx(trust)


def test_snapshot_roundtrip_keeps_relations(preset, campaign):
    campaign.relations.add(
        "faction_empire", "faction_republic", {"fear": 0.4, "trust": -0.2}
    )
    restored = AutomataCampaign(
        preset, snapshot=campaign.save_snapshot()
    )
    assert restored.relations.value(
        "faction_empire", "faction_republic", "fear"
    ) == pytest.approx(0.4)
    assert restored.relations.value(
        "faction_empire", "faction_republic", "trust"
    ) == pytest.approx(-0.2)
    assert restored.faction(SIDE).relations is restored.relations
    assert restored.snapshot()["relations"] == campaign.snapshot()[
        "relations"
    ]
