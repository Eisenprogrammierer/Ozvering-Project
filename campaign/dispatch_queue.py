"""Очередь, журнал, обрезка и снимок диспетчера докладов."""

from __future__ import annotations

import copy
from typing import Mapping

from .dispatch_support import (
    _as_list,
    _as_mapping,
    _nested_tuple,
    _number,
)


class QueueMixin:

    def _expire_oldest(self, side=None):
        candidates = [
            report
            for report in self.reports
            if str(report.get("status") or "") == "pending"
            and (
                not side
                or str(report.get("side") or "") == str(side)
            )
        ]
        if not candidates:
            return None
        visible = [
            report for report in candidates if not self._is_shadowed(report)
        ]
        report = (visible or candidates)[0]
        self._expire_report(report)
        partner_id = str(report.get("contradicts") or "")
        partner = self.report(partner_id) if partner_id else None
        if (
            partner is not None
            and str(partner.get("status") or "") == "pending"
            and partner is not report
        ):
            self._expire_report(partner)
        return report

    def _expire_report(self, report):
        if str(report.get("status") or "") != "pending":
            return
        report["status"] = "expired"
        report["resolved"] = {
            "choice": None,
            "correct": None,
            "text": "Доклад устарел и был снят с очереди.",
            "changes": {},
            "at": round(
                _number(getattr(self.campaign, "elapsed", 0.0)), 6
            ),
            "turn": int(
                _number(getattr(self.campaign, "turn", 0), 0)
            ),
        }
        sync = getattr(self.campaign, "_sync_report_event", None)
        if callable(sync):
            sync(report)
        self._log_expired(report)

    def _trim(self):
        while len(self.reports) > self.history_limit:
            index = next(
                (
                    index
                    for index, report in enumerate(self.reports)
                    if str(report.get("status") or "") != "pending"
                ),
                None,
            )
            if index is None:
                index = 0
            removed = self.reports.pop(index)
            if str(removed.get("status") or "") == "pending":
                removed["status"] = "expired"
                sync = getattr(self.campaign, "_sync_report_event", None)
                if callable(sync):
                    sync(removed)
                self._log_expired(removed)

    def _record_story(self, report):
        record = getattr(self.campaign, "_record_report_event", None)
        if callable(record):
            record(report)

    def _log(self, event, **fields):
        stats = getattr(self.campaign, "stats", None)
        if stats is None:
            return
        stats.log(event, **fields)

    def _log_issued(self, report):
        self._log(
            "report_issued",
            report_id=report.get("id"),
            side=report.get("side"),
            source_id=report.get("source_id"),
            source_name=report.get("source_name"),
            source_post=report.get("source_post"),
            asset=report.get("asset"),
            channel=report.get("channel"),
            anonymous=report.get("anonymous"),
            follow_up=report.get("follow_up"),
            derived_from=report.get("derived_from"),
            contradiction=report.get("contradiction"),
            contradicts=report.get("contradicts"),
            counter_source=report.get("counter_source"),
            true_value=report.get("true_value"),
            perceived=report.get("perceived"),
            confidence=report.get("confidence"),
            band=report.get("band"),
            true_band=report.get("true_band"),
            tone=report.get("tone"),
            intent=report.get("intent"),
            motive=report.get("motive"),
            manipulation=report.get("manipulation"),
            recipient_id=report.get("recipient_id"),
            text=report.get("text"),
        )

    def _log_choice(self, report, choice, correct, changes, text):
        self._log(
            "report_choice",
            report_id=report.get("id"),
            side=report.get("side"),
            source_id=report.get("source_id"),
            source_name=report.get("source_name"),
            asset=report.get("asset"),
            channel=report.get("channel"),
            choice=choice,
            correct=correct,
            cost=(report.get("resolved") or {}).get("cost"),
            revealed_truth=(
                report.get("resolved") or {}
            ).get("revealed_truth"),
            follow_up=(report.get("resolved") or {}).get("follow_up"),
            contradicts=(report.get("resolved") or {}).get("contradicts"),
            resolved_by=(report.get("resolved") or {}).get("resolved_by"),
            decided_by=(report.get("resolved") or {}).get("decided_by"),
            manipulation=(report.get("resolved") or {}).get(
                "manipulation"
            ),
            motive_revealed=(report.get("resolved") or {}).get(
                "motive_revealed"
            ),
            truth_band=report.get("true_band"),
            changes=changes,
            text=text,
        )

    def _log_expired(self, report):
        self._log(
            "report_expired",
            report_id=report.get("id"),
            side=report.get("side"),
            source_id=report.get("source_id"),
            asset=report.get("asset"),
        )

    def snapshot(self):
        return {
            "progress": round(self._progress, 6),
            "seq": int(self._seq),
            "asset_index": int(self._asset_index),
            "rng_state": _nested_tuple(self.rng.getstate()),
            "spread_rng_state": _nested_tuple(
                self.spread_rng.getstate()
            ),
            "news_progress": round(self._news_progress, 6),
            "news_seq": int(self._news_seq),
            "news_index": int(self._news_index),
            "news_rng_state": _nested_tuple(
                self.news_rng.getstate()
            ),
            "retaliation_rng_state": _nested_tuple(
                self.retaliation_rng.getstate()
            ),
            "reports": [
                copy.deepcopy(report)
                for report in self.reports[-self.history_limit:]
            ],
            "intercepts": [
                copy.deepcopy(item)
                for item in self.intercepts[-self.history_limit:]
            ],
            "intercept_seq": int(self._intercept_seq),
            "memory": copy.deepcopy(self.memory),
        }

    def load(self, data):
        data = _as_mapping(data)
        if not data:
            return
        self._progress = max(0.0, _number(data.get("progress"), 0.0))
        self._seq = max(0, int(_number(data.get("seq"), 0)))
        self._asset_index = max(
            0, int(_number(data.get("asset_index"), 0))
        )
        state = data.get("rng_state")
        if state:
            try:
                self.rng.setstate(_nested_tuple(state))
            except (TypeError, ValueError):
                pass
        spread_state = data.get("spread_rng_state")
        if spread_state:
            try:
                self.spread_rng.setstate(_nested_tuple(spread_state))
            except (TypeError, ValueError):
                pass
        self._news_progress = max(
            0.0, _number(data.get("news_progress"), 0.0)
        )
        self._news_seq = max(0, int(_number(data.get("news_seq"), 0)))
        self._news_index = max(
            0, int(_number(data.get("news_index"), 0))
        )
        news_state = data.get("news_rng_state")
        if news_state:
            try:
                self.news_rng.setstate(_nested_tuple(news_state))
            except (TypeError, ValueError):
                pass
        retaliation_state = data.get("retaliation_rng_state")
        if retaliation_state:
            try:
                self.retaliation_rng.setstate(
                    _nested_tuple(retaliation_state)
                )
            except (TypeError, ValueError):
                pass
        self.reports = [
            dict(item)
            for item in _as_list(data.get("reports"))
            if isinstance(item, Mapping)
        ]
        self.intercepts = [
            dict(item)
            for item in _as_list(data.get("intercepts"))
            if isinstance(item, Mapping)
        ]
        self._intercept_seq = max(
            0, int(_number(data.get("intercept_seq"), 0))
        )
        memory = {}
        for key, item in _as_mapping(data.get("memory")).items():
            base = self._new_memory()
            base.update(
                {
                    str(name): value
                    for name, value in _as_mapping(item).items()
                }
            )
            memory[str(key)] = base
        self.memory = memory
