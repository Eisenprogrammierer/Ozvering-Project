"""Headless-тест экрана чата: вычисленный тон и отправка.

Экран не содержит диалоговой логики и не даёт выбрать регистр вручную:
тон вычисляют отношения и убеждения говорящего. Тест рисует кадр в
dummy-видеодрайвере и проверяет состояние, не открывая окно.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


@pytest.fixture(autouse=True)
def _reset_audio():
    yield
    try:
        import pygame
    except ImportError:
        return
    if pygame.mixer.get_init():
        pygame.mixer.quit()


def _chat_screen():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from campaign.automata import AutomataCampaign
    from campaign.preset import CampaignPresetGenerator
    from campaign.roles import RoleCatalog
    from view.app import App
    from view.screens.dialogue_chat import DialogueChatScreen

    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    app = App()
    app.automata_campaign = AutomataCampaign(
        generator.generate(seed=13), seed=13
    )
    return pygame, DialogueChatScreen(app)


def test_chat_always_uses_computed_style():
    _pygame, screen = _chat_screen()
    assert screen.session is not None
    assert screen.session.is_auto()
    assert screen._style_label()
    assert screen._style_reason()
    assert not hasattr(screen, "_select_style")
    assert not hasattr(screen, "_style_rows")


def test_chat_draws_computed_style_caption():
    pygame, screen = _chat_screen()
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)


def test_chat_send_adds_player_and_agent_messages():
    _pygame, screen = _chat_screen()
    screen.input_text = "Кто ты?"
    screen._send()
    history = screen._history()
    assert history[0]["role"] == "player"
    assert history[0]["text"] == "Кто ты?"
    assert history[-1]["role"] == "agent"
    assert history[-1]["text"]


def test_chat_orders_only_for_player_side():
    _pygame, screen = _chat_screen()
    campaign = screen.campaign
    screen.side = campaign.player_side
    screen.character_id = screen._default_character(screen.side)
    screen.session = screen._session()
    assert screen.session.bridge.allow_actions is True
    screen.input_text = "Покажи силу"
    screen._send()
    entry = screen._history()[-1]
    assert entry["kind"] == "action"
    assert "Приказ исполнен" in entry["text"]

    screen.side = campaign.rival_side
    screen.character_id = screen._default_character(screen.side)
    screen.session = screen._session()
    assert screen.session.bridge.allow_actions is False
