"""Должности, рынок труда, карьера, увольнения и автономные намерения."""

from __future__ import annotations

from .world_support import (
    AUTONOMY_AFFINITY_THRESHOLD,
    AUTONOMY_BASE_CHANCE,
    AUTONOMY_PERIOD,
    AUTONOMY_TRUST_THRESHOLD,
    DOMAIN_SKILLS,
    LABOR_NEGOTIATION_BASE_LOGIT,
    LABOR_NEGOTIATION_FAILURE_AFFINITY,
    LABOR_NEGOTIATION_FAVOR,
    LABOR_NEGOTIATION_INFLUENCE,
    LABOR_NEGOTIATION_MARGIN_WEIGHT,
    LABOR_NEGOTIATION_RELATION_WEIGHT,
    LABOR_NEGOTIATION_RETRY_BONUS,
    LABOR_NEGOTIATION_RETRY_BONUS_MAX,
    LABOR_NEGOTIATION_SUCCESS_AFFINITY,
    SLOTS_MAX,
    SLOT_DAY_EDGE,
    _AUTONOMY_POLICIES,
    _as_float,
    _as_int,
    _as_slot,
    _clamp,
    _profile_connection_strength,
    _profile_skill,
    _text,
    campaign_success_chance,
    condition_holds,
    math,
    metric_word,
    office_profile_status,
    success_margin,
)


class WorldCareerMixin:

    def office_templates_for_node(self, node):
        if not node:
            return []
        result = []
        for office in self.offices.values():
            if office.get("domain") != node.get("domain"):
                continue
            levels = office.get("levels") or []
            if node.get("level") not in levels and "*" not in levels:
                continue
            result.append(office)
        return sorted(
            result,
            key=lambda item: (
                _as_int(item.get("rank"), 99),
                -_as_float(item.get("authority"), 0.0),
                item["id"],
            ),
        )

    def office_label(self, office_id):
        office = self.offices.get(_text(office_id)) or {}
        return _text(office.get("label"), office_id)

    def head_office_for_node(self, node):
        templates = self.office_templates_for_node(node)
        if not templates:
            return None
        return templates[0]

    def _office_authority(self, office, node, is_player=True):
        base = _as_float(office.get("authority"), 0.5)
        if not is_player:
            return _clamp(base)
        skill_key = _text(office.get("skill"))
        skill = _profile_skill(self.profile, skill_key)
        connection = _profile_connection_strength(
            self.profile,
            office.get("connection_kinds") or (),
        )
        return _clamp(base + 0.18 * skill + 0.10 * connection)

    def _vacancy_competition(self, node, office):
        """Очередь кандидатов на должность и шанс игрока в ней.

        Очередь детерминирована seed'ом, блоком дней и id должности.
        Кандидаты — живые персонажи того же домена; состав блока
        перемешивается, поэтому между блоками кто-то приходит, а кто-то
        уходит. Межструктурная квота не даёт одной структуре занять всю
        очередь. При нехватке добавляются внешние претенденты.

        Игрок сравнивается с лучшим кандидатом по навыку, репутации и
        связям. При проигрыше вакансия считается закрытой, и карьерное
        действие недоступно без списания ресурсов.
        """
        settings = self.labor_market
        rank = _as_int(office.get("rank"), 99)
        bonus = max(0, 5 - rank) * settings["rank_bonus"]
        refresh_days = max(1, _as_int(settings["refresh_days"], 1))
        generation = self.day // refresh_days
        rivals_count = max(0, _as_int(settings["rivals"], 0))
        quota_by_key = settings.get("quota") or {}
        quota = max(
            0,
            _as_int(
                quota_by_key.get(node["id"])
                or quota_by_key.get(node.get("domain"))
                or rivals_count,
                rivals_count,
            ),
        )
        pool = []
        for character in self.characters.values():
            if not character.get("alive"):
                continue
            character_node = self.node(character.get("node_id"))
            if (
                character_node is None
                or character_node.get("domain") != node.get("domain")
            ):
                continue
            roll = self._roll(
                "labor:%s:%s:%s"
                % (generation, office["id"], character["id"])
            )
            pool.append(
                {
                    "id": character["id"],
                    "name": character["name"],
                    "node_id": character_node["id"],
                    "structure": character_node["name"],
                    "roll": roll,
                    "score": _clamp(
                        settings["rival_base"]
                        + settings["rival_spread"] * roll
                        + bonus
                    ),
                }
            )
        pool.sort(key=lambda item: (-item["roll"], item["id"]))
        structure_quota = max(
            0, _as_int(settings.get("structure_quota"), 0)
        )
        rivals = []
        per_structure = {}
        for candidate in pool:
            key = candidate["node_id"]
            if (
                structure_quota
                and per_structure.get(key, 0) >= structure_quota
            ):
                continue
            per_structure[key] = per_structure.get(key, 0) + 1
            rivals.append(candidate)
            if len(rivals) >= rivals_count:
                break
        rivals.sort(key=lambda item: (-item["score"], item["id"]))
        for index in range(len(rivals), rivals_count):
            roll = self._roll(
                "labor:%s:%s:external:%s"
                % (generation, office["id"], index)
            )
            rivals.append(
                {
                    "id": "external:%s" % index,
                    "name": "Внешний претендент",
                    "node_id": "",
                    "structure": "внешняя",
                    "roll": roll,
                    "score": _clamp(
                        settings["rival_base"]
                        + settings["rival_spread"] * roll
                        + bonus
                    ),
                }
            )
        rivals.sort(key=lambda item: (-item["score"], item["id"]))
        withdrawn = self._withdrawn_rivals(office["id"], generation)
        if withdrawn:
            rivals = [
                item for item in rivals if item["id"] not in withdrawn
            ]
        skill_key = _text(office.get("skill"))
        if skill_key:
            skill = _profile_skill(self.profile, skill_key)
        else:
            domain_skills = DOMAIN_SKILLS.get(node.get("domain"), ())
            skill = sum(
                _profile_skill(self.profile, key) for key in domain_skills
            ) / max(1, len(domain_skills))
        standing = _as_float(self.player_resources.get("standing"), 0.0)
        connection = _profile_connection_strength(
            self.profile,
            office.get("connection_kinds")
            or node.get("tags")
            or (node.get("domain"),),
        )
        player_score = _clamp(
            settings["skill_weight"] * skill
            + settings["standing_weight"] * standing
            + settings["connection_weight"] * connection
        )
        best_rival = max(
            (item["score"] for item in rivals),
            default=0.0,
        )
        return {
            "office_id": office["id"],
            "rank": rank,
            "generation": generation,
            "refresh_days": refresh_days,
            "refresh_in": refresh_days - (self.day % refresh_days),
            "rivals": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "node_id": item["node_id"],
                    "structure": item["structure"],
                    "score": item["score"],
                }
                for item in rivals
            ],
            "player_score": player_score,
            "player_skill": _clamp(skill),
            "player_standing": _clamp(standing),
            "player_connection": _clamp(connection),
            "best_rival": best_rival,
            "available": player_score + 1e-9 >= best_rival,
        }

    def _labor_round(self, office_id):
        return self.labor_negotiations.setdefault(_text(office_id), {})

    def _withdrawn_rivals(self, office_id, generation):
        """Соперники, снявшие кандидатуру в текущем поколении очереди."""
        state = self._labor_round(office_id)
        withdrawn = set()
        for rival_id, record in state.items():
            if _as_int(record.get("generation"), -1) != generation:
                continue
            if record.get("withdrawn"):
                withdrawn.add(rival_id)
        return withdrawn

    def _labor_negotiation(self, office_id, rival_id):
        return self._labor_round(office_id).get(_text(rival_id))

    @staticmethod
    def _negotiation_chance(
        player_score, rival_score, relation=0.0, attempts=0
    ):
        """Шанс переговоров: сила позиции, отношение и накопленный опыт.

        Каждая предыдущая неудачная попытка в том же поколении даёт
        небольшой бонус (соперник уже вовлечён в разговор), но не больше
        `LABOR_NEGOTIATION_RETRY_BONUS_MAX`.
        """
        margin = float(player_score) - float(rival_score)
        bonus = min(
            LABOR_NEGOTIATION_RETRY_BONUS_MAX,
            LABOR_NEGOTIATION_RETRY_BONUS * max(0, _as_int(attempts, 0)),
        )
        logit = (
            LABOR_NEGOTIATION_BASE_LOGIT
            + LABOR_NEGOTIATION_MARGIN_WEIGHT * margin
            + LABOR_NEGOTIATION_RELATION_WEIGHT * float(relation)
            + bonus
        )
        return max(0.05, min(0.95, 1.0 / (1.0 + math.exp(-logit))))

    def labor_negotiation_offer(self, office_id, rival_id):
        """Публичный прогноз переговоров без списания ресурсов.

        Возвращает причину недоступности, стоимость, шанс и самого
        соперника. UI и `negotiate_rival()` видят один и тот же расчёт.
        """
        office_id = _text(office_id)
        rival_id = _text(rival_id)
        if self.finished:
            return {"available": False, "reason": "кампания завершена"}
        if not self.attached:
            return {"available": False, "reason": "сначала выберите должность"}
        options = {
            item["id"]: item
            for item in self.office_options(self.player_node_id)
        }
        option = options.get(office_id)
        if option is None:
            return {
                "available": False,
                "reason": "должность не относится к вашей структуре",
            }
        competition = option.get("competition") or {}
        rival = next(
            (
                item
                for item in competition.get("rivals") or ()
                if item.get("id") == rival_id
            ),
            None,
        )
        if rival is None:
            return {
                "available": False,
                "reason": "этот соперник уже не участвует в очереди",
            }
        if rival_id.startswith("external:"):
            return {
                "available": False,
                "reason": "внешний претендент не выходит на переговоры",
                "rival": rival,
            }
        if self.actions_left <= 0:
            return {
                "available": False,
                "reason": "не осталось действий на сегодня",
                "rival": rival,
            }
        influence = _as_float(self.player_resources.get("influence"), 0.0)
        favor = _as_float(self.player_resources.get("favor"), 0.0)
        cost = {
            "influence": LABOR_NEGOTIATION_INFLUENCE,
            "favor": LABOR_NEGOTIATION_FAVOR,
        }
        if influence + 1e-9 < cost["influence"]:
            return {
                "available": False,
                "reason": "недостаточно влияния",
                "rival": rival,
                "cost": cost,
            }
        if favor + 1e-9 < cost["favor"]:
            return {
                "available": False,
                "reason": "недостаточно связей",
                "rival": rival,
                "cost": cost,
            }
        record = self._labor_negotiation(office_id, rival_id) or {}
        relation = 0.0
        character = self.character(rival_id)
        if character is not None:
            relation = self.character_relation(rival_id)
        overdue = self._overdue_negotiation_penalty(rival_id)
        relation -= overdue["penalty"]
        chance = self._negotiation_chance(
            competition.get("player_score", 0.0),
            rival.get("score", 0.0),
            relation=relation,
            attempts=record.get("attempts", 0),
        )
        return {
            "available": True,
            "reason": "",
            "overdue": overdue,
            "office_id": office_id,
            "office_label": option.get("label", office_id),
            "rival": rival,
            "player_score": competition.get("player_score", 0.0),
            "best_rival": competition.get("best_rival", 0.0),
            "chance": chance,
            "cost": cost,
            "generation": competition.get("generation", 0),
        }

    def negotiate_rival(self, office_id, rival_id):
        """Переговоры с конкретным соперником на рынке труда (§7.5 №29).

        Стоит одно действие дня и немного влияния/связей. Успех снимает
        кандидатуру соперника до следующего поколения очереди и улучшает
        отношение; провал ухудшает отношение и оставляет соперника в
        очереди. Исход детерминирован seed'ом, днём, должностью и номером
        попытки.
        """
        offer = self.labor_negotiation_offer(office_id, rival_id)
        if not offer.get("available"):
            return {"ok": False, "reason": offer.get("reason", "")}
        office_id = offer["office_id"]
        rival_id = _text(rival_id)
        cost = offer.get("cost") or {}
        changed = self._apply_player_map(
            {
                "influence": -_as_float(cost.get("influence"), 0.0),
                "favor": -_as_float(cost.get("favor"), 0.0),
            }
        )
        record = self._labor_round(office_id).setdefault(rival_id, {})
        generation = _as_int(offer.get("generation"), 0)
        if _as_int(record.get("generation"), -1) != generation:
            record.clear()
            record["generation"] = generation
            record["attempts"] = 0
        attempts = _as_int(record.get("attempts"), 0)
        relation = 0.0
        character = self.character(rival_id)
        if character is not None:
            relation = self.character_relation(rival_id)
        chance = offer["chance"]
        roll = self._roll(
            "negotiation:%s:%s:%s:%s:%d"
            % (self.seed, self.day, office_id, rival_id, attempts)
        )
        success = roll < chance
        record["attempts"] = attempts + 1
        record["chance"] = chance
        if success:
            record["withdrawn"] = True
            record["withdrawn_day"] = self.day
            if character is not None:
                changed.extend(
                    self._apply_character_effects(
                        {
                            "affinity": LABOR_NEGOTIATION_SUCCESS_AFFINITY,
                            "trust": LABOR_NEGOTIATION_SUCCESS_AFFINITY / 2.0,
                        },
                        character,
                    )
                )
            text = "%s снял(а) кандидатуру: вы договорились." % (
                offer["rival"]["name"]
            )
            outcome = "success"
        else:
            if character is not None:
                changed.extend(
                    self._apply_character_effects(
                        {
                            "affinity": LABOR_NEGOTIATION_FAILURE_AFFINITY,
                            "trust": LABOR_NEGOTIATION_FAILURE_AFFINITY / 2.0,
                        },
                        character,
                    )
                )
            text = "%s отказался(ась) снимать кандидатуру." % (
                offer["rival"]["name"]
            )
            outcome = "failure"
        self.player.spend_action()
        self.action_count += 1
        self.log.append(
            {
                "day": self.day,
                "kind": "negotiation",
                "text": "%s → %s: %s"
                % (offer["office_label"], offer["rival"]["name"], text),
            }
        )
        result = {
            "ok": True,
            "context": "labor_market",
            "action": "negotiate_rival",
            "action_label": "Переговоры с соперником",
            "target": rival_id,
            "target_label": offer["rival"]["name"],
            "office_id": office_id,
            "outcome": outcome,
            "chance": chance,
            "text": text,
            "changes": self._merge_changes(changed),
            "day": self.day,
        }
        self.last_result = result
        return result

    def vacancy_board(self, node_id=None):
        """Публичная доска вакансий: все должности или один узел.

        API нужен UI и калибровке, чтобы показать не только флаг
        доступности, но и очередь, силу игрока и момент обновления.
        Форма записи стабильна и не зависит от внутренних ключей оценки.
        """
        nodes = [self.node(node_id)] if node_id else list(
            self.sorted_nodes()
        )
        board = []
        for node in nodes:
            if node is None:
                continue
            for option in self.office_options(node["id"]):
                board.append(
                    {
                        "node_id": node["id"],
                        "node_name": node["name"],
                        "office_id": option["id"],
                        "label": option["label"],
                        "rank": option["rank"],
                        "enabled": option["enabled"],
                        "reason": option["reason"],
                        "competition": option["competition"],
                    }
                )
        return board

    def office_options(self, node_id):
        node = self.node(node_id)
        if node is None:
            return []
        result = []
        for office in self.office_templates_for_node(node):
            enabled, reason = office_profile_status(
                self.profile, office, self.skill_labels
            )
            result.append(
                {
                    "office": office,
                    "id": office["id"],
                    "label": _text(office.get("label"), office["id"]),
                    "enabled": enabled,
                    "reason": reason,
                    "authority": self._office_authority(office, node),
                    "rank": _as_int(office.get("rank"), 99),
                    "competition": self._vacancy_competition(node, office),
                }
            )
        return result

    def _career_target_available(self, action, target):
        if not target:
            return False, "нужна цель"
        office_kind = action.get("career")
        if office_kind not in ("promote", "transfer"):
            return True, ""
        options = self.office_options(target["id"])
        if not options:
            return False, "в цели нет подходящей должности"
        if office_kind == "promote":
            current_rank = _as_int(
                self.offices.get(self.player_office_id, {}).get("rank"), 99
            )
            candidates = [
                item
                for item in options
                if item.get("enabled") and item["rank"] < current_rank
            ]
            if not candidates:
                return False, "нет вакансии выше вашей должности"
        else:
            candidates = [item for item in options if item.get("enabled")]
            if not candidates:
                return False, "нет доступной должности в цели"
        competitive = [
            item
            for item in candidates
            if (item.get("competition") or {}).get("available", True)
        ]
        if not competitive:
            best = max(
                candidates,
                key=lambda item: (
                    (item.get("competition") or {}).get("best_rival", 0.0)
                ),
            )
            competition = best.get("competition") or {}
            rival = (competition.get("rivals") or [{}])[0]
            return (
                False,
                "очередь кандидатов сильнее: %s (ваше положение: %s, "
                "соперник: %s)"
                % (
                    rival.get("name", "другой претендент"),
                    metric_word(
                        "положение",
                        competition.get("player_score", 0.0),
                    ),
                    metric_word(
                        "положение",
                        competition.get("best_rival", 0.0),
                    ),
                ),
            )
        return True, ""

    def _career_transition(self, action, target):
        kind = action.get("career")
        if kind == "resign":
            return self._dismiss(
                "добровольная отставка",
                kind="resign",
                auto_reassign=False,
            )
        if kind not in ("promote", "transfer") or target is None:
            return ""
        options = [
            item
            for item in self.office_options(target["id"])
            if item.get("enabled")
            and (item.get("competition") or {}).get("available", True)
        ]
        if kind == "promote":
            current_rank = _as_int(
                self.offices.get(self.player_office_id, {}).get("rank"), 99
            )
            options = [item for item in options if item["rank"] < current_rank]
        if not options:
            return "Вакансия не открылась."
        chosen = sorted(
            options,
            key=lambda item: (item["rank"], -item["authority"]),
        )[0]
        previous_node = self.player_node_id
        previous_office = self.player_office_id
        self.player_node_id = target["id"]
        self.player_office_id = chosen["id"]
        self.player_authority = chosen["authority"]
        self._refresh_items()
        self.career_history.append(
            {
                "day": self.day,
                "kind": kind,
                "from": previous_node,
                "to": target["id"],
                "office_from": previous_office,
                "office_to": chosen["id"],
            }
        )
        self.log.append(
            {
                "day": self.day,
                "kind": "career",
                "text": "Новая должность: %s в структуре %s."
                % (chosen["label"], target["name"]),
            }
        )
        return "Новая должность: %s." % chosen["label"]

    def _replacement_office(self, node_id, previous_office):
        """Найти другую доступную должность в той же структуре.

        Первый срез смены роли (§7 №29) — не полноценный рынок труда, а
        немедленный перевод внутри структуры. Если другой должности нет,
        игрок остаётся вне службы и может выбрать роль через UI.
        """
        previous = _text(previous_office)
        options = [
            item
            for item in self.office_options(node_id)
            if item.get("enabled") and item["id"] != previous
        ]
        if not options:
            return None
        options.sort(
            key=lambda item: (
                item["rank"],
                -_as_float(item.get("authority"), 0.0),
                item["id"],
            )
        )
        return options[0]

    def _dismiss(self, reason, kind="dismiss", auto_reassign=True):
        """Снять игрока с должности, не завершая кампанию (§7 №29).

        Возвращает текст для журнала/результата. При `auto_reassign=True`
        игрок сразу получает другую роль в той же структуре, если она есть;
        иначе остаётся `attached=False` и может выбрать должность в UI.
        """
        if not self.attached:
            return ""
        previous_node = self.player_node_id
        previous_office = self.player_office_id
        previous_label = self.office_label(previous_office)
        self.attached = False
        self.dismissed = True
        self.dismissal_count += 1
        self.last_role_change_day = self.day
        self.player_office_id = ""
        self.player_authority = 0.0
        self._refresh_items()
        self.career_history.append(
            {
                "day": self.day,
                "kind": kind,
                "from": previous_node,
                "to": "",
                "office_from": previous_office,
                "reason": str(reason or ""),
            }
        )
        self.log.append(
            {
                "day": self.day,
                "kind": kind,
                "text": "Потеряна должность «%s»: %s."
                % (previous_label, reason or "смена роли"),
            }
        )
        if not auto_reassign:
            return "Вы оставили должность. История продолжается."
        replacement = self._replacement_office(
            previous_node, previous_office
        )
        if replacement is None:
            return "Вы потеряли должность. Вы вне службы."
        result = self.attach(previous_node, replacement["id"])
        if not result.get("ok"):
            return "Вы потеряли должность. Вы вне службы."
        self.career_history.append(
            {
                "day": self.day,
                "kind": "reassign",
                "from": previous_node,
                "to": previous_node,
                "office_from": previous_office,
                "office_to": replacement["id"],
                "reason": str(reason or ""),
            }
        )
        self.log.append(
            {
                "day": self.day,
                "kind": "career",
                "text": "Новая роль: %s в структуре %s."
                % (replacement["label"], self.node(previous_node)["name"]),
            }
        )
        return "Новая роль: %s." % replacement["label"]

    def _check_dismissal(self):
        """Проверить распад организации и смену роли (§7 №28–29).

        Имя сохранено ради совместимости с вызовами из `execute`/`end_day`,
        но терминального «увольнения» здесь больше нет: потеря должности —
        смена роли, а не `lose`.
        """
        if self.finished:
            return
        if not self.attached:
            if self._collapse_day != self.day:
                self.collapse_days = 0
                self._collapse_day = self.day
            return
        node = self.node(self.player_node_id)
        if node is None:
            self.outcome = "lose"
            self.finished = True
            self.collapsed = True
            self.log.append(
                {
                    "day": self.day,
                    "kind": "collapse",
                    "text": "Структура исчезла: организация распалась.",
                }
            )
            return
        power = float(node["stats"]["power"])
        cohesion = float(node["stats"]["cohesion"])
        strain = (
            power <= self.collapse_min_power
            or cohesion <= self.collapse_min_cohesion
        )
        total_collapse = power <= 0.0 and cohesion <= 0.0
        if total_collapse:
            self.outcome = "lose"
            self.finished = True
            self.collapsed = True
            self.log.append(
                {
                    "day": self.day,
                    "kind": "collapse",
                    "text": "Организация распалась: сила и связность "
                    "обнулились.",
                }
            )
            return
        if self._collapse_day != self.day:
            self._collapse_day = self.day
            if strain:
                self.collapse_days += 1
            else:
                if self.collapse_days:
                    self.log.append(
                        {
                            "day": self.day,
                            "kind": "recovery",
                            "text": "Организация восстановилась выше порога "
                            "распада.",
                        }
                    )
                self.collapse_days = 0
        if self.collapse_days >= self.collapse_grace_days:
            self.outcome = "lose"
            self.finished = True
            self.collapsed = True
            self.log.append(
                {
                    "day": self.day,
                    "kind": "collapse",
                    "text": "Организация распалась: сила или связность "
                    "пробыли ниже порога %d дн." % self.collapse_days,
                }
            )
            return
        if self._dismissal_day == self.day:
            return
        if (
            self.day - int(self.last_role_change_day)
            < self.role_change_cooldown_days
        ):
            return
        if self.player_resources["standing"] <= self.dismissal_standing:
            self._dismissal_day = self.day
            self._dismiss("потеря опоры и репутации")
        elif node["stats"]["legitimacy"] <= self.dismissal_legitimacy:
            self._dismissal_day = self.day
            self._dismiss("структура потеряла легитимность")

    def schedule_intent(
        self,
        due_day,
        kind,
        actor="",
        target="",
        payload=None,
        source="world",
        priority=0,
        cancel_when=None,
        due_slot=0,
    ):
        """Отложить событие мира на будущий день.

        Возвращает `Intent` или `None`, если очередь переполнена. Это
        единственный вход планировщика: сюжет, персонажи и тесты назначают
        события одинаково, а исполнение всегда идёт через `_run_intents()`.
        `priority` задаёт порядок внутри дня (больше = раньше),
        `cancel_when` — условие отмены по легаси-полям актёра,
        `due_slot` — слот внутри дня (0 — граница дня; 1..3 — порядок
        «внутри» очереди того же дня, A5).
        """
        return self.intents.schedule(
            due_day,
            kind,
            actor=actor,
            target=target,
            payload=payload,
            source=source,
            priority=priority,
            cancel_when=cancel_when,
            due_slot=due_slot,
        )

    def schedule_action(
        self, action_id, target_id=None, due_day=None, priority=0, due_slot=0
    ):
        """Запланировать действие игрока на будущий день (A5).

        Непрерывность планирования: игрок тратит энергию только в момент
        исполнения, поэтому «поставить дело в очередь» не стоит ресурсов,
        но и не гарантирует исход — к наступлению срока мир мог измениться
        (увольнение, смерть, кончилось время кампании). В начале `due_day`
        намерение проходит полный путь `execute()`: те же проверки, та же
        цена, тот же детерминированный бросок (`action_count` в токене
        ролла продолжает расти монотонно). Если действие к сроку
        недоступно, оно снимается с записью в журнал — без штрафа.

        Возвращает `Intent` или `None` (переполнение очереди).
        """
        action_id = _text(action_id)
        if action_id not in self.actions:
            return None
        day = self.day + 1 if due_day is None else max(1, _as_int(due_day, 1))
        if day < self.day:
            return None
        if day == self.day and _as_slot(due_slot) == SLOT_DAY_EDGE:
            pass
        return self.schedule_intent(
            day,
            "action",
            actor="player",
            target=_text(target_id),
            payload={"action": action_id, "target": _text(target_id)},
            source="player",
            priority=priority,
            due_slot=due_slot,
        )

    def _run_overdue(self):
        """Исполнить долги: `due_day < self.day`, в порядке слотов.

        Просроченное намерение затухало бы в очереди, пока ИИ делает ход
        по устаревшему миру, поэтому `end_day()` и `tick()` закрывают их
        первыми. Долг уже опоздал — день исполнения не выбирается «виртуально»,
        событие стоит в журнале под текущим днём; порядок внутри долгов
        сохраняется по слотам (`SLOT_DAY_EDGE` — сначала краевые). Намерения
        наступающих суток (`due_day == self.day`) здесь не берутся — они
        исполняются `_run_intents()`.
        """
        ready = [
            item for item in self.intents.items if item.due_day < self.day
        ]
        if not ready:
            return []
        ready_ids = {id(item) for item in ready}
        self.intents.items = [
            item for item in self.intents.items if id(item) not in ready_ids
        ]
        events = []
        for intent in sorted(
            ready, key=lambda item: (_as_slot(item.due_slot), -item.priority)
        ):
            events.extend(self._fire_intent(intent))
        return events

    def _fire_intent(self, intent):
        """Отмена по условию + исполнение одного намерения."""
        if intent.cancel_when:
            character = self.character(intent.actor) if intent.actor else None
            if condition_holds(intent.cancel_when, character):
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "intent_cancelled",
                        "text": "Намерение отменено: условие не выполнено.",
                    }
                )
                return [
                    {
                        "kind": "intent_cancelled",
                        "day": self.day,
                        "source": intent.source,
                        "target": intent.actor,
                        "text": "намерение снято по условию",
                        "changes": [],
                    }
                ]
        return self._apply_intent(intent)

    def _run_intents(self, max_slot=SLOTS_MAX, day=None):
        """Исполнить намерения, срок которых наступил.

        `max_slot` (A5) ограничивает исполнение слотами внутри дня:
        планировщик дня (`end_day`) вызывает метод с полным значением,
        а будущие внутридневные тики смогут выбрать только часть очереди.
        Просроченные намерения всегда исполняются первыми (слот 0).
        `day` — день выборки очереди; по умолчанию «день после текущих
        суток»: намерение со сроком «день N» исполняется в начале дня N,
        поэтому очередь выбирается строго до инкремента `self.day`.
        """
        events = []
        target_day = self.day if day is None else day
        window = _as_slot(max_slot)
        overdue = [
            item for item in self.intents.items if item.due_day < target_day
        ]
        due_today = [
            item
            for item in self.intents.items
            if item.due_day == target_day
            and (_as_slot(item.due_slot) <= window or window >= SLOTS_MAX)
        ]
        if window >= SLOTS_MAX:
            ready = overdue + due_today
        else:
            ready = [
                item
                for item in overdue
                if _as_slot(item.due_slot) <= window
            ]
            ready += due_today
        if not ready:
            return events
        ready_ids = {id(item) for item in ready}
        self.intents.items = [
            item for item in self.intents.items if id(item) not in ready_ids
        ]
        for intent in sorted(
            ready, key=lambda item: (-item.priority, _as_slot(item.due_slot))
        ):
            events.extend(self._fire_intent(intent))
        return events

    def _apply_intent(self, intent):
        if intent.kind == "message":
            text = _text(
                intent.payload.get("text"), "Событие мира без последствий."
            )
            self.log.append(
                {"day": self.day, "kind": "intent", "text": text}
            )
            return [
                {
                    "kind": "intent",
                    "day": self.day,
                    "source": intent.source,
                    "target": "",
                    "text": text,
                    "changes": [],
                }
            ]
        if intent.kind == "contact":
            if intent.source == "autonomy":
                return self._apply_autonomy_contact(intent)
            character = self.character(intent.actor)
            if character is None or not character.get("alive", True):
                return []
            effects = intent.payload.get("effects") or {}
            changed = self._apply_character_effects(effects, character)
            text = _text(
                intent.payload.get("text"),
                "%s сам(а) выходит на связь." % character["name"],
            )
            self.log.append(
                {
                    "day": self.day,
                    "kind": "contact",
                    "text": "%s: %s" % (character["name"], text),
                }
            )
            return [
                {
                    "kind": "intent",
                    "day": self.day,
                    "source": intent.source,
                    "target": character["id"],
                    "actor": character["id"],
                    "text": text,
                    "changes": changed,
                }
            ]
        if intent.kind == "action":
            day_saved = self.day
            if intent.due_day < day_saved:
                self.day = intent.due_day
            try:
                return self._apply_action_intent(intent)
            finally:
                self.day = day_saved
        return []

    def _apply_action_intent(self, intent):
        """Исполнить отложенное действие игрока через полный путь `execute()`.

        Вынесен в отдельный метод, чтобы `_apply_intent` оставался
        диспетчером по видам намерений, а виртуальный «день срока»
        (см. `_apply_intent`) корректно оборачивал и успех, и отказ.
        """
        if self.finished or not self.player_alive:
            text = "Отложенное дело не состоялось: герой вне игры."
            self.log.append(
                {"day": self.day, "kind": "intent_skipped", "text": text}
            )
            return [
                {
                    "kind": "intent_skipped",
                    "day": self.day,
                    "source": intent.source,
                    "target": _text(intent.target),
                    "text": text,
                    "changes": [],
                }
            ]
        result = self.execute(
            _text(intent.payload.get("action")),
            _text(intent.payload.get("target")) or None,
        )
        if not result.get("ok"):
            text = "Отложенное дело не состоялось: %s" % _text(
                result.get("reason"), "действие недоступно"
            )
            self.log.append(
                {"day": self.day, "kind": "intent_skipped", "text": text}
            )
            return [
                {
                    "kind": "intent_skipped",
                    "day": self.day,
                    "source": intent.source,
                    "target": _text(result.get("target")),
                    "text": text,
                    "changes": [],
                }
            ]
        return [
            {
                "kind": "intent",
                "day": self.day,
                "source": "player_action",
                "target": result["target"],
                "actor": "player",
                "action": result["action"],
                "outcome": result["outcome"],
                "chance": result.get("chance"),
                "roll": result.get("roll"),
                "margin": result.get("margin"),
                "text": "%s → %s: %s"
                % (
                    result["action_label"],
                    result["target_label"],
                    result["text"],
                ),
                "changes": list(result["changes"]),
            }
        ]

    def _autonomy_intent(self, character):
        """Выбрать вид автономного контакта по состоянию персонажа.

        Политика (срез A4): враждебный персонаж тянется к примирению,
        лояльный при высоком доверии — к сближению, остальные — к
        нейтральному разведывательному контакту. Эффекты прописаны сразу
        для исхода «успех»; бросок шанса делает `_apply_autonomy_contact`.

        Явная директива игрока (`set_directive(..., "intentions", ...)`)
        имеет приоритет над политикой, но не отменяет бросок успеха.
        """
        forced = self.directives.intended_branch(
            character.get("id"), self.day
        )
        if forced in _AUTONOMY_POLICIES:
            return forced, dict(_AUTONOMY_POLICIES[forced])
        affinity = _as_float(character.get("affinity"), 0.0)
        trust = _as_float(character.get("trust"), 0.0)
        if affinity <= AUTONOMY_AFFINITY_THRESHOLD:
            return "reconcile", {
                "effects": {"affinity": 0.02},
                "text": "предложил(а) примирение.",
            }
        if affinity >= 0.0 and trust >= AUTONOMY_TRUST_THRESHOLD:
            return "rapprochement", {
                "effects": {"affinity": 0.02, "trust": 0.01},
                "text": "укрепил(а) контакт.",
            }
        return "probe", {
            "effects": {"affinity": 0.01},
            "text": "нашёл(ла) повод для разговора.",
        }

    def _apply_autonomy_contact(self, intent):
        """Исполнить автономный контакт через общую формулу успеха.

        Атакующий — сам персонаж (его `Automaton` уже содержит F/E/H),
        защитник — его структура. Успех применяет позитивные эффекты
        выбранной политики, провал — слабый негативный дрейф. Исход
        детерминирован seed'ом мира (`_roll`).
        """
        character = self.character(intent.actor)
        if character is None or not character.get("alive", True):
            return []
        kind = _text(intent.payload.get("policy"), "probe")
        branch = _AUTONOMY_POLICIES.get(kind) or _AUTONOMY_POLICIES["probe"]
        defender = None
        if self.attached and character.get("node_id"):
            defender = self.node(character["node_id"])
        attacker_unit = character.sync()
        base = AUTONOMY_BASE_CHANCE
        if defender is not None:
            chance = campaign_success_chance(
                base,
                attacker_unit,
                self._unit_from_node(defender),
                form="info",
            )
        else:
            chance = campaign_success_chance(
                base, attacker_unit, None, form="info"
            )
        roll = self._roll(
            "autonomy:%s:%s" % (intent.due_day, character["id"])
        )
        outcome = "success" if roll < chance else "failure"
        effects = branch["effects"] if outcome == "success" else {
            key: -abs(value) * 0.5 for key, value in branch["effects"].items()
        }
        changed = self._apply_character_effects(effects, character)
        text = branch["text"] if outcome == "success" else branch.get(
            "failure_text", "контакт не удался."
        )
        self.log.append(
            {
                "day": self.day,
                "kind": "contact",
                "text": "%s: %s" % (character["name"], text),
            }
        )
        return [
            {
                "kind": "intent",
                "day": self.day,
                "source": intent.source,
                "target": character["id"],
                "actor": character["id"],
                "outcome": outcome,
                "chance": chance,
                "roll": roll,
                "margin": success_margin(chance, roll),
                "text": text,
                "changes": changed,
            }
        ]

    def _schedule_autonomy(self):
        """Автономные персонажи сами назначают контакты на будущее.

        Намерение создаётся только для персонажа с `autonomous: true`;
        по умолчанию таких нет, поэтому баланс существующих миров не
        меняется. Дубль на тот же день и актора не создаётся, а исход
        контакта детерминирован seed'ом мира. Вид контакта выбирается
        политикой `_autonomy_intent`, отложенный контакт снимается, если
        к моменту исполнения персонаж окончательно расположен к игроку
        (`cancel_when`: высокая симпатия делает «повод для разговора»
        неактуальным).
        """
        for character in self.characters.values():
            if not character.get("autonomous"):
                continue
            if not self.directives.autonomy_enabled(
                character["id"], self.day
            ):
                continue
            if not character.get("alive", True):
                continue
            period = max(
                1,
                _as_int(
                    character.get("autonomy_period"), AUTONOMY_PERIOD
                ),
            )
            if self.day % period:
                continue
            pending_today = any(
                item.due_day == self.day for item in self.intents.items
            )
            due_day = self.day + 1 if pending_today else self.day
            if self.intents.has(
                due_day=due_day, actor=character["id"], source="autonomy"
            ):
                continue
            policy, branch = self._autonomy_intent(character)
            self.schedule_intent(
                due_day,
                "contact",
                actor=character["id"],
                payload={
                    "policy": policy,
                    "effects": dict(branch["effects"]),
                    "text": branch["text"],
                },
                source="autonomy",
                priority=1 if policy == "reconcile" else 0,
                cancel_when={"field": "affinity", "op": "gt", "value": 0.8},
            )
