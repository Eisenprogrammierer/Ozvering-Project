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


def test_automaton_select_office_click_selects_office():
    app, automaton, pygame = _app_and_automaton()
    automaton._select_node("knowledge_press")
    rect, option = next(
        (item for item in automaton._office_rows_rects() if item[1]["enabled"])
    )
    event = pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": rect.center}
    )
    automaton.handle_event(event)
    assert automaton.selected_office_id == option["id"]
    pygame.quit()


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
    assert screen.main_tab == "organizations"
    assert screen.selected_target_id in [
        item["id"] for item in screen.engine.organization_groups()["allied"]
    ]
    assert screen.engine.node(screen.selected_target_id) is not None
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

    # §7 №31: при неактивном окне экран делает ограниченный фоновый догон,
    # а при возврате фокуса секунды не «выстреливают» днями.
    day_before = engine.day
    app.active = False
    screen.clock.seconds_per_day = 1.0
    screen.update(1.0)
    assert engine.day == day_before + 1
    app.active = True
    screen.update(1.0)
    assert engine.day == day_before + 1
    pygame.quit()


def test_world_screen_tabs_character_actions_and_personality():
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
    surface = pygame.Surface((1280, 720))
    assert screen.main_tab == "organizations"
    assert screen.selected_target_id != engine.player_node_id
    assert screen.selected_target_id in [
        item["id"] for item in engine.organization_groups()["allied"]
    ]
    assert any(
        item["enabled"] and not (item["action"] or {}).get("career")
        for item in screen._action_options()
    )

    screen._set_subtab(1)
    screen.draw(surface)
    assert screen._active_organizations() == []
    assert screen.selected_target_id is None

    screen._set_main_tab("characters")
    screen._set_subtab(0)
    screen.draw(surface)
    assert screen._active_characters()
    assert screen.entity_rows

    character = screen._active_characters()[0]
    screen._select_character(character["id"])
    screen.draw(surface)
    assert screen.action_rows
    option = next(item for item in screen._action_options() if item["enabled"])
    screen._select_action(option)
    screen.draw(surface)
    assert screen.selected_action_id == option["id"]
    screen._execute_selected()
    assert screen.last_result["context"] == "character"

    screen._set_main_tab("personality")
    screen._set_subtab(1)
    screen.draw(surface)
    assert screen.skill_rows
    screen._select_skill("administration")
    screen.draw(surface)
    assert screen.selected_skill_id == "administration"

    screen._set_subtab(2)
    screen.draw(surface)
    assert screen.item_rows
    item_id = screen.item_rows[0][1]
    screen._select_item(item_id)
    screen.draw(surface)
    assert screen.selected_item_id == item_id
    pygame.quit()


def test_automaton_select_can_reemploy_existing_world():
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
    from view.screens.automaton_select import AutomatonSelectScreen

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
    engine.end_day()
    day_before = engine.day
    app = App()
    screen = AutomatonSelectScreen(app, engine=engine)
    assert screen.reemployment is True
    assert screen.engine is engine
    screen._select_node("knowledge_press")
    option = next(item for item in screen.office_rows if item["enabled"])
    screen._select_office(option["id"])
    screen._start()
    # §7 №29: тот же мир, тот же день, новая должность — не новый движок.
    assert app.world is engine
    assert engine.day == day_before
    assert engine.attached is True
    assert app.manager.current.__class__.__name__ == "WorldScreen"
    pygame.quit()


def test_app_offline_progress_is_bounded_by_saved_at_and_limit():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    import time
    from types import SimpleNamespace

    from campaign.world import (
        WorldEngine,
        build_player_profile,
        load_biography,
        load_world,
    )
    from view.app import App

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
    engine.seconds_per_day = 10.0
    engine.max_offline_days = 2
    stub = SimpleNamespace(world=engine)
    # 100 секунд при 10 с/день — 10 дней, но лимит среза — 2.
    days = App._apply_offline_progress(
        stub, {"saved_at": time.time() - 100.0}
    )
    assert days == 2
    assert engine.day == 3
    # Старый сейв без saved_at не двигает мир.
    day_after = engine.day
    assert App._apply_offline_progress(stub, {}) == 0
    assert engine.day == day_after
    pygame.quit()


def test_world_art_prefers_real_assets_and_falls_back():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    pygame.display.init()
    pygame.font.init()
    pygame.display.set_mode((64, 64))
    from view.ui.asset_loader import AssetLoader
    from view.ui.world_art import WorldArt

    assert AssetLoader.USE_PLACEHOLDERS is True
    assert AssetLoader.asset_exists("items/folder_open") is True
    assert AssetLoader.asset_exists("characters/nobody") is False

    real = AssetLoader.load_asset("items/folder_open", (32, 32))
    placeholder = AssetLoader.load("items/folder_open", (32, 32))
    assert real.get_size() == (32, 32)
    assert pygame.image.tobytes(real, "RGBA") != pygame.image.tobytes(
        placeholder, "RGBA"
    )

    fallback = AssetLoader.load_asset("characters/nobody", (32, 40))
    assert fallback.get_size() == (32, 40)

    art = WorldArt("agora_world")
    assert art.portrait("nobody", (24, 30)).get_size() == (24, 30)
    assert art.skill_icon("administration", (20, 20)).get_size() == (20, 20)
    assert art.background((64, 64)).get_size() == (64, 64)

    tiled = WorldArt("agora_world")
    tile_path = os.path.join(
        AssetLoader.IMAGES_DIR, "items", "folder_open.png"
    )
    tiled._tile_files = lambda: [tile_path]
    assert tiled.background((256, 128)).get_size() == (256, 128)
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
