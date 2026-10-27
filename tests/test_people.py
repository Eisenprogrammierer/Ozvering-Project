from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from naming.people import (
    PeopleError,
    PersonCatalog,
    PersonNameGenerator,
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


def test_naming_cli_generates_people_names():
    root = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "naming",
            "--person",
            "--culture",
            "russian",
            "--gender",
            "f",
            "--count",
            "3",
            "--seed",
            "7",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") >= 3

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "naming",
            "--person",
            "--fantasy",
            "cyberpunk",
            "--count",
            "2",
            "--seed",
            "7",
            "--json",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") >= 2
    assert "cyberpunk" in result.stdout
