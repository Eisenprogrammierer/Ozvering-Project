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
from campaign.world import WorldEngine, build_player_profile, load_world

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"
COMMAND = "Приказываю Республику."
WORLDS = ROOT / "configs" / "worlds"


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


# --- F-17: declared / improvised / trace -----------------------------


def test_declared_result_carries_work_and_trace(catalog, campaign):
    bridge = ActionBridge(
        catalog,
        campaign=campaign,
        side="red",
        allow_actions=True,
    )
    result = bridge.perform(
        Intent(
            kind="order",
            action_id="show_of_force",
            target="faction:blue",
            phrase="Покажи силу",
        )
    )
    assert result.ok is True
    assert result.performed is True
    assert result.source == "declared"
    assert result.work["form"] == "coercion"
    assert result.work["amount"] > 0
    assert result.trace["source"] == "declared"
    assert result.trace["verb"] == "покажи"
    assert result.trace["action"] == "show_of_force"
    assert result.trace["form"] == "coercion"
    assert result.trace["target"] == "faction:blue"
    assert result.snapshot()["trace"] == result.trace


def test_improvised_requires_explicit_permission(catalog, campaign):
    bridge = ActionBridge(
        catalog,
        campaign=campaign,
        side="red",
        allow_actions=True,
    )
    result = bridge.perform(
        Intent(
            kind="order",
            action_id="act_hug",
            form="contact",
            target="character:mira",
            phrase="Обними его",
        )
    )
    assert result.ok is False
    assert result.performed is False
    assert result.reason == "action_unknown"
    assert result.work == {}
    bare = bridge.perform(
        Intent(kind="order", form="contact", target="character:mira")
    )
    assert bare.ok is False
    assert bare.reason == "no_action"
    assert bare.work == {}


def test_improvised_builds_work_when_allowed(catalog, campaign):
    bridge = ActionBridge(
        catalog,
        campaign=campaign,
        side="red",
        allow_actions=True,
        allow_improvised=True,
    )
    result = bridge.perform(
        Intent(
            kind="order",
            action_id="act_hug",
            form="contact",
            target="character:mira",
            phrase="Обними его",
        )
    )
    assert result.ok is True
    assert result.performed is False
    assert result.source == "improvised"
    assert result.work["form"] == "contact"
    assert result.work["meta"]["source"] == "improvised"
    assert result.trace["source"] == "improvised"
    assert result.trace["verb"] == "обними"
    assert result.trace["form"] == "contact"
    assert result.trace["target"] == "character:mira"
    assert result.result["source"] == "improvised"


def test_improvised_rejects_incompatible_target(catalog, campaign):
    bridge = ActionBridge(
        catalog,
        campaign=campaign,
        side="red",
        allow_actions=True,
        allow_improvised=True,
    )
    result = bridge.perform(
        Intent(
            kind="order",
            action_id="act_hug",
            form="contact",
            target="norm:agora_charter",
            phrase="Обними закон",
        )
    )
    assert result.ok is False
    assert result.performed is False
    assert "improvised_invalid" in result.reason
    assert result.source == "improvised"


def test_declared_world_engine_action_runs_through_bridge(catalog):
    engine = WorldEngine(
        load_world(WORLDS / "agora_world.json"),
        profile=build_player_profile({"name": "Тест"}, seed=7),
        node_id="agora_street",
        office_id="street_musician",
        seed=7,
    )
    assert engine.attach("agora_street", "street_musician")["ok"] is True
    engine._roll = lambda token: 0.0
    target = engine.action_targets("hug")[0]
    bridge = ActionBridge(
        catalog,
        engine=engine,
        allow_actions=True,
    )
    result = bridge.perform(
        Intent(
            kind="order",
            action_id="hug",
            target="%s:%s" % (target["kind"], target["id"]),
            phrase="Обними его",
        )
    )
    assert result.ok is True
    assert result.performed is True
    assert result.source == "declared"
    assert result.trace["action"] == "hug"
    assert result.trace["form"] == "care"
    assert result.result["target_label"]
