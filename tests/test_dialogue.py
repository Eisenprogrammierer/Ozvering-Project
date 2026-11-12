"""Тесты D0: данные, разбор, детерминизм и расширение только JSON-ом."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.dialogue import ChartParser, load_dialogue
from campaign.dialogue.lint import lint_catalog, lint_directory
from campaign.dialogue.semantics import entity_id

ROOT = Path(__file__).resolve().parents[1]
DIALOGUE_DIR = ROOT / "configs" / "dialogue"
LORE_PATH = ROOT / "configs" / "campaigns" / "base" / "lore_factions.json"
BDI_PATH = ROOT / "configs" / "characters" / "bdi.json"


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DIALOGUE_DIR)


@pytest.fixture(scope="module")
def parser(catalog):
    return ChartParser(catalog)


GOLDEN = [
    "Почему Империя считает Республику незаконной?",
    "Считает ли Империя Республику незаконной?",
    "Какие органы есть у Империи?",
    "Сколько законности у Империи?",
    "Кто такой Император?",
    "Что такое Абвер?",
    "Где находится Торговая планета?",
    "Когда началась война?",
    "Расскажи о Культе Земли.",
    "Что ты знаешь о Республике?",
    "Кто правит Империей?",
    "Есть ли у Империи союзники?",
    "Как дела?",
    "Привет.",
    "Почему Империя воюет с Республикой?",
]


def test_dialogue_data_lints_clean():
    assert lint_directory(DIALOGUE_DIR) == []


@pytest.mark.parametrize("phrase", GOLDEN)
def test_golden_phrases_parse(parser, phrase):
    parse = parser.parse_one(phrase)
    assert parse is not None, "нет разбора: %s" % phrase
    assert parse.cat == "S"
    assert parse.text


def test_why_outlaw_keeps_roles(parser):
    parse = parser.parse_one("Почему Империя считает Республику незаконной?")
    assert parse is not None
    sem = parse.sem
    assert sem["kind"] == "question"
    assert sem["wh"] == "why"
    body = sem["body"]
    assert body["predicate"] == "believe"
    assert entity_id(body["subject"]) == "faction:red"
    assert entity_id(body["object"]) == "faction:blue"
    assert body["value"] == "illegal"


def test_yesno_body_matches_declarative(parser):
    question = parser.parse_one("Считает ли Империя Республику незаконной?")
    assert question is not None
    assert question.sem["wh"] == "yesno"
    body = question.sem["body"]
    assert entity_id(body["subject"]) == "faction:red"
    assert entity_id(body["object"]) == "faction:blue"
    assert body["value"] == "illegal"


def test_organs_question(parser):
    parse = parser.parse_one("Какие органы есть у Империи?")
    assert parse is not None
    assert parse.sem["wh"] == "which"
    body = parse.sem["body"]
    assert body["have"] is True
    assert entity_id(body["object"]) == "noun:organ"
    assert entity_id(body["owner"]) == "faction:red"


def test_quantity_question(parser):
    parse = parser.parse_one("Сколько законности у Империи?")
    assert parse is not None
    assert parse.sem["wh"] == "how_many"
    body = parse.sem["body"]
    assert body["kind"] == "quantity"
    assert entity_id(body["object"]) == "asset:legitimacy"
    assert entity_id(body["owner"]) == "faction:red"


def test_copula_questions_name_entities(parser):
    who = parser.parse_one("Кто такой Император?")
    what = parser.parse_one("Что такое Абвер?")
    assert who is not None and what is not None
    assert who.sem["wh"] == "who"
    assert entity_id(who.sem["body"]["subject"]) == "post:red:leader"
    assert what.sem["wh"] == "what"
    assert entity_id(what.sem["body"]["subject"]) == "organ:red:abwehr"


def test_where_and_when(parser):
    where = parser.parse_one("Где находится Торговая планета?")
    when = parser.parse_one("Когда началась война?")
    assert where is not None and when is not None
    assert where.sem["wh"] == "where"
    assert where.sem["body"]["predicate"] == "locate"
    assert entity_id(where.sem["body"]["object"]) == "faction:amber"
    assert when.sem["wh"] == "when"
    assert when.sem["body"]["predicate"] == "begin"
    assert entity_id(when.sem["body"]["object"]) == "concept:war"


def test_request_topic_is_proposition(parser):
    parse = parser.parse_one("Расскажи о Культе Земли.")
    assert parse is not None
    assert parse.sem["kind"] == "request"
    assert parse.sem["action"] == "tell"
    assert parse.sem["topic"]["prep"] == "about"
    assert entity_id(parse.sem["topic"]) == "faction:green"


def test_knowledge_question_keeps_pronoun_subject(parser):
    parse = parser.parse_one("Что ты знаешь о Республике?")
    assert parse is not None
    body = parse.sem["body"]
    assert body["predicate"] == "know"
    assert body["subject"] == "you_sg"  # pronoun, не entity
    assert body["object"]["prep"] == "about"
    assert entity_id(body["object"]) == "faction:blue"


def test_who_rules_and_yesno_possession(parser):
    who = parser.parse_one("Кто правит Империей?")
    yesno = parser.parse_one("Есть ли у Империи союзники?")
    assert who is not None and yesno is not None
    assert who.sem["body"]["predicate"] == "rule"
    assert entity_id(who.sem["body"]["object"]) == "faction:red"
    assert yesno.sem["wh"] == "yesno"
    assert yesno.sem["body"]["have"] is True
    assert entity_id(yesno.sem["body"]["owner"]) == "faction:red"
    assert entity_id(yesno.sem["body"]["object"]) == "noun:ally"


def test_smalltalk_parses(parser):
    how = parser.parse_one("Как дела?")
    hello = parser.parse_one("Привет.")
    assert how is not None and hello is not None
    assert how.sem["wh"] == "how"
    assert entity_id(how.sem["body"]["topic"]) == "concept:affairs"
    assert hello.sem["kind"] == "greeting"


def test_subject_and_object_are_not_swapped(parser):
    parse = parser.parse_one("Империя считает Республику незаконной")
    assert parse is not None
    body = parse.sem
    assert entity_id(body["subject"]) == "faction:red"
    assert entity_id(body["object"]) == "faction:blue"


def test_unknown_input_is_not_an_exception(parser):
    assert parser.parse("абракадабра") == []
    assert parser.parse("!!! ???") == []
    assert parser.parse_one("") is None


def test_parsing_is_deterministic(catalog, parser):
    phrase = "Почему Империя считает Республику незаконной?"
    first = [item.key() for item in parser.parse(phrase)]
    second = [item.key() for item in parser.parse(phrase)]
    assert first == second
    fresh = ChartParser(load_dialogue(DIALOGUE_DIR))
    third = [item.key() for item in fresh.parse(phrase)]
    assert first == third


def test_lexicon_covers_all_needs(catalog):
    documented = {
        entry.id
        for entry in catalog.lexicon
        if entry.type == "need"
    }
    needs = json.loads(BDI_PATH.read_text(encoding="utf-8"))["needs"]
    assert len(needs) == 16
    assert documented == {"need:" + key for key in needs}


def test_lexicon_covers_organs_and_posts(catalog):
    lore = json.loads(LORE_PATH.read_text(encoding="utf-8"))
    expected = set()
    for side, faction in lore["factions"].items():
        for organ in faction.get("organs", []):
            expected.add("organ:%s:%s" % (side, organ["id"]))
        for post in faction.get("posts", []):
            expected.add("post:%s:%s" % (side, post["id"]))
    documented = {
        entry.id
        for entry in catalog.lexicon
        if entry.type in ("organ", "post")
    }
    assert expected <= documented


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


def test_new_word_and_rule_need_only_json(tmp_path):
    root = _copy_dialogue(tmp_path)

    def add_word(data):
        data["entries"].append(
            {
                "id": "concept:moon",
                "type": "concept",
                "cat": "N",
                "lemma": "луна",
                "forms": {
                    "nom": ["Луна"],
                    "gen": ["Луны"],
                    "dat": ["Луне"],
                    "acc": ["Луну"],
                    "ins": ["Луной"],
                    "prep": ["Луне"],
                },
                "semantic": {
                    "kind": "entity",
                    "type": "concept",
                    "id": "concept:moon",
                },
                "features": {"gender": "f"},
            }
        )

    _rewrite_json(root / "lexicon.json", add_word)
    parser = ChartParser(load_dialogue(root))
    parsed = parser.parse_one("Где находится Луна?")
    assert parsed is not None
    assert entity_id(parsed.sem["body"]["object"]) == "concept:moon"

    assert parser.parse_one("Луна где?") is None

    def add_rule(data):
        data["rules"].append(
            {
                "id": "s_topic_wh",
                "lhs": "S",
                "rhs": [
                    {"cat": "NP", "as": "topic"},
                    {"cat": "WH", "as": "wh"},
                ],
                "sem": {
                    "kind": "question",
                    "wh": "$wh",
                    "body": {"kind": "topic", "topic": "$topic"},
                },
            }
        )

    _rewrite_json(root / "grammar.json", add_rule)
    parser = ChartParser(load_dialogue(root))
    parsed = parser.parse_one("Луна где?")
    assert parsed is not None
    assert parsed.sem["wh"] == "where"
    assert entity_id(parsed.sem["body"]["topic"]) == "concept:moon"
    assert lint_directory(root) == []


def test_lint_reports_unknown_entity_type(tmp_path):
    root = _copy_dialogue(tmp_path)

    def add_alien(data):
        data["entries"].append(
            {
                "id": "alien:one",
                "type": "alien",
                "cat": "N",
                "lemma": "чужой",
                "forms": {"nom": ["Чужой"]},
                "semantic": {
                    "kind": "entity",
                    "type": "alien",
                    "id": "alien:one",
                },
            }
        )

    _rewrite_json(root / "lexicon.json", add_alien)
    problems = lint_directory(root)
    assert any("отсутствует в онтологии" in item for item in problems)


def test_lint_reports_unknown_head_role(tmp_path):
    root = _copy_dialogue(tmp_path)

    def break_head(data):
        data["rules"].append(
            {
                "id": "np_bad_head",
                "lhs": "NP",
                "rhs": [{"cat": "N", "as": "head"}],
                "head": "missing",
                "sem": {"kind": "np", "head": "$head"},
            }
        )

    _rewrite_json(root / "grammar.json", break_head)
    problems = lint_catalog(load_dialogue(root))
    assert any("head 'missing'" in item for item in problems)


def test_lint_reports_broken_semantic_role(tmp_path):
    root = _copy_dialogue(tmp_path)

    def break_rule(data):
        data["rules"].append(
            {
                "id": "s_broken",
                "lhs": "S",
                "rhs": [{"cat": "NP", "as": "topic"}],
                "sem": {"kind": "question", "wh": "$missing"},
            }
        )

    _rewrite_json(root / "grammar.json", break_rule)
    catalog = load_dialogue(root)
    problems = lint_catalog(catalog)
    assert any("неизвестную роль" in item for item in problems)
