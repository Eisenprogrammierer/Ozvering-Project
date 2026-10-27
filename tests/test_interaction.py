import pathlib
import subprocess
import sys

import pytest

from interaction import (
    ActionSpec,
    InteractionModel,
    OutcomeSpec,
    Target,
    demo_model,
    demo_targets,
)


def test_demo_content_is_domain_neutral_and_has_three_layers():
    targets = demo_targets()
    assert len(targets) == 3
    assert all(target.label and target.actions for target in targets)
    assert {target.id for target in targets} == {"alpha", "beta", "gamma"}

    model = demo_model(seed=3)
    model.select_target("alpha")
    assert [a.id for a in model.actions_for()] == ["talk", "offer", "press"]
    model.select_action("press")
    forecasts = model.forecasts()
    assert forecasts
    assert any(not item.known for item in forecasts)


def test_selection_reveals_actions_and_resets_downstream_state():
    model = demo_model(seed=1)
    assert model.actions_for() == []
    assert model.forecasts() == []

    assert model.select_target("alpha") is True
    assert model.selected_target_id == "alpha"
    assert [a.id for a in model.actions_for()] == ["talk", "offer", "press"]
    assert model.selected_action_id is None

    assert model.select_action("offer") is True
    assert model.selected_action_id == "offer"
    assert model.forecasts()

    assert model.select_target("beta") is True
    assert model.selected_action_id is None
    assert model.last_result is None
    assert model.forecasts() == []
    assert [a.id for a in model.actions_for()] == ["talk", "observe"]


def test_invalid_selections_are_rejected():
    model = demo_model(seed=2)
    assert model.select_target("missing") is False
    assert model.select_action("talk") is False
    assert model.resolve() is None

    assert model.select_target("alpha") is True
    assert model.select_action("observe") is False
    assert model.resolve() is None

    unavailable = Target("locked", "Недоступный", available=False)
    model2 = InteractionModel([unavailable])
    assert model2.select_target("locked") is False


def test_forecasts_are_stable_noisy_and_explain_uncertainty():
    model = demo_model(seed=11)
    model.select_target("alpha")
    model.select_action("press")
    first = model.forecasts()
    second = model.forecasts()
    assert first == second

    for item in first:
        assert 0.0 <= item.confidence <= 1.0
        if item.known:
            assert item.low is not None and item.high is not None
            assert 0.0 <= item.low <= item.high <= 1.0
            assert "%" in item.probability_text
        else:
            assert item.probability_text == "вероятность неизвестна"
            assert item.short_label == "Неизвестный исход"

    hidden = [item for item in first if item.hidden]
    assert hidden
    assert all(not item.known for item in hidden)

    assert all(item.label == "Неизвестный исход" for item in hidden)

    assert any(item.unknown for item in first)


def test_resolution_is_deterministic_by_seed_and_updates_history():
    def play(seed):
        model = demo_model(seed=seed)
        model.select_target("alpha")
        model.select_action("press")
        return [model.resolve() for _ in range(12)], model

    first, model_a = play(21)
    second, model_b = play(21)
    assert first == second
    assert model_a.history == model_b.history
    assert len(first) == 12
    assert all(item.target_id == "alpha" for item in first)
    assert all(item.action_id == "press" for item in first)
    assert all(item.label for item in first)
    assert model_a.last_result == first[-1]


def test_unknown_share_always_can_produce_unknown_result():
    action = ActionSpec(
        "void",
        "Неизвестное действие",
        outcomes=(OutcomeSpec("known", "Известный исход", probability=1.0),),
        unknown_share=1.0,
        unknown_description="Совсем неизвестно.",
    )
    model = InteractionModel(
        [Target("t", "Объект", actions=(action,))], seed=0
    )
    model.select_target("t")
    model.select_action("void")
    forecasts = model.forecasts()
    assert any(item.unknown for item in forecasts)
    result = model.resolve()
    assert result is not None
    assert result.unknown is True
    assert result.outcome_id is None


def test_action_without_outcomes_returns_neutral_result():
    action = ActionSpec("idle", "Ничего не делать")
    model = InteractionModel(
        [Target("t", "Объект", actions=(action,))], seed=0
    )
    model.select_target("t")
    model.select_action("idle")
    result = model.resolve()
    assert result is not None
    assert result.label == "Нет наблюдаемого эффекта"
    assert result.outcome_id is None


def test_resolve_explicit_target_uses_that_targets_action():
    model = demo_model(seed=8)
    model.select_target("beta")
    result = model.resolve("alpha", "talk")
    assert result is not None
    assert result.target_id == "alpha"
    assert result.action_id == "talk"


def test_reset_restores_seed_and_clears_history():
    model = demo_model(seed=4)
    model.select_target("alpha")
    model.select_action("talk")
    model.resolve()
    assert model.history

    model.reset()
    assert model.selected_target_id is None
    assert model.selected_action_id is None
    assert model.last_result is None
    assert model.history == []
    assert model.forecasts() == []


def test_snapshot_contains_selection_and_history():
    model = demo_model(seed=5)
    model.select_target("gamma")
    model.select_action("observe")
    model.resolve()
    snap = model.snapshot()
    assert snap["seed"] == 5
    assert snap["selected_target"] == "gamma"
    assert snap["selected_action"] == "observe"
    assert snap["last_result"]["target_id"] == "gamma"
    assert len(snap["history"]) == 1


def test_duplicate_or_empty_specs_are_validated():
    with pytest.raises(ValueError):
        OutcomeSpec("", "пусто")
    with pytest.raises(ValueError):
        ActionSpec("", "пусто")
    with pytest.raises(ValueError):
        Target("", "пусто")


def test_interaction_package_is_pygame_free():
    root = pathlib.Path(__file__).resolve().parents[1]
    code = (
        "import sys, interaction; "
        "sys.exit(1 if 'pygame' in sys.modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=root, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
