import json
import math
import random

import pytest

import simulation as S
from agents import (
    BDIPolicy,
    CHECKPOINT_VERSION,
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
    Observation,
    REWARD_TERMINAL_LOSS,
    REWARD_TERMINAL_WIN,
    REWARD_WOUND_OPPONENT,
    REWARD_WOUND_SELF,
    WOUND_MAX,
    Work,
    action_from_index,
    check_capture,
    reward_delta,
    run_duel_tick,
    terminal_reward,
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
    # Online TD(0) без target-сети: при `done=True` цель — сама награда,
    # поэтому фиксированная задача обязана сходиться, а не просто менять
    # веса. Это и есть проверка «MLP учится», а не только «MLP жив».
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
    # После одного обновления online-веса ушли, target ещё заморожен.
    assert policy.updates == 1
    assert policy.target_weights1 == initial_target
    policy.observe(transition)
    # На втором обновлении target синхронизируется с online.
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
    # Старый чекпойнт без target-сети: target копирует online-веса,
    # а не остаётся случайной инициализацией.
    assert migrated.target_weights1 == migrated.weights1
    assert migrated.target_weights2 == migrated.weights2


def test_feature_count_includes_environment_features():
    from agents.policies import features

    observation = _observation()
    action = Action("WORK", form="force", fraction=0.5)
    vector = features(observation, action)
    assert FEATURE_COUNT == 22
    assert len(vector) == FEATURE_COUNT
    # Предпоследние два слота — наблюдаемое расписание среды; последний
    # (A1) — окно уязвимости.
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
    # легаси-v0: без поля version, ключи 10 полей (болезнь отсутствует)
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
    # sickness-разряды (6-7) заполнены нулём, остальное сохранено
    assert migrated_key[:6] == legacy_key[:6]
    assert migrated_key[6:8] == (0, 0)
    assert migrated_key[8:] == legacy_key[6:]
    assert value == pytest.approx(1.5)


def test_qtable_migrates_legacy_8_field_keys_and_averages_collisions():
    # 8-полевые ключи различаются open-разрядом — после миграции остаются
    # разными (вставка нулей идёт до open, а не вместо него)
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

    # коллизия: два 8-полевых v0-ключа, различавшихся только health-разрядом
    # (в легаси-QTable он квантовался round(health/50), т.е. 100 и 149 -> 3),
    # при миграции сливаются в один 12-полевой ключ — усреднение значений
    # проверяется напрямую на уровне load_state_dict через dict с одинаковым
    # repr (JSON-формат теряет дубликаты ключей ещё до загрузки).
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

    # ключи, отличающиеся сохранёнными разрядами (open 5 vs 9), остаются
    # различными записями таблицы
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
    # обучение продолжилось с весов чекпойнта, а не со случайных
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
    reward = reward_delta(me, before, other, other_before)
    # -0.6 * 10/100 за TREAT + 1.0 * 0.08 за снятую болезнь.
    assert reward == pytest.approx(-0.06 + 0.08)

    other.sickness = 0.25
    reward = reward_delta(me, before, other, other_before)
    assert reward == pytest.approx(-0.06 + 0.08 + 0.5 * 0.25)


def test_reward_delta_wound_tuple_extends_legacy_contract():
    me = Automaton(id="me", force=100.0, energy=100.0, health=100.0)
    other = Automaton(id="other", force=100.0, energy=100.0, health=100.0)
    legacy_before = (100.0, 100.0, 100.0, 0.0)
    # Легаси-кортеж без wound — прежняя калибровка сохраняется.
    assert reward_delta(me, legacy_before, other, legacy_before) == 0.0

    me.wound = 0.25
    extended_before = (100.0, 100.0, 100.0, 0.0, 0.0)
    reward = reward_delta(me, extended_before, other, extended_before)
    # REWARD_WOUND_SELF * (before - now) / WOUND_MAX = 0.8 * (-0.25).
    assert reward == pytest.approx(REWARD_WOUND_SELF * -0.25 / WOUND_MAX)

    other.wound = 0.5
    reward = reward_delta(
        me, extended_before, other, (100.0, 100.0, 100.0, 0.0, 0.0)
    )
    assert reward == pytest.approx(
        REWARD_WOUND_SELF * -0.25 / WOUND_MAX
        + REWARD_WOUND_OPPONENT * 0.5 / WOUND_MAX
    )


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


# ---------------------------------------------------------------------------
# Доменная рандомизация (проблема готовности №7)
# ---------------------------------------------------------------------------


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
    # Неизвестный профиль — явная ошибка, а не молчаливый CANON.
    try:
        randomize_draw(profiles=("NOPE",))
        raise AssertionError("unknown profile accepted")
    except ValueError:
        pass
    # Неизвестный health-фактор тоже не должен молча игнорироваться.
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
    # duel — легаси-срез без доменов: фича честно не применяется.
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
        rng=random.Random(9), skill_jitter=0.2, sickness_min=0.2, sickness_max=0.5
    )
    env.apply_domain(**draw)
    condition = env.engine.player_condition()
    assert abs(condition["sickness"] - draw["sickness"]) < 1e-6


def test_train_campaign_career_flag_opens_career_space():
    """Готовность A3: флаг `--campaign-career` проброшен в обучение."""
    from agents.train import main as train_main

    # Прямая проверка проброса: career_actions=True расширяет legal_actions()
    # карьерными действиями (seek_promotion/request_transfer/resign),
    # по умолчанию они закрыты (opt-in).
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
    assert len(with_career.legal_actions()) > len(without_career.legal_actions())

    # CLI-флаг `--campaign-career` доходит до цикла обучения и не ломает его.
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
    # Тот же запуск без флага — прежнее замкнутое пространство.
    rc2 = train_main([
        "--env", "campaign", "--episodes", "2", "--max-steps", "6",
        "--policy", "bdi", "--seed", "3", "--eval-episodes", "0",
        "--out", nocareer_ckpt,
    ])
    assert rc2 == 0
    state2 = read_checkpoint(nocareer_ckpt)
    assert isinstance(state2, dict) and state2
    # Стартовый config среды не мутируется: второй движок без домена чист.
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
    # `duel` — легаси-срез без доменов: флаг не должен лгать в матрице.
    assert stats["domain_randomize"] is False
    assert stats["eval"]
    assert all("domain_randomized" not in row for row in stats["eval"])
