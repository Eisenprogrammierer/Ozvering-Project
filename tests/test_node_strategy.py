"""Долгосрочные стратегии узлов и расширения рынка труда."""

import copy

import pytest

from campaign.node_strategy import StrategyBook
from campaign.errors import CampaignError
from campaign.world import WorldEngine, load_world


def _engine(seed=7):
    return WorldEngine(load_world(), seed=seed)


def test_world_ships_data_driven_node_strategies():
    world = load_world()
    book = StrategyBook.from_config(world)
    assert book.get("order_consolidation") is not None
    assert book.get("knowledge_reform") is not None
    assert book.get("care_response") is not None
    assert book.get("exchange_stability") is not None
    assert world["strategies_path"].endswith("agora_strategies.json")


def test_strategy_bonus_prefers_its_action_and_reaches_goal():
    engine = _engine()
    node = engine.node("agora_government")
    strategy = engine.strategies.get("order_consolidation")
    state = engine._ensure_strategy_state(node, strategy)

    action = engine.actions["reform"]
    context = engine.node_context("agora_government")
    target = engine.node("agora_ministry_interior")

    assert strategy.progress(node, state) == pytest.approx(0.0)
    assert engine._strategy_bonus(action, context, target) > 0.0
    assert engine._strategy_bonus(
        engine.actions["sabotage"], context, target
    ) == pytest.approx(0.0)

    node["stats"]["legitimacy"] = strategy.target_value()
    assert strategy.progress(node, state) == pytest.approx(1.0)
    event = strategy.advance(node, state, engine.day + 1)
    assert event["event"] == "completed"
    assert state["completed"] is True


def test_strategy_expires_after_horizon_and_logs():
    engine = _engine()
    node = engine.node("agora_government")
    strategy = engine.strategies.get("order_consolidation")
    state = engine._ensure_strategy_state(node, strategy)
    state["start_day"] = engine.day - strategy.horizon_days

    events = engine._advance_strategies()

    assert state["expired"] is True
    assert any(event["strategy"] == strategy.id for event in events)
    assert any(
        entry.get("kind") == "strategy" for entry in engine.log
    )


def test_strategy_progress_survives_snapshot_roundtrip():
    engine = _engine()
    node = engine.node("agora_government")
    strategy = engine.strategies.get("order_consolidation")
    state = engine._ensure_strategy_state(node, strategy)
    state["start_value"] = 0.4

    restored = WorldEngine(load_world(), snapshot=engine.to_dict())
    saved = restored.strategy_state["agora_government"][strategy.id]

    assert saved["start_value"] == pytest.approx(0.4)
    assert restored.strategy_progress()
    assert restored.strategies.get(strategy.id) is not None


def test_strategy_validation_rejects_unknown_action():
    book = StrategyBook(
        [
            {
                "id": "bad",
                "nodes": ["agora_government"],
                "actions": {"missing_action": 1.0},
                "goal": {"stat": "legitimacy", "target": 0.8},
            }
        ]
    )
    with pytest.raises(CampaignError):
        book.validate(
            action_ids={"reform"}, node_ids={"agora_government"}
        )


def test_labor_market_rotates_by_generation_and_respects_quota():
    engine = _engine()
    engine.day = 1
    first = engine.office_options("agora_government")[0]["competition"]
    engine.day = 4
    second = engine.office_options("agora_government")[0]["competition"]

    assert second["generation"] > first["generation"]
    assert second["refresh_in"] >= 1
    assert len(
        {rival["node_id"] for rival in second["rivals"] if rival["node_id"]}
    ) == len(
        [rival for rival in second["rivals"] if rival["node_id"]]
    )


def test_vacancy_board_exposes_stable_public_shape():
    engine = _engine()
    board = engine.vacancy_board("agora_government")

    assert board
    entry = board[0]
    for key in (
        "node_id",
        "node_name",
        "office_id",
        "label",
        "rank",
        "enabled",
        "reason",
        "competition",
    ):
        assert key in entry
    assert entry["competition"]["office_id"] == entry["office_id"]


def test_world_without_labor_market_uses_defaults():
    world = copy.deepcopy(load_world())
    world.pop("labor_market", None)
    engine = WorldEngine(world, seed=7)

    assert engine.labor_market["rivals"] >= 0
    assert engine.office_options("agora_government")[0]["competition"]
