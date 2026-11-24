"""P3: открытый каталог действий, формы и ``entity_ref``.

Тесты проверяют данные, а не конкретные id: новое действие появляется
из JSON-каталога, адресат задаётся универсальной ссылкой, а неизвестная
форма отклоняется линтером и загрузчиком мира.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from campaign.actions import (
    ActionError,
    FormCatalog,
    build_spec_work,
    entity_matches,
    improvised_work,
    lint_action,
    merge_action_catalogs,
    normalize_action,
    parse_entity_ref,
    validate_entity_ref,
)
from campaign.world import (
    WorldEngine,
    WorldError,
    build_player_profile,
    load_world,
    validate_world,
)

ROOT = Path(__file__).resolve().parents[1]
WORLDS = ROOT / "configs" / "worlds"
CATALOG = WORLDS / "actions" / "agora_actions.json"


@pytest.fixture(scope="module")
def forms():
    return FormCatalog.load()


@pytest.fixture(scope="module")
def world():
    return load_world(WORLDS / "agora_world.json")


@pytest.fixture
def engine(world):
    engine = WorldEngine(
        world,
        profile=build_player_profile({"name": "Тест"}, seed=7),
        node_id="agora_street",
        office_id="street_musician",
        seed=7,
    )
    assert engine.attach("agora_street", "street_musician")["ok"] is True
    return engine


def test_forms_manifest_loads_and_has_handlers(forms):
    assert "care" in forms
    assert "information" in forms
    assert "character_interaction" in forms
    assert forms.require("care").target_kinds
    assert forms.require("care").payload_kinds


def test_action_catalog_adds_existing_form_without_python(engine):
    assert "calm_crowd" in engine.actions
    assert "calm_crowd" in engine.available_actions(
        engine.player_node_id
    )
    action = engine.actions["calm_crowd"]
    assert action["form"] == "care"
    assert action["target"]["required"] is False


def test_action_addresses_character_item_and_norm(engine):
    character = next(iter(engine.characters))
    item = next(iter(engine.item_catalog))
    norm = next(iter(engine.norms))

    assert engine.validate(
        "hug", target_ref={"kind": "character", "id": character}
    ) == (True, "")
    assert engine.validate(
        "offer_gift", target_ref={"kind": "item", "id": item}
    ) == (True, "")
    assert engine.validate(
        "cite_law", target_ref={"kind": "norm", "id": norm}
    ) == (True, "")

    targets = {
        ref["kind"] for ref in engine.action_targets("hug")
    }
    assert targets == {"character"}


def test_character_addressing_changes_that_character(engine):
    character_id = next(iter(engine.characters))
    character = engine.characters[character_id]
    before = float(character["affinity"])
    engine._roll = lambda token: 0.0
    result = engine.execute(
        "hug", target_ref={"kind": "character", "id": character_id}
    )
    assert result["ok"] is True
    assert result["outcome"] == "success"
    assert result["target_label"] == character["name"]
    assert float(character["affinity"]) > before


def test_catalog_merge_overrides_and_reports_duplicate():
    sources = [
        (
            "base",
            {
                "actions": [
                    {
                        "id": "calm",
                        "form": "care",
                        "target": {"kinds": ["place"]},
                        "effects": {"player": {"standing": 0.01}},
                    }
                ]
            },
        ),
        (
            "patch",
            {
                "actions": [
                    {
                        "id": "calm",
                        "form": "care",
                        "target": {"kinds": ["place"]},
                        "effects": {"player": {"standing": 0.02}},
                    }
                ]
            },
        ),
    ]
    actions, problems, overrides = merge_action_catalogs(sources)
    assert problems == []
    assert len(actions) == 1
    assert actions[0]["_source"] == "patch"
    assert overrides == [{"id": "calm", "from": "base", "to": "patch"}]

    duplicate, problems, _ = merge_action_catalogs(
        [(
            "one",
            {
                "actions": [
                    {
                        "id": "calm",
                        "form": "care",
                        "target": {"kinds": ["place"]},
                        "effects": {},
                    },
                    {
                        "id": "calm",
                        "form": "care",
                        "target": {"kinds": ["place"]},
                        "effects": {},
                    },
                ]
            },
        )]
    )
    assert len(duplicate) == 1
    assert any("дважды" in item for item in problems)


def test_unknown_form_is_rejected(forms):
    action = {
        "id": "mystery",
        "form": "deity",
        "target": {"kinds": ["character"]},
        "effects": {},
    }
    assert any("неизвестная форма" in item for item in lint_action(
        action, forms=forms, require_form=True
    ))
    with pytest.raises(ActionError):
        normalize_action(action, forms=forms)


def test_world_rejects_unknown_form_in_catalog(tmp_path):
    raw = copy.deepcopy(world_data())
    raw["actions"].append(
        {
            "id": "mystery",
            "form": "nope",
            "target": {"kinds": ["character"]},
            "effects": {"player": {"standing": 0.01}},
        }
    )
    with pytest.raises(WorldError):
        validate_world(raw)


def test_entity_ref_validates_kind_and_existence():
    ref = parse_entity_ref("character:mira_svet")
    assert ref == {"kind": "character", "id": "mira_svet"}
    assert entity_matches(ref, ["character"]) is True
    assert entity_matches(ref, ["item"]) is False
    with pytest.raises(ActionError):
        parse_entity_ref({"kind": "deity", "id": "x"})
    with pytest.raises(ActionError):
        validate_entity_ref(
            {"kind": "character", "id": "nope"},
            known={"character": {"mira_svet"}},
        )


def test_action_spec_builds_work_plan(forms):
    actions = json.loads(CATALOG.read_text(encoding="utf-8"))["actions"]
    action = next(item for item in actions if item["id"] == "cite_law")
    plan = build_spec_work(action)
    assert plan is not None
    assert plan.form == "information"
    assert plan.payload
    assert ("kind", "evidence") in plan.payload


def test_improvised_work_is_off_by_default_and_traced_when_enabled(forms):
    assert (
        improvised_work(
            {"form": "care", "target": {"kind": "character", "id": "x"}},
            forms=forms,
        )
        is None
    )
    plan = improvised_work(
        {
            "form": "care",
            "target": {"kind": "character", "id": "mira_svet"},
            "amount": 0.04,
        },
        forms=forms,
        enabled=True,
    )
    assert plan is not None
    assert plan.form == "care"
    assert plan.amount == pytest.approx(0.04)
    assert plan.meta["source"] == "improvised"
    with pytest.raises(ActionError):
        improvised_work(
            {
                "form": "care",
                "target": {"kind": "norm", "id": "agora_charter"},
            },
            forms=forms,
            enabled=True,
        )


def world_data():
    return json.loads(
        (WORLDS / "agora_world.json").read_text(encoding="utf-8")
    )
