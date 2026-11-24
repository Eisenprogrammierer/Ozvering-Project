"""Очередь докладов, такт и разбор настроек диспетчера."""

from __future__ import annotations

import random
from typing import Dict, List

from .dispatch_support import (
    AI_DEFAULTS,
    BRIEFING_DEFAULTS,
    DISTORTION_DEFAULTS,
    INTERCEPTION_DEFAULTS,
    MEMORY_DEFAULTS,
    NEWS_DEFAULTS,
    PROMISE_DEFAULTS,
    THREAT_DEFAULTS,
    _as_list,
    _as_mapping,
    _clamp,
    _merged,
    _number,
)


class DispatcherCore:

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
        self.verify_cost = max(
            0, int(_number(self.config.get("verify_cost_actions"), 1))
        )
        rumor = _as_mapping(self.config.get("rumor"))
        self.rumor_enabled = bool(rumor.get("enabled", False))
        self.rumor_chance = _clamp(rumor.get("chance"), 0.0, 1.0)
        self.rumor_confidence_scale = _clamp(
            rumor.get("confidence_scale"), 0.0, 1.0
        )
        self.rumor_noise_scale = max(
            0.0, _number(rumor.get("noise_scale"), 1.5)
        )
        self.rumor_source_label = str(
            rumor.get("source_label") or "Слух"
        )
        self.rumor_titles = _as_mapping(rumor.get("titles"))
        self.rumor_templates = _as_list(rumor.get("templates"))
        self.rumor_result_texts = _as_mapping(
            rumor.get("result_texts")
        )
        self.rumor_effects = _as_mapping(rumor.get("effects"))
        self.rumor_follow_up_text = str(
            rumor.get("follow_up_text")
            or "Проверка слуха: {asset_label} — «{band}». "
            "Твёрдых доказательств по-прежнему нет."
        )
        self.rumor_follow_up_title = str(
            rumor.get("follow_up_title") or "Проверка слуха: {asset_label}"
        )
        contradiction = _as_mapping(self.config.get("contradiction"))
        self.contradiction_enabled = bool(
            contradiction.get("enabled", False)
        )
        self.contradiction_chance = _clamp(
            contradiction.get("chance"), 0.0, 1.0
        )
        self.contradiction_title = str(
            contradiction.get("title") or "Разноречие: {asset_label}"
        )
        self.contradiction_text = str(
            contradiction.get("text")
            or "{source} настаивает: {asset_label} — «{band}». "
            "{counter_source} ранее доложил: «{counter_band}». "
            "Кому верить?"
        )
        self.contradiction_counter_line = str(
            contradiction.get("counter_line")
            or "Ранее {counter_source}: «{counter_band}»"
        )
        self.contradiction_counter_line_late = str(
            contradiction.get("counter_line_late")
            or "Позже {counter_source}: «{counter_band}»"
        )
        self.contradiction_result_texts = _as_mapping(
            contradiction.get("result_texts")
        )
        self.contradiction_effects = _as_mapping(
            contradiction.get("effects")
        )
        self.distortion = _merged(
            DISTORTION_DEFAULTS, self.config.get("distortion")
        )
        self.distortion_enabled = bool(
            self.distortion.get("enabled", True)
        )
        self.memory_config = _merged(
            MEMORY_DEFAULTS, self.config.get("memory")
        )
        self.memory_enabled = bool(
            self.memory_config.get("enabled", True)
        )
        self.ai_config = _merged(
            AI_DEFAULTS, self.config.get("ai")
        )
        self.ai_enabled = bool(self.ai_config.get("enabled", True))
        self.promise_config = _merged(
            PROMISE_DEFAULTS, self.config.get("promise")
        )
        self.promise_enabled = bool(
            self.promise_config.get("enabled", True)
        )
        self.briefing_config = _merged(
            BRIEFING_DEFAULTS, self.config.get("briefing")
        )
        self.threat_config = _merged(
            THREAT_DEFAULTS, self.config.get("threat")
        )
        self.threat_enabled = bool(
            self.threat_config.get("enabled", True)
        )
        self.news_config = _merged(
            NEWS_DEFAULTS, self.config.get("news")
        )
        self.news_enabled = bool(
            self.news_config.get("enabled", True)
        )
        self.interception_config = _merged(
            INTERCEPTION_DEFAULTS,
            self.config.get("interception"),
        )
        self.interception_enabled = bool(
            self.interception_config.get("enabled", True)
        )
        self._progress = 0.0
        self._seq = 0
        self._asset_index = 0
        self._intercept_seq = 0
        self.reports: List[dict] = []
        self.intercepts: List[dict] = []
        self.memory: Dict[str, dict] = {}
        self.rng = random.Random(
            int(_number(getattr(campaign, "seed", 0), 0)) * 7919 + 41
        )
        self.spread_rng = random.Random(
            int(_number(getattr(campaign, "seed", 0), 0)) * 7919 + 97
        )
        self.news_rng = random.Random(
            int(_number(getattr(campaign, "seed", 0), 0)) * 7919 + 131
        )
        self.retaliation_rng = random.Random(
            int(_number(getattr(campaign, "seed", 0), 0)) * 7919 + 173
        )
        self._news_progress = 0.0
        self._news_seq = 0
        self._news_index = 0

    def tick(self, seconds):
        """Накопить время и выпустить доклады по интервалу.

        Доклады получает не только игрок: лидер каждой живой фракции
        слышит своих источников. Решения чужих фракций принимает их
        лидер по своему BDI, поэтому очередь решений игрока ими не
        забивается, а на действия фракции влияют его убеждения и
        потребности.
        """
        if not self.enabled or self.campaign.finished:
            return []
        self._expire_intercepts()
        self._progress += max(0.0, _number(seconds))
        spawned = []
        while (
            self.interval > 0.0
            and self._progress + 1e-9 >= self.interval
            and not self.campaign.finished
        ):
            self._progress -= self.interval
            for faction in self._factions():
                if self.campaign.finished:
                    break
                report = self.issue(faction)
                if report is None:
                    continue
                spawned.append(report)
                if (
                    str(report.get("side") or "")
                    != str(self.campaign.player_side)
                    and self.ai_enabled
                ):
                    self.auto_resolve(report)
        self._news_tick(max(0.0, _number(seconds)))
        return spawned

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
