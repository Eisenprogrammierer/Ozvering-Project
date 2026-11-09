"""Журнал, авто-пауза и LOD кампании (§7.5 №32, §7.7 №39–42)."""

import copy

import pytest

from campaign import logbook
from campaign.clock import background_pause_reason
from campaign.lod import CampaignLod, due_on_day, node_distances
from campaign.world import (
    WorldEngine,
    build_player_profile,
    load_biography,
    load_world,
)


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


def _engine(seed=7, extra=None):
    profile = build_player_profile(
        _variables(), biography=load_biography(), seed=seed
    )
    world = copy.deepcopy(load_world())
    for key, value in (extra or {}).items():
        world[key] = value
    return WorldEngine(
        world,
        profile=profile,
        node_id="agora_government",
        office_id="head_of_government",
        seed=seed,
    )


def _entries():
    return [
        {"day": 1, "kind": "opening", "text": "начало"},
        {"day": 1, "kind": "contact", "text": "контакт"},
        {"day": 2, "kind": "economy", "text": "расход"},
        {"day": 2, "kind": "obligation", "text": "долг"},
        {"day": 3, "kind": "death", "text": "смерть"},
        {"day": 3, "kind": "day", "text": "итог дня"},
    ]


def test_severity_and_config_rules_are_data_driven():
    assert logbook.severity_for("death") == "critical"
    assert logbook.severity_for("contact") == "info"
    assert logbook.severity_for("unknown-kind") == "info"
    rules = logbook.rules_from_config(
        {
            "severity": {"contact": "notice"},
            "critical": ["economy"],
            "pause": {"obligation": "obligation_due"},
        }
    )
    assert logbook.severity_for("contact", rules) == "notice"
    assert logbook.severity_for("economy", rules) == "critical"
    assert logbook.severity_for("obligation", rules) == "critical"
    assert rules["pause"]["obligation"] == "obligation_due"


def test_log_view_filters_without_mutating_source():
    entries = _entries()
    before = copy.deepcopy(entries)
    critical = logbook.log_view(entries, min_severity="critical")
    assert [item["kind"] for item in critical] == ["death"]
    assert critical[0]["severity"] == "critical"
    assert critical[0]["rank"] == logbook.SEVERITY_RANK["critical"]
    assert entries == before

    since = logbook.log_view(entries, since_day=2)
    assert {item["day"] for item in since} == {2, 3}
    only = logbook.log_view(entries, kinds=["contact", "economy"])
    assert [item["kind"] for item in only] == ["contact", "economy"]
    limited = logbook.log_view(entries, limit=2)
    assert [item["kind"] for item in limited] == ["death", "day"]
    assert logbook.log_view(entries, limit=0) == []


def test_digest_counts_critical_and_today_without_reading_every_line():
    report = logbook.digest(_entries(), day=3)
    assert report["total"] == 6
    assert report["counts"]["day"] == 1
    assert report["by_severity"]["critical"] == 1
    assert report["critical"] == 1
    assert report["last_critical"]["kind"] == "death"
    assert report["today"] == 2
    text = logbook.summary_text(_entries(), day=3)
    assert "событий: 6" in text
    assert "критических: 1" in text


def test_compact_bounds_log_but_keeps_critical_and_recent():
    entries = [
        {"day": day, "kind": "contact", "text": str(day)}
        for day in range(1, 41)
    ]
    entries.insert(20, {"day": 20, "kind": "death", "text": "смерть"})
    kept, removed = logbook.compact(
        entries,
        max_entries=6,
        recent_days=2,
        critical_keep=5,
        day=40,
    )
    assert len(kept) <= 6
    assert removed == len(entries) - len(kept)
    assert any(item["kind"] == "death" for item in kept)
    assert any(item["day"] == 40 for item in kept)
    days = [item["day"] for item in kept]
    assert days == sorted(days)


def test_pause_reason_uses_only_current_day_and_can_be_extended():
    entries = _entries()
    assert logbook.pause_reason(entries, day=3) == "dead"
    entries.append({"day": 3, "kind": "ending", "text": "финал"})
    assert logbook.pause_reason(entries, day=3) == "finished"
    assert logbook.pause_reason(entries, day=4) == ""
    rules = logbook.rules_from_config(
        {"pause": {"obligation": "obligation_due"}}
    )
    assert logbook.pause_reason(entries, day=2, rules=rules) == (
        "obligation_due"
    )


def test_world_log_view_is_derived_and_raw_log_stays_plain():
    engine = _engine()
    raw_keys = set(engine.log[0])
    view = engine.log_view(limit=3)
    assert view
    assert "severity" in view[-1]
    assert "severity" not in engine.log[-1]
    assert set(engine.log[0]) == raw_keys
    assert engine.log_summary()


def test_critical_event_pauses_background_via_world_hook():
    engine = _engine()
    assert background_pause_reason(engine) == ""
    engine.log.append(
        {
            "day": engine.day,
            "kind": "ending",
            "text": "финал объявлен",
        }
    )
    assert engine.critical_pause_reason() == "finished"
    assert background_pause_reason(engine) == "finished"


def test_custom_critical_kind_stops_background_with_reason():
    engine = _engine(
        extra={"logging": {"pause": {"obligation": "obligation_due"}}}
    )
    assert background_pause_reason(engine) == ""
    engine.log.append(
        {"day": engine.day, "kind": "obligation", "text": "срок долга"}
    )
    assert engine.critical_pause_reason() == "obligation_due"
    assert background_pause_reason(engine) == "obligation_due"


def test_log_compaction_runs_on_day_edge_and_survives_snapshot():
    engine = _engine(
        extra={
            "logging": {
                "compact": True,
                "max_entries": 4,
                "recent_days": 0,
                "critical_keep": 2,
            }
        }
    )
    engine.log.append(
        {"day": engine.day, "kind": "death", "text": "важное"}
    )
    engine.end_day()
    assert len(engine.log) <= 4
    assert engine.log_trimmed > 0
    assert any(item["kind"] == "death" for item in engine.log)

    snapshot = engine.to_dict()
    restored = _engine()
    restored.load_snapshot(snapshot)
    assert restored.log == engine.log
    assert restored.log_trimmed == engine.log_trimmed
    assert restored._lod is None
    assert restored.tick_stats["ticks"] == 0


def test_lod_distances_and_tiers_follow_hierarchy():
    nodes = {
        "root": {"parent": "", "children": ["child"]},
        "child": {"parent": "root", "children": ["grand"]},
        "grand": {"parent": "child", "children": []},
        "other": {"parent": "", "children": []},
    }
    distances = node_distances(nodes, "root")
    assert distances["root"] == 0
    assert distances["child"] == 1
    assert distances["grand"] == 2
    assert distances["other"] > 2
    lod = CampaignLod(
        nodes,
        "root",
        {
            "enabled": True,
            "radii": [1, 2],
            "intervals": [1, 4, 12],
            "player_children_always_lod0": True,
        },
    )
    assert lod.tier("root") == 0
    assert lod.tier("child") == 0
    assert lod.tier("grand") == 0
    assert lod.tier("other") == 2
    assert lod.interval("other") == 12


def test_lod_due_schedule_is_deterministic_and_off_by_default():
    assert due_on_day("node", 1, 1) is True
    first = due_on_day("node", 5, 3)
    assert due_on_day("node", 5, 3) is first
    lod = CampaignLod({"root": {}}, "root", {})
    assert lod.config["enabled"] is False
    assert lod.due("root", 1) is True
    assert lod.report(day=1)["enabled"] is False


def test_world_lod_skips_periphery_and_records_tick_cost():
    engine = _engine(
        extra={
            "lod": {
                "enabled": True,
                "radii": [0, 1],
                "intervals": [1, 5, 9],
                "player_children_always_lod0": False,
            }
        }
    )
    view = engine.lod_view()
    assert view["enabled"] is True
    assert int(view["tiers"]["0"]) == 1
    assert int(view["tiers"]["1"]) + int(view["tiers"]["2"]) > 0

    lod = engine.lod()
    expected_skipped = sum(
        1
        for node_id in engine.node_order
        if not lod.due(node_id, engine.day)
    )
    assert expected_skipped > 0
    engine._run_node_actions(max_slot=None)
    assert engine.tick_stats["nodes_skipped"] == expected_skipped
    assert (
        engine.tick_stats["nodes_considered"]
        + engine.tick_stats["nodes_skipped"]
        == len(engine.node_order)
    )

    engine.tick(max_slot=engine._node_slot(engine.node_order[0]))
    assert engine.tick_stats["ticks"] == 1
    assert engine.tick_stats["last_cost"] >= 0.0
    scale = engine.scale_view()
    assert scale["lod"]["enabled"] is True
    assert scale["tick"]["ticks"] == 1
    assert scale["log"]["total"] == len(engine.log)


def test_lod_disabled_keeps_all_nodes_due_and_skips_nothing():
    engine = _engine()
    assert engine.lod_view()["enabled"] is False
    engine._run_node_actions(max_slot=None)
    assert engine.tick_stats["nodes_skipped"] == 0
