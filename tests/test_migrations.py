"""P7: версии снимков и миграция старых сохранений.

Старый снимок не переписывается на диске: загрузчик принимает прежнюю
версию, заполняет отсутствующие поля значениями по умолчанию и только в
памяти помечает снимок текущей схемой. Снимок из будущего отвергается.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.errors import CampaignError
from campaign.projections import (
    SCHEMA_VERSION,
    migrate_snapshot,
    snapshot_version,
)
from campaign.world import (
    WorldEngine,
    build_player_profile,
    load_world,
)

ROOT = Path(__file__).resolve().parents[1]


def _engine(world):
    engine = WorldEngine(
        world,
        profile=build_player_profile({"name": "Тест"}, seed=7),
        node_id="agora_street",
        office_id="street_musician",
        seed=7,
    )
    assert engine.attach("agora_street", "street_musician")["ok"] is True
    return engine


def test_current_schema_covers_avatar_entity_ref_and_scene():
    assert SCHEMA_VERSION >= 2


def test_migrate_snapshot_stamps_without_mutating():
    old = {"day": 4, "player": {"node_id": "agora_street"}}
    migrated = migrate_snapshot(old)

    assert "schema_version" not in old
    assert migrated["schema_version"] == SCHEMA_VERSION
    assert migrated["day"] == 4
    assert migrated is not old


def test_future_snapshot_is_rejected():
    with pytest.raises(CampaignError):
        migrate_snapshot({"schema_version": SCHEMA_VERSION + 1})


def test_v1_world_snapshot_loads_with_defaults():
    world = load_world(ROOT / "configs" / "worlds" / "agora_world.json")
    engine = _engine(world)
    snapshot = engine.to_dict()
    snapshot["schema_version"] = 1
    snapshot.pop("scene", None)
    snapshot["player"].pop("granted_items", None)
    snapshot["player"].pop("consumed_items", None)
    snapshot["player"].pop("items", None)

    restored = _engine(world)
    restored.load_snapshot(snapshot)

    assert snapshot_version(snapshot) == 1
    assert "schema_version" not in snapshot or snapshot["schema_version"] == 1
    assert restored.scene_id == ""
    assert restored.player_item_ids
    assert restored.day == engine.day


def test_v0_world_snapshot_without_optional_fields_loads():
    world = load_world(ROOT / "configs" / "worlds" / "agora_world.json")
    snapshot = {
        "world_id": world["id"],
        "day": 2,
        "profile": {},
        "player": {
            "node_id": "agora_street",
            "office_id": "street_musician",
        },
    }

    engine = _engine(world)
    engine.load_snapshot(snapshot)

    assert snapshot_version(snapshot) == 0
    assert engine.day == 2
    assert engine.scene_id == ""
    assert engine.player_item_ids
