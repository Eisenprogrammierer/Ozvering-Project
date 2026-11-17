"""Факты здравого смысла: загрузка, распознавание фраз и линтер."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from campaign.commonsense import (
    DEFAULT_DIR,
    FactBase,
    load_commonsense,
    lint_commonsense,
    main,
    normalize,
)

ROOT = Path(__file__).resolve().parents[1]
CURATED = (
    "schema.json",
    "speech_acts.jsonl",
    "mode_markers.jsonl",
    "social_causes.jsonl",
    "entities.jsonl",
)


def _copy_data(tmp_path):
    target = tmp_path / "commonsense"
    target.mkdir()
    for name in CURATED:
        shutil.copyfile(DEFAULT_DIR / name, target / name)
    return target


def _append(path, row):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _row(**overrides):
    row = {
        "s": "тест",
        "r": "Causes",
        "o": "проверка",
        "weight": 0.8,
        "lang": "ru",
        "origin": "curated",
        "source": "author",
    }
    row.update(overrides)
    return row


def test_curated_data_loads_and_has_expected_shape():
    base = load_commonsense()
    assert isinstance(base, FactBase)
    assert len(base) >= 600
    summary = base.summary()
    assert summary["files"]["speech_acts.jsonl"] >= 250
    assert summary["files"]["mode_markers.jsonl"] >= 80
    assert summary["files"]["social_causes.jsonl"] >= 140
    assert summary["files"]["entities.jsonl"] >= 110
    assert "apology" in base.acts
    assert "flirt" in base.acts
    assert "poetry" in base.modes
    assert "quarrel" in base.modes


def test_loader_ignores_raw_llm_dumps():
    assert (DEFAULT_DIR / "raw").is_dir()
    base = load_commonsense()
    assert all(not fact.file.startswith("raw/") for fact in base.facts)


def test_classify_recognizes_speech_acts():
    base = load_commonsense()
    cases = {
        "Прости меня, я был неправ.": "apology",
        "Клянусь честью, я всё исправлю.": "oath",
        "Обещаю прийти завтра.": "promise",
        "Убирайся, или ты пожалеешь.": "threat",
        "Ты мне очень нравишься.": "flirt",
        "Приказываю немедленно остановиться.": "command",
        "Не могли бы вы помочь?": "request",
        "Спасибо за помощь.": "thanks",
    }
    for phrase, act in cases.items():
        reading = base.classify(phrase)
        assert act in reading.acts, (phrase, reading.acts)
        assert reading.evidence
        assert reading.as_dict()["acts"] == list(reading.acts)


def test_classify_recognizes_modes():
    base = load_commonsense()
    cases = {
        "Ты жалкий дурак.": "insult",
        "Мне нужен твой аргумент и доказательство.": "argument",
        "Не плачь, я рядом.": "consolation",
        "Прочти мне стихи о любви.": "flirtation",
        "Она пишет поэму в стихах.": "poetry",
    }
    for phrase, mode in cases.items():
        reading = base.classify(phrase)
        assert mode in reading.modes, (phrase, reading.modes)


def test_effects_of_and_entity_queries():
    base = load_commonsense()
    effects = {fact.o for fact in base.effects_of("оскорбление")}
    assert "обида" in effects
    assert "вражда" in effects
    assert {fact.o for fact in base.classes_of("меч")} == {"оружие"}
    assert "сообщение" in {fact.o for fact in base.uses_of("письмо")}
    assert "имеет ценность" in {
        fact.o for fact in base.properties_of("монета")
    }
    assert {fact.o for fact in base.effects_of("помощь")} >= {
        "благодарность",
        "доверие",
    }


def test_lookup_filters_by_subject_relation_and_object():
    base = load_commonsense()
    assert base.lookup(subject="ХЛЕБ", relation="UsedFor")[0].o in {
        "насыщение",
    }
    assert all(
        fact.r == "Causes" for fact in base.lookup(relation="Causes")
    )
    assert all(
        normalize(fact.o) == "страх" for fact in base.lookup(object="Страх")
    )
    limited = base.lookup(subject="меч", limit=2)
    assert len(limited) == 2
    assert base.related("верность")


def test_lint_is_clean_on_shipped_data():
    assert lint_commonsense() == []


def test_linter_rejects_duplicates(tmp_path):
    target = _copy_data(tmp_path)
    path = target / "entities.jsonl"
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    _append(path, first)
    problems = lint_commonsense(target)
    assert any("дубликат" in item for item in problems)


def test_linter_rejects_self_loop_and_bad_weight(tmp_path):
    target = _copy_data(tmp_path)
    path = target / "social_causes.jsonl"
    _append(path, _row(s="ссора", o="ссора", r="Causes"))
    _append(path, _row(s="тест2", weight=1.5))
    problems = lint_commonsense(target)
    assert any("совпадает с объектом" in item for item in problems)
    assert any("вне диапазона" in item for item in problems)


def test_linter_rejects_unknown_act_relation_and_language(tmp_path):
    target = _copy_data(tmp_path)
    _append(
        target / "speech_acts.jsonl",
        _row(s="неведомое", r="IsA", o="nonsense_act"),
    )
    _append(
        target / "entities.jsonl",
        _row(s="неведомое", r="Likes", o="что-то"),
    )
    _append(
        target / "mode_markers.jsonl",
        _row(s="неведомое", r="UsedIn", o="poetry", lang="en"),
    )
    problems = lint_commonsense(target)
    assert any("не входит в acts" in item for item in problems)
    assert any("неизвестное отношение" in item for item in problems)
    assert any("неизвестный язык" in item for item in problems)


def test_linter_reports_missing_required_file(tmp_path):
    target = _copy_data(tmp_path)
    (target / "mode_markers.jsonl").unlink()
    problems = lint_commonsense(target)
    assert any("нет обязательного файла" in item for item in problems)


def test_new_fact_is_picked_up_without_python_changes(tmp_path):
    target = _copy_data(tmp_path)
    _append(
        target / "entities.jsonl",
        _row(
            s="фонарь",
            r="UsedFor",
            o="ночной дозор",
            weight=0.77,
        ),
    )
    base = load_commonsense(target)
    assert [fact.o for fact in base.uses_of("фонарь")] == ["ночной дозор"]
    assert base.lookup(subject="фонарь")[0].origin == "curated"


def test_cli_check_and_classify(capsys):
    assert main(["--check"]) == 0
    captured = capsys.readouterr()
    assert "в порядке" in captured.out
    assert main(["Клянусь", "честью"]) == 0
    captured = capsys.readouterr()
    assert "oath" in captured.out


def test_normalize_handles_case_yo_and_spaces():
    assert normalize("  Ёлка   ПРИВЕТ  ") == "елка привет"
    assert normalize("«Спасибо!»") == "спасибо"


def test_mode_styles_are_data_driven():
    base = load_commonsense()
    assert base.style_for("flirtation") == "romantic"
    assert base.style_for("insult") == "hostile"
    assert base.style_for("nonsense") == ""
    assert base.classify("Ты жалкий дурак.").styles == ("hostile",)
    assert base.classify("Не плачь, я рядом.").styles == ("friendly",)
    assert base.classify(
        "Мне нужен твой аргумент и доказательство."
    ).styles == ("official",)


def test_linter_reports_unknown_style_hint_mode(tmp_path):
    target = _copy_data(tmp_path)
    path = target / "schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["style_hints"]["nonsense"] = "hostile"
    path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    problems = lint_commonsense(target)
    assert any("неизвестные режимы" in item for item in problems)


def test_paraphrase_corpus_takes_phrases_from_commonsense():
    base = load_commonsense()
    known = {
        normalize(fact.s)
        for fact in base.by_relation("IsA")
        if fact.o in base.acts
    }
    corpus = json.loads(
        (
            ROOT / "configs" / "dialogue" / "paraphrases.json"
        ).read_text(encoding="utf-8")
    )
    linked = [
        entry
        for entry in corpus["phrases"]
        if entry.get("source") == "commonsense"
    ]
    assert len(linked) >= 10
    for entry in linked:
        assert normalize(entry["text"]) in known, entry["text"]
