import json
import random

import pytest

import simulation as S
from agents import BDIPolicy, PolicyAgent, QTablePolicy, RandomPolicy
from agents.train import train
from core41 import (
    Action,
    ArenaAgent,
    ArenaEnv,
    ArenaMatch,
    Automaton,
    CORE_ACTIONS,
    DuelEnv,
    DuelWorld,
    Observation,
    Work,
    action_from_index,
    check_capture,
    run_duel_tick,
)
from core41.types import Transition


def _observation():
    return Observation(
        self_force=10.0,
        self_energy=5.0,
        self_max_force=10.0,
        self_max_energy=10.0,
        opponent_force=8.0,
        opponent_energy=4.0,
        opponent_max_force=10.0,
        opponent_max_energy=10.0,
        opponent_pressure=3.0,
        opponent_open=False,
        time=0.0,
        forms=("force",),
    )


def test_work_form_is_channel_not_energy_type():
    work = Work(amount=3.0, form="force")
    assert work.form == "force"
    assert not hasattr(work, "energy_type")


def test_automaton_has_one_universal_energy():
    unit = Automaton(id="one", energy=10.0)
    unit.receive(Work(amount=4.0, form="info"))
    assert unit.energy == pytest.approx(11.05)
    assert unit.pressure() == pytest.approx(1.2)


def test_automaton_rejects_unhandled_form():
    unit = Automaton(id="closed", inputs=("force",), energy=10.0)
    result = unit.receive(Work(amount=4.0, form="info"))
    assert result["accepted"] is False
    assert unit.energy == 10.0


def test_duel_is_deterministic_for_a_seed():
    actions = {
        "agent": Action("WORK", form="force", fraction=0.5),
        "opponent": Action("REST", form="rest"),
    }
    first = DuelWorld(seed=11)
    second = DuelWorld(seed=11)
    for _ in range(3):
        first_obs, first_reward, first_done, _ = first.step(actions)
        second_obs, second_reward, second_done, _ = second.step(actions)
        assert first_obs == second_obs
        assert first_reward == second_reward
        assert first_done == second_done


def test_duel_spends_energy_and_uses_contextual_handler():
    world = DuelWorld(seed=3)
    energy_before = world.agent.energy
    observations, rewards, done, info = world.step(
        {
            "agent": Action("WORK", form="force", fraction=0.5),
            "opponent": Action("REST", form="rest"),
        }
    )
    assert world.agent.energy < energy_before
    assert info["agent"]["kind"] == "work"
    assert info["agent"]["spent"] > 0
    assert info["agent"]["chance"] > 0
    assert observations["agent"].time == 1.0


def test_env_reset_and_step_contract():
    env = DuelEnv(seed=5, max_steps=4)
    observation = env.reset(seed=5)
    assert isinstance(observation, Observation)
    result = env.step(Action("WORK", form="force", fraction=0.25))
    assert len(result) == 5
    next_observation, reward, done, truncated, info = result
    assert isinstance(next_observation, Observation)
    assert isinstance(reward, float)
    assert isinstance(done, bool)
    assert isinstance(truncated, bool)
    assert "winner" in info


def test_bdi_policy_updates_weights_and_serializes():
    policy = BDIPolicy(seed=4, epsilon=0.0)
    observation = _observation()
    action = Action("WORK", form="force", fraction=0.5)
    next_observation = Observation(
        self_force=10.0,
        self_energy=4.0,
        self_max_force=10.0,
        self_max_energy=10.0,
        opponent_force=6.0,
        opponent_energy=4.0,
        opponent_max_force=10.0,
        opponent_max_energy=10.0,
        opponent_pressure=4.0,
        opponent_open=True,
        time=1.0,
        forms=("force",),
    )
    before = list(policy.weights)
    policy.observe(
        Transition(
            observation=observation,
            action=action,
            reward=0.2,
            next_observation=next_observation,
            done=False,
        )
    )
    assert policy.weights != before
    assert policy.updates == 1
    state = json.loads(json.dumps(policy.state_dict()))
    loaded = BDIPolicy(seed=4)
    loaded.load_state_dict(state)
    assert loaded.weights == pytest.approx(policy.weights)


def test_qtable_policy_round_trip():
    policy = QTablePolicy(seed=1)
    observation = _observation()
    action = Action("WORK", form="force", fraction=0.5)
    policy.observe(
        Transition(
            observation=observation,
            action=action,
            reward=0.3,
            next_observation=observation,
            done=True,
        )
    )
    state = json.loads(json.dumps(policy.state_dict()))
    loaded = QTablePolicy(seed=1)
    loaded.load_state_dict(state)
    assert loaded.table == policy.table


def test_random_policy_is_total():
    policy = RandomPolicy(seed=2)
    actions = (Action("REST", form="rest"),)
    assert policy.act(_observation(), actions) in actions


def test_policy_agent_is_a_trainable_simulation_agent():
    agent = PolicyAgent(profile="CANON")
    opponent = S.Agent(profile="CANON")
    rng = random.Random(7)
    agent.sense(opponent, rng)
    act, work = agent.form_intention()
    assert act in tuple(S.TYPES) + ("REST",)
    assert work >= 0
    agent.observe_reward(0.1)
    assert agent.policy.updates == 1
    assert isinstance(agent, S.Agent)


def test_commander_ai_uses_core41_agent():
    from ui.battlefield import Commander

    commander = Commander("test", "enemy", ai=True)
    assert isinstance(commander.agent, ArenaAgent)
    assert commander.intention()[0] in ("force", "info", "REST")


def test_core_training_smoke():
    policy, stats = train(episodes=2, seed=9, max_steps=20)
    assert stats["episodes"] == 2
    assert stats["wins"] + stats["losses"] + stats["draws"] == 2
    assert isinstance(policy, BDIPolicy)


def test_arena_actions_are_generic_work_forms():
    assert len(CORE_ACTIONS) == 6
    for index, (name, fraction) in enumerate(CORE_ACTIONS):
        action = action_from_index(index)
        if name == "REST":
            assert action.kind == "REST"
        elif name == "TREAT":
            assert action.kind == "TREAT"
            assert action.form == "care"
            assert action.fraction == fraction
        else:
            assert action.kind == "WORK"
            assert action.form == name
            assert action.fraction == fraction


def test_arena_agent_has_one_energy_pool_and_form_channels():
    agent = ArenaAgent("test", profile="CANON", force=80, energy=40)
    assert agent.force == 80
    assert agent.energy_pool == 40
    assert agent.unit.max_energy == 100
    assert agent.defense in ("force", "info")
    assert agent.schmitt_on() > 0
    assert not hasattr(agent, "energy_types")
    assert not hasattr(agent.unit, "energy_types")


def test_arena_match_runs_and_updates_both_policies():
    first = ArenaMatch(
        seed=11,
        steps=30,
        rl_policy=QTablePolicy(seed=11),
        ai_policy=BDIPolicy(seed=12),
    )
    second = ArenaMatch(
        seed=11,
        steps=30,
        rl_policy=QTablePolicy(seed=11),
        ai_policy=BDIPolicy(seed=12),
    )
    for _ in range(30):
        first.step_tick()
        second.step_tick()
    assert first.step == 30
    assert first.finished
    assert len(first.rl.Q) > 0
    assert first.ai.policy.updates == 30
    assert first.rl_hist == second.rl_hist
    assert first.ai_hist == second.ai_hist


def test_arena_env_matches_active_arena_and_does_not_learn_internally():
    policy = BDIPolicy(seed=3, epsilon=0.0)
    weights_before = list(policy.weights)
    env = ArenaEnv(seed=3, steps=10, policy=policy, sickness_rl=0.5)
    observation = env.reset(seed=3)
    assert isinstance(observation, Observation)
    actions = {
        (action.kind, action.form, action.fraction)
        for action in env.action_space
    }
    assert ("WORK", "force", 0.3) in actions
    assert ("WORK", "info", 0.7) in actions
    assert ("TREAT", "care", 0.1) in actions
    next_observation, reward, done, truncated, info = env.step(
        Action("REST", form="rest")
    )
    assert isinstance(next_observation, Observation)
    assert isinstance(reward, float)
    assert not done
    assert not truncated
    assert policy.weights == weights_before
    assert "winner" in info
    assert "events" in info


def test_arena_env_terminal_and_truncated_contract():
    env = ArenaEnv(
        seed=1,
        steps=1,
        policy=RandomPolicy(seed=1),
        opponent_policy=RandomPolicy(seed=2),
    )
    env.reset(seed=1)
    observation, reward, done, truncated, info = env.step(
        Action("REST", form="rest"),
        opponent_action=Action("REST", form="rest"),
    )
    assert isinstance(observation, Observation)
    assert isinstance(reward, float)
    assert done
    assert truncated
    assert info["winner"] in ("RL", "AI", None)


def test_arena_match_forced_action_uses_ui_index():
    match = ArenaMatch(seed=5, steps=3, rl_policy=QTablePolicy(seed=5))
    energy_before = match.rl.energy_pool
    match.step_tick(forced_rl_action=2)
    assert match.last_rl_action[0] == "force"
    assert match.rl.energy_pool <= energy_before


def test_arena_run_duel_tick_uses_shared_contract():
    left = ArenaAgent("left", seed=1)
    right = ArenaAgent("right", seed=2)
    left_energy = left.energy_pool
    events, left_result, right_result = run_duel_tick(
        left,
        Action("WORK", form="force", fraction=0.7),
        right,
        Action("REST", form="rest"),
        rng=random.Random(4),
    )
    assert left.energy_pool < left_energy
    assert left_result["kind"] == "work"
    assert right_result["kind"] == "rest"
    assert len(events) == 1
    assert events[0]["frm"] == "left"
    assert events[0]["type"] == "force"


def test_arena_capture_is_a_projection_not_typed_energy():
    rl = ArenaAgent("rl", force=100, energy=100)
    ai = ArenaAgent("ai", force=40, energy=10)
    winner, dom_rl, dom_ai = check_capture(
        rl, ai, dom_rl=19, dom_ai=0
    )
    assert winner == "RL"
    assert dom_rl == 0 and dom_ai == 0
    assert ai.force < 40
    assert rl.force >= 100


def test_active_arena_match_engine_uses_core41_runtime():
    pytest.importorskip("pygame")
    import game_engine as ge

    match = ge.MatchEngine(seed=2, steps=8)
    assert isinstance(match.rl, ArenaAgent)
    assert isinstance(match.ai, ArenaAgent)
    assert match.env is None
    for _ in range(8):
        match.step_tick()
    assert match.step == 8
    assert match.finished
    assert len(match.rl_hist) == 8
    assert match.rl.defense in ("force", "info", "REST")
    assert ge.ACTIONS == CORE_ACTIONS
