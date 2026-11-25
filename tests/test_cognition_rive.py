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
