"""JSON-снимок рабочей памяти Soar: валидация, версии и roundtrip."""

from __future__ import annotations

import pytest

from campaign.cognition import SnapshotError
from campaign.cognition.soar_snapshot import (
    SNAPSHOT_SCHEMA,
    SNAPSHOT_VERSION,
    STORE_SCHEMA,
    STORE_VERSION,
    SoarSnapshotStore,
    build_snapshot,
    validate_snapshot,
)

WM = [
    {
        "attribute": "self",
        "kind": "id",
        "children": [
            {"attribute": "name", "kind": "string", "value": "Ирина"},
            {"attribute": "hunger", "kind": "double", "value": 0.4},
            {"attribute": "tick", "kind": "int", "value": 7},
        ],
    },
    {"attribute": "tick", "kind": "int", "value": 7},
]


def _payload(**overrides):
    data = {
        "schema": SNAPSHOT_SCHEMA,
        "snapshot_version": SNAPSHOT_VERSION,
        "agent_id": "npc:irina",
        "ai_model": "npc_policy@test",
        "tick": 7,
        "counters": {"decisions": 3, "errors": 0},
        "wm": WM,
    }
    data.update(overrides)
    return data


def test_validate_snapshot_normalises_counters_and_nodes():
    data = validate_snapshot(_payload(counters={"z": 2, "a": 1}))

    assert data["schema"] == SNAPSHOT_SCHEMA
    assert data["snapshot_version"] == SNAPSHOT_VERSION
    assert data["agent_id"] == "npc:irina"
    assert list(data["counters"]) == ["a", "z"]
    assert data["wm"][0]["children"][1] == {
        "attribute": "hunger",
        "kind": "double",
        "value": 0.4,
    }


def test_build_snapshot_is_deterministic():
    first = build_snapshot(
        WM, agent_id="npc:irina", counters={"b": 2, "a": 1}
    )
    second = build_snapshot(
        WM, agent_id="npc:irina", counters={"a": 1, "b": 2}
    )

    assert first == second
    assert first["snapshot_version"] == SNAPSHOT_VERSION


def test_snapshot_rejects_future_version():
    with pytest.raises(SnapshotError):
        validate_snapshot(
            _payload(snapshot_version=SNAPSHOT_VERSION + 1)
        )


def test_snapshot_rejects_unknown_schema():
    with pytest.raises(SnapshotError):
        validate_snapshot(_payload(schema="soar_snapshot.v99"))


def test_snapshot_rejects_unknown_node_kind():
    broken = [{"attribute": "x", "kind": "vector", "value": 1}]

    with pytest.raises(SnapshotError):
        validate_snapshot(_payload(wm=broken))


def test_snapshot_requires_agent_id():
    with pytest.raises(SnapshotError):
        validate_snapshot(_payload(agent_id="  "))


def test_snapshot_rejects_too_deep_children():
    node = {"attribute": "leaf", "kind": "int", "value": 0}
    for _ in range(70):
        node = {
            "attribute": "child",
            "kind": "id",
            "children": [node],
        }

    with pytest.raises(SnapshotError):
        validate_snapshot(_payload(wm=[node]))


def test_soar_agent_snapshot_roundtrips():
    pytest.importorskip("soar_sml")
    from campaign.cognition.soar_runtime import SoarAgent

    first = SoarAgent(
        agent_id="npc:irina", ai_model="npc_policy@test"
    )
    try:
        first.add_wm(WM)
        first.tick = 7
        first.counters = {"decisions": 3}
        snapshot = first.snapshot()
    finally:
        first.close()

    second = SoarAgent(
        agent_id="npc:irina", ai_model="npc_policy@test"
    )
    try:
        restored = second.restore(snapshot)
        assert restored["agent_id"] == "npc:irina"
        assert second.snapshot() == snapshot
    finally:
        second.close()


def test_restore_twice_does_not_duplicate_wm():
    pytest.importorskip("soar_sml")
    from campaign.cognition.soar_runtime import SoarAgent

    agent = SoarAgent(agent_id="npc:irina")
    try:
        agent.add_wm(WM)
        snapshot = agent.snapshot()
        agent.restore(snapshot)
        agent.restore(snapshot)
        assert agent.snapshot() == snapshot
    finally:
        agent.close()


def test_snapshot_mirrors_typed_values():
    pytest.importorskip("soar_sml")
    from campaign.cognition.soar_runtime import SoarAgent

    agent = SoarAgent(agent_id="npc:irina")
    try:
        agent.add_wm(WM)
        snapshot = agent.snapshot()
    finally:
        agent.close()

    assert snapshot["wm"][0]["kind"] == "id"
    assert snapshot["wm"][0]["children"][1]["kind"] == "double"
    assert snapshot["wm"][1] == {
        "attribute": "tick",
        "kind": "int",
        "value": 7,
    }


def test_snapshot_refuses_foreign_agent():
    pytest.importorskip("soar_sml")
    from campaign.cognition.soar_runtime import SoarAgent

    agent = SoarAgent(agent_id="npc:irina")
    try:
        with pytest.raises(SnapshotError):
            agent.restore(_payload(agent_id="npc:other"))
    finally:
        agent.close()


def test_snapshot_store_roundtrips_per_agent():
    store = SoarSnapshotStore()
    irina = build_snapshot(WM, agent_id="npc:irina", tick=7)
    boris = build_snapshot([], agent_id="npc:boris")
    store.save(irina)
    store.save(boris)

    payload = store.to_dict()
    restored = SoarSnapshotStore.from_dict(payload)

    assert payload["schema"] == STORE_SCHEMA
    assert payload["snapshot_version"] == STORE_VERSION
    assert list(payload["agents"]) == ["npc:boris", "npc:irina"]
    assert len(restored) == 2
    assert restored.load("npc:irina") == irina
    assert restored.load("npc:boris") == boris
    assert restored.load("npc:missing") == {}


def test_snapshot_store_rejects_future_version():
    with pytest.raises(SnapshotError):
        SoarSnapshotStore.from_dict(
            {
                "schema": STORE_SCHEMA,
                "snapshot_version": STORE_VERSION + 1,
                "agents": {},
            }
        )


def test_snapshot_store_rejects_key_mismatch():
    payload = {
        "schema": STORE_SCHEMA,
        "snapshot_version": STORE_VERSION,
        "agents": {"npc:other": _payload(agent_id="npc:irina")},
    }

    with pytest.raises(SnapshotError):
        SoarSnapshotStore.from_dict(payload)
