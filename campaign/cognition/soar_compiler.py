"""Компилятор решения NPC из JSON в продукции Soar.

JSON остаётся источником истины: формула оценки, пороги и настройки
выбора живут в ``configs/soar/decision.json``, а ``npc_policy.soar`` —
сгенерированный артефакт с ``source_digest``. ``--check`` доказывает,
что артефакт не разошёлся с источником.

Формула повторяет ``NeedPolicy.score``::

    score = max(score_floor, base * max(factor_floor, 1 + weight * need))

и добавляет ``rank * tie_epsilon``. Ранг — позиция id в
лексикографическом порядке: так Soar воспроизводит tie-break легаси
(``max((score, option_id))``) без сравнения строк в продукции.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

from .errors import SoarError
from .serialization import canonical_digest

COMPILER_VERSION = 1
MODEL_VERSION = 1
DEFAULT_SOAR_DIR = Path(__file__).resolve().parents[2] / "configs" / "soar"
DECISION_NAME = "decision.json"
POLICY_NAME = "npc_policy.soar"
DIGEST_PREFIX = "// source_digest: "
SELECTION_POLICIES = (
    "epsilon-greedy",
    "softmax",
    "boltzmann",
    "first",
    "last",
)
NUMERIC_MODES = ("sum", "avg")


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SoarError("%s должен быть числом" % name) from exc
    if number < minimum:
        raise SoarError("%s должен быть >= %s" % (name, minimum))
    return number


def soar_number(value: float) -> str:
    """Число в десятичной записи: Soar не понимает ``1e-9``."""

    text = "%.12f" % float(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True)
class DecisionModel:
    """Проверенная модель выбора работы."""

    score_floor: float = 0.01
    factor_floor: float = 0.05
    tie_epsilon: float = 1e-12
    selection_policy: str = "epsilon-greedy"
    numeric_mode: str = "sum"
    epsilon: float = 0.0
    random_seed: int = 0
    decision_cycles: int = 3
    version: int = MODEL_VERSION

    def __post_init__(self):
        if self.version != MODEL_VERSION:
            raise SoarError(
                "версия модели решения %r не поддерживается" % (self.version,)
            )
        if self.selection_policy not in SELECTION_POLICIES:
            raise SoarError(
                "selection.policy=%r не поддерживается; допустимо: %s"
                % (self.selection_policy, ", ".join(SELECTION_POLICIES))
            )
        if self.numeric_mode not in NUMERIC_MODES:
            raise SoarError(
                "selection.numeric_mode=%r не поддерживается" % (
                    self.numeric_mode,
                )
            )
        if not 0.0 <= self.epsilon <= 1.0:
            raise SoarError("selection.epsilon вне [0, 1]")
        if self.decision_cycles < 1:
            raise SoarError("selection.decision_cycles должен быть >= 1")

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "formula": {
                "score_floor": self.score_floor,
                "factor_floor": self.factor_floor,
                "tie_epsilon": self.tie_epsilon,
            },
            "selection": {
                "policy": self.selection_policy,
                "numeric_mode": self.numeric_mode,
                "epsilon": self.epsilon,
                "random_seed": self.random_seed,
                "decision_cycles": self.decision_cycles,
            },
        }

    def digest(self) -> str:
        return canonical_digest(self.to_dict())

    def commands(self) -> Tuple[str, ...]:
        """Команды Soar, включающие детерминированный выбор."""

        mode = "--sum" if self.numeric_mode == "sum" else "--avg"
        return (
            "decide numeric-indifferent-mode %s" % mode,
            "decide indifferent-selection --%s" % self.selection_policy,
            "decide indifferent-selection --epsilon %s"
            % soar_number(self.epsilon),
            "decide set-random-seed %d" % self.random_seed,
        )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SoarError("%s должен быть объектом" % name)
    return value


def model_from_dict(data: Mapping[str, Any]) -> DecisionModel:
    formula = _mapping(data.get("formula"), "formula")
    selection = _mapping(data.get("selection"), "selection")
    try:
        version = int(data.get("version", MODEL_VERSION))
        seed = int(selection.get("random_seed", 0))
        cycles = int(selection.get("decision_cycles", 3))
    except (TypeError, ValueError) as exc:
        raise SoarError(
            "version/random_seed/decision_cycles должны быть целыми"
        ) from exc
    return DecisionModel(
        score_floor=_number(formula.get("score_floor", 0.01), "score_floor"),
        factor_floor=_number(
            formula.get("factor_floor", 0.05), "factor_floor"
        ),
        tie_epsilon=_number(
            formula.get("tie_epsilon", 1e-12), "tie_epsilon"
        ),
        selection_policy=str(selection.get("policy") or "epsilon-greedy"),
        numeric_mode=str(selection.get("numeric_mode") or "sum"),
        epsilon=_number(selection.get("epsilon", 0.0), "epsilon"),
        random_seed=seed,
        decision_cycles=cycles,
        version=version,
    )


def load_model(
    path: Optional[Path] = None,
) -> DecisionModel:
    source = Path(path) if path else DEFAULT_SOAR_DIR / DECISION_NAME
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SoarError("не удалось прочитать %s" % source) from exc
    except ValueError as exc:
        raise SoarError("%s не является JSON" % source) from exc
    if not isinstance(data, Mapping):
        raise SoarError("%s должен содержать объект" % source)
    return model_from_dict(data)


def render_policy(model: DecisionModel) -> str:
    """Отрисовать продукции Soar для модели решения."""

    score = (
        "(+ (max %s (* <b> (max %s (+ 1 (* <w> <v>))))) (* <r> %s))"
        % (
            soar_number(model.score_floor),
            soar_number(model.factor_floor),
            soar_number(model.tie_epsilon),
        )
    )
    lines: List[str] = [
        "// Сгенерировано campaign.cognition.soar_compiler.",
        "// Не редактировать вручную: источник — configs/soar/decision.json.",
        "%s%s" % (DIGEST_PREFIX, model.digest()),
        "",
        "// Кандидат: option, base, weight, need, rank.",
        "sp {npc*propose",
        "   (state <s> ^io.input-link <il>)",
        "   (<il> ^candidate <c>)",
        "   (<c> ^option <oid> ^base <b> ^weight <w> ^need <v> ^rank <r>)",
        "-->",
        "   (<s> ^operator <o> + = %s)" % score,
        "   (<o> ^option <oid>)",
        "}",
        "",
        "// Выбранный оператор уходит в output-link.",
        "sp {npc*apply",
        "   (state <s> ^operator <o> ^io.output-link <ol>)",
        "   (<o> ^option <oid>)",
        "-->",
        "   (<ol> ^decision <oid>)",
        "}",
        "",
    ]
    return "\n".join(lines)


def compile_policy(
    source_dir: Path = DEFAULT_SOAR_DIR,
) -> Tuple[str, DecisionModel]:
    root = Path(source_dir)
    model = load_model(root / DECISION_NAME)
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


def check_policy(source_dir: Path = DEFAULT_SOAR_DIR) -> DecisionModel:
    root = Path(source_dir)
    text, model = compile_policy(root)
    target = root / POLICY_NAME
    try:
        stored = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise SoarError(
            "нет сгенерированной политики Soar: %s. "
            "Запустите python -m campaign.cognition.soar_compiler --write"
            % target
        ) from exc
    if stored != text:
        raise SoarError(
            "политика Soar устарела: %s. Перегенерируйте --write" % target
        )
    if _stored_digest(stored) != model.digest():
        raise SoarError("source_digest политики Soar не совпадает")
    return model


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Компилятор решений NPC из JSON в продукции Soar",
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
            print("политика Soar обновлена: %s" % target)
            print("  digest: %s" % model.digest()[:12])
        else:
            model = check_policy(root)
            print("политика Soar в порядке")
            print("  digest: %s" % model.digest()[:12])
    except SoarError as exc:
        print("ошибка: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "COMPILER_VERSION",
    "DECISION_NAME",
    "DEFAULT_SOAR_DIR",
    "DIGEST_PREFIX",
    "DecisionModel",
    "MODEL_VERSION",
    "POLICY_NAME",
    "check_policy",
    "compile_policy",
    "load_model",
    "main",
    "model_from_dict",
    "render_policy",
    "soar_number",
    "write_policy",
]
