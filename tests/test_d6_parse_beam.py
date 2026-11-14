"""Тесты D6.2d: детерминированный beam разбора.

Проверяют, что выбор лучшего разбора задаётся ``parsing.json``:
порядком видов, глубиной дерева и шириной beam. Никаких вероятностей:
одинаковый вход и данные дают одинаковый результат.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from campaign.dialogue.engine import DialogueSession
from campaign.dialogue.knowledge import AgentKnowledge, Fact
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.parser import ChartParser

AMBIGUOUS = (
    "Что если Империя воюет с Республикой, "
    "то Республика воюет с Империей"
)


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _catalog(directory: Path):
    return load_dialogue(directory)


def _priority(directory: Path, order) -> None:
    path = directory / "parsing.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["kind_priority"] = list(order)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_parsing_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    spec = catalog.parsing
    assert spec
    assert int(spec["beam_width"]) >= 1
    assert "counterfactual" in spec["kind_priority"]
    assert "question" in spec["kind_priority"]


def test_lint_parsing_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    relevant = [item for item in problems if "parsing" in item.lower()]
    assert relevant == []


def test_lint_catches_bad_beam_width(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "parsing.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["beam_width"] = 0
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    problems = lint_directory(directory)
    broken = [item for item in problems if "beam_width" in item]
    assert broken


def test_lint_catches_duplicate_kind(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "parsing.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["kind_priority"] = ["question", "question"]
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    problems = lint_directory(directory)
    broken = [item for item in problems if "kind_priority" in item]
    assert broken


def test_ambiguous_phrase_has_two_kinds(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    parses = ChartParser(catalog).parse(AMBIGUOUS)
    kinds = {item.sem.get("kind") for item in parses}
    assert {"counterfactual", "question"} <= kinds


def test_default_priority_prefers_counterfactual(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    best = ChartParser(catalog).parse_best(AMBIGUOUS)
    assert best is not None
    assert best.sem["kind"] == "counterfactual"


def test_priority_is_data_driven(tmp_path):
    directory = _copy_configs(tmp_path)
    _priority(directory, ["question", "counterfactual"])
    catalog = _catalog(directory)
    best = ChartParser(catalog).parse_best(AMBIGUOUS)
    assert best is not None
    assert best.sem["kind"] == "question"


def test_beam_width_limits_candidates(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "parsing.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["beam_width"] = 1
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    catalog = _catalog(directory)
    beam = ChartParser(catalog).parse_beam(AMBIGUOUS)
    assert len(beam) == 1
    assert beam[0].sem["kind"] == "counterfactual"


def test_same_kind_keeps_chart_order(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    parser = ChartParser(catalog)
    text = "Какие органы есть у Империи?"
    parses = parser.parse(text)
    beam = parser.parse_beam(text)
    assert [item.rule for item in beam] == [
        item.rule for item in parses
    ][: len(beam)]


def test_parse_best_is_deterministic(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    parser = ChartParser(catalog)
    first = parser.parse_best(AMBIGUOUS)
    second = parser.parse_best(AMBIGUOUS)
    assert first is not None and second is not None
    assert first.rule == second.rule
    assert first.sem == second.sem


def test_session_uses_beam(tmp_path):
    directory = _copy_configs(tmp_path)
    _priority(directory, ["question", "counterfactual"])
    catalog = _catalog(directory)
    knowledge = AgentKnowledge(
        catalog,
        facts=(Fact("at_war_with", ("faction:red", "faction:blue")),),
        entities={},
        side="red",
        faction_id="faction:red",
        speaker_id="char_red",
        speaker_name="Император",
        world=catalog.world,
        run_id="campaign:red:13",
    )
    session = DialogueSession(catalog, knowledge, persona_id="red")
    answer = session.ask(AMBIGUOUS)
    assert answer.data.get("question_kind") or answer.plan_id
    assert answer.kind != "counterfactual"
