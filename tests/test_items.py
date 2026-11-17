"""Предмет — автомат ``I/O/H/S/F/E/W``, а не бонус к строке.

Проверяется контракт данных: у предмета есть входы/выходы, обработчики,
состояние, сила, энергия и журнал работ. Действие ``use_item`` запускает
обработчик из JSON, меняет состояние именно этого предмета и переживает
снимок мира; старый сейв без блока автоматов читается как раньше.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.item_automaton import ITEM_AUTOMATON_SCHEMA
from campaign.world import (
    WorldEngine,
    build_player_profile,
    load_world,
)

ROOT = Path(__file__).resolve().parents[1]
WORLDS = ROOT / "configs" / "worlds"


@pytest.fixture(scope="module")
def world():
    return load_world(WORLDS / "agora_world.json")


def _engine(
    world,
    node_id="agora_street",
    office_id="street_musician",
    seed=7,
):
    engine = WorldEngine(
        world,
        profile=build_player_profile({"name": "Тест"}, seed=seed),
        node_id=node_id,
        office_id=office_id,
        seed=seed,
    )
    assert engine.attach(node_id, office_id)["ok"] is True
    engine._roll = lambda token: 0.0
    return engine


def test_items_declare_iohsfew_automata(world):
    engine = _engine(world)
    for item_id in ("personal_seal", "street_lute", "charter_draft"):
        automaton = engine.item_automaton(item_id)
        assert automaton is not None
        assert automaton["schema"] == ITEM_AUTOMATON_SCHEMA
        for key in (
            "inputs",
            "outputs",
            "handlers",
            "state",
            "force",
            "max_force",
            "energy",
            "max_energy",
            "work",
        ):
            assert key in automaton
    lute = engine.item_automaton("street_lute")
    assert "play" in lute["handlers"]
    assert lute["default_handler"] == "play"
    assert "info" in lute["inputs"]
    assert "info" in lute["outputs"]


def test_use_item_runs_handler_and_changes_its_state(world):
    engine = _engine(world)
    assert "street_lute" in engine.player_item_ids
    before = engine.item_automaton("street_lute")
    node = engine.node("agora_street")
    cohesion = float(node["stats"].get("cohesion", 0.0))

    result = engine.execute(
        "use_item", target_ref={"kind": "item", "id": "street_lute"}
    )
    assert result["ok"] is True
    assert result["outcome"] == "success"

    after = engine.item_automaton("street_lute")
    assert after["energy"] < before["energy"]
    assert after["force"] < before["force"]
    assert after["state"]["wear"] > before["state"]["wear"]
    assert after["work"][-1]["handler"] == "play"
    assert float(node["stats"].get("cohesion", 0.0)) > cohesion


def test_broken_item_is_disabled_with_reason(world):
    engine = _engine(world)
    target = {"kind": "item", "id": "street_lute"}
    engine.item_automata["street_lute"]["force"] = 0.0
    allowed, reason = engine.validate("use_item", target_ref=target)
    assert allowed is False
    assert reason == "предмет сломан"

    engine._reset_item_automaton("street_lute")
    engine.item_automata["street_lute"]["energy"] = 0.0
    allowed, reason = engine.validate("use_item", target_ref=target)
    assert allowed is False
    assert reason == "предмету не хватает запаса"


def test_charter_draft_seals_norm_and_is_consumed(world):
    engine = _engine(world)
    engine._apply_item_effects(
        {"action": "grant", "id": "charter_draft"}
    )
    assert "charter_draft" in engine.player_item_ids

    result = engine.execute(
        "use_item",
        target_ref={"kind": "item", "id": "charter_draft"},
    )
    assert result["ok"] is True
    assert "charter_draft" not in engine.player_item_ids
    assert "charter_draft" in engine.consumed_items
    automaton = engine.item_automaton("charter_draft")
    assert automaton["work"][-1]["handler"] == "seal"
    assert engine.norms["sealed_charter"]["status"] == "active"
    assert engine.entity_ref(engine.norms["sealed_charter"]) == {
        "kind": "norm",
        "id": "sealed_charter",
    }


def test_item_automaton_survives_snapshot_and_old_save(world):
    engine = _engine(world)
    engine.execute(
        "use_item", target_ref={"kind": "item", "id": "street_lute"}
    )
    snapshot = engine.to_dict()
    saved = snapshot["player"]["item_automata"]["street_lute"]
    assert saved["schema"] == ITEM_AUTOMATON_SCHEMA
    assert saved["work"]

    restored = WorldEngine(world, snapshot=snapshot)
    after = restored.item_automaton("street_lute")
    assert after["energy"] == pytest.approx(saved["energy"])
    assert after["force"] == pytest.approx(saved["force"])
    for key, value in saved["state"].items():
        assert after["state"][key] == pytest.approx(value)
    assert after["work"] == saved["work"]

    legacy = engine.to_dict()
    legacy["player"].pop("item_automata")
    old = WorldEngine(world)
    old.load_snapshot(legacy)
    fresh = old.item_automaton("street_lute")
    assert fresh["energy"] == pytest.approx(fresh["max_energy"])
    assert fresh["state"] == {"wear": 0.0, "tuning": 1.0}
    assert fresh["work"] == []
