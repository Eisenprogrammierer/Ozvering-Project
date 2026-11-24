"""Сводка штаба: очередь докладов, тренды и брифинг."""

from __future__ import annotations

from .dispatch_support import (
    _as_mapping,
    _clamp,
    _number,
    _render,
)


class BriefingMixin:

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
        if self.available_interceptions(side):
            lines.append("Есть перехваченные донесения.")
        if self.assets:
            weakest = min(
                (str(asset) for asset in self.assets),
                key=lambda key: faction.asset(key),
            )
            band = self._band(faction.asset(weakest))
            label = self.asset_labels.get(weakest, weakest)
            lines.append("%s — «%s»." % (label, band["label"]))
        trend = self._trend_summary(side, faction) or self._trend_line(
            side, faction
        )
        if trend:
            lines.append(trend)
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

    def _trend_movements(self, side, faction):
        """Подвижные активы стороны за окно, от сильного к слабому.

        Начальник штаба сравнивает первую и вторую половину выборки
        решённых докладов своей стороны. Значения берутся из снимка
        истины на момент доклада, поэтому картина не зависит от того,
        поверил ли игрок источнику. Движения меньше шага не попадают в
        список: молчание честнее выдуманного тренда.
        """
        cfg = _as_mapping(self.briefing_config)
        if not bool(cfg.get("enabled", True)):
            return []
        days = max(1.0, _number(cfg.get("trend_days"), 30.0))
        minimum = max(2, int(_number(cfg.get("trend_min_samples"), 2)))
        step = max(0.0, _number(cfg.get("trend_step"), 0.06))
        now = _number(getattr(self.campaign, "elapsed", 0.0))
        window = now - days * 86400.0
        samples = {}
        for report in self.reports:
            if str(report.get("side") or "") != str(side):
                continue
            if str(report.get("status") or "") != "resolved":
                continue
            if report.get("true_value") is None:
                continue
            created = _number(report.get("created"), 0.0)
            if created < window:
                continue
            asset = str(report.get("asset") or "")
            if asset not in self.assets:
                continue
            samples.setdefault(asset, []).append(
                (created, _clamp(report.get("true_value")))
            )
        movements = []
        for asset, values in samples.items():
            if len(values) < minimum:
                continue
            values.sort(key=lambda item: item[0])
            middle = len(values) // 2
            early = sum(value for _at, value in values[:middle]) / middle
            late = sum(
                value for _at, value in values[middle:]
            ) / (len(values) - middle)
            delta = late - early
            if abs(delta) + 1e-9 < step:
                continue
            movements.append((asset, delta))
        movements.sort(key=lambda item: (-abs(item[1]), item[0]))
        return movements

    def _trend_line(self, side, faction):
        """Направление самого подвижного актива, без точных чисел."""
        cfg = _as_mapping(self.briefing_config)
        movements = self._trend_movements(side, faction)
        if not movements:
            return ""
        asset, delta = movements[0]
        key = "up" if delta > 0 else "down"
        template = _as_mapping(cfg.get("trend_lines")).get(key) or ""
        if not template:
            return ""
        band = self._band(faction.asset(asset))
        return _render(
            template,
            {
                "asset": asset,
                "asset_label": self.asset_labels.get(asset, asset),
                "band": band["label"],
            },
        )

    def _trend_summary(self, side, faction):
        """Короткая картина по нескольким подвижным активам сразу."""
        cfg = _as_mapping(self.briefing_config)
        if not bool(cfg.get("trend_multi", True)):
            return ""
        limit = max(
            2, int(_number(cfg.get("trend_max_assets"), 3))
        )
        movements = self._trend_movements(side, faction)
        if len(movements) < 2:
            return ""
        short = _as_mapping(cfg.get("trend_short"))
        parts = []
        for asset, delta in movements[:limit]:
            key = "up" if delta > 0 else "down"
            template = short.get(key) or ""
            if not template:
                continue
            parts.append(
                _render(
                    template,
                    {
                        "asset": asset,
                        "asset_label": self.asset_labels.get(
                            asset, asset
                        ),
                    },
                )
            )
        if len(parts) < 2:
            return ""
        return _render(
            cfg.get("trend_multi_line") or "За дни: {parts}.",
            {
                "parts": str(cfg.get("trend_join") or ", ").join(
                    parts
                )
            },
        )
