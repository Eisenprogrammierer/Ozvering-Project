"""Тесты F-15: реестр типов ответа и generic-обработчики."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue.answers import AnswerPlanner, answer_handler_name
from campaign.dialogue.knowledge import AgentKnowledge, build_knowledge
from campaign.dialogue.lint import lint_catalog, lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.model import PlanSpec
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DEFAULT_DIR)


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _stub_knowledge(catalog) -> AgentKnowledge:
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


def _planner(catalog, knowledge=None):
    persona = next(iter(catalog.personas.values()))
    return AnswerPlanner(
        catalog,
        knowledge or _stub_knowledge(catalog),
        persona,
    )


def test_registry_is_loaded_and_covers_every_plan(catalog):
    kinds = catalog.answer_kinds.get("kinds") or {}
    assert kinds
    for plan in catalog.plans:
        answer_type = str(plan.answer.get("type") or "")
        assert answer_type in kinds, plan.id


def test_registry_handlers_are_implemented(catalog):
    kinds = catalog.answer_kinds.get("kinds") or {}
    for kind, spec in kinds.items():
        handler = str(spec.get("handler") or "")
        assert handler, kind
        assert hasattr(AnswerPlanner, "_answer_" + handler), kind


def test_registry_marks_generic_kinds(catalog):
    kinds = catalog.answer_kinds.get("kinds") or {}
    for kind in ("entity", "relation", "value", "list", "explain", "summary"):
        assert kinds[kind].get("generic") is True, kind


def test_handler_name_falls_back_to_type():
    registry = {"kinds": {"feeling": {"handler": "entity"}}}
    assert answer_handler_name("feeling", registry) == "entity"
    assert answer_handler_name("unknown_type", registry) == "unknown_type"
    assert answer_handler_name("feeling", {}) == "feeling"


def test_generic_entity_handler_answers_alias_type(catalog):
    plan = PlanSpec(
        id="alias_entity",
        priority=100,
        match={"kind": "assert", "target": "$target"},
        answer={"type": "feeling", "target": "$target"},
    )
    registry = {
        "schema": 1,
        "kinds": {"feeling": {"handler": "entity", "generic": True}},
    }
    local = replace(catalog, plans=(plan,), answer_kinds=registry)
    answer = _planner(local)._plan(
        {"kind": "assert", "target": "faction:red"}
    )
    assert answer.plan_id == "alias_entity"
    assert answer.kind == "entity"
    assert answer.text
    assert answer.data["target"] == "faction:red"


def _campaign() -> AutomataCampaign:
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


def test_generic_relation_handler_answers_alias_type(catalog):
    campaign = _campaign()
    speaker = campaign.faction("red").characters[1].campaign_id
    knowledge = build_knowledge(catalog, campaign, "red", speaker)
    plan = PlanSpec(
        id="alias_relation",
        priority=100,
        match={"kind": "assert", "relation": "$relation"},
        answer={
            "type": "feeling_about",
            "relation": "has_organ",
            "args": ["faction:red", "organ:red:imperial_staff"],
        },
    )
    registry = {
        "schema": 1,
        "kinds": {
            "feeling_about": {"handler": "relation", "generic": True}
        },
    }
    local = replace(catalog, plans=(plan,), answer_kinds=registry)
    answer = _planner(local, knowledge)._plan(
        {"kind": "assert", "relation": "has_organ"}
    )
    assert answer.plan_id == "alias_relation"
    assert answer.kind == "relation"
    assert answer.text


def test_unregistered_answer_type_fails_lint(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "plans.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["plans"][0]["answer"] = {"type": "mystery"}
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "answer.type" in item
        and "mystery" in item
        and "answer_kinds" in item
        for item in problems
    )


def test_missing_handler_fails_lint(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "answer_kinds.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["kinds"]["list"]["handler"] = "no_such_handler"
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(directory)
    assert any(
        "no_such_handler" in item and "не реализован" in item
        for item in problems
    )


def test_production_catalog_passes_answer_lint(catalog):
    assert lint_catalog(catalog) == []
