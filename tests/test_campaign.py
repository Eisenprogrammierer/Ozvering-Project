"""Тесты ролей игрока и детерминированных кампанийных пресетов.

Ядро тестов не требует pygame: каталог ролей, генератор и хранилище — чистый
Python. Интеграция с ``view.support.scenario`` проверяется отдельно и
пропускается, если нет numpy.
"""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from campaign.__main__ import main as campaign_main
from campaign.preset import (
    CampaignPreset,
    CampaignPresetGenerator,
    generate_preset,
)
from campaign.roles import RoleCatalog, RoleError, RoleSpec
from campaign.storage import load_preset, save_preset


@pytest.fixture(scope="module")
def preset():
    return generate_preset(seed=7)


def test_campaign_layer_is_headless():
    root = Path(__file__).resolve().parents[1]
    code = (
        "import campaign, campaign.storage, campaign.preset; "
        "import sys; "
        "assert 'pygame' not in sys.modules, 'campaign imported pygame'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=root,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_role_catalog_exposes_only_faction_leader():
    catalog = RoleCatalog.load()
    available = catalog.available_roles()
    assert [role.id for role in available] == ["faction_leader"]
    role = catalog.default_role()
    assert role.leadership == "nominal"
    assert role.faction_kind == "automaton"
    assert role.faction_slot == "player"
    assert role.faction_choice is True
    assert role.storyline_id == "faction_leader_demo"
    assert role.grants["player_role"] == "faction_leader"
    assert role.grants["leadership_mode"] == "nominal"
    assert catalog.select("faction_leader") is role


def test_role_catalog_is_extensible_but_hides_unavailable_roles():
    catalog = RoleCatalog.from_data({
        "schema": 1,
        "roles": [
            {
                "id": "faction_leader",
                "label": "Номинальный лидер",
                "sort_order": 1,
            },
            {
                "id": "future_role",
                "label": "Будущая роль",
                "available": False,
                "sort_order": 2,
            },
        ],
    })
    assert [role.id for role in catalog.available_roles()] == [
        "faction_leader"
    ]
    assert [role.id for role in catalog.all_roles()] == [
        "faction_leader", "future_role"
    ]
    with pytest.raises(RoleError):
        catalog.select("future_role")
    with pytest.raises(RoleError):
        catalog.select("missing")


def test_role_slot_selects_player_faction_without_code_changes():
    catalog = RoleCatalog.from_data({"roles": [{
        "id": "enemy_leader",
        "label": "Номинальный лидер противника",
        "faction_slot": "enemy",
        "grants": {"player_role": "enemy_leader"},
    }]})
    generated = CampaignPresetGenerator(catalog=catalog).generate(
        role_id="enemy_leader", seed=7,
    )
    assert generated.player_side == "blue"
    assert generated.player_faction["side"] == "blue"
    assert generated.player_character["side"] == "blue"
    assert generated.player_character["is_player"] is True
    assert generated.player_character["campaign_role_id"] == "enemy_leader"


def test_player_can_choose_each_faction():
    generator = CampaignPresetGenerator()
    red = generator.generate(seed=7, player_faction_id="faction_red")
    blue = generator.generate(seed=7, player_faction_id="faction_blue")
    assert red.player_side == "red"
    assert blue.player_side == "blue"
    assert red.player_faction["id"] == "faction_red"
    assert blue.player_faction["id"] == "faction_blue"
    assert red.player_character["side"] == "red"
    assert blue.player_character["side"] == "blue"
    assert red.enemy_faction["side"] == "blue"
    assert blue.enemy_faction["side"] == "red"
    assert red.player_organization["id"] == "org_red"
    assert blue.player_organization["id"] == "org_blue"
    assert red.preset_id == "test_skirmish_seed7"
    assert blue.preset_id == "test_skirmish_seed7_blue"


def test_faction_options_preview_both_sides():
    options = CampaignPresetGenerator().faction_options(seed=7)
    assert [item["id"] for item in options] == [
        "faction_red", "faction_blue"
    ]
    assert [item["companies"] for item in options] == [16, 32]
    assert [item["is_default"] for item in options] == [True, False]
    assert options[0]["organization_name"] == "Совет Севера"
    assert options[1]["organization_name"] == "Директория Агоры"
    assert all(item["leader_name"] for item in options)
    assert all(item["goals"] for item in options)


def test_faction_choice_rejects_unknown_faction():
    with pytest.raises(Exception):
        CampaignPresetGenerator().generate(
            seed=7, player_faction_id="faction_missing"
        )


def test_role_validation_rejects_bad_ids_and_empty_catalog():
    with pytest.raises(RoleError):
        RoleSpec(id="Bad-Role", label="Плохая")
    with pytest.raises(RoleError):
        RoleCatalog.from_data({"roles": []})
    with pytest.raises(RoleError):
        RoleCatalog.from_data({"roles": [{
            "id": "only_hidden", "label": "Скрытая", "available": False
        }]})


def test_preset_generation_is_deterministic(preset):
    again = generate_preset(seed=7)
    other = generate_preset(seed=8)
    assert preset.as_dict() == again.as_dict()
    assert preset.as_dict() != other.as_dict()
    assert preset.preset_id == "test_skirmish_seed7"
    assert other.preset_id == "test_skirmish_seed8"


def test_preset_has_player_faction_characters_and_organizations(preset):
    summary = preset.summary()
    assert summary["role_id"] == "faction_leader"
    assert summary["companies"] == {"red": 16, "blue": 32}
    assert summary["characters"] == 192
    assert summary["organizations"] == 2
    assert summary["automata"] == 4

    player_faction = preset.player_faction
    player_character = preset.player_character
    assert player_faction["side"] == "red"
    assert player_faction["is_player"] is True
    assert player_character["is_player"] is True
    assert player_character["is_faction_leader"] is True
    assert player_character["campaign_role_id"] == "faction_leader"
    assert player_faction["leader_id"] == player_character["id"]

    player_org = preset.organization(player_faction["organization_id"])
    assert player_org["leader_id"] == player_character["id"]
    assert player_org["leader_name"] == player_character["name"]
    assert player_org["dissolved"] is False
    assert len(player_org["member_ids"]) == 64
    assert len(player_org["summary"]) >= 2

    kinds = {item["kind"] for item in preset.automata}
    assert kinds == {"faction", "organization"}
    for item in preset.automata:
        assert item["automaton"]["states"]
        assert item["automaton"]["transitions"]


def test_preset_scenario_roster_is_complete(preset):
    units = preset.scenario["units"]
    assert len(units) == 48
    by_id = {character["id"]: character for character in preset.characters}
    for unit in units:
        assert unit["faction_id"] in {
            faction["id"] for faction in preset.factions
        }
        assert len(unit["character_ids"]) == 4
        assert all(char_id in by_id for char_id in unit["character_ids"])
        assert unit["leader_id"] == unit["character_ids"][0]
    for side, expected in (("red", 16), ("blue", 32)):
        rosters = preset.roster_by_side()[side]
        assert len(rosters) == expected
        assert all(len(roster) == 4 for roster in rosters)
        names = [character["name"] for character in preset.characters
                 if character["side"] == side]
        assert len(names) == len(set(names)) == expected * 4


def test_preset_characters_have_bdi_fields(preset):
    for character in preset.characters:
        assert character["name"]
        assert character["needs"]
        assert character["urgency"]
        assert character["personality"]
        assert 0.0 <= character["morale"] <= 100.0
        assert character["force"] > 0
        assert character["seed"] >= 0
    player = preset.player_character
    assert player["needs"]["fear"] > 0.4


def test_preset_environment_events_and_playwright(preset):
    environment = preset.environment
    assert environment["feature_ids"] == [
        "river", "forest", "storm", "ruins", "crossroads"
    ]
    assert set(environment["features"]) == set(environment["feature_ids"])

    events = preset.events
    assert len(events["hooks"]) == 8
    assert {hook["category"] for hook in events["hooks"]} <= set(
        events["categories"])
    assert all(hook["text"] for hook in events["hooks"])
    assert events["context"]["organization"] == "Совет Севера"
    assert events["context"]["rival_organization"] == "Директория Агоры"

    playwright = preset.playwright
    assert len(playwright["actors"]) == 8
    assert playwright["candidate_count"] > 0
    assert playwright["candidates"]
    assert playwright["templates"]
    assert any(actor["organization"] == "Совет Севера"
               for actor in playwright["actors"])


def test_preset_roundtrip_and_storage(tmp_path, preset):
    restored = CampaignPreset.from_dict(preset.as_dict())
    assert restored.as_dict() == preset.as_dict()
    minimal_role = dict(preset.as_dict())
    minimal_role["role"] = {"id": "faction_leader"}
    resolved = CampaignPreset.from_dict(minimal_role)
    assert resolved.role.label == "Номинальный лидер фракции"
    path = save_preset(preset, path=tmp_path / "preset.json")
    loaded = load_preset(path)
    assert loaded.as_dict() == preset.as_dict()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["role"]["id"] == "faction_leader"
    assert data["player"]["faction_id"] == "faction_red"


def test_world_uses_preset_roster_and_keeps_default_balance(preset):
    pytest.importorskip("numpy")
    from view.support.scenario import build_world

    state = build_world(campaign_preset=preset)
    assert state.count == 48
    assert state.player_side == "red"
    assert state.player_faction_id == "faction_red"
    assert state.campaign_role_id == "faction_leader"
    assert state.campaign_preset_id == preset.preset_id
    assert len(state.organization_runtimes) == 2
    first_unit = preset.scenario["units"][0]
    first_names = [preset.character(char_id)["name"]
                   for char_id in first_unit["character_ids"]]
    assert [character.name for character
            in state.units[0].characters] == first_names
    assert state.units[0].characters[0].campaign_role_id == "faction_leader"
    assert state.units[0].characters[0].campaign_leader is True

    default = build_world()
    assert default.count == 48
    assert default.organization_runtimes == []
    assert default.campaign_role_id == ""


def test_world_can_use_blue_faction_as_player():
    pytest.importorskip("numpy")
    from view.support.scenario import build_world

    chosen = generate_preset(seed=7, player_faction_id="faction_blue")
    state = build_world(campaign_preset=chosen)
    assert state.count == 48
    assert state.player_side == "blue"
    assert state.player_faction_id == "faction_blue"
    assert state.units[state.player_idx].side == "blue"
    assert state.units[state.player_idx].characters[0].campaign_role_id == (
        "faction_leader"
    )


def test_faction_leader_storyline_skips_character_creation():
    from view.support.storyline import load_storyline

    storyline = load_storyline("faction_leader_demo")
    assert storyline is not None
    assert storyline["title"] == "Мандат фракции"
    assert storyline["character_creation"] == {}
    assert [scene["type"] for scene in storyline["scenes"]] == [
        "visual_novel", "document", "gameplay"
    ]
    assert storyline["scenes"][0]["slides"][0]["image"].startswith(
        "campaign/"
    )


def test_storyline_interpolates_campaign_variables():
    from view.support.storyline import StorylineInterpreter

    interp = StorylineInterpreter(None, {
        "storyline_id": "test",
        "scenes": [],
    })
    interp.set_variable("player_faction_name", "Северный союз")
    interp.set_variable("player_companies", 16)
    assert interp.interpolate(
        "{player_faction_name}: {player_companies}"
    ) == "Северный союз: 16"
    assert interp.interpolate("неизвестно: {missing}") == (
        "неизвестно: {missing}"
    )
    resolved = interp.resolve_variant({
        "text": "{player_faction_name}",
        "slides": [{"text": "{player_companies}"}],
    })
    assert resolved["text"] == "Северный союз"
    assert resolved["slides"][0]["text"] == "16"


def test_state_snapshot_preserves_campaign_metadata(preset):
    pytest.importorskip("numpy")
    from view.support.scenario import build_world

    state = build_world(campaign_preset=preset)
    snapshot = state.to_snapshot()
    assert snapshot["campaign_preset_id"] == preset.preset_id
    assert snapshot["campaign_role_id"] == "faction_leader"
    assert snapshot["player_faction_id"] == "faction_red"
    assert snapshot["campaign_role"]["id"] == "faction_leader"

    other = build_world()
    other.apply_snapshot(snapshot)
    assert other.campaign_preset_id == preset.preset_id
    assert other.campaign_role_id == "faction_leader"
    assert other.player_faction_id == "faction_red"


def test_save_roundtrip_keeps_role_and_preset(tmp_path, monkeypatch, preset):
    pytest.importorskip("numpy")
    from view.support import save_system
    from view.support.scenario import build_world
    from view.support.time_system import CampaignTimeSystem

    monkeypatch.setattr(save_system, "SAVES_DIR", tmp_path)
    state = build_world(campaign_preset=preset)
    time_system = CampaignTimeSystem(state)
    path = save_system.save_game(
        state, time_system, "role-test",
        campaign_role=preset.role,
        campaign_preset=preset,
    )
    assert Path(path).exists()
    payload = save_system.load_game("role-test")
    assert payload["campaign_role"]["id"] == "faction_leader"
    assert payload["campaign_preset"]["preset_id"] == preset.preset_id
    assert payload["campaign"]["campaign_role_id"] == "faction_leader"

    restored = build_world(
        campaign_snapshot=payload["campaign"],
        campaign_preset=payload["campaign_preset"],
        campaign_role=payload["campaign_role"],
    )
    assert restored.campaign_preset_id == preset.preset_id
    assert restored.campaign_role_id == "faction_leader"
    assert restored.units[0].characters[0].name == preset.player_character["name"]


def test_cli_lists_roles_and_generates_preset(tmp_path, capsys):
    assert campaign_main(["--list-roles"]) == 0
    output = capsys.readouterr().out
    assert "faction_leader" in output
    assert "Номинальный лидер фракции" in output

    out = tmp_path / "generated.json"
    assert campaign_main([
        "--generate", "--seed", "7", "--out", str(out),
    ]) == 0
    output = capsys.readouterr().out
    assert "test_skirmish_seed7" in output
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["preset_id"] == "test_skirmish_seed7"
    assert data["player_faction_id"] == "faction_red"


def test_role_select_screen_constructs_and_draws():
    """Дымовой тест UI: пропускается без pygame."""
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from view.app import App
    from view.screens.role_select import RoleSelectScreen

    app = App()
    screen = RoleSelectScreen(app)
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    assert [role.id for role in screen.roles] == ["faction_leader"]
    screen.select("faction_leader")
    assert app.selected_role.id == "faction_leader"
    assert app.selected_faction_id is None
    assert app.manager.current.__class__.__name__ == "FactionSelectScreen"


def test_faction_select_screen_constructs_and_draws():
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from view.app import App
    from view.screens.faction_select import FactionSelectScreen

    app = App()
    app.selected_role = app.role_catalog.select("faction_leader")
    screen = FactionSelectScreen(app)
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    assert [item["id"] for item in screen.options] == [
        "faction_red", "faction_blue"
    ]
    assert screen.storyline["storyline_id"] == "faction_leader_demo"


def test_asset_loader_uses_procedural_placeholders():
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pytest.importorskip("pygame")
    from view.ui.asset_loader import AssetLoader

    assert AssetLoader.USE_PLACEHOLDERS is True
    image = AssetLoader.load("menus/main_menu_bg", (320, 180))
    assert image.get_size() == (320, 180)
    assert image.get_at((0, 0))[:3] != (0, 0, 0)
