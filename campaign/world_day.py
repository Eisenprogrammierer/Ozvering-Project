"""Экономика, здоровье, заражения, предметы и сюжетные линии дня."""

from __future__ import annotations

from .world_support import (
    CAMPAIGN_CONTAGION_CHANCE,
    CAMPAIGN_CONTAGION_SEVERITY,
    CAMPAIGN_ENV_WOUND_CHANCE,
    CAMPAIGN_ENV_WOUND_DAMAGE,
    CAMPAIGN_ENV_WOUND_SEVERITY,
    CAMPAIGN_FAVOR_INCOME,
    CAMPAIGN_FAVOR_PER_STANDING,
    CAMPAIGN_HEALTH_REGEN,
    CAMPAIGN_INFLUENCE_INCOME,
    CAMPAIGN_INFLUENCE_PER_AUTHORITY,
    CAMPAIGN_SICKNESS_HEALTH_DECAY,
    CAMPAIGN_SICKNESS_PROGRESS,
    CAMPAIGN_SKILL_CAP,
    CAMPAIGN_SKILL_FAILURE_GAIN,
    CAMPAIGN_SKILL_GAIN,
    CAMPAIGN_WOUND_HEALTH_DECAY,
    CAMPAIGN_WOUND_MAX,
    CAMPAIGN_WOUND_REGEN_PENALTY,
    CREDIT_DAYS,
    DEFAULT_RELATION_FORM,
    DOMAIN_SKILLS,
    ENDING_KINDS,
    HEALTH_MAX,
    MAINTENANCE_STARVE_FORCE,
    MAINTENANCE_STARVE_HEALTH,
    NATURE_BASE_WORK,
    NATURE_SEASON_LENGTH,
    SICKNESS_MAX,
    _as_float,
    _as_int,
    _clamp,
    _profile_skill,
    _text,
    balance,
    conversion_quote,
    credit_quote,
    help_quote,
    item_automaton_view,
    maintenance_cost,
    nature_yield,
    normalize_item_automaton,
    poverty_status,
    repair_quote,
    resource_projection,
    rest_quote,
    scaled_cost,
    scaled_effect,
    season_multiplier,
    season_name,
)


from .routine import run_day

NEEDS_DAY_SECONDS = 86400.0


class WorldDayMixin:

    def infect_player(self, severity):
        self.player_sickness = min(
            SICKNESS_MAX,
            max(self.player_sickness, _as_float(severity)),
        )
        return self.player_sickness

    def treat_player(self, amount):
        self.player_sickness = max(
            0.0,
            self.player_sickness - max(0.0, _as_float(amount)),
        )
        return self.player_sickness

    def injure_player(self, severity):
        """Получить рану; повторная рана не лечит старую (берётся максимум)."""
        if not self.player_alive:
            return None
        return self.player.injure(_as_float(severity))

    def treat_wound_player(self, amount):
        """Отдельное лечение раны (не путать с `treat_player` для болезни)."""
        if not self.player_alive:
            return None
        return self.player.treat_wound(max(0.0, _as_float(amount)))

    def injure_character(self, character_id, severity):
        character = self.character(character_id)
        if character is None or not character["alive"]:
            return None
        character["wound"] = min(
            CAMPAIGN_WOUND_MAX,
            max(
                _as_float(character.get("wound"), 0.0),
                _as_float(severity),
            ),
        )
        return character["wound"]

    def treat_wound_character(self, character_id, amount):
        character = self.character(character_id)
        if character is None or not character["alive"]:
            return None
        character["wound"] = max(
            0.0,
            _as_float(character.get("wound"), 0.0)
            - max(0.0, _as_float(amount)),
        )
        return character["wound"]

    def infect_character(self, character_id, severity):
        character = self.character(character_id)
        if character is None or not character["alive"]:
            return None
        character["sickness"] = min(
            SICKNESS_MAX,
            max(character["sickness"], _as_float(severity)),
        )
        return character["sickness"]

    def treat_character(self, character_id, amount):
        character = self.character(character_id)
        if character is None or not character["alive"]:
            return None
        character["sickness"] = max(
            0.0,
            character["sickness"] - max(0.0, _as_float(amount)),
        )
        return character["sickness"]

    def _advance_condition(self, health, sickness, wound=0.0):
        """Дневной срез состояния: болезнь прогрессирует, рана — нет.

        Рана (`wound`) отличается от болезни (`sickness`): она даёт прямой
        суточный урон `H` и штраф к восстановлению, но не усугубляется
        сама; лечится отдельным действием, а не отдыхом-по-болезни.
        """
        health = _clamp(health, 0.0, HEALTH_MAX)
        sickness = _clamp(sickness, 0.0, SICKNESS_MAX)
        wound = _clamp(wound, 0.0, CAMPAIGN_WOUND_MAX)
        regen = CAMPAIGN_HEALTH_REGEN
        if wound > 0.0:
            regen *= max(0.25, 1.0 - CAMPAIGN_WOUND_REGEN_PENALTY * wound)
            health = max(
                0.0,
                health - CAMPAIGN_WOUND_HEALTH_DECAY * wound,
            )
        if sickness > 0.0:
            health = max(
                0.0,
                health - CAMPAIGN_SICKNESS_HEALTH_DECAY * sickness,
            )
            sickness = min(
                SICKNESS_MAX,
                sickness + CAMPAIGN_SICKNESS_PROGRESS,
            )
        else:
            health = min(HEALTH_MAX, health + regen)
        return health, sickness, wound

    def _contagion_actors(self):
        """Живые акторы кампании, между которыми возможен контакт.

        Игрок представлен отдельной записью, персонажи — ссылкой на свой
        словарь. `sickness` в записи — снимок на начало проверки; он
        обновляется через `_set_contagion_sickness`.
        """
        actors = []
        if self.attached and self.player_alive:
            actors.append(
                {
                    "id": "player",
                    "name": "герой",
                    "node_id": self.player_node_id,
                    "sickness": float(self.player_sickness),
                    "character": None,
                }
            )
        for character_id in self.character_order:
            character = self.characters[character_id]
            if not character["alive"] or not character.get("node_id"):
                continue
            actors.append(
                {
                    "id": character["id"],
                    "name": character["name"],
                    "node_id": character["node_id"],
                    "sickness": float(character["sickness"]),
                    "character": character,
                }
            )
        return actors

    def _set_contagion_sickness(self, actor, value):
        value = _clamp(value, 0.0, SICKNESS_MAX)
        if actor["character"] is None:
            self.player_sickness = value
        else:
            actor["character"]["sickness"] = value
        actor["sickness"] = value
        return value

    def _spread_contagion(self):
        """Передать болезнь при контакте в одном узле (кампанийный срез).

        Для каждой пары живых акторов в одном узле, где болен ровно один,
        бросается детерминированный шанс `CAMPAIGN_CONTAGION_CHANCE ·
        sickness`; при успехе получатель добавляет
        `CAMPAIGN_CONTAGION_SEVERITY · sickness` источника. Если больны оба
        или никто — пара пропускается. Порядок обхода фиксирован, поэтому
        результат воспроизводим seed'ом мира.
        """
        actors = self._contagion_actors()
        changed = []
        for index, source in enumerate(actors):
            for target in actors[index + 1 :]:
                if source["node_id"] != target["node_id"]:
                    continue
                if source["sickness"] <= 0.0 and target["sickness"] <= 0.0:
                    continue
                if source["sickness"] > 0.0 and target["sickness"] <= 0.0:
                    donor, recipient = source, target
                elif target["sickness"] > 0.0 and source["sickness"] <= 0.0:
                    donor, recipient = target, source
                else:
                    continue
                chance = CAMPAIGN_CONTAGION_CHANCE * donor["sickness"]
                roll = self._roll(
                    "contagion:%s:%s:%s"
                    % (self.day, donor["id"], recipient["id"])
                )
                if roll >= chance:
                    continue
                severity = CAMPAIGN_CONTAGION_SEVERITY * donor["sickness"]
                before = recipient["sickness"]
                after = self._set_contagion_sickness(
                    recipient, before + severity
                )
                delta = after - before
                if delta <= 0.0:
                    continue
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "infection",
                        "text": "%s заразил(а) %s."
                        % (donor["name"], recipient["name"]),
                    }
                )
                changed.append(
                    ("%s · болезнь" % recipient["name"], delta)
                )
        return changed

    def _needs_routine_config(self):
        """Конфиг суточной BDI-рутины мира; ``None`` — слой выключен."""
        raw = self.config.get("bdi_routine")
        if not isinstance(raw, dict) or not raw.get("enabled", False):
            return None
        config = dict(raw)
        config["enabled"] = True
        # Силу и энергию мира двигают собственные правила дня, а не
        # восстановление рутины арены.
        config["work_energy"] = 0.0
        config["energy_recovery"] = 0.0
        config["force_recovery"] = 0.0
        return config

    def _needs_service(self, node_id, standing):
        """Бытовая норма: достаток узла и личное положение персонажа."""
        node = self.node(node_id) or self.node(self.player_node_id) or {}
        stats = node.get("stats") or {}
        supply = _clamp(_as_float(stats.get("wealth"), 0.5))
        support = _clamp(0.5 + 0.5 * _as_float(standing))
        return support, supply

    def _run_daily_needs(self):
        """Прожить суточную рутину BDI для героя и живых персонажей."""
        config = self._needs_routine_config()
        if config is None:
            return []
        changed = []
        if self.player_alive:
            support, supply = self._needs_service(
                self.player_node_id, self.player.force
            )
            result = run_day(
                self.player,
                NEEDS_DAY_SECONDS,
                support=support,
                supply=supply,
                config=config,
            )
            if result:
                for key, after_value in result["after"]["needs"].items():
                    before_value = result["before"]["needs"].get(
                        key, after_value
                    )
                    if abs(after_value - before_value) > 1e-9:
                        changed.append(
                            ("герой · %s" % key, after_value - before_value)
                        )
        for character_id in self.character_order:
            character = self.characters[character_id]
            if not character["alive"]:
                continue
            support, supply = self._needs_service(
                character.get("node_id"),
                (float(character.get("affinity", 0.0)) + 1.0) / 2.0,
            )
            result = run_day(
                character,
                NEEDS_DAY_SECONDS,
                support=support,
                supply=supply,
                config=config,
            )
            character.sync()
            if not result:
                continue
            for key, after_value in result["after"]["needs"].items():
                before_value = result["before"]["needs"].get(
                    key, after_value
                )
                if abs(after_value - before_value) > 1e-9:
                    changed.append(
                        (
                            "%s · %s" % (character["name"], key),
                            after_value - before_value,
                        )
                    )
        return changed

    def _advance_conditions(self):
        changed = []
        if not self.player_alive:
            if not self.finished:
                self.outcome = "lose"
                self.finished = True
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "death",
                        "text": "Герой умер от болезни и истощения.",
                    }
                )
        else:
            before = (self.player_health, self.player_sickness)
            (
                self.player_health,
                self.player_sickness,
                self.player_wound,
            ) = self._advance_condition(
                self.player_health,
                self.player_sickness,
                self.player_wound,
            )
            if (self.player_health, self.player_sickness) != before:
                changed.append(
                    (
                        "герой · здоровье",
                        self.player_health - before[0],
                    )
                )
            if self.player_health <= 0.0:
                # Истощение и болезнь доводят силу до нуля; фиксируем смерть
                # через единую метрику F, а не через порог здоровья.
                self.player_alive = False
                self.outcome = "lose"
                self.finished = True
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "death",
                        "text": "Герой умер от болезни и истощения.",
                    }
                )
        for character_id in self.character_order:
            character = self.characters[character_id]
            if not character["alive"]:
                continue
            before = (character["health"], character["sickness"])
            (
                character["health"],
                character["sickness"],
                character["wound"],
            ) = self._advance_condition(
                character["health"],
                character["sickness"],
                _as_float(character.get("wound"), 0.0),
            )
            if (character["health"], character["sickness"]) != before:
                changed.append(
                    (
                        "%s · здоровье" % character["name"],
                        character["health"] - before[0],
                    )
                )
            if character["health"] <= 0.0:
                character["alive"] = False
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "death",
                        "text": "%s умер(ла) от болезни."
                        % character["name"],
                    }
                )
            affinity_delta, trust_delta = character.tick()
            if abs(affinity_delta) > 1e-12:
                changed.append(
                    (
                        "%s · отношение" % character["name"],
                        affinity_delta,
                    )
                )
            if abs(trust_delta) > 1e-12:
                changed.append(
                    (
                        "%s · доверие" % character["name"],
                        trust_delta,
                    )
                )
        changed.extend(self._spread_contagion())
        changed.extend(self._apply_environment_wounds())
        changed.extend(self._run_daily_needs())
        return self._merge_changes(changed)

    def _apply_environment_wounds(self):
        """Средовые источники ран (кампанийный аналог `ENV_WOUND_*` арены).

        Редкое детерминированное событие дня: часть живых акторов получает
        прямой урон `H` и устойчивую рану. Зерно — `_roll`, поэтому исход
        воспроизводим seed'ом мира, как у заражения.
        """
        changed = []
        actors = []
        if self.attached and self.player_alive:
            actors.append(("player", "герой"))
        for character_id in self.character_order:
            character = self.characters[character_id]
            if character["alive"]:
                actors.append((character_id, character["name"]))
        for actor_id, actor_name in actors:
            roll = self._roll("env-wound:%s:%s" % (self.day, actor_id))
            if roll >= CAMPAIGN_ENV_WOUND_CHANCE:
                continue
            if actor_id == "player":
                before = self.player_health
                self.injure_player(CAMPAIGN_ENV_WOUND_SEVERITY)
                self.player_health = max(
                    0.0,
                    self.player_health - CAMPAIGN_ENV_WOUND_DAMAGE,
                )
                health_delta = self.player_health - before
                wound_value = self.player_wound
            else:
                character = self.characters[actor_id]
                before = character["health"]
                self.injure_character(actor_id, CAMPAIGN_ENV_WOUND_SEVERITY)
                character["health"] = max(
                    0.0,
                    character["health"] - CAMPAIGN_ENV_WOUND_DAMAGE,
                )
                health_delta = character["health"] - before
                wound_value = character["wound"]
                if character["health"] <= 0.0:
                    character["alive"] = False
            self.log.append(
                {
                    "day": self.day,
                    "kind": "wound",
                    "text": "%s получил(а) рану от опасного стечения "
                    "обстоятельств." % actor_name,
                }
            )
            if health_delta < 0.0:
                changed.append(
                    (
                        "%s · здоровье" % actor_name
                        if actor_id != "player"
                        else "герой · здоровье",
                        health_delta,
                    )
                )
            changed.append(("%s · рана" % actor_name, wound_value))
        return changed

    def _refresh_items(self):
        self.player_item_ids = []
        if not self.attached:
            return
        node = self.node(self.player_node_id) or {}
        domain = node.get("domain", "")
        for item_id in self.item_order:
            item = self.item_catalog[item_id]
            if (
                item_id in self.consumed_items
                and item_id not in self.granted_items
            ):
                continue
            domains = item.get("domains") or ()
            if item.get("always") or (domains and domain in domains):
                self.player_item_ids.append(item_id)
                continue
            min_skills = item.get("min_skills") or {}
            if min_skills and all(
                _profile_skill(self.profile, key) + 1e-9 >= _as_float(value)
                for key, value in min_skills.items()
            ):
                self.player_item_ids.append(item_id)
        for item_id in sorted(self.granted_items):
            if (
                item_id in self.item_catalog
                and item_id not in self.player_item_ids
            ):
                self.player_item_ids.append(item_id)
        limit = max(1, _as_int(self.config.get("max_items"), 6))
        self.player_item_ids = self.player_item_ids[:limit]

    def player_items(self):
        result = []
        for item_id in self.player_item_ids:
            item = self.item_catalog.get(item_id)
            if item is None:
                continue
            entry = dict(item)
            automaton = self.item_automata.get(item_id)
            if automaton is not None:
                entry["automaton"] = item_automaton_view(automaton)
            result.append(entry)
        return result

    def item_automaton(self, item_id):
        """Публичное состояние автомата предмета для UI и проверок."""
        automaton = self.item_automata.get(_text(item_id))
        if automaton is None:
            return None
        return item_automaton_view(automaton)

    def _reset_item_automaton(self, item_id):
        item = self.item_catalog.get(_text(item_id)) or {}
        spec = item.get("automaton")
        if not spec:
            return
        self.item_automata[item_id] = normalize_item_automaton(item_id, spec)

    def norm_entries(self):
        """Нормы мира в порядке объявления, как данные для UI."""

        return [
            dict(self.norms[norm_id])
            for norm_id in self.norm_order
            if norm_id in self.norms
        ]

    def item_label(self, item_id):
        item = self.item_catalog.get(_text(item_id)) or {}
        return _text(item.get("label"), _text(item_id))

    def economy_config(self):
        """Блок `economy` конфига мира (пустой, если экономика выключена)."""
        raw = self.config.get("economy")
        return raw if isinstance(raw, dict) else {}

    def _economy_level(self):
        """Уровень героя для масштаба цены: глубина узла или ранг должности."""
        node = self.node(self.player_node_id)
        if node is None:
            return 0.0
        office = self.offices.get(self.player_office_id) or {}
        return float(
            max(
                self.node_depth(node["id"]),
                _as_int(office.get("rank"), 0),
            )
        )

    def _economy_sources(self):
        """Наблюдаемые источники дня: доход должности и суточные приросты."""
        sources = {}
        if self.attached and self.player_alive:
            sources["влияние должности"] = (
                CAMPAIGN_INFLUENCE_INCOME
                + CAMPAIGN_INFLUENCE_PER_AUTHORITY * self.player_authority
            )
            sources["связи должности"] = (
                CAMPAIGN_FAVOR_INCOME
                + CAMPAIGN_FAVOR_PER_STANDING
                * self.player_resources["standing"]
            )
        daily = self.config.get("daily") or {}
        for key, value in (daily.get("player") or {}).items():
            amount = _as_float(value)
            if amount > 0.0:
                sources[self.stat_label(key)] = (
                    sources.get(self.stat_label(key), 0.0) + amount
                )
        for key, value in (daily.get("node") or {}).items():
            amount = _as_float(value)
            if amount > 0.0:
                label = "структура · %s" % self.stat_label(key)
                sources[label] = sources.get(label, 0.0) + amount
        nature = self.economy_config().get("nature") or {}
        if nature.get("enabled"):
            report = self.nature_view()
            if report:
                sources["природа · %s" % report.get("season_name", "")] = (
                    _as_float(report.get("wealth"))
                )
        return sources

    def _economy_sinks(self):
        """Наблюдаемые стоки дня: поддержание, природа и суточные убыли."""
        config = self.economy_config()
        sinks = {}
        maintenance = maintenance_cost(
            level=self._economy_level(),
            force=self.player_force,
            wound=self.player_wound,
            config=config.get("maintenance") or {},
        )
        if maintenance > 1e-9:
            sinks["поддержание героя"] = maintenance
        node = self.node(self.player_node_id)
        if node is not None:
            node_upkeep = _as_float(
                ((config.get("maintenance") or {}).get("node") or {}).get(
                    "wealth"
                ),
                0.0,
            )
            if node_upkeep > 1e-9:
                sinks["поддержание структуры"] = node_upkeep
        daily = self.config.get("daily") or {}
        for key, value in (daily.get("player") or {}).items():
            amount = _as_float(value)
            if amount < 0.0:
                label = self.stat_label(key)
                sinks[label] = sinks.get(label, 0.0) - amount
        for key, value in (daily.get("node") or {}).items():
            amount = _as_float(value)
            if amount < 0.0:
                label = "структура · %s" % self.stat_label(key)
                sinks[label] = sinks.get(label, 0.0) - amount
        return sinks

    def economy_view(self):
        """Срез экономики для UI и отладки: баланс, бедность и клапаны.

        Это чтение, а не скрытое списание. Сток применяется на границе
        дня (`_apply_economy_day`), а помощь/кредит/ремонт — только явными
        вызовами игрока.
        """
        config = self.economy_config()
        source_map = self._economy_sources()
        sink_map = self._economy_sinks()
        report = balance(source_map, sink_map)
        poverty_cfg = config.get("poverty") or {}
        poverty_threshold = poverty_cfg.get("energy_ratio")
        if poverty_threshold is not None:
            poverty_threshold = _as_float(poverty_threshold)
        report.update(
            {
                "energy": float(self.player_energy),
                "max_energy": float(self.player_max_energy),
                "energy_ratio": (
                    float(self.player_energy)
                    / max(1e-9, float(self.player_max_energy))
                ),
                "actions_left": int(self.actions_left),
                "actions_per_day": int(self.actions_per_day),
                "poverty": poverty_status(
                    self.player_energy,
                    self.player_max_energy,
                    self.actions_left,
                    threshold=poverty_threshold,
                ),
                "maintenance": maintenance_cost(
                    level=self._economy_level(),
                    force=self.player_force,
                    wound=self.player_wound,
                    config=config.get("maintenance") or {},
                ),
                "repair": repair_quote(
                    self.player_wound,
                    max(0.0, HEALTH_MAX - self.player_health),
                    config=config.get("repair") or {},
                ),
                "work_unit": conversion_quote(
                    self.player.energy_per_action, "info"
                ),
                "nature": self.nature_view(),
                "resources": {
                    name: resource_projection(name)
                    for name in (
                        "energy",
                        "wealth",
                        "influence",
                        "favor",
                        "standing",
                        "evidence",
                    )
                },
                "relief": {
                    "rest": "потратить остаток действий на H/F/рану",
                    "help": "взять E у союзника, создав услугу",
                    "credit": "взять E у структуры под долг со сроком",
                    "end_day": "всегда доступен и восстанавливает суточный E",
                },
            }
        )
        return report

    def nature_view(self, node_id=None):
        """Работа природы для узла: сезон, плодородие, труд и ущерб."""
        config = self.economy_config().get("nature") or {}
        if not config:
            return {}
        node = self.node(node_id or config.get("node") or self.player_node_id)
        if node is None:
            return {}
        length = _as_int(config.get("season_length"), NATURE_SEASON_LENGTH)
        season = season_multiplier(self.day, length=length)
        fertility = _as_float(
            config.get("fertility"), node["stats"].get("wealth", 0.5)
        )
        report = nature_yield(
            season=season,
            fertility=fertility,
            labor=_as_float(config.get("labor"), 0.0),
            damage=_as_float(config.get("damage"), 0.0),
            max_work=_as_float(config.get("base_work"), NATURE_BASE_WORK),
        )
        report["node"] = node["id"]
        report["node_label"] = node["name"]
        report["season_name"] = season_name(self.day, length=length)
        report["wealth_share"] = _as_float(
            config.get("wealth_share"), 1.0
        )
        return report

    def _apply_economy_day(self):
        """Применить стоки/источники экономики на границе суток.

        По умолчанию блок `economy` пуст, поэтому старые миры и сейвы
        сохраняют прежний баланс. Поддержание платится из `E`; если его не
        хватает, дефицит превращается в износ `F`/`H`, а не в отрицательную
        энергию. Природа возвращает часть работы в казну узла.
        """
        config = self.economy_config()
        if not config:
            return []
        changed = []
        nature = config.get("nature") or {}
        if nature.get("enabled"):
            report = self.nature_view()
            node = self.node(report.get("node")) if report else None
            if node is not None:
                before = node["stats"]["wealth"]
                share = max(0.0, _as_float(report.get("wealth_share"), 1.0))
                node["stats"]["wealth"] = _clamp(
                    before + _as_float(report.get("wealth")) * share
                )
                delta = node["stats"]["wealth"] - before
                if abs(delta) > 1e-9:
                    changed.append(
                        ("%s · казна" % node["name"], delta)
                    )
        node = self.node(self.player_node_id)
        if node is not None:
            node_upkeep = _as_float(
                ((config.get("maintenance") or {}).get("node") or {}).get(
                    "wealth"
                ),
                0.0,
            )
            if node_upkeep > 1e-9:
                before = node["stats"]["wealth"]
                node["stats"]["wealth"] = _clamp(before - node_upkeep)
                delta = node["stats"]["wealth"] - before
                if abs(delta) > 1e-9:
                    changed.append(
                        ("%s · казна" % node["name"], delta)
                    )
        if self.attached and self.player_alive:
            cost = maintenance_cost(
                level=self._economy_level(),
                force=self.player_force,
                wound=self.player_wound,
                config=config.get("maintenance") or {},
            )
            if cost > 1e-9:
                paid = min(float(self.player_energy), cost)
                if paid > 0.0:
                    self.player.energy = float(self.player_energy) - paid
                    changed.append(("герой · энергия", -paid))
                shortfall = cost - paid
                if shortfall > 1e-9:
                    health_before = self.player_health
                    self.player_health = max(
                        0.0,
                        self.player_health
                        - shortfall * MAINTENANCE_STARVE_HEALTH,
                    )
                    if self.player_health != health_before:
                        changed.append(
                            (
                                "герой · здоровье",
                                self.player_health - health_before,
                            )
                        )
                    standing_before = self.player_resources["standing"]
                    self.player_resources["standing"] = _clamp(
                        standing_before
                        - shortfall * MAINTENANCE_STARVE_FORCE
                    )
                    delta = self.player_resources["standing"] - standing_before
                    if abs(delta) > 1e-9:
                        changed.append(("репутация", delta))
        for key, value in (config.get("sources") or {}).items():
            amount = _as_float(value)
            if amount <= 0.0:
                continue
            if key == "energy":
                delta = self.player.grant_energy(amount)
                if abs(delta) > 1e-9:
                    changed.append(("герой · энергия", delta))
            elif key in self.player_resources:
                before = self.player_resources[key]
                self.player_resources[key] = _clamp(before + amount)
                delta = self.player_resources[key] - before
                if abs(delta) > 1e-9:
                    changed.append((self.stat_label(key), delta))
        for key, value in (config.get("sinks") or {}).items():
            amount = _as_float(value)
            if amount <= 0.0:
                continue
            if key == "energy":
                paid = min(float(self.player_energy), amount)
                if paid > 0.0:
                    self.player.energy = float(self.player_energy) - paid
                    changed.append(("герой · энергия", -paid))
            elif key in self.player_resources:
                before = self.player_resources[key]
                self.player_resources[key] = _clamp(before - amount)
                delta = self.player_resources[key] - before
                if abs(delta) > 1e-9:
                    changed.append((self.stat_label(key), delta))
        return self._merge_changes(changed)

    def _economy_source(self, source_id):
        """Разрешить источник помощи/кредита: персонаж или структура."""
        character = self.character(source_id)
        if character is not None:
            return character, self.node(character.get("node_id"))
        node = self.node(source_id)
        return None, node

    def _economy_trust(self, source_id, character, node):
        if character is not None:
            return _as_float(character.get("trust"), 0.0)
        if node is None:
            return 0.0
        if node["id"] == self.player_node_id:
            return 1.0
        if not self.player_node_id:
            return 0.0
        axes = self.relation_axes(node["id"], self.player_node_id)
        return _as_float(axes.get("trust"), 0.0)

    def rest_player(self):
        """Потратить остаток действий на отдых.

        Отдых возвращает `H`, немного `F` и уменьшает рану, но не создаёт
        действий: цена — неиспользованные возможности текущего дня.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        if not self.player_alive:
            return {"ok": False, "reason": "герой мёртв"}
        actions = int(self.actions_left)
        if actions <= 0:
            return {"ok": False, "reason": "нечего тратить на отдых"}
        quote = rest_quote(
            actions,
            self.player.energy_per_action,
            self.player_health,
            HEALTH_MAX,
            self.player_wound,
        )
        health_before = self.player_health
        standing_before = self.player_resources["standing"]
        wound_before = self.player_wound
        self.actions_left = 0
        self.player_health = min(HEALTH_MAX, health_before + quote["health"])
        self.player_resources["standing"] = _clamp(
            standing_before + quote["force"]
        )
        self.player_wound = max(0.0, wound_before - quote["wound"])
        changes = []
        if self.player_health != health_before:
            changes.append(
                (
                    "герой · здоровье",
                    self.player_health - health_before,
                )
            )
        if self.player_resources["standing"] != standing_before:
            changes.append(
                (
                    "репутация",
                    self.player_resources["standing"] - standing_before,
                )
            )
        if self.player_wound != wound_before:
            changes.append(("герой · рана", self.player_wound - wound_before))
        changes.append(("герой · энергия", -quote["energy_spent"]))
        self.log.append(
            {
                "day": self.day,
                "kind": "economy",
                "text": "отдых: потрачено %d действий, восстановлено %.1f H"
                % (actions, quote["health"]),
            }
        )
        return {
            "ok": True,
            "actions": actions,
            "changes": self._merge_changes(changes),
            "text": "Отдых вернул силы, но день потрачен.",
        }

    def request_help(self, source_id, amount=None):
        """Взять `E` у союзника, создав обязательство-услугу.

        Помощь не бесплатна: источник тратит казну, а герой становится
        должником. Без доверия или запаса источник отказывает.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        if not self.attached or not self.player_alive:
            return {"ok": False, "reason": "герой не в строю"}
        character, node = self._economy_source(source_id)
        if character is not None and not character.get("alive", True):
            return {"ok": False, "reason": "источник недоступен"}
        if node is None:
            return {"ok": False, "reason": "источник не найден"}
        trust = self._economy_trust(source_id, character, node)
        quote = help_quote(
            trust,
            node["stats"].get("wealth", 0.0),
            requested=amount,
            max_energy=self.player_max_energy,
        )
        if not quote["allowed"]:
            return {"ok": False, "reason": quote["reason"]}
        granted = self.player.grant_energy(quote["amount"])
        if granted <= 1e-9:
            return {"ok": False, "reason": "энергия уже полна"}
        before = node["stats"]["wealth"]
        node["stats"]["wealth"] = _clamp(before - quote["wealth_cost"])
        obligation = self.add_obligation(
            creditor=_text(source_id),
            debtor="player",
            kind="favor",
            amount=quote["obligation"],
            note="помощь",
        )
        self.log.append(
            {
                "day": self.day,
                "kind": "economy",
                "text": "помощь %s: +%.1f E, услуга %.2f"
                % (_text(source_id), granted, quote["obligation"]),
            }
        )
        return {
            "ok": True,
            "source": _text(source_id),
            "energy": granted,
            "wealth_cost": before - node["stats"]["wealth"],
            "obligation": obligation,
            "changes": [
                ("герой · энергия", granted),
                (
                    "%s · казна" % node["name"],
                    node["stats"]["wealth"] - before,
                ),
            ],
        }

    def take_credit(self, creditor_id, amount=None, due_days=None):
        """Взять `E` у структуры под долг со сроком и процентом.

        Кредит — не подарок и не второй бюджет: он даёт энергию сейчас,
        но создаёт `debt` с `due_day`. Просрочка не стирает долг; она
        видна в журнале обязательств и отношениях.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        if not self.attached or not self.player_alive:
            return {"ok": False, "reason": "герой не в строю"}
        character, node = self._economy_source(creditor_id)
        if character is not None and not character.get("alive", True):
            return {"ok": False, "reason": "кредитор недоступен"}
        if node is None:
            return {"ok": False, "reason": "кредитор не найден"}
        quote = credit_quote(
            node["stats"].get("wealth", 0.0),
            requested=amount,
            max_energy=self.player_max_energy,
        )
        if not quote["allowed"]:
            return {"ok": False, "reason": quote["reason"]}
        granted = self.player.grant_energy(quote["amount"])
        if granted <= 1e-9:
            return {"ok": False, "reason": "энергия уже полна"}
        before = node["stats"]["wealth"]
        node["stats"]["wealth"] = _clamp(before - quote["wealth_cost"])
        due_day = self.day + max(1, _as_int(due_days, CREDIT_DAYS))
        obligation = self.add_obligation(
            creditor=_text(creditor_id),
            debtor="player",
            kind="debt",
            amount=quote["obligation"],
            due_day=due_day,
            note="кредит",
        )
        self.log.append(
            {
                "day": self.day,
                "kind": "economy",
                "text": "кредит %s: +%.1f E, срок день %d"
                % (_text(creditor_id), granted, due_day),
            }
        )
        return {
            "ok": True,
            "creditor": _text(creditor_id),
            "energy": granted,
            "wealth_cost": before - node["stats"]["wealth"],
            "due_day": due_day,
            "obligation": obligation,
            "changes": [
                ("герой · энергия", granted),
                (
                    "%s · казна" % node["name"],
                    node["stats"]["wealth"] - before,
                ),
            ],
        }

    def repair_player(self):
        """Отремонтировать рану и недостающее здоровье за `E`."""
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        if not self.player_alive:
            return {"ok": False, "reason": "герой мёртв"}
        quote = repair_quote(
            self.player_wound,
            max(0.0, HEALTH_MAX - self.player_health),
            config=self.economy_config().get("repair") or {},
        )
        if quote["energy"] <= 1e-9:
            return {"ok": False, "reason": "нечего ремонтировать"}
        if not self.player.spend_energy(quote["energy"]):
            return {"ok": False, "reason": "недостаточно энергии"}
        health_before = self.player_health
        wound_before = self.player_wound
        self.player_wound = max(0.0, wound_before - quote["wound_repaired"])
        self.player_health = min(
            HEALTH_MAX, health_before + quote["health_restored"]
        )
        changes = [("герой · энергия", -quote["energy"])]
        if self.player_health != health_before:
            changes.append(
                (
                    "герой · здоровье",
                    self.player_health - health_before,
                )
            )
        if self.player_wound != wound_before:
            changes.append(("герой · рана", self.player_wound - wound_before))
        self.log.append(
            {
                "day": self.day,
                "kind": "economy",
                "text": "ремонт: -%.1f E" % quote["energy"],
            }
        )
        return {
            "ok": True,
            "energy": quote["energy"],
            "changes": self._merge_changes(changes),
            "text": "Ремонт завершён.",
        }

    def action_economy_view(self, action_id, target_id=None):
        """Оценка цены и эффекта действия по уровню/силе/сопротивлению."""
        action = self.actions.get(_text(action_id))
        if action is None:
            return {}
        context = self.player_context()
        if context is None:
            return {}
        target = (
            context["node"]
            if (action.get("target") or {}).get("self")
            else self.node(target_id)
        )
        form = _text(action.get("form"), DEFAULT_RELATION_FORM)
        level = (
            float(self.node_depth(target["id"]))
            if target is not None and target.get("id") in self.nodes
            else 0.0
        )
        force = _as_float((target or {}).get("stats", {}).get("power"), 0.0)
        if target is not None and hasattr(target, "sync"):
            resistance = float(target.sync().resistance(form))
        elif target is not None:
            resistance = float(self._unit_from_node(target).resistance(form))
        else:
            resistance = 0.0
        scaling = self.economy_config().get("scaling") or {}
        base = float(self.player.energy_per_action)
        price = scaled_cost(
            base,
            level=level,
            force=force,
            resistance=resistance,
            config=scaling.get("cost") or {},
        )
        return {
            "base_energy": base,
            "energy_price": price,
            "cost_ratio": price / max(1e-9, base),
            "level": level,
            "force": force,
            "resistance": resistance,
            "effect_ratio": scaled_effect(
                1.0,
                delivered=1.0,
                amount=1.0,
                resistance=resistance,
                config=scaling.get("effect") or {},
            ),
        }

    def _skill_domains(self, action, target):
        """Домены, в которых действие тренирует навыки героя.

        Сначала берётся домен адресата: `inspect`/`build_network` доступны
        в любом домене, и именно цель определяет, что герой осваивает.
        Если цели нет или у неё нет домена, используются домены самого
        действия.
        """
        if target is not None and target.get("domain") in DOMAIN_SKILLS:
            return (target["domain"],)
        domains = (action.get("actor") or {}).get("domains") or ()
        return tuple(
            domain for domain in domains if domain in DOMAIN_SKILLS
        )

    def _grow_player_skills(self, action, target, success):
        """Практика растит навыки домена с насыщением к `CAMPAIGN_SKILL_CAP`.

        Успех даёт `CAMPAIGN_SKILL_GAIN`, провал —
        `CAMPAIGN_SKILL_FAILURE_GAIN`; прирост делится между навыками
        домена и убывает по мере приближения
        к капу. Так стартовый профиль (0.08–0.12) может дорасти до
        требований `seek_promotion` (0.18) и вышестоящих должностей (0.28+)
        без ручной правки профиля. `aptitudes` — производная от навыков,
        поэтому пересчитывается вместе с ними; список предметов зависит от
        навыков и обновляется здесь же.
        """
        if action.get("career"):
            return []
        domains = self._skill_domains(action, target)
        skills = []
        for domain in domains:
            for skill in DOMAIN_SKILLS[domain]:
                if skill not in skills:
                    skills.append(skill)
        if not skills:
            return []
        base = (
            CAMPAIGN_SKILL_GAIN
            if success
            else CAMPAIGN_SKILL_FAILURE_GAIN
        )
        share = base / len(skills)
        changed = []
        profile_skills = self.profile.setdefault("skills", {})
        for skill in skills:
            current = _profile_skill(self.profile, skill)
            room = max(0.0, CAMPAIGN_SKILL_CAP - current)
            if room <= 1e-9:
                continue
            delta = min(share * (room / CAMPAIGN_SKILL_CAP), room)
            if delta <= 1e-9:
                continue
            profile_skills[skill] = _clamp(current + delta, 0.0, 1.0)
            changed.append(
                (
                    "навык «%s»" % self.skill_labels.get(skill, skill),
                    delta,
                )
            )
        if not changed:
            return changed
        aptitudes = self.profile.setdefault("aptitudes", {})
        for domain in domains:
            keys = DOMAIN_SKILLS[domain]
            aptitudes[domain] = _clamp(
                sum(_profile_skill(self.profile, key) for key in keys)
                / max(1, len(keys))
            )
        self._refresh_items()
        return changed

    def end_storyline(self, kind, text=""):
        """Публичный вход в нарративный финал (§7 №30).

        Сюжет/UI может завершить главу без объективной победы: `win`/`lose`
        остаются совместимыми с легаси, `neutral` — «глава закончилась».
        """
        return self._apply_ending(kind, text)

    def _apply_ending(self, kind, text=""):
        """Нарративный финал без объективной победы (вопрос §7 №30).

        `win`/`lose` — сюжетный исход для старых сюжетов; `neutral` —
        глава закончилась, но поражения нет. Во всех случаях `finished`
        останавливает дневной цикл, а `outcome=None` для `neutral` не даёт
        `CampaignEnv` терминального бонуса победы/поражения.
        """
        kind = _text(kind).lower()
        if kind not in ENDING_KINDS or self.finished:
            return ""
        self.ending = kind
        self.outcome = None if kind == "neutral" else kind
        self.finished = True
        label = {
            "win": "Сюжетный финал: победа.",
            "lose": "Сюжетный финал: поражение.",
            "neutral": "Сюжетный финал: глава завершена.",
        }[kind]
        self.log.append(
            {
                "day": self.day,
                "kind": "ending",
                "text": text or label,
            }
        )
        return text or label

    def _check_storyline(self):
        """Проверить сюжетные пороги мира (`storyline` в конфиге).

        Это первый срез «полного набора сюжетных финалов» §7 №30. Правила
        задаются в конфиге мира, а не в калибровочном скрипте, поэтому
        `CampaignEnv`, UI и ручная игра видят один и тот же исход:

        - `win.standing_at_least` — герой в должности и город ему доверяет;
        - `lose.standing_at_most` + `lose.days` — репутация держится ниже
          порога несколько дней подряд. Это не увольнение (№29): смена роли
          остаётся сменой роли, а сюжетный провал — отдельный исход;
        - `deadline_day` — конец главы. Без дедлайна победа срабатывает,
          как только порог взят; с дедлайном глава оценивается в его конце:
          победа, поражение или `neutral` (срок истёк, но провала нет).
          Сам мир при этом остаётся бесконечным: заканчивается глава, а не
          симуляция.

        Правила проверяются на границе дня после `_advance_conditions()`.
        Без блока `storyline` мир остаётся бесконечным, как раньше.
        """
        goals = self.config.get("storyline") or {}
        if self.finished or not goals or self.sandbox:
            return
        if self.day < _as_int(goals.get("min_day"), 0):
            return
        win = goals.get("win") or {}
        lose = goals.get("lose") or {}
        win_threshold = win.get("standing_at_least")
        lose_threshold = lose.get("standing_at_most")
        if lose_threshold is not None:
            if (
                self.attached
                and self.player_alive
                and self.player_resources["standing"]
                <= _as_float(lose_threshold)
            ):
                self.storyline_days += 1
            else:
                self.storyline_days = 0
            if self.storyline_days >= max(1, _as_int(lose.get("days"), 1)):
                self._apply_ending(
                    "lose",
                    _text(
                        lose.get("text"),
                        "Хартия провалена: город потерял доверие.",
                    ),
                )
                return
        else:
            self.storyline_days = 0
        deadline = goals.get("deadline_day")
        if deadline is not None:
            if self.day < _as_int(deadline, 0):
                return
            if not self.attached or not self.player_alive:
                self._apply_ending(
                    "lose",
                    _text(
                        lose.get("text"),
                        "Хартия провалена: вы не удержались в должности.",
                    ),
                )
                return
            if (
                win_threshold is not None
                and self.player_resources["standing"]
                >= _as_float(win_threshold)
            ):
                self._apply_ending(
                    "win",
                    _text(
                        win.get("text"),
                        "Хартия принята: город доверяет вам.",
                    ),
                )
                return
            if (
                lose_threshold is not None
                and self.player_resources["standing"]
                <= _as_float(lose_threshold)
            ):
                self._apply_ending(
                    "lose",
                    _text(
                        lose.get("text"),
                        "Хартия провалена: город потерял доверие.",
                    ),
                )
                return
            self._apply_ending(
                "neutral",
                _text(
                    goals.get("neutral_text"),
                    "Срок истёк: хартия не принята, но провала нет.",
                ),
            )
            return
        if (
            win_threshold is not None
            and self.attached
            and self.player_alive
            and self.player_resources["standing"] >= _as_float(win_threshold)
        ):
            self._apply_ending(
                "win",
                _text(
                    win.get("text"),
                    "Хартия принята: город доверяет вам.",
                ),
            )
