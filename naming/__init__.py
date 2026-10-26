"""Конфигурируемые естественные названия автоматов.

Пакет не импортирует pygame и не меняет редактор ``automata``. Он читает
лексикон и профили из ``configs/naming`` и предоставляет:

* ``NameGenerator.automaton_name(mode, need, level)``;
* ``NameGenerator.interaction_name(type_id)``;
* доступ к онтологии класса и пятёрке типа взаимодействия через
  ``NamingCatalog``.
"""

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


def automaton_name(mode, need=None, level=1, theme=None, seed=0):
    """Короткий функциональный вход для одного названия."""
    return NameGenerator(seed=seed).automaton_name(
        mode, need=need, level=level, theme=theme)


def interaction_name(type_id, seed=0):
    """Короткий функциональный вход для названия взаимодействия."""
    return NameGenerator(seed=seed).interaction_name(type_id)


__all__ = [
    "MAX_WORDS", "MIN_WORDS", "MODE_WORDS",
    "CASES", "Adjective", "MorphologyError", "Noun", "Phrase",
    "ClassProfile", "InteractionType", "NamingCatalog", "NamingError", "Pool",
    "NameGenerator", "NameResult", "automaton_name", "interaction_name",
    "default_catalog", "default_root", "sample_word_count", "word_count",
    "word_count_summary", "word_count_weights", "capitalize",
]
