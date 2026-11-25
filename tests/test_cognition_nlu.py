"""Фасад понимания на legacy-сессии и решения NeedPolicy."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition import (
    BackendError,
    Clarification,
    LegacyNlu,
    Rejection,
    UtteranceFrame,
    compare,
    decide,
    record_corpus,
    register_nlu_backend,
    understand,
)
from campaign.dialogue import (
    DialogueSession,
    build_knowledge,
    load_dialogue,
)
from campaign.npc_policy import NeedPolicy
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
DIALOGUE_DIR = ROOT / "configs" / "dialogue"
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


@pytest.fixture(scope="module")
def red():
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    campaign = AutomataCampaign(generator.generate(seed=13), seed=13)
    catalog = load_dialogue(DIALOGUE_DIR)
    return DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
        style_hints=False,
    )


def test_order_becomes_typed_frame(red):
    result = understand("Обними его.", session=red)
    assert isinstance(result, UtteranceFrame)
    assert result.intent == "act"
    assert result.speech_act == "directive"
    assert result.predicate == "act_hug"
    assert result.args["patient"] == "he"
    assert result.slots["polarity"] == "positive"
    assert result.confidence >= 0.75
    assert result.evidence[0].startswith("parser:")


def test_question_keeps_entities_and_predicate(red):
    result = understand(
        "Почему Империя считает Республику незаконной?",
        session=red,
    )
    assert isinstance(result, UtteranceFrame)
    assert result.intent == "ask_reason"
    assert result.speech_act == "question"
    assert result.predicate == "believe"
    assert result.args["agent"] == "faction:red"
    assert result.args["patient"] == "faction:blue"
    assert result.args["theme"] == "illegal"
    assert "faction:red" in result.referents


def test_empty_input_is_rejection(red):
    result = understand("", session=red)
    assert isinstance(result, Rejection)
    assert result.reason == "empty"


def test_unknown_input_is_clarification_or_rejection(red):
    result = understand("абракадабра ксизи", session=red)
    assert isinstance(result, (Clarification, Rejection))


def test_understand_does_not_mutate_dialogue_state(red):
    before = red.state_snapshot()
    understand("Обними его.", session=red)
    understand("Почему Империя считает Республику незаконной?", session=red)
    assert red.state_snapshot() == before


def test_session_exposes_cognition_facade(red):
    result = red.understand("Обними его.")
    assert isinstance(result, UtteranceFrame)
    assert result.intent == "act"


def test_record_corpus_captures_expected_results(red):
    corpus = record_corpus(
        red,
        ("Обними его.", ""),
        seed=13,
        snapshot={"turn": 1},
        category="action",
    )
    assert len(corpus) == 2
    assert corpus.get("action-000").expected["intent"] == "act"
    assert corpus.get("action-000").expected["speech_act"] == "directive"
    assert corpus.get("action-001").expected["kind"] == "rejection"


def test_recorded_corpus_roundtrips_through_parity(red):
    corpus = record_corpus(
        red,
        (
            "Обними его.",
            "Почему Империя считает Республику незаконной?",
            "",
        ),
        seed=13,
        category="parity",
    )
    expected = {
        entry.id: entry.expected for entry in corpus.sorted_entries()
    }
    actual = {
        entry.id: understand(entry.input, session=red)
        for entry in corpus.sorted_entries()
    }
    report = compare(expected, actual)
    assert report.frame_exact == 1.0
    assert report.intent_accuracy == 1.0
    assert report.determinism_match is True
    assert report.mismatches == ()


def test_unavailable_backends_fail_loudly(red):
    with pytest.raises(BackendError):
        understand("Обними его.", session=red, nlu_backend="unknown")
    with pytest.raises(BackendError):
        register_nlu_backend("legacy", LegacyNlu)


def test_rive_backend_builds_action_frame(red):
    pytest.importorskip("rivescript")
    result = understand("Покажи силу", session=red, nlu_backend="rive")
    assert isinstance(result, UtteranceFrame)
    assert result.intent == "act"
    assert "rive:action:a:show_of_force:0" in result.evidence
    legacy = understand("Покажи силу", session=red, nlu_backend="legacy")
    assert result.core() == legacy.core()


def test_shadow_runs_rive_and_returns_legacy(red):
    pytest.importorskip("rivescript")
    seen = []
    result = understand(
        "Покажи силу",
        session=red,
        nlu_backend="shadow",
        shadow_sink=lambda text, value: seen.append((text, value)),
    )
    assert isinstance(result, UtteranceFrame)
    assert not any(item.startswith("rive:") for item in result.evidence)
    assert seen and seen[0][0] == "Покажи силу"
    assert isinstance(seen[0][1], UtteranceFrame)
    assert "rive:action:a:show_of_force:0" in seen[0][1].evidence
    assert seen[0][1].core() == result.core()


def test_rive_backend_is_read_only_and_deterministic(red):
    pytest.importorskip("rivescript")
    before = red.state_snapshot()
    first = understand("Покажи силу", session=red, nlu_backend="rive")
    second = understand("Покажи силу", session=red, nlu_backend="rive")
    assert first == second
    assert red.state_snapshot() == before


def test_rive_shadow_has_full_parity_on_dialogue_corpus(red):
    pytest.importorskip("rivescript")
    from campaign.cognition.nlu_lint import collect_phrases
    from campaign.cognition.rive_runtime import RiveNlu

    phrases = collect_phrases(DIALOGUE_DIR)
    engine = RiveNlu(red)
    legacy = {}
    candidate = {}
    for index, (identifier, text) in enumerate(phrases):
        key = "%s:%03d" % (identifier, index)
        legacy[key] = understand(
            text, session=red, nlu_backend="legacy"
        )
        candidate[key] = engine.understand(text)
    report = compare(legacy, candidate)
    assert report.total >= 80
    assert report.intent_accuracy == 1.0
    assert report.slot_f1 == 1.0
    assert report.frame_exact == 1.0
    assert report.fallback_rate == 0.0
    assert report.determinism_match is True


def test_decide_delegates_to_need_policy():
    policy = NeedPolicy(weights={"fear": 1.0})
    chosen = decide(
        policy=policy,
        candidates=[("comfort", "fear", 1.0), ("eat", "hunger", 1.0)],
        needs={"fear": 0.5, "hunger": 0.5},
    )
    assert chosen == "comfort"


def test_decide_rejects_missing_policy_and_unknown_backend():
    with pytest.raises(BackendError):
        decide(policy=None, candidates=[], needs={})
    with pytest.raises(BackendError):
        decide(
            policy=NeedPolicy(),
            candidates=[("a", "fear", 1.0)],
            needs={},
            ai_backend="nope",
        )
