"""Кампания на ядре 4-2-1: `E/F/H` вместо отдельных счётчиков."""

import pytest

from agents.policies import campaign_features
from campaign.actor import (
    CAMPAIGN_ENERGY_MAX,
    CampaignActor,
)
from campaign.env import END_DAY, CampaignEnv
from core41 import CampaignAction, CampaignObservation


def test_actor_energy_projects_actions_left():
    actor = CampaignActor(actions_per_day=3)
    assert actor.energy == pytest.approx(CAMPAIGN_ENERGY_MAX)
    assert actor.actions_left == 3
    assert actor.energy_per_action == pytest.approx(
        CAMPAIGN_ENERGY_MAX / 3
    )

    assert actor.spend_action() is True
    assert actor.actions_left == 2
    assert actor.energy == pytest.approx(CAMPAIGN_ENERGY_MAX * 2 / 3)

    assert actor.spend_action() is True
    assert actor.spend_action() is True
    assert actor.actions_left == 0
    assert actor.spend_action() is False

    actor.restore_day()
    assert actor.actions_left == 3
    assert actor.energy == pytest.approx(CAMPAIGN_ENERGY_MAX)


def test_actor_actions_left_setter_is_a_projection_of_energy():
    actor = CampaignActor(actions_per_day=4)
    actor.actions_left = 2
    assert actor.energy == pytest.approx(CAMPAIGN_ENERGY_MAX / 2)
    assert actor.actions_left == 2
    actor.actions_left = 99
    assert actor.actions_left == 4


def test_actor_force_tracks_standing_and_sickness_penalizes_work():
    actor = CampaignActor(standing=0.4)
    assert actor.force == pytest.approx(0.4)
    assert actor.standing == pytest.approx(0.4)
    actor.standing = 0.9
    assert actor.force == pytest.approx(0.9)

    actor.sickness = 1.0
    assert actor.work_effectiveness() == pytest.approx(0.4)
    actor.sickness = 0.0
    assert actor.work_effectiveness() == pytest.approx(1.0)


def test_campaign_action_spends_energy_and_end_day_restores_it():
    env = CampaignEnv(seed=1, max_days=5)
    env.reset(seed=1)
    engine = env.engine
    assert engine.actions_left == engine.actions_per_day
    assert engine.player_energy == pytest.approx(CAMPAIGN_ENERGY_MAX)

    work = next(
        action for action in env.legal_actions() if action.kind != END_DAY
    )
    env.step(work)
    assert engine.actions_left == engine.actions_per_day - 1
    assert engine.player_energy == pytest.approx(
        CAMPAIGN_ENERGY_MAX - engine.player.energy_per_action
    )

    env.step(CampaignAction(END_DAY))
    assert engine.actions_left == engine.actions_per_day
    assert engine.player_energy == pytest.approx(CAMPAIGN_ENERGY_MAX)


def test_campaign_standing_is_the_same_state_as_force():
    env = CampaignEnv(seed=2, max_days=5)
    env.reset(seed=2)
    engine = env.engine
    engine.player_resources["standing"] = 0.73
    assert engine.player_force == pytest.approx(0.73)
    assert engine.player.standing == pytest.approx(0.73)


def test_campaign_snapshot_round_trips_energy_and_force():
    env = CampaignEnv(seed=3, max_days=5)
    env.reset(seed=3)
    engine = env.engine
    engine.player_resources["standing"] = 0.61
    engine.player_energy = 25.0
    snapshot = engine.to_dict()

    restored = CampaignEnv(seed=3, max_days=5, snapshot=snapshot)
    assert restored.engine.player_energy == pytest.approx(25.0)
    assert restored.engine.player_force == pytest.approx(0.61)
    assert restored.engine.actions_left == engine.actions_left


def test_campaign_observation_exposes_energy_and_force():
    env = CampaignEnv(seed=4, max_days=5)
    observation = env.reset(seed=4)
    assert observation.energy == pytest.approx(CAMPAIGN_ENERGY_MAX)
    assert observation.max_energy == pytest.approx(CAMPAIGN_ENERGY_MAX)
    assert observation.force == pytest.approx(
        env.engine.player_resources["standing"]
    )
    assert observation.max_force == pytest.approx(1.0)


def test_campaign_features_prefer_energy_over_legacy_actions_left():
    legacy = CampaignObservation(
        day=1,
        total_days=5,
        actions_left=1,
        actions_per_day=3,
    )
    energy = CampaignObservation(
        day=1,
        total_days=5,
        actions_left=1,
        actions_per_day=3,
        energy=50.0,
        max_energy=100.0,
    )
    action = CampaignAction("inspect", target="n")
    assert campaign_features(legacy, action)[1] == pytest.approx(1 / 3)
    assert campaign_features(energy, action)[1] == pytest.approx(0.5)
