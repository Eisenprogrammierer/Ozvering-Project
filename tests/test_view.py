"""Тесты кампанийного UI-каркаса ``view`` (без pygame)."""

import pytest

np = pytest.importorskip("numpy")

from view.support.scenario import build_world
from view.support.time_system import CampaignTimeSystem
from view.support.world import CampaignEngine
from view.support import save_system


def _world():
    state = build_world()
    return state, CampaignEngine(state), CampaignTimeSystem(state)


def test_campaign_world_uses_warfare_units():
    state, engine, time_system = _world()
    assert state.count >= 8
    assert len(state.entity_ids) == state.count
    assert state.player_idx in range(state.count)
    assert state.factions[state.player_idx] == "player"
    assert state.read_voltage(state.player_idx, "U_manpower") > 0
    assert 0 <= state.read_voltage(state.player_idx, "U_casualties") <= 1
    assert state.get_segment_label(state.player_idx, "order")
    assert engine.tick_count == 0
    assert "wait_30" in time_system.actions


def test_order_and_tick_change_warfare_state():
    state, engine, time_system = _world()
    start_tick = state.current_tick
    assert engine.assign_order(0, "aggressive_attack")
    assert state.get_segment_label(0, "order") == "Агрессивная атака"
    time_system.advance(1800)
    assert state.current_tick == start_tick + 1
    assert any(event["message"] for event in state.tick_events)


def test_movement_target_is_translated_to_battle_cells():
    state, engine, _ = _world()
    assert engine.set_move_target(0, (128, 128))
    assert engine._targets
    engine.tick()
    assert state.det_at(0) is not None


def test_campaign_save_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(save_system, "SAVES_DIR", tmp_path)
    state, engine, time_system = _world()
    engine.tick()
    time_system.advance(1800)
    slot = "view-test"
    path = save_system.save_game(state, time_system, slot)
    assert path.endswith("view-test.json")
    assert [item["name"] for item in save_system.list_saves()] == [slot]
    snapshot = save_system.load_game(slot)
    assert snapshot["campaign"]["turn"] == state.current_tick
    assert snapshot["time_system"]["day"] >= 1
    assert save_system.delete_save(slot)
    assert save_system.list_saves() == []


def test_effect_targets_player_and_sets_order():
    from view.support.effects import EffectInterpreter

    state, _, _ = _world()
    EffectInterpreter.apply(state, {
        "targets": ["player"],
        "set_segments": {"order": "holding_defense"},
        "add_voltages": {"U_supply": -0.1},
        "log": "Тестовый эффект",
    })
    assert state.read_voltage(state.player_idx, "U_supply") < 0.82
    assert state.event_log[-1]["message"] == "Тестовый эффект"


def test_main_dispatches_view_flag(monkeypatch):
    import sys
    import types

    import main as entry

    calls = {}

    def fake_main(argv):
        calls["argv"] = list(argv)
        return 17

    fake = types.ModuleType("view.app")
    fake.main = fake_main
    monkeypatch.setitem(sys.modules, "view.app", fake)
    assert entry.main(["--view", "-f"]) == 17
    assert calls["argv"] == ["-f"]
