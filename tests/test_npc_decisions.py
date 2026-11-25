"""Теневые решения NPC в кампании: флаги по фракции, бюджет и метрики."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition import BackendError
from campaign.npc_decisions import NpcDecisionMonitor
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
