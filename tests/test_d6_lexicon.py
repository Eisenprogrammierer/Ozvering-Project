"""Тесты D6.1: аудит ``lexicon.json``.

Проверяют, что псевдонимы не дублируют собственные формы лексемы,
линтер замечает такой дубль, а полезные псевдонимы (не совпадающие с
формами) остаются доступными.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from campaign.dialogue.lint import lint_catalog
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.model import LexForm

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalog():
    return load_dialogue(DEFAULT_DIR)


def test_lexicon_has_no_alias_form_duplicates(catalog):
    duplicated = []
    for entry in catalog.lexicon:
        forms = {form.text for form in entry.forms}
        for alias in entry.aliases:
            if alias.text in forms:
                duplicated.append((entry.id, alias.text))
    assert duplicated == []


def test_lint_flags_alias_form_duplicate(catalog):
    entry = next(item for item in catalog.lexicon if item.forms)
    duplicate = LexForm(entry.forms[0].text)
    changed = replace(entry, aliases=tuple(entry.aliases) + (duplicate,))
    broken = replace(
        catalog,
        lexicon=tuple(
            changed if item.id == entry.id else item
            for item in catalog.lexicon
        ),
    )
    problems = lint_catalog(broken)
    assert any("дублирует форму" in problem for problem in problems)


def test_redundant_affairs_alias_removed(catalog):
    entry = next(
        item for item in catalog.lexicon if item.id == "concept:affairs"
    )
    assert "дела" in {form.text for form in entry.forms}
    assert "дела" not in {alias.text for alias in entry.aliases}


def test_useful_alias_is_kept(catalog):
    entry = next(
        item for item in catalog.lexicon if item.id == "faction:red"
    )
    forms = {form.text for form in entry.forms}
    aliases = {alias.text for alias in entry.aliases}
    assert "имперцы" in aliases
    assert "имперцы" not in forms
