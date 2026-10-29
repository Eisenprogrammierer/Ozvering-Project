"""Тесты фоновых часов кампании (вопрос §7 №31, первый срез)."""

from core41 import HEALTH_CRITICAL, SICKNESS_CRITICAL

from campaign.clock import (
    MAX_CATCHUP_DAYS,
    SECONDS_PER_DAY,
    CampaignClock,
    background_pause_reason,
    normalize_max_catchup,
    normalize_seconds_per_day,
    offline_days,
)


class _FakeEngine:
    def __init__(self, condition=None, finished=False, attached=True):
        self.finished = finished
        self.attached = attached
        self._condition = condition or {
            "health": 100.0,
            "sickness": 0.0,
            "alive": True,
        }

    def player_condition(self):
        return dict(self._condition)


def test_clock_accumulates_real_seconds_and_converts_to_days():
    clock = CampaignClock(seconds_per_day=10)
    assert clock.advance(5) == 0
    assert clock.days == 0
    assert clock.advance(5) == 1
    assert clock.days == 1
    assert clock.advance(25) == 2
    assert clock.days == 3


def test_clock_caps_catchup_and_tracks_dropped_days():
    clock = CampaignClock(seconds_per_day=1, max_catchup_days=3)
    assert clock.advance(10) == 3
    assert clock.days == 3
    assert clock.dropped_days == 7


def test_clock_pause_and_reset_accumulator():
    clock = CampaignClock(seconds_per_day=10)
    clock.pause()
    assert clock.advance(100) == 0
    assert clock.paused is True
    assert clock.label == "PAUSE"
    clock.resume()
    clock.advance(5)
    clock.reset_accumulator()
    assert clock.advance(10) == 1
    clock.reset_counters()
    assert clock.days == 0
    assert clock.acc == 0.0
    assert clock.dropped_days == 0


def test_offline_days_is_bounded_and_ignores_broken_clocks():
    clock = CampaignClock(seconds_per_day=10, max_catchup_days=2)
    assert offline_days(None) == 0
    assert offline_days("garbage") == 0
    assert offline_days(100.0, now=50.0, clock=clock) == 0
    assert offline_days(100.0, now=135.0, clock=clock) == 2
    assert offline_days(100.0, now=105.0, clock=clock) == 0


def test_background_pause_reason_covers_critical_states():
    assert background_pause_reason(None) == "no_engine"
    assert background_pause_reason(_FakeEngine(finished=True)) == "finished"
    assert background_pause_reason(_FakeEngine(attached=False)) == "unattached"
    assert (
        background_pause_reason(
            _FakeEngine({"health": 100.0, "sickness": 0.0, "alive": False})
        )
        == "dead"
    )
    assert (
        background_pause_reason(
            _FakeEngine(
                {
                    "health": HEALTH_CRITICAL,
                    "sickness": 0.0,
                    "alive": True,
                }
            )
        )
        == "health"
    )
    assert (
        background_pause_reason(
            _FakeEngine(
                {
                    "health": 100.0,
                    "sickness": SICKNESS_CRITICAL,
                    "alive": True,
                }
            )
        )
        == "sickness"
    )
    assert background_pause_reason(_FakeEngine()) == ""


def test_clock_normalizers_fall_back_to_defaults():
    assert normalize_seconds_per_day(None) == SECONDS_PER_DAY
    assert normalize_seconds_per_day(0) == 1.0
    assert normalize_max_catchup(None) == MAX_CATCHUP_DAYS
    assert normalize_max_catchup(0) == 1
