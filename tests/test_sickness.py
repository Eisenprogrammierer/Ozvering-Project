import pytest

from agents import BDIPolicy, default_actions
from agents.policies import features
from core41 import (
    Action,
    ArenaAgent,
    ArenaMatch,
    Automaton,
    CONTAGION_CHANCE,
    CONTAGION_SEVERITY,
    DuelWorld,
    SICKNESS_DAMAGE_BONUS,
    SICKNESS_HEALTH_DECAY,
    SICKNESS_MAX,
    SICKNESS_PROGRESS,
    SICKNESS_REST_RECOVERY,
    SICKNESS_TREAT_RATE,
    SICKNESS_WORK_FLOOR,
    SICKNESS_WORK_PENALTY,
    TREAT_ENERGY_FRACTION,
    Work,
    run_duel_tick,
    success_probability,
    transmit_sickness,
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


def test_illness_is_not_counted_twice_in_sickness_damage():
    def make(aging, illness):
        return Automaton(
            id="unit",
            health=100.0,
            sickness=0.2,
            health_factors={
                "aging": aging,
                "illness": illness,
                "stress": 1.0,
                "care": 1.0,
            },
        )

    frail = make(1.0, 2.0)
    frail.tick_health(resting=False)
    # `illness` ускоряет прогресс болезни ровно один раз ...
    assert frail.sickness == pytest.approx(0.2 + SICKNESS_PROGRESS * 2.0)
    # ... и не умножает урон от уже накопленной тяжести повторно.
    assert frail.health == pytest.approx(100.0 - SICKNESS_HEALTH_DECAY * 0.2)

    aged = make(2.0, 1.0)
    aged.tick_health(resting=False)
    assert aged.health == pytest.approx(
        100.0 - SICKNESS_HEALTH_DECAY * 0.2 * 2.0
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


def test_sickness_reduces_work_effectiveness_without_touching_skill_or_energy():
    unit = Automaton(id="worker", skills={"force": 0.6}, energy=100.0)
    assert unit.work_effectiveness() == pytest.approx(1.0)

    unit.sickness = 0.5
    assert unit.work_effectiveness() == pytest.approx(
        1.0 - SICKNESS_WORK_PENALTY * 0.5
    )
    # Болезнь не переписывает сохранённый навык и не сжигает энергию.
    assert unit.skill("force") == pytest.approx(0.6)
    assert unit.energy == pytest.approx(100.0)

    unit.sickness = 1.0
    assert unit.work_effectiveness() == pytest.approx(SICKNESS_WORK_FLOOR)


def test_sickness_lowers_success_but_illness_only_acts_through_it():
    healthy = Automaton(id="healthy", skills={"force": 0.6})
    sick = Automaton(id="sick", skills={"force": 0.6}, sickness=0.5)
    frail = Automaton(id="frail", skills={"force": 0.6})
    frail.set_health_factor("illness", 2.0)
    defender = Automaton(id="target")
    work = Work(amount=30.0, form="force")

    p_healthy = success_probability(healthy, defender, work, False)
    p_sick = success_probability(sick, defender, work, False)
    p_frail = success_probability(frail, defender, work, False)

    assert p_sick < p_healthy
    # `illness` сам по себе не дублирует штраф: он действует через `sickness`.
    assert p_frail == pytest.approx(p_healthy)


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
    # Полностью отдохнувшему REST не предлагается: это no-op, из-за
    # которого self-play застревал в бесконечных ничьих.
    assert len(healthy.actions()) == 4
    assert all(action.kind != "TREAT" for action in healthy.actions())

    healthy.energy_pool = healthy.max_energy - 1.0
    assert len(healthy.actions()) == 5
    assert any(action.kind == "REST" for action in healthy.actions())

    sick = ArenaAgent("sick", sickness=0.3)
    kinds = [action.kind for action in sick.actions()]
    assert kinds.count("TREAT") == 1
    assert len(kinds) == 6


class _FixedRng:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value


def test_contagion_transmits_on_successful_force_contact():
    source = Automaton(id="source", sickness=0.8)
    target = Automaton(id="target")
    amount = transmit_sickness(
        source, target, _FixedRng(0.0), "force"
    )
    assert amount == pytest.approx(CONTAGION_SEVERITY * 0.8)
    assert target.sickness == pytest.approx(amount)
    assert CONTAGION_CHANCE > 0.0


def test_contagion_rejects_healthy_info_and_lucky_targets():
    healthy = Automaton(id="healthy")
    target = Automaton(id="target")
    assert transmit_sickness(
        healthy, target, _FixedRng(0.0), "force"
    ) == 0.0
    assert target.sickness == 0.0

    source = Automaton(id="source", sickness=1.0)
    assert transmit_sickness(
        source, target, _FixedRng(0.0), "info"
    ) == 0.0
    assert transmit_sickness(
        source, target, _FixedRng(0.99), "force"
    ) == 0.0
    assert target.sickness == 0.0


def test_contagion_does_not_reduce_existing_sickness():
    source = Automaton(id="source", sickness=1.0)
    target = Automaton(id="target", sickness=0.9)
    assert transmit_sickness(
        source, target, _FixedRng(0.0), "force"
    ) == 0.0
    assert target.sickness == pytest.approx(0.9)


def test_run_duel_tick_transmits_sickness_on_hit():
    left = ArenaAgent("left", sickness=1.0, energy=100)
    right = ArenaAgent("right", energy=100)
    _events, result, _other = run_duel_tick(
        left,
        Action("WORK", form="force", fraction=0.7),
        right,
        Action("REST", form="rest"),
        rng=_FixedRng(0.0),
    )
    assert result["success"] is True
    assert result["infection"] == pytest.approx(
        CONTAGION_SEVERITY * 1.0
    )
    assert right.sickness == pytest.approx(
        CONTAGION_SEVERITY - SICKNESS_REST_RECOVERY
    )
    assert any(event["kind"] == "infection" for event in _events)


def test_duel_world_transmits_sickness():
    world = DuelWorld(seed=1)
    world.agent.sickness = 1.0
    world.rng = _FixedRng(0.0)
    _obs, _rewards, _done, info = world.step(
        {"agent": Action("WORK", form="force", fraction=1.0)}
    )
    assert info["agent"]["infection"] == pytest.approx(
        CONTAGION_SEVERITY
    )
    assert world.opponent.sickness == pytest.approx(
        CONTAGION_SEVERITY - SICKNESS_REST_RECOVERY
    )


def test_condition_state_roundtrip_and_hard_reset():
    agent = ArenaAgent("unit", health=60, sickness=0.4)
    state = agent.condition_state()
    assert state == {"health": 60.0, "sickness": 0.4}

    restored = ArenaAgent("unit")
    restored.load_condition(state)
    assert restored.health == 60.0
    assert restored.sickness == 0.4

    restored.load_condition({"health": 999, "sickness": 9})
    assert restored.health == 100.0
    assert restored.sickness == SICKNESS_MAX

    restored.reset_state()
    assert restored.health == 100.0
    assert restored.sickness == 0.0
