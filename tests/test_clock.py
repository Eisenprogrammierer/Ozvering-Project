import pytest

from core41 import (
    BASE_TICK_SECONDS,
    DEFAULT_SPEED,
    SPEEDS,
    SimulationClock,
    normalize_speed,
    speed_label,
)


def test_default_clock_runs_one_tick_per_second():
    clock = SimulationClock()
    assert DEFAULT_SPEED == 1.0
    assert BASE_TICK_SECONDS == 1.0
    assert clock.speed == 1.0
    assert clock.ticks_per_sec == 1.0
    assert clock.seconds_per_tick == 1.0
    assert not clock.paused


def test_normalize_speed_snaps_to_supported_values():
    assert normalize_speed(0) == 0.0
    assert normalize_speed(-4) == 0.0
    assert normalize_speed(1) == 1.0
    assert normalize_speed(3) == 2.0
    assert normalize_speed(5) == 4.0
    assert normalize_speed(99) == 16.0
    assert SPEEDS == (0.0, 1.0, 2.0, 4.0, 8.0, 16.0)


def test_speed_labels():
    assert speed_label(0) == "PAUSE"
    assert speed_label(1) == "1x"
    assert speed_label(16) == "16x"


def test_advance_accumulates_whole_ticks():
    clock = SimulationClock(speed=1)
    assert clock.advance(0.5) == 0
    assert clock.advance(0.5) == 1
    assert clock.ticks == 1
    assert clock.acc == pytest.approx(0.0)


def test_advance_scales_with_speed():
    clock = SimulationClock(speed=16)
    assert clock.advance(0.25) == 4
    assert clock.ticks == 4
    assert clock.seconds_per_tick == pytest.approx(1.0 / 16.0)


def test_paused_clock_does_not_advance_and_keeps_selected_speed():
    clock = SimulationClock(speed=4)
    clock.pause("test")
    assert clock.paused
    assert clock.pause_reason == "test"
    assert clock.selected_speed == 4
    assert clock.advance(10.0) == 0
    clock.resume()
    assert not clock.paused
    assert clock.speed == 4


def test_speed_can_be_selected_while_paused_without_resuming():
    clock = SimulationClock(speed=1)
    clock.pause()
    clock.faster()
    assert clock.paused
    assert clock.selected_speed == 2
    assert clock.speed == 0


def test_faster_and_slower_walk_through_speeds():
    clock = SimulationClock(speed=1)
    assert clock.faster() == 2
    assert clock.faster() == 4
    assert clock.slower() == 2
    clock.set_speed(16)
    assert clock.faster() == 16
    clock.set_speed(1)
    assert clock.slower() == 1


def test_catchup_is_capped_and_counted():
    clock = SimulationClock(speed=16, max_catchup=8)
    assert clock.advance(10.0) == 8
    assert clock.dropped_ticks == 152
    assert clock.ticks == 8
    assert clock.acc == 0.0


def test_toggle_pause():
    clock = SimulationClock(speed=2)
    clock.toggle_pause()
    assert clock.paused
    clock.toggle_pause()
    assert not clock.paused
    assert clock.speed == 2
