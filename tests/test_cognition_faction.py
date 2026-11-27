"""Решения фракции: компилятор, Soar-рантайм и режимы.

Проверки держат два контракта: артефакт ``faction.soar`` совпадает с
JSON-источником, а Soar выбирает то же действие/приказ, что легаси-
рулетка при том же ``rng``. Теневой режим не меняет состояние кампании
и пишет согласие в монитор.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition import BackendError, SoarError
from campaign.cognition.faction_compiler import (
    FactionModel,
    check_policy,
    load_model,
    render_policy,
    write_policy,
)
from campaign.cognition.faction_runtime import (
    FactionDecisionMonitor,
    SoarFactionPolicy,
    faction_available,
    roulette_choice,
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


def _campaign(seed=13, backend="legacy", npc_enabled=False):
    campaign = AutomataCampaign(_preset(seed), seed=seed)
    campaign.ai_model["npc_policy"] = {
        "enabled": bool(npc_enabled),
        "backend": "legacy",
    }
    campaign._npc_policy_obj = None
    campaign.ai_model["faction_policy"] = {
        "enabled": True,
        "backend": backend,
    }
    return campaign


def test_compiler_artifact_is_fresh():
    model = load_model()
    text = render_policy(model)
    assert "source_digest" in text
    assert "faction*propose" in text
    assert "faction*apply" in text
    assert check_policy().digest() == model.digest()


def test_compiler_writes_and_detects_stale_artifact(tmp_path):
    source = tmp_path / "faction.json"
    source.write_text(
        (ROOT / "configs" / "soar" / "faction.json").read_text(
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
        FactionModel(version=99)
    with pytest.raises(SoarError):
        FactionModel(selection_policy="magic")
    with pytest.raises(SoarError):
        FactionModel(numeric_mode="magic")
    with pytest.raises(SoarError):
        FactionModel(tie_epsilon=-1.0)
    with pytest.raises(SoarError):
        FactionModel(decision_cycles=0)


def test_roulette_choice_matches_legacy_boundaries():
    candidates = [("a", 1.0), ("b", 2.0), ("c", 1.0)]
    assert roulette_choice(candidates, 0.0) == "a"
    assert roulette_choice(candidates, 0.24) == "a"
    assert roulette_choice(candidates, 0.26) == "b"
    assert roulette_choice(candidates, 0.74) == "b"
    assert roulette_choice(candidates, 0.76) == "c"
    assert roulette_choice(candidates, 0.999999) == "c"
    assert roulette_choice([], 0.5) is None
    assert roulette_choice([("a", 0.0), ("b", 0.0)], 0.5) == "b"


def test_roulette_choice_rejects_invalid_weights():
    with pytest.raises(BackendError):
        roulette_choice([("a", -1.0)], 0.5)
    with pytest.raises(BackendError):
        roulette_choice([("a", float("nan"))], 0.5)


def test_soar_matches_roulette_on_random_candidates():
    pytest.importorskip("soar_sml")
    policy = SoarFactionPolicy()
    rng = random.Random(7)
    try:
        for _trial in range(200):
            count = rng.randint(1, 8)
            candidates = [
                ("c%d" % index, round(rng.random() * 5.0, 6))
                for index in range(count)
            ]
            if not any(weight > 0.0 for _id, weight in candidates):
                candidates[0] = (candidates[0][0], 1.0)
            roll = rng.random()
            assert policy.choose(candidates, roll) == (
                roulette_choice(candidates, roll)
            )
    finally:
        policy.close()


def test_soar_zero_total_returns_last_without_agent():
    policy = SoarFactionPolicy()
    assert policy.choose([("a", 0.0), ("b", 0.0)], 0.5) == "b"


def test_soar_handles_zero_weight_prefix():
    pytest.importorskip("soar_sml")
    policy = SoarFactionPolicy()
    candidates = [("a", 0.0), ("b", 1.0), ("c", 0.0)]
    try:
        for roll in (0.0, 0.5, 0.999):
            assert policy.choose(candidates, roll) == (
                roulette_choice(candidates, roll)
            )
    finally:
        policy.close()


def test_monitor_merges_kinds_and_sides():
    monitor = FactionDecisionMonitor()
    monitor.record(
        kind="order",
        side="red",
        backend="shadow",
        legacy="hold",
        candidate="hold",
    )
    monitor.record(
        kind="action",
        side="red",
        backend="shadow",
        legacy="drill",
        candidate="patrol",
    )
    monitor.record(
        kind="action",
        side="blue",
        backend="shadow",
        legacy="trade",
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
    assert report["kinds"]["order"]["agreements"] == 1
    assert report["kinds"]["action"]["errors"] == 1
    assert report["sides"]["red"]["total"] == 2
    assert report["sides"]["red"]["agreement"] == 0.5


def test_faction_backend_uses_side_then_default_then_flag():
    campaign = _campaign()
    campaign._soar_available = lambda: True
    campaign.ai_model["faction_policy"] = {
        "enabled": True,
        "backend": "soar",
        "backends": {"red": "shadow"},
    }
    assert campaign.faction_backend("red") == "shadow"
    assert campaign.faction_backend("blue") == "soar"

    campaign.ai_model["faction_policy"] = {"enabled": True}
    campaign._cognition_flags = lambda: type(
        "Flags", (), {"ai_backend": "shadow"}
    )()
    assert campaign.faction_backend("blue") == "shadow"


def test_faction_backend_degrades_without_soar_package():
    campaign = _campaign()
    campaign._soar_available = lambda: False
    campaign.ai_model["faction_policy"] = {
        "enabled": True,
        "backend": "soar",
    }
    assert campaign.faction_backend("red") == "legacy"
    report = campaign.faction_decision_report()
    assert report["unavailable"] is True
    assert report["ok"] is False


def test_faction_backend_rejects_unknown_value():
    campaign = _campaign()
    campaign.ai_model["faction_policy"] = {
        "enabled": True,
        "backend": "magic",
    }
    with pytest.raises(BackendError):
        campaign.faction_backend("red")


def test_shadow_actions_and_orders_match_legacy():
    pytest.importorskip("soar_sml")
    legacy = _campaign(13, "legacy")
    shadow = _campaign(13, "shadow")
    legacy.run(turns=6)
    shadow.run(turns=6)
    assert shadow.snapshot() == legacy.snapshot()
    report = shadow.faction_decision_report()
    assert report["total"] > 0
    assert report["errors"] == 0
    assert report["agreement"] == 1.0
    assert report["ok"] is True
    assert set(report["kinds"]) == {"action", "order"}
    assert report["kinds"]["action"]["total"] > 0
    assert report["kinds"]["order"]["total"] > 0


def test_strict_soar_actions_and_orders_match_legacy():
    pytest.importorskip("soar_sml")
    legacy = _campaign(29, "legacy")
    soar = _campaign(29, "soar")
    legacy.run(turns=6)
    soar.run(turns=6)
    assert soar.snapshot() == legacy.snapshot()
    report = soar.faction_decision_report()
    assert report["total"] > 0
    assert report["evaluated"] == 0
    assert report["errors"] == 0
    assert report["ok"] is True


def test_shadow_without_soar_keeps_state_and_marks_unavailable():
    legacy = _campaign(17, "legacy")
    shadow = _campaign(17, "shadow")
    shadow._soar_available = lambda: False
    legacy.run(turns=4)
    shadow.run(turns=4)
    assert shadow.snapshot() == legacy.snapshot()
    report = shadow.faction_decision_report()
    assert report["unavailable"] is True
    assert report["total"] == 0
    assert report["ok"] is False


def test_faction_budget_falls_back_to_legacy():
    campaign = _campaign(17, "shadow")
    campaign._soar_available = lambda: True
    campaign.ai_model["faction_policy"] = {
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
    chosen = campaign.auto_action(side)
    assert chosen is not None
    report = campaign.faction_decision_report()
    assert report["errors"] >= 1
    assert report["ok"] is False


def test_facade_exports_faction_api():
    from campaign import cognition

    assert cognition.SoarFactionPolicy is SoarFactionPolicy
    assert cognition.FactionDecisionMonitor is FactionDecisionMonitor
    assert cognition.FactionModel is FactionModel
    assert callable(cognition.faction_available)
    assert callable(cognition.roulette_choice)
    assert cognition.load_faction_model().digest() == (
        load_model().digest()
    )
    assert cognition.check_faction().digest() == load_model().digest()


def test_faction_available_matches_package():
    pytest.importorskip("soar_sml")
    assert faction_available() is True
