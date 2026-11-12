"""Сессия диалога: разбор фразы → план → ответ.

D1 не хранит состояние диалога; это read-only слой над снимком знания.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .answers import Answer, AnswerPlanner
from .knowledge import AgentKnowledge
from .model import DialogueCatalog, Parse, Persona
from .parser import ChartParser


@dataclass(frozen=True)
class Turn:
    """Один обмен: разбор, ответ и сработавший план."""

    input: str
    parse: Optional[Parse]
    answer: Answer


class DialogueSession:
    """Детерминированный ответчик для одного агента."""

    def __init__(
        self,
        catalog: DialogueCatalog,
        knowledge: AgentKnowledge,
        persona_id: Optional[str] = None,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.parser = ChartParser(catalog)
        self.persona = _select_persona(catalog, persona_id, knowledge.side)
        self.planner = AnswerPlanner(catalog, knowledge, self.persona)

    def ask(self, text: str) -> Answer:
        parse = self.parser.parse_one(text)
        if parse is None:
            message = (
                self.persona.parse_unknown
                or self.persona.unknown
                or "Не понял вопрос."
            )
            return Answer("unknown", message, "parse")
        return self.planner.plan(parse.sem)

    def respond(self, text: str) -> Turn:
        parse = self.parser.parse_one(text)
        if parse is None:
            message = (
                self.persona.parse_unknown
                or self.persona.unknown
                or "Не понял вопрос."
            )
            return Turn(text, None, Answer("unknown", message, "parse"))
        return Turn(text, parse, self.planner.plan(parse.sem))


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
