"""Тесты D6.4: детерминированный планировщик целей.

Цели и шаги задаются ``configs/dialogue/goals.json``. Проверяется
выбор цели по данным, порядок шагов, статусы проверок и отсутствие
скрытых решений в Python.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.planner import GoalPlanner, intent_from_sem


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _catalog(directory: Path):
    return load_dialogue(directory)


def _rewrite_goals(directory: Path, goals) -> None:
    path = directory / "goals.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["goals"] = goals
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _question():
    return intent_from_sem(
        {"kind": "question", "wh": "yesno"},
        phrase="Есть ли у Империи Абвер?",
    )


def _command():
    return intent_from_sem(
        {
            "kind": "social",
            "act": "command",
            "object": {"kind": "np", "head": {"entity": "faction:blue"}},
        },
        phrase="Приказываю Республику.",
    )


def test_goals_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner = GoalPlanner(catalog)
    ids = [str(item.get("id")) for item in planner.goals()]
    assert ids == ["answer", "social", "action"]


def test_lint_goals_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    relevant = [item for item in problems if item.startswith("goals.")]
    assert relevant == []


def test_lint_catches_unknown_op(tmp_path):
    directory = _copy_configs(tmp_path)
    goals = [
        {
            "id": "answer",
            "when": {"kinds": ["question"]},
            "steps": [{"id": "reply", "op": "teleport"}],
        }
    ]
    _rewrite_goals(directory, goals)
    problems = lint_directory(directory)
    assert any("goals.goals[0].steps[0].op" in item
               for item in problems)


def test_lint_catches_empty_steps(tmp_path):
    directory = _copy_configs(tmp_path)
    goals = [
        {"id": "answer", "when": {"kinds": ["question"]}, "steps": []}
    ]
    _rewrite_goals(directory, goals)
    problems = lint_directory(directory)
    assert any("goals.goals[0].steps" in item for item in problems)


def test_intent_from_question():
    intent = _question()
    assert intent is not None
    assert intent.kind == "question"
    assert intent.act == ""


def test_intent_from_command_keeps_target():
    intent = _command()
    assert intent is not None
    assert intent.kind == "social"
    assert intent.act == "command"
    assert intent.target == "faction:blue"


def test_answer_plan_has_reply_step(tmp_path):
    planner = GoalPlanner(_catalog(_copy_configs(tmp_path)))
    plan = planner.plan(_question())
    assert plan is not None
    assert plan.id == "answer"
    assert [step.op for step in plan.steps] == ["answer"]
    assert plan.next_step().id == "reply"


def test_social_plan_checks_authority(tmp_path):
    planner = GoalPlanner(_catalog(_copy_configs(tmp_path)))
    intent = _command()
    blocked = planner.plan(intent, checks={"authority": False})
    allowed = planner.plan(intent, checks={"authority": True})
    assert blocked is not None and blocked.status == "blocked"
    assert blocked.steps[0].status == "blocked"
    assert allowed is not None and allowed.steps[0].status == "done"
    assert allowed.next_step().id == "act"


def test_action_plan_checks_availability(tmp_path):
    planner = GoalPlanner(_catalog(_copy_configs(tmp_path)))
    intent = intent_from_sem(
        {"kind": "order", "action": "show_of_force"}
    )
    plan = planner.plan(intent, checks={"available": False})
    assert plan is not None and plan.status == "blocked"
    assert plan.reason == "blocked:available"


def test_goals_are_data_driven(tmp_path):
    directory = _copy_configs(tmp_path)
    goals = [
        {
            "id": "custom",
            "when": {"kinds": ["question"]},
            "steps": [
                {"id": "a", "op": "check", "requires": "knowledge"},
                {"id": "b", "op": "answer", "label": "новый ответ"},
            ],
        }
    ]
    _rewrite_goals(directory, goals)
    planner = GoalPlanner(_catalog(directory))
    plan = planner.plan(_question(), checks={"knowledge": True})
    assert plan.id == "custom"
    assert plan.steps[0].status == "done"
    assert plan.steps[1].label == "новый ответ"


def test_unmatched_intent_returns_none(tmp_path):
    directory = _copy_configs(tmp_path)
    goals = [
        {
            "id": "only_social",
            "when": {"kinds": ["social"]},
            "steps": [{"id": "act", "op": "social"}],
        }
    ]
    _rewrite_goals(directory, goals)
    planner = GoalPlanner(_catalog(directory))
    assert planner.plan(_question()) is None


def test_plan_is_deterministic(tmp_path):
    planner = GoalPlanner(_catalog(_copy_configs(tmp_path)))
    first = planner.plan(_command(), checks={"authority": True})
    second = planner.plan(_command(), checks={"authority": True})
    assert first is not None and second is not None
    assert first.snapshot() == second.snapshot()
