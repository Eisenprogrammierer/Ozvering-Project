"""Тесты F-23: адаптер диалога, группы знания и слух."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import DialogueSession, build_knowledge
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.perception import Signal, campaign_view
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"
BLUE_WORK = {
    "actor_side": "blue",
    "turn": 3,
    "label": "Демонстрация силы",
    "success": True,
    "text": "Республика показала силу",
}
RED_WORK = {
    "actor_side": "red",
    "turn": 3,
    "label": "Эдикт",
    "success": True,
    "text": "Империя издала эдикт",
}


@pytest.fixture(scope="module")
def campaign() -> AutomataCampaign:
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DEFAULT_DIR)


def _with_log(campaign):
    if not any(
        entry.get("label") == BLUE_WORK["label"]
        for entry in campaign.log
    ):
        campaign.log.append(dict(BLUE_WORK))
    if not any(
        entry.get("label") == RED_WORK["label"] for entry in campaign.log
    ):
        campaign.log.append(dict(RED_WORK))


def test_legacy_build_keeps_all_facts(campaign, catalog):
    _with_log(campaign)
    knowledge = build_knowledge(catalog, campaign, "red")
    assert knowledge.view is None
    assert knowledge.perception is None
    assert knowledge.facts_for("recent_work")
    assert all(fact.group == "content" for fact in knowledge.facts)


def test_view_filters_unperceived_work(campaign, catalog):
    _with_log(campaign)
    view = campaign_view(campaign, None, world=catalog.world)
    knowledge = build_knowledge(
        catalog, campaign, "red", view=view
    )
    assert knowledge.view is view
    works = knowledge.facts_for("recent_work")
    assert works
    assert all("faction:blue" not in fact.args for fact in works)
    assert any("faction:red" in fact.args for fact in works)
    hidden = campaign.faction("blue").characters[0].campaign_id
    assert hidden


def test_unperceived_fact_is_unknown(campaign, catalog):
    _with_log(campaign)
    view = campaign_view(campaign, None, world=catalog.world)
    knowledge = build_knowledge(
        catalog, campaign, "red", view=view
    )
    args = (
        "faction:blue",
        "3",
        "Демонстрация силы",
        "1",
        "Республика показала силу",
    )
    data = knowledge.explain("recent_work", args)
    assert data["known"] is False
    assert data["label"] == "не знаю"
    assert knowledge.attribution("recent_work", args) == "не знаю"


def test_hearing_turns_fact_into_said(campaign, catalog):
    _with_log(campaign)
    base = campaign_view(campaign, None, world=catalog.world)
    signal = Signal(
        "recent_work",
        (
            "faction:blue",
            "3",
            "Демонстрация силы",
            "1",
            "Республика показала силу",
        ),
        channel="hearing",
        source="char_red_003",
        speaker="char_red_003",
        confidence=0.6,
        day=3,
    )
    view = replace(
        base,
        perception=replace(base.perception, signals=(signal,)),
    )
    knowledge = build_knowledge(
        catalog, campaign, "red", view=view
    )
    works = [
        fact
        for fact in knowledge.facts_for("recent_work")
        if "faction:blue" in fact.args
    ]
    assert len(works) == 1
    fact = works[0]
    assert fact.group == "said"
    assert fact.speaker == "char_red_003"
    assert fact.confidence == pytest.approx(0.6)
    assert knowledge.attribution("recent_work", fact.args) == "мне сказали"


def test_own_beliefs_are_believed(campaign, catalog):
    view = campaign_view(campaign, None, world=catalog.world)
    knowledge = build_knowledge(
        catalog, campaign, "red", view=view
    )
    beliefs = knowledge.facts_for("belief")
    assert beliefs
    assert all(fact.group == "believed" for fact in beliefs)
    assert knowledge.attribution("belief", beliefs[0].args) == (
        "я так считаю"
    )


def test_lie_does_not_change_world(campaign, catalog):
    _with_log(campaign)
    before = campaign.snapshot()
    base = campaign_view(campaign, None, world=catalog.world)
    lie = Signal(
        "recent_work",
        (
            "faction:blue",
            "3",
            "Демонстрация силы",
            "1",
            "Республика показала силу",
        ),
        channel="hearing",
        source="char_red_003",
        speaker="char_red_003",
        confidence=0.3,
        truth="false",
        day=3,
    )
    view = replace(
        base,
        perception=replace(base.perception, signals=(lie,)),
    )
    knowledge = build_knowledge(
        catalog, campaign, "red", view=view
    )
    facts = knowledge.said_for("recent_work")
    assert facts
    assert facts[0].truth == "false"
    assert campaign.snapshot() == before


def test_dialogue_does_not_reveal_unperceived_work(campaign, catalog):
    _with_log(campaign)
    view = campaign_view(campaign, None, world=catalog.world)
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red", view=view),
    )
    own = session.ask("Что Империя делала в последний ход?")
    assert own.kind == "list"
    assert "Эдикт" in own.text
    hidden = session.ask("Что Республика делала в последний ход?")
    assert hidden.kind in ("no", "unknown")
    assert "Демонстрация силы" not in hidden.text
