import pytest

from agents import BDIPolicy
from agents.policies import FEATURE_COUNT
from core41 import (
    CAPTURE_STREAK,
    Action,
    ArenaAgent,
    ArenaMatch,
    Automaton,
    DuelWorld,
    HEALTH_CRITICAL,
    HEALTH_DAMAGE_RATIO,
    HEALTH_MAX,
    HEALTH_REST_REGEN,
    check_capture,
    run_duel_tick,
)


def _duel(left_action, right_action, **kwargs):
    left = ArenaAgent("left", **kwargs)
    right = ArenaAgent("right", **kwargs)
    run_duel_tick(left, left_action, right, right_action)
    return left, right


def test_calibrated_health_constants():
    assert HEALTH_MAX == 100.0
    assert HEALTH_CRITICAL == 25.0
    assert HEALTH_REST_REGEN == 0.78
    assert HEALTH_DAMAGE_RATIO == 0.62
    assert HEALTH_MAX / HEALTH_REST_REGEN == pytest.approx(100.0 / 0.78)
    critical_to_full = (HEALTH_MAX - HEALTH_CRITICAL) / HEALTH_REST_REGEN
    assert critical_to_full == pytest.approx(75.0 / 0.78)


def test_critical_health_is_shared_by_engine_and_core():
    pytest.importorskip("pygame")
    import game_engine as ge

    assert ge.CRITICAL_HEALTH == HEALTH_CRITICAL


def test_health_is_separate_from_force_and_energy():
    agent = ArenaAgent("unit", force=40, energy=30, health=70)
    assert agent.health == 70
    assert agent.max_health == 100
    assert agent.health_ratio == pytest.approx(0.7)
    assert agent.force == 40
    assert agent.energy_pool == 30


def test_rest_regenerates_health_slowly():
    left, right = _duel(
        Action("REST", form="rest"),
        Action("REST", form="rest"),
        health=50,
        energy=50,
    )
    assert left.health == pytest.approx(50.0 + HEALTH_REST_REGEN)
    assert right.health == pytest.approx(50.0 + HEALTH_REST_REGEN)


def test_empty_energy_decays_health():
    left, _right = _duel(
        Action("WORK", form="force", fraction=0.3),
        Action("REST", form="rest"),
        energy=5,
        health=100,
    )
    assert left.energy_pool == 0
    assert left.health == pytest.approx(99.0)


def test_force_overflow_damages_health():
    unit = Automaton(id="target", force=5, health=100)
    absorbed, overflow, health_damage = unit.apply_force_damage(20)
    assert absorbed == 5
    assert overflow == 15
    assert health_damage == pytest.approx(15 * HEALTH_DAMAGE_RATIO)
    assert unit.force == 0
    assert unit.health == pytest.approx(100.0 - 15 * HEALTH_DAMAGE_RATIO)
    assert not unit.is_dead


def test_health_factors_scale_decay_regen_and_damage():
    unit = Automaton(
        id="frail",
        health_factors={
            "aging": 2.0,
            "illness": 1.5,
            "stress": 1.0,
            "care": 1.0,
        },
    )
    assert unit.health_decay_multiplier() == pytest.approx(3.0)
    assert unit.health_damage_multiplier() == pytest.approx(3.0)
    assert unit.health_regen_multiplier() == pytest.approx(2.0 / 3.0)

    unit.energy = 0
    unit.tick_health(resting=False)
    assert unit.health == pytest.approx(97.0)

    unit.energy = 50
    unit.tick_health(resting=True)
    assert unit.health == pytest.approx(97.0 + HEALTH_REST_REGEN * 2.0 / 3.0)


def test_health_factors_are_clamped():
    agent = ArenaAgent("unit")
    assert agent.set_health_factor("illness", -5) == 0.0
    assert agent.set_health_factor("aging", 999) == 10.0
    agent.set_health_factors({"care": 2.0})
    assert agent.unit.health_factor("care") == 2.0


def test_dead_unit_does_not_regenerate():
    unit = Automaton(id="dead", health=0)
    unit.energy = 50
    unit.tick_health(resting=True)
    assert unit.health == 0
    assert unit.is_dead


def test_observation_exposes_health():
    left = ArenaAgent("left", health=60)
    right = ArenaAgent("right", health=80)
    observation = left.observe(right)
    assert observation.self_health == 60
    assert observation.self_max_health == 100
    assert observation.opponent_health == 80
    assert len(BDIPolicy().weights) == FEATURE_COUNT


def test_arena_match_terminal_uses_health():
    match = ArenaMatch(seed=1, steps=10)
    match.ai.health = 0
    assert match._check_terminal()
    assert match.finished
    assert match.winner == "RL"


def test_duel_world_terminal_uses_health_not_force():
    world = DuelWorld(seed=2)
    world.agent.force = 0
    world.agent.health = 50
    _obs, _rew, done, info = world.step(
        {"agent": Action("REST", form="rest")}
    )
    assert not done
    assert info["winner"] is None

    world.agent.health = 0
    _obs, _rew, done, info = world.step(
        {"agent": Action("REST", form="rest")}
    )
    assert done
    assert info["winner"] == "opponent"


def test_capture_does_not_touch_health():
    rl = ArenaAgent("rl", force=100, energy=100, health=100)
    ai = ArenaAgent("ai", force=40, energy=10, health=100)
    winner, _dom_rl, _dom_ai = check_capture(
        rl, ai, dom_rl=CAPTURE_STREAK - 1
    )
    assert winner == "RL"
    assert ai.health == 100


def test_health_factors_cli_parser():
    pytest.importorskip("pygame")
    import game_engine as ge

    assert ge.parse_health_factors("aging=2, illness=1.5,bad") == {
        "aging": 2.0,
        "illness": 1.5,
    }
    assert ge.parse_health_factors("") == {}


def test_match_engine_passes_health_factors():
    pytest.importorskip("pygame")
    import game_engine as ge

    match = ge.MatchEngine(
        seed=1, steps=4, health_factors={"aging": 2.0}
    )
    assert match.rl.unit.health_factor("aging") == 2.0
    assert match.ai.unit.health_factor("aging") == 2.0


def test_battlefield_accepts_health_factors():
    from ui.battlefield import BattlefieldModel

    model = BattlefieldModel(seed=3, health_factors={"illness": 2.0})
    assert model.player.agent.unit.health_factor("illness") == 2.0
    assert model.enemy.agent.unit.health_factor("illness") == 2.0
    assert model.snapshot()["player"]["health"] == 100.0
