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


def test_long_report_scrolls_without_switching_reports():
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    campaign.dispatch.issue()
    campaign.dispatch.issue()
    overlay = ReportsOverlay(app, campaign)
    current = overlay._current()[0]
    assert current is not None
    current["text"] = "Доклад " * 400
    index = overlay.index
    limit = overlay._max_scroll(current)
    assert limit > 0
    assert len(overlay._queue()) >= 2

    overlay.handle_event(
        pygame.event.Event(pygame.MOUSEWHEEL, {"y": -1})
    )
    assert overlay.body_scroll == 1
    assert overlay.index == index

    overlay.body_scroll = limit + 50
    overlay.handle_event(
        pygame.event.Event(pygame.MOUSEWHEEL, {"y": -1})
    )
    assert overlay.body_scroll == limit
    assert overlay.index == index
    assert len(overlay._body_lines(current)) == overlay._line_limit()

    overlay.draw(pygame.Surface((1280, 720)))
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


def test_verify_choice_shows_action_cost():
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    report = campaign.dispatch.issue()
    overlay = ReportsOverlay(app, campaign)
    verify = next(
        item for item in report["choices"] if item["id"] == "verify"
    )
    assert overlay._choice_label(report, verify).endswith("· 1")
    app.quit()


def test_report_overlay_shows_contradiction_counter_line():
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    dispatch = campaign.dispatch
    dispatch.contradiction_enabled = True
    dispatch.contradiction_chance = 1.0
    dispatch.assets = ["supply"]
    chosen = [
        character
        for character in campaign.player.characters
        if str(getattr(character, "campaign_post_id", "") or "")
    ][:2]
    queue = list(chosen)

    def _source(_faction, _asset):
        return queue.pop(0) if queue else chosen[0]

    dispatch._source = _source
    first = dispatch.issue()
    first["band"] = "other-band"
    second = dispatch.issue()

    overlay = ReportsOverlay(app, campaign)
    overlay.index = 0
    lines = overlay._body_lines(second)

    assert second["contradicts"] == first["id"]
    assert any("Ранее" in line for line in lines)
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


def test_emulation_opens_reports_from_interrupt_banner():
    from view.screens.campaign_overlays import TimeEmulationOverlay
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    campaign.dispatch.issue()
    overlay = TimeEmulationOverlay(app, campaign)
    overlay.draw(pygame.Surface((1280, 720)))

    overlay.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            pos=overlay.reports_rect.center,
            button=1,
        )
    )

    assert isinstance(app.manager.current, ReportsOverlay)
    app.quit()


def test_story_feed_delays_third_party_news():
    from view.screens.automata_screen import AutomataScreen

    app, campaign = _app_with_campaign()
    campaign.dispatch.interval = 100.0
    campaign.dispatch._progress = 0.0
    campaign.dispatch.tick(100.0)
    screen = AutomataScreen(app, campaign)

    news = [
        entry
        for entry in campaign.story_events
        if entry.get("category") == "news"
    ]
    assert news
    assert all(entry.get("release_at") for entry in news)
    assert not any(
        entry.get("category") == "news"
        for entry in screen._story_feed()
    )

    campaign.elapsed = max(
        float(entry["release_at"]) for entry in news
    )
    feed = screen._story_feed()
    assert any(entry.get("category") == "news" for entry in feed)
    app.quit()


def _intercept(campaign, delay=0.0):
    dispatch = campaign.dispatch
    dispatch.interception_enabled = True
    dispatch.interception_config.update(
        {
            "chance": 1.0,
            "influence_weight": 0.0,
            "delay_seconds": float(delay),
            "expire_seconds": 100000.0,
            "max_pending": 6,
            "price_actions": 1,
        }
    )
    foreign = next(
        faction
        for side, faction in campaign.factions.items()
        if side != campaign.player_side
    )
    report = dispatch.issue(foreign)
    assert report is not None
    dispatch.auto_resolve(report)
    return campaign.interceptions(campaign.player_side)[-1]


def test_overlay_hides_sealed_intercept_and_opens_it(monkeypatch):
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    item = _intercept(campaign)
    overlay = ReportsOverlay(app, campaign)
    assert overlay._current()[0] is item
    assert overlay._can_open(item)

    sealed = overlay._intercept_lines(item)
    assert any("скрыты" in line for line in sealed)
    assert not any("Решение фракции" in line for line in sealed)
    overlay.draw(pygame.Surface((1280, 720)))

    spent = []
    monkeypatch.setattr(
        campaign,
        "_spend_player_action",
        lambda side: spent.append(str(side)),
    )
    overlay.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            pos=overlay._intercept_rect().center,
            button=1,
        )
    )

    assert item["status"] == "open"
    assert spent == [campaign.player_side]
    assert overlay.message
    opened = overlay._intercept_lines(item)
    assert any("Решение фракции" in line for line in opened)
    overlay.draw(pygame.Surface((1280, 720)))
    app.quit()


def test_overlay_waits_for_intercept_delivery():
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    item = _intercept(campaign, delay=3600.0)
    overlay = ReportsOverlay(app, campaign)

    assert not overlay._can_open(item)
    overlay.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            pos=overlay._intercept_rect().center,
            button=1,
        )
    )
    assert item["status"] == "sealed"
    assert "пути" in overlay.message

    campaign.elapsed = float(item["available_at"])
    assert overlay._can_open(item)
    overlay.draw(pygame.Surface((1280, 720)))
    app.quit()


def test_overlay_uses_countermeasure_after_opening(monkeypatch):
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    item = _intercept(campaign)
    overlay = ReportsOverlay(app, campaign)
    spent = []
    monkeypatch.setattr(
        campaign,
        "_spend_player_action",
        lambda side: spent.append(str(side)),
    )
    overlay._open_intercept(item)
    assert item["status"] == "open"

    options = campaign.intercept_counters(item["id"])
    assert [option["id"] for option in options] == ["warn", "expose"]
    overlay.draw(pygame.Surface((1280, 720)))
    rect = overlay._counter_rects(options)[0]
    overlay.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1
        )
    )

    assert item["counter"] == "warn"
    assert spent == [campaign.player_side, campaign.player_side]
    assert "предупреждён" in overlay.message
    lines = overlay._intercept_lines(item)
    assert any("предупреждён" in line for line in lines)
    overlay.draw(pygame.Surface((1280, 720)))
    app.quit()


def test_overlay_countermeasure_waits_for_revealed_motive():
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    item = _intercept(campaign)
    overlay = ReportsOverlay(app, campaign)
    campaign.open_intercept(item["id"])
    options = campaign.intercept_counters(item["id"])
    overlay.draw(pygame.Surface((1280, 720)))
    rect = overlay._counter_rects(options)[1]
    overlay.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1
        )
    )

    assert item.get("counter") is None
    assert "мотив" in overlay.message
    item["motive"] = "выгода"
    item["motive_revealed"] = True
    options = campaign.intercept_counters(item["id"])
    assert options[1]["available"] is True
    overlay.draw(pygame.Surface((1280, 720)))
    app.quit()


def test_story_feed_shows_city_news_after_delay():
    from view.screens.automata_screen import AutomataScreen

    app, campaign = _app_with_campaign()
    dispatch = campaign.dispatch
    dispatch.interval = 10 ** 9
    dispatch.news_config.update(
        {"interval_seconds": 100.0, "delay_seconds": 3600.0}
    )
    for key in ("city", "prices", "street"):
        block = dispatch.news_config[key]
        block["enabled"] = key == "city"
        block["chance"] = 1.0 if key == "city" else 0.0

    dispatch.tick(100.0)
    screen = AutomataScreen(app, campaign)
    city = [
        entry
        for entry in campaign.story_events
        if entry.get("news_type") == "city"
    ]
    assert city
    assert not any(
        entry.get("news_type") == "city"
        for entry in screen._story_feed()
    )
    assert campaign.decision_pending(campaign.player_side) is False

    campaign.elapsed = float(city[-1]["release_at"])
    feed = screen._story_feed()
    assert any(entry.get("news_type") == "city" for entry in feed)
    screen.draw(pygame.Surface((1280, 720)))
    app.quit()


def test_story_feed_scrolls_through_all_events(monkeypatch):
    from view.screens.automata_screen import AutomataScreen, RIGHT_RECT

    app, campaign = _app_with_campaign()
    campaign.story_events = [
        {
            "id": "story-%d" % index,
            "category": "news",
            "title": "Вести %d" % index,
            "text": "Событие номер %d." % index,
            "turn": index,
            "visible": True,
        }
        for index in range(12)
    ]
    screen = AutomataScreen(app, campaign)
    assert len(screen._story_feed()) == 12

    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: RIGHT_RECT.center)
    screen.handle_event(
        pygame.event.Event(pygame.MOUSEWHEEL, {"y": 1})
    )
    assert screen.log_scroll == 1

    screen.log_scroll = 99
    screen.draw(pygame.Surface((1280, 720)))
    assert screen.log_scroll == 11

    screen.handle_event(
        pygame.event.Event(pygame.MOUSEWHEEL, {"y": -1})
    )
    assert screen.log_scroll == 10
    screen.draw(pygame.Surface((1280, 720)))
    app.quit()


def test_countermeasures_explain_target_and_benefit():
    from view.screens.campaign_reports import ReportsOverlay

    app, campaign = _app_with_campaign()
    item = _intercept(campaign)
    campaign.open_intercept(item["id"])
    overlay = ReportsOverlay(app, campaign)
    options = campaign.intercept_counters(item["id"])
    warn = next(
        option for option in options if option["id"] == "warn"
    )

    assert "лидер" in warn["label"].lower()
    assert "лидер" in warn["benefit"].lower()
    assert "мораль" in warn["benefit"].lower()
    lines = overlay._intercept_lines(item)
    assert any("Контрмеры" in line for line in lines)
    assert any("мораль" in line for line in lines)
    overlay.draw(pygame.Surface((1280, 720)))
    app.quit()
