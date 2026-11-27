"""Планирование ответа и детерминированный синтез текста.

Общие типы и помощники — в ``answers_support``, предметные ответы — в
``answers_answer``. Публичный API ``Answer``/``AnswerPlanner`` сохранён.
"""

from __future__ import annotations

from .answers_answer import AnswerAnswerMixin
from .answers_support import (
    AgentKnowledge,
    Answer,
    Any,
    CounterfactualEngine,
    DialogueCatalog,
    Dict,
    InferenceEngine,
    List,
    Mapping,
    Optional,
    Persona,
    PlanSpec,
    Realizer,
    SocialEngine,
    StyleEngine,
    StyleSpec,
    Tuple,
    _resolve,
    _text_key,
    answer_handler_name,
    hashlib,
    match_pattern,
)


class AnswerPlanner(AnswerAnswerMixin):
    """Сопоставляет логическую форму с планом и исполняет его."""

    def __init__(
        self,
        catalog: DialogueCatalog,
        knowledge: AgentKnowledge,
        persona: Persona,
        style_engine: Optional[StyleEngine] = None,
        memory: Any = None,
        pragmatics: Any = None,
        inference: Any = None,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.persona = persona
        self.memory = memory
        self.pragmatics = pragmatics
        self.inference = inference
        self.engine = (
            inference
            if inference is not None
            else InferenceEngine(catalog, knowledge)
        )
        self.style_engine = style_engine or StyleEngine(catalog)
        self.social_engine = SocialEngine(
            catalog, knowledge, self.engine
        )
        self.counterfactual = CounterfactualEngine(
            catalog, knowledge, backend=self.inference
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
        self.style = style or StyleSpec(id="", label="")
        self.realizer.set_style(self.style)

    def plan(
        self,
        sem: Any,
        plan_id: str = "",
        style: Optional[StyleSpec] = None,
        detail: bool = False,
    ) -> Answer:
        if style is not None:
            self.set_style(style)
        self.realizer.take_trace()
        self.realizer.take_discourse_trace()
        answer = self._plan(sem, plan_id)
        answer = self._discourse(answer, detail=detail)
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
        candidates: List[Tuple[str, float, int]] = []
        for index, plan in enumerate(self.plans):
            found = match_pattern(plan.match, sem)
            if found is None:
                continue
            candidates.append((plan.id, float(plan.priority), index))
            if selected is None:
                selected = plan
                captures = found
        if selected is None:
            return self._unknown("unmatched")
        if self.pragmatics is not None and candidates:
            chosen = self.pragmatics.choose_plan(
                candidates, self._frame(sem), selected.id
            )
            if chosen != selected.id:
                for plan in self.plans:
                    if plan.id != chosen:
                        continue
                    found = match_pattern(plan.match, sem)
                    if found is not None:
                        selected = plan
                        captures = found
                    break
        if (
            isinstance(sem, Mapping)
            and sem.get("kind") == "counterfactual"
        ):
            captures = dict(captures)
            captures["$sem"] = sem
        handler_name = answer_handler_name(
            str(selected.answer.get("type", "")),
            getattr(self.catalog, "answer_kinds", {}) or {},
        )
        handler = getattr(self, "_answer_" + handler_name, None)
        if handler is None:
            return self._unknown(selected.id)
        answer = handler(selected, captures)
        answer = self._with_pragmatics(answer)
        return self._disclose(answer, selected, captures, sem=sem)

    def _with_pragmatics(self, answer: Answer) -> Answer:
        """Пометить ответ выбором Soar, не трогая текст и вывод."""

        if self.pragmatics is None or not self.pragmatics.active:
            return answer
        data = dict(answer.data or {})
        data["pragmatics_backend"] = self.pragmatics.backend
        trace = self.pragmatics.last_trace
        if trace:
            data["pragmatics_trace"] = tuple(trace)
        return Answer(
            answer.kind, answer.text, answer.plan_id, answer.proof, data
        )

    @staticmethod
    def _frame(sem: Any) -> Mapping[str, str]:
        """Класс кадра для Soar: только данные, без вывода."""

        if not isinstance(sem, Mapping):
            return {"kind": "", "act": "", "wh": ""}
        return {
            "kind": str(sem.get("kind") or ""),
            "act": str(sem.get("act") or ""),
            "wh": str(sem.get("wh") or ""),
        }

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
            "relation",
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
        self,
        answer: Answer,
        plan: PlanSpec,
        captures: Mapping[str, str],
        sem: Any = None,
    ) -> Answer:
        """Применить политику раскрытия к информативному ответу.

        D6.3. Политика выбирается по теме из ``persona.disclosure``;
        исход и тексты заданы в ``disclosure.json``. Ложь включается
        только при ``score < lie_probability`` и всегда оставляет в
        ``Answer.data`` истинный ответ и признак ``lied``.

        В режиме ``soar`` исход выбирает Soar; детерминированный бросок
        для лжи считает Python и передаёт флагом, чтобы продукции не
        сравнивали числа с плавающей точкой.
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
        active = self.pragmatics is not None and self.pragmatics.active
        if active:
            lie_flag = False
            if outcome == "lie":
                probability = max(
                    0.0,
                    min(
                        1.0,
                        float(self.persona.lie_probability or 0.0),
                    ),
                )
                score = self._lie_score(topic, data.get("args") or ())
                lie_flag = score < probability
            outcome = self.pragmatics.choose_disclosure(
                plan.id,
                policy_id,
                lie_flag,
                topic,
                outcome,
                frame=self._frame(sem),
            )
            data["pragmatics_backend"] = self.pragmatics.backend
            trace = self.pragmatics.last_trace
            if trace:
                data["pragmatics_trace"] = tuple(trace)
        if outcome == "truth":
            if not active:
                return answer
            return Answer(
                answer.kind,
                answer.text,
                answer.plan_id,
                answer.proof,
                data,
            )
        data["disclosure"] = policy_id
        data["disclosure_topic"] = topic
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

    def _discourse(self, answer: Answer, detail: bool = False) -> Answer:
        if StyleEngine.is_neutral(self.style) and not detail:
            return answer
        discourse = getattr(self.catalog, "discourse", None)
        if discourse is None:
            return answer
        pattern = discourse.pattern_for(
            answer.kind, answer.plan_id, detail=detail
        )
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
        text = self.realizer.render_moves(
            moves, connectives=pattern.connectives
        )
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
        data = dict(answer.data or {})
        reason_in_text = bool(data.get("reason_in_text"))
        result: List[Dict[str, Any]] = []
        seen_texts: set = set()
        for move_id in ordered:
            spec = discourse.move(move_id)
            if spec is None:
                continue
            if reason_in_text and str(spec.source or "") == "reason":
                continue
            text, act = self._move_text(spec, answer)
            if not text:
                if bool(spec.optional):
                    continue
                return []
            if str(spec.source or "") == "statement":
                core = _text_key(text)
                if core and core in _text_key(answer.text):
                    continue
            key = _text_key(text)
            if key in seen_texts:
                continue
            seen_texts.add(key)
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
