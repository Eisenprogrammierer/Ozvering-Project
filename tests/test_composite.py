"""Тесты составных автоматов (WORLD_CORE_MODEL §2.7, §7.1 №7–8)."""

import json

import pytest

from core41 import (
    DEFAULT_DISTRIBUTION_STRATEGY,
    DISTRIBUTION_STRATEGIES,
    MAX_COMPOSITE_DEPTH,
    Automaton,
    CompositeAutomaton,
    Work,
    automaton_state,
    load_automaton_state,
)


def _unit(node_id, **kwargs):
    kwargs.setdefault("max_energy", 1000.0)
    kwargs.setdefault("energy", 0.0)
    return Automaton(id=node_id, **kwargs)


def test_child_validation_rejects_duplicates_self_cycles_and_depth():
    root = CompositeAutomaton(id="root")
    child = _unit("child")
    root.add_child(child)
    assert root.children["child"] is child

    with pytest.raises(ValueError):
        root.add_child(Automaton(id="child"))
    with pytest.raises(ValueError):
        root.add_child(root)
    with pytest.raises(TypeError):
        root.add_child(object())
    with pytest.raises(ValueError):
        root.add_child(Automaton(id=""))

    with pytest.raises(ValueError):
        child_comp = CompositeAutomaton(id="child_comp")
        root.add_child(child_comp)
        child_comp.add_child(root)

    other = CompositeAutomaton(id="other")
    other.add_child(child)
    assert "child" not in root.children
    assert other.children["child"] is child


def test_depth_limit_is_enforced_for_nested_composites():
    root = CompositeAutomaton(id="root", max_depth=2)
    level1 = CompositeAutomaton(id="level1")
    level2 = CompositeAutomaton(id="level2")
    level3 = CompositeAutomaton(id="level3")
    root.add_child(level1)
    level1.add_child(level2)
    with pytest.raises(ValueError):
        level2.add_child(level3)
    assert MAX_COMPOSITE_DEPTH >= 2


def test_aggregate_capacity_is_additive_and_ratios_are_weighted():
    root = CompositeAutomaton(
        id="root",
        force=80.0,
        max_force=100.0,
        energy=40.0,
        max_energy=100.0,
        health=50.0,
    )
    a = Automaton(
        id="a",
        force=40.0,
        max_force=100.0,
        energy=100.0,
        max_energy=100.0,
        health=100.0,
    )
    inner = CompositeAutomaton(
        id="inner",
        force=20.0,
        max_force=50.0,
        energy=10.0,
        max_energy=50.0,
        health=0.0,
    )
    b = Automaton(
        id="b",
        force=10.0,
        max_force=50.0,
        energy=0.0,
        max_energy=50.0,
        health=100.0,
    )
    inner.add_child(b)
    root.add_child(a)
    root.add_child(inner)

    state = root.aggregate_state()
    assert state["force"] == pytest.approx(150.0)
    assert state["max_force"] == pytest.approx(300.0)
    assert state["force_ratio"] == pytest.approx(0.5)
    assert state["energy"] == pytest.approx(150.0)
    assert state["max_energy"] == pytest.approx(300.0)
    assert state["energy_ratio"] == pytest.approx(0.5)
    assert state["health_ratio"] == pytest.approx(2.0 / 3.0)
    assert state["health"] == pytest.approx(200.0 / 3.0)
    assert state["parts"] == 4
    assert state["leaves"] == 2
    assert state["height"] == 2
    assert state["alive"] is True


def test_worst_condition_and_aliveness_follow_the_whole_tree():
    root = CompositeAutomaton(id="root", force=0.0, health=0.0)
    a = Automaton(id="a", health=100.0)
    b = Automaton(id="b", health=100.0, sickness=0.4, wound=0.6)
    root.add_child(a)
    root.add_child(b)
    assert root.worst_sickness == pytest.approx(0.4)
    assert root.worst_wound == pytest.approx(0.6)
    assert root.is_sick is True
    assert root.is_wounded is True
    assert root.is_dead is False

    a.health = 0.0
    b.health = 0.0
    assert root.is_dead is True
    assert root.aggregate_state()["alive"] is False


def test_proportional_distribution_conserves_work_and_uses_capacity():
    root = CompositeAutomaton(id="root")
    a = _unit("a", max_force=100.0)
    b = _unit("b", max_force=300.0)
    root.add_child(a)
    root.add_child(b)

    report = root.distribute(Work(amount=8.0, form="info"))
    assert report["accepted"] is True
    assert report["strategy"] == DEFAULT_DISTRIBUTION_STRATEGY
    assert report["shares"]["a"]["amount"] == pytest.approx(2.0)
    assert report["shares"]["b"]["amount"] == pytest.approx(6.0)
    assert report["stored"] == pytest.approx(2.1)
    assert report["loss"] == pytest.approx(2.0)
    assert report["entropy"] == pytest.approx(3.9)
    assert (
        report["stored"] + report["loss"] + report["entropy"]
        == pytest.approx(8.0)
    )
    assert report["efficiency"] == pytest.approx(0.75)


def test_even_and_single_target_strategies():
    root = CompositeAutomaton(id="root")
    a = _unit("a", max_force=100.0, force=20.0)
    b = _unit("b", max_force=100.0, force=80.0)
    root.add_child(a)
    root.add_child(b)

    even = root.distribute(Work(amount=10.0, form="info"), strategy="even")
    assert even["shares"]["a"]["amount"] == pytest.approx(5.0)
    assert even["shares"]["b"]["amount"] == pytest.approx(5.0)

    weakest = root.distribute(
        Work(amount=10.0, form="info"), strategy="weakest"
    )
    assert set(weakest["shares"]) == {"a"}
    strongest = root.distribute(
        Work(amount=10.0, form="info"), strategy="strongest"
    )
    assert set(strongest["shares"]) == {"b"}


def test_round_robin_cycles_through_targets_deterministically():
    root = CompositeAutomaton(id="root")
    for node_id in ("a", "b", "c"):
        root.add_child(_unit(node_id))
    picks = [
        next(iter(root.distribute(
            Work(amount=3.0, form="info"), strategy="round_robin"
        )["shares"]))
        for _ in range(4)
    ]
    assert picks == ["a", "b", "c", "a"]


def test_nested_distribution_reaches_leaves_without_duplicating_work():
    root = CompositeAutomaton(id="root")
    inner = CompositeAutomaton(id="inner")
    a = _unit("a")
    b = _unit("b")
    inner.add_child(a)
    inner.add_child(b)
    root.add_child(inner)

    report = root.distribute(Work(amount=10.0, form="info"), strategy="even")
    assert set(report["shares"]) == {"a", "b"}
    assert report["shares"]["a"]["amount"] == pytest.approx(5.0)
    assert report["shares"]["b"]["amount"] == pytest.approx(5.0)
    assert (
        report["stored"] + report["loss"] + report["entropy"]
        == pytest.approx(10.0)
    )


def test_no_eligible_child_is_accounted_as_pure_loss():
    root = CompositeAutomaton(id="root", inputs=("force",))
    root.add_child(_unit("a", inputs=("force",)))
    report = root.distribute(Work(amount=4.0, form="info"))
    assert report["accepted"] is False
    assert report["stored"] == 0.0
    assert report["entropy"] == 0.0
    assert report["loss"] == pytest.approx(4.0)

    received = root.receive(Work(amount=4.0, form="info"))
    assert received["accepted"] is False
    assert received["loss"] == pytest.approx(4.0)


def test_receive_prefers_shell_handler_then_children_then_shell():
    calls = []
    root = CompositeAutomaton(id="root")
    a = _unit("a")

    def child_handler(target, work, source, world):
        calls.append(("child", work.amount))
        return {"accepted": True, "custom": "child"}

    a.set_handler("info", child_handler)
    root.add_child(a)
    report = root.receive(Work(amount=2.0, form="info"))
    assert report["accepted"] is True
    assert calls == [("child", 2.0)]

    def shell_handler(target, work, source, world):
        calls.append(("shell", work.amount))
        return {"accepted": True, "custom": "shell"}

    root.set_handler("info", shell_handler)
    assert root.receive(Work(amount=1.0, form="info"))["custom"] == "shell"
    assert calls[-1] == ("shell", 1.0)

    empty = CompositeAutomaton(id="empty")
    assert empty.receive(Work(amount=1.0, form="info"))["accepted"] is True


def test_composite_state_roundtrip_restores_children_and_keeps_handlers():
    root = CompositeAutomaton(
        id="root", force=70.0, energy=30.0, health=40.0,
        state={"pressure": 1.5},
    )
    a = Automaton(
        id="a", force=20.0, energy=10.0, health=90.0,
        sickness=0.2, wound=0.3,
    )
    calls = []

    def handler(target, work, source, world):
        calls.append(work.amount)
        return {"accepted": True}

    a.set_handler("info", handler)
    inner = CompositeAutomaton(id="inner", force=5.0, energy=6.0)
    b = Automaton(id="b", force=1.0, energy=2.0)
    inner.add_child(b)
    root.add_child(a)
    root.add_child(inner)

    payload = json.loads(json.dumps(root.composite_state()))
    a.force = 0.0
    b.energy = 0.0
    root.force = 0.0
    root.state.clear()

    restored = root.load_composite_state(payload)
    assert {"a", "b", "inner"}.issubset(set(restored))
    assert root.force == pytest.approx(70.0)
    assert root.state == {"pressure": 1.5}
    assert a.force == pytest.approx(20.0)
    assert a.sickness == pytest.approx(0.2)
    assert a.wound == pytest.approx(0.3)
    assert b.energy == pytest.approx(2.0)
    assert a.receive(Work(amount=1.0, form="info"))["accepted"] is True
    assert calls == [1.0]


def test_automaton_state_helpers_roundtrip_and_clamp():
    unit = Automaton(id="unit", force=10.0, energy=20.0, health=30.0)
    payload = automaton_state(unit)
    unit.force = 0.0
    unit.energy = 0.0
    unit.health = 0.0
    load_automaton_state(unit, payload)
    assert unit.force == pytest.approx(10.0)
    assert unit.energy == pytest.approx(20.0)
    assert unit.health == pytest.approx(30.0)

    load_automaton_state(
        unit,
        {"force": 10_000.0, "energy": 10_000.0, "health": 10_000.0},
    )
    assert unit.force == pytest.approx(unit.max_force)
    assert unit.energy == pytest.approx(unit.max_energy)
    assert unit.health == pytest.approx(unit.max_health)


def test_damage_spreads_over_living_leaves_and_can_target_one_part():
    root = CompositeAutomaton(id="root")
    a = Automaton(id="a", force=100.0, max_force=100.0)
    b = Automaton(id="b", force=300.0, max_force=300.0)
    root.add_child(a)
    root.add_child(b)

    absorbed, overflow, health_damage = root.apply_force_damage(40.0)
    assert absorbed == pytest.approx(40.0)
    assert overflow == pytest.approx(0.0)
    assert health_damage == pytest.approx(0.0)
    assert a.force == pytest.approx(90.0)
    assert b.force == pytest.approx(270.0)

    root.apply_force_damage(10.0, target_id="a")
    assert a.force == pytest.approx(80.0)
    assert b.force == pytest.approx(270.0)


def test_clone_for_tick_isolates_children_state_and_drops_handlers():
    root = CompositeAutomaton(id="root")
    child = Automaton(id="child", force=50.0)
    child.set_handler("info", lambda *args: {"accepted": True})
    root.add_child(child)

    clone = root.clone_for_tick()
    clone.children["child"].force = 1.0
    assert child.force == pytest.approx(50.0)
    assert clone.children["child"].handlers == {}
    assert clone._composite_parent is None


def test_composite_skill_effectiveness_and_resistance_are_weighted():
    root = CompositeAutomaton(id="root", force=50.0, energy=50.0)
    a = Automaton(id="a", max_force=100.0, skills={"force": 0.2})
    b = Automaton(
        id="b", max_force=100.0, skills={"force": 0.8}, sickness=1.0
    )
    root.add_child(a)
    root.add_child(b)
    assert root.skill("force") == pytest.approx(0.5)
    assert root.work_effectiveness() == pytest.approx(0.7)
    assert root.attack_effectiveness() == pytest.approx(1.0)
    expected = 0.65 * root.aggregate_force_ratio + (
        0.35 * root.aggregate_energy_ratio
    )
    assert root.resistance("force") == pytest.approx(expected)


def test_set_distribution_strategy_validates_names():
    root = CompositeAutomaton(id="root")
    for strategy in DISTRIBUTION_STRATEGIES:
        assert root.set_distribution_strategy(strategy) == strategy
        assert root.distribution_strategy() == strategy
    with pytest.raises(ValueError):
        root.set_distribution_strategy("chaos")
    root.state["distribution_strategy"] = "chaos"
    assert root.distribution_strategy() == DEFAULT_DISTRIBUTION_STRATEGY
