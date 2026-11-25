"""Parity-метрики NLU."""

from __future__ import annotations

import pytest

from campaign.cognition import (
    Clarification,
    CognitionError,
    Rejection,
    UtteranceFrame,
    compare,
)


def _frame(intent="act", slots=None, args=None):
    return UtteranceFrame(
        id="u-1",
        text="Обними его.",
        intent=intent,
        speech_act="directive",
        predicate="act_hug",
        args=args or {"patient": "he"},
        slots=slots or {"polarity": "positive"},
        confidence=0.9,
        tokens=({"surface": "обними"},),
    )


def test_identical_runs_have_perfect_parity():
    report = compare({"a": _frame()}, {"a": _frame()})
    assert report.total == 1
    assert report.intent_accuracy == 1.0
    assert report.slot_f1 == 1.0
    assert report.frame_exact == 1.0
    assert report.determinism_match is True
    assert report.mismatches == ()


def test_slot_difference_lowers_f1_but_keeps_intent():
    report = compare(
        {"a": _frame(slots={"polarity": "positive"})},
        {"a": _frame(slots={"polarity": "negative"})},
    )
    assert report.intent_accuracy == 1.0
    assert report.frame_exact == 0.0
    assert report.slot_f1 == 0.0


def test_clarification_and_rejection_are_counted():
    report = compare(
        {"a": _frame(), "b": _frame(), "c": _frame()},
        {
            "a": _frame(),
            "b": Clarification(
                id="u-2", text="?", reason="ambiguous"
            ),
            "c": Rejection(id="u-3", text="", reason="empty"),
        },
    )
    assert report.total == 3
    assert report.clarification_rate == pytest.approx(1 / 3)
    assert report.fallback_rate == pytest.approx(1 / 3)
    assert report.intent_accuracy == pytest.approx(1 / 3)


def test_missing_ids_and_bad_values_are_reported():
    report = compare({"a": _frame()}, {})
    assert report.total == 1
    assert report.mismatches[0]["candidate"] == "missing"
    with pytest.raises(CognitionError):
        compare({}, {})
    with pytest.raises(CognitionError):
        compare({"a": object()}, {"a": object()})
