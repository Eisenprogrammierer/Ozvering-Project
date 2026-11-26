"""Прагматика диалога: выбор плана и раскрытия через Soar.

Флаги живут в ``configs/cognition/backends.json`` (``dialogue_backend``),
правила — в ``configs/soar/pragmatics.json`` и
``configs/dialogue/disclosure.json``. Режимы:

* ``legacy`` — прежний Python-выбор, Soar не запускается;
* ``shadow`` — ответ строит легаси, решение Soar пишется в отчёт;
* ``soar`` — план и исход раскрытия выбирает Soar, ошибки не маскируются.

Без пакета ``soar-sml`` режимы ``shadow``/``soar`` понижаются до
``legacy``: отчёт помечает ``unavailable=True``, ``ok=False``. Синтез
текста остаётся в Python — Soar решает, что сказать, но не как.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

DIALOGUE_BACKENDS = ("legacy", "shadow", "soar")
PLACEHOLDER_POLICY = "honest"


@dataclass
class PragmaticsReport:
    """Сводка решений прагматики для теневого сравнения."""

    backend: str = "legacy"
    requested: str = "legacy"
    unavailable: bool = False
    decisions: int = 0
    agreements: int = 0
    disagreements: int = 0
    plan_mismatches: int = 0
    disclosure_mismatches: int = 0
    errors: int = 0
    last_error: str = ""
    elapsed_ms: float = 0.0
    traces: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.unavailable and self.errors == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "requested": self.requested,
            "unavailable": self.unavailable,
            "ok": self.ok,
            "decisions": self.decisions,
            "agreements": self.agreements,
            "disagreements": self.disagreements,
            "plan_mismatches": self.plan_mismatches,
            "disclosure_mismatches": self.disclosure_mismatches,
            "errors": self.errors,
            "last_error": self.last_error,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "traces": tuple(self.traces),
        }


class DialoguePragmatics:
    """Выбор плана ответа и исхода раскрытия с откатом на легаси."""

    def __init__(
        self,
        backend: str = "legacy",
        *,
        timeout_ms: Optional[float] = None,
        soar: Any = None,
        shadow_sink: Optional[
            Callable[[Mapping[str, Any]], None]
        ] = None,
    ):
        text = str(backend or "legacy")
        if text not in DIALOGUE_BACKENDS:
            raise ValueError(
                "dialogue_backend=%r не поддерживается; допустимо: %s"
                % (text, ", ".join(DIALOGUE_BACKENDS))
            )
        self.requested = text
        self.backend = text
        self.timeout_ms = timeout_ms
        self.shadow_sink = shadow_sink
        self._soar = soar
        self._ready = soar is not None
        self.report = PragmaticsReport(
            backend=self.backend, requested=self.requested
        )

    # --- состояние -------------------------------------------------

    @property
    def active(self) -> bool:
        return self.backend in ("shadow", "soar")

    @property
    def last_trace(self) -> Tuple[str, ...]:
        return tuple(self.report.traces)

    def _degrade(self, reason: str) -> None:
        self.backend = "legacy"
        self._ready = False
        self.report.backend = "legacy"
        self.report.unavailable = True
        self.report.last_error = str(reason)

    def _ensure_soar(self) -> bool:
        """Лениво поднять Soar; без пакета — понижение до легаси."""

        if not self.active:
            return False
        if self._ready and self._soar is not None:
            return True
        try:
            from ..cognition.pragmatics_runtime import (
                SoarPragmatics,
                soar_available,
            )
        except Exception as exc:  # noqa: BLE001 — деградация обязательна
            self._degrade(str(exc))
            return False
        if not soar_available():
            self._degrade("пакет soar-sml не установлен")
            return False
        try:
            self._soar = SoarPragmatics(timeout_ms=self.timeout_ms)
        except Exception as exc:  # noqa: BLE001
            self.report.errors += 1
            self.report.last_error = str(exc)
            if self.backend == "soar":
                raise
            self._degrade(str(exc))
            return False
        self._ready = True
        return True

    # --- решения ---------------------------------------------------

    def _decide(
        self,
        plans: Sequence[Tuple[str, float, int]],
        frame: Mapping[str, Any],
        disclosure: Mapping[str, Any],
    ) -> Optional[Mapping[str, Any]]:
        if not self._ensure_soar():
            return None
        try:
            result = self._soar.decide(plans, frame, disclosure)
        except Exception as exc:  # noqa: BLE001
            self.report.errors += 1
            self.report.last_error = str(exc)
            if self.backend == "soar":
                raise
            return None
        self.report.elapsed_ms += float(result.get("elapsed_ms") or 0.0)
        self.report.traces = tuple(result.get("trace") or ())
        self.report.decisions += 1
        return result

    def choose_plan(
        self,
        candidates: Sequence[Tuple[str, float, int]],
        frame: Mapping[str, Any],
        legacy_plan: str,
    ) -> str:
        """Вернуть id плана: легаси, Soar или легаси при тени."""

        if not candidates or not self.active:
            return legacy_plan
        result = self._decide(
            candidates,
            frame,
            {"policy": PLACEHOLDER_POLICY, "lie": False, "topic": ""},
        )
        if result is None:
            return legacy_plan
        chosen = str(result.get("plan") or "")
        if not chosen:
            return legacy_plan
        if self.backend == "shadow":
            self._compare_plan(chosen, legacy_plan)
            self._emit(
                {
                    "kind": "plan",
                    "legacy": legacy_plan,
                    "soar": chosen,
                }
            )
            return legacy_plan
        return chosen

    def choose_disclosure(
        self,
        plan_id: str,
        policy: str,
        lie: bool,
        topic: str,
        legacy_outcome: str,
        frame: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """Вернуть исход раскрытия: легаси, Soar или легаси при тени."""

        if not self.active or not plan_id:
            return legacy_outcome
        result = self._decide(
            [(plan_id, 0.0, 0)],
            frame or {"kind": "", "act": "", "wh": ""},
            {"policy": policy, "lie": bool(lie), "topic": topic},
        )
        if result is None:
            return legacy_outcome
        outcome = str(result.get("disclosure") or "")
        if not outcome:
            return legacy_outcome
        if self.backend == "shadow":
            self._compare_disclosure(outcome, legacy_outcome)
            self._emit(
                {
                    "kind": "disclosure",
                    "legacy": legacy_outcome,
                    "soar": outcome,
                }
            )
            return legacy_outcome
        return outcome

    # --- сравнение -------------------------------------------------

    def _emit(self, record: Mapping[str, Any]) -> None:
        """Отдать теневую запись приёмнику, не ломая игру."""

        if self.shadow_sink is None:
            return
        try:
            self.shadow_sink(record)
        except Exception as exc:  # noqa: BLE001
            self.report.errors += 1
            self.report.last_error = str(exc)

    def _compare_plan(self, soar_plan: str, legacy_plan: str) -> None:
        if soar_plan == legacy_plan:
            self.report.agreements += 1
            return
        self.report.disagreements += 1
        self.report.plan_mismatches += 1

    def _compare_disclosure(
        self, soar_outcome: str, legacy_outcome: str
    ) -> None:
        if soar_outcome == legacy_outcome:
            self.report.agreements += 1
            return
        self.report.disagreements += 1
        self.report.disclosure_mismatches += 1

    def to_dict(self) -> Dict[str, Any]:
        return self.report.to_dict()


def load_pragmatics(
    *,
    timeout_ms: Optional[float] = None,
    soar: Any = None,
    shadow_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
) -> DialoguePragmatics:
    """Собрать прагматику по флагам когниции."""

    from ..cognition.backends import load_flags

    flags = load_flags()
    return DialoguePragmatics(
        flags.dialogue_backend,
        timeout_ms=(
            flags.decision_timeout_ms if timeout_ms is None else timeout_ms
        ),
        soar=soar,
        shadow_sink=shadow_sink,
    )


__all__ = [
    "DIALOGUE_BACKENDS",
    "DialoguePragmatics",
    "PragmaticsReport",
    "load_pragmatics",
]
