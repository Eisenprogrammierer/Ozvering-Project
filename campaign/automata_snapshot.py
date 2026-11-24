"""Снимок, сохранение, загрузка и аудит."""

from __future__ import annotations

from .automata_support import (
    AVATAR_SCHEMA_VERSION,
    AvatarError,
    CAPABILITY_SCHEMA_VERSION,
    CONTEXT_MAX,
    CONTEXT_MIN,
    Mapping,
    ObligationLedger,
    RelationStore,
    SCHEMA_VERSION,
    SNAPSHOT_TAIL,
    StateMachine,
    StateMachineError,
    WORK_TRACE_VERSION,
    _as_mapping,
    _clamp,
    _nested_tuple,
    _number,
    _relation_model,
    asset_keys,
    avatar_from_snapshot,
    logger,
    math,
    migrate_snapshot,
    stamp_snapshot,
    validate_organ_network,
)


class AutomataSnapshotMixin:

    def _machines_snapshot(self):
        return {
            "factions": {
                side: machine.to_dict()
                for side, machine in self.faction_machines.items()
            },
            "subfactions": {
                side: {
                    sub_id: machine.to_dict()
                    for sub_id, machine in machines.items()
                }
                for side, machines in self.subfaction_machines.items()
            },
            "organs": {
                side: {
                    organ_id: machine.to_dict()
                    for organ_id, machine in machines.items()
                }
                for side, machines in self.organ_machines.items()
            },
        }

    def _restore_machines(self, data):
        data = _as_mapping(data)
        for side, payload in _as_mapping(
            data.get("factions")
        ).items():
            machine = self.faction_machines.get(str(side))
            if machine is None:
                continue
            try:
                self.faction_machines[str(side)] = StateMachine.from_dict(
                    payload, machine.definition
                )
            except (StateMachineError, ValueError) as error:
                logger.warning(
                    "Автомат фракции %s не восстановлен: %s",
                    side,
                    error,
                )
        for side, entries in _as_mapping(
            data.get("subfactions")
        ).items():
            machines = self.subfaction_machines.get(str(side), {})
            for sub_id, payload in _as_mapping(entries).items():
                machine = machines.get(str(sub_id))
                if machine is None:
                    continue
                try:
                    machines[str(sub_id)] = StateMachine.from_dict(
                        payload, machine.definition
                    )
                except (StateMachineError, ValueError) as error:
                    logger.warning(
                        "Автомат подфракции %s/%s не восстановлен: %s",
                        side,
                        sub_id,
                        error,
                    )
        for side, entries in _as_mapping(data.get("organs")).items():
            machines = self.organ_machines.get(str(side), {})
            for organ_id, payload in _as_mapping(entries).items():
                machine = machines.get(str(organ_id))
                if machine is None:
                    continue
                try:
                    machines[str(organ_id)] = StateMachine.from_dict(
                        payload, machine.definition
                    )
                except (StateMachineError, ValueError) as error:
                    logger.warning(
                        "Автомат органа %s/%s не восстановлен: %s",
                        side,
                        organ_id,
                        error,
                    )

    def snapshot(self):
        return {
            "preset_id": self.preset_id,
            "title": self.title,
            "capability_schema": int(
                getattr(
                    self, "capability_schema", CAPABILITY_SCHEMA_VERSION
                )
            ),
            "work_trace_version": int(
                getattr(self, "work_trace_version", WORK_TRACE_VERSION)
            ),
            "turn": self.turn,
            "cycle_limit": self.cycle_limit,
            "actions_per_cycle": self.actions_per_cycle,
            # Совместимые ключи для снимков, читаемых старым кодом.
            "max_turns": self.cycle_limit,
            "actions_per_turn": self.actions_per_cycle,
            "actions_left": self.actions_left,
            "turn_active": bool(self._turn_active),
            "elapsed": round(float(self.elapsed), 6),
            "speed": int(self.speed),
            "realtime": self._snapshot_realtime(),
            "action_progress": round(float(self._action_progress), 6),
            "ai_progress": round(float(self._ai_progress), 6),
            "round_progress": round(float(self._round_progress), 6),
            "action_process": dict(self.action_process),
            "action_slots": int(self.action_slots),
            "process_seq": int(self._process_seq),
            "processes": [
                dict(record) for record in self.processes
            ],
            "score_streak": self.score_streak,
            "score_streak_side": self.score_streak_side,
            "player_side": self.player_side,
            "avatar_schema": AVATAR_SCHEMA_VERSION,
            "avatar": (
                self.avatar.as_dict() if self.avatar is not None else None
            ),
            "rival_side": self.rival_side,
            "outcome": self.outcome,
            "finished": self.finished,
            "factions": {
                side: faction.snapshot()
                for side, faction in self.factions.items()
            },
            "events": list(self.events[-SNAPSHOT_TAIL:]),
            "story_events": list(self.story_events[-SNAPSHOT_TAIL:]),
            "narrative": list(self.narrative[-SNAPSHOT_TAIL:]),
            "briefing_seen": bool(self.briefing_seen),
            "machines": self._machines_snapshot(),
            "log": list(self.log[-SNAPSHOT_TAIL:]),
            "obligations": self.obligations.to_list(),
            "relations": self.relations.snapshot(),
            "dispatch": self.dispatch.snapshot(),
        }

    def save_snapshot(self):
        """Полный снимок: журнал, организации и состояние ГСЧ."""
        data = stamp_snapshot(self.snapshot(), SCHEMA_VERSION)
        data["capability_schema"] = int(
            getattr(
                self, "capability_schema", CAPABILITY_SCHEMA_VERSION
            )
        )
        data["work_trace_version"] = int(
            getattr(self, "work_trace_version", WORK_TRACE_VERSION)
        )
        data["log"] = list(self.log)
        data["events"] = list(self.events)
        data["narrative"] = list(self.narrative)
        data["rng_state"] = _nested_tuple(self.rng.getstate())
        data["seed"] = self.seed
        for side, faction in self.factions.items():
            state = data.get("factions", {}).get(side)
            if isinstance(state, dict):
                state["raw_assets"] = {
                    str(key): float(value)
                    for key, value in faction.assets.items()
                }
                state["context"] = {
                    str(key): float(value)
                    for key, value in faction.context.items()
                }
                state["baseline_context"] = {
                    str(key): float(value)
                    for key, value in faction.baseline_context.items()
                }
                state["baseline_assets"] = {
                    str(key): float(value)
                    for key, value in faction.baseline_assets.items()
                }
                state["flags"] = dict(faction.flags)
                state["subfactions"] = [
                    {
                        "id": item.id,
                        "share": float(item.share),
                        "assets": {
                            str(key): float(value)
                            for key, value in item.assets.items()
                        },
                    }
                    for item in faction.subfactions
                ]
                state["low_streaks"] = {
                    str(key): int(value)
                    for key, value in faction.low_streaks.items()
                }
                state["organ_state"] = [
                    {
                        "id": organ.id,
                        "integrity": float(organ.integrity),
                        "support": float(organ.support),
                        "scales": {
                            str(key): float(value)
                            for key, value in organ.scales.items()
                        },
                        "interaction_cooldowns": {
                            str(key): int(value)
                            for key, value in (
                                organ.interaction_cooldowns.items()
                            )
                        },
                        "used_turn": int(organ.used_turn),
                    }
                    for organ in faction.organs
                ]
                state["character_state"] = [
                    {
                        "id": str(
                            getattr(character, "campaign_id", "") or ""
                        ),
                        "needs": {
                            str(key): float(value)
                            for key, value in character.needs.items()
                        },
                        "personality": {
                            str(key): float(value)
                            for key, value in getattr(
                                character.personality, "values", {}
                            ).items()
                        },
                        "morale": float(character.morale),
                        "force": float(getattr(character, "force", 0.0)),
                        "energy": float(
                            getattr(character, "energy_pool", 0.0)
                        ),
                        "dead": bool(getattr(character, "dead", False)),
                        "rng_state": (
                            _nested_tuple(character.rng.getstate())
                            if getattr(character, "rng", None) is not None
                            else None
                        ),
                        "conditions": {
                            str(key): float(value)
                            for key, value in getattr(
                                getattr(character, "bdi", None),
                                "conditions",
                                {},
                            ).items()
                        },
                        "beliefs": [
                            item.as_dict()
                            for item in getattr(
                                getattr(character, "bdi", None),
                                "beliefs",
                                [],
                            )
                        ],
                        "intentions": [
                            item.as_dict()
                            for item in getattr(
                                getattr(character, "bdi", None),
                                "intentions",
                                [],
                            )
                        ],
                        "divisions": (
                            character.divisions.as_dict()
                            if getattr(
                                character, "divisions", None
                            )
                            is not None
                            else {}
                        ),
                        "cooldowns": {
                            str(key): int(value)
                            for key, value in _as_mapping(
                                getattr(
                                    character, "campaign_cooldowns", {}
                                )
                            ).items()
                        },
                        "goal": dict(
                            _as_mapping(
                                getattr(character, "campaign_goal", {})
                            )
                        ),
                        "agency": dict(
                            _as_mapping(
                                getattr(character, "campaign_agency", {})
                            )
                        ),
                        "mind": str(getattr(character, "mind", "steady")),
                        "last_mind": str(
                            getattr(character, "_last_mind", "steady")
                        ),
                        "panicked": bool(
                            getattr(character, "panicked", False)
                        ),
                        "fanatical": bool(
                            getattr(character, "fanatical", False)
                        ),
                        "panic_timer": int(
                            getattr(character, "panic_timer", 0)
                        ),
                        "fanatic_timer": int(
                            getattr(character, "fanatic_timer", 0)
                        ),
                        "panic_cooldown": int(
                            getattr(character, "panic_cooldown", 0)
                        ),
                        "fanatic_cooldown": int(
                            getattr(character, "fanatic_cooldown", 0)
                        ),
                        "under_fire": float(
                            getattr(character, "under_fire", 0.0)
                        ),
                        "casualties": int(
                            getattr(character, "casualties", 0)
                        ),
                    }
                    for character in faction.characters
                ]
                if faction.organization is not None:
                    state["organization_state"] = (
                        faction.organization.state_dict()
                    )
        return data

    def load_snapshot(self, snapshot):
        snapshot = _as_mapping(snapshot)
        if not snapshot:
            return
        snapshot = migrate_snapshot(snapshot)
        self.capability_schema = max(
            1,
            int(
                _number(
                    snapshot.get("capability_schema"),
                    1,
                )
            ),
        )
        self.work_trace_version = max(
            0,
            int(
                _number(
                    snapshot.get("work_trace_version"),
                    0,
                )
            ),
        )
        self.turn = int(_number(snapshot.get("turn"), self.turn))
        saved_max = snapshot.get("cycle_limit")
        if saved_max is None:
            saved_max = snapshot.get("max_turns")
        if saved_max is None:
            self.cycle_limit = None
        else:
            value = int(_number(saved_max, 0))
            self.cycle_limit = value if value > 0 else None
        per_cycle = snapshot.get("actions_per_cycle")
        if per_cycle is None:
            per_cycle = snapshot.get("actions_per_turn")
        self.actions_per_cycle = max(
            1,
            int(
                _number(
                    per_cycle,
                    self.actions_per_cycle,
                )
            ),
        )
        self.actions_left = max(
            0,
            min(
                self.actions_per_cycle,
                int(
                    _number(
                        snapshot.get("actions_left"), self.actions_left
                    )
                ),
            ),
        )
        self._turn_active = bool(
            snapshot.get("turn_active", self._turn_active)
        )
        self.elapsed = max(
            0.0, _number(snapshot.get("elapsed"), self.elapsed)
        )
        self._action_progress = max(
            0.0,
            _number(snapshot.get("action_progress"), self._action_progress),
        )
        self._ai_progress = max(
            0.0, _number(snapshot.get("ai_progress"), self._ai_progress)
        )
        self._round_progress = max(
            0.0,
            _number(snapshot.get("round_progress"), self._round_progress),
        )
        saved_process = _as_mapping(snapshot.get("action_process"))
        if saved_process:
            self.action_process.update(
                {str(key): value for key, value in saved_process.items()}
            )
        self.action_slots = max(
            1,
            int(
                _number(
                    snapshot.get("action_slots"),
                    _number(self.action_process.get("slots"), 2),
                )
            ),
        )
        self.processes = [
            dict(record)
            for record in (snapshot.get("processes") or ())
            if isinstance(record, Mapping) and record.get("id")
        ]
        self._process_seq = max(
            int(
                _number(
                    snapshot.get("process_seq"),
                    self._process_seq,
                )
            ),
            len(self.processes),
        )
        for record in self.processes:
            if "remaining" not in record:
                record["remaining"] = _number(
                    record.get("duration"), 0.0
                )
            if "finish_at" not in record:
                record["finish_at"] = float(self.elapsed) + _number(
                    record.get("remaining"), 0.0
                )
        for index, record in enumerate(self.processes, 1):
            if record.get("seq") is None:
                tail = str(record.get("id") or "").rsplit("-", 1)[-1]
                try:
                    record["seq"] = int(tail)
                except (TypeError, ValueError):
                    record["seq"] = index
            self._process_seq = max(
                self._process_seq, int(_number(record.get("seq"), 0))
            )
        saved_speed = max(1, int(_number(snapshot.get("speed"), self.speed)))
        allowed_speeds = [
            level for level in self.speed_levels if level >= saved_speed
        ]
        self.speed = (
            allowed_speeds[0]
            if allowed_speeds
            else self.speed_levels[-1]
        )
        self.score_streak = max(
            0, int(_number(snapshot.get("score_streak"), self.score_streak))
        )
        self.score_streak_side = snapshot.get(
            "score_streak_side", self.score_streak_side
        )
        self.outcome = snapshot.get("outcome")
        self.finished = bool(snapshot.get("finished", False))
        try:
            restored = avatar_from_snapshot(snapshot, fallback_data=self.data)
        except AvatarError as exc:
            logger.warning("Аватар из снимка не восстановлен: %s", exc)
        else:
            if "avatar" in snapshot:
                self.avatar = restored
        self._restore_machines(snapshot.get("machines"))
        rng_state = snapshot.get("rng_state")
        if rng_state:
            try:
                self.rng.setstate(_nested_tuple(rng_state))
            except (TypeError, ValueError):
                logger.warning(
                    "Состояние ГСЧ кампании автоматов не восстановлено"
                )
        for side, state in _as_mapping(snapshot.get("factions")).items():
            faction = self.faction(side)
            if faction is None:
                continue
            saved_context = _as_mapping(state.get("context"))
            if saved_context:
                faction.context = {
                    str(key): _clamp(
                        value, CONTEXT_MIN, CONTEXT_MAX
                    )
                    for key, value in saved_context.items()
                }
            else:
                # Старый сейв: раньше активы были независимыми. Для
                # совместимости подбираем контекст под сохранённые
                # значения, но не создаём отдельный кошелёк.
                for key in asset_keys(faction):
                    faction.context.setdefault(str(key), 0.5)
                for key, value in _as_mapping(
                    state.get("raw_assets") or state.get("assets")
                ).items():
                    faction.set_asset(key, value)
            faction.baseline_context = {
                str(key): _clamp(
                    value, CONTEXT_MIN, CONTEXT_MAX
                )
                for key, value in _as_mapping(
                    state.get("baseline_context")
                ).items()
            } or dict(faction.context)
            faction.baseline_assets = {
                str(key): _clamp(value)
                for key, value in _as_mapping(
                    state.get("baseline_assets")
                ).items()
            }
            faction.flags = dict(_as_mapping(state.get("flags")))
            for saved_sub in state.get("subfactions") or ():
                if not isinstance(saved_sub, Mapping):
                    continue
                sub = faction.subfaction(saved_sub.get("id"))
                if sub is None:
                    continue
                sub.share = _clamp(
                    saved_sub.get("share", sub.share)
                )
                sub.assets = {
                    str(key): _clamp(value)
                    for key, value in _as_mapping(
                        saved_sub.get("assets")
                    ).items()
                }
            faction.cooldowns = {
                str(key): int(_number(value))
                for key, value in _as_mapping(state.get("cooldowns")).items()
            }
            faction.action_uses = {
                str(key): max(0, int(_number(value)))
                for key, value in _as_mapping(
                    state.get("action_uses")
                ).items()
            }
            faction.dissolved = bool(state.get("dissolved", False))
            faction.low_streaks = {
                str(key): int(_number(value))
                for key, value in _as_mapping(
                    state.get("low_streaks")
                ).items()
            }
            faction.organization_snapshot = dict(
                _as_mapping(state.get("organization"))
            )
            faction.order_cooldowns = {
                str(key): int(_number(value))
                for key, value in _as_mapping(
                    state.get("order_cooldowns")
                ).items()
            }
            faction.last_order_turn = max(
                0, int(_number(state.get("last_order_turn"), 0))
            )
            faction.last_order = dict(
                _as_mapping(state.get("last_order"))
            )
            saved_organs = {
                str(item.get("id")): item
                for item in (state.get("organ_state") or ())
                if isinstance(item, Mapping) and item.get("id")
            }
            for organ in faction.organs:
                saved = saved_organs.get(str(organ.id))
                if not saved:
                    continue
                organ.integrity = _clamp(
                    _number(saved.get("integrity"), organ.integrity)
                )
                organ.support = _clamp(
                    _number(saved.get("support"), organ.support),
                    0.0,
                    0.5,
                )
                for key, value in _as_mapping(
                    saved.get("scales")
                ).items():
                    organ.scales[str(key)] = _clamp(
                        _number(value, organ.scales.get(str(key), 0.0))
                    )
                organ.interaction_cooldowns = {
                    str(key): int(_number(value))
                    for key, value in _as_mapping(
                        saved.get("interaction_cooldowns")
                    ).items()
                }
                organ.used_turn = int(
                    _number(saved.get("used_turn"), organ.used_turn)
                )
            saved_characters = {
                str(item.get("id")): item
                for item in (state.get("character_state") or ())
                if isinstance(item, Mapping) and item.get("id")
            }
            for character in faction.characters:
                saved = saved_characters.get(
                    str(getattr(character, "campaign_id", ""))
                )
                if not saved:
                    continue
                for key, value in _as_mapping(saved.get("needs")).items():
                    if key in character.needs:
                        character.needs[key] = _clamp(value)
                values = getattr(character.personality, "values", {})
                for key, value in _as_mapping(
                    saved.get("personality")
                ).items():
                    if key in values:
                        values[key] = _clamp(value)
                divisions = _as_mapping(saved.get("divisions"))
                if (
                    divisions
                    and getattr(character, "divisions", None) is not None
                ):
                    try:
                        character.divisions.update(divisions)
                    except Exception:
                        pass
                bdi = getattr(character, "bdi", None)
                if bdi is not None:
                    for key, value in _as_mapping(
                        saved.get("conditions")
                    ).items():
                        if key in bdi.conditions:
                            bdi.conditions[key] = max(
                                0.0, _number(value, bdi.conditions[key])
                            )
                    if saved.get("beliefs") is not None:
                        try:
                            character.beliefs = list(saved["beliefs"])
                        except Exception:
                            pass
                    if saved.get("intentions") is not None:
                        try:
                            character.intentions = list(
                                saved["intentions"]
                            )
                        except Exception:
                            pass
                if saved.get("force") is not None:
                    character.force = max(
                        0.0, _number(saved.get("force"), character.force)
                    )
                if saved.get("energy") is not None:
                    character.energy_pool = max(
                        0.0,
                        _number(
                            saved.get("energy"), character.energy_pool
                        ),
                    )
                if saved.get("dead") is not None:
                    character.dead = bool(saved.get("dead"))
                rng_state = saved.get("rng_state")
                if rng_state and getattr(character, "rng", None) is not None:
                    try:
                        character.rng.setstate(_nested_tuple(rng_state))
                    except (TypeError, ValueError):
                        pass
                character.morale = max(
                    0.0,
                    min(
                        100.0,
                        _number(
                            saved.get("morale"), character.morale
                        ),
                    ),
                )
                character.campaign_cooldowns = {
                    str(key): int(_number(value))
                    for key, value in _as_mapping(
                        saved.get("cooldowns")
                    ).items()
                }
                if isinstance(saved.get("goal"), Mapping):
                    character.campaign_goal = dict(saved["goal"])
                if isinstance(saved.get("agency"), Mapping):
                    character.campaign_agency = dict(saved["agency"])
                if "mind" in saved:
                    character.mind = str(
                        saved.get("mind") or "steady"
                    )
                if "last_mind" in saved:
                    character._last_mind = str(
                        saved.get("last_mind") or "steady"
                    )
                if "panicked" in saved:
                    character.panicked = bool(saved.get("panicked"))
                if "fanatical" in saved:
                    character.fanatical = bool(saved.get("fanatical"))
                if "panic_timer" in saved:
                    character.panic_timer = max(
                        0, int(_number(saved.get("panic_timer"), 0))
                    )
                if "fanatic_timer" in saved:
                    character.fanatic_timer = max(
                        0, int(_number(saved.get("fanatic_timer"), 0))
                    )
                if "panic_cooldown" in saved:
                    character.panic_cooldown = max(
                        0, int(_number(saved.get("panic_cooldown"), 0))
                    )
                if "fanatic_cooldown" in saved:
                    character.fanatic_cooldown = max(
                        0, int(_number(saved.get("fanatic_cooldown"), 0))
                    )
                if "under_fire" in saved:
                    character.under_fire = max(
                        0.0, _number(saved.get("under_fire"), 0.0)
                    )
                if "casualties" in saved:
                    character.casualties = max(
                        0, int(_number(saved.get("casualties"), 0))
                    )
                try:
                    character.desires = character.weighted_urgency()
                except Exception:
                    pass
            if faction.organization is not None:
                faction.organization.load_state_dict(
                    _as_mapping(state.get("organization_state"))
                )
        self.events = list(snapshot.get("events") or [])
        self.story_events = list(snapshot.get("story_events") or [])
        self.narrative = list(snapshot.get("narrative") or [])
        self.briefing_seen = bool(snapshot.get("briefing_seen", False))
        self.log = list(snapshot.get("log") or [])
        # Старый сейв без ``obligations`` очищает стартовые обязательства:
        # снимок — источник истины, а не пресет.
        self.obligations = ObligationLedger()
        self.obligations.load(snapshot.get("obligations") or ())
        self.relations = RelationStore.from_config(
            _relation_model(self.data)
        ).load(snapshot.get("relations") or {})
        self.dispatch.load(snapshot.get("dispatch") or {})
        for faction in self.factions.values():
            faction.relations = self.relations
            self._init_character_agency(faction)
        if self.outcome:
            self.finished = True
        self._sync_avatar_state()

    def audit(self):
        anomalies = []
        seen = set()
        for side, faction in self.factions.items():
            for key, value in faction.assets.items():
                token = (side, key)
                if not math.isfinite(_number(value)):
                    anomalies.append("%s/%s: не конечное значение" % token)
                if not 0.0 <= _number(value) <= 1.0:
                    anomalies.append(
                        "%s/%s: %.6f вне диапазона [0,1]"
                        % (side, key, _number(value))
                    )
                seen.add(token)
            organ_ids = set()
            for organ in faction.organs:
                if organ.id in organ_ids:
                    anomalies.append(
                        "%s: орган %s повторяется" % (side, organ.id)
                    )
                organ_ids.add(organ.id)
                if not 0.0 <= _number(organ.integrity) <= 1.0:
                    anomalies.append(
                        "%s/%s: целостность %.6f вне [0,1]"
                        % (side, organ.id, _number(organ.integrity))
                    )
            anomalies.extend(
                "%s: %s" % (side, problem)
                for problem in validate_organ_network(faction.organs)
            )
            snapshot = faction.organization_snapshot
            if snapshot:
                active = int(_number(snapshot.get("active_count"), 0))
                initial = int(_number(snapshot.get("initial_count"), 0))
                if active > initial:
                    anomalies.append(
                        "%s: активных %d больше исходных %d"
                        % (side, active, initial)
                    )
                willing = _number(snapshot.get("willing_share"), 0.0)
                if not 0.0 <= willing <= 1.0:
                    anomalies.append(
                        "%s: willing_share %.6f вне [0,1]" % (side, willing)
                    )
            if faction.dissolved and not snapshot.get("active", True):
                continue
        for item in self.log:
            if item.get("ok") and not (
                0.0 <= _number(item.get("chance"), 0.0) <= 1.0
            ):
                anomalies.append(
                    "работа %s: шанс %.6f вне [0,1]"
                    % (item.get("action_id"), _number(item.get("chance")))
                )
        return anomalies

    to_dict = snapshot
