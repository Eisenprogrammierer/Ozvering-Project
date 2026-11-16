"""P6: сцена как данные, локальная публика и работы места.

Проверяется контракт, а не текст: сцена загружается из JSON, её публика
становится обычными персонажами ``WorldEngine``, работы ссылаются на
существующие действия, вход/выход подчиняются правилам, а снимок мира
переживает перезагрузку.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.content_lint import lint_scenes_data
from campaign.scenes import SceneCatalog, SceneSpec
from campaign.world import (
    WorldEngine,
    build_player_profile,
    load_world,
)

ROOT = Path(__file__).resolve().parents[1]
WORLDS = ROOT / "configs" / "worlds"


@pytest.fixture(scope="module")
def world():
    return load_world(WORLDS / "agora_world.json")


def _engine(
    world,
    node_id="agora_street",
    office_id="street_musician",
    seed=7,
):
    engine = WorldEngine(
        world,
        profile=build_player_profile({"name": "Тест"}, seed=seed),
        node_id=node_id,
        office_id=office_id,
        seed=seed,
    )
    assert engine.attach(node_id, office_id)["ok"] is True
    engine._roll = lambda token: 0.0
    return engine


def test_scene_catalog_loads_without_a_second_engine(world):
    catalog = SceneCatalog.from_list(world.get("scenes") or ())
    scenes = {scene.id: scene for scene in catalog}

    expected = {"street", "school", "temple", "palace", "market", "barracks"}
    assert expected <= set(scenes)
    for scene in scenes.values():
        assert scene.location
        assert scene.works
        for work_id in scene.works:
            assert work_id in {
                action["id"] for action in world["actions"]
            }, "%s: неизвестная работа %s" % (scene.id, work_id)


def test_local_public_becomes_world_characters(world):
    engine = _engine(world)
    people = {person["id"]: person for person in engine.scene_public("street")}

    assert {"street_piper", "street_baker", "street_orphan"} <= set(people)
    for person in people.values():
        assert person["node_id"] == "agora_street"
    assert engine.entity_ref(people["street_piper"])["kind"] == "character"


def test_scene_actions_are_the_declared_works(world):
    engine = _engine(world)
    scene = engine.scene_catalog.get("street")
    actions = engine.scene_actions("street")

    assert [action["id"] for action in actions] == list(scene.works)
    options = engine.scene_action_options("street")
    assert options
    assert {item["id"] for item in options} <= set(scene.works)
    assert "teach_lesson" not in {item["id"] for item in options}


def test_scene_time_reads_world_clock_and_overrides_slots(world):
    engine = _engine(world)
    time = engine.scene_time("street")

    assert time["slots"] == 3
    assert time["scene_id"] == "street"
    assert time["seconds_per_day"] == engine.seconds_per_day
    assert time["actions_per_day"] == engine.actions_per_day


def test_scene_entry_checks_location_and_domain(world):
    engine = _engine(world)

    allowed, reason = engine.can_enter_scene("school")
    assert allowed is False
    assert reason

    allowed, reason = engine.can_enter_scene("street")
    assert allowed is True
    assert reason == ""

    assert engine.enter_scene("street")["ok"] is True
    assert engine.current_scene().id == "street"

    assert engine.enter_scene("market")["ok"] is False


def test_scene_public_can_be_addressed_by_action(world):
    engine = _engine(world)
    assert engine.enter_scene("street")["ok"] is True
    piper = engine.characters["street_piper"]
    before = float(piper["trust"])

    result = engine.execute(
        "embrace",
        target_ref={"kind": "character", "id": "street_piper"},
    )

    assert result["ok"] is True
    assert float(piper["trust"]) > before
    assert {
        ref["id"] for ref in engine.action_targets("embrace")
    } >= {"street_piper"}


def test_scene_snapshot_roundtrip_and_old_snapshot(world):
    engine = _engine(world)
    assert engine.enter_scene("street")["ok"] is True
    engine.day = 2
    snapshot = engine.to_dict()
    assert snapshot["scene"] == {"id": "street", "entered_day": 1}

    restored = _engine(world)
    restored.load_snapshot(snapshot)
    assert restored.scene_id == "street"
    assert restored.scene_entered_day == 1

    old = dict(snapshot)
    old.pop("scene")
    old_engine = _engine(world)
    old_engine.load_snapshot(old)
    assert old_engine.scene_id == ""

    assert engine.leave_scene()["ok"] is True
    assert engine.scene_id == ""
    assert engine.to_dict()["scene"] == {"id": "", "entered_day": 0}


def test_scene_rules_are_data_driven():
    scene = SceneSpec.from_dict(
        {
            "id": "closed",
            "location": "agora_street",
            "works": [],
            "requires": {
                "day_min": 2,
                "office_ids": ["clerk"],
                "tags_any": ["court"],
            },
            "exit": {"after_days": 2, "when_detached": True},
        }
    )

    assert scene.allows(
        attached=True,
        office={"id": "clerk"},
        day=2,
        tags=("court",),
    ) == (True, "")
    assert scene.allows(
        attached=True,
        office={"id": "clerk"},
        day=1,
        tags=("court",),
    )[0] is False
    assert scene.allows(
        attached=True,
        office={"id": "guard"},
        day=2,
        tags=("court",),
    )[0] is False
    assert scene.allows(
        attached=True,
        office={"id": "clerk"},
        day=2,
        tags=("street",),
    )[0] is False
    assert scene.exit_reason(day=3, entered_day=1) == "сцена закончилась"
    assert scene.exit_reason(day=3, entered_day=2, attached=False) == (
        "сцена закрыта без должности"
    )


def test_scene_linter_catches_duplicates_and_empty_works():
    valid = {
        "id": "street",
        "location": "agora_street",
        "works": ["perform_song"],
        "public": [{"id": "piper"}],
        "time": {"slots": 3},
    }
    assert lint_scenes_data({"scenes": [valid]}) == []

    duplicate = dict(valid)
    duplicate["public"] = [{"id": "piper"}, {"id": "piper"}]
    problems = lint_scenes_data({"scenes": [valid, duplicate]})
    assert any("объявлена дважды" in item for item in problems)

    no_works = dict(valid, id="empty", works=[])
    assert any(
        "не заданы работы" in item
        for item in lint_scenes_data({"scenes": [no_works]})
    )

    bad_slots = dict(valid, id="fast", time={"slots": 0})
    assert any(
        "time.slots" in item
        for item in lint_scenes_data({"scenes": [bad_slots]})
    )
