"""Тесты D7.0: headless-текстовик, история, откат и подсказки."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import DialogueSession, TextGame, build_knowledge
from campaign.dialogue.console import ConsoleEntry
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


def _campaign() -> AutomataCampaign:
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


def _session(catalog, campaign, allow_actions=False) -> DialogueSession:
    return DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
        allow_actions=allow_actions,
        campaign=campaign,
    )


@pytest.fixture
def catalog():
    return load_dialogue(DEFAULT_DIR)


@pytest.fixture
def campaign():
    return _campaign()


@pytest.fixture
def game(catalog, campaign):
    return TextGame(_session(catalog, campaign))


def test_submit_question_adds_history(game):
    entry = game.submit("Какие органы есть у Империи?")
    assert entry.kind == "answer"
    assert entry.reply
    assert game.history() == (entry,)


def test_empty_input_is_command(game):
    entry = game.submit("   ")
    assert entry.kind == "command"
    assert entry.reply
    assert game.history() == ()


def test_action_disabled_by_default(catalog, campaign):
    game = TextGame(_session(catalog, campaign))
    before = campaign.snapshot()
    entry = game.submit("Покажи силу.")
    assert entry.kind == "action"
    assert entry.performed is False
    assert entry.reason == "actions_disabled"
    assert campaign.snapshot() == before


def test_action_performed_with_allow_actions(catalog, campaign):
    game = TextGame(_session(catalog, campaign, allow_actions=True))
    entry = game.submit("Покажи силу.")
    assert entry.kind == "action"
    assert entry.performed is True
    assert entry.action_id == "show_of_force"
    assert campaign.actions_left == campaign.actions_per_turn - 1


def test_undo_restores_campaign_and_history(catalog, campaign):
    game = TextGame(_session(catalog, campaign, allow_actions=True))
    before = campaign.snapshot()
    game.submit("Покажи силу.")
    entry = game.submit("/undo")
    assert entry.reply
    assert campaign.snapshot() == before
    assert game.history() == ()


def test_undo_restores_dialogue_state(game):
    game.submit("Какие органы есть у Империи?")
    assert game.session.state.turn == 1
    game.submit("/undo")
    assert game.session.state.turn == 0
    assert game.session.memory.turns == 0


def test_undo_empty(game):
    entry = game.submit("/undo")
    assert entry.kind == "command"
    assert game.history() == ()


def test_history_limit_from_data(tmp_path, campaign):
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    path = target / "console.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["history_limit"] = 2
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    catalog = load_dialogue(target)
    game = TextGame(_session(catalog, campaign))
    for _ in range(3):
        game.submit("Какие органы есть у Империи?")
    assert len(game.history()) == 2


def test_hint_lists_action_phrases(game):
    hint = game.hint()
    assert "Покажи силу" in hint
    assert hint == game.hint()


def test_help_and_aliases(game):
    assert "/undo" in game.submit("/help").reply
    assert game.submit("/h").reply == game.submit("/help").reply
    assert "/undo" in game.submit("/?").reply


def test_history_command(game):
    assert game.submit("/history").reply
    game.submit("Какие органы есть у Империи?")
    reply = game.submit("/history").reply
    assert "Какие органы есть у Империи?" in reply


def test_quit_closes_game(game):
    entry = game.submit("/quit")
    assert entry.kind == "command"
    assert game.closed is True


def test_unknown_command(game):
    entry = game.submit("/nope")
    assert entry.kind == "command"
    assert "/nope" in entry.reply


def test_snapshot_is_deterministic(catalog, campaign):
    first = TextGame(_session(catalog, campaign))
    second = TextGame(_session(load_dialogue(DEFAULT_DIR), _campaign()))
    for game in (first, second):
        game.submit("Какие органы есть у Империи?")
        game.submit("/hint")
    assert first.snapshot() == second.snapshot()


def test_entry_snapshot_shape():
    entry = ConsoleEntry("answer", "вопрос", "ответ", plan_id="p")
    assert entry.snapshot()["plan_id"] == "p"
    assert entry.snapshot()["kind"] == "answer"


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _rewrite(path: Path, key: str, value) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data[key] = value
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_lint_console_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    assert [item for item in problems if item.startswith("console.")] == []


def test_lint_catches_missing_message(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "console.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["messages"]["quit"]
    _rewrite(path, "messages", data["messages"])
    problems = lint_directory(directory)
    assert any("console.messages.quit" in item for item in problems)


def test_lint_catches_unknown_alias(tmp_path):
    directory = _copy_configs(tmp_path)
    _rewrite(directory / "console.json", "aliases", {"/z": "nope"})
    problems = lint_directory(directory)
    assert any("console.aliases./z" in item for item in problems)


def test_lint_catches_empty_phrases(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "actions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["actions"][0]["phrases"] = [""]
    _rewrite(path, "actions", data["actions"])
    problems = lint_directory(directory)
    assert any("actions.actions[0].phrases" in item for item in problems)
