"""Исполнение прагматики диалога в Soar через SML.

Python раскладывает на input-link проверенные кандидаты планов, класс
кадра и вход политики раскрытия. Soar сам проходит три шага
(``interpret-frame`` → ``select-plan`` → ``disclose``) и пишет решение
и трассировку в output-link. Синтез текста остаётся в Python.

Выбор детерминирован: ``epsilon-greedy`` с ``epsilon=0`` даёт строгий
argmax, а порядок каталога передаётся рангом. Для лжи Python считает
детерминированный бросок и передаёт флаг ``lie``: Soar не сравнивает
числа с плавающей точкой.
"""

from __future__ import annotations

import itertools
from pathlib import Path
import time
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from .errors import BackendError, SoarError
from .pragmatics_compiler import (
    DEFAULT_SOAR_DIR,
    DISCLOSURE_OUTCOMES,
    POLICY_NAME,
    PRAGMATICS_NAME,
    PragmaticsModel,
    check_policy,
    load_model,
)
from .soar_runtime import (
    _kernel,
    production_blocks,
    soar_available,
)

_AGENT_NAMES = itertools.count(1)


def default_policy_path() -> Path:
    return DEFAULT_SOAR_DIR / POLICY_NAME


def _text(value: Any, name: str) -> str:
    text = str(value or "")
    if not text:
        return "unknown"
    return text


def _flag(value: Any) -> str:
    if isinstance(value, str):
        return "yes" if value.strip().lower() in ("yes", "true", "1") else "no"
    return "yes" if bool(value) else "no"


def _normalise_plans(
    plans: Iterable[Any],
) -> List[Tuple[str, float, int]]:
    items: List[Tuple[str, float, int]] = []
    for index, item in enumerate(plans):
        if not isinstance(item, (list, tuple)) or len(item) not in (2, 3):
            raise BackendError(
                "план %d должен быть (id, priority[, rank])" % index
            )
        plan_id = str(item[0] or "")
        if not plan_id:
            continue
        try:
            priority = float(item[1])
        except (TypeError, ValueError) as exc:
            raise BackendError(
                "plans[%d].priority должен быть числом" % index
            ) from exc
        rank = int(item[2]) if len(item) == 3 else index
        items.append((plan_id, priority, rank))
    return items


def _read_output(agent: Any) -> Tuple[str, str, str, Tuple[str, ...]]:
    output = agent.GetOutputLink()
    if output is None:
        raise SoarError("Soar не создал output-link")
    decision = ""
    disclosure = ""
    intent = ""
    plan = ""
    policy = ""
    outcome = ""
    for index in range(output.GetNumberChildren()):
        child = output.GetChild(index)
        name = child.GetAttribute()
        value = str(child.GetValueAsString())
        if name == "decision":
            decision = value
        elif name == "disclosure":
            disclosure = value
        elif name == "intent":
            intent = value
        elif name == "trace-plan":
            plan = value
        elif name == "trace-policy":
            policy = value
        elif name == "trace-outcome":
            outcome = value
    traces: List[str] = []
    if intent:
        traces.append("interpret:%s" % intent)
    if plan:
        traces.append("select:%s" % plan)
    if policy:
        traces.append("disclose:%s:%s" % (policy, outcome))
    return decision, disclosure, intent, tuple(traces)


class SoarPragmatics:
    """Выбор плана ответа и исхода раскрытия продукциями Soar."""

    def __init__(
        self,
        *,
        model: Optional[PragmaticsModel] = None,
        policy_path: Optional[Path] = None,
        source_dir: Path = DEFAULT_SOAR_DIR,
        timeout_ms: Optional[float] = None,
    ):
        self.model = model or load_model(
            Path(source_dir) / PRAGMATICS_NAME
        )
        self.path = Path(policy_path) if policy_path else (
            Path(source_dir) / POLICY_NAME
        )
        try:
            self.text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BackendError(
                "нет сгенерированной прагматики Soar: %s. "
                "Запустите python -m campaign.cognition."
                "pragmatics_compiler --write" % self.path
            ) from exc
        self.timeout_ms = max(0.0, float(timeout_ms or 0.0))
        self.last_elapsed_ms = 0.0

    def _agent(self) -> Any:
        kernel = _kernel()
        agent = kernel.CreateAgent("pragmatics_%d" % next(_AGENT_NAMES))
        if agent is None:
            raise SoarError("Soar не создал агента")
        return agent

    def _prepare(self, agent: Any) -> None:
        for command in self.model.commands():
            agent.ExecuteCommandLine(command)
        blocks = production_blocks(self.text)
        if not blocks:
            raise SoarError("в прагматике Soar нет продукций")
        for block in blocks:
            result = agent.ExecuteCommandLine(block)
            if str(result or "").strip() != "*":
                raise SoarError(
                    "Soar отклонил продукцию: %s" % (result,)
                )

    def _budget(self, timeout_ms: Optional[float]) -> float:
        if timeout_ms is None:
            return self.timeout_ms
        return max(0.0, float(timeout_ms))

    def _check_budget(self, started: float, limit: float) -> None:
        if not limit:
            return
        elapsed = (time.perf_counter() - started) * 1000.0
        if elapsed > limit:
            raise SoarError(
                "Soar превысил бюджет прагматики до завершения цикла: "
                "%.2f мс > %.2f мс" % (elapsed, limit)
            )

    def decide(
        self,
        plans: Iterable[Any],
        frame: Mapping[str, Any],
        disclosure: Mapping[str, Any],
        *,
        timeout_ms: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Вернуть ``plan``, ``disclosure``, ``intent`` и ``trace``."""

        items = _normalise_plans(plans)
        if not items:
            raise BackendError("прагматике нужен хотя бы один план")
        ids = {item[0] for item in items}
        frame = dict(frame or {})
        disclosure = dict(disclosure or {})
        policy = str(disclosure.get("policy") or "honest")
        lie = _flag(disclosure.get("lie", False))
        topic = str(disclosure.get("topic") or "")
        limit = self._budget(timeout_ms)
        started = time.perf_counter()
        self.last_elapsed_ms = 0.0
        agent = self._agent()
        try:
            self._prepare(agent)
            link = agent.GetInputLink()
            node = agent.CreateIdWME(link, "frame")
            agent.CreateStringWME(
                node, "kind", _text(frame.get("kind"), "kind")
            )
            agent.CreateStringWME(
                node, "act", str(frame.get("act") or "")
            )
            agent.CreateStringWME(
                node, "wh", str(frame.get("wh") or "")
            )
            for plan_id, priority, rank in items:
                item = agent.CreateIdWME(link, "plan")
                agent.CreateStringWME(item, "id", plan_id)
                agent.CreateFloatWME(item, "priority", priority)
                agent.CreateIntWME(item, "rank", rank)
            node = agent.CreateIdWME(link, "disclosure")
            agent.CreateStringWME(node, "policy", policy)
            agent.CreateStringWME(node, "lie", lie)
            agent.CreateStringWME(node, "topic", topic)
            agent.SynchronizeInputLink()
            cycles = max(1, int(self.model.decision_cycles))
            for _cycle in range(cycles):
                self._check_budget(started, limit)
                agent.RunSelf(1)
            decision, outcome, intent, trace = _read_output(agent)
        finally:
            kernel = _kernel()
            kernel.DestroyAgent(agent)
            self.last_elapsed_ms = (
                time.perf_counter() - started
            ) * 1000.0
        if not decision:
            raise SoarError("Soar не выбрал план ответа")
        if decision not in ids:
            raise SoarError(
                "Soar выбрал неизвестный план %r" % (decision,)
            )
        if outcome not in DISCLOSURE_OUTCOMES:
            raise SoarError(
                "Soar выбрал неизвестный исход раскрытия %r" % (outcome,)
            )
        if limit and self.last_elapsed_ms > limit:
            raise SoarError(
                "Soar превысил бюджет прагматики: %.2f мс > %.2f мс"
                % (self.last_elapsed_ms, limit)
            )
        return {
            "plan": decision,
            "disclosure": outcome,
            "intent": intent,
            "trace": trace,
            "elapsed_ms": round(self.last_elapsed_ms, 3),
        }


def check_artifacts(
    source_dir: Path = DEFAULT_SOAR_DIR,
) -> PragmaticsModel:
    """Проверить, что ``pragmatics.soar`` совпадает с JSON."""

    return check_policy(source_dir)


__all__ = [
    "SoarPragmatics",
    "check_artifacts",
    "default_policy_path",
    "soar_available",
]
