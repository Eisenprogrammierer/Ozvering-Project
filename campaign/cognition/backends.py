"""Флаги когнитивных бэкендов.

Значения по умолчанию и пороги живут в ``configs/cognition/backends.json``.
Переменные окружения ``OZVERIN_AI_BACKEND`` и ``OZVERIN_NLU_BACKEND``
переопределяют выбранный бэкенд, но не пороги: пороги — данные, а не
настройка окружения.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .errors import BackendError

AI_BACKENDS = ("legacy", "shadow", "soar")
NLU_BACKENDS = ("legacy", "shadow", "rive")
DIALOGUE_BACKENDS = ("legacy", "shadow", "soar")
CONFIG_VERSION = 1
ENV_CONFIG = "OZVERIN_COGNITION_CONFIG"
ENV_AI = "OZVERIN_AI_BACKEND"
ENV_NLU = "OZVERIN_NLU_BACKEND"
ENV_DIALOGUE = "OZVERIN_DIALOGUE_BACKEND"


def default_config_path() -> Path:
    """Путь к JSON-конфигу флагов в рабочем дереве."""

    return (
        Path(__file__).resolve().parents[2]
        / "configs"
        / "cognition"
        / "backends.json"
    )


def _number(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BackendError("%s должен быть числом" % name) from exc


def _backend(value: Any, allowed, name: str) -> str:
    text = str(value or "").strip()
    if text not in allowed:
        raise BackendError(
            "%s=%r не поддерживается; допустимо: %s"
            % (name, text, ", ".join(allowed))
        )
    return text


@dataclass(frozen=True)
class CognitionFlags:
    """Проверенный набор флагов и порогов."""

    ai_backend: str = "soar"
    nlu_backend: str = "legacy"
    dialogue_backend: str = "legacy"
    record_shadow: bool = False
    compare_shadow: bool = False
    accept_threshold: float = 0.75
    clarify_threshold: float = 0.45
    nlu_fallback_max: float = 0.05
    decision_timeout_ms: int = 200
    tick_timeout_ms: int = 250
    source: str = "builtin"

    def __post_init__(self):
        _backend(self.ai_backend, AI_BACKENDS, "ai_backend")
        _backend(self.nlu_backend, NLU_BACKENDS, "nlu_backend")
        _backend(
            self.dialogue_backend,
            DIALOGUE_BACKENDS,
            "dialogue_backend",
        )
        if not 0.0 <= self.clarify_threshold <= 1.0:
            raise BackendError("clarify_threshold вне [0, 1]")
        if not 0.0 <= self.accept_threshold <= 1.0:
            raise BackendError("accept_threshold вне [0, 1]")
        if not 0.0 <= self.nlu_fallback_max <= 1.0:
            raise BackendError("nlu_fallback_max вне [0, 1]")
        if self.clarify_threshold > self.accept_threshold:
            raise BackendError(
                "clarify_threshold не может быть больше accept_threshold"
            )
        if self.decision_timeout_ms <= 0 or self.tick_timeout_ms <= 0:
            raise BackendError("таймауты должны быть положительными")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ai_backend": self.ai_backend,
            "nlu_backend": self.nlu_backend,
            "dialogue_backend": self.dialogue_backend,
            "shadow": {
                "record": self.record_shadow,
                "compare": self.compare_shadow,
            },
            "thresholds": {
                "accept": self.accept_threshold,
                "clarify": self.clarify_threshold,
                "fallback_rate_max": self.nlu_fallback_max,
            },
            "timeouts": {
                "decision_ms": self.decision_timeout_ms,
                "tick_ms": self.tick_timeout_ms,
            },
            "source": self.source,
        }


def _read_config(path: Path) -> Mapping[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BackendError(
            "не удалось прочитать конфиг когниции: %s" % path
        ) from exc
    except ValueError as exc:
        raise BackendError(
            "конфиг когниции не является JSON: %s" % path
        ) from exc
    if not isinstance(raw, Mapping):
        raise BackendError("конфиг когниции должен быть объектом")
    version = raw.get("version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        raise BackendError(
            "версия конфига когниции %r не поддерживается" % (version,)
        )
    return raw


def load_flags(
    path: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> CognitionFlags:
    """Прочитать конфиг и наложить переменные окружения."""

    env = dict(os.environ if environ is None else environ)
    explicit = path is not None or bool(env.get(ENV_CONFIG))
    config_path = Path(path) if path is not None else Path(
        env.get(ENV_CONFIG) or default_config_path()
    )
    if not config_path.is_file():
        if explicit:
            raise BackendError(
                "конфиг когниции не найден: %s" % config_path
            )
        raw: Mapping[str, Any] = {}
    else:
        raw = _read_config(config_path)
    shadow = raw.get("shadow") or {}
    thresholds = raw.get("thresholds") or {}
    timeouts = raw.get("timeouts") or {}
    if not isinstance(shadow, Mapping):
        raise BackendError("shadow должен быть объектом")
    if not isinstance(thresholds, Mapping):
        raise BackendError("thresholds должен быть объектом")
    if not isinstance(timeouts, Mapping):
        raise BackendError("timeouts должен быть объектом")
    ai_backend = _backend(
        env.get(ENV_AI, raw.get("ai_backend", "soar")),
        AI_BACKENDS,
        "ai_backend",
    )
    nlu_backend = _backend(
        env.get(ENV_NLU, raw.get("nlu_backend", "legacy")),
        NLU_BACKENDS,
        "nlu_backend",
    )
    dialogue_backend = _backend(
        env.get(
            ENV_DIALOGUE,
            raw.get("dialogue_backend", "legacy"),
        ),
        DIALOGUE_BACKENDS,
        "dialogue_backend",
    )
    return CognitionFlags(
        ai_backend=ai_backend,
        nlu_backend=nlu_backend,
        dialogue_backend=dialogue_backend,
        record_shadow=bool(shadow.get("record", False)),
        compare_shadow=bool(shadow.get("compare", False)),
        accept_threshold=_number(
            thresholds.get("accept", 0.75), "thresholds.accept"
        ),
        clarify_threshold=_number(
            thresholds.get("clarify", 0.45), "thresholds.clarify"
        ),
        nlu_fallback_max=_number(
            thresholds.get("fallback_rate_max", 0.05),
            "thresholds.fallback_rate_max",
        ),
        decision_timeout_ms=int(
            _number(
                timeouts.get("decision_ms", 200),
                "timeouts.decision_ms",
            )
        ),
        tick_timeout_ms=int(
            _number(timeouts.get("tick_ms", 250), "timeouts.tick_ms")
        ),
        source=str(config_path),
    )


__all__ = [
    "AI_BACKENDS",
    "CONFIG_VERSION",
    "CognitionFlags",
    "DIALOGUE_BACKENDS",
    "ENV_AI",
    "ENV_CONFIG",
    "ENV_DIALOGUE",
    "ENV_NLU",
    "NLU_BACKENDS",
    "default_config_path",
    "load_flags",
]
