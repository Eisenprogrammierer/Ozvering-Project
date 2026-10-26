"""Тесты системных автоматов: среда, драматург и события (без pygame)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

from interaction import ActionSpec, OutcomeSpec, Target
from systems.environment import (
    EnvironmentCatalog,
    EnvironmentInteraction,
    EnvironmentRuntime,
)
from systems.events import (
    EventCatalog,
    EventError,
    EventTextGenerator,
    GameEvent,
)
from systems.playwright import (
    DramaActor,
    DramaPush,
    DramaScore,
    DramaticAction,
    Playwright,
    PlaywrightConfig,
)


@pytest.fixture(scope="module")
def environment_catalog():
    return EnvironmentCatalog.load()


@pytest.fixture(scope="module")
def event_catalog():
    return EventCatalog.load()


@pytest.fixture(scope="module")
def playwright_config():
    return PlaywrightConfig.load()


def _actors():
    return [
        DramaActor("a", "Анна", "Орден", tags=("war", "ambition"), stakes=0.8),
        DramaActor("b", "Борис", "Гильдия", tags=("trade", "secret"),
                   stakes=0.6),
        DramaActor("c", "Вера", "Совет", tags=("power", "duty"), stakes=0.4),
    ]


# --------------------------------------------------------------------------
# Среда
# --------------------------------------------------------------------------

def test_environment_catalog_is_large_and_machine_driven(environment_catalog):
    assert len(environment_catalog.features) >= 12
    for feature_id in environment_catalog.feature_ids():
        feature = environment_catalog.feature(feature_id)
        assert len(feature.states) >= 3
        assert len(feature.transitions) >= 3
        assert len(feature.actions) >= 3
        assert feature.machine.state is not None
        assert feature.machine.automaton.states
        assert feature.machine.automaton.transitions


def test_environment_features_are_interaction_targets(environment_catalog):
    for feature_id in environment_catalog.feature_ids():
        target = environment_catalog.feature(feature_id).as_target()
        assert isinstance(target, Target)
        assert target.id == feature_id
        assert target.available is True
        for action in target.actions:
            assert isinstance(action, ActionSpec)
            assert action.enabled is True
            assert action.outcomes
            assert all(isinstance(item, OutcomeSpec) for item in action.outcomes)


def test_environment_drift_is_deterministic_with_fresh_catalogs():
    def run(seed):
        catalog = EnvironmentCatalog.load()
        runtime = EnvironmentRuntime([catalog.feature("storm")], seed=seed,
                                     drift_chance=1.0)
        states = [runtime.feature("storm").machine.current]
        shifts = []
        for _ in range(8):
            shifts.extend(runtime.tick())
            states.append(runtime.feature("storm").machine.current)
        return states, [item.as_dict() for item in shifts]

    first = run(7)
    second = run(7)
    assert first == second
    assert any(step != first[0][0] for step in first[0])


def test_environment_interaction_returns_effects_and_state_change():
    catalog = EnvironmentCatalog.load()
    runtime = EnvironmentRuntime(catalog, seed=1)
    feature = runtime.feature("river")
    before = feature.machine.current

    result = runtime.interact("actor-1", "river", "ford", seed=3)
    assert isinstance(result, EnvironmentInteraction)
    assert result.actor_id == "actor-1"
    assert result.feature_id == "river"
    assert result.action_id == "ford"
    assert result.outcome_id
    assert result.effects
    assert result.state_before == before
    assert result.state_after == feature.machine.current
    assert runtime.history == [result]

    catalog = EnvironmentCatalog.load()
    runtime = EnvironmentRuntime(catalog, seed=1)
    feature = runtime.feature("river")
    built = None
    for seed in range(40):
        catalog = EnvironmentCatalog.load()
        runtime = EnvironmentRuntime(catalog, seed=1)
        feature = runtime.feature("river")
        built = runtime.interact("actor-1", "river", "build_bridge",
                                 seed=seed)
        if built is not None and built.outcome_id == "built":
            break
    assert built is not None
    assert built.outcome_id == "built"
    assert built.state_before == "calm"
    assert built.state_after == "bridged"
    assert feature.machine.current == "bridged"


def test_environment_unavailable_action_returns_none():
    catalog = EnvironmentCatalog.load()
    runtime = EnvironmentRuntime(catalog, seed=1)
    runtime.feature("river").machine.set_state("flood")
    assert runtime.interact("actor", "river", "ford", seed=1) is None


# --------------------------------------------------------------------------
# Драматург
# --------------------------------------------------------------------------

def test_playwright_config_has_normalized_weights_and_templates(
        playwright_config):
    assert playwright_config.weights
    assert sum(playwright_config.weights.values()) == pytest.approx(1.0)
    assert len(playwright_config.templates) >= 15
    assert 0.0 <= playwright_config.episode_chance <= 1.0
    assert playwright_config.cooldown >= 0
    assert playwright_config.temperature > 0


def test_drama_score_is_monotonic_by_components(playwright_config):
    playwright = Playwright(playwright_config, seed=3)
    low = DramaticAction(
        "low", "a", "b", "низкий", tags=("talk",),
        uncertainty=0.1, coherence=0.1, novelty=0.1, stakes=0.1)
    high = DramaticAction(
        "high", "a", "b", "высокий", tags=("war",),
        uncertainty=0.9, coherence=0.9, novelty=0.9, stakes=0.9)
    low_score = playwright.score(low)
    high_score = playwright.score(high)
    assert high_score.total > low_score.total
    assert high_score.uncertainty > low_score.uncertainty
    assert high_score.coherence > low_score.coherence
    assert high_score.novelty > low_score.novelty
    assert high_score.stakes > low_score.stakes


def test_novelty_decays_after_a_repeated_push(playwright_config):
    playwright = Playwright(playwright_config, seed=3)
    candidate = DramaticAction(
        "repeat", "a", "b", "повтор", tags=("war", "risk"),
        uncertainty=0.7, coherence=0.7, novelty=0.9, stakes=0.8)
    before = playwright.score(candidate)
    score = playwright.score(candidate)
    playwright.history.append((candidate, score))
    after = playwright.score(candidate)
    assert after.novelty < before.novelty
    assert after.total < before.total


def test_playwright_seeded_sequence_is_deterministic(playwright_config):
    def run(seed):
        playwright = Playwright(playwright_config, seed=seed)
        actors = _actors()
        candidates = playwright.spawn_candidates(actors)
        pushes = []
        for turn in range(20):
            push = playwright.tick(turn, actors, candidates)
            if push is not None:
                pushes.append((
                    turn,
                    push.candidate.id,
                    round(push.score.total, 6),
                    push.state_after,
                ))
        return pushes, playwright.machine.current, playwright.cooldown

    first = run(7)
    second = run(7)
    assert first == second
    assert first[0]
    assert len(first[0]) < 20


def test_playwright_respects_episode_cooldown(playwright_config):
    playwright = Playwright(playwright_config, seed=7)
    actors = _actors()
    candidates = playwright.spawn_candidates(actors)
    turns = []
    for turn in range(30):
        push = playwright.tick(turn, actors, candidates)
        if push is not None:
            turns.append(turn)
    assert turns
    assert all(
        later - earlier >= playwright_config.cooldown + 1
        for earlier, later in zip(turns, turns[1:])
    )
    assert playwright.machine.current in (
        "dormant", "watching", "tempting", "pushing", "withdrawing")


def test_playwright_event_generation_uses_context_and_names(
        playwright_config, event_catalog):
    events = EventTextGenerator(event_catalog, seed=7)
    playwright = Playwright(playwright_config, seed=7,
                            event_generator=events)
    actors = _actors()
    candidates = playwright.spawn_candidates(actors)
    push = None
    for turn in range(20):
        push = playwright.tick(turn, actors, candidates)
        if push is not None:
            break
    assert isinstance(push, DramaPush)
    assert isinstance(push.event, GameEvent)
    assert push.event.text
    assert "{" not in push.event.text
    assert push.text == push.event.text


# --------------------------------------------------------------------------
# События
# --------------------------------------------------------------------------

def test_event_catalog_is_large_and_every_template_uses_names(event_catalog):
    assert len(event_catalog.events) >= 80
    assert len(event_catalog.categories) >= 10
    name_slots = {"actor", "target", "child", "organization",
                  "rival_organization"}
    for event in event_catalog.events.values():
        assert event.templates
        for template in event.templates:
            assert "{" in template
            assert set(_slots(template)) & name_slots


def _slots(template):
    import re
    return re.findall(r"\{([a-z][a-z0-9_]*)\}", template)


def test_event_generator_fills_explicit_context_deterministically(
        event_catalog):
    events = EventTextGenerator(event_catalog, seed=7)
    context = {
        "actor": "Анна",
        "target": "Борис",
        "organization": "Орден",
    }
    first = events.render("marriage", context=context, seed=11)
    second = events.render("marriage", context=context, seed=11)
    assert isinstance(first, GameEvent)
    assert first.text == second.text
    assert "Анна" in first.text
    assert "Орден" in first.text
    assert "{" not in first.text


def test_event_generator_auto_fills_names_and_handles_random_choice(
        event_catalog):
    events = EventTextGenerator(event_catalog, seed=7)
    for seed in range(12):
        item = events.generate(category="war", seed=seed)
        assert isinstance(item, GameEvent)
        assert item.category == "war"
        assert item.text
        assert "{" not in item.text
    items = events.generate_many(count=6, seed=3)
    assert len(items) == 6
    assert all(item.text for item in items)


def test_unknown_event_is_rejected(event_catalog):
    with pytest.raises(EventError):
        event_catalog.event("not_an_event")


# --------------------------------------------------------------------------
# Чистота слоя и CLI
# --------------------------------------------------------------------------

def test_systems_layer_does_not_import_pygame():
    code = (
        "import sys; import systems; "
        "assert 'pygame' not in sys.modules, sorted(sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_systems_cli_covers_environment_events_and_playwright():
    root = str(Path(__file__).resolve().parents[1])
    commands = [
        [sys.executable, "-m", "systems", "--list"],
        [sys.executable, "-m", "systems", "--environment", "river",
         "--interact", "ford", "--seed", "7"],
        [sys.executable, "-m", "systems", "--event", "birth_child",
         "--seed", "7"],
        [sys.executable, "-m", "systems", "--playwright", "--turns", "12",
         "--seed", "7"],
    ]
    for command in commands:
        result = subprocess.run(
            command, cwd=root, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip()
