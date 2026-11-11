"""Контракт BDI: тройки убеждений, пары намерений, желания и состояния.

Тесты держат границу «данные — в JSON, алгоритмы — в Python»: они не
переписывают 16 желаний, а проверяют, что загрузчик читает их, что
триплет/дуплет нельзя испортить и что пренебрежение желанием бьёт по
силе, энергии и соседним желаниям.
"""

from __future__ import annotations

import json

import pytest

import bdi
import character_traits as traits


@pytest.fixture(scope="module")
def config():
    return bdi.load_bdi()


@pytest.fixture(scope="module")
def trait_model():
    return traits.load_traits()


def _state(config, **needs):
    return bdi.BDIState(
        character_id="actor-1",
        config=config,
        needs=needs,
    )


def test_bdi_config_has_exactly_sixteen_canonical_needs(config):
    assert tuple(config.needs) == bdi.NEEDS
    assert len(config.needs) == 16
    assert config.death["metric"] == "force"
    assert config.predicates
    assert config.essences


def test_bdi_rejects_extra_or_missing_needs():
    raw = json.loads(bdi.default_bdi_path().read_text(encoding="utf-8"))
    raw["needs"].pop("hunger")
    with pytest.raises(bdi.BDIError):
        bdi.BDIConfig(raw)

    raw = json.loads(bdi.default_bdi_path().read_text(encoding="utf-8"))
    raw["needs"]["extra"] = dict(raw["needs"]["hunger"])
    with pytest.raises(bdi.BDIError):
        bdi.BDIConfig(raw)


def test_death_metric_must_be_force():
    raw = json.loads(bdi.default_bdi_path().read_text(encoding="utf-8"))
    raw["death"]["metric"] = "health"
    with pytest.raises(bdi.BDIError):
        bdi.BDIConfig(raw)


def test_spillover_references_known_needs():
    raw = json.loads(bdi.default_bdi_path().read_text(encoding="utf-8"))
    raw["needs"]["hunger"]["spillover"]["unknown"] = 0.5
    with pytest.raises(bdi.BDIError):
        bdi.BDIConfig(raw)


def test_belief_roundtrips_and_requires_subject_and_predicate():
    belief = bdi.Belief("actor-1", "trusts", "actor-2")
    assert belief.as_tuple() == ("actor-1", "trusts", "actor-2")
    assert bdi.Belief.from_data(["actor-1", "trusts", "actor-2"]) == belief
    assert bdi.Belief.from_data(belief.as_dict()) == belief
    with pytest.raises(bdi.BDIError):
        bdi.Belief.from_data({"subject": "actor-1"})
    with pytest.raises(bdi.BDIError):
        bdi.Belief("", "trusts", "actor-2")


def test_predicate_object_rules_come_from_content(config):
    assert config.predicate_object_rule("trusts") == "required"
    assert config.predicate_object_rule("is_legitimate") == "forbidden"
    with pytest.raises(bdi.BDIError):
        config.validate_belief({"subject": "a", "predicate": "trusts"})
    with pytest.raises(bdi.BDIError):
        config.validate_belief(
            {"subject": "a", "predicate": "is_legitimate", "object": "a"}
        )
    property_belief = config.validate_belief(
        {"subject": "a", "predicate": "is_legitimate"}
    )
    assert property_belief.object == ""


def test_belief_value_and_ttl_are_carried(config):
    state = _state(config)
    state.believe(
        "actor-1",
        "trusts",
        "actor-2",
        value=0.5,
        confidence=0.4,
        source="rumor",
        ttl=2.0,
    )
    belief = state.beliefs[0]
    assert belief.value == pytest.approx(0.5)
    assert belief.confidence == pytest.approx(0.4)
    assert belief.source == "rumor"
    assert belief.ttl == pytest.approx(2.0)
    restored = bdi.Belief.from_data(belief.as_dict())
    assert restored == belief


def test_belief_value_uses_strength_and_confidence(config):
    weak = _state(config)
    weak.believe(
        "actor-1", "trusts", "actor-2", value=0.2, confidence=0.5
    )
    strong = _state(config)
    strong.believe("actor-1", "trusts", "actor-2")
    assert strong.belief_value("trusts", "actor-2") > weak.belief_value(
        "trusts", "actor-2"
    )


def test_decay_beliefs_drops_expired_and_lowers_confidence(config):
    state = _state(config)
    state.believe("actor-1", "trusts", "actor-2", ttl=1.0)
    state.believe("actor-1", "is_legitimate")
    state.decay_beliefs(0.5)
    assert [item.ttl for item in state.beliefs] == [pytest.approx(0.5), None]
    state.decay_beliefs(1.0)
    assert [item.predicate for item in state.beliefs] == ["is_legitimate"]
    assert state.beliefs[0].confidence == pytest.approx(0.925)


def test_intention_is_a_duplet_with_derived_target_kind():
    need = bdi.Intention("hunger", "eat")
    assert need.as_tuple() == ("hunger", "eat")
    assert need.target_kind == "need"
    assert need.need == "hunger"

    character = bdi.Intention("character:actor-2", "befriend")
    assert character.target_kind == "character"
    assert character.target_id == "actor-2"

    automaton = bdi.Intention("automaton:gate", "probe")
    assert automaton.target_kind == "automaton"

    plain = bdi.Intention("actor-3", "attack")
    assert plain.target_kind == "automaton"
    assert plain.target_id == "actor-3"

    with pytest.raises(bdi.BDIError):
        bdi.Intention("actor-3", "")


def test_believe_replaces_same_subject_predicate_and_forgets(config):
    state = _state(config)
    state.believe("actor-1", "trusts", "actor-2")
    state.believe("actor-1", "trusts", "actor-3")
    assert [item.object for item in state.beliefs] == ["actor-3"]
    assert state.beliefs_about("actor-1") == state.beliefs
    assert state.beliefs_about("actor-3") == state.beliefs

    removed = state.forget("actor-1", "trusts")
    assert len(removed) == 1
    assert state.beliefs == []


def test_intention_history_is_bounded_by_config(config):
    state = _state(config)
    for index in range(config.history + 5):
        state.intend("hunger", "eat")
    assert len(state.intentions) == config.history
    assert state.should("eat")
    assert state.latest_intention().essence == "eat"


def test_seed_keeps_multiple_objects_for_one_predicate(config):
    state = _state(config)
    state.seed(
        beliefs=[
            {"subject": "actor-1", "predicate": "trusts", "object": "actor-2"},
            {"subject": "actor-1", "predicate": "trusts", "object": "actor-3"},
            {"subject": "actor-1", "predicate": "trusts", "object": "actor-2"},
        ]
    )
    assert sorted(item.object for item in state.beliefs) == [
        "actor-2",
        "actor-3",
    ]


def test_seed_accepts_property_beliefs_without_object(config):
    state = _state(config)
    state.seed(
        beliefs=[
            {
                "subject": "faction.empire",
                "predicate": "is_legitimate",
                "source": "content",
                "value": 0.9,
                "confidence": 0.8,
            }
        ]
    )
    belief = state.beliefs[0]
    assert belief.object == ""
    assert belief.source == "content"
    assert belief.value == pytest.approx(0.9)
    assert state.belief_value("is_legitimate") > 0.0


def test_seed_makes_content_intention_current(config):
    state = _state(config)
    state.seed(intentions=[{"target": "faction.republic", "essence": "coerce"}])
    latest = state.latest_intention()
    assert latest.target == "faction.republic"
    assert latest.target_kind == "automaton"
    assert latest.essence == "coerce"


def test_choose_intention_respects_content_target(config):
    state = _state(config, hunger=1.0)
    intention = state.choose_intention(
        context={"target": "faction.republic", "preferred": "coerce"}
    )
    assert intention.target == "faction.republic"
    assert intention.essence == "coerce"


def test_weighted_desires_use_needs_and_trait_coefficients(
    config, trait_model
):
    state = _state(config, hunger=0.8, knowledge=0.5)
    state.traits = {"curiosity": 0.0}
    low = state.weighted_desires(trait_model)
    state.traits = {"curiosity": 1.0}
    high = state.weighted_desires(trait_model)
    assert high["knowledge"] > low["knowledge"]
    assert high["hunger"] == pytest.approx(low["hunger"])


def test_neglect_pressure_only_grows_after_threshold(config):
    hungry = _state(config, hunger=0.9)
    calm = _state(config, hunger=0.1)
    assert hungry.neglect_pressure()["force"] > 0.0
    assert hungry.neglect_pressure()["energy"] > 0.0
    assert calm.neglect_pressure() == {"force": 0.0, "energy": 0.0}

    sick = _state(config)
    sick.infect(0.8)
    pressure = sick.neglect_pressure()
    assert pressure["force"] > 0.0
    assert pressure["energy"] > 0.0


def test_tick_spills_neglect_into_other_needs_and_drains_force(config):
    hungry = _state(config, hunger=1.0)
    calm = _state(config, hunger=0.0)
    hungry_delta = hungry.tick(seconds=1800)
    calm_delta = calm.tick(seconds=1800)

    assert hungry_delta["force"] < 0.0
    assert hungry_delta["energy"] < 0.0
    assert hungry_delta["needs"]["fatigue"] > calm_delta["needs"]["fatigue"]
    assert hungry_delta["needs"]["health"] > calm_delta["needs"]["health"]


def test_satisfy_restores_force_and_energy(config):
    state = _state(config, hunger=1.0)
    result = state.satisfy({"hunger": 0.5})
    assert result["restored"]["hunger"] == pytest.approx(0.5)
    assert result["force"] > 0.0
    assert result["energy"] > 0.0
    assert state.needs["hunger"] == pytest.approx(0.5)


def test_conditions_are_bdi_state_not_automaton_metrics(config):
    state = _state(config)
    assert state.infect(0.4) == pytest.approx(0.4)
    assert state.injure(0.3) == pytest.approx(0.3)
    assert state.is_sick()
    assert state.is_wounded()
    assert state.condition_work_factor() < 1.0

    state.treat(10.0)
    state.treat_wound(10.0)
    assert not state.is_sick()
    assert not state.is_wounded()


def test_choose_intention_returns_need_duplet(config):
    state = _state(config, hunger=1.0)
    intention = state.choose_intention()
    assert intention.target == "hunger"
    assert intention.essence == "eat"

    preferred = state.choose_intention(
        context={"preferred": "learn", "forbidden": ("eat",)}
    )
    assert preferred.essence == "learn"
    assert state.should("learn")


def test_state_dict_roundtrip_preserves_bdi(config):
    state = _state(config, hunger=0.8)
    state.believe("actor-1", "trusts", "actor-2")
    state.intend("hunger", "eat")
    state.infect(0.25)

    restored = _state(config)
    restored.load_state_dict(state.state_dict())
    assert restored.needs == state.needs
    assert restored.beliefs == state.beliefs
    assert restored.intentions == state.intentions
    assert restored.conditions == state.conditions
    assert restored.snapshot()["needs"]["hunger"] == pytest.approx(0.8)
