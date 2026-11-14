"""D6.4: мост «фраза → намерение → действие».

Диалог по умолчанию read-only. Мост включается только явным
``allow_actions=True`` и только для вызова ``act``: обычный ``ask``
по-прежнему ничего не меняет. Действие проверяется по публичному
``available_actions`` кампании, поэтому условия, бюджет и перезарядки
остаются в одном месте — в ``AutomataCampaign``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional

from .planner import GoalPlan, GoalPlanner, Intent, intent_from_sem


@dataclass(frozen=True)
class ActionResult:
    """Результат попытки выполнить действие из диалога."""

    ok: bool
    performed: bool
    reason: str = ""
    action_id: str = ""
    target: str = ""
    intent: Optional[Intent] = None
    plan: Optional[GoalPlan] = None
    result: Mapping[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict:
        return {
            "ok": self.ok,
            "performed": self.performed,
            "reason": self.reason,
            "action_id": self.action_id,
            "target": self.target,
            "intent": self.intent.snapshot() if self.intent else None,
            "plan": self.plan.snapshot() if self.plan else None,
            "result": dict(self.result),
        }


class ActionBridge:
    """Детерминированный мост к ``AutomataCampaign``."""

    def __init__(
        self,
        catalog: Any,
        campaign: Any = None,
        side: str = "",
        allow_actions: bool = False,
    ):
        self.catalog = catalog
        self.campaign = campaign
        self.side = str(side or "")
        self.allow_actions = bool(allow_actions)
        self.planner = GoalPlanner(catalog)

    def intent(
        self,
        sem: Any,
        phrase: str = "",
        action_id: str = "",
    ) -> Optional[Intent]:
        found = intent_from_sem(sem, phrase=phrase, action_id=action_id)
        if found is None or not found.action_id:
            return found
        resolved = self.resolve(found.action_id)
        if resolved == found.action_id:
            return found
        return replace(found, action_id=resolved)

    def resolve(self, action_id: str) -> str:
        """Привести псевдоним действия к id кампании по ``actions.json``."""

        requested = str(action_id or "")
        if not requested:
            return ""
        spec = getattr(self.catalog, "actions", None) or {}
        for item in spec.get("actions") or ():
            if not isinstance(item, Mapping):
                continue
            canonical = str(item.get("id") or "")
            if requested == canonical:
                return canonical
            aliases = [
                str(alias) for alias in (item.get("aliases") or ())
            ]
            if requested in aliases:
                return canonical
        return requested

    def plan(
        self,
        intent: Intent,
        checks: Optional[Mapping[str, Any]] = None,
    ) -> Optional[GoalPlan]:
        return self.planner.plan(intent, checks=checks)

    def checks(
        self,
        intent: Intent,
        checks: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """Публичные проверки цели: доступность действия плюс внешние."""

        return self._checks(intent, checks)

    def _option(self, action_id: str) -> Mapping[str, Any]:
        if self.campaign is None or not self.side:
            return {}
        try:
            options = self.campaign.action_options(self.side)
        except AttributeError:
            return {}
        for item in options or ():
            if str(item.get("id")) == str(action_id):
                return item
        return {}

    def _checks(
        self,
        intent: Intent,
        checks: Optional[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        merged = dict(checks or {})
        merged["action"] = bool(intent.action_id)
        if self.campaign is not None and intent.action_id:
            option = self._option(intent.action_id)
            merged["available"] = bool(option.get("enabled"))
        else:
            merged["available"] = False
        return merged

    def perform(
        self,
        intent: Intent,
        checks: Optional[Mapping[str, Any]] = None,
    ) -> ActionResult:
        """Выполнить действие, если мост включён и проверки пройдены."""

        if not self.allow_actions:
            return ActionResult(
                ok=False,
                performed=False,
                reason="actions_disabled",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
            )
        if self.campaign is None:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_campaign",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
            )
        if not self.side:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_side",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
            )
        if not intent.action_id:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_action",
                target=intent.target,
                intent=intent,
            )
        resolved = self.resolve(intent.action_id)
        if resolved != intent.action_id:
            intent = replace(intent, action_id=resolved)
        option = self._option(intent.action_id)
        if not option:
            return ActionResult(
                ok=False,
                performed=False,
                reason="action_unknown",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
            )
        merged = self._checks(intent, checks)
        plan = self.plan(intent, checks=merged)
        if plan is not None and plan.status == "blocked":
            return ActionResult(
                ok=False,
                performed=False,
                reason=str(option.get("reason") or plan.reason or "blocked"),
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
                plan=plan,
            )
        if not option.get("enabled"):
            return ActionResult(
                ok=False,
                performed=False,
                reason=str(option.get("reason") or "action_unavailable"),
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
                plan=plan,
            )
        try:
            result = self.campaign.perform(
                self.side,
                intent.action_id,
                target=intent.target or None,
            )
        except AttributeError:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_campaign",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
                plan=plan,
            )
        data = dict(result or {})
        ok = bool(data.get("ok"))
        return ActionResult(
            ok=ok,
            performed=ok,
            reason=str(data.get("reason") or ""),
            action_id=intent.action_id,
            target=intent.target,
            intent=intent,
            plan=plan,
            result=data,
        )
