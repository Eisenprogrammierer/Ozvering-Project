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

D5.3 подключает подсказку стиля из фактов здравого смысла:
``schema.json.style_hints`` связывает режим разговора (флирт, утешение,
ссора) со стилем ответа. Подсказка участвует в общем порядке правил
через ``hint_priority``, поэтому отношения и полномочия остаются
сильнее. Без загруженной базы фактов сессия работает как раньше.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .answers import Answer, AnswerPlanner
from .bridge import ActionBridge, ActionResult
from .fallback import FallbackEngine
from .knowledge import AgentKnowledge
from .morph import Morphology
from .model import DialogueCatalog, Parse, Persona
from .movement import MovementGuide, MoveResult
from .narrator import Narration, Narrator
from .parser import ChartParser
from .planner import GoalPlan, Intent
from .state import DialogueMemory, build_state
from .style import StyleEngine
from .timeflow import TimeGuide, TimeResult


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
        engine: Any = None,
        forms: Any = None,
        allow_improvised: bool = False,
        senses: Any = None,
        style_hints: bool = True,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.parser = ChartParser(catalog)
        self.persona = _select_persona(catalog, persona_id, knowledge.side)
        self.style_engine = StyleEngine(catalog)
        self.explicit_style_id = ""
        if style_id is not None and str(style_id) in self.style_engine.styles:
            self.explicit_style_id = str(style_id)
        if senses is None and style_hints:
            try:
                from ..commonsense import default_factbase

                senses = default_factbase()
            except Exception:
                senses = None
        self.senses = senses if style_hints else None
        self._hint_style = ""
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
        self.fallback = FallbackEngine(
            catalog, knowledge, self.state.entities, focus=self.state.focus
        )
        defaults = (catalog.movement or {}).get("defaults") or {}
        if not self.state.location:
            map_side = getattr(knowledge, "player_side", "") or knowledge.side
            self.state.location = str(
                getattr(knowledge, "player_organ_id", "")
                or defaults.get(map_side)
                or ""
            )
        self.bridge = ActionBridge(
            catalog,
            campaign=campaign,
            side=knowledge.side,
            allow_actions=allow_actions,
            social=self.planner.social_engine,
            listener=knowledge.speaker_id,
            engine=engine,
            forms=forms,
            allow_improvised=allow_improvised,
        )

    @property
    def style_id(self) -> str:
        """Текущий стиль: явный, иначе вычисленный по контексту."""

        return self.style_decision().style_id

    def style_decision(self):
        """Текущий регистр и причина выбора для интерфейса."""

        return self.style_engine.explain_for_context(
            self.explicit_style_id,
            self.persona,
            self.knowledge,
            hint_style=self._hint_style,
        )

    def style_hint(self, text: str) -> str:
        """Стиль из фактов здравого смысла, если режим распознан уверенно.

        Пустая строка означает «нет уверенной подсказки»: сессия
        остаётся на правилах ``style_context.json``.
        """

        senses = self.senses
        if senses is None or not str(text or "").strip():
            return ""
        try:
            reading = senses.classify(text)
        except Exception:
            return ""
        threshold = self.style_engine.hint_min_weight
        for mode, weight in getattr(reading, "weights", ()):
            if weight < threshold:
                continue
            style = str(senses.style_for(mode) or "")
            if style in self.style_engine.styles:
                return style
        return ""

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

        D7.1: речевое действие (``kind: social``) уходит в
        ``ActionBridge.perform_social``: гейты проверяет ``SocialEngine``,
        эффект реакции пишется в ``ConversationState``, а взаимодействие
        применяет публичный метод кампании.
        """

        parse = self.parser.parse_best(text)
        if parse is None:
            return ActionResult(
                ok=False, performed=False, reason="not_an_intent"
            )
        found = self.bridge.intent(
            parse.sem, phrase=text, action_id=action_id
        )
        if found is None:
            return ActionResult(
                ok=False, performed=False, reason="not_an_intent"
            )
        merged = {"authority": self._authority()}
        merged.update(checks or {})
        result = self.bridge.perform(
            found, checks=merged, sem=parse.sem
        )
        if result.performed:
            social = (result.result or {}).get("social")
            effect = (
                social.get("effect")
                if isinstance(social, Mapping)
                else None
            )
            if isinstance(effect, Mapping):
                self.state.apply_effect(effect)
        return result

    def travel(self, text: str) -> MoveResult:
        """Построить маршрут и переместиться, если действия разрешены.

        D7.2: расстояние, путь и «рядом/далеко» читаются из геометрии
        стороны; места и сообщения — из ``movement.json``. Меняется
        только ``ConversationState.location``, не кампания.
        """

        found = self.intent(text)
        if found is None or found.kind != "move":
            guide = MovementGuide(
                self.catalog,
                self.knowledge,
                campaign=self.bridge.campaign,
                state=self.state,
                allow_actions=self.bridge.allow_actions,
            )
            return MoveResult(
                ok=False,
                moved=False,
                reason="not_move",
                text=guide.message(
                    "not_move", "Это не команда перемещения."
                ),
            )
        guide = MovementGuide(
            self.catalog,
            self.knowledge,
            campaign=self.bridge.campaign,
            state=self.state,
            allow_actions=self.bridge.allow_actions,
        )
        return guide.move(found.target)

    def time(self, text: str) -> TimeResult:
        """Подождать или сменить темп, если действия разрешены.

        D7.3: длительности, фазы и направления темпа — данные
        ``time.json``. В read-only режиме возвращается план без
        изменения ``AutomataCampaign``.
        """

        found = self.intent(text)
        guide = TimeGuide(
            self.catalog,
            self.knowledge,
            campaign=self.bridge.campaign,
            allow_actions=self.bridge.allow_actions,
        )
        if found is None or found.kind not in ("wait", "speed"):
            return TimeResult(
                ok=False,
                performed=False,
                reason="not_time",
                text=guide.message(
                    "not_time", "Это не команда времени."
                ),
            )
        if found.kind == "speed":
            return guide.speed(found.direction)
        return guide.wait(found.target)

    def narrate(self, limit: Optional[int] = None) -> Narration:
        """Описать последние события кампании, не меняя мир.

        D7.4: источники, лимиты и шаблоны — данные ``narrator.json``.
        ``story_events`` фильтруются по видимости, работы берутся из
        ``log`` (богаче, чем ``events``), прочие ``events`` — как есть.
        """

        return Narrator(
            self.catalog, campaign=self.bridge.campaign
        ).describe(limit=limit)

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
        if not key:
            self._hint_style = ""
        self.planner.set_style(self._profile())
        return self.style_id

    def is_auto(self) -> bool:
        """Сессия в авто-режиме выбора стиля?"""

        return not self.explicit_style_id

    def _profile(self):
        return self.style_engine.profile_for_context(
            self.explicit_style_id,
            self.persona,
            self.knowledge,
            hint_style=self._hint_style,
        )

    def respond(self, text: str) -> Turn:
        self.state.begin_turn(self.knowledge.clock)
        self._hint_style = self.style_hint(text)
        sem, parse, source = self._interpret(text)
        if sem is None:
            return self._clarification(text, parse, source)
        detail = bool(isinstance(sem, Mapping) and sem.get("detail"))
        if detail:
            sem = {
                key: value
                for key, value in dict(sem).items()
                if key != "detail"
            }
        sem, unresolved = self.state.resolve_pronouns(sem)
        if unresolved:
            return self._clarification(text, parse, source, "no_referent")
        sem = self.state.apply_question_intent(sem, text)
        mentioned = self.state.observe_sem(sem)
        answer = self.planner.plan(
            sem, style=self._profile(), detail=detail
        )
        if answer.plan_id == "unmatched" and source == "parser":
            fallback_sem, fallback_id = self.fallback.interpret(text)
            if fallback_sem is not None:
                fallback_sem, unresolved = self.state.resolve_pronouns(
                    fallback_sem
                )
                if not unresolved:
                    fallback_sem = self.state.apply_question_intent(
                        fallback_sem, text
                    )
                    sem = fallback_sem
                    source = "fallback:%s" % fallback_id
                    mentioned = self.state.observe_sem(sem)
                    answer = self.planner.plan(
                        sem, style=self._profile(), detail=detail
                    )
        if answer.plan_id == "unmatched":
            hint = self._hint_answer(text)
            if hint is not None:
                answer = hint
        if answer.kind == "social":
            effect = (answer.data or {}).get("effect")
            if isinstance(effect, Mapping):
                self.state.apply_effect(effect)
        self.state.push_turn(sem, answer)
        self.state.remember(sem, answer, mentioned)
        return Turn(text, parse, answer, sem, source, self.state_snapshot())

    def _hint_answer(self, text: str) -> Optional[Answer]:
        """Подсказка вместо «не знаю» для естественного вопроса.

        Если фраза — вопрос, но разбор не дал плана, честнее предложить
        темы, о которых агент умеет говорить. Просьба без вопросительной
        формы и случайный набор слов по-прежнему получают «не понял».
        """

        if not self.fallback.is_question(text):
            return None
        message = str(self.fallback.texts.get("help") or "").strip()
        if not message:
            return None
        return self._meta_answer("hint", message, "topic")

    def _meta_answer(
        self, kind: str, message: str, reason: str = ""
    ) -> Answer:
        """Ответить мета-репликой в выбранном регистре."""

        self.planner.set_style(self._profile())
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
            "location": self.state.location,
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
        sem, rule_id = self.fallback.interpret(text)
        if sem is not None:
            return sem, None, "fallback:%s" % rule_id
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
            hint = self._hint_answer(text)
            if hint is not None:
                self.state.push_turn(None, hint)
                return Turn(
                    text, parse, hint, None, source, self.state_snapshot()
                )
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
