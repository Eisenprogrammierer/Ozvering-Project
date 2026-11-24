"""Перехваты, контрмеры, retaliation и их жизненный цикл."""

from __future__ import annotations

from .dispatch_support import (
    _as_list,
    _as_mapping,
    _clamp,
    _number,
    _render,
)


class InterceptMixin:

    def interceptions(self, side=None):
        """Доступные игроку перехваты, без истёкших записей."""
        side = str(side or self.campaign.player_side)
        return [
            item
            for item in self.intercepts
            if str(item.get("side") or "") == side
            and str(item.get("status") or "") != "expired"
        ]

    def available_interceptions(self, side=None):
        """Перехваты, которые уже доставлены и ждут вскрытия."""
        now = _number(getattr(self.campaign, "elapsed", 0.0))
        return [
            item
            for item in self.interceptions(side)
            if str(item.get("status") or "") == "sealed"
            and _number(item.get("available_at"), 0.0) <= now
        ]

    def intercept(self, intercept_id):
        key = str(intercept_id or "")
        for item in self.intercepts:
            if str(item.get("id") or "") == key:
                return item
        return None

    def open_intercept(self, intercept_id):
        """Вскрыть перехваченное донесение за действие игрока.

        Содержание не меняет активы: игрок просто узнаёт, что видел и
        решил соперник. Цена списывается из того же бюджета действий,
        что и проверка доклада.
        """
        item = self.intercept(intercept_id)
        if item is None:
            return {"ok": False, "reason": "перехват не найден"}
        status = str(item.get("status") or "")
        if status != "sealed":
            return {
                "ok": False,
                "reason": "перехват уже вскрыт",
                "intercept": item,
            }
        now = _number(getattr(self.campaign, "elapsed", 0.0))
        if now + 1e-9 < _number(item.get("available_at"), 0.0):
            return {
                "ok": False,
                "reason": "шифр ещё в пути",
                "intercept": item,
            }
        expires_at = _number(item.get("expires_at"), 0.0)
        if expires_at and now >= expires_at:
            self._expire_intercept(item)
            return {
                "ok": False,
                "reason": "перехват устарел",
                "intercept": item,
            }
        price = max(
            0, int(_number(item.get("price"), 0))
        )
        cost = 0
        if price:
            gate = getattr(
                self.campaign, "_player_action_gate", None
            )
            if callable(gate):
                reason = gate(item.get("side"))
                if reason:
                    return {
                        "ok": False,
                        "reason": "вскрытие недоступно: %s" % reason,
                        "intercept": item,
                    }
            spend = getattr(
                self.campaign, "_spend_player_action", None
            )
            if callable(spend):
                spend(item.get("side"))
            cost = price
        item["status"] = "open"
        item["opened_at"] = round(now, 6)
        item["cost"] = cost
        item["title"] = str(
            item.get("open_title") or item.get("title") or "Перехват"
        )
        self._log(
            "intercept_opened",
            intercept_id=item.get("id"),
            report_id=item.get("report_id"),
            side=item.get("side"),
            source_id=item.get("source_id"),
            asset=item.get("asset"),
            cost=cost,
        )
        return {
            "ok": True,
            "intercept": item,
            "text": str(
                self.interception_config.get("open_text")
                or "Шифр вскрыт."
            ),
            "cost": cost,
        }

    def countermeasure_options(self, item):
        """Список контрмер для вскрытого перехвата и их доступность."""
        if item is None or str(item.get("status") or "") != "open":
            return []
        if item.get("counter"):
            return []
        disabled_motive = str(
            self.interception_config.get("counter_disabled_motive")
            or "Нужен раскрытый мотив подлога."
        )
        options = []
        for raw in _as_list(
            self.interception_config.get("countermeasures")
        ):
            data = _as_mapping(raw)
            option_id = str(data.get("id") or "")
            if not option_id:
                continue
            reason = ""
            if bool(data.get("requires_motive")) and not bool(
                item.get("motive_revealed")
            ):
                reason = disabled_motive
            options.append(
                {
                    "id": option_id,
                    "label": str(data.get("label") or option_id),
                    "benefit": _render(
                        data.get("benefit") or "",
                        {
                            "faction": item.get("faction_name") or "",
                            "source": item.get("source_name") or "",
                            "asset_label": item.get("asset_label") or "",
                        },
                    ),
                    "price": max(
                        0,
                        int(_number(data.get("price_actions"), 1)),
                    ),
                    "available": not reason,
                    "reason": reason,
                }
            )
        return options

    def use_intercept(self, intercept_id, counter_id):
        """Потратить вскрытый перехват на контрмеру.

        Контрмера не трогает активы: она пишет убеждения в BDI,
        отношения, мораль и потребности. Игрок может предупредить
        своего лидера или подорвать доверие соперника к источнику.
        """
        item = self.intercept(intercept_id)
        if item is None:
            return {"ok": False, "reason": "перехват не найден"}
        if str(item.get("status") or "") != "open":
            return {
                "ok": False,
                "reason": "сначала вскройте перехват",
                "intercept": item,
            }
        if item.get("counter"):
            return {
                "ok": False,
                "reason": str(
                    self.interception_config.get("counter_already_text")
                    or "Контрмера уже принята."
                ),
                "intercept": item,
            }
        options = self.countermeasure_options(item)
        option = None
        for data in _as_list(
            self.interception_config.get("countermeasures")
        ):
            data = _as_mapping(data)
            if str(data.get("id") or "") == str(counter_id or ""):
                option = data
                break
        if option is None:
            return {
                "ok": False,
                "reason": "неизвестная контрмера",
                "intercept": item,
            }
        info = next(
            (
                entry
                for entry in options
                if entry["id"] == str(counter_id or "")
            ),
            None,
        )
        if info is None or not info.get("available"):
            return {
                "ok": False,
                "reason": (
                    (info or {}).get("reason")
                    or "контрмера недоступна"
                ),
                "intercept": item,
            }
        price = int(info.get("price") or 0)
        cost = 0
        if price:
            gate = getattr(
                self.campaign, "_player_action_gate", None
            )
            if callable(gate):
                reason = gate(item.get("side"))
                if reason:
                    return {
                        "ok": False,
                        "reason": "контрмера недоступна: %s" % reason,
                        "intercept": item,
                    }
            spend = getattr(
                self.campaign, "_spend_player_action", None
            )
            if callable(spend):
                spend(item.get("side"))
            cost = price
        player_faction = self.campaign.faction(item.get("side"))
        origin_faction = self.campaign.faction(item.get("origin_side"))
        player_leader = self._leader_for(player_faction)
        origin_leader = self._leader_for(origin_faction)
        self._apply_counter_belief(
            player_leader, player_faction, option.get("belief"), item
        )
        self._apply_counter_belief(
            origin_leader,
            origin_faction,
            option.get("enemy_belief"),
            item,
        )
        if player_leader is not None:
            morale = _number(getattr(player_leader, "morale", 0.0))
            player_leader.morale = max(
                0.0, min(100.0, morale + _number(option.get("morale")))
            )
            for need, delta in _as_mapping(
                option.get("needs")
            ).items():
                if need in getattr(player_leader, "needs", {}):
                    player_leader.needs[need] = _clamp(
                        _number(player_leader.needs.get(need))
                        + _number(delta)
                    )
        relation = _as_mapping(option.get("relation"))
        relations = getattr(self.campaign, "relations", None)
        if relation and relations is not None and origin_faction is not None:
            source_id = str(item.get("source_id") or "")
            if source_id:
                try:
                    relations.add(
                        str(origin_faction.id),
                        source_id,
                        dict(relation),
                        1.0,
                    )
                except Exception:
                    pass
        now = _number(getattr(self.campaign, "elapsed", 0.0))
        label = str(option.get("label") or counter_id)
        text = _render(
            option.get("text")
            or self.interception_config.get("counter_used_text"),
            {
                "faction": item.get("faction_name") or "",
                "label": label,
                "source": item.get("source_name") or "",
                "asset_label": item.get("asset_label") or "",
            },
        )
        item["counter"] = str(counter_id or "")
        item["counter_label"] = label
        item["counter_text"] = text
        item["counter_at"] = round(now, 6)
        item["counter_cost"] = cost
        retaliation = self._retaliate(
            item, str(counter_id or ""), now
        )
        self._log(
            "intercept_used",
            intercept_id=item.get("id"),
            report_id=item.get("report_id"),
            side=item.get("side"),
            origin_side=item.get("origin_side"),
            counter=str(counter_id or ""),
            cost=cost,
            retaliated=bool(retaliation),
        )
        result = {
            "ok": True,
            "intercept": item,
            "text": text,
            "cost": cost,
        }
        if retaliation:
            result["retaliation"] = retaliation
        return result

    def _apply_counter_belief(self, character, faction, block, item):
        """Записать убеждение контрмеры без изменения активов."""
        data = _as_mapping(block)
        predicate = str(data.get("predicate") or "")
        if not predicate or character is None or faction is None:
            return None
        mode = str(data.get("target") or "source")
        if mode == "origin_faction":
            target = item.get("faction_id")
        elif mode == "origin_side":
            target = item.get("origin_side")
        elif mode == "asset":
            target = item.get("asset")
        else:
            target = item.get("source_id")
        try:
            return self._believe(
                character,
                self._leader_key(faction, character),
                predicate,
                str(target or ""),
                _number(data.get("value"), 1.0),
                _number(data.get("confidence"), 0.8),
            )
        except Exception:
            return None

    def _retaliation_chance(self, item, counter_id):
        """Шанс, что соперник заметит вмешательство игрока."""
        cfg = _as_mapping(self.interception_config.get("retaliation"))
        if not bool(cfg.get("enabled", True)):
            return 0.0
        chances = _as_mapping(cfg.get("chances"))
        base = _number(
            chances.get(counter_id), _number(cfg.get("chance"), 0.3)
        )
        origin = self.campaign.faction(item.get("origin_side"))
        player = self.campaign.faction(item.get("side"))
        if origin is None or player is None:
            return 0.0
        origin_influence = _clamp(origin.asset("influence"))
        player_influence = _clamp(player.asset("influence"))
        return _clamp(
            base
            + _number(cfg.get("influence_weight"), 0.3)
            * (origin_influence - 0.5)
            - _number(cfg.get("player_influence_weight"), 0.3)
            * (player_influence - 0.5),
            0.0,
            1.0,
        )

    def _retaliate(self, item, counter_id, now):
        """Соперник замечает контрмеру и отвечает через BDI.

        Ответ не трогает активы: лидер получает убеждение об угрозе со
        стороны игрока, а отношения между фракциями проседают. Дальше
        вес работ меняет уже ``ai_model.beliefs.rules``.
        """
        if not counter_id:
            return None
        chance = self._retaliation_chance(item, counter_id)
        if chance <= 0.0 or self.retaliation_rng.random() >= chance:
            return None
        origin_faction = self.campaign.faction(item.get("origin_side"))
        player_faction = self.campaign.faction(item.get("side"))
        if origin_faction is None or player_faction is None:
            return None
        leader = self._leader_for(origin_faction)
        if leader is None:
            return None
        cfg = _as_mapping(self.interception_config.get("retaliation"))
        belief = _as_mapping(cfg.get("belief"))
        predicate = str(belief.get("predicate") or "")
        target = str(getattr(player_faction, "id", "") or "")
        if predicate and target:
            try:
                self._believe(
                    leader,
                    self._leader_key(origin_faction, leader),
                    predicate,
                    target,
                    _number(belief.get("value"), 0.7),
                    _number(belief.get("confidence"), 0.75),
                )
            except Exception:
                pass
        relation = _as_mapping(cfg.get("relation"))
        relations = getattr(self.campaign, "relations", None)
        if relation and relations is not None:
            try:
                relations.add(
                    str(origin_faction.id),
                    str(player_faction.id),
                    dict(relation),
                    1.0,
                )
            except Exception:
                pass
        texts = _as_mapping(cfg.get("texts"))
        text = _render(
            texts.get(counter_id)
            or cfg.get("fallback_text")
            or "{faction} что-то заподозрила.",
            {
                "faction": str(
                    getattr(origin_faction, "name", "")
                    or item.get("faction_name")
                    or ""
                ),
                "player": str(
                    getattr(player_faction, "name", "") or ""
                ),
            },
        )
        payload = {
            "counter": counter_id,
            "text": text,
            "belief": predicate,
            "target": target,
            "chance": round(chance, 6),
            "at": round(now, 6),
        }
        item["retaliation"] = payload
        item["retaliation_text"] = text
        self._log(
            "intercept_retaliated",
            intercept_id=item.get("id"),
            report_id=item.get("report_id"),
            origin_side=item.get("origin_side"),
            side=item.get("side"),
            counter=counter_id,
            chance=round(chance, 6),
            belief=predicate,
            target=target,
        )
        return payload

    def _capture_intercept(self, report):
        """Сохранить копию чужого доклада для возможного перехвата."""
        if not self.interception_enabled or report is None:
            return None
        side = str(report.get("side") or "")
        if side == str(getattr(self.campaign, "player_side", "")):
            return None
        if str(report.get("status") or "") != "resolved":
            return None
        report_id = str(report.get("id") or "")
        for item in self.intercepts:
            if str(item.get("report_id") or "") == report_id:
                return item
        chance = self._intercept_chance()
        if chance <= 0.0 or self.rng.random() >= chance:
            return None
        now = _number(getattr(self.campaign, "elapsed", 0.0))
        self._intercept_seq += 1
        item = self._intercept_record(report, now)
        self.intercepts.append(item)
        self._trim_intercepts()
        self._log(
            "intercept_available",
            intercept_id=item.get("id"),
            report_id=report_id,
            side=item.get("origin_side"),
            source_id=item.get("source_id"),
            asset=item.get("asset"),
            available_at=item.get("available_at"),
        )
        return item

    def _intercept_record(self, report, now):
        config = self.interception_config
        side = str(report.get("side") or "")
        faction = self.campaign.faction(side)
        faction_name = str(
            getattr(faction, "name", "") or side or "соперник"
        )
        delay = max(
            0.0, _number(config.get("delay_seconds"), 7200.0)
        )
        expire = max(0.0, _number(config.get("expire_seconds"), 0.0))
        choice = str(report.get("choice") or "")
        label = choice
        for item in report.get("choices") or ():
            if str(item.get("id") or "") == choice:
                label = str(item.get("label") or choice)
                break
        resolved = _as_mapping(report.get("resolved"))
        player_side = str(
            getattr(self.campaign, "player_side", "") or ""
        )
        return {
            "id": "intercept-%04d" % self._intercept_seq,
            "kind": "intercept",
            "report_id": report.get("id"),
            "side": player_side,
            "origin_side": side,
            "faction_id": str(getattr(faction, "id", "") or ""),
            "faction_name": faction_name,
            "source_id": report.get("source_id"),
            "source_name": report.get("source_name"),
            "source_post": report.get("source_post"),
            "asset": report.get("asset"),
            "asset_label": report.get("asset_label"),
            "title": _render(
                str(config.get("title") or "Перехват: {faction}"),
                {"faction": faction_name, "side": side},
            ),
            "open_title": _render(
                str(
                    config.get("open_title")
                    or "Перехват вскрыт: {faction}"
                ),
                {"faction": faction_name, "side": side},
            ),
            "sealed_text": str(
                config.get("sealed_text") or ""
            ),
            "in_transit_text": str(
                config.get("in_transit_text") or ""
            ),
            "source_unknown": str(
                config.get("source_unknown")
                or "источник неизвестен"
            ),
            "decision_unknown": str(
                config.get("decision_unknown") or ""
            ),
            "channel": report.get("channel"),
            "channel_label": report.get("channel_label"),
            "text": report.get("text"),
            "band": report.get("band"),
            "band_label": report.get("band_label"),
            "confidence": report.get("confidence"),
            "confidence_label": report.get("confidence_label"),
            "choice": choice,
            "choice_label": label,
            "decision_text": str(resolved.get("text") or ""),
            "decided_by": str(resolved.get("decided_by") or "ai"),
            "motive": resolved.get("motive"),
            "motive_revealed": bool(
                resolved.get("motive_revealed")
            ),
            "created": round(now, 6),
            "available_at": round(now + delay, 6),
            "expires_at": (
                round(now + expire, 6) if expire else 0.0
            ),
            "status": "sealed",
            "price": max(
                0,
                int(
                    _number(config.get("price_actions"), 1)
                ),
            ),
            "cost": 0,
        }

    def _intercept_chance(self):
        config = self.interception_config
        base = _clamp(config.get("chance"), 0.0, 1.0)
        weight = _number(config.get("influence_weight"), 0.0)
        return _clamp(base + weight * (self._player_influence() - 0.5))

    def _player_influence(self):
        faction = self.campaign.faction(
            getattr(self.campaign, "player_side", "")
        )
        if faction is None:
            return 0.5
        try:
            return _clamp(faction.asset("influence"))
        except Exception:
            return 0.5

    def _expire_intercepts(self):
        now = _number(getattr(self.campaign, "elapsed", 0.0))
        for item in list(self.intercepts):
            if str(item.get("status") or "") != "sealed":
                continue
            expires_at = _number(item.get("expires_at"), 0.0)
            if expires_at and now >= expires_at:
                self._expire_intercept(item)
        self._trim_intercepts()

    def _expire_intercept(self, item):
        if str(item.get("status") or "") != "sealed":
            return
        item["status"] = "expired"
        item["expired_at"] = round(
            _number(getattr(self.campaign, "elapsed", 0.0)), 6
        )
        self._log(
            "intercept_expired",
            intercept_id=item.get("id"),
            report_id=item.get("report_id"),
            side=item.get("origin_side"),
            asset=item.get("asset"),
        )

    def _trim_intercepts(self):
        limit = max(
            1,
            int(
                _number(
                    self.interception_config.get("max_pending"), 6
                )
            ),
        )
        sealed = [
            item
            for item in self.intercepts
            if str(item.get("status") or "") == "sealed"
        ]
        while len(sealed) > limit:
            self._expire_intercept(sealed.pop(0))
        self.intercepts = self.intercepts[-self.history_limit:]
