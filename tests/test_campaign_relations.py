"""Влияние отношений и обязательства кампании (§7.6 №36–38)."""

import pytest

from campaign.obligations import (
    OBLIGATION_FULFILL_TRUST,
    OBLIGATION_KINDS,
    ObligationLedger,
)
from campaign.errors import CampaignError
from campaign.relations import (
    RELATION_EFFECT_LIMIT,
    RELATION_EFFECT_WEIGHTS,
    asymmetry_rows,
    relation_effect,
    relation_effect_view,
)
from campaign.world import (
    WorldEngine,
    build_player_profile,
    load_biography,
    load_world,
)
from campaign.actor import campaign_success_chance


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


def _engine(
    node_id="agora_government", office_id="head_of_government", seed=7
):
    return WorldEngine(
        load_world(),
        profile=_profile(),
        node_id=node_id,
        office_id=office_id,
        seed=seed,
    )


def test_relation_effect_is_bounded_and_direction_aware():
    axes = {"affinity": 1.0, "trust": 1.0, "fear": 1.0, "respect": 1.0}
    for form in RELATION_EFFECT_WEIGHTS:
        value = relation_effect(axes, form)
        assert -RELATION_EFFECT_LIMIT <= value <= RELATION_EFFECT_LIMIT
    trust = {"trust": 1.0}
    assert relation_effect(trust, "info") > 0.0
    assert relation_effect(trust, "force") < 0.0
    fear = {"fear": 1.0}
    assert relation_effect(fear, "force") > 0.0
    assert relation_effect(fear, "info") < 0.0
    assert relation_effect(axes, "unknown") == 0.0
    assert relation_effect({}, "info") == 0.0
    view = relation_effect_view({"affinity": 0.4}, "info")
    assert view["axes"]["affinity"] == pytest.approx(0.4)
    assert view["effects"]["info"] == pytest.approx(0.4 * 0.06)
    assert view["limit"] == RELATION_EFFECT_LIMIT


def test_asymmetry_rows_keep_both_directions_in_axis_order():
    rows = asymmetry_rows(
        {"affinity": 0.5, "trust": -0.2},
        {"affinity": -0.5, "respect": 0.9},
    )
    assert [row[0] for row in rows] == [
        "affinity",
        "trust",
        "fear",
        "respect",
    ]
    assert rows[0][1] == pytest.approx(0.5)
    assert rows[0][2] == pytest.approx(-0.5)
    assert rows[3][2] == pytest.approx(0.9)


def test_action_chance_uses_target_to_actor_axes():
    engine = _engine()
    character = engine.characters[engine.character_order[0]]
    action = engine.character_actions["heart_to_heart"]
    context = engine.player_context()
    success = action.get("success") or {}
    character["fear"] = 0.0
    character["respect"] = 0.0
    low = engine._action_chance(action, character, context, success, True)
    character["fear"] = 1.0
    character["respect"] = 1.0
    high = engine._action_chance(action, character, context, success, True)
    assert high > low
    assert high - low <= RELATION_EFFECT_LIMIT + 1e-9
    axes = engine._relation_axes_to_actor(
        character, context["node"]["id"]
    )
    assert axes["fear"] == pytest.approx(1.0)
    assert relation_effect(axes, "force") > 0.0


def test_node_action_chance_uses_node_axes_not_scalar_projection():
    engine = _engine()
    player_node = engine.node(engine.player_node_id)
    target = next(
        node
        for node in engine.nodes.values()
        if node["id"] != player_node["id"]
    )
    action = engine.actions["inspect"]
    context = engine.player_context()
    success = action.get("success") or {}
    engine.set_relation_axes(
        target["id"],
        player_node["id"],
        {"fear": 0.0, "respect": 0.0, "trust": 0.0, "affinity": 0.0},
    )
    low = engine._action_chance(action, target, context, success, True)
    engine.set_relation_axes(
        target["id"],
        player_node["id"],
        {"fear": 1.0, "respect": 1.0},
    )
    high = engine._action_chance(action, target, context, success, True)
    assert high > low


def test_obligation_ledger_validates_and_roundtrips():
    ledger = ObligationLedger()
    obligation = ledger.add(
        "player", "mira_svet", "favor", 2.0, created_day=1, due_day=4
    )
    assert obligation.id.startswith("obl")
    assert obligation.active()
    assert ledger.summary(2)["open"] == 1
    assert ledger.due(2) == []
    assert ledger.due(4) == [obligation]
    assert ledger.overdue(5) == [obligation]
    assert ledger.for_party("mira_svet") == [obligation]

    payload = ledger.to_list()
    restored = ObligationLedger().load(payload)
    assert restored.to_list() == payload
    fulfilled = restored.fulfill(obligation.id, 3)
    assert fulfilled.status == "fulfilled"
    assert restored.open() == []
    assert restored.fulfill(obligation.id, 4) is None

    for kind in OBLIGATION_KINDS:
        assert ledger.add("a", "b", kind, 1.0, created_day=1)
    with pytest.raises(CampaignError):
        ledger.add("", "b")
    with pytest.raises(CampaignError):
        ledger.add("a", "a")
    with pytest.raises(CampaignError):
        ledger.add("a", "b", "unknown")
    with pytest.raises(CampaignError):
        ledger.add("a", "b", "favor", 0.0)
    with pytest.raises(CampaignError):
        ledger.add("a", "b", "favor", 1.0, created_day=5, due_day=4)


def test_fulfilled_player_obligation_raises_trust_and_persists():
    engine = _engine(seed=11)
    character = engine.characters[engine.character_order[0]]
    before = float(character.get("trust", 0.0))
    obligation = engine.add_obligation(
        "player", character["id"], "favor", 1.0, due_day=engine.day + 3
    )
    assert engine.obligation_view()["summary"]["open"] == 1

    result = engine.fulfill_obligation(obligation["id"])
    assert result["status"] == "fulfilled"
    assert result["fulfilled_day"] == engine.day
    assert float(character.get("trust", 0.0)) > before
    assert result["changes"]
    assert engine.obligation_view()["summary"]["open"] == 0

    snapshot = engine.to_dict()
    assert snapshot["obligations"] == engine.obligations.to_list()
    restored = WorldEngine(load_world(), snapshot=snapshot)
    assert restored.obligations.to_list() == engine.obligations.to_list()
    assert restored.obligation_view()["summary"]["fulfilled"] == 1

    legacy = dict(snapshot)
    legacy.pop("obligations")
    assert WorldEngine(load_world(), snapshot=legacy).obligations.items == []


def test_node_obligation_shifts_creditor_axes_toward_debtor():
    engine = _engine(seed=11)
    source = next(
        node
        for node in engine.nodes.values()
        if node["id"] != engine.player_node_id
    )
    target = next(
        node
        for node in engine.nodes.values()
        if node["id"] not in (engine.player_node_id, source["id"])
    )
    before = engine.relation_axes(source["id"], target["id"])["trust"]
    obligation = engine.add_obligation(
        source["id"], target["id"], "debt", 1.0
    )
    result = engine.fulfill_obligation(obligation["id"])
    after = engine.relation_axes(source["id"], target["id"])["trust"]
    assert after == pytest.approx(before + OBLIGATION_FULFILL_TRUST)
    assert result["changes"]


def test_relation_effect_preserves_core_chance_calibration():
    engine = _engine(seed=11)
    character = engine.characters[engine.character_order[0]]
    action = engine.character_actions["heart_to_heart"]
    context = engine.player_context()
    success = action.get("success") or {}
    character["fear"] = 0.0
    character["respect"] = 0.0
    chance = engine._action_chance(action, character, context, success, True)
    axes = {axis: float(character.get(axis, 0.0)) for axis in (
        "affinity",
        "trust",
        "fear",
        "respect",
    )}
    core = campaign_success_chance(
        float(success.get("chance")) + relation_effect(axes, "force"),
        engine.player,
        character.sync(),
        form="force",
    )
    assert chance == pytest.approx(core)
    assert 0.05 <= chance <= 0.95
