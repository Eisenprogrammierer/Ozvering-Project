"""Тесты кампанейной среды `CampaignEnv` (проблема готовности №6).

Среда — Gym-подобный контракт reset/step над дневным `WorldEngine`:
плоское нормированное наблюдение, награда из дельт положения/организации/
здоровья/болезни + терминальный бонус исхода, одиночный агент (без оппонента
и self-play), персистентность через снимок мира. Открытые вопросы §7 (28–31)
закрыты первым срезом: распад с grace-днями, увольнение как смена роли,
бесконечный горизонт без win, ограниченный фон/оффлайн-догон.
"""

import json
from dataclasses import replace

import pytest

from agents import BDIPolicy, QTablePolicy, make_policy
from agents.policies import campaign_features
from agents.train import evaluate, train
from campaign.env import (
    CAMPAIGN_REWARD_ILLEGAL,
    END_DAY,
    TREAT_SELF,
    TREAT_WOUND,
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


def test_campaign_env_career_actions_are_opt_in():
    default = CampaignEnv(seed=2, max_days=5)
    assert not any(
        action.kind in {"seek_promotion", "request_transfer", "resign"}
        for action in default.legal_actions()
    )

    env = CampaignEnv(seed=2, max_days=5, career_actions=True)
    kinds = {action.kind for action in env.legal_actions()}
    # request_transfer доступен с первого дня (standing >= 0.25).
    assert "request_transfer" in kinds
    assert END_DAY in kinds

    state = json.loads(json.dumps(env.state_dict()))
    restored = CampaignEnv(seed=2, max_days=5)
    restored.load_state_dict(state)
    assert restored.career_actions is True
    assert "request_transfer" in {
        action.kind for action in restored.legal_actions()
    }


def test_campaign_env_all_target_mode_exposes_multiple_targets():
    env = CampaignEnv(seed=2, max_days=5, target_mode="all")
    actions = env.legal_actions()
    targets = {action.target for action in actions if action.target}
    assert len(targets) > 1
    assert END_DAY in {action.kind for action in actions}


def test_campaign_env_first_target_mode_keeps_narrow_space():
    env = CampaignEnv(seed=2, max_days=5, target_mode="first")
    targets = {action.target for action in env.legal_actions() if action.target}
    assert len(targets) <= 1


def test_campaign_env_treat_self_reduces_sickness():
    env = CampaignEnv(seed=1, max_days=5, sickness=0.5)
    env.reset(seed=1)
    kinds = {action.kind for action in env.legal_actions()}
    assert TREAT_SELF in kinds
    before = env.observe().sickness
    observation, _reward, done, truncated, info = env.step(
        CampaignAction(TREAT_SELF)
    )
    assert info["result"]["ok"] is True
    assert observation.sickness < before
    assert not done and not truncated


def test_campaign_env_dismissal_without_role_is_terminal_neutral():
    env = CampaignEnv(seed=7, max_days=10)
    env.reset(seed=7)
    env.engine._dismiss("тест", auto_reassign=False)
    observation, _reward, done, truncated, info = env.step(
        CampaignAction(END_DAY)
    )
    assert done is True
    assert truncated is False
    assert info["outcome"] == "neutral"
    assert info["terminal_reason"] == "dismissed"
    assert observation.finished is True
    with pytest.raises(RuntimeError):
        env.step(CampaignAction(END_DAY))


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
    # Детерминированная смерть героя: терминальный шаг не зависит от
    # перебора сидов и новых правил распада/увольнения (§7 №28–29).
    env.engine.player_health = 1.0
    env.engine.infect_player(1.0)
    _obs, _reward, done, _truncated, _info = env.step(CampaignAction(END_DAY))
    assert done is True
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
        "wound": 0.0,
    }
    after = {
        "standing": 0.40,
        "power": 0.60,
        "cohesion": 0.50,
        "health": 90.0,
        "sickness": 0.20,
        "wound": 0.0,
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
    # Устойчивая рана: прирост на 0.25 стоит CAMPAIGN_REWARD_WOUND*0.25.
    wounded = dict(after, wound=0.25)
    assert campaign_reward(before, wounded) == pytest.approx(
        -0.175 - 0.8 * 0.25
    )
    # Лечение раны (уменьшение) возвращает штраф — знак симметричный болезни.
    assert campaign_reward(dict(before, wound=0.25), after) == pytest.approx(
        -0.175 + 0.8 * 0.25
    )


def test_terminal_campaign_reward_maps_outcomes():
    assert terminal_campaign_reward("win") == 1.0
    assert terminal_campaign_reward("lose") == -1.0
    assert terminal_campaign_reward("") == 0.0
    assert terminal_campaign_reward(None) == 0.0


def test_campaign_env_terminal_step_carries_outcome_bonus():
    # Терминальный шаг (смерть героя) должен нести outcome_bonus. Раньше
    # тест перебирал сиды в поисках естественного финала; после §7 №29–30
    # увольнение и горизонт больше не терминальны, поэтому сценарий смерти
    # задаётся детерминированно.
    env = CampaignEnv(seed=7, max_days=30)
    env.reset(seed=7)
    env.engine.player_health = 1.0
    env.engine.infect_player(1.0)
    _obs, _reward, done, truncated, info = env.step(CampaignAction(END_DAY))
    assert done is True
    assert truncated is False
    assert info["outcome"] == "lose"
    assert info["outcome_delta"] == terminal_campaign_reward("lose")
    assert info["ending"] == ""


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
    assert len(end_day) == len(work) == len(heal) == 21
    # Флаги действия: slot7 END_DAY, slot8 работа (с целью), slot17 self-ход.
    assert (end_day[7], end_day[8], end_day[17]) == (1.0, 0.0, 0.0)
    assert (work[7], work[8], work[17]) == (0.0, 1.0, 0.0)
    assert (heal[7], heal[8], heal[17]) == (0.0, 0.0, 1.0)
    # 19-й слот различает действия с одинаковыми флагами: без него
    # `inspect` и `build_network` давали бы один и тот же вектор.
    assert work[18] != heal[18]
    # 20-й слот — устойчивая рана героя (общее состояние с ареной);
    # без ран он нулевой, 21-й остаётся нейтральной константой среды.
    assert (work[19], work[20]) == (0.0, 1.0)
    wounded_observation = replace(observation, wound=0.4)
    wounded = campaign_features(wounded_observation, CampaignAction(END_DAY))
    assert wounded[19] == pytest.approx(0.4)
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


def test_bdi_campaign_prefers_work_while_actions_remain():
    policy = BDIPolicy(seed=1, epsilon=0.0)
    observation = CampaignObservation(
        day=1,
        total_days=5,
        actions_left=2,
        actions_per_day=3,
        energy=66.0,
        max_energy=100.0,
        standing=0.3,
    )
    actions = (
        CampaignAction(END_DAY),
        CampaignAction("inspect", target="n"),
    )

    chosen = policy.act(observation, actions, explore=False)

    assert chosen.kind == "inspect"
    # Аренные веса не переписаны кампанейским приором.
    assert policy.campaign_weights != policy.weights


def test_bdi_campaign_weights_round_trip_and_legacy_checkpoint():
    policy = BDIPolicy(seed=2, epsilon=0.0)
    policy.campaign_weights[18] = 0.42
    state = json.loads(json.dumps(policy.state_dict()))

    loaded = BDIPolicy(seed=3)
    loaded.load_state_dict(state)
    assert loaded.campaign_weights == pytest.approx(
        policy.campaign_weights
    )

    # Старый чекпойнт без кампанейских весов получает приор поверх
    # сохранённых аренных.
    legacy = dict(state)
    legacy.pop("campaign_weights")
    restored = BDIPolicy(seed=4)
    restored.load_state_dict(legacy)
    assert restored.campaign_weights[7] == pytest.approx(-0.6)
    assert restored.campaign_weights[8] == pytest.approx(0.6)


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
    # draw в кампании = усечение горизонта (§7 №30), не поражение:
    # исходы всегда разбивают эпизоды на wins/losses/draws.
    assert result["wins"] + result["losses"] + result["draws"] == 2
    assert result["draws"] >= 0


def test_campaign_horizon_is_counted_as_draw_not_loss():
    from agents.train import _play_campaign_episode

    class EndDayPolicy:
        def act(self, _observation, _actions, explore=True):
            return CampaignAction(END_DAY)

    env = CampaignEnv(seed=7, max_days=1)
    info = _play_campaign_episode(
        env, EndDayPolicy(), 7, learn=False, explore=False
    )
    assert info["truncated"] is True
    assert info["winner"] is None
    assert info["outcome"] == ""


def test_campaign_observation_separates_dismissal_from_defeat():
    env = CampaignEnv(seed=7, max_days=10)
    env.reset(seed=7)
    env.engine._dismiss("тестовая смена роли", auto_reassign=False)
    observation = env.observe()
    # §7 №29: вне службы — не поражение; наблюдение различает флаги.
    assert observation.attached is False
    assert observation.dismissed is True
    assert observation.finished is False
    assert observation.outcome == ""
    assert observation.extra["dismissal_count"] == 1


def test_campaign_narrative_ending_has_no_terminal_bonus():
    env = CampaignEnv(seed=7, max_days=10)
    env.reset(seed=7)
    env.engine.end_storyline("neutral")
    observation = env.observe()
    assert observation.finished is True
    assert observation.outcome == ""
    assert observation.extra["ending"] == "neutral"
    assert terminal_campaign_reward(observation.outcome) == 0.0


def test_train_campaign_has_held_out_world_eval():
    _policy, stats = train(
        episodes=1,
        seed=0,
        policy_name="bdi",
        max_steps=3,
        env_name="campaign",
        eval_episodes=2,
    )
    # Кампания — один агент: матрица вырождается в одну строку «политика
    # против мира», но контракт held-out оценки сохраняется.
    assert len(stats["eval"]) == 1
    row = stats["eval"][0]
    assert row["policy"] == "bdi"
    assert row["opponent"] == "world"
    assert row["env"] == "campaign"
    assert row["wins"] + row["losses"] + row["draws"] == 2


def test_campaign_env_smoke_with_random_policy():
    import random

    env = CampaignEnv(seed=11, max_days=6)
    env.reset(seed=11)
    rng = random.Random(11)
    steps, info = _run_random(env, rng)
    assert steps >= 1
    assert "outcome" in info or "day" in info


def test_campaign_env_attaches_to_live_engine_without_rebuilding():
    base = CampaignEnv(seed=17, max_days=5)
    engine = base.engine
    day_before = engine.day
    actions_before = engine.actions_left

    env = CampaignEnv(engine=engine, max_days=5)
    assert env.engine is engine
    assert env.observe().day == day_before
    # Среда не создаёт второй мир: шаг меняет тот же движок.
    observation, _reward, _done, _truncated, info = env.advance(
        BDIPolicy(seed=3), explore=False
    )
    assert observation.day >= day_before
    assert env.engine is engine
    assert info["day"] == engine.day
    assert engine.day > day_before or engine.actions_left < actions_before


def test_campaign_env_attach_reuses_engine_after_reset():
    env = CampaignEnv(seed=4, max_days=4)
    engine = env.engine
    env.attach(engine)
    assert env.engine is engine
    assert env._resolved_start == (
        engine.player_node_id,
        engine.player_office_id,
    )


# ---------------------------------------------------------------------------
# Устойчивые раны в кампании (§7: рана — отдельное состояние, не болезнь)
# ---------------------------------------------------------------------------


def test_campaign_env_treat_wound_is_legal_only_when_wounded():
    env = CampaignEnv(seed=5, max_days=5)
    env.reset(seed=5)
    kinds = [action.kind for action in env.legal_actions()]
    assert TREAT_WOUND not in kinds
    env.engine.player_wound = 0.3
    kinds = [action.kind for action in env.legal_actions()]
    assert TREAT_WOUND in kinds
    # Здоровье без ран: TREAT_SELF не обязан быть доступен — действия разделены.
    assert TREAT_SELF not in kinds


def test_campaign_env_treat_wound_step_reduces_wound_not_sickness():
    env = CampaignEnv(seed=5, max_days=5)
    env.reset(seed=5)
    env.engine.player_sickness = 0.2
    env.engine.player_wound = 0.4
    actions_left = env.engine.actions_left
    _obs, reward, _done, _truncated, info = env.step(CampaignAction(TREAT_WOUND))
    result = info["result"]
    assert result["ok"] and result["action"] == TREAT_WOUND
    assert env.engine.player_wound == pytest.approx(0.15)
    # Рана лечится отдельно: болезнь не тронута одним и тем же шагом.
    assert env.engine.player_sickness == pytest.approx(0.2)
    assert env.engine.actions_left == actions_left - 1
    # Снижение раны возвращает штраф прошлых шагов: награда положительна.
    assert reward > 0.0


def test_campaign_env_observe_exposes_wound_and_reward_penalises_injury():
    env = CampaignEnv(seed=9, max_days=5)
    observation = env.reset(seed=9)
    assert observation.wound == pytest.approx(0.0)
    before = env._metrics()
    env.engine.injure_player(0.3)
    after = env._metrics()
    assert after["wound"] == pytest.approx(0.3)
    penalty = campaign_reward(before, after)
    # Только рана (без других дельт) стоит CAMPAIGN_REWARD_WOUND * 0.3.
    assert penalty < 0.0
    observation = env.observe()
    assert observation.wound == pytest.approx(0.3)


def test_campaign_env_wound_persists_through_snapshot_roundtrip():
    env = CampaignEnv(seed=6, max_days=5)
    env.reset(seed=6)
    env.engine.player_wound = 0.35
    state = env.state_dict()
    restored = CampaignEnv(seed=6, max_days=5)
    restored.load_state_dict(state)
    assert restored.engine.player_wound == pytest.approx(0.35)
    assert restored.observe().wound == pytest.approx(0.35)
