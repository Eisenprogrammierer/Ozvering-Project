"""Актор среды в core41: флаг `with_env` больше не мёртвый."""

import pytest

from core41 import (
    ArenaAgent,
    ArenaEnv,
    ArenaEnvironment,
    ArenaMatch,
)
from core41.environment import (
    ENV_ENERGY_DRAIN,
    ENV_ENERGY_RELIEF,
    ENV_EVENT_INTERVAL,
    ENV_HEALTH_DRAIN,
    ENV_HEALTH_RELIEF,
    ENV_RELIEF_INTERVAL,
)


def _agents():
    return ArenaAgent("left", seed=1), ArenaAgent("right", seed=2)


def test_environment_is_deterministic_and_seasonal():
    left, right = _agents()
    env = ArenaEnvironment(seed=7, asymmetric=False)

    before = (left.energy_pool, right.energy_pool)
    events = ()
    for _ in range(ENV_EVENT_INTERVAL):
        events = env.tick(left, right)

    assert events and events[-1]["event"] == "strain"
    multiplier = env.public_state()["season_multiplier"]
    assert left.energy_pool == pytest.approx(
        before[0] - ENV_ENERGY_DRAIN * multiplier
    )
    assert right.energy_pool == pytest.approx(
        before[1] - ENV_ENERGY_DRAIN * multiplier
    )
    assert left.health == pytest.approx(
        100.0 - ENV_HEALTH_DRAIN * multiplier
    )
    assert right.health == pytest.approx(
        100.0 - ENV_HEALTH_DRAIN * multiplier
    )


def test_environment_asymmetric_event_hits_primary_fully_and_secondary_half():
    left, right = _agents()
    env = ArenaEnvironment(seed=7, asymmetric=True)
    for _ in range(ENV_EVENT_INTERVAL):
        events = env.tick(left, right)
    event = events[-1]
    assert event["target"] in ("rl", "ai")
    multiplier = env.public_state()["season_multiplier"]
    drained = {
        "rl": 100.0 - left.energy_pool,
        "ai": 100.0 - right.energy_pool,
    }
    primary = event["target"]
    secondary = "ai" if primary == "rl" else "rl"
    assert drained[primary] == pytest.approx(
        ENV_ENERGY_DRAIN * multiplier
    )
    assert drained[secondary] == pytest.approx(
        ENV_ENERGY_DRAIN * multiplier * 0.5
    )


def test_environment_relief_cycle_restores_both_sides():
    left, right = _agents()
    env = ArenaEnvironment(seed=7, asymmetric=False)
    # Сначала доводим до истощения, затем до передышки.
    for _ in range(ENV_EVENT_INTERVAL):
        env.tick(left, right)
    low = left.energy_pool
    events = ()
    for _ in range(ENV_RELIEF_INTERVAL - ENV_EVENT_INTERVAL):
        events = env.tick(left, right)

    assert events and events[-1]["event"] == "relief"
    multiplier = env.public_state()["season_multiplier"]
    assert left.energy_pool == pytest.approx(
        min(left.max_energy, low + ENV_ENERGY_RELIEF * multiplier)
    )
    assert right.health == pytest.approx(
        100.0
        - ENV_HEALTH_DRAIN * multiplier
        + ENV_HEALTH_RELIEF * multiplier
    )


def test_arena_match_creates_environment_only_with_flag():
    without = ArenaMatch(seed=3, steps=5, with_env=False)
    assert without.env is None

    with_env = ArenaMatch(seed=3, steps=ENV_EVENT_INTERVAL + 2, with_env=True)
    assert isinstance(with_env.env, ArenaEnvironment)

    seen = False
    for _ in range(ENV_EVENT_INTERVAL):
        with_env.step_tick()
        seen = seen or any(
            event.get("kind") == "environment"
            for event in with_env.events
        )
    assert seen


def test_arena_env_forwards_with_env_to_match():
    env = ArenaEnv(seed=5, steps=4, with_env=True)
    assert env.match.env is not None
    env.reset(seed=5)
    assert env.match.env is not None


def test_arena_env_matches_active_game_by_default_and_can_disable_env():
    training = ArenaEnv(seed=5, steps=4)
    assert training.with_env is True
    assert training.match.env is not None

    control = ArenaEnv(seed=5, steps=4, with_env=False)
    assert control.with_env is False
    assert control.match.env is None
