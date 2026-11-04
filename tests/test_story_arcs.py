"""Сюжетные арки Агоры загружаются как Data-Driven JSON-контент."""

from view.support.storyline import list_storylines, load_storyline


def test_agora_arcs_are_listed_and_loadable():
    ids = {item["storyline_id"] for item in list_storylines()}

    assert {"agora_crisis", "agora_reform", "agora_legacy"} <= ids

    for storyline_id in ("agora_crisis", "agora_reform", "agora_legacy"):
        data = load_storyline(storyline_id)
        assert data["world_path"] == "configs/worlds/agora_world.json"
        assert data["character_creation"]["steps"]
        assert data["scenes"]
        assert data["win_conditions"]
        assert data["lose_conditions"]
        assert any(
            scene.get("type") == "world" for scene in data["scenes"]
        )
