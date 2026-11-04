"""Сюжетные арки Агоры загружаются как Data-Driven JSON-контент."""

from pathlib import Path

from view.support.storyline import list_storylines, load_storyline

FIXTURE_STORYLINES = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "content"
    / "configs"
    / "storylines"
)


def test_agora_arcs_are_listed_and_loadable():
    ids = {
        item["storyline_id"] for item in list_storylines(FIXTURE_STORYLINES)
    }

    assert {"agora_crisis", "agora_reform", "agora_legacy"} <= ids

    for storyline_id in ("agora_crisis", "agora_reform", "agora_legacy"):
        data = load_storyline(storyline_id, FIXTURE_STORYLINES)
        assert data["world_path"] == (
            "tests/fixtures/content/configs/worlds/agora_world.json"
        )
        assert data["character_creation"]["steps"]
        assert data["scenes"]
        assert data["win_conditions"]
        assert data["lose_conditions"]
        assert any(
            scene.get("type") == "world" for scene in data["scenes"]
        )
