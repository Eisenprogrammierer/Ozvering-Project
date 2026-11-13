"""Тесты D5.2: автовыбор регистра по контексту разговора.

Проверяют, что правила ``style_context.json`` выбирают регистр по
фактам и полям ``AgentKnowledge``, что явный выбор игрока побеждает
правила, что пустой каталог отключает автовыбор, а линтер ловит
битые ссылки. Мир и BDI не меняются.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.dialogue.engine import DialogueSession
from campaign.dialogue.knowledge import AgentKnowledge, Fact
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.style import StyleEngine


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _catalog(directory: Path):
    return load_dialogue(directory)


def _knowledge(
    catalog,
    *,
    side="red",
    speaker_id="char_red",
    player_id="char_player",
    player_side="red",
    faction_id="faction:red",
    player_faction="faction:red",
    facts=(),
):
    return AgentKnowledge(
        catalog,
        facts=tuple(facts),
        entities={},
        side=side,
        faction_id=faction_id,
        speaker_id=speaker_id,
        speaker_name="Император",
        world=catalog.world,
        player_id=player_id,
        player_name="Игрок",
        player_side=player_side,
        player_faction=player_faction,
    )


def _session(catalog, knowledge, style_id=None):
    return DialogueSession(
        catalog,
        knowledge,
        persona_id=None,
        memory=None,
        style_id=style_id,
    )


# --- загрузка ------------------------------------------------------


def test_style_context_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    assert catalog.style_context.enabled
    assert catalog.style_context.rules
    ids = {rule.id for rule in catalog.style_context.rules}
    assert "enemy_hostile" in ids
    assert "same_faction_friendly" in ids


def test_style_context_ordered_by_priority(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    rules = catalog.style_context.ordered()
    priorities = [rule.priority for rule in rules]
    assert priorities == sorted(priorities, reverse=True)


def test_lint_style_context_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    context_problems = [
        item for item in problems if "style_context" in item.lower()
    ]
    assert context_problems == []


# --- автовыбор -----------------------------------------------------


def test_auto_war_is_hostile(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[
            Fact("at_war_with", ("faction:blue", "faction:red")),
        ],
    )
    session = _session(catalog, knowledge)
    assert session.is_auto()
    assert session.style_id == "hostile"


def test_auto_same_faction_is_friendly(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog,
        side="red",
        speaker_id="char_red",
        faction_id="faction:red",
        player_side="red",
        player_faction="faction:red",
    )
    session = _session(catalog, knowledge)
    assert session.style_id == "friendly"


def test_auto_superior_is_report(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[
            Fact("has_authority", ("char_player", "char_blue")),
        ],
    )
    session = _session(catalog, knowledge)
    assert session.style_id == "report"


def test_auto_subordinate_is_order(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[
            Fact("has_authority", ("char_blue", "char_player")),
        ],
    )
    session = _session(catalog, knowledge)
    assert session.style_id == "order"


def test_auto_ally_is_friendly(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[
            Fact(
                "allied_with",
                ("faction:blue", "faction:red"),
            ),
        ],
    )
    session = _session(catalog, knowledge)
    assert session.style_id == "friendly"


def test_auto_falls_back_to_default(tmp_path):
    """Ни одно правило не сработало — стиль по умолчанию."""

    directory = _copy_configs(tmp_path)
    path = directory / "style_context.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"] = []
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    knowledge = _knowledge(catalog)
    session = _session(catalog, knowledge)
    assert session.style_id == catalog.styles.default


# --- явный выбор побеждает ----------------------------------------


def test_explicit_style_wins_over_rules(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[
            Fact("at_war_with", ("faction:blue", "faction:red")),
        ],
    )
    session = _session(catalog, knowledge, style_id="mentor")
    assert not session.is_auto()
    assert session.style_id == "mentor"


def test_set_style_none_returns_to_auto(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[
            Fact("at_war_with", ("faction:blue", "faction:red")),
        ],
    )
    session = _session(catalog, knowledge, style_id="mentor")
    assert session.style_id == "mentor"
    result = session.set_style(None)
    assert result == "hostile"
    assert session.is_auto()


def test_set_style_unknown_keeps_auto(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(catalog)
    session = _session(catalog, knowledge, style_id="mentor")
    result = session.set_style("nope")
    assert session.is_auto()
    assert result == session.style_id


# --- пустой каталог ------------------------------------------------


def test_missing_style_context_is_ok(tmp_path):
    directory = _copy_configs(tmp_path)
    (directory / "style_context.json").unlink()
    catalog = _catalog(directory)
    assert not catalog.style_context.rules
    assert not catalog.style_context.enabled
    knowledge = _knowledge(catalog)
    session = _session(catalog, knowledge)
    assert session.style_id == catalog.styles.default


# --- линтер --------------------------------------------------------


def test_lint_catches_unknown_style(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "style_context.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"][0]["style"] = "nonexistent"
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "style_context" in item and "nonexistent" in item
        for item in problems
    )


def test_lint_catches_unknown_relation(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "style_context.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"][0]["when"] = [
        {
            "kind": "fact",
            "rel": "nope_relation",
            "args": ["$speaker_faction", "$player_faction"],
        }
    ]
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "style_context" in item and "nope_relation" in item
        for item in problems
    )


def test_lint_catches_unknown_field(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "style_context.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"].append(
        {
            "id": "broken",
            "style": "friendly",
            "priority": 1,
            "when": [
                {
                    "kind": "field",
                    "field": "nonexistent_field",
                    "op": "eq",
                    "value": "x",
                }
            ],
        }
    )
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "style_context" in item and "nonexistent_field" in item
        for item in problems
    )


def test_lint_catches_unknown_operator(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "style_context.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"].append(
        {
            "id": "broken_op",
            "style": "friendly",
            "priority": 1,
            "when": [
                {
                    "kind": "field",
                    "field": "player_id",
                    "op": "nope_op",
                    "value": "x",
                }
            ],
        }
    )
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "style_context" in item and "nope_op" in item
        for item in problems
    )


# --- JSON-only расширение -----------------------------------------


def test_new_rule_json_only(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "style_context.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"].insert(
        0,
        {
            "id": "romantic_private",
            "style": "romantic",
            "priority": 200,
            "when": [
                {
                    "kind": "fact",
                    "rel": "trusts",
                    "args": ["$speaker_id", "$player_id"],
                }
            ],
        },
    )
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    knowledge = _knowledge(
        catalog,
        facts=[Fact("trusts", ("char_red", "char_player"))],
    )
    session = _session(catalog, knowledge)
    assert session.style_id == "romantic"


def test_determinism_two_runs(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[
            Fact("at_war_with", ("faction:blue", "faction:red")),
        ],
    )
    first = _session(catalog, knowledge).style_id
    second = _session(catalog, knowledge).style_id
    assert first == second