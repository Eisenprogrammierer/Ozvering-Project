"""Граница управления BDI-персонажами (WORLD_CORE_MODEL §7.3)."""

import pytest

from campaign.control import (
    AUTONOMY_BRANCHES,
    CONTROL_SCOPES,
    DirectiveBook,
)
from campaign.errors import CampaignError
from campaign.world import WorldEngine, load_world


def _engine(seed=11):
    return WorldEngine(load_world(), seed=seed)


def _character(engine):
    return engine.characters[engine.character_order[0]]


def test_directive_book_validates_scopes_payloads_and_expiry():
    book = DirectiveBook()
    directive = book.set(
        "c1", "autonomy", {"enabled": False}, day=3, expires_day=5
    )
    assert directive.scope == "autonomy"
    assert book.autonomy_enabled("c1", 3) is False
    assert book.autonomy_enabled("c1", 6) is True
    assert book.get("c1", "autonomy", 6) is None

    for scope in CONTROL_SCOPES:
        payload = {
            "autonomy": False,
            "beliefs": {"trust": 0.4},
            "desires": {"survive": 1.0},
            "intentions": "probe",
            "work_queue": "manual",
        }[scope]
        book.set("c1", scope, payload, day=1)
        assert book.get("c1", scope, 1) is not None

    with pytest.raises(CampaignError):
        book.set("c1", "chaos", True)
    with pytest.raises(CampaignError):
        book.set("", "autonomy", True)
    with pytest.raises(CampaignError):
        book.set("c1", "intentions", "betray")
    with pytest.raises(CampaignError):
        book.set("c1", "beliefs", "not-a-map")

    assert book.clear("c1", "autonomy") == 1
    assert book.get("c1", "autonomy", 1) is None
    assert book.clear("c1") >= 1
    assert book.items == []


def test_directive_book_roundtrip_and_active_view():
    book = DirectiveBook()
    book.set("c1", "intentions", "reconcile", day=1, expires_day=4)
    book.set("c2", "autonomy", False, day=2, expires_day=2)
    payload = book.to_list()
    restored = DirectiveBook().load(payload)
    assert restored.to_list() == payload
    assert restored.intended_branch("c1", 3) == "reconcile"
    assert restored.intended_branch("c1", 5) == ""
    assert restored.autonomy_enabled("c2", 2) is False
    assert restored.autonomy_enabled("c2", 3) is True
    assert set(restored.view(day=3)) == {"c1"}
    assert restored.prune(3) == 1
    assert restored.prune(5) == 1
    assert restored.items == []


def test_autonomy_directive_suspends_and_then_restores_contacts():
    engine = _engine()
    character = _character(engine)
    character["autonomous"] = True
    character["autonomy_period"] = 1

    engine.set_directive(character["id"], "autonomy", False, days=1)
    control = engine.character_control(character["id"])
    assert control["autonomy_enabled"] is False
    assert control["directives"]["autonomy"] == {"enabled": False}

    engine.end_day()
    assert engine.intents.due(engine.day) == []

    engine.end_day()
    control = engine.character_control(character["id"])
    assert control["autonomy_enabled"] is True
    assert engine.intents.due(engine.day)


def test_intention_directive_overrides_autonomy_policy():
    engine = _engine(seed=11)
    character = engine.characters[engine.character_order[1]]
    character["autonomous"] = True
    character["autonomy_period"] = 1
    character["affinity"] = 0.5
    character["trust"] = 0.9
    engine.set_directive(character["id"], "intentions", "reconcile", days=2)

    engine.end_day()
    pending = [
        intent
        for intent in engine.intents.due(engine.day)
        if intent.actor == character["id"]
    ]
    assert pending
    assert pending[0].payload["policy"] == "reconcile"
    assert pending[0].payload["policy"] in AUTONOMY_BRANCHES

    engine.clear_directive(character["id"], "intentions")
    assert (
        engine.character_control(character["id"])["intended_branch"] == ""
    )


def test_unknown_character_and_snapshot_roundtrip():
    engine = _engine()
    character = _character(engine)
    with pytest.raises(CampaignError):
        engine.set_directive("nope", "autonomy", False)

    engine.set_directive(
        character["id"], "beliefs", {"trust": 0.25}, days=3
    )
    engine.set_directive(
        character["id"], "desires", {"survive": 0.9}, days=3
    )
    snapshot = engine.to_dict()
    assert snapshot["directives"] == engine.directives.to_list()
    restored = WorldEngine(load_world(), snapshot=snapshot)
    assert restored.directives.to_list() == engine.directives.to_list()
    view = restored.directive_view(character["id"])
    assert view[character["id"]]["beliefs"] == {"trust": 0.25}
    assert view[character["id"]]["desires"] == {"survive": 0.9}

    legacy = dict(snapshot)
    legacy.pop("directives")
    assert WorldEngine(load_world(), snapshot=legacy).directives.items == []
