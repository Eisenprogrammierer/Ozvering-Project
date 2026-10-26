"""Геометрия бригадного боя и исторические суточные потери."""

import pytest

from view.support.geometry import (
    BREACH_PRESSURE_TICKS, HOLD_DEFENDER_DAILY,
)
from view.support.scenario import build_world
from view.support.world import CampaignEngine


def _world():
    state = build_world()
    return state, CampaignEngine(state)


def _player_units(state):
    return [d for d in state.units if d.side == state.player_side]


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
    # Запас на семь кампанийных суток по 180 пятиминутных тактов.
    assert state.sim.max_turns >= 7 * 180


def test_prepared_defense_is_not_three_to_one_at_any_sector():
    """Двукратное общее превосходство не даёт троекратного на участке."""
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
    front = next(
        d for d in _player_units(state) if d.sector == "front"
    )
    left = next(
        d for d in _player_units(state) if d.sector == "left"
    )
    rear = next(
        d for d in _player_units(state) if d.sector == "rear"
    )
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
        rates[det.sector] * det.force
        for det in _player_units(state)
    )
    total_force = sum(det.force for det in _player_units(state))
    assert weighted / total_force == pytest.approx(
        HOLD_DEFENDER_DAILY, rel=1e-3
    )


def test_historical_attrition_is_slow_and_attackers_lose_more():
    """Три часа боя: потери обороны далеки от «дивизия уничтожена»."""
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
    """Поставить красных крестом: север/юг/восток/запад от центра (10, 12)."""
    reds = _player_units(state)
    positions = (
        [(10, 8)] * 4 + [(10, 16)] * 4 + [(14, 12)] * 4 + [(6, 12)] * 4
    )
    for det, position in zip(reds, positions):
        det.position = position
    return reds


def test_sector_is_derived_from_facing_not_frozen_on_detachment():
    """Армия смотрит на север, а масса врага — на востоке: это фланг."""
    state, _ = _world()
    reds = _place_red_cross(state)
    # Противник сосредоточен восточнее красных.
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
    assert east.sector == "right"      # восточный фланг
    assert west.sector == "left"
    # Смена фронта пересчитывает проекции: та же рота уже не «тыл».
    state.geometry.set_facing("red", (1, 0))
    state.geometry.recompute()
    assert east.sector == "front"
    assert north.sector == "left"
    assert south.sector == "right"


def test_surrounded_army_has_front_on_outer_ring_and_rear_in_the_centre():
    state, _ = _world()
    reds = _player_units(state)
    # Четыре роты на внешнем кольце, остальные — в центре строя.
    outer_positions = [(14, 12), (6, 12), (10, 16), (10, 8)]
    for det in reds[4:]:
        det.position = (10, 12)
    for det, position in zip(reds[:4], outer_positions):
        det.position = position
    # Синие охватывают красных по всему кругу.
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
    # После загрузки армия снова может повернуть вслед за движением.
    for det in reds:
        det.position = (det.position[0] + 3, det.position[1])
    state.geometry.recompute()
    assert state.geometry.facing_of("red")[0] > 0.0


def test_breach_after_sustained_local_superiority_raises_loss_rate():
    state, _ = _world()
    # Игрок вытянул все роты в одну линию вдоль фронта: фланги остались
    # без защитников. Проекции вычисляются из позиций, поэтому просто
    # «переставить метку» уже нельзя — двигаем сами роты.
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
