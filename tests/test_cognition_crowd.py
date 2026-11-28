"""LOD массовых NPC: общий пул намерений и стоимость тика."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition.intention_runtime import (
    SoarIntentionPool,
    close_intention_pool,
    intention_pool_report,
    latency_summary,
    shared_intention,
)
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


def _disable_work_policy(campaign):
    campaign.ai_model["npc_policy"] = {"enabled": False}
    campaign._npc_policy_obj = None


def test_latency_summary_percentiles():
    empty = latency_summary([])
    assert empty == {
        "samples": 0,
        "p50_ms": 0.0,
        "p95_ms": 0.0,
        "max_ms": 0.0,
    }

    report = latency_summary([5.0, 1.0, 3.0, 2.0, 4.0])
    assert report["samples"] == 5
    assert report["p50_ms"] == 3.0
    assert report["p95_ms"] == 5.0
    assert report["max_ms"] == 5.0


def test_intention_pool_reuses_agent_and_bounds_lru():
    pool = SoarIntentionPool(max_agents=2)
    try:
        first = pool.get(1)
        assert pool.get(1) is first
        assert len(pool) == 1
        pool.get(2)
        pool.get(3)
        assert len(pool) == 2
        assert pool.starts == 3
        assert pool.evictions == 1
        report = pool.report()
        assert report["agents"] == 2
        assert report["max_agents"] == 2
        assert report["starts"] == 3
        assert report["evictions"] == 1
        assert report["latency"]["samples"] == 0
    finally:
        pool.close()


def test_shared_intention_is_one_shared_agent():
    close_intention_pool()
    try:
        first = shared_intention(7)
        assert shared_intention(7) is first
        report = intention_pool_report()
        assert report["agents"] == 1
        assert report["max_agents"] == 1
        assert report["starts"] == 1
    finally:
        close_intention_pool()


def test_campaign_reports_shared_pool_and_tick_cost(monkeypatch):
    pytest.importorskip("soar_sml")
    monkeypatch.setenv("OZVERIN_AI_BACKEND", "soar")
    campaign = _campaign(31)
    _disable_work_policy(campaign)
    campaign.run(turns=3)

    report = campaign.intention_report()
    assert report["queries"] > 0
    assert report["errors"] == 0
    assert report["pool"]["agents"] == 1
    assert report["pool"]["shared"] is True
    assert report["latency"]["samples"] > 0
    assert report["latency"]["p95_ms"] >= 0.0

    mass = campaign.mass_npc_report()
    assert mass["ticks"] > 0
    assert mass["characters"] > 0
    assert mass["deliberated"] > 0
    assert mass["latency"]["samples"] > 0
    assert mass["exceeded"] is False
    assert mass["ok"] is True

    outcome = campaign.npc_outcome_report()
    assert outcome["mass_npc"]["ticks"] == mass["ticks"]
    assert outcome["ok"] is True


def test_mass_npc_tick_budget_marks_exceeded(monkeypatch):
    pytest.importorskip("soar_sml")
    monkeypatch.setenv("OZVERIN_AI_BACKEND", "soar")
    campaign = _campaign(37)
    _disable_work_policy(campaign)
    campaign.ai_model["character_agency"]["tick_budget_ms"] = 0.001
    campaign.run(turns=2)

    mass = campaign.mass_npc_report()
    assert mass["ticks"] > 0
    assert mass["budget_ms"] == 0.001
    assert mass["exceeded"] is True
    assert mass["ok"] is False
    assert campaign.npc_outcome_report()["ok"] is False
