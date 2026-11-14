"""Тесты D6.4: мост «фраза → намерение → действие».

Мост выключен по умолчанию; ``ask`` остаётся read-only. При
``allow_actions=True`` действие проходит проверку доступности и
уходит в ``AutomataCampaign.perform`` только через явный ``act``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import DialogueSession, build_knowledge
from campaign.dialogue.bridge import ActionBridge
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.planner import Intent
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"
COMMAND = "Приказываю Республику."


@pytest.fixture
def catalog():
    return load_dialogue(DEFAULT_DIR)


@pytest.fixture
def campaign():
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


@pytest.fixture
def session(catalog, campaign):
    return DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
        campaign=campaign,
    )


def test_bridge_is_disabled_by_default(catalog, campaign):
    bridge = ActionBridge(catalog, campaign=campaign, side="red")
    result = bridge.perform(Intent(kind="order", action_id="show_of_force"))
    assert result.ok is False
    assert result.performed is False
    assert result.reason == "actions_disabled"
    assert campaign.actions_left == 0


def test_bridge_requires_campaign(catalog):
    bridge = ActionBridge(catalog, campaign=None, side="red",
                          allow_actions=True)
    result = bridge.perform(Intent(kind="order", action_id="show_of_force"))
    assert result.reason == "no_campaign"
    assert result.performed is False


def test_bridge_requires_side(catalog, campaign):
    bridge = ActionBridge(catalog, campaign=campaign, side="",
                          allow_actions=True)
    result = bridge.perform(Intent(kind="order", action_id="show_of_force"))
    assert result.reason == "no_side"


def test_bridge_requires_action_id(catalog, campaign):
    bridge = ActionBridge(catalog, campaign=campaign, side="red",
                          allow_actions=True)
    result = bridge.perform(Intent(kind="order"))
    assert result.reason == "no_action"


def test_bridge_rejects_unknown_action(catalog, campaign):
    bridge = ActionBridge(catalog, campaign=campaign, side="red",
                          allow_actions=True)
    result = bridge.perform(Intent(kind="order", action_id="nope"))
    assert result.reason == "action_unknown"


def test_bridge_performs_order_and_passes_target(catalog, campaign):
    bridge = ActionBridge(catalog, campaign=campaign, side="red",
                          allow_actions=True)
    before = campaign.action_budget()
    result = bridge.perform(
        Intent(
            kind="order",
            action_id="show_of_force",
            target="faction:blue",
        )
    )
    assert result.ok is True
    assert result.performed is True
    assert result.result["target_side"] == "blue"
    assert before["active"] is False
    assert campaign.actions_left == campaign.actions_per_turn - 1


def test_bridge_reports_cooldown_reason(catalog, campaign):
    bridge = ActionBridge(catalog, campaign=campaign, side="red",
                          allow_actions=True)
    first = bridge.perform(Intent(kind="order", action_id="show_of_force"))
    second = bridge.perform(Intent(kind="order", action_id="show_of_force"))
    assert first.ok is True
    assert second.ok is False
    assert second.reason


def test_session_intent_from_phrase(session):
    intent = session.intent(COMMAND)
    assert intent is not None
    assert intent.kind == "social"
    assert intent.act == "command"
    assert intent.target == "faction:blue"


def test_session_act_is_disabled_by_default(session, campaign):
    before = campaign.snapshot()
    result = session.act(COMMAND, "show_of_force")
    assert result.reason == "actions_disabled"
    assert campaign.snapshot() == before


def test_session_act_blocks_without_authority(session, campaign):
    before = campaign.snapshot()
    result = session.act(
        COMMAND, "show_of_force", checks={"authority": False}
    )
    assert result.ok is False
    assert result.performed is False
    assert campaign.snapshot() == before


def test_session_act_performs_with_authority(catalog, campaign):
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
        allow_actions=True,
        campaign=campaign,
    )
    result = session.act(
        COMMAND, "show_of_force", checks={"authority": True}
    )
    assert result.ok is True
    assert result.performed is True
    assert result.result["target_side"] == "blue"


def test_session_ask_stays_read_only(catalog, campaign):
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
        allow_actions=True,
        campaign=campaign,
    )
    before = campaign.snapshot()
    session.ask("Какие органы есть у Империи?")
    assert campaign.snapshot() == before


def test_session_plan_goal_reflects_checks(session):
    blocked = session.plan_goal(
        COMMAND, "show_of_force", checks={"authority": False}
    )
    allowed = session.plan_goal(
        COMMAND, "show_of_force", checks={"authority": True}
    )
    assert blocked is not None and blocked.status == "blocked"
    assert allowed is not None and allowed.next_step().id == "act"
