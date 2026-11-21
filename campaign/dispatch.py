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

DISTORTION_DEFAULTS = {
    "enabled": True,
    "base": 0.06,
    "ambition": 0.22,
    "disloyalty": 0.18,
    "fear": 0.08,
    "grievance": 0.12,
    "shift": 1,
    "strong_shift": 2,
    "strong_at": 0.7,
    "motive_reveal": 0.75,
    "motives": {
        "ambitious": "полномочия",
        "hostile": "подрыв",
        "loyal_fearful": "страх",
        "loyal": "оправдание",
        "neutral": "выгода",
    },
}

AI_DEFAULTS = {
    "enabled": True,
    "trust_base": 0.35,
    "trust_relation": 0.45,
    "trust_loyalty": 0.20,
    "trust_history": 0.25,
    "trust_fear": -0.30,
    "verify_base": 0.10,
    "verify_anxiety": 0.35,
    "verify_discipline": 0.30,
    "verify_distrust": 0.30,
    "verify_history": 0.20,
    "ignore_base": 0.10,
    "ignore_fear": 0.35,
    "ignore_distrust": 0.25,
    "ignore_loyalty": 0.20,
    "noise": 0.0,
}

PROMISE_DEFAULTS = {
    "enabled": True,
    "chance": 0.30,
    "kind": "favor",
    "amount": 1.0,
    "due_days": 5,
    "tones": ["ambitious", "loyal_fearful", "neutral"],
    "request_text": "{source} просит не оставлять это без ответа.",
    "line": "Вы обещали {source} поддержку по «{asset_label}».",
    "overdue_line": (
        "Обещание по «{asset_label}» просрочено. "
        "{source} помнит об этом."
    ),
    "fulfilled_line": (
        "Обещание по «{asset_label}» исполнено. "
        "{source} отметил это."
    ),
}

MEMORY_DEFAULTS = {
    "enabled": True,
    "confidence_step": 0.04,
    "lines": {
        "trusted": (
            "В прошлый раз вы доверились мне насчёт {last_asset_label}."
        ),
        "ignored": (
            "В прошлый раз вы отложили мой доклад о {last_asset_label}."
        ),
        "verified_right": (
            "Мой прошлый доклад о {last_asset_label} подтвердился."
        ),
        "verified_wrong": (
            "В прошлый раз я ошибся с {last_asset_label} "
            "и стал осторожнее."
        ),
        "lied": (
            "В прошлый раз вы раскрыли мою подтасовку "
            "насчёт {last_asset_label}."
        ),
        "expired": (
            "Мой прошлый доклад о {last_asset_label} остался без ответа."
        ),
    },
}

THREAT_DEFAULTS = {
    "enabled": True,
    "bands": ["critical", "low"],
    "predicate": "sees_as_threat",
    "strength": 0.8,
    "confidence": 0.7,
}


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


def _merged(defaults, raw):
    """Слить секцию конфига с умолчаниями, не теряя вложенные словари."""
    result = {}
    for key, value in defaults.items():
        result[key] = dict(value) if isinstance(value, Mapping) else value
    for key, value in _as_mapping(raw).items():
        if isinstance(value, Mapping) and isinstance(
            result.get(key), Mapping
        ):
            merged = dict(result[key])
            merged.update(value)
            result[key] = merged
        else:
            result[key] = value
    return result


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
        self.threat_config = _merged(
            THREAT_DEFAULTS, self.config.get("threat")
        )
        self.threat_enabled = bool(
            self.threat_config.get("enabled", True)
        )
        self.news_config = _merged(
            {
                "enabled": True,
                "delay_seconds": 21600.0,
                "title": "Вести: {faction}",
                "texts": {},
            },
            self.config.get("news"),
        )
        self.news_enabled = bool(
            self.news_config.get("enabled", True)
        )
        self._progress = 0.0
        self._seq = 0
        self._asset_index = 0
        self.reports: List[dict] = []
        self.memory: Dict[str, dict] = {}
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
        """Накопить время и выпустить доклады по интервалу.

        Доклады получает не только игрок: лидер каждой живой фракции
        слышит своих источников. Решения чужих фракций принимает их
        лидер по своему BDI, поэтому очередь решений игрока ими не
        забивается, а на действия фракции влияют его убеждения и
        потребности.
        """
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
        return spawned

    def pending(self, side=None):
        return self._pending_reports(side)

    def briefing(self, side=None):
        """Качественная сводка начальника штаба, без точных чисел.

        Игроку нужен смысл, а не таблица: где тонко, что требует
        решения, чего боится лидер и какие обещания ещё висят. Числа
        остаются в аудите и снимке.
        """
        side = str(side or self.campaign.player_side)
        faction = self.campaign.faction(side)
        result = {"chief": "", "lines": []}
        if faction is None:
            return result
        chief = None
        for character in getattr(faction, "characters", ()) or ():
            if str(
                getattr(character, "campaign_post_id", "") or ""
            ) == "chief_of_staff":
                chief = character
                break
        if chief is None:
            characters = list(getattr(faction, "characters", ()) or ())
            chief = characters[1] if len(characters) > 1 else (
                characters[0] if characters else None
            )
        result["chief"] = str(
            getattr(chief, "name", "") or "Начальник штаба"
        )
        lines = []
        pending = self.pending(side)
        if pending:
            lines.append("Ждут решения доклады источников.")
        if self.assets:
            weakest = min(
                (str(asset) for asset in self.assets),
                key=lambda key: faction.asset(key),
            )
            band = self._band(faction.asset(weakest))
            label = self.asset_labels.get(weakest, weakest)
            lines.append("%s — «%s»." % (label, band["label"]))
        leader = self._leader_for(faction)
        if leader is not None:
            needs = getattr(leader, "needs", {}) or {}
            config = getattr(
                getattr(leader, "bdi", None), "config", None
            )
            names = getattr(config, "needs", {}) or {}
            heavy = []
            for key, value in needs.items():
                meta = names.get(key)
                threshold = _number(
                    getattr(meta, "threshold", 0.65), 0.65
                )
                if _number(value) >= threshold:
                    heavy.append(
                        str(getattr(meta, "label", key) or key)
                    )
            if heavy:
                lines.append("Тяготит: %s." % ", ".join(heavy[:2]))
            else:
                lines.append("Лидер держится ровно.")
        obligations = getattr(self.campaign, "obligations", None)
        if obligations is not None and leader is not None:
            party = self._leader_key(faction, leader)
            active = [
                item
                for item in obligations.for_party(party)
                if item.active()
            ]
            if active:
                lines.append("Есть незакрытые обещания.")
        recent = self._recent_report_news(side)
        if recent:
            lines.append(recent)
        result["lines"] = lines[:4]
        return result

    def _recent_report_news(self, side):
        for report in reversed(self.reports):
            if str(report.get("side") or "") != str(side):
                continue
            if str(report.get("status") or "") != "resolved":
                continue
            choice = str(report.get("choice") or "")
            label = str(report.get("asset_label") or "")
            if choice == "verify":
                return "Проверка по «%s» дала ответ." % label
            if choice == "ignore":
                return "Доклад о «%s» остался без ответа." % label
            return "Источник по «%s» получил поддержку." % label
        return ""

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

    def report(self, report_id):
        key = str(report_id or "")
        for report in self.reports:
            if str(report.get("id") or "") == key:
                return report
        return None

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

    # --- решения чужих фракций -------------------------------------
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
        return result

    def _ai_choice(self, report, faction, leader):
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
        memory = self.memory.get(str(report.get("source_id") or "")) or {}
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
        return max(scores, key=lambda key: (scores[key], key))

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
        confidence = self._confidence(values, needs)
        chain_line, memory_delta = self._memory_line(source_id)
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
                source, values, needs, tone
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
            "recipient_id": str(
                getattr(leader, "campaign_id", "") or ""
            ),
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

    def _memory_line(self, source_id):
        """Строка-цепочка: источник помнит прошлый доклад и его исход."""
        if not self.memory_enabled:
            return "", 0.0
        memory = self.memory.get(str(source_id or "")) or {}
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

    def _intent(self, source, values, needs, tone):
        """Намеренная манипуляция отличается от честной ошибки.

        Честный источник искажает картину только собственной ошибкой.
        Амбициозный или нелояльный — сознательно сдвигает полосу в
        сторону, которая даёт ему рычаг: просит полномочия, топит
        соперника или прячет провал. Проверка может вскрыть мотив.
        """
        cfg = self.distortion
        if not self.distortion_enabled:
            return "honest", "", 0
        memory = self.memory.get(
            str(getattr(source, "campaign_id", "") or "")
        ) or {}
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
                memory = self.memory.setdefault(
                    source_id, self._new_memory()
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
        self._log("promise_overdue", **changes)

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

    def _remember(self, report, choice, correct, effect_key):
        """Записать исход в память источника для следующих докладов."""
        if not self.memory_enabled:
            return
        source_id = str(report.get("source_id") or "")
        if not source_id:
            return
        memory = self.memory.setdefault(source_id, self._new_memory())
        memory["reports"] = int(_number(memory.get("reports"), 0)) + 1
        if effect_key in ("trust", "rumor_trust"):
            memory["trusted"] = int(_number(memory.get("trusted"), 0)) + 1
            outcome = "trusted"
        elif effect_key == "verify_right":
            memory["verified_right"] = int(
                _number(memory.get("verified_right"), 0)
            ) + 1
            outcome = "verified_right"
        elif effect_key == "verify_lie":
            memory["lied"] = int(
                _number(memory.get("lied"), 0)
            ) + 1
            outcome = "lied"
        elif effect_key == "verify_wrong":
            memory["verified_wrong"] = int(
                _number(memory.get("verified_wrong"), 0)
            ) + 1
            outcome = "verified_wrong"
        elif effect_key in ("ignore", "rumor_ignore"):
            memory["ignored"] = int(_number(memory.get("ignored"), 0)) + 1
            outcome = "ignored"
        elif effect_key in ("rumor_verify",):
            memory["verified_wrong"] = int(
                _number(memory.get("verified_wrong"), 0)
            ) + 1
            outcome = "verified_wrong"
        else:
            outcome = str(choice or "")
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

    def _character(self, character_id):
        key = str(character_id or "")
        if not key:
            return None
        for faction in self.campaign.factions.values():
            for character in getattr(faction, "characters", ()) or ():
                if str(getattr(character, "campaign_id", "")) == key:
                    return character
        return None

    def _apply_effects(
        self,
        faction,
        source,
        report,
        effect,
        effect_key,
        belief_target=None,
        motive=None,
    ):
        changes = {}
        leader = self._leader_for(faction)
        leader_key = self._leader_key(faction, leader)
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
                "verify_lie": "suspects",
                "rumor_trust": "trusts",
                "rumor_ignore": "ignored",
                "rumor_verify": "doubts",
                "contradiction_trust": "distrusted",
                "contradiction_ignore": "ignored",
                "contradiction_verify_right": "verified",
                "contradiction_verify_wrong": "doubts",
            }.get(effect_key)
            if predicate:
                if belief_target is not None:
                    target = belief_target
                elif effect_key in (
                    "verify_right",
                    "verify_wrong",
                    "verify_lie",
                    "rumor_verify",
                ):
                    target = report.get("asset")
                else:
                    target = report.get("source_id")
                try:
                    source.believe(
                        leader_key, predicate, str(target or "")
                    )
                except Exception:
                    pass
                changes["belief"] = {
                    "subject": leader_key,
                    "predicate": predicate,
                    "object": str(target or ""),
                }
        if leader is not None and leader is not source:
            changes["leader"] = self._apply_leader_effects(
                faction,
                leader,
                leader_key,
                report,
                effect,
                effect_key,
                motive=motive,
            )
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

    def _apply_leader_effects(
        self,
        faction,
        leader,
        leader_key,
        report,
        effect,
        effect_key,
        motive=None,
    ):
        """Последствия доклада для того, кто принимает решение.

        Это и есть связь событий с действиями фракции: лидер получает
        потребности, мораль и убеждение об источнике или угрозе, а
        ``ai_model.beliefs.rules`` уже взвешивает по ним работы.
        """
        config = _as_mapping(effect.get("leader"))
        changes = {}
        morale_before = _number(getattr(leader, "morale", 0.0))
        morale = _number(config.get("morale"))
        if morale:
            leader.morale = max(
                0.0, min(100.0, morale_before + morale)
            )
            changes["morale"] = round(
                leader.morale - morale_before, 6
            )
        for need, delta in _as_mapping(config.get("needs")).items():
            if need not in getattr(leader, "needs", {}):
                continue
            before = _number(leader.needs.get(need))
            leader.needs[need] = _clamp(before + _number(delta))
            changes.setdefault("needs", {})[str(need)] = round(
                leader.needs[need] - before, 6
            )
        predicate = str(config.get("predicate") or "")
        if predicate:
            target_mode = str(config.get("target") or "source")
            if target_mode == "asset":
                target = report.get("asset")
            elif target_mode == "self":
                target = str(getattr(faction, "id", "") or "")
            else:
                target = report.get("source_id")
            try:
                self._believe(
                    leader,
                    leader_key,
                    predicate,
                    str(target or ""),
                    _number(config.get("value"), 1.0),
                    _number(config.get("confidence"), 0.8),
                )
                changes["belief"] = {
                    "subject": leader_key,
                    "predicate": predicate,
                    "object": str(target or ""),
                }
            except Exception:
                pass
        if motive:
            changes["motive"] = motive
        threat = self.threat_config
        if (
            self.threat_enabled
            and str(report.get("band") or "")
            in {
                str(item)
                for item in _as_list(threat.get("bands"))
            }
            and effect_key not in ("ignore", "rumor_ignore")
        ):
            target = self._rival_faction_id(faction)
            if target:
                try:
                    self._believe(
                        leader,
                        leader_key,
                        str(
                            threat.get("predicate") or "sees_as_threat"
                        ),
                        target,
                        _number(threat.get("strength"), 0.8),
                        _number(threat.get("confidence"), 0.7),
                    )
                    changes["threat"] = target
                except Exception:
                    pass
        return changes

    @staticmethod
    def _believe(
        character, subject, predicate, target, value=1.0, confidence=0.8
    ):
        """Записать убеждение в BDI персонажа.

        ``Character.believe`` принимает только триплет; уверенность и
        значение живут в ``BDIState.believe``. Обёртка держит оба пути
        совместимыми.
        """
        bdi = getattr(character, "bdi", None)
        if bdi is not None:
            belief = bdi.believe(
                subject,
                predicate,
                str(target or ""),
                value=value,
                confidence=confidence,
                source="report",
            )
            character.beliefs = bdi.beliefs
            return belief
        return character.believe(subject, predicate, str(target or ""))

    # --- история и путь --------------------------------------------
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
        self.reports = [
            dict(item)
            for item in _as_list(data.get("reports"))
            if isinstance(item, Mapping)
        ]
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


__all__ = ["ReportDispatcher"]
