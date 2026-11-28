"""Реакции на доклад/угрозу: компилятор, Soar-рантайм и режимы.

Проверки держат два контракта: артефакт ``reaction.soar`` совпадает с
JSON-источником, а Soar выбирает ту же реакцию, что легаси-argmax при
тех же оценках. Теневой режим не меняет состояние кампании и пишет
согласие в монитор.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition import BackendError, SoarError
from campaign.cognition.reaction_compiler import (
    ReactionModel,
    check_policy,
    load_model,
    render_policy,
    write_policy,
)
from campaign.cognition.reaction_runtime import (
    ReactionDecisionMonitor,
    SoarReactionPolicy,
    reaction_available,
    reaction_choice,
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


def _campaign(seed=13, backend="legacy"):
    campaign = AutomataCampaign(_preset(seed), seed=seed)
    campaign.ai_model["reaction_policy"] = {
        "enabled": True,
        "backend": backend,
    }
    return campaign


def _foreign(campaign):
    for side, faction in campaign.factions.items():
        if side != campaign.player_side:
            return faction
    raise AssertionError("нет чужой фракции")


def _resolve_reports(campaign, faction, count=8):
    for _index in range(count):
        report = campaign.dispatch.issue(faction)
        if report is None:
            break
        campaign.dispatch.auto_resolve(report)


def test_compiler_artifact_is_fresh():
    model = load_model()
    text = render_policy(model)
    assert "source_digest" in text
    assert "reaction*propose" in text
    assert "reaction*apply" in text
    assert check_policy().digest() == model.digest()


def test_compiler_writes_and_detects_stale_artifact(tmp_path):
    source = tmp_path / "reaction.json"
    source.write_text(
        (ROOT / "configs" / "soar" / "reaction.json").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    target = write_policy(tmp_path)
    assert target.exists()
    assert check_policy(tmp_path).digest() == load_model().digest()
    target.write_text(target.read_text(encoding="utf-8") + "\n// stale\n")
    with pytest.raises(SoarError):
        check_policy(tmp_path)


def test_compiler_rejects_bad_model():
    with pytest.raises(SoarError):
        ReactionModel(version=99)
    with pytest.raises(SoarError):
        ReactionModel(selection_policy="magic")
    with pytest.raises(SoarError):
        ReactionModel(numeric_mode="magic")
    with pytest.raises(SoarError):
        ReactionModel(tie_epsilon=-1.0)
    with pytest.raises(SoarError):
        ReactionModel(decision_cycles=0)


def test_reaction_choice_matches_legacy_argmax():
    assert reaction_choice(
        [("trust", 0.5), ("verify", 0.4), ("ignore", 0.1)]
    ) == "trust"
    assert reaction_choice(
        [("trust", 0.5), ("verify", 0.5), ("ignore", 0.5)]
    ) == "verify"
    assert reaction_choice(
        [("trust", -1.0), ("verify", -2.0), ("ignore", -0.5)]
    ) == "ignore"
    assert reaction_choice([]) is None


def test_reaction_choice_rejects_invalid_scores():
    with pytest.raises(BackendError):
        reaction_choice([("trust", float("nan"))])
    with pytest.raises(BackendError):
        reaction_choice([("trust", float("inf"))])
    with pytest.raises(BackendError):
        reaction_choice([("trust", 1.0), ("trust", 2.0)])
    with pytest.raises(BackendError):
        reaction_choice([("trust",)])


def test_soar_matches_legacy_argmax_on_random_scores():
    pytest.importorskip("soar_sml")
    policy = SoarReactionPolicy()
    rng = random.Random(11)
    try:
        for _trial in range(200):
            count = rng.randint(1, 3)
            candidates = [
                ("c%d" % index, round(rng.uniform(-2.0, 2.0), 3))
                for index in range(count)
            ]
            assert policy.choose(candidates) == reaction_choice(
                candidates
            )
    finally:
        policy.close()


def test_soar_matches_legacy_on_exact_ties():
    pytest.importorskip("soar_sml")
    policy = SoarReactionPolicy()
    candidates = [
        ("ignore", 0.25),
        ("trust", 0.25),
        ("verify", 0.25),
    ]
    try:
        assert policy.choose(candidates) == "verify"
        assert policy.choose(list(reversed(candidates))) == "verify"
    finally:
        policy.close()


def test_monitor_merges_kinds_and_sides():
    monitor = ReactionDecisionMonitor()
    monitor.record(
        kind="report",
        side="red",
        backend="shadow",
        legacy="trust",
        candidate="trust",
    )
    monitor.record(
        kind="threat",
        side="red",
        backend="shadow",
        legacy="verify",
        candidate="ignore",
    )
    monitor.record(
        kind="threat",
        side="blue",
        backend="shadow",
        legacy="ignore",
        candidate=None,
        error="timeout",
    )
    report = monitor.report()
    assert report["kind"] == "reaction_decisions"
    assert report["total"] == 3
    assert report["evaluated"] == 2
    assert report["agreements"] == 1
    assert report["agreement"] == 0.5
    assert report["errors"] == 1
    assert report["ok"] is False
    assert report["kinds"]["report"]["agreements"] == 1
    assert report["kinds"]["threat"]["errors"] == 1
    assert report["sides"]["red"]["total"] == 2
    assert report["sides"]["red"]["agreement"] == 0.5


def test_reaction_backend_uses_side_then_default_then_flag():
    campaign = _campaign()
    campaign._soar_available = lambda: True
    campaign.ai_model["reaction_policy"] = {
        "enabled": True,
        "backend": "soar",
        "backends": {"red": "shadow"},
    }
    assert campaign.reaction_backend("red") == "shadow"
    assert campaign.reaction_backend("blue") == "soar"

    campaign.ai_model["reaction_policy"] = {"enabled": True}
    campaign._cognition_flags = lambda: type(
        "Flags", (), {"ai_backend": "shadow"}
    )()
    assert campaign.reaction_backend("blue") == "shadow"


def test_reaction_backend_degrades_without_soar_package():
    campaign = _campaign()
    campaign._soar_available = lambda: False
    campaign.ai_model["reaction_policy"] = {
        "enabled": True,
        "backend": "soar",
    }
    assert campaign.reaction_backend("red") == "legacy"
    report = campaign.reaction_decision_report()
    assert report["unavailable"] is True
    assert report["ok"] is False


def test_reaction_backend_rejects_unknown_value():
    campaign = _campaign()
    campaign.ai_model["reaction_policy"] = {
        "enabled": True,
        "backend": "magic",
    }
    with pytest.raises(BackendError):
        campaign.reaction_backend("red")


def test_reaction_kind_splits_threat_bands():
    campaign = _campaign()
    dispatch = campaign.dispatch
    assert dispatch._reaction_kind({"band": "critical"}) == "threat"
    assert dispatch._reaction_kind({"band": "stable"}) == "report"
    dispatch.threat_enabled = False
    assert dispatch._reaction_kind({"band": "critical"}) == "report"


def test_dispatcher_uses_campaign_report_select():
    campaign = _campaign()
    dispatch = campaign.dispatch
    faction = _foreign(campaign)
    leader = dispatch._leader_for(faction)
    source = dispatch._source(faction, "supply")
    assert source is not None
    calls = []

    def _select(**kwargs):
        calls.append(kwargs)
        return "ignore"

    campaign._report_select = _select
    report = {
        "side": faction.side,
        "source_id": source.campaign_id,
        "recipient_id": leader.campaign_id,
        "band": "critical",
    }
    assert dispatch._ai_choice(report, faction, leader) == "ignore"
    assert calls and calls[0]["kind"] == "threat"
    assert calls[0]["side"] == faction.side
    assert [item[0] for item in calls[0]["candidates"]] == [
        "trust",
        "verify",
        "ignore",
    ]


def test_shadow_with_noise_consumes_same_rng():
    pytest.importorskip("soar_sml")
    legacy = _campaign(23, "legacy")
    shadow = _campaign(23, "shadow")
    for campaign in (legacy, shadow):
        campaign.dispatch.ai_config["noise"] = 0.4
    legacy_faction = _foreign(legacy)
    shadow_faction = _foreign(shadow)
    legacy_source = legacy.dispatch._source(
        legacy_faction, "supply"
    )
    shadow_source = shadow.dispatch._source(
        shadow_faction, "supply"
    )
    assert legacy_source is not None and shadow_source is not None
    legacy_leader = legacy.dispatch._leader_for(legacy_faction)
    shadow_leader = shadow.dispatch._leader_for(shadow_faction)
    legacy_report = {
        "side": legacy_faction.side,
        "source_id": legacy_source.campaign_id,
        "recipient_id": legacy_leader.campaign_id,
        "band": "critical",
    }
    shadow_report = {
        "side": shadow_faction.side,
        "source_id": shadow_source.campaign_id,
        "recipient_id": shadow_leader.campaign_id,
        "band": "critical",
    }
    for _index in range(20):
        assert legacy.dispatch._ai_choice(
            legacy_report, legacy_faction, legacy_leader
        ) == shadow.dispatch._ai_choice(
            shadow_report, shadow_faction, shadow_leader
        )
    assert legacy.dispatch.rng.getstate() == (
        shadow.dispatch.rng.getstate()
    )
    report = shadow.reaction_decision_report()
    assert report["errors"] == 0
    assert report["agreement"] == 1.0
    assert report["kinds"]["threat"]["total"] == 20


def test_shadow_reports_match_legacy():
    pytest.importorskip("soar_sml")
    for seed in (13, 17, 29):
        legacy = _campaign(seed, "legacy")
        shadow = _campaign(seed, "shadow")
        _resolve_reports(legacy, _foreign(legacy))
        _resolve_reports(shadow, _foreign(shadow))
        assert shadow.snapshot() == legacy.snapshot()
        report = shadow.reaction_decision_report()
        assert report["total"] > 0
        assert report["errors"] == 0
        assert report["agreement"] == 1.0
        assert report["ok"] is True


def test_strict_soar_reports_match_legacy():
    pytest.importorskip("soar_sml")
    for seed in (13, 17):
        legacy = _campaign(seed, "legacy")
        soar = _campaign(seed, "soar")
        _resolve_reports(legacy, _foreign(legacy))
        _resolve_reports(soar, _foreign(soar))
        assert soar.snapshot() == legacy.snapshot()
        report = soar.reaction_decision_report()
        assert report["total"] > 0
        assert report["evaluated"] == 0
        assert report["errors"] == 0
        assert report["ok"] is True


def test_shadow_without_soar_keeps_state_and_marks_unavailable():
    legacy = _campaign(17, "legacy")
    shadow = _campaign(17, "shadow")
    shadow._soar_available = lambda: False
    _resolve_reports(legacy, _foreign(legacy))
    _resolve_reports(shadow, _foreign(shadow))
    assert shadow.snapshot() == legacy.snapshot()
    report = shadow.reaction_decision_report()
    assert report["unavailable"] is True
    assert report["total"] == 0
    assert report["ok"] is False


def test_reaction_budget_falls_back_to_legacy():
    campaign = _campaign(17, "shadow")
    campaign._soar_available = lambda: True
    campaign.ai_model["reaction_policy"] = {
        "enabled": True,
        "backend": "shadow",
        "tick_timeout_ms": 1,
    }
    campaign.begin_turn()
    campaign._npc_tick_spent_ms = 1.0
    side = next(
        item for item in campaign.factions
        if item != campaign.player_side
    )
    chosen = campaign._report_select(
        side=side,
        kind="report",
        candidates=[("trust", 0.6), ("verify", 0.3), ("ignore", 0.1)],
    )
    assert chosen == "trust"
    report = campaign.reaction_decision_report()
    assert report["errors"] >= 1
    assert report["ok"] is False


def test_npc_outcome_report_includes_reactions():
    campaign = _campaign()
    report = campaign.npc_outcome_report()
    assert "reactions" in report
    assert report["reactions"]["kind"] == "reaction_decisions"
    assert report["ok"] is True


def test_facade_exports_reaction_api():
    from campaign import cognition

    assert cognition.SoarReactionPolicy is SoarReactionPolicy
    assert cognition.ReactionDecisionMonitor is ReactionDecisionMonitor
    assert cognition.ReactionModel is ReactionModel
    assert callable(cognition.reaction_available)
    assert callable(cognition.reaction_choice)
    assert cognition.load_reaction_model().digest() == (
        load_model().digest()
    )
    assert cognition.check_reaction().digest() == load_model().digest()


def test_reaction_available_matches_package():
    pytest.importorskip("soar_sml")
    assert reaction_available() is True
