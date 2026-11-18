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
