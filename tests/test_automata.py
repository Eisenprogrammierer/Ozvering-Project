from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from automata.model import (
    Automaton,
    AutomatonError,
    History,
    SCHEMA,
    slugify,
)
from automata.storage import AutomataStore, StoreError


def test_state_ids_and_one_initial():
    automaton = Automaton()
    first = automaton.add_state(name="A", x=10, y=20, initial=True)
    second = automaton.add_state(name="B", x=300, y=20, initial=True)

    assert first.id == "s1"
    assert second.id == "s2"
    assert first.initial is False
    assert second.initial is True
    assert automaton.initial_states == [second]
    assert automaton.counts() == (2, 0)


def test_remove_state_removes_connected_transitions():
    automaton = Automaton()
    a = automaton.add_state("A")
    b = automaton.add_state("B")
    c = automaton.add_state("C")
    automaton.add_transition(a.id, b.id, "ab")
    automaton.add_transition(b.id, c.id, "bc")
    automaton.add_transition(c.id, a.id, "ca")

    assert automaton.remove_state(b.id) is True
    assert [s.id for s in automaton.states] == ["s1", "s3"]
    assert [t.id for t in automaton.transitions] == ["t3"]
    assert automaton.transitions[0].source == "s3"
    assert automaton.transitions[0].target == "s1"
    assert automaton.remove_state("nope") is False


def test_rename_state_updates_edges_and_rejects_bad_values():
    automaton = Automaton()
    a = automaton.add_state("A")
    b = automaton.add_state("B")
    transition = automaton.add_transition(a.id, b.id, "go")

    automaton.rename_state(a.id, "q0")
    assert transition.source == "q0"
    assert automaton.state("q0") is not None

    with pytest.raises(AutomatonError):
        automaton.rename_state("q0", "s2")
    with pytest.raises(AutomatonError):
        automaton.rename_state("q0", "с пробелом")
    with pytest.raises(AutomatonError):
        automaton.rename_state("missing", "q1")


def test_transition_requires_known_states():
    automaton = Automaton()
    a = automaton.add_state("A")
    with pytest.raises(AutomatonError):
        automaton.add_transition(a.id, "missing")
    with pytest.raises(AutomatonError):
        automaton.add_transition("missing", a.id)


def test_set_initial_and_final():
    automaton = Automaton()
    a = automaton.add_state("A")
    b = automaton.add_state("B")
    automaton.set_initial(a.id)
    automaton.set_initial(b.id)
    assert a.initial is False and b.initial is True
    automaton.set_initial(b.id, False)
    assert automaton.initial_states == []

    automaton.set_final(a.id)
    automaton.set_final(b.id)
    assert automaton.final_states == [a, b]


def test_validation_reports_unreachable_and_dead_end():
    automaton = Automaton()
    a = automaton.add_state("A", initial=True)
    b = automaton.add_state("B", final=True)
    c = automaton.add_state("C")
    automaton.add_transition(a.id, b.id, "go")

    codes = {issue.code for issue in automaton.validate()}
    assert "unreachable" in codes
    assert "dead_end" in codes
    assert not any(issue.is_error for issue in automaton.validate())


def test_validation_reports_structural_errors():
    data = {
        "version": SCHEMA,
        "name": "Broken",
        "states": [
            {"id": "s1", "name": "A", "initial": True},
            {"id": "s2", "name": "B", "initial": True},
        ],
        "transitions": [
            {"id": "t1", "source": "s1", "target": "missing"},
            {"id": "t2", "source": "s1", "target": "s2", "event": "x"},
            {"id": "t3", "source": "s1", "target": "s2", "event": "x"},
        ],
    }
    automaton = Automaton.from_dict(data)
    issues = automaton.validate()
    codes = {issue.code for issue in issues}
    assert "multiple_initial" in codes
    assert "missing_state" in codes
    assert "duplicate_edge" in codes
    assert any(issue.is_error for issue in issues)


def test_empty_automaton_has_error():
    automaton = Automaton()
    issues = automaton.validate()
    assert len(issues) == 1
    assert issues[0].code == "empty"
    assert issues[0].is_error


def test_json_roundtrip_and_clone():
    automaton = Automaton("Имя", "Описание")
    a = automaton.add_state("A", 10, 20, initial=True)
    b = automaton.add_state("B", 300, 20, final=True)
    automaton.add_transition(a.id, b.id, "go", "если можно")
    automaton.add_transition(b.id, b.id, "loop")

    payload = automaton.to_dict()
    assert payload["version"] == SCHEMA
    restored = Automaton.from_dict(json.loads(json.dumps(payload)))
    assert restored.to_dict() == payload

    copy = automaton.clone()
    copy.name = "Другое"
    assert copy.to_dict() != automaton.to_dict()
    assert copy.states[0].name == "A"


def test_from_dict_rejects_duplicate_ids():
    with pytest.raises(AutomatonError):
        Automaton.from_dict(
            {
                "states": [{"id": "s1"}, {"id": "s1"}],
                "transitions": [],
            }
        )
    with pytest.raises(AutomatonError):
        Automaton.from_dict({"states": "not-a-list"})


def test_history_undo_redo_and_branch():
    history = History({"name": "0"})
    assert history.can_undo is False and history.can_redo is False
    history.push({"name": "1"})
    history.push({"name": "2"})
    assert history.can_undo is True

    assert history.undo() == {"name": "1"}
    assert history.undo() == {"name": "0"}
    assert history.undo() is None
    assert history.redo() == {"name": "1"}
    history.push({"name": "3"})
    assert history.can_redo is False
    assert history.redo() is None


def test_history_limit_keeps_the_tail():
    history = History({"n": 0}, limit=3)
    for number in range(1, 8):
        history.push({"n": number})
    assert len(history) == 3
    assert history.undo() == {"n": 6}
    assert history.undo() == {"n": 5}
    assert history.undo() is None


def test_slugify_transliterates_and_cleans():
    assert slugify("Простой цикл") == "prostoy_cikl"
    assert slugify("Hello, World!") == "hello_world"
    assert slugify("   ") == "automaton"
    assert slugify("a" * 100).startswith("a" * 48)
    assert len(slugify("a" * 100)) <= 48


def test_store_crud_and_unique_slugs(tmp_path):
    store = AutomataStore(tmp_path)
    automaton = Automaton("Тест")
    a = automaton.add_state("A", initial=True)
    b = automaton.add_state("B", final=True)
    automaton.add_transition(a.id, b.id, "go")

    first = store.save(automaton)
    second = store.save(automaton)
    assert first == "test"
    assert second == "test_2"
    assert store.exists(first) and store.exists(second)

    entries = store.list_entries()
    assert [entry["slug"] for entry in entries] == ["test", "test_2"]
    assert entries[0]["states"] == 2
    assert entries[0]["transitions"] == 1
    assert not entries[0]["error"]

    loaded = store.load(first)
    assert loaded.to_dict() == automaton.to_dict()

    duplicate = store.duplicate(first)
    assert duplicate == "kopiya_test"
    assert store.load(duplicate).name == "Копия — Тест"

    assert store.delete(first) is True
    assert store.delete(first) is False
    assert not store.exists(first)


def test_store_reports_corrupt_json(tmp_path):
    (tmp_path / "broken.json").write_text("{oops", encoding="utf-8")
    store = AutomataStore(tmp_path)
    entries = store.list_entries()
    assert len(entries) == 1
    assert entries[0]["slug"] == "broken"
    assert "не удалось прочитать" in entries[0]["error"]
    with pytest.raises(StoreError):
        store.load("broken")


def test_store_rejects_bad_slug(tmp_path):
    store = AutomataStore(tmp_path)
    with pytest.raises(StoreError):
        store.load("../secret")
    with pytest.raises(StoreError):
        store.save(Automaton(), "../secret")


def test_example_file_is_valid():
    root = Path(__file__).resolve().parents[1]
    store = AutomataStore(root / "configs" / "automata")
    automaton = store.load("example")
    assert automaton.counts() == (4, 6)
    assert automaton.validate() == []


def test_core_model_does_not_import_pygame():
    code = (
        "import sys; import automata.model; "
        "assert 'pygame' not in sys.modules, sorted(sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
