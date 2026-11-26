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


def test_rive_counts_unknown_phrase_as_fallback(catalog, knowledge):
    session = _session(catalog, knowledge, "rive")
    session.respond("абракадабра зюзьга")
    report = session.nlu.report.to_dict()
    assert report["total"] >= 1
    assert report["fallback"] >= 1
    assert report["fallback_rate"] > 0.0


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
