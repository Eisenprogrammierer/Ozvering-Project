"""Тесты D6.4: императивы и псевдонимы действий.

Псевдонимы живут в ``configs/dialogue/actions.json``: логическая
форма императива ссылается на псевдоним, мост приводит его к id
действия кампании. Никаких скрытых соответствий в Python.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import DialogueSession, build_knowledge
from campaign.dialogue.bridge import ActionBridge
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.parser import ChartParser
from campaign.dialogue.planner import Intent
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _rewrite_actions(directory: Path, actions) -> None:
    path = directory / "actions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["actions"] = actions
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@pytest.fixture
def catalog():
    return load_dialogue(DEFAULT_DIR)


@pytest.fixture
def campaign():
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


def test_actions_loaded(catalog):
    spec = catalog.actions
    assert spec
    ids = [str(item.get("id")) for item in spec["actions"]]
    assert "show_of_force" in ids


def test_lint_actions_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    assert [item for item in problems if item.startswith("actions.")] == []


def test_lint_catches_unknown_alias(tmp_path):
    directory = _copy_configs(tmp_path)
    _rewrite_actions(
        directory,
        [{"id": "show_of_force", "aliases": ["no_such_alias"]}],
    )
    problems = lint_directory(directory)
    assert any("actions.actions[0].aliases" in item for item in problems)


def test_lint_catches_duplicate_alias(tmp_path):
    directory = _copy_configs(tmp_path)
    _rewrite_actions(
        directory,
        [
            {"id": "show_of_force", "aliases": ["show_force"]},
            {"id": "garrison_network", "aliases": ["show_force"]},
        ],
    )
    problems = lint_directory(directory)
    assert any("повтор" in item and "show_force" in item
               for item in problems)


def test_alias_can_be_added_by_data_only(tmp_path):
    directory = _copy_configs(tmp_path)
    _rewrite_actions(
        directory,
        [{"id": "show_of_force", "aliases": ["show_force", "threaten"]}],
    )
    problems = lint_directory(directory)
    assert [item for item in problems if item.startswith("actions.")] == []


def test_resolve_alias_and_canonical(catalog):
    bridge = ActionBridge(catalog)
    assert bridge.resolve("show_force") == "show_of_force"
    assert bridge.resolve("show_of_force") == "show_of_force"
    assert bridge.resolve("unknown") == "unknown"


def test_imperative_phrases_parse_to_actions(catalog):
    parser = ChartParser(catalog)
    bridge = ActionBridge(catalog)
    cases = {
        "Покажи силу.": "show_of_force",
        "Укрепи гарнизон.": "garrison_network",
        "Согласуй план.": "staff_plan",
        "Опубликуй эдикт.": "imperial_edict",
    }
    for phrase, expected in cases.items():
        parse = parser.parse_best(phrase)
        assert parse is not None, phrase
        assert parse.sem["kind"] == "order"
        intent = bridge.intent(parse.sem, phrase=phrase)
        assert intent is not None
        assert intent.action_id == expected


def test_imperative_with_target_pp(catalog):
    parser = ChartParser(catalog)
    intent = ActionBridge(catalog).intent(
        parser.parse_best("Покажи силу против Республики.").sem
    )
    assert intent is not None
    assert intent.action_id == "show_of_force"
    assert intent.target == "faction:blue"


def test_session_intent_resolves_alias(catalog, campaign):
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
        campaign=campaign,
    )
    intent = session.intent("Покажи силу.")
    assert intent is not None
    assert intent.kind == "order"
    assert intent.action_id == "show_of_force"


def test_bridge_performs_alias(catalog, campaign):
    bridge = ActionBridge(
        catalog, campaign=campaign, side="red", allow_actions=True
    )
    result = bridge.perform(
        Intent(kind="order", action_id="show_force")
    )
    assert result.ok is True
    assert result.performed is True
    assert result.action_id == "show_of_force"
    assert campaign.actions_left == campaign.actions_per_turn - 1


def test_session_act_imperative(catalog, campaign):
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
        allow_actions=True,
        campaign=campaign,
    )
    result = session.act("Покажи силу.")
    assert result.ok is True
    assert result.performed is True
    assert result.action_id == "show_of_force"


def test_session_act_imperative_disabled_by_default(catalog, campaign):
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
        campaign=campaign,
    )
    before = campaign.snapshot()
    result = session.act("Покажи силу.")
    assert result.reason == "actions_disabled"
    assert campaign.snapshot() == before
