"""Компилятор RL-предпочтений из JSON в продукции Soar.

JSON остаётся источником истины: параметры обучения, выбора и пороги
сравнения живут в ``configs/soar/rl.json``. ``rl.soar`` — сгенерированный
артефакт с ``source_digest``; ``--check`` доказывает, что он не разошёлся
с источником.

Продукции:

* ``rl*init`` — метка корневого состояния;
* ``rl*context`` — контекст эпизода на состоянии;
* ``rl*propose`` — по одному оператору на кандидата;
* ``rl*choose`` — RL-шаблон (``:template``) с numeric-indifferent
  предпочтением; Soar сам ведёт значения операторов;
* ``rl*force`` — при обучении поднимает выбранное в эпизоде действие
  выше остальных, чтобы награда относилась именно к нему;
* ``rl*finish`` — фиксирует выбор, кладёт награду в ``^reward-link``
  и останавливает агента: RL-обновление Soar выполняет при halt.

Soar RL — эпизодический: награда читается только при остановке агента.
Поэтому обучение идёт циклом «``init-soar`` → эпизод → ``(halt)``».
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

from .errors import SoarError
from .serialization import canonical_digest
from .soar_compiler import (
    DIGEST_PREFIX,
    NUMERIC_MODES,
    SELECTION_POLICIES,
    soar_number,
)

COMPILER_VERSION = 1
MODEL_VERSION = 1
DEFAULT_SOAR_DIR = (
    Path(__file__).resolve().parents[2] / "configs" / "soar"
)
MODEL_NAME = "rl.json"
POLICY_NAME = "rl.soar"
FORCE_VALUE = 1000.0


def _number(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SoarError("%s должен быть числом" % name) from exc


def _integer(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SoarError("%s должен быть целым" % name) from exc


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SoarError("%s должен быть объектом" % name)
    return value


@dataclass(frozen=True)
class RlModel:
    """Проверенная модель RL-предпочтений."""

    name: str = "rl"
    learning_enabled: bool = True
    learning_rate: float = 0.3
    discount_rate: float = 0.9
    step_size_parameter: float = 1.0
    decay_mode: str = "normal"
    selection_policy: str = "epsilon-greedy"
    numeric_mode: str = "sum"
    epsilon: float = 0.0
    random_seed: int = 0
    decision_cycles: int = 4
    max_candidates: int = 32
    max_contexts: int = 128
    max_episodes: int = 512
    min_episodes: int = 20
    coverage_threshold: float = 0.5
    reward_tolerance: float = 0.0
    version: int = MODEL_VERSION

    def __post_init__(self):
        if self.version != MODEL_VERSION:
            raise SoarError(
                "версия модели RL %r не поддерживается" % (self.version,)
            )
        if not self.name or not all(
            char.isalpha() or char == "*" for char in self.name
        ):
            raise SoarError(
                "name должен состоять из букв и '*': %r" % (self.name,)
            )
        if self.selection_policy not in SELECTION_POLICIES:
            raise SoarError(
                "selection.policy=%r не поддерживается; допустимо: %s"
                % (
                    self.selection_policy,
                    ", ".join(SELECTION_POLICIES),
                )
            )
        if self.numeric_mode not in NUMERIC_MODES:
            raise SoarError(
                "selection.numeric_mode=%r не поддерживается"
                % (self.numeric_mode,)
            )
        if self.decay_mode not in (
            "normal",
            "exp",
            "log",
            "delta-bar-delta",
        ):
            raise SoarError(
                "learning.decay_mode=%r не поддерживается"
                % (self.decay_mode,)
            )
        if not 0.0 <= self.epsilon <= 1.0:
            raise SoarError("selection.epsilon вне [0, 1]")
        for name in (
            "learning_rate",
            "discount_rate",
            "step_size_parameter",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise SoarError("learning.%s вне [0, 1]" % name)
        if self.decision_cycles < 1:
            raise SoarError(
                "selection.decision_cycles должен быть >= 1"
            )
        for name in (
            "max_candidates",
            "max_contexts",
            "max_episodes",
            "min_episodes",
        ):
            if getattr(self, name) < 1:
                raise SoarError("%s должен быть >= 1" % name)
        for name in ("coverage_threshold",):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise SoarError("%s вне [0, 1]" % name)
        if self.reward_tolerance < 0.0:
            raise SoarError("reward_tolerance должен быть >= 0")

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "name": self.name,
            "learning": {
                "enabled": self.learning_enabled,
                "learning_rate": self.learning_rate,
                "discount_rate": self.discount_rate,
                "step_size_parameter": self.step_size_parameter,
                "decay_mode": self.decay_mode,
            },
            "selection": {
                "policy": self.selection_policy,
                "numeric_mode": self.numeric_mode,
                "epsilon": self.epsilon,
                "random_seed": self.random_seed,
                "decision_cycles": self.decision_cycles,
            },
            "limits": {
                "max_candidates": self.max_candidates,
                "max_contexts": self.max_contexts,
                "max_episodes": self.max_episodes,
            },
            "comparison": {
                "min_episodes": self.min_episodes,
                "coverage_threshold": self.coverage_threshold,
                "reward_tolerance": self.reward_tolerance,
            },
        }

    def digest(self) -> str:
        return canonical_digest(self.to_dict())

    def commands(
        self,
        *,
        epsilon: Optional[float] = None,
        seed: Optional[int] = None,
    ) -> Tuple[str, ...]:
        """Команды Soar для одного эпизода обучения или проверки."""

        value = self.epsilon if epsilon is None else float(epsilon)
        random_seed = self.random_seed if seed is None else int(seed)
        mode = "--sum" if self.numeric_mode == "sum" else "--avg"
        commands = [
            "decide numeric-indifferent-mode %s" % mode,
            "decide indifferent-selection --%s" % self.selection_policy,
            "decide indifferent-selection --epsilon %s"
            % soar_number(value),
            "decide set-random-seed %d" % random_seed,
            "rl --set learning %s"
            % ("on" if self.learning_enabled else "off"),
            "rl --set learning-rate %s"
            % soar_number(self.learning_rate),
            "rl --set discount-rate %s"
            % soar_number(self.discount_rate),
            "rl --set step-size-parameter %s"
            % soar_number(self.step_size_parameter),
            "rl --set decay-mode %s" % self.decay_mode,
        ]
        return tuple(commands)


def model_from_dict(data: Mapping[str, Any]) -> RlModel:
    learning = _mapping(data.get("learning"), "learning")
    selection = _mapping(data.get("selection"), "selection")
    limits = _mapping(data.get("limits"), "limits")
    comparison = _mapping(data.get("comparison"), "comparison")
    return RlModel(
        name=str(data.get("name") or "rl"),
        learning_enabled=bool(learning.get("enabled", True)),
        learning_rate=_number(
            learning.get("learning_rate", 0.3), "learning_rate"
        ),
        discount_rate=_number(
            learning.get("discount_rate", 0.9), "discount_rate"
        ),
        step_size_parameter=_number(
            learning.get("step_size_parameter", 1.0),
            "step_size_parameter",
        ),
        decay_mode=str(learning.get("decay_mode") or "normal"),
        selection_policy=str(
            selection.get("policy") or "epsilon-greedy"
        ),
        numeric_mode=str(selection.get("numeric_mode") or "sum"),
        epsilon=_number(selection.get("epsilon", 0.0), "epsilon"),
        random_seed=_integer(
            selection.get("random_seed", 0), "random_seed"
        ),
        decision_cycles=_integer(
            selection.get("decision_cycles", 4), "decision_cycles"
        ),
        max_candidates=_integer(
            limits.get("max_candidates", 32), "max_candidates"
        ),
        max_contexts=_integer(
            limits.get("max_contexts", 128), "max_contexts"
        ),
        max_episodes=_integer(
            limits.get("max_episodes", 512), "max_episodes"
        ),
        min_episodes=_integer(
            comparison.get("min_episodes", 20), "min_episodes"
        ),
        coverage_threshold=_number(
            comparison.get("coverage_threshold", 0.5),
            "coverage_threshold",
        ),
        reward_tolerance=_number(
            comparison.get("reward_tolerance", 0.0),
            "reward_tolerance",
        ),
        version=_integer(data.get("version", MODEL_VERSION), "version"),
    )


def load_model(path: Optional[Path] = None) -> RlModel:
    source = Path(path) if path else DEFAULT_SOAR_DIR / MODEL_NAME
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SoarError("не удалось прочитать %s" % source) from exc
    except ValueError as exc:
        raise SoarError("%s не является JSON" % source) from exc
    if not isinstance(data, Mapping):
        raise SoarError("%s должен содержать объект" % source)
    return model_from_dict(data)


def render_policy(model: RlModel) -> str:
    """Отрисовать продукции Soar для RL-предпочтений."""

    name = model.name
    lines: List[str] = [
        "// Сгенерировано campaign.cognition.rl_compiler.",
        "// Не редактировать вручную: источник — configs/soar/rl.json.",
        "%s%s" % (DIGEST_PREFIX, model.digest()),
        "",
        "// Корневое состояние эпизода.",
        "sp {%s*init" % name,
        "   (state <s> ^superstate nil)",
        "-->",
        "   (<s> ^name %s)" % name,
        "}",
        "",
        "// Контекст эпизода: сторона, архетип и полоса нужд.",
        "sp {%s*context" % name,
        "   (state <s> ^superstate nil ^io.input-link <i>)",
        "   (<i> ^context <c>)",
        "-->",
        "   (<s> ^context <c>)",
        "}",
        "",
        "// Один оператор на кандидата.",
        "sp {%s*propose" % name,
        "   (state <s> ^name %s ^io.input-link <i>)" % name,
        "   (<i> ^candidate <c>)",
        "   (<c> ^name <n>)",
        "-->",
        "   (<s> ^operator <o> +)",
        "   (<o> ^name <n>)",
        "}",
        "",
        "// RL-шаблон: значение оператора ведёт Soar RL.",
        "sp {%s*choose" % name,
        "   :template",
        "   (state <s> ^name %s ^context <ctx> ^operator <o> +)"
        % name,
        "   (<o> ^name <n>)",
        "-->",
        "   (<s> ^operator <o> = 0)",
        "}",
        "",
        "// Обучение: награда относится к действию из эпизода.",
        "sp {%s*force" % name,
        "   (state <s> ^name %s ^io.input-link <i>)" % name,
        "   (<i> ^chosen <n> ^candidate <c>)",
        "   (<c> ^name <n>)",
        "-->",
        "   (<s> ^operator <o> + = %s)"
        % soar_number(FORCE_VALUE),
        "   (<o> ^name <n>)",
        "}",
        "",
        "// Фиксация выбора, награда и остановка: RL обновляет",
        "// значения только при halt.",
        "sp {%s*finish" % name,
        "   (state <s> ^name %s ^operator <o> ^reward-link <r>"
        " ^io <io>)" % name,
        "   (<o> ^name <n>)",
        "   (<io> ^input-link <i>)",
        "   (<i> ^reward <v>)",
        "-->",
        "   (<s> ^chosen <n>)",
        "   (<r> ^reward <rid>)",
        "   (<rid> ^value <v>)",
        "   (halt)",
        "}",
        "",
    ]
    return "\n".join(lines)


def compile_policy(
    source_dir: Path = DEFAULT_SOAR_DIR,
) -> Tuple[str, RlModel]:
    root = Path(source_dir)
    model = load_model(root / MODEL_NAME)
    return render_policy(model), model


def write_policy(source_dir: Path = DEFAULT_SOAR_DIR) -> Path:
    root = Path(source_dir)
    text, _ = compile_policy(root)
    target = root / POLICY_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _stored_digest(text: str) -> str:
    for line in text.splitlines():
        if line.startswith(DIGEST_PREFIX):
            return line[len(DIGEST_PREFIX):].strip()
    return ""


def check_policy(
    source_dir: Path = DEFAULT_SOAR_DIR,
) -> RlModel:
    root = Path(source_dir)
    text, model = compile_policy(root)
    target = root / POLICY_NAME
    try:
        stored = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise SoarError(
            "нет сгенерированной RL-политики: %s. "
            "Запустите python -m campaign.cognition.rl_compiler --write"
            % target
        ) from exc
    if stored != text:
        raise SoarError(
            "RL-политика устарела: %s. Перегенерируйте --write" % target
        )
    if _stored_digest(stored) != model.digest():
        raise SoarError("source_digest RL-политики не совпадает")
    return model


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Компилятор RL-предпочтений из JSON в продукции Soar",
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--soar-dir", default=str(DEFAULT_SOAR_DIR))
    args = parser.parse_args(argv)
    if not args.write and not args.check:
        args.check = True
    root = Path(args.soar_dir)
    try:
        if args.write:
            target = write_policy(root)
            model = check_policy(root)
            print("RL-политика обновлена: %s" % target)
            print("  digest: %s" % model.digest()[:12])
        else:
            model = check_policy(root)
            print("RL-политика в порядке")
            print("  digest: %s" % model.digest()[:12])
    except SoarError as exc:
        print("ошибка: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COMPILER_VERSION",
    "DEFAULT_SOAR_DIR",
    "FORCE_VALUE",
    "MODEL_NAME",
    "MODEL_VERSION",
    "POLICY_NAME",
    "RlModel",
    "check_policy",
    "compile_policy",
    "load_model",
    "main",
    "model_from_dict",
    "render_policy",
    "write_policy",
]
