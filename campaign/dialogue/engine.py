"""Сессия диалога: разбор фразы → состояние → план → ответ.

D2 добавляет к read-only слою QUD, активные референты, разрешение
местоимений, декларативный эллипсис и память партии. D4 добавляет
речевые действия: эффект реакции из ``social.json`` записывается в
``ConversationState.commitments``. Состояние разговора не меняет
кампанию и BDI: оно лишь читает снимок знания и хранит следы беседы
для связности.

D5.2 добавляет авто-режим выбора регистра: если игрок не выбрал стиль
явно, регистр определяется правилами из ``style_context.json`` по
данным ``AgentKnowledge``. Явный выбор побеждает любые правила.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .answers import Answer, AnswerPlanner
from .bridge import ActionBridge, ActionResult
from .knowledge import AgentKnowledge
from .morph import Morphology
from .model import DialogueCatalog, Parse, Persona
from .parser import ChartParser
from .planner import GoalPlan, Intent
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
        allow_actions: bool = False,
        campaign: Any = None,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.parser = ChartParser(catalog)
        self.persona = _select_persona(catalog, persona_id, knowledge.side)
        self.style_engine = StyleEngine(catalog)
        self.explicit_style_id = ""
        if style_id is not None and str(style_id) in self.style_engine.styles:
            self.explicit_style_id = str(style_id)
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
        self.bridge = ActionBridge(
            catalog,
            campaign=campaign,
            side=knowledge.side,
            allow_actions=allow_actions,
        )

    @property
    def style_id(self) -> str:
        """Текущий стиль: явный, иначе вычисленный по контексту."""

        return self.style_engine.resolve_for_context(
            self.explicit_style_id, self.persona, self.knowledge
        )

    def ask(self, text: str) -> Answer:
        return self.respond(text).answer

    def _authority(self) -> bool:
        """Есть ли у игрока полномочия по фактам знания."""

        for fact in self.knowledge.facts_for("has_authority"):
            if fact.args and fact.args[0] and fact.args[1]:
                return True
        return False

    def intent(self, text: str, action_id: str = "") -> Optional[Intent]:
        """Разобрать фразу в намерение, не трогая мир."""

        parse = self.parser.parse_best(text)
        if parse is None:
            return None
        return self.bridge.intent(
            parse.sem, phrase=text, action_id=action_id
        )

    def plan_goal(
        self,
        text: str,
        action_id: str = "",
        checks: Optional[Mapping[str, Any]] = None,
    ) -> Optional[GoalPlan]:
        """Построить план цели с проверками, не выполняя действие."""

        found = self.intent(text, action_id=action_id)
        if found is None:
            return None
        merged = {"authority": self._authority()}
        merged.update(checks or {})
        return self.bridge.plan(
            found, checks=self.bridge.checks(found, merged)
        )

    def act(
        self,
        text: str,
        action_id: str = "",
        checks: Optional[Mapping[str, Any]] = None,
    ) -> ActionResult:
        """Выполнить действие из фразы, если мост включён.

        ``allow_actions=False`` (по умолчанию) всегда возвращает
        ``actions_disabled`` и не меняет кампанию. ``ask``/``respond``
        остаются read-only независимо от флага.
        """

        found = self.intent(text, action_id=action_id)
        if found is None:
            return ActionResult(
                ok=False, performed=False, reason="not_an_intent"
            )
        merged = {"authority": self._authority()}
        merged.update(checks or {})
        return self.bridge.perform(found, checks=merged)

    def set_style(self, style_id: Optional[str]) -> str:
        """Сменить регистровый профиль.

        ``None`` переключает в авто-режим: стиль выбирается правилами
        ``style_context.json`` по ``AgentKnowledge``. Явный идентификатор
        побеждает любые правила, но только если он существует.
        """

        key = "" if style_id is None else str(style_id)
        if key and key not in self.style_engine.styles:
            key = ""
        self.explicit_style_id = key
        self.planner.set_style(self._profile())
        return self.style_id

    def is_auto(self) -> bool:
        """Сессия в авто-режиме выбора стиля?"""

        return not self.explicit_style_id

    def _profile(self):
        return self.style_engine.profile_for_context(
            self.explicit_style_id, self.persona, self.knowledge
        )

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
            "style_id": self.style_id,
            "style_auto": self.is_auto(),
        }

    def _interpret(self, text: str):
        parse = self.parser.parse_best(text)
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