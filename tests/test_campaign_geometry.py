import pytest

# Сценный/графический слой view требует numpy; в окружении без него тест
# честно скипается через importorskip, а не роняет коллекцию всего прогона.
pytest.importorskip("numpy")


from view.support.geometry import (
    BREACH_PRESSURE_TICKS,
    HOLD_DEFENDER_DAILY,
    ORDERLY_RETREAT_DAILY_CAP,
)
from view.support.scenario import build_world
from view.support.world import CampaignEngine


def _world():
    state = build_world()
    return state, CampaignEngine(state)


def _player_units(state):
    return [d for d in state.units if d.side == state.player_side]


def _front_player(state):
    state.geometry.set_facing(state.player_side, (1, 0))
    state.geometry.recompute()
    return next(d for d in _player_units(state) if d.sector == "front")


def _enemy(state):
    return next(d for d in state.units if d.side != state.player_side)


def _park_enemies(state):
    for det in state.units:
        if det.side != state.player_side:
            det.position = (23, 23)


def test_brigade_has_sixteen_player_and_thirty_two_enemy_companies():
    state, _ = _world()
    player = _player_units(state)
    enemy = [d for d in state.units if d.side != state.player_side]
    assert len(player) == 16
    assert len(enemy) == 32
    assert sum(d.force for d in enemy) == pytest.approx(
        2.0 * sum(d.force for d in player)
    )
    assert state.geometry.player_side == state.player_side
    assert state.geometry.enemy_side != state.player_side

    assert state.sim.max_turns >= 7 * 180


def test_prepared_defense_is_not_three_to_one_at_any_sector():
    state, _ = _world()
    statuses = state.geometry.statuses()
    for status in statuses:
        if status.sector == "rear":
            continue
        assert status.attacker_force < 3.0 * max(
            1.0, status.defender_force
        ), status
        assert status.ratio < 1.80, status
    total_player = sum(d.force for d in _player_units(state))
    total_enemy = sum(
        d.force for d in state.units if d.side != state.player_side
    )
    assert total_enemy == pytest.approx(2.0 * total_player)


def test_sector_projection_reports_different_effective_force():
    state, _ = _world()
    front = next(d for d in _player_units(state) if d.sector == "front")
    left = next(d for d in _player_units(state) if d.sector == "left")
    rear = next(d for d in _player_units(state) if d.sector == "rear")
    assert state.projected_force(front) > state.projected_force(left)
    assert state.projected_force(left) > state.projected_force(rear)


def test_sector_loss_rates_differ_but_average_to_daily_norm():
    state, _ = _world()
    geometry = state.geometry
    rates = {
        sector: geometry.sector_daily_rate("red", sector)
        for sector in ("front", "left", "right", "rear")
    }
    assert rates["left"] > rates["front"] > rates["rear"]
    assert rates["left"] == pytest.approx(rates["right"])
    weighted = sum(
        rates[det.sector] * det.force for det in _player_units(state)
    )
    total_force = sum(det.force for det in _player_units(state))
    assert weighted / total_force == pytest.approx(
        HOLD_DEFENDER_DAILY, rel=1e-3
    )


def test_historical_attrition_is_slow_and_attackers_lose_more():
    state, engine = _world()
    for _ in range(36):
        engine.tick()
    red_losses = sum(d.losses for d in state.units if d.side == "red")
    blue_losses = sum(d.losses for d in state.units if d.side == "blue")
    red_force = sum(d.force for d in state.units if d.side == "red")
    blue_force = sum(d.force for d in state.units if d.side == "blue")
    red_fraction = red_losses / max(1.0, red_force + red_losses)
    blue_fraction = blue_losses / max(1.0, blue_force + blue_losses)
    assert state.geometry.daily_rate("red") == pytest.approx(
        HOLD_DEFENDER_DAILY
    )
    assert state.division_loss_percent() < 2.0
    assert blue_losses > red_losses
    assert blue_fraction > red_fraction
    assert state.geometry.breached == set()


def _place_red_cross(state):
    reds = _player_units(state)
    positions = [(10, 8)] * 4 + [(10, 16)] * 4 + [(14, 12)] * 4 + [(6, 12)] * 4
    for det, position in zip(reds, positions):
        det.position = position
    return reds


def test_sector_is_derived_from_facing_not_frozen_on_detachment():
    state, _ = _world()
    reds = _place_red_cross(state)

    for det in state.units:
        if det.side != state.player_side:
            det.position = (22, 12)
    state.geometry.set_facing("red", (0, -1))
    state.geometry.recompute()

    north = next(d for d in reds if d.position == (10, 8))
    south = next(d for d in reds if d.position == (10, 16))
    east = next(d for d in reds if d.position == (14, 12))
    west = next(d for d in reds if d.position == (6, 12))

    assert north.sector == "front"
    assert south.sector == "rear"
    assert east.sector == "right"
    assert west.sector == "left"

    state.geometry.set_facing("red", (1, 0))
    state.geometry.recompute()
    assert east.sector == "front"
    assert north.sector == "left"
    assert south.sector == "right"


def test_surrounded_army_has_front_on_outer_ring_and_rear_in_the_centre():
    state, _ = _world()
    reds = _player_units(state)

    outer_positions = [(14, 12), (6, 12), (10, 16), (10, 8)]
    for det in reds[4:]:
        det.position = (10, 12)
    for det, position in zip(reds[:4], outer_positions):
        det.position = position

    import math

    enemies = [d for d in state.units if d.side != state.player_side]
    for index, det in enumerate(enemies):
        angle = 2.0 * math.pi * index / len(enemies)
        det.position = (
            10 + 5 * math.cos(angle),
            12 + 5 * math.sin(angle),
        )
    state.geometry.recompute()
    frame = state.geometry._compute_frame("red")
    assert frame["surrounded"]
    assert all(det.sector == "front" for det in reds[:4])
    assert all(det.sector == "rear" for det in reds[4:])


def test_army_facing_follows_centre_of_mass_movement():
    state, _ = _world()
    reds = _player_units(state)
    before = state.geometry.facing_of("red")
    for det in reds:
        det.position = (det.position[0], det.position[1] - 3)
    state.geometry.recompute()
    after = state.geometry.facing_of("red")
    assert after[1] < 0.0
    assert abs(after[1]) > abs(before[1])


def test_loaded_facing_is_initial_direction_not_permanent_lock():
    state, _ = _world()
    reds = _player_units(state)
    state.geometry.set_facing("red", (0, -1))
    snapshot = state.geometry.snapshot()
    for det in reds:
        det.position = (det.position[0], det.position[1] - 3)
    state.geometry.load_snapshot(snapshot)
    assert state.geometry.facing_of("red") == pytest.approx((0.0, -1.0))

    for det in reds:
        det.position = (det.position[0] + 3, det.position[1])
    state.geometry.recompute()
    assert state.geometry.facing_of("red")[0] > 0.0


def test_breach_after_sustained_local_superiority_raises_loss_rate():
    state, _ = _world()

    for index, det in enumerate(_player_units(state)):
        det.position = (2 + index, 12)
    state.geometry.recompute()
    for tick in range(BREACH_PRESSURE_TICKS):
        state.geometry.update(
            engaged_sides={"red", "blue"}, tick=state.current_tick + tick
        )
    assert {"left", "right"} <= state.geometry.breached
    assert state.geometry.daily_rate("red") == pytest.approx(0.13)
    assert state.geometry.daily_rate("blue") == pytest.approx(0.08)
    assert state.geometry.statuses()[1].breached


def test_intact_front_does_not_treat_close_flank_melee_as_rout():
    state, _ = _world()
    target = _front_player(state)
    _park_enemies(state)
    enemy = _enemy(state)

    enemy.position = (target.position[0], target.position[1] - 2)
    state.geometry.recompute()
    context = state.geometry.combat_context(target)
    assert not state.geometry.breached
    assert context.kind == "intact"
    assert context.daily_rate == pytest.approx(
        state.geometry.sector_daily_rate(target.side, target.sector)
    )


def test_enemy_in_rear_before_formal_breach_is_a_local_overrun():
    state, _ = _world()
    target = _front_player(state)
    _park_enemies(state)
    enemy = _enemy(state)
    enemy.position = (target.position[0] - 1, target.position[1])
    state.geometry.recompute()
    context = state.geometry.combat_context(target)
    assert not state.geometry.breached
    assert context.kind == "overrun"
    assert context.overrun and context.routed
    assert context.daily_rate > 0.5


def test_breach_makes_holding_the_lost_line_much_costlier():
    state, _ = _world()
    target = _front_player(state)
    _park_enemies(state)
    state.geometry.breached = {target.sector}
    state.geometry.recompute()

    holding = state.geometry.combat_context(target)
    assert holding.kind == "breach_hold"
    assert holding.sector_breached
    assert holding.daily_rate > 0.20

    target.ui_order = "withdrawal"
    target.retreating = True
    target.panicked = False
    withdrawing = state.geometry.combat_context(target)
    assert withdrawing.kind == "withdrawal"
    assert withdrawing.ordered_retreat
    assert withdrawing.daily_rate <= ORDERLY_RETREAT_DAILY_CAP
    assert withdrawing.daily_rate < holding.daily_rate


def test_flank_and_rear_attacks_after_breach_scale_losses():
    state, _ = _world()
    target = _front_player(state)
    _park_enemies(state)
    enemy = _enemy(state)
    state.geometry.breached = {target.sector}
    state.geometry.recompute()

    enemy.position = (target.position[0], target.position[1] - 2)
    state.geometry.recompute()
    flank = state.geometry.combat_context(target)
    assert flank.kind == "flank"
    assert flank.flank_force > 0

    enemy.position = (target.position[0] - 3, target.position[1])
    state.geometry.recompute()
    rear = state.geometry.combat_context(target)
    assert rear.kind == "rear"
    assert rear.rear_force > 0
    assert rear.daily_rate > flank.daily_rate


def test_orderly_withdrawal_avoids_rout_losses_under_overrun():
    holding_state, _ = _world()
    withdraw_state, _ = _world()
    holding_target = _front_player(holding_state)
    withdraw_target = _front_player(withdraw_state)

    for state, target in (
        (holding_state, holding_target),
        (withdraw_state, withdraw_target),
    ):
        _park_enemies(state)
        enemy = _enemy(state)
        enemy.position = (target.position[0] - 1, target.position[1])
        state.geometry.breached = {target.sector}
        state.geometry.ticks_per_day = 1
        state.geometry.recompute()

    holding_target.ui_order = "holding_defense"
    holding_target.retreating = False
    holding_target.panicked = False
    withdraw_target.ui_order = "withdrawal"
    withdraw_target.retreating = True
    withdraw_target.panicked = False

    holding = holding_state.geometry.combat_context(holding_target)
    withdrawing = withdraw_state.geometry.combat_context(withdraw_target)
    assert holding.routed and not withdrawing.routed
    assert withdrawing.daily_rate <= ORDERLY_RETREAT_DAILY_CAP
    assert withdrawing.daily_rate < 0.25 * holding.daily_rate

    for state in (holding_state, withdraw_state):
        before = {det.name: det.force for det in state.units}
        state.geometry.apply_attrition(before, {state.player_side})
    assert withdraw_target.losses < 0.3 * holding_target.losses
    assert holding_target.losses > 5.0
    assert not withdraw_target.broken
