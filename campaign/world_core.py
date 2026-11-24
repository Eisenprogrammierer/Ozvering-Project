"""Жизненный цикл мира: свойства игрока, такт, день, журнал и LOD."""

from __future__ import annotations

from .world_support import (
    CampaignLod,
    SLOTS_MAX,
    SLOT_DAY_EDGE,
    _as_float,
    _as_int,
    _as_slot,
    _clamp,
    _logbook,
    _text,
    time,
)


class WorldCoreMixin:

    @property
    def actions_left(self):
        return self.player.actions_left

    @actions_left.setter
    def actions_left(self, value):
        self.player.actions_left = value

    @property
    def player_energy(self):
        return self.player.energy

    @player_energy.setter
    def player_energy(self, value):
        self.player.energy = value

    @property
    def player_max_energy(self):
        return self.player.max_energy

    @property
    def player_force(self):
        return self.player.force

    @player_force.setter
    def player_force(self, value):
        self.player.force = value

    @property
    def player_health(self):
        return self.player.health

    @player_health.setter
    def player_health(self, value):
        self.player.health = value

    @property
    def player_sickness(self):
        return self.player.sickness

    @player_sickness.setter
    def player_sickness(self, value):
        self.player.sickness = value

    @property
    def player_wound(self):
        return self.player.wound

    @player_wound.setter
    def player_wound(self, value):
        self.player.wound = value

    @property
    def player_alive(self):
        return not self._player_dead and self.player.alive

    @player_alive.setter
    def player_alive(self, value):
        self._player_dead = not bool(value)
        if not value:
            # Смерть — это обнуление силы. Здоровье остаётся состоянием,
            # но не отдельным порогом смерти.
            self.player.force = 0.0
            self.player.health = 0.0
            resources = getattr(self, "player_resources", None)
            if resources is not None:
                resources["standing"] = 0.0

    def validate(
        self, action_id, target_id=None, context=None, target_ref=None
    ):
        action = self.actions.get(_text(action_id))
        context = context or self.player_context()
        if action is None:
            return False, "неизвестное действие"
        if context is None:
            return False, "сначала выберите должность"
        target = (
            self.entity(target_ref)
            if target_ref is not None
            else (self.node(target_id) if target_id else None)
        )
        if target_ref is not None and target is None:
            return False, "адресат не найден"
        if (action.get("target") or {}).get("self"):
            target = context["node"]
        reason = self._reason_actor(action, context)
        if reason:
            return False, reason
        reason = self._reason_target(action, context, target)
        if reason:
            return False, reason
        reason = self._reason_requirements(action, context, target)
        if reason:
            return False, reason
        reason = self._value_reason(action, context)
        if reason:
            return False, reason
        reason = self._reason_cost(action, context)
        if reason:
            return False, reason
        if not context.get("ai"):
            cooldown = _as_int(action.get("cooldown_days"), 0)
            if cooldown:
                key = "%s:%s" % (
                    action["id"],
                    target["id"] if target else "",
                )
                last_day = self.cooldowns.get(key)
                if (
                    last_day is not None
                    and self.day - int(last_day) < cooldown
                ):
                    return False, "повтор не раньше дня %d" % (
                        int(last_day) + cooldown
                    )
            if self.actions_left <= 0:
                return False, "действия на сегодня исчерпаны"
            if action.get("once") and action["id"] in self.used_actions:
                return False, "действие уже использовано"
        return True, ""

    def log_rules(self):
        """Правила важности/паузы из блока `logging` (кэш на инстанс)."""
        cached = getattr(self, "_log_rules_cache", None)
        if cached is None:
            cached = _logbook.rules_from_config(
                self.config.get("logging") or {}
            )
            self._log_rules_cache = cached
        return cached

    def log_view(self, **kwargs):
        """Размеченный журнал для UI без изменения исходных записей."""
        return _logbook.log_view(
            self.log, rules=self.log_rules(), **kwargs
        )

    def log_digest(self, day=None):
        """Сводка журнала: счётчики и последнее критическое событие."""
        return _logbook.digest(
            self.log,
            day=self.day if day is None else day,
            rules=self.log_rules(),
        )

    def log_summary(self):
        """Короткая строка сводки журнала для HUD."""
        return _logbook.summary_text(
            self.log, day=self.day, rules=self.log_rules()
        )

    def log_stats(self):
        """Диагностика журнала: размер, сжатие и полная сводка."""
        report = self.log_digest()
        return {
            "total": len(self.log),
            "trimmed": int(self.log_trimmed),
            "digest": report,
        }

    def critical_pause_reason(self):
        """Причина остановить фон по критическим событиям дня.

        Состояние героя проверяется напрямую, а журнал добавляет события,
        которых нет в состоянии: например, объявленный контент `collapse`
        или пользовательский критический вид из блока `logging.pause`.
        """
        reason = _logbook.pause_reason(
            self.log, day=self.day, rules=self.log_rules()
        )
        if reason:
            return reason
        if self.finished:
            return "finished"
        if not self.attached:
            return "unattached"
        if not self.player_alive:
            return "dead"
        return ""

    def _trim_log(self):
        """Сжать журнал на границе дня, если это включено контентом."""
        rules = self.log_rules()
        if not rules.get("compact"):
            return 0
        kept, removed = _logbook.compact(
            self.log,
            max_entries=rules.get("max_entries"),
            recent_days=rules.get("recent_days"),
            critical_keep=rules.get("critical_keep"),
            day=self.day,
            rules=rules,
        )
        if removed:
            self.log = kept
            self.log_trimmed += removed
        return removed

    def lod(self):
        """LOD-профиль узлов, пересобираемый при смене узла героя."""
        if self._lod is None or self._lod_root != self.player_node_id:
            self._lod = CampaignLod(
                self.nodes,
                self.player_node_id,
                self.config.get("lod") or {},
            )
            self._lod_root = self.player_node_id
        return self._lod

    def lod_view(self, day=None):
        """Сколько узлов на каждом LOD и сколько ходит в указанный день."""
        return self.lod().report(self.day if day is None else day)

    def scale_view(self):
        """Один срез масштаба: LOD, стоимость тика и размер журнала."""
        return {
            "lod": self.lod_view(),
            "tick": dict(self.tick_stats),
            "log": self.log_stats(),
        }

    def tick(self, max_slot=SLOTS_MAX):
        """Внутридневной тик планировщика (A5).

        Непрерывность времени кампании: мир исполняет намерения не только
        на границе дня (слот 0), но и внутри него. `tick(max_slot=1)`
        запускает очередь слотов 0..1 и НЕ двигает сутки — это чистый
        внутридневный шаг. Полный цикл дня по-прежнему делает `end_day()`.

        Контракт времени A5: намерение со сроком «день N» исполняется в
        начале дня N. Тик внутри суток N открывает очередь этих суток —
        долг (due_day < self.day) и слоты 0..max_slot дня self.day;
        дальние дни ждут своего перехода. Извлечённые намерения исчезают
        из очереди, поэтому `end_day()` повторно их не исполнит.

        Возвращает список событий (пустой, если очередью делать нечего).
        Стоимость и число пропущенных LOD-узлов пишутся в `tick_stats`:
        это наблюдаемость §7.7 №40, а не часть состояния мира.
        """
        if self.finished:
            return []
        started = time.perf_counter()
        events = self._run_overdue()
        events.extend(self._run_intents(max_slot=max_slot))
        events.extend(self._run_node_actions(max_slot=max_slot))
        self.tick_stats["ticks"] += 1
        self.tick_stats["intents"] += len(events)
        self.tick_stats["last_cost"] = time.perf_counter() - started
        self.tick_stats["last_slot"] = _as_slot(max_slot)
        return events

    def _node_slot(self, node_id):
        """Внутридневной слот автономного узла (детерминированный).

        Узлы, как и персонажи, действуют не только на границе суток: слот
        распределяет их ходы по дню, чтобы фон не «включался» одной пачкой
        в `end_day()`. Слот зависит от дня и id узла, поэтому повторный
        запуск мира воспроизводит тот же порядок, а сохранение не требует
        хранить расписание.
        """
        if SLOTS_MAX <= 0:
            return SLOT_DAY_EDGE
        token = "node-slot:%s:%s" % (self.day, node_id)
        return min(
            SLOTS_MAX,
            int(self._roll(token) * (SLOTS_MAX + 1)),
        )

    def _run_node_actions(self, max_slot=None):
        """Ходы автономных узлов: не более одного раза за сутки.

        `max_slot` ограничивает выборку внутридневными слотами; `None`
        означает «доиграть остаток дня» и используется `end_day()`. Факт
        хода фиксируется до вызова `_ai_action()`, поэтому узел без
        доступного действия не будет повторно опрошен в тот же день.
        """
        limit = SLOTS_MAX if max_slot is None else _as_slot(max_slot)
        events = []
        lod = self.lod()
        for node_id in self.node_order:
            if self.node_action_day.get(node_id) == self.day:
                continue
            if (
                max_slot is not None
                and self._node_slot(node_id) > limit
            ):
                continue
            if not lod.due(node_id, self.day):
                self.tick_stats["nodes_skipped"] += 1
                continue
            self.tick_stats["nodes_considered"] += 1
            self.node_action_day[node_id] = self.day
            entry = self._ai_action(node_id)
            if entry is not None:
                self.tick_stats["nodes_acted"] += 1
                events.append(entry)
        return events

    def end_day(self):
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        events = []
        events.extend(self._run_overdue())
        events.extend(self._run_intents(max_slot=SLOTS_MAX, day=self.day))
        events.extend(self._run_node_actions())
        daily = self.config.get("daily") or {}
        changed = []
        for key, value in (daily.get("node") or {}).items():
            for node in self.nodes.values():
                if key in node["stats"]:
                    before = node["stats"][key]
                    node["stats"][key] = _clamp(before + _as_float(value))
                    delta = node["stats"][key] - before
                    if abs(delta) > 1e-9:
                        changed.append(
                            (
                                "%s · %s"
                                % (node["name"], self.stat_label(key)),
                                delta,
                            )
                        )
        if daily.get("player"):
            changed.extend(self._apply_player_map(daily.get("player")))
        changed.extend(self._apply_legitimacy_recovery())
        changed.extend(self._apply_organizational_drift())
        events.extend(self._advance_strategies())
        changed.extend(self._apply_daily_income())
        changed.extend(self._advance_conditions())
        self.day += 1
        self.actions_left = self.actions_per_day
        changed.extend(self._apply_economy_day())
        events.extend(self._apply_overdue_obligations())
        events.extend(self._advance_coalitions())
        self.directives.prune(self.day)
        events.extend(self._run_intents(max_slot=SLOTS_MAX))
        if self.day > self.days and not self.sandbox:
            if self.infinite:
                if not self.horizon_passed:
                    self.horizon_passed = True
                    self.log.append(
                        {
                            "day": self.day,
                            "kind": "horizon",
                            "text": "Сюжетный горизонт пройден; история "
                            "продолжается.",
                        }
                    )
            elif self.outcome is None:
                self.outcome = (
                    "win"
                    if self.player_resources["standing"] >= 0.35
                    else "lose"
                )
                self.finished = True
        self._check_storyline()
        self._check_dismissal()
        self._schedule_autonomy()
        summary = "Мир сделал ход: %d событий." % len(events)
        result = {
            "ok": True,
            "day": self.day,
            "text": summary,
            "events": events,
            "changes": self._merge_changes(changed),
        }
        self.last_result = {
            "ok": True,
            "action": "end_day",
            "action_label": "Завершение дня",
            "target": "",
            "target_label": "",
            "outcome": "day",
            "text": summary,
            "changes": result["changes"],
            "day": self.day,
        }
        self.log.append({"day": self.day, "kind": "day", "text": summary})
        self._trim_log()
        return result

    def advance_days(self, days, max_days=None):
        """Продвинуть мир на несколько дней для фона/оффлайна (§7 №31).

        Останавливается на первом терминальном исходе или ошибке. Возвращает
        список результатов `end_day()`; ограничение `max_days` защищает от
        случайного огромного догона.
        """
        try:
            limit = max(0, int(days))
        except (TypeError, ValueError):
            limit = 0
        if max_days is not None:
            limit = min(limit, max(0, int(max_days)))
        results = []
        for _ in range(limit):
            if self.finished:
                break
            result = self.end_day()
            if not result.get("ok"):
                break
            results.append(result)
            if self.finished:
                break
        return results

    def world_outcome(self):
        return {
            "outcome": self.outcome,
            "finished": self.finished,
            "day": self.day,
            "standing": self.player_resources["standing"],
            "health": self.player_health,
            "sickness": self.player_sickness,
            "alive": self.player_alive,
            "energy": self.player_energy,
            "actions_left": self.actions_left,
            "force": self.player_force,
            "infinite": bool(self.infinite),
            "sandbox": bool(self.sandbox),
            "realtime": bool(self.realtime),
            "horizon_passed": bool(self.horizon_passed),
            "ending": self.ending,
            "dismissed": bool(self.dismissed),
            "dismissal_count": int(self.dismissal_count),
            "collapsed": bool(self.collapsed),
            "collapse_days": int(self.collapse_days),
            "storyline_days": int(self.storyline_days),
            "organization": self.organization_status(),
        }

    def sorted_nodes(self):
        return [self.nodes[node_id] for node_id in self.node_order]
