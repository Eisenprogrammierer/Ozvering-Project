"""Тесты D5.4: production-паттерн с ``topics`` и просьба «Подробнее».

Развёрнутый паттерн ``explanation_detailed`` помечен ``detail: true``,
поэтому обычный вопрос остаётся коротким. Абзац собирается по явной
просьбе: «Подробнее» или «Почему?» как уточнение к прошлому ответу.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import (
    DialogueSession,
    build_knowledge,
    load_dialogue,
)
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

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


def _session(catalog, campaign, style_id="official"):
    return DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id=style_id,
    )


def test_production_detailed_pattern_is_loaded(catalog):
    pattern = catalog.discourse.pattern_for(
        "explanation", "belief_why", detail=True
    )
    assert pattern is not None
    assert pattern.id == "explanation_detailed"
    assert pattern.detail
    assert pattern.connectives is False
    assert pattern.topics[:3] == ("statement", "answer", "justify")
    for move_id in pattern.moves:
        assert move_id in catalog.discourse.moves


def test_short_answer_does_not_pick_detailed_pattern(catalog):
    pattern = catalog.discourse.pattern_for("explanation", "belief_why")
    assert pattern is not None
    assert pattern.id == "explanation_basic"
    assert not pattern.detail


def test_detail_falls_back_for_other_kinds(catalog):
    pattern = catalog.discourse.pattern_for(
        "list", "organs_list", detail=True
    )
    assert pattern is not None
    assert pattern.id == "list_with_conclusion"
    assert not pattern.detail


def test_short_explanation_stays_short(catalog, campaign):
    session = _session(catalog, campaign)
    answer = session.ask("Почему Империя считает Республику незаконной?")
    move_ids = [
        move["id"] for move in (answer.data or {}).get("moves") or ()
    ]
    assert move_ids == ["answer"]
    assert "По имеющимся сведениям" not in answer.text


def test_detail_followup_builds_paragraph(catalog, campaign):
    session = _session(catalog, campaign)
    session.ask("Почему Империя считает Республику незаконной?")
    answer = session.ask("Подробнее")
    move_ids = [
        move["id"] for move in (answer.data or {}).get("moves") or ()
    ]
    assert answer.plan_id == "belief_why"
    assert move_ids == [
        "statement",
        "answer",
        "hedge_detail",
        "conclusion",
    ]
    assert "Империя" in answer.text
    assert "Причина:" in answer.text
    assert "По имеющимся сведениям" in answer.text
    assert "Таково положение" in answer.text


def test_detail_followup_works_in_neutral(catalog, campaign):
    session = _session(catalog, campaign, style_id="neutral")
    session.ask("Почему Империя считает Республику незаконной?")
    answer = session.ask("Подробнее")
    move_ids = [
        move["id"] for move in (answer.data or {}).get("moves") or ()
    ]
    assert move_ids == [
        "statement",
        "answer",
        "hedge_detail",
        "conclusion",
    ]
    assert "Насколько мне известно" in answer.text
    assert "Вот и всё" in answer.text


def test_why_fragment_asks_for_detail(catalog, campaign):
    session = _session(catalog, campaign)
    session.ask("Империя воюет с Республикой?")
    answer = session.ask("Почему?")
    move_ids = [
        move["id"] for move in (answer.data or {}).get("moves") or ()
    ]
    assert answer.plan_id == "war_why"
    assert len(move_ids) >= 3
    assert "По имеющимся сведениям" in answer.text


def test_detail_flag_does_not_leak_into_state(catalog, campaign):
    session = _session(catalog, campaign)
    session.ask("Почему Империя считает Республику незаконной?")
    session.ask("Подробнее")
    assert session.state.qud
    assert "detail" not in session.state.qud[-1]["sem"]
    follow = session.ask("Какие органы есть у Империи?")
    assert follow.kind == "list"


def test_detail_without_question_asks_for_topic(catalog, campaign):
    session = _session(catalog, campaign, style_id="neutral")
    answer = session.ask("Подробнее")
    assert answer.kind == "clarification"
    assert answer.text == session.persona.clarify["no_qud"]
