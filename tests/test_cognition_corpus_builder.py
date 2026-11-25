"""Золотой корпус диалога: сборка, проверка устаревания и parity."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition import GoldenCorpus, compare
from campaign.cognition.corpus import CorpusEntry
from campaign.cognition.corpus_builder import (
    DEFAULT_CORPUS_PATH,
    build_corpus,
    check_corpus,
    dialogue_variants,
    main,
)
from campaign.cognition.errors import CorpusError
from campaign.cognition.nlu_lint import collect_phrases
from campaign.dialogue import (
    DialogueSession,
    build_knowledge,
    load_dialogue,
)
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


def test_committed_corpus_matches_current_dialogue(red):
    corpus = GoldenCorpus.load(DEFAULT_CORPUS_PATH)
    assert len(corpus) == 144
    check_corpus(red, corpus, dialogue_variants(collect_phrases()))


def test_main_check_mode_is_green():
    assert main(["--check"]) == 0


def test_variants_cover_case_punctuation_and_spaces():
    variants = dialogue_variants([("greeting", "Привет.")])
    assert variants == (
        ("greeting", "Привет."),
        ("greeting:upper", "ПРИВЕТ."),
        ("greeting:bang", "Привет!"),
        ("greeting:space", "  Привет.  "),
    )


def test_variants_limit_extra_copies():
    phrases = [("id%02d" % i, "Фраза %d." % i) for i in range(30)]
    variants = dialogue_variants(phrases)
    assert len(variants) == 30 + 20 * 3


def test_build_is_deterministic(red):
    phrases = [("x", "Привет."), ("y", "Покажи силу")]
    first = build_corpus(red, phrases)
    second = build_corpus(red, phrases)
    assert first.digest() == second.digest()
    assert first.sorted_entries()[0].id == "000:x"


def test_stale_corpus_is_rejected(red):
    phrases = [("x", "Привет.")]
    corpus = build_corpus(red, phrases)
    with pytest.raises(CorpusError):
        check_corpus(red, corpus, phrases + [("y", "Покажи силу")])
    with pytest.raises(CorpusError):
        check_corpus(red, corpus, [("x", "Покажи силу")])


def test_changed_frame_is_rejected(red):
    phrases = [("x", "Привет.")]
    corpus = build_corpus(red, phrases)
    entry = corpus.sorted_entries()[0]
    broken = GoldenCorpus()
    broken.add(
        CorpusEntry(
            id=entry.id,
            seed=entry.seed,
            snapshot=entry.snapshot,
            input=entry.input,
            topic=entry.topic,
            category=entry.category,
            expected=dict(entry.expected, intent="farewell"),
        )
    )
    with pytest.raises(CorpusError):
        check_corpus(red, broken, phrases)


def test_rive_matches_golden_corpus(red):
    pytest.importorskip("rivescript")
    from campaign.cognition.rive_runtime import RiveNlu

    corpus = GoldenCorpus.load(DEFAULT_CORPUS_PATH)
    engine = RiveNlu(red)
    legacy = {}
    candidate = {}
    for entry in corpus:
        legacy[entry.id] = entry.expected
        candidate[entry.id] = engine.understand(entry.input).to_dict()
    report = compare(legacy, candidate)
    assert report.total == len(corpus)
    assert report.intent_accuracy == 1.0
    assert report.slot_f1 == 1.0
    assert report.frame_exact == 1.0
    assert report.fallback_rate == 0.0
    assert report.determinism_match is True
