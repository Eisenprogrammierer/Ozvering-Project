"""Формирование и распад коалиций кампании (§7.3 №19)."""

import copy

import pytest

from campaign.coalitions import (
    CoalitionBook,
    coalition_config,
    pair_score,
)
from campaign.world import (
    WorldEngine,
    build_player_profile,
    load_biography,
    load_world,
)


def _variables():
    return {
        "name": "Ирина Свет",
        "gender": "female",
        "origin": "port",
        "family": "clerk",
        "education": "academy",
        "formative": "harbor_fire",
        "vocation": "state",
        "value": "order",
        "value2": "knowledge",
        "flaw": "ambition",
        "patron": "minister",
        "reputation": "respectable",
    }


def _profile():
    return build_player_profile(
        _variables(), biography=load_biography(), seed=7
    )


def _engine(extra=None):
    world = copy.deepcopy(load_world())
    for key, value in (extra or {}).items():
        world[key] = value
    return WorldEngine(
        world,
        profile=_profile(),
        node_id="agora_government",
        office_id="head_of_government",
        seed=7,
    )


def _rules(**overrides):
    raw = {
        "enabled": True,
        "form_threshold": 0.35,
        "decay_threshold": 0.15,
        "form_days": 2,
        "decay_days": 2,
        "max_coalitions": 3,
        "axes": ["affinity", "trust"],
    }
    raw.update(overrides)
    return coalition_config(raw)


def _join(engine, left, right, value=0.9):
    axes = {"affinity": value, "trust": value}
    engine.set_relation_axes(left, right, axes)
    engine.set_relation_axes(right, left, axes)


# ---------------------------------------------------------------------------
# Чистая модель: пара, формирование, распад, персистентность
# ---------------------------------------------------------------------------


def test_pair_score_is_symmetric_bounded_and_obligation_aware():
    left = {"affinity": 0.8, "trust": 0.6}
    right = {"affinity": 0.6, "trust": 0.8}
    base = pair_score(left, right)
    assert base == pytest.approx(0.7)
    assert pair_score(right, left) == pytest.approx(base)
    assert pair_score({}, {}) == 0.0
    assert pair_score(
        {"affinity": 1.0, "trust": 1.0},
        {"affinity": 1.0, "trust": 1.0},
        obligations=99,
    ) == 1.0
    assert pair_score(left, right, obligations=1) > base


def test_coalition_forms_after_pressure_and_dissolves_after_decay():
    rules = _rules()
    book = CoalitionBook()
    scores = {("a", "b"): 0.8}
    eligible = {"a": True, "b": True}

    assert book.update(1, scores, eligible, rules) == []
    events = book.update(2, scores, eligible, rules)
    assert len(events) == 1
    assert events[0]["action"] == "formed"
    assert book.active()[0].members == ("a", "b")
    assert book.active()[0].strength == pytest.approx(0.8)

    # Первый слабый день — только давление распада.
    assert book.update(3, {("a", "b"): 0.0}, eligible, rules) == []
    events = book.update(4, {("a", "b"): 0.0}, eligible, rules)
    assert len(events) == 1
    assert events[0]["action"] == "dissolved"
    assert book.active() == []
    assert book.items[0].status == "dissolved"


def test_coalition_dissolves_immediately_when_member_is_gone():
    rules = _rules(decay_days=5)
    book = CoalitionBook().load(
        {
            "items": [
                {
                    "id": "coa1",
                    "members": ["a", "b"],
                    "created_day": 1,
                    "strength": 0.8,
                    "last_active_day": 1,
                }
            ],
            "next_index": 2,
        }
    )
    events = book.update(
        2, {("a", "b"): 0.8}, {"a": True, "b": False}, rules
    )
    assert events[0]["action"] == "dissolved"
    assert book.active() == []


def test_coalition_roundtrip_and_deterministic_order():
    rules = _rules(form_days=1)
    scores = {
        ("c", "d"): 0.5,
        ("a", "b"): 0.9,
        ("a", "c"): 0.4,
    }
    eligible = {key: True for key in "abcd"}
    first = CoalitionBook()
    second = CoalitionBook()
    first_events = first.update(1, scores, eligible, rules)
    second_events = second.update(1, scores, eligible, rules)
    assert first_events == second_events
    assert first.active()[0].members == ("a", "b")

    restored = CoalitionBook().load(first.to_dict())
    assert restored.to_dict() == first.to_dict()


# ---------------------------------------------------------------------------
# Интеграция с миром: opt-in, журнал, распад и снимок
# ---------------------------------------------------------------------------


def test_coalitions_are_off_by_default_and_do_not_touch_log():
    engine = _engine()
    _join(engine, "agora_ministry_interior", "agora_watch")
    engine.end_day()
    engine.end_day()
    assert engine.coalition_view()["active"] == []
    assert engine.coalition_view()["enabled"] is False
    assert not any(
        entry.get("kind") == "coalition" for entry in engine.log
    )
    assert engine.coalition_partners("agora_ministry_interior") == []


def test_world_forms_coalition_logs_it_and_boosts_cooperation():
    engine = _engine({"coalitions": _rules()})
    _join(engine, "agora_ministry_interior", "agora_watch")
    engine.end_day()
    engine.end_day()
    view = engine.coalition_view()
    assert view["enabled"] is True
    assert view["count"] == 1
    members = view["active"][0]["members"]
    assert set(members) == {"agora_ministry_interior", "agora_watch"}
    assert engine.coalition_partners("agora_ministry_interior") == [
        "agora_watch"
    ]

    entries = [
        entry for entry in engine.log if entry.get("kind") == "coalition"
    ]
    assert entries
    assert "сформирован" in entries[0]["text"]

    context = engine.node_context("agora_ministry_interior")
    assert engine._coalition_bonus(
        context, engine.nodes["agora_watch"]
    ) > 0.0
    assert engine._coalition_bonus(
        context, engine.nodes["agora_army_command"]
    ) == 0.0


def test_broken_relations_dissolve_coalition_on_day_edge():
    engine = _engine({"coalitions": _rules(decay_days=1)})
    _join(engine, "agora_ministry_interior", "agora_watch")
    engine.end_day()
    engine.end_day()
    assert engine.coalition_view()["count"] == 1

    for left, right in (
        ("agora_ministry_interior", "agora_watch"),
        ("agora_watch", "agora_ministry_interior"),
    ):
        engine.set_relation_axes(
            left, right, {"affinity": 0.0, "trust": 0.0}
        )
    engine.end_day()
    view = engine.coalition_view()
    assert view["active"] == []
    assert view["dissolved"]
    assert any(
        entry.get("kind") == "coalition"
        and entry.get("action") == "dissolved"
        for entry in engine.log
    )


def test_coalitions_survive_snapshot_and_restore_pressure():
    engine = _engine({"coalitions": _rules()})
    _join(engine, "agora_ministry_interior", "agora_watch")
    engine.end_day()
    engine.end_day()
    snapshot = engine.to_dict()

    restored = _engine({"coalitions": _rules()})
    restored.load_snapshot(snapshot)
    assert restored.coalition_view()["active"] == (
        engine.coalition_view()["active"]
    )
    assert restored.coalitions.pressure == engine.coalitions.pressure
    assert restored.coalitions.next_index == engine.coalitions.next_index
