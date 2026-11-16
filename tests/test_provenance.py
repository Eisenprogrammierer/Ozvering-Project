"""Тесты провенанса: факт, память диалога, BDI и эффекты."""

from __future__ import annotations

from pathlib import Path

import pytest

import bdi
from campaign.automata import AutomataCampaign
from campaign.dialogue.knowledge import Fact
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.state import DialogueMemory
from campaign.effects import apply_effects
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


def _campaign(seed=7) -> AutomataCampaign:
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=seed), seed=seed)


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DEFAULT_DIR)


def test_fact_key_ignores_provenance():
    first = Fact("at_war_with", ("faction:red", "faction:blue"))
    second = Fact(
        "at_war_with",
        ("faction:red", "faction:blue"),
        source="hearing",
        channel="hearing",
        speaker="char:1",
        truth="false",
    )
    assert first.key() == second.key()
    assert first.group == "content"
    assert second.group == "said"
    assert second.attribution == "мне сказали"


def test_fact_groups_and_attribution():
    seen = Fact("rel", ("a",), channel="sight")
    read = Fact("rel", ("a",), channel="reading")
    believed = Fact("rel", ("a",), channel="memory")
    lied = Fact("rel", ("a",), truth="false", channel="hearing")
    assert seen.group == "perceived"
    assert seen.attribution == "я видел"
    assert read.attribution == "я прочитал"
    assert believed.group == "believed"
    assert believed.attribution == "я так считаю"
    assert lied.group == "said"


def test_memory_persists_provenance(catalog):
    memory = DialogueMemory(catalog.state, run_id="run", clock=2)
    memory.note_fact(
        "recent_work",
        ("faction:blue", "3", "акт"),
        2,
        {"faction:blue"},
        source="char_red_003",
        channel="hearing",
        speaker="char_red_003",
        confidence=0.6,
        truth="false",
    )
    record = memory.facts["recent_work|faction:blue|3|акт"]
    assert record["source"] == "char_red_003"
    assert record["channel"] == "hearing"
    assert record["speaker"] == "char_red_003"
    assert record["confidence"] == 0.6
    assert record["truth"] == "false"

    restored = DialogueMemory.from_dict(catalog.state, memory.to_dict())
    assert restored.to_dict() == memory.to_dict()
    same = restored.facts["recent_work|faction:blue|3|акт"]
    assert same["speaker"] == "char_red_003"
    assert same["truth"] == "false"


def test_old_memory_record_gets_defaults(catalog):
    restored = DialogueMemory.from_dict(
        catalog.state,
        {
            "facts": {
                "at_war_with|faction:red|faction:blue": {
                    "key": "at_war_with|faction:red|faction:blue",
                    "rel": "at_war_with",
                    "args": ["faction:red", "faction:blue"],
                    "weight": 1.0,
                }
            }
        },
    )
    record = restored.facts["at_war_with|faction:red|faction:blue"]
    assert record["source"] == "dialogue"
    assert record["channel"] == "memory"
    assert record["confidence"] == 1.0
    assert record["truth"] == "true"


def test_belief_source_defaults_to_content():
    config = bdi.load_bdi()
    belief = config.validate_belief(
        {"subject": "faction:red", "predicate": "is_legitimate"}
    )
    assert belief.source == "content"
    explicit = config.validate_belief(
        {
            "subject": "faction:red",
            "predicate": "is_legitimate",
            "source": "rumor",
        }
    )
    assert explicit.source == "rumor"


def test_preset_beliefs_have_source():
    campaign = _campaign()
    for faction in campaign.factions.values():
        for character in faction.characters:
            for belief in character.bdi.beliefs:
                assert belief.source


def test_effects_marks_belief_source():
    campaign = _campaign()
    actor = campaign.faction("red")
    leader = actor.characters[0]
    leader.bdi.beliefs = []
    apply_effects(
        actor,
        {
            "self": {
                "beliefs": {
                    "add": [{"predicate": "is_legitimate"}]
                }
            }
        },
    )
    belief = next(
        item
        for item in leader.bdi.beliefs
        if item.predicate == "is_legitimate"
    )
    assert belief.source == "effect"
