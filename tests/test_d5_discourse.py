"""Тесты D5.1: дискурсивный планировщик как данные.

Проверяют, что ходы, шаблоны и связки читаются из ``discourse.json``,
нейтральный стиль сохраняет путь байт-в-байт, а ответ на не-нейтральном
стиле собирается из 1–3 ходов и склеивается регистровыми связками.
Ходы не добавляют фактов: содержание берётся из ``Answer.data``,
``Answer.proof`` и ``Answer.text``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.dialogue.answers import Answer, AnswerPlanner
from campaign.dialogue.knowledge import AgentKnowledge
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.model import StyleSpec
from campaign.dialogue.state import DialogueMemory
from campaign.dialogue.style import StyleEngine


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _catalog(directory: Path):
    return load_dialogue(directory)


def _knowledge(catalog):
    return AgentKnowledge(
        catalog,
        facts=(),
        entities={},
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


def _planner(catalog, style_id: str = "official"):
    knowledge = _knowledge(catalog)
    style_engine = StyleEngine(catalog)
    style = style_engine.profile(style_id)
    planner = AnswerPlanner(
        catalog, knowledge, _persona(catalog), style_engine=style_engine
    )
    planner.set_style(style)
    return planner, style


# --- загрузка -------------------------------------------------------


def test_discourse_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    assert catalog.discourse.moves
    assert catalog.discourse.patterns
    assert catalog.discourse.connectives
    for name in ("answer", "justify", "hedge", "conclusion"):
        assert name in catalog.discourse.moves


def test_discourse_patterns_resolve(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    pattern = catalog.discourse.pattern_for("explanation", "")
    assert pattern is not None
    assert pattern.kind == "explanation"
    for move_id in pattern.moves:
        assert move_id in catalog.discourse.moves


def test_lint_discourse_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    discourse_problems = [
        item for item in problems if "discourse" in item.lower()
    ]
    assert discourse_problems == []


# --- нейтральный путь -----------------------------------------------


def test_neutral_style_skips_discourse(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner, style = _planner(catalog, "neutral")
    assert StyleEngine.is_neutral(style)
    answer = Answer(
        "explanation",
        "Империя считает Республику незаконной.",
        "p1",
        data={"reason": "Эдикт объявил её мятежом."},
    )
    result = planner._discourse(answer)
    assert result.text == answer.text
    assert "moves" not in (result.data or {})


def test_missing_pattern_skips_discourse(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["patterns"].pop("explanation_basic", None)
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    planner, _ = _planner(catalog, "official")
    answer = Answer(
        "explanation",
        "Империя считает Республику незаконной.",
        "p1",
        data={"reason": "Эдикт объявил её мятежом."},
    )
    result = planner._discourse(answer)
    assert result.text == answer.text
    assert "moves" not in (result.data or {})


# --- не-нейтральный путь --------------------------------------------


def test_official_explanation_has_two_moves(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner, _ = _planner(catalog, "official")
    answer = Answer(
        "explanation",
        "Империя считает Республику незаконной.",
        "p1",
        data={
            "reason": "Эдикт объявил её мятежом",
            "reason_args": ("faction:red", "faction:blue"),
        },
    )
    result = planner._discourse(answer)
    moves = (result.data or {}).get("moves") or ()
    assert len(moves) == 2
    ids = [move["id"] for move in moves]
    # Порядок задаётся pattern.topic: justify идёт первым
    assert ids[0] == "justify"
    assert ids[1] == "answer"
    assert moves[1]["text"] == "Империя считает Республику незаконной."
    trace = (result.data or {}).get("discourse_trace") or ()
    assert trace
    assert trace[0]["id"].startswith("connective:official_")


def test_friendly_uses_friendly_connective(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner, _ = _planner(catalog, "friendly")
    answer = Answer(
        "explanation",
        "Империя считает Республику незаконной.",
        "p1",
        data={"reason": "Эдикт объявил её мятежом"},
    )
    result = planner._discourse(answer)
    trace = (result.data or {}).get("discourse_trace") or ()
    assert trace
    assert trace[0]["id"].startswith("connective:friendly_")


def test_report_uses_report_connective(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner, _ = _planner(catalog, "report")
    answer = Answer(
        "explanation",
        "Империя считает Республику незаконной.",
        "p1",
        data={"reason": "Эдикт объявил её мятежом"},
    )
    result = planner._discourse(answer)
    trace = (result.data or {}).get("discourse_trace") or ()
    assert trace
    assert trace[0]["id"].startswith("connective:report_")


def test_discourse_deterministic(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner, _ = _planner(catalog, "official")
    answer = Answer(
        "explanation",
        "Империя считает Республику незаконной.",
        "p1",
        data={"reason": "Эдикт объявил её мятежом"},
    )
    first = planner._discourse(answer)
    second = planner._discourse(answer)
    assert first.text == second.text
    assert first.data["moves"] == second.data["moves"]


# --- антиповтор связок ---------------------------------------------


def test_connective_avoid_recent(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner, style = _planner(catalog, "official")
    style = StyleSpec(
        id=style.id,
        label=style.label,
        register=style.register,
        features=style.features,
        selection={**dict(style.selection), "avoid_recent": 2},
    )
    planner.set_style(style)
    memory = DialogueMemory(catalog.state)
    memory.note_discourse("connective:official_moreover")
    planner.realizer.memory = memory
    answer = Answer(
        "explanation",
        "Империя считает Республику незаконной.",
        "p1",
        data={"reason": "Эдикт объявил её мятежом"},
    )
    result = planner._discourse(answer)
    trace = (result.data or {}).get("discourse_trace") or ()
    assert trace
    chosen = trace[0]["id"]
    assert chosen != "connective:official_moreover"


# --- JSON-only расширение ------------------------------------------


def test_new_kind_json_only(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["patterns"]["description_two_moves"] = {
        "id": "description_two_moves",
        "kind": "description",
        "moves": ["answer", "conclusion"],
        "priority": 1,
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    pattern = catalog.discourse.pattern_for("description", "")
    assert pattern is not None
    assert pattern.moves == ("answer", "conclusion")


def test_missing_reason_drops_justify(tmp_path):
    """Ход justify необязателен: без reason он просто выпадает."""

    catalog = _catalog(_copy_configs(tmp_path))
    planner, _ = _planner(catalog, "official")
    answer = Answer(
        "explanation",
        "Империя считает Республику незаконной.",
        "p1",
        data={},
    )
    result = planner._discourse(answer)
    moves = (result.data or {}).get("moves") or ()
    assert len(moves) == 1
    assert moves[0]["id"] == "answer"


def test_source_only_move_loads(tmp_path):
    """Ход, ссылающийся только на source, валиден: это готовая строка."""

    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["moves"]["example"] = {
        "id": "example",
        "label": "пример",
        "source": "example_text",
        "optional": True,
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    assert "example" in catalog.discourse.moves
    problems = lint_directory(directory)
    assert not any(
        "discourse.moves.example" in item for item in problems
    )


# --- линтер --------------------------------------------------------


def test_lint_catches_broken_move_reference(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["patterns"]["explanation_basic"]["moves"] = ["nope"]
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "discourse.patterns.explanation_basic" in item
        for item in problems
    )


def test_lint_catches_duplicate_connective_id(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["connectives"]["connective:official_plain_dup"] = {
        "id": "connective:official_plain",
        "text": "И",
        "features": {"formality": "high"},
        "priority": 1,
        "position": "between",
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "discourse.connectives" in item and "повтор" in item
        for item in problems
    )


def test_lint_catches_missing_move_fields(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "discourse.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["moves"]["broken"] = {"id": "broken", "label": "пусто"}
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "discourse.moves.broken" in item
        for item in problems
    )


def test_empty_discourse_is_ok(tmp_path):
    """Отсутствие discourse.json — валидное состояние (слой опционален)."""

    directory = _copy_configs(tmp_path)
    (directory / "discourse.json").unlink()
    problems = lint_directory(directory)
    discourse_problems = [
        item for item in problems if "discourse" in item.lower()
    ]
    assert discourse_problems == []