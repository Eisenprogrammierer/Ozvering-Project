"""Взаимодействия automata-кампании: органы, автоматы, персонажи.

Вынесено из ``automata_actions.py`` после W4. Миксин использует те же
примитивы ядра, что и остальные действия, и подключается к
``AutomataActionsMixin`` без изменения публичного API.
"""

from __future__ import annotations

from .automata_support import (
    EVENT_LOG_LIMIT,
    _as_mapping,
    _clamp,
    _number,
    _text,
    apply_report,
    build_interaction_work,
    copy,
    derived_assets,
    logger,
    organ_links,
    receive,
    spread_organ_effect,
)


class AutomataInteractionsMixin:

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
