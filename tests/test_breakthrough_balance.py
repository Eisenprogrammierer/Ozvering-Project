from types import SimpleNamespace

import pytest

# Сценный/графический слой view требует numpy; в окружении без него тест
# честно скипается через importorskip, а не роняет коллекцию всего прогона.
pytest.importorskip("numpy")


from view.support.geometry import (
    ENCIRCLE_MAX_GAP,
    ENCIRCLE_SURRENDER_TICKS,
    HOLD_DEFENDER_DAILY,
    MAX_ENCIRCLED_DAILY_RATE,
    ORDERLY_RETREAT_DAILY_CAP,
)
from view.support.scenario import build_world
from view.support.world import CampaignEngine


def _world():
    state = build_world()
    return state, CampaignEngine(state)


def _player_units(state):
    return [d for d in state.units if d.side == state.player_side]


def _enemy_units(state):
    return [d for d in state.units if d.side != state.player_side]


def _park_enemies(state, position=(240, 240)):
    for det in _enemy_units(state):
        det.position = position
    state.geometry.recompute()


def _front_target(state):
    state.geometry.set_facing(state.player_side, (1, 0))
    state.geometry.recompute()
    return next(d for d in _player_units(state) if d.sector == "front")


def _force_before(state):
    return {det.name: det.force for det in state.units}


def _apply_tick(state):
    state.geometry.apply_attrition(_force_before(state), {state.player_side})


def _place_ring(state, target, positions=None):
    _park_enemies(state)
    enemies = _enemy_units(state)
    x, y = target.position
    if positions is None:
        positions = [
            (x + 1, y),
            (x, y + 1),
            (x - 1, y),
            (x, y - 1),
        ]
    for enemy, position in zip(enemies, positions):
        enemy.position = position
    state.geometry.recompute()
    return enemies[: len(positions)]


def _one_day_loss(state, *, breached=False):
    _park_enemies(state)
    state.geometry.set_facing(state.player_side, (1, 0))
    if breached:
        state.geometry.breached = {"front"}
    state.geometry.ticks_per_day = 1
    state.geometry.recompute()
    total_start = sum(d.start_force for d in _player_units(state))
    _apply_tick(state)
    losses = sum(
        float(getattr(d, "losses", 0.0)) for d in _player_units(state)
    )
    return total_start, losses


def test_bearing_uses_forward_flank_and_rear_cones_not_map_quadrants():
    state, _ = _world()
    geometry = state.geometry
    target = SimpleNamespace(position=(10.0, 10.0))
    facing = (1.0, 0.0)

    cases = {
        (13, 10): "front",
        (12, 12): "front",
        (12, 14): "flank",
        (10, 14): "flank",
        (8, 13): "flank",
        (7, 12): "rear",
        (8, 10): "rear",
    }
    for position, expected in cases.items():
        enemy = SimpleNamespace(position=position)
        bearing, _ = geometry._bearing(target, enemy, facing)
        assert bearing == expected, (position, bearing)


def test_intact_day_costs_exactly_the_historical_defender_share():
    state, _ = _world()
    total_start, losses = _one_day_loss(state, breached=False)
    assert losses == pytest.approx(total_start * HOLD_DEFENDER_DAILY)
    assert state.division_loss_percent() == pytest.approx(
        100.0 * HOLD_DEFENDER_DAILY, abs=0.01
    )
    assert not any(d.broken for d in _player_units(state))


def test_breach_day_is_more_than_four_times_costlier_than_intact_day():
    intact_state, _ = _world()
    breach_state, _ = _world()
    total_start, intact_losses = _one_day_loss(intact_state, breached=False)
    _, breach_losses = _one_day_loss(breach_state, breached=True)

    assert breach_losses / intact_losses > 4.0
    assert breach_losses / total_start >= 0.17
    assert not any(d.broken for d in _player_units(breach_state))
    contexts = [
        breach_state.geometry.combat_context(d)
        for d in _player_units(breach_state)
    ]
    hold = [c for c in contexts if c.kind == "breach_hold"]
    assert hold
    assert all(c.daily_rate > 0.30 for c in hold)


def test_four_enemies_on_one_side_do_not_form_an_encirclement():
    state, _ = _world()
    target = _front_target(state)
    x, y = target.position
    _place_ring(
        state,
        target,
        [
            (x + 1, y),
            (x + 2, y),
            (x + 1, y + 1),
            (x + 1, y - 1),
        ],
    )
    context = state.geometry.combat_context(target)

    assert not context.encircled
    assert context.encircle_gap > ENCIRCLE_MAX_GAP
    assert context.kind == "intact"
    for _ in range(ENCIRCLE_SURRENDER_TICKS):
        _apply_tick(state)
    assert not target.broken


def test_three_sides_leave_a_corridor_and_do_not_start_the_clock():
    state, _ = _world()
    target = _front_target(state)
    x, y = target.position
    _place_ring(
        state,
        target,
        [
            (x + 1, y),
            (x, y + 1),
            (x, y - 1),
        ],
    )
    context = state.geometry.combat_context(target)

    assert not context.encircled
    assert context.encircle_gap > ENCIRCLE_MAX_GAP
    _apply_tick(state)
    assert target.name not in state.geometry.encircle_ticks
    for _ in range(ENCIRCLE_SURRENDER_TICKS + 2):
        _apply_tick(state)
    assert not target.broken


def test_full_ring_is_detected_even_without_formal_front_breach():
    state, _ = _world()
    target = _front_target(state)
    enemies = _place_ring(state, target)
    context = state.geometry.combat_context(target)

    assert not state.geometry.breached
    assert context.encircled
    assert context.overrun and context.routed
    assert context.encircle_gap <= ENCIRCLE_MAX_GAP
    assert context.encircle_force == pytest.approx(
        sum(e.force for e in enemies)
    )
    assert context.daily_rate > 1.0
    assert context.daily_rate <= MAX_ENCIRCLED_DAILY_RATE
    assert "ОКРУЖЕНИЕ" in context.label
    assert context.surrender_in == ENCIRCLE_SURRENDER_TICKS


def test_encircled_company_capitulates_on_the_twelfth_tick():
    state, _ = _world()
    target = _front_target(state)
    _place_ring(state, target)
    state.geometry.ticks_per_day = 180
    start = target.start_force
    initial_div_loss = state.division_loss_percent()

    for tick in range(1, ENCIRCLE_SURRENDER_TICKS):
        _apply_tick(state)
        assert not target.broken
        assert state.geometry.encircle_ticks[target.name] == tick
        context = state.geometry.combat_context(target)
        assert context.encircled
        assert context.surrender_in == ENCIRCLE_SURRENDER_TICKS - tick

    _apply_tick(state)
    assert target.broken
    assert target.surrendered
    assert target.force == pytest.approx(1.0)
    assert target.losses == pytest.approx(start - 1.0)
    assert target.morale <= 5.0
    assert target.panicked
    assert state.division_loss_percent() > initial_div_loss + 5.0

    surrender_events = [
        event["message"]
        for event in state.event_log
        if "капитулировала" in event["message"]
    ]
    assert len(surrender_events) == 1
    assert target.name in surrender_events[0]

    losses_after = target.losses
    _apply_tick(state)
    assert target.losses == pytest.approx(losses_after)
    assert target.force == pytest.approx(1.0)
    assert (
        len(
            [
                event
                for event in state.event_log
                if "капитулировала" in event["message"]
            ]
        )
        == 1
    )


def test_withdrawal_order_does_not_save_a_fully_encircled_company():
    state, _ = _world()
    target = _front_target(state)
    _place_ring(state, target)
    target.ui_order = "withdrawal"
    target.retreating = True
    target.panicked = False
    state.geometry.ticks_per_day = 180

    context = state.geometry.combat_context(target)
    assert context.ordered_retreat
    assert context.encircled
    assert context.routed
    assert context.daily_rate > 5.0 * ORDERLY_RETREAT_DAILY_CAP

    for _ in range(ENCIRCLE_SURRENDER_TICKS):
        _apply_tick(state)
    assert target.broken
    assert target.surrendered


def test_reopening_a_corridor_resets_the_surrender_clock():
    state, _ = _world()
    target = _front_target(state)
    enemies = _place_ring(state, target)

    for _ in range(6):
        _apply_tick(state)
    assert state.geometry.encircle_ticks[target.name] == 6
    assert not target.broken

    enemies[0].position = (240, 240)
    state.geometry.recompute()
    _apply_tick(state)

    assert target.name not in state.geometry.encircle_ticks
    assert not target.broken
    context = state.geometry.combat_context(target)
    assert not context.encircled
    assert context.encircle_gap > ENCIRCLE_MAX_GAP

    for _ in range(ENCIRCLE_SURRENDER_TICKS):
        _apply_tick(state)
    assert not target.broken


def test_enemy_context_stays_attacker_inside_the_player_ring():
    state, _ = _world()
    target = _front_target(state)
    enemies = _place_ring(state, target)
    enemy = enemies[0]
    context = state.geometry.combat_context(enemy)

    assert context.kind == "attacker"
    assert context.daily_rate == pytest.approx(
        state.geometry.daily_rate(enemy.side)
    )
    assert not context.encircled
    assert context.encircle_ticks == 0


def test_surrender_and_encirclement_state_survive_snapshot():
    state, _ = _world()
    target = _front_target(state)
    _place_ring(state, target)
    state.geometry.ticks_per_day = 180
    for _ in range(6):
        _apply_tick(state)
    clock_snapshot = state.geometry.snapshot()
    assert clock_snapshot["encircle_ticks"][target.name] == 6

    clone, _ = _world()
    clone.geometry.load_snapshot(clock_snapshot)
    assert clone.geometry.encircle_ticks[target.name] == 6

    for _ in range(ENCIRCLE_SURRENDER_TICKS - 6):
        _apply_tick(state)
    assert target.broken and target.surrendered
    snapshot = state.to_snapshot()
    item = next(
        row for row in snapshot["detachments"] if row["name"] == target.name
    )
    assert item["surrendered"] is True
    assert item["broken"] is True
    assert item["force"] == pytest.approx(1.0)
    assert item["losses"] == pytest.approx(target.start_force - 1.0)

    restored, _ = _world()
    restored.apply_snapshot(snapshot)
    restored_target = next(d for d in restored.units if d.name == target.name)
    assert restored_target.broken
    assert restored_target.surrendered
    assert restored_target.force == pytest.approx(1.0)
    assert restored_target.losses == pytest.approx(target.start_force - 1.0)


def test_no_engaged_side_means_no_attrition_and_no_clock():
    state, _ = _world()
    target = _front_target(state)
    _place_ring(state, target)
    state.geometry.ticks_per_day = 1
    before = _force_before(state)
    state.geometry.apply_attrition(before, set())

    assert all(d.losses == pytest.approx(0.0) for d in state.units)
    assert not state.geometry.encircle_ticks
    assert not target.broken


def test_mauled_encircled_company_collapses_without_waiting_for_the_clock():
    state, _ = _world()
    target = _front_target(state)
    _place_ring(state, target)
    start = target.start_force
    target.force = start * 0.30
    target.losses = start - target.force
    state.geometry.ticks_per_day = 180

    context = state.geometry.combat_context(target)
    assert context.encircled
    assert target.force / start < 0.35
    _apply_tick(state)

    assert target.broken
    assert target.surrendered
    assert target.force == pytest.approx(1.0)
    assert target.losses == pytest.approx(start - 1.0)


def test_one_day_step_marks_encircled_capitulation_not_silent_break():
    state, _ = _world()
    target = _front_target(state)
    _place_ring(state, target)
    state.geometry.ticks_per_day = 1
    start = target.start_force

    _apply_tick(state)

    assert target.broken
    assert target.surrendered
    assert target.force == pytest.approx(1.0)
    assert target.losses == pytest.approx(start - 1.0)
    assert any(
        "капитулировала" in event["message"] for event in state.event_log
    )
