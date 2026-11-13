"""Признаки и детерминированное сопоставление конструкций.

Стиль в этой архитектуре — не список фраз, а набор признаков:
формальность, дистанция, авторитет, аффект, прямота, номинализация.
Конструкции и лексемы объявляют, с какими значениями признаков они
совместимы. Реализатор выбирает самую конкретную совместимую единицу.

Сопоставление не вероятностное: это проверка ограничений и подсчёт
числа совпавших признаков. Никакой статистики.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def _values(value: Any) -> tuple:
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value)
    return (str(value),)


def match_score(
    constraints: Mapping[str, Any] | None,
    features: Mapping[str, Any],
) -> int:
    """Вернуть число совпавших признаков или ``-1`` при несовместимости."""

    if not constraints:
        return 0
    score = 0
    for name, allowed in constraints.items():
        key = str(name)
        if key not in features:
            return -1
        actual = str(features.get(key) or "")
        expected = _values(allowed)
        if actual not in expected:
            return -1
        score += 1
    return score


def compatible(
    constraints: Mapping[str, Any] | None,
    features: Mapping[str, Any],
) -> bool:
    return match_score(constraints, features) >= 0


def select_best(
    candidates: Iterable[Any],
    features: Mapping[str, Any],
    *,
    recent: Iterable[str] = (),
    avoid: int = 0,
) -> Any:
    """Выбрать самую конкретную совместимую единицу.

    Порядок: сначала отбрасываются несовместимые, затем недавние (если
    остаются альтернативы), затем сортировка по числу совпавших
    признаков и приоритету; при равенстве сохраняется порядок данных.
    """

    items = list(candidates)
    scored = []
    for index, item in enumerate(items):
        constraints = getattr(item, "features", None)
        if constraints is None and isinstance(item, Mapping):
            constraints = item.get("features")
        score = match_score(constraints, features)
        if score >= 0:
            scored.append((score, index, item))
    if not scored:
        return None
    recent = [str(value) for value in recent]
    if avoid and recent:
        blocked = set(recent[-avoid:])
        filtered = [
            row for row in scored if _candidate_id(row[2]) not in blocked
        ]
        if filtered:
            scored = filtered

    def priority(item: Any) -> int:
        if isinstance(item, Mapping):
            value = item.get("priority")
        else:
            value = getattr(item, "priority", None)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    scored.sort(key=lambda row: (-row[0], -priority(row[2]), row[1]))
    return scored[0][2]


def _candidate_id(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("id") or "")
    return str(getattr(item, "id", "") or "")


def filter_compatible(
    candidates: Iterable[Any], features: Mapping[str, Any]
) -> list:
    result = []
    for item in candidates:
        constraints = getattr(item, "features", None)
        if constraints is None and isinstance(item, Mapping):
            constraints = item.get("features")
        if match_score(constraints, features) >= 0:
            result.append(item)
    return result
