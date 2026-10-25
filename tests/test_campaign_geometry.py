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


def test_breach_after_sustained_local_superiority_raises_loss_rate():
    state, _ = _world()
    left = [d for d in _player_units(state) if d.sector == "left"]
    # Игрок оголил фланг: две роты из трёх ушли на фронт.
    for det in left[1:]:
        det.sector = "front"
    for tick in range(BREACH_PRESSURE_TICKS):
        state.geometry.update(
            engaged_sides={"red", "blue"}, tick=state.current_tick + tick
        )
    assert "left" in state.geometry.breached
    assert state.geometry.daily_rate("red") == pytest.approx(0.13)
    assert state.geometry.daily_rate("blue") == pytest.approx(0.08)
    assert state.geometry.statuses()[1].breached
