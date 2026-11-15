"""Каталог архетипов: загрузка, фильтры и перенос на персонажа."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from campaign.identity import (
    ArchetypeCatalog,
    IdentityError,
    load_archetypes_catalog,
)
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGNS = ROOT / "configs" / "campaigns"


def _preset(template_id="empire_campaign", seed=11):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=CAMPAIGNS / ("%s.json" % template_id),
    )
    return generator.generate(seed=seed)


def test_archetype_catalog_loads_and_filters():
    catalog = load_archetypes_catalog()
    assert catalog is not None
    assert len(catalog.playable()) >= 8
    ids = [item.id for item in catalog.all()]
    assert len(ids) == len(set(ids))
    assert "street_musician" in ids
    assert "school_student" in ids

    street = [item.id for item in catalog.by_layer("street")]
    assert "street_musician" in street
    assert all(
        item.social_layer == "street" for item in catalog.by_layer("street")
    )
    music = [item.id for item in catalog.by_tag("music")]
    assert "street_musician" in music


def test_archetype_catalog_rejects_unknown_fields():
    with pytest.raises(IdentityError):
        ArchetypeCatalog(
            {
                "schema": 1,
                "archetypes": [
                    {
                        "id": "robot",
                        "label": "Робот",
                        "entity_kind": "robot",
                    }
                ],
            }
        )


def test_archetype_keys_match_trait_and_need_models():
    import bdi
    import warfare as W

    catalog = load_archetypes_catalog()
    assert catalog is not None
    needs = set(bdi.load_bdi().needs)
    traits = set(W.TRAITS)
    for item in catalog.all():
        assert set(item.traits) <= traits, item.id
        assert set(item.needs) <= needs, item.id
        assert set(item.priority_needs) <= needs, item.id


def test_archetype_catalog_rejects_duplicate_ids():
    with pytest.raises(IdentityError):
        ArchetypeCatalog(
            {
                "schema": 1,
                "archetypes": [
                    {"id": "same", "label": "Первый"},
                    {"id": "same", "label": "Второй"},
                ],
            }
        )


def test_preset_applies_archetype_to_player():
    preset = _preset()
    player = preset.player_character
    before_needs = dict(player["needs"])
    before_personality = dict(player["personality"])

    preset.apply_player_identity(
        {"name": "Тестовый герой", "archetype_id": "street_musician"}
    )

    player = preset.player_character
    assert player["name"] == "Тестовый герой"
    assert player["archetype"] == "street_musician"
    assert player["archetype_id"] == "street_musician"
    assert player["social_layer"] == "street"
    assert player["start_faction"] == ""
    assert player["archetype_scenes"] == ["street", "market", "temple"]
    assert player["archetype_priority_needs"] == [
        "creativity",
        "status",
        "friendship",
    ]
    assert player["needs"]["creativity"] > before_needs["creativity"]
    assert (
        player["personality"]["creativity"]
        > before_personality["creativity"]
    )


def test_preset_ignores_missing_archetype():
    preset = _preset()
    player = preset.player_character
    before = dict(player["needs"])
    before_archetype = player.get("archetype")
    preset.apply_player_identity(
        {"name": "Без архетипа", "archetype_id": "does_not_exist"}
    )
    player = preset.player_character
    assert player["name"] == "Без архетипа"
    assert player.get("archetype") == before_archetype
    assert "archetype_id" not in player
    assert player["needs"] == before


def test_archetype_screen_shows_more_than_four():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pytest.importorskip("pygame")
    from view.app import App
    from view.screens.archetype_select import ArchetypeSelectScreen

    app = App()
    screen = ArchetypeSelectScreen(app)
    assert len(screen.all_archetypes) >= 8
    screen.select("street_musician")
    assert screen.selected_id == "street_musician"
    screen.apply()
    assert app.selected_archetype_id == "street_musician"
    assert app.selected_archetype_label == "Уличный музыкант"
    app.quit()


def test_identity_editor_limits_sections_for_archetype():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pytest.importorskip("pygame")
    from view.app import App
    from view.screens.identity_editor import IdentityEditorScreen

    app = App()
    app.selected_archetype_id = "street_musician"
    screen = IdentityEditorScreen(app, {"title": "Тест"})
    assert screen.sections == ["gender", "origin", "value", "flaw"]
    screen.select_section("vocation")
    assert screen.selected_section != "vocation"
    identity = screen.build_identity()
    assert "vocation" not in identity
    assert "trait" not in identity
    assert identity["origin"]
    assert identity["value"]
    app.quit()
