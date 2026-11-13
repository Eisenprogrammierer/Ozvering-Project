"""Тесты D5.3: агрегация, анафора и порядок тема-рема.

Проверяют, что связки с ``mode: "clause"`` склеивают ходы в одно
сложное предложение, что анафора внутри ответа заменяет повтор имени
первого хода на местоимение по роду/числу, что ``topic`` меняет
порядок ходов, и что всё это задаётся в ``discourse.json`` без правки
Python.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.dialogue.answers import Answer, AnswerPlanner
from campaign.dialogue.knowledge import (
    AgentKnowledge,
    EntityInfo,
    Fact,
)
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.style import StyleEngine


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _catalog(directory: Path):
    return load_dialogue(directory)


def _entities(catalog) -> dict:
    """Все сущности лексикона — как в реальной сессии.

    ``build_knowledge`` заполняет ``entities`` из ``catalog.lexicon``
    через ``_nominal(entry)`` (номинативная форма), а не через
    ``entry.lemma``. Тест воспроизводит это же поведение, иначе
    регистр в ``knowledge.name`` не совпадёт с регистром в тексте.
    """

    result = {}
    for entry in catalog.lexicon:
        name = entry.lemma
        for form in entry.forms:
            if form.features.get("case") == "nom":
                name = form.text
                break
        result[entry.id] = EntityInfo(
            id=entry.id,
            type=entry.type,
            name=name,
        )
    return result


def _knowledge(catalog, facts=()):
    return AgentKnowledge(
        catalog,
        facts=tuple(facts),
        entities=_entities(catalog),
        side="red",
        faction_id="faction:red",
        speaker_id="char_red",
        speaker_name="Император",
        world=catalog.world,
        player_id="char_player",
        player_name="Игрок",
    )


def _persona(catalog):
    return catalog.personas.get("default") or list(
        catalog.personas.values()
    )[0]


def _planner(catalog, style_id="official", facts=()):
    knowledge = _knowledge(catalog, facts)
    style_engine = StyleEngine(catalog)
    style = style_engine.profile(style_id)
    planner = AnswerPlanner(
        catalog, knowledge, _persona(catalog), style_engine=style_engine
    )
    planner.set_style(style)
    return planner


def _answer_with_reason(left="faction:red", right="faction:blue"):
    return Answer(
        "explanation",
        "Империя сильна. Республика слаба.",
        "p1",
        data={
            "reason": "эдикт объявил её мятежом",
            "reason_args": (left, right),
            "args": (left, right),
            "target": left,
        },
    )


# --- загрузка ------------------------------------------------------


def test_anaphora_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    assert catalog.discourse.anaphora.enabled
    assert "faction" in catalog.discourse.anaphora.types
    assert "justify" in catalog.discourse.anaphora.kinds
    assert catalog.discourse.anaphora.pronouns.get("f:sg")


def test_lint_anaphora_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    anaphora_problems = [
        item for item in problems if "anaphora" in item.lower()
    ]
    assert anaphora_problems == []


# --- mode: clause --------------------------------------------------


def test_clause_mode_joins_in_one_sentence(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for connective in data["connectives"].values():
        connective["mode"] = "clause"
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    planner = _planner(catalog, style_id="official")
    answer = _answer_with_reason()
    result = planner._discourse(answer)
    # Одно предложение: внутри нет «. » между ходами
    assert result.text.count(".") <= 2
    assert ", " in result.text
    trace = (result.data or {}).get("discourse_trace") or ()
    connective_trace = [
        item for item in trace if item.get("kind") == "connective"
    ]
    assert connective_trace
    assert connective_trace[0]["mode"] == "clause"


def test_plain_mode_keeps_two_sentences(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for connective in data["connectives"].values():
        connective["mode"] = "plain"
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    planner = _planner(catalog, style_id="official")
    answer = _answer_with_reason()
    result = planner._discourse(answer)
    trace = (result.data or {}).get("discourse_trace") or ()
    connective_trace = [
        item for item in trace if item.get("kind") == "connective"
    ]
    assert connective_trace
    assert connective_trace[0]["mode"] == "plain"


# --- анафора -------------------------------------------------------


def test_anaphora_replaces_repeated_name(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner = _planner(catalog, style_id="official")
    answer = Answer(
        "explanation",
        "Империя сильна.",
        "p1",
        data={
            "reason": "Империя всегда побеждает",
            "reason_args": ("faction:red", "faction:blue"),
            "args": ("faction:red", "faction:blue"),
            "target": "faction:red",
        },
    )
    result = planner._discourse(answer)
    trace = (result.data or {}).get("discourse_trace") or ()
    anaphora_trace = [
        item for item in trace if item.get("kind") == "anaphora"
    ]
    assert anaphora_trace
    assert anaphora_trace[0]["pronoun"] == "она"
    moves = (result.data or {}).get("moves") or ()
    assert len(moves) == 2
    by_id = {move["id"]: move["text"] for move in moves}
    assert by_id["justify"] == "Империя всегда побеждает"
    assert by_id["answer"] == "Империя сильна."
    assert result.text.count("Империя") == 1
    assert "она сильна" in result.text
    assert "Империя сильна" not in result.text


def test_anaphora_skips_short_names(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["anaphora"]["min_length"] = 200
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    planner = _planner(catalog, style_id="official")
    answer = Answer(
        "explanation",
        "Империя сильна.",
        "p1",
        data={
            "reason": "Империя всегда побеждает",
            "reason_args": ("faction:red", "faction:blue"),
            "args": ("faction:red", "faction:blue"),
            "target": "faction:red",
        },
    )
    result = planner._discourse(answer)
    assert "Империя всегда побеждает" in result.text


def test_anaphora_respects_kinds(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["anaphora"]["kinds"] = ["conclusion"]
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    planner = _planner(catalog, style_id="official")
    answer = Answer(
        "explanation",
        "Империя сильна.",
        "p1",
        data={
            "reason": "Империя всегда побеждает",
            "reason_args": ("faction:red", "faction:blue"),
            "args": ("faction:red", "faction:blue"),
            "target": "faction:red",
        },
    )
    result = planner._discourse(answer)
    assert "Империя всегда побеждает" in result.text


# --- тема-рема -----------------------------------------------------


def test_topic_moves_justify_first(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner = _planner(catalog, style_id="official")
    answer = _answer_with_reason()
    result = planner._discourse(answer)
    moves = (result.data or {}).get("moves") or ()
    assert moves
    assert moves[0]["id"] == "justify"
    assert moves[1]["id"] == "answer"


def test_topic_can_be_disabled_json_only(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["patterns"]["explanation_basic"]["topic"] = ""
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    planner = _planner(catalog, style_id="official")
    answer = _answer_with_reason()
    result = planner._discourse(answer)
    moves = (result.data or {}).get("moves") or ()
    assert moves[0]["id"] == "answer"


# --- линтер -------------------------------------------------------


def test_lint_catches_unknown_anaphora_type(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["anaphora"]["types"].append("nonexistent")
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "anaphora" in item and "nonexistent" in item
        for item in problems
    )


def test_lint_catches_bad_mode(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    first = next(iter(data["connectives"]))
    data["connectives"][first]["mode"] = "nope"
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "discourse.connectives" in item and "nope" in item
        for item in problems
    )