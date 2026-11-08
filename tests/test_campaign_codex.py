"""Прямые действия из кодекса и команды автоматов в сети."""

from __future__ import annotations

import json
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


def test_codex_actions_target_own_character_and_organ():
    from view.screens.campaign_codex import CampaignCodexScreen

    app, campaign = _app_with_campaign()
    screen = CampaignCodexScreen(app)
    surface = pygame.Surface((1280, 720))

    character_index = next(
        index
        for index, item in enumerate(screen.characters)
        if item.get("side") == campaign.player_side
    )
    screen.select(character_index)
    layout = screen._action_layout()
    assert layout
    rect, kind, owner_id, option = layout[0]
    assert kind == "character"
    assert option["enabled"] is True

    campaign.begin_turn()
    before = campaign.actions_left
    result = screen.apply_action(kind, owner_id, option["id"])
    assert result and result["ok"] is True
    assert campaign.actions_left == before - 1
    assert "мораль" in screen.action_message
    screen.draw(surface)

    screen.set_tab("automata")
    organ_index = next(
        index
        for index, item in enumerate(screen.automata)
        if item.get("kind") == "organ"
        and item.get("side") == campaign.player_side
    )
    screen.select(organ_index)
    layout = screen._action_layout()
    assert layout
    rect, kind, owner_id, option = layout[0]
    assert kind == "organ"
    result = screen.apply_action(kind, owner_id, option["id"])
    assert result and result["ok"] is True
    assert result["organ_id"] == owner_id
    assert "целостность" in screen.action_message
    screen.draw(surface)
    app.quit()


def test_codex_does_not_offer_actions_for_foreign_faction():
    from view.screens.campaign_codex import CampaignCodexScreen

    app, campaign = _app_with_campaign()
    screen = CampaignCodexScreen(app)

    foreign_index = next(
        index
        for index, item in enumerate(screen.characters)
        if item.get("side") != campaign.player_side
    )
    screen.select(foreign_index)
    assert screen._action_options() == []
    assert screen._action_layout() == []
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    app.quit()


def test_network_sends_automaton_command_to_another_automaton():
    from view.screens.automata_network import AutomataNetworkScreen

    app, campaign = _app_with_campaign()
    screen = AutomataNetworkScreen(app, campaign)
    surface = pygame.Surface((1280, 720))
    assert screen.mode == "automata"

    option = next(
        item
        for item in screen._automaton_interaction_options()
        if item["enabled"] and item["targets"]
    )
    assert screen.select_automaton_interaction(option["id"]) is True
    target = option["targets"][0]
    assert screen.select_automaton_target(target["id"]) is True

    before_turn = campaign.turn
    before_budget = campaign.actions_left
    screen.apply_current()

    assert screen.last_result
    assert screen.last_result["kind"] == "automaton"
    assert screen.last_result["source_organ_id"] == screen.selected_organ_id
    assert screen.last_result["target_organ_id"] == target["id"]
    assert campaign.turn == before_turn
    assert campaign.actions_left == before_budget - 1
    screen.draw(surface)
    app.quit()


def test_continue_game_skips_legacy_military_save(tmp_path, monkeypatch):
    from view.support import save_system

    monkeypatch.setattr(save_system, "SAVES_DIR", tmp_path)
    legacy = {
        "version": 2,
        "updated": "2026-11-08 12:00:00",
        "scenario_path": "scenarios/mvp.json",
        "campaign": {"turn": 3},
        "campaign_preset": {"scenario": {"mode": None}},
    }
    compatible = {
        "version": 2,
        "updated": "2026-11-08 11:00:00",
        "scenario_path": "automata",
        "campaign": {"automata": {}, "turn": 5},
    }
    (tmp_path / "legacy.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )
    (tmp_path / "automata.json").write_text(
        json.dumps(compatible), encoding="utf-8"
    )

    from view.app import App

    app = App()
    calls = []
    monkeypatch.setattr(
        app, "load_game", lambda name: calls.append(name) or True
    )
    app.continue_game()
    assert calls == ["automata"]
    app.quit()


def test_load_game_rejects_legacy_military_save_without_opening_rts(
    tmp_path, monkeypatch
):
    from view.support import save_system
    from view.app import App

    monkeypatch.setattr(save_system, "SAVES_DIR", tmp_path)
    legacy = {
        "version": 2,
        "updated": "2026-11-08 12:00:00",
        "scenario_path": "scenarios/mvp.json",
        "campaign": {"turn": 3},
        "campaign_preset": {"scenario": {"mode": None}},
    }
    (tmp_path / "legacy.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )

    app = App()
    current = type(app.manager.current).__name__
    assert app.load_game("legacy") is False
    assert type(app.manager.current).__name__ == current
    assert type(app.manager.current).__name__ != "RTSScreen"
    app.quit()
