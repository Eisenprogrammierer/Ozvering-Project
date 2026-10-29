import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Сценный/графический слой view требует numpy; в окружении без него тест
# честно скипается через importorskip, а не роняет коллекцию всего прогона.
pytest.importorskip("numpy")


from campaign.world import (
    COLLAPSE_GRACE_DAYS,
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
    # §7 №29: потеря должности — смена роли, а не поражение.
    assert dismissed.finished is False
    assert dismissed.outcome is None
    assert dismissed.dismissed is True
    assert dismissed.dismissal_count == 1
    assert dismissed.attached is True
    assert dismissed.player_office_id != "head_of_government"
    assert dismissed.career_history[-2]["kind"] == "dismiss"
    assert dismissed.career_history[-1]["kind"] == "reassign"
    assert any(entry["kind"] == "career" for entry in dismissed.log)


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


def test_characters_have_circles_actions_and_qualitative_preview():
    engine = _engine()
    close = engine.characters_by_circle("close")
    assert len(close) >= 5
    assert all(item["circle"] == "close" for item in close)
    assert engine.character_circle_label("close") == "ближний круг"

    options = engine.character_action_options("mira_svet")
    assert {item["id"] for item in options} >= {
        "heart_to_heart",
        "offer_help",
        "ask_favor",
    }
    assert any(item["enabled"] for item in options)
    assert any(not item["enabled"] and item["reason"] for item in options)

    preview = engine.character_preview("heart_to_heart", "mira_svet")
    assert preview["enabled"] is True
    assert preview["success_effects_map"]["affinity"] > 0
    assert preview["failure_effects_map"]

    before_actions = engine.actions_left
    before_affinity = engine.character_relation("mira_svet")
    result = engine.execute_character_action("heart_to_heart", "mira_svet")
    assert result["ok"] is True
    assert result["context"] == "character"
    assert result["target"] == "mira_svet"
    assert engine.actions_left == before_actions - 1
    assert engine.character_relation("mira_svet") != before_affinity
    assert engine.last_result == result


def test_character_actions_and_items_survive_snapshot_roundtrip():
    engine = _engine()
    engine.execute_character_action("heart_to_heart", "mira_svet")
    snapshot = json.loads(json.dumps(engine.to_dict()))
    assert snapshot["characters"]["mira_svet"]
    assert snapshot["player"]["items"] == engine.player_item_ids
    restored = WorldEngine(load_world(), snapshot=snapshot)
    assert restored.character_relation(
        "mira_svet"
    ) == engine.character_relation("mira_svet")
    assert restored.character_trust("mira_svet") == engine.character_trust(
        "mira_svet"
    )
    assert restored.player_item_ids == engine.player_item_ids
    assert restored.player_items()

    legacy = json.loads(json.dumps(engine.to_dict()))
    legacy["player"].pop("items")
    legacy.pop("characters")
    legacy_engine = WorldEngine(load_world(), snapshot=legacy)
    assert legacy_engine.player_items()
    assert legacy_engine.character("mira_svet") is not None


def test_organization_categories_follow_relations_and_keep_player_node():
    engine = _engine()
    groups = engine.organization_groups()
    assert engine.organization_category(engine.player_node_id) == "allied"
    assert engine.player_node_id in [item["id"] for item in groups["allied"]]
    for category, nodes in groups.items():
        if category == "allied":
            continue
        assert all(item["kind"] != "asset" for item in nodes)

    press = _engine("knowledge_press", "printer")
    press_allied = press.organization_groups()["allied"]
    assert press.player_node_id in [item["id"] for item in press_allied]
    assert all(
        item["kind"] != "asset" or item["id"] == press.player_node_id
        for item in press_allied
    )

    target = groups["neutral"][0]
    source = engine.node(engine.player_node_id)
    target_node = engine.node(target["id"])
    source["relations"][target["id"]] = -0.5
    target_node["relations"][engine.player_node_id] = -0.5
    assert engine.organization_category(target["id"]) == "hostile"
    assert target["id"] in [
        item["id"] for item in engine.organization_groups()["hostile"]
    ]


def test_items_and_skill_tree_are_derived_from_office_and_profile():
    engine = _engine()
    items = engine.player_items()
    assert items
    assert any(item["id"] == "personal_seal" for item in items)
    assert all(item.get("label") for item in items)
    assert not {
        "service_folder",
        "pocket_notebook",
        "pocket_map",
        "field_glasses",
        "radio_set",
    } & {item["id"] for item in items}

    tree = engine.skill_tree()
    assert len(tree) == 3
    skills = [skill for branch in tree for skill in branch["skills"]]
    assert {skill["id"] for skill in skills} == set(engine.skill_labels)
    assert all(0.0 <= skill["value"] <= 1.0 for skill in skills)
    assert all(skill.get("description") for skill in skills)


def test_campaign_action_grows_target_domain_skills():
    engine = _engine()
    for skill in ("administration", "command"):
        engine.profile["skills"][skill] = 0.12
    before = dict(engine.profile["skills"])

    result = engine.execute("inspect", "agora_ministry_interior")

    assert result["ok"] is True
    assert engine.profile["skills"]["administration"] > 0.12
    assert engine.profile["skills"]["command"] > 0.12
    # Цель в домене order тренирует именно order-навыки, а не все девять.
    assert engine.profile["skills"]["faith"] == before["faith"]
    assert any("навык" in label for label, _ in result["changes"])


def test_campaign_skill_growth_saturates_at_cap():
    from campaign.world import CAMPAIGN_SKILL_CAP

    engine = _engine()
    for skill in ("administration", "command"):
        engine.profile["skills"][skill] = CAMPAIGN_SKILL_CAP

    engine.execute("inspect", "agora_ministry_interior")

    assert engine.profile["skills"]["administration"] == pytest.approx(
        CAMPAIGN_SKILL_CAP
    )
    assert engine.profile["skills"]["command"] == pytest.approx(
        CAMPAIGN_SKILL_CAP
    )


def test_campaign_skill_growth_unlocks_promotion_requirement():
    engine = _engine(
        node_id="agora_ministry_interior", office_id="ministry_official"
    )
    engine.player_resources["standing"] = 0.9
    for skill in ("administration", "command"):
        engine.profile["skills"][skill] = 0.175

    # До практики навык ниже требования seek_promotion (0.18).
    blocked = engine.execute("seek_promotion", "agora_government")
    assert blocked["ok"] is False
    assert "навык" in blocked["reason"]

    engine.execute("inspect", "agora_watch")
    assert engine.profile["skills"]["administration"] >= 0.18

    result = engine.execute("seek_promotion", "agora_government")
    assert result["ok"] is True


def test_campaign_skill_growth_survives_snapshot_roundtrip():
    engine = _engine()
    engine.profile["skills"]["administration"] = 0.12
    engine.execute("inspect", "agora_ministry_interior")
    grown = engine.profile["skills"]["administration"]

    restored = WorldEngine(
        load_world(), snapshot=json.loads(json.dumps(engine.to_dict()))
    )

    assert restored.profile["skills"]["administration"] == pytest.approx(
        grown
    )


def test_campaign_sickness_can_kill_player_and_character():
    engine = _engine()
    engine.infect_player(1.0)
    engine.player_health = 3.0
    engine.infect_character("mira_svet", 1.0)
    engine.characters["mira_svet"]["health"] = 2.0

    engine.end_day()

    assert engine.player_alive is False
    assert engine.player_health == 0.0
    assert engine.finished is True
    assert engine.outcome == "lose"
    assert engine.collapsed is False
    assert engine.characters["mira_svet"]["alive"] is False
    option = engine.character_action_options("mira_svet")[0]
    assert option["enabled"] is False
    assert "мёртв" in option["reason"]


def test_campaign_organization_collapse_is_defeat():
    engine = _engine()
    node = engine.node(engine.player_node_id)
    node["stats"]["power"] = 0.0
    node["stats"]["cohesion"] = 0.0
    engine.end_day()
    assert engine.finished is True
    assert engine.outcome == "lose"
    assert any(entry["kind"] == "collapse" for entry in engine.log)


def test_campaign_condition_survives_snapshot_roundtrip():
    engine = _engine()
    engine.infect_player(0.4)
    engine.player_health = 63.5
    engine.infect_character("mira_svet", 0.3)
    engine.characters["mira_svet"]["health"] = 71.0

    restored = WorldEngine(
        load_world(), snapshot=json.loads(json.dumps(engine.to_dict()))
    )
    assert restored.player_condition() == engine.player_condition()
    assert restored.character_condition(
        "mira_svet"
    ) == engine.character_condition("mira_svet")
    assert restored.infect_player(0.2) == 0.4
    assert restored.treat_player(0.1) == pytest.approx(0.3)


def test_campaign_collapse_requires_grace_days_and_reports_status():
    engine = _engine()
    node = engine.node(engine.player_node_id)
    node["stats"]["power"] = 0.0
    node["stats"]["cohesion"] = 0.5

    status = engine.organization_status()
    assert status["strain"] is True
    assert status["collapse_days"] == 0
    assert status["collapse_in"] == COLLAPSE_GRACE_DAYS

    engine.end_day()
    assert engine.finished is False
    assert engine.collapse_days == 1
    assert engine.organization_status()["collapse_in"] == (
        COLLAPSE_GRACE_DAYS - 1
    )

    # Дневные действия мира могут поднять силу выше порога; для проверки
    # grace-дней удерживаем её ниже порога и на втором дне.
    node["stats"]["power"] = 0.0
    engine.end_day()
    assert engine.finished is True
    assert engine.outcome == "lose"
    assert engine.collapsed is True
    assert engine.collapse_days >= COLLAPSE_GRACE_DAYS
    assert any(entry["kind"] == "collapse" for entry in engine.log)


def test_campaign_collapse_counter_resets_after_recovery():
    engine = _engine()
    node = engine.node(engine.player_node_id)
    node["stats"]["power"] = 0.04
    engine.end_day()
    assert engine.collapse_days == 1
    node["stats"]["power"] = 0.5
    engine.end_day()
    assert engine.finished is False
    assert engine.collapse_days == 0
    assert any(entry["kind"] == "recovery" for entry in engine.log)


def test_campaign_dismissal_checks_are_idempotent_per_day():
    engine = _engine()
    node = engine.node(engine.player_node_id)
    node["stats"]["power"] = 0.04
    node["stats"]["cohesion"] = 0.5

    engine._check_dismissal()
    engine._check_dismissal()
    engine._check_dismissal()

    assert engine.collapse_days == 1
    assert engine.finished is False


def test_campaign_role_change_happens_once_per_day():
    engine = _engine()
    node = engine.node(engine.player_node_id)
    node["stats"]["legitimacy"] = 0.07

    engine._check_dismissal()
    engine._check_dismissal()
    engine._check_dismissal()

    assert engine.dismissal_count == 1


def test_campaign_resign_is_role_change_not_defeat():
    engine = _engine()
    result = engine.execute("resign", "")
    assert result["ok"] is True
    # §7 №29: добровольная отставка не завершает кампанию и не даёт lose.
    assert engine.finished is False
    assert engine.outcome is None
    assert engine.attached is False
    assert engine.dismissed is True
    assert engine.dismissal_count == 1
    assert engine.career_history[-1]["kind"] == "resign"
    assert engine.execute("inspect", "knowledge_press") == {
        "ok": False,
        "reason": "сначала выберите должность",
    }


def test_campaign_can_be_reemployed_after_role_change():
    engine = _engine()
    engine.player_resources["standing"] = 0.0
    engine.end_day()
    previous_day = engine.day
    # Возвращаемся к прежней должности через тот же публичный API, что UI.
    assert engine.attached is True
    engine.player_office_id = ""
    engine.attached = False
    option = next(
        item
        for item in engine.office_options("agora_government")
        if item["enabled"]
    )
    assert engine.attach("agora_government", option["id"])["ok"] is True
    assert engine.attached is True
    assert engine.day == previous_day


def test_campaign_infinite_horizon_does_not_award_win():
    engine = _engine()
    engine.days = 1
    assert engine.infinite is True
    engine.end_day()
    engine.end_day()
    assert engine.day > engine.days
    assert engine.finished is False
    assert engine.outcome is None
    assert engine.horizon_passed is True
    assert any(entry["kind"] == "horizon" for entry in engine.log)


def test_campaign_finite_legacy_horizon_still_awards_outcome():
    engine = _engine()
    engine.infinite = False
    engine.days = 1
    engine.player_resources["standing"] = 0.9
    engine.end_day()
    engine.end_day()
    assert engine.finished is True
    assert engine.outcome == "win"


def test_campaign_narrative_ending_is_not_objective_win():
    engine = _engine()
    assert engine.end_storyline("neutral", "Глава завершена.") == (
        "Глава завершена."
    )
    assert engine.finished is True
    assert engine.ending == "neutral"
    assert engine.outcome is None
    assert engine.end_day() == {"ok": False, "reason": "кампания завершена"}


def test_campaign_advance_days_catches_up_and_stops_on_finish():
    engine = _engine()
    results = engine.advance_days(3)
    assert len(results) == 3
    assert engine.day == 4

    engine.player_health = 0.0
    engine.infect_player(1.0)
    engine.end_day()
    assert engine.finished is True
    assert engine.advance_days(3) == []


def test_campaign_advance_days_honours_limit():
    engine = _engine()
    results = engine.advance_days(10, max_days=2)
    assert len(results) == 2
    assert engine.day == 3


def test_campaign_contagion_spreads_from_player_to_same_node_character():
    engine = _engine()
    character = engine.characters["mira_svet"]
    character["node_id"] = engine.player_node_id
    engine.infect_player(0.9)

    for _ in range(10):
        engine.end_day()
        if any(entry["kind"] == "infection" for entry in engine.log):
            break

    assert character["sickness"] > 0.0
    infections = [
        entry for entry in engine.log if entry["kind"] == "infection"
    ]
    assert infections
    assert any("заразил" in entry["text"] for entry in infections)


def test_campaign_contagion_requires_same_node():
    engine = _engine()
    character = engine.characters["mira_svet"]
    other = next(
        node_id
        for node_id in engine.node_order
        if node_id != engine.player_node_id
    )
    character["node_id"] = other
    engine.infect_player(1.0)

    for _ in range(5):
        engine.end_day()

    assert character["sickness"] == 0.0


def test_campaign_contagion_is_inert_without_sickness():
    engine = _engine()

    for _ in range(5):
        engine.end_day()

    assert not any(entry["kind"] == "infection" for entry in engine.log)
    assert all(
        character["sickness"] == 0.0
        for character in engine.characters.values()
    )
