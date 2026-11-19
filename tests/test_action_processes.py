"""Процессы действий: слоты, длительность и завершение во времени.

Мгновенный ``perform`` остаётся legacy-путём. Новый API ``start_action``
занимает слот, списывает цену и применяет эффект только при завершении,
когда мир уже мог измениться. Поэтому предпосылки проверяются повторно.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from campaign.automata import ACTION_PROCESS_DEFAULTS, AutomataCampaign
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
SIDE = "red"


@pytest.fixture(scope="module")
def preset():
    return CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    ).generate(seed=11)


@pytest.fixture
def campaign(preset):
    return AutomataCampaign(preset, seed=11)


def _action(campaign, action_id):
    return campaign.faction(SIDE).action(action_id)


def _process(campaign, process_id):
    return next(
        item for item in campaign.processes if item["id"] == process_id
    )


def test_config_declares_two_slots_and_scaling():
    assert int(ACTION_PROCESS_DEFAULTS["slots"]) == 2
    assert float(ACTION_PROCESS_DEFAULTS["duration_scale"]) > 0
    assert bool(ACTION_PROCESS_DEFAULTS["recheck_on_finish"]) is True


def test_start_action_defers_effect_until_finish(campaign):
    action_id = campaign.available_actions(SIDE)[0]
    log_before = len(campaign.log)

    started = campaign.start_action(SIDE, action_id, duration=10)
    assert started["ok"] is True
    process = started["process"]
    assert process["status"] == "active"
    assert process["remaining"] == pytest.approx(10.0)
    assert started["slots"]["used"] == 1
    assert campaign.slot_state(SIDE)["used"] == 1
    assert len(campaign.log) == log_before

    campaign.advance_time(9.0)
    assert campaign.slot_state(SIDE)["used"] == 1
    assert len(campaign.log) == log_before

    campaign.advance_time(1.5)
    assert campaign.slot_state(SIDE)["used"] == 0
    assert len(campaign.log) == log_before + 1
    assert _process(campaign, process["id"])["status"] == "done"
    assert campaign.log[-1]["action_id"] == action_id


def test_two_slots_limit_concurrent_work(campaign):
    available = campaign.available_actions(SIDE)
    assert len(available) >= 2
    first = campaign.start_action(SIDE, available[0], duration=10)
    second = campaign.start_action(SIDE, available[1], duration=10)
    assert first["ok"] is True and second["ok"] is True
    assert campaign.slot_state(SIDE) == {
        "side": SIDE,
        "slots": 2,
        "used": 2,
        "free": 0,
    }

    blocked = campaign.start_action(SIDE, available[2], duration=10)
    assert blocked["ok"] is False
    assert "слот" in blocked["reason"]


def test_same_action_cannot_run_twice(campaign):
    action_id = campaign.available_actions(SIDE)[0]
    assert campaign.start_action(SIDE, action_id, duration=10)["ok"]
    duplicate = campaign.start_action(SIDE, action_id, duration=10)
    assert duplicate["ok"] is False
    assert "уже выполняется" in duplicate["reason"]


def test_scenario_can_override_slots_and_duration(preset):
    data = copy.deepcopy(preset.as_dict())
    data["scenario"]["action_process"] = {
        "slots": 1,
        "duration_scale": 2.0,
    }
    campaign = AutomataCampaign(data, seed=11)
    assert campaign.action_slots == 1
    action_id = campaign.available_actions(SIDE)[0]
    action = _action(campaign, action_id)
    action.pop("duration", None)
    action["template"] = dict(action.get("template") or {}, duration=3.0)
    assert campaign._action_duration(action) == pytest.approx(6.0)
    available = campaign.available_actions(SIDE)
    first = campaign.start_action(SIDE, available[0], duration=1)
    assert first["ok"] is True
    second = campaign.start_action(SIDE, available[1], duration=1)
    assert second["ok"] is False


def test_duration_comes_from_action_template_and_scale(campaign):
    action_id = campaign.available_actions(SIDE)[0]
    action = _action(campaign, action_id)
    action.pop("duration", None)
    action["template"] = dict(action.get("template") or {}, duration=1.0)
    process = campaign.start_action(SIDE, action_id)["process"]
    assert process["duration"] == pytest.approx(
        float(campaign.action_process["duration_scale"])
    )

    explicit = campaign._action_duration(action, duration=3)
    assert explicit == pytest.approx(3.0)


def test_failed_recheck_cancels_and_refunds_cost(campaign):
    action_id = campaign.available_actions(SIDE)[0]
    action = _action(campaign, action_id)
    action["cost"] = {"legitimacy": 0.05}
    faction = campaign.faction(SIDE)
    started = campaign.start_action(SIDE, action_id, duration=5)
    assert started["ok"] is True
    after_cost = faction.asset("legitimacy")

    action["requires"] = {"min_turn": campaign.turn + 100}
    campaign.advance_time(6.0)

    process = _process(campaign, started["process"]["id"])
    assert process["status"] == "cancelled"
    assert "доступно с цикла" in process["reason"]
    assert process["cost"] == {"legitimacy": pytest.approx(0.05)}
    # Возврат идёт через apply_asset_delta: производные активы не
    # обещают точную обратимость, но цена не должна пропасть.
    assert faction.asset("legitimacy") > after_cost
    assert campaign.slot_state(SIDE)["used"] == 0


def test_snapshot_restores_active_process_and_finishes(preset):
    campaign = AutomataCampaign(preset, seed=11)
    action_id = campaign.available_actions(SIDE)[0]
    started = campaign.start_action(SIDE, action_id, duration=10)
    assert started["ok"] is True

    restored = AutomataCampaign(preset, snapshot=campaign.save_snapshot())
    assert restored.slot_state(SIDE)["used"] == 1
    assert restored.processes[0]["remaining"] == pytest.approx(10.0)

    restored.advance_time(11.0)
    assert restored.slot_state(SIDE)["used"] == 0
    assert restored.processes[0]["status"] == "done"
    assert restored.log[-1]["action_id"] == action_id


def test_legacy_perform_stays_instant(campaign):
    action_id = campaign.available_actions(SIDE)[0]
    log_before = len(campaign.log)
    result = campaign.perform(SIDE, action_id)
    assert result["ok"] is True
    assert len(campaign.log) == log_before + 1
    assert campaign.slot_state(SIDE)["used"] == 0


def test_advance_time_moves_world_without_end_turn(campaign):
    """Мир идёт по физическому времени, а не по кнопке «завершить ход».

    Организационный цикл, ИИ и организации обновляются внутри
    ``advance_time``. ``end_turn`` не вызывается, но кампания всё равно
    должна сдвинуться: иначе свободный режим остаётся TBS-игрой.
    """
    campaign.ensure_clock()
    turn_before = campaign.turn
    history_before = len(campaign.history)
    log_before = len(campaign.log)
    snapshots_before = {
        side: bool(faction.organization_snapshot)
        for side, faction in campaign.factions.items()
    }

    campaign.advance_time(campaign.organization_interval_seconds)

    assert campaign.turn > turn_before
    assert len(campaign.history) == history_before + 1

    ai_entries = [
        entry
        for entry in campaign.log[log_before:]
        if entry.get("actor_side")
        and entry["actor_side"] != campaign.player_side
    ]
    ai_processes = [
        process
        for process in campaign.processes
        if process.get("side") != campaign.player_side
    ]
    assert ai_entries or ai_processes

    assert any(
        faction.organization_snapshot and not snapshots_before[side]
        for side, faction in campaign.factions.items()
    )
    # Часы активированы, но цикл не переключался вручную.
    assert campaign.actions_left >= 0
