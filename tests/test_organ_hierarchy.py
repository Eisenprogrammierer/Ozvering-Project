"""Орган-в-органе и собственные шкалы органа (G-05).

Дерево задаётся ``parent_id``, а не отдельным кодом: дочерний орган
тянется к родителю, родитель слышит детей, шкалы вроде ``stealth``
живут в данных и читаются эффектами, условиями и снимком.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.conditions import check_conditions
from campaign.effects import apply_effects
from campaign.fractal import (
    OrganRuntime,
    organ_children,
    organ_depth,
    organ_descendants,
    organ_roots,
    organ_target,
    tick_organs,
    validate_organ_hierarchy,
    validate_organ_network,
)
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]


class FakeFaction:
    dissolved = False

    def __init__(self, assets=None):
        self._assets = dict(assets or {"cohesion": 0.5})
        self.organs = []
        self.characters = []
        self.flags = {}

    def asset(self, key, default=0.5):
        return float(self._assets.get(str(key), default))

    def add_asset(self, key, delta):
        self._assets[str(key)] = self.asset(key) + float(delta)

    def bump_context(self, key, delta):
        self.add_asset(key, delta)

    def organ(self, organ_id):
        return next(
            (
                organ
                for organ in self.organs
                if str(organ.id) == str(organ_id)
            ),
            None,
        )


def _organ(organ_id, parent_id="", **kwargs):
    return OrganRuntime.from_record(
        {"id": organ_id, "parent_id": parent_id, **kwargs}
    )


def test_organ_runtime_reads_parent_and_scales():
    organ = _organ(
        "cells",
        "agents",
        kind="intelligence",
        scales={"stealth": 0.4},
        scale_targets={"stealth": 0.8, "reach": 0.3},
    )
    assert organ.parent_id == "agents"
    assert organ.scales["stealth"] == pytest.approx(0.4)
    # Цель без текущего значения заводит шкалу, а не теряется.
    assert organ.scales["reach"] == pytest.approx(0.3)
    snapshot = organ.snapshot()
    assert snapshot["scales"]["stealth"] == pytest.approx(0.4)
    assert snapshot["scale_targets"]["reach"] == pytest.approx(0.3)


def test_hierarchy_helpers_build_tree_and_detect_cycles():
    root = _organ("root")
    middle = _organ("middle", "root")
    leaf = _organ("leaf", "middle")
    organs = [root, middle, leaf]

    assert organ_roots(organs) == ["root"]
    assert organ_children(organs) == {
        "root": ["middle"],
        "middle": ["leaf"],
        "leaf": [],
    }
    assert organ_depth(organs, "leaf") == 2
    assert organ_descendants(organs, "root") == ["middle", "leaf"]
    assert validate_organ_hierarchy(organs) == []

    middle.parent_id = "leaf"
    assert "цикл родителей" in " ".join(
        validate_organ_hierarchy(organs)
    )
    assert "цикл родителей" in " ".join(validate_organ_network(organs))

    leaf.parent_id = "missing"
    assert "неизвестный родитель" in " ".join(
        validate_organ_hierarchy(organs)
    )


def test_tick_pulls_child_to_parent_and_parent_to_children():
    faction = FakeFaction({"cohesion": 0.5})
    parent = _organ("parent", integrity=0.9)
    child = _organ("child", "parent", integrity=0.1)
    faction.organs = [parent, child]

    tick_organs(faction, faction.organs)

    assert child.integrity > 0.1
    assert parent.integrity < 0.9


def test_tick_moves_scale_to_parent_or_explicit_target():
    faction = FakeFaction({"cohesion": 0.5})
    parent = _organ("parent", integrity=0.5, scales={"stealth": 0.8})
    inherited = _organ(
        "inherited", "parent", integrity=0.5, scales={"stealth": 0.2}
    )
    explicit = _organ(
        "explicit",
        "parent",
        integrity=0.5,
        scales={"stealth": 0.2},
        scale_targets={"stealth": 0.9},
    )
    faction.organs = [parent, inherited, explicit]

    tick_organs(faction, faction.organs)

    assert inherited.scales["stealth"] > 0.2
    assert inherited.scales["stealth"] < 0.8
    assert explicit.scales["stealth"] > inherited.scales["stealth"]


def test_effects_conditions_and_snapshot_use_scales():
    faction = FakeFaction({"cohesion": 0.5})
    organ = _organ("agents", integrity=0.5, scales={"stealth": 0.4})
    faction.organs = [organ]

    report = apply_effects(
        faction, {"organs": {"agents": {"scales": {"stealth": 0.2}}}}
    )
    assert organ.scales["stealth"] == pytest.approx(0.6)
    assert report["organs"][0]["key"] == "scale:stealth"

    assert (
        check_conditions(
            [
                {
                    "kind": "organ",
                    "key": "agents",
                    "scale": "stealth",
                    "op": ">=",
                    "value": 0.6,
                }
            ],
            {"faction": faction},
        )
        == ""
    )
    assert organ.snapshot()["scales"]["stealth"] == pytest.approx(0.6)


@pytest.fixture(scope="module")
def preset():
    return CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    ).generate(seed=11)


@pytest.fixture
def campaign(preset):
    return AutomataCampaign(preset, seed=11)


def test_campaign_snapshot_preserves_organ_scales(preset, campaign):
    faction = campaign.faction("amber")
    organ = faction.organ("agents")
    organ.scales["stealth"] = 0.77
    restored = AutomataCampaign(
        preset, snapshot=campaign.save_snapshot()
    )
    assert restored.faction("amber").organ("agents").scales[
        "stealth"
    ] == pytest.approx(0.77)


def test_support_raises_target_and_survives_ticks():
    faction = FakeFaction({"cohesion": 0.5})
    plain = _organ("plain", integrity=0.5)
    supported = _organ("supported", integrity=0.5, support=0.2)
    faction.organs = [plain, supported]

    assert organ_target(faction, supported.kind, support=0.2) > (
        organ_target(faction, supported.kind, support=0.0)
    )

    tick_organs(faction, faction.organs)

    assert supported.integrity > plain.integrity
    assert 0.0 < supported.support < 0.2
    snapshot = supported.snapshot()
    assert snapshot["support"] == pytest.approx(supported.support)
    restored = OrganRuntime.from_record(snapshot)
    assert restored.support == pytest.approx(supported.support)


def test_campaign_organs_inherit_support_from_default_interactions():
    preset = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    ).generate(seed=11)
    campaign = AutomataCampaign(preset, seed=11)
    organ = campaign.player.organs[0]
    reinforce = organ.interaction("reinforce")
    resupply = organ.interaction("resupply")

    assert reinforce["support"] == pytest.approx(0.18)
    assert resupply["support"] == pytest.approx(0.12)
