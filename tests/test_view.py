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
    # 30 игровых минут при такте боя в 5 минут = 6 тактов.
    assert state.current_tick == start_tick + 6
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


def test_needs_actions_consume_supplies_and_restore_needs():
    state, _, _ = _world()
    idx = state.player_idx
    det = state.det_at(idx)
    before = det.needs_summary()["hunger"]
    before_food = state.supplies["food"]
    result = state.needs.apply(idx, "feed")
    assert result["ok"]
    assert state.supplies["food"] == before_food - 4
    assert det.needs_summary()["hunger"] < before
    assert not state.needs.apply(idx, "feed")["ok"]  # кулдаун


def test_evening_and_morning_mandatory_scenes_advance_day():
    state, engine, time_system = _world()
    time_system.advance(75600 - time_system.seconds_of_day)
    assert time_system.pending_mandatory_scene == "evening_inspection"
    time_system.complete_mandatory_scene("evening_inspection")
    time_system.choose_night_duty(False)
    assert time_system.day == 2
    assert time_system.pending_mandatory_scene == "morning_inspection"
    time_system.complete_mandatory_scene("morning_inspection")
    assert time_system.pending_mandatory_scene is None


def test_time_advances_by_minutes_and_combat_on_five_minute_ticks():
    state, engine, time_system = _world()
    start = time_system.seconds_of_day
    time_system.advance(60)
    assert time_system.seconds_of_day == start + 60
    assert state.current_tick == 0
    time_system.advance(240)
    assert time_system.seconds_of_day == start + 300
    assert state.current_tick == 1


def test_division_losses_accumulate_and_are_reported():
    state, engine, _ = _world()
    for _ in range(40):
        engine.tick()
    player = [det for det in state.units if det.side == state.player_side]
    assert any(det.losses > 0 for det in player)
    assert state.division_loss_percent() > 0
    assert state.read_voltage(state.player_idx, "U_casualties") > 0


def test_reserve_spawn_does_not_create_phantom_losses():
    """Выход резерва не должен считаться безвозвратными потерями.

    До исправления резерв тикал как самостоятельная среда внутри стана,
    выходил с силой 28.8 вместо штатных 12, а на следующем такте UI
    ограничивал силу до штата и записывал разницу (11) в потери. Из-за
    этого потери дивизии прыгали с 1% до 18% за один такт.

    Бригадный сценарий больше не содержит станов, поэтому регрессия
    проверяется на синтетическом мире с явным резервом.
    """
    import warfare as W
    from view.support.world import CampaignState

    sim = W.WarfareSimulation(seed=3, turns=30)
    sim.engage_range = 3
    line = W.Detachment(
        "Р-1", "red",
        W._character_roster("red", "Р", ["rifleman", "veteran"], 1),
    )
    reserve = W.Detachment(
        "Р-резерв-1", "red",
        W._character_roster("red", "РР", ["conscript", "rifleman"], 2),
    )
    enemy = W.Detachment(
        "С-1", "blue",
        W._character_roster("blue", "С", ["rifleman", "veteran"], 4),
        position=(23, 23),
    )
    sim.add_detachment(line)
    sim.add_detachment(enemy)
    sim.add_stan(W.Stan(
        "Стан-Р", "red", reserve=[reserve],
        spawn_interval=9, position=(0, 8), rally=(1, 8),
    ))
    state = CampaignState(sim)
    engine = CampaignEngine(state)
    for _ in range(9):
        engine.tick()
    spawned = next(
        det for det in state.units
        if det.side == state.player_side and "резерв" in det.name
    )
    assert spawned.force == pytest.approx(spawned.start_force)
    assert spawned.losses == pytest.approx(0.0)
    before = state.division_loss_percent()
    engine.tick()
    assert spawned.force == pytest.approx(spawned.start_force)
    assert spawned.losses == pytest.approx(0.0)
    assert state.division_loss_percent() - before < 5


def test_force_and_losses_stay_within_roster():
    state, engine, _ = _world()
    for _ in range(60):
        engine.tick()
    for idx, det in enumerate(state.units):
        if det.side != state.player_side:
            continue
        start = state._start_force(det)
        assert det.force <= start
        assert det.losses <= max(0.0, start - 1.0)
        assert 0.0 <= state.read_voltage(idx, "U_casualties") <= 1.0


def test_needs_grow_with_elapsed_time_not_per_combat_tick():
    state, _, _ = _world()
    character = state.det_at(state.player_idx).characters[0]
    character.needs["hunger"] = 0.2
    character.tick_needs(seconds=300)
    short_gain = character.needs["hunger"] - 0.2
    character.needs["hunger"] = 0.2
    character.tick_needs(seconds=1800)
    long_gain = character.needs["hunger"] - 0.2
    assert short_gain > 0
    assert long_gain > 5.0 * short_gain


def test_evening_scene_uses_hq_evening_background():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = json.loads(
        (root / "configs/content/mandatory_scenes.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["evening_inspection"]["background"] == "scenes/hq_evening"
    assert (root / "assets/images/scenes/hq_evening.jpg").exists()


def test_withdrawal_order_and_return_to_defense():
    state, engine, _ = _world()
    idx = state.player_idx
    det = state.det_at(idx)
    assert engine.assign_order(idx, "withdrawal")
    assert det.retreating
    assert det.ui_order == "withdrawal"
    assert engine._targets.get(det.name) is not None
    assert engine.assign_order(idx, "holding_defense")
    assert not det.retreating
    assert det.ui_order == "holding_defense"


def test_logistics_operation_and_convoy_change_stocks():
    state, _, _ = _world()
    idx = state.player_idx
    ls = state.logistics
    before_engineering = ls.stock("engineering")
    result = ls.apply_operation("fortify", idx)
    assert result["ok"]
    assert ls.stock("engineering") < before_engineering
    assert state.det_at(idx).ui_fortification > 0
    before_ammo = ls.stock("ammo")
    assert ls.request_convoy("ammo")["ok"]
    assert ls.stock("ammo") > before_ammo


def test_logistics_operation_can_target_several_units_at_once():
    state, _, _ = _world()
    ls = state.logistics
    player_indices = [
        i for i, det in enumerate(state.units)
        if det.side == state.player_side
    ][:3]
    untouched = state.det_at(player_indices[2] + 1)
    before = ls.stock("engineering")
    result = ls.apply_operation("fortify", player_indices)
    assert result["ok"]
    assert result["count"] == 3
    # Цена умножается на число рот; четвёртая рота остаётся без эффекта.
    assert ls.stock("engineering") == pytest.approx(before - 3)
    for idx in player_indices:
        assert state.det_at(idx).ui_fortification > 0
    assert untouched.ui_fortification == 0


def test_multi_target_logistics_is_all_or_nothing():
    state, _, _ = _world()
    ls = state.logistics
    player_indices = [
        i for i, det in enumerate(state.units)
        if det.side == state.player_side
    ][:3]
    ls.supplies["engineering"] = 2.0
    result = ls.apply_operation("fortify", player_indices)
    assert not result["ok"]
    assert ls.stock("engineering") == pytest.approx(2.0)
    assert all(
        state.det_at(idx).ui_fortification == 0 for idx in player_indices
    )


def test_passive_influence_and_free_convoy():
    state, _, _ = _world()
    ls = state.logistics
    assert ls.influence_per_hour > 0
    start = ls.stock("influence")
    events_before = len(state.event_log)
    # Доход дробный и виден уже после первого пятиминутного такта.
    ls.on_tick(300, [])
    assert ls.stock("influence") > start
    # 36 тактов по 300 секунд = 3 игровых часа: +12 влияния и одна
    # автоколонна. Автоколонна не тратит влияние.
    for _ in range(35):
        ls.on_tick(300, [])
    assert ls.stock("influence") == pytest.approx(start + 12.0)
    assert ls._free_convoy_index == 1
    assert ls.next_free_convoy_minutes == pytest.approx(180.0)
    assert any(
        "Автоколонна" in event.get("message", "")
        for event in state.event_log[events_before:]
    )


def test_groups_are_saved_with_campaign_state():
    state, _, _ = _world()
    names = [
        det.name for det in state.units
        if det.side == state.player_side
    ][:3]
    state.groups[2] = names
    snapshot = state.to_snapshot()
    assert snapshot["groups"]["2"] == names
    state.groups[2] = []
    state.apply_snapshot(snapshot)
    assert state.groups[2] == names


def test_time_system_advance_stops_at_evening_boundary():
    state, engine, time_system = _world()
    time_system.advance(75600 - time_system.seconds_of_day + 3600)
    assert time_system.seconds_of_day == 75600
    assert time_system.pending_mandatory_scene == "evening_inspection"


def test_campaign_save_keeps_needs_state(tmp_path, monkeypatch):
    monkeypatch.setattr(save_system, "SAVES_DIR", tmp_path)
    state, engine, time_system = _world()
    assert state.needs.apply(state.player_idx, "water")["ok"]
    save_system.save_game(state, time_system, "needs-test")
    snapshot = save_system.load_game("needs-test")
    assert snapshot["campaign"]["needs"]["supplies"]["water"] == 137
    assert snapshot["campaign"]["supplies"]["water"] == 137
    needs = snapshot["campaign"]["detachments"][state.player_idx]["needs"]
    assert needs and "thirst" in needs[0]


def test_old_campaign_save_without_needs_keeps_default_supplies():
    state, _, _ = _world()
    snapshot = state.to_snapshot()
    snapshot.pop("needs", None)
    snapshot.pop("supplies", None)
    for item in snapshot["detachments"]:
        item.pop("needs", None)
    state.apply_snapshot(snapshot)
    assert state.supplies["food"] == 120
    assert state.supplies["water"] == 140


def test_needs_actions_cover_all_sixteen_needs():
    import warfare as W

    from view.support.needs import NEED_ACTIONS

    covered = set()
    for definition in NEED_ACTIONS.values():
        covered.update(definition["effects"])
    assert covered == set(W.NEEDS)


def test_player_commander_needs_are_separate_from_units():
    state, _, _ = _world()
    det = state.det_at(state.player_idx)
    commander_before = state.needs.player_needs_summary()["hunger"]
    unit_before = det.needs_summary()["hunger"]
    food_before = state.supplies["food"]
    result = state.needs.apply_player("feed")
    assert result["ok"]
    assert state.needs.player_needs_summary()["hunger"] < commander_before
    assert det.needs_summary()["hunger"] == pytest.approx(unit_before)
    assert state.supplies["food"] == food_before - 1


def test_units_self_care_through_logistics():
    state, _, _ = _world()
    det = state.det_at(state.player_idx)
    for character in det.characters:
        character.needs["hunger"] = 1.0
        character.needs["thirst"] = 1.0
    state.logistics.on_tick(300, [])
    assert det.needs_summary()["hunger"] < 1.0
    assert det.needs_summary()["thirst"] < 1.0


def test_manpower_loss_condition_uses_division_losses():
    from view.support.storyline import check_storyline_condition

    state, _, _ = _world()
    for det in state.units:
        if det.side != state.player_side:
            continue
        det.losses = state._start_force(det) * 0.3
    assert check_storyline_condition(
        {"type": "manpower_loss_above", "value": 0.2},
        state, None, {"initial_manpower": 1.0},
    )


def test_player_death_is_a_storyline_defeat_condition():
    from view.support.storyline import check_storyline_condition

    state, _, _ = _world()
    assert not check_storyline_condition(
        {"type": "player_dead"}, state, None, {}
    )
    state.needs.commander.needs["health"] = 1.0
    assert state.needs.player_dead
    assert check_storyline_condition(
        {"type": "player_dead"}, state, None, {}
    )
    snapshot = state.to_snapshot()
    state.needs.commander.needs["health"] = 0.0
    state.needs.commander.dead = False
    state.apply_snapshot(snapshot)
    assert state.needs.player_dead


def test_mvp_win_scene_uses_existing_outtro_assets():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = json.loads(
        (root / "configs/storylines/mvp_demo.json").read_text(
            encoding="utf-8"
        )
    )
    slides = data["win_scene"]["slides"]
    images = []
    for slide in slides:
        if "image" in slide:
            images.append(slide["image"])
        for variant in slide.get("variants", {}).values():
            if variant.get("image"):
                images.append(variant["image"])
    assert len(slides) == 6
    assert set(images) == {
        "outtro_male_1", "outtro_female_1", "outtro_2", "outtro_3",
        "outtro_4", "outtro_5", "outtro_6",
    }
    for name in images:
        assert list((root / "assets/images/scenes").glob(name + ".*"))


def test_mvp_loss_threshold_allows_meaningful_battle():
    """45% — дивизия теряет боеспособность, но бой не обрывается сразу."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = json.loads(
        (root / "configs/storylines/mvp_demo.json").read_text(
            encoding="utf-8"
        )
    )
    loss_condition = next(
        condition for condition in data["lose_conditions"][0]["conditions"]
        if condition["type"] == "manpower_loss_above"
    )
    assert loss_condition["value"] == pytest.approx(0.45)


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
