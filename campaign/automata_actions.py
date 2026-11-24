"""Действия игрока и взаимодействия."""

from __future__ import annotations

from .automata_support import (
    ASSET_LABELS,
    EVENT_LOG_LIMIT,
    Mapping,
    _as_mapping,
    _clamp,
    _number,
    _sigmoid,
    _text,
    apply_effects,
    apply_report,
    asset_reason,
    build_interaction_work,
    build_work,
    check_conditions,
    copy,
    damage_organs,
    delta_map,
    derived_assets,
    logger,
    organ_links,
    readiness_scale,
    receive,
    relation_reason,
    spread_organ_effect,
    strengthen_organ,
    trace_from_report,
)


class AutomataActionsMixin:

    def _player_action_gate(self, side):
        """Проверить бюджет перед действием игрока."""
        if str(side) != self.player_side:
            return None
        if self.finished:
            return "кампания завершена"
        self.ensure_clock()
        if self.actions_left <= 0:
            return (
                "бюджет действий исчерпан: действия восстанавливаются "
                "со временем (до %d за интервал)" % self.actions_per_cycle
            )
        return None

    def _spend_player_action(self, side):
        if str(side) == self.player_side and self.actions_left > 0:
            self.actions_left -= 1

    def _cooldown_left(self, faction, action, turn=None):
        """Сколько ходов ещё нельзя повторять работу.

        ``cooldown=1`` означает один пропущенный ход: работа, использованная
        на ходе ``t``, снова доступна на ходе ``t + 2``. Так значение
        совпадает с текстом «перезарядка ещё N» и одинаково трактуется для
        игрока и для автоматического выбора.
        """
        cooldown = int(
            _number(
                action.get(
                    "cooldown", self.model.get("cooldown_turns")
                ),
                0,
            )
        )
        last = faction.cooldowns.get(str(action.get("id")))
        if cooldown <= 0 or last is None:
            return 0
        current = self.turn if turn is None else int(turn)
        return max(0, cooldown + 1 - (current - int(last)))

    def _action_use_limit(self, action):
        """Сколько раз работу вообще можно выполнить (0 — без лимита)."""
        if action.get("once") is True or action.get("repeatable") is False:
            return 1
        try:
            value = int(_number(action.get("max_uses"), 0))
        except (TypeError, ValueError):
            value = 0
        return max(0, value)

    def _action_use_reason(self, faction, action):
        limit = self._action_use_limit(action)
        used = int(faction.action_uses.get(str(action.get("id")), 0))
        if limit <= 0 or used < limit:
            return ""
        if limit == 1:
            return "уже выполнено"
        return "исчерпано (%d из %d)" % (used, limit)

    @staticmethod
    def _asset_requirement_reason(prefix, assets, conditions):
        """Проверить условия на активы и вернуть первую причину отказа."""
        return asset_reason(prefix, assets, conditions, ASSET_LABELS)

    def _condition_context(self, faction, target=None):
        """Собрать состояние для типизированных условий."""
        return {
            "faction": faction,
            "target": target,
            "character": (
                faction.characters[0] if faction.characters else None
            ),
            "target_character": (
                target.characters[0]
                if target is not None and target.characters
                else None
            ),
            "turn": int(self.turn),
            "used_actions": {
                str(key)
                for key, value in faction.action_uses.items()
                if int(value) > 0
            },
            "labels": ASSET_LABELS,
            "relations": (
                self.relations.view(faction.id)
                if faction is not None
                else {}
            ),
            "target_relations": (
                self.relations.view(target.id)
                if target is not None
                else {}
            ),
            "relation_store": self.relations,
        }

    def _action_requirement_reason(
        self, faction, action, target=None, assets=None
    ):
        """Проверить предпосылки работы: состояния, историю и цели.

        Данные работы могут задавать блок ``requires``:

        * ``self``/``target`` — минимальные/максимальные значения активов;
        * ``used_actions``/``not_used_actions`` — зависимость от истории;
        * ``min_turn`` — самый ранний цикл, когда работа допустима.
        """
        requires = _as_mapping(action.get("requires"))
        if not requires:
            return ""
        minimum_turn = requires.get("min_turn")
        if minimum_turn is not None and self.turn < int(
            _number(minimum_turn, 0)
        ):
            return "доступно с цикла %d" % int(_number(minimum_turn, 0))
        used = {
            str(key)
            for key, value in faction.action_uses.items()
            if int(value) > 0
        }
        required_used = requires.get("used_actions") or ()
        if isinstance(required_used, str):
            required_used = (required_used,)
        for action_id in required_used:
            if str(action_id) not in used:
                return "сначала нужно: %s" % str(action_id)
        forbidden_used = requires.get("not_used_actions") or ()
        if isinstance(forbidden_used, str):
            forbidden_used = (forbidden_used,)
        for action_id in forbidden_used:
            if str(action_id) in used:
                return "несовместимо с: %s" % str(action_id)
        reason = self._asset_requirement_reason(
            "нужно",
            assets if assets is not None else faction.assets,
            requires.get("self"),
        )
        if reason:
            return reason
        if target is not None:
            reason = self._asset_requirement_reason(
                "цель", target.assets, requires.get("target")
            )
            if reason:
                return reason
        reason = relation_reason(
            "нужно",
            requires.get("relations"),
            self.relations,
            getattr(faction, "id", ""),
        )
        if reason:
            return reason
        reason = check_conditions(
            requires.get("when"),
            self._condition_context(faction, target),
        )
        if reason:
            return reason
        return ""

    def _action_cost(self, faction, action):
        """Цена работы с поправкой на курс правящей подфракции.

        Курс — это состояние, а не сюжет: работы органов доминирующей
        подфракции дешевле по политическому ресурсу (``influence``),
        потому что опираются на её аппарат. Материальные расходы не
        меняются, чтобы курс не подменял экономику.
        """
        cost = {
            str(key): _number(value)
            for key, value in _as_mapping(action.get("cost")).items()
            if _number(value)
        }
        course = faction.action_course(action)
        if course.get("aligned") and "influence" in cost:
            discount = max(
                0.0,
                min(0.9, _number(self.model.get("course_cost_discount"))),
            )
            if discount:
                cost["influence"] = round(
                    cost["influence"] * (1.0 - discount), 6
                )
        return cost

    def action_options(self, side, turn=None):
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        assets = derived_assets(faction)
        options = []
        for action in faction.actions:
            cost = self._action_cost(faction, action)
            course = faction.action_course(action)
            affordable = all(
                assets.get(str(key), 0.0) + 1e-9 >= _number(value, 0.0)
                for key, value in cost.items()
            )
            left = self._cooldown_left(faction, action, turn=turn)
            target = self.faction(self._target_side(side, action))
            used_reason = self._action_use_reason(faction, action)
            requirement_reason = self._action_requirement_reason(
                faction, action, target, assets=assets
            )
            if used_reason:
                reason = used_reason
            elif requirement_reason:
                reason = requirement_reason
            elif not affordable:
                reason = "не хватает состояния"
            elif left > 0:
                reason = "перезарядка ещё %d" % left
            else:
                reason = ""
            options.append(
                {
                    "action": action,
                    "id": str(action.get("id")),
                    "label": str(action.get("label") or action.get("id")),
                    "enabled": bool(not reason),
                    "reason": reason,
                    "uses": int(
                        faction.action_uses.get(str(action.get("id")), 0)
                    ),
                    "max_uses": self._action_use_limit(action),
                    "cost": {
                        str(key): round(_number(value), 6)
                        for key, value in cost.items()
                    },
                    "course": dict(course),
                }
            )
        return options

    def available_actions(self, side):
        return [
            item["id"]
            for item in self.action_options(side)
            if item.get("enabled")
        ]

    def organ(self, side, organ_id):
        faction = self.faction(side)
        if faction is None:
            return None
        return faction.organ(organ_id)

    def organ_options(self, side):
        """Снимки органов фракции для графа и кодекса."""
        faction = self.faction(side)
        if faction is None:
            return []
        return [organ.snapshot() for organ in faction.organs]

    def organ_interaction_options(self, side, organ_id):
        """Доступные взаимодействия с конкретным органом."""
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        organ = faction.organ(organ_id)
        if organ is None:
            return []
        assets = derived_assets(faction)
        options = []
        for interaction in organ.interactions:
            cost = _as_mapping(interaction.get("cost"))
            affordable = all(
                assets.get(str(key), 0.0) + 1e-9
                >= _number(value, 0.0)
                for key, value in cost.items()
            )
            left = organ.cooldown_left(interaction, self.turn)
            options.append(
                {
                    "interaction": interaction,
                    "id": str(interaction.get("id")),
                    "label": str(
                        interaction.get("label")
                        or interaction.get("id")
                    ),
                    "description": str(
                        interaction.get("description") or ""
                    ),
                    "integrity": round(
                        _number(interaction.get("integrity")), 6
                    ),
                    "cost": {
                        str(key): round(_number(value), 6)
                        for key, value in cost.items()
                    },
                    "enabled": bool(affordable and left <= 0),
                    "reason": (
                        "не хватает состояния"
                        if not affordable
                        else ("перезарядка ещё %d" % left if left > 0 else "")
                    ),
                }
            )
        return options

    def _busy_interaction(self, side, kind, interaction_id, target_id):
        for record in self._active_processes(side):
            if record.get("kind") != kind:
                continue
            if str(record.get("interaction_id")) != str(interaction_id):
                continue
            if str(record.get("target_id")) != str(target_id):
                continue
            return record
        return None

    def _start_interaction_process(
        self,
        side,
        kind,
        interaction,
        *,
        label,
        description,
        target_id,
        target_name,
    ):
        """Занять слот взаимодействием и применить его по завершении.

        Влияния и команды больше не тратят отдельный запас действий:
        единственный лимит — два слота. Стоимость списывается сразу,
        эффект применяется в :meth:`_finish_process`, когда процесс
        доходит до ``finish_at``. Это позволяет видеть в интерфейсе
        занятость слотов и не выполнять одно и то же действие дважды.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        self._activate_clock()
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        interaction_id = str(
            interaction.get("id") or kind
        )
        busy = self._busy_interaction(
            side, kind, interaction_id, target_id
        )
        if busy is not None:
            return {
                "ok": False,
                "reason": "это действие уже выполняется",
            }
        slots = self.slot_state(faction.side)
        if slots["free"] <= 0:
            return {
                "ok": False,
                "reason": "заняты все слоты (%d)" % slots["slots"],
                "slots": slots,
            }
        cost = {
            str(key): _number(value)
            for key, value in _as_mapping(
                interaction.get("cost")
            ).items()
        }
        for key, value in cost.items():
            faction.add_asset(key, -value)
        seconds = self._interaction_duration(kind, interaction)
        self._process_seq += 1
        record = {
            "id": "process-%d" % self._process_seq,
            "seq": int(self._process_seq),
            "kind": str(kind),
            "phase": "interaction",
            "side": faction.side,
            "action_id": interaction_id,
            "interaction_id": interaction_id,
            "label": str(label or interaction.get("label") or kind),
            "description": str(
                description or interaction.get("description") or ""
            ),
            "target_side": str(kind),
            "target_id": str(target_id or ""),
            "target_name": str(target_name or ""),
            "turn": int(self.turn),
            "started": round(float(self.elapsed), 6),
            "finish_at": round(float(self.elapsed) + float(seconds), 6),
            "duration": round(float(seconds), 6),
            "remaining": round(float(seconds), 6),
            "cost": cost,
            "interaction": copy.deepcopy(dict(interaction)),
            "status": "active",
        }
        decision = self._record_narrative(
            "decision",
            actor=faction.name,
            actor_side=faction.side,
            target=record["target_name"],
            target_side=faction.side,
            action_id=interaction_id,
            label=record["label"],
        )
        record["narrative_id"] = str(decision.get("id") or "")
        self.processes.append(record)
        self._log_process(record, "начата")
        result = {
            "ok": True,
            "started": True,
            "side": faction.side,
            "kind": str(kind),
            "turn": self.turn,
            "interaction_id": interaction_id,
            "label": record["label"],
            "description": record["description"],
            "target_id": record["target_id"],
            "target_name": record["target_name"],
            "duration": record["duration"],
            "cost": dict(cost),
            "process": dict(record),
            "slots": self.slot_state(faction.side),
            "actions_left": self.actions_left,
        }
        for key in (
            "organ_id",
            "character_id",
            "source_organ_id",
            "target_organ_id",
            "relation",
        ):
            if key in interaction:
                result[key] = interaction[key]
        return result

    def _apply_organ_interaction(
        self, faction, organ, interaction, label, description
    ):
        """Применить уже начатое влияние на орган (без списания цены)."""
        record = dict(interaction)
        record["organ_id"] = organ.id
        plan = build_interaction_work(
            record,
            "organ_interaction",
            faction,
            faction,
            self,
        )
        if plan is None:
            return {
                "ok": False,
                "reason": "работа взаимодействия не собрана",
            }
        try:
            report = receive(
                plan.to_work(),
                plan,
                faction,
                faction,
                self,
                success=True,
            )
        except Exception as exc:
            logger.warning(
                "Обработчик organ_interaction не сработал: %s", exc
            )
            return {
                "ok": False,
                "reason": "обработчик взаимодействия: %s" % exc,
            }
        cost = _as_mapping(interaction.get("cost"))
        before = organ.integrity
        support_before = organ.support
        applied = apply_report(
            faction,
            faction,
            report,
            scale=1.0,
            source="organ_interaction",
        )
        delta = organ.integrity - before
        # Вложение оставляет постоянную опору: иначе суточный тик тянул
        # целостность обратно к старой цели, и игрок не видел эффекта
        # снабжения или усиления.
        support_delta = _number(interaction.get("support"), 0.0)
        if support_delta:
            organ.support = _clamp(
                organ.support + support_delta, 0.0, 0.5
            )
        spread = spread_organ_effect(
            faction, organ, delta, self.model
        )
        organ.used_turn = self.turn
        result = {
            "ok": True,
            "turn": self.turn,
            "actions_left": self.actions_left,
            "side": faction.side,
            "organ_id": organ.id,
            "organ_name": organ.name,
            "organ_kind": organ.kind,
            "interaction_id": str(interaction.get("id")),
            "label": str(label or interaction.get("label") or ""),
            "description": str(
                description or interaction.get("description") or ""
            ),
            "integrity_before": round(before, 6),
            "integrity_after": round(organ.integrity, 6),
            "integrity_delta": round(delta, 6),
            "support_before": round(support_before, 6),
            "support_after": round(organ.support, 6),
            "support_delta": round(
                organ.support - support_before, 6
            ),
            "faction_spread": round(spread, 6),
            "cost": {
                str(key): round(_number(value), 6)
                for key, value in cost.items()
            },
            "text": str(
                interaction.get("text")
                or description
                or interaction.get("description")
                or ""
            ),
            "status": organ.status(),
        }
        if report is not None:
            result["report"] = report.as_dict()
        detail = (
            "ход %d: %s → орган «%s»: %s; целостность %.2f → %.2f"
            % (
                self.turn,
                faction.name,
                organ.name,
                result["label"],
                before,
                organ.integrity,
            )
        )
        self.events.append(
            {
                "turn": self.turn,
                "kind": "organ",
                "text": detail,
                "side": faction.side,
                "organ_id": organ.id,
                "actor": faction.name,
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]
        self._record_narrative(
            "organ",
            actor=faction.name,
            actor_side=faction.side,
            target=organ.name,
            target_side=faction.side,
            action_id=result["interaction_id"],
            label=result["label"],
            success=True,
            assets=applied.get("assets") or (),
            integrity_delta=round(delta, 6),
            organ_id=organ.id,
        )
        self.last_organ_result = result
        return result

    def perform_organ_interaction(
        self, side, organ_id, interaction_id, *, defer=True
    ):
        """Повлиять на орган: усилить, реформировать, почистить, снабдить.

        По умолчанию влияние занимает свободный слот и применяется,
        когда процесс завершится. ``defer=False`` оставлен для
        синхронных legacy-вызовов (``advance(organ_action=...)``).
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        if not defer:
            gate = self._player_action_gate(side)
            if gate:
                return {"ok": False, "reason": gate}
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        organ = faction.organ(organ_id)
        if organ is None:
            return {"ok": False, "reason": "орган не найден"}
        option = next(
            (
                item
                for item in self.organ_interaction_options(
                    side, organ_id
                )
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return {"ok": False, "reason": "взаимодействие не найдено"}
        if not option.get("enabled"):
            return {
                "ok": False,
                "reason": option.get("reason") or "взаимодействие недоступно",
            }
        interaction = copy.deepcopy(dict(option["interaction"]))
        interaction["organ_id"] = organ.id
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if defer:
            result = self._start_interaction_process(
                side,
                "organ",
                interaction,
                label=option["label"],
                description=option["description"],
                target_id=organ.id,
                target_name=organ.name,
            )
            if result.get("ok") and cooldown > 0:
                organ.interaction_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            if result.get("ok"):
                organ.used_turn = self.turn
            return result
        for key, value in _as_mapping(interaction.get("cost")).items():
            faction.add_asset(key, -_number(value))
        result = self._apply_organ_interaction(
            faction,
            organ,
            interaction,
            option["label"],
            option["description"],
        )
        if result.get("ok"):
            if cooldown > 0:
                organ.interaction_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            self._spend_player_action(side)
            result["actions_left"] = self.actions_left
        return result

    def _automaton_targets(self, faction, source, relation):
        """Кандидаты в цели для команды автомата.

        ``relation`` задаётся данными: ``any`` — любой другой узел,
        ``linked``/``neighbor`` — соседи по сети, ``same_kind`` — узлы
        того же типа. Старые ``subordinate``/``superior``/``peer``
        читаются как сетевые связи, а не как вертикаль подчинения.
        """
        relation = str(relation or "any").lower()
        organs = list(faction.organs)
        links = organ_links(organs)
        if relation in ("linked", "neighbor", "adjacent", "subordinate",
                        "superior", "peer"):
            neighbors = set(links.get(source.id, ()))
            return [organ for organ in organs if organ.id in neighbors]
        if relation in ("same_kind", "kind"):
            return [
                organ
                for organ in organs
                if organ.id != source.id
                and str(organ.kind) == str(source.kind)
            ]
        return [organ for organ in organs if organ.id != source.id]

    def automaton_interaction_options(self, side, organ_id):
        """Команды выбранного автомата другим автоматам своей фракции."""
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        source = faction.organ(organ_id)
        if source is None:
            return []
        assets = derived_assets(faction)
        options = []
        for interaction in faction.automaton_interactions:
            cost = _as_mapping(interaction.get("cost"))
            affordable = all(
                assets.get(str(key), 0.0) + 1e-9
                >= _number(value, 0.0)
                for key, value in cost.items()
            )
            relation = str(interaction.get("relation") or "any").lower()
            targets = self._automaton_targets(faction, source, relation)
            left = source.cooldown_left(interaction, self.turn)
            if not targets:
                if relation in (
                    "linked",
                    "neighbor",
                    "adjacent",
                    "subordinate",
                    "superior",
                    "peer",
                ):
                    reason = "нет связанных автоматов"
                elif relation in ("same_kind", "kind"):
                    reason = "нет автоматов того же типа"
                else:
                    reason = "нет других автоматов"
            elif not affordable:
                reason = "не хватает состояния"
            elif left > 0:
                reason = "перезарядка ещё %d" % left
            else:
                reason = ""
            options.append(
                {
                    "interaction": interaction,
                    "id": str(interaction.get("id")),
                    "label": str(
                        interaction.get("label")
                        or interaction.get("id")
                    ),
                    "description": str(
                        interaction.get("description") or ""
                    ),
                    "relation": relation,
                    "cost": {
                        str(key): round(_number(value), 6)
                        for key, value in cost.items()
                    },
                    "source_integrity": round(
                        _number(interaction.get("source_integrity")), 6
                    ),
                    "target_integrity": round(
                        _number(interaction.get("target_integrity")), 6
                    ),
                    "targets": [
                        {
                            "id": target.id,
                            "name": target.name,
                            "integrity": round(target.integrity, 6),
                            "status": target.status(),
                        }
                        for target in targets
                    ],
                    "enabled": bool(targets and affordable and left <= 0),
                    "reason": reason,
                }
            )
        return options

    def _apply_automaton_interaction(
        self,
        faction,
        source,
        target,
        interaction,
        label,
        description,
    ):
        """Применить уже начатую команду автомата (без списания цены)."""
        record = dict(interaction)
        record["source_organ_id"] = source.id
        record["target_organ_id"] = target.id
        plan = build_interaction_work(
            record,
            "automaton_interaction",
            faction,
            faction,
            self,
        )
        if plan is None:
            return {
                "ok": False,
                "reason": "работа взаимодействия не собрана",
            }
        try:
            report = receive(
                plan.to_work(),
                plan,
                faction,
                faction,
                self,
                success=True,
            )
        except Exception as exc:
            logger.warning(
                "Обработчик automaton_interaction не сработал: %s", exc
            )
            return {
                "ok": False,
                "reason": "обработчик взаимодействия: %s" % exc,
            }
        cost = _as_mapping(interaction.get("cost"))
        source_before = source.integrity
        target_before = target.integrity
        applied = apply_report(
            faction,
            faction,
            report,
            scale=1.0,
            source="automaton_interaction",
        )
        source_delta = source.integrity - source_before
        target_delta = target.integrity - target_before
        source_spread = spread_organ_effect(
            faction, source, source_delta, self.model
        )
        target_spread = spread_organ_effect(
            faction, target, target_delta, self.model
        )
        source.used_turn = self.turn
        target.used_turn = self.turn
        result = {
            "ok": True,
            "turn": self.turn,
            "actions_left": self.actions_left,
            "side": faction.side,
            "source_organ_id": source.id,
            "source_organ_name": source.name,
            "target_organ_id": target.id,
            "target_organ_name": target.name,
            "interaction_id": str(interaction.get("id")),
            "label": str(label or interaction.get("label") or ""),
            "description": str(
                description or interaction.get("description") or ""
            ),
            "relation": str(interaction.get("relation") or "any"),
            "source_integrity_before": round(source_before, 6),
            "source_integrity_after": round(source.integrity, 6),
            "source_integrity_delta": round(source_delta, 6),
            "target_integrity_before": round(target_before, 6),
            "target_integrity_after": round(target.integrity, 6),
            "target_integrity_delta": round(target_delta, 6),
            "faction_spread": round(source_spread + target_spread, 6),
            "cost": {
                str(key): round(_number(value), 6)
                for key, value in cost.items()
            },
            "text": str(
                interaction.get("text")
                or description
                or interaction.get("description")
                or ""
            ),
            "status": target.status(),
        }
        if report is not None:
            result["report"] = report.as_dict()
        detail = (
            "ход %d: %s → %s → %s: %s; цель %.2f → %.2f"
            % (
                self.turn,
                faction.name,
                source.name,
                target.name,
                result["label"],
                target_before,
                target.integrity,
            )
        )
        self.events.append(
            {
                "turn": self.turn,
                "kind": "automaton",
                "text": detail,
                "side": faction.side,
                "organ_id": source.id,
                "target_organ_id": target.id,
                "actor": source.name,
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]
        self._record_narrative(
            "automaton",
            actor=faction.name,
            actor_side=faction.side,
            target=target.name,
            target_side=faction.side,
            action_id=result["interaction_id"],
            label=result["label"],
            success=True,
            assets=applied.get("assets") or (),
            integrity_delta=round(target_delta, 6),
            organ_id=target.id,
        )
        self.last_automaton_result = result
        return result

    def perform_automaton_interaction(
        self,
        side,
        source_organ_id,
        target_organ_id,
        interaction_id,
        *,
        defer=True,
    ):
        """Провести команду одного автомата другому внутри своей сети.

        По умолчанию команда занимает слот и применяется по завершении
        процесса. ``defer=False`` — синхронный legacy-путь.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        if not defer:
            gate = self._player_action_gate(side)
            if gate:
                return {"ok": False, "reason": gate}
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        source = faction.organ(source_organ_id)
        if source is None:
            return {"ok": False, "reason": "автомат-источник не найден"}
        target = faction.organ(target_organ_id)
        if target is None:
            return {"ok": False, "reason": "автомат-цель не найден"}
        option = next(
            (
                item
                for item in self.automaton_interaction_options(
                    side, source_organ_id
                )
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return {"ok": False, "reason": "команда не найдена"}
        if not option.get("enabled"):
            return {
                "ok": False,
                "reason": option.get("reason") or "команда недоступна",
            }
        if target.id not in {
            item["id"] for item in option.get("targets", ())
        }:
            return {
                "ok": False,
                "reason": "цель не подходит для этой команды",
            }
        interaction = copy.deepcopy(dict(option["interaction"]))
        interaction["source_organ_id"] = source.id
        interaction["target_organ_id"] = target.id
        interaction["relation"] = option.get("relation", "any")
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if defer:
            result = self._start_interaction_process(
                side,
                "automaton",
                interaction,
                label=option["label"],
                description=option["description"],
                target_id=target.id,
                target_name=target.name,
            )
            if result.get("ok") and cooldown > 0:
                source.interaction_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            if result.get("ok"):
                source.used_turn = self.turn
                target.used_turn = self.turn
            return result
        for key, value in _as_mapping(interaction.get("cost")).items():
            faction.add_asset(key, -_number(value))
        result = self._apply_automaton_interaction(
            faction,
            source,
            target,
            interaction,
            option["label"],
            option["description"],
        )
        if result.get("ok"):
            if cooldown > 0:
                source.interaction_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            self._spend_player_action(side)
            result["actions_left"] = self.actions_left
        return result

    def character(self, side, character_id):
        faction = self.faction(side)
        if faction is None:
            return None
        return faction.character(character_id)

    def character_options(self, side):
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        return faction.character_options()

    def _character_cooldown_left(self, character, interaction):
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if cooldown <= 0:
            return 0
        last = _as_mapping(
            getattr(character, "campaign_cooldowns", {})
        ).get(str(interaction.get("id")))
        if last is None:
            return 0
        return max(
            0,
            cooldown + 1 - (int(self.turn) - int(last)),
        )

    def character_interaction_options(self, side, character_id):
        """Взаимодействия с конкретным персонажем."""
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        character = faction.character(character_id)
        if character is None:
            return []
        is_self = bool(getattr(character, "campaign_is_player", False))
        assets = derived_assets(faction)
        options = []
        for interaction in faction.character_interactions:
            cost = _as_mapping(interaction.get("cost"))
            affordable = all(
                assets.get(str(key), 0.0) + 1e-9
                >= _number(value, 0.0)
                for key, value in cost.items()
            )
            left = self._character_cooldown_left(character, interaction)
            self_blocked = bool(
                is_self and not interaction.get("allow_self", False)
            )
            if self_blocked:
                reason = "нельзя применять к самому себе"
            elif not affordable:
                reason = "не хватает состояния"
            elif left > 0:
                reason = "перезарядка ещё %d" % left
            else:
                reason = ""
            options.append(
                {
                    "interaction": interaction,
                    "id": str(interaction.get("id")),
                    "label": str(
                        interaction.get("label")
                        or interaction.get("id")
                    ),
                    "description": str(
                        interaction.get("description") or ""
                    ),
                    "cost": {
                        str(key): round(_number(value), 6)
                        for key, value in cost.items()
                    },
                    "morale": round(_number(interaction.get("morale")), 6),
                    "needs": {
                        str(key): round(_number(value), 6)
                        for key, value in _as_mapping(
                            interaction.get("needs")
                        ).items()
                    },
                    "personality": {
                        str(key): round(_number(value), 6)
                        for key, value in _as_mapping(
                            interaction.get("personality")
                        ).items()
                    },
                    "target_is_self": is_self,
                    "allow_self": bool(
                        interaction.get("allow_self", False)
                    ),
                    "enabled": bool(
                        affordable and left <= 0 and not self_blocked
                    ),
                    "reason": reason,
                }
            )
        return options

    def _apply_interaction_relations(
        self, faction, character, interaction
    ):
        """Записать отношения взаимодействия «фракция ↔ персонаж».

        Блок ``relations`` у взаимодействия может быть простым словарём
        осей или объектом ``{"source": "character", "axes": {...}}``.
        По умолчанию источник — фракция, потому что эффект применяет она.
        """
        raw = _as_mapping(interaction.get("relations"))
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

    def _apply_character_interaction(
        self, faction, character, interaction, label, description
    ):
        """Применить уже начатое действие персонала (без списания цены)."""
        if character is None or bool(
            getattr(character, "is_dead", False)
        ) or bool(getattr(character, "dead", False)):
            return {"ok": False, "reason": "персонаж недоступен"}
        organ = faction.organ(
            getattr(character, "campaign_organ_id", "")
        )
        record = dict(interaction)
        record["character_id"] = str(
            getattr(character, "campaign_id", "")
        )
        record["organ_id"] = organ.id if organ is not None else ""
        plan = build_interaction_work(
            record,
            "character_interaction",
            faction,
            faction,
            self,
        )
        if plan is None:
            return {
                "ok": False,
                "reason": "работа взаимодействия не собрана",
            }
        try:
            report = receive(
                plan.to_work(),
                plan,
                faction,
                faction,
                self,
                success=True,
            )
        except Exception as exc:
            logger.warning(
                "Обработчик character_interaction не сработал: %s", exc
            )
            return {
                "ok": False,
                "reason": "обработчик взаимодействия: %s" % exc,
            }
        cost = _as_mapping(interaction.get("cost"))
        needs_snapshot = {
            str(key): _clamp(value)
            for key, value in character.needs.items()
        }
        morale_before = _number(character.morale)
        organ_before = organ.integrity if organ is not None else None
        applied = apply_report(
            faction,
            faction,
            report,
            scale=1.0,
            source="character_interaction",
        )
        relation_changes = self._apply_interaction_relations(
            faction, character, interaction
        )
        needs_before = {}
        for key, before_value in needs_snapshot.items():
            after_value = _clamp(character.needs.get(key, 0.0))
            if abs(after_value - before_value) > 1e-9:
                needs_before[key] = before_value
        organ_delta = 0.0
        if organ is not None and organ_before is not None:
            organ_delta = organ.integrity - organ_before
            spread_organ_effect(
                faction, organ, organ_delta, self.model
            )
        result = {
            "ok": True,
            "turn": self.turn,
            "actions_left": self.actions_left,
            "side": faction.side,
            "character_id": str(
                getattr(character, "campaign_id", "")
            ),
            "character_name": str(getattr(character, "name", "")),
            "post": str(getattr(character, "campaign_post", "") or ""),
            "interaction_id": str(interaction.get("id")),
            "label": str(label or interaction.get("label") or ""),
            "description": str(
                description or interaction.get("description") or ""
            ),
            "cost": {
                str(key): round(_number(value), 6)
                for key, value in cost.items()
            },
            "needs_before": {
                key: round(value, 6) for key, value in needs_before.items()
            },
            "needs_after": {
                key: round(_clamp(character.needs.get(key, 0.0)), 6)
                for key in needs_before
            },
            "morale_before": round(morale_before, 6),
            "morale_after": round(_number(character.morale), 6),
            "organ_id": organ.id if organ is not None else "",
            "organ_integrity_before": (
                round(organ_before, 6) if organ_before is not None else None
            ),
            "organ_integrity_after": (
                round(organ.integrity, 6) if organ is not None else None
            ),
            "organ_integrity_delta": round(organ_delta, 6),
            "relations": relation_changes,
            "text": str(
                interaction.get("text")
                or description
                or interaction.get("description")
                or ""
            ),
        }
        if report is not None:
            result["report"] = report.as_dict()
        detail = (
            "ход %d: %s → персонаж «%s» (%s): %s; мораль %.0f → %.0f"
            % (
                self.turn,
                faction.name,
                result["character_name"],
                result["post"] or "без должности",
                result["label"],
                morale_before,
                character.morale,
            )
        )
        self.events.append(
            {
                "turn": self.turn,
                "kind": "character",
                "text": detail,
                "side": faction.side,
                "character_id": result["character_id"],
                "actor": faction.name,
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]
        self._record_narrative(
            "character",
            actor=faction.name,
            actor_side=faction.side,
            target=result["character_name"],
            target_side=faction.side,
            action_id=result["interaction_id"],
            label=result["label"],
            success=True,
            assets=applied.get("assets") or (),
            integrity_delta=round(organ_delta, 6),
            morale_before=morale_before,
            morale_after=_number(character.morale),
            character_id=result["character_id"],
            organ_id=organ.id if organ is not None else "",
        )
        self.last_character_result = result
        return result

    def perform_character_interaction(
        self, side, character_id, interaction_id, *, defer=True
    ):
        """Применить действие к выбранному персонажу.

        По умолчанию действие занимает слот и применяется по завершении
        процесса. ``defer=False`` — синхронный legacy-путь.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        if not defer:
            gate = self._player_action_gate(side)
            if gate:
                return {"ok": False, "reason": gate}
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        character = faction.character(character_id)
        if character is None:
            return {"ok": False, "reason": "персонаж не найден"}
        option = next(
            (
                item
                for item in self.character_interaction_options(
                    side, character_id
                )
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return {"ok": False, "reason": "взаимодействие не найдено"}
        if not option.get("enabled"):
            return {
                "ok": False,
                "reason": option.get("reason")
                or "взаимодействие недоступно",
            }
        interaction = copy.deepcopy(dict(option["interaction"]))
        interaction["character_id"] = str(
            getattr(character, "campaign_id", character_id)
        )
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if defer:
            result = self._start_interaction_process(
                side,
                "character",
                interaction,
                label=option["label"],
                description=option["description"],
                target_id=interaction["character_id"],
                target_name=str(getattr(character, "name", "")),
            )
            if result.get("ok") and cooldown > 0:
                character.campaign_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            return result
        for key, value in _as_mapping(interaction.get("cost")).items():
            faction.add_asset(key, -_number(value))
        result = self._apply_character_interaction(
            faction,
            character,
            interaction,
            option["label"],
            option["description"],
        )
        if result.get("ok"):
            if cooldown > 0:
                character.campaign_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            self._spend_player_action(side)
            result["actions_left"] = self.actions_left
        return result

    def _target_side(self, side, action, target=None):
        faction = self.faction(side)
        if faction is None:
            return None
        requested = str(target or action.get("target") or "rival")
        if requested in ("self", faction.id, faction.side):
            return faction.side
        if requested == "rival":
            return self.rival_of(side)
        if requested in ("any", "all", "all_rivals", "other"):
            others = self.other_sides(side)
            return others[0] if others else None
        if requested == "strongest":
            others = [self.faction(item) for item in self.other_sides(side)]
            others = [item for item in others if item is not None]
            if not others:
                return None
            return max(
                others, key=lambda item: (item.score(), item.side)
            ).side
        if requested == "weakest":
            others = [self.faction(item) for item in self.other_sides(side)]
            others = [item for item in others if item is not None]
            if not others:
                return None
            return min(
                others, key=lambda item: (item.score(), item.side)
            ).side
        if requested in self.factions:
            return requested
        for item in self.factions.values():
            if requested in (item.id, item.record.get("name")):
                return item.side
        return self.rival_of(side)

    def _log_work(self, result):
        self.log.append(result)
        trace = result.get("trace")
        if not isinstance(trace, Mapping):
            trace = {}
        detail = (
            "ход %d: %s → %s работой «%s» (%s); amount=%.3f "
            "eff=%.3f stored=%.3f loss=%.3f entropy=%.3f; "
            "шанс %.3f, бросок %.3f, успех=%s"
            % (
                result["turn"],
                result["actor_name"],
                result["target_name"],
                result["label"],
                result["form"],
                _number(trace.get("amount"), 0.0),
                _number(trace.get("efficiency"), 0.0),
                _number(trace.get("stored"), 0.0),
                _number(trace.get("loss"), 0.0),
                _number(trace.get("entropy"), 0.0),
                result["chance"],
                result["roll"],
                "да" if result["success"] else "нет",
            )
        )
        if trace.get("essence"):
            detail += "; суть=%s" % trace["essence"]
        if result.get("reason"):
            detail += "; причина: %s" % result["reason"]
        logger.debug("%s", detail)
        self.events.append(
            {
                "turn": result["turn"],
                "kind": "work",
                "text": detail,
                "side": result["actor_side"],
                "actor": result["actor_name"],
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]

    def _action_intention(self, action, actor, target_faction):
        """Собрать дуплет намерения из подсказок capability.

        Авторская метка живёт в ``hints.intention_essence`` (fallback —
        ``hints.essence``), цель — в ``hints.intention_target``. Старый
        блок ``intention`` читается только как совместимый fallback.
        Пустой/алиасный target разрешается в фактическую цель работы,
        поэтому один и тот же шаблон работает для любой стороны.
        """
        action = _as_mapping(action)
        hints = _as_mapping(action.get("hints"))
        raw = _as_mapping(action.get("intention"))
        essence = str(
            hints.get("intention_essence")
            or hints.get("essence")
            or raw.get("essence")
            or action.get("essence")
            or ""
        ).strip()
        if not essence:
            return None
        target = str(
            hints.get("intention_target") or raw.get("target") or ""
        ).strip()
        if target == "self":
            target = actor.id
        elif target in (
            "",
            "target",
            "rival",
            "any",
            "all",
            "all_rivals",
            "other",
            "strongest",
            "weakest",
        ):
            target = (
                target_faction.id
                if target_faction is not None
                else actor.id
            )
        return {"target": target, "essence": essence}

    def perform(self, side, action_id, target=None):
        """Выполнить работу стороны.

        Работа строится из capability (``build_work``), проходит через
        ``handlers.receive`` и применяется как ``WorkReport.projections``
        через ``apply_report``. Провал — это ветка ``failure`` в правиле
        обработчика, а не отдельный словарь эффектов в capability.
        """
        actor = self.faction(side)
        if actor is None or actor.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        gate = self._player_action_gate(side)
        if gate:
            return {"ok": False, "reason": gate}
        action = actor.action(action_id)
        if action is None:
            return {"ok": False, "reason": "действие не найдено"}
        if action_id not in self.available_actions(side):
            option = next(
                (
                    item
                    for item in self.action_options(side)
                    if item["id"] == str(action_id)
                ),
                {},
            )
            return {
                "ok": False,
                "reason": option.get("reason") or "действие недоступно",
            }
        target_side = self._target_side(side, action, target=target)
        target_faction = self.faction(target_side)
        if target_faction is None:
            return {"ok": False, "reason": "нет цели"}
        return self._resolve_action(
            actor,
            action,
            action_id,
            target_side,
            target_faction,
            charge_cost=True,
            spend_budget=True,
        )

    def _resolve_action(
        self,
        actor,
        action,
        action_id,
        target_side,
        target_faction,
        charge_cost=True,
        spend_budget=False,
        effect_fraction=1.0,
        executor=None,
    ):
        """Рассчитать и применить работу без предварительных гейтов.

        Общая часть ``perform`` и завершения процесса: бросок, обработчик,
        эффекты, перезарядка и запись в журнал. Стоимость списывает
        вызывающий: ``perform`` — сразу, процесс — при запуске.

        ``effect_fraction`` позволяет применить только часть проекций.
        Процесс делает так первый импульс, а остаток разворачивает во
        времени через ``_advance_effects``. Legacy ``perform`` передаёт
        ``1.0`` и остаётся мгновенным.
        """
        side = actor.side
        stats_before = None
        if self.stats.enabled and self.stats.actions:
            stats_before = {
                "actor": self.stats.assets(actor),
                "target": self.stats.assets(target_faction),
            }
        cost = self._action_cost(actor, action)
        chance_spec = _as_mapping(action.get("chance"))
        attack_asset = str(
            chance_spec.get("attack")
            or action.get("attack_asset")
            or "influence"
        )
        defense_asset = str(
            chance_spec.get("defense")
            or action.get("defense_asset")
            or "cohesion"
        )
        attack_value = actor.asset(attack_asset)
        defense_value = (
            actor.asset(defense_asset)
            if target_faction.side == actor.side
            else target_faction.asset(defense_asset)
        )
        base = _number(
            chance_spec.get("base"),
            _number(action.get("base"), self.model["success_base"]),
        )
        slope = _number(
            chance_spec.get("slope"),
            _number(action.get("slope"), self.model["success_slope"]),
        )
        form = self._action_form(action)
        relation_shift = 0.0
        if (
            self.relations is not None
            and target_faction.id != actor.id
        ):
            relation_shift = self.relations.effect(
                target_faction.id, actor.id, form
            )
        chance = _sigmoid(
            base
            + slope * (attack_value - defense_value)
            + relation_shift
        )
        roll = self.rng.random()
        success = roll < chance
        organ_id = str(action.get("organ_id") or "")
        organ = actor.organ(organ_id) if organ_id else None
        readiness = readiness_scale(organ, self.model)
        used_before = int(actor.action_uses.get(str(action_id), 0))
        decay = _number(
            action.get(
                "repeat_effect_decay",
                self.model.get("repeat_effect_decay", 1.0),
            ),
            1.0,
        )
        decay = max(0.0, min(1.0, decay))
        repeat_scale = decay ** used_before if used_before > 0 else 1.0

        plan = build_work(action, actor, target_faction, self)
        if plan is None:
            return {
                "ok": False,
                "reason": "работа не собрана: нет template/amount",
            }
        try:
            report = receive(
                plan.to_work(),
                plan,
                actor,
                target_faction,
                self,
                success=success,
            )
        except Exception as exc:
            logger.warning("Обработчик работы не сработал: %s", exc)
            return {
                "ok": False,
                "reason": "обработчик работы: %s" % exc,
            }
        if charge_cost:
            for key, value in cost.items():
                actor.add_asset(key, -_number(value))
        fraction = max(0.0, min(1.0, _number(effect_fraction, 1.0)))
        executor_support = 0.0
        executor_competence = 0.0
        executor_factor = 1.0
        if executor is not None:
            agency = self._agency_model()
            effect_model = _as_mapping(agency.get("executor_effect"))
            executor_support = self._character_support(
                executor, action, actor
            )
            executor_competence = self._character_competence(executor)
            spec = 1.0 + _number(
                effect_model.get("support_weight"), 0.2
            ) * executor_support + _number(
                effect_model.get("competence_weight"), 0.15
            ) * (executor_competence - 0.5)
            executor_factor = max(
                _number(effect_model.get("min_factor"), 0.7),
                min(
                    _number(effect_model.get("max_factor"), 1.25),
                    spec,
                ),
            )
        effect_scale = (
            self.model["effect_scale"]
            * readiness
            * repeat_scale
            * executor_factor
        )
        course = actor.action_course(action)
        if course.get("aligned"):
            effect_scale *= 1.0 + max(
                0.0, _number(self.model.get("course_effect_bonus"))
            )
        applied = apply_report(
            actor,
            target_faction,
            report,
            scale=effect_scale * fraction,
            source="work",
        )
        intention = (
            self._action_intention(action, actor, target_faction)
            if success
            else None
        )
        trace_essence = str(
            (report.trace or {}).get("essence")
            or plan.essence_hint
            or ""
        )
        if intention is not None:
            if trace_essence:
                intention = dict(intention, essence=trace_essence)
            apply_effects(
                actor,
                {"self": {"intentions": {"push": [intention]}}},
                target=None,
                scale=1.0,
                source="work",
            )
        try:
            trace = trace_from_report(
                plan, chance, roll, success, report
            ).as_dict()
        except Exception:
            trace = None
        organ_before_integrity = (
            organ.integrity if organ is not None else None
        )
        if organ is not None:
            if success:
                gain = self.model["organ_action_gain"] * (
                    1.0 - organ.integrity
                )
                strengthen_organ(organ, gain)
            else:
                loss = self.model["organ_action_loss"] * organ.integrity
                strengthen_organ(organ, -loss)
            organ.used_turn = self.turn
        if success and target_faction.side != actor.side:
            damage_organs(
                target_faction,
                defense_asset,
                self.model["organ_damage"] * readiness,
                self.model,
            )
        cooldown = int(
            _number(
                action.get(
                    "cooldown", self.model.get("cooldown_turns")
                ),
                0,
            )
        )
        if cooldown > 0:
            actor.cooldowns[str(action_id)] = self.turn
        actor.action_uses[str(action_id)] = used_before + 1
        if spend_budget:
            self._spend_player_action(actor.side)
        result = {
            "ok": True,
            "turn": self.turn,
            "actions_left": self.actions_left,
            "actor_side": actor.side,
            "actor_id": actor.id,
            "actor_name": actor.name,
            "target_side": target_faction.side,
            "target_id": target_faction.id,
            "target_name": target_faction.name,
            "action_id": str(action_id),
            "label": str(action.get("label") or action_id),
            "uses": used_before + 1,
            "repeat_scale": round(repeat_scale, 6),
            "organ_id": str(action.get("organ_id") or ""),
            "organ": str(action.get("organ") or ""),
            "organ_integrity": round(
                organ.integrity if organ is not None else 1.0, 6
            ),
            "organ_status": (
                organ.status() if organ is not None else "нет органа"
            ),
            "organ_readiness": round(readiness, 6),
            "form": str(plan.form),
            "attack_asset": attack_asset,
            "attack_value": round(attack_value, 6),
            "defense_asset": defense_asset,
            "defense_value": round(defense_value, 6),
            "chance": round(chance, 6),
            "relation_shift": round(relation_shift, 6),
            "roll": round(roll, 6),
            "success": bool(success),
            "effect_scale": round(effect_scale, 6),
            "effect_fraction": round(fraction, 6),
            "course": dict(course),
            "executor_id": str(
                getattr(executor, "campaign_id", "") or ""
            ),
            "executor_name": str(
                getattr(executor, "name", "") or ""
            ),
            "executor_support": round(executor_support, 6),
            "executor_competence": round(executor_competence, 6),
            "executor_factor": round(executor_factor, 6),
            "intention": dict(intention or {}),
            "trace": trace,
            "cost": {
                key: round(_number(value), 6)
                for key, value in cost.items()
            },
            "self_after": {
                key: round(_clamp(value), 6)
                for key, value in actor.assets.items()
            },
            "target_after": {
                key: round(_clamp(value), 6)
                for key, value in target_faction.assets.items()
            },
            "text": str(action.get("text") or ""),
        }
        result["report"] = report.as_dict()
        integrity_delta = None
        if organ is not None and organ_before_integrity is not None:
            integrity_delta = organ.integrity - organ_before_integrity
        self._record_narrative(
            "action",
            actor=actor.name,
            actor_side=actor.side,
            target=target_faction.name,
            target_side=target_faction.side,
            action_id=str(action_id),
            label=result["label"],
            success=bool(success),
            essence=trace_essence,
            form=str(plan.form),
            assets=applied.get("assets") or (),
            integrity_delta=(
                round(integrity_delta, 6)
                if integrity_delta is not None
                else None
            ),
            organ_id=str(action.get("organ_id") or ""),
        )
        if stats_before is not None:
            assets_after = {
                "actor": self.stats.assets(actor),
                "target": self.stats.assets(target_faction),
            }
            applied_log = {
                key: value
                for key, value in applied.items()
                if key != "report"
            }
            self.stats.log(
                "work",
                side=actor.side,
                actor_id=actor.id,
                actor=actor.name,
                target_side=target_faction.side,
                target_id=target_faction.id,
                target=target_faction.name,
                action_id=str(action_id),
                label=str(action.get("label") or action_id),
                form=str(plan.form),
                chance_formula={
                    "base": round(base, 6),
                    "slope": round(slope, 6),
                    "attack_asset": attack_asset,
                    "attack_value": round(attack_value, 6),
                    "defense_asset": defense_asset,
                    "defense_value": round(defense_value, 6),
                    "difference": round(
                        attack_value - defense_value, 6
                    ),
                    "relation_shift": round(relation_shift, 6),
                    "logit": round(
                        base
                        + slope * (attack_value - defense_value)
                        + relation_shift,
                        6,
                    ),
                    "chance": round(chance, 6),
                    "roll": round(roll, 6),
                    "success": bool(success),
                },
                modifiers={
                    "readiness": round(readiness, 6),
                    "repeat_uses": used_before,
                    "repeat_decay": round(decay, 6),
                    "repeat_scale": round(repeat_scale, 6),
                    "effect_scale": round(effect_scale, 6),
                    "effect_fraction": round(fraction, 6),
                    "executor_support": round(executor_support, 6),
                    "executor_competence": round(
                        executor_competence, 6
                    ),
                    "executor_factor": round(executor_factor, 6),
                },
                cost=result["cost"],
                applied=applied_log,
                trace=trace,
                report=(
                    report.as_dict()
                    if self.stats.verbose_report
                    else None
                ),
                assets_before=stats_before,
                assets_after=assets_after,
                asset_deltas={
                    "actor": delta_map(
                        stats_before["actor"], assets_after["actor"]
                    ),
                    "target": delta_map(
                        stats_before["target"], assets_after["target"]
                    ),
                },
                organ={
                    "id": str(action.get("organ_id") or ""),
                    "integrity": round(
                        organ.integrity if organ is not None else 1.0,
                        6,
                    ),
                    "readiness": round(readiness, 6),
                    "status": (
                        organ.status() if organ is not None else "нет"
                    ),
                },
            )
        self._log_work(result)
        return result

    interact_organ = perform_organ_interaction

    interact_automaton = perform_automaton_interaction

    interact_character = perform_character_interaction
