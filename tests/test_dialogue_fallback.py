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
    "Из-за чего война?",
    "С кем враждуете?",
    "Покажи свои силы.",
    "Кто у вас главный?",
    "Что слышно?",
    "Ты мне доверяешь?",
    "Расскажи о войне.",
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


def test_ellipsis_leader_takes_topic_from_previous_turn():
    session = build_session("red", seed=13)
    session.ask("Расскажи про Республику.")
    answer = session.ask("А кто лидер?")
    assert answer.plan_id == "leader_who"
    assert "Республик" in answer.text
    leader = next(
        fact.args[3]
        for fact in session.knowledge.facts
        if fact.rel == "leader" and fact.args[0] == "faction:blue"
    )
    assert leader in answer.text


def test_ellipsis_why_takes_topic_from_previous_turn():
    session = build_session("red", seed=13)
    session.ask("Расскажи про Республику.")
    answer = session.ask("А почему?")
    assert answer.plan_id == "tell_why"
    assert answer.kind == "explanation"
    assert "незаконн" in answer.text.casefold()
    assert "не знаю" not in answer.text.casefold()


def test_why_after_stance_explains_the_stance():
    session = build_session("red", seed=13)
    session.ask("Что ты думаешь о Республике?")
    answer = session.ask("Почему?")
    assert answer.plan_id == "think_why"
    assert answer.kind == "explanation"
    assert answer.text.startswith("Причина:")


def test_why_after_leader_keeps_topic():
    session = build_session("red", seed=13)
    session.ask("Кто лидер Республики?")
    answer = session.ask("А почему?")
    assert answer.plan_id == "rule_why"
    assert "Республик" in answer.text


def test_leader_question_with_pronoun_stays_with_speaker_faction():
    session = build_session("red", seed=13)
    session.ask("Расскажи про Республику.")
    answer = session.ask("Кто у вас главный?")
    assert answer.plan_id == "leader_who"
    assert "Импери" in answer.text
    assert "Республик" not in answer.text


def test_natural_question_without_parse_gets_hint_not_unknown():
    session = build_session("red", seed=13)
    answer = session.ask("Квантовый флуктуатор?")
    assert answer.kind == "hint"
    assert "Можно спросить" in answer.text
    assert "не знаю" not in answer.text.casefold()


def test_gibberish_without_question_stays_honest():
    session = build_session("red", seed=13)
    answer = session.ask("абракадабра")
    assert answer.kind == "unknown"


def test_war_reason_prefers_derived_rule():
    session = build_session("red", seed=13)
    answer = session.ask("Из-за чего война?")
    assert answer.plan_id == "war_reason_fallback"
    assert "законност" in answer.text.casefold()
    assert answer.proof
    assert answer.proof[0].rule == "war_reason_legitimacy"


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


def test_attitude_fallback_states_relation_without_numbers():
    catalog = load_dialogue(DEFAULT_DIR)
    warm = DialogueSession(
        catalog,
        _knowledge(catalog, relation_axes={"trust": 0.8, "affinity": 0.3}),
    )
    cold = DialogueSession(
        catalog,
        _knowledge(catalog, relation_axes={"affinity": -0.6, "fear": 0.2}),
    )
    positive = warm.ask("Ты меня уважаешь?")
    negative = cold.ask("Ты меня уважаешь?")
    for answer in (positive, negative):
        assert answer.plan_id == "attitude_fallback"
        assert answer.text.strip()
        assert not any(char.isdigit() for char in answer.text)
    assert "доверие" in positive.text.lower()
    assert "страх" in negative.text.lower()


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
