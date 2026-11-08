"""Личность героя и экраны, которые её используют."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.identity import IdentityError, load_identity_catalog
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = ROOT / "configs" / "campaigns"


@pytest.fixture(autouse=True)
def _reset_audio():
    yield
    try:
        import pygame
    except ImportError:
        return
    if pygame.mixer.get_init():
        pygame.mixer.quit()


def _preset(template_id="empire_campaign", seed=11):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=CAMPAIGNS / ("%s.json" % template_id),
    )
    return generator.generate(seed=seed)


def test_identity_catalog_builds_and_applies_to_preset():
    catalog = load_identity_catalog()
    assert len(catalog.option_ids("origins")) == 6
    identity = catalog.build(
        {
            "name": "Мария Вельд",
            "gender": "female",
            "origin": "church_orphan",
            "vocation": "court",
            "value": "order",
            "flaw": "zeal",
            "trait": "discipline",
        }
    )
    assert identity["name"] == "Мария Вельд"
    assert identity["origin_label"] == "Церковный приют"
    assert identity["trait"] == "discipline"
    assert identity["biography"]
    assert identity["needs"]
    assert identity["traits"]["discipline"] > 0.2

    preset = _preset()
    seed = preset.seed
    assets = [dict(faction["assets"]) for faction in preset.factions]
    faction_seeds = [
        character["seed"] for character in preset.characters
    ]
    preset.apply_player_identity(identity)

    player = preset.player_character
    assert player["name"] == "Мария Вельд"
    assert player["biography"] == identity["biography"]
    assert player["trait"] == "discipline"
    assert preset.player_faction["leader_name"] == "Мария Вельд"
    assert preset.player_faction["role_title"] == "императрица"
    assert preset.player_role_title == "императрица"
    organization = preset.organization(
        preset.player_faction["organization_id"]
    )
    assert organization["leader_name"] == "Мария Вельд"
    assert organization["leader_title"] == "императрица"
    assert preset.seed == seed
    assert [faction["assets"] for faction in preset.factions] == assets
    assert [
        character["seed"] for character in preset.characters
    ] == faction_seeds
    assert preset.summary()["player_identity"]["name"] == "Мария Вельд"
    assert preset.as_dict()["player_identity"]["name"] == "Мария Вельд"


def test_identity_catalog_rejects_broken_option(tmp_path):
    path = tmp_path / "identity.json"
    path.write_text(
        '{"schema": 1, "genders": {"male": {}}, '
        '"origins": {}, "vocations": {}, "values": {}, "flaws": {}}',
        encoding="utf-8",
    )
    with pytest.raises(IdentityError):
        load_identity_catalog(path, use_cache=False)


def test_identity_editor_screen_builds_and_draws():
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from view.app import App
    from view.screens.identity_editor import IdentityEditorScreen

    app = App()
    captured = []
    screen = IdentityEditorScreen(
        app,
        {"title": "Тестовая кампания"},
        on_start=captured.append,
    )
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    screen.select_section("origin")
    before = screen.values["origin"]
    screen.cycle("origin", 1)
    assert screen.values["origin"] != before
    screen.name = "Анна"
    screen.start()
    assert screen.started is True
    assert captured[0]["name"] == "Анна"
    assert captured[0]["origin"] == screen.values["origin"]
    app.quit()


def test_role_select_opens_identity_editor_only_for_flagged_storyline(
    monkeypatch,
):
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pytest.importorskip("pygame")
    import view.support.storyline as storyline_module
    from view.app import App
    from view.screens.role_select import RoleSelectScreen

    storyline = {
        "storyline_id": "world_demo",
        "title": "С личностью",
        "identity_editor": True,
        "scenes": [],
    }
    monkeypatch.setattr(
        storyline_module, "load_storyline", lambda sid: storyline
    )
    app = App()
    screen = RoleSelectScreen(app)
    screen.select("world_actor")
    screen.continue_to_storyline()
    assert app.manager.current.__class__.__name__ == "IdentityEditorScreen"
    app.quit()


def test_campaign_codex_shows_characters_and_organs():
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from view.app import App
    from view.screens.campaign_codex import CampaignCodexScreen

    app = App()
    app.campaign_preset = _preset()
    screen = CampaignCodexScreen(app)
    assert len(screen.characters) == len(app.campaign_preset.characters)
    expected_automata = [
        item
        for item in app.campaign_preset.automata
        if item.get("kind") != "organization"
    ]
    assert len(screen.automata) == len(expected_automata)
    assert any(
        item["kind"] == "organ" for item in screen.automata
    )
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    screen.set_tab("automata")
    assert screen.tab == "automata"
    organ_index = next(
        index
        for index, item in enumerate(screen.automata)
        if item["kind"] == "organ"
    )
    screen.select(organ_index)
    screen.scroll_by(4)
    screen.draw(surface)
    app.quit()


def test_automata_campaign_uses_player_identity():
    from campaign.automata import AutomataCampaign

    catalog = load_identity_catalog()
    identity = catalog.build(
        {
            "name": "Пётр",
            "origin": "frontier",
            "vocation": "army",
            "value": "honor",
            "flaw": "doubt",
            "trait": "courage",
        }
    )
    preset = _preset()
    preset.apply_player_identity(identity)
    campaign = AutomataCampaign(preset, seed=11)
    assert campaign.player.record["leader_name"] == "Пётр"
    leader = next(
        character
        for character in campaign.player.characters
        if character.name == "Пётр"
    )
    assert leader.campaign_faction_id == preset.player_faction_id
    assert leader.personality.values["courage"] > 0.7
