"""Доклады, решения, перехваты и сводка штаба."""

from __future__ import annotations

from .automata_support import (
    EVENT_LOG_LIMIT,
    Mapping,
    _as_mapping,
    _character_alive,
    _clamp,
    _normalize_gender,
    _number,
    logger,
)
from .chronicle import MAX_NARRATIVE, narrative_record


class AutomataReportsMixin:

    def _story_character_stats(self, character):
        """Нормированный срез персонажа для условий событий."""
        if character is None:
            return {}
        state = getattr(character, "state", {}) or {}
        max_force = float(state.get("max_force", 10.0) or 10.0)
        max_energy = float(state.get("max_energy", 3.0) or 3.0)
        bdi = getattr(character, "bdi", None)
        return {
            "id": str(getattr(character, "campaign_id", "") or ""),
            "name": str(getattr(character, "name", "") or ""),
            "role": str(getattr(character, "campaign_role_id", "") or ""),
            "gender": _normalize_gender(
                getattr(character, "campaign_gender", "")
            ),
            "post": str(getattr(character, "campaign_post", "") or ""),
            "organ_id": str(
                getattr(character, "campaign_organ_id", "") or ""
            ),
            "alive": _character_alive(character),
            "morale": round(
                _clamp(float(getattr(character, "morale", 0.0)) / 100.0),
                6,
            ),
            "force": round(
                _clamp(
                    float(getattr(character, "force", 0.0))
                    / max(1e-9, max_force)
                ),
                6,
            ),
            "energy": round(
                _clamp(
                    float(getattr(character, "energy_pool", 0.0))
                    / max(1e-9, max_energy)
                ),
                6,
            ),
            "needs": dict(getattr(character, "needs", {}) or {}),
            "conditions": (
                dict(bdi.conditions) if bdi is not None else {}
            ),
            "beliefs": (
                [item.as_dict() for item in bdi.beliefs]
                if bdi is not None
                else []
            ),
            "intentions": (
                [item.as_dict() for item in bdi.intentions]
                if bdi is not None
                else []
            ),
        }

    def _story_relations(self, leader):
        """Проекция убеждений-отношений лидера: объект → предикат → сила.

        Слой отражения читает только то, что уже записано в BDI. Никакого
        отдельного хранилища отношений не появляется (G-11 остаётся
        отдельной задачей).
        """
        bdi = getattr(leader, "bdi", None)
        config = getattr(bdi, "config", None)
        if bdi is None or config is None:
            return {}
        relations = {}
        for belief in bdi.beliefs:
            spec = config.predicate(belief.predicate) or {}
            if str(spec.get("kind") or "") != "relation":
                continue
            target = str(belief.object or "").strip()
            if not target:
                continue
            strength = _clamp(
                float(belief.value) * float(belief.confidence)
            )
            bucket = relations.setdefault(target, {})
            bucket[belief.predicate] = max(
                float(bucket.get(belief.predicate, 0.0)), strength
            )
        return relations

    def _story_organization(self, faction):
        """Снимок организации для событий: свежий или сохранённый."""
        state = {}
        organization = getattr(faction, "organization", None)
        if organization is not None:
            try:
                state = dict(organization.snapshot())
            except Exception:
                logger.exception("не удалось прочитать снимок организации")
        if not state:
            state = dict(
                _as_mapping(getattr(faction, "organization_snapshot", {}))
            )
        state.setdefault("name", str(getattr(faction, "name", "") or ""))
        return state

    def _story_context(self, side=None):
        """Контекст для условий/видимости событий.

        Берётся лидер фракции (по умолчанию — игрок). Числа нормированы в
        ``0..1``, чтобы условия в JSON были переносимыми. Помимо лидера
        контекст видит активы, органы, флаги, ростер персонажей, намерения
        и отношения — событие отражает фракцию, а не один силуэт.
        """
        side = str(side or self.player_side)
        faction = self.faction(side)
        if faction is None or not faction.characters:
            return {
                "side": side,
                "faction_id": getattr(faction, "id", ""),
                "alive": False,
                "time": self.elapsed,
            }
        # Ролевой слой не должен описывать мёртвых как живых. Для
        # обычных сцен берём живого лидера и живого второго персонажа,
        # а погибших отдаём отдельными полями ``fallen``/``has_dead``:
        # события смерти, похорон и наследования срабатывают только
        # тогда, когда такой персонаж действительно есть.
        living = [
            item for item in faction.characters
            if _character_alive(item)
        ]
        candidates = living or list(faction.characters)
        leader = candidates[0]
        bdi = getattr(leader, "bdi", None)
        divisions = getattr(leader, "divisions", None)
        rival_faction = self.faction(self.rival_of(side))
        rival_leader = None
        if rival_faction is not None and rival_faction.characters:
            rival_leader = next(
                (
                    item for item in rival_faction.characters
                    if _character_alive(item)
                ),
                rival_faction.characters[0],
            )
        actor_gender = _normalize_gender(
            getattr(leader, "campaign_gender", "")
        )
        # Второй участник — по возможности свой, а не соперник: иначе
        # «свадьба» связывала лидера с главой враждебной фракции.
        # Разнополого кандидата предпочитаем, чтобы парные события не
        # собирали однополую пару.
        target_character = None
        pair_same_faction = False
        for item in candidates[1:]:
            if item is leader:
                continue
            target_character = item
            pair_same_faction = True
            item_gender = _normalize_gender(
                getattr(item, "campaign_gender", "")
            )
            if actor_gender and item_gender and actor_gender != item_gender:
                break
        if target_character is None:
            target_character = rival_leader
        target_gender = _normalize_gender(
            getattr(target_character, "campaign_gender", "")
        )
        fallen = next(
            (
                item for item in faction.characters
                if not _character_alive(item)
            ),
            None,
        )
        rival_name = str(
            getattr(rival_leader, "name", "")
            or getattr(rival_faction, "name", "")
            or ""
        )
        characters = {}
        for character in faction.characters:
            stats = self._story_character_stats(character)
            if stats.get("id"):
                characters[stats["id"]] = stats
        return {
            "id": str(getattr(leader, "campaign_id", "") or ""),
            "name": str(getattr(leader, "name", "") or ""),
            "actor": str(getattr(leader, "name", "") or ""),
            "target": str(getattr(target_character, "name", "") or ""),
            "actor_gender": actor_gender,
            "target_gender": target_gender,
            "opposite_gender": bool(
                actor_gender and target_gender
                and actor_gender != target_gender
            ),
            "actor_alive": _character_alive(leader),
            "target_alive": bool(
                target_character is not None
                and _character_alive(target_character)
            ),
            "pair_alive": bool(
                target_character is not None
                and _character_alive(leader)
                and _character_alive(target_character)
            ),
            "pair_same_faction": pair_same_faction,
            "has_dead": fallen is not None,
            "fallen": str(getattr(fallen, "name", "") or ""),
            "fallen_gender": _normalize_gender(
                getattr(fallen, "campaign_gender", "")
            ),
            "rival": rival_name,
            "side": side,
            "faction_id": str(getattr(faction, "id", "") or ""),
            "faction_name": str(getattr(faction, "name", "") or ""),
            "organization": str(getattr(faction, "name", "") or ""),
            "organization_state": self._story_organization(faction),
            "rival_id": str(getattr(rival_faction, "id", "") or ""),
            "rival_organization": rival_name,
            "role": str(getattr(leader, "campaign_role_id", "") or ""),
            "needs": dict(getattr(leader, "needs", {}) or {}),
            "traits": dict(getattr(leader.personality, "values", {}) or {}),
            "divisions": (
                divisions.as_dict() if divisions is not None else {}
            ),
            "tags": divisions.tags() if divisions is not None else [],
            "conditions": (
                dict(bdi.conditions) if bdi is not None else {}
            ),
            "beliefs": list(bdi.beliefs) if bdi is not None else [],
            "intentions": (
                [item.as_dict() for item in bdi.intentions]
                if bdi is not None
                else []
            ),
            "relations": self._story_relations(leader),
            "assets": {
                str(key): float(value)
                for key, value in faction.assets.items()
            },
            "organs": {
                str(organ.id): float(organ.integrity)
                for organ in faction.organs
            },
            "organ_statuses": {
                str(organ.id): organ.status() for organ in faction.organs
            },
            "organ_scales": {
                str(organ.id): dict(organ.scales)
                for organ in faction.organs
            },
            "flags": dict(getattr(faction, "flags", {}) or {}),
            "characters": characters,
            "character_count": len(faction.characters),
            "priority_needs": list(
                _as_mapping(faction.record).get("priority_needs") or ()
            ),
            "goals": list(
                _as_mapping(faction.record).get("goals") or ()
            ),
            "doctrine": dict(
                _as_mapping(
                    _as_mapping(faction.record).get("doctrine")
                )
            ),
            "turn": int(self.turn),
            "used_actions": sorted(
                str(key)
                for key, value in faction.action_uses.items()
                if int(value) > 0
            ),
            "force": max(
                0.0,
                float(getattr(leader, "force", 0.0))
                / max(
                    1e-9,
                    float(
                        getattr(leader, "state", {}).get(
                            "max_force", 10.0
                        )
                    ),
                ),
            ),
            "energy": max(
                0.0,
                float(getattr(leader, "energy_pool", 0.0))
                / max(
                    1e-9,
                    float(
                        getattr(leader, "state", {}).get(
                            "max_energy", 3.0
                        )
                    ),
                ),
            ),
            "alive": _character_alive(leader),
            "time": float(self.elapsed),
        }

    def pending_reports(self, side=None):
        """Доклады, ожидающие решения игрока."""
        return self.dispatch.pending(side)

    def pending_decisions(self, side=None):
        """События, которые нельзя игнорировать во время эмуляции.

        Сейчас это доклады с выбором. Список остаётся общим, чтобы
        будущие сюжетные события с выбором попадали в ту же проверку.
        """
        decisions = list(self.dispatch.pending(side))
        seen = {
            str(item.get("id") or "")
            for item in decisions
            if item.get("id")
        }
        for entry in self.story_events:
            if not entry.get("requires_choice"):
                continue
            if str(entry.get("status") or "") != "pending":
                continue
            if str(entry.get("id") or "") in seen:
                continue
            if side and str(entry.get("side") or "") not in ("", str(side)):
                continue
            decisions.append(entry)
        return decisions

    def decision_pending(self, side=None):
        """Есть ли событие, требующее немедленного решения игрока."""
        return bool(self.pending_decisions(side))

    def report(self, report_id):
        """Найти доклад по идентификатору."""
        return self.dispatch.report(report_id)

    def resolve_report(self, report_id, choice):
        """Принять решение по докладу.

        Последствия живут в BDI, отношениях, потребностях и морали
        источника. Прямых записей в активы фракции нет.
        """
        return self.dispatch.resolve(report_id, choice)

    def interceptions(self, side=None):
        """Перехваченные донесения противника для игрока."""
        return self.dispatch.interceptions(side)

    def available_interceptions(self, side=None):
        """Перехваты, которые уже можно вскрыть."""
        return self.dispatch.available_interceptions(side)

    def intercept(self, intercept_id):
        """Найти перехват по идентификатору."""
        return self.dispatch.intercept(intercept_id)

    def open_intercept(self, intercept_id):
        """Вскрыть перехваченное донесение за действие игрока."""
        return self.dispatch.open_intercept(intercept_id)

    def intercept_counters(self, intercept_id):
        """Контрмеры, доступные по вскрытому перехвату."""
        return self.dispatch.countermeasure_options(
            self.dispatch.intercept(intercept_id)
        )

    def use_intercept(self, intercept_id, counter_id):
        """Потратить вскрытый перехват на контрмеру."""
        result = self.dispatch.use_intercept(intercept_id, counter_id)
        if result.get("ok") and result.get("retaliation"):
            self._record_retaliation_event(result)
        return result

    def _record_retaliation_event(self, result):
        """Показать ответ соперника в информационной ленте."""
        item = result.get("intercept") or {}
        text = str(item.get("retaliation_text") or "")
        if not text:
            return None
        entry = {
            "id": "retaliation-%s" % (item.get("id") or ""),
            "template_id": "retaliation",
            "category": "retaliation",
            "title": "Ответ соперника",
            "text": text,
            "severity": None,
            "stakes": None,
            "speed": "instant",
            "duration": 0.0,
            "elapsed": float(self.elapsed),
            "visible": True,
            "visibility": {},
            "effects": {},
            "turn": self.turn,
            "side": str(item.get("origin_side") or ""),
            "faction_id": str(item.get("faction_id") or ""),
            "source_id": "",
            "source_name": str(item.get("faction_name") or ""),
            "asset": item.get("asset"),
            "report_id": item.get("report_id"),
            "intercept_id": item.get("id"),
            "requires_choice": False,
            "status": "resolved",
        }
        self.story_events.append(entry)
        if len(self.story_events) > EVENT_LOG_LIMIT:
            self.story_events = self.story_events[-EVENT_LOG_LIMIT:]
        return entry

    def _record_narrative(self, kind, **fields):
        """Записать факт симуляции в структурированный журнал хроники.

        Здесь нет текста и сюжетных решений: только кто, к кому, каким
        механизмом, с каким результатом и какие дельты состояния он
        оставил. Текст эпизода собирает ``campaign.chronicle`` из этих
        полей.

        У каждой записи есть ``id``, а у следствия — ``cause_id``. Это
        позволяет хронике собрать цепочку «это произошло потому, что»,
        а не только «это случилось рядом».
        """

        fields.pop("id", None)
        cause_id = str(
            fields.pop("cause_id", "")
            or getattr(self, "_narrative_cause", "")
            or ""
        )
        cause_label = str(fields.pop("cause_label", "") or "")
        if cause_id and not cause_label:
            for item in reversed(self.narrative):
                if str(item.get("id") or "") == cause_id:
                    cause_label = str(item.get("label") or "")
                    break
        turn = int(self.turn)
        seq = 1
        prefix = "n-%d-" % turn
        for item in reversed(self.narrative):
            if int(_number(item.get("turn"), 0)) != turn:
                continue
            record_id = str(item.get("id") or "")
            if not record_id.startswith(prefix):
                continue
            try:
                seq = int(record_id.rsplit("-", 1)[1]) + 1
            except (IndexError, ValueError):
                pass
            break
        record = narrative_record(
            kind,
            turn,
            id=prefix + str(seq),
            cause_id=cause_id,
            cause_label=cause_label,
            elapsed=self.elapsed,
            **fields,
        )
        self.narrative.append(record)
        if len(self.narrative) > MAX_NARRATIVE:
            self.narrative = self.narrative[-MAX_NARRATIVE:]
        return record

    def _narrative_id_for_report(self, report_id):
        """Найти запись хроники, порождённую докладом."""

        report_id = str(report_id or "")
        if not report_id:
            return ""
        for item in reversed(self.narrative):
            if str(item.get("report_id") or "") == report_id:
                return str(item.get("id") or "")
        return ""

    def _record_report_event(self, report):
        """Положить доклад в повествовательную ленту кампании."""
        entry = {
            "id": report.get("id"),
            "template_id": "report",
            "category": "report",
            "title": report.get("title") or "Доклад",
            "text": report.get("text") or "",
            "severity": None,
            "stakes": None,
            "speed": "instant",
            "duration": 0.0,
            "elapsed": report.get("created"),
            "visible": True,
            "visibility": {},
            "effects": {},
            "turn": self.turn,
            "side": report.get("side"),
            "source_id": report.get("source_id"),
            "source_name": report.get("source_name"),
            "asset": report.get("asset"),
            "report_id": report.get("id"),
            "requires_choice": True,
            "status": report.get("status"),
            "choices": [dict(item) for item in report.get("choices") or ()],
        }
        self.story_events.append(entry)
        if len(self.story_events) > EVENT_LOG_LIMIT:
            self.story_events = self.story_events[-EVENT_LOG_LIMIT:]
        return entry

    def _sync_report_event(self, report):
        """Обновить статус доклада и выпустить вести о чужих фракциях."""
        report_id = str(report.get("id") or "")
        entry = None
        for item in self.story_events:
            if str(item.get("report_id") or "") != report_id:
                continue
            item["status"] = report.get("status")
            item["resolved"] = report.get("resolved")
            entry = item
            break
        if (
            entry is not None
            and str(report.get("side") or "") != str(self.player_side)
            and str(report.get("status") or "") == "resolved"
        ):
            self._record_third_party_news(report)
        return entry

    def _record_third_party_news(self, report):
        """Новость о решении чужой фракции приходит с задержкой.

        Игрок не видит чужие доклады напрямую: он узнаёт о них позже и
        только в общих чертах. Запись живёт в ``story_events`` без
        выбора, поэтому попадает в информационную ленту, а не в окно
        решений.
        """
        config = getattr(self.dispatch, "news_config", {}) or {}
        if not bool(config.get("enabled", True)):
            return None
        news_id = "news-%s" % str(report.get("id") or "")
        for entry in self.story_events:
            if str(entry.get("id") or "") == news_id:
                return entry
        faction = self.faction(report.get("side"))
        faction_name = str(
            getattr(faction, "name", "") or report.get("side") or ""
        )
        choice = str(report.get("choice") or "")
        if choice and choice not in ("verify", "trust", "ignore"):
            if "verify" in choice:
                choice = "verify"
            elif "trust" in choice:
                choice = "trust"
            elif "ignore" in choice:
                choice = "ignore"
        texts = config.get("texts")
        texts = texts if isinstance(texts, Mapping) else {}
        template = str(
            texts.get(choice)
            or "{faction} приняла решение по докладу о «{asset_label}»."
        )
        asset_label = str(report.get("asset_label") or "")
        text = (
            template.replace("{faction}", faction_name)
            .replace("{asset_label}", asset_label)
            .replace("{side}", str(report.get("side") or ""))
        )
        title_template = str(config.get("title") or "Вести: {faction}")
        title = title_template.replace("{faction}", faction_name)
        delay = max(
            0.0, float(config.get("delay_seconds") or 0.0)
        )
        entry = {
            "id": news_id,
            "template_id": "news",
            "category": "news",
            "title": title,
            "text": text,
            "severity": None,
            "stakes": None,
            "speed": "instant",
            "duration": 0.0,
            "elapsed": float(self.elapsed),
            "release_at": float(self.elapsed) + delay,
            "visible": True,
            "visibility": {},
            "effects": {},
            "turn": self.turn,
            "side": str(report.get("side") or ""),
            "faction_id": str(getattr(faction, "id", "") or ""),
            "source_id": "",
            "source_name": faction_name,
            "asset": report.get("asset"),
            "report_id": report.get("id"),
            "requires_choice": False,
            "status": "resolved",
        }
        self.story_events.append(entry)
        if len(self.story_events) > EVENT_LOG_LIMIT:
            self.story_events = self.story_events[-EVENT_LOG_LIMIT:]
        return entry

    def staff_briefing(self, side=None):
        """Сводка начальника штаба для правой панели."""
        briefing = getattr(self.dispatch, "briefing", None)
        if not callable(briefing):
            return {"chief": "", "lines": []}
        return briefing(side)

    def _advance_story_events(self, seconds):
        if self.finished or self.story_engine is None:
            return []
        # Контекст события — дорогой срез всех персонажей и органов.
        # Строим его только когда событие действительно может сработать,
        # а не каждый кадр: ``advance`` нужен лишь для хода времени.
        self.story_engine.advance(seconds)
        self._story_progress += max(0.0, float(seconds))
        interval = max(4.0, self.organization_interval_seconds * 0.5)
        spawned = []
        context = None
        render_context = None
        while self._story_progress >= interval:
            self._story_progress -= interval
            if context is None:
                context = self._story_context()
                # Условия читают структуры (активы, органы, ростер), а
                # тексту нужны только имена. Разделяем, чтобы словари не
                # попадали в подстановки и в контекст события.
                render_context = {
                    key: context[key]
                    for key in (
                        "actor",
                        "target",
                        "rival",
                        "fallen",
                        "organization",
                        "rival_organization",
                    )
                    if context.get(key)
                }
            instance = self.story_engine.trigger(
                context=context, render_context=render_context
            )
            if instance is None:
                continue
            # Ролевой слой только фиксирует событие. Никаких записей в
            # состояние: на состояние влияют работы и автоматы.
            applied = {}
            entry = {
                "id": instance.id,
                "template_id": instance.template_id,
                "category": instance.category,
                "title": instance.title,
                "text": instance.text,
                "severity": instance.severity,
                "stakes": instance.stakes,
                "speed": instance.speed,
                "duration": instance.duration,
                "elapsed": instance.elapsed,
                "visible": instance.mature,
                "visibility": instance.visibility.as_dict(),
                "effects": applied,
                "turn": self.turn,
            }
            self.story_events.append(entry)
            spawned.append(entry)
        if len(self.story_events) > EVENT_LOG_LIMIT:
            self.story_events = self.story_events[-EVENT_LOG_LIMIT:]
        return spawned
