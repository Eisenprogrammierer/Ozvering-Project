"""Отношения, обязательства, ценности, коалиции и директивы."""

from __future__ import annotations

from .world_support import (
    CampaignError,
    DEFAULT_OBLIGATION_KIND,
    DEFAULT_OVERDUE_OBLIGATION,
    Mapping,
    OBLIGATION_FULFILL_AFFINITY,
    OBLIGATION_FULFILL_TRUST,
    RELATION_BACK_SHARE,
    _as_float,
    _as_int,
    _clamp,
    _text,
    _values,
    coalition_config,
    pair_score,
)


class WorldRelationsMixin:

    def relation(self, source_id, target_id):
        source = self.node(source_id) or {}
        return _as_float((source.get("relations") or {}).get(target_id), 0.0)

    def relation_axes(self, source_id, target_id):
        """Направленные оси R_ij: легаси + оси из конфига мира.

        Легаси-шкала `relations` — проекция `affinity`. Оси создаются
        лениво из текущей скалярной проекции, поэтому старые сейвы и
        конфиги без блока отношений получают осмысленные значения.
        """
        source = self.node(source_id)
        if source is None:
            return {axis: 0.0 for axis in self.relation_axis_ids}
        target_id = _text(target_id)
        store = source.setdefault("relation_axes", {})
        axes = store.get(target_id)
        if axes is None:
            axes = {axis: 0.0 for axis in self.relation_axis_ids}
            axes["affinity"] = self.relation(source_id, target_id)
            store[target_id] = axes
        return {
            axis: _clamp(
                _as_float(axes.get(axis), 0.0), -1.0, 1.0
            )
            for axis in self.relation_axis_ids
        }

    def set_relation_axes(self, source_id, target_id, values):
        """Записать оси одного направления и обновить проекцию `affinity`."""
        source = self.node(source_id)
        target = self.node(target_id)
        if source is None or target is None:
            return self.relation_axes(source_id, target_id)
        axes = self.relation_axes(source_id, target_id)
        for axis in self.relation_axis_ids:
            if axis in values:
                axes[axis] = _clamp(
                    _as_float(values.get(axis), axes[axis]), -1.0, 1.0
                )
        source.setdefault("relation_axes", {})[target["id"]] = axes
        source.setdefault("relations", {})[target["id"]] = axes["affinity"]
        return axes

    def _shift_relation(
        self,
        source,
        target,
        affinity=0.0,
        affinity_back=None,
        axes=None,
        axes_back=None,
    ):
        """Сдвинуть отношения в двух направлениях независимо.

        По умолчанию обратное направление получает половину эффекта
        (`RELATION_BACK_SHARE`): действие игрока сильнее меняет его
        отношение к цели, чем отношение цели к игроку. Явные
        `relation_back`/`relation_axes_back` в контенте переопределяют
        это правило.
        """
        if source is None or target is None:
            return 0.0
        if affinity_back is None:
            affinity_back = float(affinity) * RELATION_BACK_SHARE
        forward = dict(axes or {})
        if abs(float(affinity)) > 1e-12:
            forward["affinity"] = forward.get("affinity", 0.0) + float(
                affinity
            )
        backward = dict(axes_back or {})
        if abs(float(affinity_back)) > 1e-12:
            backward["affinity"] = backward.get(
                "affinity", 0.0
            ) + float(affinity_back)
        changed = 0.0
        if forward:
            before = self.relation(source["id"], target["id"])
            current = self.relation_axes(source["id"], target["id"])
            payload = {
                axis: current[axis] + _as_float(forward.get(axis), 0.0)
                for axis in forward
            }
            after = self.set_relation_axes(
                source["id"], target["id"], payload
            )
            changed += abs(after["affinity"] - before)
        if backward:
            before = self.relation(target["id"], source["id"])
            current = self.relation_axes(target["id"], source["id"])
            payload = {
                axis: current[axis] + _as_float(backward.get(axis), 0.0)
                for axis in backward
            }
            after = self.set_relation_axes(
                target["id"], source["id"], payload
            )
            changed += abs(after["affinity"] - before)
        return changed

    def add_obligation(
        self,
        creditor,
        debtor,
        kind=DEFAULT_OBLIGATION_KIND,
        amount=1.0,
        *,
        due_day=None,
        note="",
    ):
        """Создать обязательство: `debtor` должен `creditor`."""
        obligation = self.obligations.add(
            creditor,
            debtor,
            kind,
            amount,
            created_day=self.day,
            due_day=due_day,
            note=note,
        )
        self.log.append(
            {
                "day": self.day,
                "kind": "obligation",
                "text": "обязательство %s: %s → %s"
                % (obligation.id, obligation.debtor, obligation.creditor),
            }
        )
        return obligation.to_dict()

    def _shift_character_relation(self, character, trust=0.0, affinity=0.0):
        changed = []
        for axis, delta in (("trust", trust), ("affinity", affinity)):
            if abs(float(delta)) <= 1e-12:
                continue
            before = _as_float(character.get(axis), 0.0)
            character[axis] = _clamp(before + float(delta), -1.0, 1.0)
            actual = character[axis] - before
            if abs(actual) > 1e-12:
                changed.append(
                    (
                        "%s · %s"
                        % (
                            character.get("name", character["id"]),
                            self.relation_axis_labels.get(axis, axis),
                        ),
                        actual,
                    )
                )
        if hasattr(character, "sync"):
            character.sync()
        return changed

    def _shift_relation_between(self, source_id, target_id, trust, affinity):
        source_id = _text(source_id)
        target_id = _text(target_id)
        if not source_id or not target_id or source_id == target_id:
            return []
        source = self.node(source_id)
        target = self.node(target_id)
        if source is None or target is None:
            return []
        current = self.relation_axes(source_id, target_id)
        after = self.set_relation_axes(
            source_id,
            target_id,
            {
                "trust": current["trust"] + float(trust),
                "affinity": current["affinity"] + float(affinity),
            },
        )
        changed = []
        for axis, delta in (
            ("trust", after["trust"] - current["trust"]),
            ("affinity", after["affinity"] - current["affinity"]),
        ):
            if abs(delta) <= 1e-12:
                continue
            changed.append(
                (
                    "%s → %s · %s"
                    % (
                        source.get("name", source_id),
                        target.get("name", target_id),
                        self.relation_axis_labels.get(axis, axis),
                    ),
                    delta,
                )
            )
        return changed

    def _apply_obligation_fulfillment(self, obligation):
        """Исполнение повышает доверие кредитора к должнику.

        Характер связи зависит от сторон: персонаж ↔ игрок меняет
        легаси-поля персонажа и `player_relations`; узел ↔ узел — оси
        `relation_axes`; персонаж ↔ персонаж остаётся записью журнала без
        выдуманной двусторонней шкалы (её ещё нет в модели).
        """
        scale = min(1.0, max(0.0, float(obligation.amount)))
        trust = OBLIGATION_FULFILL_TRUST * scale
        affinity = OBLIGATION_FULFILL_AFFINITY * scale
        creditor = obligation.creditor
        debtor = obligation.debtor
        creditor_char = self.character(creditor)
        debtor_char = self.character(debtor)
        changed = []
        if creditor == "player" and debtor_char is not None:
            changed.extend(
                self._shift_character_relation(debtor_char, trust, affinity)
            )
            view = self.player_relations.setdefault(debtor_char["id"], {})
            for axis, delta in (("trust", trust), ("affinity", affinity)):
                before = _as_float(view.get(axis), 0.0)
                view[axis] = _clamp(before + delta, -1.0, 1.0)
                actual = view[axis] - before
                if abs(actual) > 1e-12:
                    changed.append(
                        (
                            "вы · %s"
                            % self.relation_axis_labels.get(axis, axis),
                            actual,
                        )
                    )
            return changed
        if debtor == "player" and creditor_char is not None:
            changed.extend(
                self._shift_character_relation(
                    creditor_char, trust, affinity
                )
            )
            view = self.player_relations.setdefault(creditor_char["id"], {})
            for axis, delta in (("trust", trust), ("affinity", affinity)):
                before = _as_float(view.get(axis), 0.0)
                view[axis] = _clamp(before + delta, -1.0, 1.0)
                actual = view[axis] - before
                if abs(actual) > 1e-12:
                    changed.append(
                        (
                            "вы · %s"
                            % self.relation_axis_labels.get(axis, axis),
                            actual,
                        )
                    )
            return changed
        source_id = (
            self.player_node_id if creditor == "player" else creditor
        )
        target_id = self.player_node_id if debtor == "player" else debtor
        changed.extend(
            self._shift_relation_between(
                source_id, target_id, trust, affinity
            )
        )
        return changed

    def fulfill_obligation(self, obligation_id, day=None):
        """Отметить обязательство исполненным и сместить отношения."""
        obligation = self.obligations.fulfill(
            obligation_id, self.day if day is None else day
        )
        if obligation is None:
            return None
        changed = self._apply_obligation_fulfillment(obligation)
        self.log.append(
            {
                "day": self.day,
                "kind": "obligation",
                "text": "обязательство %s исполнено: %s → %s"
                % (obligation.id, obligation.debtor, obligation.creditor),
            }
        )
        result = obligation.to_dict()
        result["changes"] = changed
        return result

    def cancel_obligation(self, obligation_id, day=None):
        obligation = self.obligations.cancel(
            obligation_id, self.day if day is None else day
        )
        return None if obligation is None else obligation.to_dict()

    def obligation_view(self, party=None, day=None):
        """Срез журнала для UI и отладки."""
        day = self.day if day is None else _as_int(day, self.day)
        entries = (
            self.obligations.for_party(party)
            if party is not None
            else list(self.obligations)
        )
        return {
            "summary": self.obligations.summary(day),
            "entries": [item.to_dict() for item in entries],
            "due": [
                item.to_dict() for item in self.obligations.due(day)
            ],
            "overdue": [
                item.to_dict() for item in self.obligations.overdue(day)
            ],
        }

    def _overdue_obligation_rules(self):
        """Правила цены просроченного слова из блока `obligations`."""
        raw = self.config.get("obligations")
        raw = raw if isinstance(raw, Mapping) else {}
        raw = raw.get("overdue")
        raw = raw if isinstance(raw, Mapping) else {}
        relation = raw.get("relation")
        relation = relation if isinstance(relation, Mapping) else {}
        defaults = DEFAULT_OVERDUE_OBLIGATION["relation"]
        return {
            "enabled": bool(raw.get("enabled", True)),
            "relation": {
                axis: _as_float(relation.get(axis), default)
                for axis, default in defaults.items()
            },
            "negotiation_penalty": max(
                0.0,
                _as_float(
                    raw.get("negotiation_penalty"),
                    DEFAULT_OVERDUE_OBLIGATION["negotiation_penalty"],
                ),
            ),
            "max_stack": max(
                1,
                _as_int(
                    raw.get("max_stack"),
                    DEFAULT_OVERDUE_OBLIGATION["max_stack"],
                ),
            ),
        }

    def _apply_obligation_breach(self, obligation, rules):
        """Просроченное слово бьёт по доверию кредитора к должнику.

        Это зеркало `_apply_obligation_fulfillment()`: исполнение повышает
        доверие, просрочка его снижает. Прямых записей в активы нет.
        """
        scale = min(1.0, max(0.0, float(obligation.amount)))
        relation = rules.get("relation")
        relation = relation if isinstance(relation, Mapping) else {}
        trust = _as_float(relation.get("trust"), 0.0) * scale
        affinity = _as_float(relation.get("affinity"), 0.0) * scale
        creditor = obligation.creditor
        debtor = obligation.debtor
        creditor_char = self.character(creditor)
        debtor_char = self.character(debtor)
        changed = []
        if creditor == "player" and debtor_char is not None:
            changed.extend(
                self._shift_character_relation(
                    debtor_char, trust, affinity
                )
            )
            view = self.player_relations.setdefault(debtor_char["id"], {})
            for axis, delta in (("trust", trust), ("affinity", affinity)):
                before = _as_float(view.get(axis), 0.0)
                view[axis] = _clamp(before + delta, -1.0, 1.0)
                actual = view[axis] - before
                if abs(actual) > 1e-12:
                    changed.append(
                        (
                            "вы · %s"
                            % self.relation_axis_labels.get(axis, axis),
                            actual,
                        )
                    )
            return changed
        if debtor == "player" and creditor_char is not None:
            changed.extend(
                self._shift_character_relation(
                    creditor_char, trust, affinity
                )
            )
            view = self.player_relations.setdefault(creditor_char["id"], {})
            for axis, delta in (("trust", trust), ("affinity", affinity)):
                before = _as_float(view.get(axis), 0.0)
                view[axis] = _clamp(before + delta, -1.0, 1.0)
                actual = view[axis] - before
                if abs(actual) > 1e-12:
                    changed.append(
                        (
                            "вы · %s"
                            % self.relation_axis_labels.get(axis, axis),
                            actual,
                        )
                    )
            return changed
        source_id = (
            self.player_node_id if creditor == "player" else creditor
        )
        target_id = self.player_node_id if debtor == "player" else debtor
        changed.extend(
            self._shift_relation_between(
                source_id, target_id, trust, affinity
            )
        )
        return changed

    def _apply_overdue_obligations(self):
        """Один раз оплатить каждое просроченное обязательство."""
        rules = self._overdue_obligation_rules()
        if not rules["enabled"]:
            return []
        events = []
        for obligation in self.obligations.overdue(self.day):
            if obligation.breached():
                continue
            obligation.mark_breached(self.day)
            changed = self._apply_obligation_breach(obligation, rules)
            event = {
                "day": int(self.day),
                "kind": "obligation",
                "action": "overdue",
                "obligation_id": obligation.id,
                "creditor": obligation.creditor,
                "debtor": obligation.debtor,
                "changes": changed,
                "text": (
                    "слово просрочено: %s → %s"
                    % (obligation.debtor, obligation.creditor)
                ),
            }
            self.log.append(event)
            events.append(event)
        return events

    def _overdue_negotiation_penalty(self, character_id):
        """Штраф к переговорам за просроченные долги с соперником."""
        rules = self._overdue_obligation_rules()
        if not rules["enabled"]:
            return {"count": 0, "penalty": 0.0}
        character = self.character(character_id) or {}
        node_id = _text(character.get("node_id"))
        player_refs = {"player", self.player_node_id}
        rival_refs = {str(character_id), node_id}
        player_refs.discard("")
        rival_refs.discard("")
        count = 0
        for obligation in self.obligations.overdue(self.day):
            ends = {str(obligation.creditor), str(obligation.debtor)}
            if ends & player_refs and ends & rival_refs:
                count += 1
        count = min(rules["max_stack"], count)
        return {
            "count": count,
            "penalty": round(rules["negotiation_penalty"] * count, 6),
        }

    def value_rules(self):
        """Правила ценностей из блока `values` (кэш на инстанс)."""
        cached = getattr(self, "_value_rules_cache", None)
        if cached is None:
            cached = _values.value_rules(self.config.get("values") or {})
            self._value_rules_cache = cached
        return cached

    def _value_profile(self, context=None):
        """Профиль ценностей для игрока или узла/персонажа."""
        context = context or {}
        raw = context.get("values")
        if isinstance(raw, dict) and raw:
            return {"values": dict(raw)}
        if isinstance(raw, (list, tuple)) and raw:
            return {"value_ids": list(raw)}
        if context.get("is_player") or not context.get("node"):
            return self.profile
        node_values = context["node"].get("values")
        if isinstance(node_values, dict) and node_values:
            return {"values": dict(node_values)}
        if isinstance(node_values, (list, tuple)) and node_values:
            return {"value_ids": list(node_values)}
        return {}

    def value_check(self, action, context=None):
        """Проверить действие против жёстких ценностей.

        Пустое ограничение всегда разрешает действие: предательство по
        умолчанию возможно и оплачивается отношениями, репутацией и
        обязательствами. Запрет срабатывает только при явном `values` на
        действии (или при `values.defaults.betrayal` в конфиге мира).
        """
        if isinstance(action, str):
            action = self.actions.get(action) or {"id": action}
        return _values.check_action(
            action, self._value_profile(context), self.value_rules()
        )

    def _value_reason(self, action, context=None):
        result = self.value_check(action, context)
        return "" if result["allowed"] else result["reason"]

    def value_view(self):
        """Срез ценностей героя и объявленных ограничений для UI."""
        return _values.value_view(
            self.profile,
            self.value_rules(),
            list(self.actions.values()),
        )

    def coalition_rules(self):
        """Правила коалиций из блока `coalitions` (или `coalition`)."""
        cached = getattr(self, "_coalition_rules_cache", None)
        if cached is None:
            raw = self.config.get("coalitions")
            if raw is None:
                raw = self.config.get("coalition")
            cached = coalition_config(raw or {})
            self._coalition_rules_cache = cached
        return cached

    def _coalition_party(self, party):
        """Свести персонажа или игрока к узлу для счёта коалиции."""
        party = _text(party)
        if party == "player":
            return self.player_node_id
        if party in self.nodes:
            return party
        character = self.character(party)
        if character is not None:
            return _text(character.get("node_id")) or party
        return party

    def _coalition_obligation_counts(self, left, right):
        """Открытые и просроченные обязательства между двумя узлами."""
        parties = {str(left), str(right)}
        opened = 0
        overdue = 0
        for item in self.obligations.open():
            pair = {
                self._coalition_party(item.creditor),
                self._coalition_party(item.debtor),
            }
            if pair != parties:
                continue
            if item.overdue(self.day):
                overdue += 1
            else:
                opened += 1
        return opened, overdue

    def _coalition_obligations(self, left, right):
        """Совместимый счёт открытых обязательств без просрочки."""
        return self._coalition_obligation_counts(left, right)[0]

    def _coalition_pair_scores(self):
        """Сила всех рассматриваемых пар узлов на текущий день."""
        rules = self.coalition_rules()
        nodes = [
            node_id
            for node_id in self.node_order
            if node_id in self.nodes
        ]
        if not rules.get("include_player"):
            nodes = [
                node_id
                for node_id in nodes
                if node_id != self.player_node_id
            ]
        scores = {}
        for index, left in enumerate(nodes):
            for right in nodes[index + 1 :]:
                opened, overdue = self._coalition_obligation_counts(
                    left, right
                )
                scores[(left, right)] = pair_score(
                    self.relation_axes(left, right),
                    self.relation_axes(right, left),
                    opened,
                    axes=rules["axes"],
                    obligation_bonus=rules["obligation_bonus"],
                    overdue=overdue,
                    overdue_penalty=rules["overdue_penalty"],
                )
        return scores

    def _advance_coalitions(self):
        """Суточный шаг коалиций: распад, затем формирование.

        Пока блок `coalitions.enabled` выключен, метод ничего не делает и
        не пишет в журнал. Формирование идёт по детерминированному порядку
        пар, поэтому повторный запуск мира даёт тот же результат.
        """
        rules = self.coalition_rules()
        if not rules["enabled"]:
            return []
        eligible = {node_id: True for node_id in self.nodes}
        if not rules.get("include_player"):
            eligible.pop(self.player_node_id, None)
        names = {
            node_id: node.get("name", node_id)
            for node_id, node in self.nodes.items()
        }
        events = self.coalitions.update(
            self.day,
            self._coalition_pair_scores(),
            eligible=eligible,
            config=rules,
            names=names,
        )
        for event in events:
            self.log.append(event)
        return events

    def coalition_view(self, day=None):
        """Срез коалиций для UI/отладки."""
        view = self.coalitions.view(
            self.day if day is None else _as_int(day, self.day)
        )
        view["enabled"] = bool(self.coalition_rules()["enabled"])
        view["rules"] = dict(self.coalition_rules())
        return view

    def coalition_partners(self, node_id):
        """Активные союзники узла (пусто, если коалиции выключены)."""
        if not self.coalition_rules()["enabled"]:
            return []
        return self.coalitions.partners(node_id)

    def _coalition_bonus(self, context, target):
        """Небольшой бонус сотрудничеству внутри активной коалиции."""
        if target is None or not self.coalition_rules()["enabled"]:
            return 0.0
        node = context.get("node") or {}
        strength = self.coalitions.strength(
            node.get("id"), target.get("id")
        )
        if strength <= 0.0:
            return 0.0
        return self.coalition_rules()["cooperation_bonus"] * strength

    def set_directive(
        self,
        character_id,
        scope,
        payload,
        *,
        days=None,
        expires_day=None,
    ):
        """Дать персонажу явную директиву игрока.

        Области: `autonomy` (`{"enabled": bool}`), `intentions`
        (`reconcile/rapprochement/probe` или `""`), `beliefs`/`desires`
        (объект чисел для UI/отладки) и `work_queue` (очередь работы живёт
        в `IntentQueue`; здесь хранится только пометка). `days` — срок в
        днях от текущего; `expires_day` — абсолютный день.
        """
        character = self.character(character_id)
        if character is None:
            raise CampaignError("неизвестный персонаж: %s" % character_id)
        if expires_day is None and days is not None:
            expires_day = self.day + max(0, _as_int(days, 0))
        directive = self.directives.set(
            character["id"],
            scope,
            payload,
            day=self.day,
            expires_day=expires_day,
        )
        self.log.append(
            {
                "day": self.day,
                "kind": "directive",
                "text": "директива %s → %s"
                % (directive.scope, character.get("name", character["id"])),
            }
        )
        return directive.to_dict()

    def clear_directive(self, character_id, scope=None):
        """Снять директиву персонажа; без `scope` — все его директивы."""
        character = self.character(character_id)
        target = character["id"] if character is not None else character_id
        return self.directives.clear(target, scope)

    def directive_view(self, character_id=None):
        """Активные на текущий день директивы: target → scope → payload."""
        return self.directives.view(day=self.day, target=character_id)

    def character_control(self, character_id):
        """Граница автономии персонажа для UI и отладки."""
        character = self.character(character_id)
        if character is None:
            return None
        return {
            "id": character["id"],
            "autonomous": bool(character.get("autonomous")),
            "autonomy_enabled": self.directives.autonomy_enabled(
                character["id"], self.day
            ),
            "intended_branch": self.directives.intended_branch(
                character["id"], self.day
            ),
            "directives": self.directives.view(
                day=self.day, target=character["id"]
            ).get(character["id"], {}),
        }
