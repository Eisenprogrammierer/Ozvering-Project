"""Тесты корпуса парафраз D6.2d.

Корпус — данные ``configs/dialogue/paraphrases.json``: фраза, ожидаемый
вид разбора и ключевые поля семантики. Тест не кодирует ответы в
Python, а сверяет детерминированный ``parse_best`` с JSON.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

import pytest

from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.parser import ChartParser

CORPUS = Path(__file__).resolve().parents[1] / (
    "configs/dialogue/paraphrases.json"
)
ENTRIES = json.loads(CORPUS.read_text(encoding="utf-8"))["phrases"]


def _lookup(sem: Any, path: str) -> Any:
    current = sem
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _rewrite_corpus(directory: Path, entries) -> None:
    path = directory / "paraphrases.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["phrases"] = entries
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DEFAULT_DIR)


def test_corpus_loaded_and_not_empty(catalog):
    assert catalog.paraphrases
    assert len(catalog.paraphrases["phrases"]) == len(ENTRIES)
    assert len(ENTRIES) >= 25


def test_corpus_lint_clean():
    problems = lint_directory(DEFAULT_DIR)
    relevant = [item for item in problems if "paraphrases" in item]
    assert relevant == []


@pytest.mark.parametrize(
    "entry", ENTRIES, ids=[item["id"] for item in ENTRIES]
)
def test_paraphrase_parses_as_expected(catalog, entry):
    parse = ChartParser(catalog).parse_best(entry["text"])
    assert parse is not None, entry["text"]
    assert parse.sem["kind"] == entry["kind"], entry["text"]
    for path, expected in (entry.get("expect") or {}).items():
        assert _lookup(parse.sem, path) == expected, (
            entry["text"],
            path,
        )


def test_paraphrase_parse_is_deterministic(catalog):
    parser = ChartParser(catalog)
    for entry in ENTRIES:
        first = parser.parse_best(entry["text"])
        second = parser.parse_best(entry["text"])
        assert first is not None and second is not None
        assert first.rule == second.rule
        assert first.sem == second.sem


def test_lint_catches_duplicate_text(tmp_path):
    directory = _copy_configs(tmp_path)
    entries = [dict(item) for item in ENTRIES]
    entries[1]["text"] = entries[0]["text"]
    _rewrite_corpus(directory, entries)
    problems = lint_directory(directory)
    assert any("paraphrases.phrases[1].text: повтор" in item
               for item in problems)


def test_lint_catches_unknown_kind(tmp_path):
    directory = _copy_configs(tmp_path)
    entries = [dict(item) for item in ENTRIES]
    entries[0]["kind"] = "nonsense"
    _rewrite_corpus(directory, entries)
    problems = lint_directory(directory)
    assert any("paraphrases.phrases[0].kind" in item for item in problems)


def test_lint_catches_empty_corpus(tmp_path):
    directory = _copy_configs(tmp_path)
    _rewrite_corpus(directory, [])
    problems = lint_directory(directory)
    assert any("paraphrases.phrases: ожидался" in item
               for item in problems)
