"""D6.4: детерминированный планировщик целей разговора и действий.

Планировщик не трогает мир и не принимает решений за игрока: он
раскладывает намерение на шаги по данным ``configs/dialogue/goals.json``.
Цель выбирается первым совпадением ``when``, шаги выполняются в
объявленном порядке. Проверки (``op: check``) получают статус
``done``/``blocked`` только из явно переданных ``checks`` — никаких
скрытых эвристик и вероятностей.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class Intent:
    """Намерение, извлечённое из разобранной фразы."""

    kind: str
    act: str = ""
    target: str = ""
    action_id: str = ""
    phrase: str = ""

    def snapshot(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "act": self.act,
            "target": self.target,
            "action_id": self.action_id,
        }


@dataclass(frozen=True)
class GoalStep:
    """Шаг плана: ответ, речевое действие, действие мира или проверка."""

    id: str
    op: str
    label: str = ""
    requires: str = ""
    status: str = "planned"
    reason: str = ""

    def snapshot(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "op": self.op,
            "label": self.label,
            "requires": self.requires,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class GoalPlan:
    """Дерево подцелей с проверяемым статусом."""

    id: str
    goal: str
    intent: Intent
    steps: Tuple[GoalStep, ...] = field(default_factory=tuple)
    status: str = "planned"
    reason: str = ""

    def next_step(self) -> Optional[GoalStep]:
        """Первый ещё не выполненный шаг."""

        for step in self.steps:
            if step.status == "planned":
                return step
        return None

    def evaluate(self, checks: Mapping[str, Any]) -> "GoalPlan":
        """Проставить проверкам ``done``/``blocked`` по словарю ``checks``."""

        steps = []
        blocked = False
        for step in self.steps:
            status = step.status
            reason = step.reason
            if step.op == "check" and step.requires:
                if step.requires in checks:
                    passed = bool(checks[step.requires])
                    status = "done" if passed else "blocked"
                    reason = "" if passed else "check_failed:%s" % (
                        step.requires
                    )
            if status == "blocked":
                blocked = True
            steps.append(replace(step, status=status, reason=reason))
        if blocked:
            plan_status = "blocked"
        elif steps and all(item.status == "done" for item in steps):
            plan_status = "done"
        else:
            plan_status = "planned"
        reason = ""
        if blocked:
            failed = [
                item.requires
                for item in steps
                if item.status == "blocked" and item.requires
            ]
            reason = "blocked:" + ",".join(failed)
        return replace(
            self,
            steps=tuple(steps),
            status=plan_status,
            reason=reason,
        )

    def snapshot(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status,
            "reason": self.reason,
            "intent": self.intent.snapshot(),
            "steps": [step.snapshot() for step in self.steps],
        }


def _entity(value: Any) -> str:
    """Достать ``head.entity`` из NP/PP, иначе пустая строка."""

    if not isinstance(value, Mapping):
        return ""
    head = value.get("head")
    if isinstance(head, Mapping):
        return str(head.get("entity") or "")
    inner = value.get("object")
    if isinstance(inner, Mapping):
        return _entity(inner)
    return ""


def intent_from_sem(
    sem: Any, phrase: str = "", action_id: str = ""
) -> Optional[Intent]:
    """Извлечь намерение из логической формы; ``None`` — не намерение."""

    if not isinstance(sem, Mapping):
        return None
    kind = str(sem.get("kind") or "")
    if not kind:
        return None
    target = _entity(sem.get("object"))
    if not target:
        target = _entity(sem.get("destination"))
    if not target:
        target = _entity(sem.get("target"))
    resolved_action = str(action_id or "")
    if not resolved_action and kind == "order":
        resolved_action = str(sem.get("action") or "")
    return Intent(
        kind=kind,
        act=str(sem.get("act") or ""),
        target=target,
        action_id=resolved_action,
        phrase=str(phrase or ""),
    )


class GoalPlanner:
    """Выбор цели и разложение на шаги по ``goals.json``."""

    def __init__(self, catalog: Any):
        self.catalog = catalog

    def _spec(self) -> Mapping[str, Any]:
        return getattr(self.catalog, "goals", None) or {}

    def goals(self) -> Tuple[Mapping[str, Any], ...]:
        return tuple(
            item
            for item in (self._spec().get("goals") or ())
            if isinstance(item, Mapping)
        )

    def match(self, intent: Intent) -> Optional[Mapping[str, Any]]:
        """Первая цель, чьё ``when`` покрывает намерение."""

        for goal in self.goals():
            when = goal.get("when") or {}
            if not isinstance(when, Mapping):
                continue
            kinds = [str(item) for item in (when.get("kinds") or ())]
            acts = [str(item) for item in (when.get("acts") or ())]
            if kinds and intent.kind not in kinds:
                continue
            if acts and intent.act not in acts:
                continue
            return goal
        return None

    def plan(
        self,
        intent: Intent,
        checks: Optional[Mapping[str, Any]] = None,
    ) -> Optional[GoalPlan]:
        """Построить план цели; ``None``, если цель не описана данными."""

        goal = self.match(intent)
        if goal is None:
            return None
        steps = []
        for item in goal.get("steps") or ():
            if not isinstance(item, Mapping):
                continue
            steps.append(
                GoalStep(
                    id=str(item.get("id") or ""),
                    op=str(item.get("op") or ""),
                    label=str(item.get("label") or ""),
                    requires=str(item.get("requires") or ""),
                )
            )
        plan = GoalPlan(
            id=str(goal.get("id") or ""),
            goal=str(goal.get("id") or ""),
            intent=intent,
            steps=tuple(steps),
            status="done" if not steps else "planned",
        )
        if checks is not None:
            plan = plan.evaluate(checks)
        return plan
