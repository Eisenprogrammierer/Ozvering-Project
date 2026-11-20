"""Качественные метрики UI: слова вместо точных чисел."""

from __future__ import annotations

from view.support.metrics import (
    amount_phrase,
    chance_phrase,
    cost_phrase,
    delta_phrase,
    effect_phrase,
    metric_phrase,
    progress_phrase,
    relation_phrase,
    share_phrase,
)


def _has_digit(text):
    return any(char.isdigit() for char in text)


def test_metric_phrase_has_no_numbers_and_agrees():
    assert metric_phrase("законность", 0.9) == "законность: очень высокая"
    assert metric_phrase("влияние", 0.4) == "влияние: умеренное"
    assert metric_phrase("страх", 0.2) == "страх: низкий"
    assert metric_phrase("мораль", 80.0, high=100.0) == (
        "мораль: высокая"
    )
    for value in (0.0, 0.2, 0.5, 0.7, 1.0):
        assert not _has_digit(metric_phrase("влияние", value))


def test_delta_and_effects_are_qualitative():
    assert delta_phrase("мораль", 40.0, 42.0, scale=100.0) == (
        "мораль слегка выросла"
    )
    assert delta_phrase("целостность", 0.6, 0.2) == (
        "целостность сильно снизилась"
    )
    assert delta_phrase("целостность", 0.6, 0.45) == (
        "целостность заметно снизилась"
    )
    assert delta_phrase("влияние", 0.5, 0.5) == "влияние: без изменений"
    assert effect_phrase("влияние", 0.12) == "влияние заметно растёт"
    assert effect_phrase("законность", -0.12) == (
        "законность заметно снижается"
    )
    assert not _has_digit(effect_phrase("влияние", 0.12))


def test_chance_cost_progress_and_share_have_no_numbers():
    for value in (0.05, 0.3, 0.5, 0.7, 0.95):
        assert not _has_digit(chance_phrase(value))
    assert chance_phrase(0.05) == "маловероятно"
    assert chance_phrase(0.95) == "почти наверняка"
    assert cost_phrase("влияние", 0.2) == "влияние: умеренно"
    assert progress_phrase(0.95) == "почти завершена"
    assert share_phrase(0.9) == "почти все"
    assert not _has_digit(amount_phrase(0.2))


def test_relation_phrase_is_signed_but_textual():
    assert relation_phrase("доверие", 0.6) == "доверие: высокое"
    assert relation_phrase("страх", -0.6) == "страх: низкий"
    assert not _has_digit(relation_phrase("доверие", 0.6))
