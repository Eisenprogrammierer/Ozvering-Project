"""F-20: эмоциональные оси отношений читаются из данных мира."""

from __future__ import annotations

from pathlib import Path

import pytest

import bdi
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.relations import (
    asymmetry_rows,
    normalize_relation_axes_config,
    relation_axes_from_config,
    relation_axis_labels_from_config,
    relation_axis_short_labels_from_config,
    relation_effect,
    relation_effect_limit_from_config,
    relation_effect_weights_from_config,
)
from campaign.world import WorldEngine, load_world

ROOT = Path(__file__).resolve().parents[1]
WORLD_PATH = ROOT / "configs" / "worlds" / "agora_world.json"


@pytest.fixture()
def engine():
    return WorldEngine(
        load_world(WORLD_PATH),
        node_id="agora_government",
        office_id="head_of_government",
        seed=7,
    )


def test_custom_axes_and_labels_come_from_config():
    config = {
        "relation_axes": {
            "affinity": {"label": "симпатия", "short": "симп."},
            "romance": {"label": "романтика", "short": "роман."},
        }
    }
    assert relation_axes_from_config(config) == (
        "affinity",
        "romance",
        "trust",
        "fear",
        "respect",
    )
    labels = relation_axis_labels_from_config(config)
    assert labels["affinity"] == "симпатия"
    assert labels["romance"] == "романтика"
    assert labels["trust"] == "доверие"
    short = relation_axis_short_labels_from_config(config)
    assert short["romance"] == "роман."
    assert short["fear"] == "страх"


def test_normalize_axes_config_rejects_empty_and_duplicates():
    assert normalize_relation_axes_config(["romance", "family"]) == {
        "romance": {},
        "family": {},
    }
    with pytest.raises(ValueError):
        normalize_relation_axes_config({"": {}})
    with pytest.raises(ValueError):
        normalize_relation_axes_config(["romance", "romance"])


def test_real_world_exposes_emotional_axes_and_character_data(engine):
    for axis in ("romance", "family", "ritual", "vassalage"):
        assert axis in engine.relation_axis_ids
        assert axis in engine.relation_axis_labels
        assert axis in engine.relation_axis_short_labels
    relations = engine.character_relations("mira_svet")
    assert relations["character_to_player"]["family"] == pytest.approx(0.9)
    assert relations["character_to_player"]["romance"] == pytest.approx(0.0)
    rows = asymmetry_rows(
        relations["player_to_character"],
        relations["character_to_player"],
        engine.relation_axis_ids,
    )
    assert [row[0] for row in rows] == list(engine.relation_axis_ids)
    assert len(rows) == 8


def test_character_effects_apply_and_clamp_emotional_axes(engine):
    character = engine.character("mira_svet")
    engine._apply_character_effects(
        {"romance": 0.5, "family": -2.0}, character
    )
    assert character["romance"] == pytest.approx(0.5)
    assert character["family"] == pytest.approx(-1.0)
    engine._apply_player_view(
        {"player_romance": 0.25, "player_family": -0.5}, character
    )
    view = engine.player_relations["mira_svet"]
    assert view["romance"] == pytest.approx(0.25)
    assert view["family"] == pytest.approx(-0.5)


def test_emotional_axis_weights_and_limit_from_config(engine):
    weights = engine.relation_effect_weights
    assert relation_effect(
        {"romance": 1.0},
        "contact",
        weights=weights,
        limit=engine.relation_effect_limit,
    ) == pytest.approx(0.12)
    assert relation_effect(
        {"romance": 1.0},
        "missing_form",
        weights=weights,
    ) == 0.0
    bounded = relation_effect(
        {"affinity": 1.0},
        "huge",
        weights={"huge": {"affinity": 100.0}},
        limit=0.2,
    )
    assert bounded == pytest.approx(0.2)
    config = {
        "relation_axis": {},
        "relation_effect_weights": {"care": {"family": 0.5}},
        "relation_effect_limit": 0.07,
    }
    merged = relation_effect_weights_from_config(config)
    assert merged["force"]  # легаси-веса не потеряны
    assert merged["care"] == {"family": 0.5}
    assert relation_effect_limit_from_config(config) == pytest.approx(0.07)


def test_actions_and_character_actions_carry_emotional_effects(engine):
    kiss = engine.actions["kiss"]
    assert kiss["success"]["effects"]["target"]["romance"] > 0.0
    sacrifice = engine.actions["offer_sacrifice"]
    assert sacrifice["success"]["effects"]["relation_axes"]["ritual"] > 0.0
    comfort = engine.actions["comfort_person"]
    assert comfort["success"]["effects"]["target"]["family"] > 0.0
    lesson = engine.actions["teach_lesson"]
    assert lesson["success"]["effects"]["target"]["vassalage"] > 0.0
    heart = engine.character_actions["heart_to_heart"]
    assert heart["success"]["effects"]["romance"] > 0.0
    ambition = engine.character_actions["support_ambition"]
    assert ambition["success"]["effects"]["vassalage"] > 0.0


def test_old_save_without_emotional_axes_uses_config_defaults(engine):
    node = engine.node("agora_government")
    target = next(
        item for item in engine.nodes.values() if item["id"] != node["id"]
    )
    engine.set_relation_axes(
        node["id"], target["id"], {"romance": 0.4, "family": 0.3}
    )
    engine._apply_character_effects(
        {"romance": 0.2, "player_romance": 0.1},
        engine.character("mira_svet"),
    )
    snapshot = engine.to_dict()
    for saved in (snapshot.get("characters") or {}).values():
        for axis in ("romance", "family", "ritual", "vassalage"):
            saved.pop(axis, None)
    for saved in (snapshot.get("player_relations") or {}).values():
        for axis in ("romance", "family", "ritual", "vassalage"):
            saved.pop(axis, None)
    for saved in (snapshot.get("nodes") or {}).values():
        for axes in (saved.get("relation_axes") or {}).values():
            for axis in ("romance", "family", "ritual", "vassalage"):
                axes.pop(axis, None)

    restored = WorldEngine(load_world(WORLD_PATH), snapshot=snapshot)
    character = restored.character("mira_svet")
    assert character["affinity"] == pytest.approx(
        engine.character("mira_svet")["affinity"]
    )
    assert character["family"] == pytest.approx(0.9)
    assert character["romance"] == pytest.approx(0.0)
    assert restored.relation_axes(
        node["id"], target["id"]
    )["romance"] == pytest.approx(0.0)
    assert restored.player_relation(
        "mira_svet", "romance"
    ) == pytest.approx(0.0)


def test_snapshot_roundtrip_keeps_emotional_axes(engine):
    node = engine.node("agora_government")
    target = next(
        item for item in engine.nodes.values() if item["id"] != node["id"]
    )
    engine.set_relation_axes(
        node["id"], target["id"], {"romance": 0.4, "vassalage": -0.2}
    )
    engine._apply_character_effects(
        {"family": 0.1, "player_ritual": 0.3},
        engine.character("mira_svet"),
    )
    restored = WorldEngine(
        load_world(WORLD_PATH), snapshot=engine.to_dict()
    )
    axes = restored.relation_axes(node["id"], target["id"])
    assert axes["romance"] == pytest.approx(0.4)
    assert axes["vassalage"] == pytest.approx(-0.2)
    assert restored.character("mira_svet")["family"] == pytest.approx(1.0)
    assert restored.player_relation(
        "mira_svet", "ritual"
    ) == pytest.approx(0.3)


def test_sixteen_needs_are_not_expanded_by_emotional_axes():
    assert len(bdi.NEEDS) == 16
    assert "romance" not in bdi.NEEDS
    assert "vassalage" not in bdi.NEEDS


def test_dialogue_registry_knows_emotional_relations():
    catalog = load_dialogue(DEFAULT_DIR)
    for relation in ("romance_with", "kin_of", "ritual_bound_to", "sworn_to"):
        assert relation in catalog.world["relations"]
        assert relation in catalog.world["perception"]["relations"]
    types = catalog.ontology.entity_types
    assert "romance" in types
    assert "family" in types
    assert "vassalage" in types
    assert "rite" in types
    ontology = catalog.ontology.relations
    assert ontology["romance_with"]["subject"] == "character"
    assert ontology["ritual_bound_to"]["object"] == "place"
