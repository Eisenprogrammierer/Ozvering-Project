"""Выбор BDI-намерения: компилятор, Soar-рантайм и режимы.

Проверки держат два контракта: артефакт ``intention.soar`` совпадает с
JSON-источником, а Soar выбирает то же намерение, что легаси-цикл
``BDIState.choose_intention``. Теневой режим не меняет состояние и
пишет расхождения в монитор.
"""

from __future__ import annotations

import json

import pytest

import bdi
import character_traits as traits
from campaign.cognition import intention_runtime
from campaign.cognition.intention_compiler import (
    check_policy,
    load_model,
    render_policy,
)
from campaign.cognition.intention_runtime import (
    SoarIntention,
    shared_intention,
)


@pytest.fixture(scope="module")
def model():
    return traits.load_traits()


def _state(model, backend, needs=None, traits_value=None):
    return bdi.BDIState(
        character_id="actor-1",
        needs=needs or {},
        traits=traits_value or {},
        backend=backend,
    )


def test_compiler_artifact_is_fresh():
    compiled = load_model()
    text = render_policy(compiled)
    assert "source_digest" in text
    assert "intention*propose" in text
    assert "intention*apply" in text
    assert check_policy().digest() == compiled.digest()


def test_soar_matches_legacy_on_matrix(model):
    pytest.importorskip("soar_sml")
    contexts = [
        {},
        {"target": "fear"},
        {"preferred": "attack"},
        {"preferred": "retreat", "forbidden": ["attack"]},
        {"target": "faction", "preferred": "seek_order"},
    ]
    needsets = [
        {"hunger": 0.9},
        {"fear": 0.8},
        {"fatigue": 0.8},
        {"status": 0.8},
        {"loneliness": 0.9},
        {"knowledge": 0.9},
        {"health": 0.9, "wound": 1.0},
        {"boredom": 0.9},
    ]
    traitsets = [
        {},
        {"courage": 0.0, "discipline": 0.95, "empathy": 0.9},
        {"courage": 1.0, "aggression": 0.9, "fanaticism": 0.8},
    ]
    for needs in needsets:
        for trait_values in traitsets:
            for context in contexts:
                legacy = _state(model, "legacy", needs, trait_values)
                soar = _state(model, "soar", needs, trait_values)
                left = legacy.choose_intention(model, context)
                right = soar.choose_intention(model, context)
                assert right.as_dict() == left.as_dict(), (
                    needs,
                    trait_values,
                    context,
                )


def test_negative_belief_bonus_keeps_viable_candidates(model):
    pytest.importorskip("soar_sml")
    raw = json.loads(
        bdi.default_bdi_path().read_text(encoding="utf-8")
    )
    for essence, data in raw["intention_essences"].items():
        if data.get("need") == "hunger":
            data["belief_bonus"] = -1.0
    raw["intention_essences"]["drink"]["belief_bonus"] = 0.0
    config = bdi.BDIConfig(raw)
    needs = {"hunger": 0.9, "thirst": 0.8}
    legacy = bdi.BDIState(
        character_id="actor-1",
        config=config,
        needs=needs,
        backend="legacy",
    )
    soar = bdi.BDIState(
        character_id="actor-1",
        config=config,
        needs=needs,
        backend="soar",
    )
    left = legacy.choose_intention(model)
    right = soar.choose_intention(model)
    assert left.essence == "drink"
    assert right.as_dict() == left.as_dict()


def test_negative_score_falls_back_like_legacy(model):
    pytest.importorskip("soar_sml")
    raw = json.loads(
        bdi.default_bdi_path().read_text(encoding="utf-8")
    )
    for data in raw["intention_essences"].values():
        data["belief_bonus"] = -20.0
    config = bdi.BDIConfig(raw)
    contexts = [
        {},
        {"preferred": "eat"},
        {"preferred": "retreat", "forbidden": ["eat"]},
    ]
    for context in contexts:
        legacy = bdi.BDIState(
            character_id="actor-1",
            config=config,
            needs={"hunger": 0.9},
            backend="legacy",
        )
        soar = bdi.BDIState(
            character_id="actor-1",
            config=config,
            needs={"hunger": 0.9},
            backend="soar",
        )
        left = legacy.choose_intention(model, context)
        right = soar.choose_intention(model, context)
        assert right.as_dict() == left.as_dict(), context


def test_shadow_agrees_and_keeps_state(model):
    pytest.importorskip("soar_sml")
    needs = {"hunger": 0.9, "fear": 0.4}
    legacy = _state(model, "legacy", needs)
    shadow = _state(model, "shadow", needs)
    left = legacy.choose_intention(model, {"target": "hunger"})
    right = shadow.choose_intention(model, {"target": "hunger"})
    assert right.as_dict() == left.as_dict()
    assert shadow.intentions == legacy.intentions
    report = shadow.intention_monitor.report()
    assert report["queries"] == 1
    assert report["agreements"] == 1
    assert report["disagreements"] == 0
    assert report["ok"] is True


def test_forbidden_falls_back_like_legacy(model):
    pytest.importorskip("soar_sml")
    essences = list(bdi.load_bdi().essences)
    cases = [
        {"preferred": "retreat", "forbidden": essences},
        {
            "preferred": "retreat",
            "forbidden": [
                essence for essence in essences if essence != "retreat"
            ],
        },
    ]
    for context in cases:
        legacy = _state(model, "legacy")
        soar = _state(model, "soar")
        left = legacy.choose_intention(model, context)
        right = soar.choose_intention(model, context)
        assert right.as_dict() == left.as_dict()
        assert right.essence in bdi.load_bdi().essences


def test_soar_degrades_without_package(monkeypatch, model):
    monkeypatch.setattr(
        intention_runtime, "intention_available", lambda: False
    )
    state = _state(model, "soar", {"hunger": 0.9})
    intent = state.choose_intention(model, {"target": "hunger"})
    assert intent.essence == "eat"
    report = state.intention_monitor.report()
    assert report["unavailable"] is True
    assert report["ok"] is False


def test_unknown_backend_is_rejected(model):
    state = _state(model, "magic")
    with pytest.raises(bdi.BDIError):
        state.choose_intention(model)


def test_shared_selector_is_reused():
    assert shared_intention(17) is shared_intention(17)


def test_facade_exports_intention_api():
    from campaign import cognition

    assert cognition.SoarIntention is SoarIntention
    assert cognition.IntentionMonitor is not None
    assert callable(cognition.intention_available)
    assert cognition.load_intention_model().digest() == (
        load_model().digest()
    )
    assert cognition.check_intention().digest() == load_model().digest()


def test_empty_candidates_return_none():
    assert SoarIntention().choose([], {}) is None


def test_character_deliberates_with_soar_backend():
    pytest.importorskip("soar_sml")
    import warfare as W

    legacy = W.Character("actor", "red", seed=3, archetype="veteran")
    legacy.bdi.backend = "legacy"
    soar = W.Character("actor", "red", seed=3, archetype="veteran")
    soar.bdi.backend = "soar"
    left = legacy.deliberate()
    right = soar.deliberate()
    assert right.as_dict() == left.as_dict()
    assert soar.intentions == legacy.intentions
