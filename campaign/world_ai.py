"""ИИ узлов мира: оценка действий, стратегии и выбор хода."""

from __future__ import annotations

from .world_support import (
    _as_float,
    _as_int,
    _text,
    success_margin,
)


class WorldAIMixin:

    def _ai_targets(self, action, context):
        spec = action.get("target") or {}
        if spec.get("self"):
            return [context["node"]]
        if not spec.get("required", True):
            return [None]
        result = []
        for node in self.nodes.values():
            if node["id"] == context["node"]["id"]:
                if spec.get("exclude_self"):
                    continue
            reason = self._reason_target(action, context, node)
            if not reason:
                result.append(node)
        return result

    def _ensure_strategy_state(self, node, strategy):
        """Лениво создать/перезапустить состояние стратегии узла."""
        per_node = self.strategy_state.setdefault(node["id"], {})
        state = per_node.get(strategy.id)
        if state is not None and (
            state.get("completed") or state.get("expired")
        ):
            resolved = _as_int(state.get("resolved_day"), self.day)
            if (
                strategy.repeat
                and self.day - resolved >= strategy.cooldown_days
            ):
                state = strategy.new_state(node, self.day)
                per_node[strategy.id] = state
        if state is None:
            state = strategy.new_state(node, self.day)
            per_node[strategy.id] = state
        return state

    def _strategy_bonus(self, action, context, target):
        """Бонус долгосрочной стратегии к выбору действия узла."""
        node = context.get("node")
        if node is None or not len(self.strategies):
            return 0.0
        total = 0.0
        for strategy in self.strategies.for_node(node):
            if not strategy.matches_target(target):
                continue
            state = self._ensure_strategy_state(node, strategy)
            total += strategy.score_bonus(
                action["id"], node, state, self.day
            )
        return total

    def _advance_strategies(self):
        """Оценить прогресс стратегий на границе дня.

        Завершённая/просроченная стратегия применяет свои эффекты один раз
        и попадает в журнал. `repeat`-стратегии перезапускаются после
        `cooldown_days`, поэтому долгосрочная цель может быть циклом, а не
        одноразовым событием.
        """
        events = []
        for node_id, per_node in list(self.strategy_state.items()):
            node = self.nodes.get(node_id)
            if node is None:
                continue
            for strategy_id, state in list(per_node.items()):
                strategy = self.strategies.get(strategy_id)
                if strategy is None:
                    continue
                event = strategy.advance(node, state, self.day)
                if event is None:
                    continue
                changed = self._apply_stat_map(node, event.get("stats"))
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "strategy",
                        "source": node_id,
                        "text": "%s: %s"
                        % (node["name"], event["text"]),
                    }
                )
                entry = dict(event)
                entry["kind"] = "strategy"
                entry["day"] = self.day
                entry["node_id"] = node_id
                entry["node_name"] = node["name"]
                entry["changes"] = changed
                events.append(entry)
                if strategy.repeat and strategy.cooldown_days <= 0:
                    per_node[strategy_id] = strategy.new_state(
                        node, self.day
                    )
        return events

    def strategy_progress(self):
        """Публичный срез долгосрочных целей узлов для UI и калибровки."""
        result = []
        for node_id, per_node in self.strategy_state.items():
            node = self.nodes.get(node_id)
            if node is None:
                continue
            for strategy_id, state in per_node.items():
                strategy = self.strategies.get(strategy_id)
                if strategy is None:
                    continue
                start = _as_int(state.get("start_day"), self.day)
                result.append(
                    {
                        "node_id": node_id,
                        "node_name": node["name"],
                        "strategy_id": strategy_id,
                        "label": strategy.label,
                        "progress": strategy.progress(node, state),
                        "days_left": max(
                            0, strategy.horizon_days - (self.day - start)
                        ),
                        "completed": bool(state.get("completed")),
                        "expired": bool(state.get("expired")),
                        "goal": dict(strategy.goal),
                    }
                )
        result.sort(
            key=lambda item: (
                item["completed"],
                item["expired"],
                item["node_id"],
                item["strategy_id"],
            )
        )
        return result

    def _ai_base(self, action, context):
        """Часть оценки действия, не зависящая от цели.

        `interests` узла и `ai_weight` действия постоянны в пределах
        одного `_ai_action`, поэтому взвешенная сумма и штрафы за стоимость
        считаются один раз на действие, а не для каждой пары
        «действие × цель». Это главный горячий участок дневного шага.
        """
        weight = action.get("ai_weight") or {}
        score = 0.0
        if weight:
            interests = context["node"].get("interests") or {}
            for key, value in weight.items():
                score += _as_float(interests.get(key), 0.0) * _as_float(value)
        else:
            score = 0.2
        stats = context["node"].get("stats") or {}
        for key, value in (action.get("cost") or {}).get("node", {}).items():
            score -= 0.10 * _as_float(value)
            if _as_float(stats.get(key), 0.0) < 0.2:
                score -= 0.3
        return score

    def _ai_score(self, action, context, target, base=None):
        if base is None:
            base = self._ai_base(action, context)
        score = base
        if target is not None:
            relations = context["node"].get("relations") or {}
            score += 0.15 * _as_float(relations.get(target["id"]), 0.0)
            if target.get("polity") == context["node"].get("polity"):
                score += 0.05
        token = "ai-choice:%s:%s:%s:%s" % (
            self.day,
            context["node"]["id"],
            action["id"],
            target["id"] if target else "-",
        )
        score += 0.20 * self._roll(token)
        score += self._strategy_bonus(action, context, target)
        score += self._coalition_bonus(context, target)
        return score

    def _ai_action(self, node_id):
        context = self.node_context(node_id)
        if context is None:
            return None
        best = None
        for action in self.actions.values():
            if not action.get("ai", True):
                continue
            if self._reason_actor(action, context):
                continue
            if self._reason_cost(action, context):
                continue
            base = self._ai_base(action, context)
            if action.get("target", {}).get("self"):
                candidates = [context["node"]]
            else:
                candidates = self._ai_targets(action, context)
            for target in candidates:
                if self._reason_requirements(action, context, target):
                    continue
                if self._value_reason(action, context):
                    continue
                score = self._ai_score(action, context, target, base)
                if best is None or score > best[0]:
                    best = (score, action, target)
        if best is None:
            return None
        _score, action, target = best
        self._pay_cost(action, context)
        changed = self._apply_effects(
            action.get("immediate"), context, target, is_player=False
        )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        chance = self._action_chance(
            action, target, context, success, is_player=False
        )
        roll = self._roll(
            "ai:%s:%s:%s:%s"
            % (
                self.day,
                node_id,
                action["id"],
                target["id"] if target else "-",
            )
        )
        outcome = "success" if roll < chance else "failure"
        branch = success if outcome == "success" else failure
        changed.extend(
            self._world_effects(
                action,
                context,
                target,
                success=(outcome == "success"),
                is_player=False,
            )
        )
        text = _text(branch.get("text"), action.get("description", ""))
        entry = {
            "day": self.day,
            "kind": "world",
            "source": context["node"]["id"],
            "target": target["id"] if target else "",
            "outcome": outcome,
            "chance": chance,
            "roll": roll,
            "margin": success_margin(chance, roll),
            "text": "%s: %s %s"
            % (
                context["node"]["name"],
                _text(action.get("label"), action["id"]).lower(),
                "— %s" % text if text else "",
            ),
            "changes": changed,
        }
        self.log.append(entry)
        return entry

    @staticmethod
    def _merge_changes(changed):
        merged = {}
        for label, value in changed:
            merged[label] = merged.get(label, 0.0) + float(value)
        return [
            (label, value)
            for label, value in merged.items()
            if abs(value) > 1e-9
        ]
