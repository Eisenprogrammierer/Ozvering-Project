"""Сериализация и загрузка состояния мира."""

from __future__ import annotations

from .world_support import (
    CAMPAIGN_WOUND_MAX,
    HEALTH_MAX,
    SCHEMA_VERSION,
    SICKNESS_MAX,
    _as_float,
    _as_int,
    _clamp,
    _text,
    item_automaton_snapshot,
    migrate_snapshot,
    normalize_profile,
    restore_item_automaton,
)


class WorldSnapshotMixin:

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "world_id": self.config.get("id"),
            "seed": self.seed,
            "day": self.day,
            "days": self.days,
            "actions_left": self.actions_left,
            "action_count": self.action_count,
            "scene": {
                "id": self.scene_id,
                "entered_day": int(self.scene_entered_day or 0),
            },
            "profile": dict(self.profile),
            "player": {
                "node_id": self.player_node_id,
                "office_id": self.player_office_id,
                "authority": self.player_authority,
                "resources": dict(self.player_resources),
                "career_history": list(self.career_history),
                "items": list(self.player_item_ids),
                "granted_items": sorted(self.granted_items),
                "consumed_items": sorted(self.consumed_items),
                "item_automata": {
                    item_id: item_automaton_snapshot(automaton)
                    for item_id, automaton in self.item_automata.items()
                },
                "health": float(self.player_health),
                "sickness": float(self.player_sickness),
                "wound": float(self.player_wound),
                "alive": bool(self.player_alive),
                "energy": float(self.player_energy),
                "max_energy": float(self.player_max_energy),
                "force": float(self.player_force),
                "max_force": float(self.player.max_force),
                "needs": dict(self.player.needs),
            },
            "characters": {
                character_id: dict(
                    {
                        axis: float(
                            _as_float(character.get(axis), 0.0)
                        )
                        for axis in self.relation_axis_ids
                    },
                    health=float(character["health"]),
                    sickness=float(character["sickness"]),
                    wound=float(_as_float(character.get("wound"), 0.0)),
                    alive=bool(character["alive"]),
                    needs=dict(character.needs),
                )
                for character_id, character in self.characters.items()
            },
            "player_relations": {
                character_id: {
                    axis: float(_as_float(view.get(axis), 0.0))
                    for axis in self.relation_axis_ids
                }
                for character_id, view in self.player_relations.items()
            },
            "nodes": {
                node_id: {
                    "stats": dict(node["stats"]),
                    "relations": dict(node["relations"]),
                    "relation_axes": {
                        other_id: {
                            axis: float(_as_float(axes.get(axis), 0.0))
                            for axis in self.relation_axis_ids
                        }
                        for other_id, axes in (
                            node.get("relation_axes") or {}
                        ).items()
                    },
                }
                for node_id, node in self.nodes.items()
            },
            "cooldowns": dict(self.cooldowns),
            "labor_negotiations": {
                office_id: {
                    rival_id: dict(record)
                    for rival_id, record in per_office.items()
                }
                for office_id, per_office in self.labor_negotiations.items()
            },
            "used_actions": list(self.used_actions),
            "log": list(self.log),
            "log_trimmed": int(self.log_trimmed),
            "last_result": self.last_result,
            "outcome": self.outcome,
            "finished": self.finished,
            "attached": self.attached,
            "infinite": bool(self.infinite),
            "horizon_passed": bool(self.horizon_passed),
            "ending": self.ending,
            "dismissed": bool(self.dismissed),
            "dismissal_count": int(self.dismissal_count),
            "last_role_change_day": int(self.last_role_change_day),
            "collapsed": bool(self.collapsed),
            "collapse_days": int(self.collapse_days),
            "storyline_days": int(self.storyline_days),
            "intents": self.intents.to_list(),
            "directives": self.directives.to_list(),
            "obligations": self.obligations.to_list(),
            "coalitions": self.coalitions.to_dict(),
            "node_action_day": dict(self.node_action_day),
            "node_strategy_state": {
                node_id: {
                    strategy_id: dict(state)
                    for strategy_id, state in per_node.items()
                }
                for node_id, per_node in self.strategy_state.items()
            },
        }

    def load_snapshot(self, snapshot):
        if not snapshot:
            return
        snapshot = migrate_snapshot(snapshot)
        self.seed = _as_int(snapshot.get("seed"), self.seed)
        self.day = max(1, _as_int(snapshot.get("day"), 1))
        self.days = max(1, _as_int(snapshot.get("days"), self.days))
        self.actions_left = _as_int(
            snapshot.get("actions_left"), self.actions_per_day
        )
        self.action_count = _as_int(snapshot.get("action_count"), 0)
        scene = snapshot.get("scene") or {}
        if scene:
            scene_id = _text(scene.get("id"))
            self.scene_id = (
                scene_id if self.scene_catalog.get(scene_id) else ""
            )
            self.scene_entered_day = _as_int(scene.get("entered_day"), 0)
        if snapshot.get("profile"):
            self.profile = normalize_profile(snapshot["profile"])
        player = snapshot.get("player") or {}
        self.player_node_id = _text(player.get("node_id"))
        self.player_office_id = _text(player.get("office_id"))
        self.player_authority = _as_float(player.get("authority"), 0.0)
        if "health" in player:
            self.player_health = _clamp(
                _as_float(player.get("health"), HEALTH_MAX),
                0.0,
                HEALTH_MAX,
            )
        if "sickness" in player:
            self.player_sickness = _clamp(
                _as_float(player.get("sickness"), 0.0),
                0.0,
                SICKNESS_MAX,
            )
        if "wound" in player:
            self.player_wound = _clamp(
                _as_float(player.get("wound"), 0.0),
                0.0,
                CAMPAIGN_WOUND_MAX,
            )
        if "alive" in player:
            self.player_alive = bool(player.get("alive"))
        else:
            self.player_alive = self.player_health > 0.0
        for key, value in (player.get("resources") or {}).items():
            if key in self.player_resources:
                self.player_resources[key] = _clamp(value)
        if "force" in player:
            self.player_resources["standing"] = _clamp(
                player.get("force", 0.0)
            )
        if "energy" in player:
            self.player_energy = _clamp(
                _as_float(player.get("energy"), 0.0),
                0.0,
                self.player_max_energy,
            )
        if "needs" in player:
            self.player.load_needs(player.get("needs"))
        self.career_history = list(player.get("career_history") or [])
        if "items" in player:
            self.player_item_ids = [
                str(item_id)
                for item_id in (player.get("items") or ())
                if str(item_id) in self.item_catalog
            ]
        if "granted_items" in player or "consumed_items" in player:
            self.granted_items = {
                str(item_id)
                for item_id in (player.get("granted_items") or ())
                if str(item_id) in self.item_catalog
            }
            self.consumed_items = {
                str(item_id)
                for item_id in (player.get("consumed_items") or ())
                if str(item_id) in self.item_catalog
            }
        saved_automata = player.get("item_automata") or {}
        if isinstance(saved_automata, dict):
            for item_id, automaton in self.item_automata.items():
                saved = saved_automata.get(item_id)
                if isinstance(saved, dict):
                    restore_item_automaton(automaton, saved)
        for character_id, saved in (snapshot.get("characters") or {}).items():
            character = self.characters.get(character_id)
            if character is None:
                continue
            for axis in self.relation_axis_ids:
                character[axis] = _clamp(
                    saved.get(axis, character.get(axis, 0.0)),
                    -1.0,
                    1.0,
                )
            if "health" in saved:
                character["health"] = _clamp(
                    _as_float(saved.get("health"), HEALTH_MAX),
                    0.0,
                    HEALTH_MAX,
                )
            if "sickness" in saved:
                character["sickness"] = _clamp(
                    _as_float(saved.get("sickness"), 0.0),
                    0.0,
                    SICKNESS_MAX,
                )
            if "wound" in saved:
                character["wound"] = _clamp(
                    _as_float(saved.get("wound"), 0.0),
                    0.0,
                    CAMPAIGN_WOUND_MAX,
                )
            if "alive" in saved:
                character["alive"] = bool(saved.get("alive"))
            else:
                character["alive"] = character["health"] > 0.0
            if "needs" in saved:
                character.load_needs(saved.get("needs"))
        for node_id, saved in (snapshot.get("nodes") or {}).items():
            node = self.nodes.get(node_id)
            if node is None:
                continue
            node["relation_axes"] = {}
            for key, value in (saved.get("stats") or {}).items():
                if key in node["stats"]:
                    node["stats"][key] = _clamp(value)
            for other_id, value in (saved.get("relations") or {}).items():
                if other_id in self.nodes:
                    node["relations"][other_id] = _clamp(value, -1.0, 1.0)
            for other_id, axes in (saved.get("relation_axes") or {}).items():
                if other_id not in self.nodes or not isinstance(axes, dict):
                    continue
                stored = node.setdefault("relation_axes", {})
                stored[other_id] = {
                    axis: _clamp(
                        _as_float(axes.get(axis), 0.0), -1.0, 1.0
                    )
                    for axis in self.relation_axis_ids
                }
                node["relations"][other_id] = stored[other_id]["affinity"]
        self.player_relations = {}
        for character_id, view in (
            snapshot.get("player_relations") or {}
        ).items():
            if character_id not in self.characters or not isinstance(
                view, dict
            ):
                continue
            self.player_relations[character_id] = {
                axis: _clamp(_as_float(view.get(axis), 0.0), -1.0, 1.0)
                for axis in self.relation_axis_ids
            }
        self.cooldowns = {
            str(key): _as_int(value)
            for key, value in (snapshot.get("cooldowns") or {}).items()
        }
        self.labor_negotiations = {}
        for office_id, per_office in (
            snapshot.get("labor_negotiations") or {}
        ).items():
            if not isinstance(per_office, dict):
                continue
            self.labor_negotiations[str(office_id)] = {
                str(rival_id): {
                    "generation": _as_int(record.get("generation"), 0),
                    "attempts": max(
                        0, _as_int(record.get("attempts"), 0)
                    ),
                    "withdrawn": bool(record.get("withdrawn", False)),
                    "withdrawn_day": _as_int(
                        record.get("withdrawn_day"), 0
                    ),
                    "chance": _as_float(record.get("chance"), 0.0),
                }
                for rival_id, record in per_office.items()
                if isinstance(record, dict)
            }
        self.used_actions = list(snapshot.get("used_actions") or [])
        self.log = list(snapshot.get("log") or [])
        self.log_trimmed = _as_int(snapshot.get("log_trimmed"), 0)
        self._lod = None
        self._lod_root = None
        self.tick_stats = {
            "ticks": 0,
            "intents": 0,
            "nodes_considered": 0,
            "nodes_skipped": 0,
            "nodes_acted": 0,
            "last_cost": 0.0,
            "last_slot": 0,
        }
        self.last_result = snapshot.get("last_result")
        self.outcome = snapshot.get("outcome")
        self.finished = bool(snapshot.get("finished", False))
        self.infinite = bool(snapshot.get("infinite", self.infinite))
        self.horizon_passed = bool(
            snapshot.get("horizon_passed", self.horizon_passed)
        )
        self.ending = snapshot.get("ending", self.ending)
        self.dismissed = bool(snapshot.get("dismissed", self.dismissed))
        self.dismissal_count = _as_int(
            snapshot.get("dismissal_count"), self.dismissal_count
        )
        self.last_role_change_day = _as_int(
            snapshot.get("last_role_change_day"),
            self.last_role_change_day,
        )
        self.collapsed = bool(snapshot.get("collapsed", self.collapsed))
        self.collapse_days = max(
            0, _as_int(snapshot.get("collapse_days"), self.collapse_days)
        )
        self.storyline_days = max(
            0, _as_int(snapshot.get("storyline_days"), self.storyline_days)
        )
        self.intents.load(snapshot.get("intents") or ())
        self.directives.load(snapshot.get("directives") or ())
        self.obligations.load(snapshot.get("obligations") or ())
        self.coalitions.load(snapshot.get("coalitions") or {})
        self.node_action_day = {
            str(node_id): _as_int(day)
            for node_id, day in (
                snapshot.get("node_action_day") or {}
            ).items()
        }
        self.strategy_state = {}
        for node_id, per_node in (
            snapshot.get("node_strategy_state") or {}
        ).items():
            if node_id not in self.nodes or not isinstance(per_node, dict):
                continue
            kept = {}
            for strategy_id, state in per_node.items():
                if self.strategies.get(strategy_id) is None:
                    continue
                if not isinstance(state, dict):
                    continue
                kept[strategy_id] = {
                    "start_day": _as_int(state.get("start_day"), self.day),
                    "start_value": _as_float(
                        state.get("start_value"), 0.0
                    ),
                    "completed": bool(state.get("completed")),
                    "expired": bool(state.get("expired")),
                    "resolved_day": _as_int(
                        state.get("resolved_day"), 0
                    ),
                    "actions": {
                        str(key): _as_int(value, 0)
                        for key, value in (state.get("actions") or {}).items()
                    },
                }
            if kept:
                self.strategy_state[node_id] = kept
        self.attached = bool(
            snapshot.get("attached")
            or (self.player_node_id and self.player_office_id)
        )
        if "items" not in player and self.attached:
            self._refresh_items()
