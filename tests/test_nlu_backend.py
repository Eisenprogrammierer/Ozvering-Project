"""Phase 4: живой NLU-бэкенд диалога.

Проверяют, что ``nlu_backend`` действительно подключён к ``respond()``:
``legacy`` сохраняет прежний разбор, ``shadow`` сравнивает RiveScript и
пишет расхождения, ``rive`` даёт те же ответы. Смысл кадра по-прежнему
строит legacy-адаптер — это первый шаг Phase 4, а не замена семантики.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition.corpus_builder import dialogue_variants
from campaign.cognition.errors import BackendError
from campaign.cognition.nlu_backend import NluBackend, load_nlu
from campaign.cognition.nlu_lint import collect_phrases
from campaign.dialogue import DialogueSession, build_knowledge, load_dialogue
from campaign.dialogue.loader import DEFAULT_DIR
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


@pytest.fixture(scope="module")
def catalog():
    return load_dialogue(DEFAULT_DIR)


@pytest.fixture(scope="module")
def knowledge(catalog):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    campaign = AutomataCampaign(generator.generate(seed=13), seed=13)
    return build_knowledge(catalog, campaign, "red")


@pytest.fixture(scope="module")
def phrases():
    return dialogue_variants(collect_phrases())


def _session(catalog, knowledge, mode):
    session = DialogueSession(catalog, knowledge, persona_id="red")
    session.nlu = load_nlu(session, backend=mode)
    return session


def test_backend_validates_mode(catalog, knowledge):
    session = _session(catalog, knowledge, "legacy")
    with pytest.raises(ValueError):
        NluBackend(session, backend="magic")


def test_legacy_backend_preserves_plain_interpret(
    catalog, knowledge, phrases
):
    session = _session(catalog, knowledge, "legacy")
    plain = DialogueSession(catalog, knowledge, persona_id="red")
    for _identifier, text in phrases[:24]:
        assert session._interpret(text) == plain._interpret(text)


def test_live_path_matches_legacy_on_corpus(
    catalog, knowledge, phrases
):
    def run(mode):
        session = _session(catalog, knowledge, mode)
        answers = []
        for _identifier, text in phrases:
            turn = session.respond(text)
            answers.append(
                (
                    turn.source,
                    turn.answer.plan_id,
                    turn.answer.kind,
                    turn.answer.text,
                )
            )
        return answers, session.nlu.report.to_dict()

    base, _report = run("legacy")
    for mode in ("shadow", "rive"):
        answers, report = run(mode)
        assert report["errors"] == 0
        assert report["ok"] is True
        assert report["mismatches"] == 0
        assert report["matched"] > 0
        assert answers == base


def test_rive_builds_frame_from_manifest_without_parser(
    catalog, knowledge
):
    pytest.importorskip("rivescript")
    from campaign.cognition.frame import UtteranceFrame
    from campaign.cognition.rive_runtime import RiveNlu

    session = _session(catalog, knowledge, "legacy")
    engine = RiveNlu(session)

    def boom(*_args, **_kwargs):
        raise AssertionError("ChartParser не должен участвовать")

    session.parser.parse_best = boom
    for text, prefix in (
        ("Привет.", "p:"),
        ("Считает ли Империя Абвер незаконным?", "g:"),
    ):
        result = engine.understand(text)
        assert isinstance(result, UtteranceFrame)
        assert engine.last_trigger.startswith(prefix)
        assert engine.counts["semantic_fallback"] == 0


def test_rive_grammar_stars_fill_roles(catalog, knowledge):
    pytest.importorskip("rivescript")
    from campaign.cognition.nlu import LegacyNlu
    from campaign.cognition.parity import result_core
    from campaign.cognition.rive_runtime import RiveNlu

    text = "Считает ли Империя Абвер незаконным?"
    session = _session(catalog, knowledge, "legacy")
    engine = RiveNlu(session)
    result = engine.understand(text)
    assert engine.last_trigger == "g:s_yesno_v_part_np_np_adj"
    assert engine.counts["semantic_fallback"] == 0
    legacy = LegacyNlu(session).understand(text)
    assert result_core(result) == result_core(legacy)


def test_rive_grammar_multword_stars_and_yo(catalog, knowledge):
    pytest.importorskip("rivescript")
    from campaign.cognition.nlu import LegacyNlu
    from campaign.cognition.parity import result_core
    from campaign.cognition.rive_runtime import RiveNlu

    text = "Если Империя воюет с Республикой то Республика ждёт"
    session = _session(catalog, knowledge, "legacy")
    engine = RiveNlu(session)
    result = engine.understand(text)
    assert engine.last_trigger == "g:s_conditional"
    assert engine.counts["semantic_fallback"] == 0
    legacy = LegacyNlu(session).understand(text)
    assert result_core(result) == result_core(legacy)


def test_rive_survives_foreign_nlu_subroutine(catalog, knowledge):
    pytest.importorskip("rivescript")
    from rivescript import RiveScript

    from campaign.cognition.rive_runtime import RiveNlu

    session = _session(catalog, knowledge, "legacy")
    engine = RiveNlu(session)
    # RiveScript 1.15 держит Python-объекты в общем словаре: чужой
    # движок может перетереть ``nlu`` и лишить захваты звёзд.
    foreign = RiveScript(utf8=True)
    foreign.set_subroutine("nlu", lambda rs, args: "broken")
    result = engine.understand("Считает ли Империя Абвер незаконным?")
    assert engine.last_trigger == "g:s_yesno_v_part_np_np_adj"
    assert engine.counts["semantic_fallback"] == 0
    assert result.intent == "ask_yesno"


def test_rive_semantic_fallback_keeps_legacy(
    monkeypatch, catalog, knowledge
):
    pytest.importorskip("rivescript")
    from campaign.cognition.nlu import LegacyNlu
    from campaign.cognition.parity import result_core
    from campaign.cognition.rive_runtime import RiveNlu

    text = "Привет."
    session = _session(catalog, knowledge, "legacy")
    engine = RiveNlu(session)

    def unresolved(*_args, **_kwargs):
        return None

    monkeypatch.setattr(engine, "_build_sem", unresolved)
    result = engine.understand(text)
    assert engine.counts["semantic_fallback"] == 1
    legacy = LegacyNlu(session).understand(text)
    assert result_core(result) == result_core(legacy)


def test_rive_counts_unknown_phrase_as_fallback(catalog, knowledge):
    session = _session(catalog, knowledge, "rive")
    session.respond("абракадабра зюзьга")
    report = session.nlu.report.to_dict()
    assert report["total"] >= 1
    assert report["fallback"] >= 1
    assert report["fallback_rate"] > 0.0


def test_rive_recovers_from_engine_error(monkeypatch, catalog, knowledge):
    pytest.importorskip("rivescript")
    session = _session(catalog, knowledge, "rive")
    rive = session.nlu._ensure_rive()

    def boom(*_args, **_kwargs):
        raise BackendError("движок упал")

    monkeypatch.setattr(rive, "understand", boom)
    turn = session.respond("Привет")
    assert turn.answer is not None
    report = session.nlu.report.to_dict()
    assert report["errors"] == 1
    assert "движок упал" in report["last_error"]
    assert report["backend"] == "rive"


def test_shadow_degrades_without_rive(monkeypatch, catalog, knowledge):
    session = _session(catalog, knowledge, "shadow")

    def missing(_self):
        raise BackendError("нет пакета rivescript")

    monkeypatch.setattr(NluBackend, "_ensure_rive", missing)
    turn = session.respond("Привет")
    assert turn.answer is not None
    report = session.nlu.report.to_dict()
    assert report["backend"] == "legacy"
    assert report["unavailable"] is True
    assert report["ok"] is False


def test_rive_refuses_without_package(monkeypatch, catalog, knowledge):
    session = _session(catalog, knowledge, "rive")

    def missing(_self):
        raise BackendError("нет пакета rivescript")

    monkeypatch.setattr(NluBackend, "_ensure_rive", missing)
    with pytest.raises(BackendError):
        session.respond("Привет")


def test_rive_clarifications_match_legacy(catalog, knowledge):
    """Уточнения и отказы на rive-пути не теряются и совпадают с legacy."""

    pytest.importorskip("rivescript")

    cases = (
        "",
        "А он?",
        "Почему?",
        "Обними его",
        "абракадабра ксизи",
    )

    def run(mode):
        session = _session(catalog, knowledge, mode)
        rows = []
        for text in cases:
            turn = session.respond(text)
            rows.append(
                (
                    turn.source,
                    turn.answer.kind,
                    turn.answer.plan_id,
                    turn.answer.text,
                )
            )
        return rows, session.nlu.report.to_dict()

    base, base_report = run("legacy")
    candidate, report = run("rive")
    assert candidate == base
    assert base_report["errors"] == 0
    assert report["errors"] == 0
    # Уточнение — это ответ по причине, а не «не понял» без следа.
    assert [row[0] for row in candidate[:3]] == [
        "empty",
        "no_referent",
        "no_qud",
    ]
    assert candidate[3][1:3] == ("clarification", "state:no_referent")
    assert candidate[4][1] == "unknown"


def test_rive_recovers_after_transient_engine_error(
    monkeypatch, catalog, knowledge
):
    """Первый сбой движка перезагружает RiveScript и не портит ход."""

    pytest.importorskip("rivescript")
    session = _session(catalog, knowledge, "rive")
    rive = session.nlu._ensure_rive()
    original = rive.understand
    calls = {"count": 0}

    def flaky(text, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise BackendError("временный сбой")
        return original(text, **kwargs)

    monkeypatch.setattr(rive, "understand", flaky)
    turn = session.respond("Привет")
    report = session.nlu.report.to_dict()
    assert turn.answer.kind == "smalltalk"
    assert calls["count"] == 2
    assert report["recoveries"] == 1
    assert report["errors"] == 0
    assert report["ok"] is True


def test_shadow_survives_transient_engine_error(
    monkeypatch, catalog, knowledge
):
    """Тень не выключается навсегда из-за одного временного сбоя."""

    pytest.importorskip("rivescript")
    session = _session(catalog, knowledge, "shadow")
    rive = session.nlu._ensure_rive()
    original = rive.understand
    calls = {"count": 0}

    def flaky(text, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise BackendError("временный сбой")
        return original(text, **kwargs)

    monkeypatch.setattr(rive, "understand", flaky)
    session.respond("Привет")
    report = session.nlu.report.to_dict()
    assert report["backend"] == "shadow"
    assert report["recoveries"] == 1
    assert report["errors"] == 0
    assert report["mismatches"] == 0


def test_rive_falls_back_after_unrecoverable_error(
    monkeypatch, catalog, knowledge
):
    """Если перезагрузка не помогла, ход строит legacy, а rive живёт дальше."""

    pytest.importorskip("rivescript")
    session = _session(catalog, knowledge, "rive")
    rive = session.nlu._ensure_rive()

    def boom(*_args, **_kwargs):
        raise BackendError("движок упал")

    monkeypatch.setattr(rive, "understand", boom)
    first = session.respond("Привет")
    assert first.answer is not None
    report = session.nlu.report.to_dict()
    assert report["errors"] == 1
    assert report["recoveries"] == 0
    assert report["backend"] == "rive"

    # Следующий ход снова идёт через rive: бэкенд не деградировал.
    monkeypatch.undo()
    second = session.respond("Привет")
    assert second.source == "parser"
    assert session.nlu.report.to_dict()["backend"] == "rive"


def test_low_confidence_is_clarification_on_both_paths(catalog, knowledge):
    """Неполный кадр доходит до диалога как уточнение, а не как ответ."""

    pytest.importorskip("rivescript")
    from campaign.cognition.backends import CognitionFlags
    from campaign.cognition.frame import Clarification
    from campaign.cognition.nlu import LegacyNlu
    from campaign.cognition.rive_runtime import RiveNlu

    flags = CognitionFlags(
        clarify_threshold=1.0,
        accept_threshold=1.0,
    )
    session = _session(catalog, knowledge, "legacy")

    legacy = LegacyNlu(session, flags)
    legacy_result = legacy.understand("Привет.")
    assert isinstance(legacy_result, Clarification)
    assert legacy_result.reason == "low_confidence"
    assert legacy.last_sem is None
    assert legacy.last_reason == "low_confidence"

    rive = RiveNlu(session, flags)
    rive_result = rive.understand("Привет.")
    assert isinstance(rive_result, Clarification)
    assert rive_result.reason == "low_confidence"
    assert rive.last_sem is None
    assert rive.last_reason == "low_confidence"

    live = NluBackend(session, flags=flags, backend="rive")
    session.nlu = live
    turn = session.respond("Привет.")
    assert turn.answer.kind == "clarification"
    assert turn.source == "low_confidence"
