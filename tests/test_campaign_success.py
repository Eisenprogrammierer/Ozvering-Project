"""Предикторы, коэффициенты и маржа успеха (§7.6 №33–35)."""

import copy

import pytest

from campaign.actor import campaign_success_chance
from campaign.success import (
    SUCCESS_PREDICTORS,
    resolve_success_coefficients,
    success_margin,
    success_margin_view,
)
from campaign.world import (
    WorldEngine,
    build_player_profile,
    load_biography,
    load_world,
)
from core41.model import (
    DEFAULT_SUCCESS_COEFFICIENTS,
    SUCCESS_COEFFICIENT_KEYS,
    success_probability,
)
from core41.types import Work


def _variables():
    return {
        "name": "Ирина Свет",
        "gender": "female",
        "origin": "port",
        "family": "clerk",
        "education": "academy",
        "formative": "harbor_fire",
        "vocation": "state",
        "value": "order",
        "value2": "knowledge",
        "flaw": "ambition",
        "patron": "minister",
        "reputation": "respectable",
    }


def _engine(seed=7):
    profile = build_player_profile(
        _variables(), biography=load_biography(), seed=seed
    )
    return WorldEngine(
        load_world(),
        profile=profile,
        node_id="agora_government",
        office_id="head_of_government",
        seed=seed,
    )


def test_predictor_registry_covers_every_coefficient():
    keys = [item["key"] for item in SUCCESS_PREDICTORS]
    assert keys == list(SUCCESS_COEFFICIENT_KEYS)
    for item in SUCCESS_PREDICTORS:
        assert item["label"]
        assert item["source"]
        assert item["direction"] in (-1, 1)
        assert item["key"] in DEFAULT_SUCCESS_COEFFICIENTS


def test_explicit_default_coefficients_preserve_core_chance():
    engine = _engine()
    character = engine.characters[engine.character_order[0]]
    action = copy.deepcopy(engine.character_actions["heart_to_heart"])
    context = engine.player_context()
    action["success"] = {"chance": 0.57}
    without = engine._action_chance(
        action, character, context, action["success"], True
    )
    action["success"]["coefficients"] = dict(DEFAULT_SUCCESS_COEFFICIENTS)
    with_defaults = engine._action_chance(
        action, character, context, action["success"], True
    )
    assert with_defaults == pytest.approx(without)


def test_unknown_and_invalid_coefficients_are_ignored_and_clamped():
    defaults = resolve_success_coefficients({})
    assert defaults == DEFAULT_SUCCESS_COEFFICIENTS
    ignored = resolve_success_coefficients(
        {
            "success": {
                "coefficients": {
                    "skill": "not-a-number",
                    "unknown": 99.0,
                }
            }
        }
    )
    assert ignored == DEFAULT_SUCCESS_COEFFICIENTS
    clamped = resolve_success_coefficients(
        {"success": {"coefficients": {"skill": 100.0, "authority": -100.0}}}
    )
    assert clamped["skill"] == 10.0
    assert clamped["authority"] == -10.0
    short = resolve_success_coefficients(
        {"success_coefficients": {"intercept": 1.25}}
    )
    assert short["intercept"] == pytest.approx(1.25)
    assert short["skill"] == DEFAULT_SUCCESS_COEFFICIENTS["skill"]


def test_action_coefficients_change_chance_but_keep_bounds():
    engine = _engine()
    character = engine.characters[engine.character_order[0]]
    action = copy.deepcopy(engine.character_actions["heart_to_heart"])
    context = engine.player_context()
    low_action = copy.deepcopy(action)
    low_action["success"] = {
        "chance": 0.5,
        "coefficients": {"intercept": -2.0},
    }
    high_action = copy.deepcopy(action)
    high_action["success"] = {
        "chance": 0.5,
        "coefficients": {"intercept": 2.0},
    }
    low = engine._action_chance(
        low_action, character, context, low_action["success"], True
    )
    high = engine._action_chance(
        high_action, character, context, high_action["success"], True
    )
    assert high > low
    for chance in (low, high):
        assert 0.05 <= chance <= 0.95
    # Прямая проверка ядра: те же коэффициенты дают тот же сдвиг логита.
    assert success_probability(
        engine.player.unit,
        character.sync(),
        Work(amount=0.0, form="force"),
        False,
        coefficients={"intercept": 2.0},
    ) > success_probability(
        engine.player.unit,
        character.sync(),
        Work(amount=0.0, form="force"),
        False,
        coefficients={"intercept": -2.0},
    )


def test_success_margin_is_signed_and_outcome_matches_roll():
    assert success_margin(0.6, 0.4) == pytest.approx(0.2)
    assert success_margin(0.4, 0.6) == pytest.approx(-0.2)
    view = success_margin_view(0.6, 0.4)
    assert view["outcome"] == "success"
    assert view["distance"] == pytest.approx(0.2)
    assert success_margin_view(0.6, 0.6)["outcome"] == "failure"


def test_action_result_records_chance_roll_and_margin():
    engine = _engine(seed=11)
    candidate = None
    for node in engine.nodes.values():
        for item in engine.action_options(node["id"]):
            if item["enabled"] and not item["action"].get("career"):
                candidate = (item, node["id"])
                break
        if candidate is not None:
            break
    assert candidate is not None
    option, target_id = candidate
    result = engine.execute(option["id"], target_id)
    assert result["ok"] is True
    assert 0.05 <= result["chance"] <= 0.95
    assert 0.0 <= result["roll"] <= 1.0
    assert result["margin"] == pytest.approx(
        result["chance"] - result["roll"]
    )
    assert (result["outcome"] == "success") is (result["margin"] > 0.0)


def test_autonomy_event_records_margin():
    from campaign.planner import Intent

    engine = _engine(seed=11)
    character = engine.characters[engine.character_order[0]]
    character["autonomous"] = True
    intent = Intent(
        due_day=engine.day,
        kind="contact",
        actor=character["id"],
        payload={"policy": "probe", "effects": {"affinity": 0.01}},
        source="autonomy",
    )
    events = engine._apply_autonomy_contact(intent)
    assert events
    event = events[0]
    assert "chance" in event
    assert "roll" in event
    assert event["margin"] == pytest.approx(
        event["chance"] - event["roll"]
    )
    assert (event["outcome"] == "success") is (event["margin"] > 0.0)


def test_campaign_success_chance_accepts_coefficients():
    engine = _engine()
    character = engine.characters[engine.character_order[0]]
    base = campaign_success_chance(
        0.5, engine.player, character.sync(), coefficients={}
    )
    biased = campaign_success_chance(
        0.5,
        engine.player,
        character.sync(),
        coefficients={"intercept": 4.0},
    )
    assert biased != base
    assert 0.05 <= biased <= 0.95
