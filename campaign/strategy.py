from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from .errors import CampaignError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STRATEGY_PATH = ROOT / "configs" / "strategy" / "agora_charter.json"
TYPE_ORDER = ("character", "organization", "asset", "institution")
TYPE_STATS = {
    "character": {"loyalty": 0.5, "leverage": 0.5},
    "organization": {"loyalty": 0.5, "capacity": 0.5},
    "asset": {"control": 0.5, "condition": 0.5},
    "institution": {"support": 0.5, "capture": 0.5},
}
PLAYER_ORG_LOYALTY = 0.74
RIVAL_ORG_LOYALTY = 0.34


class StrategyError(CampaignError):
    pass


def _clamp(value, low=0.0, high=1.0):
    return max(float(low), min(float(high), float(value)))


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def load_strategy(path=None):
    target = Path(path) if path is not None else DEFAULT_STRATEGY_PATH
    if not target.is_absolute():
        target = ROOT / target
    try:
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise StrategyError("файл стратегии не найден: %s" % target)
    except Exception as exc:
        raise StrategyError(
            "не удалось прочитать стратегию %s: %s" % (target, exc)
        )
    if not isinstance(data, dict):
        raise StrategyError("стратегия должна быть объектом")
    if not data.get("actions"):
        raise StrategyError("в стратегии нет действий")
    if not data.get("entities") and not data.get("character_stats"):
        raise StrategyError("в стратегии нет доступных сущностей")
    return data


def _preset_parts(preset):
    if preset is None:
        return {}, [], []
    if hasattr(preset, "player_faction"):
        faction = preset.player_faction or {}
        organizations = list(getattr(preset, "organizations", []) or [])
        characters = list(getattr(preset, "characters", []) or [])
        return faction, organizations, characters
    if isinstance(preset, dict):
        faction_id = preset.get("player_faction_id")
        factions = preset.get("factions") or []
        faction = next(
            (item for item in factions if item.get("id") == faction_id),
            {},
        )
        return (
            dict(faction or {}),
            list(preset.get("organizations") or []),
            list(preset.get("characters") or []),
        )
    return {}, [], []


def _preset_seed(preset, fallback):
    if preset is None:
        return int(fallback)
    if hasattr(preset, "seed"):
        return int(getattr(preset, "seed", fallback))
    if isinstance(preset, dict):
        return _as_int(preset.get("seed"), fallback)
    return int(fallback)


class StrategyEngine:

    def __init__(self, config, preset=None, seed=None, snapshot=None):
        self.config = config
        self.preset = preset
        self.seed = _preset_seed(preset, 7 if seed is None else seed)
        self.days = max(1, _as_int(config.get("days"), 10))
        self.actions_per_day = max(
            1, _as_int(config.get("actions_per_day"), 3)
        )
        self.actions = {
            item.get("id"): dict(item)
            for item in (config.get("actions") or [])
            if item.get("id")
        }
        self.resource_defs = dict(config.get("resources") or {})
        self.resource_labels = {
            key: value.get("label", key)
            for key, value in self.resource_defs.items()
        }
        self.type_labels = dict(config.get("type_labels") or {})
        self.stat_labels = dict(config.get("stat_labels") or {})
        self.subtype_labels = dict(config.get("subtype_labels") or {})
        self.character_stats = dict(config.get("character_stats") or {})
        faction, _organizations, _characters = _preset_parts(preset)
        self.player_side = faction.get("side", "red")
        self.entities = {}
        self.entity_order = []
        self.player_character_record = {
            "id": _characters[0].get("id") if _characters else "player",
            "name": (
                _characters[0].get("name")
                if _characters
                else "Действующее лицо"
            ),
            "role": _characters[0].get("post") if _characters else "мандат",
            "side": self.player_side,
            "type": "character",
        }
        self._build_entities()
        self.day = 1
        self.actions_left = self.actions_per_day
        self.action_count = 0
        self.resources = self._initial_resources()
        self.obligations = []
        self.pending = []
        self.used_actions = []
        self.cooldowns = {}
        self.log = []
        self.last_result = None
        self.outcome = None
        self.finished = False
        self._opening()
        if snapshot:
            self.load_snapshot(snapshot)

    def _initial_resources(self):
        faction, _organizations, _characters = _preset_parts(self.preset)
        assets = faction.get("assets") or {}
        values = {}
        for key, definition in self.resource_defs.items():
            default = _as_float(definition.get("initial"), 0.45)
            values[key] = _clamp(assets.get(key, default))
        return values

    def _add_entity(self, entity):
        entity_id = str(entity.get("id") or "")
        if not entity_id or entity_id in self.entities:
            return
        entity_type = str(entity.get("type") or "character")
        stats = dict(TYPE_STATS.get(entity_type, {}))
        stats.update(entity.get("stats") or {})
        record = dict(entity)
        record["id"] = entity_id
        record["type"] = entity_type
        record["stats"] = {key: _clamp(value) for key, value in stats.items()}
        record.setdefault("side", "shared")
        record.setdefault("tags", [])
        record.setdefault("description", "")
        record.setdefault("revealed", False)
        self.entities[entity_id] = record
        self.entity_order.append(entity_id)

    def _build_entities(self):
        faction, organizations, characters = _preset_parts(self.preset)
        player_faction_id = faction.get("id")
        player_side = faction.get("side", "red")
        for organization in organizations:
            side = organization.get("side")
            is_player = organization.get("faction_id") == player_faction_id
            summary = organization.get("summary") or []
            description = " ".join(str(item) for item in summary[:2])
            self._add_entity(
                {
                    "id": organization.get("id"),
                    "name": organization.get("name"),
                    "type": "organization",
                    "subtype": "coalition",
                    "side": side,
                    "description": description
                    or (
                        "Гражданская организация, участвующая "
                        "в согласовании Хартии."
                    ),
                    "tags": ["organization", "coalition"],
                    "stats": {
                        "loyalty": (
                            PLAYER_ORG_LOYALTY
                            if is_player
                            else RIVAL_ORG_LOYALTY
                        ),
                        "capacity": 0.58,
                    },
                    "hidden_agenda": (
                        "Организация поддержит Хартию, если сохранит право "
                        "распоряжаться своими людьми и средствами."
                    ),
                }
            )
        self.player_character_record = next(
            (
                item
                for item in characters
                if item.get("side") == player_side and item.get("is_player")
            ),
            self.player_character_record,
        )
        player_chars = [
            item
            for item in characters
            if item.get("side") == player_side and not item.get("is_player")
        ]
        other_chars = [
            item for item in characters if item.get("side") != player_side
        ]
        chosen = []
        chosen.extend(player_chars[:4])
        chosen.extend(other_chars[:3])
        for character in chosen:
            post_id = str(
                character.get("post_id") or character.get("role") or "line"
            )
            stats = dict(self.character_stats.get(post_id) or {})
            if not stats:
                stats = dict(self.character_stats.get("line") or {})
            self._add_entity(
                {
                    "id": character.get("id"),
                    "name": character.get("name"),
                    "type": "character",
                    "subtype": post_id,
                    "side": character.get("side"),
                    "role": character.get("post") or "Делегат",
                    "description": (
                        character.get("biography")
                        or "Участник городских переговоров."
                    ),
                    "tags": ["character", post_id],
                    "stats": stats,
                    "is_player": bool(character.get("is_player")),
                    "hidden_agenda": (
                        "Личный интерес: сохранить место в новой системе "
                        "и не потерять сторонников."
                    ),
                }
            )
        for item in self.config.get("entities") or []:
            self._add_entity(item)

    def _opening(self):
        for text in self.config.get("opening_log") or []:
            self.log.append({"day": self.day, "kind": "opening", "text": text})

    def entity(self, entity_id):
        return self.entities.get(str(entity_id or ""))

    @property
    def player_character(self):
        return self.player_character_record

    @property
    def available_entity_count(self):
        return len(self.entities)

    def resource(self, key):
        return float(self.resources.get(key, 0.0))

    def resource_text(self, key):
        return "%.0f%%" % (100.0 * self.resource(key))

    def entity_label(self, entity_id):
        entity = self.entity(entity_id)
        if not entity:
            return "—"
        return str(entity.get("name") or entity_id)

    def entity_type_label(self, entity_type):
        return self.type_labels.get(entity_type, entity_type)

    def stat_label(self, key):
        return self.stat_labels.get(key, key)

    def subtype_label(self, key):
        return self.subtype_labels.get(key, key)

    def entity_stat(self, entity_id, key):
        entity = self.entity(entity_id) or {}
        return _as_float((entity.get("stats") or {}).get(key), 0.0)

    def sorted_entities(self):
        priority = {item: index for index, item in enumerate(TYPE_ORDER)}

        def key(entity_id):
            entity = self.entities[entity_id]
            side = entity.get("side")
            if side == self.player_side:
                side_rank = 0
            elif side == "shared":
                side_rank = 1
            else:
                side_rank = 2
            return (
                priority.get(entity.get("type"), 99),
                side_rank,
                self.entity_order.index(entity_id),
            )

        return [
            self.entities[item] for item in sorted(self.entity_order, key=key)
        ]

    def _cost_available(self, action):
        for key, value in (action.get("cost") or {}).items():
            if key not in self.resources:
                continue
            if self.resource(key) + 1e-9 < _as_float(value):
                return (
                    False,
                    "недостаточно ресурса «%s»"
                    % self.resource_labels.get(key, key),
                )
        return True, ""

    def _requirements_available(self, action, target):
        requires = action.get("requires") or {}
        for key, value in (requires.get("resource_min") or {}).items():
            if self.resource(key) + 1e-9 < _as_float(value):
                return False, "нужно больше «%s»" % self.resource_labels.get(
                    key, key
                )
        target_stats = (target or {}).get("stats") or {}
        for key, value in (requires.get("target_min") or {}).items():
            if _as_float(target_stats.get(key), 0.0) + 1e-9 < _as_float(value):
                return False, "нужна поддержка цели"
        return True, ""

    def action_options(self, entity_id):
        entity = self.entity(entity_id)
        if entity is None:
            return []
        options = []
        for action in self.actions.values():
            if entity.get("type") not in (action.get("target_types") or []):
                continue
            enabled = True
            reason = ""
            if self.actions_left <= 0:
                enabled = False
                reason = "действия на сегодня исчерпаны"
            elif action.get("once") and action.get("id") in self.used_actions:
                enabled = False
                reason = "действие уже использовано"
            else:
                cooldown = _as_int(action.get("cooldown_days"), 0)
                key = "%s:%s" % (action.get("id"), entity_id)
                last_day = self.cooldowns.get(key)
                if (
                    cooldown > 0
                    and last_day is not None
                    and self.day - int(last_day) < cooldown
                ):
                    enabled = False
                    reason = "повтор не раньше дня %d" % (
                        int(last_day) + cooldown
                    )
                else:
                    enabled, reason = self._cost_available(action)
                if enabled:
                    enabled, reason = self._requirements_available(
                        action, entity
                    )
            options.append(
                {
                    "action": action,
                    "id": action.get("id"),
                    "label": action.get("label", action.get("id")),
                    "enabled": enabled,
                    "reason": reason,
                }
            )
        return options

    def available_actions(self, entity_id):
        return [
            item["id"]
            for item in self.action_options(entity_id)
            if item.get("enabled")
        ]

    def _effect_texts(self, effects, target=None):
        lines = []
        resources = (effects or {}).get("resources") or {}
        for key, value in resources.items():
            amount = _as_float(value)
            if abs(amount) < 1e-9:
                continue
            lines.append(
                "%s %s%.0f%%"
                % (
                    self.resource_labels.get(key, key),
                    "+" if amount > 0 else "",
                    100.0 * amount,
                )
            )
        target_stats = (target or {}).get("stats") or {}
        target_effects = (effects or {}).get("target") or {}
        for key, value in target_effects.items():
            if target is not None and key not in target_stats:
                continue
            amount = _as_float(value)
            if abs(amount) < 1e-9:
                continue
            lines.append(
                "%s %s%.0f%%"
                % (
                    self.stat_label(key),
                    "+" if amount > 0 else "",
                    100.0 * amount,
                )
            )
        if (effects or {}).get("reveal"):
            lines.append("раскрывает скрытый интерес")
        return lines

    def preview(self, action_id, entity_id):
        action = self.actions.get(str(action_id or ""))
        entity = self.entity(entity_id)
        if action is None or entity is None:
            return None
        options = {item["id"]: item for item in self.action_options(entity_id)}
        option = options.get(action.get("id"), {})
        cost = []
        for key, value in (action.get("cost") or {}).items():
            cost.append(
                "%s −%.0f%%"
                % (
                    self.resource_labels.get(key, key),
                    100.0 * _as_float(value),
                )
            )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        delayed = action.get("delayed") or {}
        return {
            "action": action,
            "target": entity,
            "enabled": bool(option.get("enabled", False)),
            "reason": option.get("reason", ""),
            "cost": cost,
            "immediate": self._effect_texts(
                action.get("immediate"), target=entity
            ),
            "success_chance": _as_float(success.get("chance"), 0.0),
            "success_text": success.get("text", ""),
            "success_effects": self._effect_texts(
                success.get("effects"), target=entity
            ),
            "failure_chance": _as_float(failure.get("chance"), 0.0),
            "failure_text": failure.get("text", ""),
            "failure_effects": self._effect_texts(
                failure.get("effects"), target=entity
            ),
            "delayed_text": delayed.get("text", ""),
            "delayed_effects": self._effect_texts(delayed.get("effects")),
            "obligations": list(action.get("obligations_add") or []),
            "ends_game": (success or {}).get("ends_game", ""),
            "cooldown_days": _as_int(action.get("cooldown_days"), 0),
        }

    def _merge_changes(self, changed):
        merged = {}
        for label, value in changed:
            merged[label] = merged.get(label, 0.0) + float(value)
        return [
            (label, value)
            for label, value in merged.items()
            if abs(value) > 1e-9
        ]

    def _apply_effects(self, effects, target=None):
        effects = effects or {}
        changed = []
        for key, value in (effects.get("resources") or {}).items():
            if key not in self.resources:
                continue
            before = self.resource(key)
            self.resources[key] = _clamp(before + _as_float(value))
            changed.append(
                (
                    self.resource_labels.get(key, key),
                    self.resources[key] - before,
                )
            )
        if target is not None:
            for key, value in (effects.get("target") or {}).items():
                stats = target.setdefault("stats", {})
                if key not in stats:
                    continue
                before = _as_float(stats.get(key), 0.0)
                stats[key] = _clamp(before + _as_float(value))
                changed.append((self.stat_label(key), stats[key] - before))
            if effects.get("reveal"):
                target["revealed"] = True
        return changed

    def _roll(self, action_id, entity_id):
        token = "%s:%s:%s:%s:%s" % (
            self.seed,
            self.day,
            self.action_count,
            action_id,
            entity_id,
        )
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return int(digest[:12], 16) / float(16**12)

    def execute(self, action_id, entity_id):
        action = self.actions.get(str(action_id or ""))
        target = self.entity(entity_id)
        if action is None:
            return {"ok": False, "reason": "неизвестное действие"}
        if target is None:
            return {"ok": False, "reason": "неизвестная цель"}
        options = {item["id"]: item for item in self.action_options(entity_id)}
        option = options.get(action.get("id"))
        if option is None:
            return {"ok": False, "reason": "действие несовместимо с целью"}
        if not option.get("enabled"):
            return {"ok": False, "reason": option.get("reason", "недоступно")}

        for key, value in (action.get("cost") or {}).items():
            if key in self.resources:
                self.resources[key] = _clamp(
                    self.resource(key) - _as_float(value)
                )
        changed = self._apply_effects(action.get("immediate"), target)
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        chance = _as_float(success.get("chance"), 0.0)
        outcome = (
            "success"
            if self._roll(action_id, entity_id) < chance
            else "failure"
        )
        branch = success if outcome == "success" else failure
        changed.extend(self._apply_effects(branch.get("effects"), target))
        for obligation in action.get("obligations_add") or []:
            if obligation not in self.obligations:
                self.obligations.append(str(obligation))
        delayed = action.get("delayed") or {}
        if delayed:
            due_day = self.day + max(1, _as_int(delayed.get("days"), 2))
            self.pending.append(
                {
                    "due_day": due_day,
                    "text": delayed.get("text", ""),
                    "effects": delayed.get("effects") or {},
                }
            )
        self.actions_left = max(0, self.actions_left - 1)
        self.action_count += 1
        cooldown = _as_int(action.get("cooldown_days"), 0)
        if cooldown > 0:
            self.cooldowns["%s:%s" % (action.get("id"), entity_id)] = self.day
        if action.get("once"):
            self.used_actions.append(action.get("id"))
        text = branch.get("text") or action.get("description", "")
        result = {
            "ok": True,
            "action": action.get("id"),
            "action_label": action.get("label", action.get("id")),
            "target": entity_id,
            "target_label": target.get("name", entity_id),
            "outcome": outcome,
            "text": text,
            "changes": self._merge_changes(changed),
            "day": self.day,
        }
        self.last_result = result
        self.log.append(
            {
                "day": self.day,
                "kind": outcome,
                "text": "%s → %s: %s"
                % (action.get("label", action_id), target.get("name"), text),
            }
        )
        if outcome == "success" and branch.get("ends_game") == "win":
            self.outcome = "win"
            self.finished = True
        self._check_lose()
        return result

    def _check_lose(self):
        if self.outcome is not None:
            return
        for rule in (self.config.get("goals") or {}).get("lose", []):
            if "metric" in rule:
                value = self.resource(rule["metric"])
                if "at_most" in rule and value <= _as_float(rule["at_most"]):
                    self.outcome = "lose"
                    self.finished = True
                    return
            if "day_above" in rule and self.day > _as_int(
                rule["day_above"], 9999
            ):
                self.outcome = "lose"
                self.finished = True
                return

    def goals_met(self):
        for rule in (self.config.get("goals") or {}).get("win", []):
            value = self.resource(rule.get("metric"))
            if value + 1e-9 < _as_float(rule.get("at_least"), 0.0):
                return False
        return True

    def end_day(self):
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        texts = []
        changed = []
        due = [
            item for item in self.pending if item.get("due_day") <= self.day
        ]
        self.pending = [
            item for item in self.pending if item.get("due_day") > self.day
        ]
        for item in due:
            changed.extend(self._apply_effects(item.get("effects")))
            if item.get("text"):
                texts.append(str(item["text"]))
        daily = self.config.get("daily") or {}
        if daily:
            changed.extend(self._apply_effects({"resources": daily}))
        events = self.config.get("day_events") or []
        if events:
            event = events[(self.day - 1) % len(events)]
            changed.extend(self._apply_effects(event.get("effects")))
            texts.append(str(event.get("text", "")))
        self.day += 1
        self.actions_left = self.actions_per_day
        self._check_lose()
        if self.outcome is None and self.day > self.days:
            self.outcome = "lose"
            self.finished = True
        result = {
            "ok": True,
            "day": self.day,
            "text": " ".join(text for text in texts if text),
            "changes": self._merge_changes(changed),
        }
        if result["text"]:
            self.last_result = {
                "ok": True,
                "action": "end_day",
                "action_label": "Завершение дня",
                "target": "",
                "target_label": "",
                "outcome": "day",
                "text": result["text"],
                "changes": result["changes"],
                "day": result["day"],
            }
            self.log.append(
                {
                    "day": result["day"],
                    "kind": "day",
                    "text": result["text"],
                }
            )
        return result

    def to_dict(self):
        return {
            "seed": self.seed,
            "day": self.day,
            "actions_left": self.actions_left,
            "action_count": self.action_count,
            "resources": dict(self.resources),
            "entities": {
                key: {
                    "stats": dict(value.get("stats") or {}),
                    "revealed": bool(value.get("revealed")),
                }
                for key, value in self.entities.items()
            },
            "obligations": list(self.obligations),
            "pending": list(self.pending),
            "used_actions": list(self.used_actions),
            "cooldowns": dict(self.cooldowns),
            "log": list(self.log),
            "last_result": self.last_result,
            "outcome": self.outcome,
            "finished": self.finished,
        }

    def load_snapshot(self, snapshot):
        if not snapshot:
            return
        self.seed = _as_int(snapshot.get("seed"), self.seed)
        self.day = max(1, _as_int(snapshot.get("day"), self.day))
        self.actions_left = _as_int(
            snapshot.get("actions_left"), self.actions_left
        )
        self.action_count = _as_int(snapshot.get("action_count"), 0)
        for key, value in (snapshot.get("resources") or {}).items():
            if key in self.resources:
                self.resources[key] = _clamp(value)
        for entity_id, saved in (snapshot.get("entities") or {}).items():
            entity = self.entities.get(entity_id)
            if entity is None:
                continue
            for key, value in (saved.get("stats") or {}).items():
                if key in entity["stats"]:
                    entity["stats"][key] = _clamp(value)
            entity["revealed"] = bool(saved.get("revealed"))
        self.obligations = list(snapshot.get("obligations") or [])
        self.pending = list(snapshot.get("pending") or [])
        self.used_actions = list(snapshot.get("used_actions") or [])
        self.cooldowns = {
            str(key): _as_int(value)
            for key, value in (snapshot.get("cooldowns") or {}).items()
        }
        self.log = list(snapshot.get("log") or [])
        self.last_result = snapshot.get("last_result")
        self.outcome = snapshot.get("outcome")
        self.finished = bool(snapshot.get("finished", False))


def build_strategy(config, preset=None, seed=None, snapshot=None):
    return StrategyEngine(config, preset=preset, seed=seed, snapshot=snapshot)
