"""Версионирование и миграция сохранений кампании."""

import json

from view.support import save_system


def test_migrate_v1_adds_v2_containers_without_losing_state():
    payload = {
        "version": 1,
        "campaign": {"day": 7, "player": {"node_id": "n"}},
    }

    migrated = save_system.migrate_save(payload)

    assert migrated["version"] == save_system.SAVE_VERSION
    assert migrated["campaign"]["day"] == 7
    assert migrated["campaign"]["node_strategy_state"] == {}
    assert migrated["campaign"]["environment_plan"] == {}


def test_migrate_future_version_is_loaded_unchanged():
    payload = {"version": save_system.SAVE_VERSION + 5, "campaign": {}}

    migrated = save_system.migrate_save(payload)

    assert migrated["version"] == save_system.SAVE_VERSION + 5
    assert migrated["campaign"] == {}


def test_save_roundtrip_writes_current_version(tmp_path, monkeypatch):
    monkeypatch.setattr(save_system, "SAVES_DIR", tmp_path)

    class State:
        def to_snapshot(self):
            return {"day": 3, "profile": {"name": "Тест"}}

    path = save_system.save_game(State(), None, "slot")

    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    assert raw["version"] == save_system.SAVE_VERSION
    assert raw["campaign"]["day"] == 3

    loaded = save_system.load_game("slot")
    assert loaded["version"] == save_system.SAVE_VERSION
    assert loaded["campaign"]["node_strategy_state"] == {}


def test_old_save_file_is_migrated_on_load(tmp_path, monkeypatch):
    monkeypatch.setattr(save_system, "SAVES_DIR", tmp_path)
    payload = {"version": 1, "campaign": {"day": 9}}
    (tmp_path / "legacy.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    loaded = save_system.load_game("legacy")

    assert loaded["version"] == save_system.SAVE_VERSION
    assert loaded["campaign"]["day"] == 9
    assert "node_strategy_state" in loaded["campaign"]


def test_save_compatibility_rejects_legacy_rts_payload():
    legacy = {
        "scenario_path": "scenarios/mvp.json",
        "campaign": {"turn": 30},
        "campaign_preset": {"scenario": {"mode": None}},
    }
    assert save_system.save_is_compatible(legacy) is False


def test_save_compatibility_accepts_automata_strategy_and_world():
    assert save_system.save_is_compatible(
        {"campaign": {"automata": {"turn": 1}}}
    )
    assert save_system.save_is_compatible(
        {"storyline": {"state": {"strategy": {"day": 2}}}}
    )
    assert save_system.save_is_compatible(
        {"storyline": {"state": {"world": {"day": 2}}}}
    )
    assert save_system.save_is_compatible(
        {"campaign_preset": {"scenario": {"mode": "strategy"}}}
    )


def test_list_compatible_saves_filters_legacy_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(save_system, "SAVES_DIR", tmp_path)
    legacy = {
        "updated": "2026-11-08 12:00:00",
        "campaign": {"turn": 1},
    }
    automata = {
        "updated": "2026-11-08 11:00:00",
        "campaign": {"automata": {"turn": 4}},
    }
    (tmp_path / "legacy.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )
    (tmp_path / "automata.json").write_text(
        json.dumps(automata), encoding="utf-8"
    )

    all_saves = {item["name"]: item for item in save_system.list_saves()}
    assert all_saves["legacy"]["compatible"] is False
    assert all_saves["automata"]["compatible"] is True
    assert [
        item["name"] for item in save_system.list_compatible_saves()
    ] == ["automata"]
