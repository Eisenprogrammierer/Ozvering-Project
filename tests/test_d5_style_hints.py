"""Тесты D5.3: подсказка стиля из фактов здравого смысла.

Подсказка ``schema.json.style_hints`` — такое же правило автовыбора
регистра, как записи ``style_context.json``, только приходит из
классификации фразы. Её приоритет задан данными, поэтому отношения и
полномочия остаются сильнее. Без базы фактов сессия работает как
раньше.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from campaign.commonsense import Reading, load_commonsense
from campaign.dialogue.engine import DialogueSession
from campaign.dialogue.knowledge import AgentKnowledge, Fact
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _catalog(directory: Path | None = None):
    return load_dialogue(directory or DEFAULT_DIR)


def _knowledge(
    catalog,
    *,
    side="red",
    speaker_id="char_red",
    player_id="char_player",
    player_side="red",
    faction_id="faction:red",
    player_faction="faction:red",
    facts=(),
):
    return AgentKnowledge(
        catalog,
        facts=tuple(facts),
        entities={},
        side=side,
        faction_id=faction_id,
        speaker_id=speaker_id,
        speaker_name="Император",
        world=catalog.world,
        player_id=player_id,
        player_name="Игрок",
        player_side=player_side,
        player_faction=player_faction,
    )


def _neutral_knowledge(catalog):
    """Собеседник без союза и полномочий: контекст даёт official."""

    return _knowledge(
        catalog,
        side="red",
        faction_id="faction:red",
        player_side="green",
        player_faction="faction:green",
    )


def _session(catalog, knowledge, **kwargs):
    return DialogueSession(
        catalog,
        knowledge,
        persona_id=None,
        memory=None,
        **kwargs
    )


class _Senses:
    """Подставная база фактов: классификация без загрузки с диска."""

    def __init__(self, weight=0.9, mode="flirtation", style="romantic"):
        self.weight = weight
        self.mode = mode
        self.style = style

    def classify(self, text):
        return Reading(
            text=str(text),
            modes=(self.mode,),
            styles=(self.style,),
            weights=((self.mode, self.weight),),
        )

    def style_for(self, mode):
        return self.style if mode == self.mode else ""


# --- данные --------------------------------------------------------


def test_style_context_reads_hint_thresholds():
    catalog = _catalog()
    context = catalog.style_context
    assert context.hint_priority == 40
    assert context.hint_min_weight == 0.8


def test_classify_exposes_mode_weights():
    base = load_commonsense()
    reading = base.classify("я тебя люблю")
    assert reading.modes == ("flirtation",)
    assert reading.weights == (("flirtation", 0.85),)
    assert reading.mode_weight == 0.85
    assert reading.as_dict()["weights"] == {"flirtation": 0.85}


def test_classify_without_markers_has_zero_weight():
    base = load_commonsense()
    reading = base.classify("кто ты")
    assert reading.weights == ()
    assert reading.mode_weight == 0.0


# --- подсказка в сессии --------------------------------------------


def test_hint_from_curated_facts():
    catalog = _catalog()
    session = _session(catalog, _knowledge(catalog))
    assert session.style_hint("ты красивая") == "romantic"
    assert session.style_hint("ты дурак") == "hostile"
    assert session.style_hint("кто ты") == ""


def test_low_weight_hint_is_ignored():
    catalog = _catalog()
    session = _session(
        catalog,
        _knowledge(catalog),
        senses=_Senses(weight=0.4),
    )
    assert session.style_hint("флирт") == ""


def test_unknown_style_hint_is_ignored():
    catalog = _catalog()
    session = _session(
        catalog,
        _knowledge(catalog),
        senses=_Senses(style="nonexistent"),
    )
    assert session.style_hint("флирт") == ""


# --- приоритет ------------------------------------------------------


def test_hint_beats_default_official():
    catalog = _catalog()
    knowledge = _neutral_knowledge(catalog)
    engine = _session(catalog, knowledge).style_engine
    assert (
        engine.resolve_for_context(None, None, knowledge)
        == "official"
    )
    assert (
        engine.resolve_for_context(
            None, None, knowledge, hint_style="romantic"
        )
        == "romantic"
    )


def test_hint_does_not_beat_order():
    catalog = _catalog()
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[Fact("has_authority", ("char_blue", "char_player"))],
    )
    session = _session(catalog, knowledge, senses=_Senses())
    result = session.style_engine.resolve_for_context(
        None, None, knowledge, hint_style="romantic"
    )
    assert result == "order"
    assert session.style_hint("флирт") == "romantic"


def test_hint_does_not_beat_hostile():
    catalog = _catalog()
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[Fact("at_war_with", ("faction:blue", "faction:red"))],
    )
    engine = _session(catalog, knowledge).style_engine
    assert (
        engine.resolve_for_context(
            None, None, knowledge, hint_style="romantic"
        )
        == "hostile"
    )


def test_hint_does_not_beat_friendly():
    catalog = _catalog()
    knowledge = _knowledge(catalog)
    engine = _session(catalog, knowledge).style_engine
    assert (
        engine.resolve_for_context(
            None, None, knowledge, hint_style="romantic"
        )
        == "friendly"
    )


def test_explicit_style_beats_hint():
    catalog = _catalog()
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[Fact("at_war_with", ("faction:blue", "faction:red"))],
    )
    session = _session(
        catalog, knowledge, style_id="mentor", senses=_Senses()
    )
    assert session.style_hint("флирт") == "romantic"
    assert session.style_id == "mentor"


def test_hint_priority_is_data_driven(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "style_context.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["hint_priority"] = 95
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    knowledge = _knowledge(
        catalog,
        side="blue",
        speaker_id="char_blue",
        faction_id="faction:blue",
        player_side="red",
        player_faction="faction:red",
        facts=[Fact("has_authority", ("char_blue", "char_player"))],
    )
    engine = _session(catalog, knowledge).style_engine
    assert (
        engine.resolve_for_context(
            None, None, knowledge, hint_style="romantic"
        )
        == "romantic"
    )


def test_hint_threshold_is_data_driven(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "style_context.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["hint_min_weight"] = 0.9
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    session = _session(
        catalog,
        _knowledge(catalog),
        senses=_Senses(weight=0.85),
    )
    assert session.style_hint("флирт") == ""


# --- объяснение выбора ---------------------------------------------


def test_decision_explains_rule():
    catalog = _catalog()
    knowledge = _knowledge(catalog)
    decision = _session(catalog, knowledge).style_decision()
    assert decision.style_id == "friendly"
    assert decision.source == "rule"
    assert decision.rule_id == "same_faction_friendly"
    assert decision.description


def test_decision_explains_hint():
    catalog = _catalog()
    knowledge = _neutral_knowledge(catalog)
    session = _session(
        catalog, knowledge, senses=_Senses(weight=0.9)
    )
    session._hint_style = session.style_hint("флирт")
    decision = session.style_decision()
    assert decision.style_id == "romantic"
    assert decision.source == "hint"


def test_decision_explains_explicit():
    catalog = _catalog()
    session = _session(
        catalog, _knowledge(catalog), style_id="mentor"
    )
    decision = session.style_decision()
    assert decision.style_id == "mentor"
    assert decision.source == "explicit"


def test_decision_explains_default(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "style_context.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"] = []
    path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    decision = _session(catalog, _knowledge(catalog)).style_decision()
    assert decision.style_id == catalog.styles.default
    assert decision.source == "default"


# --- совместимость --------------------------------------------------


def test_without_senses_session_still_works():
    catalog = _catalog()
    session = _session(
        catalog, _knowledge(catalog), style_hints=False
    )
    assert session.senses is None
    assert session.style_hint("флирт") == ""
    assert session.style_id == "friendly"


def test_respond_applies_hint_to_parsed_turn():
    catalog = _catalog()
    session = _session(
        catalog, _neutral_knowledge(catalog), senses=_Senses(weight=0.9)
    )
    turn = session.respond("кто ты")
    assert turn.answer is not None
    assert turn.state["style_id"] == "romantic"
    assert session.style_id == "romantic"


def test_respond_clears_hint_after_unparsed_turn():
    catalog = _catalog()
    session = _session(
        catalog, _neutral_knowledge(catalog), senses=_Senses(weight=0.9)
    )
    session.respond("кто ты")
    assert session.style_id == "romantic"
    session.respond("абракадабра")
    assert session.style_id == "official"
