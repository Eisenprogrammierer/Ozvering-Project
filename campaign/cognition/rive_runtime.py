"""Исполнение сгенерированного RiveScript в теневом NLU.

Движок отвечает только за выбор точного триггера. Кадр, слоты и
уверенность пока строит legacy-адаптер; Phase 1 доказывает, что
RiveScript выбирает тот же смысл, не меняя ядро кадра. Phase 4 заменит
эту часть собственными слотами и прагматикой.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .backends import CognitionFlags, load_flags
from .errors import BackendError, RiveError
from .frame import UtteranceFrame
from .nlu import LegacyNlu
from .rive_compiler import (
    DEFAULT_RIVE_DIR,
    MANIFEST_NAME,
    RIVE_NAME,
    RiveManifest,
)

FALLBACK_ID = "__fallback__"
_ENGINE_CACHE: Dict[Tuple[str, int], Any] = {}
_MANIFEST_CACHE: Dict[Tuple[str, int], RiveManifest] = {}


def default_manifest_path() -> Path:
    return DEFAULT_RIVE_DIR / MANIFEST_NAME


def default_rive_path() -> Path:
    return DEFAULT_RIVE_DIR / RIVE_NAME


def _nlu_subroutine(rs: Any, args: Tuple[str, ...]) -> str:
    return str(args[0]) if args else FALLBACK_ID


def _load_manifest(path: Path) -> RiveManifest:
    source = Path(path)
    try:
        stamp = source.stat().st_mtime_ns
    except OSError as exc:
        raise BackendError(
            "нет манифеста RiveScript: %s. "
            "Запустите python -m campaign.cognition.rive_compiler --write"
            % source
        ) from exc
    key = (str(source), stamp)
    cached = _MANIFEST_CACHE.get(key)
    if cached is not None:
        return cached
    manifest = RiveManifest.load(source)
    _MANIFEST_CACHE[key] = manifest
    return manifest


def _load_engine(path: Path) -> Any:
    source = Path(path)
    try:
        stamp = source.stat().st_mtime_ns
    except OSError as exc:
        raise BackendError(
            "нет сгенерированного RiveScript: %s. "
            "Запустите python -m campaign.cognition.rive_compiler --write"
            % source
        ) from exc
    key = (str(source), stamp)
    cached = _ENGINE_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from rivescript import RiveScript
    except ImportError as exc:
        raise BackendError(
            "nlu_backend=rive требует пакет rivescript "
            "(pip install 'rivescript>=1.15,<2')"
        ) from exc
    engine = RiveScript(utf8=True)
    try:
        engine.load_file(str(source))
        engine.sort_replies()
    except Exception as exc:
        raise RiveError("не удалось загрузить %s" % source) from exc
    engine.set_subroutine("nlu", _nlu_subroutine)
    _ENGINE_CACHE[key] = engine
    return engine


class RiveNlu:
    """NLU-бэкенд: RiveScript выбирает триггер, legacy строит кадр."""

    def __init__(
        self,
        session: Any,
        flags: Optional[CognitionFlags] = None,
        *,
        manifest_path: Optional[Path] = None,
        rive_path: Optional[Path] = None,
    ):
        resolved = flags or load_flags()
        self.session = session
        self.flags = resolved
        self.legacy = LegacyNlu(session, resolved)
        self.manifest = _load_manifest(
            Path(manifest_path) if manifest_path else default_manifest_path()
        )
        self.engine = _load_engine(
            Path(rive_path) if rive_path else default_rive_path()
        )

    def _trigger_id(self, text: str) -> str:
        try:
            reply = self.engine.reply("nlu", text)
        except Exception as exc:
            raise BackendError("RiveScript не смог разобрать фразу") from exc
        value = str(reply or "").strip()
        if value.startswith("[ERR:"):
            raise BackendError("RiveScript: %s" % value)
        return value

    def understand(self, text: str, *, topic: str = "default"):
        raw = str(text or "")
        base = self.legacy.understand(raw, topic=topic)
        if not raw.strip():
            return base
        trigger_id = self._trigger_id(raw)
        if not trigger_id or trigger_id == FALLBACK_ID:
            return base
        match = self.manifest.get(trigger_id)
        if match is None:
            return base
        return self._apply(base, match)

    def _apply(self, base: Any, match: Any) -> Any:
        if not isinstance(base, UtteranceFrame):
            return base
        evidence = base.evidence + (
            "rive:%s:%s" % (match.source, match.id),
        )
        floor = 0.9 if match.source in ("action", "marker") else 0.85
        confidence = min(1.0, max(float(base.confidence), floor))
        return replace(
            base,
            confidence=confidence,
            evidence=evidence,
        )


__all__ = [
    "FALLBACK_ID",
    "RiveNlu",
    "default_manifest_path",
    "default_rive_path",
]
