"""Тесты D3.2/D6.2: контрфакты, отрицание и «то»-следствие.

Проверяют, что движок собирает контрмодель только из whitelist-а,
честно различает ``changed`` / ``unchanged`` / ``unknown``, не мутирует
исходное знание, а предикаты разбора резолвятся в отношения мира через
данные ``world.predicate_relations``. Отдельно проверяются D6.2a
(перестановка ``remove``/``add`` при отрицании) и D6.2b (следствие
«то …» как цель сравнения).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campaign.dialogue.answers import AnswerPlanner
from campaign.dialogue.counterfactual import CounterfactualEngine
from campaign.dialogue.knowledge import AgentKnowledge, Fact
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.parser import ChartParser
from campaign.dialogue.style import StyleEngine


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _catalog(directory: Path):
    return load_dialogue(directory)


def _knowledge(catalog, facts=()):
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


def _planner(catalog, facts=(), style_id="neutral"):
    knowledge = _knowledge(catalog, facts)
    style_engine = StyleEngine(catalog)
    style = style_engine.profile(style_id)
    persona = catalog.personas.get("default") or list(
        catalog.personas.values()
    )[0]
    planner = AnswerPlanner(
        catalog, knowledge, persona, style_engine=style_engine
    )
    planner.set_style(style)
    return planner


def _assert_sem(predicate, subject, obj, negated=False):
    item = {
        "kind": "assert",
        "predicate": predicate,
        "subject": {"head": {"entity": subject}},
        "object": {"head": {"entity": obj}},
    }
    if negated:
        item["negated"] = True
    return item


def _with_sem(predicate, subject, obj, negated=False):
    item = {
        "kind": "assert",
        "predicate": predicate,
        "subject": {"head": {"entity": subject}},
        "object": {
            "kind": "pp",
            "prep": "with",
            "object": {"head": {"entity": obj}},
        },
    }
    if negated:
        item["negated"] = True
    return item


def _have_sem(subject, obj, negated=False):
    item = {
        "kind": "assert",
        "have": True,
        "subject": {"head": {"entity": subject}},
        "object": {"head": {"entity": obj}},
    }
    if negated:
        item["negated"] = True
    return item


def _counterfactual(antecedent, consequent=None):
    sem = {"kind": "counterfactual", "antecedent": antecedent}
    if consequent is not None:
        sem["consequent"] = consequent
    return sem


# --- данные и линтер ------------------------------------------------


def test_counterfactual_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    spec = catalog.counterfactual
    assert spec is not None
    assert "at_war_with" in spec.relations
    assert "has_organ" in spec.relations
    assert spec.max_steps >= 1
    assert spec.outcomes.get("changed")


def test_predicate_relations_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    table = catalog.world.get("predicate_relations") or {}
    believe = table.get("believe") or {}
    assert believe.get("relation") == "considers_outlaw"
    assert believe.get("remove", {}).get("rel") == "belief"
    fight = table.get("fight") or {}
    assert fight.get("relation") == "at_war_with"


def test_lint_counterfactual_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    relevant = [
        item
        for item in problems
        if "counterfactual" in item.lower()
        or "predicate_relations" in item
    ]
    assert relevant == []


def test_lint_reports_broken_predicate_relation(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "world.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["predicate_relations"]["believe"]["relation"] = "missing_rel"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    problems = lint_directory(directory)
    broken = [
        item for item in problems if "predicate_relations" in item
    ]
    assert broken
    assert "missing_rel" in broken[0]


# --- исходы движка --------------------------------------------------


def test_changed_when_supporting_fact_removed(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog, [Fact("at_war_with", ("faction:red", "faction:blue"))]
    )
    engine = CounterfactualEngine(catalog, knowledge)
    result = engine.compare(
        "at_war_with",
        ("faction:red", "faction:blue"),
        remove=[Fact("at_war_with", ("faction:red", "faction:blue"))],
    )
    assert result.outcome == "changed"
    assert result.removed
    assert result.differences
    assert result.construction == "cf_changed"


def test_unchanged_when_target_is_independent(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog,
        [
            Fact("at_war_with", ("faction:red", "faction:blue")),
            Fact("asset", ("faction:red", "gold", "5")),
        ],
    )
    engine = CounterfactualEngine(catalog, knowledge)
    result = engine.compare(
        "asset",
        ("faction:red", "gold", "5"),
        remove=[Fact("at_war_with", ("faction:red", "faction:blue"))],
    )
    assert result.outcome == "unchanged"
    assert result.differences == ()
    assert result.construction == "cf_unchanged"


def test_unknown_when_no_proof_on_both_sides(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(catalog, [])
    engine = CounterfactualEngine(catalog, knowledge)
    result = engine.compare(
        "at_war_with", ("faction:red", "faction:green")
    )
    assert result.outcome == "unknown"
    assert result.construction == "cf_unknown"


def test_whitelist_ignores_unlisted_relation(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    fact = Fact("located_at", ("faction:red", "столица"))
    knowledge = _knowledge(catalog, [fact])
    engine = CounterfactualEngine(catalog, knowledge)
    assert "located_at" not in engine.allowed
    result = engine.compare(
        "located_at",
        ("faction:red", "столица"),
        remove=[fact],
    )
    assert result.outcome == "unchanged"
    assert result.removed == ()
    assert result.differences == ()


def test_compare_does_not_mutate_knowledge(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    fact = Fact("at_war_with", ("faction:red", "faction:blue"))
    knowledge = _knowledge(catalog, [fact])
    before = knowledge.facts
    engine = CounterfactualEngine(catalog, knowledge)
    model = engine.with_facts(remove=[fact])
    assert knowledge.facts == before
    assert fact in knowledge.facts
    assert model is not knowledge
    assert fact not in model.facts


def test_differences_limited_by_max_steps(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(
        catalog, [Fact("at_war_with", ("faction:red", "faction:blue"))]
    )
    engine = CounterfactualEngine(catalog, knowledge)
    result = engine.compare(
        "at_war_with",
        ("faction:red", "faction:blue"),
        remove=[Fact("at_war_with", ("faction:red", "faction:blue"))],
    )
    assert len(result.differences) <= engine.max_steps


# --- D6.2c: предикаты и отношения ----------------------------------


def test_believe_uses_source_fact(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    belief = Fact(
        "belief",
        (
            "char_red",
            "faction:red",
            "considers_illegitimate",
            "faction:blue",
        ),
    )
    planner = _planner(
        catalog,
        [
            Fact("speaks_for", ("char_red", "faction:red")),
            belief,
        ],
    )
    answer = planner.plan(
        _counterfactual(
            _assert_sem("believe", "faction:red", "faction:blue")
        )
    )
    assert answer.plan_id == "cf_explain"
    assert answer.kind == "counterfactual"
    assert answer.data["predicate"] == "believe"
    assert answer.data["relation"] == "considers_outlaw"
    assert answer.data["outcome"] == "changed"
    assert answer.data["removed"] == (belief,)


def test_have_maps_to_has_organ(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    organ = Fact("has_organ", ("faction:red", "organ:red:abwehr"))
    planner = _planner(catalog, [organ])
    answer = planner.plan(
        _counterfactual(_have_sem("faction:red", "organ:red:abwehr"))
    )
    assert answer.plan_id == "cf_explain_yesno"
    assert answer.data["relation"] == "has_organ"
    assert answer.data["outcome"] == "changed"
    assert answer.data["removed"] == (organ,)


def test_fight_pp_object_uses_with_plan(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    war = Fact("at_war_with", ("faction:red", "faction:blue"))
    planner = _planner(catalog, [war])
    answer = planner.plan(
        _counterfactual(
            _with_sem("fight", "faction:red", "faction:blue")
        )
    )
    assert answer.plan_id == "cf_explain_with"
    assert answer.data["relation"] == "at_war_with"
    assert answer.data["args"] == ("faction:red", "faction:blue")
    assert answer.data["removed"] == (war,)


# --- D6.2a: отрицание -----------------------------------------------


def test_negation_swaps_remove_and_add(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    war = Fact("at_war_with", ("faction:red", "faction:green"))
    planner = _planner(catalog, [])
    answer = planner.plan(
        _counterfactual(
            _with_sem(
                "fight", "faction:red", "faction:green", negated=True
            )
        )
    )
    assert answer.data["negated"] is True
    assert answer.data["removed"] == ()
    assert answer.data["added"] == (war,)
    assert answer.data["outcome"] == "changed"


def test_negation_parsed_from_surface(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    parses = ChartParser(catalog).parse(
        "Империя не воюет с Республикой"
    )
    assert parses
    matches = [
        item
        for item in parses
        if item.sem.get("kind") == "assert"
        and item.sem.get("negated")
    ]
    assert matches
    assert matches[0].sem.get("predicate") == "fight"


# --- D6.2b: «то»-следствие ------------------------------------------


def test_consequent_parsed(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    parses = ChartParser(catalog).parse(
        "Что было бы, если бы Империя не издала эдикт, "
        "то Республика бы пала?"
    )
    assert parses
    sem = parses[0].sem
    assert sem.get("kind") == "counterfactual"
    assert sem.get("antecedent", {}).get("negated") is True
    assert sem.get("antecedent", {}).get("predicate") == "issue"
    assert sem.get("consequent", {}).get("predicate") == "fall"


def test_consequent_becomes_comparison_target(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    war = Fact("at_war_with", ("faction:red", "faction:blue"))
    planner = _planner(catalog, [war])
    sem = _counterfactual(
        _with_sem("fight", "faction:red", "faction:blue"),
        _with_sem("fight", "faction:blue", "faction:red"),
    )
    answer = planner.plan(sem)
    assert answer.data["relation"] == "at_war_with"
    assert answer.data["args"] == ("faction:blue", "faction:red")
    assert answer.data["outcome"] == "changed"
    assert answer.data["removed"] == (war,)
