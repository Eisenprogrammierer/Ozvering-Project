"""Проверки целей, действий, персоны и раскрытия диалога.

Средний слой ``campaign.dialogue.lint``: здесь живут проверки целей и
социальных действий. Базовые грамматические проверки — в ``lint_base``,
верхние слои и сборка отчёта — в ``lint_ext``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set

from .errors import DialogueError
from .loader import (
    CONTEXT_OPERATORS,
    DEFAULT_DIR,
    EFFECT_TYPES,
    load_dialogue,
)
from .model import AtomSpec, DialogueCatalog, GrammarRule
from .style import SELECTION_KEYS, _SUBJECT_FIELDS
from .lint_base import (
    _DISCOURSE_KINDS,
    _GOAL_OPS,
    _atom_problems,
    _fact_problems,
    _paraphrase_problems,
    _parsing_problems,
    _persona_problems,
    _plan_problems,
    _realization_problems,
    _relations,
    _rule_data_problems,
    _rule_problems,
    _synthesis_problems,
    _variables,
    _world_problems,
)


def _goal_problems(catalog: DialogueCatalog) -> List[str]:
    """Проверить цели и шаги D6.4."""

    spec = getattr(catalog, "goals", None) or {}
    if not spec:
        return []
    problems: List[str] = []
    entries = spec.get("goals")
    if not isinstance(entries, (list, tuple)) or not entries:
        return ["goals.goals: ожидался непустой список"]
    seen: Set[str] = set()
    for index, goal in enumerate(entries):
        where = "goals.goals[%d]" % index
        if not isinstance(goal, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        goal_id = str(goal.get("id") or "")
        if not goal_id:
            problems.append("%s.id: пусто" % where)
        elif goal_id in seen:
            problems.append("%s.id: повтор %r" % (where, goal_id))
        seen.add(goal_id)
        when = goal.get("when") or {}
        if not isinstance(when, Mapping):
            problems.append("%s.when: ожидался объект" % where)
        else:
            for key in ("kinds", "acts"):
                value = when.get(key)
                if value is None:
                    continue
                if not isinstance(value, (list, tuple)):
                    problems.append("%s.when.%s: ожидался список"
                                    % (where, key))
                    continue
                if any(not str(item or "") for item in value):
                    problems.append("%s.when.%s: пустой элемент"
                                    % (where, key))
        steps = goal.get("steps")
        if not isinstance(steps, (list, tuple)) or not steps:
            problems.append("%s.steps: ожидался непустой список" % where)
            continue
        step_ids: Set[str] = set()
        for offset, step in enumerate(steps):
            step_where = "%s.steps[%d]" % (where, offset)
            if not isinstance(step, Mapping):
                problems.append("%s: ожидался объект" % step_where)
                continue
            step_id = str(step.get("id") or "")
            op = str(step.get("op") or "")
            if not step_id:
                problems.append("%s.id: пусто" % step_where)
            elif step_id in step_ids:
                problems.append("%s.id: повтор %r" % (step_where, step_id))
            step_ids.add(step_id)
            if op not in _GOAL_OPS:
                problems.append("%s.op: неизвестная операция %r"
                                % (step_where, op))
            if op == "check" and not str(step.get("requires") or ""):
                problems.append("%s.requires: пусто у check" % step_where)
    return problems


def _action_problems(catalog: DialogueCatalog) -> List[str]:
    """Проверить псевдонимы действий D6.4."""

    spec = getattr(catalog, "actions", None) or {}
    if not spec:
        return []
    problems: List[str] = []
    entries = spec.get("actions")
    if not isinstance(entries, (list, tuple)) or not entries:
        return ["actions.actions: ожидался непустой список"]
    lexical: Set[str] = set()
    for entry in catalog.lexicon:
        semantic = entry.semantic
        if isinstance(semantic, Mapping):
            value = str(semantic.get("id") or "")
            if value:
                lexical.add(value)
    seen_ids: Set[str] = set()
    seen_aliases: Set[str] = set()
    declared_ids = {
        str(item.get("id") or "")
        for item in entries
        if isinstance(item, Mapping)
    }
    declared_ids.discard("")
    for index, item in enumerate(entries):
        where = "actions.actions[%d]" % index
        if not isinstance(item, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        action_id = str(item.get("id") or "")
        if not action_id:
            problems.append("%s.id: пусто" % where)
        elif action_id in seen_ids:
            problems.append("%s.id: повтор %r" % (where, action_id))
        seen_ids.add(action_id)
        aliases = item.get("aliases")
        if not isinstance(aliases, (list, tuple)) or not aliases:
            problems.append("%s.aliases: ожидался непустой список"
                            % where)
            continue
        phrases = item.get("phrases")
        if phrases is not None:
            if not isinstance(phrases, (list, tuple)) or not phrases:
                problems.append("%s.phrases: ожидался непустой список"
                                % where)
            elif any(not str(value or "").strip() for value in phrases):
                problems.append("%s.phrases: пустая фраза" % where)
        for alias in aliases:
            value = str(alias or "")
            if not value:
                problems.append("%s.aliases: пустой псевдоним" % where)
                continue
            if value in seen_aliases:
                problems.append("%s.aliases: повтор %r" % (where, value))
            seen_aliases.add(value)
            if value in declared_ids:
                problems.append(
                    "%s.aliases: псевдоним совпадает с id %r"
                    % (where, value)
                )
            if value not in lexical:
                problems.append(
                    "%s.aliases: псевдоним %r не объявлен в лексиконе"
                    % (where, value)
                )
    return problems


def _marker_problems(catalog: DialogueCatalog) -> List[str]:
    """Проверить фразы-маркеры режимов разговора в ``actions.json``."""

    spec = getattr(catalog, "actions", None) or {}
    markers = spec.get("markers")
    if markers is None:
        return []
    if not isinstance(markers, (list, tuple)) or not markers:
        return ["actions.markers: ожидался непустой список"]
    from .parser import ChartParser

    parser = ChartParser(catalog)
    social = getattr(catalog, "social", None)
    acts = set((getattr(social, "acts", {}) or {}).keys())
    problems: List[str] = []
    seen: Set[str] = set()
    for index, item in enumerate(markers):
        where = "actions.markers[%d]" % index
        if not isinstance(item, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        act = str(item.get("act") or "")
        if not act:
            problems.append("%s.act: пусто" % where)
        elif act not in acts:
            problems.append(
                "%s.act: неизвестный речевой акт %r" % (where, act)
            )
        phrases = item.get("phrases")
        if not isinstance(phrases, (list, tuple)) or not phrases:
            problems.append(
                "%s.phrases: ожидался непустой список" % where
            )
            continue
        for phrase in phrases:
            value = str(phrase or "").strip()
            if not value:
                problems.append("%s.phrases: пустая фраза" % where)
                continue
            if value in seen:
                problems.append("%s.phrases: повтор %r" % (where, value))
            seen.add(value)
            parse = parser.parse_best(value)
            if parse is None:
                problems.append(
                    "%s.phrases: фраза не разбирается: %r"
                    % (where, value)
                )
                continue
            sem = parse.sem if isinstance(parse.sem, Mapping) else {}
            if (
                str(sem.get("kind") or "") != "social"
                or str(sem.get("act") or "") != act
            ):
                problems.append(
                    "%s.phrases: фраза ведёт не к акту %r: %r"
                    % (where, act, value)
                )
    return problems


def _sem_values(value, key):
    """Собрать значения ``key`` из вложенной семантики правила."""

    found = set()
    if isinstance(value, Mapping):
        item = value.get(key)
        if isinstance(item, str) and item:
            found.add(item)
        for nested in value.values():
            found.update(_sem_values(nested, key))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.update(_sem_values(nested, key))
    return found


def _verb_path_problems(catalog: DialogueCatalog) -> List[str]:
    """Каждый глагол действия обязан иметь реестр или речевой акт."""

    problems: List[str] = []
    entries = (getattr(catalog, "actions", None) or {}).get("actions") or ()
    aliases = set()
    for item in entries:
        if isinstance(item, Mapping):
            aliases.update(
                str(alias) for alias in (item.get("aliases") or ())
            )
    try:
        from .projection import projected_registry

        projected, projection_problems, _ = projected_registry(
            manual=catalog.actions
        )
    except Exception as exc:  # pragma: no cover - защита от битых данных
        problems.append("projection: %s" % exc)
        projected, projection_problems = [], []
    for problem in projection_problems:
        problems.append("projection: %s" % problem)
    for item in projected.get("actions") or ():
        if isinstance(item, Mapping):
            aliases.update(
                str(alias) for alias in (item.get("aliases") or ())
            )
    social_ids = set(getattr(catalog.social, "acts", {}) or {})
    social_grammar = set()
    for rule in catalog.grammar.rules:
        social_grammar.update(
            value
            for value in _sem_values(rule.sem, "act")
            if value
        )
    for entry in catalog.lexicon:
        semantic = entry.semantic
        if not isinstance(semantic, Mapping):
            continue
        if semantic.get("kind") != "predicate":
            continue
        value = str(semantic.get("id") or "")
        if not value:
            continue
        if value.startswith("act_") and value not in aliases:
            problems.append(
                "лексема %s: действие %r отсутствует в actions.json"
                % (entry.id, value)
            )
        elif value in social_ids and value not in social_grammar:
            problems.append(
                "лексема %s: речевой акт %r не покрыт грамматикой"
                % (entry.id, value)
            )
    return problems


def _answer_kind_problems(catalog: DialogueCatalog) -> List[str]:
    """Проверить реестр типов ответа и покрытие планов.

    ``answer_kinds.json`` связывает ``plan.answer.type`` с Python-
    обработчиком. Новый тип без записи в реестре — ошибка линтера, а не
    молчаливое «не знаю».
    """

    registry = getattr(catalog, "answer_kinds", None) or {}
    kinds = registry.get("kinds") if isinstance(registry, Mapping) else None
    if not kinds:
        return []
    if not isinstance(kinds, Mapping):
        return ["answer_kinds.kinds: ожидался объект"]
    problems: List[str] = []
    try:
        from .answers import AnswerPlanner

        implemented = {
            name[len("_answer_"):]
            for name in dir(AnswerPlanner)
            if name.startswith("_answer_")
        }
    except Exception:  # pragma: no cover - защита от цикла импорта
        implemented = set()
    for kind, spec in kinds.items():
        where = "answer_kinds.kinds.%s" % kind
        if not isinstance(spec, Mapping):
            problems.append("%s: ожидался объект" % where)
            continue
        handler = str(spec.get("handler") or "").strip()
        if not handler:
            problems.append("%s.handler: пусто" % where)
        elif implemented and handler not in implemented:
            problems.append(
                "%s.handler: обработчик %r не реализован"
                % (where, handler)
            )
        if "generic" in spec and not isinstance(spec.get("generic"), bool):
            problems.append("%s.generic: ожидалось true/false" % where)
    for index, plan in enumerate(getattr(catalog, "plans", ()) or ()):
        answer = plan.answer if isinstance(plan.answer, Mapping) else {}
        answer_type = str(answer.get("type") or "")
        if not answer_type:
            problems.append(
                "plans.plans[%d].answer.type: пусто" % index
            )
        elif answer_type not in kinds:
            problems.append(
                "plans.plans[%d].answer.type: тип %r отсутствует "
                "в answer_kinds.kinds" % (index, answer_type)
            )
    return problems


_CONSOLE_MESSAGES = frozenset(
    {
        "empty",
        "unknown",
        "undo_empty",
        "undo_done",
        "history_empty",
        "hint_empty",
        "hint_prefix",
        "action_done",
        "action_failed",
        "quit",
    }
)


def _console_problems(catalog: DialogueCatalog) -> List[str]:
    """Проверить настройки текстового интерфейса D7.0."""

    spec = getattr(catalog, "console", None) or {}
    if not spec:
        return []
    problems: List[str] = []
    limit = spec.get("history_limit", 50)
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 0
    if value < 1:
        problems.append("console.history_limit: ожидалось целое >= 1")
    messages = spec.get("messages")
    if not isinstance(messages, Mapping):
        problems.append("console.messages: ожидался объект")
    else:
        missing = sorted(_CONSOLE_MESSAGES - set(messages))
        for key in missing:
            problems.append("console.messages.%s: отсутствует" % key)
        for key, item in messages.items():
            if not str(item or "").strip():
                problems.append("console.messages.%s: пусто" % key)
    commands = spec.get("commands")
    if not isinstance(commands, Mapping) or not commands:
        problems.append("console.commands: ожидался непустой объект")
    else:
        for key, item in commands.items():
            if not str(item or "").strip():
                problems.append("console.commands.%s: пусто" % key)
        aliases = spec.get("aliases")
        if not isinstance(aliases, Mapping):
            problems.append("console.aliases: ожидался объект")
        else:
            for key, item in aliases.items():
                if str(item or "") not in commands:
                    problems.append(
                        "console.aliases.%s: неизвестная команда %r"
                        % (key, item)
                    )
    return problems


def _disclosure_problems(catalog: DialogueCatalog) -> List[str]:
    """Проверить политики раскрытия и ссылки персон на них."""

    problems: List[str] = []
    spec = getattr(catalog, "disclosure", None) or {}
    if not spec:
        return problems
    policies = spec.get("policies") or {}
    if not isinstance(policies, Mapping) or not policies:
        return ["disclosure.policies: пусто"]
    default = str(spec.get("default") or "")
    if default and default not in policies:
        problems.append(
            "disclosure.default: политика %r отсутствует" % default
        )
    for key, raw in policies.items():
        where = "disclosure.policies.%s" % key
        policy = raw if isinstance(raw, Mapping) else {}
        if not policy:
            problems.append("%s: ожидался объект" % where)
            continue
        outcome = str(policy.get("outcome") or "")
        if outcome not in ("truth", "partial", "withhold", "evade", "lie"):
            problems.append(
                "%s.outcome: неизвестный исход %r" % (where, outcome)
            )
            continue
        if outcome in ("withhold", "evade") and not str(
            policy.get("text") or ""
        ).strip():
            problems.append("%s.text: пусто" % where)
        if outcome == "partial" and not str(
            policy.get("prefix") or ""
        ).strip():
            problems.append("%s.prefix: пусто" % where)
        if outcome == "lie" and not any(
            str(policy.get(name) or "").strip()
            for name in ("yes", "no", "other")
        ):
            problems.append(
                "%s: нужен хотя бы один текст yes/no/other" % where
            )
    for key, persona in catalog.personas.items():
        probability = float(persona.lie_probability or 0.0)
        if probability < 0.0 or probability > 1.0:
            problems.append(
                "persona %s: lie_probability вне [0, 1]" % key
            )
        disclosure = persona.disclosure or {}
        if not disclosure:
            continue
        policy_id = str(disclosure.get("default") or "")
        if policy_id and policy_id not in policies:
            problems.append(
                "persona %s: default disclosure %r отсутствует"
                % (key, policy_id)
            )
        on_topic = disclosure.get("on_topic") or {}
        if not isinstance(on_topic, Mapping):
            problems.append(
                "persona %s: disclosure.on_topic ожидался объект" % key
            )
            continue
        for topic, policy_id in on_topic.items():
            if str(policy_id) not in policies:
                problems.append(
                    "persona %s: disclosure.on_topic.%s: политика %r "
                    "отсутствует" % (key, topic, policy_id)
                )
    return problems
