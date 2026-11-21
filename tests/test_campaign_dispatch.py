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

    campaign = AutomataCampaign(_preset(), seed=11)
    campaign.dispatch.rumor_enabled = False
    return campaign


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


def _force_contradiction(campaign):
    dispatch = campaign.dispatch
    dispatch.contradiction_enabled = True
    dispatch.contradiction_chance = 1.0
    dispatch.assets = ["supply"]
    faction = campaign.player
    chosen = [
        character
        for character in faction.characters
        if str(getattr(character, "campaign_post_id", "") or "")
    ][:2]
    assert len(chosen) == 2
    queue = list(chosen)

    def _source(_faction, _asset):
        return queue.pop(0) if queue else chosen[0]

    dispatch._source = _source
    return chosen


def test_source_is_chosen_by_asset_post():
    campaign = _campaign()
    faction = campaign.player
    intendant = campaign.dispatch._source(faction, "supply")
    assert intendant is not None
    assert intendant.campaign_post_id == "intendant"
    justice = campaign.dispatch._source(faction, "legitimacy")
    assert justice is not None
    assert justice.campaign_post_id in ("justice", "propaganda")


def test_source_rotates_between_posts_of_same_asset():
    campaign = _campaign()
    dispatch = campaign.dispatch
    first = dispatch._source(campaign.player, "supply")
    dispatch._seq = 1
    second = dispatch._source(campaign.player, "supply")
    dispatch._seq = 2
    third = dispatch._source(campaign.player, "supply")

    assert first is not second
    assert first is third


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
    campaign.actions_left = 10
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
    campaign.actions_left = 10
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
    campaign.actions_left = 10
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

    sides = {report["side"] for report in spawned}
    assert len(spawned) == 2 * len(campaign.factions)
    assert sides == set(campaign.factions)
    assert campaign.dispatch._progress == pytest.approx(50.0)
    assert len(campaign.pending_reports(campaign.player_side)) == 2
    for report in spawned:
        if report["side"] == campaign.player_side:
            assert report["status"] == "pending"
        else:
            assert report["status"] == "resolved"
            assert report.get("decided_by") == "ai"


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


def test_verify_requires_action_budget():
    campaign = _campaign()
    campaign._turn_active = True
    campaign.actions_left = 0
    report = _issue(campaign)

    blocked = campaign.resolve_report(report["id"], "verify")
    assert blocked["ok"] is False
    assert "проверка недоступна" in blocked["reason"]
    assert report["status"] == "pending"

    campaign.actions_left = 1
    allowed = campaign.resolve_report(report["id"], "verify")
    assert allowed["ok"] is True
    assert allowed["cost"] == 1
    assert campaign.actions_left == 0


def test_rumor_is_anonymous_and_verify_yields_new_claim():
    campaign = _campaign()
    campaign.dispatch.rumor_enabled = True
    campaign.dispatch.rumor_chance = 1.0
    campaign.actions_left = 10

    report = _issue(campaign)
    assert report["channel"] == "rumor"
    assert report["anonymous"] is True
    assert report["source_name"] == "Слух"
    assert report["source_post"] == ""
    assert report["confidence"] <= campaign.dispatch.rumor_confidence_scale

    result = campaign.resolve_report(report["id"], "verify")
    assert result["ok"] is True
    assert result["correct"] is None
    assert result["revealed_truth"] is False
    assert result["truth_band"] is None
    assert result["cost"] == 1
    assert result["follow_up"]

    follow = campaign.report(result["follow_up"])
    assert follow is not None
    assert follow["follow_up"] is True
    assert follow["derived_from"] == report["id"]
    assert follow["status"] == "pending"
    assert campaign.decision_pending(campaign.player_side) is True

    campaign.actions_left = 10
    second = campaign.resolve_report(follow["id"], "verify")
    assert second["ok"] is True
    assert second["follow_up"] is None


def test_contradiction_links_two_pending_reports():
    campaign = _campaign()
    _force_contradiction(campaign)
    first = _issue(campaign)
    first["band"] = "other-band"
    first["band_label"] = "иное"

    second = _issue(campaign)

    assert second["contradiction"] is True
    assert second["contradicts"] == first["id"]
    assert second["counter_source"] == first["source_name"]
    assert "Ранее" in second["counter_line"]
    assert first["contradicted_by"] == second["id"]
    assert "Позже" in first["counter_line"]
    assert [
        item["id"]
        for item in campaign.pending_reports(campaign.player_side)
    ] == [second["id"]]
    assert campaign.decision_pending(campaign.player_side) is True


def test_contradiction_trust_closes_both_reports():
    campaign = _campaign()
    _force_contradiction(campaign)
    first = _issue(campaign)
    first["band"] = "other-band"
    second = _issue(campaign)

    result = campaign.resolve_report(second["id"], "trust")

    assert result["ok"] is True
    assert result["counterpart"]["id"] == first["id"]
    assert first["status"] == "resolved"
    assert first["resolved"]["resolved_by"] == second["id"]
    assert second["status"] == "resolved"
    assert campaign.decision_pending(campaign.player_side) is False


def test_contradiction_verify_resolves_both_and_costs_once():
    campaign = _campaign()
    campaign.actions_left = 10
    _force_contradiction(campaign)
    first = _issue(campaign)
    first["band"] = "other-band"
    second = _issue(campaign)

    result = campaign.resolve_report(second["id"], "verify")

    assert result["ok"] is True
    assert result["cost"] == 1
    assert campaign.actions_left == 9
    assert result["counterpart"]["correct"] in (True, False)
    assert first["status"] == "resolved"
    assert first["resolved"]["revealed_truth"] is True
    assert first["resolved"]["resolved_by"] == second["id"]


def test_contradiction_ignore_closes_both_reports():
    campaign = _campaign()
    _force_contradiction(campaign)
    first = _issue(campaign)
    first["band"] = "other-band"
    second = _issue(campaign)

    result = campaign.resolve_report(second["id"], "ignore")

    assert result["ok"] is True
    assert first["status"] == "resolved"
    assert second["status"] == "resolved"
    assert campaign.decision_pending(campaign.player_side) is False


def test_contradiction_pair_closes_from_either_report():
    campaign = _campaign()
    _force_contradiction(campaign)
    first = _issue(campaign)
    first["band"] = "other-band"
    second = _issue(campaign)

    result = campaign.resolve_report(first["id"], "trust")

    assert result["ok"] is True
    assert result["counterpart"]["id"] == second["id"]
    assert first["status"] == "resolved"
    assert second["status"] == "resolved"
    assert campaign.decision_pending(campaign.player_side) is False


def test_expiring_contradiction_removes_both_reports():
    campaign = _campaign()
    _force_contradiction(campaign)
    campaign.dispatch.max_pending = 2
    first = _issue(campaign)
    first["band"] = "other-band"
    second = _issue(campaign)
    third = _issue(campaign)
    fourth = _issue(campaign)

    assert first["status"] == "expired"
    assert second["status"] == "expired"
    assert third["status"] == "pending"
    assert fourth["status"] == "pending"
    assert len(campaign.pending_reports(campaign.player_side)) == 2


def _foreign(campaign):
    for side, faction in campaign.factions.items():
        if side != campaign.player_side:
            return faction
    raise AssertionError("нет чужой фракции")


def _fresh_report(campaign, faction, asset="supply", source=None):
    dispatch = campaign.dispatch
    if source is None:
        source = dispatch._source(faction, asset)
    assert source is not None
    report = dispatch._build_report(faction, source, asset)
    assert report is not None
    dispatch.reports.append(report)
    return report, source


def test_ai_decides_foreign_report_through_leader_bdi():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = _foreign(campaign)
    report = dispatch.issue(faction)
    assert report is not None
    leader = dispatch._leader_for(faction)
    beliefs_before = [item.as_dict() for item in leader.bdi.beliefs]
    needs_before = dict(leader.needs)
    morale_before = leader.morale

    result = dispatch.auto_resolve(report)

    assert result is not None and result["ok"] is True
    assert report["status"] == "resolved"
    assert report["decided_by"] == "ai"
    assert report["recipient_id"] == leader.campaign_id
    beliefs_after = [item.as_dict() for item in leader.bdi.beliefs]
    assert (
        beliefs_after != beliefs_before
        or dict(leader.needs) != needs_before
        or leader.morale != morale_before
    )
    assert report["resolved"]["decided_by"] == "ai"


def test_foreign_report_trust_changes_faction_action_weights():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = _foreign(campaign)
    leader = dispatch._leader_for(faction)
    leader_key = dispatch._leader_key(faction, leader)
    report, _source = _fresh_report(campaign, faction)
    report["band"] = "low"
    report["band_label"] = "просело"
    before = campaign.ai_action_weights(faction.side)

    result = dispatch.resolve(report["id"], "trust")

    assert result["ok"] is True
    threat_target = dispatch._rival_faction_id(faction)
    assert threat_target
    assert any(
        belief.predicate == "sees_as_threat"
        and belief.object == threat_target
        for belief in leader.bdi.beliefs
    )
    after = campaign.ai_action_weights(faction.side)
    assert any(
        after[key] > before[key] + 1e-9
        for key in after
        if key in before
    )
    assert leader_key in {
        item.subject for item in leader.bdi.beliefs
    }


def test_source_memory_appears_in_next_report_and_survives_snapshot():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = campaign.player
    report, source = _fresh_report(campaign, faction)
    dispatch.resolve(report["id"], "ignore")

    memory = dispatch._memory_for(source.campaign_id)
    assert memory["last_outcome"] == "ignored"
    assert memory["last_report_id"] == report["id"]

    follow, _source = _fresh_report(
        campaign, faction, source=source
    )
    assert "В прошлый раз" in follow["chain_line"]
    assert "отложили" in follow["chain_line"]

    from campaign.automata import AutomataCampaign

    restored = AutomataCampaign(
        _preset(), seed=11, snapshot=campaign.snapshot()
    )
    loaded = restored.dispatch._memory_for(source.campaign_id)
    assert loaded["last_outcome"] == "ignored"
    assert loaded["last_report_id"] == report["id"]


def test_promise_ledger_reminds_and_penalizes_overdue():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = campaign.player
    report, source = _fresh_report(campaign, faction)
    report["asks_promise"] = True
    report["request_line"] = "Прошу поддержки."

    result = dispatch.resolve(report["id"], "trust")

    assert result["ok"] is True
    promise_id = result["promise"]
    assert promise_id
    obligation = campaign.obligations.get(promise_id)
    assert obligation is not None
    assert obligation.creditor == source.campaign_id
    assert obligation.debtor == "player"
    assert obligation.note.startswith("report:%s:" % report["id"])

    reminder, overdue = dispatch._promise_context(
        faction, source, report["asset"], report["true_value"]
    )
    assert "обещали" in reminder
    assert overdue is False

    campaign.turn = obligation.due_day
    overdue_line, overdue = dispatch._promise_context(
        faction, source, report["asset"], report["true_value"]
    )
    assert overdue is True
    assert "просрочено" in overdue_line
    memory = dispatch._memory_for(source.campaign_id)
    assert "promise:%s" % promise_id in memory["penalized_promises"]


def test_verification_separates_error_from_deliberate_lie():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = campaign.player

    honest, _source = _fresh_report(campaign, faction)
    honest["manipulation"] = False
    honest["distortion"] = 0
    honest["band"] = "excellent"
    honest["band_label"] = "образцово"
    honest["perceived"] = 0.95
    honest["true_value"] = 0.1
    honest_result = dispatch.resolve(honest["id"], "verify")
    assert honest_result["ok"] is True
    assert honest_result["correct"] is False
    assert honest_result["manipulation"] is False
    assert "ошибся" in honest_result["text"]

    dispatch.distortion["motive_reveal"] = 1.0
    lie, lie_source = _fresh_report(campaign, faction)
    lie["manipulation"] = True
    lie["distortion"] = 1
    lie["motive"] = "выгода"
    lie["band"] = "excellent"
    lie["band_label"] = "образцово"
    lie["perceived"] = 0.95
    lie["true_value"] = 0.1
    lie_result = dispatch.resolve(lie["id"], "verify")
    assert lie_result["ok"] is True
    assert lie_result["correct"] is False
    assert lie_result["manipulation"] is True
    assert lie_result["motive_revealed"] is True
    assert lie_result["motive"] == "выгода"
    assert "подлог" in lie_result["text"]
    assert "выгода" in lie_result["text"]
    assert (
        dispatch._memory_for(lie_source.campaign_id)["last_outcome"]
        == "lied"
    )


def test_third_party_news_is_delayed_and_briefing_is_qualitative():
    campaign = _campaign()
    dispatch = campaign.dispatch
    dispatch.interval = 100.0
    dispatch._progress = 0.0

    spawned = dispatch.tick(100.0)

    news = [
        entry
        for entry in campaign.story_events
        if entry.get("category") == "news"
    ]
    assert news
    assert len(news) == len(
        [item for item in spawned if item["side"] != campaign.player_side]
    )
    assert all(entry["requires_choice"] is False for entry in news)
    assert all(entry["release_at"] > campaign.elapsed for entry in news)
    assert all(
        campaign.faction(entry["side"]) is not None for entry in news
    )

    briefing = campaign.staff_briefing(campaign.player_side)
    assert briefing["chief"]
    assert briefing["lines"]
    assert any(
        "доклад" in line.lower() or "«" in line
        for line in briefing["lines"]
    )
    for decision in campaign.pending_decisions(campaign.player_side):
        assert str(decision.get("side") or "") in (
            "",
            campaign.player_side,
        )


def test_ai_verify_does_not_spend_player_actions(monkeypatch):
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = _foreign(campaign)
    report = dispatch.issue(faction)
    assert report is not None
    monkeypatch.setattr(
        dispatch, "_ai_choice", lambda *_args, **_kwargs: "verify"
    )
    campaign.actions_left = 2

    result = dispatch.auto_resolve(report)

    assert result["ok"] is True
    assert result["choice"] == "verify"
    assert result["cost"] == 0
    assert campaign.actions_left == 2


def _intercept(campaign, delay=0.0, expire=100000.0):
    dispatch = campaign.dispatch
    dispatch.interception_enabled = True
    dispatch.interception_config.update(
        {
            "chance": 1.0,
            "influence_weight": 0.0,
            "delay_seconds": float(delay),
            "expire_seconds": float(expire),
            "max_pending": 6,
            "price_actions": 1,
        }
    )
    faction = _foreign(campaign)
    report = dispatch.issue(faction)
    assert report is not None
    dispatch.auto_resolve(report)
    items = campaign.interceptions(campaign.player_side)
    assert items
    return report, items[-1]


def test_foreign_report_is_intercepted_sealed_without_a_decision():
    campaign = _campaign()
    report, item = _intercept(campaign)

    assert item["kind"] == "intercept"
    assert item["side"] == campaign.player_side
    assert item["origin_side"] == report["side"]
    assert item["status"] == "sealed"
    assert item["text"] == report["text"]
    assert item["source_name"] == report["source_name"]
    assert item["available_at"] == item["created"]
    assert campaign.decision_pending(campaign.player_side) is False
    briefing = campaign.staff_briefing(campaign.player_side)
    assert any("перехвач" in line for line in briefing["lines"])


def test_open_intercept_reveals_decision_and_spends_player_action(
    monkeypatch,
):
    campaign = _campaign()
    _report, item = _intercept(campaign)
    spent = []
    monkeypatch.setattr(
        campaign,
        "_spend_player_action",
        lambda side: spent.append(str(side)),
    )

    result = campaign.open_intercept(item["id"])

    assert result["ok"] is True
    assert result["cost"] == 1
    assert spent == [campaign.player_side]
    assert item["status"] == "open"
    assert item["text"]
    assert item["choice"]
    assert item["choice_label"]
    assert item["decision_text"]
    assert campaign.open_intercept(item["id"])["ok"] is False


def test_open_intercept_waits_for_delivery_and_respects_gate(monkeypatch):
    campaign = _campaign()
    _report, item = _intercept(campaign, delay=3600.0)
    campaign.elapsed = item["created"] + 10.0

    early = campaign.open_intercept(item["id"])
    assert early["ok"] is False
    assert "пути" in early["reason"]

    campaign.elapsed = float(item["available_at"])
    monkeypatch.setattr(
        campaign, "_player_action_gate", lambda _side: "нет действий"
    )
    blocked = campaign.open_intercept(item["id"])
    assert blocked["ok"] is False
    assert "нет действий" in blocked["reason"]

    monkeypatch.setattr(
        campaign, "_player_action_gate", lambda _side: None
    )
    opened = campaign.open_intercept(item["id"])
    assert opened["ok"] is True


def test_intercepts_expire_and_snapshot_roundtrip():
    campaign = _campaign()
    _report, _item = _intercept(campaign, expire=10.0)
    snapshot = campaign.snapshot()

    loaded = _campaign()
    loaded.load_snapshot(snapshot)
    items = loaded.interceptions(loaded.player_side)
    assert len(items) == 1
    assert items[0]["report_id"] == _item["report_id"]
    assert items[0]["status"] == "sealed"

    loaded.elapsed = 100.0
    loaded.dispatch.tick(0.1)
    assert loaded.interceptions(loaded.player_side) == []
    assert loaded.dispatch.intercepts[0]["status"] == "expired"


def test_interception_can_be_disabled():
    campaign = _campaign()
    dispatch = campaign.dispatch
    dispatch.interception_enabled = False
    faction = _foreign(campaign)
    report = dispatch.issue(faction)
    assert report is not None
    dispatch.auto_resolve(report)

    assert campaign.interceptions(campaign.player_side) == []


def test_source_memory_is_separate_for_each_recipient():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = campaign.player
    report, source = _fresh_report(campaign, faction)
    dispatch.resolve(report["id"], "trust")
    recipient = report["recipient_id"]
    other = "other-leader"

    player_memory = dispatch._memory_for(
        source.campaign_id, recipient
    )
    assert player_memory["trusted"] == 1
    assert player_memory["ignored"] == 0

    foreign_report = dict(report, id="report-other", recipient_id=other)
    dispatch._remember(foreign_report, "ignore", False, "ignore")

    other_memory = dispatch._memory_for(source.campaign_id, other)
    assert other_memory["trusted"] == 0
    assert other_memory["ignored"] == 1
    assert dispatch._memory_for(source.campaign_id, recipient)[
        "trusted"
    ] == 1

    player_line, _delta = dispatch._memory_line(
        source.campaign_id, recipient
    )
    other_line, _delta = dispatch._memory_line(
        source.campaign_id, other
    )
    assert "доверились" in player_line
    assert "отложили" in other_line

    from campaign.automata import AutomataCampaign

    restored = AutomataCampaign(
        _preset(), seed=11, snapshot=campaign.snapshot()
    )
    assert restored.dispatch._memory_for(
        source.campaign_id, recipient
    )["trusted"] == 1
    assert restored.dispatch._memory_for(
        source.campaign_id, other
    )["ignored"] == 1


def test_legacy_shared_memory_remains_a_fallback():
    campaign = _campaign()
    dispatch = campaign.dispatch
    source_id = "char-legacy"
    memory = dispatch._new_memory()
    memory["last_outcome"] = "ignored"
    dispatch.memory[source_id] = memory

    line, delta = dispatch._memory_line(source_id, "new-leader")

    assert "отложили" in line
    assert delta < 0
    assert dispatch._memory_for(source_id, "new-leader") is memory


def test_ai_choice_uses_only_its_own_recipient_memory():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = _foreign(campaign)
    leader = dispatch._leader_for(faction)
    source = dispatch._source(faction, "supply")
    assert source is not None
    recipient = leader.campaign_id
    dispatch.ai_config.update(
        {
            "trust_base": 0.0,
            "trust_relation": 0.0,
            "trust_loyalty": 0.0,
            "trust_history": 1.0,
            "trust_fear": 0.0,
            "verify_base": 0.0,
            "verify_anxiety": 0.0,
            "verify_discipline": 0.0,
            "verify_distrust": 0.0,
            "verify_history": 0.0,
            "ignore_base": 0.0,
            "ignore_fear": 0.0,
            "ignore_distrust": 0.0,
            "ignore_loyalty": 0.0,
            "noise": 0.0,
        }
    )
    trusted = dispatch._memory_entry(source.campaign_id, recipient)
    trusted.update(
        {"reports": 4, "trusted": 4, "last_outcome": "trusted"}
    )
    report = {
        "side": faction.side,
        "source_id": source.campaign_id,
        "recipient_id": recipient,
    }
    assert dispatch._ai_choice(report, faction, leader) == "trust"

    ignored = dispatch._memory_entry(
        source.campaign_id, "other-leader"
    )
    ignored.update(
        {"reports": 4, "ignored": 4, "last_outcome": "ignored"}
    )
    assert dispatch._ai_choice(report, faction, leader) == "trust"

    other_report = dict(report, recipient_id="other-leader")
    assert dispatch._ai_choice(
        other_report, faction, leader
    ) != "trust"


def test_overdue_promise_weights_leader_work_and_atones_on_fulfil():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = campaign.player
    leader = dispatch._leader_for(faction)
    report, source = _fresh_report(campaign, faction)
    report["asks_promise"] = True
    report["request_line"] = "Прошу поддержки."
    dispatch.resolve(report["id"], "trust")
    obligation = campaign.obligations.get(report["promise_id"])
    assert obligation is not None

    probe = {
        "id": "probe_reassure",
        "label": "Поддержать",
        "ai_priority": 1.0,
        "template": {"form": "support"},
        "hints": {"essence": "reassure"},
        "chance": {"defense": "cohesion"},
    }
    baseline = campaign._ai_action_weight(faction.side, probe)

    campaign.turn = obligation.due_day + 1
    line, overdue = dispatch._promise_context(
        faction, source, report["asset"], report["true_value"]
    )
    assert overdue is True
    assert "просрочено" in line
    breaches = [
        belief
        for belief in leader.bdi.beliefs
        if belief.predicate == "has_broken_word"
    ]
    assert len(breaches) == 1
    assert breaches[0].subject == "player"
    boosted = campaign._ai_action_weight(faction.side, probe)
    assert boosted > baseline * 1.05

    dispatch._promise_context(
        faction, source, report["asset"], report["true_value"]
    )
    assert len(
        [
            belief
            for belief in leader.bdi.beliefs
            if belief.predicate == "has_broken_word"
        ]
    ) == 1

    reference = float(obligation.note.split(":")[3])
    dispatch._promise_context(
        faction, source, report["asset"], reference + 0.5
    )
    assert campaign.obligations.get(obligation.id).active() is False
    assert not any(
        belief.predicate == "has_broken_word"
        for belief in leader.bdi.beliefs
    )
    assert campaign._ai_action_weight(faction.side, probe) == baseline


def test_foreign_leader_broken_word_is_its_own_belief():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = _foreign(campaign)
    leader = dispatch._leader_for(faction)
    source = dispatch._source(faction, "supply")
    assert source is not None

    dispatch._penalize_promise(faction, source, leader, "supply")

    assert any(
        belief.predicate == "has_broken_word"
        and belief.subject == leader.campaign_id
        for belief in leader.bdi.beliefs
    )
    player_leader = dispatch._leader_for(campaign.player)
    assert not any(
        belief.predicate == "has_broken_word"
        for belief in player_leader.bdi.beliefs
    )


def _resolved_sample(campaign, faction, asset, created, value):
    report, _source = _fresh_report(campaign, faction, asset=asset)
    report["status"] = "resolved"
    report["choice"] = "trust"
    report["created"] = float(created)
    report["true_value"] = float(value)
    return report


def test_staff_briefing_shows_rising_asset_trend():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = campaign.player
    dispatch.briefing_config.update(
        {"trend_days": 20.0, "trend_min_samples": 2, "trend_step": 0.05}
    )
    campaign.elapsed = 10 * 86400.0
    for offset, value in (
        (8 * 86400.0, 0.2),
        (6 * 86400.0, 0.25),
        (2 * 86400.0, 0.75),
        (1 * 86400.0, 0.8),
    ):
        _resolved_sample(
            campaign, faction, "supply", campaign.elapsed - offset, value
        )

    lines = dispatch.briefing(faction.side)["lines"]

    assert any("прибывает" in line for line in lines)
    assert any("снабжение" in line for line in lines)
    assert not any("0.8" in line or "0,8" in line for line in lines)


def test_staff_briefing_shows_falling_asset_trend():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = campaign.player
    dispatch.briefing_config.update(
        {"trend_days": 20.0, "trend_min_samples": 2, "trend_step": 0.05}
    )
    campaign.elapsed = 10 * 86400.0
    for offset, value in (
        (8 * 86400.0, 0.85),
        (6 * 86400.0, 0.8),
        (2 * 86400.0, 0.2),
        (1 * 86400.0, 0.15),
    ):
        _resolved_sample(
            campaign, faction, "cohesion", campaign.elapsed - offset, value
        )

    lines = dispatch.briefing(faction.side)["lines"]

    assert any("проседает" in line for line in lines)


def test_staff_briefing_skips_thin_or_stale_trend_samples():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = campaign.player
    dispatch.briefing_config.update(
        {"trend_days": 5.0, "trend_min_samples": 2, "trend_step": 0.05}
    )
    campaign.elapsed = 20 * 86400.0
    _resolved_sample(campaign, faction, "supply", 0.0, 0.1)
    _resolved_sample(
        campaign, faction, "supply", campaign.elapsed - 86400.0, 0.9
    )

    lines = dispatch.briefing(faction.side)["lines"]

    assert not any("прибывает" in line for line in lines)
    assert not any("проседает" in line for line in lines)


def test_intercept_countermeasure_warns_leader_without_touching_assets(
    monkeypatch,
):
    campaign = _campaign()
    dispatch = campaign.dispatch
    _report, item = _intercept(campaign)
    assert campaign.open_intercept(item["id"])["ok"] is True
    leader = dispatch._leader_for(campaign.player)
    assets_before = {
        asset: campaign.faction(campaign.player_side).asset(asset)
        for asset in dispatch.assets
        if asset != "morale"
    }
    morale_before = leader.morale
    spent = []
    monkeypatch.setattr(
        campaign,
        "_spend_player_action",
        lambda side: spent.append(str(side)),
    )

    result = campaign.use_intercept(item["id"], "warn")

    assert result["ok"] is True
    assert result["cost"] == 1
    assert spent == [campaign.player_side]
    assert item["counter"] == "warn"
    assert item["counter_label"] == "Предупредить лидера"
    assert "предупреждён" in result["text"]
    assert any(
        belief.predicate == "sees_as_threat"
        and belief.subject == "player"
        and belief.object == item["faction_id"]
        for belief in leader.bdi.beliefs
    )
    assert leader.morale >= morale_before
    assert assets_before == {
        asset: campaign.faction(campaign.player_side).asset(asset)
        for asset in dispatch.assets
        if asset != "morale"
    }
    assert campaign.use_intercept(item["id"], "warn")["ok"] is False


def test_intercept_countermeasure_requires_open_and_motive():
    campaign = _campaign()
    _report, item = _intercept(campaign)

    sealed = campaign.use_intercept(item["id"], "warn")
    assert sealed["ok"] is False
    assert "вскройте" in sealed["reason"]

    assert campaign.open_intercept(item["id"])["ok"] is True
    options = {
        option["id"]: option
        for option in campaign.intercept_counters(item["id"])
    }
    assert options["warn"]["available"] is True
    assert options["expose"]["available"] is False
    blocked = campaign.use_intercept(item["id"], "expose")
    assert blocked["ok"] is False
    assert "мотив" in blocked["reason"]
    assert not item.get("counter")


def test_intercept_expose_shakes_enemy_trust_in_source():
    campaign = _campaign()
    dispatch = campaign.dispatch
    report, item = _intercept(campaign)
    campaign.open_intercept(item["id"])
    item["motive"] = "выгода"
    item["motive_revealed"] = True
    origin = campaign.faction(item["origin_side"])
    origin_leader = dispatch._leader_for(origin)

    result = campaign.use_intercept(item["id"], "expose")

    assert result["ok"] is True
    assert item["counter"] == "expose"
    assert any(
        belief.predicate == "feels_betrayed_by"
        and belief.object == report["source_id"]
        for belief in origin_leader.bdi.beliefs
    )


def test_used_intercept_counter_survives_snapshot():
    campaign = _campaign()
    _report, item = _intercept(campaign)
    campaign.open_intercept(item["id"])
    campaign.use_intercept(item["id"], "warn")
    snapshot = campaign.snapshot()

    from campaign.automata import AutomataCampaign

    restored = AutomataCampaign(_preset(), seed=11, snapshot=snapshot)
    loaded = restored.intercept(item["id"])

    assert loaded is not None
    assert loaded["counter"] == "warn"
    assert loaded["counter_label"] == "Предупредить лидера"
    assert restored.intercept_counters(item["id"]) == []


def test_intercept_countermeasure_needs_action_budget(monkeypatch):
    campaign = _campaign()
    _report, item = _intercept(campaign)
    campaign.open_intercept(item["id"])
    monkeypatch.setattr(
        campaign,
        "_player_action_gate",
        lambda _side: "нет действий",
    )

    result = campaign.use_intercept(item["id"], "warn")

    assert result["ok"] is False
    assert "нет действий" in result["reason"]
    assert not item.get("counter")
