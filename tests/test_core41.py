import json
import random

import pytest

import simulation as S
from agents import BDIPolicy, PolicyAgent, QTablePolicy, RandomPolicy
from agents.train import train
from core41 import Action, Automaton, DuelEnv, DuelWorld, Observation, Work
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


def test_commander_ai_uses_policy_agent():
    from ui.battlefield import Commander

    commander = Commander("test", "enemy", ai=True)
    assert isinstance(commander.agent, PolicyAgent)
    assert commander.intention()[0] in tuple(S.TYPES) + ("REST",)


def test_core_training_smoke():
    policy, stats = train(episodes=2, seed=9, max_steps=20)
    assert stats["episodes"] == 2
    assert stats["wins"] + stats["losses"] + stats["draws"] == 2
    assert isinstance(policy, BDIPolicy)
