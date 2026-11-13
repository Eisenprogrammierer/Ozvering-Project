"""Отчёт покрытия стилей речевыми актами и лексемами.

Модуль нужен для ремонтопригодности: при добавлении стиля видно, какие
акты получают собственный маркер, а какие молча откатываются к
нейтральному. Это не ранжирование и не статистика — только проверка
совместимости признаков.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .features import select_best
from .style import StyleEngine

CORE_ACTS = (
    "confirm",
    "deny",
    "unknown",
    "clarify",
    "list",
    "value",
)


@dataclass(frozen=True)
class CoverageIssue:
    """Один случай, требующий внимания автора стиля."""

    style: str
    act: str
    kind: str
    chosen: str
    detail: str


def _catalog_markers(synthesis: Mapping[str, Any]) -> List[Dict[str, Any]]:
    result = []
    for key, value in (synthesis.get("markers") or {}).items():
        if not isinstance(value, Mapping):
            continue
        item = dict(value)
        item.setdefault("id", str(key))
        result.append(item)
    return result


def _act_constructions(
    synthesis: Mapping[str, Any], act: str
) -> List[Dict[str, Any]]:
    result = []
    for key, value in (synthesis.get("constructions") or {}).items():
        if not isinstance(value, Mapping):
            continue
        if str(value.get("act") or "") != str(act):
            continue
        item = dict(value)
        item.setdefault("id", str(key))
        result.append(item)
    return result


def _marker_concepts(parts: Iterable[Any]) -> Sequence[str]:
    result = []
    for part in parts or ():
        if not isinstance(part, Mapping):
            continue
        if str(part.get("kind") or "") == "marker":
            concept = str(part.get("concept") or "")
            if concept:
                result.append(concept)
    return tuple(result)


def _is_fallback(chosen: Mapping[str, Any]) -> bool:
    return not bool(chosen.get("features"))


def style_coverage(catalog: Any) -> List[CoverageIssue]:
    """Проверить, покрыты ли основные акты для каждого стиля."""

    synthesis = getattr(catalog, "synthesis", {}) or {}
    markers = _catalog_markers(synthesis)
    styles = getattr(catalog, "styles", None)
    issues: List[CoverageIssue] = []
    if styles is None:
        return issues
    lexical_groups = synthesis.get("lexical_groups") or {}
    address_ids = set(lexical_groups.get("address") or ())
    entries = {
        entry.id: entry for entry in getattr(catalog, "lexicon", ()) or ()
    }
    address_entries = [
        entries[key] for key in address_ids if key in entries
    ]
    for style in styles.styles.values():
        features = StyleEngine.features(style)
        allow = bool(style.selection.get("allow_fallback"))
        non_neutral = style.register not in ("", "neutral")
        for act in CORE_ACTS:
            candidates = _act_constructions(synthesis, act)
            construction = select_best(candidates, features)
            if construction is None:
                if non_neutral and not allow:
                    issues.append(
                        CoverageIssue(
                            style.id,
                            act,
                            "act",
                            "",
                            "нет совместимой конструкции акта",
                        )
                    )
                continue
            for concept in _marker_concepts(
                construction.get("parts") or ()
            ):
                pool = [
                    item
                    for item in markers
                    if str(item.get("concept") or "")
                    == concept
                    or str(item.get("id") or "").startswith(
                        "marker:%s_" % concept
                    )
                ]
                chosen = select_best(pool, features)
                if chosen is None:
                    if non_neutral and not allow:
                        issues.append(
                            CoverageIssue(
                                style.id,
                                act,
                                "marker",
                                "",
                                "нет маркера для концепта %s" % concept,
                            )
                        )
                    continue
                if (
                    non_neutral
                    and not allow
                    and _is_fallback(chosen)
                ):
                    issues.append(
                        CoverageIssue(
                            style.id,
                            act,
                            "marker-fallback",
                            str(chosen.get("id") or ""),
                            "выбран нейтральный маркер",
                        )
                    )
        mode = style.feature("address_mode", "none")
        if mode != "none" and non_neutral:
            for gender in ("m", "f"):
                pool = [
                    entry
                    for entry in address_entries
                    if str(entry.features.get("gender") or "") == gender
                ]
                chosen = select_best(pool, features)
                if chosen is None and not allow:
                    issues.append(
                        CoverageIssue(
                            style.id,
                            "address",
                            "address",
                            "",
                            "нет обращения для пола %s" % gender,
                        )
                    )
    return issues
