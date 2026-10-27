from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

import pytest

from naming import (
    MAX_WORDS,
    MIN_WORDS,
    MODE_WORDS,
    NameGenerator,
    NamingCatalog,
    sample_word_count,
    word_count_summary,
    word_count_weights,
)
from naming.morphology import Adjective, Noun, Phrase

EXPECTED_CLASSES = {
    "order",
    "meaning",
    "provision",
    "status",
    "knowledge",
    "care",
    "exchange",
}
EXPECTED_INTERACTIONS = {
    "coercion",
    "exchange",
    "instruction",
    "care",
    "ritual",
    "recruitment",
    "reconnaissance",
    "negotiation",
}
CASES = ("nom", "gen", "dat", "acc", "ins", "prep")


@pytest.fixture(scope="module")
def catalog():
    return NamingCatalog.load()


def test_word_count_distribution_has_mode_two_tail_and_hard_cap():
    weights = word_count_weights()
    summary = word_count_summary(weights)

    assert set(weights) == set(range(MIN_WORDS, MAX_WORDS + 1))
    assert sum(weights.values()) == pytest.approx(1.0)
    assert summary["mode"] == MODE_WORDS == 2
    assert summary["p_ge_6"] < 0.01
    assert max(weights, key=lambda value: weights[value]) == 2


def test_sampling_never_exceeds_hard_cap():
    rng = random.Random(7)
    sampled = [sample_word_count(rng) for _ in range(3000)]
    assert min(sampled) >= MIN_WORDS
    assert max(sampled) <= MAX_WORDS


def test_catalog_contains_seven_classes_and_eight_interactions(catalog):
    assert set(catalog.class_ids()) == EXPECTED_CLASSES
    assert set(catalog.interaction_ids()) == EXPECTED_INTERACTIONS


def test_every_class_has_base_theme_levels_and_deep_ontology(catalog):
    for class_id in catalog.class_ids():
        profile = catalog.class_profile(class_id)
        assert profile.base.heads
        assert profile.themes
        assert {"1", "2", "3"} <= set(profile.levels)
        for need, theme in profile.need_themes.items():
            assert theme in profile.themes, (class_id, need)

        ontology = catalog.ontology_for(class_id)
        for key in ("inputs", "outputs", "states", "handlers", "surrounding"):
            assert ontology.get(key), (class_id, key)
        for key in ("inputs", "outputs", "states", "handlers", "surrounding"):
            for item in ontology[key]:
                assert item["label"]
                assert item["kind"]
                assert item["keywords"]
        for handler in ontology["handlers"]:
            assert handler["kind"] in ("nested_automaton", "scheme")


def test_every_interaction_has_complete_quintuple(catalog):
    for type_id in catalog.interaction_ids():
        item = catalog.interaction(type_id)
        quintuple = item.quintuple
        assert {
            "recipient_input",
            "sender_output",
            "handlers",
            "states",
            "surrounding_influence",
        } <= set(quintuple)
        assert quintuple["recipient_input"]["keywords"]
        assert quintuple["sender_output"]["keywords"]
        for side in ("sender", "recipient"):
            assert quintuple["handlers"][side]
            assert quintuple["states"][side]
            for handler in quintuple["handlers"][side]:
                assert handler["kind"] in ("nested_automaton", "scheme")
                assert handler["keywords"]
            for state in quintuple["states"][side]:
                assert state["keywords"]
        assert quintuple["surrounding_influence"]["sources"]
        assert item.naming.heads


def test_adjective_agreement_all_genders():
    blagoy = Adjective("blagoy", "благой")
    assert blagoy.form("nom", "m") == "благой"
    assert blagoy.form("nom", "f") == "благая"
    assert blagoy.form("nom", "n") == "благое"
    assert blagoy.form("nom", "pl") == "благие"
    assert blagoy.form("gen", "f") == "благой"

    krotkiy = Adjective("krotkiy", "кроткий")
    assert krotkiy.form("nom", "f") == "кроткая"
    assert krotkiy.form("gen", "f") == "кроткой"

    obshchiy = Adjective("obshchiy", "общий")
    assert obshchiy.form("nom", "f") == "общая"
    assert obshchiy.form("gen", "f") == "общей"


def test_all_lexicon_words_have_all_case_forms(catalog):
    for word in catalog.lexicon.values():
        if isinstance(word, Noun):
            for case in CASES:
                assert word.form(case)
        elif isinstance(word, Adjective):
            for case in CASES:
                for gender in ("m", "f", "n", "pl"):
                    assert word.form(case, gender)
                    assert word.form(case, gender, animate=True)
        elif isinstance(word, Phrase):
            for case in CASES:
                assert word.form(case)


def test_noun_declension_and_animacy():
    gruppa = Noun("gruppa", "группа", "группы", gender="f")
    assert [gruppa.form(case) for case in CASES] == [
        "группа",
        "группы",
        "группе",
        "группа",
        "группой",
        "группе",
    ]

    agent = Noun("agent", "агент", "агента", gender="m", animate=True)
    assert agent.form("acc") == "агента"
    assert agent.form("ins") == "агентом"


def test_automaton_names_are_deterministic_for_all_classes(catalog):
    generator = NameGenerator(catalog, seed=0)
    for class_id in catalog.class_ids():
        first = generator.automaton_name(
            class_id, need="fear", level=3, seed=17
        )
        second = generator.automaton_name(
            class_id, need="fear", level=3, seed=17
        )
        assert first.text == second.text
        assert first.seed == 17
        assert 1 <= first.words <= MAX_WORDS
        assert first.nom == first.text
        assert first.parts["head"]["id"]
        for case in CASES:
            assert first.render(case)
        assert first.render("gen")


def test_generated_names_vary_with_seed_and_need(catalog):
    generator = NameGenerator(catalog, seed=0)
    names = {
        generator.automaton_name("order", need="fear", level=3, seed=seed).text
        for seed in range(20)
    }
    assert len(names) > 3

    fear = generator.automaton_name("order", need="fear", level=3, seed=7)
    health = generator.automaton_name("order", need="health", level=3, seed=7)
    assert fear.theme != health.theme


def test_generate_many_returns_unique_names(catalog):
    generator = NameGenerator(catalog, seed=5)
    results = generator.generate_many(
        "provision", need="hunger", level=2, count=25, seed=5
    )
    assert len(results) == 25
    assert len({item.text for item in results}) == 25
    assert all(1 <= item.words <= MAX_WORDS for item in results)


def test_interaction_names_are_deterministic_and_declined(catalog):
    generator = NameGenerator(catalog, seed=0)
    for type_id in catalog.interaction_ids():
        first = generator.interaction_name(type_id, seed=23)
        second = generator.interaction_name(type_id, seed=23)
        assert first.text == second.text
        assert first.kind == "interaction"
        assert first.mode == type_id
        assert 1 <= first.words <= MAX_WORDS
        for case in CASES:
            assert first.render(case)


def test_interaction_names_vary_across_types(catalog):
    generator = NameGenerator(catalog, seed=0)
    names = {
        generator.interaction_name(type_id, seed=11).text
        for type_id in catalog.interaction_ids()
    }
    assert len(names) == len(EXPECTED_INTERACTIONS)


def test_naming_does_not_import_pygame():
    code = (
        "import sys; import naming; "
        "assert 'pygame' not in sys.modules, sorted(sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_naming_cli_previews_names_and_ontology():
    root = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "naming",
            "--mode",
            "order",
            "--need",
            "fear",
            "--level",
            "3",
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
            "--interaction",
            "coercion",
            "--count",
            "2",
            "--seed",
            "7",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") >= 2
