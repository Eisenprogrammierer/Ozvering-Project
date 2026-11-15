"""Тесты D7.3: время и темп через текст.

Проверяют данные ``time.json``, разбор «Жду», «Жду до утра» и
«Ускоряю», read-only режим, продвижение ``AutomataCampaign`` только
через явный мост, смену темпа, лимиты и откат в ``TextGame``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import (
    DialogueSession,
    TextGame,
    TimeGuide,
    build_knowledge,
)
from campaign.dialogue.lint import lint_catalog
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"
WAIT = "Жду."
MORNING = "Жду до утра."
SPEED_UP = "Ускоряю."
SPEED_DOWN = "Замедляю."
SPEED_RESET = "Сбрасываю."


class FakeCampaign:
    """Минимальная кампания для проверки расчёта фаз."""

    def __init__(self, elapsed=0.0, speed=1):
        self.elapsed = float(elapsed)
        self.speed = int(speed)
        self.finished = False
        self.outcome = ""
        self.advanced = []

    def time_label(self):
        total = max(0, int(self.elapsed))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "%02d:%02d:%02d" % (hours, minutes, seconds)

    def advance_time(self, dt):
        self.advanced.append(float(dt))
        self.elapsed += float(dt) * self.speed

    def speed_up(self):
        self.speed += 1

    def slow_down(self):
        self.speed = max(1, self.speed - 1)

    def reset_speed(self):
        self.speed = 1


def _campaign() -> AutomataCampaign:
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


def _session(
    catalog,
    campaign,
    allow_actions=True,
) -> DialogueSession:
    knowledge = build_knowledge(
        catalog, campaign, "red", "char_red_002"
    )
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


def test_time_data_loads_and_lints(catalog):
    spec = catalog.time
    assert spec["wait_seconds"] == 240
    assert spec["cycle_seconds"] == 86400
    assert spec["phases"]["noun:morning"]["hour"] == 6
    assert set(spec["speeds"]) == {"up", "down", "reset"}
    assert lint_catalog(catalog) == []


def test_phase_entities_exist_in_lexicon(catalog):
    entity_ids = {
        entry.semantic.get("id")
        for entry in catalog.lexicon
        if entry.semantic.get("kind") == "entity"
    }
    for entity_id in catalog.time["phases"]:
        assert entity_id in entity_ids


# --- разбор ----------------------------------------------------------


def test_wait_parses(session):
    intent = session.intent(WAIT)
    assert intent is not None
    assert intent.kind == "wait"
    assert intent.target == ""


def test_wait_until_parses(session):
    intent = session.intent(MORNING)
    assert intent is not None
    assert intent.kind == "wait"
    assert intent.target == "noun:morning"


def test_speed_parses(session):
    cases = {
        SPEED_UP: "up",
        SPEED_DOWN: "down",
        SPEED_RESET: "reset",
    }
    for phrase, direction in cases.items():
        intent = session.intent(phrase)
        assert intent is not None
        assert intent.kind == "speed"
        assert intent.direction == direction


# --- read-only -------------------------------------------------------


def test_wait_read_only_does_not_touch_campaign(catalog, campaign):
    session = _session(catalog, campaign, allow_actions=False)
    before = campaign.snapshot()
    result = session.time(WAIT)
    assert result.ok is False
    assert result.performed is False
    assert result.reason == "actions_disabled"
    assert result.seconds == pytest.approx(240.0)
    assert "Можно подождать" in result.text
    assert campaign.snapshot() == before


def test_speed_read_only_does_not_touch_campaign(catalog, campaign):
    session = _session(catalog, campaign, allow_actions=False)
    result = session.time(SPEED_UP)
    assert result.ok is False
    assert result.performed is False
    assert result.reason == "actions_disabled"
    assert campaign.speed == 1


# --- ожидание --------------------------------------------------------


def test_wait_advances_time(session, campaign):
    result = session.time(WAIT)
    assert result.ok is True
    assert result.performed is True
    assert result.seconds == pytest.approx(240.0)
    assert result.real_seconds == pytest.approx(240.0)
    assert campaign.elapsed == pytest.approx(240.0)
    assert result.time == campaign.time_label()


def test_wait_respects_speed(session, campaign):
    campaign.speed = 2
    result = session.time(WAIT)
    assert result.performed is True
    assert result.seconds == pytest.approx(240.0)
    assert result.real_seconds == pytest.approx(120.0)
    assert campaign.elapsed == pytest.approx(240.0)


def test_wait_until_phase_delta(catalog, campaign):
    knowledge = build_knowledge(
        catalog, campaign, "red", "char_red_002"
    )
    fake = FakeCampaign(elapsed=3600.0, speed=1)
    guide = TimeGuide(catalog, knowledge, fake, allow_actions=True)
    result = guide.wait("noun:morning")
    assert result.ok is True
    assert result.performed is True
    assert result.seconds == pytest.approx(18000.0)
    assert fake.elapsed == pytest.approx(21600.0)
    assert result.time == "06:00:00"
    assert "утро" in result.text


def test_wait_until_next_cycle(catalog, campaign):
    knowledge = build_knowledge(
        catalog, campaign, "red", "char_red_002"
    )
    fake = FakeCampaign(elapsed=21600.0, speed=1)
    guide = TimeGuide(catalog, knowledge, fake, allow_actions=True)
    result = guide.wait("noun:morning")
    assert result.seconds == pytest.approx(86400.0)
    assert fake.elapsed == pytest.approx(108000.0)


def test_unknown_phase(catalog, campaign):
    knowledge = build_knowledge(
        catalog, campaign, "red", "char_red_002"
    )
    guide = TimeGuide(catalog, knowledge, FakeCampaign(), True)
    result = guide.wait("noun:noon")
    assert result.ok is False
    assert result.reason == "unknown_phase"
    assert "noun:noon" in result.text


def test_no_campaign(catalog, campaign):
    knowledge = build_knowledge(
        catalog, campaign, "red", "char_red_002"
    )
    guide = TimeGuide(catalog, knowledge, None, allow_actions=True)
    result = guide.wait("")
    assert result.ok is False
    assert result.reason == "no_campaign"


def test_finished_campaign_stops_time(catalog, campaign):
    campaign.finished = True
    session = _session(catalog, campaign)
    before = campaign.snapshot()
    result = session.time(WAIT)
    assert result.ok is False
    assert result.reason == "finished"
    assert campaign.snapshot() == before


# --- темп ------------------------------------------------------------


def test_speed_up_and_down(session, campaign):
    up = session.time(SPEED_UP)
    assert up.ok is True
    assert up.performed is True
    assert up.speed == 2
    assert campaign.speed == 2
    down = session.time(SPEED_DOWN)
    assert down.performed is True
    assert down.speed == 1
    assert campaign.speed == 1


def test_speed_reset(session, campaign):
    session.time(SPEED_UP)
    session.time(SPEED_UP)
    assert campaign.speed == 4
    result = session.time(SPEED_RESET)
    assert result.ok is True
    assert result.performed is True
    assert campaign.speed == 1


def test_speed_limit_is_reported(session, campaign):
    result = session.time(SPEED_DOWN)
    assert result.ok is True
    assert result.performed is False
    assert result.reason == "speed_limit"
    assert campaign.speed == 1


# --- TextGame --------------------------------------------------------


def test_textgame_wait(catalog, campaign):
    game = TextGame(_session(catalog, campaign))
    entry = game.submit(WAIT)
    assert entry.kind == "wait"
    assert entry.performed is True
    assert entry.reason == ""
    assert campaign.elapsed == pytest.approx(240.0)


def test_textgame_speed(catalog, campaign):
    game = TextGame(_session(catalog, campaign))
    entry = game.submit(SPEED_UP)
    assert entry.kind == "speed"
    assert entry.action_id == "up"
    assert entry.performed is True
    assert campaign.speed == 2


def test_textgame_undo_restores_time(catalog, campaign):
    game = TextGame(_session(catalog, campaign))
    game.submit(WAIT)
    assert campaign.elapsed > 0.0
    game.submit("/undo")
    assert campaign.elapsed == pytest.approx(0.0)
    assert game.history() == ()
