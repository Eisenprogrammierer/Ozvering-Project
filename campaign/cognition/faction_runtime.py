"""Выбор действия/приказа фракции в Soar через SML.

Python считает веса кандидатов, накопленные границы и ``pick`` — ровно
те же числа, что в легаси-рулетке. Soar получает готовые границы и
выбирает первого кандидата, чья граница не меньше ``pick``. Так
сохраняются распределение и расход ``rng``, но правило выбора живёт в
Soar.

Модуль не импортирует ``soar_sml`` на уровне модуля: без пакета
``SoarFactionPolicy`` отказывает с понятной ошибкой, а кампания
деградирует до легаси.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .errors import BackendError, SoarError
from .faction_compiler import (
    DEFAULT_SOAR_DIR,
    FACTION_NAME,
    POLICY_NAME,
    FactionModel,
    load_model,
)
from ..npc_decisions import (
    DEFAULT_AGREEMENT_THRESHOLD,
    NpcDecisionMonitor,
)
from .soar_runtime import (
    _kernel,
    _new_agent,
    _prepare_agent,
    soar_available,
)

MONITOR_VERSION = 1
FACTION_KINDS = ("action", "order")


def _float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BackendError("%s должен быть числом" % name) from exc


def _normalise(
    candidates: Iterable[Any],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen = set()
    for index, item in enumerate(candidates):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise BackendError(
                "кандидат %d должен быть парой (id, weight)" % index
            )
        option_id = str(item[0] or "")
        if not option_id:
            continue
        if option_id in seen:
            raise BackendError(
                "кандидат %r повторяется" % option_id
            )
        seen.add(option_id)
        weight = _float(item[1], "candidates[%d].weight" % index)
        if not math.isfinite(weight) or weight < 0.0:
            raise BackendError(
                "вес кандидата %r должен быть конечным и >= 0"
                % option_id
            )
        items.append(
            {
                "id": option_id,
                "weight": weight,
                "rank": index,
            }
        )
    return items


def roulette_choice(
    candidates: Iterable[Any],
    roll: float,
) -> Optional[str]:
    """Легаси-рулетка: первый, чья накопленная граница не меньше pick.

    Возвращает ``None`` для пустого списка и последний id, если сумма
    весов не положительна — ровно как прежний код кампании.
    """

    items = _normalise(candidates)
    if not items:
        return None
    total = sum(item["weight"] for item in items)
    if total <= 0.0:
        return items[-1]["id"]
    pick = min(max(_float(roll, "roll"), 0.0), 1.0) * total
    upto = 0.0
    for item in items:
        upto += item["weight"]
        if pick <= upto:
            return item["id"]
    return items[-1]["id"]


def _read_decision(agent: Any) -> Optional[str]:
    output = agent.GetOutputLink()
    if output is None:
        return None
    decisions: List[str] = []
    for index in range(output.GetNumberChildren()):
        child = output.GetChild(index)
        if child.GetAttribute() == "decision":
            decisions.append(str(child.GetValueAsString()))
    if len(decisions) > 1:
        raise SoarError(
            "Soar записал %d решений вместо одного" % len(decisions)
        )
    return decisions[0] if decisions else None


@dataclass
class FactionDecisionMonitor:
    """Счётчики согласия Soar с легаси по действиям и приказам."""

    REPORT_KIND = "faction_decisions"
    max_samples: int = 20
    unavailable: bool = False
    monitors: Dict[str, NpcDecisionMonitor] = field(default_factory=dict)

    def _monitor(self, kind: Any) -> NpcDecisionMonitor:
        key = str(kind or "decision")
        monitor = self.monitors.get(key)
        if monitor is None:
            monitor = NpcDecisionMonitor(max_samples=self.max_samples)
            self.monitors[key] = monitor
        return monitor

    def record(
        self,
        *,
        kind: Any,
        side: Any,
        backend: str,
        legacy: Any,
        candidate: Any,
        elapsed_ms: float = 0.0,
        error: Optional[str] = None,
        turn: Optional[int] = None,
        budget: bool = False,
    ) -> None:
        self._monitor(kind).record(
            side=side,
            backend=backend,
            legacy=legacy,
            candidate=candidate,
            elapsed_ms=elapsed_ms,
            error=error,
            turn=turn,
            budget=budget,
        )

    def note(
        self,
        *,
        kind: Any,
        side: Any,
        elapsed_ms: float = 0.0,
    ) -> None:
        self._monitor(kind).note_decision(
            side=side, elapsed_ms=elapsed_ms
        )

    def _merge_sides(
        self,
        reports: Mapping[str, Mapping[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for report in reports.values():
            for key, item in report.get("sides", {}).items():
                bundle = merged.setdefault(
                    key,
                    {
                        "total": 0,
                        "evaluated": 0,
                        "agreements": 0,
                        "errors": 0,
                        "budget": 0,
                        "elapsed_ms": 0.0,
                        "max_elapsed_ms": 0.0,
                    },
                )
                for name in (
                    "total",
                    "evaluated",
                    "agreements",
                    "errors",
                    "budget",
                ):
                    bundle[name] += int(item.get(name, 0))
                bundle["elapsed_ms"] += float(
                    item.get("elapsed_ms", 0.0)
                )
                bundle["max_elapsed_ms"] = max(
                    bundle["max_elapsed_ms"],
                    float(item.get("max_elapsed_ms", 0.0)),
                )
        for bundle in merged.values():
            evaluated = bundle["evaluated"]
            bundle["agreement"] = (
                bundle["agreements"] / float(evaluated)
                if evaluated
                else 1.0
            )
            bundle["elapsed_ms"] = round(bundle["elapsed_ms"], 3)
            bundle["max_elapsed_ms"] = round(
                bundle["max_elapsed_ms"], 3
            )
        return merged

    def report(
        self,
        threshold: float = DEFAULT_AGREEMENT_THRESHOLD,
    ) -> Dict[str, Any]:
        limit = float(threshold)
        reports = {
            key: monitor.report(limit)
            for key, monitor in sorted(self.monitors.items())
        }
        total = sum(item["total"] for item in reports.values())
        evaluated = sum(
            item["evaluated"] for item in reports.values()
        )
        agreements = sum(
            item["agreements"] for item in reports.values()
        )
        errors = sum(item["errors"] for item in reports.values())
        elapsed = sum(
            float(item["elapsed_ms"]) for item in reports.values()
        )
        peak = max(
            (
                float(item["max_elapsed_ms"])
                for item in reports.values()
            ),
            default=0.0,
        )
        agreement = (
            agreements / float(evaluated) if evaluated else 1.0
        )
        ok = (
            not self.unavailable
            and errors == 0
            and agreement >= limit
        )
        return {
            "kind": self.REPORT_KIND,
            "version": MONITOR_VERSION,
            "total": total,
            "evaluated": evaluated,
            "agreements": agreements,
            "agreement": round(agreement, 6),
            "threshold": limit,
            "ok": ok,
            "errors": errors,
            "unavailable": bool(self.unavailable),
            "elapsed_ms": round(elapsed, 3),
            "max_elapsed_ms": round(peak, 3),
            "kinds": {
                key: {
                    "total": item["total"],
                    "evaluated": item["evaluated"],
                    "agreements": item["agreements"],
                    "agreement": item["agreement"],
                    "errors": item["errors"],
                    "budget": item["budget"],
                    "elapsed_ms": item["elapsed_ms"],
                    "max_elapsed_ms": item["max_elapsed_ms"],
                    "ok": item["ok"],
                }
                for key, item in reports.items()
            },
            "sides": self._merge_sides(reports),
            "mismatches": [
                dict(sample)
                for report in reports.values()
                for sample in report.get("mismatches", [])
            ],
            "error_samples": [
                dict(sample)
                for report in reports.values()
                for sample in report.get("error_samples", [])
            ],
        }


class SoarFactionPolicy:
    """Выбор действия/приказа продукциями Soar с parity к рулетке."""

    def __init__(
        self,
        *,
        model: Optional[FactionModel] = None,
        policy_path: Optional[Path] = None,
        source_dir: Path = DEFAULT_SOAR_DIR,
        timeout_ms: Optional[float] = None,
    ):
        self.model = model or load_model(
            Path(source_dir) / FACTION_NAME
        )
        self.path = Path(policy_path) if policy_path else (
            Path(source_dir) / POLICY_NAME
        )
        try:
            self.text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BackendError(
                "нет сгенерированной политики фракции: %s. "
                "Запустите python -m campaign.cognition."
                "faction_compiler --write" % self.path
            ) from exc
        self.timeout_ms = max(0.0, float(timeout_ms or 0.0))
        self.last_elapsed_ms = 0.0
        self._agent: Any = None

    def _agent_for(self) -> Any:
        if self._agent is None:
            agent = _new_agent()
            try:
                _prepare_agent(agent, self.model, self.text)
            except Exception:
                _kernel().DestroyAgent(agent)
                raise
            self._agent = agent
        return self._agent

    def close(self) -> None:
        if self._agent is not None:
            _kernel().DestroyAgent(self._agent)
            self._agent = None

    def _reset(self, agent: Any) -> None:
        agent.ExecuteCommandLine("init-soar")
        for command in self.model.commands():
            agent.ExecuteCommandLine(command)

    def _budget(self, timeout_ms: Optional[float]) -> float:
        if timeout_ms is not None:
            return max(0.0, float(timeout_ms))
        return self.timeout_ms

    def _check_budget(self, started: float, limit: float) -> None:
        if not limit:
            return
        elapsed = (time.perf_counter() - started) * 1000.0
        if elapsed > limit:
            raise SoarError(
                "Soar превысил бюджет фракции до завершения цикла: "
                "%.2f мс > %.2f мс" % (elapsed, limit)
            )

    def choose(
        self,
        candidates: Iterable[Any],
        roll: float,
        *,
        timeout_ms: Optional[float] = None,
    ) -> Optional[str]:
        """Вернуть id действия/приказа; ``None``, если кандидатов нет."""

        items = _normalise(candidates)
        if not items:
            return None
        total = sum(item["weight"] for item in items)
        if total <= 0.0:
            return items[-1]["id"]
        pick = min(max(_float(roll, "roll"), 0.0), 1.0) * total
        upto = 0.0
        for item in items:
            upto += item["weight"]
            item["upto"] = upto
        limit = self._budget(timeout_ms)
        started = time.perf_counter()
        self.last_elapsed_ms = 0.0
        agent = self._agent_for()
        ok = False
        decision: Optional[str] = None
        try:
            self._reset(agent)
            link = agent.GetInputLink()
            agent.CreateFloatWME(link, "pick", pick)
            for item in items:
                node = agent.CreateIdWME(link, "candidate")
                agent.CreateStringWME(node, "id", item["id"])
                agent.CreateFloatWME(node, "upto", item["upto"])
                agent.CreateIntWME(node, "rank", item["rank"])
            agent.SynchronizeInputLink()
            cycles = max(1, int(self.model.decision_cycles))
            for _cycle in range(cycles):
                self._check_budget(started, limit)
                agent.RunSelf(1)
            decision = _read_decision(agent)
            ok = True
        finally:
            self.last_elapsed_ms = (
                time.perf_counter() - started
            ) * 1000.0
            if not ok:
                self.close()
        if decision is None:
            raise SoarError("Soar не выбрал действие фракции")
        known = {item["id"] for item in items}
        if decision not in known:
            raise SoarError(
                "Soar выбрал неизвестное действие %r" % (decision,)
            )
        if limit and self.last_elapsed_ms > limit:
            raise SoarError(
                "Soar превысил бюджет фракции: %.2f мс > %.2f мс"
                % (self.last_elapsed_ms, limit)
            )
        return decision


def faction_available() -> bool:
    """Есть ли рабочий пакет Soar."""

    return bool(soar_available())


__all__ = [
    "FACTION_KINDS",
    "FactionDecisionMonitor",
    "MONITOR_VERSION",
    "SoarFactionPolicy",
    "faction_available",
    "roulette_choice",
]
