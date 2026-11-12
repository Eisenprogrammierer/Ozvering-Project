"""Контракт подфракций: данные, эффекты, условия, автоматы и снимок."""

from __future__ import annotations

from pathlib import Path

import bdi
from campaign import content_lint
from campaign.automata import AutomataCampaign
from campaign.conditions import check_conditions
from campaign.effects import apply_effects
from campaign.faction_state import faction_metric
from campaign.preset import CampaignPresetGenerator, _organ_records
from campaign.preset import _subfaction_records
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]


def _preset(seed=7):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT
        / "configs"
        / "campaigns"
        / "empire_campaign.json",
    )
    preset = generator.generate(seed=seed)
    faction = next(
        item for item in preset.factions if item["side"] == "red"
    )
    faction["subfactions"] = [
        {
            "id": "orthodox",
            "label": "Ортодоксы",
            "share": 0.45,
            "assets": {"influence": 0.10, "grievance": 0.80},
            "organs": [
                {
                    "id": "orthodox_inquisition",
                    "name": "Ортодоксальная инквизиция",
                    "kind": "legitimacy",
                }
            ],
        },
        {
            "id": "revisionists",
            "label": "Ревизионисты",
            "share": 0.20,
            "assets": {"influence": 0.70, "grievance": 0.30},
        },
    ]
    return preset


def test_preset_flattens_nested_organs_and_records_subfactions():
    cfg = {
        "organs": [{"id": "staff", "name": "Ставка"}],
        "subfactions": [
            {
                "id": "orthodox",
                "label": "Ортодоксы",
                "share": 0.5,
                "assets": {"influence": 0.7},
                "organs": [{"id": "inquisition", "name": "Инквизиция"}],
            }
        ],
    }
    organs = _organ_records(cfg)
    assert {item["id"] for item in organs} == {"staff", "inquisition"}
    assert next(
        item for item in organs if item["id"] == "inquisition"
    )["subfaction_id"] == "orthodox"
    subs = _subfaction_records(cfg)
    assert subs[0]["organ_ids"] == ["inquisition"]
    assert "organs" not in subs[0]


def test_runtime_builds_subfactions_and_nested_organs():
    campaign = AutomataCampaign(_preset())
    faction = campaign.faction("red")
    assert [item.id for item in faction.subfactions] == [
        "orthodox",
        "revisionists",
    ]
    organ = faction.organ("orthodox_inquisition")
    assert organ is not None
    assert organ.subfaction_id == "orthodox"
    assert "revisionists" in campaign.subfaction_machines["red"]


def test_effects_conditions_and_metrics_read_subfactions():
    campaign = AutomataCampaign(_preset())
    faction = campaign.faction("red")
    sub = faction.subfaction("orthodox")
    applied = apply_effects(
        faction,
        {
            "subfactions": {
                "orthodox": {
                    "assets": {"influence": 0.4},
                    "share": 0.1,
                }
            }
        },
        scale=1.0,
    )
    assert sub.asset("influence") == 0.5
    assert sub.share == 0.55
    assert applied["subfactions"]
    context = {
        "faction": faction,
        "subfaction": sub,
    }
    assert (
        check_conditions(
            {
                "kind": "subfaction",
                "asset": "influence",
                "op": ">=",
                "value": 0.5,
            },
            context,
        )
        == ""
    )
    assert check_conditions(
        {
            "kind": "subfaction",
            "asset": "influence",
            "op": "<",
            "value": 0.5,
        },
        context,
    )
    assert faction_metric(
        faction, "subfactions.orthodox.influence"
    ) == 0.5
    assert faction_metric(
        faction, "subfactions.max:influence"
    ) == 0.7


def test_unknown_subfaction_effect_is_ignored_not_an_asset():
    campaign = AutomataCampaign(_preset())
    faction = campaign.faction("red")
    applied = apply_effects(
        faction,
        {"subfactions": {"missing": {"assets": {"influence": 0.5}}}},
    )
    assert applied["subfactions"] == []
    assert applied["ignored"]


def test_subfaction_machine_ticks_and_snapshot_roundtrip():
    preset = _preset()
    campaign = AutomataCampaign(preset)
    machine = campaign.subfaction_machines["red"]["orthodox"]
    assert machine.state == "loyal"
    campaign.end_turn()
    assert machine.state == "sidelined"
    campaign.faction("red").subfaction("orthodox").assets[
        "influence"
    ] = 0.5
    campaign.end_turn()
    assert machine.state == "ascendant"

    restored = AutomataCampaign(
        preset, snapshot=campaign.save_snapshot()
    )
    restored_sub = restored.faction("red").subfaction("orthodox")
    assert restored_sub.asset("influence") == 0.5
    assert (
        restored.subfaction_machines["red"]["orthodox"].state
        == "ascendant"
    )
    assert restored.snapshot() == campaign.snapshot()


def test_linter_checks_subfaction_references():
    config = bdi.load_bdi()
    problems = content_lint.check_faction(
        "red",
        {
            "id": "faction.a",
            "organs": [{"id": "staff"}],
            "subfactions": [
                {
                    "id": "orthodox",
                    "share": 1.5,
                    "assets": [],
                    "organ_ids": ["missing"],
                }
            ],
        },
        config,
    )
    assert any("share" in item for item in problems)
    assert any("assets" in item for item in problems)
    assert any("неизвестный орган" in item for item in problems)
