"""Тесты D5.3/D5.4: агрегация, анафора, тема-рема, порядок абзаца.

D5.3: связки ``mode: "clause"``, анафора, ``topic``.
D5.4: ``topics: [...]`` — порядок абзаца 4+ ходов. Паттерн
``explanation_detailed`` добавляется в фикстуру, а не лежит в
production: иначе ``pattern_for("explanation", "")`` подхватывал бы
его, когда ``explanation_basic`` убран, и это ломало бы семантику
«нет паттерна — нет дискурса» (см. ``test_missing_pattern_skips_discourse``
в ``test_d5_discourse.py``).
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


def _add_detailed_pattern(directory: Path) -> None:
    """Добавить ``explanation_detailed`` в фикстуру.

    Паттерн намеренно не лежит в production-`discourse.json`:
    ``test_missing_pattern_skips_discourse`` требует, чтобы без
    `explanation_basic` дискурс не подхватывался. Поэтому тесты D5.4
    добавляют паттерн локально.
    """

    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["patterns"]["explanation_detailed"] = {
        "id": "explanation_detailed",
        "kind": "explanation",
        "moves": ["answer", "justify", "hedge", "conclusion"],
        "topics": ["justify", "answer", "conclusion", "hedge"],
        "priority": 1,
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
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


# --- D5.4: topics --------------------------------------------------


def test_explanation_detailed_added_by_json_only(tmp_path):
    """Паттерн с ``topics`` загружается из JSON и работает."""

    directory = _copy_configs(tmp_path)
    _add_detailed_pattern(directory)
    catalog = _catalog(directory)
    pattern = next(
        (
            item
            for item in catalog.discourse.patterns
            if item.id == "explanation_detailed"
        ),
        None,
    )
    assert pattern is not None
    assert pattern.topics == (
        "justify",
        "answer",
        "conclusion",
        "hedge",
    )
    assert pattern.moves == (
        "answer",
        "justify",
        "hedge",
        "conclusion",
    )


def test_topics_set_paragraph_order(tmp_path):
    """``topics`` задаёт порядок абзаца 4+ хода."""

    directory = _copy_configs(tmp_path)
    _add_detailed_pattern(directory)
    data = json.loads(
        (directory / "discourse.json").read_text(encoding="utf-8")
    )
    del data["patterns"]["explanation_basic"]
    (directory / "discourse.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    planner = _planner(catalog, style_id="official")
    answer = Answer(
        "explanation",
        "Империя сильна.",
        "p1",
        data={
            "reason": "эдикт объявил её мятежом",
            "reason_args": ("faction:red", "faction:blue"),
        },
    )
    result = planner._discourse(answer)
    moves = (result.data or {}).get("moves") or ()
    ids = [move["id"] for move in moves]
    assert ids[0] == "justify"
    assert ids[1] == "answer"


def test_topics_partial_falls_back_to_moves(tmp_path):
    """Неполный ``topics``: недостающие идут по ``moves``."""

    directory = _copy_configs(tmp_path)
    _add_detailed_pattern(directory)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["patterns"]["explanation_basic"]
    data["patterns"]["explanation_detailed"]["topics"] = ["justify"]
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
            "reason": "эдикт объявил её мятежом",
            "reason_args": ("faction:red", "faction:blue"),
        },
    )
    result = planner._discourse(answer)
    moves = (result.data or {}).get("moves") or ()
    ids = [move["id"] for move in moves]
    assert ids[0] == "justify"
    assert "answer" in ids


def test_lint_catches_unknown_topic(tmp_path):
    directory = _copy_configs(tmp_path)
    _add_detailed_pattern(directory)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["patterns"]["explanation_detailed"]["topics"] = [
        "justify",
        "nonexistent",
    ]
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "discourse.patterns.explanation_detailed" in item
        and "nonexistent" in item
        for item in problems
    )


def test_lint_catches_duplicate_topic(tmp_path):
    directory = _copy_configs(tmp_path)
    _add_detailed_pattern(directory)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["patterns"]["explanation_detailed"]["topics"] = [
        "justify",
        "justify",
        "answer",
    ]
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "discourse.patterns.explanation_detailed" in item
        and "повтор" in item
        for item in problems
    )


# --- линтер (D5.3) -----------------------------------------------


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