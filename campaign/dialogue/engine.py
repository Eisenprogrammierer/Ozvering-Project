"""Сессия диалога: разбор фразы → состояние → план → ответ.

D2 добавляет к read-only слою QUD, активные референты, разрешение
местоимений, декларативный эллипсис и память партии. D4 добавляет
речевые действия: эффект реакции из ``social.json`` записывается в
``ConversationState.commitments``. Состояние разговора не меняет
кампанию и BDI: оно лишь читает снимок знания и хранит следы беседы
для связности.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .answers import Answer, AnswerPlanner
from .knowledge import AgentKnowledge
from .morph import Morphology
from .model import DialogueCatalog, Parse, Persona
from .parser import ChartParser
from .state import DialogueMemory, build_state
from .style import StyleEngine


@dataclass(frozen=True)
class Turn:
    """Один обмен: разбор, ответ и сработавший план."""

    input: str
    parse: Optional[Parse]
    answer: Answer
    sem: Any = None
    source: str = "parser"
    state: Mapping[str, Any] = field(default_factory=dict)


class DialogueSession:
    """Детерминированный ответчик для одного агента."""

    def __init__(
        self,
        catalog: DialogueCatalog,
        knowledge: AgentKnowledge,
        persona_id: Optional[str] = None,
        memory: Optional[DialogueMemory] = None,
        style_id: Optional[str] = None,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.parser = ChartParser(catalog)
        self.persona = _select_persona(catalog, persona_id, knowledge.side)
        self.style_engine = StyleEngine(catalog)
        self.style_id = self.style_engine.resolve(
            style_id, self.persona
        )
        self.morphology = Morphology(catalog.synthesis)
        self.memory = memory or DialogueMemory(
            catalog.state,
            run_id=knowledge.run_id,
            clock=knowledge.clock,
        )
        self.planner = AnswerPlanner(
            catalog,
            knowledge,
            self.persona,
            style_engine=self.style_engine,
            memory=self.memory,
        )
        self.planner.set_style(self._profile())
        self.state = build_state(
            catalog,
            knowledge,
            self.memory,
            morphology=self.morphology,
        )

    def ask(self, text: str) -> Answer:
        return self.respond(text).answer

    def set_style(self, style_id: Optional[str]) -> str:
        """Сменить регистровый профиль; неизвестный стиль безопасен."""

        self.style_id = self.style_engine.resolve(style_id, self.persona)
        self.planner.set_style(self._profile())
        return self.style_id

    def _profile(self):
        return self.style_engine.profile(self.style_id, self.persona)

    def respond(self, text: str) -> Turn:
        self.state.begin_turn(self.knowledge.clock)
        sem, parse, source = self._interpret(text)
        if sem is None:
            return self._clarification(text, parse, source)
        sem, unresolved = self.state.resolve_pronouns(sem)
        if unresolved:
            return self._clarification(text, parse, source, "no_referent")
        sem = self.state.apply_question_intent(sem, text)
        mentioned = self.state.observe_sem(sem)
        answer = self.planner.plan(sem, style=self._profile())
        if answer.kind == "social":
            effect = (answer.data or {}).get("effect")
            if isinstance(effect, Mapping):
                self.state.apply_effect(effect)
        self.state.push_turn(sem, answer)
        self.state.remember(sem, answer, mentioned)
        return Turn(text, parse, answer, sem, source, self.state_snapshot())

    def _meta_answer(self, kind: str, message: str, reason: str = "") -> Answer:
        """Ответить мета-репликой в выбранном регистре."""

        text = self.planner.realizer.realize_answer(
            kind,
            {"message": message, "reason": reason},
            fallback=message,
            keys=(
                "answer_%s:%s" % (kind, reason),
                "answer_" + kind,
            ),
        )
        return Answer(kind, text, reason)

    def state_snapshot(self) -> Mapping[str, Any]:
        """Краткий срез состояния для отладки и тестов."""

        return {
            "turn": self.state.turn,
            "qud": len(self.state.qud),
            "referents": sorted(self.state.referents),
            "common_ground": len(self.state.common_ground),
            "commitments": len(self.state.commitments),
            "memory_turns": self.memory.turns,
        }

    def _interpret(self, text: str):
        parse = self.parser.parse_one(text)
        if parse is not None:
            return parse.sem, parse, "parser"
        sem, fragment_id, reason = self.state.fragment(text)
        if sem is not None:
            return sem, None, "fragment:%s" % fragment_id
        return None, None, reason

    def _clarification(
        self,
        text: str,
        parse: Optional[Parse],
        source: str,
        reason: str = "",
    ) -> Turn:
        reason = reason or source or "no_match"
        if reason == "no_match":
            message = (
                self.persona.parse_unknown
                or self.persona.unknown
                or "Не понял."
            )
            answer = self._meta_answer("unknown", message, "parse")
            self.state.push_turn(None, answer)
            return Turn(
                text, parse, answer, None, source, self.state_snapshot()
            )
        policy = self.catalog.state.get("clarifications") or {}
        message = (
            self.persona.clarify.get(reason)
            or str(policy.get(reason) or "")
            or self.persona.parse_unknown
            or self.persona.unknown
            or "Не понял."
        )
        answer = self._meta_answer(
            "clarification", message, "state:%s" % reason
        )
        self.state.push_turn(None, answer)
        return Turn(text, parse, answer, None, source, self.state_snapshot())


def _select_persona(
    catalog: DialogueCatalog, persona_id: Optional[str], side: str
) -> Persona:
    personas = catalog.personas
    if persona_id and persona_id in personas:
        return personas[persona_id]
    if side in personas:
        return personas[side]
    if "default" in personas:
        return personas["default"]
    if personas:
        return personas[sorted(personas)[0]]
    return Persona(id="default")