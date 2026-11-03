"""Инварианты математической модели: границы, монотонность, детерминизм."""

from __future__ import annotations

import random

import pytest

from campaign.actor import CampaignActor, campaign_success_chance
from campaign.env import (
    campaign_reward,
    terminal_campaign_reward,
)
from core41 import (
    HEALTH_MAX,
    SICKNESS_MAX,
    WOUND_MAX,
    Automaton,
    Work,
    success_probability,
)
from core41.model import sigmoid


def _unit(**kwargs):
    defaults = {
        "id": "unit",
        "force": 50.0,
        "energy": 50.0,
        "max_force": 100.0,
        "max_energy": 100.0,
        "skills": {"force": 0.5, "info": 0.5},
        "authority": 0.0,
        "inputs": ("force", "info"),
    }
    defaults.update(kwargs)
    return Automaton(**defaults)


def _work(amount=10.0, form="force"):
    return Work(amount=amount, form=form)


def test_sigmoid_is_bounded_monotone_and_symmetric():
    values = [-1000.0, -60.0, -10.0, -1.0, 0.0, 1.0, 10.0, 60.0, 1000.0]
    outputs = [sigmoid(value) for value in values]
    assert outputs == sorted(outputs)
    assert all(0.0 <= value <= 1.0 for value in outputs)
    assert sigmoid(0.0) == pytest.approx(0.5)
    for value in (-12.0, -3.0, 0.0, 2.5, 9.0):
        assert sigmoid(value) + sigmoid(-value) == pytest.approx(1.0)


def test_success_probability_is_bounded_and_monotone():
    attacker = _unit()
    defender = _unit()

    base = success_probability(attacker, defender, _work(), False)
    assert 0.0 <= base <= 1.0

    better_skill = _unit(skills={"force": 0.9, "info": 0.5})
    assert success_probability(
        better_skill, defender, _work(), False
    ) > base

    more_authority = _unit(authority=1.0)
    assert success_probability(
        more_authority, defender, _work(), False
    ) > base

    assert success_probability(
        attacker, defender, _work(), True
    ) > base
    assert success_probability(
        attacker, defender, _work(), False, env_bonus=1.0
    ) > base

    stronger_defender = _unit(force=100.0, energy=100.0)
    assert success_probability(
        attacker, stronger_defender, _work(), False
    ) < base

    heavier_work = _work(amount=100.0)
    assert success_probability(
        attacker, defender, heavier_work, False
    ) < base


def test_success_probability_stays_in_unit_interval_for_extremes():
    rng = random.Random(7)
    for _ in range(200):
        attacker = _unit(
            force=rng.uniform(0.0, 100.0),
            energy=rng.uniform(0.0, 100.0),
            skills={"force": rng.uniform(0.0, 1.0)},
            authority=rng.uniform(-1.0, 1.0),
            sickness=rng.uniform(0.0, 1.0),
            wound=rng.uniform(0.0, 1.0),
        )
        defender = _unit(
            force=rng.uniform(0.0, 100.0),
            energy=rng.uniform(0.0, 100.0),
            skills={"force": rng.uniform(0.0, 1.0)},
        )
        probability = success_probability(
            attacker,
            defender,
            _work(amount=rng.uniform(0.0, 500.0)),
            rng.random() < 0.5,
            env_bonus=rng.uniform(-5.0, 5.0),
        )
        assert 0.0 <= probability <= 1.0


def test_work_effectiveness_is_bounded_and_decreasing():
    previous = 1.0
    for severity in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        unit = _unit(sickness=severity)
        value = unit.work_effectiveness()
        assert 0.0 < value <= 1.0
        assert value <= previous
        previous = value

    previous = 1.0
    for severity in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        unit = _unit(wound=severity)
        value = unit.work_effectiveness()
        assert 0.0 < value <= 1.0
        assert value <= previous
        previous = value

    both = _unit(sickness=1.0, wound=1.0)
    sick_only = _unit(sickness=1.0)
    wounded_only = _unit(wound=1.0)
    assert both.work_effectiveness() < sick_only.work_effectiveness()
    assert both.work_effectiveness() < wounded_only.work_effectiveness()


def test_infect_and_injure_are_monotone_and_clamped():
    unit = _unit()
    assert unit.infect(-1.0) == 0.0
    assert unit.infect(0.3) == pytest.approx(0.3)
    assert unit.infect(0.2) == pytest.approx(0.3)
    assert unit.infect(5.0) == pytest.approx(SICKNESS_MAX)

    assert unit.injure(-1.0) == 0.0
    assert unit.injure(0.4) == pytest.approx(0.4)
    assert unit.injure(0.1) == pytest.approx(0.4)
    assert unit.injure(5.0) == pytest.approx(WOUND_MAX)


def test_treatments_reduce_severity_to_zero_without_overshoot():
    unit = _unit(sickness=0.9, wound=0.9)
    sickness_values = [unit.treat(0.1) for _ in range(12)]
    wound_values = [unit.treat_wound(0.1) for _ in range(12)]
    assert sickness_values == sorted(sickness_values, reverse=True)
    assert wound_values == sorted(wound_values, reverse=True)
    assert unit.sickness == 0.0
    assert unit.wound == 0.0
    assert unit.treat(0.5) == 0.0
    assert unit.treat_wound(0.5) == 0.0


def test_apply_force_damage_conserves_damage_and_clamps_health():
    rng = random.Random(11)
    for _ in range(200):
        force = rng.uniform(0.0, 100.0)
        damage = rng.uniform(0.0, 300.0)
        health = rng.uniform(0.0, HEALTH_MAX)
        unit = _unit(force=force, health=health)
        absorbed, overflow, health_damage = unit.apply_force_damage(damage)
        assert absorbed >= 0.0
        assert overflow >= 0.0
        assert health_damage >= 0.0
        assert absorbed + overflow == pytest.approx(damage)
        assert unit.force == pytest.approx(max(0.0, force - damage))
        assert 0.0 <= unit.health <= HEALTH_MAX


def test_more_damage_never_increases_health():
    rng = random.Random(13)
    for _ in range(100):
        force = rng.uniform(0.0, 100.0)
        health = rng.uniform(1.0, HEALTH_MAX)
        first = _unit(force=force, health=health)
        second = _unit(force=force, health=health)
        damage = rng.uniform(0.0, 250.0)
        first.apply_force_damage(damage)
        second.apply_force_damage(damage + rng.uniform(0.0, 250.0))
        assert second.health <= first.health


def test_tick_health_is_bounded_and_resting_helps():
    sick = _unit(
        health=50.0,
        energy=50.0,
        sickness=0.6,
        wound=0.5,
    )
    rested = _unit(
        health=50.0,
        energy=50.0,
        sickness=0.6,
        wound=0.5,
    )
    before_health = sick.health
    sick.tick_health(resting=False)
    rested.tick_health(resting=True)
    assert 0.0 <= sick.health <= HEALTH_MAX
    assert 0.0 <= rested.health <= HEALTH_MAX
    assert rested.health >= sick.health
    assert rested.sickness < sick.sickness
    assert rested.wound < sick.wound
    assert sick.health < before_health

    starving = _unit(health=50.0, energy=0.0)
    starving.tick_health(resting=True)
    assert starving.health < 50.0

    dead = _unit(health=0.0, sickness=1.0, wound=1.0)
    assert dead.tick_health(resting=True) == 0.0


def test_campaign_success_chance_blends_and_stays_bounded():
    defender = _unit()
    weak = _unit(skills={"force": 0.1})
    strong = _unit(skills={"force": 0.95}, authority=1.0)

    assert campaign_success_chance(
        0.5, weak, defender, weight=0.0
    ) == pytest.approx(0.5)
    low = campaign_success_chance(0.5, weak, defender, weight=1.0)
    high = campaign_success_chance(0.5, strong, defender, weight=1.0)
    assert 0.05 <= low <= high <= 0.95

    sick = _unit(skills={"force": 0.95}, authority=1.0, sickness=1.0)
    assert campaign_success_chance(
        0.5, sick, defender, weight=1.0
    ) <= high
    assert campaign_success_chance(
        1.0, strong, defender, weight=1.0
    ) == pytest.approx(0.95)


def _snapshot(**overrides):
    values = {
        "standing": 0.5,
        "power": 0.5,
        "cohesion": 0.5,
        "health": HEALTH_MAX / 2.0,
        "sickness": 0.2,
        "wound": 0.2,
    }
    values.update(overrides)
    return values


def test_campaign_reward_signs_follow_state_changes():
    before = _snapshot()
    after = dict(before)

    assert campaign_reward(before, after) == pytest.approx(0.0)
    assert campaign_reward(before, _snapshot(standing=0.8)) > 0.0
    assert campaign_reward(before, _snapshot(standing=0.2)) < 0.0
    assert campaign_reward(before, _snapshot(health=HEALTH_MAX)) > 0.0
    assert campaign_reward(before, _snapshot(health=0.0)) < 0.0
    assert campaign_reward(before, _snapshot(sickness=0.8)) < 0.0
    assert campaign_reward(before, _snapshot(wound=0.8)) < 0.0
    assert campaign_reward(
        before, after, outcome_delta=0.5
    ) == pytest.approx(0.5)
    assert campaign_reward(
        before, after, success=True
    ) > campaign_reward(before, after)


def test_terminal_reward_is_symmetric_and_zero_for_neutral():
    assert terminal_campaign_reward("win") == pytest.approx(1.0)
    assert terminal_campaign_reward("lose") == pytest.approx(-1.0)
    assert terminal_campaign_reward("neutral") == pytest.approx(0.0)
    assert terminal_campaign_reward(None) == pytest.approx(0.0)


def test_campaign_actor_energy_projection_is_clamped():
    actor = CampaignActor(actions_per_day=3)
    assert actor.actions_left == 3
    for remaining in (2, 1, 0):
        assert actor.spend_action() is True
        assert actor.actions_left == remaining
    assert actor.spend_action() is False
    actor.restore_day()
    assert actor.actions_left == 3

    actor.actions_left = 10
    assert actor.actions_left == 3
    actor.actions_left = -1
    assert actor.actions_left == 0
    actor.energy = 1000.0
    assert actor.energy == actor.max_energy
    actor.energy = -100.0
    assert actor.energy == 0.0
    actor.force = 5.0
    assert actor.force == 1.0
    actor.force = -1.0
    assert actor.force == 0.0
