"""Конвейер понимания фразы и фасад когнитивных бэкендов.

Phase 0: единственный доступный NLU-бэкенд — ``legacy``. Он оборачивает
существующие ``ChartParser``, эллипсис и fallback в типизированный
``UtteranceFrame``. RiveScript подключается в Phase 1 через
``register_nlu_backend``, не меняя вызовы игры.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from campaign.dialogue.morphology import tokenize

from .backends import CognitionFlags, load_flags
from .errors import BackendError, CognitionError
from .frame import (
    Clarification,
    Rejection,
    UnderstandResult,
    UtteranceFrame,
    frame_confidence,
)

NLU_FACTORIES: Dict[str, Callable[..., Any]] = {}

_ROLE_MAP = {
    "subject": "agent",
    "agent": "agent",
    "object": "patient",
    "patient": "patient",
    "instrument": "instrument",
    "value": "theme",
    "theme": "theme",
    "target": "target",
    "destination": "destination",
}
_INTENT_NAMES = {
    "why": "ask_reason",
    "what": "ask_what",
    "who": "ask_who",
    "where": "ask_where",
    "when": "ask_when",
    "how": "ask_how",
    "which": "ask_which",
    "yesno": "ask_yesno",
}
_NEGATIONS = {"не", "нет", "ни", "без"}


def register_nlu_backend(
    name: str,
    factory: Callable[..., Any],
    *,
    replace: bool = False,
) -> None:
    """Зарегистрировать фабрику NLU-бэкенда."""

    name = str(name or "").strip()
    if not name:
        raise BackendError("имя NLU-бэкенда не может быть пустым")
    if not callable(factory):
        raise BackendError("фабрика NLU-бэкенда должна быть вызываемой")
    if name in NLU_FACTORIES and not replace:
        raise BackendError("NLU-бэкенд %r уже зарегистрирован" % name)
    NLU_FACTORIES[name] = factory


def available_nlu_backends() -> Tuple[str, ...]:
    """Имена зарегистрированных NLU-бэкендов."""

    return tuple(sorted(NLU_FACTORIES))


def _entity(value: Any) -> str:
    if isinstance(value, Mapping):
        head = value.get("head")
        if isinstance(head, Mapping):
            return str(head.get("entity") or "")
        if isinstance(head, str):
            return ""
        for key in ("object", "destination", "target", "instrument"):
            found = _entity(value.get(key))
            if found:
                return found
    return ""


def _arg_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        head = value.get("head")
        if isinstance(head, str) and head:
            return head
    entity = _entity(value)
    if entity:
        return entity
    if isinstance(value, str):
        return value
    return None


def _sem_body(sem: Mapping[str, Any]) -> Mapping[str, Any]:
    body = sem.get("body")
    return body if isinstance(body, Mapping) else {}


def _collect_args(sem: Mapping[str, Any]) -> Dict[str, Any]:
    sources = (_sem_body(sem), sem)
    found: Dict[str, Any] = {}
    for source in sources:
        for role, value in source.items():
            name = _ROLE_MAP.get(str(role))
            if not name:
                continue
            resolved = _arg_value(value)
            if resolved is None:
                continue
            if name == "instrument" and "patient" not in found:
                name = "patient"
            found.setdefault(name, resolved)
    return found


def _intent_name(sem: Mapping[str, Any]) -> str:
    kind = str(sem.get("kind") or "")
    if kind == "question":
        wh = str(sem.get("wh") or "yesno")
        return _INTENT_NAMES.get(wh, "ask_%s" % wh)
    if kind == "order":
        return "act"
    if kind == "assert":
        return "inform"
    return kind or "unknown"


def _speech_act(sem: Mapping[str, Any]) -> str:
    kind = str(sem.get("kind") or "")
    if kind == "question":
        return "question"
    if kind == "order":
        return "directive"
    if kind == "assert":
        return "statement"
    return "inform"


def _predicate(sem: Mapping[str, Any]) -> str:
    body = _sem_body(sem)
    for source in (body, sem):
        value = source.get("predicate") or source.get("action")
        if value:
            return str(value)
    return ""


def _slots(sem: Mapping[str, Any], tokens: Tuple[str, ...]) -> Dict[str, Any]:
    slots: Dict[str, Any] = {}
    if sem.get("kind") == "question":
        slots["wh"] = str(sem.get("wh") or "yesno")
    for name in ("time", "modality", "aspect", "polarity"):
        value = sem.get(name)
        if value not in (None, ""):
            slots[name] = value
    if "polarity" not in slots:
        negative = any(token in _NEGATIONS for token in tokens)
        slots["polarity"] = "negative" if negative else "positive"
    return slots


def _referents(args: Mapping[str, Any]) -> Tuple[str, ...]:
    found = []
    for value in args.values():
        if isinstance(value, str) and ":" in value:
            found.append(value)
    return tuple(sorted(set(found)))


def _frame_id(text: str, topic: str) -> str:
    digest = hashlib.sha256(
        ("%s|%s" % (topic, text)).encode("utf-8")
    ).hexdigest()
    return "u-%s" % digest[:12]


class LegacyNlu:
    """Адаптер существующего разбора в ``UtteranceFrame``."""

    def __init__(self, session: Any, flags: Optional[CognitionFlags] = None):
        for name in ("parser", "state", "fallback", "catalog"):
            if not hasattr(session, name):
                raise CognitionError(
                    "legacy-сессия не содержит %r" % name
                )
        self.session = session
        self.flags = flags or load_flags()
        self._known_tokens = self._build_known_tokens(session.catalog)

    @staticmethod
    def _build_known_tokens(catalog: Any) -> frozenset:
        tokens = set()
        for entry in getattr(catalog, "lexicon", ()) or ():
            for form in entry.all_forms():
                tokens.update(tokenize(form.text))
        return frozenset(tokens)

    def _lex_coverage(self, tokens: Tuple[str, ...]) -> float:
        if not tokens:
            return 0.0
        known = sum(1 for token in tokens if token in self._known_tokens)
        return known / float(len(tokens))

    def _specificity(self, source: str) -> float:
        return {"parser": 1.0, "fragment": 0.55, "fallback": 0.70}.get(
            source, 0.40
        )

    def _slot_fill(self, args: Mapping[str, Any], sem: Mapping[str, Any]):
        if args:
            return 1.0
        if sem.get("kind") == "question" and sem.get("wh") == "yesno":
            return 0.8
        return 0.5

    def _evidence(
        self,
        source: str,
        rule: str,
        args: Mapping[str, Any],
    ) -> Tuple[str, ...]:
        evidence = ["%s:%s" % (source, rule)] if rule else [source]
        evidence.extend("entity:%s" % item for item in _referents(args))
        return tuple(evidence)

    def understand(
        self,
        text: str,
        *,
        topic: str = "default",
    ) -> UnderstandResult:
        raw = str(text or "")
        tokens = tuple(tokenize(raw))
        if not tokens:
            return Rejection(
                id=_frame_id(raw, topic),
                text=raw,
                reason="empty",
            )
        parse = self.session.parser.parse_best(raw)
        sem: Optional[Mapping[str, Any]] = None
        source = ""
        rule = ""
        reason = ""
        if parse is not None:
            sem = parse.sem if isinstance(parse.sem, Mapping) else None
            source = "parser"
            rule = str(parse.rule or "")
        if sem is None:
            sem, fragment_id, reason = self.session.state.fragment(raw)
            if sem is not None:
                source = "fragment"
                rule = str(fragment_id or "")
        if sem is None:
            sem, fallback_id = self.session.fallback.interpret(raw)
            if sem is not None:
                source = "fallback"
                rule = str(fallback_id or "")
        if sem is None or not isinstance(sem, Mapping):
            return Clarification(
                id=_frame_id(raw, topic),
                text=raw,
                reason=reason or "no_match",
                options=(),
                confidence=0.0,
            )
        resolved, unresolved = self.session.state.resolve_pronouns(sem)
        if isinstance(resolved, Mapping):
            sem = resolved
        args = _collect_args(sem)
        confidence = frame_confidence(
            self._specificity(source),
            self._slot_fill(args, sem),
            self._lex_coverage(tokens),
            len(unresolved) / float(len(tokens)),
        )
        evidence = self._evidence(source, rule, args)
        if confidence < self.flags.clarify_threshold:
            return Clarification(
                id=_frame_id(raw, topic),
                text=raw,
                reason="low_confidence",
                options=(_intent_name(sem),),
                confidence=confidence,
                evidence=evidence,
            )
        return UtteranceFrame(
            id=_frame_id(raw, topic),
            text=raw,
            intent=_intent_name(sem),
            speech_act=_speech_act(sem),
            predicate=_predicate(sem),
            args=args,
            slots=_slots(sem, tokens),
            referents=_referents(args),
            confidence=confidence,
            evidence=evidence,
            unknowns=tuple(unresolved),
            tokens=tuple({"surface": token} for token in tokens),
        )


def _run_backend(
    backend: str,
    session: Any,
    flags: CognitionFlags,
    text: str,
    topic: str,
) -> Any:
    factory = NLU_FACTORIES.get(backend)
    if factory is None:
        raise BackendError(
            "NLU-бэкенд %r не зарегистрирован; доступно: %s"
            % (backend, ", ".join(available_nlu_backends()) or "нет")
        )
    return factory(session, flags).understand(text, topic=topic)


def understand(
    text: str,
    *,
    session: Any,
    topic: str = "default",
    flags: Optional[CognitionFlags] = None,
    nlu_backend: Optional[str] = None,
    shadow_sink: Optional[Callable[[str, Any], None]] = None,
) -> UnderstandResult:
    """Понять фразу, не выполняя действий и не меняя мир."""

    resolved = flags or load_flags()
    backend = nlu_backend or resolved.nlu_backend
    if backend == "legacy":
        return _run_backend("legacy", session, resolved, text, topic)
    if backend == "shadow":
        primary = _run_backend("legacy", session, resolved, text, topic)
        shadow = _run_backend("rive", session, resolved, text, topic)
        if shadow_sink is not None:
            shadow_sink(text, shadow)
        return primary
    if backend == "rive":
        return _run_backend("rive", session, resolved, text, topic)
    raise BackendError("неизвестный nlu_backend: %r" % backend)


def decide(
    *,
    policy: Any,
    candidates: Any,
    needs: Any,
    explore: Optional[bool] = None,
    flags: Optional[CognitionFlags] = None,
    ai_backend: Optional[str] = None,
) -> Any:
    """Выбрать действие; Phase 0 делегирует ``NeedPolicy.choose``."""

    resolved = flags or load_flags()
    backend = ai_backend or resolved.ai_backend
    if backend == "legacy":
        if policy is None or not hasattr(policy, "choose"):
            raise BackendError(
                "legacy-решение требует политику с методом choose()"
            )
        return policy.choose(candidates, needs, explore=explore)
    if backend == "shadow":
        raise BackendError(
            "ai_backend=shadow появится в Phase 2 вместе с Soar-агентом"
        )
    if backend == "soar":
        raise BackendError(
            "ai_backend=soar не подключён: Soar-мост появится в Phase 2"
        )
    raise BackendError("неизвестный ai_backend: %r" % backend)


if "legacy" not in NLU_FACTORIES:
    register_nlu_backend("legacy", LegacyNlu)


__all__ = [
    "LegacyNlu",
    "NLU_FACTORIES",
    "available_nlu_backends",
    "decide",
    "register_nlu_backend",
    "understand",
]
