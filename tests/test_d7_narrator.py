"""Тесты D7.4: нарративный слой поверх истории кампании.

Проверяют данные ``narrator.json``, сбор ``story_events``/``log``/
``events``, видимость, дедупликацию работ, подписи важности, форм и
исходов, лимиты и хронологию, read-only режим, ``/look`` и откат
не затрагивается.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import (
    DialogueSession,
    Narrator,
    TextGame,
    build_knowledge,
)
from campaign.dialogue.lint import lint_catalog
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"
WAIT = "Жду."


class FakeCampaign:
    """Минимальная кампания с готовыми списками истории."""

    def __init__(self, story_events=None, log=None, events=None):
        self.story_events = list(story_events or [])
        self.log = list(log or [])
        self.events = list(events or [])
        self.elapsed = 0.0
        self.speed = 1
        self.finished = False
        self.outcome = ""

    def time_label(self):
        total = max(0, int(self.elapsed))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "%02d:%02d:%02d" % (hours, minutes, seconds)

    def advance_time(self, dt):
        self.elapsed += float(dt) * self.speed


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
    speaker="char_red_002",
    side="red",
) -> DialogueSession:
    knowledge = build_knowledge(catalog, campaign, side, speaker)
    return DialogueSession(
        catalog,
        knowledge,
        style_id="neutral",
        allow_actions=allow_actions,
        campaign=campaign,
    )


def _story(turn=1, title="Событие", text="текст", severity=0.5,
           visible=True):
    return {
        "turn": turn,
        "title": title,
        "text": text,
        "severity": severity,
        "visible": visible,
    }


def _work(turn=1, form="information", success=True):
    return {
        "turn": turn,
        "actor_name": "Республика",
        "target_name": "Империя",
        "label": "Опубликовать утечку",
        "form": form,
        "success": success,
        "text": "работа выполнена",
    }


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


def test_narrator_data_loads_and_lints(catalog):
    spec = catalog.narrator
    assert spec["limit"] == 5
    assert spec["max_limit"] == 20
    assert spec["visible_only"] is True
    assert set(spec["kinds"]) >= {
        "story",
        "work",
        "organ",
        "automaton",
        "character",
    }
    assert lint_catalog(catalog) == []


def test_narrator_forms_cover_work_and_production_forms(catalog):
    forms = catalog.narrator["forms"]
    assert forms["work"] == "работа"
    assert forms["information"] == "сведения"
    assert forms["coercion"] == "принуждение"


# --- источники -------------------------------------------------------


def test_story_visibility_filter(catalog):
    fake = FakeCampaign(
        story_events=[
            _story(title="Видно", text="открытое", visible=True),
            _story(title="Скрыто", text="тайное", visible=False),
        ]
    )
    narration = Narrator(catalog, fake).describe()
    assert narration.ok is True
    assert "открытое" in narration.text
    assert "тайное" not in narration.text
    assert len(narration.entries) == 1
    assert narration.entries[0].source == "story"


def test_work_comes_from_log_without_event_duplicate(catalog):
    fake = FakeCampaign(
        log=[_work()],
        events=[
            {"turn": 1, "kind": "work", "text": "краткая копия"},
        ],
    )
    narration = Narrator(catalog, fake).describe()
    assert "работа выполнена" in narration.text
    assert "краткая копия" not in narration.text
    assert len(narration.entries) == 1
    assert narration.entries[0].kind == "work"
    assert narration.entries[0].source == "log"


def test_organ_automaton_character_templates(catalog):
    fake = FakeCampaign(
        events=[
            {"turn": 1, "kind": "organ", "text": "орган сработал"},
            {"turn": 1, "kind": "automaton", "text": "автомат решил"},
            {"turn": 1, "kind": "character", "text": "герой устал"},
        ]
    )
    narration = Narrator(catalog, fake).describe()
    assert "Орган: орган сработал" in narration.text
    assert "Автомат: автомат решил" in narration.text
    assert "Персонаж: герой устал" in narration.text
    assert {entry.kind for entry in narration.entries} == {
        "organ",
        "automaton",
        "character",
    }


def test_unknown_kind_uses_fallback(catalog):
    fake = FakeCampaign(
        events=[{"turn": 1, "kind": "mystery", "text": "нечто"}]
    )
    narration = Narrator(catalog, fake).describe()
    assert "нечто" in narration.text
    assert "mystery" not in narration.text
    assert narration.entries[0].kind == "mystery"


# --- подписи ---------------------------------------------------------


def test_severity_labels(catalog):
    fake = FakeCampaign(
        story_events=[
            _story(turn=1, title="Тихо", text="a", severity=0.2),
            _story(turn=1, title="Средне", text="b", severity=0.5),
            _story(turn=1, title="Громко", text="c", severity=0.9),
        ]
    )
    narration = Narrator(catalog, fake).describe()
    assert "слух: «Тихо»" in narration.text
    assert "новость: «Средне»" in narration.text
    assert "важное: «Громко»" in narration.text


def test_form_and_outcome_labels(catalog):
    fake = FakeCampaign(
        log=[
            _work(turn=1, form="coercion", success=False),
            _work(turn=2, form="information", success=True),
        ]
    )
    narration = Narrator(catalog, fake).describe()
    assert "принуждение" in narration.text
    assert "неудача" in narration.text
    assert "сведения" in narration.text
    assert "успех" in narration.text


# --- лимит и порядок -------------------------------------------------


def test_limit_keeps_latest_and_clamps_to_max(catalog):
    events = [
        _story(turn=index, title="t%d" % index, text="text %d" % index)
        for index in range(25)
    ]
    fake = FakeCampaign(story_events=events)
    narration = Narrator(catalog, fake).describe(limit=999)
    assert len(narration.entries) == catalog.narrator["max_limit"]
    assert narration.entries[0].turn == 5
    assert narration.entries[-1].turn == 24


def test_chronology_and_default_limit(catalog):
    fake = FakeCampaign(
        story_events=[
            _story(turn=3, title="Три", text="three"),
            _story(turn=1, title="Один", text="one"),
            _story(turn=2, title="Два", text="two"),
        ]
    )
    narration = Narrator(catalog, fake).describe()
    assert len(narration.entries) == 3
    assert "one" in narration.lines[0]
    assert "two" in narration.lines[1]
    assert "three" in narration.lines[2]


def test_source_priority_within_turn(catalog):
    fake = FakeCampaign(
        story_events=[_story(turn=1, title="Сцена", text="story")],
        log=[_work(turn=1)],
        events=[{"turn": 1, "kind": "organ", "text": "organ"}],
    )
    narration = Narrator(catalog, fake).describe()
    assert [entry.kind for entry in narration.entries] == [
        "story",
        "work",
        "organ",
    ]


def test_custom_limit_keeps_tail(catalog):
    fake = FakeCampaign(
        story_events=[
            _story(turn=index, title="t%d" % index, text="text %d" % index)
            for index in range(6)
        ]
    )
    narration = Narrator(catalog, fake).describe(limit=2)
    assert [entry.turn for entry in narration.entries] == [4, 5]


# --- пустота и read-only --------------------------------------------


def test_empty_campaign(catalog):
    narration = Narrator(catalog, FakeCampaign()).describe()
    assert narration.ok is True
    assert narration.lines == ()
    assert narration.text == catalog.narrator["messages"]["empty"]


def test_no_campaign(catalog):
    narration = Narrator(catalog, None).describe()
    assert narration.ok is False
    assert narration.reason == "no_campaign"
    assert narration.text == catalog.narrator["messages"]["no_campaign"]


def test_narrate_is_read_only(catalog, campaign):
    session = _session(catalog, campaign, allow_actions=False)
    before = campaign.save_snapshot()
    narration = session.narrate(limit=20)
    assert narration.ok is True
    assert campaign.save_snapshot() == before


# --- TextGame --------------------------------------------------------


def test_textgame_look_after_wait(catalog, campaign):
    game = TextGame(_session(catalog, campaign))
    empty = game.submit("/look")
    assert empty.kind == "narrate"
    assert empty.reply == catalog.narrator["messages"]["empty"]
    game.submit(WAIT)
    seen = game.submit("/look")
    assert seen.kind == "narrate"
    assert "Что видно" in seen.reply
    narration = game.session.narrate(limit=20)
    assert narration.entries
    assert all(entry.kind for entry in narration.entries)


def test_textgame_look_alias(catalog, campaign):
    game = TextGame(_session(catalog, campaign))
    game.submit(WAIT)
    short = game.submit("/l")
    full = game.submit("/осмотреться")
    assert short.kind == "narrate"
    assert full.kind == "narrate"
    assert short.reply == full.reply
    assert "Что видно" in full.reply


def test_textgame_look_is_not_undoable(catalog, campaign):
    game = TextGame(_session(catalog, campaign))
    game.submit(WAIT)
    game.submit("/look")
    assert len(game.history()) == 1
    assert game.history()[0].kind == "wait"
    done = game.submit("/undo")
    assert done.kind == "command"
    assert campaign.elapsed == pytest.approx(0.0)
