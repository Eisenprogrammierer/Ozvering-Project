"""Сюжет как проекция симуляции, а не как сценарий в данных."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parents[1]
STORYLINES = ROOT / "configs" / "storylines"
CAMPAIGNS = ROOT / "configs" / "campaigns"
LORE = (
    "empire_campaign",
    "republic_campaign",
    "cult_campaign",
    "corporation_campaign",
)


@pytest.fixture(autouse=True)
def _reset_audio():
    yield
    try:
        import pygame
    except ImportError:
        return
    if pygame.mixer.get_init():
        pygame.mixer.quit()


def _preset(template_id="empire_campaign", seed=13):
    from campaign.preset import CampaignPresetGenerator
    from campaign.roles import RoleCatalog

    return CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=CAMPAIGNS / ("%s.json" % template_id),
    ).generate(seed=seed)


def _campaign(template_id="empire_campaign", seed=13):
    from campaign.automata import AutomataCampaign

    return AutomataCampaign(_preset(template_id, seed), seed=seed)


def test_lore_storylines_have_no_authored_story():
    for storyline_id in LORE:
        main = json.loads(
            (STORYLINES / ("%s.json" % storyline_id)).read_text(
                encoding="utf-8"
            )
        )
        for key in ("arc", "win_scene", "lose_scene"):
            assert key not in main, (storyline_id, key)
        scenes = json.loads(
            (STORYLINES / ("%s_scenes.json" % storyline_id)).read_text(
                encoding="utf-8"
            )
        )
        assert [scene["type"] for scene in scenes["sequence"]] == [
            "gameplay"
        ], storyline_id
        assert "slides" not in json.dumps(scenes, ensure_ascii=False)


def test_action_records_structured_narrative_fact():
    campaign = _campaign()
    action_id = campaign.available_actions(campaign.player_side)[0]
    result = campaign.perform(campaign.player_side, action_id)
    assert result.get("ok"), result
    assert campaign.narrative
    record = campaign.narrative[-1]
    assert record["kind"] == "action"
    assert record["actor"] and record["target"]
    assert record["action_id"] == action_id
    assert record["assets"]
    assert record["magnitude"] > 0.0


def test_chronicle_text_is_derived_and_not_in_configs():
    from campaign.chronicle import chronicle

    campaign = _campaign()
    action_id = campaign.available_actions(campaign.player_side)[0]
    campaign.perform(campaign.player_side, action_id)
    entries = chronicle(campaign.narrative)
    assert entries
    text = entries[0]["text"]
    assert campaign.player.name in text
    assert campaign.rival.name in text
    configs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "configs").rglob("*.json")
    )
    assert text not in configs


def test_different_simulation_gives_different_chronicle():
    from campaign.chronicle import chronicle

    first = _campaign(seed=13)
    second = _campaign(seed=13)
    first_actions = first.available_actions(first.player_side)
    second_actions = second.available_actions(second.player_side)
    first.perform(first.player_side, first_actions[0])
    second.perform(second.player_side, second_actions[1])
    first_text = [entry["text"] for entry in chronicle(first.narrative)]
    second_text = [entry["text"] for entry in chronicle(second.narrative)]
    assert first_text != second_text


def test_narrative_survives_snapshot_roundtrip():
    from campaign.automata import AutomataCampaign

    campaign = _campaign()
    action_id = campaign.available_actions(campaign.player_side)[0]
    campaign.perform(campaign.player_side, action_id)
    restored = AutomataCampaign(
        _preset(), snapshot=campaign.save_snapshot()
    )
    assert restored.narrative == campaign.narrative
    assert restored.narrative[-1]["assets"]


def test_briefing_and_ending_are_built_from_state():
    from campaign.chronicle import briefing_slides, ending_view

    campaign = _campaign()
    briefing = briefing_slides(campaign)[0]["text"]
    assert "император" in briefing
    assert "Счёт:" in briefing
    assert "Провал при:" in briefing
    campaign.outcome = "win"
    view = ending_view(campaign)
    texts = "\n".join(slide["text"] for slide in view["slides"])
    assert "Итог: преимущество" in texts
    assert "Счёт:" in texts
    assert "Порог поражения:" in texts
    assert view["scores"]["player"] > 0.0


def test_report_decision_enters_narrative():
    campaign = _campaign()
    campaign.dispatch.issue()
    reports = campaign.pending_reports(campaign.player_side)
    assert reports
    report = reports[0]
    campaign.resolve_report(report["id"], report["choices"][0]["id"])
    assert any(record["kind"] == "report" for record in campaign.narrative)


def test_screen_header_uses_state_and_chronicle_feed():
    pygame = pytest.importorskip("pygame")
    from view.app import App
    from view.screens.automata_screen import AutomataScreen

    app = App()
    campaign = _campaign()
    app.automata_campaign = campaign
    app.storyline_interpreter = None
    screen = AutomataScreen(app, campaign)
    assert screen._course_label()
    campaign.player.set_asset("myth", 0.31)
    assert "миф" in screen._risk_text()
    action_id = campaign.available_actions(campaign.player_side)[0]
    campaign.perform(campaign.player_side, action_id)
    assert any(
        entry.get("category") == "chronicle"
        for entry in screen._story_feed()
    )
    screen.draw(pygame.Surface((1280, 720)))
    app.quit()


def test_process_effect_is_linked_to_its_decision():
    from campaign.chronicle import episode_text, episodes

    campaign = _campaign()
    side = campaign.player_side
    action_id = campaign.available_actions(side)[0]
    started = campaign.start_action(side, action_id, duration=10)
    assert started.get("ok"), started
    decision_id = started["process"]["narrative_id"]
    assert decision_id
    campaign.advance_time(10.5)
    effects = [
        record
        for record in campaign.narrative
        if record["kind"] == "action"
        and record["action_id"] == action_id
        and record["actor_side"] == side
    ]
    assert effects
    effect = effects[-1]
    assert effect["cause_id"] == decision_id
    episode = next(
        item for item in episodes(campaign.narrative)
        if effect["id"] in item["ids"]
    )
    assert decision_id in episode["ids"]
    assert "«" in episode_text(episode)


def test_course_biases_aligned_work_and_score_weights():
    campaign = _campaign()
    player = campaign.player
    course = player.course()
    assert course["asset"]
    options = campaign.action_options(campaign.player_side)
    aligned = [
        option for option in options if option["course"]["aligned"]
    ]
    assert aligned
    option = aligned[0]
    raw_cost = option["action"].get("cost") or {}
    if "influence" in raw_cost:
        assert option["cost"]["influence"] < float(
            raw_cost["influence"]
        )
    raw_weights = dict(player.score_assets)
    weights = player.score_weights()
    assert weights != raw_weights
    assert weights[course["asset"]] > raw_weights.get(
        course["asset"], 0.0
    )


def test_world_briefing_is_built_from_config_and_state():
    from campaign.world import load_world
    from campaign.world_briefing import briefing_slides

    config = load_world(ROOT / "configs" / "worlds" / "agora_world.json")
    slides = briefing_slides(config, profile={"name": "Лира"})
    assert slides
    text = slides[0]["text"]
    assert "Агора" in text
    assert "Республика" in text
    assert "Лира" in text
    assert "Режим: свободный мир; история не ограничена." in text
    assert "Горизонт" not in text
    assert "глава" not in text.lower()


def test_world_ending_uses_republic_and_open_mode():
    from campaign.world import WorldEngine, load_world
    from campaign.world_briefing import ending_view

    config = load_world(ROOT / "configs" / "worlds" / "agora_world.json")
    world = WorldEngine(config, profile={"name": "Лира"})
    view = ending_view(world, config)
    text = "\n".join(slide["text"] for slide in view["slides"])
    assert "Республика Агора" in text
    assert "Режим: свободный мир; история не ограничена." in text
    assert "Горизонт" not in text
    assert "глава" not in text.lower()


def _synthetic_record(record_id, delta, kind="action"):
    from campaign.chronicle import narrative_record

    return narrative_record(
        kind,
        1,
        id=record_id,
        actor="Империя",
        actor_side="red",
        target="Республика",
        target_side="blue",
        action_id="show_of_force",
        label="Демонстрация силы",
        success=True,
        assets=[{"scope": "faction", "key": "legitimacy", "delta": delta}],
    )


def test_chronicle_literary_layer_uses_state_and_language_templates():
    from campaign.chronicle import episode_text, episodes, load_phrases

    phrases = load_phrases()
    assert phrases.get("openings")
    quiet = _synthetic_record("n-1-1", 0.01)
    decisive = _synthetic_record("n-1-2", 0.8)
    quiet_text = episode_text(episodes([quiet])[0])
    decisive_text = episode_text(episodes([decisive])[0])
    assert any(
        quiet_text.startswith(item)
        for item in phrases["openings"]["quiet"]
    )
    assert any(
        decisive_text.startswith(item)
        for item in phrases["openings"]["decisive"]
    )
    configs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "configs").rglob("*.json")
    )
    assert quiet_text not in configs
    assert decisive_text not in configs


def test_dialogue_marker_phrases_reach_social_acts():
    from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
    from campaign.dialogue.parser import ChartParser

    catalog = load_dialogue(DEFAULT_DIR)
    markers = catalog.actions.get("markers") or []
    assert markers
    parser = ChartParser(catalog)
    for marker in markers:
        act = marker["act"]
        for phrase in marker["phrases"]:
            parse = parser.parse_best(phrase)
            assert parse is not None, phrase
            assert parse.sem.get("kind") == "social", phrase
            assert parse.sem.get("act") == act, phrase
