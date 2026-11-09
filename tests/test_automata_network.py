"""Экран сети автоматов и влияние на органы."""

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


def test_network_screen_draws_tree_and_applies_interaction():
    from campaign.automata import AutomataCampaign
    from view.app import App
    from view.screens.automata_network import AutomataNetworkScreen

    preset = _preset()
    campaign = AutomataCampaign(preset, seed=11)
    app = App()
    app.storyline_interpreter = None
    app.campaign_preset = preset
    screen = AutomataNetworkScreen(app, campaign)
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)

    assert screen.selected_organ_id
    assert screen.organ_rect(screen.selected_organ_id) is not None

    assert screen.select_faction("blue") is False
    assert screen.selected_faction_side == campaign.player_side
    assert screen._organ() is not None
    screen.select_faction("red")

    organ = campaign.player.organs[0]
    screen.select_organ(organ.id)
    option = next(
        item
        for item in screen._interaction_options()
        if item["enabled"]
    )
    before_turn = campaign.turn
    before_budget = campaign.actions_left
    screen.select_interaction(option["id"])
    screen.apply_interaction()

    assert campaign.turn == before_turn
    assert campaign.actions_left == before_budget - 1
    assert screen.last_result
    assert screen.last_result["ok"] is True
    assert screen.last_result["organ_id"] == organ.id
    screen.draw(surface)
    app.quit()


def test_network_screen_selects_character_and_applies_character_action():
    from campaign.automata import AutomataCampaign
    from view.app import App
    from view.screens.automata_network import AutomataNetworkScreen

    preset = _preset()
    campaign = AutomataCampaign(preset, seed=11)
    app = App()
    app.storyline_interpreter = None
    screen = AutomataNetworkScreen(app, campaign)
    surface = pygame.Surface((1280, 720))

    mode_event = pygame.event.Event(
        pygame.MOUSEBUTTONDOWN,
        pos=screen._characters_tab_rect.center,
        button=1,
    )
    screen.handle_event(mode_event)
    assert screen.mode == "characters"
    character = screen._characters()[1]
    assert screen.select_character(character["id"]) is True
    option = next(
        item
        for item in screen._character_interaction_options()
        if item["enabled"]
    )
    screen.select_character_interaction(option["id"])
    before_turn = campaign.turn
    screen.apply_character_interaction()
    assert campaign.turn == before_turn
    assert screen.last_result
    assert screen.last_result["ok"] is True
    assert screen.last_result["character_id"] == character["id"]
    screen.draw(surface)
    app.quit()


def test_automata_screen_selects_description_and_opens_network():
    from campaign.automata import AutomataCampaign
    from view.app import App
    from view.screens.automata_screen import AutomataScreen
    from view.screens.automata_network import AutomataNetworkScreen

    preset = _preset()
    campaign = AutomataCampaign(preset, seed=11)
    app = App()
    app.storyline_interpreter = None
    screen = AutomataScreen(app, campaign)
    action_id = campaign.available_actions(campaign.player_side)[0]
    screen.selected_action_id = action_id
    selected = screen._selected_option()
    assert selected is not None
    assert selected["action"]["description"]
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)

    buttons = [
        screen._execute_rect(),
        screen._speed_up_rect(),
        screen._slow_down_rect(),
        screen._network_rect(),
        screen._codex_rect(),
        screen._finish_rect(),
    ]
    for index, first in enumerate(buttons):
        for second in buttons[index + 1 :]:
            assert not first.colliderect(second), (
                "кнопки нижней панели пересекаются: %s и %s"
                % (first, second)
            )

    screen.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            pos=screen._network_rect().center,
            button=1,
        )
    )
    assert isinstance(app.manager.current, AutomataNetworkScreen)
    app.manager.current.draw(surface)
    app.quit()


def test_speed_buttons_cancel_acceleration_without_going_below_one():
    from campaign.automata import AutomataCampaign
    from view.app import App
    from view.screens.automata_network import AutomataNetworkScreen

    campaign = AutomataCampaign(_preset(), seed=11)
    app = App()
    app.storyline_interpreter = None
    screen = AutomataNetworkScreen(app, campaign)
    surface = pygame.Surface((1280, 720))

    campaign.speed_up()
    campaign.speed_up()
    assert campaign.speed == 4
    screen.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            pos=screen._slow_down_rect.center,
            button=1,
        )
    )
    assert campaign.speed == 2
    assert "Ускорение отменено" in screen.message
    screen.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            pos=screen._slow_down_rect.center,
            button=1,
        )
    )
    assert campaign.speed == 1
    screen.handle_event(
        pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            pos=screen._slow_down_rect.center,
            button=1,
        )
    )
    assert campaign.speed == 1
    assert "Минимальная скорость" in screen.message
    screen.draw(surface)
    app.quit()
