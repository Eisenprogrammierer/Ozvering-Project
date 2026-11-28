"""Выбор реакции лидера на доклад/угрозу в Soar через SML.

Python считает оценки вариантов ``trust`` / ``verify`` / ``ignore`` —
ровно те же числа, что в легаси-``_ai_choice``, включая шум из ``rng``.
Soar получает готовые оценки и выбирает строгий максимум; ранг с
крошечным шагом повторяет легаси-tie-break по имени варианта. Так
сохраняются и решение, и расход генератора: шум по-прежнему
генерируется в Python в прежнем порядке.

Модуль не импортирует ``soar_sml`` на уровне модуля: без пакета
``SoarReactionPolicy`` отказывает с понятной ошибкой, а диспетчер
деградирует до легаси.
"""

from __future__ import annotations

from pathlib import Path
import math
import time
from typing import Any, Dict, Iterable, List, Optional

from .errors import BackendError, SoarError
from .faction_runtime import FactionDecisionMonitor
from .reaction_compiler import (
    DEFAULT_SOAR_DIR,
    POLICY_NAME,
    REACTION_NAME,
    ReactionModel,
    load_model,
)
from .soar_runtime import (
    _kernel,
    _new_agent,
    _prepare_agent,
    soar_available,
)

MONITOR_VERSION = 1
REACTION_KINDS = ("report", "threat")


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
                "кандидат %d должен быть парой (id, score)" % index
            )
        option_id = str(item[0] or "")
        if not option_id:
            continue
        if option_id in seen:
            raise BackendError(
                "кандидат %r повторяется" % option_id
            )
        seen.add(option_id)
        score = _float(item[1], "candidates[%d].score" % index)
        if not math.isfinite(score):
            raise BackendError(
                "оценка кандидата %r должна быть конечной" % option_id
            )
        items.append(
            {
                "id": option_id,
                "score": score,
                "rank": 0,
            }
        )
    order = sorted(item["id"] for item in items)
    ranks = {option_id: rank for rank, option_id in enumerate(order)}
    for item in items:
        item["rank"] = ranks[item["id"]]
    return items


def reaction_choice(
    candidates: Iterable[Any],
) -> Optional[str]:
    """Легаси-выбор реакции: максимум оценки, tie-break по имени.

    Возвращает ``None`` для пустого списка. Совпадает с
    ``max(scores, key=lambda key: (scores[key], key))``.
    """

    items = _normalise(candidates)
    if not items:
        return None
    best = items[0]
    for item in items[1:]:
        if (item["score"], item["id"]) > (
            best["score"],
            best["id"],
        ):
            best = item
    return best["id"]


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
            "Soar записал %d реакций вместо одной" % len(decisions)
        )
    return decisions[0] if decisions else None


class ReactionDecisionMonitor(FactionDecisionMonitor):
    """Счётчики согласия Soar с легаси по докладам и угрозам."""

    REPORT_KIND = "reaction_decisions"


class SoarReactionPolicy:
    """Выбор реакции продукциями Soar с parity к легаси-argmax."""

    def __init__(
        self,
        *,
        model: Optional[ReactionModel] = None,
        policy_path: Optional[Path] = None,
        source_dir: Path = DEFAULT_SOAR_DIR,
        timeout_ms: Optional[float] = None,
    ):
        self.model = model or load_model(
            Path(source_dir) / REACTION_NAME
        )
        self.path = Path(policy_path) if policy_path else (
            Path(source_dir) / POLICY_NAME
        )
        try:
            self.text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BackendError(
                "нет сгенерированной политики реакции: %s. "
                "Запустите python -m campaign.cognition."
                "reaction_compiler --write" % self.path
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
                "Soar превысил бюджет реакции до завершения цикла: "
                "%.2f мс > %.2f мс" % (elapsed, limit)
            )

    def choose(
        self,
        candidates: Iterable[Any],
        *,
        timeout_ms: Optional[float] = None,
    ) -> Optional[str]:
        """Вернуть id реакции; ``None``, если кандидатов нет."""

        items = _normalise(candidates)
        if not items:
            return None
        limit = self._budget(timeout_ms)
        started = time.perf_counter()
        self.last_elapsed_ms = 0.0
        agent = self._agent_for()
        ok = False
        decision: Optional[str] = None
        try:
            self._reset(agent)
            link = agent.GetInputLink()
            for item in items:
                node = agent.CreateIdWME(link, "candidate")
                agent.CreateStringWME(node, "id", item["id"])
                agent.CreateFloatWME(
                    node, "score", item["score"]
                )
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
            raise SoarError("Soar не выбрал реакцию")
        known = {item["id"] for item in items}
        if decision not in known:
            raise SoarError(
                "Soar выбрал неизвестную реакцию %r" % (decision,)
            )
        if limit and self.last_elapsed_ms > limit:
            raise SoarError(
                "Soar превысил бюджет реакции: %.2f мс > %.2f мс"
                % (self.last_elapsed_ms, limit)
            )
        return decision


def reaction_available() -> bool:
    """Есть ли рабочий пакет Soar."""

    return bool(soar_available())


__all__ = [
    "MONITOR_VERSION",
    "REACTION_KINDS",
    "ReactionDecisionMonitor",
    "SoarReactionPolicy",
    "reaction_available",
    "reaction_choice",
]
