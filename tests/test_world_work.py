"""Дневной мир строит ``Work`` и идёт через общий ``receive``.

Эффекты веток остаются в данных действий для превью (отдельная задача
плана), но исполнение читает обработчик мира. Тест держит оба слоя
синхронными и проверяет совместимый откат для мира без обработчиков.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("numpy")

import campaign.world as world_module
from campaign.handlers import HandlerRegistry
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
    return WorldEngine(
        load_world(),
        profile=build_player_profile(
            _variables(), biography=load_biography(), seed=7
        ),
        node_id="agora_government",
        office_id="head_of_government",
        seed=seed,
    )


def _rules(directory=None):
    directory = Path(directory or world_module.DEFAULT_WORLD_HANDLERS)
    result = {}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        form = str(data.get("form") or path.stem)
        for rule in data.get("rules") or ():
            action_id = str((rule.get("when") or {}).get("id") or "")
            if action_id:
                result[(form, action_id)] = rule
    return result


def test_world_handlers_match_action_effects():
    engine = _engine()
    rules = _rules()
    for action in list(engine.actions.values()) + list(
        engine.character_actions.values()
    ):
        action_id = str(action.get("id") or "")
        form = engine._world_form(action)
        success = (action.get("success") or {}).get("effects") or {}
        failure = (action.get("failure") or {}).get("effects") or {}
        if not success and not failure:
            continue
        rule = rules.get((form, action_id))
        assert rule is not None, (form, action_id)
        assert rule["receiver"]["effect"] == success, (form, action_id)
        assert rule["failure"]["receiver"]["effect"] == failure, (
            form,
            action_id,
        )


def test_player_action_builds_work_and_uses_world_handler(monkeypatch):
    engine = _engine(seed=5)
    calls = []
    original = engine.world_handlers.receive

    def receive(work, plan, faction, target, campaign, success=True):
        calls.append((work.form, plan.capability_id, success))
        return original(
            work, plan, faction, target, campaign, success=success
        )

    monkeypatch.setattr(engine.world_handlers, "receive", receive)
    result = engine.execute("inspect", "knowledge_press")

    assert result["ok"] is True
    assert calls
    assert calls[0][0] == "world"
    assert calls[0][1] == "inspect"


def test_world_without_handlers_falls_back_to_action_effects():
    engine = _engine(seed=3)
    context = engine.player_context()
    target = engine.node("knowledge_press")
    action = engine.actions["inspect"]
    with tempfile.TemporaryDirectory() as directory:
        engine.world_handlers = HandlerRegistry(directory)
        changed = engine._world_effects(
            action, context, target, success=True, is_player=True
        )
    assert changed


def test_world_work_is_deterministic():
    first = _engine(seed=19)
    second = _engine(seed=19)
    result_a = first.execute("inspect", "knowledge_press")
    result_b = second.execute("inspect", "knowledge_press")
    assert result_a == result_b
    assert first.player_resources == second.player_resources
