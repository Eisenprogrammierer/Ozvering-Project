"""Тесты D2: QUD, референты, эллипсис, память и её сохранение."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import (
    DialogueMemory,
    DialogueMemoryStore,
    DialogueSession,
    build_knowledge,
    load_dialogue,
)
from campaign.dialogue.lint import lint_directory
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog
from view.support import save_system

ROOT = Path(__file__).resolve().parents[1]
DIALOGUE_DIR = ROOT / "configs" / "dialogue"
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


@pytest.fixture(scope="module")
def campaign():
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DIALOGUE_DIR)


def _session(catalog, campaign, side="red", memory=None):
    return DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, side),
        memory=memory,
    )


def _snapshot(data):
    return json.loads(json.dumps(data, ensure_ascii=False))


def test_ellipsis_reuses_question_and_replaces_owner(catalog, campaign):
    session = _session(catalog, campaign, "red")
    first = session.ask("Какие органы есть у Империи?")
    second = session.ask("А у Республики?")
    direct = _session(catalog, campaign, "red").ask(
        "Какие органы есть у Республики?"
    )

    assert first.plan_id == "organs_list"
    assert second.plan_id == "organs_list"
    assert second.text == direct.text
    assert "Дипломатическое ведомство" in second.text
    assert session.state.qud[-1]["wh"] == "which"


def test_why_fragment_reuses_last_question(catalog, campaign):
    session = _session(catalog, campaign, "red")
    assert session.ask("Империя воюет с Республикой?").kind == "yes"
    answer = session.ask("Почему?")

    assert answer.plan_id == "war_why"
    assert "законности" in answer.text.lower()
    assert answer.proof


def test_pronoun_resolves_recent_character(catalog, campaign):
    session = _session(catalog, campaign, "red")
    assert session.ask("Кто правит Империей?").plan_id == "leader_who"
    answer = session.ask("А он?")

    assert answer.plan_id == "describe_entity"
    assert "Григорий Иванов" in answer.text
    assert "Император" in answer.text


def test_pronoun_without_referent_asks_for_clarification(catalog, campaign):
    session = _session(catalog, campaign, "red")
    answer = session.ask("А он?")

    assert answer.kind == "clarification"
    assert answer.text == session.persona.clarify["no_referent"]


def test_fragment_without_topic_asks_for_topic(catalog, campaign):
    session = _session(catalog, campaign, "red")
    answer = session.ask("Почему?")

    assert answer.kind == "clarification"
    assert answer.text == session.persona.clarify["no_qud"]


def test_noun_fragment_keeps_previous_owner(catalog, campaign):
    session = _session(catalog, campaign, "blue")
    answer = session.ask("Какие органы есть у Республики?")
    assert answer.plan_id == "organs_list"
    answer = session.ask("А какие союзники?")

    assert answer.plan_id == "allies_list"
    assert "Республики" in answer.text
    assert "союзник" in answer.text.lower()


def test_dialogue_does_not_mutate_campaign(catalog, campaign):
    before = _snapshot(campaign.snapshot())
    session = _session(catalog, campaign, "red")
    for phrase in (
        "Какие органы есть у Империи?",
        "А у Республики?",
        "Кто правит Империей?",
        "А он?",
        "Почему Империя воюет с Республикой?",
        "Почему?",
    ):
        session.ask(phrase)

    assert _snapshot(campaign.snapshot()) == before


def test_stateful_dialogue_is_deterministic(catalog, campaign):
    phrases = (
        "Какие органы есть у Империи?",
        "А у Республики?",
        "Кто правит Империей?",
        "А он?",
        "Почему Империя воюет с Республикой?",
        "Почему?",
    )
    first = _session(catalog, campaign, "red")
    second = _session(catalog, campaign, "red")
    first_texts = [first.ask(phrase).text for phrase in phrases]
    second_texts = [second.ask(phrase).text for phrase in phrases]

    assert first_texts == second_texts
    assert first.memory.to_dict() == second.memory.to_dict()


def test_memory_roundtrip_restores_context(catalog, campaign):
    session = _session(catalog, campaign, "red")
    session.ask("Кто правит Империей?")
    saved = session.memory.to_dict()

    restored = DialogueMemory.from_dict(catalog.state, _snapshot(saved))
    assert restored.to_dict() == saved
    resumed = _session(catalog, campaign, "red", memory=restored)
    answer = resumed.ask("А он?")

    assert answer.plan_id == "describe_entity"
    assert "Григорий Иванов" in answer.text
    assert "character:char_red_001" in resumed.state.referents


def test_memory_decays_unpinned_and_keeps_pinned(catalog):
    memory = DialogueMemory(catalog.state, run_id="run", clock=0)
    memory.note_entity("organ:x", "Орган", "organ", "m", 0)
    memory.note_entity("faction:y", "Фракция", "faction", "f", 0)
    memory.note_fact(
        "at_war_with", ("faction:y", "faction:z"), 0, {"faction:y"}
    )
    memory.note_fact(
        "has_organ", ("faction:y", "organ:x"), 0,
        {"faction:y", "organ:x"},
    )

    organ_before = memory.entities["organ:x"]["weight"]
    faction_before = memory.entities["faction:y"]["weight"]
    pinned_before = memory.facts["at_war_with|faction:y|faction:z"]["weight"]
    memory.observe_clock(50)
    faction_after = memory.entities["faction:y"]["weight"]
    pinned_after = memory.facts["at_war_with|faction:y|faction:z"]["weight"]

    assert organ_before > 0
    assert "organ:x" not in memory.entities
    assert faction_after == faction_before
    assert pinned_after == pinned_before
    assert "has_organ|faction:y|organ:x" not in memory.facts


def test_memory_limits_are_deterministic(catalog):
    policy = _snapshot(catalog.state)
    policy["memory"]["limits"]["entities"] = 2
    policy["memory"]["min_weight"] = 0.0
    memory = DialogueMemory(policy, run_id="run", clock=0)
    for identifier in ("organ:c", "organ:a", "organ:b"):
        memory.note_entity(identifier, identifier, "organ", "m", 0)
    memory.prune()

    assert sorted(memory.entities) == ["organ:a", "organ:b"]


def test_memory_store_keeps_agents_isolated(catalog):
    store = DialogueMemoryStore(catalog.state)
    red = store.memory("character:red", run_id="run:1", clock=0)
    blue = store.memory("character:blue", run_id="run:1", clock=0)
    red.note_entity("faction:red", "Фракция", "faction", "f", 0)

    assert "faction:red" in red.entities
    assert blue.entities == {}
    other = store.memory("character:blue", run_id="run:2", clock=0)
    assert other is not blue
    assert other.entities == {}


def test_save_payload_roundtrips_dialogue_memory(
    catalog, campaign, tmp_path, monkeypatch
):
    monkeypatch.setattr(save_system, "SAVES_DIR", tmp_path)
    session = _session(catalog, campaign, "red")
    session.ask("Кто правит Империей?")
    store = DialogueMemoryStore(catalog.state)
    store.agents["character:char_red_001"] = session.memory

    class State:
        def to_snapshot(self):
            return {"day": 4}

    path = save_system.save_game(
        State(),
        None,
        "slot",
        dialogue_snapshot=store.to_dict(),
    )
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    loaded = save_system.load_game("slot")
    restored = DialogueMemoryStore.from_dict(
        catalog.state, loaded["dialogue"]
    )

    assert raw["version"] == save_system.SAVE_VERSION
    assert "dialogue" in raw
    restored_agent = restored.agents["character:char_red_001"]
    assert restored_agent.to_dict() == session.memory.to_dict()


def _copy_dialogue(tmp_path, name="state_data"):
    target = tmp_path / name
    shutil.copytree(DIALOGUE_DIR, target)
    return target


def _rewrite(path, mutate):
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_new_fragment_is_added_by_json_only(catalog, campaign, tmp_path):
    root = _copy_dialogue(tmp_path)

    def add_fragment(data):
        data["fragments"].append(
            {
                "id": "why_otchego",
                "tokens": ["отчего"],
                "edits": [{"path": "wh", "value": "why"}],
            }
        )

    _rewrite(root / "state.json", add_fragment)
    extended = load_dialogue(root)
    session = _session(extended, campaign, "red")
    assert session.ask("Империя воюет с Республикой?").kind == "yes"
    answer = session.ask("Отчего?")

    assert answer.plan_id == "war_why"
    assert "законности" in answer.text.lower()


def test_lint_reports_unknown_fragment_slot(tmp_path):
    root = _copy_dialogue(tmp_path, "broken_state")

    def break_edit(data):
        data["fragments"][0]["edits"][0]["value"] = "$ghost"

    _rewrite(root / "state.json", break_edit)
    problems = lint_directory(root)
    assert any("ghost" in item for item in problems)
