"""Контракт JSON Schema для контента (G-12).

Схемы ловят то, что семантический линтер не видит: опечатки во вложенных
полях эффектов, условий и автоматов, неверные типы и неизвестные ключи
органов/подфракций. Семантика (ссылки, предикаты, известные виды) остаётся
в ``campaign/content_lint.py``.
"""

from __future__ import annotations

import bdi
import pytest

from campaign import content_lint, content_schema

pytestmark = pytest.mark.skipif(
    not content_schema.available(),
    reason="нужен jsonschema (requirements-dev.txt)",
)


@pytest.fixture(scope="module")
def config():
    return bdi.load_bdi()


def test_schema_files_are_valid():
    assert content_schema.check_schema_files() == []


def test_schema_set_covers_core_contracts():
    assert set(content_schema.schema_names()) == {
        "effects",
        "conditions",
        "requires",
        "organ",
        "subfaction",
        "order",
        "automaton",
    }


def test_real_content_passes_schema_lint():
    assert content_lint.lint() == []


def test_linter_keys_come_from_schemas():
    assert content_lint.EFFECT_KEYS == content_schema.schema_keys("effects")
    assert content_lint.REQUIRE_KEYS == content_schema.schema_keys(
        "requires"
    )
    assert content_lint.CONDITION_KINDS == content_schema.condition_kinds()


def test_effects_reject_unknown_top_level_key():
    problems = content_lint.check_effects("x", {"belief": {}})
    assert any("неизвестное поле: belief" in item for item in problems)


def test_effects_reject_nested_typo():
    problems = content_lint.check_effects(
        "x",
        {"beliefs": {"add": [{"predicate": "trusts", "valeu": 1}]}},
    )
    assert any(
        "beliefs/add/0" in item and "valeu" in item for item in problems
    )


def test_effects_reject_wrong_value_type():
    problems = content_lint.check_effects(
        "x", {"assets": {"legitimacy": "много"}}
    )
    assert any("ожидался тип number" in item for item in problems)


def test_effects_allow_recursive_self_and_target():
    effect = {
        "self": {"assets": {"legitimacy": 0.1}},
        "target": {"needs": {"fear": -0.05}},
    }
    assert content_schema.validate("effects", effect) == []


def test_requires_reject_unknown_key():
    problems = content_lint.check_requires(
        "x", {"min_turn": 1, "valeu": 2}
    )
    assert any("неизвестное поле: valeu" in item for item in problems)


def test_requires_reject_typo_in_threshold():
    problems = content_lint.check_requires(
        "x", {"self": {"legitimacy": {"minimum": 0.3}}}
    )
    assert any(
        "self/legitimacy" in item and "minimum" in item
        for item in problems
    )


def test_conditions_reject_typo_in_automaton():
    automaton = {
        "schema": 2,
        "id": "test.condition",
        "kind": "faction",
        "initial": "a",
        "states": {
            "a": {
                "transitions": [
                    {
                        "to": "a",
                        "when": [
                            {
                                "kind": "asset",
                                "key": "legitimacy",
                                "op": ">=",
                                "value": 0.3,
                                "valeu": 1,
                            }
                        ],
                    }
                ]
            }
        },
    }
    problems = content_lint.check_automaton(automaton, "automaton")
    assert any(
        "when/0" in item and "valeu" in item for item in problems
    )


def test_conditions_allow_groups_and_lists():
    condition = {
        "all": [
            {"kind": "turn", "op": ">=", "value": 1},
            {"any": [{"kind": "flag", "key": "x", "value": True}]},
        ]
    }
    assert content_schema.validate("conditions", condition) == []
    assert content_schema.validate(
        "conditions", [{"kind": "turn", "op": ">=", "value": 1}]
    ) == []


def test_automaton_rejects_unknown_state_field():
    automaton = {
        "schema": 2,
        "id": "test.state",
        "kind": "faction",
        "initial": "a",
        "states": {"a": {"labl": "A"}},
    }
    problems = content_lint.check_automaton(automaton, "automaton")
    assert any("states/a" in item and "labl" in item for item in problems)


def test_automaton_rejects_unknown_transition_field():
    automaton = {
        "schema": 2,
        "id": "test.transition",
        "kind": "faction",
        "initial": "a",
        "states": {"a": {"transitions": [{"to": "a", "prio": 1}]}},
    }
    problems = content_lint.check_automaton(automaton, "automaton")
    assert any(
        "transitions/0" in item and "prio" in item for item in problems
    )


def test_organ_rejects_unknown_field(config):
    data = {
        "factions": {
            "red": {
                "id": "faction.red",
                "organs": [
                    {"id": "staff", "name": "Ставка", "link": ["x"]}
                ],
            }
        }
    }
    problems = content_lint.lint_factions_data(data, config)
    assert any("organs[0]" in item and "link" in item for item in problems)


def test_subfaction_rejects_unknown_field(config):
    data = {
        "factions": {
            "red": {
                "id": "faction.red",
                "organs": [{"id": "staff", "name": "Ставка"}],
                "subfactions": [{"id": "moderate", "shar": 0.5}],
            }
        }
    }
    problems = content_lint.lint_factions_data(data, config)
    assert any("shar" in item for item in problems)


def test_without_jsonschema_validation_is_skipped(monkeypatch):
    monkeypatch.setattr(content_schema, "available", lambda: False)
    assert content_schema.validate("effects", {"belief": {}}) == []
    assert content_schema.check_schema_files() == []
