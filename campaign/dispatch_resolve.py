"""Реакция на выбор игрока: память, обещания, слухи, последствия."""

from __future__ import annotations

from typing import Mapping

from .dispatch_support import (
    MEMORY_OUTCOMES,
    _alive,
    _as_mapping,
    _clamp,
    _number,
    _render,
)


class ResolveMixin:

    def resolve(self, report_id, choice_id):
        report = self.report(report_id)
        if report is None:
            return {"ok": False, "reason": "доклад не найден"}
        if str(report.get("status") or "") != "pending":
            return {
                "ok": False,
                "reason": "доклад уже закрыт",
                "report": report,
            }
        choice_id = str(choice_id or "").strip()
        allowed = {
            str(item.get("id") or "") for item in report.get("choices") or ()
        }
        if choice_id not in allowed:
            return {
                "ok": False,
                "reason": "неизвестный выбор",
                "report": report,
            }
        faction = self.campaign.faction(report.get("side"))
        source = self._character(report.get("source_id"))
        rumor = str(report.get("channel") or "") == "rumor"
        counterpart = None if rumor else self._pending_counterpart(report)
        if counterpart is None and not rumor:
            partner_id = str(report.get("contradicted_by") or "")
            partner = self.report(partner_id) if partner_id else None
            if (
                partner is not None
                and str(partner.get("status") or "") == "pending"
            ):
                counterpart = partner
        cost = 0
        if choice_id == "verify" and self.verify_cost:
            gate = getattr(
                self.campaign, "_player_action_gate", None
            )
            if callable(gate):
                reason = gate(report.get("side"))
                if reason:
                    return {
                        "ok": False,
                        "reason": "проверка недоступна: %s" % reason,
                        "report": report,
                    }
            spend = getattr(
                self.campaign, "_spend_player_action", None
            )
            if callable(spend):
                spend(report.get("side"))
            cost = (
                self.verify_cost
                if str(report.get("side") or "")
                == str(getattr(self.campaign, "player_side", ""))
                else 0
            )
        effect_key = choice_id
        correct = None
        revealed_truth = not rumor
        revealed_motive = False
        manipulation = bool(report.get("manipulation"))
        if choice_id == "verify":
            if rumor:
                effect_key = "rumor_verify"
                revealed_truth = False
            else:
                error = abs(
                    _number(report.get("perceived"))
                    - _number(report.get("true_value"))
                )
                band_error = str(report.get("band") or "") != str(
                    report.get("true_band") or ""
                )
                manipulation = manipulation and band_error
                correct = (
                    error <= self.verify_tolerance + 1e-9
                    and not manipulation
                )
                if correct:
                    effect_key = "verify_right"
                elif manipulation:
                    effect_key = "verify_lie"
                    revealed_motive = (
                        self.rng.random()
                        <= _clamp(
                            self.distortion.get("motive_reveal", 0.75)
                        )
                    )
                else:
                    effect_key = "verify_wrong"
        elif rumor:
            effect_key = "rumor_%s" % choice_id
        effect_pool = self.rumor_effects if rumor else self.effects
        effect = _as_mapping(effect_pool.get(effect_key))
        if not effect and effect_key == "verify_lie":
            effect = _as_mapping(effect_pool.get("verify_wrong"))
        changes = self._apply_effects(
            faction,
            source,
            report,
            effect,
            effect_key,
            motive=report.get("motive") if revealed_motive else None,
        )
        promise = self._make_promise(
            faction, source, report, choice_id
        )
        if promise is not None:
            changes["promise"] = promise
        recorder = getattr(self.campaign, "_record_narrative", None)
        if callable(recorder):
            leader_changes = _as_mapping(changes.get("leader"))
            morale_delta = _number(changes.get("morale")) + _number(
                leader_changes.get("morale")
            )
            cause_id = ""
            finder = getattr(
                self.campaign, "_narrative_id_for_report", None
            )
            if callable(finder):
                for key in ("derived_from", "contradicted_by"):
                    reference = str(report.get(key) or "")
                    if not reference:
                        continue
                    cause_id = finder(reference)
                    if cause_id:
                        break
            recorder(
                "report",
                actor=str(getattr(faction, "name", "") or ""),
                actor_side=str(getattr(faction, "side", "") or ""),
                target=str(report.get("source_name") or ""),
                target_side=str(report.get("side") or ""),
                action_id=str(choice_id or ""),
                label=str(report.get("title") or "доклад"),
                success=correct,
                form="report",
                morale_delta=round(morale_delta, 6),
                report_id=str(report.get("id") or ""),
                cause_id=cause_id,
                cause_label=(
                    str(report.get("title") or "") if cause_id else ""
                ),
            )
        values_map = {
            "source": report.get("source_name") or "Источник",
            "asset": report.get("asset") or "",
            "asset_label": report.get("asset_label") or "",
            "band": report.get("band_label") or "",
            "truth_band": report.get("true_band_label") or "",
            "motive": (
                report.get("motive") if revealed_motive else ""
            ),
        }
        if counterpart is not None:
            values_map["counter_source"] = (
                counterpart.get("source_name") or "Источник"
            )
            values_map["counter_band"] = (
                counterpart.get("band_label") or ""
            )
        text_pool = (
            self.rumor_result_texts if rumor else self.result_texts
        )
        if counterpart is not None:
            contradiction_key = (
                "verify" if choice_id == "verify" else choice_id
            )
            text = _render(
                self.contradiction_result_texts.get(
                    contradiction_key
                )
                or "Спор рассмотрен: {asset_label} — «{truth_band}».",
                values_map,
            )
        else:
            text_key = effect_key
            if effect_key == "verify_lie" and not revealed_motive:
                text_key = "verify_lie_hidden"
            text = _render(
                text_pool.get(text_key)
                or text_pool.get(effect_key)
                or text_pool.get(choice_id)
                or self.result_texts.get(text_key)
                or self.result_texts.get(effect_key)
                or self.result_texts.get(choice_id)
                or "Решение принято.",
                values_map,
            )
        follow_up = None
        if (
            rumor
            and choice_id == "verify"
            and not report.get("follow_up")
        ):
            follow_up = self._spawn_rumor_follow_up(
                faction, source, report
            )
        self._remember(
            report, choice_id, correct, effect_key
        )
        report["status"] = "resolved"
        report["choice"] = choice_id
        report["resolved"] = {
            "choice": choice_id,
            "correct": correct,
            "manipulation": manipulation,
            "motive": (
                report.get("motive") if revealed_motive else None
            ),
            "motive_revealed": revealed_motive,
            "text": text,
            "changes": changes,
            "cost": cost,
            "revealed_truth": revealed_truth,
            "promise": (
                promise.get("id") if promise is not None else None
            ),
            "follow_up": (
                follow_up.get("id") if follow_up is not None else None
            ),
            "decided_by": report.get("decided_by") or "player",
            "at": round(
                _number(getattr(self.campaign, "elapsed", 0.0)), 6
            ),
            "turn": int(_number(getattr(self.campaign, "turn", 0), 0)),
        }
        counterpart_result = None
        if counterpart is not None and counterpart is not report:
            counterpart_result = self._resolve_counterpart(
                counterpart, report, choice_id, revealed_truth
            )
            if counterpart_result is not None:
                report["resolved"]["contradicts"] = (
                    counterpart_result.get("id")
                )
        sync = getattr(self.campaign, "_sync_report_event", None)
        if callable(sync):
            sync(report)
        self._log_choice(report, choice_id, correct, changes, text)
        return {
            "ok": True,
            "report": report,
            "choice": choice_id,
            "correct": correct,
            "manipulation": manipulation,
            "motive": (
                report.get("motive") if revealed_motive else None
            ),
            "motive_revealed": revealed_motive,
            "truth_band": (
                report.get("true_band") if revealed_truth else None
            ),
            "truth_band_label": (
                report.get("true_band_label") if revealed_truth else None
            ),
            "revealed_truth": revealed_truth,
            "cost": cost,
            "follow_up": (
                follow_up.get("id") if follow_up is not None else None
            ),
            "promise": (
                promise.get("id") if promise is not None else None
            ),
            "counterpart": counterpart_result,
            "text": text,
            "changes": changes,
        }

    def _make_promise(self, faction, source, report, choice_id):
        """Доверие к просьбе источника рождает обещание в журнале."""
        if not self.promise_enabled or choice_id != "trust":
            return None
        if not report.get("asks_promise") or source is None:
            return None
        if str(report.get("channel") or "") == "rumor":
            return None
        if report.get("promise_id"):
            return None
        leader = self._leader_for(faction)
        if leader is None:
            return None
        creditor = str(getattr(source, "campaign_id", "") or "")
        if str(getattr(faction, "side", "")) == str(
            getattr(self.campaign, "player_side", "")
        ):
            debtor = "player"
        else:
            debtor = str(getattr(leader, "campaign_id", "") or "")
        if not creditor or not debtor or creditor == debtor:
            return None
        turn = int(_number(getattr(self.campaign, "turn", 0), 0))
        due_days = max(
            1, int(_number(self.promise_config.get("due_days"), 5))
        )
        note = "report:%s:%s:%s" % (
            report.get("id"),
            report.get("asset"),
            "%.6f" % _number(report.get("true_value"), 0.0),
        )
        add = getattr(self.campaign, "add_obligation", None)
        if not callable(add):
            return None
        try:
            obligation = add(
                creditor,
                debtor,
                str(self.promise_config.get("kind") or "favor"),
                _number(self.promise_config.get("amount"), 1.0),
                due_day=turn + due_days,
                note=note,
            )
        except Exception:
            return None
        if not isinstance(obligation, Mapping):
            return None
        report["promise_id"] = obligation.get("id")
        self._log(
            "promise_made",
            side=report.get("side"),
            report_id=report.get("id"),
            source_id=creditor,
            debtor=debtor,
            obligation_id=obligation.get("id"),
            due_day=obligation.get("due_day"),
        )
        return dict(obligation)

    @staticmethod
    def _outcome_key(effect_key, choice):
        """Свести эффект решения к исходу памяти источника."""
        if effect_key in ("trust", "rumor_trust"):
            return "trusted"
        if effect_key == "verify_right":
            return "verified_right"
        if effect_key == "verify_lie":
            return "lied"
        if effect_key in ("verify_wrong", "rumor_verify"):
            return "verified_wrong"
        if effect_key in ("ignore", "rumor_ignore"):
            return "ignored"
        return str(choice or "")

    def _remember(self, report, choice, correct, effect_key):
        """Записать исход в память получателя для следующих докладов."""
        if not self.memory_enabled:
            return
        source_id = str(report.get("source_id") or "")
        if not source_id:
            return
        memory = self._memory_entry(
            source_id, report.get("recipient_id")
        )
        memory["reports"] = int(_number(memory.get("reports"), 0)) + 1
        outcome = self._outcome_key(effect_key, choice)
        if outcome in (
            "trusted",
            "ignored",
            "verified_right",
            "verified_wrong",
            "lied",
        ):
            memory[outcome] = int(_number(memory.get(outcome), 0)) + 1
        memory["last_outcome"] = outcome
        memory["last_report_id"] = str(report.get("id") or "")
        memory["last_asset"] = str(report.get("asset") or "")
        memory["last_asset_label"] = str(
            report.get("asset_label") or report.get("asset") or ""
        )
        memory["last_band"] = str(report.get("band") or "")
        memory["last_band_label"] = str(report.get("band_label") or "")
        memory["last_source_name"] = str(
            report.get("source_name") or ""
        )
        memory["last_correct"] = correct
        self._spread_outcome(report, outcome)

    def _spread_outcome(self, report, outcome):
        """Разнести слух об исходе доклада по чужим лидерам.

        Память источника остаётся личной: получатель знает исход точно,
        а остальные слышат ослабленный слух через общих знакомых или
        городскую молву. Слух не задаёт ``last_outcome``, поэтому не
        выдаёт себя за личный доклад. По дороге слух может исказиться:
        перевернуть исход, преувеличить силу или приписать всё другому
        источнику.
        """
        cfg = _as_mapping(self.memory_config.get("spread"))
        if not bool(cfg.get("enabled", True)):
            return []
        if outcome not in MEMORY_OUTCOMES:
            return []
        source_id = str(report.get("source_id") or "")
        recipient_id = str(report.get("recipient_id") or "")
        origin_side = str(report.get("side") or "")
        if not source_id:
            return []
        base = _clamp(cfg.get("chance"), 0.0, 1.0)
        weight = max(0.0, _number(cfg.get("weight"), 0.5))
        relation_weight = _number(cfg.get("relation_weight"), 0.4)
        include_player = bool(cfg.get("include_player", False))
        distortion = _as_mapping(cfg.get("distortion"))
        distortion_on = bool(distortion.get("enabled", True))
        distort_chance = _clamp(distortion.get("chance"), 0.0, 1.0)
        source_chance = _clamp(
            distortion.get("source_chance"), 0.0, 1.0
        )
        weight_scale = max(
            0.0, _number(distortion.get("weight_scale"), 1.5)
        )
        flips = _as_mapping(distortion.get("outcomes"))
        player_side = str(
            getattr(self.campaign, "player_side", "") or ""
        )
        spread = []
        for faction in self._factions():
            side = str(getattr(faction, "side", "") or "")
            if side == origin_side:
                continue
            if side == player_side and not include_player:
                continue
            leader = self._leader_for(faction)
            if leader is None:
                continue
            leader_id = str(
                getattr(leader, "campaign_id", "") or ""
            )
            if not leader_id or leader_id in (recipient_id, source_id):
                continue
            shared = self._shared_acquaintance(
                leader_id, recipient_id, source_id
            )
            chance = _clamp(
                base + relation_weight * shared, 0.0, 1.0
            )
            if chance <= 0.0 or self.spread_rng.random() >= chance:
                continue
            rumor_source = source_id
            rumor_outcome = outcome
            rumor_weight = weight
            distorted = False
            if (
                distortion_on
                and distort_chance > 0.0
                and self.spread_rng.random() < distort_chance
            ):
                flipped = str(flips.get(rumor_outcome) or "")
                if flipped in MEMORY_OUTCOMES:
                    rumor_outcome = flipped
                rumor_weight *= weight_scale
                distorted = True
            if (
                distortion_on
                and source_chance > 0.0
                and self.spread_rng.random() < source_chance
            ):
                confused = self._confuse_source(
                    report, source_id, recipient_id
                )
                if confused:
                    rumor_source = confused
                    distorted = True
            memory = self._memory_entry(rumor_source, leader_id)
            memory["reports"] = _number(
                memory.get("reports"), 0.0
            ) + rumor_weight
            memory[rumor_outcome] = _number(
                memory.get(rumor_outcome), 0.0
            ) + rumor_weight
            memory["spread"] = int(
                _number(memory.get("spread"), 0)
            ) + 1
            spread.append(
                {
                    "side": side,
                    "outcome": rumor_outcome,
                    "source_id": rumor_source,
                    "distorted": distorted,
                }
            )
            self._log(
                "memory_spread",
                side=side,
                from_side=origin_side,
                source_id=rumor_source,
                true_source_id=source_id,
                outcome=rumor_outcome,
                true_outcome=outcome,
                weight=rumor_weight,
                distorted=distorted,
            )
        return spread

    def _confuse_source(self, report, source_id, recipient_id=""):
        """Подменить источник слуха другим человеком той же стороны."""
        faction = self.campaign.faction(report.get("side"))
        if faction is None:
            return ""
        candidates = []
        for character in getattr(faction, "characters", ()) or ():
            cid = str(getattr(character, "campaign_id", "") or "")
            if not cid or cid in (source_id, recipient_id):
                continue
            if not _alive(character):
                continue
            candidates.append(cid)
        if not candidates:
            return ""
        return self.spread_rng.choice(candidates)

    def _shared_acquaintance(self, leader_id, recipient_id, source_id):
        """Насколько чужой лидер близок к участникам доклада."""
        relations = getattr(self.campaign, "relations", None)
        if relations is None:
            return 0.0
        best = 0.0
        for other in (recipient_id, source_id):
            if not other or other == leader_id:
                continue
            for pair in ((leader_id, other), (other, leader_id)):
                try:
                    axes = relations.axes_for(*pair)
                except Exception:
                    continue
                best = max(
                    best,
                    _number(axes.get("affinity")),
                    _number(axes.get("trust")),
                )
        return _clamp(best, 0.0, 1.0)

    def _resolve_counterpart(
        self, counterpart, winner, choice_id, revealed_truth
    ):
        """Закрыть второй доклад спора тем же решением игрока."""
        if counterpart is None or counterpart is winner:
            return None
        faction = self.campaign.faction(counterpart.get("side"))
        source = self._character(counterpart.get("source_id"))
        correct = None
        if choice_id == "verify":
            error = abs(
                _number(counterpart.get("perceived"))
                - _number(counterpart.get("true_value"))
            )
            correct = error <= self.verify_tolerance + 1e-9
            effect_key = (
                "contradiction_verify_right"
                if correct
                else "contradiction_verify_wrong"
            )
        elif choice_id == "trust":
            effect_key = "contradiction_trust"
        else:
            effect_key = "contradiction_ignore"
        effect = _as_mapping(
            self.contradiction_effects.get(effect_key)
        )
        belief_target = (
            counterpart.get("asset")
            if choice_id == "verify"
            else winner.get("source_id")
        )
        changes = self._apply_effects(
            faction,
            source,
            counterpart,
            effect,
            effect_key,
            belief_target=belief_target,
        )
        if choice_id == "verify":
            text = "Спор разрешён: «%s»." % (
                counterpart.get("true_band_label") or "неизвестно"
            )
            derived_choice = "contradiction_verify"
        elif choice_id == "trust":
            text = "Спор решён в пользу другого источника."
            derived_choice = "contradiction_trust"
        else:
            text = "Спор отложен."
            derived_choice = "contradiction_ignore"
        counterpart["status"] = "resolved"
        counterpart["choice"] = derived_choice
        counterpart["resolved"] = {
            "choice": derived_choice,
            "correct": correct,
            "text": text,
            "changes": changes,
            "cost": 0,
            "revealed_truth": revealed_truth,
            "follow_up": None,
            "resolved_by": winner.get("id"),
            "at": round(
                _number(getattr(self.campaign, "elapsed", 0.0)), 6
            ),
            "turn": int(_number(getattr(self.campaign, "turn", 0), 0)),
        }
        sync = getattr(self.campaign, "_sync_report_event", None)
        if callable(sync):
            sync(counterpart)
        self._log_choice(
            counterpart, derived_choice, correct, changes, text
        )
        return {
            "id": counterpart.get("id"),
            "source_name": counterpart.get("source_name"),
            "choice": derived_choice,
            "correct": correct,
            "text": text,
            "changes": changes,
        }

    def _spawn_rumor_follow_up(self, faction, source, report):
        """Проверка слуха рождает новый claim, а не истину."""
        if faction is None or source is None:
            return None
        if len(
            self._pending_reports(
                report.get("side"), include_shadowed=True
            )
        ) >= self.max_pending:
            return None
        follow = self._build_report(
            faction, source, report.get("asset"), "rumor"
        )
        if follow is None:
            return None
        values_map = {
            "source": follow.get("source_name") or "Слух",
            "asset": follow.get("asset") or "",
            "asset_label": follow.get("asset_label") or "",
            "band": follow.get("band_label") or "",
            "truth_band": follow.get("true_band_label") or "",
        }
        follow["follow_up"] = True
        follow["derived_from"] = report.get("id")
        follow["text"] = _render(self.rumor_follow_up_text, values_map)
        follow["title"] = _render(
            self.rumor_follow_up_title, values_map
        )
        follow["confidence"] = min(
            0.95, _number(report.get("confidence")) + 0.15
        )
        follow["confidence_label"] = self._confidence_label(
            follow["confidence"]
        )
        self.reports.append(follow)
        self._trim()
        self._record_story(follow)
        self._log_issued(follow)
        return follow

    @staticmethod
    def _memory_key(recipient_id, source_id):
        return "%s|%s" % (str(recipient_id or ""), str(source_id or ""))

    def _memory_for(self, source_id, recipient_id=None):
        """Память конкретного получателя, с откатом к общей записи.

        Старые снимки хранили одну память на источник. Она остаётся
        общим запасным вариантом, а новые исходы пишутся отдельно для
        каждого лидера-получателя.
        """
        source_id = str(source_id or "")
        if recipient_id is None:
            leader = self._leader_for(
                self.campaign.faction(
                    getattr(self.campaign, "player_side", "")
                )
            )
            recipient_id = getattr(leader, "campaign_id", "")
        recipient_id = str(recipient_id or "")
        key = self._memory_key(recipient_id, source_id)
        memory = self.memory.get(key)
        if memory is not None:
            return memory
        return self.memory.get(source_id) or {}

    def _memory_entry(self, source_id, recipient_id):
        key = self._memory_key(recipient_id, source_id)
        return self.memory.setdefault(key, self._new_memory())

    def _memory_line(self, source_id, recipient_id=None):
        """Строка-цепочка: источник помнит прошлый доклад и его исход."""
        if not self.memory_enabled:
            return "", 0.0
        memory = self._memory_for(str(source_id or ""), recipient_id)
        outcome = str(memory.get("last_outcome") or "")
        if not outcome:
            return "", 0.0
        lines = _as_mapping(self.memory_config.get("lines"))
        template = lines.get(outcome) or lines.get("expired") or ""
        if not template:
            return "", 0.0
        delta = {
            "trusted": 1.0,
            "verified_right": 1.25,
            "ignored": -1.0,
            "verified_wrong": -1.25,
            "lied": -1.5,
            "expired": -0.5,
        }.get(outcome, 0.0)
        line = _render(
            template,
            {
                "last_asset": memory.get("last_asset") or "",
                "last_asset_label": memory.get("last_asset_label")
                or memory.get("last_asset")
                or "",
                "last_band": memory.get("last_band") or "",
                "last_band_label": memory.get("last_band_label") or "",
                "last_source": memory.get("last_source_name") or "",
            },
        )
        return line, delta

    def _intent(
        self, source, values, needs, tone, recipient_id=None
    ):
        """Намеренная манипуляция отличается от честной ошибки.

        Честный источник искажает картину только собственной ошибкой.
        Амбициозный или нелояльный — сознательно сдвигает полосу в
        сторону, которая даёт ему рычаг: просит полномочия, топит
        соперника или прячет провал. Проверка может вскрыть мотив.
        """
        cfg = self.distortion
        if not self.distortion_enabled:
            return "honest", "", 0
        memory = self._memory_for(
            str(getattr(source, "campaign_id", "") or ""),
            recipient_id,
        )
        total = max(1, int(_number(memory.get("reports"), 0)))
        grievance = (
            _number(memory.get("ignored"), 0.0)
            + _number(memory.get("verified_wrong"), 0.0)
        ) / total
        chance = (
            _number(cfg.get("base"), 0.06)
            + _number(cfg.get("ambition"), 0.22)
            * _number(values.get("ambition"), 0.5)
            + _number(cfg.get("disloyalty"), 0.18)
            * (1.0 - _number(values.get("loyalty"), 0.5))
            + _number(cfg.get("fear"), 0.08)
            * _number(needs.get("fear"), 0.0)
            + _number(cfg.get("grievance"), 0.12) * grievance
        )
        if self.rng.random() >= _clamp(chance):
            return "honest", "", 0
        motives = _as_mapping(cfg.get("motives"))
        motive = str(motives.get(tone) or motives.get("neutral") or "")
        if tone in ("ambitious", "hostile", "neutral"):
            direction = -1
        elif tone == "loyal_fearful":
            direction = 1
        else:
            direction = -1
        strong_at = _number(cfg.get("strong_at"), 0.7)
        strength = max(
            _number(values.get("ambition"), 0.5),
            _number(needs.get("fear"), 0.0),
            1.0 - _number(values.get("loyalty"), 0.5),
        )
        steps = (
            int(_number(cfg.get("strong_shift"), 2))
            if strength >= strong_at
            else int(_number(cfg.get("shift"), 1))
        )
        return "manipulation", motive, direction * max(1, steps)

    def _shift_band(self, band, steps):
        index = int(band.get("index", 0)) + int(steps)
        index = max(0, min(len(self.bands) - 1, index))
        return self.bands[index]

    def _promise_context(self, faction, source, asset, true_value):
        """Напомнить об обещании и закрыть его, если положение улучшилось."""
        if not self.promise_enabled:
            return "", False
        source_id = str(getattr(source, "campaign_id", "") or "")
        leader = self._leader_for(faction)
        if not source_id or leader is None:
            return "", False
        obligations = getattr(self.campaign, "obligations", None)
        if obligations is None:
            return "", False
        source_name = str(getattr(source, "name", "") or "Источник")
        reminder = ""
        for obligation in obligations.for_party(source_id):
            if not obligation.active():
                continue
            note = str(obligation.note or "")
            if not note.startswith("report:"):
                continue
            parts = note.split(":")
            if len(parts) < 4:
                continue
            promised_asset = parts[2]
            try:
                reference = float(parts[3])
            except (TypeError, ValueError):
                reference = 0.0
            label = self.asset_labels.get(
                promised_asset, promised_asset
            )
            values_map = {
                "source": source_name,
                "asset": promised_asset,
                "asset_label": label,
            }
            tolerance = _number(self.verify_tolerance, 0.12)
            if (
                promised_asset == str(asset)
                and true_value >= reference + tolerance
            ):
                fulfill = getattr(
                    self.campaign, "fulfill_obligation", None
                )
                if callable(fulfill):
                    fulfill(obligation.id)
                self._forgive_broken_word(faction, leader)
                self._log(
                    "promise_fulfilled",
                    side=getattr(faction, "side", ""),
                    source_id=source_id,
                    obligation_id=obligation.id,
                    asset=promised_asset,
                )
                return _render(
                    self.promise_config.get("fulfilled_line"),
                    values_map,
                ), False
            if obligation.due(
                int(_number(getattr(self.campaign, "turn", 0), 0))
            ):
                penalty_key = "promise:%s" % obligation.id
                memory = self._memory_entry(
                    source_id,
                    getattr(leader, "campaign_id", ""),
                )
                penalized = list(memory.get("penalized_promises") or ())
                if penalty_key not in penalized:
                    self._penalize_promise(
                        faction, source, leader, promised_asset
                    )
                    penalized.append(penalty_key)
                    memory["penalized_promises"] = penalized
                return _render(
                    self.promise_config.get("overdue_line"),
                    values_map,
                ), True
            reminder = _render(
                self.promise_config.get("line"),
                values_map,
            )
            if promised_asset == str(asset):
                break
        return reminder, False

    def _penalize_promise(self, faction, source, leader, asset):
        """Просроченное обещание живёт в BDI, а не в активах."""
        try:
            source.needs["fear"] = _clamp(
                _number(source.needs.get("fear"), 0.0) + 0.01
            )
        except Exception:
            pass
        morale = _number(getattr(source, "morale", 0.0))
        try:
            source.morale = max(0.0, min(100.0, morale - 1.5))
        except Exception:
            pass
        leader_key = self._leader_key(faction, leader)
        try:
            source.believe(
                leader_key, "feels_betrayed_by", str(faction.id)
            )
        except Exception:
            pass
        relations = getattr(self.campaign, "relations", None)
        if relations is not None:
            try:
                relations.add(
                    str(faction.id),
                    str(getattr(source, "campaign_id", "") or ""),
                    {"trust": -0.03, "affinity": -0.02},
                    1.0,
                )
            except Exception:
                pass
        changes = {
            "promise_overdue": True,
            "asset": str(asset),
            "source_id": str(getattr(source, "campaign_id", "") or ""),
        }
        belief = _as_mapping(self.promise_config.get("belief"))
        predicate = str(belief.get("predicate") or "")
        if predicate and leader is not None:
            try:
                self._believe(
                    leader,
                    leader_key,
                    predicate,
                    str(getattr(source, "campaign_id", "") or ""),
                    _number(belief.get("value"), 0.7),
                    _number(belief.get("confidence"), 0.8),
                )
                changes["belief"] = predicate
            except Exception:
                pass
        self._log("promise_overdue", **changes)

    def _forgive_broken_word(self, faction, leader):
        """Снять след просрочки, когда лидер закрыл свои долги.

        Убеждение ``has_broken_word`` даёт вес работам, которые
        восстанавливают опору: поддержке, награде и ремонту. Оно живёт,
        пока у лидера остаётся хотя бы один просроченный долг; закрытие
        последнего возвращает прежние веса.
        """
        predicate = str(
            _as_mapping(self.promise_config.get("belief")).get("predicate")
            or ""
        )
        if not predicate or leader is None:
            return False
        obligations = getattr(self.campaign, "obligations", None)
        day = int(_number(getattr(self.campaign, "turn", 0), 0))
        if obligations is not None:
            party = self._leader_key(faction, leader)
            for item in obligations.for_party(party):
                if item.active() and item.overdue(day):
                    return False
        bdi = getattr(leader, "bdi", None)
        if bdi is None:
            return False
        removed = bdi.forget(
            self._leader_key(faction, leader), predicate
        )
        if not removed:
            return False
        leader.beliefs = bdi.beliefs
        self._log(
            "promise_atoned",
            side=getattr(faction, "side", ""),
            predicate=predicate,
        )
        return True

    def _new_memory(self):
        return {
            "reports": 0,
            "trusted": 0,
            "verified_right": 0,
            "verified_wrong": 0,
            "lied": 0,
            "ignored": 0,
            "expired": 0,
            "last_outcome": "",
            "last_report_id": "",
            "last_asset": "",
            "last_asset_label": "",
            "last_band": "",
            "last_band_label": "",
            "last_source_name": "",
            "penalized_promises": [],
            "spread": 0,
        }

    def _leader_key(self, faction, leader=None):
        if leader is None:
            leader = self._leader_for(faction)
        if str(getattr(faction, "side", "")) == str(
            getattr(self.campaign, "player_side", "")
        ):
            return "player"
        if leader is not None:
            return str(getattr(leader, "campaign_id", "") or "")
        return str(getattr(faction, "id", "") or "")
