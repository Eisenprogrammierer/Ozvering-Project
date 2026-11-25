"""Parity-метрики старого и нового NLU.

Сравнение идёт по смысловой части результата (``core``): интент,
речевой акт, предикат, аргументы, слоты и референты. Технические поля
(``id``, ``tokens``, ``evidence``) в exact-сравнение не входят, иначе
метрика измеряла бы форматирование, а не понимание.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from .errors import CognitionError
from .frame import Clarification, Rejection, UtteranceFrame
from .serialization import canonical_digest, canonical_json


def result_core(value: Any) -> Dict[str, Any]:
    """Смысловая часть любого результата понимания."""

    if isinstance(value, UtteranceFrame):
        return value.core()
    if isinstance(value, (Clarification, Rejection)):
        return value.core()
    if isinstance(value, Mapping):
        kind = str(value.get("kind") or "")
        if kind == "clarification":
            return {
                "kind": kind,
                "reason": str(value.get("reason") or ""),
                "options": list(value.get("options") or ()),
            }
        if kind == "rejection":
            return {
                "kind": kind,
                "reason": str(value.get("reason") or ""),
            }
        data = dict(value)
        data.pop("kind", None)
        if "intent" in data:
            return UtteranceFrame.from_dict(data).core()
    raise CognitionError(
        "результат %r не является кадром, уточнением или отказом"
        % (type(value).__name__,)
    )


def _intent(core: Mapping[str, Any]) -> str:
    if core.get("kind") == "frame":
        return str(core.get("intent") or "")
    return "__%s__" % core.get("kind")


def _slot_items(core: Mapping[str, Any]) -> set:
    slots = core.get("slots") or {}
    if not isinstance(slots, Mapping):
        return set()
    return {
        (str(key), canonical_json(value))
        for key, value in slots.items()
    }


def _as_pairs(values: Any) -> Dict[str, Any]:
    if isinstance(values, Mapping):
        return {str(key): item for key, item in values.items()}
    pairs: Dict[str, Any] = {}
    for item in values:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise CognitionError(
                "ожидалась пара (id, результат), получено %r" % (item,)
            )
        key, value = item
        pairs[str(key)] = value
    return pairs


@dataclass(frozen=True)
class ParityReport:
    """Сводка сравнения двух прогонов на одном корпусе."""

    total: int
    intent_accuracy: float
    slot_f1: float
    slot_precision: float
    slot_recall: float
    frame_exact: float
    fallback_rate: float
    clarification_rate: float
    determinism_match: bool
    legacy_digest: str
    candidate_digest: str
    mismatches: Tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "intent_accuracy": self.intent_accuracy,
            "slot_f1": self.slot_f1,
            "slot_precision": self.slot_precision,
            "slot_recall": self.slot_recall,
            "frame_exact": self.frame_exact,
            "fallback_rate": self.fallback_rate,
            "clarification_rate": self.clarification_rate,
            "determinism_match": self.determinism_match,
            "legacy_digest": self.legacy_digest,
            "candidate_digest": self.candidate_digest,
            "mismatches": [dict(item) for item in self.mismatches],
        }

    def render(self) -> str:
        lines = [
            "NLU parity: %d фраз" % self.total,
            "  intent_accuracy: %.3f" % self.intent_accuracy,
            "  slot_f1: %.3f (P=%.3f, R=%.3f)"
            % (self.slot_f1, self.slot_precision, self.slot_recall),
            "  frame_exact: %.3f" % self.frame_exact,
            "  fallback_rate: %.3f" % self.fallback_rate,
            "  clarification_rate: %.3f" % self.clarification_rate,
            "  determinism: %s" % ("ok" if self.determinism_match else "fail"),
        ]
        if self.mismatches:
            lines.append("  mismatches: %d" % len(self.mismatches))
            for item in self.mismatches[:10]:
                lines.append(
                    "    %s: %s != %s"
                    % (
                        item.get("id"),
                        item.get("legacy"),
                        item.get("candidate"),
                    )
                )
        return "\n".join(lines)


def compare(
    legacy: Any,
    candidate: Any,
) -> ParityReport:
    """Сравнить два набора результатов по общим id."""

    old = _as_pairs(legacy)
    new = _as_pairs(candidate)
    ids = sorted(set(old) | set(new))
    if not ids:
        raise CognitionError("нечего сравнивать: корпус пуст")
    intent_hits = 0
    exact_hits = 0
    fallbacks = 0
    clarifications = 0
    true_positive = 0
    false_positive = 0
    false_negative = 0
    mismatches: List[Mapping[str, Any]] = []
    old_cores = {}
    new_cores = {}
    for key in ids:
        if key not in old or key not in new:
            mismatches.append(
                {
                    "id": key,
                    "legacy": "missing" if key not in old else "present",
                    "candidate": (
                        "missing" if key not in new else "present"
                    ),
                }
            )
            continue
        old_core = result_core(old[key])
        new_core = result_core(new[key])
        old_cores[key] = old_core
        new_cores[key] = new_core
        if _intent(old_core) == _intent(new_core):
            intent_hits += 1
        if old_core == new_core:
            exact_hits += 1
        else:
            mismatches.append(
                {
                    "id": key,
                    "legacy": _intent(old_core),
                    "candidate": _intent(new_core),
                }
            )
        if new_core.get("kind") == "rejection":
            fallbacks += 1
        if new_core.get("kind") == "clarification":
            clarifications += 1
        old_slots = _slot_items(old_core)
        new_slots = _slot_items(new_core)
        true_positive += len(old_slots & new_slots)
        false_positive += len(new_slots - old_slots)
        false_negative += len(old_slots - new_slots)
    total = len(ids)
    precision = (
        true_positive / float(true_positive + false_positive)
        if true_positive + false_positive
        else 1.0
    )
    recall = (
        true_positive / float(true_positive + false_negative)
        if true_positive + false_negative
        else 1.0
    )
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    legacy_digest = canonical_digest(old_cores)
    candidate_digest = canonical_digest(new_cores)
    return ParityReport(
        total=total,
        intent_accuracy=intent_hits / float(total),
        slot_f1=round(f1, 6),
        slot_precision=round(precision, 6),
        slot_recall=round(recall, 6),
        frame_exact=exact_hits / float(total),
        fallback_rate=fallbacks / float(total),
        clarification_rate=clarifications / float(total),
        determinism_match=legacy_digest == candidate_digest,
        legacy_digest=legacy_digest,
        candidate_digest=candidate_digest,
        mismatches=tuple(mismatches),
    )


__all__ = [
    "ParityReport",
    "compare",
    "result_core",
]
