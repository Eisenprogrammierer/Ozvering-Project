"""Персонажи, агентность, цели и автономия."""

from __future__ import annotations

from .automata_support import (
    Mapping,
    _as_mapping,
    _clamp,
    _number,
    _same_id,
    _text,
    logger,
    math,
)


class AutomataCharactersMixin:

    def _agency_model(self):
        return _as_mapping(
            _as_mapping(self.ai_model).get("character_agency")
        )

    def _agency_enabled(self):
        return bool(self._agency_model().get("enabled", False))

    def _agency_state(self, character, faction=None):
        """Личная память персонажа: доверие, обида, инициатива.

        Состояние живёт на самом персонаже и попадает в снимок. Старые
        сейвы без блока получают нейтральные значения, поэтому загрузка
        не ломается.
        """
        raw = getattr(character, "campaign_agency", None)
        state = dict(raw) if isinstance(raw, Mapping) else {}
        state["trust"] = _clamp(_number(state.get("trust"), 0.5))
        state["grievance"] = _clamp(
            _number(state.get("grievance"), 0.0)
        )
        state["initiative"] = _clamp(
            _number(state.get("initiative"), 0.0)
        )
        state["assignments"] = max(
            0, int(_number(state.get("assignments"), 0))
        )
        state["orders"] = max(0, int(_number(state.get("orders"), 0)))
        state["last_order"] = _text(state.get("last_order"))
        memory = [
            dict(item)
            for item in (state.get("memory") or ())
            if isinstance(item, Mapping)
        ]
        state["memory"] = memory[-8:]
        return state

    def _goal_need(self, character):
        """Ведущая потребность персонажа для личной цели.

        Сначала читаются BDI-желания, затем сырые потребности. Сортировка
        по имени делает выбор детерминированным и не тратит
        ``character.rng``.
        """
        values = _as_mapping(getattr(character, "desires", {}))
        if not values:
            values = _as_mapping(getattr(character, "needs", {}))
        if not values:
            return ""
        need, _value = max(
            values.items(),
            key=lambda item: (_number(item[1]), str(item[0])),
        )
        return _text(need)

    def _goal_target(self, character, faction, kind):
        """Разрешить вид цели в конкретный объект мира.

        Виды целей приходят из данных: ``organ`` (свой орган или самый
        целый орган фракции), ``faction``, ``rival``, ``leader``, ``self``.
        Неизвестный вид безопасно сводится к личности самого персонажа.
        """
        kind = _text(kind, "self")
        if kind == "organ" and faction is not None:
            organ_id = _text(
                getattr(character, "campaign_organ_id", "")
            )
            organ = faction.organ(organ_id) if organ_id else None
            if organ is None and faction.organs:
                organ = max(
                    faction.organs,
                    key=lambda item: (
                        _number(getattr(item, "integrity", 0.0)),
                        str(getattr(item, "id", "")),
                    ),
                )
            if organ is not None:
                return str(organ.id), str(
                    getattr(organ, "name", organ.id)
                )
            return str(faction.id), str(faction.name)
        if kind == "faction" and faction is not None:
            return str(faction.id), str(faction.name)
        if kind == "rival":
            rival_side = _text(self.rival_side)
            if faction is not None and rival_side == faction.side:
                rival_side = next(
                    (
                        side
                        for side in self.factions
                        if side != faction.side
                    ),
                    "",
                )
            rival = self.faction(rival_side)
            if rival is not None:
                return str(rival.id), str(rival.name)
        if kind == "leader" and faction is not None and faction.characters:
            leader = faction.characters[0]
            if leader is not character:
                return (
                    str(getattr(leader, "campaign_id", "")),
                    str(getattr(leader, "name", "")),
                )
            return str(faction.id), str(faction.name)
        return (
            str(getattr(character, "campaign_id", "")),
            str(getattr(character, "name", "")),
        )

    def _character_goal(self, character, faction=None):
        """Личная цель персонажа из данных ``character_agency.goals``."""
        model = self._agency_model()
        goals = _as_mapping(model.get("goals"))
        by_need = _as_mapping(goals.get("by_need"))
        kinds = _as_mapping(goals.get("kinds"))
        default_kind = _text(goals.get("default_kind"), "duty")
        need = self._goal_need(character)
        kind = _text(by_need.get(need), default_kind)
        spec = _as_mapping(kinds.get(kind))
        if not spec:
            spec = _as_mapping(kinds.get(default_kind))
        if not spec:
            spec = {
                "label": kind,
                "essence": need or "seek_order",
                "target": "faction",
            }
        essence = _text(spec.get("essence"), need or "seek_order")
        target_kind = _text(spec.get("target"), "self")
        target, target_name = self._goal_target(
            character, faction, target_kind
        )
        return {
            "kind": kind,
            "label": _text(spec.get("label"), kind),
            "need": need,
            "essence": essence,
            "target_kind": target_kind,
            "target": target,
            "target_name": target_name,
            "started": int(self.turn),
            "revised": int(self.turn),
        }

    def _init_character_agency(self, faction):
        """Завести цели и память всем персонажам фракции.

        Вызывается после сборки фракций и после загрузки снимка. Уже
        существующие цель и память сохраняются: старый сейв остаётся
        источником истины.
        """
        if not self._agency_enabled() or faction is None:
            return
        for character in faction.characters:
            character.campaign_agency = self._agency_state(
                character, faction
            )
            goal = getattr(character, "campaign_goal", None)
            if (
                not isinstance(goal, Mapping)
                or not _text(goal.get("kind"))
            ):
                character.campaign_goal = self._character_goal(
                    character, faction
                )

    def _character_competence(self, character):
        """Компетентность исполнителя по чертам из данных."""
        model = self._agency_model()
        traits = [
            _text(item)
            for item in (model.get("competence_traits") or ())
            if _text(item)
        ]
        if not traits:
            return 0.5
        values = _as_mapping(
            getattr(getattr(character, "personality", None), "values", {})
        )
        total = sum(_clamp(values.get(trait, 0.0)) for trait in traits)
        return total / float(len(traits))

    def _character_support(self, character, action, faction=None):
        """Насколько персонаж поддерживает работу или саботирует её.

        Поддержка складывается из личной цели, BDI-намерения, потребности
        и совпадения адресата. Доверие и инициатива усиливают вклад,
        обида его гасит. При высокой обиде персонаж переходит к саботажу,
        и работа теряет вес.
        """
        model = self._agency_model()
        if not bool(model.get("enabled", False)) or character is None:
            return 0.0
        if bool(
            getattr(
                character,
                "is_dead",
                getattr(character, "dead", False),
            )
        ):
            return 0.0
        if faction is None:
            faction = self.faction(str(getattr(character, "side", "")))
        essences = self._action_essences(action)
        need = ""
        for essence in essences:
            need = self._action_need(essence, character)
            if need:
                break
        target = None
        if faction is not None:
            target = self.faction(
                self._target_side(faction.side, action)
            )
        target_id = _text(getattr(target, "id", ""))
        state = self._agency_state(character, faction)
        goal = _as_mapping(getattr(character, "campaign_goal", {}))
        goal_weight = _number(model.get("goal_weight"), 0.35)
        target_weight = _number(model.get("target_weight"), 0.2)
        intention_weight = _number(model.get("intention_weight"), 0.25)
        need_weight = _number(model.get("need_weight"), 0.2)
        trust_weight = _number(model.get("trust_weight"), 0.25)
        grievance_weight = _number(model.get("grievance_weight"), 0.45)
        initiative_weight = _number(
            model.get("initiative_weight"), 0.15
        )
        sabotage_weight = _number(model.get("sabotage_weight"), 0.35)
        sabotage_floor = _number(model.get("sabotage_floor"), 0.35)
        urgency_floor = _number(model.get("urgency_floor"), 0.25)

        support = 0.0
        if _text(goal.get("essence")) in essences:
            support += goal_weight
        if need and _text(goal.get("need")) == need:
            support += goal_weight * 0.5
        if (
            target_id
            and _text(goal.get("target"))
            and _same_id(goal.get("target"), target_id)
        ):
            support += target_weight
        bdi = getattr(character, "bdi", None)
        intention = (
            bdi.latest_intention()
            if bdi is not None
            and callable(getattr(bdi, "latest_intention", None))
            else None
        )
        desires = _as_mapping(getattr(character, "desires", {}))
        urgency = max(
            [_number(value) for value in desires.values()] or [0.0]
        )
        if (
            intention is not None
            and _text(getattr(intention, "essence", "")) in essences
            and urgency >= urgency_floor
        ):
            support += intention_weight * urgency
        if need:
            support += need_weight * _clamp(
                _as_mapping(getattr(character, "needs", {})).get(need)
            )
        trust = _clamp(state.get("trust", 0.5))
        initiative = _clamp(state.get("initiative", 0.0))
        grievance = _clamp(state.get("grievance", 0.0))
        support *= 1.0 + trust_weight * (trust - 0.5) * 2.0
        support *= 1.0 + initiative_weight * initiative
        support -= grievance_weight * grievance
        if grievance >= sabotage_floor:
            support -= sabotage_weight * grievance
        return support

    def _remember_assignment(self, character, record, success=None,
                             started=False):
        """Запомнить назначение на работу и его исход."""
        if character is None or not self._agency_enabled():
            return {}
        faction = self.faction(_text(record.get("side")))
        state = self._agency_state(character, faction)
        model = self._agency_model()
        if started:
            state["assignments"] = (
                max(0, int(state.get("assignments", 0))) + 1
            )
            state["initiative"] = _clamp(
                state.get("initiative", 0.0)
                + _number(model.get("initiative_gain"), 0.2) * 0.25
            )
        if success is True:
            state["trust"] = _clamp(
                state.get("trust", 0.5)
                + _number(model.get("order_trust"), 0.1) * 0.5
            )
            state["grievance"] = _clamp(
                state.get("grievance", 0.0) * 0.9
            )
        elif success is False:
            state["grievance"] = _clamp(
                state.get("grievance", 0.0)
                + _number(model.get("order_grievance"), 0.15) * 0.5
            )
        character.campaign_agency = state
        return dict(state)

    def _order_goal_harmony(self, order, goal):
        """Согласован ли приказ с личной целью адресата.

        Данные приказа могут прямо задать ``goal_alignment`` или списки
        ``goal_needs``/``goal_essences``. Иначе выводятся из эффектов:
        снижение целевой потребности поддерживает цель, повышение —
        вызывает обиду; совпадение сути намерения усиливает доверие.
        """
        goal = _as_mapping(goal)
        order = _as_mapping(order)
        if not goal:
            return 0.0
        harmony = 0.0
        effects = _as_mapping(order.get("effects"))
        need_delta = _as_mapping(effects.get("needs"))
        goal_need = _text(goal.get("need"))
        declared_needs = {
            _text(item) for item in (order.get("goal_needs") or ())
        }
        if goal_need and goal_need in declared_needs:
            harmony += 0.5
        if goal_need and goal_need in need_delta:
            delta = _number(need_delta.get(goal_need), 0.0)
            harmony += 0.55 if delta < 0.0 else -0.45
        order_essences = set()
        intentions = _as_mapping(effects.get("intentions"))
        for item in intentions.get("push") or ():
            if isinstance(item, Mapping):
                essence = _text(item.get("essence"))
                if essence:
                    order_essences.add(essence)
        for item in order.get("goal_essences") or ():
            essence = _text(item)
            if essence:
                order_essences.add(essence)
        goal_essence = _text(goal.get("essence"))
        if goal_essence and goal_essence in order_essences:
            harmony += 0.6
        elif order_essences:
            harmony -= 0.2
        alignment = _text(order.get("goal_alignment"))
        if alignment == "support":
            harmony += 0.5
        elif alignment == "conflict":
            harmony -= 0.5
        return max(-1.0, min(1.0, harmony))

    def _remember_order(self, character, order, faction=None):
        """Приказ оставляет след: доверие или обиду у адресата."""
        if character is None or not self._agency_enabled():
            return {}
        state = self._agency_state(character, faction)
        model = self._agency_model()
        goal = _as_mapping(getattr(character, "campaign_goal", {}))
        harmony = self._order_goal_harmony(order, goal)
        trust_delta = _number(model.get("order_trust"), 0.1) * (
            0.5 + 0.5 * harmony
        )
        grievance_delta = _number(
            model.get("order_grievance"), 0.15
        ) * (0.5 - 0.5 * harmony)
        state["trust"] = _clamp(
            _number(state.get("trust"), 0.5) + trust_delta
        )
        state["grievance"] = _clamp(
            _number(state.get("grievance"), 0.0) + grievance_delta
        )
        state["orders"] = max(0, int(state.get("orders", 0))) + 1
        state["last_order"] = _text(order.get("id"))
        memory = list(state.get("memory") or ())
        memory.append(
            {
                "turn": int(self.turn),
                "order_id": _text(order.get("id")),
                "harmony": round(harmony, 6),
                "trust": round(state["trust"], 6),
                "grievance": round(state["grievance"], 6),
            }
        )
        state["memory"] = memory[-8:]
        character.campaign_agency = state
        return {
            "trust": round(state["trust"], 6),
            "grievance": round(state["grievance"], 6),
            "harmony": round(harmony, 6),
            "goal": str(goal.get("label") or ""),
        }

    def _choose_executor(self, side, action):
        """Выбрать исполнителя работы по цели, компетентности и органу.

        Персонаж игрока не назначается автоматически: им управляет
        игрок. Лидер фракции может быть исполнителем, если лучше всех
        подходит по цели. При равенстве выигрывает стабильный порядок
        персонажей, поэтому выбор детерминирован.
        """
        if not self._agency_enabled():
            return None
        faction = self.faction(side)
        if faction is None:
            return None
        model = self._agency_model()
        competence_weight = _number(
            model.get("competence_weight"), 0.2
        )
        organ_bonus = _number(model.get("executor_organ_bonus"), 0.25)
        organ_id = _text(action.get("organ_id"))
        best = None
        best_score = -math.inf
        for character in faction.characters:
            if bool(
                getattr(
                    character,
                    "is_dead",
                    getattr(character, "dead", False),
                )
            ):
                continue
            if bool(getattr(character, "campaign_is_player", False)):
                continue
            support = self._character_support(
                character, action, faction
            )
            competence = self._character_competence(character)
            score = 1.0 + support + competence_weight * (
                competence - 0.5
            )
            if (
                organ_id
                and _same_id(
                    getattr(character, "campaign_organ_id", ""),
                    organ_id,
                )
            ):
                score += organ_bonus
            if score > best_score + 1e-9:
                best = character
                best_score = score
        return best

    def _tick_character_autonomy(self, faction, seconds=None):
        """Пересмотреть личные цели и выбрать BDI-намерение.

        Цель живёт ``goal_hold_turns`` ходов и не меняется каждый такт:
        иначе персонаж дёргается между потребностями. Память приказов
        затухает, инициатива возвращается к норме. Персонаж игрока
        сохраняет цель для отображения, но не выбирает намерение сам.
        """
        if not self._agency_enabled() or faction is None:
            return
        model = self._agency_model()
        decay = _clamp(_number(model.get("memory_decay"), 0.92))
        hold = max(
            1, int(_number(model.get("goal_hold_turns"), 3))
        )
        every = max(
            1, int(_number(model.get("deliberate_every"), 1))
        )
        for character in faction.characters:
            if bool(
                getattr(
                    character,
                    "is_dead",
                    getattr(character, "dead", False),
                )
            ):
                continue
            state = self._agency_state(character, faction)
            state["trust"] = 0.5 + (
                _number(state.get("trust"), 0.5) - 0.5
            ) * decay
            state["grievance"] = _clamp(
                _number(state.get("grievance"), 0.0) * decay
            )
            state["initiative"] = _clamp(
                _number(state.get("initiative"), 0.0) * decay
            )
            character.campaign_agency = state
            goal = _as_mapping(getattr(character, "campaign_goal", {}))
            started = int(_number(goal.get("started"), -10 ** 9))
            if not goal or int(self.turn) - started >= hold:
                goal = self._character_goal(character, faction)
                goal["started"] = int(self.turn)
                goal["revised"] = int(self.turn)
                character.campaign_goal = goal
            if bool(getattr(character, "campaign_is_player", False)):
                continue
            if every and int(self.turn) % every:
                continue
            try:
                character.deliberate(
                    target=_text(goal.get("target")) or None,
                    preferred=_text(goal.get("essence")) or None,
                )
            except Exception:
                logger.exception(
                    "Намерение персонажа %s не выбрано",
                    getattr(character, "name", "?"),
                )
