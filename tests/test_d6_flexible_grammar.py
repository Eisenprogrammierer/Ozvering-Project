"""Тесты F-12: лексикон и грамматика гибких действий."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.dialogue.bridge import ActionBridge
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.parser import ChartParser

ROOT = Path(__file__).resolve().parents[1]

CASES = {
    "Поцелуй меня.": "kiss",
    "Обними его.": "hug",
    "Принеси жертву.": "offer_sacrifice",
    "Прими закон.": "accept_law",
    "Сыграй на улице.": "perform_song",
    "Научи меня.": "teach_lesson",
    "Успокой улицу.": "calm_crowd",
    "Сошлись на норму.": "cite_law",
}


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DEFAULT_DIR, project=True)


def test_ontology_covers_contact_ritual_law_and_family():
    data = json.loads(
        (DEFAULT_DIR / "ontology.json").read_text(encoding="utf-8")
    )
    types = set(data["entity_types"])
    assert {
        "norm",
        "rite",
        "gift",
        "body_contact",
        "family",
        "romance",
    } <= types


@pytest.mark.parametrize("phrase,expected", CASES.items())
def test_dod_phrases_reach_action(catalog, phrase, expected):
    parser = ChartParser(catalog)
    bridge = ActionBridge(catalog)
    parse = parser.parse_best(phrase)
    assert parse is not None, phrase
    intent = bridge.intent(parse.sem, phrase=phrase)
    assert intent is not None, phrase
    assert intent.action_id == expected, phrase
    assert bridge.resolve(intent.action_id) == expected


def test_action_verbs_are_projected(catalog):
    ids = {entry["id"] for entry in catalog.actions["actions"]}
    assert {
        "kiss",
        "hug",
        "offer_sacrifice",
        "accept_law",
        "perform_song",
        "teach_lesson",
        "calm_crowd",
        "cite_law",
    } <= ids


def test_lint_rejects_action_verb_without_registry(tmp_path):
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    path = target / "lexicon.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"].append(
        {
            "id": "verb:missing_action",
            "type": "verb",
            "cat": "V",
            "lemma": "мечтать",
            "forms": ["мечтать"],
            "semantic": {"kind": "predicate", "id": "act_missing_action"},
        }
    )
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(target)
    assert any(
        "act_missing_action" in item and "actions.json" in item
        for item in problems
    )


def test_lint_rejects_social_verb_without_grammar(tmp_path):
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    social_path = target / "social.json"
    social = json.loads(social_path.read_text(encoding="utf-8"))
    social["acts"]["dream"] = {
        "id": "dream",
        "label": "мечтание",
        "match": {"kind": "social", "act": "dream"},
        "proposition": {"object": "$object"},
        "validity": [],
        "interaction": "social_offer",
        "taboo": [],
        "reactions": ["accept", "clarify"],
    }
    social_path.write_text(
        json.dumps(social, ensure_ascii=False), encoding="utf-8"
    )
    lex_path = target / "lexicon.json"
    lexicon = json.loads(lex_path.read_text(encoding="utf-8"))
    lexicon["entries"].append(
        {
            "id": "verb:dream",
            "type": "verb",
            "cat": "V",
            "lemma": "мечтать",
            "forms": ["мечтать"],
            "semantic": {"kind": "predicate", "id": "dream"},
        }
    )
    lex_path.write_text(
        json.dumps(lexicon, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(target)
    assert any(
        "речевой акт 'dream'" in item and "грамматик" in item
        for item in problems
    )
