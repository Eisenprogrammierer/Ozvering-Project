"""Метрики решений NPC: согласие Soar с ``NeedPolicy`` и бюджет.

Монитор не пишет журнал и не меняет состояние кампании: он только
накапливает счётчики для длинных прогонов и тестов. Снимок кампании
метрики не хранит, поэтому схема сейва не меняется.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Mapping, Optional

MONITOR_VERSION = 1
DEFAULT_AGREEMENT_THRESHOLD = 0.95


def job_diversity(counts: Mapping[str, Any]) -> Dict[str, Any]:
    """Разнообразие выбранных работ: энтропия, distinct и top_share.

    ``evenness`` — энтропия, нормированная на ``log2(distinct)``: 1.0
    означает равномерное распределение по использованным работам, 0.0 —
    одну работу. Это не сравнение с полным каталогом работ (он зависит
    от хода), а честная мера рассеяния фактических решений.
    """

    values = []
    for value in counts.values():
        try:
            count = int(value)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            values.append(count)
    total = sum(values)
    if total <= 0:
        return {
            "total": 0,
            "distinct": 0,
            "entropy": 0.0,
            "evenness": 0.0,
            "top_share": 0.0,
        }
    shares = [value / float(total) for value in values]
    entropy = -sum(share * math.log2(share) for share in shares)
    distinct = len(values)
    evenness = entropy / math.log2(distinct) if distinct > 1 else 0.0
    return {
        "total": total,
        "distinct": distinct,
        "entropy": round(entropy, 6),
        "evenness": round(evenness, 6),
        "top_share": round(max(values) / float(total), 6),
    }


def _side_bundle() -> Dict[str, Any]:
    return {
        "total": 0,
        "evaluated": 0,
        "agreements": 0,
        "errors": 0,
        "budget": 0,
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
    budget: int = 0
    elapsed_ms: float = 0.0
    max_elapsed_ms: float = 0.0
    sides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    mismatches: List[Dict[str, Any]] = field(default_factory=list)
    error_samples: List[Dict[str, Any]] = field(default_factory=list)
    jobs: Dict[str, Dict[str, int]] = field(default_factory=dict)
    job_total: int = 0

    def record_action(self, *, side: Any, action_id: Any) -> None:
        """Учесть выбранную работу для метрик разнообразия."""

        if action_id is None:
            return
        counts = self.jobs.setdefault(str(side), {})
        key = str(action_id)
        counts[key] = counts.get(key, 0) + 1
        self.job_total += 1

    def job_report(self) -> Dict[str, Any]:
        """Сводка разнообразия работ по сторонам и целиком."""

        merged: Dict[str, int] = {}
        for counts in self.jobs.values():
            for key, value in counts.items():
                merged[key] = merged.get(key, 0) + int(value)
        overall = job_diversity(merged)
        return {
            "total": self.job_total,
            "distinct": overall["distinct"],
            "entropy": overall["entropy"],
            "evenness": overall["evenness"],
            "top_share": overall["top_share"],
            "sides": {
                key: job_diversity(counts)
                for key, counts in sorted(self.jobs.items())
            },
        }

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
        budget: bool = False,
    ) -> None:
        """Записать одно решение; ошибка Soar не считается согласием."""

        key = str(side)
        bundle = self.sides.setdefault(key, _side_bundle())
        self.total += 1
        bundle["total"] += 1
        if budget:
            self.budget += 1
            bundle["budget"] += 1
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

    def note_decision(self, *, side: Any, elapsed_ms: float = 0.0) -> None:
        """Учесть решение без сравнения с легаси (строгий ``soar``).

        Согласие здесь не считается: сравнивать не с чем. Счётчик нужен,
        чтобы отчёт строгого прогона показывал объём и латентность.
        """

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
            "budget": self.budget,
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
                    "budget": value["budget"],
                    "elapsed_ms": round(value["elapsed_ms"], 3),
                    "max_elapsed_ms": round(
                        value["max_elapsed_ms"], 3
                    ),
                }
                for key, value in sorted(self.sides.items())
            },
            "mismatches": [dict(item) for item in self.mismatches],
            "error_samples": [dict(item) for item in self.error_samples],
            "jobs": self.job_report(),
        }


__all__ = [
    "DEFAULT_AGREEMENT_THRESHOLD",
    "MONITOR_VERSION",
    "NpcDecisionMonitor",
    "job_diversity",
]
