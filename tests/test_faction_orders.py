"""Нисходящий приказ «фракция → персонаж» (G-14).

Приказы — данные ``order_model.orders``. Игрок и ИИ идут одним путём:
требования → эффекты персонажу → отношения → цена → перезарядка.
"""

from __future__ import annotations

from campaign import content_lint
from campaign.automata import AutomataCampaign


def _preset():
    return {
        "title": "Приказы",
        "scenario": {
            "mode": "automata",
            "player_side": "red",
            "enemy_side": "blue",
            "order_model": {
                "enabled": True,
                "interval": 1,
                "max_per_tick": 1,
                "cooldown": 2,
                "recipient": "priority",
                "orders": [
                    {
                        "id": "steady",
                        "label": "Спокойствие",
                        "description": "Командир гасит страх.",
                        "priority": 1.0,
                        "cooldown": 2,
                        "recipient": "priority",
                        "effects": {
                            "needs": {"fear": -0.2, "anxiety": -0.1},
                            "morale": {"amount": 5.0},
                        },
                        "relations": {
                            "source": "faction",
                            "axes": {"trust": 0.1, "fear": 0.05},
                        },
                    },
                    {
                        "id": "push",
                        "label": "Вперёд",
                        "priority": 0.4,
                        "recipient": "all",
                        "when": [
                            {
                                "kind": "asset",
                                "key": "supply",
                                "op": ">=",
                                "value": 0.9,
                            }
                        ],
                        "effects": {"needs": {"fatigue": 0.1}},
                    },
                ],
            },
        },
        "factions": [
            {
                "side": "red",
                "id": "faction_red",
                "name": "Красные",
                "assets": {"fear": 0.5, "morale": 0.6},
            },
            {
                "side": "blue",
                "id": "faction_blue",
                "name": "Синие",
                "assets": {"fear": 0.5, "morale": 0.6},
            },
        ],
        "characters": [
            {
                "id": "red_leader",
                "side": "red",
                "name": "Красный вождь",
                "is_faction_leader": True,
                "needs": {"fear": 0.8},
            },
            {
                "id": "blue_leader",
                "side": "blue",
                "name": "Синий вождь",
                "is_faction_leader": True,
                "needs": {"fear": 0.8, "anxiety": 0.7},
            },
        ],
    }


def _campaign():
    return AutomataCampaign(_preset(), seed=7)


def test_order_options_come_from_data_and_explain_availability():
    campaign = _campaign()
    options = campaign.order_options("blue")
    assert [item["id"] for item in options] == ["steady", "push"]
    steady = next(item for item in options if item["id"] == "steady")
    push = next(item for item in options if item["id"] == "push")
    assert steady["enabled"]
    assert not push["enabled"]
    assert "нужно" in push["reason"]


def test_issue_order_targets_character_and_writes_relations():
    campaign = _campaign()
    character = campaign.faction("blue").character("blue_leader")
    fear_before = character.needs["fear"]
    result = campaign.issue_order("blue", "steady")
    assert result["ok"], result
    assert result["characters"] == [
        {"id": "blue_leader", "name": "Синий вождь"}
    ]
    assert character.needs["fear"] < fear_before
    assert character.morale > 60.0
    assert campaign.relations.value(
        "faction_blue", "blue_leader", "trust"
    ) > 0.0
    assert campaign.faction("blue").last_order["order_id"] == "steady"
    reopened = campaign.issue_order("blue", "steady")
    assert not reopened["ok"]
    assert "перезарядка" in reopened["reason"]


def test_ai_issues_orders_but_player_faction_does_not():
    campaign = _campaign()
    campaign.turn = 1
    campaign._tick_organizations()
    blue = campaign.faction("blue")
    red = campaign.faction("red")
    assert blue.last_order["order_id"]
    assert not red.last_order
    assert any(
        event["kind"] == "order" and event["side"] == "blue"
        for event in campaign.events
    )


def test_order_snapshot_keeps_cooldowns_and_last_order():
    campaign = _campaign()
    campaign.issue_order("blue", "steady")
    snapshot = campaign.save_snapshot()
    restored = AutomataCampaign(_preset(), seed=7, snapshot=snapshot)
    blue = restored.faction("blue")
    assert blue.last_order["order_id"] == "steady"
    assert blue.order_cooldowns["steady"] == campaign.turn
    again = restored.issue_order("blue", "steady")
    assert not again["ok"]
    assert "перезарядка" in again["reason"]


def test_order_lint_reports_unknown_effect_and_bad_cost():
    defaults = {
        "asset_labels": {"legitimacy": "законность"},
        "faction_state": {"assets": {}},
        "organ_kinds": {},
        "order_model": {
            "orders": [
                {
                    "id": "bad",
                    "effects": {"teleport": {}},
                    "cost": {"supply": -1},
                }
            ]
        },
    }
    problems = content_lint.check_defaults(defaults, {"factions": {}})
    assert any("teleport" in item for item in problems)
    assert any("отрицательной" in item for item in problems)
