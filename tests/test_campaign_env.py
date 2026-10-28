"""Тесты кампанейной среды `CampaignEnv` (проблема готовности №6).

Среда — Gym-подобный контракт reset/step над дневным `WorldEngine`:
плоское нормированное наблюдение, награда из дельт положения/организации/
здоровья/болезни + терминальный бонус исхода, одиночный агент (без оппонента
и self-play), персистентность через снимок мира. Открытые вопросы §7 (28–31)
здесь фиксируются как наблюдаемые флаги, но не считаются закрытыми.
"""

import json

import pytest

from agents import BDIPolicy, QTablePolicy, make_policy
from agents.policies import campaign_features
from agents.train import evaluate, train
from campaign.env import (
    CAMPAIGN_REWARD_ILLEGAL,
    END_DAY,
    CampaignEnv,
    campaign_reward,
    terminal_campaign_reward,
)
from core41.types import (
    Action,
    CampaignAction,
    CampaignObservation,
    Observation,
    Transition,
)


def _run_random(env, rng, limit=80):
    """Прогон случайной политики до done/truncated; возвращает (steps, info)."""
    steps = 0
    info = {}
    while steps < limit:
        actions = tuple(env.legal_actions())
        action = rng.choice(actions)
        _obs, _reward, done, truncated, info = env.step(action)
        steps += 1
        if done or truncated:
            break
    return steps, info


# ---------------------------------------------------------------------------
# Контракт среды
# ---------------------------------------------------------------------------


def test_campaign_env_reset_returns_flat_normalized_observation():
    env = CampaignEnv(seed=1, max_days=6)
    observation = env.reset(seed=1)
    assert isinstance(observation, CampaignObservation)
    assert observation.day == 1
    assert observation.total_days == 6
    assert observation.attached is True
    assert observation.alive is True
    assert 0.0 <= observation.sickness <= 1.0
    assert observation.health == pytest.approx(100.0)
    # Нормированные поля в [0, 1].
    for name in (
        "influence",
        "favor",
        "evidence",
        "standing",
        "authority",
        "power",
        "cohesion",
    ):
        value = getattr(observation, name)
        assert -1.0 <= value <= 1.0, name


def test_campaign_env_legal_actions_always_include_end_day():
    env = CampaignEnv(seed=2, max_days=5)
    env.reset(seed=2)
    actions = tuple(env.legal_actions())
    kinds = {action.kind for action in actions}
    assert END_DAY in kinds
    assert env.action_space == actions
    # Career-действия исключены из MVP (вопрос №29).
    career_ids = {
        action_id
        for action_id, action in env.engine.actions.items()
        if action.get("career")
    }
    assert kinds.isdisjoint(career_ids)


def test_campaign_env_is_deterministic_per_seed():
    def rollout(seed):
        env = CampaignEnv(seed=seed, max_days=4)
        env.reset(seed=seed)
        trace = []
        for _ in range(10):
            actions = tuple(env.legal_actions())
            _obs, reward, done, truncated, info = env.step(actions[-1])
            trace.append((round(reward, 6), done, truncated, info["day"]))
            if done or truncated:
                break
        return trace

    assert rollout(7) == rollout(7)


def test_campaign_env_truncates_at_horizon_without_outcome():
    env = CampaignEnv(seed=1, max_days=2)
    env.reset(seed=1)
    truncated_seen = False
    for _ in range(30):
        _obs, _reward, done, truncated, info = env.step(CampaignAction(END_DAY))
        if truncated:
            truncated_seen = True
            assert done is False
            assert info["horizon"] is True
            assert env.engine.finished is False
            break
        if done:
            break
    assert truncated_seen


def test_campaign_env_step_after_finish_raises():
    env = CampaignEnv(seed=2, max_days=3)
    env.reset(seed=2)
    steps = 0
    while not env.engine.finished and steps < 60:
        actions = tuple(env.legal_actions())
        env.step(actions[-1])
        steps += 1
    assert env.engine.finished
    with pytest.raises(RuntimeError):
        env.step(CampaignAction(END_DAY))


def test_campaign_env_accepts_plain_string_action():
    env = CampaignEnv(seed=5, max_days=5)
    env.reset(seed=5)
    observation, reward, done, truncated, info = env.step(END_DAY)
    assert isinstance(observation, CampaignObservation)
    assert info["result"]["ok"] is True
    assert env.last_transition["observation"] is observation


def test_campaign_env_illegal_action_penalizes_without_exception():
    env = CampaignEnv(seed=5, max_days=5)
    env.reset(seed=5)
    before = env._metrics()["standing"]
    observation, reward, done, truncated, info = env.step(
        CampaignAction("no_such_action", target="no_such_node")
    )
    assert info["illegal"] is True
    assert info["result"]["ok"] is False
    assert reward <= -CAMPAIGN_REWARD_ILLEGAL + 1e-9
    assert env._metrics()["standing"] == pytest.approx(before)
    assert not done or env.engine.finished


# ---------------------------------------------------------------------------
# Награда
# ---------------------------------------------------------------------------


def test_campaign_reward_composition_matches_formula():
    before = {
        "standing": 0.20,
        "power": 0.50,
        "cohesion": 0.50,
        "health": 100.0,
        "sickness": 0.0,
    }
    after = {
        "standing": 0.40,
        "power": 0.60,
        "cohesion": 0.50,
        "health": 90.0,
        "sickness": 0.20,
    }
    # 0.5*0.2 + 0.25*0.1 - 0.1 - 0.2 = -0.175
    assert campaign_reward(before, after) == pytest.approx(-0.175)
    # успех даёт малый shaping, терминал — исход сюжета
    assert campaign_reward(before, after, success=True) == pytest.approx(
        -0.175 + 0.10
    )
    assert campaign_reward(
        before, after, outcome_delta=terminal_campaign_reward("win")
    ) == pytest.approx(-0.175 + 1.0)


def test_terminal_campaign_reward_maps_outcomes():
    assert terminal_campaign_reward("win") == 1.0
    assert terminal_campaign_reward("lose") == -1.0
    assert terminal_campaign_reward("") == 0.0
    assert terminal_campaign_reward(None) == 0.0


def test_campaign_env_terminal_step_carries_outcome_bonus():
    # Ищем сид, при котором кампания завершается естественным исходом
    # (смерть героя или распад организации) до горизонта max_days:
    # именно на таком терминальном шаге должен появиться outcome_bonus.
    found = False
    for seed in range(1, 40):
        env = CampaignEnv(seed=seed, max_days=30)
        env.reset(seed=seed)
        last = None
        steps = 0
        while steps < 400:
            actions = tuple(env.legal_actions())
            result = env.step(actions[-1])
            steps += 1
            last = result
            if result[2] or result[3]:
                break
        _obs, _reward, done, truncated, info = last
        if not done:
            continue
        assert truncated is False
        assert info["outcome"] in ("win", "lose")
        assert info["outcome_delta"] == terminal_campaign_reward(info["outcome"])
        found = True
        break
    assert found, "ни один сид из 1..39 не довёл кампанию до терминального исхода"


def test_campaign_env_horizon_truncates_without_outcome_bonus():
    # Горизонт max_days без естественного финала — усечение (truncated),
    # а не поражение; терминальный бонус на таком шаге отсутствует (№30).
    env = CampaignEnv(seed=7, max_days=2)
    env.reset(seed=7)
    last = None
    for _ in range(30):
        result = env.step(CampaignAction(END_DAY))
        last = result
        if result[2] or result[3]:
            break
    _obs, _reward, done, truncated, info = last
    assert done is False
    assert truncated is True
    assert info["horizon"] is True
    assert info["outcome_delta"] == 0.0


# ---------------------------------------------------------------------------
# Персистентность
# ---------------------------------------------------------------------------


def test_campaign_env_state_dict_round_trip_restores_progress():
    env = CampaignEnv(seed=3, max_days=8)
    env.reset(seed=3)
    env.step(CampaignAction(END_DAY))
    day_before = env.engine.day
    state = env.state_dict()
    assert state["kind"] == "campaign_env"
    assert state["version"] == 1
    assert json.dumps(state)  # сериализуется в JSON без правок

    restored = CampaignEnv(seed=99, max_days=99)
    observation = restored.load_state_dict(state)
    assert restored.engine.day == day_before == observation.day
    assert restored.seed == 3
    assert restored.max_days == 8


# ---------------------------------------------------------------------------
# Политики на кампанейном срезе
# ---------------------------------------------------------------------------


def test_campaign_features_vector_shape_and_flags():
    observation = CampaignObservation(
        day=2,
        total_days=10,
        actions_left=2,
        actions_per_day=3,
        health=80.0,
        sickness=0.3,
        standing=0.4,
        power=0.6,
        cohesion=0.5,
        attached=True,
    )
    end_day = campaign_features(observation, CampaignAction(END_DAY))
    work = campaign_features(observation, CampaignAction("inspect", target="n"))
    heal = campaign_features(observation, CampaignAction("build_network"))
    assert len(end_day) == len(work) == len(heal) == 18
    # Флаги действия: slot7 END_DAY, slot8 работа (с целью), slot17 self-ход.
    assert (end_day[7], end_day[8], end_day[17]) == (1.0, 0.0, 0.0)
    assert (work[7], work[8], work[17]) == (0.0, 1.0, 0.0)
    assert (heal[7], heal[8], heal[17]) == (0.0, 0.0, 1.0)
    # Все признаки нормированы к [0, 1].
    assert all(-1e-9 <= value <= 1.0 + 1e-9 for value in work)


def test_bdi_policy_acts_and_learns_on_campaign_observation():
    policy = BDIPolicy(seed=1, epsilon=0.0)
    observation = CampaignObservation(day=1, total_days=5, actions_left=2)
    actions = (CampaignAction(END_DAY),)
    chosen = policy.act(observation, actions, explore=False)
    assert chosen.kind == END_DAY
    before_updates = policy.updates
    policy.observe(
        Transition(
            observation=observation,
            action=chosen,
            reward=0.1,
            next_observation=observation,
            done=False,
            next_actions=actions,
            info={},
        )
    )
    assert policy.updates == before_updates + 1


def test_qtable_campaign_flag_keeps_tables_separate(tmp_path):
    arena_table = QTablePolicy(seed=1)
    campaign_table = make_policy("qtable-campaign", seed=1)
    assert campaign_table.campaign is True
    assert arena_table.campaign is False
    observation = CampaignObservation(day=1, total_days=5)
    action = CampaignAction(END_DAY)
    key = campaign_table.key(observation, action)
    assert len(key) == 12
    assert key[9] == END_DAY
    # Кампанейная таблица не смешивается с ареной: аренный ключ строится
    # из энергетических разрядов дуэли (self_force/self_energy/...), а
    # кампанейный — из нормированных дневных признаков; поля action.kind
    # при этом различаются ("END_DAY" против "build_network").
    arena_obs = Observation(
        self_force=50.0,
        self_energy=40.0,
        self_max_force=100.0,
        self_max_energy=100.0,
        opponent_force=30.0,
        opponent_energy=20.0,
        opponent_max_force=100.0,
        opponent_max_energy=100.0,
        opponent_pressure=0.0,
        opponent_open=False,
        time=1.0,
        self_health=80.0,
        opponent_health=60.0,
    )
    arena_key = arena_table.key(arena_obs, Action("WORK", form="force"))
    # campaign-объект с тем же действием даёт другой ключ: таблицы не
    # смешиваются даже при совпадении action.kind.
    campaign_same_action = campaign_table.key(observation, Action("WORK", form="force"))
    assert campaign_same_action != arena_key
    assert key[9] == END_DAY and arena_key[9] == "WORK"
    # Флаг среза сохраняется в чекпойнте и возвращается при загрузке.
    path = tmp_path / "qtable-campaign.json"
    state = campaign_table.state_dict()
    assert state["campaign"] is True
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    loaded = QTablePolicy(seed=9)
    with open(path, encoding="utf-8") as handle:
        loaded.load_state_dict(json.load(handle))
    assert loaded.campaign is True


# ---------------------------------------------------------------------------
# Цикл обучения (single-agent episode)
# ---------------------------------------------------------------------------


def test_train_campaign_single_agent_no_self_play():
    _policy, stats = train(
        episodes=2,
        seed=0,
        policy_name="bdi",
        max_steps=4,
        env_name="campaign",
        eval_episodes=0,
    )
    assert stats["env"] == "campaign"
    assert stats["self_play"] is False
    assert stats["policy_updates"] > 0
    assert "opponent_updates" not in stats


def test_evaluate_campaign_ignores_opponent_and_counts_outcomes():
    result = evaluate(
        make_policy("bdi", seed=2),
        make_policy("random", seed=3),
        episodes=2,
        seed=500000,
        max_steps=4,
        env_name="campaign",
    )
    assert result["env"] == "campaign"
    assert result["episodes"] == 2
    # draw в кампании = усечение горизонта (§7 №30), считается отдельно.
    assert result["wins"] + result["losses"] == 2
    assert result["draws"] == 0


def test_campaign_env_smoke_with_random_policy():
    import random

    env = CampaignEnv(seed=11, max_days=6)
    env.reset(seed=11)
    rng = random.Random(11)
    steps, info = _run_random(env, rng)
    assert steps >= 1
    assert "outcome" in info or "day" in info
