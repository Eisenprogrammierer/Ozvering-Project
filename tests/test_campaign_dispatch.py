"""Доклады источников: BDI, качественные claim'ы и последствия выбора."""

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

    return AutomataCampaign(_preset(), seed=11)


def _issue(campaign):
    report = campaign.dispatch.issue()
    assert report is not None
    return report


def _read(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_source_is_chosen_by_asset_post():
    campaign = _campaign()
    faction = campaign.player
    intendant = campaign.dispatch._source(faction, "supply")
    assert intendant is not None
    assert intendant.campaign_post_id == "intendant"
    justice = campaign.dispatch._source(faction, "legitimacy")
    assert justice is not None
    assert justice.campaign_post_id in ("justice", "propaganda")


def test_report_carries_claim_with_confidence_and_quality_band():
    campaign = _campaign()
    report = _issue(campaign)

    assert report["status"] == "pending"
    assert report["source_name"]
    assert report["source_post"]
    assert report["text"]
    assert report["source_name"] in report["text"] or (
        report["asset_label"] in report["text"]
    )
    assert 0.0 <= report["confidence"] <= 1.0
    assert 0.0 <= report["perceived"] <= 1.0
    assert 0.0 <= report["true_value"] <= 1.0
    assert report["band_label"]
    assert report["true_band_label"]
    assert [item["id"] for item in report["choices"]] == [
        "trust",
        "verify",
        "ignore",
    ]
    assert campaign.pending_reports(campaign.player_side)[0]["id"] == (
        report["id"]
    )


def test_tone_follows_source_bdi():
    campaign = _campaign()
    dispatch = campaign.dispatch
    loyal = {
        "loyalty": 0.9,
        "ambition": 0.2,
    }
    disloyal = {
        "loyalty": 0.2,
        "ambition": 0.2,
    }
    ambitious = {
        "loyalty": 0.5,
        "ambition": 0.9,
    }
    calm = {"fear": 0.1}
    fearful = {"fear": 0.9}

    assert dispatch._tone(loyal, calm) == "loyal"
    assert dispatch._tone(loyal, fearful) == "loyal_fearful"
    assert dispatch._tone(disloyal, calm) == "hostile"
    assert dispatch._tone(ambitious, calm) == "ambitious"


def test_choices_do_not_touch_assets(monkeypatch):
    campaign = _campaign()
    faction = campaign.player
    calls = []
    monkeypatch.setattr(
        faction, "add_asset", lambda *args, **kwargs: calls.append(args)
    )
    monkeypatch.setattr(
        faction, "set_asset", lambda *args, **kwargs: calls.append(args)
    )

    for choice in ("trust", "verify", "ignore"):
        report = _issue(campaign)
        assert campaign.resolve_report(report["id"], choice)["ok"] is True

    assert calls == []


def test_trust_changes_relations_and_belief_without_direct_assets(monkeypatch):
    campaign = _campaign()
    report = _issue(campaign)
    source = campaign.dispatch._character(report["source_id"])
    morale = source.morale
    trust_before = campaign.relations.axes_for(
        campaign.player.id, report["source_id"]
    )
    calls = []
    monkeypatch.setattr(
        campaign.player,
        "add_asset",
        lambda *args, **kwargs: calls.append(args),
    )

    result = campaign.resolve_report(report["id"], "trust")

    assert result["ok"] is True
    assert source.morale > morale
    assert campaign.relations.axes_for(
        campaign.player.id, report["source_id"]
    )["trust"] > trust_before["trust"]
    assert any(
        belief.subject == "player" and belief.predicate == "trusts"
        for belief in source.beliefs
    )
    assert calls == []
    assert report["status"] == "resolved"


def test_verify_separates_right_from_wrong():
    campaign = _campaign()
    correct = _issue(campaign)
    correct["perceived"] = correct["true_value"]
    source = campaign.dispatch._character(correct["source_id"])

    result = campaign.resolve_report(correct["id"], "verify")
    assert result["ok"] is True
    assert result["correct"] is True
    assert any(
        belief.predicate == "verified" for belief in source.beliefs
    )

    wrong = _issue(campaign)
    wrong["perceived"] = min(
        1.0, wrong["true_value"] + campaign.dispatch.verify_tolerance + 0.2
    )
    wrong_source = campaign.dispatch._character(wrong["source_id"])
    morale = wrong_source.morale
    result = campaign.resolve_report(wrong["id"], "verify")
    assert result["ok"] is True
    assert result["correct"] is False
    assert wrong_source.morale < morale
    assert any(
        belief.predicate == "doubts" for belief in wrong_source.beliefs
    )


def test_ignore_raises_fear_and_lowers_trust():
    campaign = _campaign()
    report = _issue(campaign)
    source = campaign.dispatch._character(report["source_id"])
    fear = source.needs["fear"]
    trust = campaign.relations.axes_for(
        campaign.player.id, report["source_id"]
    )["trust"]

    result = campaign.resolve_report(report["id"], "ignore")

    assert result["ok"] is True
    assert source.needs["fear"] > fear
    assert campaign.relations.axes_for(
        campaign.player.id, report["source_id"]
    )["trust"] < trust
    assert any(
        belief.predicate == "ignored" for belief in source.beliefs
    )


def test_report_enters_story_feed():
    campaign = _campaign()
    report = _issue(campaign)

    entry = next(
        item
        for item in campaign.story_events
        if item.get("category") == "report"
    )
    assert entry["report_id"] == report["id"]
    assert entry["source_name"] == report["source_name"]
    assert entry["effects"] == {}
    assert entry["requires_choice"] is True


def test_pending_decision_disappears_after_resolution():
    campaign = _campaign()
    report = _issue(campaign)
    assert campaign.decision_pending(campaign.player_side) is True
    assert campaign.pending_decisions(campaign.player_side)[0]["id"] == (
        report["id"]
    )

    campaign.resolve_report(report["id"], "trust")

    assert campaign.decision_pending(campaign.player_side) is False
    assert campaign.pending_decisions(campaign.player_side) == []


def test_snapshot_keeps_pending_queue_and_rng():
    campaign = _campaign()
    report = _issue(campaign)
    snapshot = campaign.snapshot()

    from campaign.automata import AutomataCampaign

    restored = AutomataCampaign(
        _preset(), seed=11, snapshot=snapshot
    )
    loaded = restored.report(report["id"])
    assert loaded is not None
    assert loaded["status"] == "pending"
    assert loaded["source_id"] == report["source_id"]
    assert restored.dispatch.rng.getstate() == campaign.dispatch.rng.getstate()
    assert restored.resolve_report(report["id"], "trust")["ok"] is True


def test_dispatch_tick_issues_by_interval():
    campaign = _campaign()
    campaign.dispatch.interval = 100.0
    campaign.dispatch._progress = 0.0

    spawned = campaign.dispatch.tick(250.0)

    assert len(spawned) == 2
    assert campaign.dispatch._progress == pytest.approx(50.0)
    assert len(campaign.pending_reports(campaign.player_side)) == 2


def test_audit_logs_report_issue_and_choice(tmp_path, monkeypatch):
    path = tmp_path / "campaign_stats.log"
    monkeypatch.setenv("OZVERIN_STATS", "1")
    monkeypatch.setenv("OZVERIN_STATS_LOG", str(path))
    campaign = _campaign()
    report = _issue(campaign)
    campaign.resolve_report(report["id"], "ignore")

    records = _read(path)
    issued = next(
        item for item in records if item["event"] == "report_issued"
    )
    choice = next(
        item for item in records if item["event"] == "report_choice"
    )
    assert issued["report_id"] == report["id"]
    assert issued["true_value"] == report["true_value"]
    assert issued["perceived"] == report["perceived"]
    assert choice["choice"] == "ignore"
    assert choice["changes"]["morale"] < 0
    assert "assets_before" not in choice
    assert "assets_after" not in choice
