"""Тесты D7.1: речевые действия как действия кампании.

Проверяют, что ``social.json`` связывает акт с взаимодействием
кампании, ``SocialEngine`` проверяет ``has_authority``/``trusts``,
``ActionBridge`` применяет взаимодействие только при
``allow_actions=True``, а ``TextGame`` направляет social-фразы в
``act`` вместо read-only ответа.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import DialogueSession, TextGame, build_knowledge
from campaign.dialogue.lint import lint_catalog
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"

COMMAND = "Приказываю атаку."
PROMISE = "Обещаю сделку."
THREAT = "Угрожаю Республике."
OFFER = "Предлагаю переговоры."
APOLOGY = "Сожалею о войне."


def _campaign() -> AutomataCampaign:
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


def _session(
    catalog,
    campaign,
    character_id="",
    side="red",
    allow_actions=True,
) -> DialogueSession:
    if not character_id:
        character_id = (
            "char_red_002" if side == "red" else None
        )
    knowledge = build_knowledge(catalog, campaign, side, character_id)
    return DialogueSession(
        catalog,
        knowledge,
        style_id="neutral",
        allow_actions=allow_actions,
        campaign=campaign,
    )


@pytest.fixture
def catalog():
    return load_dialogue(DEFAULT_DIR)


# --- данные и линт ---------------------------------------------------


def test_social_acts_bind_campaign_interactions(catalog):
    expected = {
        "command": "social_command",
        "promise": "social_promise",
        "threat": "social_threat",
        "offer": "social_offer",
        "apology": "social_apology",
    }
    actual = {
        key: act.interaction for key, act in catalog.social.acts.items()
    }
    assert actual == expected
    assert lint_catalog(catalog) == []


def test_campaign_configs_have_social_interactions():
    paths = (
        ROOT / "configs" / "campaigns" / "base" / "automata_defaults.json",
        ROOT / "configs" / "campaigns" / "base" / "lore_factions.json",
    )
    expected = {
        "social_command",
        "social_promise",
        "social_threat",
        "social_offer",
        "social_apology",
    }
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = {
            item.get("id")
            for item in data.get("character_interactions") or ()
        }
        assert expected <= ids, path


def test_trusts_fact_derived_for_own_faction(catalog):
    campaign = _campaign()
    knowledge = build_knowledge(catalog, campaign, "red", "char_red_002")
    facts = [fact.args for fact in knowledge.facts_for("trusts")]
    assert ("char_red_001", "char_red_002") in facts


def test_lint_rejects_bad_interaction_id(tmp_path, catalog):
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    path = target / "social.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["acts"]["command"]["interaction"] = "Social Command"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    problems = lint_catalog(load_dialogue(target))
    assert any("social.acts.command.interaction" in item for item in problems)


# --- мост и сессия ---------------------------------------------------


def test_command_performs_campaign_interaction(catalog):
    campaign = _campaign()
    session = _session(catalog, campaign)
    result = session.act(COMMAND)
    assert result.ok is True
    assert result.performed is True
    assert result.action_id == "social_command"
    assert result.result["interaction_id"] == "social_command"
    assert result.result["social"]["reaction_id"] == "accept"
    assert campaign.actions_left == campaign.actions_per_turn - 1
    assert any(
        event.get("kind") == "character"
        and event.get("character_id") == "char_red_002"
        for event in campaign.events
    )
    assert session.state.commitments
    assert session.state.commitments[-1]["object"] == "concept:attack"


def test_command_rejected_without_authority(catalog):
    campaign = _campaign()
    before = campaign.snapshot()
    session = _session(catalog, campaign, side="blue")
    result = session.act(COMMAND)
    assert result.ok is False
    assert result.performed is False
    assert result.reason == "has_authority"
    assert campaign.snapshot() == before
    assert session.state.commitments == []


def test_promise_requires_trust(catalog):
    campaign = _campaign()
    session = _session(catalog, campaign)
    result = session.act(PROMISE)
    assert result.performed is True
    assert result.result["social"]["reaction_id"] == "accept"

    other = _campaign()
    hostile = _session(catalog, other, side="blue")
    before = other.snapshot()
    rejected = hostile.act(PROMISE)
    assert rejected.performed is False
    assert rejected.reason == "trusts"
    assert other.snapshot() == before


def test_threat_performs_even_when_listener_rejects(catalog):
    campaign = _campaign()
    session = _session(catalog, campaign)
    result = session.act(THREAT)
    assert result.performed is True
    assert result.result["social"]["reaction_id"] == "reject"
    assert result.result["social"]["admissible"] is True
    assert session.state.commitments[-1]["kind"] == "refusal"


@pytest.mark.parametrize(
    "phrase, interaction",
    [
        (COMMAND, "social_command"),
        (PROMISE, "social_promise"),
        (THREAT, "social_threat"),
        (OFFER, "social_offer"),
        (APOLOGY, "social_apology"),
    ],
)
def test_each_act_reaches_its_interaction(catalog, phrase, interaction):
    campaign = _campaign()
    result = _session(catalog, campaign).act(phrase)
    assert result.performed is True
    assert result.action_id == interaction
    assert result.result["social"]["interaction_id"] == interaction


def test_actions_disabled_keeps_world_unchanged(catalog):
    campaign = _campaign()
    before = campaign.snapshot()
    session = _session(catalog, campaign, allow_actions=False)
    result = session.act(COMMAND)
    assert result.performed is False
    assert result.reason == "actions_disabled"
    assert campaign.snapshot() == before


def test_social_requires_campaign(catalog):
    campaign = _campaign()
    knowledge = build_knowledge(
        catalog, campaign, "red", "char_red_002"
    )
    session = DialogueSession(
        catalog,
        knowledge,
        style_id="neutral",
        allow_actions=True,
    )
    result = session.act(COMMAND)
    assert result.performed is False
    assert result.reason == "no_campaign"


def test_missing_interaction_is_loud(tmp_path, catalog):
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    path = target / "social.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["acts"]["command"]["interaction"]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    local = load_dialogue(target)
    campaign = _campaign()
    before = campaign.snapshot()
    result = _session(local, campaign).act(COMMAND)
    assert result.performed is False
    assert result.reason == "no_interaction"
    assert campaign.snapshot() == before


# --- текстовый интерфейс --------------------------------------------


def test_text_game_routes_social_to_action(catalog):
    campaign = _campaign()
    game = TextGame(_session(catalog, campaign))
    entry = game.submit(COMMAND)
    assert entry.kind == "action"
    assert entry.performed is True
    assert entry.action_id == "social_command"
    assert "приказ" in entry.reply.lower()
    assert campaign.actions_left == campaign.actions_per_turn - 1


def test_text_game_social_read_only_without_flag(catalog):
    campaign = _campaign()
    before = campaign.snapshot()
    game = TextGame(_session(catalog, campaign, allow_actions=False))
    entry = game.submit(COMMAND)
    assert entry.kind == "answer"
    assert entry.performed is False
    assert campaign.snapshot() == before


def test_text_game_undo_restores_social_action(catalog):
    campaign = _campaign()
    game = TextGame(_session(catalog, campaign))
    before = campaign.snapshot()
    game.submit(COMMAND)
    entry = game.submit("/undo")
    assert entry.kind == "command"
    assert campaign.snapshot() == before
    assert game.session.state.commitments == []
    assert game.history() == ()
