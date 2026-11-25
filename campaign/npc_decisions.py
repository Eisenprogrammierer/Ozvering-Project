"""Метрики решений NPC: согласие Soar с ``NeedPolicy`` и бюджет.

Монитор не пишет журнал и не меняет состояние кампании: он только
накапливает счётчики для длинных прогонов и тестов. Снимок кампании
метрики не хранит, поэтому схема сейва не меняется.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

MONITOR_VERSION = 1
DEFAULT_AGREEMENT_THRESHOLD = 0.95


def _side_bundle() -> Dict[str, Any]:
    return {
        "total": 0,
        "evaluated": 0,
        "agreements": 0,
        "errors": 0,
        "elapsed_ms": 0.0,
        "max_elapsed_ms": 0.0,
    }


@dataclass
class NpcDecisionMonitor:
    """Счётчики согласия теневого Soar с легаси-политикой."""

    max_samples: int = 20
    total: int = 0
    evaluated: int = 0
    agreements: int = 0
    errors: int = 0
    elapsed_ms: float = 0.0
    max_elapsed_ms: float = 0.0
    sides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    mismatches: List[Dict[str, Any]] = field(default_factory=list)
    error_samples: List[Dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        *,
        side: Any,
        backend: str,
        legacy: Any,
        candidate: Any,
        elapsed_ms: float = 0.0,
        error: Optional[str] = None,
        turn: Optional[int] = None,
    ) -> None:
        """Записать одно решение; ошибка Soar не считается согласием."""

        key = str(side)
        bundle = self.sides.setdefault(key, _side_bundle())
        self.total += 1
        bundle["total"] += 1
        elapsed = max(0.0, float(elapsed_ms or 0.0))
        if elapsed:
            self.elapsed_ms += elapsed
            self.max_elapsed_ms = max(self.max_elapsed_ms, elapsed)
            bundle["elapsed_ms"] += elapsed
            bundle["max_elapsed_ms"] = max(
                bundle["max_elapsed_ms"], elapsed
            )
        if error is not None:
            self.errors += 1
            bundle["errors"] += 1
            if len(self.error_samples) < self.max_samples:
                self.error_samples.append(
                    {
                        "side": key,
                        "backend": backend,
                        "turn": turn,
                        "error": str(error),
                    }
                )
            return
        self.evaluated += 1
        bundle["evaluated"] += 1
        if candidate == legacy:
            self.agreements += 1
            bundle["agreements"] += 1
        elif len(self.mismatches) < self.max_samples:
            self.mismatches.append(
                {
                    "side": key,
                    "backend": backend,
                    "turn": turn,
                    "legacy": legacy,
                    "candidate": candidate,
                }
            )

    @property
    def agreement(self) -> float:
        if not self.evaluated:
            return 1.0
        return self.agreements / float(self.evaluated)

    def report(
        self,
        threshold: float = DEFAULT_AGREEMENT_THRESHOLD,
    ) -> Dict[str, Any]:
        """JSON-совместимая сводка для тестов, CLI и диагностики."""

        limit = float(threshold)
        ok = self.errors == 0 and self.agreement >= limit
        return {
            "kind": "npc_decisions",
            "version": MONITOR_VERSION,
            "total": self.total,
            "evaluated": self.evaluated,
            "agreements": self.agreements,
            "agreement": round(self.agreement, 6),
            "threshold": limit,
            "ok": ok,
            "errors": self.errors,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "max_elapsed_ms": round(self.max_elapsed_ms, 3),
            "sides": {
                key: {
                    "total": value["total"],
                    "evaluated": value["evaluated"],
                    "agreements": value["agreements"],
                    "agreement": (
                        value["agreements"] / float(value["evaluated"])
                        if value["evaluated"]
                        else 1.0
                    ),
                    "errors": value["errors"],
                    "elapsed_ms": round(value["elapsed_ms"], 3),
                    "max_elapsed_ms": round(
                        value["max_elapsed_ms"], 3
                    ),
                }
                for key, value in sorted(self.sides.items())
            },
            "mismatches": [dict(item) for item in self.mismatches],
            "error_samples": [dict(item) for item in self.error_samples],
        }


__all__ = [
    "DEFAULT_AGREEMENT_THRESHOLD",
    "MONITOR_VERSION",
    "NpcDecisionMonitor",
]
