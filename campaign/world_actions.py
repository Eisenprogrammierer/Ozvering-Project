"""Действия игрока, проверки, последствия, ИИ и стратегии."""

from __future__ import annotations

from .world_support import (
    Automaton,
    CAMPAIGN_ACTION_WOUND_CHANCE,
    CAMPAIGN_ACTION_WOUND_DAMAGE,
    CAMPAIGN_ACTION_WOUND_SEVERITY,
    CAMPAIGN_FAVOR_INCOME,
    CAMPAIGN_FAVOR_PER_STANDING,
    CAMPAIGN_INFLUENCE_INCOME,
    CAMPAIGN_INFLUENCE_PER_AUTHORITY,
    CAMPAIGN_WOUND_DODGE_SKILL,
    CAMPAIGN_WOUND_MAX,
    CampaignError,
    DECAY_BROKE_COHESION,
    DECAY_CRISIS_COHESION,
    DECAY_CRISIS_POWER,
    DECAY_RECOVERY_COHESION,
    DECAY_RECOVERY_LEGITIMACY,
    DECAY_RECOVERY_POWER,
    DECAY_STRAIN_COHESION,
    DECAY_STRAIN_POWER,
    DEFAULT_OBLIGATION_KIND,
    DEFAULT_RELATION_FORM,
    HEALTH_MAX,
    SICKNESS_MAX,
    _as_float,
    _as_int,
    _clamp,
    _is_wound_risky,
    _profile_skill,
    _text,
    apply_item_handler,
    build_work,
    campaign_success_chance,
    cost_phrase,
    effect_phrase,
    hashlib,
    item_handler_reason,
    logger,
    relation_effect,
    resolve_success_coefficients,
    success_margin,
    time,
)


class WorldActionsMixin:

    def skill_tree(self):
        raw_tree = self.config.get("skill_tree") or {}
        branches = raw_tree.get("branches") or []
        descriptions = raw_tree.get("descriptions") or {}
        result = []
        for branch in branches:
            skills = []
            for skill_id in branch.get("skills") or ():
                if skill_id not in self.skill_labels:
                    continue
                skills.append(
                    {
                        "id": skill_id,
                        "label": self.skill_labels[skill_id],
                        "value": _profile_skill(self.profile, skill_id),
                        "description": _text(descriptions.get(skill_id)),
                    }
                )
            if skills:
                result.append(
                    {
                        "id": branch.get("id", ""),
                        "label": _text(branch.get("label"), ""),
                        "description": _text(branch.get("description")),
                        "skills": skills,
                    }
                )
        return result

    def _character_reason_cost(self, action):
        context = self.player_context()
        if context is None:
            return "сначала выберите должность"
        return self._reason_cost(action, context)

    def _reason_character(self, action, character):
        if not character.get("alive", True):
            return "собеседник мёртв"
        circles = action.get("circles") or ()
        if circles and character["circle"] not in circles:
            return "этот шаг не подходит для такой связи"
        requires = action.get("requires") or {}
        for key, minimum in (requires.get("character") or {}).items():
            current = _as_float(character.get(key), 0.0)
            if current + 1e-9 < _as_float(minimum):
                label = self.relation_axis_labels.get(key, key)
                return "недостаточно: %s" % label
        for key, minimum in (requires.get("player") or {}).items():
            if _as_float(
                self.player_resources.get(key), 0.0
            ) + 1e-9 < _as_float(minimum):
                return "нужно больше личного ресурса «%s»" % self.stat_label(
                    key
                )
        for skill, minimum in (requires.get("skills") or {}).items():
            if _profile_skill(self.profile, skill) + 1e-9 < _as_float(minimum):
                return "нужен навык «%s»" % self.skill_labels.get(skill, skill)
        reason = self._character_reason_cost(action)
        if reason:
            return reason
        if self.actions_left <= 0:
            return "действия на сегодня исчерпаны"
        if action.get("once") and action["id"] in self.used_actions:
            return "действие уже использовано"
        cooldown = _as_int(action.get("cooldown_days"), 0)
        if cooldown:
            key = "character:%s:%s" % (action["id"], character["id"])
            last_day = self.cooldowns.get(key)
            if last_day is not None and self.day - int(last_day) < cooldown:
                return "повтор не раньше дня %d" % (int(last_day) + cooldown)
        return ""

    def character_action_options(self, character_id):
        character = self.character(character_id)
        if character is None:
            return []
        result = []
        for action in self.character_actions.values():
            reason = self._reason_character(action, character)
            success = action.get("success") or {}
            result.append(
                {
                    "action": action,
                    "id": action["id"],
                    "label": _text(action.get("label"), action["id"]),
                    "enabled": not reason,
                    "reason": reason,
                    "cost": self._cost_text(action),
                    "chance": _as_float(
                        success.get("chance"),
                        action.get("success_chance", 0.6),
                    ),
                    "character_id": character["id"],
                    "character_name": character["name"],
                }
            )
        return result

    def character_preview(self, action_id, character_id):
        action = self.character_actions.get(_text(action_id))
        character = self.character(character_id)
        if action is None:
            return None
        reason = (
            self._reason_character(action, character)
            if character is not None
            else "собеседник не найден"
        )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        return {
            "action": action,
            "character": character,
            "target_label": (
                character["name"] if character is not None else "—"
            ),
            "enabled": not reason,
            "reason": reason,
            "cost": self._cost_text(action),
            "immediate": self._effect_lines(action.get("immediate")),
            "success_chance": _as_float(
                success.get("chance"),
                action.get("success_chance", 0.6),
            ),
            "success_text": _text(success.get("text")),
            "success_effects": self._effect_lines(success.get("effects")),
            "failure_chance": _as_float(
                failure.get("chance"),
                max(
                    0.0,
                    1.0 - _as_float(action.get("success_chance"), 0.6),
                ),
            ),
            "failure_text": _text(failure.get("text")),
            "failure_effects": self._effect_lines(failure.get("effects")),
            "immediate_map": action.get("immediate") or {},
            "success_effects_map": success.get("effects") or {},
            "failure_effects_map": failure.get("effects") or {},
        }

    def _apply_character_effects(self, effects, character):
        effects = effects or {}
        changed = []
        for key in self.relation_axis_ids:
            if key not in effects:
                continue
            before = _as_float(character.get(key), 0.0)
            character[key] = _clamp(
                before + _as_float(effects.get(key)), -1.0, 1.0
            )
            delta = character[key] - before
            if abs(delta) > 1e-9:
                changed.append(
                    (
                        "%s · %s"
                        % (
                            character["name"],
                            self.relation_axis_labels.get(key, key),
                        ),
                        delta,
                    )
                )
        changed.extend(self._apply_player_map(effects.get("player")))
        changed.extend(
            self._apply_player_view(effects, character)
        )
        node_relation = _as_float(effects.get("node_relation"), 0.0)
        if (
            (
                abs(node_relation) > 1e-9
                or effects.get("node_relation_back") is not None
                or effects.get("node_relation_axes")
            )
            and self.attached
            and character.get("node_id")
            and self.node(character["node_id"]) is not None
        ):
            target = self.node(character["node_id"])
            source = self.node(self.player_node_id)
            if source is not None:
                self._shift_relation(
                    source,
                    target,
                    affinity=node_relation,
                    affinity_back=effects.get("node_relation_back"),
                    axes=effects.get("node_relation_axes"),
                )
            changed.append(
                (
                    "%s · отношения" % target["name"],
                    node_relation,
                )
            )
        return self._merge_changes(changed)

    def execute_character_action(self, action_id, character_id):
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        action = self.character_actions.get(_text(action_id))
        character = self.character(character_id)
        if action is None:
            return {"ok": False, "reason": "неизвестное действие"}
        if character is None:
            return {"ok": False, "reason": "собеседник не найден"}
        reason = self._reason_character(action, character)
        if reason:
            return {"ok": False, "reason": reason}
        context = self.player_context()
        if context is None:
            return {"ok": False, "reason": "сначала выберите должность"}
        self._pay_cost(action, context)
        changed = self._apply_character_effects(
            action.get("immediate"), character
        )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        chance = self._action_chance(
            action, character, context, success, is_player=True
        )
        roll = self._roll(
            "character:%s:%s:%s:%s"
            % (
                self.day,
                action["id"],
                character["id"],
                self.action_count,
            )
        )
        outcome = "success" if roll < chance else "failure"
        branch = success if outcome == "success" else failure
        changed.extend(
            self._world_character_effects(
                action,
                context,
                character,
                success=(outcome == "success"),
            )
        )
        changed.extend(self._apply_action_wound(action, outcome))
        self.player.spend_action()
        self.action_count += 1
        cooldown = _as_int(action.get("cooldown_days"), 0)
        if cooldown:
            self.cooldowns[
                "character:%s:%s" % (action["id"], character["id"])
            ] = self.day
        if action.get("once"):
            self.used_actions.append(action["id"])
        text = _text(branch.get("text"), action.get("description", ""))
        result = {
            "ok": True,
            "action": action["id"],
            "action_label": _text(action.get("label"), action["id"]),
            "target": character["id"],
            "target_label": character["name"],
            "outcome": outcome,
            "chance": chance,
            "roll": roll,
            "margin": success_margin(chance, roll),
            "text": text,
            "changes": changed,
            "day": self.day,
            "context": "character",
        }
        self.last_result = result
        self.log.append(
            {
                "day": self.day,
                "kind": outcome,
                "text": "%s → %s: %s"
                % (
                    result["action_label"],
                    character["name"],
                    text,
                ),
            }
        )
        self._check_dismissal()
        return result

    def _reason_actor(self, action, context):
        spec = action.get("actor") or {}
        domains = spec.get("domains") or []
        if domains and context["domain"] not in domains:
            return "действие относится к другой сфере: %s" % ", ".join(
                self.domain_label(item) for item in domains
            )
        levels = spec.get("levels") or []
        if levels and context["level"] not in levels:
            return "должность не того уровня: нужно %s" % ", ".join(
                self.level_label(context["domain"], item) for item in levels
            )
        offices = spec.get("offices") or []
        if offices and context["office"].get("id") not in offices:
            return "ваша должность не даёт этого права"
        kinds = spec.get("kinds") or []
        if kinds and context["kind"] not in kinds:
            return "этот тип структуры не может так действовать: нужно %s" % (
                ", ".join(self.kind_label(item) for item in kinds)
            )
        if context["authority"] + 1e-9 < _as_float(
            spec.get("min_authority"), 0.0
        ):
            return "недостаточно полномочий: нужно %.0f%%" % (
                100.0 * _as_float(spec.get("min_authority"), 0.0)
            )
        tags = spec.get("tags_any") or []
        if tags and not any(
            tag in context["node"].get("tags", ()) for tag in tags
        ):
            return "нужен признак структуры: %s" % ", ".join(tags)
        return ""

    def _reason_target(self, action, context, target):
        spec = action.get("target") or {}
        if spec.get("self"):
            if target is not None and target["id"] != context["node"]["id"]:
                return "действие выполняется для вашей собственной должности"
            return ""
        if not spec.get("required", True):
            return ""
        if target is None:
            return "нужно выбрать цель"
        actual = self._entity_kind(target)
        if spec.get("exclude_self") and target["id"] == context["node"]["id"]:
            return "нельзя выбрать собственную структуру"
        kinds = spec.get("kinds") or []
        if kinds and not self._kind_matches(actual, kinds):
            return _text(
                spec.get("invalid_kind_reason"),
                "цель не того типа: нужно %s"
                % ", ".join(self.kind_label(item) for item in kinds),
            )
        if actual != "institution" and actual != "asset":
            return ""
        domains = spec.get("domains") or []
        if domains and target["domain"] not in domains:
            return "цель относится к другой сфере: %s" % ", ".join(
                self.domain_label(item) for item in domains
            )
        levels = spec.get("levels") or []
        if levels and target["level"] not in levels:
            return "цель не того уровня: нужно %s" % ", ".join(
                self.level_label(target["domain"], item) for item in levels
            )
        polities = spec.get("polities") or []
        if polities and target["polity"] not in polities:
            return "цель находится в другой политии"
        if spec.get("same_polity") and target["polity"] != context["polity"]:
            return "цель должна быть в вашей политии"
        if spec.get("other_polity") and target["polity"] == context["polity"]:
            return "цель должна быть вне вашей политии"
        lineage = spec.get("lineage") or []
        if lineage:
            relation = "self" if target["id"] == context["node"]["id"] else ""
            if not relation and target["id"] in context["node"].get(
                "children", []
            ):
                relation = "child"
            if not relation and self.is_descendant(
                target["id"], context["node"]["id"]
            ):
                relation = "descendant"
            if not relation and context["node"].get("parent") == target["id"]:
                relation = "parent"
            if not relation and self.is_descendant(
                context["node"]["id"], target["id"]
            ):
                relation = "ancestor"
            if relation not in lineage:
                return "цель вне нужной ветви иерархии"
        return ""

    def _reason_requirements(self, action, context, target):
        requires = action.get("requires") or {}
        if context.get("is_player"):
            for key, minimum in (requires.get("player") or {}).items():
                if _as_float(
                    self.player_resources.get(key), 0.0
                ) + 1e-9 < _as_float(minimum):
                    return (
                        "нужно больше личного ресурса «%s»"
                        % self.stat_label(key)
                    )
            for skill, minimum in (requires.get("skills") or {}).items():
                if _profile_skill(self.profile, skill) + 1e-9 < _as_float(
                    minimum
                ):
                    return "нужен навык «%s» не ниже %.0f%%" % (
                        self.skill_labels.get(skill, skill),
                        100.0 * _as_float(minimum),
                    )
        for key, minimum in (requires.get("node") or {}).items():
            if _as_float(
                context["node"]["stats"].get(key), 0.0
            ) + 1e-9 < _as_float(minimum):
                return "у структуры мало ресурса «%s»" % self.stat_label(key)
        if target is not None:
            target_stats = target.get("stats")
            if isinstance(target_stats, dict):
                for key, minimum in (requires.get("target") or {}).items():
                    if _as_float(
                        target_stats.get(key), 0.0
                    ) + 1e-9 < _as_float(minimum):
                        return "у цели мало ресурса «%s»" % self.stat_label(
                            key
                        )
            if self._entity_kind(target) == "character":
                for axis, key in (
                    ("affinity_min", "affinity"),
                    ("trust_min", "trust"),
                    ("respect_min", "respect"),
                ):
                    minimum = requires.get(axis)
                    if minimum is not None and _as_float(
                        target.get(key), 0.0
                    ) + 1e-9 < _as_float(minimum):
                        return "человек ещё не готов к такому шагу"
                maximum = requires.get("fear_max")
                if maximum is not None and _as_float(
                    target.get("fear"), 0.0
                ) - 1e-9 > _as_float(maximum):
                    return "человек слишком напуган"
            statuses = requires.get("target_status")
            if statuses:
                if self._entity_kind(target) != "norm":
                    return "цель не является нормой"
                if target.get("status") not in statuses:
                    return _text(
                        requires.get("invalid_status_reason"),
                        "норма не в подходящем состоянии",
                    )
            item_handler = requires.get("item_handler")
            if item_handler:
                if self._entity_kind(target) != "item":
                    return "цель не является предметом"
                automaton = self.item_automata.get(
                    _text(target.get("id"))
                )
                handler = "default" if item_handler == "default" else (
                    _text(item_handler)
                )
                reason = item_handler_reason(
                    automaton,
                    "" if handler == "default" else handler,
                )
                if reason:
                    return reason
            relation_min = requires.get("relation_min")
            if relation_min is not None:
                value = self.relation(context["node"]["id"], target["id"])
                if value + 1e-9 < _as_float(relation_min):
                    return "слишком плохие отношения с целью"
        for item_id in requires.get("items") or ():
            if _text(item_id) not in self.player_item_ids:
                return "нужен предмет: %s" % self.item_label(item_id)
        return ""

    def _reason_cost(self, action, context):
        for key, value in (action.get("cost") or {}).get("node", {}).items():
            if _as_float(
                context["node"]["stats"].get(key), 0.0
            ) + 1e-9 < _as_float(value):
                return "недостаточно ресурса структуры «%s»" % self.stat_label(
                    key
                )
        if context.get("is_player"):
            for key, value in (
                (action.get("cost") or {}).get("player", {}).items()
            ):
                if _as_float(
                    self.player_resources.get(key), 0.0
                ) + 1e-9 < _as_float(value):
                    return (
                        "недостаточно личного ресурса «%s»"
                        % self.stat_label(key)
                    )
            for item_id in (action.get("cost") or {}).get("items") or ():
                if _text(item_id) not in self.player_item_ids:
                    return "нужен предмет: %s" % self.item_label(item_id)
        return ""

    def action_options(
        self, target_id=None, include_disabled=True, target_ref=None
    ):
        context = self.player_context()
        if context is None:
            return []
        result = []
        for action in self.actions.values():
            self_target = bool((action.get("target") or {}).get("self"))
            target = (
                context["node"]
                if self_target
                else (
                    self.entity(target_ref)
                    if target_ref is not None
                    else self.node(target_id)
                )
            )
            enabled, reason = self.validate(
                action["id"],
                target["id"] if target else None,
                context,
                target_ref=target_ref if not self_target else None,
            )
            if not enabled and not include_disabled:
                continue
            result.append(
                {
                    "action": action,
                    "id": action["id"],
                    "label": _text(action.get("label"), action["id"]),
                    "enabled": enabled,
                    "reason": reason,
                    "self": self_target,
                    "target_id": target["id"] if target else "",
                    "target_ref": self.entity_ref(target) if target else {},
                    "cost": self._cost_text(action),
                }
            )
        return result

    def available_actions(self, target_id=None, target_ref=None):
        return [
            item["id"]
            for item in self.action_options(
                target_id, include_disabled=False, target_ref=target_ref
            )
        ]

    def _cost_text(self, action):
        cost = action.get("cost") or {}
        parts = []
        for key, value in (cost.get("node") or {}).items():
            parts.append(cost_phrase(self.stat_label(key), _as_float(value)))
        for key, value in (cost.get("player") or {}).items():
            parts.append(cost_phrase(self.stat_label(key), _as_float(value)))
        for item_id in cost.get("items") or ():
            parts.append("предмет: %s" % self.item_label(item_id))
        return ", ".join(parts) or "без прямой платы"

    def stat_label(self, key):
        return self.stat_labels.get(key, key)

    def relation_stat_label(self, key):
        """Подпись оси отношения или обычной шкалы мира."""
        return self.relation_axis_labels.get(key, self.stat_label(key))

    def _effect_lines(self, effects):
        lines = []
        if not effects:
            return lines
        for section, label in (
            ("node", "структура"),
            ("target", "цель"),
            ("player", "вы"),
        ):
            for key, value in (effects.get(section) or {}).items():
                amount = _as_float(value)
                if abs(amount) < 1e-9:
                    continue
                lines.append(
                    "%s · %s"
                    % (
                        label,
                        effect_phrase(
                            self.relation_stat_label(key), amount
                        ),
                    )
                )
        return lines

    def preview(self, action_id, target_id=None, target_ref=None):
        action = self.actions.get(_text(action_id))
        if action is None:
            return None
        context = self.player_context()
        target = (
            context["node"]
            if action.get("target", {}).get("self") and context
            else (
                self.entity(target_ref)
                if target_ref is not None
                else self.node(target_id)
            )
        )
        enabled, reason = self.validate(
            action["id"],
            target["id"] if target else None,
            context,
            target_ref=(
                None
                if action.get("target", {}).get("self")
                else target_ref
            ),
        )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        return {
            "action": action,
            "target": target,
            "target_label": (
                target.get("name") or target.get("label")
                if target
                else "своя должность"
            ),
            "enabled": enabled,
            "reason": reason,
            "cost": self._cost_text(action),
            "immediate": self._effect_lines(action.get("immediate")),
            "success_chance": _as_float(
                success.get("chance"), action.get("success_chance", 0.6)
            ),
            "success_text": _text(success.get("text")),
            "success_effects": self._effect_lines(success.get("effects")),
            "failure_chance": _as_float(
                failure.get("chance"),
                max(0.0, 1.0 - _as_float(action.get("success_chance"), 0.6)),
            ),
            "failure_text": _text(failure.get("text")),
            "failure_effects": self._effect_lines(failure.get("effects")),
            "immediate_map": action.get("immediate") or {},
            "success_effects_map": success.get("effects") or {},
            "failure_effects_map": failure.get("effects") or {},
        }

    def _apply_stat_map(self, node, changes):
        if node is None:
            return []
        stats = node.get("stats")
        if not isinstance(stats, dict):
            return []
        changed = []
        for key, value in (changes or {}).items():
            if key not in stats:
                continue
            before = stats[key]
            stats[key] = _clamp(before + _as_float(value))
            delta = stats[key] - before
            if abs(delta) > 1e-9:
                changed.append(
                    ("%s · %s" % (node["name"], self.stat_label(key)), delta)
                )
        return changed

    def _apply_character_map(self, character, changes):
        """Аддитивные эффекты на конкретного человека мира (P3/P4).

        F-20: набор осей берётся из конфига мира, поэтому романтическая,
        семейная, обрядовая и вассальная оси не требуют правки Python.
        """
        if character is None:
            return []
        changed = []
        for key in self.relation_axis_ids:
            value = (changes or {}).get(key)
            if value is None:
                continue
            before = _as_float(character.get(key), 0.0)
            character[key] = _clamp(before + _as_float(value), -1.0, 1.0)
            delta = character[key] - before
            if abs(delta) > 1e-9:
                changed.append(
                    (
                        "%s · %s"
                        % (
                            character.get("name", character["id"]),
                            self.relation_axis_labels.get(key, key),
                        ),
                        delta,
                    )
                )
        for key, limit, label in (
            ("health", HEALTH_MAX, "здоровье"),
            ("sickness", SICKNESS_MAX, "болезнь"),
            ("wound", CAMPAIGN_WOUND_MAX, "рана"),
        ):
            value = (changes or {}).get(key)
            if value is None:
                continue
            before = _as_float(character.get(key), 0.0)
            character[key] = _clamp(before + _as_float(value), 0.0, limit)
            delta = character[key] - before
            if abs(delta) > 1e-9:
                changed.append(
                    (
                        "%s · %s"
                        % (character.get("name", character["id"]), label),
                        delta,
                    )
                )
        if "health" in (changes or {}):
            character["alive"] = _as_float(character.get("health"), 0.0) > 0.0
        if hasattr(character, "sync"):
            character.sync()
        return changed

    def _apply_player_map(self, changes):
        changed = []
        for key, value in (changes or {}).items():
            if key not in self.player_resources:
                continue
            before = self.player_resources[key]
            self.player_resources[key] = _clamp(before + _as_float(value))
            delta = self.player_resources[key] - before
            if abs(delta) > 1e-9:
                changed.append((self.stat_label(key), delta))
        return changed

    def _apply_legitimacy_recovery(self):
        """Вернуть структуре немного легитимности за спокойные сутки.

        Восстановление не работает ниже порога распада: организация,
        потерявшая силу/связность, не должна «самолечиться». Смена роли
        (§7 №29) получает передышку, а дорогие действия по-прежнему
        остаются реальной ценой.
        """
        if not self.attached or not self.player_alive:
            return []
        node = self.node(self.player_node_id)
        if node is None:
            return []
        stats = node["stats"]
        if self.legitimacy_recovery <= 0.0:
            return []
        if (
            float(stats["power"]) <= self.collapse_min_power
            or float(stats["cohesion"]) <= self.collapse_min_cohesion
        ):
            return []
        before = float(stats["legitimacy"])
        stats["legitimacy"] = _clamp(
            before + self.legitimacy_recovery
        )
        delta = stats["legitimacy"] - before
        if abs(delta) <= 1e-9:
            return []
        return [("%s · %s" % (node["name"], self.stat_label("legitimacy")),
                 delta)]

    def _apply_organizational_drift(self):
        """Экономика распада: связность и сила следуют за легитимностью.

        Ниже `DISMISSAL_LEGITIMACY` структура теряет связность, ниже
        `COLLAPSE_LEGITIMACY` — ещё и силу; пустая казна ускоряет эрозию.
        Здоровая легитимность и казна медленно возвращают обе шкалы.
        Порог `COLLAPSE_*` остаётся единственным критерием распада: дрейф
        лишь приближает или отодвигает его, поэтому распад становится
        процессом, а не случайным срезом одной шкалы.
        """
        if not self.attached or not self.player_alive:
            return []
        if not self.organizational_drift:
            return []
        node = self.node(self.player_node_id)
        if node is None:
            return []
        stats = node["stats"]
        legitimacy = float(stats["legitimacy"])
        wealth = float(stats["wealth"])
        cohesion = float(stats["cohesion"])
        power = float(stats["power"])
        d_cohesion = 0.0
        d_power = 0.0
        if legitimacy <= self.collapse_legitimacy:
            d_cohesion -= DECAY_CRISIS_COHESION
            d_power -= DECAY_CRISIS_POWER
        elif legitimacy <= self.dismissal_legitimacy:
            d_cohesion -= DECAY_STRAIN_COHESION
            d_power -= DECAY_STRAIN_POWER
        if wealth <= self.decay_broke_wealth:
            d_cohesion -= DECAY_BROKE_COHESION
        if (
            legitimacy >= DECAY_RECOVERY_LEGITIMACY
            and wealth > self.decay_broke_wealth
            and power > self.collapse_min_power
            and cohesion > self.collapse_min_cohesion
        ):
            d_cohesion += DECAY_RECOVERY_COHESION
            d_power += DECAY_RECOVERY_POWER
        changed = []
        scale = self.organizational_drift_scale
        for key, delta in (
            ("cohesion", d_cohesion * scale),
            ("power", d_power * scale),
        ):
            if abs(delta) <= 1e-9:
                continue
            before = float(stats[key])
            stats[key] = _clamp(before + delta)
            actual = stats[key] - before
            if abs(actual) > 1e-9:
                changed.append(
                    (
                        "%s · %s" % (node["name"], self.stat_label(key)),
                        actual,
                    )
                )
        return changed

    def _apply_daily_income(self):
        """Дневной доход должности — политическая проекция `E`.

        Влияние и связи не являются отдельным бюджетом действий: бюджет —
        это `E`/`actions_left`. Доход лишь возвращает политический ресурс,
        который тратят действия, чтобы `E` оставался реальным ограничением,
        а не маскировался пустой казной героя. Без должности или после
        смерти дохода нет.
        """
        if not self.attached or not self.player_alive:
            return []
        income = (
            (
                "influence",
                CAMPAIGN_INFLUENCE_INCOME
                + CAMPAIGN_INFLUENCE_PER_AUTHORITY * self.player_authority,
            ),
            (
                "favor",
                CAMPAIGN_FAVOR_INCOME
                + CAMPAIGN_FAVOR_PER_STANDING
                * self.player_resources["standing"],
            ),
        )
        changed = []
        for key, amount in income:
            before = self.player_resources[key]
            self.player_resources[key] = _clamp(before + amount)
            delta = self.player_resources[key] - before
            if abs(delta) > 1e-9:
                changed.append((self.stat_label(key), delta))
        return changed

    def _consume_item(self, item_id):
        item_id = _text(item_id)
        if item_id not in self.player_item_ids:
            return False
        self.player_item_ids = [
            value for value in self.player_item_ids if value != item_id
        ]
        self.granted_items.discard(item_id)
        self.consumed_items.add(item_id)
        self.log.append(
            {
                "day": self.day,
                "kind": "item",
                "text": "израсходован предмет: %s"
                % self.item_label(item_id),
            }
        )
        return True

    def _apply_item_work(self, spec, context, target):
        """Запустить обработчик предмета-автомата (P4)."""
        if not spec:
            return []
        entries = spec if isinstance(spec, list) else [spec]
        changed = []
        for entry in entries:
            if isinstance(entry, str):
                entry = {"handler": entry}
            if not isinstance(entry, dict):
                continue
            item_id = _text(entry.get("id"))
            if item_id in ("", "$target"):
                if self._entity_kind(target) != "item":
                    continue
                item_id = _text(target.get("id"))
            automaton = self.item_automata.get(item_id)
            if automaton is None:
                continue
            handler = _text(entry.get("handler"))
            payload, reason = apply_item_handler(
                automaton, handler, self.day
            )
            if payload is None:
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "item",
                        "text": "предмет не сработал: %s (%s)"
                        % (self.item_label(item_id), reason),
                    }
                )
                continue
            effects = dict(payload.get("effects") or {})
            effects.pop("item_work", None)
            changed.extend(
                self._apply_effects(
                    effects, context, target, is_player=True
                )
            )
            if payload.get("consume"):
                self._consume_item(item_id)
        return changed

    def _apply_item_effects(self, spec):
        """Выдать или забрать предметы игрока (P4)."""
        if not spec:
            return []
        entries = spec if isinstance(spec, list) else [spec]
        for entry in entries:
            if isinstance(entry, str):
                action, item_id = "grant", entry
            elif isinstance(entry, dict):
                action = _text(entry.get("action"), "grant")
                item_id = _text(entry.get("id") or entry.get("item_id"))
            else:
                continue
            if not item_id or item_id not in self.item_catalog:
                continue
            if action in ("grant", "add"):
                if item_id not in self.player_item_ids:
                    self.player_item_ids.append(item_id)
                    self.granted_items.add(item_id)
                    self.consumed_items.discard(item_id)
                    self._reset_item_automaton(item_id)
                    self.log.append(
                        {
                            "day": self.day,
                            "kind": "item",
                            "text": "получен предмет: %s"
                            % self.item_label(item_id),
                        }
                    )
            elif action in ("take", "consume", "remove"):
                if item_id in self.player_item_ids:
                    self.player_item_ids = [
                        value
                        for value in self.player_item_ids
                        if value != item_id
                    ]
                    self.granted_items.discard(item_id)
                    self.consumed_items.add(item_id)
                    self.log.append(
                        {
                            "day": self.day,
                            "kind": "item",
                            "text": "израсходован предмет: %s"
                            % self.item_label(item_id),
                        }
                    )
        return []

    def _apply_norm_effects(self, spec, target=None):
        """Создать, изменить или отменить норму мира (P4)."""
        if not spec:
            return []
        entries = spec if isinstance(spec, list) else [spec]
        fields = ("label", "domain", "status", "scope", "description")
        for entry in entries:
            if isinstance(entry, str):
                entry = {"id": entry}
            if not isinstance(entry, dict):
                continue
            norm_id = _text(entry.get("id"))
            if norm_id == "$target":
                if self._entity_kind(target) != "norm":
                    continue
                norm_id = _text(target.get("id"))
            if not norm_id:
                continue
            norm = self.norms.get(norm_id)
            if norm is None:
                norm = {
                    "id": norm_id,
                    "label": _text(entry.get("label"), norm_id),
                    "domain": _text(entry.get("domain"), "order"),
                    "status": _text(entry.get("status"), "active"),
                    "scope": _text(entry.get("scope")),
                    "description": _text(entry.get("description")),
                }
                self.norms[norm_id] = norm
                self.norm_order.append(norm_id)
                self._entity_kinds[id(norm)] = "norm"
                text = "принята норма: %s" % norm["label"]
            else:
                for key in fields:
                    if key in entry:
                        norm[key] = _text(entry.get(key), norm.get(key, ""))
                if norm.get("status") in ("repealed", "revoked", "inactive"):
                    text = "отменена норма: %s" % norm.get(
                        "label", norm_id
                    )
                else:
                    text = "изменена норма: %s" % norm.get("label", norm_id)
            self.log.append({"day": self.day, "kind": "norm", "text": text})
        return []

    def _apply_obligation_effects(self, spec, target=None):
        """Создать обязательство из эффекта действия (P4)."""
        if not spec:
            return []
        entries = spec if isinstance(spec, list) else [spec]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            creditor = _text(entry.get("creditor"), "player")
            debtor = _text(entry.get("debtor"))
            if not debtor and self._entity_kind(target) == "character":
                debtor = _text(target.get("id"))
            if not debtor or creditor == debtor:
                continue
            due_in_days = entry.get("due_in_days")
            due_day = (
                self.day + max(0, _as_int(due_in_days))
                if due_in_days is not None
                else None
            )
            try:
                self.add_obligation(
                    creditor,
                    debtor,
                    _text(entry.get("kind"), DEFAULT_OBLIGATION_KIND),
                    _as_float(entry.get("amount"), 1.0),
                    due_day=due_day,
                    note=_text(entry.get("note")),
                )
            except CampaignError:
                continue
        return []

    def _apply_effects(self, effects, context, target, is_player=True):
        effects = effects or {}
        changed = []
        changed.extend(
            self._apply_stat_map(context["node"], effects.get("node"))
        )
        if self._entity_kind(target) == "character":
            changed.extend(
                self._apply_character_map(target, effects.get("target"))
            )
        else:
            changed.extend(
                self._apply_stat_map(target, effects.get("target"))
            )
        if is_player:
            changed.extend(self._apply_player_map(effects.get("player")))
            self._apply_item_effects(
                effects.get("item") or effects.get("items")
            )
            changed.extend(
                self._apply_item_work(
                    effects.get("item_work"), context, target
                )
            )
            self._apply_norm_effects(
                effects.get("norm") or effects.get("norms"), target
            )
            self._apply_obligation_effects(
                effects.get("obligation") or effects.get("obligations"),
                target,
            )
        relation = _as_float(effects.get("relation"), 0.0)
        if (
            target is not None
            and self._entity_kind(target) in ("institution", "asset")
            and (
                abs(relation) > 1e-9
                or effects.get("relation_back") is not None
                or effects.get("relation_axes")
                or effects.get("relation_axes_back")
            )
        ):
            source = context["node"]
            self._shift_relation(
                source,
                target,
                affinity=relation,
                affinity_back=effects.get("relation_back"),
                axes=effects.get("relation_axes"),
                axes_back=effects.get("relation_axes_back"),
            )
        if effects.get("ending"):
            self._apply_ending(effects.get("ending"), effects.get("text"))
        return self._merge_changes(changed)

    def _world_form(self, action):
        return str(
            action.get("form")
            or self.work_config.get("default_form")
            or "world"
        )

    def _branch_effects(self, action, success):
        branch = (
            action.get("success") if success else action.get("failure")
        ) or {}
        return branch.get("effects") or {}

    def _world_report(self, action, context, target, success):
        """Собрать ``Work`` для действия мира и принять его обработчиком.

        Действие больше не применяет ``success.effects`` напрямую: оно
        строит ``WorkPlan`` и идёт через тот же ``receive``, что и
        кампания автоматов. Если для мира нет обработчика (старый
        пользовательский мир), сохраняется совместимый откат к эффектам
        ветки из записи действия.
        """
        plan = build_work(
            action,
            context.get("node"),
            target,
            self,
            default_amount=_as_float(
                self.work_config.get("default_amount"), 0.01
            ),
            default_form=self._world_form(action),
        )
        if plan is None:
            return None
        try:
            return self.world_handlers.receive(
                plan.to_work(),
                plan,
                context.get("node"),
                target,
                self,
                success=success,
            )
        except Exception as exc:  # pragma: no cover - защитный откат
            now = time.time()
            if now - getattr(self, "_last_world_work_warning", 0.0) > 60:
                self._last_world_work_warning = now
                logger.warning("Обработчик мира не сработал: %s", exc)
            return None

    def _world_effects(
        self, action, context, target, success, is_player=True
    ):
        report = self._world_report(action, context, target, success)
        effects = dict(report.effect) if report and report.effect else {}
        if not effects:
            effects = self._branch_effects(action, success)
        return self._apply_effects(
            effects, context, target, is_player=is_player
        )

    def _world_character_effects(
        self, action, context, character, success
    ):
        report = self._world_report(action, context, character, success)
        effects = dict(report.effect) if report and report.effect else {}
        if not effects:
            effects = self._branch_effects(action, success)
        return self._apply_character_effects(effects, character)

    def _roll(self, token):
        digest = hashlib.sha256(
            ("%s:%s" % (self.seed, token)).encode("utf-8")
        ).hexdigest()
        return int(digest[:12], 16) / float(16**12)

    def _apply_action_wound(self, action, outcome):
        """Устойчивая рана за провал рискованного действия.

        Только действия с `wound_risk` (или из списка `WOUND_RISKY_ACTIONS`)
        и только при `outcome == "failure"` могут ранить: политические ходы
        не должны калечить героя. Тяжесть раны снижается ловкостью
        (`CAMPAIGN_WOUND_DODGE_SKILL`), как на арене сила снижает шанс
        попадания. Бросок — `_roll`, поэтому исход воспроизводим seed'ом.
        """
        if outcome != "failure" or not _is_wound_risky(action):
            return []
        if not self.player_alive:
            return []
        roll = self._roll(
            "action-wound:%s:%s:%s"
            % (self.day, action.get("id"), self.action_count)
        )
        if roll >= CAMPAIGN_ACTION_WOUND_CHANCE:
            return []
        dexterity = _profile_skill(self.profile, CAMPAIGN_WOUND_DODGE_SKILL)
        severity = CAMPAIGN_ACTION_WOUND_SEVERITY * max(
            0.25, 1.0 - 0.5 * dexterity
        )
        before_health = self.player_health
        wound_value = self.injure_player(severity)
        if wound_value is None:
            return []
        self.player_health = max(
            0.0, self.player_health - CAMPAIGN_ACTION_WOUND_DAMAGE
        )
        health_delta = self.player_health - before_health
        name = _text(self.profile.get("name"), "Герой")
        self.log.append(
            {
                "day": self.day,
                "kind": "wound",
                "text": "%s: неудача обошлась раной." % name,
            }
        )
        changed = [("герой · рана", float(wound_value))]
        if health_delta < 0.0:
            changed.append(("герой · здоровье", health_delta))
        if self.player_health <= 0.0:
            self.player_alive = False
            self.outcome = "lose"
            self.finished = True
            self.log.append(
                {
                    "day": self.day,
                    "kind": "death",
                    "text": "Герой умер от полученной раны.",
                }
            )
        return changed

    @staticmethod
    def _unit_from_node(node, authority=0.0):
        """Автомат-защитник из легаси-статистики узла.

        Кампанийные `power/cohesion/...` остаются проекциями канала form,
        но для броска успеха они переводятся в `F/E` и навыки `Automaton`,
        чтобы использовать ту же `success_probability`, что и арена.
        """
        stats = (node or {}).get("stats") or {}
        return Automaton(
            id=_text((node or {}).get("id"), "target"),
            force=_clamp(_as_float(stats.get("power"), 0.5)),
            max_force=1.0,
            energy=_clamp(_as_float(stats.get("capacity"), 0.5)),
            max_energy=1.0,
            skills={
                "force": _clamp(_as_float(stats.get("cohesion"), 0.5)),
                "info": _clamp(_as_float(stats.get("legitimacy"), 0.5)),
            },
            authority=_clamp(authority),
        )

    def _relation_axes_to_actor(self, target, actor_id):
        """Оси отношения цели к действующему автомату (R_target→actor).

        Для персонажа это легаси-поля `affinity/trust/fear/respect`
        (они хранят чувства персонажа к игроку), для узла — полные оси
        `relation_axes(target, actor)`. Направление важно: принуждение
        повышает страх цели, а не её доверие к себе.
        """
        if target is None:
            return {}
        target_id = _text(target.get("id"))
        if not target_id or target_id == _text(actor_id):
            return {}
        if hasattr(target, "sync"):
            return {
                axis: _as_float(target.get(axis), 0.0)
                for axis in self.relation_axis_ids
            }
        return self.relation_axes(target_id, actor_id)

    def _action_chance(
        self, action, target, context, success, is_player
    ):
        base = _as_float(
            success.get("chance"), action.get("success_chance", 0.6)
        )
        if is_player:
            attacker = self.player
        else:
            attacker = self._unit_from_node(
                context["node"], context.get("authority", 0.0)
            )
        if target is None or target.get("id") == context["node"]["id"]:
            defender = self._unit_from_node(
                context["node"], context.get("authority", 0.0)
            )
        elif hasattr(target, "sync"):
            defender = target.sync()
        elif isinstance(target.get("stats"), dict):
            defender = self._unit_from_node(target)
        else:
            defender = self._unit_from_node(
                context["node"], context.get("authority", 0.0)
            )
        form = _text(action.get("form"), DEFAULT_RELATION_FORM)
        relation_shift = relation_effect(
            self._relation_axes_to_actor(target, context["node"]["id"]),
            form,
            weights=self.relation_effect_weights,
            limit=self.relation_effect_limit,
        )
        return campaign_success_chance(
            base + relation_shift,
            attacker,
            defender,
            form=form,
            amount=0.0,
            coefficients=resolve_success_coefficients(action),
        )

    def _pay_cost(self, action, context):
        for key, value in (action.get("cost") or {}).get("node", {}).items():
            if key in context["node"]["stats"]:
                context["node"]["stats"][key] = _clamp(
                    context["node"]["stats"][key] - _as_float(value)
                )
        if context.get("is_player"):
            for key, value in (
                (action.get("cost") or {}).get("player", {}).items()
            ):
                if key in self.player_resources:
                    self.player_resources[key] = _clamp(
                        self.player_resources[key] - _as_float(value)
                    )
            paid_items = {
                _text(item_id)
                for item_id in (action.get("cost") or {}).get("items") or ()
            }
            if paid_items:
                self.player_item_ids = [
                    item_id
                    for item_id in self.player_item_ids
                    if item_id not in paid_items
                ]
                for item_id in paid_items:
                    self.granted_items.discard(item_id)
                    self.consumed_items.add(item_id)

    def execute(self, action_id, target_id=None, target_ref=None):
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        action = self.actions.get(_text(action_id))
        if action is None:
            return {"ok": False, "reason": "неизвестное действие"}
        context = self.player_context()
        if context is None:
            return {"ok": False, "reason": "сначала выберите должность"}
        target = (
            context["node"]
            if action.get("target", {}).get("self")
            else (
                self.entity(target_ref)
                if target_ref is not None
                else self.node(target_id)
            )
        )
        enabled, reason = self.validate(
            action["id"],
            target["id"] if target else None,
            context,
            target_ref=(
                None
                if action.get("target", {}).get("self")
                else target_ref
            ),
        )
        if not enabled:
            return {"ok": False, "reason": reason}
        if action.get("career"):
            available, career_reason = self._career_target_available(
                action, target
            )
            if not available:
                return {"ok": False, "reason": career_reason}
        self._pay_cost(action, context)
        changed = self._apply_effects(
            action.get("immediate"), context, target, is_player=True
        )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        chance = self._action_chance(
            action, target, context, success, is_player=True
        )
        roll = self._roll(
            "player:%s:%s:%s:%s"
            % (
                self.day,
                action["id"],
                target["id"] if target else "-",
                self.action_count,
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
                is_player=True,
            )
        )
        changed.extend(
            self._grow_player_skills(
                action, target, success=(outcome == "success")
            )
        )
        changed.extend(self._apply_action_wound(action, outcome))
        changed = self._merge_changes(changed)
        career_text = ""
        if outcome == "success" and action.get("career"):
            career_text = self._career_transition(action, target)
        if outcome == "failure" and action.get("career") == "resign":
            career_text = self._career_transition(action, target)
        self.player.spend_action()
        self.action_count += 1
        cooldown = _as_int(action.get("cooldown_days"), 0)
        if cooldown:
            self.cooldowns[
                "%s:%s" % (action["id"], target["id"] if target else "")
            ] = self.day
        if action.get("once"):
            self.used_actions.append(action["id"])
        text = _text(branch.get("text"), action.get("description", ""))
        if career_text:
            text = "%s %s" % (text, career_text) if text else career_text
        result = {
            "ok": True,
            "action": action["id"],
            "action_label": _text(action.get("label"), action["id"]),
            "target": target["id"] if target else "",
            "target_label": (
                target.get("name") or target.get("label")
                if target
                else "своя должность"
            ),
            "outcome": outcome,
            "chance": chance,
            "roll": roll,
            "margin": success_margin(chance, roll),
            "text": text,
            "changes": changed,
            "day": self.day,
            "ending": self.ending,
        }
        self.last_result = result
        self.log.append(
            {
                "day": self.day,
                "kind": outcome,
                "text": "%s → %s: %s"
                % (
                    result["action_label"],
                    result["target_label"],
                    text,
                ),
            }
        )
        self._check_dismissal()
        return result
