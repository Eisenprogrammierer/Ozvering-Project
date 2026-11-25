"""Схема ``UtteranceFrame`` и результаты понимания.

Кадр — типизированный, сериализуемый результат стадий 0–5. Он не
содержит действий и не ссылается на объекты мира: только id, роли,
слоты, уверенность и следы сработавших правил.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, Mapping, Tuple, Union

from .errors import FrameError

FRAME_VERSION = 1
SPEECH_ACTS = ("question", "directive", "statement", "inform")
CORE_FIELDS = (
    "intent",
    "speech_act",
    "predicate",
    "args",
    "slots",
    "referents",
)
FRAME_FIELDS = frozenset(
    (
        "version",
        "id",
        "text",
        "tokens",
        "intent",
        "speech_act",
        "predicate",
        "args",
        "slots",
        "referents",
        "confidence",
        "evidence",
        "unknowns",
    )
)


def _plain(value: Any) -> Any:
    """Привести значение к JSON-совместимому виду без потери смысла."""

    if isinstance(value, Mapping):
        return {
            str(key): _plain(item)
            for key, item in sorted(
                value.items(), key=lambda pair: str(pair[0])
            )
        }
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _text_tuple(value: Any, name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise FrameError("%s должен быть списком строк" % name)
    try:
        items = tuple(str(item) for item in value)
    except TypeError as exc:
        raise FrameError("%s должен быть списком строк" % name) from exc
    return items


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise FrameError("%s должен быть объектом" % name)
    return {str(key): item for key, item in value.items()}


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FrameError("confidence должен быть числом") from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise FrameError("confidence вне [0, 1]")
    return number


def _version(value: Any) -> int:
    if not isinstance(value, int) or value < 1:
        raise FrameError("версия кадра должна быть положительным целым")
    if value > FRAME_VERSION:
        raise FrameError(
            "версия кадра %r новее поддерживаемой %r"
            % (value, FRAME_VERSION)
        )
    return value


@dataclass(frozen=True)
class UtteranceFrame:
    """Один разобранный кадр фразы."""

    id: str
    text: str
    intent: str
    speech_act: str = "inform"
    predicate: str = ""
    args: Mapping[str, Any] = field(default_factory=dict)
    slots: Mapping[str, Any] = field(default_factory=dict)
    referents: Tuple[str, ...] = ()
    confidence: float = 0.0
    evidence: Tuple[str, ...] = ()
    unknowns: Tuple[str, ...] = ()
    tokens: Tuple[Mapping[str, Any], ...] = ()
    version: int = FRAME_VERSION

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise FrameError("id кадра обязателен")
        if not isinstance(self.text, str):
            raise FrameError("text кадра должен быть строкой")
        if not isinstance(self.intent, str) or not self.intent.strip():
            raise FrameError("intent кадра обязателен")
        if self.speech_act not in SPEECH_ACTS:
            raise FrameError("неизвестный speech_act: %r" % self.speech_act)
        if not isinstance(self.predicate, str):
            raise FrameError("predicate кадра должен быть строкой")
        if not isinstance(self.args, Mapping):
            raise FrameError("args кадра должен быть объектом")
        if not isinstance(self.slots, Mapping):
            raise FrameError("slots кадра должен быть объектом")
        for name in ("referents", "evidence", "unknowns"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, str) for item in value
            ):
                raise FrameError("%s кадра должен быть кортежем строк" % name)
        object.__setattr__(
            self, "confidence", _confidence(self.confidence)
        )
        if not isinstance(self.tokens, tuple):
            raise FrameError("tokens кадра должен быть кортежем")
        for token in self.tokens:
            if not isinstance(token, Mapping):
                raise FrameError("токен кадра должен быть объектом")
            if not str(token.get("surface") or "").strip():
                raise FrameError("у токена кадра нет surface")
        _version(self.version)

    @property
    def kind(self) -> str:
        return "frame"

    def core(self) -> Dict[str, Any]:
        """Смысловая часть кадра для сравнения и метрик."""

        return {
            "kind": "frame",
            "intent": self.intent,
            "speech_act": self.speech_act,
            "predicate": self.predicate,
            "args": _plain(self.args),
            "slots": _plain(self.slots),
            "referents": list(self.referents),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "id": self.id,
            "text": self.text,
            "tokens": _plain(self.tokens),
            "intent": self.intent,
            "speech_act": self.speech_act,
            "predicate": self.predicate,
            "args": _plain(self.args),
            "slots": _plain(self.slots),
            "referents": list(self.referents),
            "confidence": float(self.confidence),
            "evidence": list(self.evidence),
            "unknowns": list(self.unknowns),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UtteranceFrame":
        if not isinstance(data, Mapping):
            raise FrameError("кадр должен быть объектом")
        unknown = sorted(set(data) - FRAME_FIELDS)
        if unknown:
            raise FrameError(
                "неизвестные поля кадра: %s" % ", ".join(unknown)
            )
        tokens = data.get("tokens") or ()
        if not isinstance(tokens, (list, tuple)):
            raise FrameError("tokens кадра должен быть списком")
        return cls(
            id=str(data.get("id") or ""),
            text=str(data.get("text") or ""),
            intent=str(data.get("intent") or ""),
            speech_act=str(data.get("speech_act") or "inform"),
            predicate=str(data.get("predicate") or ""),
            args=_mapping(data.get("args"), "args"),
            slots=_mapping(data.get("slots"), "slots"),
            referents=_text_tuple(data.get("referents"), "referents"),
            confidence=data.get("confidence", 0.0),
            evidence=_text_tuple(data.get("evidence"), "evidence"),
            unknowns=_text_tuple(data.get("unknowns"), "unknowns"),
            tokens=tuple(_mapping(item, "token") for item in tokens),
            version=int(data.get("version", FRAME_VERSION)),
        )


@dataclass(frozen=True)
class Clarification:
    """Фаза не смогла выбрать один смысл и просит уточнение."""

    id: str
    text: str
    reason: str
    options: Tuple[str, ...] = ()
    confidence: float = 0.0
    evidence: Tuple[str, ...] = ()
    version: int = FRAME_VERSION

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise FrameError("id уточнения обязателен")
        if not isinstance(self.text, str):
            raise FrameError("text уточнения должен быть строкой")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise FrameError("reason уточнения обязателен")
        object.__setattr__(
            self, "options", _text_tuple(self.options, "options")
        )
        object.__setattr__(
            self, "evidence", _text_tuple(self.evidence, "evidence")
        )
        object.__setattr__(
            self, "confidence", _confidence(self.confidence)
        )
        _version(self.version)

    @property
    def kind(self) -> str:
        return "clarification"

    def core(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "options": list(self.options),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "reason": self.reason,
            "options": list(self.options),
            "confidence": float(self.confidence),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class Rejection:
    """Ввод вне поддерживаемого мира; действие не выполняется."""

    id: str
    text: str
    reason: str
    evidence: Tuple[str, ...] = ()
    version: int = FRAME_VERSION

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise FrameError("id отказа обязателен")
        if not isinstance(self.text, str):
            raise FrameError("text отказа должен быть строкой")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise FrameError("reason отказа обязателен")
        object.__setattr__(
            self, "evidence", _text_tuple(self.evidence, "evidence")
        )
        _version(self.version)

    @property
    def kind(self) -> str:
        return "rejection"

    def core(self) -> Dict[str, Any]:
        return {"kind": self.kind, "reason": self.reason}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }


UnderstandResult = Union[UtteranceFrame, Clarification, Rejection]


def frame_confidence(
    specificity: float,
    slot_fill: float,
    lex_coverage: float,
    unknown_penalty: float = 0.0,
) -> float:
    """Детерминированная уверенность кадра из §5.2 плана."""

    def clamp(value: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(number):
            return 0.0
        return max(0.0, min(1.0, number))

    score = (
        0.45 * clamp(specificity)
        + 0.30 * clamp(slot_fill)
        + 0.25 * clamp(lex_coverage)
        - 0.20 * clamp(unknown_penalty)
    )
    return round(max(0.0, min(1.0, score)), 6)


__all__ = [
    "CORE_FIELDS",
    "Clarification",
    "FRAME_VERSION",
    "FrameError",
    "Rejection",
    "SPEECH_ACTS",
    "UnderstandResult",
    "UtteranceFrame",
    "frame_confidence",
]
