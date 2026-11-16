"""D6.4/F-17: мост «фраза → намерение → действие → работа».

Диалог по умолчанию read-only. Мост включается только явным
``allow_actions=True`` и только для вызова ``act``: обычный ``ask``
по-прежнему ничего не меняет.

При включённом мосте действие проходит путь ``Intent → ActionSpec →
validate → Work``. Объявленное действие (``source: declared``) берётся
из кампании или ``WorldEngine``; свободное действие (``source:
improvised``) собирается через ``improvised_work`` только при явном
``allow_improvised=True``. Каждая попытка оставляет трассировку: глагол,
речевой акт, форма и адресат.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional

from ..actions import (
    ActionError,
    build_spec_work,
    improvised_work,
    parse_entity_ref,
)
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
    source: str = ""
    work: Mapping[str, Any] = field(default_factory=dict)
    trace: Mapping[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict:
        return {
            "ok": self.ok,
            "performed": self.performed,
            "reason": self.reason,
            "action_id": self.action_id,
            "target": self.target,
            "source": self.source,
            "intent": self.intent.snapshot() if self.intent else None,
            "plan": self.plan.snapshot() if self.plan else None,
            "work": dict(self.work),
            "trace": dict(self.trace),
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
        engine: Any = None,
        forms: Any = None,
        allow_improvised: bool = False,
    ):
        self.catalog = catalog
        self.campaign = campaign
        self.side = str(side or "")
        self.allow_actions = bool(allow_actions)
        self.social = social
        self.listener = str(listener or "")
        self.engine = engine
        self.forms = forms
        self.allow_improvised = bool(allow_improvised)
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

        return self._checks(intent, checks, self._target_ref(intent))

    def _option(
        self,
        action_id: str,
        target_ref: Optional[Mapping[str, str]] = None,
    ) -> Mapping[str, Any]:
        if not action_id:
            return {}
        if self.campaign is not None and self.side:
            try:
                options = self.campaign.action_options(self.side)
            except AttributeError:
                options = ()
            for item in options or ():
                if str(item.get("id")) == str(action_id):
                    return item
        if self.engine is not None:
            try:
                options = self.engine.action_options(
                    target_ref=target_ref, include_disabled=True
                )
            except (AttributeError, TypeError):
                options = ()
            for item in options or ():
                if str(item.get("id")) == str(action_id):
                    return item
            record = (getattr(self.engine, "actions", {}) or {}).get(
                str(action_id)
            )
            if isinstance(record, Mapping):
                try:
                    enabled, reason = self.engine.validate(
                        action_id, target_ref=target_ref
                    )
                except (AttributeError, TypeError):
                    enabled, reason = True, ""
                return {
                    "id": str(action_id),
                    "action": record,
                    "enabled": bool(enabled),
                    "reason": str(reason or ""),
                }
        return {}

    def _record(self, action_id: str) -> Mapping[str, Any]:
        option = self._option(action_id)
        record = option.get("action")
        if isinstance(record, Mapping):
            return record
        for item in (
            getattr(self.catalog, "actions", {}) or {}
        ).get("actions") or ():
            if isinstance(item, Mapping) and str(item.get("id")) == str(
                action_id
            ):
                return item
        return {}

    def _checks(
        self,
        intent: Intent,
        checks: Optional[Mapping[str, Any]],
        target_ref: Optional[Mapping[str, str]] = None,
    ) -> Mapping[str, Any]:
        merged = dict(checks or {})
        merged["action"] = bool(intent.action_id)
        if intent.action_id:
            option = self._option(intent.action_id, target_ref)
            merged["available"] = bool(option.get("enabled"))
        else:
            merged["available"] = False
        return merged

    def _form_catalog(self) -> Any:
        if self.forms is not None:
            return self.forms or None
        try:
            from ..actions import FormCatalog

            self.forms = FormCatalog.load()
        except Exception:
            self.forms = False
        return self.forms or None

    @staticmethod
    def _target_ref(intent: Intent) -> Optional[Mapping[str, str]]:
        target = str(intent.target or "")
        if not target or target in ("self", "me", "я"):
            return None
        try:
            return parse_entity_ref(target)
        except ActionError:
            return None

    @staticmethod
    def _spec(record: Mapping[str, Any], action_id: str) -> dict:
        """Собрать ``ActionSpec`` из записи кампании или движка.

        Берутся только поля работы: id, label, form, template, cost и
        hints. Адресат кампании (``rival``/``self``) не является
        ``entity_ref`` и в спецификацию не попадает.
        """

        data = record if isinstance(record, Mapping) else {}
        template = data.get("template")
        template = dict(template) if isinstance(template, Mapping) else {}
        form = str(data.get("form") or template.get("form") or "")
        spec = {
            "id": str(data.get("id") or action_id),
            "label": str(data.get("label") or action_id),
            "template": template,
        }
        if form:
            spec["form"] = form
            template.setdefault("form", form)
        cost = data.get("cost")
        if isinstance(cost, Mapping):
            spec["cost"] = dict(cost)
        hints = data.get("hints")
        if isinstance(hints, Mapping):
            spec["hints"] = dict(hints)
        return spec

    @staticmethod
    def _trace(
        intent: Intent,
        source: str,
        action_id: str,
        form: str,
        target_ref: Optional[Mapping[str, str]] = None,
    ) -> dict:
        token = intent.phrase.strip().split()
        verb = token[0].lower() if token else str(intent.verb or "")
        if verb.startswith("act_"):
            verb = verb[4:]
        target = str(intent.target or "")
        if not target and target_ref:
            target = "%s:%s" % (target_ref.get("kind"), target_ref.get("id"))
        return {
            "source": source,
            "verb": verb,
            "act": intent.act,
            "action": action_id,
            "form": form,
            "target": target,
            "phrase": intent.phrase,
        }

    def _execute(
        self,
        intent: Intent,
        target_ref: Optional[Mapping[str, str]],
    ) -> Mapping[str, Any]:
        action_id = str(intent.action_id)
        engine_actions = getattr(self.engine, "actions", {}) or {}
        if self.engine is not None and action_id in engine_actions:
            kwargs = {"target_ref": target_ref} if target_ref else {}
            return dict(self.engine.execute(action_id, **kwargs) or {})
        if self.campaign is not None and self.side:
            return dict(
                self.campaign.perform(
                    self.side,
                    action_id,
                    target=intent.target or None,
                )
                or {}
            )
        return {"ok": False, "reason": "no_campaign"}

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
        if self.campaign is None and self.engine is None:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_campaign",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
            )
        if self.campaign is not None and not self.side:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_side",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
            )
        if intent.action_id:
            resolved = self.resolve(intent.action_id)
            if resolved != intent.action_id:
                intent = replace(intent, action_id=resolved)
        target_ref = self._target_ref(intent)
        option = (
            self._option(intent.action_id, target_ref)
            if intent.action_id
            else {}
        )
        if option:
            return self._perform_declared(
                intent, option, checks=checks, target_ref=target_ref
            )
        if not self.allow_improvised:
            return ActionResult(
                ok=False,
                performed=False,
                reason="action_unknown" if intent.action_id else "no_action",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
            )
        if not intent.form:
            return ActionResult(
                ok=False,
                performed=False,
                reason="action_unknown" if intent.action_id else "no_action",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
            )
        return self._perform_improvised(
            intent, checks=checks, target_ref=target_ref
        )

    def _perform_declared(
        self,
        intent: Intent,
        option: Mapping[str, Any],
        checks: Optional[Mapping[str, Any]] = None,
        target_ref: Optional[Mapping[str, str]] = None,
    ) -> ActionResult:
        record = option.get("action")
        if not isinstance(record, Mapping):
            record = self._record(intent.action_id)
        spec = self._spec(record, intent.action_id)
        form = str(spec.get("form") or "")
        work = None
        try:
            work = build_spec_work(spec, campaign=self.campaign)
        except ActionError as exc:
            trace = self._trace(
                intent, "declared", intent.action_id, form, target_ref
            )
            return ActionResult(
                ok=False,
                performed=False,
                reason="work_invalid: %s" % exc,
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
                source="declared",
                trace=trace,
            )
        trace = self._trace(
            intent,
            "declared",
            intent.action_id,
            form or (work.form if work is not None else ""),
            target_ref,
        )
        work_data = work.as_dict() if work is not None else {}
        if work is None and form:
            return ActionResult(
                ok=False,
                performed=False,
                reason="work_not_built",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
                source="declared",
                trace=trace,
            )
        merged = self._checks(intent, checks, target_ref)
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
                source="declared",
                work=work_data,
                trace=trace,
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
                source="declared",
                work=work_data,
                trace=trace,
            )
        try:
            result = self._execute(intent, target_ref)
        except AttributeError:
            return ActionResult(
                ok=False,
                performed=False,
                reason="no_campaign",
                action_id=intent.action_id,
                target=intent.target,
                intent=intent,
                plan=plan,
                source="declared",
                work=work_data,
                trace=trace,
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
            source="declared",
            work=work_data,
            trace=trace,
        )

    def _perform_improvised(
        self,
        intent: Intent,
        checks: Optional[Mapping[str, Any]] = None,
        target_ref: Optional[Mapping[str, str]] = None,
    ) -> ActionResult:
        """Собрать свободную работу, если политика её разрешает.

        Импровизация не обходит проверки: нужна существующая форма и
        совместимый адресат. План помечается ``source: improvised``.
        Применение свободной работы выполняет исполнитель, если он
        предоставляет ``execute_work``/``execute_spec``; иначе мост
        возвращает готовый план для трассировки и не меняет мир.
        """

        action_id = intent.action_id or "improvised"
        spec = {
            "id": action_id,
            "label": intent.phrase or "Свободное действие",
            "form": intent.form,
            "target": target_ref,
        }
        try:
            work = improvised_work(
                spec,
                forms=self._form_catalog(),
                campaign=self.campaign,
                enabled=True,
            )
        except ActionError as exc:
            trace = self._trace(
                intent, "improvised", action_id, intent.form, target_ref
            )
            return ActionResult(
                ok=False,
                performed=False,
                reason="improvised_invalid: %s" % exc,
                action_id=action_id,
                target=intent.target,
                intent=intent,
                source="improvised",
                trace=trace,
            )
        if work is None:
            trace = self._trace(
                intent, "improvised", action_id, intent.form, target_ref
            )
            return ActionResult(
                ok=False,
                performed=False,
                reason="improvised_invalid",
                action_id=action_id,
                target=intent.target,
                intent=intent,
                source="improvised",
                trace=trace,
            )
        trace = self._trace(
            intent, "improvised", action_id, work.form, target_ref
        )
        work_data = work.as_dict()
        result: Mapping[str, Any] = {
            "ok": True,
            "performed": False,
            "source": "improvised",
            "work": work_data,
        }
        executor = None
        if self.engine is not None:
            executor = getattr(self.engine, "execute_work", None)
        if executor is None and self.campaign is not None:
            executor = getattr(self.campaign, "execute_work", None)
        if callable(executor):
            try:
                applied = dict(executor(work) or {})
            except Exception as exc:  # pragma: no cover - защита моста
                applied = {"ok": False, "reason": str(exc)}
            result = dict(applied)
            result.setdefault("source", "improvised")
            result.setdefault("work", work_data)
        performed = bool(result.get("performed", result.get("ok", False)))
        return ActionResult(
            ok=bool(result.get("ok", True)),
            performed=performed,
            reason=str(result.get("reason") or ""),
            action_id=action_id,
            target=intent.target,
            intent=intent,
            result=result,
            source="improvised",
            work=work_data,
            trace=trace,
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
