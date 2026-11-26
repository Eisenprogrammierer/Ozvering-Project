"""Теневые решения NPC в кампании: флаги по фракции, бюджет и метрики."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition import BackendError
from campaign.npc_decisions import NpcDecisionMonitor, job_diversity
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]


def _preset(seed=13):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    )
    return generator.generate(seed=seed)


def _campaign(seed=13):
    return AutomataCampaign(_preset(seed), seed=seed)


def _enable(campaign, **config):
    campaign.ai_model["npc_policy"] = dict(
        {"enabled": True}, **config
    )
    campaign._npc_policy_obj = None


def _ai_sides(campaign):
    return [
        side
        for side in campaign.factions
        if side != campaign.player_side
    ]


def test_monitor_counts_agreement_and_errors():
    monitor = NpcDecisionMonitor(max_samples=1)
    monitor.record(
        side="red", backend="shadow", legacy="a", candidate="a"
    )
    monitor.record(
        side="red", backend="shadow", legacy="b", candidate="c"
    )
    monitor.record(
        side="blue",
        backend="shadow",
        legacy="d",
        candidate=None,
        error="timeout",
    )
    report = monitor.report()
    assert report["total"] == 3
    assert report["evaluated"] == 2
    assert report["agreements"] == 1
    assert report["agreement"] == 0.5
    assert report["errors"] == 1
    assert report["ok"] is False
    assert report["mismatches"][0]["legacy"] == "b"
    assert report["error_samples"][0]["side"] == "blue"
    assert report["sides"]["red"]["total"] == 2
    assert report["sides"]["red"]["agreement"] == 0.5


def test_monitor_without_errors_and_full_agreement_is_ok():
    monitor = NpcDecisionMonitor()
    monitor.record(
        side="red", backend="shadow", legacy="a", candidate="a"
    )
    report = monitor.report()
    assert report["ok"] is True
    assert report["agreement"] == 1.0
    assert report["errors"] == 0


def test_npc_backend_uses_side_then_default_then_flag():
    campaign = _campaign()
    _enable(campaign, backend="soar", backends={"red": "shadow"})
    assert campaign.npc_backend("red") == "shadow"
    assert campaign.npc_backend("blue") == "soar"
    _enable(campaign, backends={"red": "legacy"})
    assert campaign.npc_backend("blue") == "legacy"

    campaign._cognition_flags = lambda: type(
        "Flags", (), {"ai_backend": "shadow", "decision_timeout_ms": 50}
    )()
    campaign.ai_model["npc_policy"] = {"enabled": True}
    assert campaign.npc_backend("green") == "shadow"
    assert campaign.npc_decision_timeout_ms() == 50.0


def test_npc_backend_rejects_unknown_value():
    campaign = _campaign()
    _enable(campaign, backend="nope")
    with pytest.raises(BackendError):
        campaign.npc_backend("red")


def test_local_timeout_overrides_global_flag():
    campaign = _campaign()
    _enable(campaign, timeout_ms=17)
    assert campaign.npc_decision_timeout_ms() == 17.0


def test_campaign_shadow_matches_legacy_on_long_run():
    pytest.importorskip("soar_sml")
    campaign = _campaign(13)
    sides = _ai_sides(campaign)
    _enable(
        campaign,
        backend="legacy",
        backends={side: "shadow" for side in sides},
    )
    campaign.run(turns=20)
    report = campaign.npc_decision_report()
    assert report["total"] > 0
    assert report["errors"] == 0
    assert report["agreement"] >= 0.95
    assert report["ok"] is True
    assert set(report["sides"]) <= set(sides)


def test_campaign_shadow_does_not_change_state():
    pytest.importorskip("soar_sml")
    shadow = _campaign(17)
    legacy = _campaign(17)
    sides = _ai_sides(shadow)
    _enable(
        shadow,
        backend="legacy",
        backends={side: "shadow" for side in sides},
    )
    _enable(legacy, backend="legacy")
    shadow.run(turns=12)
    legacy.run(turns=12)
    assert shadow.snapshot() == legacy.snapshot()
    assert shadow.npc_decision_report()["total"] > 0
    assert legacy.npc_decision_report()["total"] == 0


def test_job_diversity_reports_spread_and_concentration():
    single = job_diversity({"work": 4})
    assert single == {
        "total": 4,
        "distinct": 1,
        "entropy": 0.0,
        "evenness": 0.0,
        "top_share": 1.0,
    }
    even = job_diversity({"a": 2, "b": 2})
    assert even["distinct"] == 2
    assert even["evenness"] == 1.0
    assert even["top_share"] == 0.5
    skewed = job_diversity({"a": 3, "b": 1})
    assert 0.0 < skewed["evenness"] < 1.0
    assert skewed["top_share"] == 0.75
    assert job_diversity({})["total"] == 0


def test_monitor_records_jobs_per_side():
    monitor = NpcDecisionMonitor()
    monitor.record_action(side="red", action_id="drill")
    monitor.record_action(side="red", action_id="drill")
    monitor.record_action(side="red", action_id="patrol")
    monitor.record_action(side="blue", action_id="trade")
    monitor.record_action(side="blue", action_id=None)
    report = monitor.report()
    assert report["jobs"]["total"] == 4
    assert report["jobs"]["distinct"] == 3
    assert report["jobs"]["sides"]["red"]["total"] == 3
    assert report["jobs"]["sides"]["red"]["distinct"] == 2
    assert report["jobs"]["sides"]["blue"]["total"] == 1


def test_campaign_outcome_report_covers_needs_and_jobs():
    campaign = _campaign(23)
    _enable(campaign, backend="legacy")
    campaign.run(turns=8)
    report = campaign.npc_outcome_report()
    assert report["kind"] == "npc_outcomes"
    assert report["ok"] is True
    needs = report["needs"]
    assert needs["overall"]["characters"] > 0
    assert 0.0 <= needs["overall"]["pressure"] <= 1.0
    assert 0.0 <= needs["overall"]["satisfaction"] <= 1.0
    for side, item in needs["sides"].items():
        assert item["characters"] > 0, side
        assert len(item["needs"]) == 16, side
        assert 0.0 <= item["pressure"] <= 1.0
        assert item["satisfaction"] == pytest.approx(
            1.0 - item["pressure"], abs=1e-5
        )
    jobs = report["jobs"]
    assert jobs["total"] > 0
    assert jobs["distinct"] >= 1
    assert set(jobs["sides"]) <= set(needs["sides"])


def test_snapshot_keeps_npc_policy_config():
    campaign = _campaign(7)
    _enable(
        campaign,
        backend="legacy",
        backends={"blue": "shadow"},
        timeout_ms=25,
    )
    restored = AutomataCampaign(
        _preset(7), seed=7, snapshot=campaign.save_snapshot()
    )
    policy = restored.ai_model["npc_policy"]
    assert policy["backend"] == "legacy"
    assert policy["backends"] == {"blue": "shadow"}
    assert policy["timeout_ms"] == 25
    assert restored.npc_backend("blue") == "shadow"
    assert restored.npc_backend("red") == "legacy"
    assert restored.snapshot() == campaign.snapshot()


def test_soar_save_load_continues_with_soar_backend():
    pytest.importorskip("soar_sml")
    campaign = _campaign(7)
    _enable(campaign, backend="soar")
    campaign.run(turns=2)
    restored = AutomataCampaign(
        _preset(7), seed=7, snapshot=campaign.save_snapshot()
    )
    assert restored.npc_backend("red") == "soar"
    assert restored.snapshot() == campaign.snapshot()
    campaign.run(turns=1)
    restored.run(turns=1)
    assert restored.snapshot() == campaign.snapshot()
    assert restored.npc_outcome_report()["needs"] == (
        campaign.npc_outcome_report()["needs"]
    )


def test_soar_backend_matches_legacy_state_and_outcomes():
    pytest.importorskip("soar_sml")
    soar = _campaign(29)
    legacy = _campaign(29)
    _enable(soar, backend="soar")
    _enable(legacy, backend="legacy")
    soar.run(turns=10)
    legacy.run(turns=10)
    assert soar.snapshot() == legacy.snapshot()
    assert soar.npc_outcome_report()["needs"] == (
        legacy.npc_outcome_report()["needs"]
    )
    assert soar.npc_outcome_report()["jobs"] == (
        legacy.npc_outcome_report()["jobs"]
    )
    assert soar.npc_outcome_report()["decisions"]["errors"] == 0
    assert soar.npc_outcome_report()["ok"] is True


def test_tick_budget_resets_on_new_turn():
    campaign = _campaign()
    _enable(campaign, backend="legacy", tick_timeout_ms=100)
    campaign.end_turn()
    assert campaign.turn == 1
    campaign._npc_tick_spent_ms = 42.0
    campaign.end_turn()
    assert campaign.turn == 2
    assert campaign._npc_tick_spent_ms == 0.0
    budget = campaign.npc_tick_budget()
    assert budget["limit_ms"] == 100.0
    assert budget["left_ms"] == 100.0


def test_tick_budget_falls_back_to_legacy_in_shadow():
    campaign = _campaign()
    sides = _ai_sides(campaign)
    _enable(
        campaign,
        backend="legacy",
        backends={side: "shadow" for side in sides},
        tick_timeout_ms=1,
    )
    campaign.begin_turn()
    campaign._npc_tick_spent_ms = 1.0
    side = sides[0]
    chosen = campaign.auto_action(side)
    assert chosen is not None
    report = campaign.npc_decision_report()
    assert report["budget"] >= 1
    assert report["errors"] >= 1
    assert report["ok"] is False


def test_tick_budget_refuses_in_strict_soar():
    from campaign.cognition import SoarError

    campaign = _campaign()
    _enable(campaign, backend="soar", tick_timeout_ms=1)
    campaign.begin_turn()
    campaign._npc_tick_spent_ms = 1.0
    with pytest.raises(SoarError):
        campaign.auto_action(_ai_sides(campaign)[0])


def test_tick_budget_limits_single_decision():
    pytest.importorskip("soar_sml")
    from campaign.cognition import SoarError
    from campaign.cognition.soar_runtime import SoarNpcPolicy

    policy = SoarNpcPolicy()
    with pytest.raises(SoarError):
        policy.choose(
            [("work", "hunger", 1.0)],
            {"hunger": 0.5},
            timeout_ms=0.001,
        )
    assert policy.last_elapsed_ms > 0.0
