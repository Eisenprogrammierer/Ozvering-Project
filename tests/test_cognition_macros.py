"""Object macros RiveScript: морфология, числа, качества, сущности."""

from __future__ import annotations

import pytest

from campaign.cognition.rive_macros import (
    build_macros,
    load_macros,
    parse_number,
    parse_quality,
    register_macros,
)


def test_morph_and_entity_follow_lexicon():
    macros = load_macros()
    assert macros.morph("Империей") == "империя"
    assert macros.entity("Империей") == "faction:red"
    assert macros.entity("Республику") == "faction:blue"
    assert macros.entity("ксизи") == ""
    assert macros.digest() == load_macros().digest()


def test_number_parser_is_deterministic():
    assert parse_number("двадцать один") == "21"
    assert parse_number("сто два") == "102"
    assert parse_number("тысяча двести") == "1200"
    assert parse_number("ксизи") == ""
    assert parse_number("") == ""


def test_quality_parser_maps_levels():
    assert parse_quality("нет") == "0"
    assert parse_quality("низкий") == "1"
    assert parse_quality("средний") == "2"
    assert parse_quality("высокий") == "3"
    assert parse_quality("ксизи") == ""


def test_ambiguous_entities_are_not_guessed():
    macros = build_macros(
        [
            {
                "lemma": "империя",
                "forms": ["Империей"],
                "semantic": {"kind": "entity", "id": "faction:red"},
            },
            {
                "lemma": "империя",
                "forms": ["Империей"],
                "semantic": {"kind": "entity", "id": "noun:empire"},
            },
        ]
    )
    assert macros.entity("Империей") == ""
    assert "империей" in macros.ambiguous_entities


def test_macros_are_callable_from_rivescript():
    pytest.importorskip("rivescript")
    from rivescript import RiveScript

    engine = RiveScript(utf8=True)
    engine.stream(
        "\n".join(
            (
                "! version = 2.0",
                "+ морф *",
                "- <call>morph <star></call>",
                "+ число *",
                "- <call>number <star></call>",
                "+ качество *",
                "- <call>quality <star></call>",
                "+ сущность *",
                "- <call>entity <star></call>",
            )
        )
    )
    engine.sort_replies()
    register_macros(engine, load_macros())
    assert engine.reply("u", "морф Империей") == "империя"
    assert engine.reply("u", "число двадцать один") == "21"
    assert engine.reply("u", "качество высокий") == "3"
    assert engine.reply("u", "сущность Республику") == "faction:blue"
