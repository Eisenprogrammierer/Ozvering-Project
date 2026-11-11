"""Тесты проекций старых шкал и версии снимка (WORLD_CORE_MODEL §7.2)."""

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.errors import CampaignError
from campaign.preset import CampaignPresetGenerator
from campaign.projections import (
    PROJECTIONS,
    SCHEMA_VERSION,
    core_state,
    describe_projection,
    ensure_supported_snapshot,
    player_projection_view,
    projection,
    snapshot_version,
    stamp_snapshot,
)
from campaign.roles import RoleCatalog
from campaign.world import WorldEngine, load_world

ROOT = Path(__file__).resolve().parents[1]


def _engine():
    return WorldEngine(load_world(), seed=11)


def _campaign():
    return AutomataCampaign(_campaign_preset(), seed=11)


def test_projection_registry_explains_every_legacy_scale():
    for name in (
        "standing",
        "power",
        "wealth",
        "actions_left",
        "health",
        "legitimacy",
        "cohesion",
        "reach",
        "capacity",
        "influence",
        "favor",
        "evidence",
    ):
        entry = projection(name)
        assert entry is not None, name
        assert entry["core"]
        assert entry["kind"]
        assert name in describe_projection(name)
        assert entry["note"] in describe_projection(name)
    assert projection("unknown") is None
    assert describe_projection("unknown") == "unknown"
    for name in ("influence", "favor", "evidence"):
        assert PROJECTIONS[name]["core"] != "E"


def test_core_state_normalizes_ratios_fatigue_and_defaults():
    state = core_state(
        {
            "force": 50.0,
            "max_force": 100.0,
            "energy": 25.0,
            "max_energy": 100.0,
            "health": 80.0,
            "max_health": 100.0,
            "sickness": 0.2,
            "wound": 0.1,
        }
    )
    assert state["force_ratio"] == pytest.approx(0.5)
    assert state["energy_ratio"] == pytest.approx(0.25)
    assert state["health_ratio"] == pytest.approx(0.8)
    assert state["fatigue"] == pytest.approx(0.75)
    assert state["alive"] is True
    empty = core_state({})
    assert empty["force_ratio"] == 0.0
    assert empty["energy_ratio"] == 0.0
    assert empty["fatigue"] == 1.0
    assert empty["alive"] is False
    # Смерть определяется силой, а не здоровьем.
    assert core_state({"force": 1.0, "health": 0.0})["alive"] is True
    assert core_state({"force": 0.0, "health": 100.0})["alive"] is False


def test_player_projection_view_keeps_core_and_legacy_in_sync():
    engine = _engine()
    engine.player_force = 0.4
    engine.player_energy = 60.0
    view = engine.projection_view()
    condition = engine.player_condition()
    assert view["core"]["force"] == pytest.approx(condition["force"])
    assert view["core"]["energy"] == pytest.approx(condition["energy"])
    assert view["core"]["health"] == pytest.approx(condition["health"])
    assert view["legacy"]["standing"] == pytest.approx(view["core"]["force"])
    assert view["legacy"]["actions_left"] == condition["actions_left"]
    assert view["legacy"]["health"] == pytest.approx(view["core"]["health"])
    for key in ("standing", "actions_left", "health"):
        assert key in view["notes"]
        assert "→" in view["notes"][key]
    assert list(view) == ["core", "legacy", "notes"]


def test_snapshot_is_stamped_and_future_version_is_rejected():
    engine = _engine()
    payload = engine.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert snapshot_version(payload) == SCHEMA_VERSION

    legacy = dict(payload)
    legacy.pop("schema_version")
    assert snapshot_version(legacy) == 0
    restored = WorldEngine(load_world(), snapshot=legacy)
    assert restored.day == engine.day
    assert ensure_supported_snapshot(legacy) == 0

    newer = dict(payload)
    newer["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(CampaignError):
        WorldEngine(load_world(), snapshot=newer)

    raw = {"day": 1}
    stamped = stamp_snapshot(raw)
    assert "schema_version" not in raw
    assert stamped["schema_version"] == SCHEMA_VERSION


def test_automata_campaign_snapshot_carries_schema_version():
    campaign = _campaign()
    payload = campaign.save_snapshot()
    assert payload["schema_version"] == SCHEMA_VERSION
    restored = AutomataCampaign(_campaign_preset(), snapshot=payload)
    assert restored.turn == campaign.turn

    future = dict(payload)
    future["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(CampaignError):
        AutomataCampaign(_campaign_preset(), snapshot=future)


def _campaign_preset():
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    )
    return generator.generate(seed=11)
