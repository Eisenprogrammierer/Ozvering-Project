"""Контракт единого движка эффектов.

Эффекты — единственная точка записи состояния. Тесты держат оба формата:
старый плоский и новый с областями, а также проверяют, что движок не
превращает неизвестную область в актив молча.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.effects import apply_effects
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]


def _campaign(seed=7):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / "empire_campaign.json",
    )
    return AutomataCampaign(generator.generate(seed=seed))


def test_legacy_flat_format_matches_previous_math():
    campaign = _campaign()
    actor = campaign.faction("red")
    target = campaign.faction("blue")
    before = actor.asset("legitimacy")
    target_before = target.asset("cohesion")
    fear_before = target.characters[0].needs["fear"]
    applied = apply_effects(
        actor,
        {
            "self": {"legitimacy": 0.1},
            "target": {"cohesion": -0.05},
            "needs": {"target": {"fear": 0.2}},
        },
        target=target,
        scale=1.0,
    )
    self_delta = applied["assets"][0]
    assert self_delta["scope"] == "self"
    assert self_delta["key"] == "legitimacy"
    assert self_delta["delta"] == pytest.approx(0.1)
    assert actor.asset("legitimacy") > before
    assert target.asset("cohesion") < target_before
    assert target.characters[0].needs["fear"] == pytest.approx(
        min(1.0, fear_before + 0.2)
    )
    assert applied["needs"]


def test_nested_format_applies_beliefs_and_organs():
    campaign = _campaign()
    actor = campaign.faction("red")
    leader = actor.characters[0]
    organ = actor.organs[0]
    organ_before = organ.integrity
    asset_before = actor.asset("legitimacy")
    applied = apply_effects(
        actor,
        {
            "self": {
                "assets": {"legitimacy": 0.05},
                "beliefs": {
                    "add": [
                        {"predicate": "is_legitimate", "value": 0.6}
                    ]
                },
                "organs": {organ.id: {"integrity": -0.2}},
            }
        },
        scale=1.0,
    )
    assert actor.asset("legitimacy") > asset_before
    assert any(
        item.predicate == "is_legitimate" for item in leader.bdi.beliefs
    )
    assert organ.integrity == pytest.approx(max(0.0, organ_before - 0.2))
    assert applied["beliefs"][0]["action"] == "add"


def test_effects_remove_beliefs_and_push_intentions():
    campaign = _campaign()
    actor = campaign.faction("red")
    leader = actor.characters[0]
    subject = leader.campaign_id
    leader.bdi.believe(subject, "trusts", "faction.republic")
    applied = apply_effects(
        actor,
        {
            "self": {
                "beliefs": {
                    "remove": [
                        {
                            "predicate": "trusts",
                            "object": "faction.republic",
                        }
                    ]
                },
                "intentions": {
                    "push": [
                        {
                            "target": "faction.republic",
                            "essence": "coerce",
                        }
                    ]
                },
            }
        },
    )
    assert not any(
        item.predicate == "trusts" for item in leader.bdi.beliefs
    )
    assert leader.bdi.latest_intention().essence == "coerce"
    assert applied["intentions"][0]["action"] == "push"


def test_flags_are_stored_and_survive_save():
    campaign = _campaign()
    actor = campaign.faction("red")
    apply_effects(actor, {"flags": {"amnesty_offered": True}})
    assert actor.flags["amnesty_offered"] is True
    assert campaign.snapshot()["factions"]["red"]["flags"][
        "amnesty_offered"
    ] is True
    saved = campaign.save_snapshot()
    assert saved["factions"]["red"]["flags"]["amnesty_offered"] is True


def test_scale_multiplies_all_numbers():
    campaign = _campaign()
    actor = campaign.faction("red")
    before = actor.asset("legitimacy")
    applied = apply_effects(
        actor, {"self": {"legitimacy": 0.2}}, scale=0.5
    )
    assert applied["assets"][0]["delta"] == pytest.approx(0.1)
    assert actor.asset("legitimacy") > before


def test_unknown_nested_organ_is_reported_not_applied():
    campaign = _campaign()
    actor = campaign.faction("red")
    applied = apply_effects(
        actor, {"self": {"organs": {"missing": {"integrity": -0.5}}}}
    )
    assert applied["ignored"]
    assert applied["ignored"][0]["reason"] == "unknown"
