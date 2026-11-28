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
from .cognition.errors import BackendError, SnapshotError, SoarError
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

    def _soar_available(self):
        """Есть ли пакет Soar; кэшируется на кампанию."""
        cached = getattr(self, "_soar_available_cache", None)
        if cached is None:
            from .cognition.soar_runtime import soar_available

            cached = bool(soar_available())
            self._soar_available_cache = cached
        return cached

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
        if backend in ("shadow", "soar") and not self._soar_available():
            # Колесо soar-sml собрано не под все платформы. Soar повторяет
            # формулу NeedPolicy и tie-break один в один, поэтому выбор
            # тот же; отсутствие пакета видно в отчёте как unavailable.
            self.npc_decision_monitor().unavailable = True
            return "legacy"
        return backend

    def npc_decision_timeout_ms(self):
        """Бюджет решения: локальный ``timeout_ms`` или общий флаг."""
        config = self._npc_config()
        timeout = _number(config.get("timeout_ms"), 0.0)
        if timeout <= 0.0:
            timeout = self._cognition_flags().decision_timeout_ms
        return float(timeout)

    def npc_tick_timeout_ms(self):
        """Бюджет Soar на ход: локальный ``tick_timeout_ms`` или флаг."""
        config = self._npc_config()
        timeout = _number(config.get("tick_timeout_ms"), 0.0)
        if timeout <= 0.0:
            timeout = self._cognition_flags().tick_timeout_ms
        return float(timeout)

    def reset_npc_tick_budget(self):
        """Начать новый ход: израсходованное время решений обнуляется."""
        self._npc_tick_spent_ms = 0.0

    def npc_tick_budget(self):
        """Остаток бюджета тика для диагностики и тестов."""
        limit = self.npc_tick_timeout_ms()
        spent = float(getattr(self, "_npc_tick_spent_ms", 0.0) or 0.0)
        return {
            "limit_ms": round(limit, 3),
            "spent_ms": round(spent, 3),
            "left_ms": round(max(0.0, limit - spent), 3),
        }

    def npc_decision_monitor(self):
        monitor = getattr(self, "_npc_decision_monitor", None)
        if monitor is None:
            monitor = NpcDecisionMonitor()
            self._npc_decision_monitor = monitor
        return monitor

    def _rl_config(self):
        return _as_mapping(self._npc_config().get("rl"))

    def rl_enabled(self):
        """Включён ли сбор эпизодов для RL-предпочтений."""

        return bool(self._rl_config().get("enabled", False))

    @staticmethod
    def _rl_satisfaction(leader):
        needs = _as_mapping(getattr(leader, "needs", {}))
        if not needs:
            return 0.0
        values = [_clamp(value) for value in needs.values()]
        return 1.0 - sum(values) / float(len(values))

    def _rl_context(self, side, leader, satisfaction):
        band = min(3, max(0, int(satisfaction * 4.0)))
        archetype = _text(getattr(leader, "archetype", "")) or "unknown"
        return "%s|%s|%d" % (_text(side), archetype, band)

    def _rl_observe(self, side, leader, candidates, chosen):
        """Записать ход в эпизод RL: награда — прирост нужд.

        Награда за решение известна только на следующем ходу, поэтому
        эпизод закрывается при следующем выборе той же стороны.
        """

        if not self.rl_enabled() or chosen is None:
            return
        config = self._rl_config()
        limit = max(
            1, int(_number(config.get("max_episodes"), 512))
        )
        episodes = getattr(self, "_rl_episodes", None)
        if episodes is None:
            episodes = []
            self._rl_episodes = episodes
        pending = getattr(self, "_rl_pending", None)
        if pending is None:
            pending = {}
            self._rl_pending = pending
        satisfaction = self._rl_satisfaction(leader)
        key = _text(side)
        previous = pending.get(key)
        if previous is not None:
            episodes.append(
                {
                    "context": previous["context"],
                    "candidates": list(previous["candidates"]),
                    "chosen": previous["chosen"],
                    "reward": round(
                        satisfaction - previous["satisfaction"], 6
                    ),
                }
            )
            if len(episodes) > limit:
                del episodes[: len(episodes) - limit]
        names = [str(option) for option, _need, _base in candidates]
        if str(chosen) not in names:
            pending.pop(key, None)
            return
        pending[key] = {
            "context": self._rl_context(side, leader, satisfaction),
            "candidates": names,
            "chosen": str(chosen),
            "satisfaction": satisfaction,
        }

    def rl_episode_report(self):
        """Собранные эпизоды RL и последнее сравнение с легаси."""

        episodes = list(getattr(self, "_rl_episodes", ()) or ())
        comparison = getattr(self, "_rl_comparison", None)
        enabled = self.rl_enabled()
        return {
            "enabled": enabled,
            "episodes": len(episodes),
            "contexts": len(
                {str(item.get("context")) for item in episodes}
            ),
            "pending": len(getattr(self, "_rl_pending", {}) or {}),
            "last_reward": (
                round(float(episodes[-1].get("reward", 0.0)), 6)
                if episodes
                else 0.0
            ),
            "comparison": comparison,
            "ok": bool(
                not enabled
                or comparison is None
                or comparison.get("ok")
            ),
        }

    def rl_compare(self, episodes=None):
        """Обучить RL на эпизодах и сравнить с записанным выбором."""

        from .cognition.soar_rl import compare_episodes

        items = list(
            episodes
            if episodes is not None
            else getattr(self, "_rl_episodes", ()) or ()
        )
        config = dict(self._rl_config())
        if "seed" not in config:
            config["seed"] = int(getattr(self, "seed", 0) or 0)
        report = compare_episodes(items, config=config)
        self._rl_comparison = report
        return report

    def _faction_config(self):
        return _as_mapping(
            _as_mapping(self.ai_model).get("faction_policy")
        )

    def faction_backend(self, side):
        """Бэкенд решений фракции: ``backends`` → ``backend`` → флаг."""

        config = self._faction_config()
        if not config or not bool(config.get("enabled", True)):
            return "legacy"
        backends = _as_mapping(config.get("backends"))
        value = backends.get(str(side))
        if value is None:
            value = config.get("backend")
        if value is None:
            value = self._cognition_flags().ai_backend
        backend = str(value or "legacy")
        if backend not in AI_BACKENDS:
            raise BackendError(
                "faction_policy.backend=%r не поддерживается; допустимо: %s"
                % (backend, ", ".join(AI_BACKENDS))
            )
        if backend in ("shadow", "soar") and not self._soar_available():
            # Без soar-sml рулетка остаётся легаси; факт виден в отчёте.
            self.faction_decision_monitor().unavailable = True
            return "legacy"
        return backend

    def faction_decision_timeout_ms(self):
        """Бюджет решения фракции: локальный ``timeout_ms`` или флаг."""

        config = self._faction_config()
        timeout = _number(config.get("timeout_ms"), 0.0)
        if timeout <= 0.0:
            timeout = self._cognition_flags().decision_timeout_ms
        return float(timeout)

    def faction_tick_timeout_ms(self):
        """Бюджет Soar на ход для фракции: локальный или общий флаг."""

        config = self._faction_config()
        timeout = _number(config.get("tick_timeout_ms"), 0.0)
        if timeout <= 0.0:
            timeout = self._cognition_flags().tick_timeout_ms
        return float(timeout)

    def faction_decision_monitor(self):
        monitor = getattr(self, "_faction_decision_monitor", None)
        if monitor is None:
            from .cognition.faction_runtime import (
                FactionDecisionMonitor,
            )

            monitor = FactionDecisionMonitor()
            self._faction_decision_monitor = monitor
        return monitor

    def faction_decision_report(
        self,
        threshold=DEFAULT_AGREEMENT_THRESHOLD,
    ):
        """Сводка согласия Soar с легаси по действиям и приказам."""

        return self.faction_decision_monitor().report(threshold)

    def _soar_faction(self):
        policy = getattr(self, "_soar_faction_obj", None)
        if policy is None:
            from .cognition.faction_runtime import SoarFactionPolicy

            policy = SoarFactionPolicy(
                timeout_ms=self.faction_decision_timeout_ms()
            )
            self._soar_faction_obj = policy
        return policy

    def _faction_select(self, *, side, kind, candidates, roll):
        """Выбрать id рулеткой: легаси, теневой Soar или строгий Soar.

        ``roll`` берётся из ``self.rng`` один раз и передаётся и легаси,
        и Soar: расход генератора не меняется, поэтому снимок кампании
        совпадает во всех режимах.
        """

        from .cognition.faction_runtime import roulette_choice

        candidates = list(candidates)
        legacy = roulette_choice(candidates, roll)
        if legacy is None:
            return None
        backend = self.faction_backend(side)
        if backend == "legacy":
            return legacy
        limit = self.faction_tick_timeout_ms()
        spent = float(getattr(self, "_npc_tick_spent_ms", 0.0) or 0.0)
        left = max(0.0, limit - spent)
        elapsed_ms = 0.0
        error = None
        candidate = None
        if left <= 0.0:
            error = (
                "бюджет тика исчерпан: %.2f мс из %.2f мс"
                % (spent, limit)
            )
        else:
            soar = self._soar_faction()
            decision = self.faction_decision_timeout_ms()
            budget = min(decision, left) if decision > 0 else left
            try:
                candidate = soar.choose(
                    candidates, roll, timeout_ms=budget
                )
            except (BackendError, SoarError) as exc:
                if backend == "soar":
                    raise
                error = str(exc)
            finally:
                elapsed_ms = float(soar.last_elapsed_ms)
                self._npc_tick_spent_ms = spent + elapsed_ms
        monitor = self.faction_decision_monitor()
        if backend == "soar" and error is None:
            monitor.note(
                kind=kind, side=side, elapsed_ms=elapsed_ms
            )
            return candidate
        monitor.record(
            kind=kind,
            side=side,
            backend=backend,
            legacy=legacy,
            candidate=candidate,
            elapsed_ms=elapsed_ms,
            error=error,
            turn=getattr(self, "turn", None),
            budget=left <= 0.0,
        )
        return legacy

    def _reaction_config(self):
        return _as_mapping(
            _as_mapping(self.ai_model).get("reaction_policy")
        )

    def reaction_backend(self, side):
        """Бэкенд реакции на доклад: ``backends`` → ``backend`` → флаг."""

        config = self._reaction_config()
        if not config or not bool(config.get("enabled", True)):
            return "legacy"
        backends = _as_mapping(config.get("backends"))
        value = backends.get(str(side))
        if value is None:
            value = config.get("backend")
        if value is None:
            value = self._cognition_flags().ai_backend
        backend = str(value or "legacy")
        if backend not in AI_BACKENDS:
            raise BackendError(
                "reaction_policy.backend=%r не поддерживается; "
                "допустимо: %s" % (backend, ", ".join(AI_BACKENDS))
            )
        if backend in ("shadow", "soar") and not self._soar_available():
            # Без soar-sml решение остаётся легаси; факт виден в отчёте.
            self.reaction_decision_monitor().unavailable = True
            return "legacy"
        return backend

    def reaction_decision_timeout_ms(self):
        """Бюджет решения реакции: локальный ``timeout_ms`` или флаг."""

        config = self._reaction_config()
        timeout = _number(config.get("timeout_ms"), 0.0)
        if timeout <= 0.0:
            timeout = self._cognition_flags().decision_timeout_ms
        return float(timeout)

    def reaction_tick_timeout_ms(self):
        """Бюджет Soar на ход для реакции: локальный или общий флаг."""

        config = self._reaction_config()
        timeout = _number(config.get("tick_timeout_ms"), 0.0)
        if timeout <= 0.0:
            timeout = self._cognition_flags().tick_timeout_ms
        return float(timeout)

    def reaction_decision_monitor(self):
        monitor = getattr(self, "_reaction_decision_monitor", None)
        if monitor is None:
            from .cognition.reaction_runtime import (
                ReactionDecisionMonitor,
            )

            monitor = ReactionDecisionMonitor()
            self._reaction_decision_monitor = monitor
        return monitor

    def reaction_decision_report(
        self,
        threshold=DEFAULT_AGREEMENT_THRESHOLD,
    ):
        """Сводка согласия Soar с легаси по докладам и угрозам."""

        return self.reaction_decision_monitor().report(threshold)

    def _soar_reaction(self):
        policy = getattr(self, "_soar_reaction_obj", None)
        if policy is None:
            from .cognition.reaction_runtime import SoarReactionPolicy

            policy = SoarReactionPolicy(
                timeout_ms=self.reaction_decision_timeout_ms()
            )
            self._soar_reaction_obj = policy
        return policy

    def _report_select(self, *, side, kind, candidates):
        """Выбрать реакцию на доклад: легаси, теневой Soar или строгий Soar.

        Оценки вариантов и шум уже посчитаны диспетчером — Soar получает
        готовые числа и не трогает ``rng``. Поэтому расход генератора и
        снимок кампании совпадают во всех режимах.
        """

        from .cognition.reaction_runtime import reaction_choice

        candidates = list(candidates)
        legacy = reaction_choice(candidates)
        if legacy is None:
            return None
        backend = self.reaction_backend(side)
        if backend == "legacy":
            return legacy
        limit = self.reaction_tick_timeout_ms()
        spent = float(getattr(self, "_npc_tick_spent_ms", 0.0) or 0.0)
        left = max(0.0, limit - spent)
        elapsed_ms = 0.0
        error = None
        candidate = None
        if left <= 0.0:
            error = (
                "бюджет тика исчерпан: %.2f мс из %.2f мс"
                % (spent, limit)
            )
        else:
            soar = self._soar_reaction()
            decision = self.reaction_decision_timeout_ms()
            budget = min(decision, left) if decision > 0 else left
            try:
                candidate = soar.choose(
                    candidates, timeout_ms=budget
                )
            except (BackendError, SoarError) as exc:
                if backend == "soar":
                    raise
                error = str(exc)
            finally:
                elapsed_ms = float(soar.last_elapsed_ms)
                self._npc_tick_spent_ms = spent + elapsed_ms
        monitor = self.reaction_decision_monitor()
        if backend == "soar" and error is None:
            monitor.note(
                kind=kind, side=side, elapsed_ms=elapsed_ms
            )
            return candidate
        monitor.record(
            kind=kind,
            side=side,
            backend=backend,
            legacy=legacy,
            candidate=candidate,
            elapsed_ms=elapsed_ms,
            error=error,
            turn=getattr(self, "turn", None),
            budget=left <= 0.0,
        )
        return legacy

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
        intentions = self.intention_report()
        factions = self.faction_decision_report(threshold)
        reactions = self.reaction_decision_report(threshold)
        agents = self.soar_agent_report()
        mass_npc = self.mass_npc_report()
        rl = self.rl_episode_report()
        return {
            "kind": "npc_outcomes",
            "version": MONITOR_VERSION,
            "needs": self.npc_needs_summary(),
            "jobs": decisions["jobs"],
            "decisions": decisions,
            "intentions": intentions,
            "factions": factions,
            "reactions": reactions,
            "agents": agents,
            "mass_npc": mass_npc,
            "rl": rl,
            "ok": bool(
                decisions["ok"]
                and intentions["ok"]
                and factions["ok"]
                and reactions["ok"]
                and not agents["errors"]
                and mass_npc["ok"]
                and rl["ok"]
            ),
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

    def _npc_pool_config(self):
        return _as_mapping(self._npc_config().get("agent_pool"))

    def _soar_npc_pool(self):
        """Пул долгоживущих агентов именных NPC; создаётся лениво."""

        pool = getattr(self, "_soar_npc_pool_obj", None)
        if pool is None:
            from .cognition.soar_npc import (
                DEFAULT_MAX_AGENTS,
                DEFAULT_MAX_BELIEFS,
                DEFAULT_MAX_INTENTIONS,
                SoarNpcPool,
            )

            config = self._npc_pool_config()
            pool = SoarNpcPool(
                max_agents=max(
                    1,
                    int(
                        _number(
                            config.get("max_agents"),
                            DEFAULT_MAX_AGENTS,
                        )
                    ),
                ),
                max_beliefs=max(
                    0,
                    int(
                        _number(
                            config.get("max_beliefs"),
                            DEFAULT_MAX_BELIEFS,
                        )
                    ),
                ),
                max_intentions=max(
                    0,
                    int(
                        _number(
                            config.get("max_intentions"),
                            DEFAULT_MAX_INTENTIONS,
                        )
                    ),
                ),
                timeout_ms=self.npc_decision_timeout_ms(),
            )
            self._soar_npc_pool_obj = pool
        return pool

    @staticmethod
    def _npc_agent_id(side, leader):
        character_id = _text(getattr(leader, "campaign_id", ""))
        if character_id:
            return "npc:%s" % character_id
        return "npc:%s" % _text(side)

    def soar_snapshot(self):
        """JSON-снимок всех долгоживущих агентов или ``None``."""

        pool = getattr(self, "_soar_npc_pool_obj", None)
        if pool is None:
            return None
        return pool.snapshot()

    def restore_soar_snapshot(self, data):
        """Загрузить снимок агентов; пустой блок — no-op."""

        if not data:
            return None
        pool = self._soar_npc_pool()
        pool.restore(data)
        return pool.snapshot()

    def soar_agent_report(self):
        pool = getattr(self, "_soar_npc_pool_obj", None)
        if pool is None:
            return {
                "agents": 0,
                "max_agents": 0,
                "starts": 0,
                "evictions": 0,
                "saved": 0,
                "decisions": 0,
                "errors": 0,
                "ids": [],
            }
        return pool.report()

    @staticmethod
    def _npc_explore(policy):
        if not bool(getattr(policy, "explore", False)):
            return False
        return _number(getattr(policy, "epsilon", 0.0), 0.0) > 0.0

    def _soar_candidate(
        self, policy, candidates, needs, soar, timeout_ms=None
    ):
        from .cognition.soar_runtime import weights_for

        names = sorted(
            {str(need) for _option, need, _base in candidates}
        )
        return soar.choose(
            candidates,
            needs,
            weights=weights_for(policy, names),
            explore=self._npc_explore(policy),
            timeout_ms=timeout_ms,
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
            legacy = policy.choose(candidates, needs)
            self._rl_observe(side, leader, candidates, legacy)
            return legacy
        limit = self.npc_tick_timeout_ms()
        spent = float(getattr(self, "_npc_tick_spent_ms", 0.0) or 0.0)
        left = max(0.0, limit - spent)
        elapsed_ms = 0.0
        error = None
        candidate = None
        if left <= 0.0:
            error = (
                "бюджет тика исчерпан: %.2f мс из %.2f мс"
                % (spent, limit)
            )
        else:
            # Политика создаётся только когда решение действительно
            # будет считаться: при исчерпанном бюджете Soar не нужен.
            decision = self.npc_decision_timeout_ms()
            budget = min(decision, left) if decision > 0 else left
            if leader is not None:
                # Именной NPC получает своего долгоживущего агента с
                # BDI-памятью; без лидера остаётся одноразовый селектор.
                from .cognition.soar_runtime import weights_for

                names = sorted(
                    {str(need) for _option, need, _base in candidates}
                )
                agent = None
                try:
                    agent = self._soar_npc_pool().get(
                        self._npc_agent_id(side, leader),
                        leader,
                        tick=int(getattr(self, "turn", 0) or 0),
                    )
                    candidate = agent.choose(
                        candidates,
                        needs,
                        weights=weights_for(policy, names),
                        timeout_ms=budget,
                    )
                except (BackendError, SnapshotError, SoarError) as exc:
                    if backend == "soar":
                        raise
                    error = str(exc)
                finally:
                    elapsed_ms = float(
                        getattr(agent, "last_elapsed_ms", 0.0)
                    )
                    self._npc_tick_spent_ms = spent + elapsed_ms
            else:
                soar = self._soar_policy()
                try:
                    candidate = self._soar_candidate(
                        policy,
                        candidates,
                        needs,
                        soar,
                        timeout_ms=budget,
                    )
                except (BackendError, SoarError) as exc:
                    if backend == "soar":
                        raise
                    error = str(exc)
                finally:
                    elapsed_ms = float(soar.last_elapsed_ms)
                    self._npc_tick_spent_ms = spent + elapsed_ms
        if backend == "soar" and error is None:
            self.npc_decision_monitor().note_decision(
                side=side, elapsed_ms=elapsed_ms
            )
            self._rl_observe(side, leader, candidates, candidate)
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
            budget=left <= 0.0,
        )
        self._rl_observe(side, leader, candidates, legacy)
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
            roll = self.rng.random()
            chosen = self._faction_select(
                side=side,
                kind="action",
                candidates=[
                    (option["id"], weight)
                    for option, weight in weighted
                ],
                roll=roll,
            )
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
