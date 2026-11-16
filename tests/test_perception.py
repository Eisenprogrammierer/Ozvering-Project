"""Тесты F-23: призма восприятия и видимость мира."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.perception import (
    CHANNELS,
    DEFAULT_SCOPES,
    SCOPES,
    Perception,
    Signal,
    campaign_view,
    perception_scopes,
    world_view,
)
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


def _campaign(seed=13) -> AutomataCampaign:
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=seed), seed=seed)


class _NodeWorld:
    """Минимальный мир с иерархией узлов и персонажами."""

    def __init__(self):
        self.player_node_id = "b"
        self.day = 4
        self.nodes = {
            "a": {"id": "a", "parent": "", "children": ["b", "c"]},
            "b": {"id": "b", "parent": "a", "children": ["d"]},
            "c": {"id": "c", "parent": "a", "children": []},
            "d": {"id": "d", "parent": "b", "children": []},
            "e": {"id": "e", "parent": "", "children": []},
        }
        self.characters = {
            "c1": {"id": "c1", "node_id": "b"},
            "c2": {"id": "c2", "node_id": "a"},
            "c3": {"id": "c3", "node_id": "d"},
            "c4": {"id": "c4", "node_id": "e"},
        }

    def node(self, node_id):
        return self.nodes.get(str(node_id))

    def node_path(self, node_id):
        path = []
        current = self.node(node_id)
        while current is not None:
            path.append(current)
            current = self.node(current.get("parent"))
        return list(reversed(path))

    def character(self, character_id):
        return self.characters.get(str(character_id))

    def scene(self, scene_id=None):
        return None


def test_signal_normalizes_and_classifies():
    signal = Signal(
        "recent_work",
        ("faction:blue", 1, "акт"),
        channel="unknown",
        speaker="char_red_003",
        confidence=4,
        truth="maybe",
        day="3",
    )
    assert signal.channel == "sight"
    assert signal.confidence == 1.0
    assert signal.truth == "unknown"
    assert signal.day == 3
    assert signal.group == "said"
    assert signal.label == "мне сказали"


@pytest.mark.parametrize("channel", CHANNELS)
def test_signal_accepts_every_channel(channel):
    signal = Signal("rel", ("a",), channel=channel)
    assert signal.channel == channel


def test_perception_scopes_resolve_adapter_and_validate():
    world = {
        "adapter": {"recent_work": "last_seen"},
        "perception": {
            "relations": {
                "recent_work": "visible",
                "faction_name": "public",
            }
        },
    }
    scopes = perception_scopes(world)
    assert scopes["last_seen"] == "visible"
    assert scopes["faction_name"] == "public"
    for scope in scopes.values():
        assert scope in SCOPES


def test_perception_uses_default_scopes_without_data():
    scopes = perception_scopes({})
    assert scopes["recent_work"] == DEFAULT_SCOPES["recent_work"]
    assert scopes["belief"] == "belief"


def test_perception_scopes_by_visibility():
    perception = Perception(
        observer="char:me",
        self_id="char:me",
        faction_id="faction:red",
        visible=frozenset({"char:me", "char:friend", "faction:red"}),
        scopes={
            "public_rel": "public",
            "record_rel": "reading",
            "self_rel": "self",
            "faction_rel": "faction",
            "visible_rel": "visible",
            "belief_rel": "belief",
            "hidden_rel": "hidden",
        },
    )
    assert perception.signal_for("public_rel", ("x",)) is not None
    assert perception.signal_for("record_rel", ("x",)) is not None
    assert perception.signal_for("self_rel", ("char:me",)) is not None
    assert perception.signal_for("self_rel", ("char:other",)) is None
    assert (
        perception.signal_for("faction_rel", ("faction:red",)) is not None
    )
    assert (
        perception.signal_for("visible_rel", ("char:friend",)) is not None
    )
    assert (
        perception.signal_for("visible_rel", ("char:other",)) is None
    )
    assert (
        perception.signal_for("belief_rel", ("char:me",)) is not None
    )
    assert perception.signal_for("hidden_rel", ("char:me",)) is None


def test_perception_explains_unknown_reason():
    perception = Perception(observer="char:me", self_id="char:me")
    data = perception.explain("hidden_rel", ("x",))
    assert data["known"] is False
    assert data["reason"] == "not-visible"
    assert data["label"] == "не знаю"


def test_explicit_signal_overrides_scope():
    signal = Signal(
        "hidden_rel",
        ("x",),
        channel="hearing",
        source="char:friend",
        speaker="char:friend",
        confidence=0.4,
        truth="false",
    )
    perception = Perception(
        observer="char:me",
        self_id="char:me",
        scopes={"hidden_rel": "hidden"},
        signals=(signal,),
    )
    found = perception.signal_for("hidden_rel", ("x",))
    assert found is signal
    assert found.group == "said"
    assert found.truth == "false"
    assert found.confidence == 0.4


def test_campaign_view_sees_own_faction_only():
    campaign = _campaign()
    view = campaign_view(campaign, None, world={})
    leader = campaign.faction("red").characters[0]
    assert view.observer == leader.campaign_id
    assert view.perception.self_id == leader.campaign_id
    assert "faction:red" in view.perception.visible
    assert "faction:blue" not in view.perception.visible
    other = campaign.faction("blue").characters[0]
    assert (
        view.explain(
            "character_info",
            ("character:%s" % other.campaign_id, "faction:blue", "X", ""),
        )["known"]
        is False
    )


def test_world_view_marks_local_nodes_and_public():
    world = _NodeWorld()
    view = world_view(world, "player")
    assert view.location == "b"
    assert view.day == 4
    assert set(view.visible_nodes) == {"a", "b", "c", "d"}
    assert "c1" in view.visible_characters
    assert "c2" in view.visible_characters
    assert "c3" in view.visible_characters
    assert "c4" not in view.visible_characters
    assert view.accepts("character_info", ("c1", "faction:x"))
    assert not view.accepts("character_info", ("c4", "faction:x"))


def test_world_view_without_local_context_is_empty():
    world = _NodeWorld()
    world.player_node_id = "missing"
    view = world_view(world, "player")
    assert view.visible_nodes == ()
    assert view.visible_characters == ()
