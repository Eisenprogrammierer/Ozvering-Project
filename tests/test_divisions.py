"""Контракт 15 делений: данные из JSON, код только проверяет и хранит."""

from __future__ import annotations

import json

import pytest

from campaign.divisions import (
    DIMENSIONS,
    Divisions,
    DivisionCatalog,
    DivisionError,
    division_tags,
    load_divisions,
)


@pytest.fixture(scope="module")
def catalog():
    return load_divisions()


def test_catalog_has_exactly_fifteen_canonical_dimensions(catalog):
    assert catalog.keys == DIMENSIONS
    assert len(catalog.dimensions) == 15
    for key in DIMENSIONS:
        definition = catalog.definition(key)
        assert definition is not None
        assert definition.values
        assert len(definition.value_ids) == len(set(definition.value_ids))


def test_presets_are_made_of_known_values(catalog):
    assert {"germanic", "russian", "anglo"} <= set(catalog.presets)
    for name, values in catalog.presets.items():
        assert values
        for key, value_id in values.items():
            assert key in DIMENSIONS, name
            assert catalog.value(key, value_id) is not None, (name, key)


def test_catalog_rejects_missing_dimension():
    raw = json.loads(
        (catalog_path()).read_text(encoding="utf-8")
    )
    raw["dimensions"].pop("family")
    with pytest.raises(DivisionError):
        DivisionCatalog(raw)


def test_catalog_rejects_duplicate_values():
    raw = json.loads(
        (catalog_path()).read_text(encoding="utf-8")
    )
    values = raw["dimensions"]["family"]["values"]
    values.append(dict(values[0]))
    with pytest.raises(DivisionError):
        DivisionCatalog(raw)


def test_non_strict_catalog_drops_unknown_values(catalog):
    assert not catalog.strict
    result = catalog.validate(
        {"family": "clan", "unknown": "x", "social": "nobody"}
    )
    assert result == {"family": "clan"}


def test_strict_catalog_rejects_unknown_dimension_and_value(catalog):
    raw = json.loads(
        (catalog_path()).read_text(encoding="utf-8")
    )
    raw["strict"] = True
    strict = DivisionCatalog(raw)
    with pytest.raises(DivisionError):
        strict.validate({"unknown": "x"})
    with pytest.raises(DivisionError):
        strict.validate({"family": "nobody"})


def test_divisions_set_get_clear_and_completeness(catalog):
    divisions = Divisions(catalog=catalog)
    assert divisions.missing() == list(DIMENSIONS)
    assert not divisions.is_complete()

    first = divisions.set("family", "clan")
    assert first.id == "clan"
    assert divisions.get("family") == "clan"
    assert divisions.label("family") == first.label
    assert "family:clan" in divisions.tags()

    divisions.set("family", "")
    assert divisions.get("family") is None
    with pytest.raises(DivisionError):
        divisions.set("unknown", "x")
    with pytest.raises(DivisionError):
        divisions.set("family", "nobody")


def test_divisions_from_preset_and_snapshot(catalog):
    preset = catalog.preset("germanic")
    divisions = catalog.from_data(preset)
    assert divisions.values == preset
    assert divisions.is_complete() is False
    assert divisions.snapshot()["family"]["id"] == "clan"
    assert divisions.snapshot()["family"]["label"]
    assert set(divisions.as_dict()) == set(preset)

    empty = catalog.empty()
    empty.update({"family": "single", "unknown": "x"})
    assert empty.as_dict() == {"family": "single"}


def test_division_tags_helper(catalog):
    tags = division_tags({"family": "clan", "family_extra": "x"}, catalog)
    assert tags == ["family:clan"]


def catalog_path():
    from campaign.divisions import default_divisions_path

    return default_divisions_path()
