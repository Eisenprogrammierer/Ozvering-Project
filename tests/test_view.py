import pytest

np = pytest.importorskip("numpy")

from view.support.camp_state import camp_state_for_loss
from view.support.scenario import build_world
from view.support.storyline import loss_limit_percent
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
    EffectInterpreter.apply(
        state,
        {
            "targets": ["player"],
            "set_segments": {"order": "holding_defense"},
            "add_voltages": {"U_supply": -0.1},
            "log": "Тестовый эффект",
        },
    )
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
    assert not state.needs.apply(idx, "feed")["ok"]


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
    import warfare as W
    from view.support.world import CampaignState

    sim = W.WarfareSimulation(seed=3, turns=30)
    sim.engage_range = 3
    line = W.Detachment(
        "Р-1",
        "red",
        W._character_roster("red", "Р", ["rifleman", "veteran"], 1),
    )
    reserve = W.Detachment(
        "Р-резерв-1",
        "red",
        W._character_roster("red", "РР", ["conscript", "rifleman"], 2),
    )
    enemy = W.Detachment(
        "С-1",
        "blue",
        W._character_roster("blue", "С", ["rifleman", "veteran"], 4),
        position=(23, 23),
    )
    sim.add_detachment(line)
    sim.add_detachment(enemy)
    sim.add_stan(
        W.Stan(
            "Стан-Р",
            "red",
            reserve=[reserve],
            spawn_interval=9,
            position=(0, 8),
            rally=(1, 8),
        )
    )
    state = CampaignState(sim)
    engine = CampaignEngine(state)
    for _ in range(9):
        engine.tick()
    spawned = next(
        det
        for det in state.units
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
    sent = ls.request_convoy("ammo", risk=0.0)
    assert sent["ok"]
    assert sent["eta_minutes"] > 0

    assert ls.stock("ammo") == pytest.approx(before_ammo)
    assert ls.convoy_status_rows()
    ls._process_convoys(sent["eta_minutes"] + 1)
    assert ls.stock("ammo") > before_ammo
    assert not ls.convoys


def test_water_convoy_is_delayed_and_survives_save_load():
    state, _, _ = _world()
    ls = state.logistics
    before = ls.stock("water")
    sent = ls.request_convoy("water", risk=0.0)
    assert sent["ok"]
    assert sent["eta_minutes"] > 0
    assert ls.stock("water") == pytest.approx(before)
    assert any(row["kind"] == "water" for row in ls.convoy_status_rows())

    snapshot = state.to_snapshot()
    loaded = build_world()
    loaded.apply_snapshot(snapshot)
    assert loaded.logistics.convoy_status_rows()
    before_loaded = loaded.logistics.stock("water")
    loaded.logistics._process_convoys(10_000)
    assert loaded.logistics.stock("water") > before_loaded


def test_convoy_attack_can_delay_or_destroy_cargo():
    from view.support.logistics import Convoy

    state, _, _ = _world()
    ls = state.logistics

    class AttackRng:
        def random(self):
            return 0.0

        def uniform(self, low, high):
            return (low + high) / 2.0

        def randint(self, low, high):
            return low

    ls.rng = AttackRng()
    ls.convoy_full_loss_chance = 0.0
    before = ls.stock("water")
    convoy = Convoy(
        "water",
        {"water": 100.0},
        remaining_minutes=0.0,
        total_minutes=10.0,
        risk=1.0,
    )
    delayed = ls._arrive_convoy(convoy)
    assert delayed is convoy
    assert convoy.cargo["water"] == pytest.approx(65.0)
    assert convoy.remaining_minutes == 30.0
    assert ls.stock("water") == pytest.approx(before)

    convoy.risk = 0.0
    ls.convoys = [convoy]
    ls._process_convoys(31)
    assert ls.stock("water") == pytest.approx(before + 65.0)

    lost = Convoy(
        "water",
        {"water": 100.0},
        remaining_minutes=0.0,
        total_minutes=10.0,
        risk=1.0,
    )
    ls.convoy_full_loss_chance = 0.25
    before_loss = ls.stock("water")
    assert ls._arrive_convoy(lost) is None
    assert ls.stock("water") == pytest.approx(before_loss)


def test_commander_trait_changes_needs_logistics_and_actions():
    neutral = build_world()
    scholar = build_world()
    scholar.needs.set_commander_trait("general_scholar")
    assert scholar.needs.trait_info["label"] == "Генерал-учёный"
    assert (
        scholar.logistics.operation_cost("fortify", 1)["engineering"]
        < neutral.logistics.operation_cost("fortify", 1)["engineering"]
    )
    neutral_eta = neutral.logistics.request_convoy("water", risk=0.0)[
        "eta_minutes"
    ]
    scholar_eta = scholar.logistics.request_convoy("water", risk=0.0)[
        "eta_minutes"
    ]
    assert scholar_eta < neutral_eta

    knight = build_world()
    knight.needs.set_commander_trait("knight")
    neutral_effect = neutral.needs.status_player()["encourage"]["effects"][
        "fear"
    ]
    knight_effect = knight.needs.status_player()["encourage"]["effects"][
        "fear"
    ]
    assert knight_effect > neutral_effect

    freeloader = build_world()
    freeloader.needs.set_commander_trait("freeloader")
    neutral_food = neutral.logistics.stock("food")
    freeloader_food = freeloader.logistics.stock("food")
    neutral.logistics.on_tick(300, [])
    freeloader.logistics.on_tick(300, [])
    neutral_used = neutral_food - neutral.logistics.stock("food")
    freeloader_used = freeloader_food - freeloader.logistics.stock("food")
    assert freeloader_used > neutral_used


def test_morale_falls_under_sustained_combat():
    import random

    state, _, _ = _world()
    det = next(det for det in state.units if det.side == state.player_side)
    for character in det.characters:
        character.morale = 80.0
    det.refresh_psychology()
    for index in range(24):
        det.after_combat(under_fire=0.5, rng=random.Random(index))
    assert det.morale < 70.0


def test_fear_does_not_become_critical_by_day_two():
    state, _, _ = _world()
    commander = state.needs.commander
    for _ in range(576):
        commander.tick_needs(
            in_combat=True,
            under_fire=0.3,
            supported=0.45,
            seconds=300,
        )
    assert commander.needs["fear"] < 0.8
    assert not commander.is_dead


def test_logistics_operation_can_target_several_units_at_once():
    state, _, _ = _world()
    ls = state.logistics
    player_indices = [
        i for i, det in enumerate(state.units) if det.side == state.player_side
    ][:3]
    untouched = state.det_at(player_indices[2] + 1)
    before = ls.stock("engineering")
    result = ls.apply_operation("fortify", player_indices)
    assert result["ok"]
    assert result["count"] == 3

    assert ls.stock("engineering") == pytest.approx(before - 3)
    for idx in player_indices:
        assert state.det_at(idx).ui_fortification > 0
    assert untouched.ui_fortification == 0


def test_multi_target_logistics_is_all_or_nothing():
    state, _, _ = _world()
    ls = state.logistics
    player_indices = [
        i for i, det in enumerate(state.units) if det.side == state.player_side
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

    ls.on_tick(300, [])
    assert ls.stock("influence") > start

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
    names = [det.name for det in state.units if det.side == state.player_side][
        :3
    ]
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
    assert snapshot["campaign"]["needs"]["supplies"]["water"] == 617
    assert snapshot["campaign"]["supplies"]["water"] == 617
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
    assert state.supplies["food"] == 420
    assert state.supplies["water"] == 620


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
        state,
        None,
        {"initial_manpower": 1.0},
    )


def test_player_death_is_a_storyline_defeat_condition():
    from view.support.storyline import check_storyline_condition

    state, _, _ = _world()
    assert not check_storyline_condition(
        {"type": "player_dead"}, state, None, {}
    )
    state.needs.commander.needs["health"] = 1.0
    assert state.needs.player_dead
    assert check_storyline_condition({"type": "player_dead"}, state, None, {})
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
        (root / "configs/storylines/mvp_demo.json").read_text(encoding="utf-8")
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
        "outtro_male_1",
        "outtro_female_1",
        "outtro_2",
        "outtro_3",
        "outtro_4",
        "outtro_5",
        "outtro_6",
    }
    for name in images:
        assert list((root / "assets/images/scenes").glob(name + ".*"))


def test_mvp_loss_threshold_allows_meaningful_battle():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = json.loads(
        (root / "configs/storylines/mvp_demo.json").read_text(encoding="utf-8")
    )
    loss_condition = next(
        condition
        for condition in data["lose_conditions"][0]["conditions"]
        if condition["type"] == "manpower_loss_above"
    )
    assert loss_condition["value"] == pytest.approx(0.25)


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


def _center_of(units):
    alive = [det for det in units if not getattr(det, "broken", False)]
    return (
        sum(det.position[0] for det in alive) / max(1, len(alive)),
        sum(det.position[1] for det in alive) / max(1, len(alive)),
    )


def test_enemy_default_plan_advances_without_player_orders():
    state, engine, _ = _world()
    blue = [det for det in state.units if det.side == "blue"]
    before = _center_of(blue)
    assert engine.plan_for("blue").mode == "advance"
    for _ in range(8):
        engine.tick()
    after = _center_of(blue)
    assert after[0] < before[0] - 0.5


def test_hold_plan_assigns_line_and_moves_army_to_it():
    state, engine, _ = _world()
    red = [det for det in state.units if det.side == state.player_side]
    before = _center_of(red)
    assert engine.set_auto_plan("hold", target=(14, 12))
    plan = engine.plan_for()
    assert plan.active and plan.mode == "hold"
    assert plan.line is not None
    assert plan.line[0][0] >= 13
    assert any(engine._plan_goals.get(det.name) is not None for det in red)
    for _ in range(4):
        engine.tick()
    after = _center_of(red)
    assert after[0] > before[0] + 0.2


def test_advance_plan_moves_all_player_companies():
    state, engine, _ = _world()
    red = [det for det in state.units if det.side == state.player_side]
    before = _center_of(red)
    assert engine.set_auto_plan("advance", target=(20, 12))
    assert engine.plan_for().mode == "advance"
    assert all(det.ui_order == "attack" for det in red)
    for _ in range(6):
        engine.tick()
    after = _center_of(red)
    assert after[0] > before[0] + 0.4


def test_manual_order_exempts_company_until_plan_reactivated():
    state, engine, _ = _world()
    assert engine.set_auto_plan("advance", target=(20, 12))
    det = state.units[0]
    idx = state.units.index(det)
    assert engine.assign_order(idx, "holding_defense")
    assert det.name in state.plan_exempt
    assert det.name not in engine._plan_goals
    assert det.name not in engine._targets
    engine.tick()
    assert det.name not in engine._plan_goals
    manual_order = engine._ui_orders.get(idx)
    assert engine.set_auto_plan("hold", target=(12, 12), keep_exemptions=True)
    assert det.name in state.plan_exempt
    assert manual_order is not None and manual_order.active
    assert idx in engine._ui_orders
    assert engine.set_auto_plan("hold")
    assert det.name not in state.plan_exempt
    assert engine.plan_for().mode == "hold"
    assert manual_order is not None and not manual_order.active
    assert idx not in engine._ui_orders


def test_contact_produces_more_than_static_attrition():
    state, engine, _ = _world()
    for _ in range(25):
        engine.tick()
    red_before = _center_of(
        [det for det in state.units if det.side == state.player_side]
    )
    blue_before = _center_of(
        [det for det in state.units if det.side != state.player_side]
    )
    positions = {det.name: det.position for det in state.units}
    for _ in range(20):
        engine.tick()
    moved = sum(
        1 for det in state.units if det.position != positions.get(det.name)
    )
    assert moved > 0
    red_after = _center_of(
        [det for det in state.units if det.side == state.player_side]
    )
    blue_after = _center_of(
        [det for det in state.units if det.side != state.player_side]
    )
    front_shift = abs(red_after[0] - red_before[0]) + abs(
        blue_after[0] - blue_before[0]
    )
    assert front_shift > 0.2


def test_auto_plan_survives_snapshot_round_trip():
    state, engine, _ = _world()
    assert engine.set_auto_plan("hold", target=(13, 11))
    det = state.units[0]
    engine.assign_order(state.units.index(det), "rest")
    snapshot = state.to_snapshot()

    loaded = build_world()
    loaded.apply_snapshot(snapshot)
    assert loaded.auto_plans["red"].mode == "hold"
    assert loaded.auto_plans["red"].line is not None
    assert det.name in loaded.plan_exempt

    loaded_engine = CampaignEngine(loaded)
    assert loaded_engine.plan_for().mode == "hold"
    assert loaded_engine.plan_for().line is not None
    assert loaded_engine._plan_orders.get("red") is not None


def test_loss_limit_percent_reads_nested_storyline_condition():
    storyline = {
        "lose_conditions": [
            {
                "type": "any_of",
                "conditions": [
                    {"type": "manpower_loss_above", "value": 0.25},
                    {"type": "all_player_units_destroyed"},
                ],
            }
        ],
    }
    assert loss_limit_percent(storyline) == 25
    assert (
        loss_limit_percent(
            {
                "lose_conditions": [
                    {"type": "manpower_loss_above", "value": 0.2}
                ]
            }
        )
        == 20
    )
    assert (
        loss_limit_percent(
            {
                "lose_conditions": [
                    {"type": "manpower_loss_above", "value": 0.45}
                ]
            }
        )
        == 45
    )

    assert loss_limit_percent({"lose_conditions": []}) == 45


@pytest.mark.parametrize("limit", [20, 25, 45])
def test_camp_stages_use_whole_loss_limit_range(limit):
    fresh_end = int(limit * 0.40) - 1
    wounded_start = int(limit * 0.40)
    wounded_end = int(limit * 0.80)
    critical_start = wounded_end + 1

    assert camp_state_for_loss(0, limit) == "fresh"
    assert camp_state_for_loss(fresh_end, limit) == "fresh"
    assert camp_state_for_loss(wounded_start, limit) == "wounded"
    assert camp_state_for_loss(wounded_end, limit) == "wounded"
    assert camp_state_for_loss(critical_start, limit) == "critical"
    assert camp_state_for_loss(limit - 1, limit) == "critical"
    assert camp_state_for_loss(limit, limit) == "critical"
    assert {
        camp_state_for_loss(0, limit),
        camp_state_for_loss(wounded_start, limit),
        camp_state_for_loss(critical_start, limit),
    } == {"fresh", "wounded", "critical"}


def test_morning_camp_content_has_distinct_texts_and_existing_assets():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    data = json.loads(
        (root / "configs/content/mandatory_scenes.json").read_text(
            encoding="utf-8"
        )
    )
    morning = data["morning_inspection"]
    expected = {"fresh", "wounded", "critical"}
    assert set(morning["backgrounds"]) == expected
    assert set(morning["texts"]) == expected
    assert len(set(morning["backgrounds"].values())) == 3
    for asset in morning["backgrounds"].values():
        assert list((root / "assets/images").glob(asset + ".*")), asset
