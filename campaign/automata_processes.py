"""Процессы действий, слоты, длительности и эффекты."""

from __future__ import annotations

from .automata_support import (
    EVENT_LOG_LIMIT,
    Mapping,
    _as_mapping,
    _clamp,
    _number,
    _text,
    apply_report,
)


class AutomataProcessesMixin:

    def _active_processes(self, side=None):
        side = None if side is None else str(side)
        return [
            record
            for record in self.processes
            if record.get("status") == "active"
            and (side is None or str(record.get("side")) == side)
        ]

    def active_processes(self, side=None):
        """Копии активных процессов: для UI и диалогового моста."""
        return [dict(record) for record in self._active_processes(side)]

    def settling_processes(self, side=None):
        """Процессы, чей эффект ещё разворачивается во времени."""
        side = None if side is None else str(side)
        return [
            dict(record)
            for record in self.processes
            if _as_mapping(record.get("effect")).get("status")
            == "settling"
            and (side is None or str(record.get("side")) == side)
        ]

    def ongoing_processes(self, side=None):
        """Подготовка и разворачивающийся эффект — для панели времени."""
        return self.active_processes(side) + self.settling_processes(side)

    def slot_state(self, side=None):
        """Сколько слотов занято и свободно у стороны."""
        side = str(side or self.player_side)
        used = len(self._active_processes(side))
        return {
            "side": side,
            "slots": self.action_slots,
            "used": used,
            "free": max(0, self.action_slots - used),
        }

    @staticmethod
    def _process_sort_key(record):
        """Порядок завершений: ``(finish_at, seq)``.

        Идентификатор сортировать нельзя: ``process-10`` лексикографически
        раньше ``process-2``. ``seq`` присваивается при создании процесса
        и переживает снимок; старые сейвы без поля получают номер из id.
        """
        raw_seq = record.get("seq")
        if raw_seq is None:
            tail = str(record.get("id") or "").rsplit("-", 1)[-1]
            try:
                raw_seq = int(tail)
            except (TypeError, ValueError):
                raw_seq = 0
        return (
            _number(record.get("finish_at"), 0.0),
            int(_number(raw_seq, 0.0)),
            str(record.get("id") or ""),
        )

    def slot_cards(self, side=None):
        """Карточки слотов: занят процессом или свободен.

        Слот занимает подготовка работы; разворачивающийся эффект живёт
        отдельно и показывается в списке процессов. Возвращаемые значения
        — только данные, без форматирования: UI решает, как их показать.
        """
        side = str(side or self.player_side)
        active = sorted(
            self._active_processes(side), key=self._process_sort_key
        )
        cards = []
        for index in range(self.action_slots):
            record = active[index] if index < len(active) else None
            if record is None:
                cards.append(
                    {
                        "slot": index + 1,
                        "side": side,
                        "occupied": False,
                    }
                )
                continue
            duration = max(0.0, _number(record.get("duration"), 0.0))
            remaining = max(0.0, _number(record.get("remaining"), 0.0))
            progress = (
                1.0
                if duration <= 0.0
                else max(0.0, min(1.0, 1.0 - remaining / duration))
            )
            cards.append(
                {
                    "slot": index + 1,
                    "side": side,
                    "occupied": True,
                    "id": str(record.get("id") or ""),
                    "kind": str(record.get("kind") or "action"),
                    "action_id": str(record.get("action_id") or ""),
                    "label": str(
                        record.get("label")
                        or record.get("action_id")
                        or "работа"
                    ),
                    "target_name": str(record.get("target_name") or ""),
                    "remaining": round(remaining, 6),
                    "duration": round(duration, 6),
                    "finish_at": round(
                        _number(record.get("finish_at"), 0.0), 6
                    ),
                    "progress": round(progress, 6),
                }
            )
        return cards

    def cancel_action(self, side, process_id, reason=""):
        """Отменить активный процесс стороны с пеней.

        Автоматическая отмена по изменившимся условиям возвращает цену
        полностью. Добровольная отмена игроком удерживает долю
        ``action_process.cancel.penalty``: слот освобождается, но работа
        не исчезает бесследно.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        side = str(side or self.player_side)
        record = next(
            (
                item
                for item in self.processes
                if str(item.get("id")) == str(process_id)
            ),
            None,
        )
        if record is None:
            return {"ok": False, "reason": "процесс не найден"}
        if str(record.get("side")) != side:
            return {"ok": False, "reason": "это процесс другой стороны"}
        if str(record.get("status")) != "active":
            return {"ok": False, "reason": "процесс уже завершён"}
        config = _as_mapping(self.action_process.get("cancel"))
        if not bool(config.get("enabled", True)):
            return {"ok": False, "reason": "отмена недоступна"}
        penalty = max(
            0.0, min(1.0, _number(config.get("penalty"), 0.5))
        )
        self._cancel_process(
            record,
            reason or str(config.get("reason") or "действие отменено"),
            penalty=penalty,
            voluntary=True,
        )
        return {
            "ok": True,
            "side": side,
            "process": dict(record),
            "penalty": round(penalty, 6),
            "refunded": dict(record.get("refunded") or {}),
            "forfeited": dict(record.get("forfeited") or {}),
            "slots": self.slot_state(side),
            "actions_left": self.actions_left,
        }

    def _duration_unit_seconds(self):
        """Сколько игровых секунд в одной единице ``template.duration``.

        В данных единица — час: ``duration_scale=3600``. Старые пресеты
        могли использовать секунды; они задают свой ``duration_scale``.
        """
        return max(
            0.0,
            _number(
                self.action_process.get("duration_unit"),
                _number(self.action_process.get("duration_scale"), 3600.0),
            ),
        )

    def _duration_class_hours(self, name):
        raw = _as_mapping(
            self.action_process.get("duration_classes")
        ).get(str(name))
        if isinstance(raw, Mapping):
            raw = raw.get("hours")
        return max(0.0, _number(raw, 0.0))

    def _action_duration(self, action, duration=None):
        """Длительность работы в игровых секундах.

        Приоритет: явное значение вызова, поле ``duration`` работы,
        ``template.duration`` (часы по умолчанию) с множителем из
        ``action_process.duration_scale``. Если задан
        ``template.duration_class`` (``hours``/``day``/``week``/…), его
        часы умножаются на ``template.duration`` и ``duration_unit``.
        Всё берётся из данных.
        """
        minimum = max(
            0.0, _number(self.action_process.get("min_duration"), 1.0)
        )
        if duration is not None:
            return max(minimum, _number(duration, minimum))
        explicit = action.get("duration")
        if explicit is not None:
            return max(minimum, _number(explicit, minimum))
        template = _as_mapping(action.get("template"))
        class_hours = self._duration_class_hours(
            template.get("duration_class")
        )
        if class_hours > 0.0:
            raw = template.get("duration")
            multiplier = 1.0 if raw is None else _number(raw, 1.0)
            return max(
                minimum,
                class_hours
                * max(0.0, multiplier)
                * self._duration_unit_seconds(),
            )
        scale = _number(
            self.action_process.get("duration_scale"),
            _number(self.action_process.get("default_duration"), 1.0),
        )
        raw = template.get("duration")
        if raw is None:
            raw = 1.0
        return max(minimum, _number(raw, 1.0) * max(0.0, scale))

    def _interaction_duration(self, kind, interaction, duration=None):
        """Длительность влияния или команды с учётом политики видов.

        Шаблоны в лорных фракциях исторически хранят ``duration: 1.0``
        (час). Реалистичный темп задаётся один раз в
        ``action_process.interaction_durations``: реформа — недели,
        повышение — неделя, поддержка — часы. Явная длительность
        вызова остаётся главнее политики.
        """
        minimum = max(
            0.0, _number(self.action_process.get("min_duration"), 1.0)
        )
        if duration is not None:
            return max(minimum, _number(duration, minimum))
        explicit = interaction.get("duration")
        if explicit is not None:
            return max(minimum, _number(explicit, minimum))
        policies = _as_mapping(
            self.action_process.get("interaction_durations")
        )
        entry = _as_mapping(
            _as_mapping(policies.get(str(kind))).get(
                str(interaction.get("id"))
            )
        )
        class_hours = self._duration_class_hours(entry.get("class"))
        if class_hours > 0.0:
            amount = _number(entry.get("amount"), 1.0)
            return max(
                minimum,
                class_hours
                * max(0.0, amount)
                * self._duration_unit_seconds(),
            )
        return self._action_duration(interaction, duration)

    def _action_effect_window(self, action, duration):
        """Сколько игровых секунд эффект действия разворачивается.

        Явное ``effect_duration`` в действии — часы. Иначе окно считается
        от длительности по коэффициенту формы из
        ``action_process.effect_window``. Это позволяет эдикту действовать
        неделями, а медицинской помощи — часами.
        """
        explicit = action.get("effect_duration")
        if explicit is not None:
            return max(
                0.0,
                _number(explicit, 0.0) * self._duration_unit_seconds(),
            )
        model = _as_mapping(
            self.action_process.get("effect_window")
        )
        form = self._action_form(action)
        by_form = _as_mapping(model.get("by_form"))
        scale = _number(
            by_form.get(form),
            _number(model.get("default_scale"), 1.0),
        )
        return max(0.0, _number(duration, 0.0) * max(0.0, scale))

    def _process_for_action(self, side, action_id):
        for record in self._active_processes(side):
            if str(record.get("action_id")) == str(action_id):
                return record
        return None

    def process_for_action(self, side, action_id):
        record = self._process_for_action(side, action_id)
        return dict(record) if record is not None else None

    def start_action(self, side, action_id, target=None, duration=None):
        """Начать процесс работы: слот, оплата и длительность.

        Эффект не применяется сразу. Процесс завершается в
        ``advance_time``; к этому моменту мир мог измениться, поэтому
        предпосылки проверяются повторно. Бюджет хода не тратится:
        ограничение — число слотов и время.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        actor = self.faction(side)
        if actor is None or actor.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        action = actor.action(action_id)
        if action is None:
            return {"ok": False, "reason": "действие не найдено"}
        if self._process_for_action(side, action_id) is not None:
            return {"ok": False, "reason": "действие уже выполняется"}
        slots = self.slot_state(actor.side)
        if slots["free"] <= 0:
            return {
                "ok": False,
                "reason": "заняты все слоты (%d)" % slots["slots"],
                "slots": slots,
            }
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
                "slots": slots,
            }
        target_side = self._target_side(side, action, target=target)
        target_faction = self.faction(target_side)
        if target_faction is None:
            return {"ok": False, "reason": "нет цели", "slots": slots}
        cost = self._action_cost(actor, action)
        for key, value in cost.items():
            actor.add_asset(key, -value)
        seconds = self._action_duration(action, duration)
        executor = self._choose_executor(actor.side, action)
        self._process_seq += 1
        record = {
            "id": "process-%d" % self._process_seq,
            "seq": int(self._process_seq),
            "side": actor.side,
            "action_id": str(action_id),
            "label": str(action.get("label") or action_id),
            "target_side": target_faction.side,
            "target_id": target_faction.id,
            "target_name": target_faction.name,
            "turn": int(self.turn),
            "started": round(float(self.elapsed), 6),
            "finish_at": round(float(self.elapsed) + float(seconds), 6),
            "duration": round(float(seconds), 6),
            "remaining": round(float(seconds), 6),
            "cost": cost,
            "executor_id": str(
                getattr(executor, "campaign_id", "") or ""
            ),
            "executor_name": str(
                getattr(executor, "name", "") or ""
            ),
            "executor_support": round(
                self._character_support(executor, action, actor)
                if executor is not None
                else 0.0,
                6,
            ),
            "executor_competence": round(
                self._character_competence(executor)
                if executor is not None
                else 0.0,
                6,
            ),
            "status": "active",
        }
        decision = self._record_narrative(
            "decision",
            actor=actor.name,
            actor_side=actor.side,
            target=target_faction.name,
            target_side=target_faction.side,
            action_id=str(action_id),
            label=record["label"],
        )
        record["narrative_id"] = str(decision.get("id") or "")
        self.processes.append(record)
        self._remember_assignment(executor, record, started=True)
        self._log_process(record, "начата")
        if self.stats.enabled and self.stats.actions:
            self.stats.log(
                "process_start",
                process_id=record["id"],
                side=record["side"],
                action_id=record["action_id"],
                label=record["label"],
                target_side=record["target_side"],
                target_id=record["target_id"],
                target_name=record["target_name"],
                duration=record["duration"],
                finish_at=record["finish_at"],
                cost=record["cost"],
                executor_id=record["executor_id"],
                executor_name=record["executor_name"],
                slots=self.slot_state(actor.side),
            )
        return {
            "ok": True,
            "process": dict(record),
            "slots": self.slot_state(actor.side),
            "actions_left": self.actions_left,
        }

    def _refund_process(self, record, share=1.0):
        """Вернуть часть цены процесса.

        ``share=1.0`` — полный возврат (автоматическая отмена по
        изменившимся условиям). Добровольная отмена игроком передаёт
        долю меньше единицы: потеря — это пена, а не скрытый штраф.
        """
        if not bool(self.action_process.get("refund_on_cancel", True)):
            return {}
        try:
            share = max(0.0, min(1.0, float(share)))
        except (TypeError, ValueError):
            share = 1.0
        actor = self.faction(record.get("side"))
        if actor is None:
            return {}
        refunded = {}
        for key, value in _as_mapping(record.get("cost")).items():
            amount = _number(value) * share
            if amount:
                actor.add_asset(key, amount)
                refunded[str(key)] = round(amount, 6)
        return refunded

    def _cancel_process(self, record, reason, penalty=0.0, voluntary=False):
        record["status"] = "cancelled"
        record["reason"] = str(reason or "процесс отменён")
        record["finished"] = round(float(self.elapsed), 6)
        record["remaining"] = 0.0
        penalty = max(0.0, min(1.0, _number(penalty, 0.0)))
        record["voluntary"] = bool(voluntary)
        record["penalty"] = round(penalty, 6)
        refunded = self._refund_process(record, share=1.0 - penalty)
        record["refunded"] = dict(refunded)
        if penalty > 0.0:
            lost = {}
            for key, value in _as_mapping(record.get("cost")).items():
                amount = _number(value) * penalty
                if amount:
                    lost[str(key)] = round(amount, 6)
            record["forfeited"] = lost
        self.last_process_result = dict(record)
        self._log_process(record, "отменена")
        self._log_process_stats(record)

    def _log_process_stats(self, record, result=None):
        """Записать начало/конец процесса в файловый аудит."""
        if not self.stats.enabled or not self.stats.actions:
            return
        result = _as_mapping(result)
        summary = {}
        for key in (
            "ok",
            "reason",
            "interaction_id",
            "organ_id",
            "organ_name",
            "integrity_before",
            "integrity_after",
            "integrity_delta",
            "morale_before",
            "morale_after",
            "needs_before",
            "needs_after",
            "faction_spread",
            "status",
            "text",
        ):
            if key in result:
                summary[key] = result[key]
        self.stats.log(
            "process_finish",
            process_id=record.get("id"),
            kind=record.get("kind") or "work",
            side=record.get("side"),
            action_id=record.get("action_id"),
            label=record.get("label"),
            target_side=record.get("target_side"),
            target_id=record.get("target_id"),
            target_name=record.get("target_name"),
            status=record.get("status"),
            duration=record.get("duration"),
            started=record.get("started"),
            finished=record.get("finished"),
            reason=record.get("reason", ""),
            result=summary,
        )

    def _finish_interaction_process(self, record):
        """Завершить влияние/команду и применить её эффект."""
        kind = str(record.get("kind") or "")
        faction = self.faction(record.get("side"))
        interaction = _as_mapping(record.get("interaction"))
        label = record.get("label")
        description = record.get("description")
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        if kind == "organ":
            organ = faction.organ(record.get("target_id"))
            if organ is None:
                return {"ok": False, "reason": "орган не найден"}
            return self._apply_organ_interaction(
                faction,
                organ,
                interaction,
                label,
                description,
            )
        if kind == "automaton":
            source = faction.organ(
                interaction.get("source_organ_id")
                or record.get("source_organ_id")
            )
            target = faction.organ(
                interaction.get("target_organ_id")
                or record.get("target_id")
            )
            if source is None:
                return {
                    "ok": False,
                    "reason": "автомат-источник не найден",
                }
            if target is None:
                return {
                    "ok": False,
                    "reason": "автомат-цель не найден",
                }
            return self._apply_automaton_interaction(
                faction,
                source,
                target,
                interaction,
                label,
                description,
            )
        if kind == "character":
            character = faction.character(record.get("target_id"))
            if character is None:
                return {"ok": False, "reason": "персонаж не найден"}
            return self._apply_character_interaction(
                faction,
                character,
                interaction,
                label,
                description,
            )
        return {"ok": False, "reason": "неизвестный процесс"}

    def _finish_process(self, record):
        """Завершить процесс, связав эффект с решением о его запуске."""

        cause_id = str(record.get("narrative_id") or "")
        previous = getattr(self, "_narrative_cause", "")
        self._narrative_cause = cause_id
        try:
            return self._finish_process_inner(record)
        finally:
            self._narrative_cause = previous

    def _finish_process_inner(self, record):
        if str(record.get("kind") or "") in (
            "organ",
            "automaton",
            "character",
        ):
            result = self._finish_interaction_process(record)
            record["finished"] = round(float(self.elapsed), 6)
            record["remaining"] = 0.0
            if result.get("ok"):
                record["status"] = "done"
                record["result"] = result
            else:
                record["status"] = "cancelled"
                record["reason"] = result.get(
                    "reason"
                ) or "действие не выполнено"
                self._refund_process(record)
            self.last_process_result = dict(record)
            self._log_process(
                record,
                "завершена" if result.get("ok") else "отменена",
            )
            self._log_process_stats(record, result)
            return result
        actor = self.faction(record.get("side"))
        action_id = str(record.get("action_id") or "")
        target_side = str(record.get("target_side") or "")
        target_faction = self.faction(target_side)
        reason = ""
        if actor is None or actor.dissolved:
            reason = "фракция недоступна"
        elif target_faction is None:
            reason = "нет цели"
        else:
            action = actor.action(action_id)
            if action is None:
                reason = "действие не найдено"
            elif bool(self.action_process.get("recheck_on_finish", True)):
                reason = self._action_use_reason(
                    actor, action
                ) or self._action_requirement_reason(
                    actor, action, target_faction
                )
            if not reason:
                initial = max(
                    0.0,
                    min(
                        1.0,
                        _number(
                            self.action_process.get(
                                "effect_initial_share"
                            ),
                            1.0,
                        ),
                    ),
                )
                executor = (
                    actor.character(record.get("executor_id"))
                    if actor is not None
                    else None
                )
                result = self._resolve_action(
                    actor,
                    action,
                    action_id,
                    target_side,
                    target_faction,
                    charge_cost=False,
                    spend_budget=False,
                    effect_fraction=initial,
                    executor=executor,
                )
                record["finished"] = round(float(self.elapsed), 6)
                record["remaining"] = 0.0
                record["result"] = result
                self._remember_assignment(
                    executor,
                    record,
                    success=bool(result.get("success")),
                )
                if result.get("ok"):
                    record["status"] = "done"
                    self._start_settlement(
                        record,
                        action,
                        _number(record.get("duration"), 0.0),
                        initial,
                    )
                else:
                    record["status"] = "cancelled"
                    record["reason"] = result.get(
                        "reason"
                    ) or "работа не выполнена"
                    self._refund_process(record)
                self.last_process_result = dict(record)
                self._log_process(record, "завершена")
                self._log_process_stats(record, result)
                return
        self._cancel_process(record, reason)

    def _start_settlement(self, record, action, duration, initial=1.0):
        """Начать постепенное разворачивание эффекта действия.

        Подготовка (``status="done"``) закончена, но проекции работы
        применяются не разом: первый импульс уже прошёл вместе с
        завершением, остаток распределяется по окну
        ``action_process.effect_window``. Поэтому эдикт продолжает
        действовать дни и недели, а не «срабатывает» в один кадр.
        """
        effect = _as_mapping(record.get("effect"))
        initial = max(0.0, min(1.0, _number(initial, 1.0)))
        remaining = max(0.0, 1.0 - initial)
        window = self._action_effect_window(action, duration)
        pulses = max(
            1,
            int(_number(self.action_process.get("effect_pulses"), 8)),
        )
        power = max(0.1, _number(
            self.action_process.get("effect_curve_power"), 1.5
        ))
        if remaining <= 1e-9 or window <= 0.0:
            effect.update(
                {
                    "initial": round(initial, 6),
                    "applied": round(initial, 6),
                    "effective": round(initial, 6),
                    "remaining": 0.0,
                    "pulses": 0,
                    "next_pulse": 0,
                    "status": "settled",
                    "started": round(float(self.elapsed), 6),
                    "finish_at": round(float(self.elapsed), 6),
                }
            )
            record["effect"] = effect
            return
        interval = window / float(pulses)
        effect.update(
            {
                "initial": round(initial, 6),
                "applied": round(initial, 6),
                "effective": round(initial, 6),
                "remaining": round(remaining, 6),
                "window": round(window, 6),
                "interval": round(interval, 6),
                "pulses": pulses,
                "next_pulse": 1,
                "curve_power": power,
                "started": round(float(self.elapsed), 6),
                "next_at": round(float(self.elapsed) + interval, 6),
                "finish_at": round(float(self.elapsed) + window, 6),
                "status": "settling",
            }
        )
        record["effect"] = effect
        self._log_effect(
            record,
            "эффект начал разворачиваться",
            "окно %.1f ч, импульсов %d" % (
                window / max(1.0, self._duration_unit_seconds()),
                pulses,
            ),
        )

    def _effect_condition_factor(self, record):
        """Насколько обстоятельства усиливают или гасят эффект.

        Данные ``action_process.settlement`` задают опорные активы,
        препятствия и вес органов. Мир меняется между импульсами, поэтому
        один и тот же эдикт в сильной и слабой фракции действует
        по-разному.
        """
        actor = self.faction(record.get("side"))
        if actor is None or actor.dissolved:
            return 0.0
        result = _as_mapping(record.get("result"))
        model = _as_mapping(self.action_process.get("settlement"))
        factor = 1.0
        support = [
            str(item)
            for item in (model.get("support_assets") or ())
            if str(item)
        ]
        if support:
            average = sum(actor.asset(key) for key in support) / float(
                len(support)
            )
            factor *= 0.5 + _clamp(average)
        obstacles = [
            str(item)
            for item in (model.get("obstacle_assets") or ())
            if str(item)
        ]
        threshold = _number(model.get("obstacle_threshold"), 0.35)
        penalty = _number(model.get("obstacle_penalty"), 0.6)
        for key in obstacles:
            if actor.asset(key) < threshold:
                factor *= max(0.05, penalty)
        organ_id = str(result.get("organ_id") or "")
        organ = actor.organ(organ_id) if organ_id else None
        if organ is not None:
            organ_weight = _clamp(_number(
                model.get("organ_weight"), 0.35
            ))
            factor *= 1.0 - organ_weight * (1.0 - _clamp(organ.integrity))
        target = self.faction(record.get("target_side"))
        defense_asset = str(result.get("defense_asset") or "")
        if target is not None and defense_asset:
            resistance = _clamp(target.asset(defense_asset))
            factor *= max(
                0.2,
                1.0
                - _clamp(_number(model.get("defense_weight"), 0.3))
                * resistance,
            )
        # Исполнитель продолжает влиять на эффект и после подготовки:
        # его поддержка цели и компетентность записаны в результат
        # процесса и переживают сохранение/загрузку.
        factor *= _number(result.get("executor_factor"), 1.0)
        return max(
            _number(model.get("min_factor"), 0.1),
            min(_number(model.get("max_factor"), 1.6), factor),
        )

    def _pulse_effect(self, record):
        effect = _as_mapping(record.get("effect"))
        if not effect or effect.get("status") != "settling":
            return
        index = int(_number(effect.get("next_pulse"), 1))
        total = max(1, int(_number(effect.get("pulses"), 1)))
        power = max(0.1, _number(effect.get("curve_power"), 1.5))
        remaining = max(0.0, _number(effect.get("remaining"), 0.0))
        weights = [float(i) ** power for i in range(index, total + 1)]
        weight_sum = sum(weights) or 1.0
        fraction = remaining * weights[0] / weight_sum
        factor = self._effect_condition_factor(record)
        result = _as_mapping(record.get("result"))
        report = _as_mapping(result.get("report"))
        actor = self.faction(record.get("side"))
        target = self.faction(record.get("target_side"))
        base_scale = _number(
            result.get("effect_scale"), self.model["effect_scale"]
        )
        applied = apply_report(
            actor,
            target,
            report,
            scale=base_scale * fraction * factor,
            source="process",
        )
        effect["applied"] = round(
            _number(effect.get("applied"), 0.0) + fraction, 6
        )
        effect["effective"] = round(
            _number(effect.get("effective"), 0.0) + fraction * factor, 6
        )
        effect["remaining"] = round(max(0.0, remaining - fraction), 6)
        effect["next_pulse"] = index + 1
        effect["last_factor"] = round(factor, 6)
        effect["last_scale"] = round(base_scale * fraction * factor, 6)
        effect["last_applied"] = applied
        started = _number(effect.get("started"), self.elapsed)
        interval = _number(effect.get("interval"), 0.0)
        if index >= total or effect["remaining"] <= 1e-9:
            effect["status"] = "settled"
            effect["finish_at"] = round(float(self.elapsed), 6)
            effect["next_at"] = round(float(self.elapsed), 6)
        else:
            effect["next_at"] = round(
                started + interval * float(index + 1), 6
            )
        record["effect"] = effect
        if self.stats.enabled and self.stats.effects:
            self.stats.log(
                "effect_pulse",
                process_id=record.get("id"),
                side=record.get("side"),
                action_id=record.get("action_id"),
                label=record.get("label"),
                pulse=index,
                pulses=total,
                fraction=round(fraction, 6),
                condition_factor=round(factor, 6),
                base_scale=round(base_scale, 6),
                effective_scale=round(
                    base_scale * fraction * factor, 6
                ),
                remaining=effect.get("remaining"),
                status=effect.get("status"),
                applied={
                    key: value
                    for key, value in applied.items()
                    if key != "report"
                },
            )
        self._log_effect(
            record,
            "импульс эффекта",
            "%.0f%% применено, множитель обстоятельств %.2f" % (
                effect["applied"] * 100.0,
                factor,
            ),
        )

    def _advance_effects(self):
        """Провести импульсы эффектов, у которых подошло время."""
        for record in list(self.processes):
            effect = _as_mapping(record.get("effect"))
            if effect.get("status") != "settling":
                continue
            guard = 0
            while (
                _as_mapping(record.get("effect")).get("status")
                == "settling"
                and self.elapsed + 1e-9
                >= _number(
                    _as_mapping(record.get("effect")).get(
                        "next_at", float("inf")
                    ),
                    float("inf"),
                )
                and guard < 10000
            ):
                self._pulse_effect(record)
                guard += 1
            effect = _as_mapping(record.get("effect"))
            if effect.get("status") == "settled":
                self._log_effect(
                    record, "эффект завершён", "действие перестало меняться"
                )

    def _log_effect(self, record, phase, detail=""):
        self.events.append(
            {
                "turn": int(self.turn),
                "kind": "effect",
                "phase": str(phase),
                "process_id": record.get("id"),
                "side": record.get("side"),
                "action_id": record.get("action_id"),
                "label": record.get("label"),
                "remaining": _as_mapping(record.get("effect")).get(
                    "remaining"
                ),
                "text": "эффект «%s»: %s%s"
                % (
                    record.get("label") or record.get("action_id"),
                    phase,
                    (" (%s)" % detail) if detail else "",
                ),
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]

    def _advance_processes(self, seconds):
        if self.finished:
            return
        expired = []
        for record in self._active_processes():
            remaining = _number(record.get("remaining"), 0.0) - seconds
            record["remaining"] = round(max(0.0, remaining), 6)
            if remaining <= 0.0:
                expired.append(record)
        expired.sort(key=self._process_sort_key)
        for record in expired:
            self._finish_process(record)
        self._advance_effects()
        self._trim_processes()

    def _log_process(self, record, phase):
        self.events.append(
            {
                "turn": int(self.turn),
                "kind": "process",
                "phase": str(phase),
                "process_id": record.get("id"),
                "side": record.get("side"),
                "action_id": record.get("action_id"),
                "label": record.get("label"),
                "status": record.get("status"),
                "remaining": record.get("remaining"),
                "reason": record.get("reason", ""),
                "text": "процесс «%s» %s" % (
                    record.get("label") or record.get("action_id"),
                    phase,
                ),
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]

    def _trim_processes(self):
        limit = max(
            1, int(_number(self.action_process.get("log_limit"), 40))
        )
        if len(self.processes) <= limit:
            return
        active = [
            record
            for record in self.processes
            if record.get("status") == "active"
        ]
        settling = [
            record
            for record in self.processes
            if _as_mapping(record.get("effect")).get("status")
            == "settling"
        ]
        done = [
            record
            for record in self.processes
            if record.get("status") != "active"
            and _as_mapping(record.get("effect")).get("status")
            != "settling"
        ]
        keep = max(0, limit - len(active) - len(settling))
        self.processes = (
            active + settling + done[-keep:] if keep else active + settling
        )

    def _leader(self, side):
        """Лидер фракции: первый персонаж, чьи BDI/органы ведут политику."""
        faction = self.faction(side)
        if faction is None or not faction.characters:
            return None
        return faction.characters[0]

    def _action_form(self, action):
        action = _as_mapping(action)
        return _text(
            action.get("form")
            or _as_mapping(action.get("template")).get("form")
        )

    def _action_essences(self, action):
        hints = _as_mapping(_as_mapping(action).get("hints"))
        values = [
            _text(hints.get("essence")),
            _text(hints.get("intention_essence")),
        ]
        return [value for value in values if value]

    def _action_need(self, essence, leader):
        if leader is None or not essence:
            return ""
        config = getattr(getattr(leader, "bdi", None), "config", None)
        if config is None:
            return ""
        return _text(config.need_for_essence(essence))
