"""Окно докладов: текст не залезает за кнопки, выбор закрывает доклад."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

pygame = pytest.importorskip("pygame")

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = ROOT / "configs" / "campaigns"


@pytest.fixture(autouse=True)
def _reset_audio():
    yield
    try:
        if pygame.mixer.get_init():
            pygame.mixer.quit()
    except Exception:
        pass


def _preset(seed=11):
    from campaign.preset import CampaignPresetGenerator
    from campaign.roles import RoleCatalog

    return CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=CAMPAIGNS / "empire_campaign.json",
    ).generate(seed=seed)


def _app_with_campaign():
    from campaign.automata import AutomataCampaign
    from view.app import App

    preset = _preset()
    campaign = AutomataCampaign(preset, seed=11)
    app = App()
    app.storyline_interpreter = None
    app.campaign_preset = preset
    app.automata_campaign = campaign
    return app, campaign


def test_screen_opens_reports_overlay():
    from view.screens.automata_screen import AutomataScreen
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    screen = AutomataScreen(app, campaign)
    screen.draw(pygame.Surface((1280, 720)))

    screen.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            pos=screen._reports_rect().center,
            button=1,
        )
    )
    assert isinstance(app.manager.current, ReportsOverlay)
    app.quit()


def test_overlay_wraps_text_above_choices():
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    report = campaign.dispatch.issue()
    assert report is not None
    report["text"] = "Доклад " * 400
    overlay = ReportsOverlay(app, campaign)
    lines = overlay._body_lines(report)
    body = overlay._body_rect()
    rects = overlay._choice_rects(report)
    line_h = app.font_small.get_height() + 5
    last_bottom = body.y + 10 + len(lines) * line_h
    assert lines
    assert last_bottom <= rects[0].top
    for line in lines:
        assert app.font_small.size(line)[0] <= body.width

    surface = pygame.Surface((1280, 720))
    overlay.draw(surface)
    app.quit()


def test_choice_click_resolves_without_touching_assets(monkeypatch):
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    report = campaign.dispatch.issue()
    calls = []
    monkeypatch.setattr(
        campaign.player,
        "add_asset",
        lambda *args, **kwargs: calls.append(args),
    )
    overlay = ReportsOverlay(app, campaign)
    rects = overlay._choice_rects(report)
    trust = rects[0]

    overlay.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=trust.center, button=1
        )
    )

    assert campaign.report(report["id"])["status"] == "resolved"
    assert calls == []
    assert overlay.message
    overlay.draw(pygame.Surface((1280, 720)))
    app.quit()


def test_empty_overlay_is_readable():
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    overlay = ReportsOverlay(app, campaign)
    assert overlay._current()[0] is None
    overlay.draw(pygame.Surface((1280, 720)))
    app.quit()


def test_main_feed_shows_story_events_but_not_decisions():
    from view.screens.automata_screen import AutomataScreen

    app, campaign = _app_with_campaign()
    campaign.story_events.append(
        {
            "id": "story-1",
            "category": "news",
            "title": "Сводка",
            "text": "На границе тихо.",
            "turn": 1,
            "visible": True,
        }
    )
    campaign.dispatch.issue()
    screen = AutomataScreen(app, campaign)

    feed = screen._story_feed()
    assert [item["id"] for item in feed] == ["story-1"]
    screen.draw(pygame.Surface((1280, 720)))
    app.quit()


def test_emulation_stops_when_decision_appears():
    from view.screens.campaign_overlays import TimeEmulationOverlay

    app, campaign = _app_with_campaign()
    overlay = TimeEmulationOverlay(app, campaign)
    overlay.start()
    assert overlay.active is True

    campaign.dispatch.issue()
    overlay.update(0.1)

    assert overlay.active is False
    assert overlay.paused is True
    assert overlay.interrupted is True
    assert "требует решения" in overlay.message

    overlay.start()
    assert overlay.active is False
    assert "требует решения" in overlay.message
    app.quit()


def test_emulation_refuses_to_start_with_pending_decision():
    from view.screens.campaign_overlays import TimeEmulationOverlay

    app, campaign = _app_with_campaign()
    campaign.dispatch.issue()
    overlay = TimeEmulationOverlay(app, campaign)

    overlay.start()

    assert overlay.active is False
    assert overlay.interrupted is True
    assert "требует решения" in overlay.message

    report = campaign.pending_reports(campaign.player_side)[0]
    campaign.resolve_report(report["id"], "trust")
    overlay.start()
    assert overlay.active is True
    app.quit()
