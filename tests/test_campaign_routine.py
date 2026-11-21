"""Суточная рутина BDI: сон, еда, уход и обратная связь снабжения."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = ROOT / "configs" / "campaigns"


def _preset(template_id="empire_campaign", seed=11):
    from campaign.preset import CampaignPresetGenerator
    from campaign.roles import RoleCatalog

    return CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=CAMPAIGNS / ("%s.json" % template_id),
    ).generate(seed=seed)


def _campaign(seed=11):
    from campaign.automata import AutomataCampaign

    return AutomataCampaign(_preset(seed=seed), seed=seed)


def _mean(values):
    values = list(values)
    return sum(values) / float(len(values)) if values else 0.0


def test_service_level_is_bounded_and_grows_with_supply():
    from campaign.routine import service_level

    low = service_level(0.2, 0.1)
    high = service_level(0.9, 0.9)

    assert 0.0 <= low < high <= 1.0
    assert service_level(0.0, 0.0) > 0.0
    assert service_level(1.0, 1.0) == pytest.approx(1.0)


def test_one_day_of_routine_does_not_cascade_needs():
    from campaign.routine import run_day

    campaign = _campaign()
    character = campaign.player.characters[0]
    record = run_day(
        character,
        86400.0,
        support=0.9,
        supply=0.9,
        config=campaign.routine,
        rng=character.rng,
    )

    assert record["seconds"] == pytest.approx(86400.0)
    assert record["rested_seconds"] > 0.0
    assert record["effects"]
    assert all(0.0 <= value < 1.0 for value in character.needs.values())
    assert character.morale > 50.0


def test_routine_holds_needs_near_targets_across_two_weeks():
    from campaign.routine import run_day

    campaign = _campaign()
    for _ in range(14):
        for character in campaign.player.characters:
            run_day(
                character,
                86400.0,
                support=0.8,
                supply=0.85,
                config=campaign.routine,
                rng=character.rng,
            )

    needs = [character.needs for character in campaign.player.characters]
    morale = [character.morale for character in campaign.player.characters]

    assert _mean(item["hunger"] for item in needs) < 0.5
    assert _mean(item["thirst"] for item in needs) < 0.5
    assert _mean(item["fatigue"] for item in needs) < 0.6
    assert _mean(item["fear"] for item in needs) < 0.85
    assert _mean(morale) > 45.0


def test_poor_supply_leaves_people_hungrier_and_less_willing():
    from campaign.routine import run_day

    def run(supply):
        campaign = _campaign()
        for _ in range(40):
            for character in campaign.player.characters:
                run_day(
                    character,
                    86400.0,
                    support=0.8,
                    supply=supply,
                    config=campaign.routine,
                    rng=character.rng,
                )
        return campaign

    good = run(0.9)
    poor = run(0.12)

    good_hunger = _mean(
        character.needs["hunger"] for character in good.player.characters
    )
    poor_hunger = _mean(
        character.needs["hunger"] for character in poor.player.characters
    )
    good_fear = _mean(
        character.needs["fear"] for character in good.player.characters
    )
    poor_fear = _mean(
        character.needs["fear"] for character in poor.player.characters
    )

    def force_share(campaign):
        return _mean(
            character.force / max(1e-9, float(character.state["max_force"]))
            for character in campaign.player.characters
            if not character.is_dead
        )

    assert poor_hunger > good_hunger
    assert poor_fear >= good_fear
    assert force_share(poor) < force_share(good)


def test_routine_recovers_force_and_energy_with_good_service():
    from campaign.routine import run_day

    campaign = _campaign()
    character = campaign.player.characters[0]
    maximum = float(character.state["max_force"])
    character.force = maximum * 0.2
    character.energy_pool = 0.4

    record = run_day(
        character,
        86400.0,
        support=1.0,
        supply=1.0,
        config=campaign.routine,
        rng=character.rng,
    )

    assert character.force > maximum * 0.2
    assert character.energy_pool > 0.4
    assert record["rested_seconds"] > 0.0


def test_routine_covers_several_days_in_one_call():
    from campaign.routine import run_day

    campaign = _campaign()
    character = campaign.player.characters[0]
    record = run_day(
        character,
        86400.0 * 3.0,
        support=0.8,
        supply=0.8,
        config=campaign.routine,
        rng=character.rng,
    )

    assert record["seconds"] == pytest.approx(86400.0 * 3.0)
    assert record["rested_seconds"] > 0.0
    assert character.needs["hunger"] < 0.6


def test_two_weeks_without_player_actions_keeps_morale_and_force():
    campaign = _campaign()
    for _ in range(14):
        campaign.advance_time(86400.0, snapshot=False)

    alive = [
        character
        for character in campaign.player.characters
        if not character.is_dead
    ]
    assert len(alive) == len(campaign.player.characters)
    assert _mean(character.morale for character in alive) > 45.0
    assert all(character.force > 0.0 for character in alive)
    assert campaign.player.asset("morale") > 0.4
    assert campaign.player.asset("energy") > 0.4


def test_routine_does_not_write_assets_directly():
    from campaign.routine import run_day

    campaign = _campaign()
    faction = campaign.player
    before_context = dict(faction.context)
    before_baseline = dict(faction.baseline_context)
    before_assets = faction.derived_assets()

    for character in faction.characters:
        run_day(
            character,
            86400.0,
            support=0.8,
            supply=0.8,
            config=campaign.routine,
            rng=character.rng,
        )

    assert faction.context == before_context
    assert faction.baseline_context == before_baseline
    assert faction.derived_assets() != before_assets


def test_campaign_day_tick_uses_full_routine():
    campaign = _campaign()
    campaign.advance_time(86400.0, snapshot=False)

    character = campaign.player.characters[0]
    assert character.needs["hunger"] < 0.6
    assert character.needs["thirst"] < 0.6
    assert character.energy_pool > 0.0
    assert character.morale > 40.0
    assert (
        campaign.player.organization_snapshot.get("willing_share", 0.0)
        > 0.0
    )
