"""Тесты D6.3: политика раскрытия и детерминированная ложь.

Проверяют, что исход ответа (правда, частичная правда, утаивание,
уклонение, ложь) задаётся данными ``disclosure.json`` и полями персоны,
а не скрытой эвристикой. Ложь включается только при
``lie_score < lie_probability``, всегда оставляет истину в
``Answer.data`` и воспроизводима при одинаковых seed/ходе/теме.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

from campaign.dialogue.answers import AnswerPlanner
from campaign.dialogue.engine import DialogueSession
from campaign.dialogue.knowledge import AgentKnowledge, Fact
from campaign.dialogue.lint import lint_directory
from campaign.dialogue.loader import DEFAULT_DIR, load_dialogue
from campaign.dialogue.style import StyleEngine


def _copy_configs(tmp_path: Path) -> Path:
    target = tmp_path / "dialogue"
    shutil.copytree(DEFAULT_DIR, target)
    return target


def _catalog(directory: Path):
    return load_dialogue(directory)


def _knowledge(catalog, facts=(), run_id="campaign:red:13"):
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
        run_id=run_id,
    )


def _persona(catalog, **changes):
    base = catalog.personas.get("red") or list(
        catalog.personas.values()
    )[0]
    return dataclasses.replace(base, **changes)


def _planner(catalog, persona=None, facts=(), run_id="campaign:red:13"):
    knowledge = _knowledge(catalog, facts, run_id)
    style_engine = StyleEngine(catalog)
    planner = AnswerPlanner(
        catalog,
        knowledge,
        persona or catalog.personas["red"],
        style_engine=style_engine,
    )
    planner.set_style(style_engine.profile("neutral"))
    return planner, knowledge


def _war_sem():
    return {
        "kind": "question",
        "wh": "yesno",
        "body": {
            "kind": "assert",
            "predicate": "fight",
            "subject": {"head": {"entity": "faction:red"}},
            "object": {
                "kind": "pp",
                "prep": "with",
                "object": {"head": {"entity": "faction:blue"}},
            },
        },
    }


def _belief_sem():
    return {
        "kind": "question",
        "wh": "yesno",
        "body": {
            "kind": "assert",
            "predicate": "believe",
            "value": "illegal",
            "subject": {"head": {"entity": "faction:red"}},
            "object": {"head": {"entity": "faction:blue"}},
        },
    }


WAR = Fact("at_war_with", ("faction:red", "faction:blue"))


# --- данные и линтер ------------------------------------------------


def test_disclosure_loaded(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    spec = catalog.disclosure
    assert spec
    policies = spec.get("policies") or {}
    assert set(policies) == {
        "honest",
        "partial",
        "withhold",
        "evasive",
        "lie",
    }
    assert spec.get("default") == "honest"
    assert policies["lie"]["outcome"] == "lie"


def test_persona_disclosure_fields_loaded(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "personas.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["red"]["disclosure"] = {
        "default": "withhold",
        "on_topic": {"at_war_with": "lie"},
    }
    data["red"]["lie_probability"] = 0.25
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    catalog = _catalog(directory)
    persona = catalog.personas["red"]
    assert persona.disclosure["default"] == "withhold"
    assert persona.disclosure["on_topic"]["at_war_with"] == "lie"
    assert persona.lie_probability == 0.25


def test_persona_defaults_are_honest(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    for persona in catalog.personas.values():
        assert persona.lie_probability == 0.0
        assert not persona.disclosure


def test_lint_disclosure_clean(tmp_path):
    problems = lint_directory(_copy_configs(tmp_path))
    relevant = [item for item in problems if "disclosure" in item.lower()]
    assert relevant == []


def test_lint_catches_unknown_default_policy(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "personas.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["red"]["disclosure"] = {"default": "missing"}
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    problems = lint_directory(directory)
    broken = [item for item in problems if "disclosure" in item.lower()]
    assert broken
    assert "missing" in broken[0]


def test_lint_catches_unknown_outcome(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "disclosure.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["policies"]["honest"]["outcome"] = "bogus"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    problems = lint_directory(directory)
    broken = [item for item in problems if "outcome" in item]
    assert broken
    assert "bogus" in broken[0]


def test_lint_catches_probability_out_of_range(tmp_path):
    directory = _copy_configs(tmp_path)
    path = directory / "personas.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["red"]["lie_probability"] = 1.5
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    problems = lint_directory(directory)
    broken = [
        item for item in problems if "lie_probability" in item
    ]
    assert broken


# --- исходы ---------------------------------------------------------


def test_honest_keeps_truth(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    planner, _ = _planner(catalog, facts=[WAR])
    answer = planner.plan(_war_sem())
    assert answer.kind == "yes"
    assert answer.data["relation"] == "at_war_with"
    assert "disclosure" not in answer.data
    assert "lied" not in answer.data


def test_partial_prefixes_truth(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    persona = _persona(catalog, disclosure={"default": "partial"})
    planner, _ = _planner(catalog, persona, [WAR])
    answer = planner.plan(_war_sem())
    assert answer.data["disclosure"] == "partial"
    assert answer.data["partial"] is True
    assert answer.text.startswith("Кое-что я знаю")
    assert answer.text.endswith("Да. Империя воюет с Республикой.")


def test_withhold_hides_truth_but_records_it(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    persona = _persona(catalog, disclosure={"default": "withhold"})
    planner, _ = _planner(catalog, persona, [WAR])
    answer = planner.plan(_war_sem())
    assert answer.data["disclosure"] == "withhold"
    assert answer.data["withheld"] is True
    assert answer.text == "Об этом я говорить не буду."
    assert answer.data["truth_text"] == "Да. Империя воюет с Республикой."
    assert answer.data["truth_kind"] == "yes"


def test_evasive_keeps_kind_and_records_truth(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    persona = _persona(catalog, disclosure={"default": "evasive"})
    planner, _ = _planner(catalog, persona, [WAR])
    answer = planner.plan(_war_sem())
    assert answer.data["disclosure"] == "evasive"
    assert answer.data["evaded"] is True
    assert answer.text == "Смотря что считать ответом."
    assert answer.data["truth_text"] == "Да. Империя воюет с Республикой."


def test_lie_probability_one_inverts_yes(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    persona = _persona(
        catalog, disclosure={"default": "lie"}, lie_probability=1.0
    )
    planner, _ = _planner(catalog, persona, [WAR])
    answer = planner.plan(_war_sem())
    assert answer.data["lied"] is True
    assert answer.text == "Нет, это не так."
    assert answer.data["truth_text"] == "Да. Империя воюет с Республикой."
    assert answer.data["truth_kind"] == "yes"
    assert 0.0 <= answer.data["lie_score"] < 1.0


def test_lie_probability_zero_stays_truthful(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    persona = _persona(
        catalog, disclosure={"default": "lie"}, lie_probability=0.0
    )
    planner, _ = _planner(catalog, persona, [WAR])
    answer = planner.plan(_war_sem())
    assert answer.data["lied"] is False
    assert answer.kind == "yes"
    assert answer.text == "Да. Империя воюет с Республикой."


def _organ_sem():
    return {
        "kind": "question",
        "wh": "yesno",
        "body": {
            "kind": "assert",
            "have": True,
            "object": {
                "kind": "np",
                "head": {"entity": "organ:red:abwehr"},
            },
            "owner": {
                "kind": "pp",
                "prep": "at",
                "object": {
                    "kind": "np",
                    "head": {"entity": "faction:red"},
                },
            },
        },
    }


def test_lie_inverts_no_to_yes(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    persona = _persona(
        catalog, disclosure={"default": "lie"}, lie_probability=1.0
    )
    planner, _ = _planner(catalog, persona, [])
    answer = planner.plan(_organ_sem())
    assert answer.kind == "no"
    assert answer.data["lied"] is True
    assert answer.text == "Да, это так."
    assert answer.data["truth_kind"] == "no"


def test_lie_score_is_deterministic(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    persona = _persona(
        catalog, disclosure={"default": "lie"}, lie_probability=0.5
    )
    first, _ = _planner(catalog, persona, [WAR])
    second, _ = _planner(catalog, persona, [WAR])
    one = first.plan(_war_sem())
    two = second.plan(_war_sem())
    assert one.data["lie_score"] == two.data["lie_score"]
    assert one.data["lied"] == two.data["lied"]


def test_on_topic_policy_beats_default(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    persona = _persona(
        catalog,
        disclosure={
            "default": "honest",
            "on_topic": {"at_war_with": "withhold"},
        },
    )
    belief = Fact(
        "belief",
        (
            "char_red",
            "faction:red",
            "considers_illegitimate",
            "faction:blue",
        ),
    )
    planner, _ = _planner(
        catalog,
        persona,
        [WAR, Fact("speaks_for", ("char_red", "faction:red")), belief],
    )
    war = planner.plan(_war_sem())
    other = planner.plan(_belief_sem())
    assert war.data["disclosure"] == "withhold"
    assert war.data["disclosure_topic"] == "at_war_with"
    assert "disclosure" not in other.data
    assert other.data["relation"] == "considers_outlaw"


def test_disclosure_does_not_mutate_knowledge(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    persona = _persona(
        catalog, disclosure={"default": "lie"}, lie_probability=1.0
    )
    planner, knowledge = _planner(catalog, persona, [WAR])
    before = knowledge.facts
    planner.plan(_war_sem())
    assert knowledge.facts == before == (WAR,)


# --- интеграция с сессией -------------------------------------------


def _belief_facts():
    return [
        Fact("speaks_for", ("char_red", "faction:red")),
        Fact(
            "belief",
            (
                "char_red",
                "faction:red",
                "considers_illegitimate",
                "faction:blue",
            ),
        ),
    ]


def test_session_applies_disclosure(tmp_path):
    directory = _copy_configs(tmp_path)
    catalog = _catalog(directory)
    persona = _persona(
        catalog, disclosure={"default": "lie"}, lie_probability=1.0
    )
    catalog = dataclasses.replace(
        catalog, personas={**catalog.personas, "red": persona}
    )
    knowledge = _knowledge(catalog, _belief_facts())
    session = DialogueSession(catalog, knowledge, persona_id="red")
    answer = session.ask("Считает ли Империя Республику незаконной?")
    assert answer.plan_id == "belief_yesno"
    assert answer.data["disclosure"] == "lie"
    assert answer.data["disclosure_topic"] == "considers_outlaw"
    assert answer.data["lied"] is True
    assert answer.data["truth_kind"] == "yes"
    assert answer.text == "Нет, это не так."


def test_session_honest_by_default(tmp_path):
    catalog = _catalog(_copy_configs(tmp_path))
    knowledge = _knowledge(catalog, _belief_facts())
    session = DialogueSession(catalog, knowledge, persona_id="red")
    answer = session.ask("Считает ли Империя Республику незаконной?")
    assert answer.kind == "yes"
    assert "disclosure" not in answer.data
    assert "lied" not in answer.data
