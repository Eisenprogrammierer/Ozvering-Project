"""Управляемый персонаж (PlayerAvatar): модель, пресет и снимок."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.avatar import (
    AVATAR_SCHEMA_VERSION,
    AvatarError,
    PlayerAvatar,
    avatar_from_preset,
    avatar_from_snapshot,
)
from campaign.preset import CampaignPresetError, CampaignPresetGenerator
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


def test_avatar_requires_character_and_valid_mode():
    with pytest.raises(AvatarError):
        PlayerAvatar(character_id="")
    with pytest.raises(AvatarError):
        PlayerAvatar(character_id="char_1", control_mode="remote")


def test_avatar_allows_no_faction_and_no_office():
    avatar = PlayerAvatar(character_id="school_student_1")
    assert avatar.has_faction is False
    assert avatar.has_office is False
    assert avatar.control_mode == "delegated"
    assert avatar.schema == AVATAR_SCHEMA_VERSION


def test_avatar_office_and_scene_changes_are_explicit():
    avatar = PlayerAvatar(
        character_id="char_1", faction_id="faction.market"
    )
    moved = avatar.with_office("apprentice").with_scene("market")
    assert moved.office_id == "apprentice"
    assert moved.scene_id == "market"
    assert moved.faction_id == "faction.market"
    # Исходный аватар неизменяем.
    assert avatar.office_id == ""
    assert avatar.scene_id == ""


def test_avatar_round_trip():
    avatar = PlayerAvatar(
        character_id="char_1",
        faction_id="faction.a",
        office_id="clerk",
        scene_id="court",
        control_mode="direct",
    )
    restored = PlayerAvatar.from_data(avatar.as_dict())
    assert restored == avatar


def test_preset_exposes_avatar():
    preset = _preset()
    avatar = preset.avatar
    assert avatar is not None
    assert avatar.character_id == preset.player_character_id
    assert avatar.faction_id == preset.player_faction_id
    assert avatar.control_mode == "delegated"
    assert preset.as_dict()["avatar"]["character_id"] == avatar.character_id
    assert preset.summary()["avatar"]["character_id"] == avatar.character_id


def test_identity_can_switch_control_mode_and_office():
    preset = _preset()
    preset.apply_player_identity(
        {
            "name": "Тестовый герой",
            "control_mode": "direct",
            "office_id": "apprentice",
            "scene_id": "market",
        }
    )
    avatar = preset.avatar
    assert avatar is not None
    assert avatar.control_mode == "direct"
    assert avatar.office_id == "apprentice"
    assert avatar.scene_id == "market"


def test_avatar_from_preset_handles_missing_player():
    assert avatar_from_preset({}) is None
    assert avatar_from_preset({"player_character_id": ""}) is None


def test_campaign_snapshot_restores_avatar():
    preset = _preset()
    campaign = AutomataCampaign(preset)
    assert campaign.avatar is not None
    campaign.move_avatar("market")
    campaign.assign_avatar_office("musician")
    snapshot = campaign.save_snapshot()
    assert snapshot["avatar"]["scene_id"] == "market"
    assert snapshot["avatar"]["office_id"] == "musician"

    restored = AutomataCampaign(preset)
    restored.load_snapshot(snapshot)
    assert restored.avatar == campaign.avatar
    assert restored.avatar.character_id == campaign.avatar.character_id
    character = restored.avatar_character()
    assert character is not None
    assert character.campaign_post_id == "musician"
    assert character.scene_id == "market"


def test_legacy_snapshot_without_avatar_stays_delegated():
    preset = _preset()
    campaign = AutomataCampaign(preset)
    snapshot = campaign.save_snapshot()
    snapshot.pop("avatar", None)
    snapshot.pop("avatar_schema", None)

    restored = AutomataCampaign(preset)
    restored.load_snapshot(snapshot)
    assert restored.avatar is not None
    assert restored.avatar.control_mode == "delegated"


def test_avatar_from_snapshot_reads_legacy_player_character():
    snapshot = {
        "player_character_id": "char_7",
        "player_faction_id": "faction.a",
    }
    avatar = avatar_from_snapshot(snapshot)
    assert avatar is not None
    assert avatar.character_id == "char_7"
    assert avatar.control_mode == "delegated"


def test_avatar_character_finds_character_by_id():
    preset = _preset()
    campaign = AutomataCampaign(preset)
    character = campaign.avatar_character()
    assert character is not None
    assert character.campaign_id == campaign.avatar.character_id


def test_preset_can_select_non_leader_character():
    preset = _preset()
    candidates = preset.available_player_characters()
    assert len(candidates) >= 2
    chosen = candidates[1]
    preset.select_player_character(chosen["id"])
    assert preset.player_character_id == chosen["id"]
    assert preset.player_character["is_player"] is True
    players = [
        item["id"] for item in preset.characters if item.get("is_player")
    ]
    assert players == [chosen["id"]]
    avatar = preset.avatar
    assert avatar.character_id == chosen["id"]
    assert avatar.control_mode == "direct"


def test_selected_character_receives_identity():
    preset = _preset()
    chosen = preset.available_player_characters()[1]
    preset.select_player_character(chosen["id"])
    before = chosen["name"]
    preset.apply_player_identity({"name": "Выбранный герой"})
    assert preset.player_character["name"] == "Выбранный герой"
    assert preset.player_character["name"] != before


def test_preset_rejects_unknown_player_character():
    preset = _preset()
    with pytest.raises(CampaignPresetError):
        preset.select_player_character("char_missing")


def test_campaign_uses_selected_avatar():
    preset = _preset()
    chosen = preset.available_player_characters()[1]
    preset.select_player_character(chosen["id"])
    campaign = AutomataCampaign(preset)
    assert campaign.avatar.character_id == chosen["id"]
    character = campaign.avatar_character()
    assert character is not None
    assert character.campaign_is_player is True


def test_selected_avatar_survives_snapshot_round_trip():
    preset = _preset()
    chosen = preset.available_player_characters()[1]
    preset.select_player_character(chosen["id"])
    campaign = AutomataCampaign(preset)
    snapshot = campaign.save_snapshot()

    restored = AutomataCampaign(preset)
    restored.load_snapshot(snapshot)
    assert restored.avatar.character_id == chosen["id"]
    assert restored.avatar.control_mode == "direct"
    assert restored.avatar_character().campaign_is_player is True


def test_character_select_screen_lists_and_applies(monkeypatch):
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    del pygame
    from view.app import App
    from view.screens import character_select

    app = App()
    app.role_catalog = RoleCatalog.load(ROOT / "configs" / "roles")
    app.selected_role = app.role_catalog.select("empire_leader")
    monkeypatch.setattr(
        character_select,
        "load_storyline",
        lambda _storyline_id: {
            "campaign_template": str(
                CAMPAIGNS / "empire_campaign.json"
            )
        },
    )
    screen = character_select.CharacterSelectScreen(app)
    assert len(screen.characters) >= 2
    target = screen.characters[1]["id"]
    screen.select(target)
    screen.apply()
    assert app.selected_player_character_id == target
    assert app.selected_player_character_label
    app.quit()
