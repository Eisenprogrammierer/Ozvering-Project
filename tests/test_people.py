from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from naming.people import (
    PeopleError,
    PersonCatalog,
    PersonCulture,
    PersonNameGenerator,
    PersonPolicyCatalog,
)


@pytest.fixture(scope="module")
def catalog():
    return PersonCatalog.load()


def test_catalog_has_many_real_cultures_and_fantasy_themes(catalog):
    assert len(catalog.cultures) >= 20
    assert len(catalog.themes) >= 19
    assert "russian" in catalog.culture_ids()
    assert "japanese" in catalog.culture_ids()
    assert "yoruba" in catalog.culture_ids()
    assert "high_elf" in catalog.theme_ids()
    assert "cyberpunk" in catalog.theme_ids()
    assert "cosmic" in catalog.theme_ids()
    assert catalog.default_culture == "russian"


def test_real_names_are_deterministic_and_culturally_grounded(catalog):
    generator = PersonNameGenerator(catalog, seed=7)
    first = generator.real(culture="russian", gender="f", seed=11)
    second = generator.real(culture="russian", gender="f", seed=11)

    assert first == second
    assert first.full == second.full
    assert first.culture == "russian"
    assert first.gender == "f"
    assert first.family.endswith("ова") or first.family.endswith("ева")
    assert first.given in catalog.culture("russian").given["f"]
    assert first.family in catalog.culture("russian").family["f"]
    assert first.full == "%s %s" % (first.given, first.family)


def test_east_asian_names_keep_family_first_order(catalog):
    generator = PersonNameGenerator(catalog, seed=5)
    for culture in ("chinese", "japanese", "korean"):
        item = generator.real(culture=culture, seed=13)
        assert item.full.startswith(item.family + " ")
        assert item.given in item.full


def test_fantasy_names_are_themed_and_deterministic(catalog):
    generator = PersonNameGenerator(catalog, seed=9)
    for theme in ("high_elf", "dark_elf", "cyberpunk", "undead", "cosmic"):
        first = generator.fantasy(theme=theme, seed=17)
        second = generator.fantasy(theme=theme, seed=17)
        assert first == second
        assert first.theme == theme
        assert first.style == "fantasy"
        assert first.full
    names = {
        generator.fantasy(theme="high_elf", seed=seed).full
        for seed in range(12)
    }
    assert len(names) >= 6


def test_generate_many_is_unique_deterministic_and_mixed(catalog):
    generator = PersonNameGenerator(catalog, seed=3)
    first = generator.generate_many(count=24, seed=23)
    second = generator.generate_many(count=24, seed=23)

    assert [item.full for item in first] == [item.full for item in second]
    assert len({item.full for item in first}) >= 20
    assert any(item.style == "real" for item in first)
    assert any(item.style == "fantasy" for item in first)
    assert all(item.full and not item.full.startswith(" ") for item in first)


def test_policy_catalog_resolves_faction_and_storyline_aliases():
    policies = PersonPolicyCatalog.load()
    assert set(policies.ids()) == {
        "empire",
        "republic",
        "cult",
        "corporation",
    }
    for key in ("faction_empire", "empire_campaign", "empire"):
        assert policies.get(key).id == "empire"
    assert policies.resolve("unknown") is None


def test_empire_policy_is_european_and_prefers_germanic(catalog):
    generator = PersonNameGenerator(catalog, seed=5)
    items = generator.generate_many(
        600, policy="faction_empire", seed=17
    )
    european = {
        "russian",
        "germanic",
        "nordic",
        "anglo",
        "french",
        "italian",
        "iberian",
        "celtic",
        "greek",
    }
    assert all(item.style == "real" for item in items)
    assert all(item.culture in european for item in items)
    assert all(item.epithet == "" for item in items)
    counts = {}
    for item in items:
        counts[item.culture] = counts.get(item.culture, 0) + 1
    other = {
        culture: amount
        for culture, amount in counts.items()
        if culture != "germanic"
    }
    assert counts.get("germanic", 0) > max(other.values())


def test_republic_and_corporation_allow_any_name_without_epithets(catalog):
    generator = PersonNameGenerator(catalog, seed=9)
    for policy in ("faction_republic", "faction_corporation"):
        items = generator.generate_many(200, policy=policy, seed=23)
        assert all(item.epithet == "" for item in items)
        assert all("{epithet}" not in item.full for item in items)
        assert any(item.style == "real" for item in items)
        assert any(item.style == "fantasy" for item in items)


def test_cult_policy_generates_only_religious_epithets(catalog):
    generator = PersonNameGenerator(catalog, seed=3)
    policy = generator.policy("faction_cult")
    items = generator.generate_many(30, policy=policy, seed=11)
    assert len({item.full for item in items}) == 30
    for item in items:
        assert item.style == "epithet"
        assert item.given == ""
        assert item.family == ""
        assert item.full == item.epithet
        assert item.epithet in policy.epithets


def test_gender_specific_pools_are_strict(catalog):
    russian = catalog.culture("russian")
    generator = PersonNameGenerator(catalog, seed=7)
    for gender, key in (("m", "m"), ("f", "f")):
        items = generator.generate_many(
            40, culture="russian", gender=gender, seed=13
        )
        assert all(item.gender == gender for item in items)
        assert all(item.given in russian.given[key] for item in items)
        assert all(item.family in russian.family[key] for item in items)

    only_male = PersonCulture.from_data(
        "only_male",
        {"given": {"m": ["Иван"]}, "family": {"m": ["Иванов"]}},
        "real",
    )
    with pytest.raises(PeopleError):
        only_male.given_for("f")
    with pytest.raises(PeopleError):
        only_male.family_for("f")


def test_unknown_policy_is_rejected(catalog):
    generator = PersonNameGenerator(catalog, seed=0)
    with pytest.raises(PeopleError):
        generator.generate(policy="missing")
    with pytest.raises(PeopleError):
        generator.generate_many(3, policy="missing")


def test_bad_culture_or_theme_is_rejected(catalog):
    generator = PersonNameGenerator(catalog, seed=0)
    with pytest.raises(PeopleError):
        generator.real(culture="atlantis")
    with pytest.raises(PeopleError):
        generator.fantasy(theme="unknown")
    with pytest.raises(PeopleError):
        generator.generate(culture="russian", theme="high_elf")


def test_people_layer_does_not_import_pygame():
    code = (
        "import sys; import naming.people; "
        "assert 'pygame' not in sys.modules, sorted(sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_naming_cli_generates_people_names(capsys):
    from naming.__main__ import main as naming_main

    assert naming_main(
        [
            "--person",
            "--culture",
            "russian",
            "--gender",
            "f",
            "--count",
            "3",
            "--seed",
            "7",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert output.count("\n") >= 3

    assert naming_main(
        [
            "--person",
            "--fantasy",
            "cyberpunk",
            "--count",
            "2",
            "--seed",
            "7",
            "--json",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert output.count("\n") >= 2
    assert "cyberpunk" in output
