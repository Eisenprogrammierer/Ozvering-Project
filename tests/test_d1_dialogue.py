"""Тесты D1: read-only вопросы о мире, вывод, детерминизм и данные."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import (
    DialogueSession,
    build_knowledge,
    load_dialogue,
)
from campaign.dialogue.lint import lint_directory
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
DIALOGUE_DIR = ROOT / "configs" / "dialogue"
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


@pytest.fixture(scope="module")
def campaign():
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    return AutomataCampaign(generator.generate(seed=13), seed=13)


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DIALOGUE_DIR)


@pytest.fixture(scope="module")
def red(catalog, campaign):
    return DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
    )


@pytest.fixture(scope="module")
def blue(catalog, campaign):
    return DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "blue"),
        style_id="neutral",
    )


def _snapshot(campaign) -> dict:
    return json.loads(json.dumps(campaign.snapshot(), ensure_ascii=False))


def test_dialogue_data_lints_clean():
    assert lint_directory(DIALOGUE_DIR) == []


def test_why_uses_rule_and_proof_trace(red):
    answer = red.ask("Почему Империя считает Республику незаконной?")
    assert answer.plan_id == "belief_why"
    assert answer.kind == "explanation"
    assert "лидер фракции" in answer.text.lower()
    assert answer.proof
    proof = answer.proof[0]
    assert proof.rule == "belief_outlaw"
    assert proof.because
    assert any("belief" in line for line in proof.lines())


def test_yesno_proves_and_states_the_belief(red):
    answer = red.ask("Считает ли Империя Республику незаконной?")
    assert answer.plan_id == "belief_yesno"
    assert answer.kind == "yes"
    assert answer.text.startswith("Да.")
    assert "Империя" in answer.text
    assert "Республику" in answer.text


def test_unknown_belief_is_not_invented(red):
    answer = red.ask("Почему Империя считает Культ Земли незаконной?")
    assert answer.kind == "unknown"
    assert answer.text == red.persona.unknown


def test_agent_only_speaks_for_own_beliefs(blue):
    answer = blue.ask("Почему Империя считает Республику незаконной?")
    assert answer.kind == "unknown"
    assert answer.text == blue.persona.unknown


def test_war_reason_comes_from_rule(red):
    answer = red.ask("Почему Империя воюет с Республикой?")
    assert answer.plan_id == "war_why"
    assert "о законности" in answer.text.lower()
    assert answer.proof[0].rule == "war_reason_legitimacy"


def test_organs_list_is_deterministic_and_named(red):
    first = red.ask("Какие органы есть у Империи?")
    second = red.ask("Какие органы есть у Империи?")
    assert first.kind == "list"
    assert first.text == second.text
    assert "Абвер" in first.text
    assert "Имперская ставка" in first.text


def test_organ_yesno_uses_possession(red):
    answer = red.ask("Есть ли у Империи Абвер?")
    assert answer.plan_id == "organ_yesno"
    assert answer.kind == "yes"
    assert "Абвер" in answer.text


def test_allies_yesno_uses_symmetric_belief(red):
    answer = red.ask("Есть ли у Империи союзники?")
    assert answer.plan_id == "allies_yesno"
    assert answer.text.startswith("Да.")
    assert "Торговая планета" in answer.text


def test_works_list_reads_campaign_actions(red):
    answer = red.ask("Какие работы есть у Империи?")
    assert answer.kind == "list"
    assert "Опубликовать имперский эдикт" in answer.text


def test_asset_value_is_read_from_snapshot(red):
    answer = red.ask("Сколько законности у Империи?")
    assert answer.plan_id == "asset_quantity"
    assert answer.kind == "value"
    assert "0.72" in answer.text
    assert "законность" in answer.text.lower()


def test_leader_is_resolved_through_post(red):
    answer = red.ask("Кто правит Империей?")
    assert answer.plan_id == "leader_who"
    assert "Император" in answer.text
    assert "Григорий Иванов" in answer.text


def test_organ_description_uses_ontology_and_state(red):
    answer = red.ask("Что такое Абвер?")
    assert answer.plan_id == "describe_entity"
    assert "Абвер" in answer.text
    assert "орган" in answer.text.lower()
    assert "Целостность" in answer.text


def test_where_and_when_use_static_facts(red):
    where = red.ask("Где находится Торговая планета?")
    when = red.ask("Когда началась война?")
    assert "вне территорий двух империй" in where.text
    assert "двести лет назад" in when.text


def test_faction_summary_combines_state_and_beliefs(red):
    answer = red.ask("Что ты знаешь о Республике?")
    assert answer.kind == "summary"
    assert "Органы:" in answer.text
    assert "Активы:" in answer.text
    assert "Убеждения:" in answer.text
    assert "Империя считает Республику незаконной" in answer.text
    assert ".;" not in answer.text


def test_concept_summary_uses_description(red):
    answer = red.ask("Расскажи о войне.")
    assert answer.kind == "summary"
    assert "война" in answer.text.lower()
    assert "двести лет" in answer.text


def test_last_work_waits_for_a_real_turn(catalog, campaign):
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
    )
    empty = session.ask("Что Империя делала в последний ход?")
    assert empty.kind == "no"
    assert "нет записанных работ" in empty.text

    advanced = AutomataCampaign(
        CampaignPresetGenerator(
            catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
            template_path=TEMPLATE,
        ).generate(seed=13),
        seed=13,
    )
    for _ in range(2):
        advanced.advance(player_action=advanced.auto_action(advanced.player_side))
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, advanced, "red"),
        style_id="neutral",
    )
    answer = session.ask("Что Империя делала в последний ход?")
    assert answer.kind == "list"
    assert "Последний ход Империи" in answer.text


def test_greeting_and_unknown_tone_depend_on_persona(red, blue):
    assert red.ask("Привет.").text != blue.ask("Привет.").text
    assert red.ask("абракадабра").text == red.persona.parse_unknown
    assert blue.ask("абракадабра").text == blue.persona.parse_unknown
    assert red.persona.parse_unknown != blue.persona.parse_unknown


@pytest.mark.parametrize(
    "phrase",
    [
        "Почему Империя считает Республику незаконной?",
        "Считает ли Империя Республику незаконной?",
        "Какие органы есть у Империи?",
        "Сколько законности у Империи?",
        "Кто правит Империей?",
        "Что такое Абвер?",
        "Есть ли у Империи союзники?",
        "Почему Империя воюет с Республикой?",
        "Где находится Торговая планета?",
        "Когда началась война?",
        "Расскажи о Республике.",
        "Привет.",
    ],
)
def test_answers_are_deterministic_and_have_plans(red, phrase):
    first = red.ask(phrase)
    second = red.ask(phrase)
    assert first == second
    assert first.plan_id
    assert first.text


def test_dialogue_is_read_only(catalog, campaign):
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
    )
    before = _snapshot(campaign)
    for phrase in (
        "Почему Империя считает Республику незаконной?",
        "Какие органы есть у Империи?",
        "Сколько законности у Империи?",
        "Что ты знаешь о Республике?",
        "Что Империя делала в последний ход?",
        "абракадабра",
    ):
        session.ask(phrase)
    after = _snapshot(campaign)
    assert before == after


def _copy_dialogue(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DIALOGUE_DIR, target)
    return target


def _rewrite_json(path: Path, mutate) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_new_fact_needs_only_json(tmp_path, campaign):
    root = _copy_dialogue(tmp_path)

    def add_fact(data):
        data["facts"].append(
            {
                "rel": "description",
                "args": ["concept:affairs", "Дела идут своим чередом."],
            }
        )

    _rewrite_json(root / "facts.json", add_fact)
    assert lint_directory(root) == []
    catalog = load_dialogue(root)
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
    )
    answer = session.ask("Расскажи о делах.")
    assert "Дела идут своим чередом." in answer.text


def test_new_rule_needs_only_json(tmp_path, campaign):
    root = _copy_dialogue(tmp_path)

    def add_rule(data):
        data["rules"].append(
            {
                "id": "alliance_symmetric",
                "priority": 30,
                "head": {
                    "rel": "allied_with",
                    "args": ["$a", "$b"],
                },
                "premises": [
                    {
                        "rel": "allied_with",
                        "args": ["$b", "$a"],
                    }
                ],
                "because": "союз симметричен",
            }
        )

    _rewrite_json(root / "rules.json", add_rule)
    assert lint_directory(root) == []
    catalog = load_dialogue(root)
    session = DialogueSession(
        catalog,
        build_knowledge(catalog, campaign, "red"),
        style_id="neutral",
    )
    answer = session.ask("Есть ли у Торговой планеты союзники?")
    assert answer.kind == "list"
    assert "Империя" in answer.text


def test_lint_reports_unknown_relation_and_bad_arity(tmp_path):
    root = _copy_dialogue(tmp_path)

    def break_fact(data):
        data["facts"].append({"rel": "unknown_relation", "args": ["a"]})

    _rewrite_json(root / "facts.json", break_fact)
    problems = lint_directory(root)
    assert any("не объявлено" in item for item in problems)

    root = _copy_dialogue(tmp_path / "second")

    def break_rule(data):
        data["rules"][0]["head"]["args"] = ["$faction"]

    _rewrite_json(root / "rules.json", break_rule)
    problems = lint_directory(root)
    assert any("арность" in item for item in problems)


def test_lint_reports_unbound_head_variable(tmp_path):
    root = _copy_dialogue(tmp_path)

    def break_rule(data):
        data["rules"][0]["head"]["args"].append("$ghost")

    _rewrite_json(root / "rules.json", break_rule)
    problems = lint_directory(root)
    assert any("не связана посылками" in item for item in problems)


def test_lint_reports_missing_realization_key(tmp_path):
    root = _copy_dialogue(tmp_path)

    def break_plan(data):
        data["plans"][0]["answer"]["key"] = "missing_key"

    _rewrite_json(root / "plans.json", break_plan)
    problems = lint_directory(root)
    assert any("missing_key" in item for item in problems)