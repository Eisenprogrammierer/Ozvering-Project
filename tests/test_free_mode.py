"""Свободный режим: жизнь без мандата, фракции и военной кампании.

Тесты используют production-контент явными путями: общий ``conftest``
подменяет каталоги на компактные фикстуры, а свободный режим должен
проверяться на реальных ролях, сюжете и мире.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"
STORYLINES = CONFIGS / "storylines"
WORLDS = CONFIGS / "worlds"
ROLES = CONFIGS / "roles"
ARCHETYPES = CONFIGS / "characters" / "archetypes.json"

FREE_ACTIONS = {
    "street_musician": "perform",
    "school_student": "study",
    "artisan": "craft",
}


@pytest.fixture(autouse=True)
def _reset_audio():
    yield
    try:
        import pygame
    except ImportError:
        return
    if pygame.mixer.get_init():
        pygame.mixer.quit()


@pytest.fixture
def storyline():
    from view.support.storyline import load_storyline

    data = load_storyline("free_life", directory=str(STORYLINES))
    assert data is not None
    return data


@pytest.fixture
def world():
    from campaign.world import load_world

    return load_world(WORLDS / "agora_world.json")


def _identity(archetype_id="street_musician", name="Лира"):
    return {
        "name": name,
        "gender": "female",
        "origin": "trade_house",
        "origin_label": "Торговый дом",
        "value": "freedom",
        "value_label": "Свобода",
        "flaw": "ambition",
        "flaw_label": "Амбициозность",
        "summary": "Торговый дом · Свобода",
        "biography": "Вы выросли среди весов и расписок.",
        "traits": {"creativity": 0.1},
        "archetype_id": archetype_id,
    }


def _free_app(archetype_id="street_musician", name="Лира"):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pytest.importorskip("pygame")
    from campaign.roles import RoleCatalog
    from view.app import App
    from view.support.storyline import load_storyline

    app = App()
    # Общий conftest подменяет каталог ролей на фикстуры; свободный
    # режим проверяем на production-роли.
    app.role_catalog = RoleCatalog.load(ROLES)
    app.selected_role = app.role_catalog.select("free_citizen")
    app.selected_archetype_id = archetype_id
    data = load_storyline("free_life", directory=str(STORYLINES))
    assert data is not None
    identity = _identity(archetype_id, name)
    app.start_storyline(data, player_identity=identity)
    return app


def _reach_world(app):
    interp = app.storyline_interpreter
    assert app.manager.current.__class__.__name__ == "VisualNovelScreen"
    interp.advance()
    app._play_next_scene()
    return app.manager.current


def test_free_role_exists_without_faction_or_office():
    from campaign.roles import RoleCatalog

    catalog = RoleCatalog.load(ROLES)
    role = catalog.select("free_citizen")
    assert role.available is True
    assert role.storyline_id == "free_life"
    assert role.archetype_id == "street_musician"
    assert role.faction_kind == "none"
    assert role.leadership == "none"
    assert role.start_faction == ""
    assert role.start_offices == ()
    assert "free" in role.tags
    assert "free" in role.storyline_tags
    assert "free_citizen" in [item.id for item in catalog.available_roles()]


def test_free_storyline_declares_start_for_every_archetype(storyline, world):
    from campaign.identity import load_archetypes_catalog

    assert storyline["world_path"] == "configs/worlds/agora_world.json"
    assert storyline["identity_editor"] is True
    assert storyline["free_start"]
    assert storyline["win_conditions"] == [
        {"type": "world_outcome", "value": "win"}
    ]
    assert storyline["lose_conditions"] == [
        {"type": "world_outcome", "value": "lose"}
    ]
    # Сюжет начинается с представления и заканчивается миром.
    assert storyline["scenes"][0]["type"] == "visual_novel"
    assert storyline["scenes"][-1]["type"] == "world"

    catalog = load_archetypes_catalog(ARCHETYPES, use_cache=False)
    assert catalog is not None
    archetype_ids = {item.id for item in catalog.playable()}
    assert set(storyline["free_start"]) == archetype_ids

    node_ids = {item["id"] for item in world["nodes"]}
    office_ids = {item["id"] for item in world["offices"]}
    for archetype_id, entry in storyline["free_start"].items():
        assert entry["node_id"] in node_ids, archetype_id
        assert entry["office_id"] in office_ids, archetype_id


def test_free_world_starts_every_archetype(storyline, world):
    from campaign.world import WorldEngine, profile_from_identity

    profile = profile_from_identity(_identity(), seed=7)
    assert profile["name"] == "Лира"
    assert profile["origin"] == "Торговый дом"
    assert profile["values"] == ["Свобода"]
    assert profile["archetype_id"] == "street_musician"
    assert profile["traits"], "черты личности должны дойти до мира"

    for archetype_id, entry in storyline["free_start"].items():
        engine = WorldEngine(
            world,
            profile=profile,
            node_id=entry["node_id"],
            office_id=entry["office_id"],
            seed=7,
        )
        assert engine.attached is True, archetype_id
        assert engine.player_node_id == entry["node_id"]
        assert engine.player_office_id == entry["office_id"]
        assert engine.day == 1


def test_free_archetypes_get_their_own_available_action(world, storyline):
    from campaign.world import WorldEngine, profile_from_identity

    profile = profile_from_identity(_identity(), seed=7)
    for archetype_id, action_id in FREE_ACTIONS.items():
        entry = storyline["free_start"][archetype_id]
        engine = WorldEngine(
            world,
            profile=profile,
            node_id=entry["node_id"],
            office_id=entry["office_id"],
            seed=7,
        )
        actions = engine.available_actions(engine.player_node_id)
        assert action_id in actions, (archetype_id, actions)
        result = engine.execute(action_id, engine.player_node_id)
        assert result["ok"] is True, result
        assert result["action"] == action_id
        assert result["outcome"] in ("success", "failure")
        assert engine.day == 1, "действие не должно само завершать день"


def test_role_select_offers_free_citizen_and_archetypes():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pytest.importorskip("pygame")
    from campaign.roles import RoleCatalog
    from view.app import App
    from view.screens.role_select import RoleSelectScreen

    app = App()
    app.role_catalog = RoleCatalog.load(ROLES)
    screen = RoleSelectScreen(app)
    ids = [role.id for role in screen.roles]
    assert "free_citizen" in ids

    screen.select("free_citizen")
    assert screen.current_role.id == "free_citizen"
    screen.open_archetypes()
    picker = app.manager.current
    assert picker.__class__.__name__ == "ArchetypeSelectScreen"
    picker.select("school_student")
    picker.apply()
    assert app.selected_archetype_id == "school_student"
    assert app.selected_archetype_label == "Школьник"


def test_free_mode_skips_military_campaign_and_binds_office():
    app = _free_app("street_musician")
    assert app.state is None
    assert app.engine is None
    assert app.time_system is None
    assert app.selected_role.id == "free_citizen"
    assert app.world_config["id"] == "agora_world"

    screen = _reach_world(app)
    assert screen.__class__.__name__ == "WorldScreen"
    assert app.world.attached is True
    assert app.world.player_node_id == "agora_street"
    assert app.world.player_office_id == "street_musician"
    assert app.world.profile["name"] == "Лира"
    assert "perform" in app.world.available_actions(
        app.world.player_node_id
    )


def test_free_mode_school_student_start():
    app = _free_app("school_student", name="Нил")
    screen = _reach_world(app)
    assert screen.__class__.__name__ == "WorldScreen"
    assert app.world.player_node_id == "knowledge_faculty_law"
    assert app.world.player_office_id == "student"
    assert "study" in app.world.available_actions(app.world.player_node_id)


def test_free_mode_save_and_load_returns_world_screen(monkeypatch, tmp_path):
    import view.support.save_system as save_system
    import view.support.storyline as storyline_support

    monkeypatch.setattr(save_system, "SAVES_DIR", tmp_path)
    monkeypatch.setattr(storyline_support, "STORYLINES_DIR", str(STORYLINES))

    app = _free_app("street_musician")
    screen = _reach_world(app)
    screen._end_day()
    assert app.world.day == 2
    path = app.save_game("free-mode")
    assert path is not None and Path(path).exists()

    from view.app import App

    loaded = App()
    assert loaded.load_game("free-mode") is True
    assert loaded.selected_role.id == "free_citizen"
    assert loaded.state is None
    assert loaded.engine is None
    assert loaded.time_system is None
    assert loaded.world.day == 2
    assert loaded.world.player_node_id == "agora_street"
    assert loaded.world.player_office_id == "street_musician"
    assert loaded.world.profile["name"] == "Лира"
    assert loaded.manager.current.__class__.__name__ == "WorldScreen"


def test_free_mode_world_outcome_drives_storyline():
    app = _free_app("street_musician")
    screen = _reach_world(app)

    app.world.outcome = "win"
    screen._sync_storyline()
    assert app.storyline_interpreter.state["world"]["outcome"] == "win"
    assert app.storyline_interpreter.check_win_conditions() is True
    assert app.storyline_interpreter.check_lose_conditions() is False
    app.check_storyline_end_of_day()
    assert app.pending_storyline_outcome == "win"
    assert app.storyline_interpreter.finished is True

    app = _free_app("street_musician")
    screen = _reach_world(app)
    app.world.outcome = "lose"
    screen._sync_storyline()
    assert app.storyline_interpreter.check_win_conditions() is False
    assert app.storyline_interpreter.check_lose_conditions() is True
    app.check_storyline_end_of_day()
    assert app.pending_storyline_outcome == "lose"
