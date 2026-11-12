"""Контракт исполняемых автоматов кампании.

Автомат — данные: состояния, переходы и эффекты не живут в Python.
Тесты держат приоритеты, условия, ``on_enter``/``on_tick``, обработчики,
снимок и связку с кампанией.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog
from campaign.state_machine import (
    StateMachine,
    StateMachineCatalog,
    StateMachineDefinition,
    StateMachineError,
    default_root,
    load_catalog,
    machine_map,
)

ROOT = Path(__file__).resolve().parents[1]


class _Actor:
    """Минимальная действующая сторона для движка эффектов."""

    def __init__(self):
        self.assets = {"legitimacy": 0.5}
        self.flags = {}
        self.characters = []

    def add_asset(self, key, delta):
        self.assets[str(key)] = self.assets.get(str(key), 0.0) + delta


def _definition(states, initial="a", handlers=None, kind="faction"):
    return StateMachineDefinition.from_data(
        {
            "schema": 2,
            "id": "test.machine",
            "kind": kind,
            "initial": initial,
            "states": states,
            "handlers": handlers or {},
        }
    )


def _campaign(seed=7):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT
        / "configs"
        / "campaigns"
        / "empire_campaign.json",
    )
    return generator.generate(seed=seed)


def test_transition_requires_condition_and_stays_stable():
    definition = _definition(
        {
            "a": {
                "transitions": [
                    {
                        "to": "b",
                        "when": [
                            {
                                "kind": "turn",
                                "op": ">=",
                                "value": 2,
                            }
                        ],
                    }
                ]
            },
            "b": {"transitions": []},
        }
    )
    machine = StateMachine(definition)
    assert machine.tick({"turn": 1}) == []
    assert machine.state == "a"
    reports = machine.tick({"turn": 2})
    assert machine.state == "b"
    assert reports[0]["from"] == "a"
    assert reports[0]["to"] == "b"


def test_priority_wins_over_declaration_order():
    definition = _definition(
        {
            "a": {
                "transitions": [
                    {"to": "b", "priority": 1},
                    {"to": "c", "priority": 10},
                ]
            },
            "b": {},
            "c": {},
        }
    )
    machine = StateMachine(definition)
    machine.tick({})
    assert machine.state == "c"


def test_on_enter_effect_uses_single_write_engine():
    definition = _definition(
        {
            "a": {"transitions": [{"to": "b"}]},
            "b": {"on_enter": [{"flags": {"entered": True}}]},
        }
    )
    actor = _Actor()
    machine = StateMachine(definition)
    reports = machine.tick({}, actor=actor)
    assert machine.state == "b"
    assert actor.flags["entered"] is True
    assert reports[0]["effects"][0]["flags"][0]["key"] == "entered"


def test_on_tick_effect_runs_before_transition():
    definition = _definition(
        {
            "a": {
                "on_tick": [
                    {"self": {"assets": {"legitimacy": 0.1}}}
                ],
                "transitions": [
                    {
                        "to": "b",
                        "when": [
                            {
                                "kind": "asset",
                                "key": "legitimacy",
                                "op": ">=",
                                "value": 0.55,
                            }
                        ],
                    }
                ],
            },
            "b": {},
        }
    )
    actor = _Actor()
    machine = StateMachine(definition)
    machine.tick({}, actor=actor)
    assert actor.assets["legitimacy"] == pytest.approx(0.6)
    assert machine.state == "b"


def test_handler_respects_when_and_applies_effects():
    definition = _definition(
        {
            "a": {},
        },
        handlers={
            "alarm": {
                "when": [
                    {
                        "kind": "turn",
                        "op": ">=",
                        "value": 2,
                    }
                ],
                "effects": {"flags": {"alarm": True}},
            }
        },
    )
    actor = _Actor()
    machine = StateMachine(definition)
    assert machine.handle("alarm", {"turn": 1}, actor=actor) == []
    assert "alarm" not in actor.flags
    machine.handle("alarm", {"turn": 2}, actor=actor)
    assert actor.flags["alarm"] is True


def test_snapshot_roundtrip_keeps_state_and_history():
    definition = _definition(
        {
            "a": {"transitions": [{"to": "b"}]},
            "b": {"transitions": [{"to": "c"}]},
            "c": {},
        }
    )
    machine = StateMachine(definition)
    machine.tick({})
    machine.tick({})
    restored = StateMachine.from_dict(machine.to_dict(), definition)
    assert restored.state == "c"
    assert restored.history == ["a", "b"]
    assert restored.to_dict() == machine.to_dict()


def test_definition_rejects_broken_target_and_unknown_kind():
    with pytest.raises(StateMachineError):
        _definition({"a": {"transitions": [{"to": "missing"}]}})
    with pytest.raises(StateMachineError):
        _definition({"a": {}}, kind="army")


def test_default_catalog_has_faction_and_organ(tmp_path):
    catalog = load_catalog()
    faction = catalog.first("faction")
    organ = catalog.first("organ")
    assert faction is not None and faction.initial == "latent"
    assert organ is not None and organ.initial == "forming"
    assert default_root().is_dir()
    machines = machine_map(
        catalog, kind="faction", ids=["red", "blue"]
    )
    assert set(machines) == {"red", "blue"}
    assert all(
        item.state == faction.initial for item in machines.values()
    )
    empty = StateMachineCatalog.load(tmp_path)
    assert empty.machines == {}


def test_catalog_skips_editor_graphs(tmp_path):
    (tmp_path / "editor.json").write_text(
        json.dumps(
            {
                "version": 1,
                "name": "Граф редактора",
                "states": [{"id": "s1", "name": "Старт"}],
                "transitions": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "machine.json").write_text(
        json.dumps(
            {
                "schema": 2,
                "id": "test.machine",
                "kind": "faction",
                "initial": "a",
                "states": {"a": {}},
            }
        ),
        encoding="utf-8",
    )
    catalog = StateMachineCatalog.load(tmp_path)
    assert list(catalog.machines) == ["test.machine"]


def test_campaign_ticks_and_persists_machines():
    preset = _campaign(seed=7)
    campaign = AutomataCampaign(preset)
    assert campaign.faction_machines["red"].state == "latent"
    organ_machines = campaign.organ_machines["red"]
    assert organ_machines
    assert all(
        item.state == "forming" for item in organ_machines.values()
    )

    campaign.end_turn()
    assert campaign.faction_machines["red"].state != "latent"
    assert campaign.faction("red").flags["faction_mobilizing"] is True
    assert all(
        item.state != "forming" for item in organ_machines.values()
    )

    restored = AutomataCampaign(
        preset, snapshot=campaign.save_snapshot()
    )
    assert restored.snapshot() == campaign.snapshot()
    assert {
        side: machine.state
        for side, machine in restored.faction_machines.items()
    } == {
        side: machine.state
        for side, machine in campaign.faction_machines.items()
    }
    for side, machines in campaign.organ_machines.items():
        for organ_id, machine in machines.items():
            assert (
                restored.organ_machines[side][organ_id].state
                == machine.state
            )
