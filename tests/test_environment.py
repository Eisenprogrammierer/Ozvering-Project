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


def test_environment_is_deterministic_and_symmetric():
    left, right = _agents()
    env = ArenaEnvironment(seed=7)

    before = (left.energy_pool, right.energy_pool)
    events = ()
    for _ in range(ENV_EVENT_INTERVAL):
        events = env.tick(left, right)

    assert events and events[-1]["event"] == "strain"
    assert left.energy_pool == pytest.approx(
        before[0] - ENV_ENERGY_DRAIN
    )
    assert right.energy_pool == pytest.approx(
        before[1] - ENV_ENERGY_DRAIN
    )
    assert left.health == pytest.approx(100.0 - ENV_HEALTH_DRAIN)
    assert right.health == pytest.approx(100.0 - ENV_HEALTH_DRAIN)


def test_environment_relief_cycle_restores_both_sides():
    left, right = _agents()
    env = ArenaEnvironment(seed=7)
    # Сначала доводим до истощения, затем до передышки.
    for _ in range(ENV_EVENT_INTERVAL):
        env.tick(left, right)
    low = left.energy_pool
    events = ()
    for _ in range(ENV_RELIEF_INTERVAL - ENV_EVENT_INTERVAL):
        events = env.tick(left, right)

    assert events and events[-1]["event"] == "relief"
    assert left.energy_pool == pytest.approx(
        min(left.max_energy, low + ENV_ENERGY_RELIEF)
    )
    assert right.health == pytest.approx(
        100.0 - ENV_HEALTH_DRAIN + ENV_HEALTH_RELIEF
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
