"""Доклады источников: ролевой слой событий кампании.

Источник — не всеведущий рассказчик, а персонаж с BDI. Он видит актив с
ошибкой, зависящей от дисциплины, любопытства и страха, выбирает тон по
лояльности и амбиции и присылает доклад. Игрок может довериться,
проверить или проигнорировать сообщение.

Инвариант: доклад **не меняет активы**. Выбор игрока живёт в морали,
потребностях, убеждениях и отношениях источника. Следующий доклад
почувствует это.

Данные приходят из секции ``dispatch`` базовых настроек кампании:

    {"dispatch": {"enabled": true, "interval_seconds": 172800.0, ...}}

Очередь докладов входит в снимок кампании и переживает сохранение.
"""

from __future__ import annotations

import copy
import random
from typing import Dict, Iterable, List, Mapping, Optional

from .relations import RELATION_AXES


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if result != result or result in (float("inf"), float("-inf")):
        return float(default)
    return result


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _number(value, low)))


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _as_list(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _nested_tuple(value):
    if isinstance(value, (list, tuple)):
        return tuple(_nested_tuple(item) for item in value)
    return value


class _Fields(dict):
    """Словарь для ``format_map``: пропуск остаётся видимым, а не падает."""

    def __missing__(self, key):
        return "{%s}" % key


def _render(template, values):
    try:
        return str(template).format_map(_Fields(values))
    except (KeyError, IndexError, ValueError, AttributeError):
        return str(template)


def _alive(character):
    if character is None:
        return False
    return not bool(
        getattr(
            character,
            "is_dead",
            getattr(character, "dead", False),
        )
    )


class ReportDispatcher:
    """Очередь докладов и реакции источников на выбор игрока."""

    def __init__(self, campaign, config=None):
        self.campaign = campaign
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", True))
        self.interval = max(
            60.0, _number(self.config.get("interval_seconds"), 172800.0)
        )
        self.max_pending = max(
            1, int(_number(self.config.get("max_pending"), 8))
        )
        self.history_limit = max(
            2, int(_number(self.config.get("history_limit"), 32))
        )
        self.assets = [
            str(item)
            for item in _as_list(self.config.get("assets"))
            if str(item).strip()
        ]
        self.source_by_asset = {
            str(key): [str(item) for item in _as_list(value)]
            for key, value in _as_mapping(
                self.config.get("source_by_asset")
            ).items()
        }
        self.asset_labels = {
            str(key): str(value)
            for key, value in _as_mapping(
                self.config.get("asset_labels")
            ).items()
        }
        self.bands = self._parse_bands(self.config.get("bands"))
        self.confidence_cfg = _as_mapping(self.config.get("confidence"))
        self.tone_cfg = _as_mapping(self.config.get("tone"))
        self.titles = _as_mapping(self.config.get("titles"))
        self.channels = _as_mapping(self.config.get("channels"))
        self.templates = _as_mapping(self.config.get("templates"))
        self.choices = self._parse_choices(self.config.get("choices"))
        self.effects = _as_mapping(self.config.get("effects"))
        self.result_texts = _as_mapping(self.config.get("result_texts"))
        self.confidence_labels = _as_list(
            self.config.get("confidence_labels")
        )
        self.verify_tolerance = max(
            0.0, _number(self.config.get("verify_tolerance"), 0.12)
        )
        self._progress = 0.0
        self._seq = 0
        self._asset_index = 0
        self.reports: List[dict] = []
        self.rng = random.Random(
            int(_number(getattr(campaign, "seed", 0), 0)) * 7919 + 41
        )

    @staticmethod
    def _parse_bands(raw):
        bands = []
        for index, item in enumerate(_as_list(raw)):
            data = _as_mapping(item)
            if not data:
                continue
            bands.append(
                {
                    "index": index,
                    "id": str(data.get("id") or "band-%d" % index),
                    "max": _clamp(data.get("max"), 0.0, 1.0),
                    "label": str(data.get("label") or "неизвестно"),
                }
            )
        bands.sort(key=lambda item: (item["max"], item["index"]))
        for index, item in enumerate(bands):
            item["index"] = index
        if not bands:
            bands = [
                {
                    "index": 0,
                    "id": "unknown",
                    "max": 1.0,
                    "label": "неизвестно",
                }
            ]
        return bands

    @staticmethod
    def _parse_choices(raw):
        choices = []
        for item in _as_list(raw):
            data = _as_mapping(item)
            if not data:
                continue
            choice_id = str(data.get("id") or "").strip()
            if not choice_id:
                continue
            choices.append(
                {
                    "id": choice_id,
                    "label": str(data.get("label") or choice_id),
                }
            )
        if not choices:
            choices = [
                {"id": "trust", "label": "Довериться"},
                {"id": "verify", "label": "Проверить"},
                {"id": "ignore", "label": "Игнорировать"},
            ]
        return choices

    # --- очередь ----------------------------------------------------
    def tick(self, seconds):
        """Накопить время и выпустить доклады по интервалу."""
        if not self.enabled or self.campaign.finished:
            return []
        self._progress += max(0.0, _number(seconds))
        spawned = []
        while (
            self.interval > 0.0
            and self._progress + 1e-9 >= self.interval
            and not self.campaign.finished
        ):
            self._progress -= self.interval
            report = self.issue()
            if report is not None:
                spawned.append(report)
        return spawned

    def pending(self, side=None):
        side = str(side or "")
        return [
            report
            for report in self.reports
            if str(report.get("status") or "") == "pending"
            and (not side or str(report.get("side") or "") == side)
        ]

    def report(self, report_id):
        key = str(report_id or "")
        for report in self.reports:
            if str(report.get("id") or "") == key:
                return report
        return None

    # --- выпуск -----------------------------------------------------
    def issue(self, faction=None):
        """Создать один доклад от подходящего источника."""
        if not self.enabled:
            return None
        faction = faction or self.campaign.faction(
            self.campaign.player_side
        )
        if faction is None or not self.assets:
            return None
        if len(self.pending(faction.side)) >= self.max_pending:
            self._expire_oldest(faction.side)
        asset = self._next_asset()
        source = self._source(faction, asset)
        if source is None:
            return None
        report = self._build_report(faction, source, asset)
        if report is None:
            return None
        self.reports.append(report)
        self._trim()
        self._record_story(report)
        self._log_issued(report)
        return report

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
        for post_id in self.source_by_asset.get(asset, ()):
            for character in characters:
                if (
                    str(
                        getattr(character, "campaign_post_id", "")
                        or ""
                    )
                    == post_id
                ):
                    return character
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

    def _build_report(self, faction, source, asset):
        asset = str(asset)
        true_value = _clamp(faction.asset(asset))
        true_band = self._band(true_value)
        values = getattr(
            getattr(source, "personality", None), "values", {}
        ) or {}
        needs = getattr(source, "needs", {}) or {}
        confidence = self._confidence(values, needs)
        span = (1.0 - confidence) * _number(
            self.confidence_cfg.get("noise"), 0.35
        )
        noise = self.rng.uniform(-span, span) if span else 0.0
        perceived = _clamp(true_value + noise)
        tone = self._tone(values, needs)
        reported_band = self._frame_band(self._band(perceived), tone)
        label = self.asset_labels.get(asset, asset)
        source_name = str(getattr(source, "name", "") or "Источник")
        source_post = str(
            getattr(source, "campaign_post", "")
            or getattr(source, "campaign_post_id", "")
            or ""
        )
        channel = "report"
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
        template = self._template(tone)
        text = _render(template, values_map)
        title = _render(
            self.titles.get(channel) or "Доклад: {asset_label}",
            values_map,
        )
        self._seq += 1
        return {
            "id": "report-%d" % self._seq,
            "side": str(faction.side),
            "source_id": str(
                getattr(source, "campaign_id", "") or ""
            ),
            "source_name": source_name,
            "source_post": source_post,
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

    # --- выбор игрока ----------------------------------------------
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
        effect_key = choice_id
        correct = None
        if choice_id == "verify":
            error = abs(
                _number(report.get("perceived"))
                - _number(report.get("true_value"))
            )
            correct = error <= self.verify_tolerance + 1e-9
            effect_key = "verify_right" if correct else "verify_wrong"
        effect = _as_mapping(self.effects.get(effect_key))
        changes = self._apply_effects(
            faction, source, report, effect, effect_key
        )
        values_map = {
            "source": report.get("source_name") or "Источник",
            "asset": report.get("asset") or "",
            "asset_label": report.get("asset_label") or "",
            "band": report.get("band_label") or "",
            "truth_band": report.get("true_band_label") or "",
        }
        text = _render(
            self.result_texts.get(effect_key)
            or self.result_texts.get(choice_id)
            or "Решение принято.",
            values_map,
        )
        report["status"] = "resolved"
        report["choice"] = choice_id
        report["resolved"] = {
            "choice": choice_id,
            "correct": correct,
            "text": text,
            "changes": changes,
            "at": round(
                _number(getattr(self.campaign, "elapsed", 0.0)), 6
            ),
            "turn": int(_number(getattr(self.campaign, "turn", 0), 0)),
        }
        sync = getattr(self.campaign, "_sync_report_event", None)
        if callable(sync):
            sync(report)
        self._log_choice(report, choice_id, correct, changes, text)
        return {
            "ok": True,
            "report": report,
            "choice": choice_id,
            "correct": correct,
            "truth_band": report.get("true_band"),
            "truth_band_label": report.get("true_band_label"),
            "text": text,
            "changes": changes,
        }

    def _character(self, character_id):
        key = str(character_id or "")
        if not key:
            return None
        for faction in self.campaign.factions.values():
            for character in getattr(faction, "characters", ()) or ():
                if str(getattr(character, "campaign_id", "")) == key:
                    return character
        return None

    def _apply_effects(self, faction, source, report, effect, effect_key):
        changes = {}
        if source is not None:
            morale_before = _number(getattr(source, "morale", 0.0))
            morale = _number(effect.get("morale"))
            if morale:
                source.morale = max(
                    0.0,
                    min(100.0, morale_before + morale),
                )
                changes["morale"] = round(
                    source.morale - morale_before, 6
                )
            needs = _as_mapping(effect.get("needs"))
            for need, delta in needs.items():
                if need not in getattr(source, "needs", {}):
                    continue
                before = _number(source.needs.get(need))
                source.needs[need] = _clamp(before + _number(delta))
                changes.setdefault("needs", {})[str(need)] = round(
                    source.needs[need] - before, 6
                )
            predicate = {
                "trust": "trusts",
                "ignore": "ignored",
                "verify_right": "verified",
                "verify_wrong": "doubts",
            }.get(effect_key)
            if predicate:
                target = (
                    report.get("asset")
                    if effect_key.startswith("verify_")
                    else report.get("source_id")
                )
                try:
                    source.believe("player", predicate, str(target or ""))
                except Exception:
                    pass
                changes["belief"] = {
                    "subject": "player",
                    "predicate": predicate,
                    "object": str(target or ""),
                }
        relations = getattr(self.campaign, "relations", None)
        if relations is not None and faction is not None:
            player = str(getattr(faction, "id", "") or "")
            other = str(report.get("source_id") or "")
            for prefix, start, end in (
                ("player_", player, other),
                ("source_", other, player),
            ):
                axes = {}
                for axis in RELATION_AXES:
                    key = prefix + axis
                    if key in effect:
                        axes[axis] = _number(effect.get(key))
                if axes:
                    applied = relations.add(start, end, axes, 1.0)
                    changes.setdefault("relations", []).append(
                        {
                            "source": start,
                            "target": end,
                            "axes": applied,
                        }
                    )
        return changes

    # --- история и путь --------------------------------------------
    def _expire_oldest(self, side=None):
        for report in self.reports:
            if str(report.get("status") or "") != "pending":
                continue
            if side and str(report.get("side") or "") != str(side):
                continue
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
            return report
        return None

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
            true_value=report.get("true_value"),
            perceived=report.get("perceived"),
            confidence=report.get("confidence"),
            band=report.get("band"),
            true_band=report.get("true_band"),
            tone=report.get("tone"),
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
            choice=choice,
            correct=correct,
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

    # --- снимок -----------------------------------------------------
    def snapshot(self):
        return {
            "progress": round(self._progress, 6),
            "seq": int(self._seq),
            "asset_index": int(self._asset_index),
            "rng_state": _nested_tuple(self.rng.getstate()),
            "reports": [
                copy.deepcopy(report)
                for report in self.reports[-self.history_limit:]
            ],
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
        self.reports = [
            dict(item)
            for item in _as_list(data.get("reports"))
            if isinstance(item, Mapping)
        ]


__all__ = ["ReportDispatcher"]
