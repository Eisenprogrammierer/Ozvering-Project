"""Актор среды в core41: флаг `with_env` больше не мёртвый."""

import pytest

from core41 import (
    Action,
    ArenaAgent,
    ArenaEnv,
    ArenaEnvironment,
    ArenaMatch,
)
from core41.environment import (
    ENV_BONUS,
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


# ---------------------------------------------------------------------------
# Средовые источники болезни и острые раны
# ---------------------------------------------------------------------------


def test_environment_illness_reservoir_raises_sickness():
    from core41.environment import ENV_ILLNESS_INTERVAL, ENV_SICKNESS

    left, right = _agents()
    env = ArenaEnvironment(
        seed=7,
        asymmetric=False,
        event_interval=10**9,
        relief_interval=10**9,
    )
    for _ in range(ENV_ILLNESS_INTERVAL):
        events = env.tick(left, right)

    assert events and events[-1]["event"] == "illness"
    multiplier = env.public_state()["season_multiplier"]
    expected = ENV_SICKNESS * multiplier
    assert left.sickness == pytest.approx(expected)
    assert right.sickness == pytest.approx(expected)


def test_environment_wound_event_damages_health():
    from core41.environment import ENV_WOUND_DAMAGE, ENV_WOUND_INTERVAL

    left, right = _agents()
    env = ArenaEnvironment(
        seed=7,
        asymmetric=False,
        event_interval=10**9,
        relief_interval=10**9,
        illness_interval=10**9,
    )
    for _ in range(ENV_WOUND_INTERVAL):
        events = env.tick(left, right)

    assert events and events[-1]["event"] == "wound"
    multiplier = env.public_state()["season_multiplier"]
    expected = 100.0 - ENV_WOUND_DAMAGE * multiplier
    assert left.health == pytest.approx(expected)
    assert right.health == pytest.approx(expected)


def test_environment_asymmetric_illness_hits_primary_fully():
    from core41.environment import ENV_SICKNESS

    left, right = _agents()
    env = ArenaEnvironment(
        seed=1,
        asymmetric=True,
        event_interval=10**9,
        relief_interval=10**9,
        wound_interval=10**9,
        illness_interval=5,
    )
    for _ in range(5):
        env.tick(left, right)

    event = env.events[-1]
    assert event["event"] == "illness"
    primary = event["target"]
    secondary = "ai" if primary == "rl" else "rl"
    sickness = {"rl": left.sickness, "ai": right.sickness}
    multiplier = env.public_state()["season_multiplier"]
    assert sickness[primary] == pytest.approx(ENV_SICKNESS * multiplier)
    assert sickness[secondary] == pytest.approx(
        ENV_SICKNESS * multiplier * 0.5
    )


def test_environment_public_state_reports_reservoir_schedule():
    left, right = _agents()
    env = ArenaEnvironment(seed=3, illness_interval=5, wound_interval=7)
    env.tick(left, right)

    state = env.public_state()
    for key in ("illness", "wound", "next_illness", "next_wound"):
        assert key in state
    assert state["next_illness"] == 4
    assert state["next_wound"] == 6


def test_environment_state_round_trips_reservoir_intervals():
    left, right = _agents()
    env = ArenaEnvironment(
        seed=3, illness_interval=13, wound_interval=19
    )
    state = env.state_dict()
    assert state["illness_interval"] == 13
    assert state["wound_interval"] == 19

    restored = ArenaEnvironment(seed=0)
    restored.load_state_dict(state)
    assert restored.illness_interval == 13
    assert restored.wound_interval == 19


# --- A6: исход среды (цель/коллапс) — событие фона, а не конец дуэли ---


def _env_match(steps=5000, seed=11):
    return ArenaMatch(seed=seed, steps=steps, with_env=True)


def _advance_until(match, predicate, limit=5000):
    for _ in range(limit):
        if predicate():
            return True
        if match.finished:
            return False
        match.step_tick()
    return predicate()


def test_env_goal_is_event_not_match_end():
    m = _env_match()
    env = m.env
    env.goal_horizon = 5000
    # Ставим фон у самой цели и открываем окно: следующий такт даст goal.
    env.force = env.goal_force - 1e-3
    env.receive_pressure(500.0)
    assert env.status == "active"
    assert env.work_bonus() == pytest.approx(ENV_BONUS)

    assert _advance_until(m, lambda: m.env.goal_reached, limit=5)
    assert m.env_event == "goal"
    assert m.env_outcome == "goal"
    assert not m.finished  # партия продолжается
    assert m.winner is None
    assert env.status == "strengthened"
    assert env.work_bonus() == pytest.approx(ENV_BONUS * 1.5)
    assert not env.collapsed


def test_env_goal_does_not_stop_economy_state():
    m = _env_match()
    env = m.env
    env.goal_horizon = 5000
    env.force = env.goal_force - 1e-3
    env.receive_pressure(500.0)
    assert _advance_until(m, lambda: m.env.goal_reached, limit=5)
    force_at_goal = env.force
    m.step_tick(
        forced_rl_action=Action("REST", form="rest"),
        forced_ai_action=Action("REST", form="rest"),
    )
    # `env_event` — только событие текущего такта; последний исход
    # сохраняется в `env_outcome`, а дуэль продолжается.
    assert m.env_event is None
    assert m.env_outcome == "goal"
    assert not m.finished
    assert env.force == pytest.approx(force_at_goal)
    assert env.status == "strengthened"


def test_env_collapse_is_event_not_match_end():
    m = _env_match()
    env = m.env
    # Цель недостижима за горизонт: потолок силы ниже целевой силы.
    env.force = 0.0
    env.goal_ratio = 1.0
    env.goal_horizon = 5

    assert _advance_until(m, lambda: m.env.collapsed, limit=10)
    assert m.env_event == "collapse"
    assert m.env_outcome == "collapse"
    assert not m.finished
    assert m.winner is None
    assert env.status == "collapsed"
    assert env.work_bonus() == 0.0
    assert not env.goal_reached
    assert not env.window_open()


def test_env_event_carries_status_and_work_bonus():
    m = _env_match()
    env = m.env
    env.force = env.goal_force - 1e-3
    env.receive_pressure(500.0)
    assert _advance_until(m, lambda: m.env.goal_reached, limit=5)
    event = next(
        e
        for e in m.events
        if e.get("kind") == "environment" and e.get("event") == "goal"
    )
    assert event["status"] == "strengthened"
    assert event["work_bonus"] == pytest.approx(ENV_BONUS * 1.5)
    assert event["ticks"] == m.step


def test_arena_env_does_not_truncate_on_env_goal():
    env = ArenaEnv(seed=3, steps=50, with_env=True)
    env.reset(seed=3)
    match_env = env.match.env
    match_env.goal_horizon = 5000
    match_env.force = match_env.goal_force - 1e-3
    match_env.receive_pressure(500.0)

    obs, reward, done, truncated, info = env.step(Action("REST", form="rest"))
    assert info["env_event"] == "goal"
    assert info["env_outcome"] == "goal"
    assert not done
    assert not truncated
    assert info["winner"] is None


def test_arena_env_truncates_only_on_step_limit():
    env = ArenaEnv(seed=5, steps=4, with_env=True)
    env.reset(seed=5)
    env.match.env.goal_horizon = 5000
    truncated = False
    info = {}
    for _ in range(4):
        obs, reward, done, truncated, info = env.step(
            Action("REST", form="rest")
        )
    assert done and truncated
    assert info["env_event"] is None
    assert info["env_outcome"] is None
    assert info["step"] >= 4


def test_no_env_matches_keep_old_semantics():
    m = ArenaMatch(seed=1, steps=50)
    import random as _r

    rng = _r.Random(2)
    while not m.finished:
        m.step_tick(
            forced_rl_action=rng.choice(m.rl.actions()),
            forced_ai_action=rng.choice(m.ai.actions()),
        )
    assert m.env_outcome is None
    assert m.env is None


def test_arena_env_exposes_fog_switch():
    fog_env = ArenaEnv(seed=4, steps=4)
    _obs, _reward, _done, _truncated, info = fog_env.step(
        Action("REST", form="rest")
    )
    assert info["fog"] is True

    clear_env = ArenaEnv(seed=4, steps=4, fog=False)
    _obs, _reward, _done, _truncated, info = clear_env.step(
        Action("REST", form="rest")
    )
    assert info["fog"] is False
