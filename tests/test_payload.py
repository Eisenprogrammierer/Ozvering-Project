"""Типизированный payload работы (§7.1 №4)."""

import json

import pytest

from core41 import (
    Automaton,
    PAYLOAD_KINDS,
    PayloadError,
    Work,
    apply_payload,
    describe_payload,
    make_payload,
    normalize_payload,
    payload_fields,
    payload_kind,
    payload_map,
    payload_state,
)


def test_typed_payload_is_canonical_immutable_and_roundtrips_json():
    payload = make_payload(
        "item",
        item_id="sealed_orders",
        quantity=2,
        quality=0.8,
    )
    assert isinstance(payload, tuple)
    assert payload[0] == ("kind", "item")
    assert payload_kind(payload) == "item"
    assert payload_map(payload)["quantity"] == 2.0
    assert payload_fields(payload) == {
        "item_id": "sealed_orders",
        "quantity": 2.0,
        "quality": 0.8,
        "label": "",
    }
    # Нормализация и JSON-круговорот не теряют схему.
    assert normalize_payload(payload) == payload
    assert normalize_payload(dict(payload)) == payload
    assert normalize_payload(json.loads(json.dumps(dict(payload)))) == payload


def test_payload_schema_rejects_typos_and_missing_required_fields():
    with pytest.raises(PayloadError):
        make_payload("item", item_id="seal", quantity=1, qty=1)
    with pytest.raises(PayloadError):
        make_payload("item", quantity=1)
    with pytest.raises(PayloadError):
        make_payload("unknown", item_id="seal")
    with pytest.raises(PayloadError):
        make_payload("item", item_id="seal", quantity={"bad": 1})
    with pytest.raises(PayloadError):
        normalize_payload([("kind", "item")])
    assert "item" in PAYLOAD_KINDS


def test_opaque_payload_without_kind_keeps_backward_compatibility():
    payload = normalize_payload([("a", 1), ("b", "x")])
    assert payload == (("a", 1), ("b", "x"))
    assert payload_kind(payload) == ""
    assert payload_map(payload) == {"a": 1, "b": "x"}
    assert normalize_payload(()) == ()


def test_apply_payload_updates_state_without_touching_energy_or_force():
    unit = Automaton("unit")
    before = (unit.energy, unit.force, unit.health)
    applied = apply_payload(
        unit,
        make_payload("item", item_id="seal", quantity=3),
    )
    assert applied == [("item:seal", 3.0)]
    assert unit.state["items"] == {"seal": 3.0}
    assert (unit.energy, unit.force, unit.health) == before

    apply_payload(
        unit,
        make_payload(
            "evidence", claim="казна пуста", strength=0.7, subject="city"
        ),
    )
    apply_payload(
        unit,
        make_payload("info", topic="harbor", confidence=0.9),
    )
    apply_payload(
        unit,
        make_payload("order", action="inspect", target="port"),
    )
    state = payload_state(unit)
    assert state["evidence"][0]["claim"] == "казна пуста"
    assert state["knowledge"]["harbor"] == pytest.approx(0.9)
    assert state["orders"][0]["action"] == "inspect"


def test_payload_history_is_bounded_and_described_in_russian():
    unit = Automaton("unit")
    for index in range(100):
        apply_payload(
            unit,
            make_payload("evidence", claim="факт %d" % index),
        )
    assert len(unit.state["evidence"]) == 32
    assert "свидетельство" in describe_payload(
        make_payload("evidence", claim="факт")
    )
    assert "предмет" in describe_payload(
        make_payload("item", item_id="seal")
    )
    assert "приказ" in describe_payload(
        make_payload("order", action="inspect")
    )
    assert "сведения" in describe_payload(
        make_payload("info", topic="harbor")
    )
    assert "принуждение" in describe_payload(
        make_payload("force", intent="pressure")
    )


def test_automaton_receive_reports_and_applies_typed_payload():
    unit = Automaton("unit")
    work = Work(
        amount=4.0,
        form="info",
        payload=make_payload("item", item_id="press_folder", quantity=1),
    )
    report = unit.receive(work)
    assert report["accepted"] is True
    assert report["payload"]["kind"] == "item"
    assert report["payload_applied"] == [("item:press_folder", 1.0)]
    assert unit.state["items"]["press_folder"] == 1.0


def test_bad_payload_does_not_cancel_accepted_work():
    unit = Automaton("unit")
    report = unit.receive(
        Work(amount=4.0, form="info", payload=(("kind", "item"),))
    )
    assert report["accepted"] is True
    assert "payload_error" in report
    assert "items" not in unit.state
