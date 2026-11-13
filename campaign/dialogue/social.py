"""Детерминированный выбор реакции на речевое действие.

Акты, реакции и эффекты — данные (``social.json``). Условия реакций — те
же ``AtomSpec``, что в правилах вывода, и доказываются тем же
``InferenceEngine``. Модуль не меняет кампанию и BDI: решение только
читает снимок знания и возвращает типизированный эффект, который сессия
записывает в ``ConversationState``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .inference import InferenceEngine, Solution
from .knowledge import AgentKnowledge
from .model import (
    AtomSpec,
    DialogueCatalog,
    ReactionSpec,
    SocialActSpec,
)


@dataclass(frozen=True)
class SocialDecision:
    """Решение по речевому действию: реакция, эффект и трасса.

    ``effect`` — типизированный словарь (``type`` плюс поля). Сессия
    применяет его к ``ConversationState``; сам движок состояние не
    меняет. ``trace`` объясняет, какие условия проверялись и что
    сработало: это часть белого ящика.
    """

    act_id: str
    reaction_id: str
    effect: Mapping[str, Any] = field(default_factory=dict)
    construction: str = ""
    bindings: Mapping[str, str] = field(default_factory=dict)
    trace: Tuple[Mapping[str, Any], ...] = ()
    reason: str = ""


def _resolve(template: Any, bindings: Mapping[str, str]) -> Any:
    """Подставить ``$переменные`` в скаляр, список или объект."""

    if isinstance(template, str):
        text = template
        if text.startswith("$") and text[1:] in bindings:
            return bindings[text[1:]]
        for name, value in bindings.items():
            text = text.replace("$" + name, str(value))
        return text
    if isinstance(template, Mapping):
        return {
            str(key): _resolve(value, bindings)
            for key, value in template.items()
        }
    if isinstance(template, (list, tuple)):
        return [_resolve(item, bindings) for item in template]
    return template


def _bind_atom(
    atom: AtomSpec, bindings: Mapping[str, str]
) -> Tuple[str, ...]:
    args: List[str] = []
    for arg in atom.args:
        value = str(arg)
        if value.startswith("$"):
            name = value[1:]
            value = str(bindings.get(name, ""))
        args.append(value)
    return tuple(args)


def _matches(pattern: Any, value: Any) -> bool:
    """Сопоставить шаблон акта с логической формой без привязки переменных.

    Достаточно проверить ключи и скалярные значения: ``$переменные`` в
    шаблоне акта означают «любое значение» и не участвуют в связывании.
    """

    if isinstance(pattern, Mapping):
        if not isinstance(value, Mapping):
            return False
        for key, item in pattern.items():
            if key not in value:
                return False
            if not _matches(item, value[key]):
                return False
        return True
    if isinstance(pattern, list):
        if not isinstance(value, list) or len(pattern) != len(value):
            return False
        return all(
            _matches(item, actual)
            for item, actual in zip(pattern, value)
        )
    if isinstance(pattern, str) and pattern.startswith("$"):
        return True
    return pattern == value


class SocialEngine:
    """Выбирает реакцию на речевое действие по данным и знанию агента."""

    def __init__(
        self,
        catalog: DialogueCatalog,
        knowledge: AgentKnowledge,
        engine: InferenceEngine,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.engine = engine
        self.social = catalog.social

    def act_for(self, sem: Any) -> Optional[SocialActSpec]:
        """Найти акт по логической форме; порядок — как в JSON."""

        for act in self.social.acts.values():
            if _matches(act.match, sem):
                return act
        return None

    def decide(
        self, sem: Any, bindings: Optional[Mapping[str, str]] = None
    ) -> Optional[SocialDecision]:
        """Выбрать реакцию и вернуть эффект с трассой.

        Порядок детерминирован:

        1. акт находится по ``match``;
        2. ``taboo`` выносит решение сразу (``evade``);
        3. ``validity`` проверяется по порядку; провал → ``reject``;
        4. реакции проверяются по приоритету; первая сработавшая
           становится решением;
        5. иначе — реакция ``clarify`` как fallback.
        """

        act = self.act_for(sem)
        if act is None:
            return None
        bound = dict(bindings or {})
        bound.setdefault("speaker", self.knowledge.player_id or "$player")
        bound.setdefault("listener", self.knowledge.speaker_id)
        trace: List[Mapping[str, Any]] = [
            {
                "kind": "act",
                "act": act.id,
                "register": "",
                "bindings": dict(bound),
            }
        ]

        taboo_hit = self._taboo_hit(act, sem, bound)
        if taboo_hit:
            trace.append(
                {"kind": "taboo", "topic": taboo_hit}
            )
            return self._reaction(
                act, "evade", bound, trace, reason="taboo:%s" % taboo_hit
            )

        invalid = self._validity_failure(act, bound, trace)
        if invalid:
            trace.append(
                {"kind": "invalid", "reason": invalid}
            )
            return self._reaction(
                act, "reject", bound, trace, reason=invalid
            )

        for reaction_id in act.reactions:
            if reaction_id == "clarify":
                continue
            reaction = self.social.reaction(reaction_id)
            if reaction is None:
                continue
            if self._conditions_hold(reaction, bound, trace):
                return self._reaction(
                    act, reaction_id, bound, trace
                )
        return self._reaction(
            act, "clarify", bound, trace, reason="no_reaction"
        )

    # --- проверки ----------------------------------------------------

    def _taboo_hit(
        self, act: SocialActSpec, sem: Any, bindings: Mapping[str, str]
    ) -> str:
        if not act.taboo:
            return ""
        subject = str(
            bindings.get("object")
            or bindings.get("topic")
            or ""
        )
        for name in act.taboo:
            if str(name) == subject:
                return str(name)
        return ""

    def _validity_failure(
        self,
        act: SocialActSpec,
        bindings: Mapping[str, str],
        trace: List[Mapping[str, Any]],
    ) -> str:
        for atom in act.validity:
            args = _bind_atom(atom, bindings)
            solutions = self.engine.prove(atom.rel, args)
            found = len(solutions) > 0
            trace.append(
                {
                    "kind": "validity",
                    "relation": atom.rel,
                    "args": args,
                    "found": found,
                }
            )
            if not found:
                return atom.rel
        return ""

    def _conditions_hold(
        self,
        reaction: ReactionSpec,
        bindings: Mapping[str, str],
        trace: List[Mapping[str, Any]],
    ) -> bool:
        if not reaction.conditions:
            trace.append(
                {"kind": "reaction", "reaction": reaction.id}
            )
            return True
        for atom in reaction.conditions:
            args = _bind_atom(atom, bindings)
            solutions = self.engine.prove(atom.rel, args)
            found = len(solutions) > 0
            trace.append(
                {
                    "kind": "condition",
                    "reaction": reaction.id,
                    "relation": atom.rel,
                    "args": args,
                    "found": found,
                }
            )
            if not found:
                return False
        trace.append(
            {"kind": "reaction", "reaction": reaction.id}
        )
        return True

    # --- сборка решения ----------------------------------------------

    def _reaction(
        self,
        act: SocialActSpec,
        reaction_id: str,
        bindings: Mapping[str, str],
        trace: List[Mapping[str, Any]],
        reason: str = "",
    ) -> SocialDecision:
        reaction = self.social.reaction(reaction_id)
        if reaction is None:
            reaction = self.social.reaction("clarify")
        if reaction is None:
            return SocialDecision(
                act_id=act.id,
                reaction_id="",
                trace=tuple(trace),
                reason="missing_reaction",
            )
        effect = _resolve(reaction.effect, bindings)
        return SocialDecision(
            act_id=act.id,
            reaction_id=reaction.id,
            effect=effect,
            construction=reaction.construction,
            bindings=dict(bindings),
            trace=tuple(trace),
            reason=reason,
        )


def social_bindings(
    sem: Any, knowledge: AgentKnowledge
) -> Dict[str, str]:
    """Связать ``$speaker``/``$listener``/``$object`` из формы и знания.

    Логическая форма социального акта строится парсером и содержит
    ``speaker`` и ``object`` как строки или ``$переменные``. Слушатель
    известен из знания: это сам агент. Игрок — говорящий, если парсер
    не назвал другого.
    """

    bindings: Dict[str, str] = {
        "speaker": knowledge.player_id or "player",
        "listener": knowledge.speaker_id,
    }
    if not isinstance(sem, Mapping):
        return bindings
    body = sem.get("body") if isinstance(sem.get("body"), Mapping) else sem
    for key in ("speaker", "subject", "object", "verb", "consequence"):
        value = body.get(key)
        if isinstance(value, Mapping):
            head = value.get("object") or value.get("head") or {}
            entity = head.get("entity") if isinstance(head, Mapping) else ""
            if entity:
                bindings[key] = str(entity)
        elif isinstance(value, str) and value:
            bindings[key] = value
    return bindings