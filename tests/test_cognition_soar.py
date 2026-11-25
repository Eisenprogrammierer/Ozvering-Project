"""Soar-политика NPC: компилятор, рантайм и parity с NeedPolicy."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from campaign.cognition import (
    BackendError,
    CognitionError,
    CognitionFlags,
    DecisionReport,
    SoarError,
    compare_choices,
    decide,
)
from campaign.cognition.soar_compiler import (
    DEFAULT_SOAR_DIR,
    DecisionModel,
    check_policy,
    compile_policy,
    load_model,
    model_from_dict,
    render_policy,
    soar_number,
    write_policy,
)
from campaign.npc_policy import NeedPolicy

ROOT = Path(__file__).resolve().parents[1]


def test_committed_policy_matches_json_source():
    model = check_policy()
    text, compiled = compile_policy()
    assert model.to_dict() == compiled.to_dict()
    assert compiled.digest() in text
    assert "sp {npc*propose" in text
    assert "sp {npc*apply" in text


def test_compile_is_deterministic():
    first, model = compile_policy()
    second, _ = compile_policy()
    assert first == second
    assert first == render_policy(model)


def test_numbers_have_no_exponent():
    assert soar_number(0.01) == "0.01"
    assert soar_number(1e-12) == "0.000000000001"
    assert soar_number(2.0) == "2"
    assert soar_number(0.0) == "0"


def test_production_blocks_are_extracted():
    from campaign.cognition.soar_runtime import production_blocks

    text, _ = compile_policy()
    blocks = production_blocks(text)
    assert len(blocks) == 2
    assert blocks[0].startswith("sp {npc*propose")
    assert blocks[1].startswith("sp {npc*apply")
    assert all(block.endswith("}") for block in blocks)
    with pytest.raises(SoarError):
        production_blocks("sp {broken\n (state <s> ^x y)")


def test_stale_and_missing_policy_are_reported(tmp_path):
    (tmp_path / "decision.json").write_text(
        (DEFAULT_SOAR_DIR / "decision.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    write_policy(tmp_path)
    check_policy(tmp_path)
    path = tmp_path / "npc_policy.soar"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n// stale\n",
        encoding="utf-8",
    )
    with pytest.raises(SoarError):
        check_policy(tmp_path)
    with pytest.raises(SoarError):
        check_policy(tmp_path / "missing")


def test_model_validation_rejects_bad_selection():
    with pytest.raises(SoarError):
        model_from_dict({"version": 1, "selection": {"policy": "random"}})
    with pytest.raises(SoarError):
        model_from_dict({"version": 1, "selection": {"epsilon": 2.0}})
    with pytest.raises(SoarError):
        model_from_dict(
            {"version": 1, "selection": {"decision_cycles": 0}}
        )
    with pytest.raises(SoarError):
        DecisionModel(version=99)


def test_model_commands_are_deterministic():
    model = load_model()
    assert model.selection_policy == "epsilon-greedy"
    assert model.epsilon == 0.0
    commands = model.commands()
    assert "decide indifferent-selection --epsilon-greedy" in commands
    assert "decide indifferent-selection --epsilon 0" in commands
    assert "decide numeric-indifferent-mode --sum" in commands


def test_compare_choices_reports_agreement():
    report = compare_choices(
        {"a": "one", "b": "two"},
        {"a": "one", "b": "three"},
    )
    assert isinstance(report, DecisionReport)
    assert report.total == 2
    assert report.agreements == 1
    assert report.agreement == 0.5
    assert report.ok(0.5) is True
    assert report.ok(0.95) is False
    assert "b: two != three" in report.render()
    assert report.to_dict()["mismatches"][0]["id"] == "b"
    with pytest.raises(CognitionError):
        compare_choices({}, {})


def _policy():
    return NeedPolicy(
        weights={"hunger": 1.0, "rest": -0.5, "fear": 0.25},
        seed=0,
    )


def _soar():
    pytest.importorskip("soar_sml")
    from campaign.cognition.soar_runtime import SoarNpcPolicy

    return SoarNpcPolicy()


def test_soar_matches_need_policy_on_random_candidates():
    soar = _soar()
    policy = _policy()
    rng = random.Random(11)
    weights = {
        need: policy.weight(need)
        for need in ("hunger", "rest", "fear", "love")
    }
    legacy = {}
    candidate = {}
    for trial in range(30):
        size = rng.randint(1, 6)
        items = [
            (
                "work%02d" % index,
                rng.choice(sorted(weights)),
                rng.uniform(0.1, 2.0),
            )
            for index in range(size)
        ]
        needs = {
            need: rng.uniform(0.0, 1.0) for need in weights
        }
        key = "%02d" % trial
        legacy[key] = policy.choose(items, needs)
        candidate[key] = soar.choose(items, needs, weights=weights)
    report = compare_choices(legacy, candidate)
    assert report.agreement == 1.0


def test_soar_reproduces_legacy_tie_break():
    soar = _soar()
    policy = NeedPolicy()
    items = [
        ("alpha", "hunger", 1.0),
        ("beta", "hunger", 1.0),
        ("gamma", "hunger", 1.0),
    ]
    needs = {"hunger": 0.5}
    for _ in range(3):
        assert soar.choose(items, needs) == policy.choose(items, needs)


def test_soar_is_read_only_and_empty_safe():
    soar = _soar()
    policy = _policy()
    before = dict(policy.weights)
    assert soar.choose([], {"hunger": 1.0}) is None
    soar.choose([("eat", "hunger", 1.0)], {"hunger": 0.9})
    assert policy.weights == before
    assert soar.last_elapsed_ms >= 0.0


def test_soar_is_deterministic_on_equal_scores():
    soar = _soar()
    items = [
        ("alpha", "hunger", 1.0),
        ("beta", "hunger", 1.0),
        ("gamma", "hunger", 1.0),
    ]
    needs = {"hunger": 0.5}
    first = soar.choose(items, needs)
    assert first == "gamma"
    assert [soar.choose(items, needs) for _ in range(10)] == [first] * 10


def test_soar_refuses_exploration():
    soar = _soar()
    with pytest.raises(BackendError):
        soar.choose(
            [("eat", "hunger", 1.0)],
            {"hunger": 0.9},
            explore=True,
        )


def test_soar_respects_decision_budget():
    pytest.importorskip("soar_sml")
    from campaign.cognition.soar_runtime import SoarNpcPolicy

    soar = SoarNpcPolicy(timeout_ms=0.000001)
    with pytest.raises(SoarError):
        soar.choose([("eat", "hunger", 1.0)], {"hunger": 0.9})


def test_decide_shadow_falls_back_when_budget_exceeded():
    _soar()
    policy = _policy()
    items = [("eat", "hunger", 1.0), ("rest", "rest", 1.5)]
    needs = {"hunger": 0.9, "rest": 0.1}
    seen = []
    result = decide(
        policy=policy,
        candidates=items,
        needs=needs,
        ai_backend="shadow",
        flags=CognitionFlags(decision_timeout_ms=0.000001),
        shadow_sink=lambda primary, shadow: seen.append(
            (primary, shadow)
        ),
    )
    assert result == policy.choose(items, needs)
    assert seen == [(result, None)]


def test_missing_policy_artifact_is_reported(tmp_path):
    pytest.importorskip("soar_sml")
    from campaign.cognition.soar_runtime import SoarNpcPolicy

    (tmp_path / "decision.json").write_text(
        (DEFAULT_SOAR_DIR / "decision.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    with pytest.raises(BackendError):
        SoarNpcPolicy(source_dir=tmp_path)


def test_decide_legacy_requires_choose():
    with pytest.raises(BackendError):
        decide(policy=None, candidates=[], needs={}, ai_backend="legacy")


def test_decide_soar_matches_legacy():
    _soar()
    policy = _policy()
    items = [("eat", "hunger", 1.0), ("rest", "rest", 1.5)]
    needs = {"hunger": 0.9, "rest": 0.1}
    assert decide(
        policy=policy,
        candidates=items,
        needs=needs,
        ai_backend="soar",
    ) == policy.choose(items, needs)


def test_decide_shadow_returns_legacy_and_reports():
    _soar()
    policy = _policy()
    items = [("eat", "hunger", 1.0), ("rest", "rest", 1.5)]
    needs = {"hunger": 0.9, "rest": 0.1}
    seen = []
    result = decide(
        policy=policy,
        candidates=items,
        needs=needs,
        ai_backend="shadow",
        shadow_sink=lambda primary, shadow: seen.append((primary, shadow)),
    )
    assert result == policy.choose(items, needs)
    assert seen and seen[0][0] == result
    assert seen[0][1] == result


def test_shadow_never_breaks_without_soar(monkeypatch):
    from campaign.cognition import soar_runtime

    class Broken:
        def __init__(self, *args, **kwargs):
            raise BackendError("нет Soar")

    monkeypatch.setattr(soar_runtime, "SoarNpcPolicy", Broken)
    policy = _policy()
    items = [("eat", "hunger", 1.0)]
    seen = []
    result = decide(
        policy=policy,
        candidates=items,
        needs={"hunger": 0.9},
        ai_backend="shadow",
        shadow_sink=lambda primary, shadow: seen.append((primary, shadow)),
    )
    assert result == "eat"
    assert seen == [("eat", None)]


def test_soar_matches_policy_on_real_campaign_choices():
    _soar()
    from campaign.automata import AutomataCampaign
    from campaign.cognition.soar_runtime import SoarNpcPolicy, weights_for
    from campaign.preset import CampaignPresetGenerator
    from campaign.roles import RoleCatalog

    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    )
    campaign = AutomataCampaign(generator.generate(seed=13), seed=13)
    campaign.ai_model["npc_policy"] = {"enabled": True}
    campaign._npc_policy_obj = None
    policy = campaign._npc_policy()
    soar = SoarNpcPolicy()
    checked = 0
    for side in campaign.factions:
        leader = campaign._leader(side)
        needs = dict(getattr(leader, "needs", {}) or {})
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
        if not items:
            continue
        weights = weights_for(policy, sorted({need for _, need, _ in items}))
        assert soar.choose(items, needs, weights=weights) == policy.choose(
            items, needs
        )
        checked += 1
    assert checked > 0
