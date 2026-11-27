"""Живой NLU-бэкенд диалога: legacy, теневой RiveScript и RiveScript.

Флаг ``nlu_backend`` живёт в ``configs/cognition/backends.json``.
Режимы:

* ``legacy`` — прежний ``ChartParser``/фрагменты/fallback;
* ``shadow`` — ответ строит легаси, RiveScript выбирает триггер рядом и
  сравнивается; расхождения попадают в отчёт;
* ``rive`` — триггер и слоты выбирает RiveScript, кадр собирается из
  манифеста и захватов ``<star>``; без пакета ``rivescript`` режим
  отказывает с понятной ошибкой.

Смысловая часть совпадает с ``LegacyNlu`` на золотом корпусе, поэтому
ответы и ``Turn.source`` не меняются. ``ChartParser`` разбирает
вложенные ``S``-слоты и служит полным откатом при неизвестном триггере
или неразрешённом слоте.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Dict, Optional

from .backends import NLU_BACKENDS, CognitionFlags, load_flags
from .errors import BackendError, RiveError
from .nlu import LegacyNlu
from .parity import result_core


@dataclass
class NluReport:
    """Сводка живого NLU для теневого сравнения."""

    backend: str = "legacy"
    requested: str = "legacy"
    unavailable: bool = False
    total: int = 0
    matched: int = 0
    fallback: int = 0
    semantic_fallback: int = 0
    mismatches: int = 0
    errors: int = 0
    last_error: str = ""
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.unavailable and self.errors == 0

    @property
    def fallback_rate(self) -> float:
        return self.fallback / float(self.total) if self.total else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "requested": self.requested,
            "unavailable": self.unavailable,
            "ok": self.ok,
            "total": self.total,
            "matched": self.matched,
            "fallback": self.fallback,
            "semantic_fallback": self.semantic_fallback,
            "fallback_rate": round(self.fallback_rate, 6),
            "mismatches": self.mismatches,
            "errors": self.errors,
            "last_error": self.last_error,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


class NluBackend:
    """Выбор NLU с теневым RiveScript и откатом на легаси."""

    def __init__(
        self,
        session: Any,
        flags: Optional[CognitionFlags] = None,
        backend: Optional[str] = None,
        *,
        shadow_sink: Optional[Callable[[str, Any], None]] = None,
    ):
        resolved = flags or load_flags()
        requested = str(backend or resolved.nlu_backend)
        if requested not in NLU_BACKENDS:
            raise ValueError(
                "nlu_backend=%r не поддерживается; допустимо: %s"
                % (requested, ", ".join(NLU_BACKENDS))
            )
        self.session = session
        self.flags = resolved
        self.requested = requested
        self.backend = requested
        self.shadow_sink = shadow_sink
        self.legacy = LegacyNlu(session, resolved)
        self._rive = None
        self.last_sem: Any = None
        self.last_parse: Any = None
        self.last_source = ""
        self.last_rule = ""
        self.last_reason = ""
        self.last_trigger = ""
        self.report = NluReport(
            backend=self.backend, requested=self.requested
        )

    @property
    def active(self) -> bool:
        return self.backend in ("shadow", "rive")

    def _degrade(self, reason: str) -> None:
        self.backend = "legacy"
        self.report.backend = "legacy"
        self.report.unavailable = True
        self.report.last_error = str(reason)

    def _ensure_rive(self) -> Any:
        if self._rive is not None:
            return self._rive
        from .rive_runtime import RiveNlu

        self._rive = RiveNlu(self.session, self.flags)
        return self._rive

    def _adopt(self, source: Any) -> None:
        self.last_sem = source.last_sem
        self.last_parse = source.last_parse
        self.last_source = source.last_source
        self.last_rule = source.last_rule
        self.last_reason = source.last_reason
        self.last_trigger = getattr(source, "last_trigger", "")

    def _sync(self) -> None:
        rive = self._rive
        if rive is None:
            return
        self.report.total = rive.counts["total"]
        self.report.matched = rive.counts["matched"]
        self.report.fallback = rive.counts["fallback"]
        self.report.semantic_fallback = rive.counts.get(
            "semantic_fallback", 0
        )

    def understand(self, text: str, *, topic: str = "default"):
        """Разобрать фразу, сохранив последний смысл для живого пути."""

        started = time.perf_counter()
        try:
            if self.backend == "legacy":
                result = self.legacy.understand(text, topic=topic)
                self._adopt(self.legacy)
                self.report.total += 1
                return result
            if self.backend == "shadow":
                primary = self.legacy.understand(text, topic=topic)
                self._adopt(self.legacy)
                try:
                    rive = self._ensure_rive()
                    shadow = rive.understand(text, topic=topic)
                    self._sync()
                    if result_core(primary) == result_core(shadow):
                        pass
                    else:
                        self.report.mismatches += 1
                    if self.shadow_sink is not None:
                        self.shadow_sink(text, shadow)
                except Exception as exc:
                    self.report.errors += 1
                    self._degrade(str(exc))
                return primary
            try:
                rive = self._ensure_rive()
            except Exception as exc:
                raise BackendError(
                    "nlu_backend=rive недоступен: %s" % exc
                ) from exc
            try:
                result = rive.understand(text, topic=topic)
            except (BackendError, RiveError) as exc:
                # Сбой движка не имеет права сорвать ход: отдаём
                # legacy-разбор и честно помечаем ошибку в отчёте.
                self.report.errors += 1
                self.report.last_error = str(exc)
                result = self.legacy.understand(text, topic=topic)
                self._adopt(self.legacy)
                self._sync()
                return result
            self._adopt(rive)
            self._sync()
            return result
        finally:
            self.report.elapsed_ms += (
                time.perf_counter() - started
            ) * 1000.0


def load_nlu(
    session: Any,
    flags: Optional[CognitionFlags] = None,
    backend: Optional[str] = None,
    *,
    shadow_sink: Optional[Callable[[str, Any], None]] = None,
) -> NluBackend:
    """Собрать живой NLU-бэкенд для сессии диалога."""

    return NluBackend(
        session,
        flags=flags,
        backend=backend,
        shadow_sink=shadow_sink,
    )


__all__ = ["NluBackend", "NluReport", "load_nlu"]
