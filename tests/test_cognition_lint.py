"""Линтер покрытия NLU и отчёт по неизвестной лексике."""

from __future__ import annotations

import json
from pathlib import Path

from campaign.cognition.nlu_lint import (
    collect_phrases,
    known_tokens,
    lint_dialogue,
    main,
)

ROOT = Path(__file__).resolve().parents[1]
DIALOGUE = ROOT / "configs" / "dialogue"


def _write(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )


def _minimal_dialogue(root: Path, text: str = "Ксизи") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "lexicon.json", {"entries": []})
    _write(
        root / "paraphrases.json",
        {"phrases": [{"id": "x", "text": text}]},
    )
    _write(root / "actions.json", {"actions": [], "markers": []})
    _write(root / "grammar.json", {"rules": []})
    return root


def test_current_dialogue_has_full_lexicon_coverage():
    report = lint_dialogue()
    assert report.phrases >= 80
    assert report.unknown == ()
    assert report.ok()
    assert "0 неизвестных" in report.render()
    assert report.stats["grammar_triggers"] > 0
    assert (
        report.stats["grammar_rules_covered"]
        + report.stats["grammar_rules_skipped"]
        == report.stats["grammar_rules"]
    )
    assert "грамматика:" in report.render()


def test_unknown_token_is_reported_with_phrase_id(tmp_path):
    root = _minimal_dialogue(tmp_path)
    report = lint_dialogue(root)
    assert report.unknown == (("ксизи", ("x",)),)
    assert report.ok() is False
    assert "ксизи" in report.render()


def test_strict_mode_fails_on_unknown(tmp_path):
    root = _minimal_dialogue(tmp_path)
    assert main(["--dialogue-dir", str(root)]) == 0
    assert main(["--strict", "--dialogue-dir", str(root)]) == 1


def test_collect_phrases_covers_actions_and_markers():
    phrases = collect_phrases(DIALOGUE)
    identifiers = {identifier for identifier, _ in phrases}
    assert "show_of_force" in identifiers
    assert "marker:command" in identifiers


def test_known_tokens_reads_forms_and_aliases():
    entries = [
        {
            "lemma": "империя",
            "forms": {"nom": ["Империя"], "ins": ["Империей"]},
            "aliases": ["имперцы"],
        }
    ]
    tokens = known_tokens(entries)
    assert {"империя", "империей", "имперцы"} <= tokens
