"""Тесты F-16: протокол WorldView и адаптеры миров."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import build_knowledge
from campaign.dialogue.lint import lint_catalog, lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.perception import (
    WORLD_ADAPTER_KINDS,
    AutomataCampaignAdapter,
    SceneAdapter,
    Signal,
    WorldEngineAdapter,
    WorldView,
    adapter_for,
    campaign_view,
)
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog
from campaign.world import WorldEngine, build_player_profile, load_world

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


@pytest.fixture(scope="module")
def campaign() -> AutomataCampaign:
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DEFAULT_DIR)


WORLDS = ROOT / "configs" / "worlds"


@pytest.fixture(scope="module")
def world_engine():
    engine = WorldEngine(
        load_world(WORLDS / "agora_world.json"),
        profile=build_player_profile({"name": "Тест"}, seed=7),
        node_id="agora_street",
        office_id="street_musician",
        seed=7,
    )
    assert engine.attach("agora_street", "street_musician")["ok"] is True
    return engine


def test_world_config_declares_adapters(catalog):
    adapters = catalog.world.get("adapters") or {}
    assert set(WORLD_ADAPTER_KINDS) <= set(adapters)
    for kind, spec in adapters.items():
        assert spec.get("kind") == kind
    assert lint_catalog(catalog) == []


def test_unknown_adapter_kind_fails_lint(tmp_path):
    import json
    import shutil

    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    path = target / "world.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["adapters"]["scene"]["kind"] = "no_such_world"
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    problems = lint_directory(target)
    assert any(
        "world.adapters.scene.kind" in item and "no_such_world" in item
        for item in problems
    )


def test_automata_adapter_returns_world_view(campaign, catalog):
    adapter = AutomataCampaignAdapter(campaign, catalog.world)
    signal = Signal(
        "recent_work",
        ("faction:red", "1", "Эдикт", "1", "Империя издала эдикт"),
        channel="sight",
        source="campaign",
    )
    view = adapter.view(None, side="red", signals=(signal,))
    assert isinstance(view, WorldView)
    assert view.observer
    assert view.perception.faction_id == "faction:red"
    assert "recent_work" in view.relations
    assert view.recent_work == view.perception.known("recent_work")
    assert view.perceived == view.perception.group("perceived")
    assert view.believed == view.perception.group("believed")


def test_automata_adapter_matches_campaign_view(campaign, catalog):
    adapter = AutomataCampaignAdapter(campaign, catalog.world)
    direct = campaign_view(campaign, None, world=catalog.world, side="red")
    assert adapter.view(None, side="red") == direct


def test_world_view_unknown_and_entities(campaign, catalog):
    adapter = AutomataCampaignAdapter(campaign, catalog.world)
    view = adapter.view(None, side="red")
    hidden = ("faction:blue", "1", "Демонстрация силы", "1", "Республика")
    assert view.unknown("recent_work", hidden)
    assert view.entities
    assert "faction:red" in view.entities


def test_world_view_does_not_leak_hidden_entity(campaign, catalog):
    adapter = AutomataCampaignAdapter(campaign, catalog.world)
    view = adapter.view(None, side="red")
    hidden = campaign.faction("blue").characters[0].campaign_id
    assert view.unknown("character_info", ("character:%s" % hidden,))


def test_arbitrary_side_works_without_faction_override(campaign, catalog):
    world = dict(catalog.world)
    world["factions"] = {}
    local = replace(catalog, world=world)
    view = campaign_view(
        campaign,
        campaign.faction("blue").characters[0].campaign_id,
        world=world,
        side="blue",
    )
    knowledge = build_knowledge(
        local, campaign, "blue", view=view
    )
    assert knowledge.faction_id == "faction:blue"
    assert knowledge.facts


def test_world_engine_adapter_uses_engine_state(world_engine, catalog):
    adapter = WorldEngineAdapter(world_engine, catalog.world)
    view = adapter.view("player")
    assert isinstance(view, WorldView)
    assert view.location == world_engine.player_node_id
    assert view.visible_nodes
    assert view.entities
    assert view.unknown("character_info", ("character:nobody",))


def test_scene_adapter_narrows_to_current_scene(world_engine, catalog):
    adapter = SceneAdapter(world_engine, catalog.world)
    view = adapter.view("player")
    scene = world_engine.current_scene()
    assert scene is not None
    assert view.scene == scene.id
    assert scene.location in view.visible_nodes
    public = world_engine.scene_public(scene.id)
    for person in public:
        assert person["id"] in view.entities


def test_adapter_for_infers_kind(campaign, catalog, world_engine):
    assert isinstance(
        adapter_for(campaign, world_data=catalog.world),
        AutomataCampaignAdapter,
    )
    assert isinstance(
        adapter_for(world_engine, world_data=catalog.world),
        WorldEngineAdapter,
    )
    assert isinstance(
        adapter_for(world_engine, "scene", catalog.world),
        SceneAdapter,
    )


def test_hearing_signal_survives_adapter(campaign, catalog):
    adapter = AutomataCampaignAdapter(campaign, catalog.world)
    signal = Signal(
        "recent_work",
        ("faction:blue", "1", "Слух", "1", "так говорят"),
        channel="hearing",
        source="char_red_003",
        speaker="char_red_003",
    )
    view = adapter.view(None, side="red", signals=(signal,))
    assert any(
        item.speaker == "char_red_003" for item in view.said
    )
    assert any(
        item.key == signal.key for item in view.recent_work
    )
