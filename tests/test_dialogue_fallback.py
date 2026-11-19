"""Свободные формулировки и вычисленный тон.

Проверяют, что естественный вопрос не проваливается в «Не знаю», что
фолбэк берёт форму из ``fallback.json`` и что регистр зависит от
отношений и убеждений, а не от ручного выбора игрока.
"""

from __future__ import annotations

import pytest

from campaign.dialogue.engine import DialogueSession
from campaign.dialogue.knowledge import AgentKnowledge, Fact
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.repl import build_session


@pytest.fixture(scope="module")
def red():
    return build_session("red", seed=13)


NATURAL_QUESTIONS = (
    "Привет! Как жизнь?",
    "Расскажи о себе.",
    "Что нового?",
    "Как дела в Империи?",
    "Что происходит в мире?",
    "Почему война?",
    "С кем ты воюешь?",
    "Кто твой враг?",
    "Что ты можешь?",
    "Помоги мне.",
    "Мне нужна должность.",
    "Сколько у тебя войск?",
    "Ты меня уважаешь?",
    "Что ты думаешь о Республике?",
    "Расскажи про Республику.",
    "Почему Империя против Республики?",
    "Что случилось?",
    "Как твои дела?",
    "Есть новости?",
    "Кто лидер Республики?",
)


def test_natural_questions_get_substantive_answers(red):
    for question in NATURAL_QUESTIONS:
        answer = red.ask(question)
        assert answer.kind != "unknown", question
        assert answer.text.strip(), question
        assert "не знаю" not in answer.text.casefold(), question


def test_free_form_war_question_uses_fallback(red):
    turn = red.respond("С кем ты воюешь?")
    assert turn.source.startswith("fallback:")
    assert turn.answer.plan_id in ("war_fallback", "war_reason_fallback")
    assert "Республик" in turn.answer.text


def test_about_target_with_pro_preposition_resolves(red):
    answer = red.ask("Расскажи про Республику.")
    assert answer.plan_id == "tell_about"
    assert "Республика" in answer.text


def _knowledge(catalog, **kwargs):
    values = {
        "side": "blue",
        "faction_id": "faction:blue",
        "speaker_id": "char_blue",
        "speaker_name": "Грета",
        "player_id": "char_player",
        "player_name": "Игрок",
        "player_side": "red",
        "player_faction": "Империя",
        "player_faction_id": "faction:red",
        "world": catalog.world,
    }
    facts = kwargs.pop("facts", ())
    values.update(kwargs)
    return AgentKnowledge(
        catalog, facts=tuple(facts), entities={}, **values
    )


def _style(catalog, **kwargs):
    return DialogueSession(catalog, _knowledge(catalog, **kwargs))


def test_style_comes_from_belief_threat():
    catalog = load_dialogue(DEFAULT_DIR)
    session = _style(
        catalog,
        facts=[
            Fact(
                "belief",
                (
                    "char_blue",
                    "faction:blue",
                    "sees_as_threat",
                    "faction:red",
                ),
            )
        ],
    )
    decision = session.style_decision()
    assert decision.style_id == "hostile"
    assert decision.rule_id == "belief_threat_hostile"


def test_style_comes_from_relation_axes():
    catalog = load_dialogue(DEFAULT_DIR)
    session = _style(
        catalog,
        relation_axes={"trust": 0.7, "affinity": 0.2},
    )
    decision = session.style_decision()
    assert decision.style_id == "friendly"
    assert decision.rule_id == "relation_trust_friendly"


def test_numeric_relation_operator_handles_zero_threshold():
    catalog = load_dialogue(DEFAULT_DIR)
    session = _style(
        catalog,
        relation_axes={"respect": 0.8, "affinity": 0.0},
    )
    decision = session.style_decision()
    assert decision.style_id == "mentor"
    assert decision.rule_id == "relation_respect_mentor"


def test_intention_coerce_is_hostile():
    catalog = load_dialogue(DEFAULT_DIR)
    session = _style(
        catalog,
        facts=[
            Fact(
                "intention",
                ("char_blue", "faction:red", "coerce"),
            )
        ],
    )
    decision = session.style_decision()
    assert decision.style_id == "hostile"
    assert decision.rule_id == "intention_coerce_hostile"
