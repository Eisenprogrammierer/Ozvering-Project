"""Тесты F-14: расширенный набор речевых актов."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import DialogueSession, build_knowledge
from campaign.dialogue.lint import lint_catalog
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"

CASES = {
    "Флиртую с тобой.": ("flirt", "social_offer"),
    "Признаюсь в любви.": ("confess", "social_promise"),
    "Сочувствую тебе.": ("console", "social_apology"),
    "Благословляю тебя.": ("bless", "social_offer"),
    "Клянусь тебе.": ("oath", "social_promise"),
    "Извиняюсь.": ("beg_pardon", "social_apology"),
    "Сватаюсь к тебе.": ("propose", "social_offer"),
}


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DEFAULT_DIR)


def _campaign(seed=13) -> AutomataCampaign:
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=seed), seed=seed)


def _session(catalog, campaign, side="red") -> DialogueSession:
    speaker = campaign.faction(side).characters[1].campaign_id
    return DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, side, speaker),
        style_id="neutral",
        allow_actions=True,
        campaign=campaign,
    )


def test_social_catalog_has_extended_acts(catalog):
    expected = {
        "command",
        "promise",
        "threat",
        "blackmail",
        "offer",
        "apology",
        "flirt",
        "confess",
        "console",
        "bless",
        "oath",
        "beg_pardon",
        "propose",
    }
    assert set(catalog.social.acts) == expected
    assert lint_catalog(catalog) == []


@pytest.mark.parametrize("phrase,expected", CASES.items())
def test_extended_act_reaches_interaction(catalog, phrase, expected):
    act_id, interaction = expected
    campaign = _campaign()
    session = _session(catalog, campaign)
    intent = session.intent(phrase)
    assert intent is not None
    assert intent.kind == "social"
    assert intent.act == act_id
    result = session.act(phrase)
    assert result.performed is True
    assert result.action_id == interaction
    social = result.result["social"]
    assert social["act_id"] == act_id
    assert social["interaction_id"] == interaction
    assert social["reaction_id"] in (
        "accept",
        "reject",
        "counter",
        "clarify",
    )


@pytest.mark.parametrize("phrase", ["Клянусь тебе.", "Сватаюсь к тебе."])
def test_trust_gated_acts_reject_without_trust(catalog, phrase):
    campaign = _campaign()
    before = campaign.snapshot()
    session = _session(catalog, campaign, side="blue")
    result = session.act(phrase)
    assert result.performed is False
    assert result.reason == "trusts"
    assert campaign.snapshot() == before


def test_beg_pardon_does_not_require_target(catalog):
    campaign = _campaign()
    result = _session(catalog, campaign).act("Извиняюсь.")
    assert result.performed is True
    assert result.action_id == "social_apology"
