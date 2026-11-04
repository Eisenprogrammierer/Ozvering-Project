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
