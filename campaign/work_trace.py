"""След работы: ``WorkReport`` + ``trace`` для UI, диалога и лога.

Работа кампании проходит через ``receive`` и возвращает ``WorkReport``,
который переводится в ``trace``. ``trace`` — стабильная схема
(``WORK_TRACE_VERSION = 1``), на которую опираются лог, UI и диалог,
чтобы объяснить исход без чтения авторских ``effects``.

Модуль ничего не применяет: применение отчёта к состоянию фракции живёт
в ``campaign.effects.apply_report``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

WORK_TRACE_VERSION = 1


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def _round(value):
    return round(_number(value, 0.0), 6)


@dataclass
class WorkTrace:
    """След работы для лога, UI и диалога.

    Поля соответствуют схеме ``WORK_TRACE_VERSION = 1``. ``essence``
    берётся из ``report.trace`` (обработчик), а не из capability: это
    вычисленный след, а не авторская метка.
    """

    capability_id: str
    amount: float
    form: str
    payload: tuple = ()
    duration: float = 1.0
    efficiency: float = 0.0
    stored: float = 0.0
    loss: float = 0.0
    entropy: float = 0.0
    chance: float = 0.0
    roll: float = 0.0
    success: bool = False
    accepted: bool = False
    essence: str = ""
    target_side: str = ""
    version: int = WORK_TRACE_VERSION

    def as_dict(self):
        return {
            "version": int(self.version),
            "capability_id": str(self.capability_id),
            "amount": _round(self.amount),
            "form": str(self.form),
            "payload": list(self.payload or ()),
            "duration": _round(self.duration),
            "efficiency": _round(self.efficiency),
            "stored": _round(self.stored),
            "loss": _round(self.loss),
            "entropy": _round(self.entropy),
            "chance": _round(self.chance),
            "roll": _round(self.roll),
            "success": bool(self.success),
            "accepted": bool(self.accepted),
            "essence": str(self.essence),
            "target_side": str(self.target_side),
        }


def trace_from_report(plan, chance, roll, success, report):
    """Собрать ``WorkTrace`` из ``WorkPlan``, броска и ``WorkReport``.

    ``plan`` — ``campaign.work.WorkPlan``; ``chance``/``roll``/``success``
    — из резолвера кампании (а не из обработчика: обработчик
    детерминирован); ``report`` — ``WorkReport`` от ``receive``.

    Не бросает: отсутствующие поля отчёта трактуются как 0/False, чтобы
    схема оставалась стабильной для неполных отчётов старых обработчиков.
    """
    report = _as_mapping(report)
    report_trace = _as_mapping(report.get("trace"))
    return WorkTrace(
        capability_id=str(getattr(plan, "capability_id", "") or ""),
        amount=_number(getattr(plan, "amount", 0.0), 0.0),
        form=str(getattr(plan, "form", "") or ""),
        payload=tuple(getattr(plan, "payload", ()) or ()),
        duration=_number(getattr(plan, "duration", 1.0), 1.0),
        efficiency=_number(report.get("efficiency"), 0.0),
        stored=_number(report.get("stored"), 0.0),
        loss=_number(report.get("loss"), 0.0),
        entropy=_number(report.get("entropy"), 0.0),
        chance=_number(chance, 0.0),
        roll=_number(roll, 0.0),
        success=bool(success),
        accepted=bool(report.get("accepted", False)),
        essence=str(report_trace.get("essence") or ""),
        target_side=str(getattr(plan, "target_side", "") or ""),
    )


def balance_error(trace):
    """Проверить аддитивность отчёта: ``stored + loss + entropy == amount``.

    Возвращает абсолютную ошибку. Используется DoD §7.2 (баланс
    работы) и тестами конвейера.
    """
    trace = trace if isinstance(trace, WorkTrace) else None
    if trace is None:
        return 0.0
    return abs(
        float(trace.stored)
        + float(trace.loss)
        + float(trace.entropy)
        - float(trace.amount)
    )


__all__ = [
    "WORK_TRACE_VERSION",
    "WorkTrace",
    "balance_error",
    "trace_from_report",
]
