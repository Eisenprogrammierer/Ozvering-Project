"""Контракт линтера контента.

Линтер — часть Data-Driven ядра: он делает ошибки данных громкими.
Тесты проверяют, что рабочий контент проходит, а неизвестные ссылки,
предикаты, эффекты и «производящие» события отклоняются.
"""

from __future__ import annotations

import bdi
import pytest

from campaign import content_lint


@pytest.fixture(scope="module")
def config():
    return bdi.load_bdi()


def test_real_content_passes_lint():
    assert content_lint.lint() == []


def test_world_lint_catches_unknown_scene_work():
    from campaign.world import load_world

    world = load_world()
    world = dict(world)
    world["scenes"] = list(world["scenes"]) + [
        {
            "id": "broken",
            "location": world["nodes"][0]["id"],
            "works": ["no_such_work"],
        }
    ]
    problems = content_lint.lint_world_data(world)
    assert any("неизвестные работы сцены" in item for item in problems)


def test_storyline_lint_catches_missing_refs(tmp_path):
    path = tmp_path / "mini.json"
    data = {
        "storyline_id": "other",
        "storyline_tags": ["free", "free"],
        "world_path": "missing_world.json",
        "scenes": "missing_scenes",
    }
    problems = content_lint.lint_storylines_data(path, data)
    assert any("storyline_id" in item for item in problems)
    assert any("storyline_tags повторяются" in item for item in problems)
    assert any("world_path" in item for item in problems)
    assert any("scenes: файл не найден" in item for item in problems)


def test_unknown_predicate_is_reported(config):
    problems = content_lint.check_beliefs(
        "actor",
        [{"subject": "faction.a", "predicate": "nope", "object": "x"}],
        config,
    )
    assert any("неизвестный предикат" in item for item in problems)


def test_relation_requires_object(config):
    problems = content_lint.check_beliefs(
        "actor",
        [{"subject": "faction.a", "predicate": "trusts"}],
        config,
    )
    assert any("требует object" in item for item in problems)


def test_property_forbids_object(config):
    problems = content_lint.check_beliefs(
        "actor",
        [
            {
                "subject": "faction.a",
                "predicate": "is_legitimate",
                "object": "faction.a",
            }
        ],
        config,
    )
    assert any("не имеет object" in item for item in problems)


def test_property_without_object_passes(config):
    problems = content_lint.check_beliefs(
        "actor",
        [{"subject": "faction.a", "predicate": "is_legitimate"}],
        config,
    )
    assert problems == []


def test_unknown_intention_essence_is_reported(config):
    problems = content_lint.check_intentions(
        "actor",
        [{"target": "faction.a", "essence": "nope"}],
        config,
    )
    assert any("неизвестная суть" in item for item in problems)


def test_archetypes_lint_reports_unknown_needs_and_traits(config):
    data = {
        "schema": 1,
        "archetypes": [
            {
                "id": "test",
                "label": "Тест",
                "needs": {"nope": 0.1},
                "priority_needs": ["also_nope"],
                "traits": {"nope": 0.1},
                "identity_sections": ["values"],
            }
        ],
    }
    problems = content_lint.lint_archetypes_data(data, config)
    assert any("неизвестная потребность" in item for item in problems)
    assert any("неизвестная черта" in item for item in problems)


def test_archetypes_lint_reports_unknown_identity_section():
    problems = content_lint.lint_archetypes_data(
        {
            "schema": 1,
            "archetypes": [
                {
                    "id": "test",
                    "label": "Тест",
                    "identity_sections": ["nope"],
                }
            ],
        }
    )
    assert any("identity_sections" in item for item in problems)


def test_archetypes_lint_reports_invalid_catalog():
    problems = content_lint.lint_archetypes_data(
        {"schema": 1, "archetypes": [{"label": "Без id"}]}
    )
    assert any("пустой id" in item for item in problems)


def test_forms_manifest_requires_handler_and_addresses():
    problems = content_lint.lint_forms_data(
        {
            "forms": [
                {
                    "id": "missing_form",
                    "payload_kinds": ["info"],
                    "target_kinds": ["character"],
                }
            ]
        }
    )
    assert any("нет обработчика" in item for item in problems)


def test_action_catalog_reports_unknown_form():
    problems = content_lint.lint_actions_data(
        {
            "actions": [
                {
                    "id": "calm",
                    "form": "nope",
                    "target": {"kinds": ["place"]},
                    "effects": {},
                }
            ]
        },
        forms=content_lint.FormCatalog.load(),
    )
    assert any("неизвестная форма" in item for item in problems)


def test_unimplemented_effect_is_reported():
    problems = content_lint.check_effects(
        "work", {"self": {"legitimacy": 0.1}, "relations": {}}
    )
    assert any("не поддерживается ядром" in item for item in problems)


def test_event_must_not_have_effects():
    problems = content_lint.check_events(
        "events",
        [
            {
                "id": "coup",
                "text": "Переворот",
                "effects": {"self": {"legitimacy": -0.2}},
            }
        ],
    )
    assert any("не может менять состояние" in item for item in problems)


def test_faction_links_and_actions_are_checked(config):
    data = {
        "factions": {
            "red": {
                "id": "faction.a",
                "organs": [{"id": "staff", "links": ["missing"]}],
                "actions": [
                    {
                        "id": "work",
                        "organ_id": "nope",
                        "effects": {"self": {"legitimacy": 0.1}},
                    }
                ],
                "character_defaults": {
                    "beliefs": [
                        {
                            "subject": "faction.a",
                            "predicate": "nope",
                            "object": "x",
                        }
                    ],
                    "intentions": [
                        {"target": "faction.b", "essence": "nope"}
                    ],
                },
                "posts": [],
            }
        }
    }
    problems = content_lint.lint_factions_data(data, config)
    assert any("неизвестный орган" in item for item in problems)
    assert any("неизвестный предикат" in item for item in problems)
    assert any("неизвестная суть" in item for item in problems)


def test_defaults_require_labels_and_formulas():
    defaults = {
        "asset_labels": {"legitimacy": "законность"},
        "faction_state": {"assets": {"legitimacy": []}},
    }
    factions = {
        "factions": {
            "red": {"assets": {"legitimacy": 0.5, "myth": 0.4}}
        }
    }
    problems = content_lint.check_defaults(defaults, factions)
    assert any("asset_labels" in item and "myth" in item for item in problems)
    assert any(
        "faction_state.assets" in item and "myth" in item
        for item in problems
    )


def test_automaton_targets_and_effects_are_checked():
    broken = {
        "schema": 2,
        "id": "test.broken",
        "kind": "faction",
        "initial": "a",
        "states": {
            "a": {"transitions": [{"to": "missing"}]},
        },
    }
    problems = content_lint.check_automaton(broken, "automaton")
    assert any("ведёт в никуда" in item for item in problems)

    invalid = {
        "schema": 2,
        "id": "test.invalid",
        "kind": "organ",
        "initial": "a",
        "states": {
            "a": {
                "on_enter": [{"relations": {}}],
                "transitions": [
                    {"to": "b", "when": [{"kind": "nope"}]}
                ],
            },
            "b": {},
        },
    }
    problems = content_lint.check_automaton(invalid, "automaton")
    assert any("не поддерживается ядром" in item for item in problems)
    assert any("неизвестный вид условия" in item for item in problems)


def test_automaton_schema_is_checked():
    problems = content_lint.check_automaton(
        {
            "schema": 1,
            "id": "test.old",
            "kind": "faction",
            "initial": "a",
            "states": {"a": {}},
        },
        "automaton",
    )
    assert any("ожидалась 2" in item for item in problems)
