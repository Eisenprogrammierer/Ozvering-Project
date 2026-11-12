"""Тесты D1.5: композиционный синтез, морфология и расширяемость.

Проверяется главное обещание слоя: содержание ответа собирается из
конструкций и морфологии, а не выбирается из готовых предложений. Новые
сущности, отношения, конструкции и фразы добавляются JSON-ом.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.dialogue import (
    ChartParser,
    DialogueSession,
    build_knowledge,
    load_dialogue,
)
from campaign.dialogue.inference import InferenceEngine
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.morph import Morphology
from campaign.dialogue.realize import Realizer
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
        catalog, build_knowledge(catalog, campaign, "red")
    )


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DIALOGUE_DIR, target)
    return target


def _rewrite(path: Path, mutate) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_content_answers_do_not_use_whole_sentence_templates(
    tmp_path, campaign
):
    root = _copy(tmp_path)

    def poison(data):
        data["statements"] = {
            relation: {"template": "FALLBACK"}
            for relation in data["statements"]
        }
        data["describe"] = {
            type_name: ["FALLBACK"] for type_name in data["describe"]
        }
        data["summary"] = {
            type_name: ["FALLBACK"] for type_name in data["summary"]
        }
        for key in (
            "value",
            "leader",
            "last_work_intro",
            "last_work_success",
            "last_work_failure",
            "last_work_empty",
        ):
            data["answers"][key] = "FALLBACK"
        data["answers"]["list"] = {
            key: {"intro": "FALLBACK"} for key in data["answers"]["list"]
        }
        data["answers"]["empty"] = {
            key: "FALLBACK" for key in data["answers"]["empty"]
        }
        for spec in data["beliefs"].values():
            spec["template"] = "FALLBACK"

    _rewrite(root / "realization.json", poison)
    poisoned = load_dialogue(root)
    session = DialogueSession(
        poisoned, build_knowledge(poisoned, campaign, "red")
    )
    for phrase in (
        "Считает ли Империя Республику незаконной?",
        "Какие органы есть у Империи?",
        "Есть ли у Империи союзники?",
        "Сколько законности у Империи?",
        "Кто правит Империей?",
        "Что такое Абвер?",
        "Что ты знаешь о Республике?",
        "Что Империя делала в последний ход?",
    ):
        answer = session.ask(phrase)
        assert "FALLBACK" not in answer.text, phrase
        assert answer.text, phrase


def test_new_construction_changes_surface_without_python(tmp_path, campaign):
    root = _copy(tmp_path)

    def add_construction(data):
        data["constructions"]["clause_alliance_alt"] = {
            "parts": [
                {"kind": "np", "source": "subject", "case": "nom"},
                {"kind": "literal", "text": "дружит с"},
                {"kind": "np", "source": "object", "case": "ins"},
            ],
            "end": ".",
        }
        data["statements"]["allied_with"]["construction"] = (
            "clause_alliance_alt"
        )

    _rewrite(root / "synthesis.json", add_construction)
    assert lint_directory(root) == []
    changed = load_dialogue(root)
    knowledge = build_knowledge(changed, campaign, "red")
    realizer = Realizer(
        changed, knowledge, InferenceEngine(changed, knowledge)
    )
    statement = realizer.statement(
        "allied_with", ("faction:red", "faction:amber")
    )
    assert statement == "Империя дружит с Торговой планетой."
    assert "состоит в союзе" not in statement


def test_new_phrase_extends_description_without_python(tmp_path, campaign):
    root = _copy(tmp_path)

    def add_phrase(data):
        data["phrases"]["motto"] = {
            "parts": [
                {
                    "kind": "literal",
                    "text": "Девиз: порядок и точность",
                }
            ],
            "end": ".",
        }
        data["describe"]["organ"].append("motto")

    _rewrite(root / "synthesis.json", add_phrase)
    assert lint_directory(root) == []
    changed = load_dialogue(root)
    session = DialogueSession(
        changed, build_knowledge(changed, campaign, "red")
    )
    answer = session.ask("Что такое Абвер?")
    assert "Девиз: порядок и точность" in answer.text


def test_new_relation_entity_and_lexeme_via_json_only(tmp_path, campaign):
    root = _copy(tmp_path)

    def add_type(data):
        data["entity_types"]["artifact"] = {
            "label": "артефакт",
            "plural": "артефакты",
            "summary": "Предмет, значимый для мира.",
        }

    _rewrite(root / "ontology.json", add_type)

    def add_lexeme(data):
        data["entries"].append(
            {
                "id": "artifact:relic",
                "type": "artifact",
                "cat": "N",
                "lemma": "реликвия",
                "forms": {
                    "nom": ["реликвия"],
                    "gen": ["реликвии"],
                    "dat": ["реликвии"],
                    "acc": ["реликвию"],
                    "ins": ["реликвией"],
                    "prep": ["реликвии"],
                },
                "semantic": {
                    "kind": "entity",
                    "type": "artifact",
                    "id": "artifact:relic",
                },
                "features": {"gender": "f"},
            }
        )

    _rewrite(root / "lexicon.json", add_lexeme)

    def add_relation(data):
        data["relations"]["guards"] = 2

    _rewrite(root / "world.json", add_relation)

    def add_fact(data):
        data["facts"].append(
            {"rel": "guards", "args": ["artifact:relic", "faction:red"]}
        )

    _rewrite(root / "facts.json", add_fact)

    def add_synthesis(data):
        data["constructions"]["clause_guard"] = {
            "parts": [
                {"kind": "np", "source": "subject", "case": "nom"},
                {
                    "kind": "lex",
                    "entry": "verb:defend",
                    "form": "present",
                    "agreement": "subject",
                },
                {"kind": "np", "source": "object", "case": "acc"},
            ],
            "end": ".",
        }
        data["statements"]["guards"] = {
            "construction": "clause_guard",
            "args": {"subject": 0, "object": 1},
        }

    _rewrite(root / "synthesis.json", add_synthesis)
    assert lint_directory(root) == []

    changed = load_dialogue(root)
    knowledge = build_knowledge(changed, campaign, "red")
    realizer = Realizer(
        changed, knowledge, InferenceEngine(changed, knowledge)
    )
    assert (
        realizer.statement("guards", ("artifact:relic", "faction:red"))
        == "Реликвия защищает Империю."
    )


def test_generated_statement_roundtrips_through_parser(red, catalog):
    answer = red.ask("Считает ли Империя Республику незаконной?")
    assert answer.text.startswith("Да. ")
    statement = answer.text.split(". ", 1)[1]
    parse = ChartParser(catalog).parse_one(statement)
    assert parse is not None
    sem = parse.sem
    assert sem["predicate"] == "believe"
    assert sem["value"] == "illegal"
    assert sem["subject"]["head"]["entity"] == "faction:red"
    assert sem["object"]["head"]["entity"] == "faction:blue"


def test_morphology_is_deterministic_and_overridable():
    morphology = Morphology({})
    assert (
        morphology.inflect_phrase("Торговая планета", "gen")
        == "Торговой планеты"
    )
    assert (
        morphology.inflect_phrase("Председатель парламента", "nom")
        == "Председатель парламента"
    )
    assert (
        morphology.inflect_phrase("Председатель парламента", "ins")
        == "Председателем парламента"
    )
    assert morphology.verb("воевать", form="present") == "воюет"
    assert (
        morphology.adjective(
            "незаконный", "ins", "sg", "f", entry_id="adj:illegal"
        )
        == "незаконной"
    )

    overridden = Morphology(
        {"word_forms": {"adj:illegal": {"ins_f": "ОСОБОЙ"}}}
    )
    assert (
        overridden.adjective(
            "незаконный", "ins", "sg", "f", entry_id="adj:illegal"
        )
        == "ОСОБОЙ"
    )


def _copy_into(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    target.mkdir()
    return _copy(target)


def test_lint_reports_missing_construction(tmp_path):
    root = _copy_into(tmp_path, "missing_construction")

    def break_statement(data):
        data["statements"]["allied_with"]["construction"] = "ghost"

    _rewrite(root / "synthesis.json", break_statement)
    problems = lint_directory(root)
    assert any("ghost" in item for item in problems)


def test_lint_reports_missing_phrase_and_collection(tmp_path):
    root = _copy_into(tmp_path, "missing_phrase")

    def break_describe(data):
        data["describe"]["organ"].append("ghost_phrase")

    _rewrite(root / "synthesis.json", break_describe)
    problems = lint_directory(root)
    assert any("ghost_phrase" in item for item in problems)

    root = _copy_into(tmp_path, "bad_collection")

    def break_collection(data):
        data["collections"]["organs"]["pattern"] = ["$self"]

    _rewrite(root / "synthesis.json", break_collection)
    problems = lint_directory(root)
    assert any("pattern" in item for item in problems)


def test_lint_reports_missing_lexeme_in_construction(tmp_path):
    root = _copy_into(tmp_path, "missing_lexeme")

    def break_construction(data):
        data["constructions"]["clause_alliance"]["parts"][2]["entry"] = (
            "noun:ghost"
        )

    _rewrite(root / "synthesis.json", break_construction)
    problems = lint_directory(root)
    assert any("noun:ghost" in item for item in problems)


def test_phrases_with_missing_required_sources_are_skipped(catalog, campaign):
    knowledge = build_knowledge(catalog, campaign, "red")
    realizer = Realizer(
        catalog, knowledge, InferenceEngine(catalog, knowledge)
    )
    # Словарная лексема не выдаёт себя за конкретную работу.
    assert realizer.describe("noun:work") == ""
    # Понятие без начала не оставляет висящее «Начало:».
    affairs = realizer.describe("concept:affairs")
    assert affairs == "Дело — понятие."
    assert "Начало:" not in affairs
    # А у понятия с началом фраза сохраняется.
    assert "Начало: двести лет назад" in realizer.describe("concept:war")


def test_lint_reports_required_source_not_used_in_parts(tmp_path):
    root = _copy_into(tmp_path, "bad_requires")

    def break_requires(data):
        data["phrases"]["beginning_line"]["requires"] = ["ghost"]

    _rewrite(root / "synthesis.json", break_requires)
    problems = lint_directory(root)
    assert any("ghost" in item for item in problems)


def test_morphology_preserves_capitalization_of_single_word():
    morphology = Morphology({})
    assert morphology.inflect_phrase("Император", "nom") == "Император"
    assert morphology.inflect_phrase("Император", "gen") == "Императора"
    assert (
        morphology.inflect_phrase("Григорий Иванов", "gen")
        == "Григория Иванова"
    )


def test_runtime_code_has_no_plot_specific_vocabulary():
    forbidden = (
        "Импери",
        "Республик",
        "Культ Земли",
        "Торговая планета",
        "Абвер",
        "Григорий",
        "faction:red",
        "faction_empire",
    )
    for path in sorted((ROOT / "campaign" / "dialogue").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, "%s содержит %r" % (path.name, token)
