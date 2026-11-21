"""Файловый аудит статистики: формулы активов, BDI и работы."""

from __future__ import annotations

import json
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


def _campaign():
    from campaign.automata import AutomataCampaign

    campaign = AutomataCampaign(_preset(), seed=11)
    campaign.begin_turn()
    return campaign


def _read(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _enable(monkeypatch, tmp_path):
    path = tmp_path / "campaign_stats.log"
    monkeypatch.setenv("OZVERIN_STATS", "1")
    monkeypatch.setenv("OZVERIN_STATS_LOG", str(path))
    return path


def test_asset_breakdown_matches_derived_asset():
    from campaign.faction_state import asset_breakdown

    campaign = _campaign()
    faction = campaign.player
    for key, value in faction.derived_assets().items():
        breakdown = asset_breakdown(faction, key)
        assert breakdown["value"] == pytest.approx(value, abs=1e-6)
        weighted = sum(
            item["weight"] * item["value"]
            for item in breakdown["terms"]
        )
        assert breakdown["weight_sum"] > 0.0
        assert weighted / breakdown["weight_sum"] == pytest.approx(
            breakdown["raw"], abs=1e-6
        )


def test_stats_log_tick_formulas_and_bdi(tmp_path, monkeypatch):
    path = _enable(monkeypatch, tmp_path)
    campaign = _campaign()
    campaign.advance_time(86400.0)

    records = _read(path)
    assert records[0]["event"] == "campaign_start"
    tick = next(
        item
        for item in records
        if item["event"] == "tick"
        and item["side"] == campaign.player_side
    )
    assert tick["assets_before"]
    assert tick["assets_after"]
    assert tick["asset_deltas"]
    energy = tick["breakdowns"]["energy"]
    assert energy["terms"]
    assert energy["weight_sum"] > 0.0
    assert tick["characters"]["count"] > 0

    bdi = next(
        item
        for item in records
        if item["event"] == "bdi"
        and item["side"] == campaign.player_side
    )
    assert bdi["interval_seconds"] == pytest.approx(86400.0)
    assert bdi["simulated_seconds"] == pytest.approx(86400.0)
    assert bdi["before"]["needs"]
    assert bdi["after"]["needs"]
    assert "energy" in bdi["delta"]
    routine = bdi["routine"]
    assert routine["service"] > 0.0
    assert routine["rested_seconds"] > 0.0
    assert routine["effects"]


def test_stats_log_work_chance_formula(tmp_path, monkeypatch):
    path = _enable(monkeypatch, tmp_path)
    campaign = _campaign()
    action_id = campaign.action_options(campaign.player_side)[0]["id"]
    result = campaign.perform(campaign.player_side, action_id)
    assert result["ok"] is True

    work = next(
        item for item in _read(path) if item["event"] == "work"
    )
    formula = work["chance_formula"]
    assert formula["attack_asset"]
    assert formula["defense_asset"]
    assert 0.0 <= formula["chance"] <= 1.0
    assert formula["success"] is (
        formula["roll"] < formula["chance"]
    )
    assert work["modifiers"]["effect_scale"] > 0.0
    assert work["assets_before"]["actor"]
    assert work["assets_after"]["actor"]
    assert "assets" in work["applied"]


def test_stats_log_outcome_decision(tmp_path, monkeypatch):
    path = _enable(monkeypatch, tmp_path)
    campaign = _campaign()
    campaign.outcome_rules = {
        "streak_turns": 2,
        "defeat": {campaign.player_side: {"legitimacy": 0.99}},
    }
    campaign._check_outcome()
    campaign._check_outcome()
    records = [
        item for item in _read(path) if item["event"] == "outcome"
    ]
    assert records[-1]["decision"] == "lose"
    assert records[-1]["rule"] == "defeat"
    assert records[-1]["checks"][0]["streak"] == 2


def test_stats_disabled_by_environment(tmp_path, monkeypatch):
    path = tmp_path / "disabled.log"
    monkeypatch.setenv("OZVERIN_STATS", "0")
    monkeypatch.setenv("OZVERIN_STATS_LOG", str(path))
    campaign = _campaign()
    campaign.advance_time(86400.0)
    assert not path.exists()


def test_stats_do_not_write_to_console(monkeypatch, tmp_path, capsys):
    _enable(monkeypatch, tmp_path)
    capsys.readouterr()
    campaign = _campaign()
    campaign.advance_time(86400.0)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_stats_log_rotates_and_keeps_writing(tmp_path, monkeypatch):
    import campaign.audit as audit

    monkeypatch.setattr(audit, "MAX_BYTES", 500)
    path = _enable(monkeypatch, tmp_path)
    campaign = _campaign()
    campaign.advance_time(3 * 86400.0)
    assert path.exists()
    assert path.with_name(path.name + ".1").exists()
    assert _read(path)


def test_character_force_metric_uses_starting_maximum():
    from campaign.faction_state import character_metric

    campaign = _campaign()
    character = campaign.player.characters[0]
    assert character.state["max_force"] > 0.0
    assert character.state["max_energy"] > 0.0
    assert character.force == pytest.approx(
        character.state["max_force"]
    )
    assert character_metric(character, "force") == pytest.approx(1.0)
    character.force *= 0.5
    assert character_metric(character, "force") == pytest.approx(0.5)
