"""Очередь намерений кампании: первый срез real-time-планировщика."""

import json

import pytest

from campaign.planner import (
    MAX_INTENTS,
    PRIORITY_MAX,
    PRIORITY_MIN,
    SLOT_DAY_EDGE,
    SLOTS_MAX,
    Intent,
    IntentQueue,
    condition_holds,
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


def _engine(seed=7):
    profile = build_player_profile(
        _variables(), biography=load_biography(), seed=seed
    )
    engine = WorldEngine(
        load_world(),
        profile=profile,
        node_id="agora_government",
        office_id="head_of_government",
        seed=seed,
    )
    engine.attach("agora_government", "head_of_government")
    return engine


def _first_character(engine):
    return engine.characters[engine.character_order[0]]


def test_intent_queue_orders_by_day_and_trims_farthest():
    queue = IntentQueue(limit=3)
    queue.schedule(5, "message", payload={"text": "поздно"})
    queue.schedule(2, "message", payload={"text": "рано"})
    queue.schedule(3, "contact", actor="a")
    assert [item.due_day for item in queue] == [2, 3, 5]

    assert queue.schedule(9, "message", payload={"text": "далеко"}) is None
    assert [item.due_day for item in queue] == [2, 3, 5]


def test_intent_queue_round_trips_through_snapshot_format():
    queue = IntentQueue()
    queue.schedule(
        4,
        "contact",
        actor="friend",
        payload={"effects": {"affinity": 0.1}, "text": "привет"},
        source="autonomy",
    )
    raw = queue.to_list()
    restored = IntentQueue(raw)
    assert restored.to_list() == raw
    item = restored.pop_due(4)[0]
    assert isinstance(item, Intent)
    assert item.actor == "friend"
    assert item.payload["effects"] == {"affinity": 0.1}


def test_intent_queue_rejects_unknown_kind():
    queue = IntentQueue()
    with pytest.raises(ValueError):
        queue.schedule(1, "mystery")


def test_world_runs_due_message_intent_before_ai_turn():
    engine = _engine()
    text = "Гонец приносит весть."
    engine.schedule_intent(
        engine.day + 1,
        "message",
        payload={"text": text},
        due_slot=0,
    )

    engine.end_day()

    assert engine.day == 2
    assert len(engine.intents) == 0
    assert any(entry["text"] == text for entry in engine.log)


def test_world_contact_intent_moves_affinity():
    engine = _engine()
    character = _first_character(engine)
    before = float(character["affinity"])
    engine.schedule_intent(
        engine.day + 1,
        "contact",
        actor=character["id"],
        payload={
            "effects": {"affinity": 0.1},
            "text": "предлагает помощь.",
        },
    )

    result = engine.end_day()

    assert float(character["affinity"]) > before + 0.05
    assert any(
        entry["kind"] == "intent" and entry.get("actor") == character["id"]
        for entry in result["events"]
    )


def test_world_intents_persist_and_fire_after_restore():
    engine = _engine()
    character = _first_character(engine)
    engine.schedule_intent(
        engine.day + 1,
        "contact",
        actor=character["id"],
        payload={"effects": {"affinity": 0.5}},
    )
    snapshot = engine.to_dict()
    assert snapshot["intents"]

    restored = WorldEngine(load_world(), snapshot=snapshot)
    before = float(restored.characters[character["id"]]["affinity"])
    restored.end_day()
    restored.tick()

    assert len(restored.intents) == 0
    assert float(restored.characters[character["id"]]["affinity"]) > before


def test_old_snapshot_without_intents_loads_empty_queue():
    engine = _engine()
    snapshot = engine.to_dict()
    snapshot.pop("intents", None)

    restored = WorldEngine(load_world(), snapshot=snapshot)

    assert len(restored.intents) == 0
    assert restored.end_day()["ok"] is True


def test_autonomous_character_schedules_contact_and_fires_next_day():
    """A4: лояльный персонаж получает rapprochement, но при affinity > 0.8
    намерение честно аннулируется по `cancel_when` — мир не «дарит»
    расположение уже преданному персонажу. Это заявленное поведение
    политики автономии (см. `_schedule_autonomy`)."""
    engine = _engine()
    character = _first_character(engine)
    character["autonomous"] = True
    character["autonomy_period"] = 1
    before = float(character["affinity"])

    engine.end_day()
    assert len(engine.intents) == 1
    pending = engine.intents.due(engine.day)[0]
    assert pending.source == "autonomy"
    assert pending.actor == character["id"]
    assert pending.payload["policy"] == "rapprochement"
    assert pending.cancel_when == {
        "field": "affinity",
        "op": "gt",
        "value": 0.8,
    }

    engine.end_day()
    result = engine.end_day()

    cancelled = [
        entry
        for entry in result["events"]
        if entry["kind"] == "intent_cancelled"
        and entry.get("source") == "autonomy"
    ]
    assert len(cancelled) == 1
    assert abs(float(character["affinity"]) - before) < 0.05
    pending = list(engine.intents)
    assert len(pending) == 1
    assert pending[0].due_day == engine.day
    assert pending[0].source == "autonomy"


def test_hostile_autonomous_character_reconciles_with_priority():
    """Враждебный персонаж тянется к примирению (`reconcile`).

    Приоритет 1, исход бросается общей формулой успеха — событие
    исполняется, а не снимается.
    """
    engine = _engine(seed=11)
    character = engine.characters[engine.character_order[1]]
    character["autonomous"] = True
    character["autonomy_period"] = 1
    character["affinity"] = -0.5
    character["trust"] = -0.3
    before = float(character["affinity"])

    engine.end_day()
    pending = engine.intents.due(engine.day)[0]
    assert pending.payload["policy"] == "reconcile"
    assert pending.priority == 1

    engine.end_day()
    result = engine.end_day()
    fired = [
        entry
        for entry in result["events"]
        if entry["kind"] == "intent" and entry.get("actor") == character["id"]
    ]
    assert len(fired) == 1
    assert fired[0]["outcome"] in ("success", "failure")
    assert abs(float(character["affinity"]) - before) >= 0.0


def test_autonomy_contact_success_path_applies_positive_effects():
    """Прямой вызов исполнителя: успех применяет позитивные эффекты политики,
    провал — зеркалит их вдвое слабее (детерминировано seed'ом)."""
    engine = _engine()
    character = _first_character(engine)
    character["autonomous"] = True
    from campaign.planner import Intent

    intent = Intent(
        due_day=engine.day,
        kind="contact",
        actor=character["id"],
        payload={"policy": "probe", "effects": {"affinity": 0.01}},
        source="autonomy",
    )
    before = float(character["affinity"])
    events = engine._apply_autonomy_contact(intent)
    assert len(events) == 1
    outcome = events[0]["outcome"]
    delta = float(character["affinity"]) - before
    if outcome == "success":
        assert delta > 0.0
    else:
        assert delta < 0.0
    again = engine._apply_autonomy_contact(intent)
    assert again[0]["outcome"] == outcome


def test_dead_autonomous_character_contact_is_skipped():
    engine = _engine()
    character = _first_character(engine)
    from campaign.planner import Intent

    intent = Intent(
        due_day=engine.day,
        kind="contact",
        actor=character["id"],
        payload={"policy": "probe"},
        source="autonomy",
    )
    character["alive"] = False
    assert engine._apply_autonomy_contact(intent) == []


def test_intent_queue_orders_by_priority_within_day():
    queue = IntentQueue()
    queue.schedule(2, "message", actor="a", source="s1", priority=0)
    queue.schedule(2, "message", actor="b", source="s2", priority=5)
    queue.schedule(1, "message", actor="c", source="s3", priority=9)
    order = [(item.actor, item.priority) for item in queue]
    assert order == [("c", 9), ("b", 5), ("a", 0)]


def test_intent_priority_clamped_and_round_trips():
    queue = IntentQueue()
    queue.schedule(1, "message", priority=99)
    queue.schedule(1, "message", actor="low", priority=-3)
    by_actor = {item.actor or "high": item.priority for item in queue}
    assert by_actor["high"] == PRIORITY_MAX
    assert by_actor["low"] == PRIORITY_MIN
    restored = IntentQueue(queue.to_list())
    assert [item.priority for item in restored] == [
        PRIORITY_MAX,
        PRIORITY_MIN,
    ]


def test_intent_queue_cancel_by_criteria():
    queue = IntentQueue()
    queue.schedule(2, "contact", actor="c1", source="autonomy")
    queue.schedule(2, "message", actor="c1", source="world")
    queue.schedule(3, "contact", actor="c2", source="autonomy")
    removed = queue.cancel(actor="c1", kind="contact")
    assert removed == 1
    assert len(queue) == 2
    assert all(item.actor != "c1" or item.kind != "contact" for item in queue)


def test_condition_holds_semantics():
    character = {"affinity": 0.5, "trust": -0.2}
    affinity = {"field": "affinity"}
    trust = {"field": "trust"}
    assert condition_holds(
        dict(affinity, op="gt", value=0.4), character
    )
    assert condition_holds(
        dict(affinity, op=">", value=0.4), character
    )
    assert not condition_holds(
        dict(affinity, op="ge", value=0.6), character
    )
    assert condition_holds(
        dict(trust, op="lt", value=0.0), character
    )
    assert condition_holds(
        dict(trust, op="eq", value=-0.2), character
    )
    assert condition_holds(
        dict(trust, op="ne", value=0.0), character
    )
    assert not condition_holds(
        {"field": "mystery", "op": "gt", "value": 0}, character
    )
    assert not condition_holds(
        {"field": "affinity", "op": "??"}, character
    )
    assert not condition_holds(None, character)
    assert not condition_holds(
        {"field": "affinity", "op": "gt", "value": 0}, None
    )


def test_world_cancels_intent_when_condition_holds():
    engine = _engine()
    character = _first_character(engine)
    before = float(character["affinity"])
    engine.schedule_intent(
        engine.day + 1,
        "contact",
        actor=character["id"],
        payload={"effects": {"affinity": 0.5}, "text": "примирение."},
        cancel_when={"field": "affinity", "op": "gt", "value": 0.0},
        due_slot=0,
    )
    result = engine.end_day()
    kinds = [entry["kind"] for entry in result["events"]]
    assert "intent_cancelled" in kinds
    assert "intent" not in kinds
    assert float(character["affinity"]) < before + 0.01
    assert any(entry.get("kind") == "intent_cancelled" for entry in engine.log)


def test_world_executes_intent_when_condition_false():
    engine = _engine()
    character = _first_character(engine)
    before = float(character["affinity"])
    engine.schedule_intent(
        engine.day + 1,
        "contact",
        actor=character["id"],
        payload={"effects": {"affinity": 0.1}, "text": "помощь."},
        cancel_when={"field": "affinity", "op": "gt", "value": 5.0},
        due_slot=0,
    )
    result = engine.end_day()
    fired = [
        entry
        for entry in result["events"]
        if entry["kind"] == "intent" and entry.get("actor") == character["id"]
    ]
    assert len(fired) == 1
    assert float(character["affinity"]) > before + 0.05


def test_non_autonomous_character_does_not_schedule_contacts():
    engine = _engine()
    character = _first_character(engine)
    assert character["autonomous"] is False

    engine.end_day()

    assert len(engine.intents) == 0


def test_campaign_env_reports_pending_intents():
    from campaign.env import CampaignEnv

    env = CampaignEnv(seed=5, max_days=6)
    env.engine.schedule_intent(
        env.engine.day + 1, "message", payload={"text": "письмо"}
    )

    observation, _reward, _done, _truncated, info = env.step(
        env.legal_actions()[0]
    )

    assert observation.day >= 1
    assert "intents" in info


def test_intent_queue_limit_is_documented():
    queue = IntentQueue()
    for day in range(MAX_INTENTS + 5):
        queue.schedule(day + 1, "message", payload={"text": str(day)})
    assert len(queue) == MAX_INTENTS
    assert queue.items[-1].due_day == MAX_INTENTS


def test_intent_sorts_by_day_then_slot_then_priority():
    queue = IntentQueue()
    queue.schedule(3, "message", payload={"text": "поздний слот"}, due_slot=2)
    queue.schedule(
        3, "message", payload={"text": "срочный у края"}, priority=5
    )
    queue.schedule(3, "message", payload={"text": "обычный у края"})
    assert [item.due_slot for item in queue] == [0, 0, 2]
    assert queue.items[0].payload["text"] == "срочный у края"


def test_intent_due_slot_defaults_to_day_edge_and_round_trips():
    intent = Intent(due_day=4, kind="message")
    assert intent.due_slot == 0
    raw = intent.to_dict()
    assert raw["due_slot"] == 0
    legacy = dict(raw)
    del legacy["due_slot"]
    assert Intent.from_dict(legacy).due_slot == 0
    assert Intent.from_dict({**raw, "due_slot": 99}).due_slot == 3
    assert Intent.from_dict({**raw, "due_slot": -1}).due_slot == 0


def test_schedule_action_defers_player_action_to_future_day():
    engine = _engine(seed=11)
    action_id = engine.available_actions()[0]
    intent = engine.schedule_action(action_id, due_day=engine.day + 1)
    assert intent is not None
    assert intent.kind == "action"
    assert intent.payload["action"] == action_id
    assert engine.action_count == 0
    assert float(engine.player_energy) > 0


def test_schedule_action_rejects_unknown_action_and_past_day():
    engine = _engine()
    assert engine.schedule_action("нет-такого-действия") is None
    assert engine.schedule_action("rally", due_day=engine.day) is None


def test_scheduled_action_executes_full_path_on_due_day():
    engine = _engine(seed=11)
    action_id = engine.available_actions()[0]
    engine.schedule_action(action_id, due_day=engine.day + 1, due_slot=1)

    result = engine.end_day()
    assert len(engine.intents) == 0

    fired = [
        entry
        for entry in result["events"]
        if entry.get("source") == "player_action"
    ]
    assert len(fired) == 1
    assert fired[0]["action"] == action_id
    assert fired[0]["outcome"] in ("success", "failure")
    assert engine.action_count == 1


def test_scheduled_action_skips_gracefully_when_no_longer_valid():
    engine = _engine(seed=11)
    action_id = engine.available_actions()[0]
    engine.schedule_action(action_id, due_day=engine.day + 1)
    engine.player_alive = False

    result = engine.end_day()
    events = result["events"]
    assert len(engine.intents) == 0
    assert not any(
        entry.get("source") == "player_action" for entry in events
    )
    assert any(entry.get("kind") == "intent_skipped" for entry in events)
    assert engine.action_count == 0


def test_scheduled_action_survives_save_and_load():
    engine = _engine(seed=11)
    action_id = engine.available_actions()[0]
    engine.schedule_action(action_id, due_day=engine.day + 1)
    snapshot = engine.to_dict()

    restored = WorldEngine(load_world(), seed=11, snapshot=snapshot)
    assert len(restored.intents) == 1
    pending = list(restored.intents)[0]
    assert pending.kind == "action" and pending.payload["action"] == action_id

    result = restored.end_day()
    fired = [
        entry
        for entry in result["events"]
        if entry.get("source") == "player_action"
    ]
    assert len(fired) == 1


def test_pop_due_respects_max_slot_boundary():
    queue = IntentQueue()
    queue.schedule(5, "message", payload={"text": "край"})
    queue.schedule(5, "message", payload={"text": "внутри"}, due_slot=2)
    edge = queue.pop_due(5, max_slot=0)
    assert [item.payload["text"] for item in edge] == ["край"]
    rest = queue.pop_due(5)
    assert [item.payload["text"] for item in rest] == ["внутри"]


def test_pop_due_runs_overdue_intents_regardless_of_slot():
    queue = IntentQueue()
    queue.schedule(4, "message", payload={"text": "долг"}, due_slot=3)
    ready = queue.pop_due(5, max_slot=0)
    assert [item.payload["text"] for item in ready] == ["долг"]
    assert len(queue) == 0


def test_tick_runs_intraday_slots_without_advancing_day():
    engine = _engine(seed=13)
    engine.attach("agora_government", "head_of_government")
    action_id = engine.available_actions()[0]
    engine.end_day()
    day_before = engine.day
    engine.schedule_action(action_id, due_day=engine.day, due_slot=2)

    events = engine.tick(max_slot=1)
    assert [
        entry for entry in events
        if entry.get("source") == "player_action"
    ] == []
    assert engine.day == day_before

    fired = engine.tick(max_slot=2)
    player_events = [e for e in fired if e.get("source") == "player_action"]
    assert len(player_events) == 1
    assert engine.day == day_before
    assert len(engine.intents) == 0


def test_tick_spreads_node_actions_across_day_and_end_day_finishes():
    engine = _engine(seed=19)
    called = []

    def spy(node_id):
        called.append((engine.day, node_id))
        return {"kind": "world", "source": node_id, "text": node_id}

    engine._ai_action = spy
    slot_zero = [
        node_id
        for node_id in engine.node_order
        if engine._node_slot(node_id) == 0
    ]
    engine.tick(max_slot=0)
    assert {node_id for _day, node_id in called} == set(slot_zero)

    engine.tick(max_slot=SLOTS_MAX)
    assert len(called) == len(engine.node_order)
    assert len({node_id for _day, node_id in called}) == len(called)

    day = engine.day
    engine.end_day()
    assert len(called) == len(engine.node_order)

    engine.tick(max_slot=SLOTS_MAX)
    new_day = [node_id for when, node_id in called if when != day]
    assert len(new_day) == len(engine.node_order)


def test_node_action_day_persists_in_snapshot():
    engine = _engine(seed=23)
    engine._ai_action = lambda node_id: None
    engine.tick(max_slot=SLOTS_MAX)
    assert engine.node_action_day

    snapshot = json.loads(json.dumps(engine.to_dict()))
    restored = WorldEngine(load_world(), snapshot=snapshot)

    assert restored.node_action_day == engine.node_action_day


def test_tick_and_end_day_do_not_double_execute():
    engine = _engine(seed=17)
    engine.attach("agora_government", "head_of_government")
    action_id = engine.available_actions()[0]
    engine.end_day()
    engine.schedule_action(action_id, due_day=engine.day, due_slot=1)

    fired_by_tick = engine.tick(max_slot=SLOTS_MAX)
    fired = [
        e for e in fired_by_tick if e.get("source") == "player_action"
    ]
    assert len(fired) == 1
    actions_after_tick = engine.action_count

    result = engine.end_day()
    repeated = [
        e for e in result["events"] if e.get("source") == "player_action"
    ]
    assert repeated == []
    assert engine.action_count == actions_after_tick


def test_run_intents_max_slot_defers_intraday_until_day_end():
    engine = _engine(seed=11)
    action_id = engine.available_actions()[0]
    engine.end_day()
    assert engine.action_count == 0

    from campaign.planner import Intent

    engine.intents.items = [
        Intent(
            due_day=2, kind="action", actor="player",
            payload={"action": action_id, "target": ""}, source="player",
            priority=5, due_slot=0,
        ),
        Intent(
            due_day=2, kind="action", actor="player",
            payload={"action": action_id, "target": ""}, source="player",
            due_slot=2,
        ),
    ]

    events = engine.tick(max_slot=SLOT_DAY_EDGE)
    fired_now = [e for e in events if e.get("source") == "player_action"]
    assert len(fired_now) == 1
    assert engine.action_count == 1
    assert [(i.due_day, i.due_slot) for i in engine.intents.items] == [(2, 2)]

    events = engine.tick(max_slot=2)
    fired_wide = [e for e in events if e.get("source") == "player_action"]
    skipped = [e for e in events if e.get("kind") == "intent_skipped"]
    assert fired_wide == []
    assert len(skipped) == 1
    assert engine.action_count == 1
    assert len(engine.intents) == 0

    result = engine.end_day()
    fired_later = [
        e for e in result["events"] if e.get("source") == "player_action"
    ]
    assert fired_later == []
    assert engine.action_count == 1


def test_tick_max_slot_defers_intraday_until_wider_tick():
    action_id = _engine(seed=11).available_actions()[0]

    engine = _engine(seed=11)
    engine.schedule_action(action_id, due_day=2, due_slot=0, priority=5)
    engine.schedule_action(action_id, due_day=2, due_slot=2)
    engine.end_day()
    assert len(engine.intents) == 0
    assert engine.action_count == 1

    engine2 = _engine(seed=11)
    engine2.schedule_action(action_id, due_day=1, due_slot=0, priority=5)
    engine2.schedule_action(action_id, due_day=1, due_slot=2)
    events = engine2.tick(max_slot=SLOT_DAY_EDGE)
    fired = [e for e in events if e.get("source") == "player_action"]
    assert len(fired) == 1
    assert len(engine2.intents) == 1
    events = engine2.tick(max_slot=1)
    assert [e for e in events if e.get("source") == "player_action"] == []
    events = engine2.tick(max_slot=2)
    fired = [e for e in events if e.get("source") == "player_action"]
    skipped = [e for e in events if e.get("kind") == "intent_skipped"]
    assert len(fired) + len(skipped) == 1
    assert len(engine2.intents) == 0
    assert engine2.action_count >= 1
