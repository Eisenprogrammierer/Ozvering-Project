"""Выбор BDI-намерения в Soar через SML.

Python раскладывает кандидатов намерения по слагаемым легаси-оценки,
Soar считает сумму и выбирает строгий максимум. Как и политика работ,
выбор детерминирован: ``epsilon-greedy`` с ``epsilon=0`` превращает
numeric-indifferent предпочтения в argmax, а ранг кандидата с крошечным
отрицательным шагом повторяет легаси-tie-break «первое намерение в
порядке конфига».

Модуль не импортирует ``soar_sml`` на уровне модуля: без пакета
``SoarIntention`` отказывает с понятной ошибкой, а BDI деградирует до
легаси.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .errors import BackendError, SoarError
from .intention_compiler import (
    DEFAULT_SOAR_DIR,
    INTENTION_NAME,
    POLICY_NAME,
    IntentionModel,
    load_model,
)
from .soar_runtime import (
    _kernel,
    _new_agent,
    _prepare_agent,
    soar_available,
)

WEIGHT_KEYS = (
    "need_weight",
    "belief_weight",
    "intention_weight",
    "preferred_bonus",
)


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
        if not isinstance(item, Mapping):
            raise BackendError(
                "кандидат %d должен быть объектом" % index
            )
        essence = str(item.get("essence") or "")
        if not essence:
            continue
        if essence in seen:
            raise BackendError(
                "намерение %r повторяется в кандидатах" % essence
            )
        seen.add(essence)
        items.append(
            {
                "essence": essence,
                "need": _float(item.get("need", 0.0), "need"),
                "belief": _float(
                    item.get("belief", 0.0), "belief"
                ),
                "predicate": _float(
                    item.get("predicate", 0.0), "predicate"
                ),
                "should": _float(item.get("should", 0.0), "should"),
                "preferred": _float(
                    item.get("preferred", 0.0), "preferred"
                ),
                "rank": int(item.get("rank", index)),
            }
        )
    return items


def _read_intention(
    agent: Any,
) -> Optional[Tuple[str, float]]:
    output = agent.GetOutputLink()
    if output is None:
        return None
    essence = ""
    score: Optional[float] = None
    count = 0
    for index in range(output.GetNumberChildren()):
        child = output.GetChild(index)
        attribute = child.GetAttribute()
        if attribute == "intention":
            count += 1
            essence = str(child.GetValueAsString())
        elif attribute == "score":
            score = float(child.GetValueAsString())
    if count > 1:
        raise SoarError(
            "Soar записал %d намерений вместо одного" % count
        )
    if not essence:
        return None
    return essence, 0.0 if score is None else score


@dataclass
class IntentionMonitor:
    """Счётчики выбора намерений: согласие с легаси и ошибки."""

    queries: int = 0
    evaluated: int = 0
    agreements: int = 0
    disagreements: int = 0
    errors: int = 0
    unavailable: bool = False
    last_error: str = ""
    elapsed_ms: float = 0.0
    samples: List[Dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        legacy: Optional[str],
        candidate: Optional[str],
        *,
        elapsed_ms: float = 0.0,
        error: Optional[str] = None,
        essence: str = "",
    ) -> None:
        self.queries += 1
        self.elapsed_ms += max(0.0, float(elapsed_ms))
        if error is not None:
            self.errors += 1
            self.last_error = str(error)
            if len(self.samples) < 8:
                self.samples.append(
                    {
                        "essence": essence,
                        "legacy": legacy,
                        "candidate": candidate,
                        "error": str(error),
                    }
                )
            return
        if legacy is None or candidate is None:
            return
        self.evaluated += 1
        if legacy == candidate:
            self.agreements += 1
        else:
            self.disagreements += 1
            if len(self.samples) < 8:
                self.samples.append(
                    {
                        "essence": essence,
                        "legacy": legacy,
                        "candidate": candidate,
                    }
                )

    def report(self) -> Dict[str, Any]:
        agreement = (
            self.agreements / float(self.evaluated)
            if self.evaluated
            else 0.0
        )
        return {
            "queries": self.queries,
            "evaluated": self.evaluated,
            "agreements": self.agreements,
            "disagreements": self.disagreements,
            "agreement": agreement,
            "errors": self.errors,
            "unavailable": self.unavailable,
            "last_error": self.last_error,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "ok": bool(
                not self.unavailable
                and not self.errors
                and not self.disagreements
            ),
            "samples": list(self.samples),
        }


class SoarIntention:
    """Выбор BDI-намерения продукциями Soar с parity к легаси."""

    def __init__(
        self,
        *,
        model: Optional[IntentionModel] = None,
        policy_path: Optional[Path] = None,
        source_dir: Path = DEFAULT_SOAR_DIR,
        timeout_ms: Optional[float] = None,
    ):
        self.model = model or load_model(
            Path(source_dir) / INTENTION_NAME
        )
        self.path = Path(policy_path) if policy_path else (
            Path(source_dir) / POLICY_NAME
        )
        try:
            self.text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BackendError(
                "нет сгенерированной политики намерения: %s. "
                "Запустите python -m campaign.cognition."
                "intention_compiler --write" % self.path
            ) from exc
        self.timeout_ms = max(0.0, float(timeout_ms or 0.0))
        self.last_elapsed_ms = 0.0
        self._agent: Any = None

    def _agent_for(self) -> Any:
        """Долгоживущий агент выбора: продукции ставятся один раз."""

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
        """Сбросить рабочую память перед следующим запросом.

        ``init-soar`` снимает WME и операторы, но сохраняет продукции;
        команды выбора выдаются заново, потому что инициализация
        возвращает настройки Soar по умолчанию.
        """

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
                "Soar превысил бюджет намерения до завершения цикла: "
                "%.2f мс > %.2f мс" % (elapsed, limit)
            )

    def choose(
        self,
        candidates: Iterable[Any],
        weights: Mapping[str, Any],
        *,
        timeout_ms: Optional[float] = None,
    ) -> Optional[Tuple[str, float]]:
        """Вернуть ``(essence, score)``; ``None``, если кандидатов нет."""

        items = _normalise(candidates)
        if not items:
            return None
        values = {
            key: _float(weights.get(key, 0.0), "weights.%s" % key)
            for key in WEIGHT_KEYS
        }
        ranks = {item["essence"]: item["rank"] for item in items}
        limit = self._budget(timeout_ms)
        started = time.perf_counter()
        self.last_elapsed_ms = 0.0
        agent = self._agent_for()
        ok = False
        decision: Optional[Tuple[str, float]] = None
        try:
            self._reset(agent)
            link = agent.GetInputLink()
            weight_node = agent.CreateIdWME(link, "weights")
            for key, value in values.items():
                agent.CreateFloatWME(weight_node, key, value)
            for item in items:
                node = agent.CreateIdWME(link, "candidate")
                agent.CreateStringWME(
                    node, "essence", item["essence"]
                )
                agent.CreateFloatWME(node, "need", item["need"])
                agent.CreateFloatWME(
                    node, "belief", item["belief"]
                )
                agent.CreateFloatWME(
                    node, "predicate", item["predicate"]
                )
                agent.CreateFloatWME(node, "should", item["should"])
                agent.CreateFloatWME(
                    node, "preferred", item["preferred"]
                )
                agent.CreateIntWME(node, "rank", item["rank"])
            agent.SynchronizeInputLink()
            cycles = max(1, int(self.model.decision_cycles))
            for _cycle in range(cycles):
                self._check_budget(started, limit)
                agent.RunSelf(1)
            decision = _read_intention(agent)
            ok = True
        finally:
            self.last_elapsed_ms = (
                time.perf_counter() - started
            ) * 1000.0
            if not ok:
                self.close()
        if decision is None:
            raise SoarError("Soar не выбрал намерение")
        essence, score = decision
        if essence not in ranks:
            raise SoarError(
                "Soar выбрал неизвестное намерение %r" % (essence,)
            )
        if limit and self.last_elapsed_ms > limit:
            raise SoarError(
                "Soar превысил бюджет намерения: %.2f мс > %.2f мс"
                % (self.last_elapsed_ms, limit)
            )
        return essence, score


_SHARED: Dict[Tuple[float, str], SoarIntention] = {}


def shared_intention(
    timeout_ms: Optional[float] = None,
    source_dir: Path = DEFAULT_SOAR_DIR,
) -> SoarIntention:
    """Общий селектор намерений: продукции ставятся один раз.

    Выбор намерения — stateless-запрос к рабочей памяти, поэтому один
    долгоживущий агент обслуживает всех персонажей процесса. Отдельный
    агент на именного NPC появится вместе с полной BDI-памятью Phase 5.
    """

    key = (float(timeout_ms or 0.0), str(Path(source_dir)))
    policy = _SHARED.get(key)
    if policy is None:
        policy = SoarIntention(
            timeout_ms=timeout_ms, source_dir=source_dir
        )
        _SHARED[key] = policy
    return policy


def intention_available() -> bool:
    """Есть ли пакет Soar для выбора намерений."""

    return bool(soar_available())


__all__ = [
    "IntentionMonitor",
    "SoarIntention",
    "WEIGHT_KEYS",
    "intention_available",
    "shared_intention",
]
