"""P6: выбор сюжета по тегам роли и архетипа.

Теги — данные сюжета. Если роль не нашла ни одного совпадения, список
остаётся полным: новая роль не должна приводить к пустому экрану.
"""

from __future__ import annotations

from pathlib import Path

from view.support.storyline import list_storylines, load_storyline

ROOT = Path(__file__).resolve().parents[1]
STORYLINES = ROOT / "configs" / "storylines"
FIXTURE_STORYLINES = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "content"
    / "configs"
    / "storylines"
)


def _ids(entries):
    return [entry["storyline_id"] for entry in entries]


def test_every_production_storyline_declares_tags():
    entries = list_storylines(STORYLINES)

    assert {"free_life", "empire_campaign"} <= set(_ids(entries))
    for entry in entries:
        assert entry["tags"], entry["storyline_id"]


def test_free_role_gets_free_life_first():
    entries = list_storylines(
        STORYLINES,
        tags=("free", "street", "school", "market", "temple", "court", "army"),
    )

    assert entries
    assert entries[0]["storyline_id"] == "free_life"
    assert set(_ids(entries)) <= {
        entry["storyline_id"] for entry in list_storylines(STORYLINES)
    }


def test_lore_role_gets_matching_campaign_first():
    entries = list_storylines(
        STORYLINES, tags=("lore", "republic", "leader", "court")
    )

    assert entries[0]["storyline_id"] == "republic_campaign"
    assert "empire_campaign" in _ids(entries)


def test_unknown_tags_fall_back_to_full_list():
    all_ids = set(_ids(list_storylines(STORYLINES)))
    filtered = list_storylines(STORYLINES, tags=("нет-такого-тега",))

    assert set(_ids(filtered)) == all_ids


def test_load_storyline_exposes_tags():
    data = load_storyline("free_life", STORYLINES)

    assert data is not None
    assert "free" in data["storyline_tags"]
    assert "street" in data["storyline_tags"]


def test_storylines_without_tags_still_list():
    entries = list_storylines(FIXTURE_STORYLINES, tags=("free",))

    assert entries
    assert all(entry["tags"] == [] for entry in entries)
