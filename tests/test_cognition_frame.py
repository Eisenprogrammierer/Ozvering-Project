"""Схема кадра и детерминированная уверенность."""

from __future__ import annotations

import pytest

from campaign.cognition import (
    Clarification,
    FrameError,
    Rejection,
    UtteranceFrame,
    frame_confidence,
)


def _frame(**overrides):
    data = {
        "id": "u-1",
        "text": "Обними его.",
        "intent": "act",
        "speech_act": "directive",
        "predicate": "act_hug",
        "args": {"patient": "he"},
        "slots": {"polarity": "positive"},
        "referents": (),
        "confidence": 0.9,
        "evidence": ("parser:s_imperative_v_np",),
        "unknowns": (),
        "tokens": ({"surface": "обними"}, {"surface": "его"}),
    }
    data.update(overrides)
    return UtteranceFrame(**data)


def test_frame_roundtrip_is_stable():
    frame = _frame()
    data = frame.to_dict()
    assert UtteranceFrame.from_dict(data) == frame
    assert frame.core()["intent"] == "act"
    assert frame.core()["kind"] == "frame"
    assert data["tokens"] == [
        {"surface": "обними"},
        {"surface": "его"},
    ]


def test_frame_rejects_bad_schema():
    with pytest.raises(FrameError):
        _frame(intent="")
    with pytest.raises(FrameError):
        _frame(confidence=1.5)
    with pytest.raises(FrameError):
        _frame(speech_act="shout")
    with pytest.raises(FrameError):
        _frame(tokens=({"lemma": "обнять"},))
    with pytest.raises(FrameError):
        UtteranceFrame.from_dict(
            {
                "id": "u-1",
                "text": "x",
                "intent": "act",
                "unknown": True,
            }
        )
    with pytest.raises(FrameError):
        UtteranceFrame.from_dict(
            {
                "id": "u-1",
                "text": "x",
                "intent": "act",
                "version": 999,
            }
        )


def test_confidence_formula_and_clamp():
    assert frame_confidence(1, 1, 1, 0) == 1.0
    assert frame_confidence(0, 0, 0, 0) == 0.0
    assert frame_confidence(1, 1, 1, 1) == 0.8
    assert frame_confidence(2, 5, 5, -3) == 1.0
    assert frame_confidence("bad", None, 0, 0) == 0.0


def test_clarification_and_rejection_have_stable_core():
    clarify = Clarification(
        id="u-2",
        text="О ком ты?",
        reason="ambiguous",
        options=("faction:red", "faction:blue"),
    )
    reject = Rejection(id="u-3", text="", reason="empty")
    assert clarify.core() == {
        "kind": "clarification",
        "reason": "ambiguous",
        "options": ["faction:red", "faction:blue"],
    }
    assert reject.core() == {"kind": "rejection", "reason": "empty"}


def test_clarification_and_rejection_reject_bad_values():
    with pytest.raises(FrameError):
        Clarification(id="", text="", reason="ambiguous")
    with pytest.raises(FrameError):
        Clarification(id="u", text="", reason="")
    with pytest.raises(FrameError):
        Clarification(
            id="u", text="", reason="ambiguous", options="faction:red"
        )
    with pytest.raises(FrameError):
        Clarification(
            id="u", text="", reason="ambiguous", confidence=2.0
        )
    with pytest.raises(FrameError):
        Rejection(id="", text="", reason="empty")
    with pytest.raises(FrameError):
        Rejection(id="u", text="", reason="")
    with pytest.raises(FrameError):
        Rejection(id="u", text="", reason="empty", version=999)
