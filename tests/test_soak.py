"""Soak-тесты: длинные прогоны и совместимость старых снимков (P2).

Эти тесты не проверяют баланс — только то, что длинная активная игра не
расходится, обучаемые политики остаются конечными, а снимки кампании без
полей `E/F` (до миграции на `core41`) загружаются и продолжают работать.
"""

import json
import math

from agents import MLPPolicy, QTablePolicy
from agents.train import train
from campaign.actor import CampaignActor
from campaign.env import CampaignEnv


def test_long_arena_env_soak_keeps_qtable_bounded_and_learning():
    policy, stats = train(
        episodes=1,
        seed=5,
        policy_name="qtable",
        opponent_name="bdi",
        max_steps=600,
        eval_episodes=0,
    )
    assert stats["with_env"] is True
    assert policy.updates > 0
    # Таблица не должна расти быстрее числа тактов и не должна содержать
    # NaN/inf после длинного прогона.
    assert len(policy.table) <= 600
    assert all(math.isfinite(value) for value in policy.table.values())


def test_long_arena_env_soak_keeps_mlp_finite():
    policy, stats = train(
        episodes=1,
        seed=6,
        policy_name="mlp",
        opponent_name="bdi",
        max_steps=300,
        eval_episodes=0,
    )
    assert isinstance(policy, MLPPolicy)
    assert stats["policy_updates"] > 0
    assert all(
        math.isfinite(value)
        for row in policy.weights1
        for value in row
    )
    assert all(math.isfinite(value) for value in policy.weights2)
    assert all(
        math.isfinite(value)
        for row in policy.target_weights1
        for value in row
    )


def test_campaign_snapshot_without_energy_or_force_loads():
    env = CampaignEnv(seed=9, max_days=8)
    state = env.state_dict()
    player = state["snapshot"]["player"]
    for key in ("energy", "max_energy", "force", "max_force"):
        player.pop(key, None)
    state["snapshot"]["actions_left"] = 2

    restored = CampaignEnv(seed=9, max_days=8)
    observation = restored.load_state_dict(state)
    # Старый снимок без E: `actions_left` остаётся источником истины,
    # а E восстанавливается из него, а не падает в ноль.
    assert observation.actions_left == 2
    assert restored.engine.actions_left == 2
    assert restored.engine.player_energy > 0.0
    # Среда остаётся рабочей: один шаг не должен требовать полей E/F.
    observation, _reward, _done, _truncated, info = restored.step(
        restored.legal_actions()[0]
    )
    assert info["day"] >= observation.day - 1


def test_campaign_actor_snapshot_without_energy_uses_actions_left():
    actor = CampaignActor(actions_per_day=4)
    state = actor.state_dict()
    state.pop("energy", None)
    state["actions_left"] = 2
    actor.load_state_dict(state)
    assert actor.actions_left == 2
    assert actor.energy == actor.energy_per_action * 2


def test_qtable_checkpoint_growth_is_serialisable(tmp_path):
    policy, _stats = train(
        episodes=1,
        seed=8,
        policy_name="qtable",
        opponent_name="bdi",
        max_steps=200,
        eval_episodes=0,
    )
    assert isinstance(policy, QTablePolicy)
    assert policy.updates > 0
    path = tmp_path / "soak-qtable.json"
    path.write_text(json.dumps(policy.state_dict()), encoding="utf-8")
    assert path.exists()
