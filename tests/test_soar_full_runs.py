"""Полные прогоны кампании и мира с Soar: паритет, бюджеты, память."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]


def _variables():
    return {
        "name": "Ирина Свет",
        "gender": "female",
        "origin": "port",
        "family": "clerk",
        "education": "academy",
        "formative": "harbor_fire",
        "vocation": "state",
        "value": "order",
        "value2": "knowledge",
        "flaw": "ambition",
        "patron": "minister",
        "reputation": "respectable",
    }


def _preset(seed=13):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    )
    return generator.generate(seed=seed)


def _campaign(seed=13):
    return AutomataCampaign(_preset(seed), seed=seed)


def _enable_soar(campaign):
    campaign.ai_model["npc_policy"] = {
        "enabled": True,
        "backend": "soar",
    }
    campaign._npc_policy_obj = None
    campaign._soar_npc_pool_obj = None


def _world(seed=7):
    from campaign.world import (
        WorldEngine,
        build_player_profile,
        load_biography,
        load_world,
    )

    return WorldEngine(
        load_world(),
        profile=build_player_profile(
            _variables(), biography=load_biography(), seed=seed
        ),
        node_id="agora_government",
        office_id="head_of_government",
        seed=seed,
    )


def test_full_campaign_soar_matches_legacy(monkeypatch):
    pytest.importorskip("soar_sml")
    monkeypatch.setenv("OZVERIN_AI_BACKEND", "soar")
    soar = _campaign(41)
    _enable_soar(soar)
    soar.run(turns=20)

    monkeypatch.setenv("OZVERIN_AI_BACKEND", "legacy")
    legacy = _campaign(41)
    _enable_soar(legacy)
    legacy.run(turns=20)

    assert soar.snapshot() == legacy.snapshot()
    assert soar.npc_outcome_report()["needs"] == (
        legacy.npc_outcome_report()["needs"]
    )


def test_full_world_soar_matches_legacy(monkeypatch):
    pytest.importorskip("soar_sml")
    monkeypatch.setenv("OZVERIN_AI_BACKEND", "soar")
    soar = _world(7)
    soar.advance_days(10)

    monkeypatch.setenv("OZVERIN_AI_BACKEND", "legacy")
    legacy = _world(7)
    legacy.advance_days(10)

    assert soar.to_dict() == legacy.to_dict()


def test_full_campaign_soar_stays_in_budgets_and_memory(monkeypatch):
    pytest.importorskip("soar_sml")
    monkeypatch.setenv("OZVERIN_AI_BACKEND", "soar")
    campaign = _campaign(43)
    _enable_soar(campaign)
    campaign.run(turns=15)

    outcome = campaign.npc_outcome_report()
    assert outcome["ok"] is True
    assert outcome["agents"]["errors"] == 0
    assert outcome["agents"]["agents"] <= outcome["agents"]["max_agents"]
    assert outcome["mass_npc"]["ok"] is True
    assert outcome["intentions"]["pool"]["agents"] <= 1
    assert outcome["intentions"]["latency"]["samples"] > 0
    assert outcome["intentions"]["latency"]["p95_ms"] < 50.0

    pool = campaign._soar_npc_pool_obj
    assert pool is not None
    assert len(pool) <= pool.max_agents
    assert pool.report()["errors"] == 0


def test_full_campaign_soar_save_load_continues(monkeypatch):
    pytest.importorskip("soar_sml")
    monkeypatch.setenv("OZVERIN_AI_BACKEND", "soar")
    campaign = _campaign(47)
    _enable_soar(campaign)
    campaign.run(turns=8)

    state = campaign.save_snapshot()
    agents = campaign.soar_snapshot()
    assert agents and agents["agents"]

    restored = AutomataCampaign(_preset(47), seed=47, snapshot=state)
    _enable_soar(restored)
    restored.restore_soar_snapshot(agents)
    assert restored.soar_agent_report()["agents"] == 0

    campaign.run(turns=4)
    restored.run(turns=4)
    assert restored.snapshot() == campaign.snapshot()
    assert restored.npc_outcome_report()["needs"] == (
        campaign.npc_outcome_report()["needs"]
    )
    assert restored.soar_agent_report()["errors"] == 0
