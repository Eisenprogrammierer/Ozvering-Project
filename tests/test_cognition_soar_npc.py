"""Долгоживущие Soar-агенты именных NPC: BDI-память, пул и снимки."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition.soar_npc import (
    DEFAULT_MAX_AGENTS,
    SoarNpcAgent,
    SoarNpcPool,
    bdi_memory,
)
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]


class _Belief:
    def __init__(self, subject, predicate, obj="", value=1.0):
        self.subject = subject
        self.predicate = predicate
        self.object = obj
        self.value = value
        self.confidence = 1.0
        self.source = "test"

    def as_dict(self):
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
        }


class _Intention:
    def __init__(self, target, essence):
        self.target = target
        self.essence = essence


class _BDI:
    def __init__(self):
        self.needs = {"hunger": 0.4, "thirst": 0.2}
        self.beliefs = [
            _Belief("a", "trusts", "b", 0.7),
            _Belief("a", "fears", "c", 0.3),
        ]
        self.intentions = [
            _Intention("hunger", "eat"),
            _Intention("rest", "sleep"),
        ]
        self.traits = {"bold": 0.6}
        self.conditions = {"wound": 0.2}


class _Character:
    campaign_id = "char_test_001"
    name = "Тест"
    needs = {"hunger": 0.4, "thirst": 0.2}
    bdi = _BDI()
    morale = 55.0
    force = 1.0
    energy = 0.9


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
    campaign._soar_npc_pool_obj = None


def _ai_sides(campaign):
    return [
        side
        for side in campaign.factions
        if side != campaign.player_side
    ]


def _candidates(campaign, side, leader):
    policy = campaign._npc_policy()
    weighted = campaign._ai_weighted_options(side, exclude_active=True)
    items = []
    for option, weight in weighted:
        essences = campaign._action_essences(option["action"])
        need = (
            campaign._action_need(essences[0], leader)
            if essences
            else ""
        )
        if need:
            items.append((option["id"], need, weight))
    return policy, items


def test_bdi_memory_covers_needs_beliefs_and_caps():
    nodes = bdi_memory(
        _Character(), tick=7, max_beliefs=1, max_intentions=1
    )

    assert len(nodes) == 1
    self_node = nodes[0]
    assert self_node["attribute"] == "self"
    children = self_node["children"]
    by_attribute = {}
    for child in children:
        by_attribute.setdefault(child["attribute"], []).append(child)
    assert by_attribute["id"][0]["value"] == "char_test_001"
    assert by_attribute["name"][0]["value"] == "Тест"
    assert by_attribute["tick"][0]["value"] == 7
    assert len(by_attribute["belief"]) == 1
    assert by_attribute["belief"][0]["children"][1]["value"] == "fears"
    assert len(by_attribute["intention"]) == 1
    assert by_attribute["intention"][0]["children"][1]["value"] == "sleep"
    needs = by_attribute["needs"][0]["children"]
    assert {item["attribute"] for item in needs} == {"hunger", "thirst"}
    assert by_attribute["traits"][0]["children"][0]["attribute"] == "bold"
    assert by_attribute["conditions"][0]["children"][0]["attribute"] == "wound"
    assert by_attribute["morale"][0]["value"] == 55.0


def test_agent_matches_one_shot_policy_and_keeps_memory():
    pytest.importorskip("soar_sml")
    from campaign.cognition.soar_runtime import (
        SoarNpcPolicy,
        weights_for,
    )

    campaign = _campaign(29)
    _enable(campaign, backend="soar")
    side = _ai_sides(campaign)[0]
    leader = campaign._leader(side)
    policy, items = _candidates(campaign, side, leader)
    names = sorted({need for _option, need, _base in items})
    weights = weights_for(policy, names)
    agent = SoarNpcAgent("npc:test", timeout_ms=200)
    one_shot = SoarNpcPolicy(timeout_ms=200)
    try:
        for tick in range(4):
            agent.remember(leader, tick=tick)
            assert agent.choose(
                items,
                leader.needs,
                weights=weights,
                timeout_ms=200,
            ) == one_shot.choose(
                items,
                leader.needs,
                weights=weights,
                timeout_ms=200,
            )
        snapshot = agent.snapshot()
    finally:
        agent.close()

    assert snapshot["counters"]["decisions"] == 4
    assert snapshot["tick"] == 4
    attributes = [node["attribute"] for node in snapshot["wm"]]
    assert attributes == ["self"]
    assert snapshot["wm"][0]["children"][0]["value"] == leader.campaign_id


def test_pool_is_lazy_evicts_lru_and_restores_snapshot():
    pytest.importorskip("soar_sml")
    campaign = _campaign(13)
    _enable(campaign, backend="soar")
    side = _ai_sides(campaign)[0]
    leader = campaign._leader(side)
    policy, items = _candidates(campaign, side, leader)
    from campaign.cognition.soar_runtime import weights_for

    weights = weights_for(
        policy, sorted({need for _option, need, _base in items})
    )
    pool = SoarNpcPool(max_agents=2, timeout_ms=200)
    try:
        first = pool.get("npc:first", leader, tick=0)
        first.choose(items, leader.needs, weights=weights)
        first_snapshot = first.snapshot()
        pool.get("npc:second", leader, tick=1)
        pool.get("npc:third", leader, tick=2)
        assert len(pool) == 2
        assert pool.evictions == 1
        assert "npc:first" in pool.store
        report = pool.report()
        assert report["agents"] == 2
        assert report["max_agents"] == 2
        assert report["starts"] == 3
        assert report["evictions"] == 1
        restored = pool.get("npc:first")
        assert restored.snapshot() == first_snapshot
    finally:
        pool.close()


def test_pool_snapshot_roundtrips():
    pytest.importorskip("soar_sml")
    campaign = _campaign(17)
    _enable(campaign, backend="soar")
    side = _ai_sides(campaign)[0]
    leader = campaign._leader(side)
    policy, items = _candidates(campaign, side, leader)
    from campaign.cognition.soar_runtime import weights_for

    weights = weights_for(
        policy, sorted({need for _option, need, _base in items})
    )
    pool = SoarNpcPool(timeout_ms=200)
    try:
        agent = pool.get("npc:round", leader, tick=3)
        agent.choose(items, leader.needs, weights=weights)
        payload = pool.snapshot()
        snapshot = agent.snapshot()
    finally:
        pool.close()

    restored = SoarNpcPool(timeout_ms=200)
    try:
        restored.restore(payload)
        assert restored.store.load("npc:round") == snapshot
        again = restored.get("npc:round")
        assert again.snapshot() == snapshot
    finally:
        restored.close()


def test_campaign_uses_pool_and_saves_agents():
    pytest.importorskip("soar_sml")
    campaign = _campaign(23)
    _enable(campaign, backend="soar")
    campaign.run(turns=4)

    report = campaign.soar_agent_report()
    assert report["agents"] >= 1
    assert report["decisions"] > 0
    assert report["errors"] == 0
    assert report["max_agents"] == DEFAULT_MAX_AGENTS
    payload = campaign.soar_snapshot()
    assert payload["schema"] == "soar_snapshots.v1"
    assert payload["agents"]
    outcome = campaign.npc_outcome_report()
    assert outcome["agents"]["decisions"] == report["decisions"]
    assert outcome["ok"] is True

    restored = _campaign(23)
    _enable(restored, backend="soar")
    restored.restore_soar_snapshot(payload)
    assert restored.soar_agent_report()["saved"] == len(payload["agents"])
    assert restored.soar_agent_report()["agents"] == 0
