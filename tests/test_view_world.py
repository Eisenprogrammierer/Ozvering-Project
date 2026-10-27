import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_audio():
    yield
    try:
        import pygame
    except ImportError:
        return
    if pygame.mixer.get_init():
        pygame.mixer.quit()


def _app_and_automaton():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from view.app import App
    from view.screens.automaton_select import AutomatonSelectScreen
    from view.screens.character_creation import CharacterCreationScreen
    from view.support.storyline import load_storyline

    app = App()
    app.selected_role = app.role_catalog.select("world_actor")
    storyline = load_storyline("world_demo")
    app.start_storyline(storyline)
    interp = app.storyline_interpreter
    assert app.manager.current.__class__.__name__ == "VisualNovelScreen"
    assert app.campaign_preset is None
    assert app.world_config["id"] == "agora_world"
    interp.advance()
    app._play_next_scene()
    assert isinstance(app.manager.current, CharacterCreationScreen)
    interp.variables.update(
        {
            "name": "Ирина Свет",
            "gender": "female",
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
    )
    screen = app.manager.current
    screen.current_step = len(screen.steps)
    screen._finish()
    automaton = app.manager.current
    assert isinstance(automaton, AutomatonSelectScreen)
    surface = pygame.Surface((1280, 720))
    automaton.draw(surface)
    return app, automaton, pygame


def test_world_role_reaches_automaton_and_world_screens():
    app, automaton, pygame = _app_and_automaton()
    automaton._select_node("knowledge_press")
    offices = {item["id"]: item for item in automaton.office_rows}
    assert offices["printer"]["enabled"] is True
    assert offices["editor"]["enabled"] is False
    assert "публичность" in offices["editor"]["reason"]
    assert automaton.selected_office_id == "printer"
    automaton._start()
    assert app.world is not None
    assert app.world.attached is True
    assert app.world.player_node_id == "knowledge_press"
    assert app.world.player_office_id == "printer"
    assert app.manager.current.__class__.__name__ == "VisualNovelScreen"
    app.storyline_interpreter.advance()
    app._play_next_scene()
    screen = app.manager.current
    assert screen.__class__.__name__ == "WorldScreen"
    assert screen.selected_target_id == "knowledge_press"
    assert len(screen._action_options()) == 47
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    pygame.quit()


def test_world_screen_executes_action_and_advances_day():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from campaign.world import (
        WorldEngine,
        build_player_profile,
        load_biography,
    )
    from campaign.world import load_world
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
        variables, biography=load_biography(), seed=7
    )
    engine = WorldEngine(
        load_world(),
        profile=profile,
        node_id="agora_government",
        office_id="head_of_government",
        seed=7,
    )
    app = App()
    screen = WorldScreen(app, engine)
    screen._select_target("knowledge_press")
    option = next(
        item for item in screen._action_options() if item["id"] == "inspect"
    )
    assert option["enabled"] is True
    screen._select_action(option)
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    screen._execute_selected()
    assert screen.last_result["ok"] is True
    assert screen.last_result["outcome"] == "success"
    assert screen.last_result["action"] == "inspect"
    screen.draw(surface)
    screen._end_day()
    assert engine.day == 2
    assert screen.last_result["outcome"] == "day"
    screen.draw(surface)
    pygame.quit()


def test_world_save_and_load_restores_world_screen():
    app, automaton, pygame = _app_and_automaton()
    automaton._start()
    app.storyline_interpreter.advance()
    app._play_next_scene()
    screen = app.manager.current
    screen._select_target("knowledge_press")
    option = next(
        item for item in screen._action_options() if item["id"] == "inspect"
    )
    screen._select_action(option)
    screen._execute_selected()
    screen._end_day()
    slot = "test_world_roundtrip"
    path = app.save_game(slot)
    assert path is not None
    try:
        assert app.load_game(slot) is True
        assert app.world is not None
        assert app.world.day == 2
        assert app.world.player_node_id == "agora_government"
        assert app.manager.current.__class__.__name__ == "WorldScreen"
        assert app._is_world_campaign() is True
        surface = pygame.Surface((1280, 720))
        app.manager.current.draw(surface)
    finally:
        Path(path).unlink(missing_ok=True)
        pygame.quit()
