"""Тесты аналитического слоя организаций и генератора автоматов (без pygame)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from automata.model import Automaton
from automata.storage import AutomataStore
from organizations.examples import (
    fear_state,
    get_scenarios,
    spirituality_church,
    status_gang,
    subsistence_artel,
)
from organizations.generator import build_automaton, save_automaton
from organizations.model import (
    Member,
    OrganizationParameters,
    OrganizationSolver,
    Population,
    level_capacity,
    organization_level,
)
from organizations.needs import MODE_ORDER, NEEDS, NEEDS_RU


def _member(member_id, needs, force=1.0, energy=1.0):
    return Member(member_id, needs=needs, force=force, energy=energy)


def _population(needs, count, complete_weight=1.0, force=1.0):
    return Population.complete(
        [_member("m%d" % index, needs, force=force)
         for index in range(count)],
        weight=complete_weight,
    )


# --------------------------------------------------------------------------
# Канон потребностей и профили
# --------------------------------------------------------------------------

def test_need_order_and_names_match_warfare():
    import warfare

    assert NEEDS == warfare.NEEDS
    assert NEEDS_RU == warfare.NEEDS_RU
    assert len(NEEDS) == 16
    assert set(MODE_ORDER) == {
        "order", "meaning", "provision", "status",
        "knowledge", "care", "exchange",
    }


def test_member_normalizes_needs_and_urgency():
    member = Member("x", needs={"fear": 2.0, "hunger": -1.0})
    assert member.needs["fear"] == 1.0
    assert member.needs["hunger"] == 0.0
    assert member.needs["status"] == 0.0
    assert member.urgency["fear"] == 1.0
    assert member.urgency["hunger"] == 0.0


def test_member_from_character_uses_bdi_and_metrics():
    import warfare

    character = warfare.Character("бойец", "red", seed=3)
    character.needs["fear"] = 0.73
    character.force = 7.0
    character.energy_pool = 4.0
    member = Member.from_character(character)

    assert member.id == "бойец"
    assert member.needs["fear"] == pytest.approx(0.73)
    assert member.urgency["fear"] == pytest.approx(
        character.weighted_urgency()["fear"])
    assert member.energy == pytest.approx(4.0)
    assert member.force == pytest.approx(7.0)


# --------------------------------------------------------------------------
# Плотность, масштаб и уровни
# --------------------------------------------------------------------------

def test_weighted_density_centrality_and_mean_energy():
    population = Population(
        members=[
            _member("a", {"fear": 0.9}, energy=1.0),
            _member("b", {"fear": 0.9}, energy=3.0),
            _member("c", {"fear": 0.9}, energy=2.0),
        ],
        links=[("a", "b", 1.0), ("b", "c", 0.5)],
    )
    # 1.5 / 3 возможные пары = 0.5
    assert population.density() == pytest.approx(0.5)
    assert population.mean_energy() == pytest.approx(2.0)
    centrality = population.centrality()
    assert centrality["b"] == pytest.approx(1.0)
    assert centrality["a"] == pytest.approx(2.0 / 3.0)
    assert centrality["c"] == pytest.approx(1.0 / 3.0)
    assert population.density(["a", "b"]) == pytest.approx(1.0)


def test_complete_population_does_not_materialize_edges():
    population = Population.complete(
        [_member("a", {"fear": 0.9}), _member("b", {"fear": 0.9}),
         _member("c", {"fear": 0.9})],
        weight=0.8,
    )
    assert population.links == []
    assert population.density() == pytest.approx(0.8)
    assert population.strengths() == pytest.approx(
        {"a": 1.6, "b": 1.6, "c": 1.6})


def test_level_thresholds_and_capacity():
    assert organization_level(0) == 0
    assert organization_level(1) == 1
    assert organization_level(165) == 1
    assert organization_level(165.1) == 2
    assert organization_level(660) == 2
    assert organization_level(660.1) == 3
    assert level_capacity(0) == pytest.approx(0)
    assert level_capacity(1) == pytest.approx(165)
    assert level_capacity(2) == pytest.approx(660)
    assert level_capacity(3) == pytest.approx(1485)


def test_scale_uses_density_and_energy():
    population = Population.complete(
        [_member("a", {"fear": 0.9}, energy=1.0),
         _member("b", {"fear": 0.9}, energy=3.0)],
        weight=0.5,
    )
    analysis = OrganizationSolver().analyze(population)
    assert analysis.density == pytest.approx(0.5)
    assert analysis.effective_count == pytest.approx(1.0)
    assert analysis.mean_energy == pytest.approx(2.0)
    assert analysis.scale == pytest.approx(2.0)
    assert analysis.level == 1


# --------------------------------------------------------------------------
# Приоритетная потребность: смесь лидера и массы
# --------------------------------------------------------------------------

def test_priority_need_is_a_mix_of_mass_and_leader():
    members = [
        _member("m%d" % index, {"fear": 0.9}, force=1.0)
        for index in range(9)
    ]
    members.append(_member("leader", {"spirituality": 0.9}, force=20.0))
    population = Population.complete(members, weight=1.0)

    mass_only = OrganizationSolver(
        OrganizationParameters(leader_priority_weight=0.0)
    ).analyze(population)
    leader_only = OrganizationSolver(
        OrganizationParameters(leader_priority_weight=1.0)
    ).analyze(population)
    mixed = OrganizationSolver(
        OrganizationParameters(leader_priority_weight=0.35)
    ).analyze(population)
    leader_dominant = OrganizationSolver(
        OrganizationParameters(leader_priority_weight=0.8)
    ).analyze(population)

    assert mass_only.priority_need == "fear"
    assert leader_only.priority_need == "spirituality"
    assert mixed.priority_need == "fear"
    assert 0.0 < mixed.priority_weights["spirituality"] < 1.0
    assert leader_dominant.priority_need == "spirituality"


# --------------------------------------------------------------------------
# Экономика участия
# --------------------------------------------------------------------------

def test_unwilling_members_leave_and_willing_members_stay():
    population = Population.complete([
        _member("high", {"fear": 0.9}),
        _member("zero", {}),
    ], weight=0.9)
    analysis = OrganizationSolver().analyze(population)
    assert analysis.dissolved is False
    assert analysis.active_ids == ["high"]
    assert analysis.active_count == 1
    assert analysis.willing_share == pytest.approx(0.5)
    assert all(item.willing for item in analysis.assessments)
    assert analysis.leader_willing is True


def test_organization_dissolves_without_willing_members():
    population = Population.complete([
        _member("a", {}), _member("b", {}),
    ], weight=1.0)
    analysis = OrganizationSolver().analyze(population)
    assert analysis.dissolved is True
    assert analysis.active_count == 0
    assert analysis.willing_count == 0
    assert analysis.level == 0
    assert analysis.archetype == "распущена"
    assert analysis.priority_need is None
    assert analysis.leader_willing is False


def test_dissolution_when_need_is_too_weak_to_pay_contribution():
    population = Population.complete([
        _member("a", {"fear": 0.01}), _member("b", {"fear": 0.01}),
    ], weight=1.0)
    analysis = OrganizationSolver().analyze(population)
    assert analysis.priority_need == "fear"
    assert analysis.dissolved is True
    assert analysis.active_count == 0


# --------------------------------------------------------------------------
# Функции, ярлыки и масштаб
# --------------------------------------------------------------------------

def test_four_examples_produce_four_derived_labels():
    state = OrganizationSolver().analyze(fear_state().population)
    church = OrganizationSolver().analyze(spirituality_church().population)
    gang = OrganizationSolver().analyze(status_gang().population)
    artel = OrganizationSolver().analyze(subsistence_artel().population)

    assert (state.priority_need, state.archetype, state.level) == (
        "fear", "государство", 3)
    assert (church.priority_need, church.archetype, church.level) == (
        "spirituality", "церковная иерархия", 3)
    assert (gang.priority_need, gang.archetype, gang.level) == (
        "status", "банда", 1)
    assert (artel.priority_need, artel.archetype, artel.level) == (
        "hunger", "торговая артель", 1)

    for analysis in (state, church, gang, artel):
        assert analysis.dissolved is False
        assert analysis.active_count > 0
        assert analysis.active_count < analysis.initial_count
        assert analysis.top_mode in MODE_ORDER
        assert analysis.mode_weights[analysis.top_mode] > 0.0
        assert analysis.goods
        assert analysis.contribution
        assert analysis.coercion
        assert analysis.legitimation
        assert analysis.reproduction


def test_same_need_changes_label_with_scale():
    small = Population.complete(
        [_member("leader", {"spirituality": 1.0}, force=10.0)] + [
            _member("m%d" % index, {"spirituality": 0.9,
                                    "loneliness": 0.4})
            for index in range(29)
        ],
        weight=0.8,
    )
    small_analysis = OrganizationSolver().analyze(small)
    large_analysis = OrganizationSolver().analyze(
        spirituality_church().population)

    assert small_analysis.priority_need == "spirituality"
    assert small_analysis.archetype == "секта"
    assert small_analysis.level == 1
    assert large_analysis.archetype == "церковная иерархия"
    assert large_analysis.level == 3


# --------------------------------------------------------------------------
# Генерация автоматов
# --------------------------------------------------------------------------

def test_active_automaton_is_valid_and_reachable():
    for scenario in get_scenarios():
        analysis = OrganizationSolver().analyze(scenario.population)
        automaton = build_automaton(analysis)

        assert automaton.name
        assert automaton.name != "%s — %s" % (
            analysis.archetype[:1].upper() + analysis.archetype[1:],
            analysis.need_ru)
        assert automaton.name == build_automaton(analysis).name
        assert automaton.validate() == []
        assert len(automaton.initial_states) == 1
        assert automaton.final_states
        assert automaton.reachable_ids() == {state.id for state in
                                             automaton.states}
        payload = automaton.to_dict()
        assert payload["version"] == 1
        restored = Automaton.from_dict(
            json.loads(json.dumps(payload, ensure_ascii=False)))
        assert restored.to_dict() == payload
        assert "Потребность:" in automaton.states[0].name
        assert any("Производство:" in state.name
                   for state in automaton.states)
        assert any("Принуждение:" in state.name
                   for state in automaton.states)
        assert any("Легитимация:" in state.name
                   for state in automaton.states)


def test_dissolved_automaton_is_minimal_and_valid():
    population = Population.complete([
        _member("a", {}), _member("b", {}),
    ], weight=1.0)
    analysis = OrganizationSolver().analyze(population)
    automaton = build_automaton(analysis)

    assert automaton.counts() == (2, 1)
    assert automaton.name == "Распущена — не определена"
    assert automaton.validate() == []
    assert automaton.initial_states[0].name == "Потребность: не определена"
    assert automaton.final_states[0].name == "Распад: нет желающих"


def test_analysis_is_json_serializable():
    analysis = OrganizationSolver().analyze(fear_state().population)
    payload = analysis.to_dict()
    text = json.dumps(payload, ensure_ascii=False)
    assert "государство" in text
    assert payload["assessments"]


def test_save_automaton_and_cli_write(tmp_path):
    analysis = OrganizationSolver().analyze(status_gang().population)
    store = AutomataStore(tmp_path)
    slug = save_automaton(analysis, store, "test_gang")
    assert slug == "test_gang"
    assert store.load(slug).name == build_automaton(analysis).name
    assert not store.load(slug).name.startswith("Банда")

    from organizations.__main__ import main

    assert main(["--write", "--out", str(tmp_path / "generated")]) == 0
    generated = AutomataStore(tmp_path / "generated")
    slugs = {entry["slug"] for entry in generated.list_entries()}
    assert slugs == {
        "state_fear", "church_spirituality",
        "gang_status", "trade_artel_hunger",
    }
    for slug in slugs:
        assert generated.load(slug).validate() == []


def test_organizations_do_not_import_pygame():
    code = (
        "import sys; import organizations; "
        "assert 'pygame' not in sys.modules, sorted(sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_natural_name_can_be_overridden_by_name_and_seed():
    analysis = OrganizationSolver().analyze(fear_state().population)

    explicit = build_automaton(analysis, name="Свой разбор")
    assert explicit.name == "Свой разбор"

    first = build_automaton(analysis, seed=7)
    second = build_automaton(analysis, seed=7)
    assert first.name == second.name

    names = {build_automaton(analysis, seed=seed).name for seed in range(12)}
    assert len(names) > 1


def test_cli_name_seed_is_reproducible(capsys):
    from organizations.__main__ import main

    assert main(["--scenario", "gang_status", "--json", "--name-seed",
                 "7"]) == 0
    first = capsys.readouterr().out
    assert main(["--scenario", "gang_status", "--json", "--name-seed",
                 "7"]) == 0
    second = capsys.readouterr().out
    assert first == second
    payload = json.loads(first)
    assert payload["name"]


# --------------------------------------------------------------------------
# Валидация данных
# --------------------------------------------------------------------------

def test_population_rejects_bad_graph_data():
    member = _member("a", {"fear": 0.9})
    with pytest.raises(ValueError):
        Population(members=[member, member])
    with pytest.raises(ValueError):
        Population(members=[member], links=[("a", "missing", 1.0)])
    with pytest.raises(ValueError):
        Population(members=[member], links=[("a", "a", 1.0)])
    with pytest.raises(ValueError):
        Population(members=[member], links=[("a", "a", 1.0)],
                   complete_weight=1.0)
