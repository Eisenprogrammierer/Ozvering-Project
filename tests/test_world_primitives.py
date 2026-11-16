"""P4: примитивы телесности, обряда, права, искусства, обучения и заботы.

Проверяется не текст, а контракт данных: новая форма существует в
манифесте, действие адресует человека/место/норму через ``entity_ref``,
эффекты меняют состояние именно этой сущности, а расход предмета и
обязательство переживают пересборку инвентаря и снимок мира.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.actions import FormCatalog
from campaign.world import (
    WorldEngine,
    build_player_profile,
    load_world,
)

ROOT = Path(__file__).resolve().parents[1]
WORLDS = ROOT / "configs" / "worlds"
HANDLERS = ROOT / "configs" / "campaigns" / "base" / "handlers"


@pytest.fixture(scope="module")
def world():
    return load_world(WORLDS / "agora_world.json")


def _engine(world, seed=7):
    engine = WorldEngine(
        world,
        profile=build_player_profile({"name": "Тест"}, seed=seed),
        node_id="agora_street",
        office_id="street_musician",
        seed=seed,
    )
    assert engine.attach("agora_street", "street_musician")["ok"] is True
    engine._roll = lambda token: 0.0
    return engine


def test_p4_forms_are_declared_with_handlers():
    forms = FormCatalog.load()
    for form_id in (
        "contact",
        "ritual",
        "law",
        "art",
        "education",
        "personal_care",
    ):
        form = forms.require(form_id)
        assert form.target_kinds
        assert (HANDLERS / ("%s.json" % form_id)).is_file()


def test_kiss_requires_consent_and_changes_the_person(world):
    engine = _engine(world)
    character_id = engine.character_order[0]
    character = engine.characters[character_id]

    character["affinity"] = 0.0
    character["trust"] = 0.0
    allowed, reason = engine.validate(
        "kiss", target_ref={"kind": "character", "id": character_id}
    )
    assert allowed is False
    assert reason

    character["affinity"] = 0.5
    character["trust"] = 0.5
    before = float(character["affinity"])
    result = engine.execute(
        "kiss", target_ref={"kind": "character", "id": character_id}
    )
    assert result["ok"] is True
    assert result["outcome"] == "success"
    assert float(character["affinity"]) > before


def test_embrace_addresses_character_not_node(world):
    engine = _engine(world)
    character_id = engine.character_order[0]
    character = engine.characters[character_id]
    before = float(character["trust"])
    result = engine.execute(
        "embrace", target_ref={"kind": "character", "id": character_id}
    )
    assert result["ok"] is True
    assert float(character["trust"]) > before
    assert {ref["kind"] for ref in engine.action_targets("embrace")} == {
        "character"
    }


def test_sacrifice_consumes_item_and_survives_refresh(world):
    engine = _engine(world)
    assert "personal_seal" in engine.player_item_ids
    result = engine.execute(
        "offer_sacrifice",
        target_ref={"kind": "place", "id": "agora_street"},
    )
    assert result["ok"] is True
    assert "personal_seal" not in engine.player_item_ids
    assert "personal_seal" in engine.consumed_items

    engine._refresh_items()
    assert "personal_seal" not in engine.player_item_ids

    restored = WorldEngine(
        world,
        profile=build_player_profile({"name": "Тест"}, seed=7),
        node_id="agora_street",
        office_id="street_musician",
        seed=7,
    )
    restored.load_snapshot(engine.to_dict())
    restored._refresh_items()
    assert "personal_seal" not in restored.player_item_ids
    assert "personal_seal" in restored.consumed_items


def test_sacrifice_requires_item(world):
    engine = _engine(world)
    engine.player_item_ids = [
        item_id
        for item_id in engine.player_item_ids
        if item_id != "personal_seal"
    ]
    allowed, reason = engine.validate(
        "offer_sacrifice",
        target_ref={"kind": "place", "id": "agora_street"},
    )
    assert allowed is False
    assert "предмет" in reason


def test_propose_law_creates_addressable_norm(world):
    engine = _engine(world)
    assert "street_charter" not in engine.norms
    result = engine.execute(
        "propose_law",
        target_ref={"kind": "norm", "id": "agora_charter"},
    )
    assert result["ok"] is True
    norm = engine.norms["street_charter"]
    assert norm["status"] == "active"
    assert engine.entity({"kind": "norm", "id": "street_charter"}) is norm
    assert engine.entity_ref(norm) == {"kind": "norm", "id": "street_charter"}
    assert {"kind": "norm", "id": "street_charter"} in engine.known_entities(
        ["norm"]
    )


def test_song_targets_place_and_changes_its_cohesion(world):
    engine = _engine(world)
    node = engine.node("agora_street")
    before = float(node["stats"].get("cohesion", 0.0))
    result = engine.execute(
        "perform_song", target_ref={"kind": "place", "id": "agora_street"}
    )
    assert result["ok"] is True
    assert float(node["stats"].get("cohesion", 0.0)) >= before


def test_lesson_raises_respect_of_student(world):
    engine = _engine(world)
    character_id = engine.character_order[0]
    character = engine.characters[character_id]
    before = float(character["respect"])
    result = engine.execute(
        "teach_lesson", target_ref={"kind": "character", "id": character_id}
    )
    assert result["ok"] is True
    assert float(character["respect"]) > before


def test_comfort_lowers_fear_of_person(world):
    engine = _engine(world)
    character_id = engine.character_order[0]
    character = engine.characters[character_id]
    character["fear"] = 0.5
    result = engine.execute(
        "comfort_person",
        target_ref={"kind": "character", "id": character_id},
    )
    assert result["ok"] is True
    assert float(character["fear"]) < 0.5


def test_ask_favor_creates_obligation_entity(world):
    engine = _engine(world)
    character_id = engine.character_order[0]
    assert engine.known_entities(["obligation"]) == []
    result = engine.execute(
        "ask_favor", target_ref={"kind": "character", "id": character_id}
    )
    assert result["ok"] is True
    obligations = engine.known_entities(["obligation"])
    assert len(obligations) == 1
    ref = obligations[0]
    obligation = engine.entity(ref)
    assert obligation["creditor"] == "player"
    assert obligation["debtor"] == character_id
    assert obligation["kind"] == "favor"
    assert engine.entity_ref(obligation) == ref


def test_item_effects_grant_take_and_snapshot(world):
    engine = _engine(world)
    engine._apply_item_effects({"action": "grant", "id": "open_ledger"})
    assert "open_ledger" in engine.player_item_ids
    assert "open_ledger" in engine.granted_items

    engine._apply_item_effects({"action": "consume", "id": "open_ledger"})
    assert "open_ledger" not in engine.player_item_ids
    assert "open_ledger" in engine.consumed_items
    assert "open_ledger" not in engine.granted_items

    restored = WorldEngine(
        world,
        profile=build_player_profile({"name": "Тест"}, seed=7),
        node_id="agora_street",
        office_id="street_musician",
        seed=7,
    )
    restored.load_snapshot(engine.to_dict())
    restored._refresh_items()
    assert "open_ledger" not in restored.player_item_ids


def test_legacy_snapshot_without_item_sets_still_loads(world):
    engine = _engine(world)
    snapshot = {
        "schema_version": 1,
        "world_id": world.get("id"),
        "seed": 7,
        "day": 1,
        "days": 30,
        "actions_left": 3,
        "action_count": 0,
        "profile": {},
        "player": {
            "node_id": "agora_street",
            "office_id": "street_musician",
            "items": ["personal_seal"],
        },
    }
    engine.load_snapshot(snapshot)
    assert engine.player_item_ids == ["personal_seal"]
    assert engine.granted_items == set()
    assert engine.consumed_items == set()
