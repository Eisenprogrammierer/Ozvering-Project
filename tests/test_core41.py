import json
import math
import random

import pytest

import simulation as S
from agents import (
    BDIPolicy,
    CHECKPOINT_VERSION,
    DUEL_CHECKPOINT_VERSION,
    DUEL_FEATURE_COUNT,
    DuelMLPPolicy,
    FEATURE_COUNT,
    MLPPolicy,
    PolicyAgent,
    QTablePolicy,
    RandomPolicy,
    load_policy,
    make_policy,
)
from agents.train import evaluate, train
from core41 import (
    Action,
    ArenaAgent,
    ArenaEnv,
    ArenaMatch,
    Automaton,
    CAPTURE_STREAK,
    CORE_ACTIONS,
    DuelEnv,
    DuelWorld,
    ENERGY_STORAGE_SHARE,
    Observation,
    RECEIVE_ENERGY_SHARE,
    REWARD_ADVANTAGE_ENERGY_COST,
    REWARD_TERMINAL_LOSS,
    REWARD_TERMINAL_WIN,
    REWARD_WOUND_OPPONENT,
    REWARD_WOUND_SELF,
    WAIT_ACTION,
    WOUND_MAX,
    Work,
    action_from_index,
    check_capture,
    conversion_efficiency,
    conversion_report,
    reward_delta,
    run_duel_tick,
    terminal_reward,
    work_amount,
    work_duration,
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


def test_conversion_report_conserves_work_and_marks_entropy():
    report = conversion_report(10.0, "info", 2.0)
    assert report["arrived"] == pytest.approx(
        10.0 * conversion_efficiency("info")
    )
    assert report["loss"] == pytest.approx(
        10.0 * (1.0 - conversion_efficiency("info"))
    )
    assert report["entropy"] == pytest.approx(
        report["arrived"] - report["stored"]
    )
    assert (
        report["loss"] + report["entropy"] + report["stored"]
        == pytest.approx(10.0)
    )
    assert report["efficiency"] == pytest.approx(
        conversion_efficiency("info")
    )


def test_automaton_energy_is_capped_and_reports_conversion_loss():
    unit = Automaton(id="cap", energy=99.0)
    result = unit.receive(Work(amount=100.0, form="info"))
    assert unit.energy == pytest.approx(unit.max_energy)
    assert result["stored"] == pytest.approx(1.0)
    total = result["loss"] + result["entropy"] + result["stored"]
    assert total == pytest.approx(100.0)
    assert result["entropy"] > 0.0


def test_rejected_work_is_accounted_as_pure_loss():
    unit = Automaton(id="closed", inputs=("force",), energy=10.0)
    result = unit.receive(Work(amount=4.0, form="info"))
    assert result["accepted"] is False
    assert result["stored"] == 0.0
    assert result["loss"] == pytest.approx(4.0)
    assert result["entropy"] == 0.0
    assert unit.energy == 10.0


def test_force_is_integrity_and_throughput_with_caps():
    unit = Automaton(id="unit", force=40.0, max_force=100.0)
    assert unit.force_ratio == pytest.approx(0.4)
    assert unit.force_throughput() == pytest.approx(40.0)
    assert unit.add_force(1000.0) == pytest.approx(60.0)
    assert unit.force == pytest.approx(100.0)
    assert unit.force_ratio == pytest.approx(1.0)


def test_handler_can_be_replaced_at_runtime_but_must_be_callable():
    unit = Automaton(id="runtime")
    calls = []

    def handler(target, work, source, world):
        calls.append(work.amount)
        return {"accepted": True, "success": True, "custom": True}

    unit.set_handler("info", handler)
    result = unit.receive(Work(amount=3.0, form="info"))
    assert result["custom"] is True
    assert calls == [3.0]
    unit.set_handler("info", None)
    assert unit.receive(Work(amount=1.0, form="info"))["accepted"] is True
    with pytest.raises(TypeError):
        unit.set_handler("force", "not-a-function")


def test_receive_energy_share_is_a_buffer_not_a_second_energy():
    assert 0.0 < RECEIVE_ENERGY_SHARE < ENERGY_STORAGE_SHARE


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


def test_mlp_policy_is_function_approximation_and_round_trips():
    policy = MLPPolicy(seed=7, epsilon=0.0)
    observation = _observation()
    action = Action("WORK", form="force", fraction=0.5)
    before = [row[:] for row in policy.weights1]
    policy.observe(
        Transition(
            observation=observation,
            action=action,
            reward=0.3,
            next_observation=observation,
            done=False,
            next_actions=(action,),
        )
    )
    assert policy.updates == 1
    assert policy.weights1 != before
    assert all(
        math.isfinite(value)
        for row in policy.weights1
        for value in row
    )
    state = json.loads(json.dumps(policy.state_dict()))
    loaded = MLPPolicy(seed=7)
    loaded.load_state_dict(state)
    assert loaded.hidden == policy.hidden
    assert loaded.weights1 == policy.weights1
    assert loaded.weights2 == policy.weights2
    assert loaded.score(observation, action) == pytest.approx(
        policy.score(observation, action)
    )


def test_mlp_policy_lowers_loss_on_fixed_task():
    policy = MLPPolicy(seed=3, epsilon=0.0, learning_rate=0.05)
    observation = _observation()
    good = Action("WORK", form="force", fraction=0.9)
    bad = Action("WORK", form="force", fraction=0.1)
    fixed = (
        Transition(
            observation=observation,
            action=good,
            reward=1.0,
            next_observation=observation,
            done=True,
        ),
        Transition(
            observation=observation,
            action=bad,
            reward=-1.0,
            next_observation=observation,
            done=True,
        ),
    )

    def loss():
        return sum(
            (item.reward - policy.score(item.observation, item.action)) ** 2
            for item in fixed
        ) / len(fixed)

    before = loss()
    for _ in range(200):
        for item in fixed:
            policy.observe(item)
    after = loss()
    assert after < before * 0.1
    assert policy.score(observation, good) > policy.score(observation, bad)
    assert policy.updates == 400


def test_mlp_target_network_freezes_then_syncs():
    policy = MLPPolicy(seed=5, epsilon=0.0, target_sync=2)
    observation = _observation()
    action = Action("WORK", form="force", fraction=0.5)
    transition = Transition(
        observation=observation,
        action=action,
        reward=0.3,
        next_observation=observation,
        done=False,
        next_actions=(action,),
    )
    initial_target = [row[:] for row in policy.target_weights1]
    policy.observe(transition)
    assert policy.updates == 1
    assert policy.target_weights1 == initial_target
    policy.observe(transition)
    assert policy.updates == 2
    assert policy.target_weights1 == policy.weights1
    assert policy.target_bias1 == policy.bias1
    assert policy.target_weights2 == policy.weights2
    assert policy.target_bias2 == policy.bias2


def test_mlp_target_network_round_trips_and_legacy_checkpoint_copies_online():
    policy = MLPPolicy(seed=9, epsilon=0.0, target_sync=1)
    observation = _observation()
    action = Action("WORK", form="force", fraction=0.5)
    for _ in range(3):
        policy.observe(
            Transition(
                observation=observation,
                action=action,
                reward=0.2,
                next_observation=observation,
                done=False,
                next_actions=(action,),
            )
        )
    state = json.loads(json.dumps(policy.state_dict()))
    loaded = MLPPolicy(seed=1)
    loaded.load_state_dict(state)
    assert loaded.target_sync == policy.target_sync
    assert loaded.target_weights1 == policy.target_weights1
    assert loaded.target_bias1 == policy.target_bias1
    assert loaded.target_weights2 == policy.target_weights2
    assert loaded.target_bias2 == policy.target_bias2
    assert loaded.target_score(observation, action) == pytest.approx(
        policy.target_score(observation, action)
    )

    legacy = dict(state)
    for key in (
        "target_weights1",
        "target_bias1",
        "target_weights2",
        "target_bias2",
        "target_sync",
    ):
        legacy.pop(key, None)
    migrated = MLPPolicy(seed=2, target_sync=7)
    migrated.load_state_dict(legacy)
    assert migrated.target_weights1 == migrated.weights1
    assert migrated.target_weights2 == migrated.weights2


def test_feature_count_includes_environment_features():
    from agents.policies import features

    observation = _observation()
    action = Action("WORK", form="force", fraction=0.5)
    vector = features(observation, action)
    assert FEATURE_COUNT == 22
    assert len(vector) == FEATURE_COUNT
    assert vector[-3] == pytest.approx(0.0)
    assert vector[-2] == pytest.approx(1.0)
    assert vector[-1] == pytest.approx(0.0)
    pressured = Observation(
        **{
            **observation.__dict__,
            "env_pressure": 0.75,
            "env_season": 1.3,
            "env_window": 1.0,
        }
    )
    pressured_vector = features(pressured, action)
    assert pressured_vector[-3] == pytest.approx(0.75)
    assert pressured_vector[-2] == pytest.approx(1.0)
    assert pressured_vector[-1] == pytest.approx(1.0)


def test_make_policy_exposes_mlp():
    assert isinstance(make_policy("mlp", seed=1), MLPPolicy)


def test_duel_mlp_uses_arena_features_and_round_trips():
    policy = DuelMLPPolicy(seed=7, epsilon=0.0)
    observation = _observation()
    action = Action("WORK", form="force", fraction=0.5)
    before = [row[:] for row in policy.weights1]
    policy.observe(
        Transition(
            observation=observation,
            action=action,
            reward=0.3,
            next_observation=observation,
            done=False,
            next_actions=(action,),
        )
    )
    assert policy.updates == 1
    assert policy.weights1 != before
    assert all(
        math.isfinite(value) for row in policy.weights1 for value in row
    )
    state = json.loads(json.dumps(policy.state_dict()))
    assert state["kind"] == "duel-mlp"
    loaded = DuelMLPPolicy(seed=99)
    loaded.load_state_dict(state)
    assert loaded.hidden == policy.hidden
    assert loaded.weights1 == policy.weights1
    assert loaded.score(observation, action) == pytest.approx(
        policy.score(observation, action)
    )


def test_duel_mlp_pads_short_feature_rows_on_load():
    policy = DuelMLPPolicy(seed=1)
    state = policy.state_dict()
    short = [[0.01] * (DUEL_FEATURE_COUNT - 3) for _ in range(policy.hidden)]
    state["weights1"] = short
    loaded = DuelMLPPolicy(seed=2)
    loaded.load_state_dict(state)
    assert all(len(row) == DUEL_FEATURE_COUNT for row in loaded.weights1)
    assert loaded.weights1[0][: DUEL_FEATURE_COUNT - 3] == pytest.approx(
        [0.01] * (DUEL_FEATURE_COUNT - 3)
    )
    assert loaded.weights1[0][DUEL_FEATURE_COUNT - 3:] == [0.0, 0.0, 0.0]


def test_duel_mlp_lowers_loss_on_fixed_task():
    policy = DuelMLPPolicy(seed=3, epsilon=0.0, learning_rate=0.05)
    observation = _observation()
    good = Action("WORK", form="force", fraction=0.9)
    bad = Action("REST", form="rest", fraction=0.0)
    initial_gap = policy.score(observation, good) - policy.score(
        observation, bad
    )
    for _step in range(400):
        policy.observe(
            Transition(
                observation=observation,
                action=good,
                reward=1.0,
                next_observation=observation,
                done=False,
                next_actions=(good, bad),
            )
        )
        policy.observe(
            Transition(
                observation=observation,
                action=bad,
                reward=-1.0,
                next_observation=observation,
                done=True,
                next_actions=(),
            )
        )
    final_gap = policy.score(observation, good) - policy.score(
        observation, bad
    )
    assert final_gap > initial_gap + 0.5
    assert policy.act(observation, (bad, good), explore=False) == good


def test_duel_mlp_target_network_freezes_then_syncs():
    policy = DuelMLPPolicy(seed=5, epsilon=0.0, target_sync=2)
    frozen = [row[:] for row in policy.target_weights1]
    observation = _observation()
    action = Action("WORK", form="force", fraction=0.5)
    transition = Transition(
        observation=observation,
        action=action,
        reward=0.5,
        next_observation=observation,
        done=False,
        next_actions=(action,),
    )
    policy.observe(transition)
    assert policy.target_weights1 == frozen
    policy.observe(transition)
    assert policy.target_weights1 != frozen
    assert policy.target_weights1 == policy.weights1


def test_make_policy_exposes_duel_mlp():
    assert isinstance(make_policy("duel-mlp", seed=1), DuelMLPPolicy)
    assert isinstance(make_policy("dmlp", seed=1), DuelMLPPolicy)


def test_load_policy_reads_duel_mlp_checkpoint(tmp_path):
    policy = DuelMLPPolicy(seed=4, epsilon=0.0)
    path = tmp_path / "duel-mlp.json"
    policy.save(str(path))
    loaded = load_policy(str(path), seed=8)
    assert isinstance(loaded, DuelMLPPolicy)
    observation = _observation()
    action = Action("WORK", form="info", fraction=0.3)
    assert loaded.score(observation, action) == pytest.approx(
        policy.score(observation, action)
    )


def _write_json(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_checkpoints_carry_version_and_round_trip(tmp_path):
    for name in ("bdi", "qtable", "mlp"):
        policy = make_policy(name, seed=3)
        state = policy.state_dict()
        assert state["version"] == CHECKPOINT_VERSION
        path = _write_json(tmp_path, "%s.json" % name, state)
        loaded = load_policy(path)
        assert type(loaded) is type(policy)
        assert loaded.state_dict()["kind"] == name


def test_qtable_migrates_legacy_10_field_keys(tmp_path):
    legacy_key = (1, 2, 3, 4, 5, 6, 0, "WORK", "force", 0.5)
    path = _write_json(
        tmp_path,
        "legacy_q.json",
        {
            "kind": "qtable",
            "table": {repr(legacy_key): 1.5},
            "epsilon": 0.1,
        },
    )
    policy = load_policy(path)
    assert len(policy.table) == 1
    migrated_key, value = next(iter(policy.table.items()))
    assert len(migrated_key) == 12
    assert migrated_key[:6] == legacy_key[:6]
    assert migrated_key[6:8] == (0, 0)
    assert migrated_key[8:] == legacy_key[6:]
    assert value == pytest.approx(1.5)


def test_qtable_migrates_legacy_8_field_keys_and_averages_collisions():
    key_a = (1, 2, 3, 4, 0, "REST", "rest", 0.0)
    key_b = (1, 2, 3, 4, 1, "REST", "rest", 0.0)
    policy = QTablePolicy(seed=0)
    policy.load_state_dict(
        {"kind": "qtable", "table": {repr(key_a): 1.0, repr(key_b): 3.0}}
    )
    assert len(policy.table) == 2
    for migrated_key in policy.table:
        assert len(migrated_key) == 12
        assert migrated_key[4:8] == (0, 0, 0, 0)

    policy2 = QTablePolicy(seed=0)
    policy2.load_state_dict(
        {
            "kind": "qtable",
            "table": {
                repr((1, 2, 3, 4, 5, "WORK", "force", 0.2)): 2.0,
            },
        }
    )
    assert len(policy2.table) == 1
    assert next(iter(policy2.table.values())) == pytest.approx(2.0)

    policy3 = QTablePolicy(seed=0)
    policy3.load_state_dict(
        {
            "kind": "qtable",
            "table": {
                repr((1, 2, 3, 4, 5, "WORK", "force", 0.24)): 1.0,
                repr((1, 2, 3, 4, 9, "WORK", "force", 0.24)): 3.0,
            },
        }
    )
    assert len(policy3.table) == 2
    for migrated_key in policy3.table:
        assert migrated_key[4:8] == (0, 0, 0, 0)


def test_load_policy_rejects_future_version(tmp_path):
    path = _write_json(
        tmp_path,
        "future.json",
        {"kind": "bdi", "version": CHECKPOINT_VERSION + 5},
    )
    with pytest.raises(ValueError):
        load_policy(path)


def test_bdi_pads_short_legacy_weights():
    policy = BDIPolicy(seed=0)
    policy.load_state_dict({"kind": "bdi", "weights": [0.1] * 16})
    assert len(policy.weights) == FEATURE_COUNT
    assert policy.weights[:16] == [0.1] * 16
    assert policy.weights[16:] == [0.0] * (FEATURE_COUNT - 16)


def test_train_resume_continues_from_checkpoint(tmp_path):
    base = make_policy("bdi", seed=11)
    observation = _observation()
    action = Action("WORK", form="force", fraction=0.5)
    transition = Transition(
        observation=observation,
        action=action,
        reward=0.5,
        next_observation=observation,
        done=False,
        next_actions=(action,),
    )
    base.observe(transition)
    weights_after_one_update = list(base.weights)
    path = _write_json(tmp_path, "resume_bdi.json", base.state_dict())

    fresh = make_policy("bdi", seed=11)
    fresh.load_state_dict(json.loads(open(path).read()))
    assert fresh.weights == weights_after_one_update

    _, stats = train(
        episodes=1,
        seed=5,
        policy_name="bdi",
        max_steps=8,
        eval_episodes=0,
        resume=path,
    )
    assert stats["resumed_from"] == path
    assert stats["policy_updates"] >= 1


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
    policy, stats = train(
        episodes=2, seed=9, max_steps=20, eval_episodes=0
    )
    assert stats["episodes"] == 2
    assert stats["wins"] + stats["losses"] + stats["draws"] == 2
    assert isinstance(policy, BDIPolicy)


def test_self_play_updates_both_policies_once_per_tick():
    policy, stats = train(
        episodes=2,
        seed=13,
        max_steps=20,
        self_play=True,
        eval_episodes=0,
    )
    assert stats["self_play"] is True
    assert stats["policy_updates"] > 0
    assert stats["opponent_updates"] > 0
    assert policy.updates == stats["policy_updates"]


def test_evaluate_uses_held_out_seed_and_does_not_learn():
    policy = BDIPolicy(seed=4, epsilon=0.0)
    opponent = RandomPolicy(seed=5)
    weights_before = list(policy.weights)
    stats = evaluate(
        policy,
        opponent,
        episodes=2,
        seed=9000,
        max_steps=20,
    )
    assert stats["seed"] == 9000
    assert stats["episodes"] == 2
    assert stats["wins"] + stats["losses"] + stats["draws"] == 2
    assert policy.weights == weights_before


def test_evaluate_forwards_explore_mode():
    class _Probe(RandomPolicy):
        def __init__(self):
            super().__init__(seed=3)
            self.modes = []

        def act(self, observation, actions, explore=True):
            self.modes.append(bool(explore))
            return super().act(observation, actions, explore=explore)

    probe = _Probe()
    evaluate(
        probe,
        RandomPolicy(seed=4),
        episodes=2,
        seed=9001,
        max_steps=10,
        explore=True,
    )
    assert probe.modes
    assert all(probe.modes)


def test_training_eval_matrix_uses_separate_opponents():
    _policy, stats = train(
        episodes=1,
        seed=21,
        max_steps=10,
        eval_episodes=1,
        eval_seed=7000,
        eval_opponents=("random",),
    )
    assert len(stats["eval"]) == 1
    row = stats["eval"][0]
    assert row["policy"] == "bdi"
    assert row["opponent"] == "random"
    assert row["seed"] == 7000


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


def test_reward_terminal_bonus_for_winner_and_loser():
    match = ArenaMatch(
        seed=2,
        steps=10,
        rl_policy=RandomPolicy(seed=2),
        ai_policy=RandomPolicy(seed=3),
    )
    match.ai.health = 0.0
    match.step_tick(
        forced_rl_action=Action("REST", form="rest"),
        forced_ai_action=Action("REST", form="rest"),
    )
    assert match.winner == "RL"
    assert match.last_rewards["rl"] >= REWARD_TERMINAL_WIN
    assert match.last_rewards["ai"] <= REWARD_TERMINAL_LOSS
    assert terminal_reward("RL", "rl") == REWARD_TERMINAL_WIN
    assert terminal_reward("RL", "ai") == REWARD_TERMINAL_LOSS
    assert terminal_reward("draw", "rl") == 0.0


def test_reward_delta_values_treatment_and_sickness():
    me = Automaton(id="me", force=100.0, energy=100.0, health=100.0)
    other = Automaton(id="other", force=100.0, energy=100.0, health=100.0)
    me.sickness = 0.5
    other.sickness = 0.0
    before = (100.0, 100.0, 100.0, 0.5)
    other_before = (100.0, 100.0, 100.0, 0.0)

    me.energy = 90.0
    me.sickness = 0.42
    reward = reward_delta(
        me, before, other, other_before, profile="legacy"
    )
    assert reward == pytest.approx(-0.06 + 0.08)

    other.sickness = 0.25
    reward = reward_delta(
        me, before, other, other_before, profile="legacy"
    )
    assert reward == pytest.approx(-0.06 + 0.08 + 0.5 * 0.25)


def test_reward_delta_wound_tuple_extends_legacy_contract():
    me = Automaton(id="me", force=100.0, energy=100.0, health=100.0)
    other = Automaton(id="other", force=100.0, energy=100.0, health=100.0)
    legacy_before = (100.0, 100.0, 100.0, 0.0)
    assert reward_delta(me, legacy_before, other, legacy_before) == 0.0

    me.wound = 0.25
    extended_before = (100.0, 100.0, 100.0, 0.0, 0.0)
    reward = reward_delta(me, extended_before, other, extended_before)
    assert reward == pytest.approx(REWARD_WOUND_SELF * -0.25 / WOUND_MAX)

    other.wound = 0.5
    reward = reward_delta(
        me, extended_before, other, (100.0, 100.0, 100.0, 0.0, 0.0)
    )
    assert reward == pytest.approx(
        REWARD_WOUND_SELF * -0.25 / WOUND_MAX
        + REWARD_WOUND_OPPONENT * 0.5 / WOUND_MAX
    )


def test_advantage_reward_ignores_regeneration_and_pays_for_damage():
    me = Automaton(id="me", force=90.0, energy=100.0, health=95.0)
    other = Automaton(id="other")
    full = (100.0, 100.0, 100.0, 0.0)
    assert reward_delta(
        me,
        (80.0, 90.0, 90.0, 0.0),
        other,
        full,
        profile="advantage",
    ) == pytest.approx(0.0)

    damaged = Automaton(id="damaged", force=70.0, health=90.0)
    assert reward_delta(
        Automaton(id="me"),
        full,
        damaged,
        full,
        profile="advantage",
    ) == pytest.approx(0.3 + 0.1)

    hurt = Automaton(id="hurt", force=70.0, health=90.0)
    assert reward_delta(
        hurt,
        full,
        Automaton(id="other"),
        full,
        profile="advantage",
    ) == pytest.approx(-(0.3 + 0.1))


def test_advantage_cost_charges_spent_energy_only():
    other = Automaton(id="other")
    full = (100.0, 100.0, 100.0, 0.0)

    spent = Automaton(id="spent", energy=70.0)
    free = reward_delta(
        spent, full, other, full, profile="advantage"
    )
    paid = reward_delta(
        spent, full, other, full, profile="advantage_cost"
    )
    assert free == pytest.approx(0.0)
    assert paid == pytest.approx(-REWARD_ADVANTAGE_ENERGY_COST * 0.3)

    recovered = Automaton(id="recovered", energy=100.0)
    assert reward_delta(
        recovered,
        (100.0, 70.0, 100.0, 0.0),
        other,
        full,
        profile="advantage_cost",
    ) == pytest.approx(0.0)


def test_default_reward_profile_is_advantage_cost():
    me = Automaton(id="me", force=90.0, energy=70.0, health=95.0)
    other = Automaton(id="other")
    reward = reward_delta(
        me,
        (80.0, 90.0, 90.0, 0.0),
        other,
        (100.0, 100.0, 100.0, 0.0),
    )
    assert reward == pytest.approx(-REWARD_ADVANTAGE_ENERGY_COST * 0.2)


def test_arena_reward_profile_is_validated_and_forwarded():
    env = ArenaEnv(
        seed=1,
        steps=10,
        policy=BDIPolicy(seed=1),
        opponent_policy=BDIPolicy(seed=2),
        reward_profile="advantage",
    )
    assert env.reward_profile == "advantage"
    assert env.match.reward_profile == "advantage"

    with pytest.raises(ValueError):
        ArenaMatch(seed=0, reward_profile="unknown")


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
        Action("WORK", form="force", fraction=0.3),
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
        rl, ai, dom_rl=CAPTURE_STREAK - 1, dom_ai=0
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
    assert match.env is not None
    assert match.env is match.core.env
    for _ in range(8):
        match.step_tick()
    assert match.step == 8
    assert match.finished
    assert len(match.rl_hist) == 8
    assert match.rl.defense in ("force", "info", "REST")
    assert ge.ACTIONS == CORE_ACTIONS


def test_randomize_draw_is_deterministic_and_in_range():
    import random

    from core41 import randomize_draw

    first = randomize_draw(
        rng=random.Random(5),
        profiles=("CANON", "ZEALOT"),
        health_factors=("aging",),
        sickness_min=0.1,
        sickness_max=0.4,
        health_min=0.8,
        health_max=1.2,
    )
    second = randomize_draw(
        rng=random.Random(5),
        profiles=("CANON", "ZEALOT"),
        health_factors=("aging",),
        sickness_min=0.1,
        sickness_max=0.4,
        health_min=0.8,
        health_max=1.2,
    )
    assert first == second
    assert first["profile_rl"] in ("CANON", "ZEALOT")
    assert 0.1 <= first["sickness_rl"] <= 0.4
    assert 0.8 <= first["health_factors_rl"]["aging"] <= 1.2
    try:
        randomize_draw(profiles=("NOPE",))
        raise AssertionError("unknown profile accepted")
    except ValueError:
        pass
    try:
        randomize_draw(health_factors=("bogus",))
        raise AssertionError("unknown health factor accepted")
    except ValueError:
        pass


def test_arena_env_apply_domain_rebuilds_match_and_rejects_unknown_keys():
    from core41 import ArenaEnv

    env = ArenaEnv(seed=1, steps=40)
    observation = env.apply_domain(
        profile_rl="ZEALOT",
        sickness_ai=0.3,
        health_factors_rl={"aging": 1.1},
    )
    assert observation is not None
    assert env.profile_rl == "ZEALOT"
    assert env.sickness_ai == 0.3
    assert env.match.rl.profile == "ZEALOT"
    try:
        env.apply_domain(bogus=1)
        raise AssertionError("unknown domain key accepted")
    except ValueError:
        pass


def test_train_domain_randomize_is_reproducible_and_skips_duel():
    from agents.train import train

    opts = {
        "profiles": ("CANON", "ZEALOT"),
        "health_factors": ("aging",),
        "sickness_min": 0.0,
        "sickness_max": 0.5,
        "health_min": 0.75,
        "health_max": 1.25,
        "skill_jitter": 0.0,
    }
    results = []
    for _ in range(2):
        _policy, stats = train(
            episodes=3,
            seed=11,
            policy_name="bdi",
            opponent_name="random",
            max_steps=25,
            env_name="arena",
            eval_episodes=0,
            domain_randomize=True,
            domain_opts=opts,
        )
        results.append(stats)
    assert results[0]["domain_randomize"] is True
    assert results[0] == results[1]
    _policy, duel_stats = train(
        episodes=2,
        seed=1,
        policy_name="bdi",
        opponent_name="random",
        max_steps=20,
        env_name="duel",
        eval_episodes=0,
        domain_randomize=True,
        domain_opts=opts,
    )
    assert duel_stats["domain_randomize"] is False


def test_campaign_env_domain_sickness_reaches_engine():
    import random

    from campaign.env import CampaignEnv

    env = CampaignEnv(seed=3, max_days=4)
    assert env.engine.player_condition()["sickness"] == 0.0
    draw = env.randomize_draw(
        rng=random.Random(9),
        skill_jitter=0.2,
        sickness_min=0.2,
        sickness_max=0.5,
    )
    env.apply_domain(**draw)
    condition = env.engine.player_condition()
    assert abs(condition["sickness"] - draw["sickness"]) < 1e-6


def test_train_campaign_career_flag_opens_career_space():
    """Готовность A3: флаг `--campaign-career` проброшен в обучение."""
    from agents.train import main as train_main

    from campaign.env import CampaignEnv as _CE

    with_career = _CE(seed=3, max_days=4, career_actions=True)
    without_career = _CE(seed=3, max_days=4)
    with_career.reset(seed=3)
    without_career.reset(seed=3)
    kinds_with = {a.kind for a in with_career.legal_actions()}
    kinds_without = {a.kind for a in without_career.legal_actions()}
    career_ids = {"seek_promotion", "request_transfer", "resign"}
    assert kinds_with > kinds_without
    assert kinds_with - kinds_without <= career_ids
    assert len(with_career.legal_actions()) > len(
        without_career.legal_actions()
    )

    career_ckpt = "/tmp/a3_career_ckpt.json"
    nocareer_ckpt = "/tmp/a3_nocareer_ckpt.json"
    rc = train_main([
        "--env", "campaign", "--episodes", "2", "--max-steps", "6",
        "--policy", "bdi", "--seed", "3", "--eval-episodes", "0",
        "--campaign-career", "--out", career_ckpt,
    ])
    assert rc == 0
    import json

    from agents.checkpoints import read_checkpoint

    state = read_checkpoint(career_ckpt)
    assert isinstance(state, dict) and state
    rc2 = train_main([
        "--env", "campaign", "--episodes", "2", "--max-steps", "6",
        "--policy", "bdi", "--seed", "3", "--eval-episodes", "0",
        "--out", nocareer_ckpt,
    ])
    assert rc2 == 0
    state2 = read_checkpoint(nocareer_ckpt)
    assert isinstance(state2, dict) and state2
    fresh = _CE(seed=3, max_days=4)
    assert fresh.engine.player_condition()["sickness"] == 0.0


def test_duel_eval_domain_flag_is_not_reported_as_applied():
    from agents.train import train

    _policy, stats = train(
        episodes=1,
        seed=2,
        policy_name="bdi",
        opponent_name="random",
        max_steps=12,
        env_name="duel",
        eval_episodes=1,
        eval_domain_randomize=True,
    )
    assert stats["domain_randomize"] is False
    assert stats["eval"]
    assert all("domain_randomized" not in row for row in stats["eval"])


class _AlwaysHit:
    def random(self):
        return 0.0


def test_simultaneous_tick_uses_start_snapshot_for_both_attacks():
    left = ArenaAgent("left", force=100, energy=100)
    right = ArenaAgent("right", force=40, energy=100)
    left.unit.skills["force"] = 1.0
    right.unit.skills["force"] = 1.0
    _events, left_result, right_result = run_duel_tick(
        left,
        Action("WORK", form="force", fraction=0.3),
        right,
        Action("WORK", form="force", fraction=0.3),
        rng=_AlwaysHit(),
    )
    assert left_result["spent"] == pytest.approx(30.0)
    assert right_result["spent"] == pytest.approx(30.0)
    assert left_result["success"] is True
    assert right_result["success"] is True
    assert left.force < 100.0
    assert right.force < 40.0


def test_health_reduces_attack_effectiveness():
    from core41.model import HEALTH_ATTACK_FLOOR, success_probability

    healthy = Automaton(id="healthy", skills={"force": 0.8})
    hurt = Automaton(id="hurt", skills={"force": 0.8}, health=25.0)
    defender = Automaton(id="target")
    work = Work(amount=20.0, form="force")

    assert hurt.attack_effectiveness() == pytest.approx(
        HEALTH_ATTACK_FLOOR + (1.0 - HEALTH_ATTACK_FLOOR) * 0.25
    )
    assert success_probability(
        hurt, defender, work, False
    ) < success_probability(healthy, defender, work, False)


def test_force_caps_work_per_tick():
    weak = ArenaAgent("weak", force=12, energy=100)
    strong = ArenaAgent("strong", force=100, energy=100)
    action = Action("WORK", form="force", fraction=0.7)
    assert work_amount(weak.unit, action) == pytest.approx(12.0)
    assert work_amount(strong.unit, action) == pytest.approx(70.0)
    assert work_duration("force", 0.7) == 2.0
    assert work_duration("force", 0.3) == 1.0


def test_strong_force_charges_then_waits():
    left = ArenaAgent("left", energy=100)
    right = ArenaAgent("right")
    _events, first, _other = run_duel_tick(
        left,
        Action("WORK", form="force", fraction=0.7),
        right,
        Action("REST", form="rest"),
        rng=random.Random(1),
    )
    assert first["kind"] == "charge"
    assert left.pending is not None
    assert [action.kind for action in left.actions()] == ["WAIT"]
    seen = right.observe(left)
    assert seen.opponent_busy == 1.0
    assert seen.opponent_pending_form == "force"
    assert seen.opponent_pending_fraction == pytest.approx(0.7)

    _events, second, _other = run_duel_tick(
        left,
        WAIT_ACTION,
        right,
        Action("REST", form="rest"),
        rng=random.Random(1),
    )
    assert second["kind"] == "work"
    assert second["duration"] == pytest.approx(2.0)
    assert left.pending is None


def test_fog_hides_hidden_fields_until_info_reveals_them():
    match = ArenaMatch(seed=3, steps=5, fog=True)
    match.rng = _AlwaysHit()
    match.ai.health = 35.0
    match.ai.sickness = 0.4
    match.ai.wound = 0.2

    hidden = match.rl.observe(match.ai)
    assert hidden.opponent_health != pytest.approx(35.0)
    assert hidden.opponent_sickness != pytest.approx(0.4)
    assert hidden.opponent_confidence == pytest.approx(0.5)

    match.step_tick(
        forced_rl_action=Action("WORK", form="info", fraction=0.3),
        forced_ai_action=Action("REST", form="rest"),
    )
    revealed = match.rl.observe(match.ai)
    assert revealed.opponent_health == pytest.approx(match.ai.health)
    assert revealed.opponent_sickness == pytest.approx(match.ai.sickness)
    assert revealed.opponent_confidence == pytest.approx(1.0)
    assert revealed.opponent_weak_point == pytest.approx(1.0)


def test_force_exploits_weak_point_for_more_damage():
    def damage_with(weak_point):
        attacker = ArenaAgent("attacker", force=100, energy=100)
        defender = ArenaAgent("defender", force=100, energy=100)
        attacker.intel.weak_point = float(weak_point)
        _events, result, _other = run_duel_tick(
            attacker,
            Action("WORK", form="force", fraction=0.3),
            defender,
            Action("REST", form="rest"),
            rng=_AlwaysHit(),
        )
        return result["damage"]

    assert damage_with(1.0) > damage_with(0.0)


def test_wait_is_not_counted_as_attack_by_opponent_model():
    from agents.policies import OpponentModel

    waiting = OpponentModel()
    resting = OpponentModel()
    waiting.update(Action("WAIT", form="wait"))
    resting.update(Action("REST", form="rest"))
    assert waiting.attack == pytest.approx(resting.attack)
    assert waiting.force_share == pytest.approx(0.0)


def test_force_work_is_counted_as_attack_by_opponent_model():
    """`ArenaEnv` передаёт `Action(kind="WORK")`, а не аренный тег."""
    from agents.policies import OpponentModel

    force = OpponentModel()
    force.update(Action("WORK", form="force", fraction=0.7))
    assert force.attack > 0.25
    assert force.force_share > 0.0

    info = OpponentModel()
    info.update(Action("WORK", form="info", fraction=0.3))
    assert info.attack > 0.25
    assert info.force_share == pytest.approx(0.0)

    passive = OpponentModel()
    passive.update(Action("WORK", form="defense", fraction=0.0))
    assert passive.attack < 0.25
    assert passive.force_share == pytest.approx(0.0)


def test_duel_vector_has_fog_and_pending_slots():
    from dataclasses import replace

    from agents.policies import OpponentModel, features

    observation = replace(
        _observation(),
        opponent_confidence=0.4,
        opponent_weak_point=0.7,
        opponent_pending_form="force",
        opponent_pending_fraction=0.7,
    )
    vector = features(
        observation,
        Action("WORK", form="force", fraction=0.3),
        OpponentModel().stats(),
    )
    assert DUEL_FEATURE_COUNT == 30
    assert len(vector) == DUEL_FEATURE_COUNT
    assert vector[-4:] == pytest.approx((0.4, 0.7, 1.0, 0.7))


def test_duel_checkpoint_pads_legacy_26_feature_rows():
    source = DuelMLPPolicy(seed=5)
    state = source.state_dict()
    state["version"] = 4
    state["feature_count"] = 26
    state["weights1"] = [row[:26] for row in state["weights1"]]
    state["target_weights1"] = [
        row[:26] for row in state["target_weights1"]
    ]
    restored = DuelMLPPolicy(seed=6)
    restored.load_state_dict(state)
    assert DUEL_CHECKPOINT_VERSION == 5
    assert all(
        len(row) == DUEL_FEATURE_COUNT for row in restored.weights1
    )
    assert all(
        len(row) == DUEL_FEATURE_COUNT
        for row in restored.target_weights1
    )
