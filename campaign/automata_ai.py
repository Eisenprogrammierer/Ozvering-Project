"""ИИ-сторона, автоигра и ход кампании."""

from __future__ import annotations

from .automata_support import (
    DEFAULT_RUN_TURNS,
    Mapping,
    _as_mapping,
    _clamp,
    _number,
    _same_id,
    _text,
)
from .cognition.backends import AI_BACKENDS, load_flags
from .cognition.errors import BackendError, SoarError
from .npc_decisions import (
    DEFAULT_AGREEMENT_THRESHOLD,
    MONITOR_VERSION,
    NpcDecisionMonitor,
)
from .npc_policy import NeedPolicy


class AutomataAIMixin:

    def _advance_ai(self, seconds):
        if self.finished:
            return
        self._ai_progress += seconds
        interval = self.ai_interval_seconds
        while self._ai_progress >= interval and not self.finished:
            self._ai_progress -= interval
            for side in list(self.factions):
                if side == self.player_side or self.finished:
                    continue
                faction = self.faction(side)
                if faction is None or faction.dissolved:
                    continue
                self._ai_start_work(side)

    def _ai_start_work(self, side):
        """Занять свободные слоты ИИ процессами, а не мгновенными работами."""
        started = []
        while (
            not self.finished
            and self.slot_state(side)["free"] > 0
        ):
            action_id = self.auto_action(side, exclude_active=True)
            if action_id is None:
                break
            result = self.start_action(side, action_id)
            if not result.get("ok"):
                break
            started.append(action_id)
        return started

    def _ai_action_weight(self, side, action, leader=None):
        """Вес работы для ИИ: данные, BDI лидера, доктрина и органы.

        Базовый вес — ``ai_priority`` работы. Дальше множители берутся
        из ``automata_defaults.json::ai_model``: потребность, намерение,
        доктрина фракции, убеждения лидера, целостность органа и защита
        цели. Ни один множитель не зашит в код: отсутствующий блок или
        нулевой вес просто не меняет базовый приоритет.
        """
        model = _as_mapping(self.ai_model)
        floor = max(0.01, _number(model.get("score_floor"), 0.01))
        weight = max(floor, _number(action.get("ai_priority"), 1.0))
        faction = self.faction(side)
        if leader is None:
            leader = self._leader(side)
        if faction is None:
            return weight

        essences = self._action_essences(action)
        form = self._action_form(action)
        target = self.faction(self._target_side(side, action))
        target_id = _text(getattr(target, "id", ""))
        faction_id = _text(getattr(faction, "id", ""))
        need = ""
        for essence in essences:
            need = self._action_need(essence, leader)
            if need:
                break

        if leader is not None and need:
            needs = _as_mapping(model.get("needs"))
            current = _clamp(
                _as_mapping(getattr(leader, "needs", {})).get(need)
            )
            weight *= 1.0 + _number(needs.get("weight"), 1.4) * current
            priorities = {
                str(item)
                for item in (
                    faction.record.get("priority_needs") or ()
                )
                if str(item)
            }
            if need in priorities:
                weight *= (
                    1.0
                    + _number(needs.get("priority_weight"), 0.6)
                    * current
                )

        intention = None
        if leader is not None:
            bdi = getattr(leader, "bdi", None)
            if bdi is not None:
                intention = bdi.latest_intention()
        if intention is not None:
            intent = _as_mapping(model.get("intention"))
            if intention.essence in essences:
                weight *= 1.0 + _number(
                    intent.get("essence_weight"), 0.6
                )
            focus = self._action_need(intention.essence, leader)
            if focus and need == focus:
                current = _clamp(
                    _as_mapping(getattr(leader, "needs", {})).get(focus)
                )
                weight *= (
                    1.0
                    + _number(intent.get("focus_weight"), 0.4)
                    * current
                )
            if target_id and _same_id(intention.target, target_id):
                weight *= 1.0 + _number(
                    intent.get("target_weight"), 0.35
                )
            if (
                essences
                and _text(intention.essence)
                and _text(intention.essence) not in essences
            ):
                weight *= max(
                    0.05,
                    1.0
                    - _number(intent.get("mismatch_penalty"), 0.15),
                )

        # Автономия персонажей: не только лидер, но и остальные люди
        # фракции вносят вклад в выбор работы своей целью, намерением,
        # потребностью, доверием и обидой. Веса — данные
        # ``ai_model.character_agency``.
        agency = _as_mapping(model.get("character_agency"))
        if bool(agency.get("enabled", False)):
            limit = max(
                1, int(_number(agency.get("max_characters"), 6))
            )
            support = 0.0
            sabotage = 0.0
            for member in list(faction.characters)[:limit]:
                if member is leader:
                    continue
                value = self._character_support(
                    member, action, faction
                )
                if value >= 0.0:
                    support += value
                else:
                    sabotage += -value
            if support > 0.0:
                weight *= 1.0 + support
            if sabotage > 0.0:
                floor = _clamp(
                    _number(agency.get("sabotage_floor"), 0.35)
                )
                weight *= max(
                    floor,
                    1.0
                    - _number(agency.get("sabotage_weight"), 0.35)
                    * sabotage,
                )

        doctrine = _as_mapping(faction.record.get("doctrine"))
        doctrine_model = _as_mapping(model.get("doctrine"))
        form_weights = _as_mapping(doctrine.get("forms"))
        essence_weights = _as_mapping(doctrine.get("essences"))
        if form and form in form_weights:
            weight *= max(
                0.05,
                1.0
                + _number(doctrine_model.get("form_weight"), 1.0)
                * _number(form_weights.get(form), 0.0),
            )
        doctrine_essence = None
        for essence in essences:
            if essence not in essence_weights:
                continue
            value = _number(essence_weights.get(essence), 0.0)
            if doctrine_essence is None or value > doctrine_essence:
                doctrine_essence = value
        if doctrine_essence is not None:
            weight *= max(
                0.05,
                1.0
                + _number(doctrine_model.get("essence_weight"), 1.0)
                * doctrine_essence,
            )

        beliefs = (
            getattr(getattr(leader, "bdi", None), "beliefs", ())
            if leader is not None
            else ()
        )
        for rule in (
            _as_mapping(model.get("beliefs")).get("rules") or ()
        ):
            if not isinstance(rule, Mapping):
                continue
            predicate = _text(rule.get("predicate"))
            if not predicate:
                continue
            rule_forms = {
                str(item) for item in (rule.get("forms") or ()) if item
            }
            rule_essences = {
                str(item)
                for item in (rule.get("essences") or ())
                if item
            }
            if (rule_forms or rule_essences) and not (
                form in rule_forms or set(essences) & rule_essences
            ):
                continue
            target_mode = _text(rule.get("target") or "any")
            strength = 0.0
            for belief in beliefs:
                if belief.predicate != predicate:
                    continue
                if (
                    target_mode == "action"
                    and not _same_id(belief.object, target_id)
                ):
                    continue
                if (
                    target_mode == "self"
                    and not _same_id(belief.object, faction_id)
                ):
                    continue
                strength = max(
                    strength,
                    _clamp(belief.value) * _clamp(belief.confidence),
                )
            if strength <= 0.0:
                continue
            weight *= max(
                0.05,
                1.0 + _number(rule.get("weight"), 0.0) * strength,
            )

        organs = _as_mapping(model.get("organs"))
        organ_id = _text(action.get("organ_id"))
        organ = faction.organ(organ_id) if organ_id else None
        if organ is not None:
            integrity = _clamp(organ.integrity)
            weight *= max(
                0.05,
                1.0
                - _number(organs.get("integrity_weight"), 0.5)
                * (1.0 - integrity),
            )
            threshold = _number(organs.get("low_threshold"), 0.4)
            repair = {
                str(item)
                for item in (organs.get("repair_essences") or ())
                if item
            }
            if integrity < threshold and set(essences) & repair:
                gap = (threshold - integrity) / max(threshold, 1e-6)
                weight *= 1.0 + _number(
                    organs.get("repair_weight"), 0.5
                ) * gap

        if target is not None:
            chance_spec = _as_mapping(action.get("chance"))
            defense = target.asset(
                str(
                    chance_spec.get("defense")
                    or action.get("defense_asset")
                    or "cohesion"
                )
            )
            defense_model = _as_mapping(model.get("defense"))
            reference = _number(defense_model.get("reference"), 0.5)
            weight *= 1.0 + _number(
                defense_model.get("weight"), 1.0
            ) * max(0.0, reference - defense)
            if self.relations is not None and target.id != faction.id:
                relation_model = _as_mapping(model.get("relations"))
                shift = self.relations.effect(
                    target.id, faction.id, form
                )
                weight *= max(
                    0.05,
                    1.0
                    + _number(
                        relation_model.get("weight"), 1.0
                    )
                    * shift,
                )
        return weight

    def _npc_policy(self):
        """Политика W2 или ``None``, если слой выключен."""
        config = _as_mapping(_as_mapping(self.ai_model).get("npc_policy"))
        if not bool(config.get("enabled", False)):
            return None
        if getattr(self, "_npc_policy_obj", None) is None:
            self._npc_policy_obj = NeedPolicy.from_config(
                config, seed=getattr(self, "seed", 0)
            )
        return self._npc_policy_obj

    def _npc_config(self):
        return _as_mapping(_as_mapping(self.ai_model).get("npc_policy"))

    def _cognition_flags(self):
        flags = getattr(self, "_cognition_flags_obj", None)
        if flags is None:
            flags = load_flags()
            self._cognition_flags_obj = flags
        return flags

    def npc_backend(self, side):
        """Бэкенд стороны: ``backends`` → ``backend`` → глобальный флаг."""
        config = self._npc_config()
        backends = _as_mapping(config.get("backends"))
        value = backends.get(str(side))
        if value is None:
            value = config.get("backend")
        if value is None:
            value = self._cognition_flags().ai_backend
        backend = str(value or "legacy")
        if backend not in AI_BACKENDS:
            raise BackendError(
                "npc_policy.backend=%r не поддерживается; допустимо: %s"
                % (backend, ", ".join(AI_BACKENDS))
            )
        return backend

    def npc_decision_timeout_ms(self):
        """Бюджет решения: локальный ``timeout_ms`` или общий флаг."""
        config = self._npc_config()
        timeout = _number(config.get("timeout_ms"), 0.0)
        if timeout <= 0.0:
            timeout = self._cognition_flags().decision_timeout_ms
        return float(timeout)

    def npc_decision_monitor(self):
        monitor = getattr(self, "_npc_decision_monitor", None)
        if monitor is None:
            monitor = NpcDecisionMonitor()
            self._npc_decision_monitor = monitor
        return monitor

    def npc_decision_report(
        self,
        threshold=DEFAULT_AGREEMENT_THRESHOLD,
    ):
        """Сводка согласия Soar с легаси за прогон."""
        return self.npc_decision_monitor().report(threshold)

    def npc_needs_summary(self):
        """Удовлетворённость 16 потребностей по сторонам (1 − давление)."""

        sides = {}
        pressures = []
        for side in getattr(self, "factions", {}) or {}:
            faction = self.faction(side)
            if faction is None:
                continue
            characters = [
                character
                for character in getattr(faction, "characters", ())
                if isinstance(getattr(character, "needs", None), Mapping)
            ]
            if not characters:
                continue
            totals = {}
            for character in characters:
                for key, value in _as_mapping(character.needs).items():
                    totals.setdefault(str(key), []).append(
                        _clamp(_number(value, 0.0))
                    )
            per_need = {
                key: sum(values) / float(len(values))
                for key, values in totals.items()
            }
            pressure = (
                sum(per_need.values()) / float(len(per_need))
                if per_need
                else 0.0
            )
            pressures.append(pressure)
            sides[str(side)] = {
                "characters": len(characters),
                "pressure": round(pressure, 6),
                "satisfaction": round(1.0 - pressure, 6),
                "needs": {
                    key: round(value, 6)
                    for key, value in sorted(per_need.items())
                },
            }
        overall_pressure = (
            sum(pressures) / float(len(pressures)) if pressures else 0.0
        )
        return {
            "sides": sides,
            "overall": {
                "characters": sum(
                    item["characters"] for item in sides.values()
                ),
                "pressure": round(overall_pressure, 6),
                "satisfaction": round(1.0 - overall_pressure, 6),
            },
        }

    def npc_outcome_report(
        self,
        threshold=DEFAULT_AGREEMENT_THRESHOLD,
    ):
        """Длинные метрики NPC: потребности, работы, паритет решений."""

        decisions = self.npc_decision_report(threshold)
        return {
            "kind": "npc_outcomes",
            "version": MONITOR_VERSION,
            "needs": self.npc_needs_summary(),
            "jobs": decisions["jobs"],
            "decisions": decisions,
            "ok": bool(decisions["ok"]),
        }

    def _soar_policy(self):
        policy = getattr(self, "_soar_policy_obj", None)
        if policy is None:
            from .cognition.soar_runtime import SoarNpcPolicy

            policy = SoarNpcPolicy(
                timeout_ms=self.npc_decision_timeout_ms()
            )
            self._soar_policy_obj = policy
        return policy

    @staticmethod
    def _npc_explore(policy):
        if not bool(getattr(policy, "explore", False)):
            return False
        return _number(getattr(policy, "epsilon", 0.0), 0.0) > 0.0

    def _soar_candidate(self, policy, candidates, needs, soar):
        from .cognition.soar_runtime import weights_for

        names = sorted(
            {str(need) for _option, need, _base in candidates}
        )
        return soar.choose(
            candidates,
            needs,
            weights=weights_for(policy, names),
            explore=self._npc_explore(policy),
        )

    def _policy_choice(self, side, weighted, leader=None):
        """Выбрать работу политикой поверх BDI; ``None`` — отдать эвристике."""
        policy = self._npc_policy()
        if policy is None:
            return None
        needs = _as_mapping(getattr(leader, "needs", {}))
        candidates = []
        for option, weight in weighted:
            essences = self._action_essences(option["action"])
            need = (
                self._action_need(essences[0], leader)
                if essences
                else ""
            )
            if need:
                candidates.append((option["id"], need, weight))
        if not candidates:
            return None
        backend = self.npc_backend(side)
        if backend == "legacy":
            return policy.choose(candidates, needs)
        soar = self._soar_policy()
        elapsed_ms = 0.0
        error = None
        candidate = None
        try:
            candidate = self._soar_candidate(
                policy, candidates, needs, soar
            )
            elapsed_ms = soar.last_elapsed_ms
        except (BackendError, SoarError) as exc:
            if backend == "soar":
                raise
            error = str(exc)
        if backend == "soar":
            return candidate
        legacy = policy.choose(candidates, needs)
        self.npc_decision_monitor().record(
            side=side,
            backend=backend,
            legacy=legacy,
            candidate=candidate,
            elapsed_ms=elapsed_ms,
            error=error,
            turn=getattr(self, "turn", None),
        )
        return legacy

    def _ai_weighted_options(
        self, side, turn=None, exclude_active=False
    ):
        options = [
            item
            for item in self.action_options(side, turn=turn)
            if item["enabled"]
        ]
        if exclude_active:
            running = {
                str(record.get("action_id"))
                for record in self._active_processes(side)
            }
            options = [
                item for item in options if item["id"] not in running
            ]
        leader = self._leader(side)
        return [
            (
                option,
                self._ai_action_weight(
                    side, option["action"], leader=leader
                ),
            )
            for option in options
        ]

    def ai_action_weights(
        self, side, turn=None, exclude_active=False
    ):
        """Веса ИИ по доступным работам стороны (диагностика/тесты)."""
        return {
            str(option["id"]): round(weight, 6)
            for option, weight in self._ai_weighted_options(
                side, turn=turn, exclude_active=exclude_active
            )
        }

    def auto_action(self, side, turn=None, exclude_active=False):
        weighted = self._ai_weighted_options(
            side, turn=turn, exclude_active=exclude_active
        )
        if not weighted:
            if self.stats.enabled and self.stats.actions:
                self.stats.log(
                    "ai_choice",
                    side=str(side),
                    chosen=None,
                    reason="нет доступных работ",
                    slots=self.slot_state(side),
                )
            return None
        total = sum(weight for _option, weight in weighted)
        chosen = None
        policy_choice = self._policy_choice(
            side, weighted, leader=self._leader(side)
        )
        if policy_choice is not None:
            chosen = policy_choice
        elif total <= 0.0:
            chosen = weighted[-1][0]["id"]
        else:
            pick = self.rng.random() * total
            upto = 0.0
            for option, weight in weighted:
                upto += weight
                if pick <= upto:
                    chosen = option["id"]
                    break
            if chosen is None:
                chosen = weighted[-1][0]["id"]
        if chosen is not None:
            self.npc_decision_monitor().record_action(
                side=side, action_id=chosen
            )
        if self.stats.enabled and self.stats.actions:
            self.stats.log(
                "ai_choice",
                side=str(side),
                chosen=str(chosen),
                total=round(total, 6),
                weights={
                    str(option["id"]): round(weight, 6)
                    for option, weight in weighted
                },
                slots=self.slot_state(side),
            )
        return chosen

    def advance(
        self,
        player_action=None,
        target=None,
        organ_action=None,
        character_action=None,
    ):
        """Совместимый helper: выполнить действие и завершить ход.

        Для нескольких действий за ход используйте ``perform``,
        ``perform_organ_interaction`` и ``perform_character_interaction``,
        а затем отдельно ``end_turn``. ``advance`` оставлен для тестов,
        экспериментов и старых вызовов. Если ``player_action`` не задан,
        игрок, как и ИИ, автоматически тратит оставшийся бюджет действий.
        """
        if self.finished:
            return self.snapshot()
        self.begin_turn()
        if organ_action:
            if isinstance(organ_action, Mapping):
                organ_id = organ_action.get("organ_id")
                interaction_id = organ_action.get("interaction_id")
            elif (
                isinstance(organ_action, (list, tuple))
                and len(organ_action) >= 2
            ):
                organ_id, interaction_id = organ_action[0], organ_action[1]
            else:
                organ_id = interaction_id = None
            if organ_id and interaction_id:
                self.perform_organ_interaction(
                    self.player_side,
                    organ_id,
                    interaction_id,
                    defer=False,
                )
        if character_action:
            if isinstance(character_action, Mapping):
                character_id = character_action.get("character_id")
                interaction_id = character_action.get("interaction_id")
            elif (
                isinstance(character_action, (list, tuple))
                and len(character_action) >= 2
            ):
                character_id = character_action[0]
                interaction_id = character_action[1]
            else:
                character_id = interaction_id = None
            if character_id and interaction_id:
                self.perform_character_interaction(
                    self.player_side,
                    character_id,
                    interaction_id,
                    defer=False,
                )
        if player_action:
            self.perform(self.player_side, player_action, target=target)
        else:
            self._auto_play_side(self.player_side, self.actions_left)
        return self.end_turn()

    def _auto_play_side(self, side, budget):
        """Потратить бюджет действий стороны на автоматический выбор."""
        for _ in range(max(0, int(budget))):
            if self.finished:
                break
            faction = self.faction(side)
            if faction is None or faction.dissolved:
                break
            action_id = self.auto_action(side)
            if action_id is None:
                break
            result = self.perform(side, action_id)
            if not result.get("ok"):
                break

    def end_turn(self):
        """Завершить текущий ход: ИИ действует, органы и организации тикают."""
        if self.finished:
            return self.snapshot()
        self.begin_turn()
        for side in list(self.factions):
            if side == self.player_side or self.finished:
                continue
            faction = self.faction(side)
            if faction is None or faction.dissolved:
                continue
            self._auto_play_side(side, self.actions_per_cycle)
        self._tick_organizations()
        self._check_outcome()
        self.history.append(self._history_record())
        self.actions_left = 0
        self._turn_active = False
        return self.snapshot()

    def run(self, turns=None, player_action=None, target=None):
        if turns is None:
            limit = self.cycle_limit or DEFAULT_RUN_TURNS
        else:
            limit = max(0, int(turns))
        for _ in range(limit):
            if self.finished:
                break
            self.advance(player_action=player_action, target=target)
        return self.snapshot()
