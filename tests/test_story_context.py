"""Слой отражения видит фракцию целиком, а не только лидера (G-08).

Событие ничего не записывает: тесты проверяют чтение активов, органов,
флагов, ростера, намерений и отношений, а также подстановку реальных
имён вместо случайных.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog
from systems.events import EventCatalog, EventEngine

ROOT = Path(__file__).resolve().parents[1]
SIDE = "red"


@pytest.fixture(scope="module")
def campaign():
    preset = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    ).generate(seed=11)
    return AutomataCampaign(preset, seed=11)


def _small_catalog(conditions):
    return EventCatalog.from_data(
        {
            "schema": 1,
            "categories": {"report": {"label": "донесение", "weight": 1.0}},
            "events": [
                {
                    "id": "faction_report",
                    "category": "report",
                    "title": "Донесение",
                    "templates": ["{actor}, {target} и {organization}"],
                    "probability": 1.0,
                    "speed": 0.0,
                    "duration": 1.0,
                    "conditions": conditions,
                }
            ],
        }
    )


def test_story_context_exposes_assets_organs_flags_and_roster(campaign):
    faction = campaign.faction(SIDE)
    context = campaign._story_context()

    assert context["assets"] == {
        str(key): pytest.approx(float(value))
        for key, value in faction.assets.items()
    }
    assert context["organs"] == {
        str(organ.id): pytest.approx(organ.integrity)
        for organ in faction.organs
    }
    assert context["organ_statuses"] == {
        str(organ.id): organ.status() for organ in faction.organs
    }
    assert context["organ_scales"] == {
        str(organ.id): dict(organ.scales) for organ in faction.organs
    }
    assert context["flags"] == faction.flags
    assert context["organization_state"]["name"]
    assert context["turn"] == campaign.turn
    assert context["used_actions"] == []


def test_story_context_exposes_leader_bdi_and_relations(campaign):
    leader = campaign.faction(SIDE).characters[0]
    context = campaign._story_context()

    assert context["intentions"] == [
        item.as_dict() for item in leader.bdi.intentions
    ]
    assert context["characters"][leader.campaign_id]["name"] == leader.name
    assert context["characters"][leader.campaign_id]["needs"] == leader.needs
    assert "faction.republic" in context["relations"]
    assert "considers_illegitimate" in context["relations"]["faction.republic"]


def test_story_context_uses_real_names_for_slots(campaign):
    leader = campaign.faction(SIDE).characters[0]
    context = campaign._story_context()

    assert context["actor"] == leader.name
    assert context["organization"] == campaign.faction(SIDE).name
    assert context["target"]
    assert context["target"] != context["actor"]
    assert context["rival"]


def test_story_event_reads_assets_and_renders_real_names(campaign):
    campaign.story_engine = EventEngine(
        catalog=_small_catalog(
            [
                {
                    "kind": "asset",
                    "key": "legitimacy",
                    "op": ">=",
                    "value": 0.5,
                }
            ]
        ),
        seed=5,
    )
    campaign._story_progress = 0.0
    spawned = campaign._advance_story_events(
        campaign.organization_interval_seconds
    )

    assert spawned
    leader = campaign.faction(SIDE).characters[0]
    entry = spawned[0]
    assert leader.name in entry["text"]
    assert campaign.faction(SIDE).name in entry["text"]
    assert entry["effects"] == {}


def test_story_event_is_filtered_by_unmet_asset_condition(campaign):
    campaign.story_engine = EventEngine(
        catalog=_small_catalog(
            [
                {
                    "kind": "asset",
                    "key": "legitimacy",
                    "op": ">=",
                    "value": 1.5,
                }
            ]
        ),
        seed=5,
    )
    campaign._story_progress = 0.0
    assert (
        campaign._advance_story_events(
            campaign.organization_interval_seconds
        )
        == []
    )


def test_story_context_prefers_alive_opposite_gender_pair(campaign):
    faction = campaign.faction(SIDE)
    for index, character in enumerate(faction.characters):
        character.campaign_gender = "f" if index == 0 else "m"
    context = campaign._story_context()

    assert context["actor_alive"] is True
    assert context["target_alive"] is True
    assert context["pair_alive"] is True
    assert context["pair_same_faction"] is True
    assert context["opposite_gender"] is True
    assert context["target"] != context["actor"]
    assert context["has_dead"] is False


def test_story_context_reports_fallen_and_skips_dead_in_pair(campaign):
    faction = campaign.faction(SIDE)
    fallen = faction.characters[1]
    original_force = fallen.force
    fallen.force = 0.0
    try:
        context = campaign._story_context()
        assert context["has_dead"] is True
        assert context["fallen"] == fallen.name
        assert context["actor"] != fallen.name
        assert context["target"] != fallen.name
        assert context["pair_alive"] is True
    finally:
        fallen.force = original_force


def test_life_events_require_logical_pairs_and_real_death():
    catalog = EventCatalog.load(ROOT / "configs" / "systems")
    living_pair = {
        "actor": "Анна",
        "target": "Борис",
        "fallen": "",
        "actor_alive": True,
        "target_alive": True,
        "pair_alive": True,
        "actor_gender": "f",
        "target_gender": "m",
        "opposite_gender": True,
        "pair_same_faction": True,
        "has_dead": False,
    }
    same_gender = dict(living_pair, target_gender="f", opposite_gender=False)
    with_fallen = dict(living_pair, has_dead=True, fallen="Борис")

    assert catalog.event("birth_child").matches(living_pair) is True
    assert catalog.event("birth_child").matches(same_gender) is False
    assert catalog.event("marriage").matches(living_pair) is True
    assert catalog.event("marriage").matches(same_gender) is False
    assert catalog.event("parenthood").matches(living_pair) is True
    assert catalog.event("death").matches(living_pair) is False
    assert catalog.event("death").matches(with_fallen) is True
    assert catalog.event("funeral").matches(with_fallen) is True
    assert catalog.event("succession").matches(with_fallen) is True
