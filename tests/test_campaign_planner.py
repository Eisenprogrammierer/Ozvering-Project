"""Очередь намерений кампании: первый срез real-time-планировщика."""

import pytest

from campaign.planner import (
    MAX_INTENTS,
    Intent,
    IntentQueue,
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
    return WorldEngine(
        load_world(),
        profile=profile,
        node_id="agora_government",
        office_id="head_of_government",
        seed=seed,
    )


def _first_character(engine):
    return engine.characters[engine.character_order[0]]


def test_intent_queue_orders_by_day_and_trims_farthest():
    queue = IntentQueue(limit=3)
    queue.schedule(5, "message", payload={"text": "поздно"})
    queue.schedule(2, "message", payload={"text": "рано"})
    queue.schedule(3, "contact", actor="a")
    assert [item.due_day for item in queue] == [2, 3, 5]

    # Переполнение отбрасывает самые далёкие намерения, близкие остаются.
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
    engine.schedule_intent(engine.day + 1, "message", payload={"text": text})

    engine.end_day()
    assert engine.day == 2
    # Намерение назначено на начало второго дня — исполняется на его ходу.
    result = engine.end_day()

    assert result["ok"] is True
    assert len(engine.intents) == 0
    assert any(
        entry["kind"] == "intent" and text in entry["text"]
        for entry in result["events"]
    )
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

    engine.end_day()
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
    restored.end_day()

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
    engine = _engine()
    character = _first_character(engine)
    character["autonomous"] = True
    character["autonomy_period"] = 1
    before = float(character["affinity"])

    engine.end_day()
    # После первого дня появилось намерение на следующий.
    assert len(engine.intents) == 1
    pending = engine.intents.due(engine.day)[0]
    assert pending.source == "autonomy"
    assert pending.actor == character["id"]

    engine.end_day()
    result = engine.end_day()

    # Старое намерение исполнено, а автономия уже назначила следующее.
    assert any(
        entry["kind"] == "intent" and entry.get("actor") == character["id"]
        for entry in result["events"]
    )
    assert float(character["affinity"]) != pytest.approx(before)
    pending = list(engine.intents)
    assert len(pending) == 1
    assert pending[0].due_day == engine.day
    assert pending[0].source == "autonomy"


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
