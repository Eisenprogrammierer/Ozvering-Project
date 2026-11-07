"""Экономика кампании на одной энергии (§7.4 №21–26)."""

import copy

import pytest

from campaign.economy import (
    DEFAULT_MAINTENANCE,
    balance,
    conversion_chain,
    conversion_quote,
    credit_quote,
    energy_price_in_money,
    energy_to_money,
    exchange_quote,
    help_quote,
    maintenance_cost,
    money_to_energy,
    nature_yield,
    poverty_status,
    price_for_effect,
    repair_quote,
    resource_kind,
    rest_quote,
    scaled_cost,
    scaled_effect,
    season_multiplier,
    season_name,
    waste_quote,
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


def _engine(seed=7, economy=None):
    profile = build_player_profile(
        _variables(), biography=load_biography(), seed=seed
    )
    world = copy.deepcopy(load_world())
    if economy is not None:
        world["economy"] = economy
    return WorldEngine(
        world,
        profile=profile,
        node_id="agora_government",
        office_id="head_of_government",
        seed=seed,
    )


# ---------------------------------------------------------------------------
# №21: конверсия, цена, потери
# ---------------------------------------------------------------------------


def test_conversion_quote_is_additive_and_prices_effect():
    report = conversion_quote(10.0, "info")
    assert report["arrived"] == pytest.approx(
        10.0 * report["efficiency"]
    )
    assert report["loss"] + report["entropy"] + report["stored"] == (
        pytest.approx(10.0)
    )
    assert report["waste"] == pytest.approx(
        report["loss"] + report["entropy"]
    )
    # Цена обратна КПД: чтобы доставить 7.5, нужно заплатить 10.
    assert price_for_effect(7.5, "info") == pytest.approx(10.0)
    assert price_for_effect(0.0, "info") == 0.0


def test_conversion_chain_does_not_create_work_from_air():
    chain = conversion_chain(10.0, ("force", "info"))
    assert chain["final"] < 10.0
    assert chain["loss"] + chain["entropy"] > 0.0
    assert chain["waste"] == pytest.approx(
        chain["loss"] + chain["entropy"]
    )
    assert len(chain["steps"]) == 2


def test_waste_quote_keeps_useful_part_separate():
    quote = waste_quote(10.0, "force")
    assert quote["waste"] == pytest.approx(
        quote["loss"] + quote["entropy"]
    )
    assert quote["stored"] >= 0.0
    assert quote["waste"] + quote["stored"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# №22: поддержание, отходы, ремонт
# ---------------------------------------------------------------------------


def test_maintenance_and_repair_are_explicit_costs():
    assert maintenance_cost() == 0.0
    cost = maintenance_cost(
        level=3,
        force=0.8,
        wound=0.5,
        config={
            "base": 1.0,
            "per_level": 0.5,
            "per_force": 2.0,
            "per_wound": 4.0,
        },
    )
    assert cost == pytest.approx(1.0 + 1.5 + 1.6 + 2.0)
    repair = repair_quote(0.25, 10.0)
    assert repair["energy"] == pytest.approx(0.25 * 20.0 + 10.0 * 0.5)
    assert repair["wound_repaired"] == pytest.approx(0.25)
    assert DEFAULT_MAINTENANCE["base"] == 0.0


# ---------------------------------------------------------------------------
# №23: масштаб цены и эффекта
# ---------------------------------------------------------------------------


def test_scaled_cost_and_effect_follow_level_and_resistance():
    base = scaled_cost(10.0)
    assert base == pytest.approx(10.0)
    expensive = scaled_cost(
        10.0,
        level=2,
        force=1.0,
        resistance=0.5,
        config={
            "level": 0.10,
            "force": 0.25,
            "resistance": 0.40,
            "domain": 0.0,
        },
    )
    assert expensive == pytest.approx(10.0 * (1.0 + 0.2 + 0.25 + 0.2))
    full = scaled_effect(1.0, delivered=1.0, amount=1.0)
    assert full == pytest.approx(1.0)
    suppressed = scaled_effect(
        1.0,
        delivered=0.5,
        amount=1.0,
        resistance=1.0,
        config={"resistance": 0.8, "max_suppression": 0.9},
    )
    assert suppressed == pytest.approx(0.5 * 0.2)


# ---------------------------------------------------------------------------
# №24: бедность и клапаны
# ---------------------------------------------------------------------------


def test_poverty_status_is_a_signal_not_a_lock():
    status = poverty_status(10.0, 100.0, 0)
    assert status["strained"] is True
    assert status["exhausted"] is True
    assert status["needs_relief"] is True
    assert status["relief"] == ["rest", "help", "credit"]
    rich = poverty_status(80.0, 100.0, 2)
    assert rich["needs_relief"] is False
    assert rich["relief"] == []


def test_rest_spends_actions_instead_of_creating_them():
    quote = rest_quote(3, 100.0 / 3.0, 50.0, 100.0, wound=0.2)
    assert quote["actions"] == 3
    assert quote["energy_spent"] == pytest.approx(100.0)
    assert quote["health"] > 0.0
    assert quote["force"] > 0.0
    assert quote["wound"] > 0.0


def test_help_requires_trust_and_source_capacity():
    refused = help_quote(0.0, 1.0)
    assert refused["allowed"] is False
    quote = help_quote(
        0.8, 1.0, requested=40.0, max_energy=100.0, source_share=1.0
    )
    assert quote["allowed"] is True
    assert quote["amount"] == pytest.approx(40.0)
    assert quote["wealth_cost"] > 0.0
    assert 0.0 < quote["obligation"] <= 1.0
    capped = help_quote(0.8, 1.0, requested=40.0, max_energy=100.0)
    assert capped["amount"] == pytest.approx(30.0)
    empty = help_quote(0.8, 0.0)
    assert empty["allowed"] is False


def test_credit_adds_interest_and_due_date_is_explicit():
    quote = credit_quote(
        1.0, requested=50.0, max_energy=100.0, source_share=1.0
    )
    assert quote["allowed"] is True
    assert quote["amount"] == pytest.approx(50.0)
    assert quote["obligation"] == pytest.approx(0.55)
    assert quote["interest"] == pytest.approx(0.10)
    capped = credit_quote(1.0, requested=50.0, max_energy=100.0)
    assert capped["amount"] == pytest.approx(45.0)
    empty = credit_quote(0.0)
    assert empty["allowed"] is False


# ---------------------------------------------------------------------------
# №25: деньги, информация, политический капитал
# ---------------------------------------------------------------------------


def test_resource_projection_does_not_create_second_energy():
    assert resource_kind("energy") == "energy"
    assert resource_kind("wealth") == "money"
    assert resource_kind("influence") == "political"
    assert resource_kind("favor") == "political"
    assert resource_kind("evidence") == "information"
    assert resource_kind("unknown") == "unknown"


def test_market_exchange_is_lossy_and_political_is_not_convertible():
    energy = money_to_energy(1.0, max_energy=100.0)
    assert energy == pytest.approx(60.0)
    money = energy_to_money(energy, max_energy=100.0)
    assert money < 1.0
    assert money == pytest.approx(0.45)
    quote = exchange_quote("wealth", "energy", 0.5, max_energy=100.0)
    assert quote["ok"] is True
    assert quote["result"] == pytest.approx(30.0)
    refused = exchange_quote("influence", "energy", 1.0)
    assert refused["ok"] is False
    assert "нет обработчика" in refused["reason"]


# ---------------------------------------------------------------------------
# №26: природа
# ---------------------------------------------------------------------------


def test_nature_work_is_seasonal_lossy_and_reduces_with_damage():
    calm = nature_yield(season=0.6, fertility=0.5)
    harsh = nature_yield(season=1.3, fertility=0.5)
    assert harsh["amount"] > calm["amount"]
    assert harsh["wealth"] > calm["wealth"]
    damaged = nature_yield(season=1.3, fertility=0.5, damage=0.5)
    assert damaged["amount"] < harsh["amount"]
    assert damaged["loss"] + damaged["entropy"] + damaged["stored"] == (
        pytest.approx(damaged["amount"])
    )
    assert season_multiplier(0) == pytest.approx(0.60)
    assert season_multiplier(90) == pytest.approx(1.00)
    assert season_name(0) == "calm"
    assert season_name(90) == "lean"


# ---------------------------------------------------------------------------
# Кампанийный API: отдых, помощь, кредит, ремонт
# ---------------------------------------------------------------------------


def test_campaign_rest_reduces_actions_and_restores_condition():
    engine = _engine()
    engine.player_energy = 100.0
    engine.player_health = 50.0
    engine.injure_player(0.2)
    before_health = engine.player_health
    before_wound = engine.player_wound
    result = engine.rest_player()
    assert result["ok"] is True
    assert engine.actions_left == 0
    assert engine.player_energy == pytest.approx(0.0)
    assert engine.player_health > before_health
    assert engine.player_wound < before_wound


def test_campaign_help_creates_favor_and_spends_node_wealth():
    engine = _engine()
    character = engine.character("mira_svet")
    node = engine.node(character["node_id"])
    character["trust"] = 0.9
    node["stats"]["wealth"] = 0.9
    engine.player_energy = 10.0
    result = engine.request_help("mira_svet", amount=20.0)
    assert result["ok"] is True
    assert engine.player_energy == pytest.approx(30.0)
    assert engine.player_energy < engine.player_max_energy
    assert node["stats"]["wealth"] < 0.9
    obligations = engine.obligation_view("mira_svet")["entries"]
    assert obligations
    assert obligations[0]["kind"] == "favor"
    assert obligations[0]["debtor"] == "player"


def test_campaign_help_refuses_low_trust_or_empty_source():
    engine = _engine()
    character = engine.character("mira_svet")
    character["trust"] = 0.0
    engine.player_energy = 10.0
    result = engine.request_help("mira_svet", amount=20.0)
    assert result["ok"] is False
    assert "доверия" in result["reason"]


def test_campaign_credit_creates_due_debt_with_interest():
    engine = _engine()
    node = engine.node("agora_ministry_finance")
    node["stats"]["wealth"] = 0.9
    engine.player_energy = 0.0
    result = engine.take_credit(
        "agora_ministry_finance", amount=30.0, due_days=5
    )
    assert result["ok"] is True
    assert engine.player_energy == pytest.approx(30.0)
    assert result["due_day"] == engine.day + 5
    obligation = result["obligation"]
    assert obligation["kind"] == "debt"
    assert obligation["due_day"] == engine.day + 5
    assert obligation["amount"] == pytest.approx(30.0 / 100.0 * 1.1)


def test_campaign_credit_refuses_empty_creditor():
    engine = _engine()
    node = engine.node("agora_ministry_finance")
    node["stats"]["wealth"] = 0.0
    engine.player_energy = 0.0
    result = engine.take_credit("agora_ministry_finance", amount=10.0)
    assert result["ok"] is False
    assert "запаса" in result["reason"]


def test_campaign_repair_spends_energy_for_condition():
    engine = _engine()
    engine.injure_player(0.2)
    engine.player_health = 80.0
    engine.player_energy = 50.0
    quote = repair_quote(
        0.2, 20.0, config=engine.economy_config().get("repair") or {}
    )
    result = engine.repair_player()
    assert result["ok"] is True
    assert engine.player_wound == pytest.approx(0.0)
    assert engine.player_health == pytest.approx(100.0)
    assert engine.player_energy == pytest.approx(50.0 - quote["energy"])


# ---------------------------------------------------------------------------
# Сводка и суточное применение
# ---------------------------------------------------------------------------


def test_economy_view_reports_sources_sinks_and_poverty():
    engine = _engine(
        economy={
            "maintenance": {"base": 0.5, "per_force": 1.0},
            "nature": {
                "enabled": True,
                "node": "agora_government",
                "base_work": 10.0,
                "fertility": 0.5,
            },
        }
    )
    engine.player_energy = 10.0
    view = engine.economy_view()
    assert view["sources"]["влияние должности"] > 0.0
    assert view["sinks"]["поддержание героя"] > 0.0
    assert view["poverty"]["strained"] is True
    assert view["nature"]["node"] == "agora_government"
    assert view["resources"]["wealth"]["kind"] == "money"
    assert view["resources"]["influence"]["kind"] == "political"
    assert view["repair"]["energy"] >= 0.0


def test_economy_day_applies_maintenance_nature_and_shortfall():
    engine = _engine(
        economy={
            "maintenance": {
                "base": 2.0,
                "per_level": 1.0,
                "per_force": 5.0,
                "per_wound": 2.0,
            },
            "nature": {
                "enabled": True,
                "node": "agora_government",
                "base_work": 10.0,
                "fertility": 0.5,
            },
        }
    )
    node = engine.node("agora_government")
    engine.player_energy = 5.0
    before_wealth = node["stats"]["wealth"]
    before_health = engine.player_health
    before_standing = engine.player_resources["standing"]
    changed = engine._apply_economy_day()
    assert changed
    assert engine.player_energy == pytest.approx(0.0)
    # Дефицит поддержания превращается в износ, а не в минус.
    assert engine.player_health < before_health
    assert engine.player_resources["standing"] < before_standing
    assert node["stats"]["wealth"] > before_wealth


def test_economy_day_is_noop_without_config():
    engine = _engine()
    assert engine.economy_config() == {}
    assert engine._apply_economy_day() == []


def test_balance_marks_negative_net_as_deficit():
    report = balance({"день": 1.0}, {"ночь": 2.0})
    assert report["source_total"] == pytest.approx(1.0)
    assert report["sink_total"] == pytest.approx(2.0)
    assert report["net"] == pytest.approx(-1.0)


def test_action_economy_view_scales_price_and_effect():
    engine = _engine(
        economy={
            "scaling": {
                "cost": {"level": 0.2, "force": 0.5, "resistance": 0.4},
                "effect": {"resistance": 0.5, "max_suppression": 0.9},
            }
        }
    )
    view = engine.action_economy_view("inspect", "agora_ministry_finance")
    assert view
    assert view["energy_price"] >= view["base_energy"]
    assert view["cost_ratio"] >= 1.0
    assert 0.0 < view["effect_ratio"] <= 1.0
