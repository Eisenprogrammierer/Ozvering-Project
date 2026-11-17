"""Headless-тест экрана чата: авто-режим, причина выбора и отправка.

Экран не содержит диалоговой логики, но именно он передаёт пустой
``style_id`` как ``set_style(None)`` и показывает причину автовыбора.
Тест рисует кадр в dummy-видеодрайвере и проверяет состояние, не
открывая окно.
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


def test_chat_starts_in_auto_mode():
    _pygame, screen = _chat_screen()
    assert screen.style_id == ""
    assert screen.session is not None
    assert screen.session.is_auto()
    rows = screen._style_rows()
    assert rows
    assert rows[0][1] == ""
    assert rows[0][2] == "авто"
    assert all(
        style_id for _rect, style_id, _label in rows[1:]
    )


def test_chat_auto_reason_comes_from_decision():
    pygame, screen = _chat_screen()
    assert screen._style_reason()
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)


def test_chat_manual_style_switches_and_keeps_reason():
    _pygame, screen = _chat_screen()
    screen._select_style("mentor")
    assert screen.style_id == "mentor"
    assert screen.session.style_id == "mentor"
    assert not screen.session.is_auto()
    assert screen._style_spec() is not None
    screen._select_style("")
    assert screen.style_id == ""
    assert screen.session.is_auto()


def test_chat_send_adds_player_and_agent_messages():
    _pygame, screen = _chat_screen()
    screen.input_text = "Кто ты?"
    screen._send()
    history = screen._history()
    assert history[0]["role"] == "player"
    assert history[0]["text"] == "Кто ты?"
    assert history[-1]["role"] == "agent"
    assert history[-1]["text"]
