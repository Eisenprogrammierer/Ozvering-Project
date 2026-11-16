"""Тесты F-13: проекция каталога действий в реестр диалога."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from campaign.dialogue.bridge import ActionBridge
from campaign.dialogue.lint import lint_catalog
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.parser import ChartParser
from campaign.dialogue.projection import (
    action_aliases,
    action_phrase,
    action_phrases,
    merge_actions,
    projected_registry,
    project_actions,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DEFAULT_DIR)


def test_projection_adds_world_actions_to_manual_registry(catalog):
    registry, problems, overrides = projected_registry(
        manual=catalog.actions
    )
    assert problems == []
    assert overrides == []
    ids = [entry["id"] for entry in registry["actions"]]
    assert len(ids) == len(set(ids))
    for action_id in (
        "show_of_force",
        "calm_crowd",
        "hug",
        "kiss",
        "teach_lesson",
        "ask_favor",
    ):
        assert action_id in ids


def test_projection_keeps_manual_entry_as_override(catalog):
    manual = {
        "actions": [
            {
                "id": "hug",
                "label": "Ручное объятие",
                "aliases": ["act_hug"],
                "phrases": ["Обними его"],
            }
        ]
    }
    registry, problems, overrides = projected_registry(
        manual=manual
    )
    assert problems == []
    entry = next(
        item for item in registry["actions"] if item["id"] == "hug"
    )
    assert entry["label"] == "Ручное объятие"
    assert {"id": "hug", "reason": "manual"} in overrides


def test_projection_deduplicates_phrase_across_actions():
    sources = [
        (
            "first",
            {
                "actions": [
                    {
                        "id": "hug",
                        "label": "Обнять",
                        "aliases": ["act_hug"],
                        "phrases": ["Обними его"],
                        "form": "care",
                        "target": {"kinds": ["character"]},
                        "effects": {"target": {"trust": 0.1}},
                    }
                ]
            },
        ),
        (
            "second",
            {
                "actions": [
                    {
                        "id": "embrace",
                        "label": "Обнять",
                        "aliases": ["act_embrace"],
                        "phrases": ["Обними его"],
                        "form": "contact",
                        "target": {"kinds": ["character"]},
                        "effects": {"target": {"trust": 0.1}},
                    }
                ]
            },
        ),
    ]
    entries, problems = project_actions(sources)
    assert problems == []
    assert entries[0]["phrases"] == ["Обними его"]
    assert "phrases" not in entries[1]


def test_manual_phrase_wins_over_projection():
    projected = [
        {
            "id": "hug",
            "label": "Обнять",
            "aliases": ["act_hug"],
            "phrases": ["Обними его"],
        }
    ]
    merged, overrides = merge_actions(
        {
            "actions": [
                {
                    "id": "care",
                    "label": "Забота",
                    "aliases": ["act_hug"],
                    "phrases": ["Обними его"],
                }
            ]
        },
        projected,
    )
    assert overrides == []
    assert merged[0]["id"] == "care"
    assert "phrases" not in merged[1]


def test_merged_registry_passes_dialogue_lint(catalog):
    registry, problems, _ = projected_registry(
        manual=catalog.actions, forms=None
    )
    assert problems == []
    merged = replace(catalog, actions=registry)
    assert lint_catalog(merged) == []


def test_every_projected_phrase_parses_to_its_action(catalog):
    registry, problems, _ = projected_registry(
        manual=catalog.actions
    )
    assert problems == []
    merged = replace(catalog, actions=registry)
    parser = ChartParser(merged)
    bridge = ActionBridge(merged)
    for entry in registry["actions"]:
        for phrase in entry.get("phrases") or ():
            parse = parser.parse_best(phrase)
            assert parse is not None, phrase
            intent = bridge.intent(parse.sem, phrase=phrase)
            assert intent is not None, phrase
            assert intent.action_id == entry["id"], phrase
            assert bridge.resolve(intent.action_id) == entry["id"]


def test_projection_alias_resolves_through_bridge(catalog):
    registry, _, _ = projected_registry(manual=catalog.actions)
    merged = replace(catalog, actions=registry)
    bridge = ActionBridge(merged)
    assert bridge.resolve("act_kiss") == "kiss"
    assert bridge.resolve("act_teach_lesson") == "teach_lesson"
    assert bridge.resolve("kiss") == "kiss"


def test_action_helpers_use_explicit_data_only():
    action = {"id": "hug", "label": "Обнять"}
    assert action_aliases(action) == ("hug",)
    assert action_phrases(action) == ()
    assert action_phrase(action) == "Обнять"
    rich = {
        "id": "hug",
        "label": "Обнять",
        "aliases": ["act_hug"],
        "phrases": ["Обними его"],
    }
    assert action_aliases(rich) == ("act_hug",)
    assert action_phrases(rich) == ("Обними его",)
    assert action_phrase(rich) == "Обними его"


def test_projection_is_opt_in_but_loadable(catalog):
    assert "hug" not in {
        entry["id"] for entry in catalog.actions["actions"]
    }
    projected = load_dialogue(DEFAULT_DIR, project=True)
    ids = {entry["id"] for entry in projected.actions["actions"]}
    assert "hug" in ids
    assert "show_of_force" in ids
    assert lint_catalog(projected) == []


def test_projection_reports_bad_action_without_crashing():
    entries, problems = project_actions(
        [("bad", {"actions": [{"id": "Bad Id", "label": "Плохо"}]})]
    )
    assert entries == []
    assert problems and "bad" in problems[0]
