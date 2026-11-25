"""Золотой корпус NLU: версия, порядок и хеш."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from campaign.cognition import (
    CORPUS_VERSION,
    CorpusEntry,
    CorpusError,
    GoldenCorpus,
)


def _entry(entry_id: str, text: str = "Обними его."):
    return CorpusEntry(
        id=entry_id,
        seed=13,
        snapshot={"turn": 4, "location": "agora"},
        input=text,
        topic="default",
        category="action",
        expected={"kind": "frame", "intent": "act"},
    )


def test_corpus_save_load_and_digest(tmp_path: Path):
    corpus = GoldenCorpus()
    corpus.add(_entry("b"))
    corpus.add(_entry("a", "Утешь его."))
    assert [item.id for item in corpus] == ["a", "b"]
    path = corpus.save(tmp_path / "corpus.json")
    loaded = GoldenCorpus.load(path)
    assert loaded.to_dict() == corpus.to_dict()
    assert loaded.digest() == corpus.digest()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == CORPUS_VERSION
    assert [item["id"] for item in data["entries"]] == ["a", "b"]


def test_duplicate_and_future_version_are_rejected():
    corpus = GoldenCorpus()
    corpus.add(_entry("a"))
    with pytest.raises(CorpusError):
        corpus.add(_entry("a"))
    corpus.add(_entry("a"), replace=True)
    with pytest.raises(CorpusError):
        GoldenCorpus(version=99)


def test_entry_rejects_unknown_fields_and_bad_types():
    with pytest.raises(CorpusError):
        CorpusEntry.from_dict({"id": "a", "seed": 1, "unknown": True})
    with pytest.raises(CorpusError):
        CorpusEntry.from_dict({"id": "", "seed": 1})
    with pytest.raises(CorpusError):
        CorpusEntry.from_dict({"id": "a", "seed": "bad"})
