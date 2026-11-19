from campaign.free_clock import FreeClock, normalize_speeds


def test_default_day_is_physical_86400_seconds():
    clock = FreeClock()
    assert clock.seconds_per_day == 86400.0
    assert clock.advance(1.0) == 0
    assert clock.acc == 1.0


def test_speed_is_never_below_one_and_can_be_reduced():
    clock = FreeClock(speeds=[1, 2, 4, 8], speed=4)
    assert clock.speed == 4.0
    clock.slow_down()
    assert clock.speed == 2.0
    clock.slow_down()
    assert clock.speed == 1.0
    assert clock.can_slow_down is False
    clock.slow_down()
    assert clock.speed == 1.0
    clock.speed_up()
    assert clock.speed == 2.0


def test_negative_dt_and_negative_snapshot_do_not_rewind():
    clock = FreeClock(seconds_per_day=10, speed=1, acc=3)
    assert clock.advance(-100) == 0
    assert clock.acc == 3
    restored = FreeClock.from_snapshot(
        {"seconds_per_day": 10, "speed": 1, "acc": -50},
        speeds=[1, 2],
    )
    assert restored.acc == 0
    assert restored.speed == 1


def test_speed_multiplies_physical_seconds_and_crosses_day_boundary():
    clock = FreeClock(seconds_per_day=10, speeds=[1, 2, 4], speed=2)
    assert clock.advance(3) == 0
    assert clock.acc == 6
    assert clock.advance(2) == 1
    assert clock.acc == 0
    assert clock.days == 1


def test_snapshot_round_trip_preserves_clock_state():
    clock = FreeClock(seconds_per_day=30, speeds=[1, 2], speed=2, acc=7)
    clock.advance(10)
    snapshot = clock.to_snapshot()
    restored = FreeClock.from_snapshot(snapshot, speeds=[1, 2])
    assert restored.to_snapshot() == snapshot


def test_speeds_are_normalized_and_filtered():
    assert normalize_speeds([0, -1, 2, 2, 4]) == (1.0, 2.0, 4.0)
    clock = FreeClock(speeds=[0.5], speed=0.5)
    assert clock.speeds == (1.0,)
    assert clock.speed == 1.0
