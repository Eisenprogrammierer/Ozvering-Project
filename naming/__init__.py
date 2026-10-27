from __future__ import annotations

from .catalog import (
    ClassProfile,
    InteractionType,
    NamingCatalog,
    NamingError,
    Pool,
    default_catalog,
    default_root,
)
from .distribution import (
    MAX_WORDS,
    MIN_WORDS,
    MODE_WORDS,
    sample_word_count,
    word_count_summary,
    word_count_weights,
)
from .generator import NameGenerator, NameResult
from .morphology import (
    CASES,
    Adjective,
    MorphologyError,
    Noun,
    Phrase,
    capitalize,
    word_count,
)
from .people import (
    PeopleError,
    PersonCatalog,
    PersonCulture,
    PersonName,
    PersonNameGenerator,
    default_catalog as default_people_catalog,
)


def automaton_name(mode, need=None, level=1, theme=None, seed=0):
    return NameGenerator(seed=seed).automaton_name(
        mode, need=need, level=level, theme=theme
    )


def interaction_name(type_id, seed=0):
    return NameGenerator(seed=seed).interaction_name(type_id)


def person_name(culture=None, theme=None, gender=None, seed=0):
    return PersonNameGenerator(seed=seed).generate(
        culture=culture, theme=theme, gender=gender, seed=seed
    )


__all__ = [
    "MAX_WORDS",
    "MIN_WORDS",
    "MODE_WORDS",
    "CASES",
    "Adjective",
    "MorphologyError",
    "Noun",
    "Phrase",
    "ClassProfile",
    "InteractionType",
    "NamingCatalog",
    "NamingError",
    "Pool",
    "NameGenerator",
    "NameResult",
    "automaton_name",
    "interaction_name",
    "PeopleError",
    "PersonCatalog",
    "PersonCulture",
    "PersonName",
    "PersonNameGenerator",
    "default_people_catalog",
    "person_name",
    "default_catalog",
    "default_root",
    "sample_word_count",
    "word_count",
    "word_count_summary",
    "word_count_weights",
    "capitalize",
]
