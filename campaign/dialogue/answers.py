"""Планирование ответа и детерминированный синтез текста.

Планы, конструкции, поля описания и морфологические исключения живут в
JSON. Python только сопоставляет логическую форму с планом, доказывает
цель и передаёт смысл в композиционный реализатор.

D4 добавляет тип ответа ``social``.
D5.1 добавляет дискурсивный слой (ходы и связки).
D5.3 добавляет агрегацию (``mode: clause``), анафору внутри ответа и
порядок тема-рема. ``_discourse`` гарантированно снабжает ходы
``entities``, чтобы анафора работала даже если ``_build_moves``
вернул ходы без этого поля.
D3.1 добавляет тип ответа ``comparison``.
D3.2 добавляет тип ответа ``counterfactual``.
D5.4 добавляет порядок абзаца через ``topics: [...]``.
D6.2a добавляет отрицание (``negated: true``) в антецеденте
контрфакта: ``remove`` и ``add`` из плана меняются местами.
D6.3 добавляет политику раскрытия (``disclosure.json``) и
детерминированную ложь с трассировкой в ``Answer.data``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .counterfactual import CounterfactualEngine
from .inference import InferenceEngine, ProofStep, Solution, is_variable
from .knowledge import AgentKnowledge, Fact
from .model import DialogueCatalog, Persona, PlanSpec, StyleSpec
from .realize import ACT_FOR_KIND, Realizer, render_lines
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


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fact_from(spec: Mapping[str, Any], values: Mapping[str, Any]) -> Fact:
    """Собрать ``Fact`` из описания в плане с подстановкой значений.

    ``values`` — захваты шаблона плюс служебные значения вроде
    ``$speaker`` и уже разрешённого ``$rel``. Имя отношения тоже может
    быть переменной: в контрфакте оно приходит из антецедента и
    резолвится через ``predicate_relations``.
    """

    rel = str(spec.get("rel") or "")
    if rel.startswith("$"):
        rel = str(values.get(rel, rel))
    raw_args = spec.get("args") or ()
    args = tuple(_resolve(str(item), values) for item in raw_args)
    return Fact(rel, args)


def _nested_entity(value: Any) -> str:
    """Найти сущность в логической форме (``np``/``pp``/``topic``).

    D6.2c/D6.2b: антецедент и следствие приходят как вложенные структуры
    разбора. Нам нужен только идентификатор сущности, чтобы передать его
    в ``CounterfactualEngine.compare``. Строка возвращается как есть,
    чтобы поддерживать и «плоские» семантические формы.
    """

    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _nested_entity(item)
            if found:
                return found
        return ""
    if isinstance(value, Mapping):
        for key in ("entity", "head", "object", "topic"):
            if key in value:
                found = _nested_entity(value[key])
                if found:
                    return found
        for item in value.values():
            found = _nested_entity(item)
            if found:
                return found
    return ""


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
        self.memory = memory
        self.engine = InferenceEngine(catalog, knowledge)
        self.style_engine = style_engine or StyleEngine(catalog)
        self.social_engine = SocialEngine(
            catalog, knowledge, self.engine
        )
        self.counterfactual = CounterfactualEngine(catalog, knowledge)
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
        self.style = style or StyleSpec(id="", label="")
        self.realizer.set_style(self.style)

    def plan(
        self, sem: Any, plan_id: str = "", style: Optional[StyleSpec] = None
    ) -> Answer:
        if style is not None:
            self.set_style(style)
        self.realizer.take_trace()
        self.realizer.take_discourse_trace()
        answer = self._plan(sem, plan_id)
        answer = self._discourse(answer)
        trace = self.realizer.take_trace()
        discourse = self.realizer.take_discourse_trace()
        data = dict(answer.data or {})
        if trace:
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
        if discourse:
            data.setdefault("discourse_trace", tuple(discourse))
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
        if (
            isinstance(sem, Mapping)
            and sem.get("kind") == "counterfactual"
        ):
            captures = dict(captures)
            captures["$sem"] = sem
        handler = getattr(
            self, "_answer_" + str(selected.answer.get("type", "")), None
        )
        if handler is None:
            return self._unknown(selected.id)
        answer = handler(selected, captures)
        return self._disclose(answer, selected, captures)

    # --- раскрытие и ложь (D6.3) ------------------------------------

    _DISCLOSURE_KINDS = frozenset(
        {
            "yes",
            "no",
            "explanation",
            "value",
            "list",
            "description",
            "summary",
            "located",
            "started",
            "last_works",
            "entity",
        }
    )

    def _disclosure_topic(
        self, answer: Answer, plan: PlanSpec, captures: Mapping[str, str]
    ) -> str:
        """Тема раскрытия: отношение ответа или план-источник."""

        data = answer.data or {}
        for key in ("relation", "predicate", "topic"):
            value = str(data.get(key) or "")
            if value:
                return value
        relation = _resolve(
            str(plan.answer.get("relation") or ""), captures
        )
        return relation or str(plan.id)

    def _disclosure_policy(self, topic: str) -> str:
        """Политика персоны для темы; честность — безопасный умолчал."""

        spec = self.catalog.disclosure or {}
        persona = self.persona.disclosure or {}
        on_topic = persona.get("on_topic") or {}
        if not isinstance(on_topic, Mapping):
            on_topic = {}
        for value in (
            on_topic.get(topic),
            persona.get("default"),
            spec.get("default"),
            "honest",
        ):
            policy = str(value or "")
            if policy:
                return policy
        return "honest"

    def _lie_score(self, topic: str, args: Any) -> float:
        """Детерминированный бросок в [0, 1] по seed-у кампании.

        Это не статистика и не обучение: одинаковые run_id, ход, тема и
        аргументы всегда дают один и тот же результат.
        """

        spec = self.catalog.disclosure or {}
        salt = str(spec.get("salt") or "disclosure")
        turns = getattr(self.memory, "turns", 0) if self.memory else 0
        payload = "|".join(
            (
                salt,
                str(self.knowledge.run_id),
                str(self.knowledge.speaker_id),
                str(turns),
                str(topic),
                ",".join(str(item) for item in args or ()),
            )
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) / float(0xFFFFFFFF)

    def _disclose(
        self, answer: Answer, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        """Применить политику раскрытия к информативному ответу.

        D6.3. Политика выбирается по теме из ``persona.disclosure``;
        исход и тексты заданы в ``disclosure.json``. Ложь включается
        только при ``score < lie_probability`` и всегда оставляет в
        ``Answer.data`` истинный ответ и признак ``lied``.
        """

        if answer.kind not in self._DISCLOSURE_KINDS:
            return answer
        spec = self.catalog.disclosure or {}
        policies = spec.get("policies") or {}
        if not policies:
            return answer
        topic = self._disclosure_topic(answer, plan, captures)
        policy_id = self._disclosure_policy(topic)
        if policy_id == "honest":
            return answer
        policy = policies.get(policy_id)
        if not isinstance(policy, Mapping):
            return answer
        outcome = str(policy.get("outcome") or "truth")
        data = dict(answer.data or {})
        data["disclosure"] = policy_id
        data["disclosure_topic"] = topic
        if outcome == "truth":
            return answer
        if outcome == "partial":
            prefix = str(policy.get("prefix") or "")
            text = (prefix + answer.text).strip()
            data["partial"] = True
            return Answer(
                answer.kind, text, answer.plan_id, answer.proof, data
            )
        if outcome in ("withhold", "evade"):
            text = str(policy.get("text") or "")
            if not text:
                return answer
            data["truth_text"] = answer.text
            data["truth_kind"] = answer.kind
            data["withheld"] = outcome == "withhold"
            data["evaded"] = outcome == "evade"
            return Answer(answer.kind, text, answer.plan_id, (), data)
        if outcome != "lie":
            return answer
        probability = max(
            0.0, min(1.0, float(self.persona.lie_probability or 0.0))
        )
        score = self._lie_score(topic, data.get("args") or ())
        data["lie_score"] = score
        data["lie_probability"] = probability
        if score >= probability:
            data["lied"] = False
            return Answer(
                answer.kind, answer.text, answer.plan_id, answer.proof, data
            )
        if answer.kind == "yes":
            key = "yes"
        elif answer.kind == "no":
            key = "no"
        else:
            key = "other"
        text = str(
            policy.get(key)
            or policy.get("other")
            or self.answers.get("no")
            or "Нет."
        )
        data["truth_text"] = answer.text
        data["truth_kind"] = answer.kind
        data["truth_relation"] = str(data.get("relation") or "")
        data["truth_args"] = tuple(data.get("args") or ())
        data["lied"] = True
        return Answer(answer.kind, text, answer.plan_id, (), data)

    # --- дискурсивный слой -----------------------------------------

    def _discourse(self, answer: Answer) -> Answer:
        if StyleEngine.is_neutral(self.style):
            return answer
        discourse = getattr(self.catalog, "discourse", None)
        if discourse is None:
            return answer
        pattern = discourse.pattern_for(answer.kind, answer.plan_id)
        if pattern is None:
            return answer
        moves = self._build_moves(answer, pattern)
        if not moves:
            return answer
        if not any(move.get("entities") for move in moves):
            entities = self._fallback_entities(answer)
            if entities:
                for move in moves:
                    move["entities"] = entities
        text = self.realizer.render_moves(moves)
        if not text:
            return answer
        discourse_trace = self.realizer.take_discourse_trace()
        data = dict(answer.data or {})
        data["moves"] = tuple(
            {
                "id": move["id"],
                "kind": move["kind"],
                "act": move.get("act", ""),
                "text": move["text"],
            }
            for move in moves
        )
        if discourse_trace:
            data["discourse_trace"] = tuple(discourse_trace)
        return Answer(
            answer.kind,
            text,
            answer.plan_id,
            answer.proof,
            data,
        )

    def _build_moves(
        self, answer: Answer, pattern: Any
    ) -> List[Dict[str, Any]]:
        discourse = getattr(self.catalog, "discourse", None)
        if discourse is None:
            return []
        entities = self._answer_entities_for_anaphora(answer)
        ordered = self._ordered_moves(pattern)
        result: List[Dict[str, Any]] = []
        for move_id in ordered:
            spec = discourse.move(move_id)
            if spec is None:
                continue
            text, act = self._move_text(spec, answer)
            if not text:
                if bool(spec.optional):
                    continue
                return []
            result.append(
                {
                    "id": spec.id,
                    "kind": spec.id,
                    "act": act,
                    "text": text,
                    "entities": entities,
                }
            )
        return result

    def _ordered_moves(self, pattern: Any) -> List[str]:
        """Порядок ходов: ``topics`` → ``topic`` → остальные ``moves``.

        D5.4. ``topics`` (абзац 4+ хода) идёт первым; ``topic`` (один
        ход) — частный случай, если ``topics`` пусто. Дубликаты
        дедуплицируются с сохранением первого вхождения. Ходы из
        ``topics``/``topic``, которых нет в ``moves``, пропускаются —
        это защита от опечаток в данных; линтер такие случаи ловит.
        """

        moves: List[str] = list(pattern.moves)
        seen: set = set()
        ordered: List[str] = []

        def add(name: Any) -> None:
            text = str(name or "")
            if not text or text in seen:
                return
            if text not in moves:
                return
            seen.add(text)
            ordered.append(text)

        topics = getattr(pattern, "topics", ()) or ()
        for name in topics:
            add(name)
        topic = str(getattr(pattern, "topic", "") or "")
        if topic:
            add(topic)
        for name in moves:
            add(name)
        return ordered

    def _fallback_entities(self, answer: Answer) -> Tuple[str, ...]:
        """Сущности из ``catalog.lexicon`` по ``args``/``target``/``owner``.

        Нужны, если адаптер знания пуст или не содержит эти id. Тип и
        имя реализатор всё равно возьмёт через лексикон. Это делает
        анафору независимой от ``knowledge.entities``.
        """

        known = {entry.id for entry in self.catalog.lexicon}
        data = dict(answer.data or {})
        found: List[str] = []

        def add(value: Any) -> None:
            text = str(value or "")
            if not text or ":" not in text:
                return
            if text not in known:
                return
            if text not in found:
                found.append(text)

        args = data.get("args") or ()
        if isinstance(args, (list, tuple)):
            for item in args:
                add(item)
        for key in ("target", "owner", "left", "right"):
            add(data.get(key))
        return tuple(found)

    def _answer_entities_for_anaphora(
        self, answer: Answer
    ) -> Tuple[str, ...]:
        known = {entry.id for entry in self.catalog.lexicon}
        data = dict(answer.data or {})
        found: List[str] = []

        def add(value: Any) -> None:
            text = str(value or "")
            if not text or ":" not in text:
                return
            if text not in known:
                return
            if text not in found:
                found.append(text)

        args = data.get("args") or ()
        if isinstance(args, (list, tuple)):
            for item in args:
                add(item)
        for key in ("target", "owner", "left", "right"):
            add(data.get(key))
        return tuple(found)

    def _move_text(
        self, spec: Any, answer: Answer
    ) -> Tuple[str, str]:
        data = dict(answer.data or {})
        if spec.act:
            text, act = self._move_act(spec, answer, data)
            return text, act
        if spec.construction:
            values = dict(data)
            values.setdefault("message", answer.text)
            text = self.realizer.construction(spec.construction, values)
            return text, spec.id
        if spec.relation:
            value = data.get(spec.source, "")
            if isinstance(value, str) and value:
                text = value
            else:
                payload = data.get("reason_args") or ()
                if payload:
                    text = self.realizer.statement(
                        spec.relation, tuple(str(item) for item in payload)
                    )
                else:
                    text = ""
            return text, spec.id
        if spec.source:
            value = data.get(spec.source, "")
            if isinstance(value, str) and value:
                return value, spec.id
        return "", spec.id

    def _move_act(
        self, spec: Any, answer: Answer, data: Mapping[str, Any]
    ) -> Tuple[str, str]:
        act = str(spec.act)
        if act == "answer":
            return answer.text, act
        values = dict(data)
        values.setdefault("message", answer.text)
        values.setdefault("claim", answer.text)
        text = self.realizer.realize_act(act, values, fallback="")
        return text, act

    # --- обработчики ------------------------------------------------

    def _answer_social(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
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
                return Answer(
                    "no",
                    text,
                    plan.id,
                    data={"relation": relation, "args": args},
                )
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
            data={
                "relation": relation,
                "args": args,
            },
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
        max_premises = self._max_premises(plan)
        reasons = self._reasons_for(solution.proof, max_premises)
        text = statement
        if str(plan.answer.get("explain_with") or "") == "because":
            if reasons:
                text = _capitalize(reasons[0]) + "."
        text = (prefix + text).strip()
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
            data={
                "relation": relation,
                "args": resolved,
                "reason": reasons[0] if reasons else "",
                "reasons": tuple(reasons),
                "reason_args": resolved,
            },
        )

    def _max_premises(self, plan: PlanSpec) -> int:
        try:
            value = int(plan.answer.get("max_premises") or 1)
        except (TypeError, ValueError):
            value = 1
        return max(1, value)

    def _reasons_for(
        self, proof: ProofStep, limit: int
    ) -> List[str]:
        found: List[str] = []

        def walk(step: ProofStep) -> None:
            if len(found) >= limit:
                return
            text = str(getattr(step, "because", "") or "")
            if text:
                found.append(text)
            for child in getattr(step, "children", ()) or ():
                if len(found) >= limit:
                    return
                walk(child)

        if proof is not None:
            walk(proof)
        return found[:limit]

    def _reason_for(self, proof: ProofStep) -> str:
        reasons = self._reasons_for(proof, 1)
        return reasons[0] if reasons else ""

    def _answer_comparison(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        relation = _resolve(
            str(plan.answer.get("relation") or ""), captures
        )
        left = _resolve(str(plan.answer.get("left") or ""), captures)
        right = _resolve(str(plan.answer.get("right") or ""), captures)
        key = _resolve(str(plan.answer.get("key") or ""), captures)
        comparison = getattr(self.catalog, "comparison", None)
        spec = comparison.get(relation) if comparison is not None else None
        if spec is None:
            return self._unknown(plan.id)
        left_value = self._value_for(spec, left, key)
        right_value = self._value_for(spec, right, key)
        left_number = _to_float(left_value) if left_value else None
        right_number = _to_float(right_value) if right_value else None
        data = {
            "relation": relation,
            "left": left,
            "right": right,
            "key": key,
            "left_name": self.knowledge.name(left),
            "right_name": self.knowledge.name(right),
            "key_gen": self.knowledge.surface(key, "gen"),
            "key_dat": self.knowledge.surface(key, "dat"),
            "left_value": left_value,
            "right_value": right_value,
        }
        construction, outcome = self._comparison_outcome(
            spec, left_number, right_number
        )
        if not construction:
            return self._unknown(plan.id)
        text = self.realizer.construction(construction, data)
        if not text:
            return self._unknown(plan.id)
        text = self.realizer.realize_answer(
            "comparison",
            {**data, "message": text, "outcome": outcome},
            fallback=text,
        )
        data["outcome"] = outcome
        data["construction"] = construction
        if left_number is not None:
            data["left_value"] = left_number
        if right_number is not None:
            data["right_value"] = right_number
        return Answer("comparison", text, plan.id, data=data)

    def _value_for(
        self, spec: Any, subject: str, key: str
    ) -> str:
        relation = str(spec.relation or "")
        if not relation:
            return ""
        normalized_key = str(key or "")
        prefix = str(getattr(spec, "key_prefix", "") or "")
        if prefix and normalized_key.startswith(prefix):
            normalized_key = normalized_key[len(prefix):]
        size = max(spec.value_arg, spec.key_arg, spec.subject_arg) + 1
        args: List[str] = [
            "$unused_%d" % index for index in range(size)
        ]
        args[spec.subject_arg] = subject
        args[spec.key_arg] = normalized_key
        args[spec.value_arg] = "$value"
        solution = self.engine.first(relation, *args)
        if solution is None:
            return ""
        for variable, value in solution.bindings.items():
            if variable == "$value":
                return str(value)
        return ""

    def _comparison_outcome(
        self,
        spec: Any,
        left_number: Optional[float],
        right_number: Optional[float],
    ) -> Tuple[str, str]:
        if left_number is None and right_number is None:
            return str(spec.both_unknown or ""), "both_unknown"
        if left_number is None:
            return str(spec.unknown_left or ""), "unknown_left"
        if right_number is None:
            return str(spec.unknown_right or ""), "unknown_right"
        if left_number == right_number:
            return str(spec.equal or ""), "equal"
        if left_number > right_number:
            return str(spec.greater or ""), "greater"
        return str(spec.less or ""), "less"

    def _predicate_mapping(self, predicate: str) -> Mapping[str, Any]:
        """Спецификация ``predicate → relation`` из ``world.json``."""

        table = (self.knowledge.world or {}).get(
            "predicate_relations"
        ) or {}
        spec = table.get(str(predicate or ""))
        if isinstance(spec, str):
            return {"relation": spec}
        if isinstance(spec, Mapping):
            return spec
        return {}

    def _predicate_relation(
        self, predicate: str, fallback: str = ""
    ) -> str:
        """Имя отношения мира для предиката разбора (D6.2c).

        Если маппинга нет, возвращается исходное имя — так сохраняется
        прежнее поведение для уже согласованных предикатов.
        """

        relation = str(
            self._predicate_mapping(predicate).get("relation") or ""
        )
        if relation:
            return relation
        return str(fallback or predicate or "")

    def _assertion_target(
        self, assertion: Any
    ) -> Tuple[str, Tuple[str, ...]]:
        """Цель сравнения из утверждения (антецедент/следствие).

        D6.2b: следствие «то …» задаёт, что именно проверять в
        контрмодели. Предикат проходит через ``predicate_relations``;
        ``have`` даёт ``has_organ``, остальные — пару
        «субъект, объект». Свойства без объекта возвращают один
        аргумент.
        """

        if not isinstance(assertion, Mapping):
            return "", ()
        if bool(assertion.get("have")):
            predicate = "have"
        elif bool(assertion.get("copula")):
            return "", ()
        else:
            predicate = str(assertion.get("predicate") or "")
        if not predicate:
            return "", ()
        relation = self._predicate_relation(predicate)
        subject = _nested_entity(assertion.get("subject"))
        obj = _nested_entity(assertion.get("object"))
        args: List[str] = []
        if subject:
            args.append(subject)
        if obj:
            args.append(obj)
        return relation, tuple(args)

    def _answer_counterfactual(
        self, plan: PlanSpec, captures: Mapping[str, str]
    ) -> Answer:
        """Построить контрфакт по антецеденту и цели из плана.

        D6.2c: предикат разбора резолвится в отношение мира через
        ``world.predicate_relations``. Если у маппинга задан исходный
        факт (``remove``), подменяется он, а не производное отношение:
        ``considers_outlaw`` доказывается из ``belief``, поэтому
        удалять надо именно ``belief``.

        D6.2b: если в форме есть ``consequent`` («…, то …»), его
        отношение и аргументы становятся целью сравнения; антецедент
        остаётся подменой фактов.

        D6.2a: если антецедент отрицательный (``negated: true``),
        ``remove`` и ``add`` меняются местами: отрицание означает
        «добавить то, чего не было», а не «убрать то, что есть».
        """

        if not self.counterfactual.enabled():
            return self._unknown(plan.id)
        values: Dict[str, Any] = dict(captures)
        values["$speaker"] = self.knowledge.speaker_id
        predicate = _resolve(
            str(plan.answer.get("relation") or ""), captures
        )
        relation = self._predicate_relation(predicate)
        args = _resolve_args(plan.answer.get("args") or (), captures)
        negated = False
        consequent: Any = None
        sem = captures.get("$sem")
        if isinstance(sem, Mapping):
            antecedent = sem.get("antecedent")
            if isinstance(antecedent, Mapping):
                negated = bool(antecedent.get("negated"))
            consequent = sem.get("consequent")
        consequent_relation, consequent_args = self._assertion_target(
            consequent
        )
        if consequent_relation:
            relation = consequent_relation
            args = consequent_args
        remove_spec = plan.answer.get("remove") or ()
        add_spec = plan.answer.get("add") or ()
        mapping = self._predicate_mapping(predicate)
        source = mapping.get("remove")
        values["$rel"] = relation
        if isinstance(source, Mapping):
            remove = [_fact_from(source, values)]
        else:
            remove = [
                _fact_from(item, values)
                for item in remove_spec
                if isinstance(item, Mapping)
            ]
        add = [
            _fact_from(item, values)
            for item in add_spec
            if isinstance(item, Mapping)
        ]
        if negated:
            remove, add = add, remove
        result = self.counterfactual.compare(
            relation, args, remove=remove, add=add
        )
        if not result.construction:
            return self._unknown(plan.id)
        target = _resolve(
            str(plan.answer.get("target") or ""), captures
        )
        data: Dict[str, Any] = {
            "relation": relation,
            "args": args,
            "predicate": predicate,
            "outcome": result.outcome,
            "differences": result.differences,
            "removed": result.removed,
            "added": result.added,
            "target": target,
            "target_name": (
                self.knowledge.name(target) if target else ""
            ),
            "negated": negated,
        }
        if consequent is not None:
            data["consequent"] = consequent
        text = self.realizer.construction(result.construction, data)
        if not text:
            return self._unknown(plan.id)
        return Answer(
            "counterfactual",
            text,
            plan.id,
            data=data,
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
            data={
                "items": [item for _, item in items],
                "labels": [label for label, _ in items],
                "owner": owner,
                "key": key,
            },
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
            data={
                "value": value,
                "owner": owner,
                "key": key,
                "label": label_entity,
            },
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

    # --- общие помощники -------------------------------------------

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
            data={
                "relation": relation,
                "args": resolved,
                "reason": self._reason_for(solution.proof),
                "reason_args": resolved,
            },
        )

    def _belief_sentences(self, target: str) -> List[str]:
        sentences = self.realizer.belief_sentences(target)
        if sentences:
            return sentences
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
    text = text[:1].upper() + text[1:] if text else text
    return text
