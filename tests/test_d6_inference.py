"""Phase 3b: логический вывод диалога в Soar.

Проверяют компилятор (JSON → продукции), исполнение через SML, режимы
``legacy|shadow|soar`` и деградацию без пакета ``soar-sml``. Soar строит
прямое замыкание, но решения, порядок и доказательства обязаны совпадать
с легаси: знание и текст ответа не меняются.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from campaign.automata import AutomataCampaign
from campaign.cognition.backends import CognitionFlags
from campaign.cognition.errors import BackendError, SoarError
from campaign.cognition.inference_compiler import (
    DEFAULT_DIALOGUE_DIR,
    DEFAULT_SOAR_DIR,
    InferenceModel,
    check_policy,
    compile_policy,
    load_model,
    load_sources,
    source_digest,
    write_policy,
)
from campaign.cognition.corpus_builder import dialogue_variants
from campaign.cognition.inference_runtime import SoarInference
from campaign.cognition.nlu_lint import collect_phrases
from campaign.dialogue import (
    DialogueSession,
    InferenceBackend,
    InferenceEngine,
    build_knowledge,
    load_dialogue,
    load_inference,
)
from campaign.dialogue.counterfactual import CounterfactualEngine
from campaign.dialogue.loader import DEFAULT_DIR
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "configs" / "campaigns" / "empire_campaign.json"


def _catalog():
    return load_dialogue(DEFAULT_DIR)


def _campaign_knowledge(seed=13, side="red"):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=TEMPLATE,
    )
    campaign = AutomataCampaign(generator.generate(seed=seed), seed=seed)
    return build_knowledge(_catalog(), campaign, side)


def _patterns(catalog, knowledge):
    relations = {fact.rel for fact in knowledge.facts}
    relations |= {rule.head.rel for rule in catalog.rules}
    result = []
    for relation in sorted(relations):
        arities = {len(fact.args) for fact in knowledge.facts
                   if fact.rel == relation}
        arities |= {
            len(rule.head.args)
            for rule in catalog.rules
            if rule.head.rel == relation
        }
        for arity in sorted(arities):
            result.append(
                (relation, tuple("$q%d" % index for index in range(arity)))
            )
            facts = [
                fact for fact in knowledge.facts
                if fact.rel == relation and len(fact.args) == arity
            ]
            for fact in facts[:2]:
                result.append((relation, tuple(fact.args)))
            for fact in facts[:1]:
                for index in range(arity):
                    pattern = [
                        "$q%d" % number for number in range(arity)
                    ]
                    pattern[index] = fact.args[index]
                    result.append((relation, tuple(pattern)))
    seen = set()
    unique = []
    for item in result:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _max_height(proof, depth=0):
    return max(
        [depth] + [_max_height(child, depth + 1)
                   for child in proof.children]
    )


def _has_cycle(proof, guards=frozenset()):
    if proof.rule == "fact":
        return False
    key = (proof.rule, proof.atom.args)
    if key in guards:
        return True
    guards = guards | {key}
    return any(_has_cycle(child, guards) for child in proof.children)


# --- компилятор -----------------------------------------------------


def test_shipped_artifact_matches_sources():
    model = load_model()
    assert isinstance(model, InferenceModel)
    assert model.run_cycles >= 2
    text, compiled, _depth = compile_policy()
    assert compiled.digest() == model.digest()
    assert "source_digest" in text
    assert "infer*export" in text
    assert check_policy() == model


def test_compiler_rejects_unbound_head_variable(tmp_path):
    dialogue = tmp_path / "dialogue"
    dialogue.mkdir()
    (dialogue / "ontology.json").write_text(
        json.dumps({"max_depth": 8}), encoding="utf-8"
    )
    (dialogue / "rules.json").write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "id": "bad",
                        "head": {"rel": "x", "args": ["$a"]},
                        "premises": [{"rel": "y", "args": ["$b"]}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    soar_dir = tmp_path / "soar"
    soar_dir.mkdir()
    shutil.copy(
        DEFAULT_SOAR_DIR / "inference.json",
        soar_dir / "inference.json",
    )
    with pytest.raises(SoarError):
        compile_policy(soar_dir, dialogue)


def test_compiler_rejects_duplicate_rule_ids(tmp_path):
    dialogue = tmp_path / "dialogue"
    dialogue.mkdir()
    (dialogue / "ontology.json").write_text(
        json.dumps({"max_depth": 8}), encoding="utf-8"
    )
    rule = {
        "id": "same",
        "head": {"rel": "x", "args": ["$a"]},
        "premises": [{"rel": "y", "args": ["$a"]}],
    }
    (dialogue / "rules.json").write_text(
        json.dumps({"rules": [rule, rule]}), encoding="utf-8"
    )
    soar_dir = tmp_path / "soar"
    soar_dir.mkdir()
    shutil.copy(
        DEFAULT_SOAR_DIR / "inference.json",
        soar_dir / "inference.json",
    )
    with pytest.raises(SoarError):
        compile_policy(soar_dir, dialogue)


def test_compiler_writes_and_checks_tmp_artifact(tmp_path):
    soar_dir = tmp_path / "soar"
    soar_dir.mkdir()
    shutil.copy(
        DEFAULT_SOAR_DIR / "inference.json",
        soar_dir / "inference.json",
    )
    target = write_policy(soar_dir)
    assert target.is_file()
    assert check_policy(soar_dir)
    target.write_text(
        target.read_text(encoding="utf-8") + "\n// stale\n",
        encoding="utf-8",
    )
    with pytest.raises(SoarError):
        check_policy(soar_dir)


def test_source_digest_changes_with_rules():
    rules, depth = load_sources(DEFAULT_DIALOGUE_DIR)
    model = load_model()
    before = source_digest(model, rules, depth)
    changed = (
        dataclasses.replace(rules[0], priority=rules[0].priority + 1),
    ) + tuple(rules[1:])
    assert source_digest(model, changed, depth) != before


# --- исполнение Soar ------------------------------------------------


@pytest.fixture
def knowledge():
    pytest.importorskip("soar_sml")
    return _campaign_knowledge()


def test_runtime_matches_legacy_on_corpus(knowledge):
    catalog = _catalog()
    legacy = InferenceEngine(catalog, knowledge)
    soar = SoarInference(catalog, knowledge, timeout_ms=30000)
    for relation, args in _patterns(catalog, knowledge):
        left = legacy.prove(relation, args)
        right = soar.prove(relation, args)
        assert [dict(item.bindings) for item in right] == [
            dict(item.bindings) for item in left
        ], (relation, args)
        assert [item.proof.signature() for item in right] == [
            item.proof.signature() for item in left
        ], (relation, args)
    assert soar.nodes > 0
    assert soar.derived > 0
    assert soar.to_dict()["ok"] is True


def test_runtime_prunes_recursive_cycle(knowledge):
    catalog = _catalog()
    soar = SoarInference(catalog, knowledge, timeout_ms=30000)
    solutions = soar.prove("at_war_with", ("$x", "$y"))
    assert len(solutions) == 2
    for solution in solutions:
        assert _max_height(solution.proof) <= soar.max_depth
        assert not _has_cycle(solution.proof)


def test_runtime_respects_catalog_depth(knowledge):
    catalog = dataclasses.replace(_catalog(), max_depth=1)
    legacy = InferenceEngine(catalog, knowledge)
    soar = SoarInference(catalog, knowledge, timeout_ms=30000)
    for relation, args in _patterns(catalog, knowledge):
        left = legacy.prove(relation, args)
        right = soar.prove(relation, args)
        assert [item.proof.signature() for item in right] == [
            item.proof.signature() for item in left
        ], (relation, args)
        assert all(
            _max_height(item.proof) <= 1 for item in right
        ), (relation, args)


def test_runtime_is_read_only(knowledge):
    before = knowledge.facts
    soar = SoarInference(_catalog(), knowledge, timeout_ms=30000)
    soar.prove("at_war_with", ("$x", "$y"))
    assert knowledge.facts == before


def test_runtime_rejects_missing_artifact(tmp_path):
    with pytest.raises(BackendError):
        SoarInference(
            _catalog(),
            _campaign_knowledge(),
            path=tmp_path / "missing.soar",
        )


def test_runtime_enforces_node_limit(knowledge):
    soar = SoarInference(
        _catalog(), knowledge, timeout_ms=30000, node_limit=1
    )
    with pytest.raises(SoarError):
        soar.prove("at_war_with", ("$x", "$y"))


# --- режимы ---------------------------------------------------------


class _FakeSoar:
    def __init__(self, results=None, error=None):
        self.results = () if results is None else results
        self.error = error
        self.calls = 0

    def prove(self, relation, args=()):
        self.calls += 1
        if self.error:
            raise self.error
        return self.results


def test_legacy_backend_never_starts_soar():
    catalog = _catalog()
    backend = InferenceBackend(catalog, _campaign_knowledge(), "legacy")
    backend.prove("at_war_with", ("$x", "$y"))
    assert backend.report.queries == 0
    assert backend.active is False
    assert backend.to_dict()["ok"] is True


def test_shadow_returns_legacy_and_records_agreement():
    catalog = _catalog()
    backend = InferenceBackend(
        catalog, _campaign_knowledge(), "shadow", soar=_FakeSoar()
    )
    expected = backend.legacy.prove("at_war_with", ("$x", "$y"))
    backend._soar.results = expected
    assert backend.prove("at_war_with", ("$x", "$y")) == expected
    report = backend.to_dict()
    assert report["backend"] == "shadow"
    assert report["queries"] == 1
    assert report["agreements"] == 1
    assert report["disagreements"] == 0


def test_shadow_records_mismatch_and_sink():
    records = []
    catalog = _catalog()
    backend = InferenceBackend(
        catalog,
        _campaign_knowledge(),
        "shadow",
        soar=_FakeSoar(results=()),
        shadow_sink=records.append,
    )
    backend.prove("at_war_with", ("$x", "$y"))
    report = backend.to_dict()
    assert report["disagreements"] == 1
    assert records == [
        {
            "kind": "inference",
            "relation": "at_war_with",
            "args": ("$x", "$y"),
            "legacy": 2,
            "soar": 0,
            "agree": False,
        }
    ]


def test_shadow_masks_soar_errors():
    backend = InferenceBackend(
        _catalog(),
        _campaign_knowledge(),
        "shadow",
        soar=_FakeSoar(error=RuntimeError("boom")),
    )
    backend.prove("at_war_with", ("$x", "$y"))
    report = backend.to_dict()
    assert report["errors"] == 1
    assert "boom" in report["last_error"]


def test_soar_does_not_mask_errors():
    backend = InferenceBackend(
        _catalog(),
        _campaign_knowledge(),
        "soar",
        soar=_FakeSoar(error=RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError):
        backend.prove("at_war_with", ("$x", "$y"))


def test_unavailable_soar_degrades_to_legacy(monkeypatch):
    import campaign.cognition.inference_runtime as runtime

    monkeypatch.setattr(runtime, "soar_available", lambda: False)
    backend = InferenceBackend(
        _catalog(), _campaign_knowledge(), "soar"
    )
    expected = backend.legacy.prove("at_war_with", ("$x", "$y"))
    assert backend.prove("at_war_with", ("$x", "$y")) == expected
    assert backend.backend == "legacy"
    assert backend.report.unavailable is True
    assert backend.to_dict()["ok"] is False
    assert "soar-sml" in backend.report.last_error


def test_load_inference_reads_flags():
    catalog = _catalog()
    knowledge = _campaign_knowledge()
    backend = load_inference(catalog, knowledge)
    assert backend.requested == "legacy"
    assert backend.backend == "legacy"
    assert backend.active is False


def test_backend_validates_mode():
    with pytest.raises(ValueError):
        InferenceBackend(_catalog(), _campaign_knowledge(), "magic")


# --- интеграция с сессией -------------------------------------------


def test_corpus_answers_agree_across_inference_modes():
    """Живой корпус: 144 входа диалога дают тот же ответ на всех режимах.

    Это проверка не отдельного ``prove()``, а полной сессии: план, вид
    ответа и текст должны совпасть, а теневой режим — не найти
    расхождений на всех 177 запросах вывода.
    """

    pytest.importorskip("soar_sml")
    catalog = _catalog()
    knowledge = _campaign_knowledge()
    phrases = tuple(
        text
        for _identifier, text in dialogue_variants(collect_phrases())
    )
    assert len(phrases) == 144

    def run(mode):
        session = DialogueSession(
            catalog,
            knowledge,
            persona_id="red",
            inference=load_inference(
                catalog,
                knowledge,
                CognitionFlags(inference_backend=mode),
            ),
        )
        answers = []
        for text in phrases:
            answer = session.respond(text).answer
            if answer is None:
                answers.append(None)
            else:
                answers.append(
                    (answer.plan_id, answer.kind, answer.text)
                )
        return answers, session.planner.inference.to_dict()

    base, _report = run("legacy")
    for mode in ("shadow", "soar"):
        answers, report = run(mode)
        assert report["errors"] == 0
        assert report["queries"] >= len(phrases)
        assert answers == base
        if mode == "shadow":
            assert report["disagreements"] == 0
            assert report["agreements"] == report["queries"]


# --- контрфакты -----------------------------------------------------


def _war_case(knowledge):
    wars = [
        fact for fact in knowledge.facts if fact.rel == "at_war_with"
    ]
    assert wars
    fact = wars[0]
    return fact, [fact]


def test_counterfactual_matches_legacy_on_soar():
    pytest.importorskip("soar_sml")
    catalog = _catalog()
    knowledge = _campaign_knowledge()
    fact, remove = _war_case(knowledge)
    legacy = CounterfactualEngine(catalog, knowledge)
    backend = InferenceBackend(catalog, knowledge, "soar")
    soar = CounterfactualEngine(catalog, knowledge, backend=backend)

    left = legacy.compare("at_war_with", fact.args, remove=remove)
    right = soar.compare("at_war_with", fact.args, remove=remove)

    assert right.outcome == left.outcome
    assert [item.key() for item in right.differences] == [
        item.key() for item in left.differences
    ]
    assert right.base_proof.proof.signature() == (
        left.base_proof.proof.signature()
    )
    if left.model_proof is None:
        assert right.model_proof is None
    else:
        assert right.model_proof.proof.signature() == (
            left.model_proof.proof.signature()
        )
    assert backend.report.queries == 2
    assert backend.report.errors == 0


def test_counterfactual_shadow_agrees_with_legacy():
    pytest.importorskip("soar_sml")
    catalog = _catalog()
    knowledge = _campaign_knowledge()
    fact, remove = _war_case(knowledge)
    legacy = CounterfactualEngine(catalog, knowledge)
    backend = InferenceBackend(catalog, knowledge, "shadow")
    shadow = CounterfactualEngine(catalog, knowledge, backend=backend)

    left = legacy.compare("at_war_with", fact.args, remove=remove)
    right = shadow.compare("at_war_with", fact.args, remove=remove)

    assert right.outcome == left.outcome
    assert backend.report.queries == 2
    assert backend.report.agreements == backend.report.queries
    assert backend.report.disagreements == 0
