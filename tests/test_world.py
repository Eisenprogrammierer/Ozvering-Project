import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from campaign.world import (
    DOMAIN_SKILLS,
    WorldEngine,
    WorldError,
    build_player_profile,
    load_biography,
    load_world,
    validate_world,
)
from view.support.storyline import check_storyline_condition, load_storyline


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


def _profile():
    return build_player_profile(
        _variables(), biography=load_biography(), seed=7
    )


def _engine(
    node_id="agora_government", office_id="head_of_government", seed=7
):
    return WorldEngine(
        load_world(),
        profile=_profile(),
        node_id=node_id,
        office_id=office_id,
        seed=seed,
    )


def test_world_has_seven_domains_multiple_polities_and_variable_depth():
    world = load_world()
    assert [item["id"] for item in world["domains"]] == [
        "order",
        "meaning",
        "provision",
        "status",
        "knowledge",
        "care",
        "exchange",
    ]
    assert len(world["polities"]) >= 4
    assert len(world["nodes"]) == 43
    assert len(world["offices"]) == 69
    assert len(world["actions"]) == 47
    engine = WorldEngine(world)
    depths = {engine.node_depth(node["id"]) for node in engine.sorted_nodes()}
    assert len(depths) >= 3


def test_world_config_rejects_hierarchy_cycles():
    world = copy.deepcopy(load_world())
    first = world["nodes"][0]
    second = world["nodes"][1]
    first["parent"] = second["id"]
    second["parent"] = first["id"]
    with pytest.raises(WorldError):
        validate_world(world)


def test_biography_builds_profile_skills_connections_and_aptitudes():
    profile = _profile()
    assert profile["name"] == "Ирина Свет"
    assert profile["origin"] == "Порт Агоры"
    assert set(profile["skills"]) == set(DOMAIN_SKILLS["order"]) | {
        "diplomacy",
        "faith",
        "trade",
        "scholarship",
        "care",
        "intrigue",
        "media",
    }
    assert profile["skills"]["administration"] > 0.24
    assert profile["skills"]["trade"] > 0.1
    assert profile["connections"]
    assert "портовый" in profile["traits"]
    assert "Порядок" in profile["values"]
    assert set(profile["aptitudes"]) == set(DOMAIN_SKILLS)
    assert 0.0 <= profile["aptitudes"]["order"] <= 1.0


def test_office_options_show_requirements_and_disable_unqualified_office():
    engine = _engine()
    government = {
        item["id"]: item for item in engine.office_options("agora_government")
    }
    assert government["head_of_government"]["enabled"] is True
    press = {
        item["id"]: item for item in engine.office_options("knowledge_press")
    }
    assert press["printer"]["enabled"] is True
    assert press["editor"]["enabled"] is False
    assert "публичность" in press["editor"]["reason"]
    assert engine.attach("knowledge_press", "editor")["ok"] is False
    assert engine.attach("agora_government", "not_an_office")["ok"] is False


def test_action_validation_uses_domain_target_level_office_and_context():
    engine = _engine()
    assert engine.validate("reform", "knowledge_press") == (
        False,
        "Реформа применяется к учреждениям, а не к имуществу или станку.",
    )
    assert engine.validate("reform", "agora_government") == (
        False,
        "нельзя выбрать собственную структуру",
    )
    assert engine.validate("reform", "agora_ministry_interior")[0] is True
    assert engine.validate("publish", "knowledge_press") == (
        False,
        "действие относится к другой сфере: Знание",
    )
    assert engine.validate("enforce_order", "agora_precinct_port")[0] is False
    assert (
        "уровня" in engine.validate("enforce_order", "agora_precinct_port")[1]
    )
    assert engine.validate("denounce", "status_house_agora") == (
        False,
        "нужно больше личного ресурса «доказательства»",
    )
    secretary = _engine(office_id="state_secretary")
    assert secretary.validate("reform", "agora_ministry_interior") == (
        False,
        "ваша должность не даёт этого права",
    )


def test_action_validation_checks_authority_and_daily_resource():
    engine = _engine(node_id="agora_watch", office_id="agency_head")
    assert engine.validate("enforce_order", "agora_precinct_port")[0] is True
    engine.player_authority = 0.1
    assert engine.validate("enforce_order", "agora_precinct_port") == (
        False,
        "недостаточно полномочий: нужно 30%",
    )
    engine.player_authority = 0.9
    engine.actions_left = 0
    assert engine.validate("enforce_order", "agora_precinct_port") == (
        False,
        "действия на сегодня исчерпаны",
    )


def test_every_world_node_acts_on_autonomous_tick():
    engine = _engine()
    for day in range(1, 6):
        result = engine.end_day()
        assert result["ok"] is True
        assert engine.day == day + 1
        assert engine.actions_left == engine.actions_per_day
        assert len(result["events"]) == len(engine.nodes)
        assert len({event["source"] for event in result["events"]}) == len(
            engine.nodes
        )
        assert all(event["day"] == day for event in result["events"])
    assert len(engine.log) >= len(engine.nodes) * 5


def test_world_is_deterministic_for_same_seed():
    first = _engine(seed=19)
    second = _engine(seed=19)
    first.end_day()
    second.end_day()
    assert first.last_result == second.last_result
    assert first.log == second.log
    assert {
        key: value["stats"] for key, value in first.to_dict()["nodes"].items()
    } == {
        key: value["stats"] for key, value in second.to_dict()["nodes"].items()
    }


def test_career_promotion_transfer_and_dismissal():
    promoted = _engine(
        node_id="agora_ministry_interior", office_id="ministry_official"
    )
    promoted.player_resources["standing"] = 0.9
    result = promoted.execute("seek_promotion", "agora_government")
    assert result["outcome"] == "success"
    assert promoted.player_node_id == "agora_government"
    assert promoted.player_office()["rank"] == 1
    assert promoted.career_history[-1]["kind"] == "promote"

    transferred = _engine(
        node_id="agora_ministry_interior",
        office_id="ministry_official",
        seed=1,
    )
    transferred.player_resources["standing"] = 0.9
    result = transferred.execute("request_transfer", "agora_ministry_finance")
    assert result["outcome"] == "success"
    assert transferred.player_node_id == "agora_ministry_finance"
    assert transferred.career_history[-1]["kind"] == "transfer"

    dismissed = _engine()
    dismissed.player_resources["standing"] = 0.0
    dismissed.end_day()
    assert dismissed.finished is True
    assert dismissed.outcome == "lose"
    assert dismissed.execute("inspect", "knowledge_press") == {
        "ok": False,
        "reason": "кампания завершена",
    }


def test_world_snapshot_roundtrip_restores_state_and_career():
    engine = _engine(
        node_id="agora_ministry_interior",
        office_id="ministry_official",
        seed=1,
    )
    engine.player_resources["standing"] = 0.9
    engine.execute("request_transfer", "agora_ministry_finance")
    engine.execute("inspect", "knowledge_press")
    engine.end_day()
    snapshot = json.loads(json.dumps(engine.to_dict()))
    restored = WorldEngine(load_world(), snapshot=snapshot)
    assert restored.attached is True
    assert restored.day == engine.day
    assert restored.player_node_id == engine.player_node_id
    assert restored.player_office_id == engine.player_office_id
    assert restored.player_resources == engine.player_resources
    assert restored.career_history == engine.career_history
    assert restored.log == json.loads(json.dumps(engine.log))
    assert restored.to_dict()["nodes"] == engine.to_dict()["nodes"]
    assert restored.action_options("knowledge_press")


def test_world_storyline_conditions_read_world_snapshot():
    engine = _engine()
    engine.player_resources["standing"] = 0.65
    storyline_state = {"world": engine.to_dict()}
    assert check_storyline_condition(
        {"type": "world_day_at_least", "value": 1},
        None,
        None,
        storyline_state,
    )
    assert check_storyline_condition(
        {"type": "world_standing_at_least", "value": 0.6},
        None,
        None,
        storyline_state,
    )
    assert check_storyline_condition(
        {
            "type": "world_node_stat_at_least",
            "node": "agora_government",
            "stat": "legitimacy",
            "value": 0.1,
        },
        None,
        None,
        storyline_state,
    )
    assert not check_storyline_condition(
        {"type": "world_outcome", "value": "win"},
        None,
        None,
        storyline_state,
    )


def test_world_storyline_definition_is_complete():
    storyline = load_storyline("world_demo")
    assert storyline is not None
    assert storyline["world_path"] == "configs/worlds/agora_world.json"
    assert storyline["biography_path"] == "configs/worlds/biography.json"
    assert storyline["campaign_seed"] == 7
    assert len(storyline["character_creation"]["steps"]) == 12
    assert [scene["type"] for scene in storyline["scenes"]] == [
        "visual_novel",
        "character_creation",
        "automaton_choice",
        "visual_novel",
        "world",
    ]
    assert storyline["scenes"][0]["slides"][0]["image"].startswith("campaign/")


def test_world_layer_is_headless():
    root = Path(__file__).resolve().parents[1]
    code = (
        "import campaign, campaign.world; import sys; "
        "assert 'pygame' not in sys.modules, 'campaign imported pygame'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
