"""Компилятор логического вывода из JSON в продукции Soar.

JSON остаётся источником истины: правила живут в
``configs/dialogue/rules.json``, глубина вывода — в
``configs/dialogue/ontology.json``, настройки исполнения — в
``configs/soar/inference.json``. Сгенерированный
``configs/soar/inference.soar`` доказывает соответствие источникам
через ``source_digest``.

Soar строит прямое замыкание правил над фактами:

* Python кладёт факты в ``input-link`` как узлы ``^node``;
* каждая продукция сопоставляет посылки правила с узлами и создаёт
  новый узел с ``^rule``, ``^childN`` и ``^height``;
* отрицательные условия по ``^height`` не дают выводу уйти глубже
  ``max_depth``, поэтому циклы (например, ``war_symmetric``)
  обрываются;
* обратный порядок, дедупликация и отсечение повторных
  ``(правило, аргументы)`` на пути доказательства остаются в Python —
  это выборка из уже построенного замыкания, а не вывод.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .errors import SoarError
from .serialization import canonical_digest
from .soar_compiler import DEFAULT_SOAR_DIR, DIGEST_PREFIX

MODEL_VERSION = 1
INFERENCE_NAME = "inference.json"
POLICY_NAME = "inference.soar"
RULES_NAME = "rules.json"
ONTOLOGY_NAME = "ontology.json"
DEFAULT_DIALOGUE_DIR = (
    Path(__file__).resolve().parents[2] / "configs" / "dialogue"
)
DEFAULT_MAX_DEPTH = 32
MIN_RUN_CYCLES = 2
# Soar не принимает пустую строку как значение. Пустой аргумент
# (например, у предиката ``is_legitimate`` без цели) передаётся этим
# символом и разворачивается обратно при чтении ответа.
EMPTY_SYMBOL = "__ozverin_empty__"


def _integer(value: Any, name: str, *, minimum: Optional[int] = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise SoarError("%s должен быть целым" % name) from exc
    if minimum is not None and number < minimum:
        raise SoarError("%s должен быть >= %d" % (name, minimum))
    return number


def _quote(value: Any) -> str:
    """Символ Soar в форме ``|...|``.

    Soar этой сборки не принимает двойные кавычки ни в условиях, ни в
    действиях, поэтому все идентификаторы передаются символьным
    литералом.
    """

    text = str(value or "")
    if not text or "|" in text or "\n" in text or "\r" in text:
        raise SoarError("недопустимый символ Soar: %r" % (text,))
    return "|%s|" % text


@dataclass(frozen=True)
class InferenceModel:
    """Проверенная модель исполнения вывода."""

    version: int = MODEL_VERSION
    run_cycles: int = MIN_RUN_CYCLES
    timeout_ms: int = 5000
    node_limit: int = 20000

    def __post_init__(self):
        if self.version != MODEL_VERSION:
            raise SoarError(
                "версия модели вывода %r не поддерживается" % (self.version,)
            )
        if self.run_cycles < MIN_RUN_CYCLES:
            raise SoarError(
                "runtime.run_cycles должен быть >= %d" % MIN_RUN_CYCLES
            )
        if self.timeout_ms < 0:
            raise SoarError("runtime.timeout_ms должен быть >= 0")
        if self.node_limit < 1:
            raise SoarError("runtime.node_limit должен быть >= 1")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "runtime": {
                "run_cycles": self.run_cycles,
                "timeout_ms": self.timeout_ms,
                "node_limit": self.node_limit,
            },
        }

    def digest(self) -> str:
        return canonical_digest(self.to_dict())

    def commands(self) -> Tuple[str, ...]:
        """Команды Soar, достаточные для замыкания правил."""

        return ("soar max-elaborations 1000",)


def model_from_dict(data: Mapping[str, Any]) -> InferenceModel:
    runtime = data.get("runtime") or {}
    if not isinstance(runtime, Mapping):
        raise SoarError("runtime должен быть объектом")
    return InferenceModel(
        version=_integer(data.get("version", MODEL_VERSION), "version"),
        run_cycles=_integer(
            runtime.get("run_cycles", MIN_RUN_CYCLES),
            "runtime.run_cycles",
            minimum=MIN_RUN_CYCLES,
        ),
        timeout_ms=_integer(
            runtime.get("timeout_ms", 5000),
            "runtime.timeout_ms",
            minimum=0,
        ),
        node_limit=_integer(
            runtime.get("node_limit", 20000),
            "runtime.node_limit",
            minimum=1,
        ),
    )


def load_model(path: Optional[Path] = None) -> InferenceModel:
    source = Path(path) if path else DEFAULT_SOAR_DIR / INFERENCE_NAME
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SoarError("не удалось прочитать %s" % source) from exc
    except ValueError as exc:
        raise SoarError("%s не является JSON" % source) from exc
    if not isinstance(data, Mapping):
        raise SoarError("%s должен содержать объект" % source)
    return model_from_dict(data)


@dataclass(frozen=True)
class _Atom:
    rel: str
    args: Tuple[str, ...]


@dataclass(frozen=True)
class _Rule:
    id: str
    head: _Atom
    premises: Tuple[_Atom, ...]
    priority: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "priority": self.priority,
            "head": {"rel": self.head.rel, "args": list(self.head.args)},
            "premises": [
                {"rel": premise.rel, "args": list(premise.args)}
                for premise in self.premises
            ],
        }


def _atom(value: Any, name: str) -> _Atom:
    if not isinstance(value, Mapping):
        raise SoarError("%s должен быть объектом" % name)
    rel = str(value.get("rel") or "").strip()
    if not rel:
        raise SoarError("%s.rel не может быть пустым" % name)
    args: List[str] = []
    for item in value.get("args") or ():
        args.append(str(item or ""))
    return _Atom(rel, tuple(args))


def _variables(atom: _Atom) -> List[str]:
    return [arg for arg in atom.args if arg.startswith("$")]


def _load_rules(path: Path) -> List[_Rule]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SoarError("не удалось прочитать %s" % path) from exc
    except ValueError as exc:
        raise SoarError("%s не является JSON" % path) from exc
    if not isinstance(raw, Mapping):
        raise SoarError("%s должен содержать объект" % path)
    rules: List[_Rule] = []
    seen = set()
    for index, item in enumerate(raw.get("rules") or ()):
        if not isinstance(item, Mapping):
            raise SoarError("rules[%d] должен быть объектом" % index)
        rule_id = str(item.get("id") or "").strip()
        if not rule_id:
            raise SoarError("rules[%d].id не может быть пустым" % index)
        if rule_id in seen:
            raise SoarError("правило %r повторяется" % rule_id)
        seen.add(rule_id)
        head = _atom(item.get("head"), "rules[%d].head" % index)
        premises = tuple(
            _atom(premise, "rules[%d].premises[%d]" % (index, number))
            for number, premise in enumerate(item.get("premises") or ())
        )
        if not premises:
            raise SoarError(
                "правило %r без посылок не поддерживается" % rule_id
            )
        head_vars = set(_variables(head))
        premise_vars = set()
        for premise in premises:
            premise_vars.update(_variables(premise))
        missing = sorted(head_vars - premise_vars)
        if missing:
            raise SoarError(
                "правило %r: переменные головы не связаны посылками: %s"
                % (rule_id, ", ".join(missing))
            )
        rules.append(
            _Rule(
                id=rule_id,
                head=head,
                premises=premises,
                priority=_integer(
                    item.get("priority", 0),
                    "rules[%d].priority" % index,
                ),
            )
        )
    if not rules:
        raise SoarError("в %s нет правил" % path)
    rules.sort(key=lambda rule: (-rule.priority, rule.id))
    return rules


def _max_depth(path: Path) -> int:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SoarError("не удалось прочитать %s" % path) from exc
    except ValueError as exc:
        raise SoarError("%s не является JSON" % path) from exc
    if not isinstance(raw, Mapping):
        raise SoarError("%s должен содержать объект" % path)
    return _integer(
        raw.get("max_depth", DEFAULT_MAX_DEPTH),
        "%s.max_depth" % path.name,
        minimum=1,
    )


def load_sources(
    dialogue_dir: Optional[Path] = None,
) -> Tuple[List[_Rule], int]:
    root = Path(dialogue_dir) if dialogue_dir else DEFAULT_DIALOGUE_DIR
    rules = _load_rules(root / RULES_NAME)
    max_depth = _max_depth(root / ONTOLOGY_NAME)
    return rules, max_depth


def _production_name(rule_id: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]", "_", rule_id)
    return "infer*rule_%s" % (name or "rule")


def _var_names(rules: Sequence[_Rule]) -> Dict[str, str]:
    """Устойчивые имена переменных Soar без коллизий."""

    names: Dict[str, str] = {}
    used = set()
    for rule in rules:
        for atom in (rule.head,) + rule.premises:
            for variable in _variables(atom):
                if variable in names:
                    continue
                base = re.sub(
                    r"[^A-Za-z0-9_]", "_", variable.lstrip("$")
                )
                candidate = "v_%s" % (base or "x")
                counter = 1
                while candidate in used:
                    counter += 1
                    candidate = "v_%s_%d" % (base or "x", counter)
                used.add(candidate)
                names[variable] = candidate
    return names


def _constant(value: str) -> str:
    return _quote(EMPTY_SYMBOL if value == "" else value)


def _atom_pattern(
    identifier: str,
    atom: _Atom,
    height: str,
    variables: Mapping[str, str],
) -> str:
    parts = ["(<%s> ^rel %s" % (identifier, _quote(atom.rel))]
    for index, arg in enumerate(atom.args, 1):
        if arg.startswith("$"):
            parts.append("^arg%d <%s>" % (index, variables[arg]))
        else:
            parts.append("^arg%d %s" % (index, _constant(arg)))
    parts.append("^height <%s>)" % height)
    return " ".join(parts)


def _head_pattern(
    rule: _Rule,
    variables: Mapping[str, str],
) -> str:
    parts = [
        "(<d> ^kind derived ^rel %s" % _quote(rule.head.rel)
    ]
    for index, arg in enumerate(rule.head.args, 1):
        if arg.startswith("$"):
            parts.append("^arg%d <%s>" % (index, variables[arg]))
        else:
            parts.append("^arg%d %s" % (index, _constant(arg)))
    parts.append("^rule %s" % _quote(rule.id))
    for index in range(len(rule.premises)):
        parts.append("^child%d <p%d>" % (index + 1, index))
    heights = ["h%d" % index for index in range(len(rule.premises))]
    if len(heights) == 1:
        height = "(+ <h0> 1)"
    else:
        height = "(+ (max %s) 1)" % " ".join(
            "<%s>" % name for name in heights
        )
    parts.append("^height %s)" % height)
    return " ".join(parts)


def _render_rule(
    rule: _Rule,
    variables: Mapping[str, str],
    max_depth: int,
) -> str:
    conditions: List[str] = ["(state <s> ^io.input-link <il>)"]
    for index, premise in enumerate(rule.premises):
        identifier = "p%d" % index
        height = "h%d" % index
        conditions.append("(<il> ^node <%s>)" % identifier)
        conditions.append(
            _atom_pattern(identifier, premise, height, variables)
        )
        conditions.append(
            "-(<%s> ^height %d)" % (identifier, max_depth)
        )
    head = _head_pattern(rule, variables)
    lines = [
        "// %s: %s" % (
            rule.id,
            " & ".join(premise.rel for premise in rule.premises),
        ),
        "sp {%s" % _production_name(rule.id),
    ]
    lines.extend("   %s" % condition for condition in conditions)
    lines.append("-->")
    lines.append("   (<il> ^node <d>)")
    lines.append("   %s" % head)
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def source_digest(
    model: InferenceModel,
    rules: Sequence[_Rule],
    max_depth: int,
) -> str:
    return canonical_digest(
        {
            "model": model.to_dict(),
            "max_depth": max_depth,
            "rules": [rule.to_dict() for rule in rules],
        }
    )


def render_policy(
    model: InferenceModel,
    rules: Sequence[_Rule],
    max_depth: int,
) -> str:
    """Отрисовать продукции Soar для прямого замыкания правил."""

    variables = _var_names(rules)
    lines: List[str] = [
        "// Сгенерировано campaign.cognition.inference_compiler.",
        "// Не редактировать вручную: источники — rules.json,",
        "// configs/dialogue/ontology.json и configs/soar/inference.json.",
        "%s%s" % (
            DIGEST_PREFIX,
            source_digest(model, rules, max_depth),
        ),
        "",
    ]
    for rule in rules:
        lines.append(_render_rule(rule, variables, max_depth))
    lines.extend(
        [
            "// Все узлы замыкания (факты и выводы) уходят в output-link.",
            "sp {infer*export",
            "   (state <s> ^io.input-link <il> ^io.output-link <ol>)",
            "   (<il> ^node <n>)",
            "-->",
            "   (<ol> ^node <n>)",
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def compile_policy(
    source_dir: Path = DEFAULT_SOAR_DIR,
    dialogue_dir: Path = DEFAULT_DIALOGUE_DIR,
) -> Tuple[str, InferenceModel, int]:
    root = Path(source_dir)
    model = load_model(root / INFERENCE_NAME)
    rules, max_depth = load_sources(dialogue_dir)
    return render_policy(model, rules, max_depth), model, max_depth


def write_policy(
    source_dir: Path = DEFAULT_SOAR_DIR,
    dialogue_dir: Path = DEFAULT_DIALOGUE_DIR,
) -> Path:
    root = Path(source_dir)
    text, _model, _depth = compile_policy(root, dialogue_dir)
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
    dialogue_dir: Path = DEFAULT_DIALOGUE_DIR,
) -> InferenceModel:
    root = Path(source_dir)
    text, model, _max_depth = compile_policy(root, dialogue_dir)
    target = root / POLICY_NAME
    try:
        stored = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise SoarError(
            "нет сгенерированного вывода Soar: %s. "
            "Запустите python -m campaign.cognition.inference_compiler --write"
            % target
        ) from exc
    if stored != text:
        raise SoarError(
            "вывод Soar устарел: %s. Перегенерируйте --write" % target
        )
    if _stored_digest(stored) != _stored_digest(text):
        raise SoarError("source_digest вывода Soar не совпадает")
    return model


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Компилятор логического вывода из JSON в продукции Soar",
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--soar-dir", default=str(DEFAULT_SOAR_DIR))
    parser.add_argument(
        "--dialogue-dir", default=str(DEFAULT_DIALOGUE_DIR)
    )
    args = parser.parse_args(argv)
    if not args.write and not args.check:
        args.check = True
    root = Path(args.soar_dir)
    dialogue = Path(args.dialogue_dir)
    try:
        if args.write:
            target = write_policy(root, dialogue)
            model = check_policy(root, dialogue)
            print("вывод Soar обновлён: %s" % target)
            print("  digest: %s" % model.digest()[:12])
        else:
            model = check_policy(root, dialogue)
            print("вывод Soar в порядке")
            print("  digest: %s" % model.digest()[:12])
    except SoarError as exc:
        print("ошибка: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_DIALOGUE_DIR",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_SOAR_DIR",
    "EMPTY_SYMBOL",
    "INFERENCE_NAME",
    "InferenceModel",
    "MIN_RUN_CYCLES",
    "MODEL_VERSION",
    "ONTOLOGY_NAME",
    "POLICY_NAME",
    "RULES_NAME",
    "check_policy",
    "compile_policy",
    "load_model",
    "load_sources",
    "main",
    "model_from_dict",
    "render_policy",
    "source_digest",
    "write_policy",
]
