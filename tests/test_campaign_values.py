"""Жёсткие ценностные ограничения кампании (§7.3 №18)."""

import copy

import pytest

from campaign import values
from campaign.world import (
    WorldEngine,
    build_player_profile,
    load_biography,
    load_world,
)


def _variables(value="order", value2="knowledge"):
    return {
        "name": "Ирина Свет",
        "gender": "female",
        "origin": "port",
        "family": "clerk",
        "education": "academy",
        "formative": "harbor_fire",
        "vocation": "state",
        "value": value,
        "value2": value2,
        "flaw": "ambition",
        "patron": "minister",
        "reputation": "respectable",
    }


def _profile(value="order", value2="knowledge"):
    return build_player_profile(
        _variables(value, value2),
        biography=load_biography(),
        seed=7,
    )


def _engine(value="order", value2="knowledge", extra=None):
    world = copy.deepcopy(load_world())
    for key, item in (extra or {}).items():
        world[key] = item
    return WorldEngine(
        world,
        profile=_profile(value, value2),
        node_id="agora_ministry_interior",
        office_id="ministry_official",
        seed=7,
    )


def _action(engine, action_id, **fields):
    action = dict(engine.actions[action_id])
    action.update(fields)
    return action


def test_profile_value_ids_are_stable_and_keep_labels_compatible():
    profile = _profile("order", "honor")
    assert profile["value_ids"] == ["order", "honor"]
    assert profile["values"] == ["Порядок", "Честь"]
    strengths = values.value_strengths(profile)
    assert strengths["order"] == pytest.approx(1.0)
    assert strengths["honor"] == pytest.approx(0.7)
    legacy = {"values": ["Порядок", "Честь"]}
    assert values.profile_value_ids(legacy) == ["order", "honor"]
    assert values.value_id("Честь") == "honor"
    assert values.label_for("honor") == "Честь"


def test_no_constraint_means_betrayal_remains_possible():
    profile = _profile("order", "honor")
    result = values.check_action(
        {"id": "sabotage", "betrayal": True}, profile
    )
    assert result["allowed"] is True
    result = values.check_action(
        {"id": "sabotage", "values": {"forbid": ["honor"]}}, profile
    )
    assert result["allowed"] is False
    assert result["blocked_by"] == "honor"
    assert "Честь" in result["reason"]


def test_hard_constraint_uses_threshold_and_require_any():
    primary = _profile("honor", "order")
    secondary_only = _profile("order", "honor")
    action = {"values": {"forbid": ["honor"], "threshold": 0.9}}
    assert values.check_action(action, primary)["allowed"] is False
    assert values.check_action(action, secondary_only)["allowed"] is True

    required = {"values": {"require_any": ["faith", "mercy"]}}
    assert values.check_action(required, primary)["allowed"] is False
    assert values.check_action(
        required, _profile("faith", "order")
    )["allowed"] is True
    assert "Вера" in values.check_action(required, primary)["reason"]


def test_world_defaults_make_betrayal_absolute_for_selected_value():
    rules = values.value_rules(
        {
            "threshold": 0.7,
            "defaults": {"betrayal": {"forbid": ["honor"]}},
        }
    )
    action = {"id": "sabotage", "betrayal": True}
    assert values.check_action(action, _profile("order", "honor"), rules)[
        "allowed"
    ] is False
    assert values.check_action(action, _profile("order", "knowledge"), rules)[
        "allowed"
    ] is True


def test_validate_blocks_only_the_declared_value_and_execute_is_unchanged():
    engine = _engine("order", "honor")
    engine.actions["audience"] = _action(
        engine, "audience", values={"forbid": ["honor"]}
    )
    allowed, reason = engine.validate("audience", "agora_government")
    assert allowed is False
    assert "Честь" in reason
    before = engine.actions_left
    result = engine.execute("audience", "agora_government")
    assert result["ok"] is False
    assert engine.actions_left == before

    engine.actions["audience"] = _action(engine, "audience")
    engine.actions["audience"].pop("values", None)
    assert engine.validate("audience", "agora_government")[0] is True


def test_value_view_reports_strengths_and_declared_constraints():
    engine = _engine("order", "knowledge")
    engine.actions["sabotage"] = _action(
        engine,
        "sabotage",
        values={"forbid": ["mercy"], "betrayal": True},
    )
    view = engine.value_view()
    assert view["ids"] == ["order", "knowledge"]
    assert view["strengths"]["order"] == pytest.approx(1.0)
    assert "sabotage" in view["constraints"]
    assert view["constraints"]["sabotage"]["betrayal"] is True
    assert view["labels"]["order"] == "Порядок"


def test_node_values_are_used_for_autonomous_agents():
    engine = _engine("order", "knowledge")
    engine.nodes["agora_watch"]["values"] = {"honor": 1.0}
    context = engine.node_context("agora_watch")
    result = engine.value_check(
        {"values": {"forbid": ["honor"]}}, context
    )
    assert result["allowed"] is False
    assert engine.value_check(
        {"values": {"forbid": ["honor"]}}, engine.player_context()
    )["allowed"] is True
