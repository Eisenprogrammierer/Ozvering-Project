"""Логический вывод диалога: легаси, теневой режим и Soar.

Флаг ``inference_backend`` живёт в ``configs/cognition/backends.json``.
Режимы:

* ``legacy`` — прежний ``InferenceEngine``, Soar не запускается;
* ``shadow`` — ответ строит легаси, замыкание Soar считается рядом и
  сравнивается; расхождения попадают в отчёт;
* ``soar`` — решения и доказательства берутся из Soar, ошибки не
  маскируются.

Soar строит прямое замыкание правил; Python выбирает из него решения в
порядке легаси и проверяет согласованность переменных. Без пакета
``soar-sml`` режимы ``shadow``/``soar`` понижаются до ``legacy``:
отчёт помечает ``unavailable=True``, ``ok=False``.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

INFERENCE_BACKENDS = ("legacy", "shadow", "soar")


@dataclass
class InferenceReport:
    """Сводка запросов вывода для теневого сравнения."""

    backend: str = "legacy"
    requested: str = "legacy"
    unavailable: bool = False
    queries: int = 0
    agreements: int = 0
    disagreements: int = 0
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
            "queries": self.queries,
            "agreements": self.agreements,
            "disagreements": self.disagreements,
            "errors": self.errors,
            "last_error": self.last_error,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "traces": tuple(self.traces),
        }


def _same(left: Sequence[Any], right: Sequence[Any]) -> bool:
    """Совпадают ли решения по связываниям и доказательствам."""

    if len(left) != len(right):
        return False
    for first, second in zip(left, right):
        if dict(first.bindings) != dict(second.bindings):
            return False
        if first.proof.signature() != second.proof.signature():
            return False
    return True


class InferenceBackend:
    """Выбор движка вывода с откатом на легаси и теневым сравнением."""

    def __init__(
        self,
        catalog: Any,
        knowledge: Any,
        backend: str = "legacy",
        *,
        timeout_ms: Optional[float] = None,
        soar: Any = None,
        shadow_sink: Optional[
            Callable[[Mapping[str, Any]], None]
        ] = None,
        report: Optional[InferenceReport] = None,
    ):
        text = str(backend or "legacy")
        if text not in INFERENCE_BACKENDS:
            raise ValueError(
                "inference_backend=%r не поддерживается; допустимо: %s"
                % (text, ", ".join(INFERENCE_BACKENDS))
            )
        from .inference import InferenceEngine

        self.catalog = catalog
        self.knowledge = knowledge
        self.requested = text
        self.backend = text
        self.timeout_ms = timeout_ms
        self.shadow_sink = shadow_sink
        self.legacy = InferenceEngine(catalog, knowledge)
        self.max_depth = self.legacy.max_depth
        self.rules = self.legacy.rules
        self._soar = soar
        self._ready = soar is not None
        self._owns_report = report is None
        self.report = report or InferenceReport(
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
        if self._owns_report:
            self.report.backend = "legacy"
        self.report.unavailable = True
        self.report.last_error = str(reason)

    def for_knowledge(self, knowledge: Any) -> "InferenceBackend":
        """Тот же режим и отчёт, но другое знание.

        Нужен контрфактам: контрмодель — копия знания с подменёнными
        фактами. Текущий режим берётся из ``self.backend``, поэтому после
        деградации до ``legacy`` новый бэкенд не пытается снова поднять
        Soar. Отчёт общий, чтобы теневые запросы контрмодели попадали в
        те же счётчики.
        """

        return InferenceBackend(
            self.catalog,
            knowledge,
            self.backend,
            timeout_ms=self.timeout_ms,
            shadow_sink=self.shadow_sink,
            report=self.report,
        )

    def _ensure_soar(self) -> bool:
        """Лениво поднять Soar; без пакета — понижение до легаси."""

        if not self.active:
            return False
        if self._ready and self._soar is not None:
            return True
        try:
            from ..cognition.inference_runtime import (
                SoarInference,
                soar_available,
            )
        except Exception as exc:  # noqa: BLE001 — деградация обязательна
            self._degrade(str(exc))
            return False
        if not soar_available():
            self._degrade("пакет soar-sml не установлен")
            return False
        try:
            self._soar = SoarInference(
                self.catalog,
                self.knowledge,
                timeout_ms=self.timeout_ms,
            )
        except Exception as exc:  # noqa: BLE001
            self.report.errors += 1
            self.report.last_error = str(exc)
            if self.backend == "soar":
                raise
            self._degrade(str(exc))
            return False
        self._ready = True
        return True

    # --- запросы ---------------------------------------------------

    def prove(
        self, relation: str, args: Iterable[str] = ()
    ) -> Tuple[Any, ...]:
        pattern = tuple(str(item) for item in args)
        legacy = self.legacy.prove(relation, pattern)
        if not self.active:
            return legacy
        if not self._ensure_soar():
            return legacy
        started = time.perf_counter()
        try:
            result = self._soar.prove(relation, pattern)
        except Exception as exc:  # noqa: BLE001
            self.report.errors += 1
            self.report.last_error = str(exc)
            if self.backend == "soar":
                raise
            return legacy
        self.report.queries += 1
        self.report.elapsed_ms += (
            time.perf_counter() - started
        ) * 1000.0
        self.report.traces = (
            "%s/%d" % (relation, len(pattern)),
        )
        if self.backend == "shadow":
            agree = _same(result, legacy)
            if agree:
                self.report.agreements += 1
            else:
                self.report.disagreements += 1
            self._emit(
                {
                    "kind": "inference",
                    "relation": str(relation),
                    "args": pattern,
                    "legacy": len(legacy),
                    "soar": len(result),
                    "agree": agree,
                }
            )
            return legacy
        return result

    def first(
        self, relation: str, *args: str
    ) -> Optional[Any]:
        results = self.prove(relation, args)
        return results[0] if results else None

    def has(self, relation: str, *args: str) -> bool:
        return bool(self.prove(relation, args))

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

    def to_dict(self) -> Dict[str, Any]:
        return self.report.to_dict()


def load_inference(
    catalog: Any,
    knowledge: Any,
    flags: Any = None,
    shadow_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
) -> InferenceBackend:
    """Собрать вывод по флагам когниции."""

    if flags is None:
        from ..cognition.backends import load_flags

        flags = load_flags()
    return InferenceBackend(
        catalog,
        knowledge,
        flags.inference_backend,
        shadow_sink=shadow_sink,
    )


__all__ = [
    "INFERENCE_BACKENDS",
    "InferenceBackend",
    "InferenceReport",
    "load_inference",
]
