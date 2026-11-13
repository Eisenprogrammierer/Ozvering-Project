"""Тесты D3.1: сравнения и расширенное «почему» как данные.

Проверяют, что таблица ``comparison.json`` выбирает исход и конструкцию
без ``if a > b`` в Python, что незнание на любой стороне даёт честный
ответ, что ``max_premises`` расширяет «почему» до N посылок, и что
линтер ловит битые ссылки. Мир и BDI не меняются.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.dialogue.answers import Answer, AnswerPlanner
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


def _knowledge(catalog, facts=()):
    return AgentKnowledge(
        catalog,
        facts=tuple(facts),
        entities={},
        side="red",
        faction_id="faction:red",
        speaker_id="char_red",
        speaker_name="Император",
        world=catalog.world,
        player_id="char_player",
        player_name="Игрок",
    )


def _planner(catalog, facts=(), style_id="neutral"):
    knowledge = _knowledge(catalog, facts)
    style_engine = StyleEngine(catalog)
    style = style_engine.profile(style_id)
    persona = catalog.personas.get("default") or list(
        catalog.personas.values()
    )[0]
    planner = AnswerPlanner(
        catalog, knowledge, persona, style_engine=style_engine
    )
    planner.set_style(style)
    return planner


def _comparison_sem(left: str, right: str, key: str) -> dict:
    return {
        "kind": "question",
        "wh": "compare",
        "body": {
            "kind": "compare",
            "relation": "asset",
            "left": {"head": {"entity": left}},
            "right": {"head": {"entity": right}},
            "key": {"head": {"entity": key}},
        },
    }


# --- загрузка ------------------------------------------------------


def test_comparison_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    assert catalog.comparison.comparisons
    spec = catalog.comparison.get("asset")
    assert spec is not None
    assert spec.relation == "asset"
    assert spec.greater and spec.less and spec.equal


def test_lint_comparison_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    comparison_problems = [
        item for item in problems if "comparison" in item.lower()
    ]
    assert comparison_problems == []


# --- исходы --------------------------------------------------------


def test_greater_picks_greater_construction(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner = _planner(
        catalog,
        facts=[
            Fact("asset", ("faction:red", "influence", "0.8")),
            Fact("asset", ("faction:blue", "influence", "0.3")),
        ],
    )
    answer = planner.plan(_comparison_sem(
        "faction:red", "faction:blue", "asset:influence"
    ))
    assert answer.kind == "comparison"
    assert answer.data["outcome"] == "greater"
    assert answer.data["construction"] == "comparison_greater"
    assert "сильнее" in answer.text


def test_less_picks_less_construction(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner = _planner(
        catalog,
        facts=[
            Fact("asset", ("faction:red", "influence", "0.2")),
            Fact("asset", ("faction:blue", "influence", "0.7")),
        ],
    )
    answer = planner.plan(_comparison_sem(
        "faction:red", "faction:blue", "asset:influence"
    ))
    assert answer.data["outcome"] == "less"
    assert answer.data["construction"] == "comparison_less"


def test_equal_picks_equal_construction(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner = _planner(
        catalog,
        facts=[
            Fact("asset", ("faction:red", "influence", "0.5")),
            Fact("asset", ("faction:blue", "influence", "0.5")),
        ],
    )
    answer = planner.plan(_comparison_sem(
        "faction:red", "faction:blue", "asset:influence"
    ))
    assert answer.data["outcome"] == "equal"
    assert answer.data["construction"] == "comparison_equal"


def test_unknown_left(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner = _planner(
        catalog,
        facts=[
            Fact("asset", ("faction:blue", "influence", "0.7")),
        ],
    )
    answer = planner.plan(_comparison_sem(
        "faction:red", "faction:blue", "asset:influence"
    ))
    assert answer.data["outcome"] == "unknown_left"
    assert answer.data["construction"] == "comparison_unknown_left"


def test_unknown_right(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner = _planner(
        catalog,
        facts=[
            Fact("asset", ("faction:red", "influence", "0.7")),
        ],
    )
    answer = planner.plan(_comparison_sem(
        "faction:red", "faction:blue", "asset:influence"
    ))
    assert answer.data["outcome"] == "unknown_right"


def test_both_unknown(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner = _planner(catalog, facts=[])
    answer = planner.plan(_comparison_sem(
        "faction:red", "faction:blue", "asset:influence"
    ))
    assert answer.data["outcome"] == "both_unknown"
    assert answer.data["construction"] == "comparison_both_unknown"


# --- JSON-only -----------------------------------------------------


def test_new_comparison_json_only(tmp_path):
    """Новое сравниваемое отношение в JSON работает без правки Python."""

    directory = _copy_configs(tmp_path)
    path = directory / "comparison.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["comparisons"]["other_asset"] = {
        "relation": "asset",
        "args": {"left": 0, "key": 1, "left_value": 2},
        "value_arg": 2,
        "key_arg": 1,
        "subject_arg": 0,
        "greater": "comparison_greater",
        "less": "comparison_less",
        "equal": "comparison_equal",
        "unknown_left": "comparison_unknown_left",
        "unknown_right": "comparison_unknown_right",
        "both_unknown": "comparison_both_unknown",
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    assert catalog.comparison.get("other_asset") is not None


# --- детерминизм --------------------------------------------------


def test_comparison_deterministic(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    facts = [
        Fact("asset", ("faction:red", "influence", "0.8")),
        Fact("asset", ("faction:blue", "influence", "0.3")),
    ]
    planner = _planner(catalog, facts=facts)
    first = planner.plan(_comparison_sem(
        "faction:red", "faction:blue", "asset:influence"
    ))
    second = planner.plan(_comparison_sem(
        "faction:red", "faction:blue", "asset:influence"
    ))
    assert first.text == second.text
    assert first.data["outcome"] == second.data["outcome"]


# --- max_premises -------------------------------------------------


def test_max_premises_default_is_one(tmp_path):
    """Без ``max_premises`` план озвучивает одно обоснование."""

    catalog = _catalog(_copy_configs(tmp_path))
    plan = next(
        item for item in catalog.plans if item.id == "belief_why"
    )
    planner = _planner(catalog)
    assert planner._max_premises(plan) == 1


def test_max_premises_can_be_increased(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "plans.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for plan in data["plans"]:
        if plan["id"] == "belief_why":
            plan["answer"]["max_premises"] = 3
            break
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    plan = next(
        item for item in catalog.plans if item.id == "belief_why"
    )
    planner = _planner(catalog)
    assert planner._max_premises(plan) == 3


# --- линтер -------------------------------------------------------


def test_lint_catches_missing_construction(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "comparison.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["comparisons"]["asset"]["greater"] = "nope"
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "comparison" in item and "nope" in item for item in problems
    )


def test_lint_catches_unknown_relation(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "comparison.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["comparisons"]["asset"]["relation"] = "nope_relation"
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "comparison" in item and "nope_relation" in item
        for item in problems
    )


def test_lint_catches_bad_max_premises(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "plans.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for plan in data["plans"]:
        if plan["id"] == "belief_why":
            plan["answer"]["max_premises"] = 0
            break
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "max_premises" in item for item in problems
    )


def test_empty_comparison_is_ok(tmp_path):
    directory = _copy_configs(tmp_path)
    (directory / "comparison.json").unlink()
    problems = lint_directory(directory)
    comparison_problems = [
        item for item in problems if "comparison" in item.lower()
    ]
    assert comparison_problems == []