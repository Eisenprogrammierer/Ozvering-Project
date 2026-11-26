"""Компилятор прагматики диалога из JSON в продукции Soar.

JSON остаётся источником истины. Настройки выбора живут в
``configs/soar/pragmatics.json``, политики раскрытия — в
``configs/dialogue/disclosure.json``. Сгенерированный
``configs/soar/pragmatics.soar`` доказывает соответствие источником
через ``source_digest``.

Soar выполняет три шага, каждый — отдельный оператор:

1. ``interpret-frame`` — фиксирует класс кадра (вопрос, приказ, ...);
2. ``select-plan`` — выбирает план ответа по приоритету и порядку
   каталога (tie-break как у легаси);
3. ``disclose`` — выбирает исход политики раскрытия D6.3.

Порядок шагов задан отрицательными условиями: следующий оператор
появляется только когда предыдущий результат ещё не записан. Поэтому
Soar проходит шаги сам, без внешнего сценария.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .errors import SoarError
from .serialization import canonical_digest
from .soar_compiler import (
    DEFAULT_SOAR_DIR,
    DIGEST_PREFIX,
    soar_number,
)

MODEL_VERSION = 1
PRAGMATICS_NAME = "pragmatics.json"
POLICY_NAME = "pragmatics.soar"
DEFAULT_DISCLOSURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "dialogue"
    / "disclosure.json"
)
DISCLOSURE_OUTCOMES = ("truth", "partial", "withhold", "evade", "lie")


def _number(value: Any, name: str, *, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SoarError("%s должен быть числом" % name) from exc
    if number < minimum:
        raise SoarError("%s должен быть >= %s" % (name, minimum))
    if not math.isfinite(number):
        raise SoarError("%s должен быть конечным числом" % name)
    return number


def _quote(value: Any) -> str:
    """Символ Soar в форме ``|...|``.

    Soar этого сборки не принимает двойные кавычки ни в условиях, ни в
    действиях («Illegal value for RHS value»), поэтому идентификаторы
    политик и исходов передаются символьным литералом.
    """

    text = str(value or "")
    if not text or "|" in text or "\n" in text:
        raise SoarError("недопустимый символ Soar: %r" % (text,))
    return "|%s|" % text


@dataclass(frozen=True)
class PragmaticsModel:
    """Проверенная модель прагматики."""

    tie_epsilon: float = 1e-9
    decision_cycles: int = 6
    version: int = MODEL_VERSION

    def __post_init__(self):
        if self.version != MODEL_VERSION:
            raise SoarError(
                "версия модели прагматики %r не поддерживается"
                % (self.version,)
            )
        if not math.isfinite(self.tie_epsilon) or self.tie_epsilon < 0.0:
            raise SoarError("selection.tie_epsilon должен быть >= 0")
        if self.decision_cycles < 1:
            raise SoarError("selection.decision_cycles должен быть >= 1")

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "selection": {
                "tie_epsilon": self.tie_epsilon,
                "decision_cycles": self.decision_cycles,
            },
        }

    def digest(self) -> str:
        return canonical_digest(self.to_dict())

    def commands(self) -> Tuple[str, ...]:
        """Команды Soar: строгий argmax и детерминированный seed."""

        return (
            "decide numeric-indifferent-mode --sum",
            "decide indifferent-selection --epsilon-greedy",
            "decide indifferent-selection --epsilon 0",
            "decide set-random-seed 0",
        )


def model_from_dict(data: Mapping[str, Any]) -> PragmaticsModel:
    selection = data.get("selection")
    if selection is None:
        selection = {}
    if not isinstance(selection, Mapping):
        raise SoarError("selection должен быть объектом")
    try:
        version = int(data.get("version", MODEL_VERSION))
        cycles = int(selection.get("decision_cycles", 6))
    except (TypeError, ValueError) as exc:
        raise SoarError(
            "version/decision_cycles должны быть целыми"
        ) from exc
    return PragmaticsModel(
        tie_epsilon=_number(
            selection.get("tie_epsilon", 1e-9), "tie_epsilon"
        ),
        decision_cycles=cycles,
        version=version,
    )


def load_model(
    path: Optional[Path] = None,
) -> PragmaticsModel:
    source = Path(path) if path else DEFAULT_SOAR_DIR / PRAGMATICS_NAME
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SoarError("не удалось прочитать %s" % source) from exc
    except ValueError as exc:
        raise SoarError("%s не является JSON" % source) from exc
    if not isinstance(data, Mapping):
        raise SoarError("%s должен содержать объект" % source)
    return model_from_dict(data)


def load_disclosure(
    path: Optional[Path] = None,
) -> Mapping[str, Any]:
    source = Path(path) if path else DEFAULT_DISCLOSURE_PATH
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SoarError(
            "не удалось прочитать политики раскрытия: %s" % source
        ) from exc
    except ValueError as exc:
        raise SoarError("%s не является JSON" % source) from exc
    if not isinstance(data, Mapping):
        raise SoarError("%s должен содержать объект" % source)
    return data


def _policies(disclosure: Mapping[str, Any]) -> Mapping[str, Any]:
    policies = disclosure.get("policies")
    if policies is None:
        return {}
    if not isinstance(policies, Mapping):
        raise SoarError("disclosure.policies должен быть объектом")
    return policies


def _check_outcome(value: Any, policy_id: str) -> str:
    outcome = str(value or "truth")
    if outcome not in DISCLOSURE_OUTCOMES:
        raise SoarError(
            "политика раскрытия %r: исход %r не поддерживается"
            % (policy_id, outcome)
        )
    return outcome


def _disclosure_rules(disclosure: Mapping[str, Any]) -> List[str]:
    lines: List[str] = []
    policies = _policies(disclosure)
    known = sorted(str(key) for key in policies)
    for index, policy_id in enumerate(known):
        policy = policies[policy_id]
        if not isinstance(policy, Mapping):
            raise SoarError(
                "политика раскрытия %r должна быть объектом" % policy_id
            )
        outcome = _check_outcome(policy.get("outcome"), policy_id)
        name = "pragmatics*disclose-%d" % index
        if outcome == "lie":
            # Для лжи решение зависит от детерминированного броска:
            # score < probability — ложь, иначе правда. Python передаёт
            # готовый флаг ``lie``, чтобы Soar не сравнивал числа.
            for suffix, flag, result in (
                ("yes", "yes", "lie"),
                ("no", "no", "truth"),
            ):
                lines.extend(
                    [
                        "// Ложь: %s." % suffix,
                        "sp {%s-lie-%s" % (name, suffix),
                        "   (state <s> ^plan <pid> ^io.input-link <il>)",
                        "   (<s> -^disclosure *)",
                        "   (<il> ^disclosure <d>)",
                        "   (<d> ^policy %s ^lie %s)"
                        % (_quote(policy_id), _quote(flag)),
                        "-->",
                        "   (<s> ^operator <o> +)",
                        "   (<o> ^name disclose ^outcome %s ^policy %s)"
                        % (_quote(result), _quote(policy_id)),
                        "}",
                        "",
                    ]
                )
            continue
        lines.extend(
            [
                "// Политика раскрытия: %s." % policy_id,
                "sp {%s" % name,
                "   (state <s> ^plan <pid> ^io.input-link <il>)",
                "   (<s> -^disclosure *)",
                "   (<il> ^disclosure <d>)",
                "   (<d> ^policy %s ^lie <lie>)" % _quote(policy_id),
                "-->",
                "   (<s> ^operator <o> +)",
                "   (<o> ^name disclose ^outcome %s ^policy %s)"
                % (_quote(outcome), _quote(policy_id)),
                "}",
                "",
            ]
        )
    # Безопасное умолчание срабатывает только для политик вне каталога:
    # у узла раскрытия ровно одно значение ``^policy``, поэтому
    # отрицательные проверки исключают все известные.
    fallback = [
        "// Неизвестная политика: безопасное умолчание — правда.",
        "sp {pragmatics*disclose-fallback",
        "   (state <s> ^plan <pid> ^io.input-link <il>)",
        "   (<s> -^disclosure *)",
        "   (<il> ^disclosure <d>)",
        "   (<d> ^policy <p>)",
    ]
    fallback.extend(
        "   (<d> -^policy %s)" % _quote(policy_id)
        for policy_id in known
    )
    fallback.extend(
        [
            "-->",
            "   (<s> ^operator <o> +)",
            "   (<o> ^name disclose ^outcome |truth| ^policy <p>)",
            "}",
            "",
        ]
    )
    lines.extend(fallback)
    return lines


def render_policy(
    model: PragmaticsModel,
    disclosure: Mapping[str, Any],
) -> str:
    """Отрисовать продукции Soar для прагматики."""

    digest = canonical_digest(
        {"model": model.to_dict(), "disclosure": dict(disclosure)}
    )
    lines: List[str] = [
        "// Сгенерировано campaign.cognition.pragmatics_compiler.",
        "// Не редактировать вручную: источники — "
        "configs/soar/pragmatics.json и configs/dialogue/disclosure.json.",
        "%s%s" % (DIGEST_PREFIX, digest),
        "",
        "// Шаг 1: класс кадра.",
        "sp {pragmatics*interpret",
        "   (state <s> ^io.input-link <il>)",
        "   (<s> -^intent <x>)",
        "   (<il> ^frame <f>)",
        "   (<f> ^kind <kind>)",
        "-->",
        "   (<s> ^operator <o> +)",
        "   (<o> ^name interpret-frame ^intent <kind>)",
        "}",
        "",
        "sp {pragmatics*apply-intent",
        "   (state <s> ^operator <o> ^io.output-link <ol>)",
        "   (<o> ^name interpret-frame ^intent <kind>)",
        "-->",
        "   (<s> ^intent <kind>)",
        "   (<ol> ^trace-intent <kind>)",
        "}",
        "",
        "// Шаг 2: план ответа. Приоритет важнее порядка каталога,",
        "// порядок — tie-break, как в легаси.",
        "sp {pragmatics*select-plan",
        "   (state <s> ^intent <kind> ^io.input-link <il>)",
        "   (<s> -^plan <x>)",
        "   (<il> ^plan <p>)",
        "   (<p> ^id <id> ^priority <prio> ^rank <rank>)",
        "-->",
        "   (<s> ^operator <o> + = "
        "(- <prio> (* <rank> %s)))" % soar_number(model.tie_epsilon),
        "   (<o> ^name select-plan ^plan <id>)",
        "}",
        "",
        "sp {pragmatics*apply-plan",
        "   (state <s> ^operator <o> ^io.output-link <ol>)",
        "   (<o> ^name select-plan ^plan <id>)",
        "-->",
        "   (<s> ^plan <id>)",
        "   (<ol> ^trace-plan <id>)",
        "}",
        "",
        "// Шаг 3: политика раскрытия D6.3.",
    ]
    lines.extend(_disclosure_rules(disclosure))
    lines.extend(
        [
            "sp {pragmatics*apply-disclosure",
            "   (state <s> ^operator <o> ^io.output-link <ol>)",
            "   (<o> ^name disclose ^outcome <outcome> ^policy <p>)",
            "-->",
            "   (<s> ^disclosure <outcome>)",
            "   (<ol> ^trace-policy <p>)",
            "   (<ol> ^trace-outcome <outcome>)",
            "}",
            "",
            "// Итог уходит в output-link.",
            "sp {pragmatics*output",
            "   (state <s> ^io.output-link <ol>)",
            "   (<s> ^intent <kind> ^plan <pid> ^disclosure <outcome>)",
            "-->",
            "   (<ol> ^intent <kind>)",
            "   (<ol> ^decision <pid>)",
            "   (<ol> ^disclosure <outcome>)",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def compile_policy(
    source_dir: Path = DEFAULT_SOAR_DIR,
    disclosure_path: Optional[Path] = None,
) -> Tuple[str, PragmaticsModel, Mapping[str, Any]]:
    root = Path(source_dir)
    model = load_model(root / PRAGMATICS_NAME)
    disclosure = load_disclosure(disclosure_path)
    return render_policy(model, disclosure), model, disclosure


def write_policy(
    source_dir: Path = DEFAULT_SOAR_DIR,
    disclosure_path: Optional[Path] = None,
) -> Path:
    root = Path(source_dir)
    text, _model, _disclosure = compile_policy(root, disclosure_path)
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
    disclosure_path: Optional[Path] = None,
) -> PragmaticsModel:
    root = Path(source_dir)
    text, model, disclosure = compile_policy(root, disclosure_path)
    target = root / POLICY_NAME
    try:
        stored = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise SoarError(
            "нет сгенерированной прагматики Soar: %s. "
            "Запустите python -m campaign.cognition.pragmatics_compiler "
            "--write" % target
        ) from exc
    if stored != text:
        raise SoarError(
            "прагматика Soar устарела: %s. Перегенерируйте --write"
            % target
        )
    expected = canonical_digest(
        {"model": model.to_dict(), "disclosure": dict(disclosure)}
    )
    if _stored_digest(stored) != expected:
        raise SoarError("source_digest прагматики Soar не совпадает")
    return model


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Компилятор прагматики диалога из JSON в Soar",
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--soar-dir", default=str(DEFAULT_SOAR_DIR))
    parser.add_argument(
        "--disclosure", default=str(DEFAULT_DISCLOSURE_PATH)
    )
    args = parser.parse_args(argv)
    if not args.write and not args.check:
        args.check = True
    root = Path(args.soar_dir)
    try:
        if args.write:
            target = write_policy(root, Path(args.disclosure))
            check_policy(root, Path(args.disclosure))
            print("прагматика Soar обновлена: %s" % target)
        else:
            check_policy(root, Path(args.disclosure))
            print("прагматика Soar в порядке")
    except SoarError as exc:
        print("ошибка: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_DISCLOSURE_PATH",
    "DISCLOSURE_OUTCOMES",
    "MODEL_VERSION",
    "POLICY_NAME",
    "PRAGMATICS_NAME",
    "PragmaticsModel",
    "check_policy",
    "compile_policy",
    "load_disclosure",
    "load_model",
    "main",
    "model_from_dict",
    "render_policy",
    "write_policy",
]
