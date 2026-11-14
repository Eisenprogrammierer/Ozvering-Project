"""Тесты D7.2: перемещение через текст.

Проверяют данные ``movement.json``, разбор фраз движения, маршрут по
геометрии стороны игрока, режим read-only, обновление
``ConversationState.location`` и откат в ``TextGame``. Кампания при
перемещении не меняется.
"""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import (
    DialogueSession,
    MovementGuide,
    TextGame,
    build_knowledge,
)
from campaign.dialogue.lint import lint_catalog
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"
GO = "Иду к Абверу."
CAPITAL = "Отправляюсь в столицу."


def _campaign() -> AutomataCampaign:
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


def _session(
    catalog,
    campaign,
    speaker="char_red_002",
    side="red",
    allow_actions=True,
) -> DialogueSession:
    knowledge = build_knowledge(catalog, campaign, side, speaker)
    return DialogueSession(
        catalog,
        knowledge,
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
def session(catalog, campaign):
    return _session(catalog, campaign)


# --- данные и линт ---------------------------------------------------


def test_movement_data_loads_and_lints(catalog):
    spec = catalog.movement
    assert spec["defaults"]["red"] == "imperial_staff"
    assert spec["places"]["organ:red:abwehr"] == {"red": "abwehr"}
    assert spec["places"]["noun:capital"]["red"] == "imperial_staff"
    assert [band["id"] for band in spec["bands"]] == [
        "near",
        "middle",
        "far",
    ]
    assert lint_catalog(catalog) == []


def test_every_organ_has_a_place(catalog):
    places = catalog.movement["places"]
    missing = []
    for entry in catalog.lexicon:
        if entry.type != "organ" or not entry.id.startswith("organ:"):
            continue
        _, side, node = entry.id.split(":")
        if places.get(entry.id, {}).get(side) != node:
            missing.append(entry.id)
    assert missing == []


# --- разбор ----------------------------------------------------------


def test_go_phrase_parses_as_move(session):
    intent = session.intent(GO)
    assert intent is not None
    assert intent.kind == "move"
    assert intent.target == "organ:red:abwehr"


def test_depart_phrase_parses_as_move(session):
    intent = session.intent(CAPITAL)
    assert intent is not None
    assert intent.kind == "move"
    assert intent.target == "noun:capital"


# --- маршрут ---------------------------------------------------------


def test_plan_route_uses_geometry_and_band(catalog, campaign):
    knowledge = build_knowledge(catalog, campaign, "red", "char_red_002")
    state = SimpleNamespace(location="imperial_staff")
    guide = MovementGuide(catalog, knowledge, campaign, state)
    result = guide.plan("organ:red:abwehr")
    assert result.ok is True
    assert result.moved is False
    assert result.node == "abwehr"
    assert result.band == "near"
    assert result.distance == pytest.approx(1.5)
    assert result.path == ("imperial_staff", "abwehr")
    assert "Абвер" in result.text
    assert "рядом" in result.text
    assert state.location == "imperial_staff"


def test_band_thresholds(catalog, campaign):
    knowledge = build_knowledge(catalog, campaign, "red", "char_red_002")
    guide = MovementGuide(catalog, knowledge, campaign)
    assert guide.band_for(0.5)[0] == "near"
    assert guide.band_for(1.5)[0] == "near"
    assert guide.band_for(1.51)[0] == "middle"
    assert guide.band_for(3.0)[0] == "middle"
    assert guide.band_for(3.01)[0] == "far"
    assert guide.band_for(99.0)[0] == "far"


def test_movement_map_follows_player_side(catalog, campaign):
    knowledge = build_knowledge(catalog, campaign, "blue")
    assert knowledge.player_side == "red"
    session = DialogueSession(
        catalog,
        knowledge,
        style_id="neutral",
        allow_actions=True,
        campaign=campaign,
    )
    assert session.state.location == "imperial_staff"
    result = session.travel(GO)
    assert result.moved is True
    assert result.node == "abwehr"


# --- read-only и перемещение ----------------------------------------


def test_read_only_plans_but_does_not_move(catalog, campaign):
    session = _session(catalog, campaign, allow_actions=False)
    before = campaign.snapshot()
    result = session.travel(GO)
    assert result.ok is False
    assert result.moved is False
    assert result.reason == "actions_disabled"
    assert result.band == "near"
    assert "Перемещение выключено" in result.text
    assert session.state.location == "imperial_staff"
    assert campaign.snapshot() == before


def test_move_updates_only_dialogue_location(session, campaign):
    before = campaign.snapshot()
    result = session.travel(GO)
    assert result.ok is True
    assert result.moved is True
    assert result.reason == ""
    assert result.node == "abwehr"
    assert session.state.location == "abwehr"
    assert session.state_snapshot()["location"] == "abwehr"
    assert campaign.snapshot() == before


def test_already_at_destination(session):
    result = session.travel(CAPITAL)
    assert result.ok is True
    assert result.moved is False
    assert result.reason == "already"
    assert result.node == "imperial_staff"
    assert session.state.location == "imperial_staff"


# --- отказы ----------------------------------------------------------


def test_unknown_place(catalog, campaign, session):
    guide = MovementGuide(
        catalog,
        session.knowledge,
        campaign,
        session.state,
        allow_actions=True,
    )
    result = guide.move("noun:zoo")
    assert result.ok is False
    assert result.reason == "unknown_place"
    assert "noun:zoo" in result.text


def test_no_geometry(catalog, campaign):
    knowledge = build_knowledge(catalog, campaign, "red", "char_red_002")
    guide = MovementGuide(
        catalog,
        knowledge,
        campaign=None,
        state=SimpleNamespace(location="imperial_staff"),
        allow_actions=True,
    )
    result = guide.move("organ:red:abwehr")
    assert result.ok is False
    assert result.reason == "no_geometry"


def test_no_path_when_node_is_missing(catalog, campaign):
    knowledge = build_knowledge(catalog, campaign, "red", "char_red_002")
    spec = copy.deepcopy(catalog.movement)
    spec["places"]["noun:nowhere"] = {"red": "nowhere"}
    fake = SimpleNamespace(movement=spec)
    guide = MovementGuide(
        fake,
        knowledge,
        campaign,
        SimpleNamespace(location="imperial_staff"),
        allow_actions=True,
    )
    result = guide.move("noun:nowhere")
    assert result.ok is False
    assert result.reason == "no_path"


def test_no_start(catalog):
    knowledge = SimpleNamespace(
        side="red",
        player_side="red",
        player_organ_id="",
        name=lambda entity_id: entity_id,
    )
    spec = copy.deepcopy(catalog.movement)
    spec["defaults"] = {}
    guide = MovementGuide(
        SimpleNamespace(movement=spec),
        knowledge,
        campaign=None,
        state=SimpleNamespace(location=""),
        allow_actions=True,
    )
    result = guide.move("noun:capital")
    assert result.ok is False
    assert result.reason == "no_start"


# --- TextGame --------------------------------------------------------


def test_textgame_move_read_only(catalog, campaign):
    game = TextGame(_session(catalog, campaign, allow_actions=False))
    entry = game.submit(GO)
    assert entry.kind == "move"
    assert entry.performed is False
    assert entry.reason == "actions_disabled"
    assert game.session.state.location == "imperial_staff"


def test_textgame_move_performed(catalog, campaign):
    game = TextGame(_session(catalog, campaign))
    entry = game.submit(GO)
    assert entry.kind == "move"
    assert entry.performed is True
    assert entry.action_id == "abwehr"
    assert game.session.state.location == "abwehr"
    assert game.history() == (entry,)


def test_textgame_undo_restores_location(catalog, campaign):
    game = TextGame(_session(catalog, campaign))
    game.submit(GO)
    assert game.session.state.location == "abwehr"
    game.submit("/undo")
    assert game.session.state.location == "imperial_staff"
    assert game.history() == ()
