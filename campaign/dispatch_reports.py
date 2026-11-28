"""Выпуск доклада: источник, тон, полоса, противоречия, ИИ-выбор."""

from __future__ import annotations

from typing import Mapping

from .dispatch_support import (
    _alive,
    _as_list,
    _as_mapping,
    _clamp,
    _number,
    _render,
)


class ReportMixin:

    def report(self, report_id):
        key = str(report_id or "")
        for report in self.reports:
            if str(report.get("id") or "") == key:
                return report
        return None

    def _pending_reports(self, side=None, include_shadowed=False):
        side = str(side or "")
        result = []
        for report in self.reports:
            if str(report.get("status") or "") != "pending":
                continue
            if side and str(report.get("side") or "") != side:
                continue
            if not include_shadowed and self._is_shadowed(report):
                continue
            result.append(report)
        return result

    def _is_shadowed(self, report):
        partner_id = str(report.get("contradicted_by") or "")
        partner = self.report(partner_id) if partner_id else None
        return (
            partner is not None
            and str(partner.get("status") or "") == "pending"
        )

    def _factions(self):
        values = getattr(self.campaign, "factions", {}) or {}
        return [
            faction
            for faction in values.values()
            if faction is not None
            and not bool(getattr(faction, "dissolved", False))
        ]

    def _leader_for(self, faction):
        if faction is None:
            return None
        getter = getattr(self.campaign, "_leader", None)
        leader = None
        if callable(getter):
            try:
                leader = getter(faction.side)
            except Exception:
                leader = None
        if leader is None and getattr(faction, "characters", None):
            leader = faction.characters[0]
        return leader

    def _rival_faction_id(self, faction):
        """Соперник для убеждения «видит угрозу».

        Для каждой фракции это её соперник по сценарию, а для самой
        соперничающей стороны — игрок. Так доклад о плохом состоянии
        подталкивает лидера к силовым работам против конкретной цели,
        которую понимает ``ai_model.beliefs.rules``.
        """
        player_side = str(getattr(self.campaign, "player_side", ""))
        rival_side = str(getattr(self.campaign, "rival_side", ""))
        side = str(getattr(faction, "side", ""))
        target_side = rival_side if side != rival_side else player_side
        target = self.campaign.faction(target_side)
        if target is not None and target is not faction:
            return str(target.id)
        return ""

    def auto_resolve(self, report):
        """Лидер чужой фракции сам решает, что делать с докладом.

        Решение — не случайная монетка: доверие к источнику, его
        лояльность, страх, тревога и дисциплина лидера, а также память о
        прошлых докладах задают веса. Последствия пишутся в BDI лидера и
        источника, поэтому меняется и выбор работ фракции.
        """
        if report is None:
            return None
        if str(report.get("status") or "") != "pending":
            return None
        side = str(report.get("side") or "")
        if side == str(getattr(self.campaign, "player_side", "")):
            return None
        faction = self.campaign.faction(side)
        leader = self._leader_for(faction)
        choice = self._ai_choice(report, faction, leader)
        report["decided_by"] = "ai"
        result = self.resolve(report.get("id"), choice)
        if leader is not None:
            report["decided_by_id"] = str(
                getattr(leader, "campaign_id", "") or ""
            )
        follow_id = (
            result.get("follow_up") if isinstance(result, Mapping) else None
        )
        if follow_id:
            follow = self.report(follow_id)
            if follow is not None:
                self.auto_resolve(follow)
        self._capture_intercept(report)
        return result

    def _ai_choice(self, report, faction, leader):
        """Оценки реакции и выбор: Soar при ``reaction_policy``, иначе argmax.

        Доверие, проверка и игнорирование считаются здесь, вместе с
        шумом из ``rng``. Сам выбор делает ``campaign._report_select``
        (Soar), а легаси-argmax с tie-break по имени остаётся резервом.
        """

        cfg = self.ai_config
        source = self._character(report.get("source_id"))
        values = getattr(
            getattr(leader, "personality", None), "values", {}
        ) or {}
        needs = getattr(leader, "needs", {}) or {}
        source_values = getattr(
            getattr(source, "personality", None), "values", {}
        ) or {}
        trust_axis = 0.0
        source_to_leader = 0.0
        relations = getattr(self.campaign, "relations", None)
        if (
            relations is not None
            and faction is not None
            and source is not None
        ):
            try:
                trust_axis = float(
                    relations.axes_for(
                        faction.id, report.get("source_id")
                    ).get("trust", 0.0)
                )
                source_to_leader = float(
                    relations.axes_for(
                        report.get("source_id"), faction.id
                    ).get("trust", 0.0)
                )
            except Exception:
                trust_axis = 0.0
                source_to_leader = 0.0
        memory = self._memory_for(
            report.get("source_id"), report.get("recipient_id")
        )
        total = max(1, int(_number(memory.get("reports"), 0)))
        history = (
            _number(memory.get("trusted"), 0.0)
            + _number(memory.get("verified_right"), 0.0) * 0.5
            - _number(memory.get("ignored"), 0.0) * 0.5
            - _number(memory.get("verified_wrong"), 0.0)
            - _number(memory.get("lied"), 0.0) * 1.2
        ) / total
        loyalty = _number(source_values.get("loyalty"), 0.5)
        discipline = _number(values.get("discipline"), 0.5)
        fear = _number(needs.get("fear"), 0.5)
        anxiety = _number(needs.get("anxiety"), 0.5)
        trust_score = (
            _number(cfg.get("trust_base"), 0.35)
            + _number(cfg.get("trust_relation"), 0.45) * trust_axis
            + _number(cfg.get("trust_loyalty"), 0.2) * loyalty
            + _number(cfg.get("trust_history"), 0.25) * history
            + _number(cfg.get("trust_fear"), -0.3) * fear
        )
        verify_score = (
            _number(cfg.get("verify_base"), 0.1)
            + _number(cfg.get("verify_anxiety"), 0.35) * anxiety
            + _number(cfg.get("verify_discipline"), 0.3) * discipline
            + _number(cfg.get("verify_distrust"), 0.3) * (1.0 - trust_axis)
            + _number(cfg.get("verify_history"), 0.2)
            * max(0.0, -history)
        )
        ignore_score = (
            _number(cfg.get("ignore_base"), 0.1)
            + _number(cfg.get("ignore_fear"), 0.35) * fear
            + _number(cfg.get("ignore_distrust"), 0.25) * (1.0 - trust_axis)
            + _number(cfg.get("ignore_loyalty"), 0.2) * (1.0 - loyalty)
        )
        scores = {
            "trust": trust_score,
            "verify": verify_score,
            "ignore": ignore_score,
        }
        noise = max(0.0, _number(cfg.get("noise"), 0.0))
        if noise:
            for key in scores:
                scores[key] += self.rng.uniform(-noise, noise)
        candidates = [(key, scores[key]) for key in scores]
        selector = getattr(self.campaign, "_report_select", None)
        if callable(selector):
            chosen = selector(
                side=report.get("side"),
                kind=self._reaction_kind(report),
                candidates=candidates,
            )
            if chosen is not None:
                return chosen
        return max(scores, key=lambda key: (scores[key], key))

    def _reaction_kind(self, report):
        """Вид решения: доклад или доклад в полосе угрозы."""

        bands = {
            str(item)
            for item in _as_list(
                self.threat_config.get("bands")
            )
        }
        if (
            self.threat_enabled
            and str(report.get("band") or "") in bands
        ):
            return "threat"
        return "report"

    def issue(self, faction=None):
        """Создать один доклад от подходящего источника."""
        if not self.enabled:
            return None
        faction = faction or self.campaign.faction(
            self.campaign.player_side
        )
        if faction is None or not self.assets:
            return None
        leader = self._leader_for(faction)
        if leader is None:
            return None
        if len(self.pending(faction.side)) >= self.max_pending:
            self._expire_oldest(faction.side)
        asset = self._next_asset()
        source = self._source(faction, asset)
        if source is None:
            return None
        channel = "report"
        if self.rumor_enabled and self.rng.random() < self.rumor_chance:
            channel = "rumor"
        report = self._build_report(faction, source, asset, channel)
        if report is None:
            return None
        self._attach_contradiction(report)
        self.reports.append(report)
        self._trim()
        self._record_story(report)
        self._log_issued(report)
        return report

    def _attach_contradiction(self, report):
        """Связать новый доклад с уже ждущим спорным сообщением."""
        if not self.contradiction_enabled:
            return None
        if str(report.get("channel") or "") != "report":
            return None
        if self.rng.random() >= self.contradiction_chance:
            return None
        counterpart = self._counterpart_for(report)
        if counterpart is None:
            return None
        values_map = self._contradiction_values(report, counterpart)
        report["contradicts"] = counterpart.get("id")
        report["contradiction"] = True
        report["counter_source"] = counterpart.get("source_name")
        report["counter_band"] = counterpart.get("band")
        report["counter_band_label"] = counterpart.get("band_label")
        report["title"] = _render(self.contradiction_title, values_map)
        report["text"] = _render(self.contradiction_text, values_map)
        report["counter_line"] = _render(
            self.contradiction_counter_line, values_map
        )
        counterpart["contradicted_by"] = report.get("id")
        mirror = self._contradiction_values(counterpart, report)
        counterpart["contradiction"] = True
        counterpart["counter_source"] = report.get("source_name")
        counterpart["counter_band"] = report.get("band")
        counterpart["counter_band_label"] = report.get("band_label")
        counterpart["counter_line"] = _render(
            self.contradiction_counter_line_late, mirror
        )
        return counterpart

    def _counterpart_for(self, report):
        for candidate in self._pending_reports(
            report.get("side"), include_shadowed=True
        ):
            if candidate is report:
                continue
            if candidate.get("contradicts") or candidate.get(
                "contradicted_by"
            ):
                continue
            if str(candidate.get("channel") or "") != "report":
                continue
            if str(candidate.get("asset") or "") != str(
                report.get("asset") or ""
            ):
                continue
            if str(candidate.get("source_id") or "") == str(
                report.get("source_id") or ""
            ):
                continue
            if str(candidate.get("band") or "") == str(
                report.get("band") or ""
            ):
                continue
            return candidate
        return None

    def _contradiction_values(self, report, counterpart):
        return {
            "source": report.get("source_name") or "Источник",
            "counter_source": counterpart.get("source_name") or "Источник",
            "asset": report.get("asset") or "",
            "asset_label": report.get("asset_label") or "",
            "band": report.get("band_label") or "",
            "counter_band": counterpart.get("band_label") or "",
            "truth_band": report.get("true_band_label") or "",
            "confidence": report.get("confidence_label") or "",
        }

    def _pending_counterpart(self, report):
        counter_id = str(report.get("contradicts") or "")
        if not counter_id:
            return None
        counterpart = self.report(counter_id)
        if counterpart is None:
            return None
        if str(counterpart.get("status") or "") != "pending":
            return None
        return counterpart

    def _next_asset(self):
        asset = self.assets[self._asset_index % len(self.assets)]
        self._asset_index += 1
        return asset

    def _source(self, faction, asset):
        characters = [
            character
            for character in getattr(faction, "characters", ()) or ()
            if _alive(character)
            and str(getattr(character, "campaign_post_id", "") or "")
        ]
        if not characters:
            return None
        matches = []
        for post_id in self.source_by_asset.get(asset, ()):
            for character in characters:
                if (
                    str(
                        getattr(character, "campaign_post_id", "")
                        or ""
                    )
                    == post_id
                ):
                    matches.append(character)
        if matches:
            return matches[self._seq % len(matches)]
        # Лидер не докладывает сам себе; если других нет — молчим.
        fallback = [
            character
            for character in characters
            if str(getattr(character, "campaign_post_id", "") or "")
            != "leader"
        ]
        if not fallback:
            return None
        return fallback[(self._seq + self._asset_index) % len(fallback)]

    def _build_report(self, faction, source, asset, channel="report"):
        asset = str(asset)
        rumor = str(channel) == "rumor"
        true_value = _clamp(faction.asset(asset))
        true_band = self._band(true_value)
        values = getattr(
            getattr(source, "personality", None), "values", {}
        ) or {}
        needs = getattr(source, "needs", {}) or {}
        source_id = str(getattr(source, "campaign_id", "") or "")
        leader = self._leader_for(faction)
        recipient_id = str(getattr(leader, "campaign_id", "") or "")
        confidence = self._confidence(values, needs)
        chain_line, memory_delta = self._memory_line(
            source_id, recipient_id
        )
        if chain_line and not rumor:
            confidence = _clamp(
                confidence + memory_delta * _number(
                    self.memory_config.get("confidence_step"), 0.04
                )
            )
        noise_scale = 1.0
        if rumor:
            confidence = _clamp(
                confidence * self.rumor_confidence_scale
            )
            noise_scale = self.rumor_noise_scale
        span = (
            (1.0 - confidence)
            * _number(self.confidence_cfg.get("noise"), 0.35)
            * noise_scale
        )
        noise = self.rng.uniform(-span, span) if span else 0.0
        perceived = _clamp(true_value + noise)
        tone = "neutral" if rumor else self._tone(values, needs)
        intent = "honest"
        motive = ""
        shift = 0
        if not rumor:
            intent, motive, shift = self._intent(
                source, values, needs, tone, recipient_id
            )
        band = self._frame_band(self._band(perceived), tone)
        if shift:
            band = self._shift_band(band, shift)
        reported_band = band
        label = self.asset_labels.get(asset, asset)
        source_name = (
            self.rumor_source_label
            if rumor
            else str(getattr(source, "name", "") or "Источник")
        )
        source_post = (
            ""
            if rumor
            else str(
                getattr(source, "campaign_post", "")
                or getattr(source, "campaign_post_id", "")
                or ""
            )
        )
        channel = "rumor" if rumor else "report"
        values_map = {
            "asset": asset,
            "asset_label": label,
            "band": reported_band["label"],
            "truth_band": true_band["label"],
            "source": source_name,
            "post": source_post,
            "channel": str(self.channels.get(channel) or channel),
            "confidence": self._confidence_label(confidence),
        }
        if rumor:
            template = (
                str(self.rng.choice(self.rumor_templates))
                if self.rumor_templates
                else "Говорят, будто {asset_label} — «{band}»."
            )
        else:
            template = self._template(tone)
        text = _render(template, values_map)
        title_key = (
            self.rumor_titles.get(channel) if rumor else None
        )
        title = _render(
            title_key
            or self.titles.get(channel)
            or "Доклад: {asset_label}",
            values_map,
        )
        promise_line = ""
        promise_overdue = False
        if not rumor:
            promise_line, promise_overdue = self._promise_context(
                faction, source, asset, true_value
            )
        asks_promise = False
        request_line = ""
        if not rumor and self.promise_enabled:
            tones = {
                str(item)
                for item in _as_list(
                    self.promise_config.get("tones")
                )
            }
            if tone in tones:
                asks_promise = (
                    self.rng.random()
                    < _number(self.promise_config.get("chance"), 0.3)
                )
            if asks_promise:
                request_line = _render(
                    self.promise_config.get("request_text"),
                    {
                        "source": source_name,
                        "asset": asset,
                        "asset_label": label,
                    },
                )
        self._seq += 1
        return {
            "id": "report-%d" % self._seq,
            "side": str(faction.side),
            "recipient_id": recipient_id,
            "source_id": source_id,
            "source_name": source_name,
            "source_post": source_post,
            "anonymous": rumor,
            "channel": channel,
            "channel_label": str(
                self.channels.get(channel) or channel
            ),
            "asset": asset,
            "asset_label": label,
            "title": title,
            "text": text,
            "band": reported_band["id"],
            "band_label": reported_band["label"],
            "true_band": true_band["id"],
            "true_band_label": true_band["label"],
            "perceived": round(perceived, 6),
            "true_value": round(true_value, 6),
            "confidence": round(confidence, 6),
            "confidence_label": self._confidence_label(confidence),
            "tone": tone,
            "intent": intent,
            "motive": motive,
            "manipulation": bool(shift),
            "distortion": int(shift),
            "chain_line": chain_line,
            "promise_line": promise_line,
            "promise_overdue": bool(promise_overdue),
            "asks_promise": bool(asks_promise),
            "request_line": request_line,
            "verify_cost": self.verify_cost,
            "status": "pending",
            "created": round(
                _number(getattr(self.campaign, "elapsed", 0.0)), 6
            ),
            "turn": int(_number(getattr(self.campaign, "turn", 0), 0)),
            "choices": [dict(item) for item in self.choices],
            "resolved": None,
        }

    def _template(self, tone):
        pool = _as_list(self.templates.get(tone))
        if not pool:
            pool = _as_list(self.templates.get("neutral"))
        if not pool:
            pool = [
                "Докладываю: {asset_label} — «{band}».",
            ]
        return str(self.rng.choice(pool))

    def _confidence(self, values, needs):
        cfg = self.confidence_cfg
        score = (
            _number(cfg.get("base"), 0.45)
            + _number(values.get("discipline"), 0.5)
            * _number(cfg.get("discipline"), 0.35)
            + _number(values.get("curiosity"), 0.5)
            * _number(cfg.get("curiosity"), 0.15)
            + _number(needs.get("fear"), 0.5)
            * _number(cfg.get("fear"), -0.15)
        )
        return _clamp(
            score,
            _number(cfg.get("min"), 0.2),
            _number(cfg.get("max"), 0.95),
        )

    def _tone(self, values, needs):
        cfg = self.tone_cfg
        loyalty = _number(values.get("loyalty"), 0.5)
        ambition = _number(values.get("ambition"), 0.5)
        fear = _number(needs.get("fear"), 0.5)
        high = _number(cfg.get("loyalty_high"), 0.62)
        low = _number(cfg.get("loyalty_low"), 0.42)
        if loyalty >= high and fear >= _number(cfg.get("fear"), 0.5):
            return "loyal_fearful"
        if loyalty >= high:
            return "loyal"
        if loyalty < low:
            return "hostile"
        if ambition >= _number(cfg.get("ambition"), 0.55):
            return "ambitious"
        return "neutral"

    def _band(self, value):
        value = _clamp(value)
        for band in self.bands:
            if value <= band["max"] + 1e-9:
                return band
        return self.bands[-1]

    def _frame_band(self, band, tone):
        index = int(band.get("index", 0))
        last = len(self.bands) - 1
        if tone == "loyal" and index <= 1:
            index = min(last, index + 1)
        elif tone in ("loyal_fearful", "ambitious", "hostile"):
            if index >= 1:
                index = max(0, index - 1)
        return self.bands[index]

    def _confidence_label(self, value):
        for item in self.confidence_labels:
            data = _as_mapping(item)
            if value >= _number(data.get("min"), 0.0):
                return str(data.get("label") or "")
        return ""
