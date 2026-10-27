from pathlib import Path

import pytest

from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog
from campaign.strategy import StrategyEngine, StrategyError, load_strategy

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = "configs/campaigns/agora_charter.json"
CONFIG = "configs/strategy/agora_charter.json"


def _preset(faction_id="faction_red"):
    catalog = RoleCatalog.load()
    generator = CampaignPresetGenerator(
        catalog=catalog, template_path=TEMPLATE
    )
    return generator.generate(
        role_id="faction_leader",
        seed=7,
        player_faction_id=faction_id,
    )


def _engine(faction_id="faction_red"):
    return StrategyEngine(
        load_strategy(CONFIG),
        preset=_preset(faction_id),
    )


def test_strategy_config_exposes_entities_actions_and_consequences():
    data = load_strategy(CONFIG)
    types = {item["type"] for item in data["entities"]}
    assert {"organization", "asset", "institution"} <= types
    assert data["character_stats"]
    actions = {item["id"]: item for item in data["actions"]}
    assert {"negotiate", "appoint", "reform", "ratify"} <= set(actions)
    for action in actions.values():
        assert action.get("target_types")
        assert action.get("description")
        assert "success" in action or "failure" in action
    assert actions["negotiate"]["success"]["text"]
    assert actions["negotiate"]["failure"]["text"]
    assert actions["negotiate"]["delayed"]["text"]


def test_strategy_template_is_required_and_reports_errors():
    with pytest.raises(StrategyError):
        load_strategy("configs/strategy/missing.json")


def test_strategic_preset_has_civilian_entities_and_no_units():
    preset = _preset()
    assert preset.scenario["mode"] == "strategy"
    assert preset.scenario["units"] == []
    assert preset.scenario["groups"] == {"red": 2, "blue": 2}
    assert preset.summary()["companies"] == {}
    assert len(preset.characters) == 16
    assert preset.player_character["post"] == "Первое лицо союза"
    assert all(
        "рот" not in character["post"].lower()
        for character in preset.characters
    )


def test_strategy_engine_builds_available_entities_and_actions():
    engine = _engine()
    assert engine.day == 1
    assert engine.actions_left == 3
    assert engine.resource("charter") == pytest.approx(0.12)
    types = {entity["type"] for entity in engine.sorted_entities()}
    assert {"character", "organization", "asset", "institution"} <= types
    asset = next(
        entity
        for entity in engine.sorted_entities()
        if entity["id"] == "press"
    )
    ids = {item["id"] for item in engine.action_options(asset["id"])}
    assert {"public_address", "intelligence", "allocate"} <= ids
    assert "negotiate" not in ids


def test_strategy_preview_hides_inapplicable_target_stats():
    engine = _engine()
    preview = engine.preview("allocate", "press")
    assert preview["immediate"] == []


def test_strategy_preview_and_execution_change_state():
    engine = _engine()
    entity = engine.entity("press")
    preview = engine.preview("public_address", entity["id"])
    assert preview["cost"] == ["Влияние −4%"]
    assert preview["success_text"]
    assert preview["failure_text"]
    assert preview["delayed_text"]
    before = engine.resource("legitimacy")
    result = engine.execute("public_address", entity["id"])
    assert result["ok"]
    assert result["outcome"] in ("success", "failure")
    assert engine.actions_left == 2
    assert engine.last_result == result
    assert engine.resource("legitimacy") != pytest.approx(before)
    assert engine.entity("press")["stats"]["control"] >= 0.0


def test_strategy_action_cooldown_and_end_day():
    engine = _engine()
    entity = engine.entity("press")
    assert engine.execute("public_address", entity["id"])["ok"]
    option = next(
        item
        for item in engine.action_options(entity["id"])
        if item["id"] == "public_address"
    )
    assert not option["enabled"]
    assert "повтор" in option["reason"]
    day_result = engine.end_day()
    assert day_result["ok"]
    assert engine.day == 2
    assert engine.actions_left == engine.actions_per_day
    assert engine.resource("influence") > 0.0


def test_strategy_ratify_wins_and_snapshot_roundtrip():
    engine = _engine()
    engine.resources["charter"] = 0.7
    engine.resources["legitimacy"] = 0.7
    engine.resources["cohesion"] = 0.7
    engine.resources["influence"] = 0.7
    engine.entity("charter_commission")["stats"]["support"] = 0.6
    engine.actions["ratify"]["success"]["chance"] = 1.0
    result = engine.execute("ratify", "charter_commission")
    assert result["ok"]
    assert engine.outcome == "win"
    assert engine.finished is True
    snapshot = engine.to_dict()
    restored = StrategyEngine(
        load_strategy(CONFIG),
        preset=_preset(),
        snapshot=snapshot,
    )
    assert restored.outcome == "win"
    assert restored.day == engine.day
    assert restored.resources["charter"] == pytest.approx(
        engine.resources["charter"]
    )
    assert restored.cooldowns == engine.cooldowns


def test_strategy_losing_condition_and_day_limit():
    engine = _engine()
    engine.resources["legitimacy"] = 0.1
    engine.end_day()
    assert engine.outcome == "lose"
    assert engine.finished is True


def test_strategy_blue_player_side_keeps_blue_entities_first():
    engine = _engine("faction_blue")
    first = engine.sorted_entities()[0]
    assert first["side"] == "blue"
    assert engine.resource("charter") == pytest.approx(0.14)
