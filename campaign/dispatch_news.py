"""Городские вести и лента новостей кампании."""

from __future__ import annotations

from .dispatch_support import (
    _as_mapping,
    _clamp,
    _number,
    _render,
)


class NewsMixin:

    def _news_tick(self, seconds):
        """Накопить время и выпустить городские вести.

        Вести не требуют выбора и не меняют активы: это сводка города,
        рыночная цена и слухи улиц. Они приходят с задержкой и попадают
        в информационную ленту, поэтому эмуляцию не останавливают.
        """
        if not bool(self.news_config.get("enabled", True)):
            return []
        interval = max(
            60.0,
            _number(
                self.news_config.get("interval_seconds"), 86400.0
            ),
        )
        limit = max(
            1, int(_number(self.news_config.get("max_pending"), 8))
        )
        self._news_progress += max(0.0, _number(seconds))
        spawned = []
        while (
            self._news_progress + 1e-9 >= interval
            and not self.campaign.finished
            and len(spawned) < limit
        ):
            self._news_progress -= interval
            entry = self.issue_news()
            if entry is not None:
                spawned.append(entry)
        return spawned

    def issue_news(self):
        """Выпустить одну информационную новость, если выпал тип.

        Типы перебираются по кругу, поэтому город получает разные вести,
        а не одну и ту же строку. Шанс каждого типа задан в его блоке.
        """
        types = []
        for key in ("city", "prices", "street"):
            block = _as_mapping(self.news_config.get(key))
            if bool(block.get("enabled", False)):
                types.append((key, block))
        if not types:
            return None
        start = int(self._news_index) % len(types)
        for offset in range(len(types)):
            position = (start + offset) % len(types)
            key, block = types[position]
            chance = _clamp(block.get("chance", 1.0), 0.0, 1.0)
            if chance <= 0.0 or self.news_rng.random() >= chance:
                continue
            builder = getattr(self, "_news_%s" % key, None)
            text = builder(block) if callable(builder) else None
            if not text:
                continue
            self._news_index = (position + 1) % len(types)
            return self._append_news(key, block, text)
        self._news_index = (start + 1) % len(types)
        return None

    def _news_city(self, block):
        """Сводка города: где тонко, а где крепко."""
        faction = self.campaign.faction(
            getattr(self.campaign, "player_side", "")
        )
        assets = [asset for asset in self.assets if asset]
        if faction is None or not assets:
            return ""
        values = [
            (asset, _clamp(faction.asset(asset))) for asset in assets
        ]
        weak = min(values, key=lambda item: item[1])
        strong = max(values, key=lambda item: item[1])
        texts = _as_mapping(block.get("texts"))
        if strong[1] - weak[1] >= 0.15:
            template = texts.get("mixed") or ""
            values_map = {
                "weak_label": self.asset_labels.get(
                    weak[0], weak[0]
                ),
                "weak_band": self._band(weak[1])["label"],
                "strong_label": self.asset_labels.get(
                    strong[0], strong[0]
                ),
                "strong_band": self._band(strong[1])["label"],
            }
        else:
            template = texts.get("calm") or ""
            values_map = {
                "asset": strong[0],
                "asset_label": self.asset_labels.get(
                    strong[0], strong[0]
                ),
                "band": self._band(strong[1])["label"],
            }
        return _render(template, values_map)

    def _news_prices(self, block):
        """Цена на рынке: дорожает, дешевеет или держится."""
        faction = self.campaign.faction(
            getattr(self.campaign, "player_side", "")
        )
        if faction is None:
            return ""
        asset = str(block.get("asset") or "supply")
        band = self._band(faction.asset(asset))
        index = int(band.get("index", 0))
        last = len(self.bands) - 1
        if index <= 1:
            key = "low"
        elif index >= max(1, last - 1):
            key = "high"
        else:
            key = "level"
        return _render(
            block.get(key) or block.get("level") or "",
            {
                "asset": asset,
                "asset_label": self.asset_labels.get(asset, asset),
                "band": band["label"],
            },
        )

    def _news_street(self, block):
        """Слух улиц: сильное убеждение или нужда случайной фракции."""
        factions = [item for item in self._factions() if item is not None]
        if not factions:
            return ""
        faction = self.news_rng.choice(factions)
        leader = self._leader_for(faction)
        texts = _as_mapping(block.get("texts"))
        predicate = ""
        target = ""
        if leader is not None:
            best = None
            for belief in getattr(
                getattr(leader, "bdi", None), "beliefs", ()
            ) or ():
                name = str(getattr(belief, "predicate", "") or "")
                if name not in texts:
                    continue
                weight = _number(
                    getattr(belief, "value", 0.0)
                ) * _number(getattr(belief, "confidence", 1.0))
                if best is None or weight > best[0]:
                    best = (
                        weight,
                        name,
                        str(getattr(belief, "object", "") or ""),
                    )
            if best is not None:
                predicate = best[1]
                target = best[2]
        template = texts.get(predicate) or texts.get("quiet") or ""
        return _render(
            template,
            {
                "faction": str(
                    getattr(faction, "name", "")
                    or getattr(faction, "side", "")
                ),
                "target": self._entity_label(target),
            },
        )

    def _entity_label(self, value):
        """Человеческое имя стороны, фракции или персонажа."""
        key = str(value or "")
        if not key:
            return "соседи"
        player_side = str(
            getattr(self.campaign, "player_side", "") or ""
        )
        if key == "player":
            key = player_side

        def normalize(value):
            return str(value or "").replace(".", "_").lower()

        target = normalize(key)
        for faction in self._factions():
            side = str(getattr(faction, "side", "") or "")
            fid = str(getattr(faction, "id", "") or "")
            if target in (normalize(side), normalize(fid)):
                return str(
                    getattr(faction, "name", "") or key
                )
        character = self._character(key)
        if character is not None:
            return str(getattr(character, "name", "") or key)
        return key

    def _append_news(self, news_type, block, text):
        """Положить весть в информационную ленту с задержкой."""
        events = getattr(self.campaign, "story_events", None)
        if events is None:
            return None
        self._news_seq += 1
        now = _number(getattr(self.campaign, "elapsed", 0.0))
        delay = max(
            0.0,
            _number(
                block.get("delay_seconds"),
                _number(self.news_config.get("delay_seconds"), 21600.0),
            ),
        )
        player_side = str(
            getattr(self.campaign, "player_side", "") or ""
        )
        faction = self.campaign.faction(player_side)
        title = str(
            block.get("title")
            or self.news_config.get("title")
            or "Вести"
        )
        entry = {
            "id": "news-city-%06d" % self._news_seq,
            "template_id": "news",
            "category": "news",
            "news_type": news_type,
            "title": title,
            "text": text,
            "severity": None,
            "stakes": None,
            "speed": "instant",
            "duration": 0.0,
            "elapsed": float(now),
            "release_at": float(now) + delay,
            "visible": True,
            "visibility": {},
            "effects": {},
            "turn": self.campaign.turn,
            "side": player_side,
            "faction_id": str(getattr(faction, "id", "") or ""),
            "source_id": "",
            "source_name": title,
            "asset": block.get("asset"),
            "report_id": None,
            "requires_choice": False,
            "status": "resolved",
        }
        events.append(entry)
        self._log(
            "news_issued",
            news_id=entry.get("id"),
            news_type=news_type,
            title=title,
            release_at=entry.get("release_at"),
        )
        try:
            from .automata import EVENT_LOG_LIMIT

            if len(events) > EVENT_LOG_LIMIT:
                del events[:-EVENT_LOG_LIMIT]
        except Exception:
            pass
        return entry

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
