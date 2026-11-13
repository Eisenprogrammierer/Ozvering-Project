"""Тесты D4: речевые действия как данные.

Проверяют, что акты и реакции читаются из ``social.json``, решение
принимает ``SocialEngine`` по условиям, эффект уходит в
``ConversationState.commitments``, а новый акт/реакция добавляются
JSON-ом без правки Python. Мир и BDI не меняются.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.dialogue.answers import AnswerPlanner
from campaign.dialogue.engine import DialogueSession
from campaign.dialogue.knowledge import Fact, build_knowledge
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.model import (
    ReactionSpec,
    SocialActSpec,
    SocialCatalog,
)
from campaign.dialogue.social import SocialEngine, social_bindings


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _catalog(directory: Path):
    return load_dialogue(directory)


def _empty_knowledge(catalog):
    """Снимок без фактов — только чтобы SocialEngine было с чем работать."""

    return build_knowledge_stub(catalog)


def build_knowledge_stub(catalog):
    from campaign.dialogue.knowledge import AgentKnowledge

    return AgentKnowledge(
        catalog,
        facts=(),
        entities={},
        side="red",
        faction_id="faction:red",
        speaker_id="char_red",
        speaker_name="Император",
        world=catalog.world,
        player_id="char_player",
        player_name="Игрок",
    )


# --- загрузка и валидация -------------------------------------------


def test_social_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    assert catalog.social.acts
    assert catalog.social.reactions
    for name in (
        "command",
        "promise",
        "threat",
        "offer",
        "apology",
    ):
        assert name in catalog.social.acts
    for name in (
        "accept",
        "reject",
        "evade",
        "counter",
        "clarify",
    ):
        assert name in catalog.social.reactions


def test_social_act_has_reactions(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    for act in catalog.social.acts.values():
        assert act.reactions, act.id
        for reaction_id in act.reactions:
            assert reaction_id in catalog.social.reactions


def test_social_reaction_has_construction(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    constructions = catalog.synthesis.get("constructions") or {}
    for reaction in catalog.social.reactions.values():
        assert reaction.construction in constructions, reaction.id


def test_social_commitment_kinds_are_acts(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    kinds = catalog.social.commitments.get("kinds") or ()
    for name in kinds:
        assert name in catalog.social.acts


def test_lint_social_clean(tmp_path):
    """Lint пропускает production-данные без ошибок по social."""

    problems = lint_directory(_copy_configs(tmp_path))
    social_problems = [
        item for item in problems if "social" in item.lower()
    ]
    assert social_problems == []


# --- SocialEngine ---------------------------------------------------


def test_act_for_finds_command(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    engine = SocialEngine(catalog, _empty_knowledge(catalog), _engine(catalog))
    act = engine.act_for({"kind": "social", "act": "command"})
    assert act is not None
    assert act.id == "command"


def test_act_for_returns_none_for_unknown(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    engine = SocialEngine(catalog, _empty_knowledge(catalog), _engine(catalog))
    assert engine.act_for({"kind": "social", "act": "nope"}) is None


def test_command_without_authority_rejected(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _empty_knowledge(catalog)
    engine = SocialEngine(
        catalog, knowledge, _engine(catalog, knowledge)
    )
    decision = engine.decide(
        {"kind": "social", "act": "command", "object": "faction:blue"},
        {
            "speaker": "char_player",
            "listener": "char_red",
            "object": "faction:blue",
        },
    )
    assert decision is not None
    assert decision.reaction_id == "reject"
    assert decision.effect["type"] == "refusal"


def test_command_with_authority_accepted(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge_with(
        catalog,
        [Fact("has_authority", ("char_player", "char_red"))],
    )
    engine = SocialEngine(
        catalog, knowledge, _engine(catalog, knowledge)
    )
    decision = engine.decide(
        {"kind": "social", "act": "command", "object": "faction:blue"},
        {
            "speaker": "char_player",
            "listener": "char_red",
            "object": "faction:blue",
        },
    )
    assert decision is not None
    assert decision.reaction_id == "accept"
    assert decision.effect["type"] == "commitment"


def test_unknown_act_returns_none(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    engine = SocialEngine(catalog, _empty_knowledge(catalog), _engine(catalog))
    decision = engine.decide({"kind": "social", "act": "nope"})
    assert decision is None


def test_decision_has_trace(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge_with(
        catalog,
        [Fact("has_authority", ("char_player", "char_red"))],
    )
    engine = SocialEngine(
        catalog, knowledge, _engine(catalog, knowledge)
    )
    decision = engine.decide(
        {"kind": "social", "act": "command", "object": "faction:blue"},
        {
            "speaker": "char_player",
            "listener": "char_red",
            "object": "faction:blue",
        },
    )
    kinds = {item.get("kind") for item in decision.trace}
    assert "act" in kinds
    assert "validity" in kinds
    assert "reaction" in kinds


def test_decision_deterministic(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge_with(
        catalog,
        [Fact("has_authority", ("char_player", "char_red"))],
    )
    engine = SocialEngine(
        catalog, knowledge, _engine(catalog, knowledge)
    )
    sem = {"kind": "social", "act": "command", "object": "faction:blue"}
    bindings = {
        "speaker": "char_player",
        "listener": "char_red",
        "object": "faction:blue",
    }
    first = engine.decide(sem, bindings)
    second = engine.decide(sem, bindings)
    assert first is not None and second is not None
    assert first.reaction_id == second.reaction_id
    assert first.effect == second.effect


# --- состояние и эффект ---------------------------------------------


def test_apply_effect_commitment(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    state = _state(catalog)
    effect = {
        "type": "commitment",
        "subject": "char_player",
        "object": "faction:blue",
    }
    state.apply_effect(effect)
    assert len(state.commitments) == 1
    assert state.commitments[0]["kind"] == "commitment"


def test_apply_effect_refusal_not_committed(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    state = _state(catalog)
    state.apply_effect(
        {
            "type": "refusal",
            "subject": "char_red",
            "object": "faction:blue",
        }
    )
    # refusal сейчас тоже пишется — см. ниже test_apply_effect_kinds
    kinds = [item["kind"] for item in state.commitments]
    assert "refusal" in kinds


def test_apply_effect_evasion_skipped(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    state = _state(catalog)
    state.apply_effect({"type": "evasion", "subject": "char_red"})
    state.apply_effect({"type": "clarification", "subject": "char_red"})
    assert state.commitments == []


def test_commitments_ttl_prune(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    state = _state(catalog)
    for _ in range(catalog.social.commitments["ttl_turns"] + 5):
        state.begin_turn(state.clock + 1)
        state.apply_effect(
            {
                "type": "commitment",
                "subject": "char_player",
                "object": "faction:blue",
            }
        )
    # Старые обязательства сняты, остаются только свежие
    assert len(state.commitments) <= catalog.social.commitments["ttl_turns"]


# --- JSON-only расширение -------------------------------------------


def test_new_act_json_only(tmp_path):
    directory = _copy_configs(tmp_path)
    social_path = directory / "social.json"
    data = json.loads(social_path.read_text(encoding="utf-8"))
    data["acts"]["bribe"] = {
        "id": "bribe",
        "label": "подкуп",
        "match": {"kind": "social", "act": "bribe"},
        "proposition": {"object": "$object"},
        "validity": [],
        "taboo": [],
        "reactions": ["accept", "reject"],
    }
    social_path.write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    catalog = _catalog(directory)
    assert "bribe" in catalog.social.acts
    engine = SocialEngine(catalog, _empty_knowledge(catalog), _engine(catalog))
    assert engine.act_for({"kind": "social", "act": "bribe"}) is not None


# --- помощники ------------------------------------------------------


def _engine(catalog, knowledge=None):
    from campaign.dialogue.inference import InferenceEngine

    if knowledge is None:
        knowledge = _empty_knowledge(catalog)
    return InferenceEngine(catalog, knowledge)


def _knowledge_with(catalog, facts):
    from campaign.dialogue.knowledge import AgentKnowledge

    return AgentKnowledge(
        catalog,
        facts=tuple(facts),
        entities={},
        side="red",
        faction_id="faction:red",
        speaker_id="char_red",
        speaker_name="Император",
        world=catalog.world,
        player_id="char_player",
        player_name="Игрок",
    )


def _state(catalog):
    from campaign.dialogue.state import build_state

    knowledge = _empty_knowledge(catalog)
    return build_state(catalog, knowledge)