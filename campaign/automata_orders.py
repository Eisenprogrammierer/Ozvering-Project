"""Заказы фракций и тик организаций."""

from __future__ import annotations

from .automata_support import (
    EVENT_LOG_LIMIT,
    _as_mapping,
    _clamp,
    _number,
    _order_payload,
    _text,
    apply_effects,
    check_conditions,
    delta_map,
    logger,
    run_routine_day,
    tick_organs,
)


class AutomataOrdersMixin:

    def _tick_faction_orders(self, faction):
        """Отдать приказ от фракции персонажу на организационном такте.

        Приказы — данные ``order_model.orders``. Игровая сторона не
        получает автоматических приказов: её направляет игрок
        (``issue_order``).
        """
        model = _as_mapping(self.order_model)
        if not model or not bool(model.get("enabled", True)):
            return None
        if faction.side == self.player_side or not faction.orders:
            return None
        interval = max(1, int(_number(model.get("interval"), 1)))
        if faction.last_order_turn and (
            int(self.turn) - int(faction.last_order_turn) < interval
        ):
            return None
        limit = max(1, int(_number(model.get("max_per_tick"), 1)))
        result = None
        for _ in range(limit):
            selected = self._choose_order(faction)
            if selected is None:
                break
            issued = self.issue_order(faction.side, selected["id"])
            if not issued.get("ok"):
                break
            result = issued
        return result

    def _choose_order(self, faction):
        """Выбрать доступный приказ по весам ``priority`` из данных."""
        options = [
            item
            for item in self.order_options(faction.side)
            if item["enabled"]
        ]
        if not options:
            return None
        weights = [
            max(1e-6, _number(item["order"].get("priority"), 1.0))
            for item in options
        ]
        candidates = [
            (str(item["order"].get("id")), weight)
            for item, weight in zip(options, weights)
        ]
        roll = self.rng.random()
        selected = self._faction_select(
            side=faction.side,
            kind="order",
            candidates=candidates,
            roll=roll,
        )
        if selected is None:
            return None
        for item in options:
            if str(item["order"].get("id")) == str(selected):
                return item["order"]
        return options[-1]["order"]

    def _order_cooldown_left(self, faction, order):
        cooldown = max(
            0,
            int(
                _number(
                    order.get("cooldown"),
                    self.order_model.get("cooldown", 1),
                )
            ),
        )
        if cooldown <= 0:
            return 0
        last = faction.order_cooldowns.get(str(order.get("id")))
        if last is None:
            return 0
        return max(0, cooldown + 1 - (int(self.turn) - int(last)))

    def _order_affordable(self, faction, order):
        cost = _as_mapping(order.get("cost"))
        return all(
            faction.asset(key) + 1e-9 >= _number(value)
            for key, value in cost.items()
        )

    def _order_requirement_reason(self, faction, order):
        requires = _as_mapping(order.get("requires"))
        reason = self._asset_requirement_reason(
            "нужно", faction.assets, requires.get("self")
        )
        if reason:
            return reason
        when = requires.get("when")
        if when is None:
            when = order.get("when")
        return check_conditions(when, self._condition_context(faction))

    def _order_targets(self, faction, order, character_id=None):
        alive = [
            character
            for character in faction.characters
            if not bool(
                getattr(
                    character,
                    "is_dead",
                    getattr(character, "dead", False),
                )
            )
        ]
        if not alive:
            return []
        if character_id:
            wanted = str(character_id)
            return [
                character
                for character in alive
                if str(getattr(character, "campaign_id", "")) == wanted
            ]
        recipient = _text(
            order.get("recipient") or self.order_model.get("recipient"),
            "priority",
        )
        if recipient in ("all", "everyone", "broadcast"):
            return alive
        if recipient == "leader":
            return alive[:1]
        if recipient == "lowest_morale":
            return [
                min(
                    alive,
                    key=lambda item: _number(
                        getattr(item, "morale", 0.0)
                    ),
                )
            ]
        if recipient == "highest_morale":
            return [
                max(
                    alive,
                    key=lambda item: _number(
                        getattr(item, "morale", 0.0)
                    ),
                )
            ]

        def need_score(character):
            values = [
                _clamp(value)
                for value in _as_mapping(
                    getattr(character, "needs", {})
                ).values()
            ]
            return sum(values) / float(len(values)) if values else 1.0

        return [min(alive, key=need_score)]

    def order_options(self, side):
        """Приказы стороны с причиной недоступности (UI и тесты)."""
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        options = []
        for order in faction.orders:
            cost = _as_mapping(order.get("cost"))
            left = self._order_cooldown_left(faction, order)
            requirement = self._order_requirement_reason(faction, order)
            affordable = self._order_affordable(faction, order)
            if requirement:
                reason = requirement
            elif left > 0:
                reason = "перезарядка ещё %d" % left
            elif not affordable:
                reason = "не хватает состояния"
            else:
                reason = ""
            options.append(
                {
                    "order": order,
                    "id": str(order.get("id")),
                    "label": str(order.get("label") or order.get("id")),
                    "description": str(order.get("description") or ""),
                    "priority": round(
                        _number(order.get("priority"), 1.0), 6
                    ),
                    "recipient": _text(
                        order.get("recipient")
                        or self.order_model.get("recipient"),
                        "priority",
                    ),
                    "cooldown": left,
                    "cost": {
                        str(key): round(_number(value), 6)
                        for key, value in cost.items()
                    },
                    "enabled": not reason,
                    "reason": reason,
                }
            )
        return options

    def _apply_order_relations(self, faction, character, order):
        """Записать отношение приказа «фракция → персонаж»."""
        raw = _as_mapping(order.get("relations"))
        if not raw or self.relations is None:
            return []
        axes = _as_mapping(raw.get("axes")) if "axes" in raw else raw
        if not axes:
            return []
        mode = _text(raw.get("source") or raw.get("from"), "faction")
        faction_id = str(getattr(faction, "id", "") or "")
        character_id = str(
            getattr(character, "campaign_id", "") or ""
        )
        if not faction_id or not character_id:
            return []
        if mode in ("character", "target", "self_character"):
            source, target = character_id, faction_id
        else:
            source, target = faction_id, character_id
        changes = self.relations.add(source, target, axes, 1.0)
        return [
            {
                "source": source,
                "target": target,
                "axis": str(axis),
                "delta": delta,
            }
            for axis, delta in changes.items()
        ]

    def issue_order(self, side, order_id, character_id=None):
        """Отдать приказ фракции конкретному персонажу.

        Игрок и ИИ используют один путь: проверка требований → эффекты
        через ``apply_effects`` → отношения → расход цены → перезарядка.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        order = next(
            (
                item
                for item in faction.orders
                if str(item.get("id")) == str(order_id)
            ),
            None,
        )
        if order is None:
            return {"ok": False, "reason": "приказ не найден"}
        option = next(
            (
                item
                for item in self.order_options(side)
                if item["id"] == str(order_id)
            ),
            None,
        )
        if option is None or not option["enabled"]:
            return {
                "ok": False,
                "reason": (
                    option.get("reason")
                    if option is not None
                    else "приказ недоступен"
                ),
            }
        targets = self._order_targets(faction, order, character_id)
        if not targets:
            return {"ok": False, "reason": "нет персонажа для приказа"}
        cost = _as_mapping(order.get("cost"))
        broadcast = (
            not character_id
            and option["recipient"] in ("all", "everyone", "broadcast")
            and len(targets) > 1
        )
        applied = []
        relations = []
        agency_memory = []
        for character in targets:
            payload = _order_payload(
                order.get("effects"),
                "" if broadcast else getattr(character, "campaign_id", ""),
            )
            applied.append(
                apply_effects(
                    faction,
                    payload,
                    target=faction,
                    scale=1.0,
                    source="order",
                )
            )
            relations.extend(
                self._apply_order_relations(faction, character, order)
            )
            memory = self._remember_order(character, order, faction)
            agency_memory.append(
                {
                    "id": str(
                        getattr(character, "campaign_id", "") or ""
                    ),
                    "name": str(
                        getattr(character, "name", "") or ""
                    ),
                    **memory,
                }
            )
        for key, value in cost.items():
            faction.add_asset(key, -_number(value))
        cooldown = max(
            0,
            int(
                _number(
                    order.get("cooldown"),
                    self.order_model.get("cooldown", 1),
                )
            ),
        )
        if cooldown > 0:
            faction.order_cooldowns[str(order.get("id"))] = int(self.turn)
        faction.last_order_turn = int(self.turn)
        record = {
            "turn": int(self.turn),
            "side": faction.side,
            "order_id": str(order.get("id")),
            "label": option["label"],
            "description": option["description"],
            "recipient": option["recipient"],
            "characters": [
                {
                    "id": str(
                        getattr(character, "campaign_id", "") or ""
                    ),
                    "name": str(getattr(character, "name", "") or ""),
                }
                for character in targets
            ],
            "cost": dict(option["cost"]),
            "relations": relations,
            "agency": agency_memory,
            "applied": applied,
        }
        faction.last_order = {
            key: value
            for key, value in record.items()
            if key != "applied"
        }
        detail = "ход %d: %s отдаёт приказ «%s» → %s" % (
            self.turn,
            faction.name,
            record["label"],
            ", ".join(
                item["name"] or item["id"]
                for item in record["characters"]
            )
            or "никому",
        )
        self.events.append(
            {
                "turn": self.turn,
                "kind": "order",
                "text": detail,
                "side": faction.side,
                "order_id": record["order_id"],
                "actor": faction.name,
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]
        self.last_order_result = record
        result = {"ok": True}
        result.update(record)
        return result

    def _tick_faction_characters(self, faction, seconds):
        """Дать BDI персонажей прожить организационный интервал.

        Активы фракции производны от потребностей, морали и силы людей,
        поэтому без этого шага «политические» шкалы выглядели бы
        застывшими между редкими взаимодействиями. Сутки моделируются
        целиком: рутина кормит, поит, даёт сон и уход, а не оставляет
        персонажей без еды на 47 из 48 тактов BDI. Насколько хорошо
        закрыта норма, решают готовность людей и производный ``supply``.
        """
        stored = _as_mapping(faction.organization_snapshot)
        support = _clamp(stored.get("willing_share", 0.5))
        supply = _clamp(faction.asset("supply"))
        for character in faction.characters:
            if bool(
                getattr(
                    character,
                    "is_dead",
                    getattr(character, "dead", False),
                )
            ):
                continue
            if not callable(getattr(character, "tick_needs", None)):
                continue
            before = (
                self.stats.character_state(character)
                if self.stats.enabled
                else None
            )
            try:
                routine = run_routine_day(
                    character,
                    seconds,
                    support=support,
                    supply=supply,
                    config=self.routine,
                    rng=getattr(character, "rng", None),
                )
            except Exception:
                logger.exception(
                    "BDI персонажа %s не обновлён",
                    getattr(character, "name", "?"),
                )
                continue
            if before is None:
                continue
            after = self.stats.character_state(character)
            self.stats.log(
                "bdi",
                side=faction.side,
                character_id=before.get("id"),
                name=before.get("name"),
                post=before.get("post"),
                support=round(support, 6),
                supply=round(supply, 6),
                interval_seconds=round(float(seconds), 3),
                simulated_seconds=(
                    round(float(routine.get("seconds", 0.0)), 3)
                    if routine
                    else 0.0
                ),
                routine=routine,
                before=before,
                after=after,
                delta=self.stats.character_delta(before, after),
            )

    def _tick_organizations(self):
        seconds = max(30.0, float(self.organization_interval_seconds))
        self._tick_machines()
        for faction in self.factions.values():
            before = (
                self.stats.faction_state(faction)
                if self.stats.enabled
                else None
            )
            self._tick_faction_characters(faction, seconds)
            self._tick_character_autonomy(faction, seconds)
            self._tick_faction_orders(faction)
            if faction.organization is None:
                faction.relax_context(self.model["asset_relax"])
                for key, value in faction.income.items():
                    faction.bump_context(key, value)
                for key, value in self.upkeep.items():
                    faction.bump_context(key, -value)
                tick_organs(faction, faction.organs, self.model)
                self._log_tick_stats(faction, seconds, before)
                continue
            snapshot = faction.organization.tick(turn=self.turn)
            initial = max(
                1,
                len(faction.characters)
                or int(_number(snapshot.get("initial_count"), 1)),
            )
            active = int(_number(snapshot.get("active_count"), initial))
            willing_count = int(_number(snapshot.get("willing_count"), active))
            willing = _clamp(willing_count / float(initial))
            share = _clamp(active / float(initial))
            snapshot = dict(snapshot)
            snapshot.update(
                {
                    "initial_count": initial,
                    "active_count": active,
                    "willing_count": willing_count,
                    "willing_share": willing,
                    "active_share": share,
                }
            )
            faction.organization_snapshot = snapshot
            if not snapshot.get("active", True):
                faction.dissolved = True
            # Это не запись в независимый кошелёк, а контекстные
            # импульсы организации: производные активы читают их вместе
            # с BDI людей и целостностью сети.
            faction.bump_context(
                "cohesion",
                self.model["organization_cohesion"] * (willing - 0.5),
            )
            faction.bump_context(
                "legitimacy",
                self.model["organization_legitimacy"] * (share - 0.5),
            )
            faction.bump_context(
                "supply", -self.model["organization_supply_drain"]
            )
            mode_weights = _as_mapping(snapshot.get("mode_weights"))
            faction.bump_context(
                "fear",
                self.model["organization_fear"]
                * _number(mode_weights.get("order"), 0.0),
            )
            faction.bump_context(
                "morale",
                self.model["organization_morale"] * share,
            )
            faction.relax_context(self.model["asset_relax"])
            for key, value in faction.income.items():
                faction.bump_context(key, value)
            for key, value in self.upkeep.items():
                faction.bump_context(key, -value)
            tick_organs(faction, faction.organs, self.model)
            self._log_tick_stats(faction, seconds, before)

    def _log_tick_stats(self, faction, seconds, before):
        """Записать дневной срез: активы, их формулы и BDI-сводку."""
        if before is None or not self.stats.enabled:
            return
        after = self.stats.faction_state(faction)
        self.stats.log(
            "tick",
            side=faction.side,
            faction=faction.name,
            seconds=round(float(seconds), 3),
            assets_before=before.get("assets"),
            assets_after=after.get("assets"),
            asset_deltas=delta_map(
                before.get("assets"), after.get("assets")
            ),
            context_before=before.get("context"),
            context_after=after.get("context"),
            context_deltas=delta_map(
                before.get("context"), after.get("context")
            ),
            organization=after.get("organization"),
            characters=after.get("characters"),
            breakdowns=self.stats.breakdowns(faction),
            low_streaks={
                str(key): int(value)
                for key, value in faction.low_streaks.items()
            },
            dissolved=bool(faction.dissolved),
        )

    def _check_outcome(self):
        if self.outcome is not None:
            return
        rules = self.outcome_rules
        streak_limit = max(
            1,
            int(
                _number(
                    rules.get("streak_turns"),
                    self.model["collapse_streak"],
                )
            ),
        )
        checks = []
        notable = False
        for side, thresholds in _as_mapping(rules.get("defeat")).items():
            faction = self.faction(side)
            if faction is None:
                continue
            for asset, threshold in _as_mapping(thresholds).items():
                key = "%s:%s" % (side, asset)
                value = faction.asset(asset)
                limit = _number(threshold, 0.0)
                if value <= limit + 1e-9:
                    faction.low_streaks[key] = (
                        faction.low_streaks.get(key, 0) + 1
                    )
                else:
                    faction.low_streaks[key] = 0
                streak = faction.low_streaks.get(key, 0)
                if streak:
                    notable = True
                checks.append(
                    {
                        "side": str(side),
                        "asset": str(asset),
                        "value": round(value, 6),
                        "threshold": round(limit, 6),
                        "streak": int(streak),
                        "streak_limit": int(streak_limit),
                    }
                )
                if streak >= streak_limit:
                    decision = (
                        "lose" if side == self.player_side else "win"
                    )
                    if self.stats.enabled and self.stats.outcome:
                        self.stats.log(
                            "outcome",
                            decision=decision,
                            rule="defeat",
                            checks=checks,
                            streak_limit=streak_limit,
                        )
                    self.outcome = decision
                    self.finished = True
                    return
        score_info = None
        if rules.get("score_margin") is not None:
            margin = _number(rules.get("score_margin"), 0.0)
            player = self.player
            rival = self.rival
            basis = str(rules.get("score_basis") or "assets")
            if basis == "progress":

                def measure(faction):
                    return faction.progress()

            else:

                def measure(faction):
                    return faction.score()

            if player is not None and rival is not None:
                player_score = measure(player)
                rival_score = measure(rival)
                difference = (
                    player_score
                    - rival_score
                    + _number(rules.get("score_bias"), 0.0)
                )
                window = max(
                    1, int(_number(rules.get("score_window"), 1))
                )
                self.score_recent.append(difference)
                if len(self.score_recent) > window:
                    del self.score_recent[:-window]
                smoothed = sum(self.score_recent) / float(
                    len(self.score_recent)
                )
                side = (
                    "win"
                    if smoothed > margin
                    else ("lose" if smoothed < -margin else None)
                )
                after = max(1, int(_number(rules.get("score_after"), 1)))
                required = max(
                    1, int(_number(rules.get("score_streak"), 2))
                )
                if self.turn < after:
                    self.score_streak = 0
                    self.score_streak_side = None
                elif side is None:
                    self.score_streak = 0
                    self.score_streak_side = None
                elif side == self.score_streak_side:
                    self.score_streak += 1
                else:
                    self.score_streak = 1
                    self.score_streak_side = side
                if side is not None:
                    notable = True
                score_info = {
                    "basis": basis,
                    "player": round(player_score, 6),
                    "rival": round(rival_score, 6),
                    "difference": round(difference, 6),
                    "smoothed": round(smoothed, 6),
                    "window": int(window),
                    "margin": round(margin, 6),
                    "side": side,
                    "streak": int(self.score_streak),
                    "required": int(required),
                    "after_turn": int(after),
                }
                if (
                    self.turn >= after
                    and side is not None
                    and self.score_streak >= required
                ):
                    if self.stats.enabled and self.stats.outcome:
                        self.stats.log(
                            "outcome",
                            decision=side,
                            rule="score",
                            checks=checks,
                            score=score_info,
                        )
                    self.outcome = side
                    self.finished = True
                    return
        if notable and self.stats.enabled and self.stats.outcome:
            self.stats.log(
                "outcome",
                decision=None,
                rule="score" if score_info else "defeat",
                checks=checks,
                score=score_info,
                streak_limit=streak_limit,
            )
