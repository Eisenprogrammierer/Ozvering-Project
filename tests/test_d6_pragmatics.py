"""Phase 3: прагматика диалога в Soar.

Проверяют компилятор (JSON → продукции), исполнение через SML, режимы
``legacy|shadow|soar`` и деградацию без пакета ``soar-sml``. Ответы на
корпусе обязаны совпадать с легаси: Soar выбирает план и исход
раскрытия, но не меняет знание и не синтезирует текст.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest

from campaign.cognition.errors import SoarError
from campaign.cognition.pragmatics_compiler import (
    DEFAULT_DISCLOSURE_PATH,
    DEFAULT_SOAR_DIR,
    PragmaticsModel,
    check_policy,
    compile_policy,
    load_model,
    write_policy,
)
from campaign.dialogue.answers import AnswerPlanner
from campaign.dialogue.engine import DialogueSession
from campaign.dialogue.knowledge import AgentKnowledge, Fact
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.pragmatics import (
    DialoguePragmatics,
    load_pragmatics,
)
from campaign.dialogue.style import StyleEngine


def _catalog():
    return load_dialogue(DEFAULT_DIR)


def _persona(catalog, **changes):
    base = catalog.personas.get("red") or list(
        catalog.personas.values()
    )[0]
    return dataclasses.replace(base, **changes)


def _knowledge(catalog, facts=()):
    return AgentKnowledge(
        catalog,
        facts=tuple(facts),
        entities={},
        side="red",
        faction_id="faction:red",
        speaker_id="char_red",
        speaker_name="Император",
        world=catalog.world,
        player_id="char_player",
        player_name="Игрок",
        run_id="campaign:red:13",
    )


def _planner(catalog, persona, facts=(), pragmatics=None):
    knowledge = _knowledge(catalog, facts)
    style_engine = StyleEngine(catalog)
    planner = AnswerPlanner(
        catalog,
        knowledge,
        persona,
        style_engine=style_engine,
        pragmatics=pragmatics,
    )
    planner.set_style(style_engine.profile("neutral"))
    return planner, knowledge


def _belief_sem():
    return {
        "kind": "question",
        "wh": "yesno",
        "body": {
            "kind": "assert",
            "predicate": "believe",
            "value": "illegal",
            "subject": {"head": {"entity": "faction:red"}},
            "object": {"head": {"entity": "faction:blue"}},
        },
    }


def _belief_facts():
    return [
        Fact("speaks_for", ("char_red", "faction:red")),
        Fact(
            "belief",
            (
                "char_red",
                "faction:red",
                "considers_illegitimate",
                "faction:blue",
            ),
        ),
    ]


# --- компилятор -----------------------------------------------------


def test_shipped_artifact_matches_sources():
    model = load_model()
    assert model.decision_cycles >= 1
    text, compiled, _disclosure = compile_policy()
    assert compiled.digest() == model.digest()
    assert "source_digest" in text
    assert check_policy() == model


def test_compiler_rejects_non_finite_tie_epsilon():
    with pytest.raises(SoarError):
        PragmaticsModel(tie_epsilon=float("inf"))
    with pytest.raises(SoarError):
        PragmaticsModel(tie_epsilon=-1.0)
    with pytest.raises(SoarError):
        PragmaticsModel(decision_cycles=0)


def test_compiler_writes_and_checks_tmp_artifact(tmp_path):
    soar_dir = tmp_path / "soar"
    soar_dir.mkdir()
    shutil.copy(
        DEFAULT_SOAR_DIR / "pragmatics.json",
        soar_dir / "pragmatics.json",
    )
    target = write_policy(soar_dir, DEFAULT_DISCLOSURE_PATH)
    assert target.is_file()
    assert check_policy(soar_dir, DEFAULT_DISCLOSURE_PATH)


# --- исполнение Soar ------------------------------------------------


@pytest.fixture
def soar():
    pytest.importorskip("soar_sml")
    from campaign.cognition.pragmatics_runtime import SoarPragmatics

    return SoarPragmatics(timeout_ms=250)


def test_plan_priority_then_catalog_order(soar):
    frame = {"kind": "question", "act": "", "wh": "yesno"}
    honest = {"policy": "honest", "lie": False, "topic": ""}
    first = soar.decide(
        [("a", 10, 0), ("b", 10, 1), ("c", 5, 2)], frame, honest
    )
    assert first["plan"] == "a"
    second = soar.decide(
        [("b", 10, 0), ("a", 10, 1)], frame, honest
    )
    assert second["plan"] == "b"
    third = soar.decide([("x", 1, 0), ("y", 9, 1)], frame, honest)
    assert third["plan"] == "y"


@pytest.mark.parametrize(
    "policy,flag,expected",
    [
        ("honest", False, "truth"),
        ("partial", False, "partial"),
        ("withhold", False, "withhold"),
        ("evasive", False, "evade"),
        ("lie", True, "lie"),
        ("lie", False, "truth"),
        ("unknown", False, "truth"),
    ],
)
def test_disclosure_outcomes(soar, policy, flag, expected):
    result = soar.decide(
        [("a", 10, 0)],
        {"kind": "question"},
        {"policy": policy, "lie": flag, "topic": "at_war_with"},
    )
    assert result["disclosure"] == expected
    assert result["trace"][0] == "interpret:question"


def test_runtime_budget_is_enforced(soar):
    from campaign.cognition.errors import SoarError

    with pytest.raises(SoarError):
        soar.decide(
            [("a", 10, 0)],
            {"kind": "question"},
            {"policy": "honest", "lie": False, "topic": ""},
            timeout_ms=1e-9,
        )


# --- режимы ---------------------------------------------------------


def test_legacy_backend_never_starts_soar():
    backend = DialoguePragmatics("legacy")
    assert backend.choose_plan([("a", 1, 0)], {}, "a") == "a"
    assert backend.choose_disclosure("a", "lie", True, "t", "lie") == "lie"
    assert backend.report.decisions == 0
    assert backend.to_dict()["ok"] is True


def test_unavailable_soar_degrades_to_legacy(monkeypatch):
    import campaign.cognition.pragmatics_runtime as runtime

    monkeypatch.setattr(runtime, "soar_available", lambda: False)
    backend = DialoguePragmatics("soar")
    assert backend.choose_plan([("a", 1, 0)], {}, "a") == "a"
    assert backend.backend == "legacy"
    assert backend.report.unavailable is True
    assert backend.to_dict()["ok"] is False
    assert "soar-sml" in backend.report.last_error


class _FakeSoar:
    def __init__(self, plan="b", disclosure="lie", error=None):
        self.plan = plan
        self.disclosure = disclosure
        self.error = error
        self.calls = 0

    def decide(self, plans, frame, disclosure, timeout_ms=None):
        self.calls += 1
        if self.error:
            raise self.error
        return {
            "plan": self.plan,
            "disclosure": self.disclosure,
            "intent": frame.get("kind", ""),
            "trace": ("interpret:x", "select:%s" % self.plan),
            "elapsed_ms": 1.0,
        }


def test_shadow_returns_legacy_and_records_mismatch():
    backend = DialoguePragmatics(
        "shadow", soar=_FakeSoar(plan="b", disclosure="withhold")
    )
    assert backend.choose_plan([("a", 1, 0), ("b", 0, 1)], {}, "a") == "a"
    assert backend.choose_disclosure("a", "lie", True, "t", "lie") == "lie"
    report = backend.to_dict()
    assert report["backend"] == "shadow"
    assert report["plan_mismatches"] == 1
    assert report["disclosure_mismatches"] == 1
    assert report["decisions"] == 2
    assert report["disagreements"] == 2


def test_shadow_sink_receives_records():
    records = []
    backend = DialoguePragmatics(
        "shadow",
        soar=_FakeSoar(plan="a", disclosure="lie"),
        shadow_sink=records.append,
    )
    backend.choose_plan([("a", 1, 0)], {}, "a")
    backend.choose_disclosure("a", "lie", True, "t", "lie")
    assert [item["kind"] for item in records] == ["plan", "disclosure"]
    assert records[0] == {"kind": "plan", "legacy": "a", "soar": "a"}
    assert records[1] == {
        "kind": "disclosure",
        "legacy": "lie",
        "soar": "lie",
    }


def test_shadow_masks_soar_errors():
    backend = DialoguePragmatics(
        "shadow", soar=_FakeSoar(error=RuntimeError("boom"))
    )
    assert backend.choose_plan([("a", 1, 0)], {}, "a") == "a"
    assert backend.choose_disclosure("a", "lie", True, "t", "lie") == "lie"
    report = backend.to_dict()
    assert report["errors"] == 2
    assert "boom" in report["last_error"]


def test_soar_does_not_mask_errors():
    backend = DialoguePragmatics(
        "soar", soar=_FakeSoar(error=RuntimeError("boom"))
    )
    with pytest.raises(RuntimeError):
        backend.choose_plan([("a", 1, 0)], {}, "a")


def test_load_pragmatics_reads_flags():
    backend = load_pragmatics()
    assert backend.requested == "legacy"
    assert backend.backend == "legacy"
    assert backend.report.requested == "legacy"
    assert backend.active is False


# --- интеграция с планировщиком ------------------------------------


def test_planner_modes_agree_on_disclosure():
    pytest.importorskip("soar_sml")
    catalog = _catalog()
    persona = _persona(
        catalog,
        disclosure={"default": "lie"},
        lie_probability=1.0,
    )
    catalog = dataclasses.replace(
        catalog, personas={**catalog.personas, "red": persona}
    )
    answers = {}
    for mode in ("legacy", "shadow", "soar"):
        planner, knowledge = _planner(
            catalog,
            persona,
            _belief_facts(),
            DialoguePragmatics(mode),
        )
        before = knowledge.facts
        answer = planner.plan(_belief_sem())
        assert knowledge.facts == before == tuple(_belief_facts())
        answers[mode] = answer
        if mode != "legacy":
            report = planner.pragmatics.to_dict()
            assert report["disagreements"] == 0
            assert report["decisions"] >= 1
            assert answer.data["pragmatics_backend"] == mode
            assert answer.data["pragmatics_trace"]
    base = answers["legacy"]
    for mode in ("shadow", "soar"):
        other = answers[mode]
        assert other.plan_id == base.plan_id
        assert other.kind == base.kind
        assert other.text == base.text
        assert other.data["disclosure"] == base.data["disclosure"]
        assert other.data.get("lied") == base.data.get("lied")


def test_honest_answer_carries_plan_trace():
    pytest.importorskip("soar_sml")
    catalog = _catalog()
    persona = _persona(catalog, disclosure={"default": "honest"})
    planner, _knowledge_obj = _planner(
        catalog,
        persona,
        _belief_facts(),
        DialoguePragmatics("shadow"),
    )
    answer = planner.plan(_belief_sem())
    assert answer.data["pragmatics_backend"] == "shadow"
    assert answer.data["pragmatics_trace"][0] == "interpret:question"
    assert answer.data["pragmatics_trace"][1].startswith("select:")
    assert "disclosure" not in answer.data


def test_corpus_answers_agree_across_modes():
    pytest.importorskip("soar_sml")
    catalog = _catalog()
    persona = _persona(
        catalog,
        disclosure={
            "default": "lie",
            "on_topic": {"at_war_with": "withhold"},
        },
        lie_probability=0.9,
    )
    catalog = dataclasses.replace(
        catalog, personas={**catalog.personas, "red": persona}
    )
    facts = _belief_facts() + [
        Fact("at_war_with", ("faction:red", "faction:blue"))
    ]
    phrases = (
        "Привет",
        "Кто ты?",
        "Считает ли Империя Республику незаконной?",
        "Империя воюет с Республикой?",
        "Почему?",
        "Расскажи о Республике",
        "Что ты знаешь о Республике?",
        "Пока",
    )

    def run(mode):
        session = DialogueSession(
            catalog,
            _knowledge(catalog, facts),
            persona_id="red",
            pragmatics=DialoguePragmatics(mode),
        )
        answers = []
        for text in phrases:
            answer = session.respond(text).answer
            payload = {
                key: value
                for key, value in (answer.data or {}).items()
                if key not in ("pragmatics_backend", "pragmatics_trace")
            }
            answers.append(
                (
                    answer.plan_id,
                    answer.kind,
                    answer.text,
                    payload,
                )
            )
        return answers, session.planner.pragmatics.to_dict()

    base, _report = run("legacy")
    for mode in ("shadow", "soar"):
        answers, report = run(mode)
        assert report["errors"] == 0
        assert report["decisions"] >= len(phrases)
        assert answers == base
        if mode == "shadow":
            assert report["disagreements"] == 0
            assert report["agreements"] == report["decisions"]


def test_session_accepts_pragmatics():
    pytest.importorskip("soar_sml")
    catalog = _catalog()
    persona = _persona(
        catalog,
        disclosure={"default": "lie"},
        lie_probability=1.0,
    )
    catalog = dataclasses.replace(
        catalog, personas={**catalog.personas, "red": persona}
    )
    session = DialogueSession(
        catalog,
        _knowledge(catalog, _belief_facts()),
        persona_id="red",
        pragmatics=DialoguePragmatics("shadow"),
    )
    answer = session.ask("Считает ли Империя Республику незаконной?")
    assert answer.data["pragmatics_backend"] == "shadow"
    assert answer.data["lied"] is True
    assert answer.text == "Нет, это не так."
