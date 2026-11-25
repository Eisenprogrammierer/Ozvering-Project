"""Планирование ответа и детерминированный синтез текста.

Планы, конструкции, поля описания и морфологические исключения живут в
JSON. Python только сопоставляет логическую форму с планом, доказывает
цель и передаёт смысл в композиционный реализатор.

D4 добавляет тип ответа ``social``.
D5.1 добавляет дискурсивный слой (ходы и связки).
D5.3 добавляет агрегацию (``mode: clause``), анафору внутри ответа и
порядок тема-рема. ``_discourse`` гарантированно снабжает ходы
``entities``, чтобы анафора работала даже если ``_build_moves``
вернул ходы без этого поля.
D3.1 добавляет тип ответа ``comparison``.
D3.2 добавляет тип ответа ``counterfactual``.
D5.4 добавляет порядок абзаца через ``topics: [...]``.
D6.2a добавляет отрицание (``negated: true``) в антецеденте
контрфакта: ``remove`` и ``add`` из плана меняются местами.
D6.3 добавляет политику раскрытия (``disclosure.json``) и
детерминированную ложь с трассировкой в ``Answer.data``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ..qualitative import metric_word, relation_word
from .counterfactual import CounterfactualEngine
from .inference import InferenceEngine, ProofStep, Solution, is_variable
from .knowledge import AgentKnowledge, Fact
from .model import DialogueCatalog, Persona, PlanSpec, StyleSpec
from .realize import ACT_FOR_KIND, Realizer, render_lines
from .social import SocialDecision, SocialEngine, social_bindings
from .style import StyleEngine


@dataclass(frozen=True)
class Answer:
    """Готовый ответ плюс объяснение и сработавший план."""

    kind: str
    text: str
    plan_id: str = ""
    proof: Tuple[ProofStep, ...] = ()
    data: Mapping[str, Any] = field(default_factory=dict)


def answer_handler_name(
    answer_type: str, answer_kinds: Mapping[str, Any]
) -> str:
    """Имя обработчика для ``answer.type`` по реестру.

    Реестр ``answer_kinds.json`` отделяет тип плана от Python-метода:
    новый тип может указать существующий generic-обработчик. Если типа
    нет в реестре, возвращается сам тип — тогда ``_plan`` либо найдёт
    старый метод, либо вернёт безопасное «не знаю».
    """

    kind = str(answer_type or "")
    kinds = (answer_kinds or {}).get("kinds") or {}
    spec = kinds.get(kind) if isinstance(kinds, Mapping) else None
    if isinstance(spec, Mapping):
        handler = str(spec.get("handler") or "").strip()
        if handler:
            return handler
    return kind


class PatternError(ValueError):
    """Некорректный шаблон вопроса в plans.json."""


def match_pattern(
    pattern: Any, value: Any, bindings: Optional[Dict[str, str]] = None
) -> Optional[Dict[str, str]]:
    result = dict(bindings or {})
    if isinstance(pattern, Mapping):
        if not isinstance(value, Mapping):
            return None
        for key, item in pattern.items():
            if key not in value:
                return None
            result = match_pattern(item, value[key], result)
            if result is None:
                return None
        return result
    if isinstance(pattern, list):
        if not isinstance(value, list) or len(pattern) != len(value):
            return None
        for item, actual in zip(pattern, value):
            result = match_pattern(item, actual, result)
            if result is None:
                return None
        return result
    if isinstance(pattern, str) and "$" in pattern:
        return _match_template(pattern, value, result)
    return result if pattern == value else None


def _match_template(
    pattern: str, value: Any, bindings: Dict[str, str]
) -> Optional[Dict[str, str]]:
    if not isinstance(value, str):
        return None
    pieces = pattern.split("$")
    names: List[str] = []
    regex = "^"
    for index, piece in enumerate(pieces):
        if index == 0:
            regex += re.escape(piece)
            continue
        match = re.match(r"([A-Za-z0-9_]+)", piece)
        if not match:
            return None
        name = match.group(1)
        names.append(name)
        regex += (
            "(?P<v%d>.+?)" % index
            if index < len(pieces) - 1
            else "(?P<v%d>.+)" % index
        )
        rest = piece[len(name):]
        regex += re.escape(rest)
    regex += "$"
    found = re.match(regex, value)
    if not found:
        return None
    result = dict(bindings)
    for index, name in enumerate(names, 1):
        actual = found.group("v%d" % index)
        key = "$" + name
        if key in result and result[key] != actual:
            return None
        result[key] = actual
    return result


def _resolve(template: str, bindings: Mapping[str, str]) -> str:
    def replace(found: re.Match) -> str:
        key = "$" + found.group(1)
        return str(bindings.get(key, found.group(0)))

    return re.sub(r"\$([A-Za-z0-9_]+)", replace, str(template))


def _resolve_args(
    args: Iterable[Any], bindings: Mapping[str, str]
) -> Tuple[str, ...]:
    return tuple(_resolve(str(item), bindings) for item in args)


def _format_number(value: Any) -> str:
    try:
        return "%.2f" % float(value)
    except (TypeError, ValueError):
        return str(value)


def _index(mapping: Mapping[str, Any], name: str, default: int) -> int:
    try:
        return int(mapping.get(name, default))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _scale_rank(scale: Any, value: Any) -> Optional[float]:
    """Позиция значения на упорядоченной шкале (низкая → высокая)."""

    token = str(value or "").strip().casefold()
    if not token:
        return None
    for rank, item in enumerate(scale or ()):
        if str(item or "").strip().casefold() == token:
            return float(rank)
    return None


def _fact_from(spec: Mapping[str, Any], values: Mapping[str, Any]) -> Fact:
    """Собрать ``Fact`` из описания в плане с подстановкой значений.

    ``values`` — захваты шаблона плюс служебные значения вроде
    ``$speaker`` и уже разрешённого ``$rel``. Имя отношения тоже может
    быть переменной: в контрфакте оно приходит из антецедента и
    резолвится через ``predicate_relations``.
    """

    rel = str(spec.get("rel") or "")
    if rel.startswith("$"):
        rel = str(values.get(rel, rel))
    raw_args = spec.get("args") or ()
    args = tuple(_resolve(str(item), values) for item in raw_args)
    return Fact(rel, args)


def _nested_entity(value: Any) -> str:
    """Найти сущность в логической форме (``np``/``pp``/``topic``).

    D6.2c/D6.2b: антецедент и следствие приходят как вложенные структуры
    разбора. Нам нужен только идентификатор сущности, чтобы передать его
    в ``CounterfactualEngine.compare``. Строка возвращается как есть,
    чтобы поддерживать и «плоские» семантические формы.
    """

    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _nested_entity(item)
            if found:
                return found
        return ""
    if isinstance(value, Mapping):
        for key in ("entity", "head", "object", "topic"):
            if key in value:
                found = _nested_entity(value[key])
                if found:
                    return found
        for item in value.values():
            found = _nested_entity(item)
            if found:
                return found
    return ""


def _capitalize(text: str) -> str:
    text = text[:1].upper() + text[1:] if text else text
    return text


def _text_key(text: Any) -> str:
    """Ключ сравнения ходов: без регистра, пунктуации и лишних пробелов."""

    cleaned = "".join(
        char if char.isalnum() else " "
        for char in str(text or "").casefold()
    )
    return " ".join(cleaned.split())
