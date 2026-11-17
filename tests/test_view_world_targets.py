"""UI-адресация мира: персонаж, предмет и норма как цель действия."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_audio():
    yield
    try:
        import pygame
    except ImportError:
        return
    if pygame.mixer.get_init():
        pygame.mixer.quit()


def _world_screen():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from campaign.world import (
        WorldEngine,
        build_player_profile,
        load_biography,
        load_world,
    )
    from view.app import App
    from view.screens.world_screen import WorldScreen

    variables = {
        "name": "Ирина Свет",
        "origin": "port",
        "family": "clerk",
        "education": "academy",
        "formative": "harbor_fire",
        "vocation": "state",
        "value": "order",
        "value2": "knowledge",
        "flaw": "ambition",
        "patron": "minister",
        "reputation": "respectable",
    }
    profile = build_player_profile(
        variables,
        biography=load_biography(
            ROOT / "configs" / "worlds" / "biography.json"
        ),
        seed=7,
    )
    engine = WorldEngine(
        load_world(ROOT / "configs" / "worlds" / "agora_world.json"),
        profile=profile,
        node_id="agora_government",
        office_id="head_of_government",
        seed=7,
    )
    app = App()
    return pygame, WorldScreen(app, engine), engine


def _world_options(options):
    return [
        option for option in options if option.get("context") == "world"
    ]


def test_character_tab_addresses_person_with_world_action():
    pygame, screen, engine = _world_screen()
    surface = pygame.Surface((1280, 720))
    screen._set_main_tab("characters")
    character = screen._active_characters()[0]
    screen._select_character(character["id"])
    screen.draw(surface)
    options = _world_options(screen._action_options())
    assert options
    option = next(item for item in options if item["enabled"])
    assert option["target_ref"] == {
        "kind": "character",
        "id": character["id"],
    }
    screen._select_action(option)
    screen.draw(surface)
    screen._execute_selected()
    assert screen.last_result["ok"] is True
    assert screen.last_result["action"] == option["id"]
    assert screen.last_result["target"] == character["id"]
    assert engine.actions[option["id"]].get("form")
    pygame.quit()


def test_item_tab_addresses_personal_item():
    pygame, screen, engine = _world_screen()
    surface = pygame.Surface((1280, 720))
    screen._set_main_tab("personality")
    screen._set_subtab(2)
    screen.draw(surface)
    item_id = screen.item_rows[0][1]
    screen._select_item(item_id)
    screen.draw(surface)
    options = _world_options(screen._action_options())
    assert options
    option = next(item for item in options if item["enabled"])
    assert option["target_ref"]["kind"] == "item"
    assert option["target_ref"]["id"] == item_id
    screen._select_action(option)
    screen.draw(surface)
    screen._execute_selected()
    assert screen.last_result["ok"] is True
    assert screen.last_result["target"] == item_id
    assert engine.actions[option["id"]].get("form")
    pygame.quit()


def test_norm_tab_addresses_law():
    pygame, screen, engine = _world_screen()
    surface = pygame.Surface((1280, 720))
    screen._set_main_tab("norms")
    screen.draw(surface)
    assert screen.entity_rows
    norm_id = screen.entity_rows[0][2]
    screen._select_norm(norm_id)
    screen.draw(surface)
    options = _world_options(screen._action_options())
    assert options
    assert "repeal_law" in {item["id"] for item in options}
    option = next(
        item
        for item in options
        if item["id"] == "cite_law" and item["enabled"]
    )
    assert option["target_ref"] == {"kind": "norm", "id": norm_id}
    screen._select_action(option)
    screen.draw(surface)
    screen._execute_selected()
    assert screen.last_result["ok"] is True
    assert screen.last_result["target"] == norm_id
    assert engine.actions["cite_law"].get("form")
    pygame.quit()
