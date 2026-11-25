"""Протокол ``soar_bridge.v1``.

Мост не зависит от способа запуска Soar: SML, subprocess или Tcl.
Python отдаёт снимок и получает только команды; Soar не пишет в
состояние игры. Валидация здесь — единственная точка допуска команд.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, Mapping, Tuple

from .errors import BridgeError

BRIDGE_VERSION = "soar_bridge.v1"
COMMAND_KINDS = (
    "say",
    "act",
    "clarify",
    "remember",
    "order",
    "move",
    "wait",
)
REQUEST_FIELDS = frozenset(
    ("version", "agent_id", "tick", "snapshot_version", "input")
)
RESPONSE_FIELDS = frozenset(("version", "commands", "trace", "timing_ms"))


def _mapping(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BridgeError("%s должен быть объектом" % name)
    return {str(key): item for key, item in value.items()}


def _text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise BridgeError("%s обязателен" % name)
    return text


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise BridgeError("%s должен быть целым" % name) from exc
    if number < minimum:
        raise BridgeError("%s должен быть >= %d" % (name, minimum))
    return number


def _number(value: Any, name: str, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BridgeError("%s должен быть числом" % name) from exc
    if not math.isfinite(number) or number < minimum:
        raise BridgeError("%s должен быть >= %s" % (name, minimum))
    return number


def validate_command(command: Any, index: int = 0) -> Dict[str, Any]:
    """Проверить одну команду Soar и вернуть нормализованный словарь."""

    data = _mapping(command, "commands[%d]" % index)
    kind = str(data.get("kind") or "")
    if kind not in COMMAND_KINDS:
        raise BridgeError(
            "commands[%d].kind=%r не поддерживается; допустимо: %s"
            % (index, kind, ", ".join(COMMAND_KINDS))
        )
    identifier = _text(data.get("id"), "commands[%d].id" % index)
    origin = _text(data.get("origin"), "commands[%d].origin" % index)
    result = dict(data)
    result["kind"] = kind
    result["id"] = identifier
    result["origin"] = origin
    if kind == "say":
        _text(data.get("act"), "commands[%d].act" % index)
        if "content" in data:
            _mapping(data.get("content"), "commands[%d].content" % index)
    elif kind == "act":
        _text(data.get("action_id"), "commands[%d].action_id" % index)
        if "target" in data and not isinstance(data.get("target"), str):
            raise BridgeError(
                "commands[%d].target должен быть строкой" % index
            )
    elif kind == "clarify":
        options = data.get("options")
        content = data.get("content")
        if options is None and content is None:
            raise BridgeError(
                "commands[%d].clarify требует options или content" % index
            )
        if content is not None:
            _mapping(content, "commands[%d].content" % index)
        if options is not None:
            if not isinstance(options, (list, tuple)) or not options:
                raise BridgeError(
                    "commands[%d].options должен быть непустым списком"
                    % index
                )
    elif kind == "remember":
        _text(data.get("key"), "commands[%d].key" % index)
        if "value" not in data:
            raise BridgeError(
                "commands[%d].remember требует value" % index
            )
    elif kind == "order":
        if not (data.get("action_id") or data.get("order_id")):
            raise BridgeError(
                "commands[%d].order требует action_id или order_id"
                % index
            )
        for key in ("action_id", "order_id"):
            if key in data:
                _text(data.get(key), "commands[%d].%s" % (index, key))
    elif kind == "move":
        _text(data.get("target"), "commands[%d].target" % index)
    elif kind == "wait":
        if "ticks" in data:
            _integer(data.get("ticks"), "commands[%d].ticks" % index, 0)
    return result


@dataclass(frozen=True)
class BridgeRequest:
    """Снимок для Soar-агента."""

    agent_id: str
    tick: int
    snapshot_version: int
    input: Mapping[str, Any] = field(default_factory=dict)
    version: str = BRIDGE_VERSION

    def __post_init__(self):
        if self.version != BRIDGE_VERSION:
            raise BridgeError(
                "версия моста %r не поддерживается" % (self.version,)
            )
        if not str(self.agent_id or "").strip():
            raise BridgeError("agent_id обязателен")
        object.__setattr__(
            self, "tick", _integer(self.tick, "tick", 0)
        )
        object.__setattr__(
            self,
            "snapshot_version",
            _integer(self.snapshot_version, "snapshot_version", 0),
        )
        if not isinstance(self.input, Mapping):
            raise BridgeError("input должен быть объектом")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "agent_id": self.agent_id,
            "tick": int(self.tick),
            "snapshot_version": int(self.snapshot_version),
            "input": dict(self.input),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BridgeRequest":
        if not isinstance(data, Mapping):
            raise BridgeError("запрос моста должен быть объектом")
        unknown = sorted(set(data) - REQUEST_FIELDS)
        if unknown:
            raise BridgeError(
                "неизвестные поля запроса: %s" % ", ".join(unknown)
            )
        return cls(
            agent_id=str(data.get("agent_id") or ""),
            tick=_integer(data.get("tick", 0), "tick"),
            snapshot_version=_integer(
                data.get("snapshot_version", 0), "snapshot_version"
            ),
            input=_mapping(data.get("input") or {}, "input"),
            version=str(data.get("version") or BRIDGE_VERSION),
        )


@dataclass(frozen=True)
class BridgeResponse:
    """Команды и трассировка от Soar-агента."""

    commands: Tuple[Mapping[str, Any], ...] = ()
    trace: Mapping[str, Any] = field(default_factory=dict)
    timing_ms: float = 0.0
    version: str = BRIDGE_VERSION

    def __post_init__(self):
        if self.version != BRIDGE_VERSION:
            raise BridgeError(
                "версия моста %r не поддерживается" % (self.version,)
            )
        if not isinstance(self.commands, tuple):
            raise BridgeError("commands должен быть кортежем")
        for index, command in enumerate(self.commands):
            validate_command(command, index)
        if not isinstance(self.trace, Mapping):
            raise BridgeError("trace должен быть объектом")
        _number(self.timing_ms, "timing_ms")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "commands": [dict(item) for item in self.commands],
            "trace": dict(self.trace),
            "timing_ms": float(self.timing_ms),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BridgeResponse":
        if not isinstance(data, Mapping):
            raise BridgeError("ответ моста должен быть объектом")
        unknown = sorted(set(data) - RESPONSE_FIELDS)
        if unknown:
            raise BridgeError(
                "неизвестные поля ответа: %s" % ", ".join(unknown)
            )
        commands = data.get("commands") or ()
        if not isinstance(commands, (list, tuple)):
            raise BridgeError("commands должен быть списком")
        return cls(
            commands=tuple(
                validate_command(item, index)
                for index, item in enumerate(commands)
            ),
            trace=_mapping(data.get("trace") or {}, "trace"),
            timing_ms=_number(data.get("timing_ms", 0.0), "timing_ms"),
            version=str(data.get("version") or BRIDGE_VERSION),
        )


def validate_request(data: Any) -> BridgeRequest:
    """Принять словарь или готовый запрос."""

    if isinstance(data, BridgeRequest):
        return data
    return BridgeRequest.from_dict(data)


def validate_response(data: Any) -> BridgeResponse:
    """Принять словарь или готовый ответ."""

    if isinstance(data, BridgeResponse):
        return data
    return BridgeResponse.from_dict(data)


def request_digest(request: BridgeRequest) -> str:
    """Детерминированный хеш запроса для parity-тестов."""

    from .serialization import canonical_digest

    return canonical_digest(request.to_dict())


def command_digest(response: BridgeResponse) -> str:
    """Детерминированный хеш команд ответа."""

    from .serialization import canonical_digest

    return canonical_digest(
        [dict(item) for item in response.commands]
    )


__all__ = [
    "BRIDGE_VERSION",
    "BridgeRequest",
    "BridgeResponse",
    "COMMAND_KINDS",
    "command_digest",
    "request_digest",
    "validate_command",
    "validate_request",
    "validate_response",
]
