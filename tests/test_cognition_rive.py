"""Компилятор JSON → RiveScript и проверка артефактов."""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.cognition import RiveError
from campaign.cognition.rive_compiler import (
    DEFAULT_DIALOGUE_DIR,
    DEFAULT_RIVE_DIR,
    RiveManifest,
    check_artifacts,
    compile_dialogue,
    lexicon_substitutions,
    render_rive,
    write_artifacts,
)

ROOT = Path(__file__).resolve().parents[1]
DIALOGUE = ROOT / "configs" / "dialogue"


def test_committed_artifacts_match_sources():
    manifest = check_artifacts()
    stored = RiveManifest.load(DEFAULT_RIVE_DIR / "manifest.json")
    assert stored.to_dict() == manifest.to_dict()
    assert manifest.source_digest
    assert manifest.stats["triggers"] == len(manifest.triggers)
    assert manifest.stats["lexicon_entries"] > 0


def test_compile_is_deterministic_and_sorted():
    first = compile_dialogue()
    second = compile_dialogue()
    assert first.digest() == second.digest()
    triggers = [item.trigger for item in first.triggers]
    assert triggers == sorted(triggers)
    assert len(triggers) == len(set(triggers))


def test_lexicon_substitutions_are_unambiguous():
    manifest = compile_dialogue()
    assert manifest.substitutions["империей"] == "империя"
    assert "империя" not in manifest.substitutions
    assert manifest.stats["lexicon_conflicts"] > 0
    assert any(
        "неоднозначных" in item for item in manifest.warnings
    )


def test_action_trigger_wins_over_paraphrase():
    manifest = compile_dialogue()
    trigger = manifest.get("a:enemy_of_state:0")
    assert trigger is not None
    assert trigger.source == "action"
    assert trigger.action_id == "enemy_of_state"
    assert trigger.trigger == "назначь враг"


def test_manifest_roundtrip(tmp_path):
    manifest = compile_dialogue()
    path = manifest.save(tmp_path / "manifest.json")
    loaded = RiveManifest.load(path)
    assert loaded.to_dict() == manifest.to_dict()
    assert loaded.digest() == manifest.digest()


def test_grammar_triggers_cover_closed_constructions():
    manifest = compile_dialogue()
    grammar = [
        item for item in manifest.triggers if item.source == "grammar"
    ]
    assert manifest.stats["grammar_triggers"] == len(grammar)
    assert grammar
    assert manifest.stats["grammar_rules"] > len(grammar)
    assert manifest.stats["grammar_rules_covered"] == len(grammar)
    assert manifest.stats["grammar_rules_skipped"] > 0
    assert (
        manifest.stats["grammar_rules_covered"]
        + manifest.stats["grammar_rules_skipped"]
        == manifest.stats["grammar_rules"]
    )
    ids = {item.id for item in grammar}
    assert "g:s_conditional" in ids
    assert "g:np_neg_v_np" in ids
    assert "g:s_wh_s" in ids


def test_grammar_patterns_partition_all_rules():
    import json

    from campaign.cognition.rive_compiler import grammar_patterns

    grammar = json.loads(
        (DIALOGUE / "grammar.json").read_text(encoding="utf-8")
    )
    lexicon = json.loads(
        (DIALOGUE / "lexicon.json").read_text(encoding="utf-8")
    )
    patterns, covered, skipped = grammar_patterns(
        grammar, lexicon["entries"], {}
    )
    all_ids = [rule["id"] for rule in grammar["rules"]]
    assert sorted(covered + skipped) == sorted(all_ids)
    assert not set(covered) & set(skipped)
    pattern_ids = {rule_id for rule_id, _, _ in patterns}
    assert pattern_ids <= set(covered)
    # NP/PP — дело кадра, а не триггера.
    for rule_id in ("np_noun", "np_adj_noun", "pp_prep_np"):
        assert rule_id in skipped
    # Каждая грамматическая конструкция уровня S с закрытым классом
    # получает хотя бы один шаблон.
    for rule_id in ("s_conditional", "s_wh_s", "np_neg_v_np"):
        assert rule_id in covered


def test_grammar_triggers_use_lexicon_forms_and_wildcards():
    manifest = compile_dialogue()
    conditional = manifest.get("g:s_conditional")
    assert conditional is not None
    assert conditional.text == "COND S TO S"
    assert conditional.trigger.startswith("(если)")
    assert "(то)" in conditional.trigger
    assert "[*]" in conditional.trigger
    negation = manifest.get("g:np_neg_v_np")
    assert negation is not None
    assert negation.trigger == "[*] (не) [*] [*]"
    greeting = manifest.get("g:s_greeting")
    assert greeting is not None
    assert greeting.trigger == "добрый день"


def test_grammar_triggers_do_not_shadow_exact_phrases():
    manifest = compile_dialogue()
    exact = {
        item.trigger
        for item in manifest.triggers
        if item.source != "grammar"
    }
    for item in manifest.triggers:
        if item.source != "grammar":
            continue
        assert item.trigger not in exact


def test_render_is_stable_and_has_fallback():
    manifest = compile_dialogue()
    text = render_rive(manifest)
    assert text == render_rive(manifest)
    assert "+ *" in text
    assert "- <call>nlu __fallback__</call>" in text
    assert "! sub империей = империя" in text


def test_stale_and_missing_artifacts_are_reported(tmp_path):
    write_artifacts(DIALOGUE, tmp_path)
    check_artifacts(DIALOGUE, tmp_path)
    rive_path = tmp_path / "dialogue.rive"
    rive_path.write_text(
        rive_path.read_text(encoding="utf-8") + "\n// stale\n",
        encoding="utf-8",
    )
    with pytest.raises(RiveError):
        check_artifacts(DIALOGUE, tmp_path)
    with pytest.raises(RiveError):
        check_artifacts(DIALOGUE, tmp_path / "missing")


def test_engine_matches_generated_triggers(tmp_path):
    pytest.importorskip("rivescript")
    from rivescript import RiveScript

    write_artifacts(DIALOGUE, tmp_path)
    engine = RiveScript(utf8=True)
    engine.load_file(str(tmp_path / "dialogue.rive"))
    engine.sort_replies()
    engine.set_subroutine(
        "nlu",
        lambda rs, args: args[0] if args else "__fallback__",
    )
    cases = {
        "Привет.": "p:greeting_hello",
        "Кто правит Империей?": "p:wh_ruler",
        "Покажи силу": "a:show_of_force:0",
        "Покажи силу против Республики": "a:show_of_force:1",
        "Назначь врага": "a:enemy_of_state:0",
        "Приказываю тебе": "m:command:0",
        "Империя не воюет": "g:np_neg_v_np_adj",
        "Если империя воюет то республика ждёт": "g:s_conditional",
        "абракадабра ксизи": "__fallback__",
    }
    for text, expected in cases.items():
        assert engine.reply("u", text) == expected


def test_lexicon_substitutions_skip_conflicts():
    entries = [
        {"lemma": "говорить", "forms": ["говорит", "говорят"]},
        {"lemma": "сказать", "forms": ["говорит"]},
        {"lemma": "империя", "forms": {"nom": ["Империя"]}},
    ]
    substitutions, conflicts = lexicon_substitutions(entries)
    assert "говорит" not in substitutions
    assert "говорят" in substitutions
    assert "империя" not in substitutions
    assert conflicts == ("говорит",)
