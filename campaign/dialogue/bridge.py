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
from .social import SocialDecision, social_bindings


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
        social: Any = None,
        listener: str = "",
    ):
        self.catalog = catalog
        self.campaign = campaign
        self.side = str(side or "")
        self.allow_actions = bool(allow_actions)
        self.social = social
        self.listener = str(listener or "")
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
        sem: Any = None,
    ) -> ActionResult:
        """Выполнить действие, если мост включён и проверки пройдены."""

        if intent.kind == "social" and not intent.action_id:
            return self.perform_social(intent, checks=checks, sem=sem)
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

    # --- D7.1: речевые действия как действия ------------------------

    def social_act(self, intent: Intent, sem: Any = None):
        """Найти акт ``social.json`` по форме или id намерения."""

        social = getattr(self.catalog, "social", None)
        if social is None:
            return None
        if sem is not None and self.social is not None:
            found = self.social.act_for(sem)
            if found is not None:
                return found
        acts = getattr(social, "acts", {}) or {}
        for act in acts.values():
            if intent.act and act.id == intent.act:
                return act
        return None

    def social_decision(
        self, sem: Any
    ) -> Optional[SocialDecision]:
        """Решение ``SocialEngine`` без выполнения действия."""

        if self.social is None or sem is None:
            return None
        bindings = social_bindings(sem, self.social.knowledge)
        return self.social.decide(sem, bindings)

    @staticmethod
    def _social_snapshot(
        act: Any, decision: Optional[SocialDecision]
    ) -> dict:
        data = {
            "act_id": str(getattr(act, "id", "") or ""),
            "act_label": str(getattr(act, "label", "") or ""),
            "interaction_id": str(getattr(act, "interaction", "") or ""),
        }
        if decision is not None:
            data.update(
                {
                    "reaction_id": decision.reaction_id,
                    "effect": dict(decision.effect or {}),
                    "bindings": dict(decision.bindings or {}),
                    "trace": [
                        dict(item) for item in decision.trace
                    ],
                    "reason": decision.reason,
                    "admissible": bool(decision.admissible),
                }
            )
        return data

    def perform_social(
        self,
        intent: Intent,
        checks: Optional[Mapping[str, Any]] = None,
        sem: Any = None,
    ) -> ActionResult:
        """Провести речевое действие и применить взаимодействие кампании.

        Гейты (``has_authority``/``trusts``) проверяет ``SocialEngine``
        по снимку знания; кампанию меняет только публичный
        ``perform_character_interaction``. Отказ по гейту не трогает мир.
        """

        plan = None
        if not self.allow_actions:
            return ActionResult(
                ok=False,
                performed=False,
                reason="actions_disabled",
                target=intent.target,
                intent=intent,
            )
        if self.campaign is None:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_campaign",
                target=intent.target,
                intent=intent,
            )
        if not self.side:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_side",
                target=intent.target,
                intent=intent,
            )
        if self.social is None:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_social_engine",
                target=intent.target,
                intent=intent,
            )
        act = self.social_act(intent, sem)
        if act is None:
            return ActionResult(
                ok=False,
                performed=False,
                reason="not_social_act",
                target=intent.target,
                intent=intent,
            )
        interaction_id = str(getattr(act, "interaction", "") or "")
        if not interaction_id:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_interaction",
                target=intent.target,
                intent=intent,
                result={"social": self._social_snapshot(act, None)},
            )
        decision = self.social_decision(sem)
        snapshot = self._social_snapshot(act, decision)
        if decision is None:
            return ActionResult(
                ok=False,
                performed=False,
                reason="not_social_act",
                action_id=interaction_id,
                target=intent.target,
                intent=intent,
                result={"social": snapshot},
            )
        if not decision.admissible:
            return ActionResult(
                ok=False,
                performed=False,
                reason=decision.reason or "social_rejected",
                action_id=interaction_id,
                target=intent.target,
                intent=intent,
                result={"social": snapshot},
            )
        listener = str(
            decision.bindings.get("listener")
            or self.listener
            or getattr(self.social.knowledge, "speaker_id", "")
            or ""
        )
        if not listener:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_listener",
                action_id=interaction_id,
                target=intent.target,
                intent=intent,
                result={"social": snapshot},
            )
        try:
            result = self.campaign.perform_character_interaction(
                self.side, listener, interaction_id
            )
        except AttributeError:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_campaign",
                action_id=interaction_id,
                target=intent.target,
                intent=intent,
                result={"social": snapshot},
            )
        data = dict(result or {})
        data["social"] = snapshot
        ok = bool(data.get("ok"))
        return ActionResult(
            ok=ok,
            performed=ok,
            reason="" if ok else str(data.get("reason") or ""),
            action_id=interaction_id,
            target=intent.target,
            intent=intent,
            plan=plan,
            result=data,
        )
