"""Тесты D6.2d: условия, уступки и косвенная речь.

Проверяют, что новые конструкции живут в данных: лексикон даёт
``SCONJ``/``COMP`` и глагол речи, грамматика собирает из них
``conditional``, ``concessive`` и ``report``, а старые разборы не
ломаются. Цитаты и детерминированный beam остаются открытыми.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from campaign.dialogue.engine import DialogueSession
from campaign.dialogue.knowledge import AgentKnowledge, Fact
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.parser import ChartParser


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _catalog(directory: Path):
    return load_dialogue(directory)


def _sem(text: str, rule: str = ""):
    parses = ChartParser(load_dialogue(DEFAULT_DIR)).parse(text)
    assert parses
    if rule:
        matches = [item for item in parses if item.rule == rule]
        assert matches, [item.rule for item in parses]
        return matches[0].sem
    return parses[0].sem


# --- данные ---------------------------------------------------------


def test_conditional_lexicon_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    entries = {entry.id: entry for entry in catalog.lexicon}
    assert entries["concept:although"].cat == "SCONJ"
    assert entries["concept:that"].cat == "COMP"
    assert entries["verb:say"].cat == "V"


def test_lint_d6_grammar_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    assert problems == []


def test_new_grammar_is_json_only(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "grammar.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["rules"] = [
        rule for rule in data["rules"] if rule["id"] != "s_concessive"
    ]
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    catalog = _catalog(directory)
    parses = ChartParser(catalog).parse(
        "Хотя Империя воюет с Республикой, "
        "Республика не воюет с Империей"
    )
    assert not [item for item in parses if item.rule == "s_concessive"]


# --- условия --------------------------------------------------------


def test_conditional_parsed():
    sem = _sem(
        "Если Империя воюет с Республикой, "
        "то Республика воюет с Империей",
        "s_conditional",
    )
    assert sem["kind"] == "conditional"
    assert sem["antecedent"]["predicate"] == "fight"
    assert sem["consequent"]["predicate"] == "fight"
    assert sem["antecedent"]["subject"]["head"]["entity"] == "faction:red"
    assert sem["consequent"]["subject"]["head"]["entity"] == "faction:blue"


def test_conditional_keeps_negation():
    sem = _sem(
        "Если Империя не воюет с Республикой, "
        "то Республика не воюет с Империей",
        "s_conditional",
    )
    assert sem["kind"] == "conditional"
    assert sem["antecedent"]["negated"] is True
    assert sem["consequent"]["negated"] is True


# --- уступки --------------------------------------------------------


def test_concessive_parsed():
    sem = _sem(
        "Хотя Империя воюет с Республикой, "
        "Республика не воюет с Империей",
        "s_concessive",
    )
    assert sem["kind"] == "concessive"
    assert sem["concession"]["predicate"] == "fight"
    assert sem["concession"]["subject"]["head"]["entity"] == "faction:red"
    assert sem["clause"]["negated"] is True
    assert sem["clause"]["subject"]["head"]["entity"] == "faction:blue"


def test_concessive_uses_data_lexeme(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "lexicon.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data["entries"]:
        if entry["id"] == "concept:although":
            entry["forms"] = ["вопреки"]
            entry["lemma"] = "вопреки"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    catalog = _catalog(directory)
    parser = ChartParser(catalog)
    assert not parser.parse(
        "Хотя Империя воюет с Республикой, "
        "Республика не воюет с Империей"
    )
    parses = parser.parse(
        "Вопреки Империя воюет с Республикой, "
        "Республика не воюет с Империей"
    )
    assert [item for item in parses if item.rule == "s_concessive"]


# --- косвенная речь -------------------------------------------------


def test_indirect_speech_parsed():
    sem = _sem(
        "Император сказал, что Империя воюет с Республикой",
        "s_indirect_speech",
    )
    assert sem["kind"] == "report"
    assert sem["predicate"] == "say"
    assert sem["speaker"]["head"]["entity"] == "post:red:leader"
    assert sem["body"]["predicate"] == "fight"
    assert sem["body"]["subject"]["head"]["entity"] == "faction:red"


def test_report_keeps_embedded_question():
    sem = _sem(
        "Император сказал, что Империя воюет с Республикой",
        "s_indirect_speech",
    )
    assert sem["body"]["kind"] == "assert"
    assert "wh" not in sem["body"]


# --- детерминизм и регрессии ---------------------------------------


def test_parses_are_deterministic():
    parser = ChartParser(load_dialogue(DEFAULT_DIR))
    text = (
        "Хотя Империя воюет с Республикой, "
        "Республика не воюет с Империей"
    )
    first = [(item.rule, repr(item.sem)) for item in parser.parse(text)]
    second = [(item.rule, repr(item.sem)) for item in parser.parse(text)]
    assert first == second


def test_legacy_yesno_still_parsed():
    sem = _sem("Считает ли Империя Республику незаконной?")
    assert sem["kind"] == "question"
    assert sem["body"]["predicate"] == "believe"


def test_session_handles_new_semantics_without_crash(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = AgentKnowledge(
        catalog,
        facts=(Fact("at_war_with", ("faction:red", "faction:blue")),),
        entities={},
        side="red",
        faction_id="faction:red",
        speaker_id="char_red",
        speaker_name="Император",
        world=catalog.world,
        run_id="campaign:red:13",
    )
    session = DialogueSession(catalog, knowledge, persona_id="red")
    answer = session.ask(
        "Хотя Империя воюет с Республикой, "
        "Республика не воюет с Империей"
    )
    assert answer.kind == "unknown"
    assert answer.plan_id == "unmatched"
