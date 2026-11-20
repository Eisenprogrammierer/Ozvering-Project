"""Оверлеи кампании: список процессов и эмуляция времени."""

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


def _preset(template_id="empire_campaign", seed=11):
    from campaign.preset import CampaignPresetGenerator
    from campaign.roles import RoleCatalog

    return CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=CAMPAIGNS / ("%s.json" % template_id),
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


def test_automata_screen_opens_processes_and_emulation():
    from view.screens.automata_screen import AutomataScreen
    from view.screens.campaign_overlays import (
        ProcessesOverlay,
        TimeEmulationOverlay,
    )

    app, campaign = _app_with_campaign()
    screen = AutomataScreen(app, campaign)
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)

    screen.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            pos=screen._processes_rect().center,
            button=1,
        )
    )
    assert isinstance(app.manager.current, ProcessesOverlay)
    app.manager.pop()

    screen.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            pos=screen._emulation_rect().center,
            button=1,
        )
    )
    assert isinstance(app.manager.current, TimeEmulationOverlay)
    app.quit()


def test_processes_overlay_lists_active_process():
    from view.screens.campaign_overlays import ProcessesOverlay

    app, campaign = _app_with_campaign()
    organ = campaign.player.organs[0]
    started = campaign.perform_organ_interaction(
        campaign.player_side, organ.id, "reinforce"
    )
    assert started["ok"] is True

    overlay = ProcessesOverlay(app, campaign)
    records = overlay._records()
    assert len(records) == 1
    mode, record = records[0]
    assert mode == "active"
    assert record["interaction_id"] == "reinforce"

    surface = pygame.Surface((1280, 720))
    overlay.draw(surface)
    app.quit()


def test_emulation_advances_selected_step_and_can_stop():
    from view.screens.campaign_overlays import TimeEmulationOverlay

    app, campaign = _app_with_campaign()
    overlay = TimeEmulationOverlay(app, campaign)
    overlay.step_index = 0
    before = campaign.elapsed

    overlay.start()
    assert overlay.active is True
    for _ in range(400):
        overlay.update(1 / 60)
        if not overlay.active:
            break

    assert overlay.active is False
    assert campaign.elapsed - before == pytest.approx(3600.0)
    assert overlay.simulated == pytest.approx(3600.0)

    overlay.start()
    second_before = campaign.elapsed
    for _ in range(3):
        overlay.update(1 / 60)
    overlay.pause()
    assert overlay.active is False
    assert overlay.paused is True
    paused_at = overlay.simulated
    assert 0.0 < paused_at < 3600.0

    overlay.start()
    assert overlay.active is True
    assert overlay.simulated == pytest.approx(paused_at)
    for _ in range(400):
        overlay.update(1 / 60)
        if not overlay.active:
            break
    assert overlay.paused is False
    assert campaign.elapsed - second_before == pytest.approx(3600.0)

    overlay.start()
    for _ in range(3):
        overlay.update(1 / 60)
    overlay.stop("Эмуляция остановлена игроком.")
    assert overlay.active is False
    assert overlay.simulated > 0.0
    assert "Пропущено" in overlay.message
    app.quit()


def test_month_emulation_completes_a_long_process():
    from view.screens.campaign_overlays import TimeEmulationOverlay

    app, campaign = _app_with_campaign()
    organ = campaign.player.organs[0]
    started = campaign.perform_organ_interaction(
        campaign.player_side, organ.id, "reform"
    )
    assert started["ok"] is True
    assert started["duration"] >= 7 * 86400.0
    assert campaign.slot_state(campaign.player_side)["used"] == 1

    overlay = TimeEmulationOverlay(app, campaign)
    overlay.step_index = 3  # месяц
    overlay.start()
    for _ in range(2000):
        overlay.update(1 / 60)
        if not overlay.active:
            break

    assert overlay.active is False
    assert campaign.slot_state(campaign.player_side)["used"] == 0
    process = next(
        item
        for item in campaign.processes
        if item.get("interaction_id") == "reform"
    )
    assert process["status"] == "done"
    app.quit()


def test_advance_simulation_ignores_speed_multiplier():
    _app, campaign = _app_with_campaign()
    campaign.set_speed(32)
    before = campaign.elapsed
    campaign.advance_simulation(3600.0, tick=False)
    assert campaign.elapsed - before == pytest.approx(3600.0)


def test_interaction_durations_are_realistic():
    _app, campaign = _app_with_campaign()
    organ = campaign.player.organs[0]
    reform = next(
        item
        for item in organ.interactions
        if item.get("id") == "reform"
    )
    duration = campaign._interaction_duration("organ", reform)
    assert duration >= 7 * 86400.0

    character = campaign.character_options(campaign.player_side)[1]
    promote = next(
        item
        for item in campaign.faction(
            campaign.player_side
        ).character_interactions
        if item.get("id") == "promote"
    )
    assert campaign._interaction_duration(
        "character", promote
    ) >= 7 * 86400.0
    assert character["id"]
