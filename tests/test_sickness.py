import pytest

from agents import BDIPolicy, default_actions
from agents.policies import features
from core41 import (
    Action,
    ArenaAgent,
    ArenaMatch,
    Automaton,
    DuelWorld,
    SICKNESS_DAMAGE_BONUS,
    SICKNESS_HEALTH_DECAY,
    SICKNESS_MAX,
    SICKNESS_PROGRESS,
    SICKNESS_REST_RECOVERY,
    SICKNESS_TREAT_RATE,
    TREAT_ENERGY_FRACTION,
    run_duel_tick,
)


def test_sickness_is_separate_state_and_clamped():
    unit = Automaton(id="unit")
    assert unit.sickness == 0.0
    assert not unit.is_sick
    assert unit.infect(2.0) == SICKNESS_MAX
    assert unit.infect(0.25) == SICKNESS_MAX
    unit.sickness = 0.4
    assert unit.infect(0.1) == 0.4
    assert unit.is_sick


def test_sickness_does_not_appear_without_infection():
    unit = Automaton(id="healthy")
    for _ in range(20):
        unit.tick_health(resting=False)
    assert unit.sickness == 0.0
    assert unit.health == 100.0


def test_untreated_sickness_progresses_and_damages_health():
    unit = Automaton(id="sick", health=100, sickness=0.2)
    unit.tick_health(resting=False)
    assert unit.sickness == pytest.approx(0.2 + SICKNESS_PROGRESS)
    assert unit.health == pytest.approx(
        100.0 - SICKNESS_HEALTH_DECAY * 0.2
    )


def test_rest_slows_sickness_and_can_recover():
    unit = Automaton(id="sick", health=100, sickness=0.5)
    for _ in range(60):
        unit.tick_health(resting=True)
    assert unit.sickness == 0.0
    assert unit.health > 99.0


def test_sickness_can_kill_when_untreated():
    unit = Automaton(id="sick", health=1.0, sickness=1.0)
    unit.tick_health(resting=False)
    assert unit.health == 0.0
    assert unit.is_dead


def test_treat_removes_sickness_and_care_scales():
    unit = Automaton(id="patient", sickness=0.5)
    unit.treat(0.1)
    assert unit.sickness == pytest.approx(0.4)
    unit.set_health_factor("care", 2.0)
    unit.treat(0.1)
    assert unit.sickness == pytest.approx(0.2)
    assert unit.treat(1.0) == 0.0


def test_sickness_increases_overflow_damage():
    healthy = Automaton(id="healthy")
    sick = Automaton(id="sick", sickness=1.0)
    _a, _o, clean = healthy.apply_force_damage(20.0)
    _a, _o, dirty = sick.apply_force_damage(20.0)
    assert dirty == pytest.approx(
        clean * (1.0 + SICKNESS_DAMAGE_BONUS)
    )


def test_sickness_factors_modify_recovery():
    unit = Automaton(id="frail", sickness=0.5)
    unit.set_health_factor("care", 0.5)
    unit.treat(0.2)
    assert unit.sickness == pytest.approx(0.4)

    unit.sickness = 0.5
    unit.set_health_factor("care", 1.0)
    unit.set_health_factor("illness", 2.0)
    unit.treat(0.2)
    assert unit.sickness == pytest.approx(0.4)


def test_sickness_default_recovery_rate_is_documented():
    assert SICKNESS_REST_RECOVERY == 0.01
    ticks = 0.5 / SICKNESS_REST_RECOVERY
    assert ticks == pytest.approx(50.0)


def test_arena_agent_sickness_api():
    agent = ArenaAgent("sick", sickness=0.6)
    assert agent.is_sick
    assert agent.sickness == 0.6
    agent.treat(0.1)
    assert agent.sickness == pytest.approx(0.5)
    agent.sickness = 2.0
    assert agent.sickness == SICKNESS_MAX
    agent.reset_state()
    assert agent.sickness == 0.0


def test_arena_match_accepts_sickness():
    match = ArenaMatch(seed=1, steps=10, sickness_rl=0.4, sickness_ai=0.2)
    assert match.rl.sickness == 0.4
    assert match.ai.sickness == 0.2


def test_match_engine_passes_sickness():
    pytest.importorskip("pygame")
    import game_engine as ge

    match = ge.MatchEngine(seed=1, steps=4, sickness=0.5)
    assert match.rl.sickness == 0.5
    assert match.ai.sickness == 0.5
    assert match.sickness == 0.5


def test_treat_action_spends_energy_and_reduces_sickness():
    left = ArenaAgent("patient", energy=50, sickness=0.5)
    right = ArenaAgent("other")
    _events, result, _other = run_duel_tick(
        left,
        Action("TREAT", form="care", fraction=TREAT_ENERGY_FRACTION),
        right,
        Action("REST", form="rest"),
    )
    assert result["kind"] == "treat"
    assert result["spent"] == pytest.approx(
        TREAT_ENERGY_FRACTION * left.unit.max_energy
    )
    assert left.energy_pool == pytest.approx(50 - result["spent"])
    assert left.sickness == pytest.approx(
        0.5 - SICKNESS_TREAT_RATE + SICKNESS_PROGRESS
    )
    assert left.last_act == "TREAT"


def test_treat_without_sickness_only_spends_energy():
    left = ArenaAgent("healthy", energy=50)
    right = ArenaAgent("other")
    run_duel_tick(
        left,
        Action("TREAT", form="care", fraction=TREAT_ENERGY_FRACTION),
        right,
        Action("REST", form="rest"),
    )
    assert left.energy_pool == pytest.approx(
        50 - TREAT_ENERGY_FRACTION * left.unit.max_energy
    )
    assert left.sickness == 0.0


def test_duel_world_offers_treat_only_when_sick():
    world = DuelWorld(seed=1)
    healthy = {
        action.kind for action in world.legal_actions("agent")
    }
    assert "TREAT" not in healthy
    world.agent.sickness = 0.4
    sick = {action.kind for action in world.legal_actions("agent")}
    assert "TREAT" in sick


def test_observation_exposes_both_sickness_values():
    left = ArenaAgent("left", sickness=0.6)
    right = ArenaAgent("right", sickness=0.3)
    observation = left.observe(right)
    assert observation.self_sickness == pytest.approx(0.6)
    assert observation.opponent_sickness == pytest.approx(0.3)


def test_policies_see_sickness_and_can_treat():
    left = ArenaAgent("left", sickness=0.4)
    right = ArenaAgent("right")
    observation = left.observe(right)
    actions = default_actions(observation)
    assert any(action.kind == "TREAT" for action in actions)
    for action in actions:
        assert len(features(observation, action)) == len(
            BDIPolicy().weights
        )

    healthy = ArenaAgent("healthy").observe(right)
    assert not any(
        action.kind == "TREAT" for action in default_actions(healthy)
    )


def test_arena_agent_actions_include_treat_only_when_sick():
    healthy = ArenaAgent("healthy")
    assert len(healthy.actions()) == 5
    assert all(action.kind != "TREAT" for action in healthy.actions())

    sick = ArenaAgent("sick", sickness=0.3)
    kinds = [action.kind for action in sick.actions()]
    assert kinds.count("TREAT") == 1
    assert len(kinds) == 6
