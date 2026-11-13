"""Планирование ответа и детерминированный синтез текста.

Планы, конструкции, поля описания и морфологические исключения живут в
JSON. Python только сопоставляет логическую форму с планом, доказывает
цель и передаёт смысл в композиционный реализатор. Готовые предложения-
шаблоны из ``realization.json`` используются лишь как аварийный fallback.

D4 добавляет тип ответа ``social``: акт и реакция берутся из
``social.json``, решение принимает ``SocialEngine``, текст собирается
конструкцией реакции, эффект уходит в ``Answer.data`` для
``ConversationState.apply_effect``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .inference import InferenceEngine, ProofStep, Solution, is_variable
from .knowledge import AgentKnowledge
from .model import DialogueCatalog, Persona, PlanSpec, StyleSpec
from .realize import Realizer, render_lines
from .social import SocialDecision, SocialEngine, social_bindings
from .style import StyleEngine


@dataclass(frozen=True)
class Answer:
    """Готовый ответ плюс объяснение и сработавший план."""

    kind: str
    text: str
    plan_id: str = ""
    proof: Tuple[ProofStep, ...] = ()
    data: Mapping[str, Any] = field(default_factory=dict)


class PatternError(ValueError):
    """Некорректный шаблон вопроса в plans.json."""


def match_pattern(
    pattern: Any, value: Any, bindings: Optional[Dict[str, str]] = None
) -> Optional[Dict[str, str]]:
    """Сопоставить шаблон с логической формой, связав ``$переменные``."""

    result = dict(bindings or {})
    if isinstance(pattern, Mapping):
        if not isinstance(value, Mapping):
            return None
        for key, item in pattern.items():
            if key not in value:
                return None
            result = match_pattern(item, value[key], result)
            if result is None:
                return None
        return result
    if isinstance(pattern, list):
        if not isinstance(value, list) or len(pattern) != len(value):
            return None
        for item, actual in zip(pattern, value):
            result = match_pattern(item, actual, result)
            if result is None:
                return None
        return result
    if isinstance(pattern, str) and "$" in pattern:
        return _match_template(pattern, value, result)
    return result if pattern == value else None


def _match_template(
    pattern: str, value: Any, bindings: Dict[str, str]
) -> Optional[Dict[str, str]]:
    if not isinstance(value, str):
        return None
    pieces = pattern.split("$")
    names: List[str] = []
    regex = "^"
    for index, piece in enumerate(pieces):
        if index == 0:
            regex += re.escape(piece)
            continue
        match = re.match(r"([A-Za-z0-9_]+)", piece)
        if not match:
            return None
        name = match.group(1)
        names.append(name)
        regex += (
            "(?P<v%d>.+?)" % index
            if index < len(pieces) - 1
            else "(?P<v%d>.+)" % index
        )
        rest = piece[len(name):]
        regex += re.escape(rest)
    regex += "$"
    found = re.match(regex, value)
    if not found:
        return None
    result = dict(bindings)
    for index, name in enumerate(names, 1):
        actual = found.group("v%d" % index)
        key = "$" + name
        if key in result and result[key] != actual:
            return None
        result[key] = actual
    return result


def _resolve(template: str, bindings: Mapping[str, str]) -> str:
    def replace(found: re.Match) -> str:
        key = "$" + found.group(1)
        return str(bindings.get(key, found.group(0)))

    return re.sub(r"\$([A-Za-z0-9_]+)", replace, str(template))


def _resolve_args(
    args: Iterable[Any], bindings: Mapping[str, str]
) -> Tuple[str, ...]:
    return tuple(_resolve(str(item), bindings) for item in args)


def _format_number(value: Any) -> str:
    try:
        return "%.2f" % float(value)
    except (TypeError, ValueError):
        return str(value)


def _index(mapping: Mapping[str, Any], name: str, default: int) -> int:
    try:
        return int(mapping.get(name, default))
    except (TypeError, ValueError):
        return default


class AnswerPlanner:
    """Сопоставляет логическую форму с планом и исполняет его."""

    def __init__(
        self,
        catalog: DialogueCatalog,
        knowledge: AgentKnowledge,
        persona: Persona,
        style_engine: Optional[StyleEngine] = None,
        memory: Any = None,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.persona = persona
        self.engine = InferenceEngine(catalog, knowledge)
        self.style_engine = style_engine or StyleEngine(catalog)
        self.social_engine = SocialEngine(
            catalog, knowledge, self.engine
        )
        self.realizer = Realizer(
            catalog,
            knowledge,
            self.engine,
            style_engine=self.style_engine,
            memory=memory,
        )
        self.style: StyleSpec = StyleSpec(id="", label="")
        self.realization = catalog.realization or {}
        self.answers = self.realization.get("answers") or {}
        self.plans = tuple(
            sorted(catalog.plans, key=lambda item: (-item.priority, item.id))
        )

    def set_style(self, style: Optional[StyleSpec]) -> None:
        """Сменить регистровый профиль, используемый при синтезе."""

        self.style = style or StyleSpec(id="", label="")
        self.realizer.set_style(self.style)

    def plan(
        self, sem: Any, plan_id: str = "", style: Optional[StyleSpec] = None
    ) -> Answer:
        if style is not None:
            self.set_style(style)
        self.realizer.take_trace()
        answer = self._plan(sem, plan_id)
        trace = self.realizer.take_trace()
        if not trace:
            return answer
        data = dict(answer.data or {})
        data.setdefault("register", self.style.register)
        data.setdefault("construction_trace", tuple(trace))
        constructions = [
            item.get("id")
            for item in trace
            if item.get("kind") == "construction" and item.get("id")
        ]
        if constructions:
            data.setdefault("constructions", tuple(constructions))
            data.setdefault("construction", constructions[0])
            data.setdefault("primary_construction", constructions[0])
        lexemes = [
            {"from": item.get("from"), "to": item.get("to")}
            for item in trace
            if item.get("kind") == "lexeme"
        ]
        if lexemes:
            data.setdefault("lexemes", tuple(lexemes))
        return Answer(
            answer.kind,
            answer.text,
            answer.plan_id,
            answer.proof,
            data,
        )

    def _plan(self, sem: Any, plan_id: str = "") -> Answer:
        selected = None
        captures: Dict[str, str] = {}
        for plan in self.plans:
            found = match_pattern(plan.match, sem)
            if found is not None:
                selected = plan
                captures = found
                break
        if selected is None:
            return self._unknown("unmatched")
        handler = getattr(
            self, "_answer_" + str(selected.answer.get("type", "")), None
        )
        if handler is None:
            return self._unknown(selected.id)
        return handler(selected, captures)

    # --- обработчики -------------------------------------------------

    def _answer_social(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        """Выбрать реакцию на речевое действие и синтезировать её.

        ``plan.answer.act`` называет акт из ``social.json``. Логическая
        форма приходит из парсера в ``captures``; если её нет, шаблон
        акта сопоставляется с ``captures`` напрямую. Реакция выбирается
        ``SocialEngine``, текст собирается конструкцией из
        ``synthesis.constructions``, эффект уходит в ``Answer.data`` для
        ``ConversationState.apply_effect``.
        """

        act_id = str(plan.answer.get("act") or "")
        bound = dict(captures)
        sem = bound.get("$sem")
        if not isinstance(sem, Mapping):
            sem = {"kind": "social", "act": act_id}
            for key, value in bound.items():
                if isinstance(key, str) and key.startswith("$"):
                    sem[key[1:]] = value
        bindings = social_bindings(sem, self.knowledge)
        for key, value in bound.items():
            if isinstance(key, str) and key.startswith("$") and value:
                bindings.setdefault(key[1:], str(value))
        decision = self.social_engine.decide(sem, bindings)
        if decision is None:
            return self._unknown(plan.id)
        data: Dict[str, Any] = {
            "act": decision.act_id,
            "reaction": decision.reaction_id,
            "effect": dict(decision.effect),
            "bindings": dict(decision.bindings),
            "social_trace": tuple(decision.trace),
            "reason": decision.reason,
        }
        text = self.realizer.construction(
            decision.construction, decision.bindings
        )
        if not text:
            text = self._social_fallback(decision)
        text = self.realizer.realize_answer(
            "social",
            {
                "message": text,
                "act": decision.act_id,
                "reaction": decision.reaction_id,
                "effect": dict(decision.effect),
            },
            fallback=text,
        )
        return Answer("social", text, plan.id, data=data)

    def _social_fallback(self, decision: SocialDecision) -> str:
        """Аварийный текст, если конструкция реакции не задана.

        Не стиль и не шаблон ответа, а защита от пустого
        ``synthesis.constructions``. Линтер требует конструкцию для
        каждой реакции, поэтому fallback в норме не срабатывает.
        """

        key = "social_" + str(decision.reaction_id or "clarify")
        fallback = self.answers.get(key) or self.answers.get("unknown", "")
        try:
            return str(fallback).format(**decision.bindings)
        except (KeyError, IndexError):
            return str(fallback)

    def _answer_smalltalk(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        key = str(plan.answer.get("key") or "")
        text = ""
        if key == "greeting":
            text = self.persona.greeting.format(
                speaker=self.knowledge.speaker_name
            )
        elif key in self.persona.smalltalk:
            text = self.persona.smalltalk[key]
        if not text:
            return self._unknown(plan.id)
        text = self.realizer.realize_answer(
            "smalltalk",
            {"message": text, "key": key},
            fallback=text,
            keys=("answer_smalltalk:" + key, "answer_smalltalk"),
        )
        return Answer("smalltalk", text, plan.id, data={"key": key})

    def _answer_prove(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        relation = str(plan.answer.get("relation") or "")
        args = _resolve_args(plan.answer.get("args") or (), captures)
        solutions = self.engine.prove(relation, args)
        if not solutions:
            missing = str(plan.answer.get("missing") or "unknown")
            if missing == "no":
                no = str(self.answers.get("no", "Нет."))
                text = self.realizer.realize_answer(
                    "no",
                    {
                        "relation": relation,
                        "args": self.realizer.values_for(relation, args),
                        "claim": "",
                        "message": no,
                    },
                    fallback=no,
                    keys=("answer_no:" + relation, "answer_no"),
                )
                return Answer("no", text, plan.id)
            return self._unknown(plan.id)
        solution = solutions[0]
        statement = self._statement(relation, args)
        yes = str(self.answers.get("yes", "Да."))
        text = (yes + " " + statement).strip()
        text = self.realizer.realize_answer(
            "yes",
            {
                "relation": relation,
                "args": self.realizer.values_for(relation, args),
                "claim": statement,
                "message": yes,
            },
            fallback=text,
            keys=("answer_yes:" + relation, "answer_yes"),
        )
        return Answer(
            "yes",
            text,
            plan.id,
            proof=(solution.proof,),
            data={"relation": relation, "args": args},
        )

    def _answer_explain(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        relation = str(plan.answer.get("relation") or "")
        args = _resolve_args(plan.answer.get("args") or (), captures)
        solutions = self.engine.prove(relation, args)
        if not solutions:
            return self._unknown(plan.id)
        solution = solutions[0]
        resolved = tuple(
            solution.bindings.get(item, item) for item in args
        )
        statement = self._statement(relation, resolved)
        prefix_key = str(plan.answer.get("prefix_key") or "")
        prefix = str(self.answers.get(prefix_key, "")) if prefix_key else ""
        if str(plan.answer.get("explain_with") or "") == "because":
            reason = str(solution.proof.because or "")
            if reason:
                statement = _capitalize(reason) + "."
        text = (prefix + statement).strip()
        text = self.realizer.realize_answer(
            "explanation",
            {"message": text, "relation": relation},
            fallback=text,
        )
        return Answer(
            "explanation",
            text,
            plan.id,
            proof=(solution.proof,),
            data={"relation": relation, "args": resolved},
        )

    def _answer_list(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        relation = str(plan.answer.get("relation") or "")
        args = _resolve_args(plan.answer.get("args") or (), captures)
        output = [str(item) for item in plan.output]
        item_name = output[0] if output else "item"
        label_name = output[1] if len(output) > 1 else ""
        items: List[Tuple[str, str]] = []
        seen_items: set = set()
        for solution in self.engine.prove(relation, args):
            item = solution.bindings.get("$" + item_name, "")
            if not item or item in seen_items:
                continue
            seen_items.add(item)
            label = ""
            label_relation = str(plan.answer.get("label_relation") or "")
            if label_relation:
                label_args = _resolve_args(
                    plan.answer.get("label_args") or (),
                    {**captures, **solution.bindings},
                )
                label_solution = self.engine.first(*(
                    [label_relation] + list(label_args)
                ))
                if label_solution is not None:
                    label = label_solution.bindings.get("$" + label_name, "")
            if not label:
                label = self.knowledge.surface(item, "nom")
            items.append((label, item))
        items.sort(key=lambda pair: (pair[0], pair[1]))
        items = items[: self.persona.max_list_items]
        key = str(plan.answer.get("intro_key") or "")
        owner = captures.get("$owner", "")
        if not items:
            text = self.realizer.list_empty(key, owner) if key else ""
            if not text:
                template = (self.answers.get("empty") or {}).get(key, "")
                text = (
                    template.format(
                        owner_gen=self.knowledge.surface(owner, "gen")
                    )
                    if template
                    else str(self.answers.get("no", "Нет."))
                )
            prefix_key = str(plan.answer.get("empty_prefix_key") or "")
            if prefix_key:
                prefix = str(self.answers.get(prefix_key, ""))
                text = (prefix + " " + text).strip()
            text = self.realizer.realize_answer(
                "no_reason",
                {
                    "owner": owner,
                    "items": [],
                    "key": key,
                    "message": text,
                },
                fallback=text,
                keys=("answer_no_list:" + key, "answer_no_list"),
            )
            return Answer("no", text, plan.id, data={"items": []})
        intro = self.realizer.list_intro(key, owner) if key else ""
        if not intro:
            intro = ((self.answers.get("list") or {}).get(key) or {}).get(
                "intro", ""
            )
            if intro:
                intro = intro.format(
                    owner_gen=self.knowledge.surface(owner, "gen")
                )
        separator = (
            self.realizer.list_separator(
                key, str(self.answers.get("list_separator", ", "))
            )
            if key
            else str(self.answers.get("list_separator", ", "))
        )
        ending = str(self.answers.get("list_end", "."))
        text = (
            intro + " " + separator.join(label for label, _ in items) + ending
        ).strip()
        prefix_key = str(plan.answer.get("prefix_key") or "")
        if prefix_key:
            prefix = str(self.answers.get(prefix_key, ""))
            text = (prefix + " " + text).strip()
        text = self.realizer.realize_answer(
            "list",
            {
                "owner": owner,
                "key": key,
                "items": [label for label, _ in items],
                "intro": intro,
                "separator": separator,
            },
            fallback=text,
            keys=(
                "answer_list:" + key,
                "answer_list:" + str(plan.id),
                "answer_list",
            ),
        )
        return Answer(
            "list",
            text,
            plan.id,
            data={"items": [item for _, item in items]},
        )

    def _answer_value(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        relation = str(plan.answer.get("relation") or "")
        args = _resolve_args(plan.answer.get("args") or (), captures)
        output = [str(item) for item in plan.output]
        value_name = output[0] if output else "value"
        solution = self.engine.first(relation, *args)
        if solution is None:
            return self._unknown(plan.id)
        value = solution.bindings.get("$" + value_name, "")
        owner = captures.get("$owner", "")
        prefix = str(plan.answer.get("label_prefix") or "")
        key = captures.get("$key", "")
        label_entity = prefix + key if prefix else ""
        template_key = str(plan.answer.get("template_key") or "value")
        text = self.realizer.answer(
            template_key,
            {
                "label": label_entity,
                "owner": owner,
                "value": value,
            },
        )
        if not text:
            label = (
                self.knowledge.surface(label_entity, "nom")
                if label_entity
                else label_entity
            )
            template = str(self.answers.get(template_key) or "")
            text = template.format(
                label=_capitalize(label),
                owner_gen=self.knowledge.surface(owner, "gen"),
                value=_format_number(value),
            )
        text = self.realizer.realize_answer(
            "value",
            {
                "owner": owner,
                "key": key,
                "value": value,
                "label": label_entity,
                "intro": text,
            },
            fallback=text,
            keys=(
                "answer_value:" + key,
                "answer_value:" + str(plan.id),
                "answer_value",
            ),
        )
        return Answer(
            "value",
            text,
            plan.id,
            data={"value": value, "owner": owner, "key": key},
        )

    def _answer_leader(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        owner = _resolve(str(plan.answer.get("owner") or ""), captures)
        relation = str(plan.answer.get("relation") or "")
        args = _resolve_args(plan.answer.get("args") or (), captures)
        output = [str(item) for item in plan.answer.get("output") or ()]
        solution = self.engine.first(relation, *args)
        if solution is None:
            return self._unknown(plan.id)
        values = {
            name: solution.bindings.get("$" + name, "")
            for name in output
        }
        data = {"owner": owner, **values}
        key = str(plan.answer.get("phrase_key") or "")
        text = self.realizer.answer(key, data) if key else ""
        if not text:
            template = str(self.answers.get("leader") or "")
            text = template.format(
                owner_gen=self.knowledge.surface(owner, "gen"),
                post=self.knowledge.surface(
                    values.get("post", ""), "nom"
                )
                if values.get("post")
                else "",
                person=values.get("person", ""),
            )
        text = self.realizer.realize_answer(
            "entity",
            {"owner": owner, **values, "message": text},
            fallback=text,
        )
        return Answer(
            "entity",
            text,
            plan.id,
            data={"owner": owner, **values},
        )

    def _answer_describe(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        target = _resolve(str(plan.answer.get("target") or ""), captures)
        text = self.realizer.describe(target)
        if not text:
            return self._unknown(plan.id)
        text = self.realizer.realize_answer(
            "description", {"message": text}, fallback=text
        )
        return Answer(
            "description",
            text,
            plan.id,
            data={"target": target},
        )

    def _answer_summary(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        target = _resolve(str(plan.answer.get("target") or ""), captures)
        text = self.realizer.summary(target)
        if not text:
            return self._unknown(plan.id)
        text = self.realizer.realize_answer(
            "summary", {"message": text}, fallback=text
        )
        return Answer(
            "summary",
            text,
            plan.id,
            data={"target": target},
        )

    def _answer_located(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        return self._statement_answer(
            plan, captures, str(plan.answer.get("relation") or "")
        )

    def _answer_started(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        return self._statement_answer(
            plan, captures, str(plan.answer.get("relation") or "")
        )

    def _answer_last_works(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        owner = _resolve(str(plan.answer.get("owner") or ""), captures)
        relation = str(plan.answer.get("relation") or "")
        keys = plan.answer.get("keys") or {}
        positions = plan.answer.get("args") or {}
        owner_arg = _index(positions, "owner", 0)
        turn_arg = _index(positions, "turn", 1)
        label_arg = _index(positions, "label", 2)
        success_arg = _index(positions, "success", 3)
        entries = [
            fact.args
            for fact in self.knowledge.facts_for(relation)
            if len(fact.args) > owner_arg and fact.args[owner_arg] == owner
        ]
        empty_key = str(keys.get("empty") or "")
        if not entries:
            text = (
                self.realizer.answer(empty_key, {"owner": owner})
                if empty_key
                else ""
            )
            if not text:
                template = str(self.answers.get(empty_key) or "")
                text = (
                    template.format(
                        owner_gen=self.knowledge.surface(owner, "gen")
                    )
                    if template
                    else ""
                )
            if text:
                return Answer("no", text, plan.id, data={"items": []})
            return self._unknown(plan.id)
        turns = []
        for args in entries:
            try:
                turns.append(int(float(args[turn_arg])))
            except (TypeError, ValueError, IndexError):
                continue
        if not turns:
            return self._unknown(plan.id)
        last = max(turns)
        items = []
        for args in entries:
            try:
                turn = int(float(args[turn_arg]))
            except (TypeError, ValueError, IndexError):
                continue
            if turn != last:
                continue
            label = args[label_arg] if len(args) > label_arg else ""
            success = (
                args[success_arg] if len(args) > success_arg else "0"
            ) == "1"
            template_key = str(
                keys.get("success" if success else "failure")
                or ("last_work_success" if success else "last_work_failure")
            )
            text = self.realizer.answer(template_key, {"label": label})
            if not text:
                template = str(self.answers.get(template_key) or "")
                text = template.format(label=label)
            if text:
                items.append(text)
        if not items:
            return self._unknown(plan.id)
        intro_key = str(keys.get("intro") or "last_work_intro")
        intro = self.realizer.answer(intro_key, {"owner": owner})
        if not intro:
            intro = str(self.answers.get(intro_key) or "").format(
                owner_gen=self.knowledge.surface(owner, "gen")
            )
        text = (intro + " " + " ".join(items)).strip()
        return Answer(
            "list",
            text,
            plan.id,
            data={"turn": last, "items": items},
        )

    # --- общие помощники --------------------------------------------

    def _unknown(self, plan_id: str = "") -> Answer:
        message = str(
            self.persona.unknown or self.answers.get("unknown", "")
        )
        text = self.realizer.realize_answer(
            "unknown",
            {"message": message, "plan": plan_id},
            fallback=message,
            keys=("answer_unknown",),
        )
        return Answer("unknown", text, plan_id)

    def _statement(self, relation: str, args: Iterable[str]) -> str:
        rendered = self.realizer.statement(relation, args)
        if rendered:
            return rendered
        spec = (self.realization.get("statements") or {}).get(relation) or {}
        template = str(spec.get("template") or "")
        if not template:
            return ""
        args = tuple(str(item) for item in args)
        data: Dict[str, str] = {}
        for name, slot in (spec.get("slots") or {}).items():
            try:
                index = int(slot.get("arg", 0))
                value = args[index] if index < len(args) else ""
            except (TypeError, ValueError):
                value = ""
            case = str(slot.get("case") or "")
            data[str(name)] = (
                self.knowledge.surface(value, case) if case else value
            )
        try:
            return _capitalize(template.format(**data))
        except (KeyError, IndexError):
            return ""

    def _statement_answer(
        self,
        plan: PlanSpec,
        captures: Mapping[str, str],
        relation: str,
    ) -> Answer:
        args = _resolve_args(plan.answer.get("args") or (), captures)
        solution = self.engine.first(relation, *args)
        if solution is None:
            return self._unknown(plan.id)
        resolved = tuple(
            solution.bindings.get(item, item) for item in args
        )
        statement = self._statement(relation, resolved)
        text = self.realizer.realize_answer(
            "explanation",
            {"message": statement, "relation": relation},
            fallback=statement,
        )
        return Answer(
            "explanation",
            text,
            plan.id,
            proof=(solution.proof,),
            data={"relation": relation, "args": resolved},
        )

    def _belief_sentences(self, target: str) -> List[str]:
        sentences = self.realizer.belief_sentences(target)
        if sentences:
            return sentences
        # Аварийный fallback: старые шаблоны убеждений.
        specs = self.realization.get("beliefs") or {}
        fallback: List[str] = []
        for fact in self.knowledge.facts_for("belief"):
            if len(fact.args) < 4:
                continue
            holder, subject, predicate, obj = fact.args[:4]
            if holder != self.knowledge.speaker_id:
                continue
            if subject != target and obj != target:
                continue
            spec = specs.get(predicate) or specs.get("fallback") or {}
            template = str(spec.get("template") or "")
            if not template:
                continue
            data = {
                "subject": self.knowledge.surface(
                    subject, str(spec.get("subject_case") or "nom")
                ),
                "object": self.knowledge.surface(
                    obj, str(spec.get("object_case") or "nom")
                )
                if obj
                else "",
                "predicate": predicate,
            }
            if "object" in template and not data["object"]:
                continue
            try:
                fallback.append(_capitalize(template.format(**data)))
            except (KeyError, IndexError):
                continue
        return fallback


def _capitalize(text: str) -> str:
    text = str(text or "")
    return text[:1].upper() + text[1:] if text else text