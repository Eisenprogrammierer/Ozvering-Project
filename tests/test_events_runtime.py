"""Контракт событий: условия, доли вероятности, видимость и тайминг.

Код событий — только алгоритм. Все пороги, тексты, скорости, длительности
и правила видимости приходят из JSON. Здесь мы подаём маленький каталог и
проверяем именно алгоритм, не завися от объёма игрового контента.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from systems.events import (
    EventCatalog,
    EventCondition,
    EventEngine,
    EventError,
    EventInstance,
    EventTextGenerator,
    EventVisibility,
)

DATA = {
    "schema": 1,
    "categories": {
        "report": {"label": "донесение", "weight": 2.0},
        "rumor": {"label": "слух", "weight": 1.0},
    },
    "events": [
        {
            "id": "hungry_report",
            "category": "report",
            "title": "Голодный бунт",
            "templates": ["{actor} голоден"],
            "weight": 2.0,
            "probability": 0.5,
            "speed": 2.0,
            "duration": 3.0,
            "cooldown": 5.0,
            "conditions": [
                {"kind": "need", "key": "hunger", "op": ">=", "value": 0.5}
            ],
            "visibility": {"scope": "global", "min_force": 0.1},
            "effects": {
                "force": -0.1,
                "energy": -0.2,
                "needs": {"hunger": 0.1},
                "conditions": {"sickness": 0.05},
            },
        },
        {
            "id": "noble_rumor",
            "category": "rumor",
            "title": "Слух знати",
            "templates": ["{place} полон слухов"],
            "weight": 1.0,
            "probability": 1.0,
            "speed": 0.0,
            "duration": 1.0,
            "conditions": [
                {
                    "kind": "division",
                    "key": "social",
                    "op": "==",
                    "value": "noble",
                },
                {
                    "kind": "belief",
                    "subject": "actor-1",
                    "predicate": "trusts",
                    "object": "actor-2",
                },
            ],
            "visibility": {
                "scope": "global",
                "divisions": ["social:noble"],
            },
        },
    ],
}


@pytest.fixture()
def catalog():
    return EventCatalog.from_data(DATA)


@pytest.fixture()
def engine(catalog):
    return EventEngine(
        catalog=catalog,
        generator=EventTextGenerator(catalog=catalog, auto_names=False),
        seed=4,
    )


def _noble_context(**overrides):
    context = {
        "needs": {"hunger": 0.8},
        "divisions": {"social": "noble"},
        "beliefs": [
            {"subject": "actor-1", "predicate": "trusts", "object": "actor-2"}
        ],
        "force": 0.5,
        "energy": 0.5,
    }
    context.update(overrides)
    return context


def test_conditions_filter_events_by_need_division_and_belief(catalog):
    assert [event.id for event in catalog.eligible(
        {"needs": {"hunger": 0.9}}
    )] == ["hungry_report"]
    assert [event.id for event in catalog.eligible(_noble_context())] == [
        "hungry_report",
        "noble_rumor",
    ]
    without_belief = _noble_context(beliefs=[])
    assert [event.id for event in catalog.eligible(without_belief)] == [
        "hungry_report"
    ]


def _rich_context():
    return {
        "id": "char-1",
        "assets": {"legitimacy": 0.7, "cohesion": 0.2},
        "organs": {"staff": 0.4, "army": 0.9},
        "organ_statuses": {"staff": "восстанавливается"},
        "flags": {"amnesty": True, "mobilization": 0.3},
        "intentions": [
            {"target": "faction.republic", "essence": "defend"}
        ],
        "relations": {
            "faction.republic": {"trusts": 0.75, "fears": 0.0}
        },
        "characters": {
            "char-1": {"morale": 0.8, "needs": {"fear": 0.6}},
            "char-2": {"morale": 0.2},
        },
        "organization_state": {
            "willing_share": 0.42,
            "phase": "crisis",
            "mode_weights": {"order": 0.2},
        },
        "beliefs": [
            {
                "subject": "faction.empire",
                "predicate": "trusts",
                "object": "faction.republic",
                "value": 0.5,
                "confidence": 0.8,
            }
        ],
    }


def _matches(spec, context=None):
    return EventCondition.from_data(spec).evaluate(
        _rich_context() if context is None else context
    )


def test_event_conditions_read_assets_organs_and_statuses():
    assert _matches(
        {"kind": "asset", "key": "legitimacy", "op": ">=", "value": 0.6}
    )
    assert not _matches(
        {"kind": "asset", "key": "legitimacy", "op": ">=", "value": 0.8}
    )
    assert _matches(
        {"kind": "organ", "key": "staff", "op": "<=", "value": 0.5}
    )
    assert _matches(
        {"kind": "organ", "key": "missing", "op": "==", "value": 0.0}
    )
    assert _matches(
        {
            "kind": "organ_status",
            "key": "staff",
            "op": "==",
            "value": "восстанавливается",
        }
    )


def test_event_conditions_read_flags_as_presence_or_numbers():
    assert _matches({"kind": "flag", "key": "amnesty"})
    assert not _matches({"kind": "flag", "key": "missing"})
    assert _matches({"kind": "flag", "key": "amnesty", "value": True})
    assert not _matches({"kind": "flag", "key": "amnesty", "value": False})
    assert _matches(
        {
            "kind": "flag",
            "key": "mobilization",
            "op": ">=",
            "value": 0.2,
        }
    )
    assert not _matches(
        {
            "kind": "flag",
            "key": "mobilization",
            "op": ">=",
            "value": 0.4,
        }
    )


def test_event_conditions_read_intentions_and_relations():
    assert _matches(
        {
            "kind": "intention",
            "key": "defend",
            "object": "faction.republic",
        }
    )
    assert not _matches({"kind": "intention", "key": "coerce"})
    assert _matches(
        {
            "kind": "relation",
            "predicate": "trusts",
            "object": "faction.republic",
            "op": ">=",
            "value": 0.7,
        }
    )
    assert not _matches(
        {
            "kind": "relation",
            "predicate": "fears",
            "object": "faction.republic",
        }
    )


def test_event_conditions_read_roster_and_organization():
    assert _matches(
        {
            "kind": "character_stats",
            "subject": "char-1",
            "key": "needs.fear",
            "op": ">=",
            "value": 0.5,
        }
    )
    assert _matches(
        {
            "kind": "character_stats",
            "subject": "char-2",
            "key": "morale",
            "op": "<",
            "value": 0.5,
        }
    )
    assert _matches(
        {
            "kind": "organization",
            "key": "willing_share",
            "op": "<",
            "value": 0.5,
        }
    )
    assert _matches(
        {
            "kind": "organization",
            "key": "mode_weights.order",
            "op": ">=",
            "value": 0.2,
        }
    )
    assert _matches(
        {"kind": "organization", "key": "phase", "op": "==", "value": "crisis"}
    )


def test_belief_condition_distinguishes_presence_and_strength():
    assert _matches({"kind": "belief", "predicate": "trusts"})
    assert not _matches({"kind": "belief", "predicate": "fears"})
    # value * confidence = 0.5 * 0.8 = 0.4
    assert _matches(
        {"kind": "belief", "predicate": "trusts", "op": ">=", "value": 0.4}
    )
    assert not _matches(
        {"kind": "belief", "predicate": "trusts", "op": ">=", "value": 0.5}
    )


def test_event_condition_supports_negation_and_membership():
    condition = EventCondition.from_data(
        {
            "kind": "need",
            "key": "fear",
            "op": ">=",
            "value": 0.5,
            "negate": True,
        }
    )
    assert condition.evaluate({"needs": {"fear": 0.2}})
    assert not condition.evaluate({"needs": {"fear": 0.8}})

    membership = EventCondition.from_data(
        {"kind": "division", "key": "social", "op": "in", "value": ["noble"]}
    )
    assert membership.evaluate({"divisions": {"social": "noble"}})
    assert not membership.evaluate({"divisions": {"social": "worker"}})


def test_event_condition_rejects_unknown_operator():
    with pytest.raises(EventError):
        EventCondition.from_data({"kind": "need", "op": "~=", "value": 1})


def test_probability_shares_use_weight_category_and_probability(catalog):
    shares = dict(
        (event.id, share)
        for event, share in catalog.probability_shares(_noble_context())
    )
    # hungry: 2 (weight) * 2 (category) * 0.5 (probability) = 2
    # noble:  1 * 1 * 1 = 1
    assert shares["hungry_report"] == pytest.approx(2.0 / 3.0)
    assert shares["noble_rumor"] == pytest.approx(1.0 / 3.0)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_probability_shares_without_eligible_events_is_empty(catalog):
    assert catalog.probability_shares({"needs": {}}) == []


def test_visibility_filters_by_division_force_and_scope():
    visibility = EventVisibility.from_data(
        {
            "scope": "global",
            "divisions": ["social:noble"],
            "min_force": 0.2,
            "max_force": 0.8,
        }
    )
    assert visibility.visible_to(
        {"divisions": {"social": "noble"}, "force": 0.5}
    )
    assert not visibility.visible_to(
        {"divisions": {"social": "worker"}, "force": 0.5}
    )
    assert not visibility.visible_to(
        {"divisions": {"social": "noble"}, "force": 0.9}
    )
    assert not EventVisibility.from_data("hidden").visible_to({"id": "a"})
    assert not EventVisibility.from_data(
        {"scope": "character"}
    ).visible_to({})


def test_event_instance_timing_uses_speed_and_duration():
    instance = EventInstance(
        id="event-1",
        template_id="hungry_report",
        category="report",
        title="Голод",
        text="Голод",
        severity=0.5,
        stakes=0.5,
        visibility=EventVisibility(),
        speed=2.0,
        duration=3.0,
    )
    assert not instance.mature
    assert instance.remaining == pytest.approx(5.0)
    assert instance.progress == 0.0

    assert instance.advance(1.0)
    assert not instance.mature
    assert instance.advance(1.0)
    assert instance.mature
    assert instance.progress == pytest.approx(0.0)

    assert instance.advance(1.5)
    assert instance.progress == pytest.approx(0.5)
    assert not instance.advance(1.5)
    assert not instance.active


def test_engine_spawn_waits_for_speed_then_publishes(engine, catalog):
    event = catalog.event("hungry_report")
    instance = engine.spawn(event, context={"actor": "Анна"})
    assert instance.speed == 2.0
    assert engine.visible() == []
    assert engine.pending() == [instance]

    engine.advance(1.0)
    assert engine.visible({"force": 0.5}) == []
    visible = engine.advance(1.0, {"force": 0.5})
    assert visible == [instance]
    assert instance.text == "Анна голоден"


def test_render_context_is_separate_from_condition_context(engine, catalog):
    event = catalog.event("hungry_report")
    instance = engine.spawn(
        event,
        context={"assets": {"legitimacy": 0.7}},
        render_context={"actor": "Ирина"},
    )
    assert instance.text == "Ирина голоден"
    assert instance.context["actor"] == "Ирина"
    # Структуры условий не попадают в подстановки и в снимок события.
    assert "assets" not in instance.context


def test_engine_honours_cooldown():
    data = {
        "categories": {"report": {}},
        "events": [
            {
                "id": "always",
                "category": "report",
                "templates": ["x"],
                "probability": 1.0,
                "cooldown": 5.0,
                "speed": 0.0,
                "duration": 0.0,
            }
        ],
    }
    catalog = EventCatalog.from_data(data)
    engine = EventEngine(
        catalog=catalog,
        generator=EventTextGenerator(catalog=catalog, auto_names=False),
        seed=2,
    )
    engine.spawn(catalog.event("always"))
    assert engine.pick({}) is None

    engine.advance(5.0)
    assert engine.pick({}).id == "always"


def test_engine_effects_sum_mature_visible_events(engine, catalog):
    engine.spawn(catalog.event("hungry_report"))
    assert engine.effects({"force": 0.5}) == {
        "force": 0.0,
        "energy": 0.0,
        "needs": {},
        "conditions": {},
    }
    engine.advance(2.0)
    effects = engine.effects({"force": 0.5})
    assert effects["force"] == pytest.approx(-0.1)
    assert effects["energy"] == pytest.approx(-0.2)
    assert effects["needs"]["hunger"] == pytest.approx(0.1)
    assert effects["conditions"]["sickness"] == pytest.approx(0.05)


def test_engine_snapshot_records_time_active_and_history(engine, catalog):
    engine.spawn(catalog.event("hungry_report"))
    engine.advance(1.0)
    snapshot = engine.snapshot()
    assert snapshot["time"] == pytest.approx(1.0)
    assert snapshot["active"][0]["template_id"] == "hungry_report"
    assert snapshot["active"][0]["mature"] is False
    assert snapshot["history"][0]["id"] == "event-1"
    assert snapshot["cooldowns"]["hungry_report"] == pytest.approx(5.0)


def test_catalog_rejects_unknown_category_and_empty_templates():
    bad = {
        "categories": {"report": {}},
        "events": [
            {
                "id": "x",
                "category": "missing",
                "templates": ["x"],
            }
        ],
    }
    with pytest.raises(EventError):
        EventCatalog.from_data(bad)

    bad["categories"]["missing"] = {}
    bad["events"][0]["templates"] = []
    with pytest.raises(EventError):
        EventCatalog.from_data(bad)


def test_production_runtime_events_are_data_driven():
    root = Path(__file__).resolve().parents[1] / "configs" / "systems"
    catalog = EventCatalog.load(root)
    for event_id in ("hunger_riot", "field_rumor", "wound_fever"):
        event = catalog.event(event_id)
        assert event.conditions
        assert event.visibility
        assert event.speed > 0.0
        assert event.duration > 0.0
        assert 0.0 < event.probability <= 1.0
        # Событие — слой отражения: оно ничего не производит.
        assert not event.effects
