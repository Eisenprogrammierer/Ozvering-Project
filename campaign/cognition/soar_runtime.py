"""Исполнение политики NPC в Soar через SML.

Soar получает кандидатов работы на input-link и сам считает оценку и
выбирает оператора. Python только раскладывает данные и читает
``output-link``; веса и значения потребностей — данные, а не решение.

Выбор детерминирован: ``decide indifferent-selection --epsilon-greedy``
с ``epsilon=0`` превращает numeric-indifferent предпочтения в строгий
argmax (по умолчанию Soar 9.6 использует softmax и выбирает случайно).
Tie-break легаси ``max((score, option_id))`` воспроизводится рангом id.

SML — опциональная зависимость: без пакета ``soar-sml`` модуль
импортируется, но ``SoarNpcPolicy`` отказывает с понятной ошибкой.
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
from .soar_compiler import (
    DECISION_NAME,
    DEFAULT_SOAR_DIR,
    POLICY_NAME,
    DecisionModel,
    check_policy,
    load_model,
)

_AGENT_NAMES = itertools.count(1)
_KERNEL: Any = None


def default_policy_path() -> Path:
    return DEFAULT_SOAR_DIR / POLICY_NAME


def soar_available() -> bool:
    """Установлен ли пакет SML."""

    try:
        import soar_sml  # noqa: F401
    except ImportError:
        return False
    return True


def _kernel() -> Any:
    global _KERNEL
    if _KERNEL is not None:
        return _KERNEL
    try:
        import soar_sml
    except ImportError as exc:
        raise BackendError(
            "ai_backend=soar требует пакет soar-sml "
            "(pip install -r requirements-soar.txt)"
        ) from exc
    try:
        _KERNEL = soar_sml.Kernel.CreateKernelInNewThread()
    except Exception as exc:  # pragma: no cover - среда без Soar
        raise SoarError("не удалось запустить Soar") from exc
    return _KERNEL


def _float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise BackendError("%s должен быть числом" % name) from exc


def _clamp(value: Any) -> float:
    return max(0.0, min(1.0, _float(value, "need")))


def production_blocks(text: str) -> Tuple[str, ...]:
    """Выделить продукции ``sp { ... }`` из сгенерированного файла."""

    blocks: List[str] = []
    current: List[str] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not current:
            if stripped.startswith("sp {"):
                current = [stripped]
            continue
        current.append(stripped)
        if stripped == "}":
            blocks.append(" ".join(current))
            current = []
    if current:
        raise SoarError("незакрытая продукция Soar")
    return tuple(blocks)


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


def _normalise(
    candidates: Iterable[Any],
) -> List[Tuple[str, str, float]]:
    items: List[Tuple[str, str, float]] = []
    for index, item in enumerate(candidates):
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise BackendError(
                "кандидат %d должен быть тройкой (id, need, base)" % index
            )
        option, need, base = item
        option_id = str(option or "")
        if not option_id:
            continue
        items.append(
            (
                option_id,
                str(need or ""),
                _float(base, "candidates[%d].base" % index),
            )
        )
    return items


class SoarNpcPolicy:
    """Выбор работы NPC продукциями Soar с parity к ``NeedPolicy``."""

    def __init__(
        self,
        *,
        model: Optional[DecisionModel] = None,
        policy_path: Optional[Path] = None,
        source_dir: Path = DEFAULT_SOAR_DIR,
    ):
        self.model = model or load_model(
            Path(source_dir) / DECISION_NAME
        )
        self.path = Path(policy_path) if policy_path else (
            Path(source_dir) / POLICY_NAME
        )
        try:
            self.text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BackendError(
                "нет сгенерированной политики Soar: %s. "
                "Запустите python -m campaign.cognition.soar_compiler --write"
                % self.path
            ) from exc
        self.last_elapsed_ms = 0.0

    def _agent(self) -> Any:
        kernel = _kernel()
        agent = kernel.CreateAgent("npc_%d" % next(_AGENT_NAMES))
        if agent is None:
            raise SoarError("Soar не создал агента")
        return agent

    def _prepare(self, agent: Any) -> None:
        for command in self.model.commands():
            agent.ExecuteCommandLine(command)
        blocks = production_blocks(self.text)
        if not blocks:
            raise SoarError("в политике Soar нет продукций")
        for block in blocks:
            result = agent.ExecuteCommandLine(block)
            if str(result or "").strip() != "*":
                raise SoarError(
                    "Soar отклонил продукцию: %s" % (result,)
                )

    def choose(
        self,
        candidates: Iterable[Any],
        needs: Mapping[str, Any],
        *,
        weights: Optional[Mapping[str, Any]] = None,
        explore: Optional[bool] = None,
    ) -> Optional[str]:
        """Вернуть id работы; ``None``, если кандидатов нет."""

        if explore:
            raise BackendError(
                "Soar-политика детерминирована и не поддерживает explore; "
                "используйте ai_backend=legacy"
            )
        items = _normalise(candidates)
        if not items:
            return None
        need_values = {
            str(key): _clamp(value) for key, value in dict(needs or {}).items()
        }
        weight_values = {
            str(key): _float(value, "weights")
            for key, value in dict(weights or {}).items()
        }
        ranks: Dict[str, int] = {
            option: index
            for index, option in enumerate(
                sorted({item[0] for item in items})
            )
        }
        started = time.perf_counter()
        agent = self._agent()
        try:
            self._prepare(agent)
            link = agent.GetInputLink()
            for option, need, base in items:
                node = agent.CreateIdWME(link, "candidate")
                agent.CreateStringWME(node, "option", option)
                agent.CreateFloatWME(node, "base", base)
                agent.CreateFloatWME(
                    node, "weight", weight_values.get(need, 0.0)
                )
                agent.CreateFloatWME(
                    node, "need", need_values.get(need, 0.0)
                )
                agent.CreateIntWME(node, "rank", ranks[option])
            agent.SynchronizeInputLink()
            agent.RunSelf(self.model.decision_cycles)
            decision = _read_decision(agent)
        finally:
            kernel = _kernel()
            kernel.DestroyAgent(agent)
            self.last_elapsed_ms = (
                time.perf_counter() - started
            ) * 1000.0
        if decision is None:
            raise SoarError("Soar не выбрал работу")
        if decision not in ranks:
            raise SoarError(
                "Soar выбрал неизвестную работу %r" % (decision,)
            )
        return decision


def check_artifacts(
    source_dir: Path = DEFAULT_SOAR_DIR,
) -> DecisionModel:
    """Проверить, что ``npc_policy.soar`` совпадает с JSON."""

    return check_policy(source_dir)


def weights_for(
    policy: Any,
    needs: Sequence[str],
) -> Dict[str, float]:
    """Веса потребностей из политики; без ``weight()`` — нули."""

    getter = getattr(policy, "weight", None)
    if getter is None:
        return {str(need): 0.0 for need in needs}
    return {str(need): float(getter(need)) for need in needs}


__all__ = [
    "SoarNpcPolicy",
    "check_artifacts",
    "default_policy_path",
    "production_blocks",
    "soar_available",
    "weights_for",
]
