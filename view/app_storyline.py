"""Запуск сюжетов: мир, автоматы, личность, профиль."""

from __future__ import annotations

from .app_support import (
    BASE_DIR,
    logger,
    os,
)


class AppStorylineMixin:

    def _start_world_storyline(self, storyline, role):
        from campaign.world import load_world
        from view.support.storyline import StorylineInterpreter
        from view.support.scenario import build_world
        from view.support.world import CampaignEngine
        from view.support.time_system import CampaignTimeSystem

        self.campaign_preset = None
        self.strategy = None
        self.strategy_config = None
        self.world = None
        self.world_clock = None
        self.player_profile = None
        self.scenario_path = storyline.get(
            "scenario_path", "scenarios/mvp.json"
        )
        self.pending_storyline_outcome = None
        self.dialogue_memory = None
        free_mode = bool(storyline.get("free_start"))
        if free_mode:
            # Свободный режим живёт на WorldEngine и не требует военного
            # состояния, фракции или пресета. Это и есть P2: субъект
            # отделён от кампании-автомата.
            self.state = None
            self.engine = None
            self.player_idx = 0
            self.time_system = None
        else:
            state = build_world(
                scenario_path=self.scenario_path,
                content=self.content,
                seed=self._campaign_seed(storyline),
            )
            self.state = state
            self.engine = CampaignEngine(state)
            self.engine.engagements = state.engagements
            self.player_idx = state.player_idx
            self.time_system = CampaignTimeSystem(
                state, engine=self.engine, app=self
            )
            self.engine.time_system = self.time_system
        from .ui.time_hud import TimeHUD

        self.time_hud = TimeHUD(self)
        self.storyline_interpreter = StorylineInterpreter(self, storyline)
        interp = self.storyline_interpreter
        for key, value in (role.grants or {}).items():
            interp.set_variable(str(key), value)
        interp.set_variable("player_role", role.id)
        interp.set_variable("player_role_label", role.label)
        interp.set_variable(
            "player_archetype_id",
            (self.player_identity or {}).get("archetype_id", ""),
        )
        self._set_identity_variables(interp)
        self.world_config = load_world(storyline.get("world_path") or None)
        interp.set_variable(
            "world_title",
            self.world_config.get("title", "Мир"),
        )
        interp.set_variable("world_days", self.world_config.get("days", 30))
        interp.set_variable(
            "world_actions_per_day",
            self.world_config.get("actions_per_day", 3),
        )
        interp.set_variable(
            "world_domains",
            [
                item.get("label", item.get("id"))
                for item in self.world_config.get("domains", [])
            ],
        )
        logger.info(
            "Сюжет мира запущен: %s; роль=%s; мир=%s",
            storyline.get("storyline_id", "?"),
            role.id,
            self.world_config.get("id"),
        )
        self._play_next_scene()

    def _set_identity_variables(self, interp):
        """Пробросить личность героя и титул в текст сцен."""
        if interp is None:
            return
        preset = getattr(self, "campaign_preset", None)
        if preset is not None:
            title = getattr(preset, "player_role_title", "")
            if title:
                interp.set_variable("player_role_title", title)
        identity = dict(self.player_identity or {})
        if not identity:
            return
        mapping = {
            "player_character_name": "name",
            "player_character_gender": "gender_label",
            "player_character_origin": "origin_label",
            "player_character_vocation": "vocation_label",
            "player_character_value": "value_label",
            "player_character_flaw": "flaw_label",
            "player_character_trait": "trait_label",
            "player_character_trait_summary": "trait_summary",
            "player_character_biography": "biography",
            "player_character_summary": "summary",
        }
        for variable, key in mapping.items():
            value = identity.get(key)
            if value:
                interp.set_variable(variable, value)

    def _start_automata_storyline(self, storyline, role):
        from campaign.automata import AutomataCampaign
        from view.support.storyline import StorylineInterpreter

        preset = self.campaign_preset
        self.automata_campaign = AutomataCampaign(
            preset, seed=self._campaign_seed(storyline)
        )
        self.state = None
        self.engine = None
        self.player_idx = 0
        self.time_system = None
        self.strategy = None
        self.strategy_config = None
        self.world = None
        self.world_clock = None
        self.player_profile = None
        self.pending_storyline_outcome = None
        self.dialogue_memory = None
        self.storyline_interpreter = StorylineInterpreter(self, storyline)
        interp = self.storyline_interpreter
        interp.set_variable("campaign_mode", "automata")
        for key, value in (role.grants or {}).items():
            interp.set_variable(str(key), value)
        interp.set_variable("player_role", role.id)
        interp.set_variable("player_role_label", role.label)
        interp.set_variable("player_faction_id", preset.player_faction_id)
        interp.set_variable("campaign_preset_id", preset.preset_id)
        interp.set_variable("player_side", self.automata_campaign.player_side)
        interp.set_variable("enemy_side", self.automata_campaign.rival_side)
        player_character = preset.player_character or {}
        player_faction = preset.player_faction or {}
        enemy_faction = preset.enemy_faction or {}
        player_organization = preset.player_organization or {}
        enemy_organization = (
            preset.organization(enemy_faction.get("organization_id")) or {}
        )
        interp.set_variable(
            "player_character_id", player_character.get("id")
        )
        interp.set_variable(
            "player_character_name",
            player_character.get("name") or "Лидер фракции",
        )
        self._set_identity_variables(interp)
        interp.set_variable(
            "player_faction_name", player_faction.get("name") or "ваша фракция"
        )
        interp.set_variable(
            "enemy_faction_name", enemy_faction.get("name") or "противник"
        )
        interp.set_variable(
            "player_organization_name",
            player_organization.get("name") or "организация",
        )
        interp.set_variable(
            "enemy_organization_name",
            enemy_organization.get("name") or "чужая организация",
        )
        interp.set_variable(
            "player_faction_goals", player_faction.get("goals") or []
        )
        populations = preset.scenario.get("populations") or {}
        interp.set_variable(
            "player_companies", int(populations.get(preset.player_side, 0))
        )
        interp.set_variable(
            "enemy_companies", int(populations.get(preset.enemy_side, 0))
        )
        interp.state["automata"] = self.automata_campaign.snapshot()
        logger.info(
            "Кампания автоматов запущена: %s; роль=%s; игрок=%s; "
            "действий за интервал=%d",
            storyline.get("storyline_id", "?"),
            role.id,
            self.automata_campaign.player_side,
            self.automata_campaign.actions_per_cycle,
        )
        self._play_next_scene()

    def start_storyline(
        self, storyline, faction_id=None, player_identity=None
    ):
        """Запустить сюжет; личность применяется до сборки кампании.

        Редактор личности передаёт сюда готовый профиль. Пресет меняет
        только игрового персонажа и подпись лидера, поэтому баланс, seed и
        состав фракций остаются прежними.

        Если выбранная роль несёт ``archetype_id`` (P1/P2: гибкость
        персонажа), он пробрасывается в ``player_identity`` до применения
        личности, чтобы ``CampaignPreset.apply_player_identity`` перенёс
        стартовую точку архетипа (социальный слой, стартовые работы,
        теги сюжета) на игрового персонажа.
        """
        from campaign import CampaignPresetGenerator
        from view.support.storyline import StorylineInterpreter
        from view.support.scenario import build_world
        from view.support.world import CampaignEngine
        from view.support.time_system import CampaignTimeSystem

        role = self.selected_role or self.role_catalog.default_role()
        self.selected_role = role
        if faction_id is not None:
            self.selected_faction_id = faction_id
        self.player_identity = dict(player_identity or {})
        archetype_id = (
            str(getattr(self, "selected_archetype_id", "") or "")
            or getattr(role, "archetype_id", "")
            or ""
        )
        if archetype_id and "archetype_id" not in self.player_identity:
            self.player_identity["archetype_id"] = archetype_id
        if storyline.get("world_path"):
            self._start_world_storyline(storyline, role)
            return
        template_path = storyline.get("campaign_template") or None
        if template_path and not os.path.isabs(template_path):
            template_path = os.path.normpath(
                os.path.join(BASE_DIR, "..", template_path)
            )
        self.campaign_preset = CampaignPresetGenerator(
            catalog=self.role_catalog,
            template_path=template_path,
        ).generate(
            role_id=role.id,
            seed=self._campaign_seed(storyline),
            player_faction_id=self.selected_faction_id,
        )
        selected_character_id = str(
            getattr(self, "selected_player_character_id", "") or ""
        )
        if selected_character_id:
            try:
                self.campaign_preset.select_player_character(
                    selected_character_id
                )
            except Exception as exc:
                logger.warning(
                    "Выбранный персонаж недоступен: %s", exc
                )
        if self.player_identity:
            self.campaign_preset.apply_player_identity(
                self.player_identity
            )
        self.selected_faction_id = self.campaign_preset.player_faction_id
        if str(self.campaign_preset.scenario.get("mode") or "") == "automata":
            self._start_automata_storyline(storyline, role)
            return
        self.automata_campaign = None
        self.scenario_path = storyline.get(
            "scenario_path", "scenarios/mvp.json"
        )
        self.pending_storyline_outcome = None
        state = build_world(
            scenario_path=self.scenario_path,
            content=self.content,
            campaign_preset=self.campaign_preset,
            campaign_role=role,
        )
        self.state = state
        self.engine = CampaignEngine(state)
        self.engine.engagements = state.engagements
        self.player_idx = state.player_idx
        self.time_system = CampaignTimeSystem(
            state, engine=self.engine, app=self
        )
        self.engine.time_system = self.time_system
        from .ui.time_hud import TimeHUD

        self.time_hud = TimeHUD(self)
        self.storyline_interpreter = StorylineInterpreter(self, storyline)
        interp = self.storyline_interpreter
        for key, value in (role.grants or {}).items():
            interp.set_variable(str(key), value)
        interp.set_variable("player_role", role.id)
        interp.set_variable("player_role_label", role.label)
        interp.set_variable(
            "player_faction_id", self.campaign_preset.player_faction_id
        )
        interp.set_variable(
            "campaign_preset_id", self.campaign_preset.preset_id
        )
        player_character = self.campaign_preset.player_character or {}
        player_faction = self.campaign_preset.player_faction or {}
        enemy_faction = self.campaign_preset.enemy_faction or {}
        player_organization = self.campaign_preset.player_organization or {}
        enemy_organization = (
            self.campaign_preset.organization(
                enemy_faction.get("organization_id")
            )
            or {}
        )
        companies = self.campaign_preset.scenario.get("companies") or {}
        if player_character:
            interp.set_variable(
                "player_character_id", player_character.get("id")
            )
            interp.set_variable(
                "player_character_name", player_character.get("name")
            )
            self._set_identity_variables(interp)
            state.needs.commander.name = str(
                player_character.get("name") or "Лидер фракции"
            )
            state.needs.commander.archetype = "faction_leader"
        interp.set_variable("player_side", self.campaign_preset.player_side)
        interp.set_variable("enemy_side", self.campaign_preset.enemy_side)
        interp.set_variable(
            "player_faction_name", player_faction.get("name") or "ваша фракция"
        )
        interp.set_variable(
            "enemy_faction_name", enemy_faction.get("name") or "противник"
        )
        interp.set_variable(
            "player_organization_name",
            player_organization.get("name") or "организация",
        )
        interp.set_variable(
            "enemy_organization_name",
            enemy_organization.get("name") or "чужая организация",
        )
        interp.set_variable(
            "player_companies",
            int(companies.get(self.campaign_preset.player_side, 0)),
        )
        interp.set_variable(
            "enemy_companies",
            int(companies.get(self.campaign_preset.enemy_side, 0)),
        )
        strategy_path = storyline.get("strategy_path") or (
            self.campaign_preset.scenario.get("strategy_path")
        )
        if strategy_path:
            from campaign.strategy import load_strategy

            self.strategy_config = load_strategy(strategy_path)
            interp.set_variable(
                "strategy_title",
                self.strategy_config.get("title", "Хартия"),
            )
            interp.set_variable(
                "strategy_days",
                self.strategy_config.get("days", 10),
            )
            interp.set_variable(
                "strategy_actions_per_day",
                self.strategy_config.get("actions_per_day", 3),
            )
        interp.set_variable(
            "player_faction_goals", player_faction.get("goals") or []
        )
        interp.state["initial_manpower"] = float(
            sum(
                value
                for value, det in zip(state.initial_manpower, state.units)
                if det.side == state.player_side
            )
        )
        if 0 <= state.player_idx < state.count:
            state.log_event(
                state.player_idx,
                "Роль: %s" % role.label,
            )
            state.log_event(
                state.player_idx,
                "Кампания: %s" % self.campaign_preset.title,
            )
        logger.info(
            "Сюжет запущен: %s; роль=%s; пресет=%s",
            storyline.get("storyline_id", "?"),
            role.id,
            self.campaign_preset.preset_id,
        )
        self._play_next_scene()

    def _free_start_entry(self, storyline, scene=None):
        """Стартовая должность свободного режима по архетипу.

        Данные живут в сюжете (``free_start``), а не в Python: новый
        архетип добавляет точку входа одним JSON. Если архетип не выбран,
        берётся архетип роли; если и его нет — игрок сам выберет должность.
        """
        data = (scene or {}).get("free_start") if scene else None
        if not data:
            data = (storyline or {}).get("free_start") or {}
        if not isinstance(data, dict):
            return {}
        archetype_id = str(
            getattr(self, "selected_archetype_id", "") or ""
        )
        if not archetype_id:
            archetype_id = str(
                (self.player_identity or {}).get("archetype_id") or ""
            )
        if not archetype_id:
            archetype_id = str(
                getattr(
                    getattr(self, "selected_role", None),
                    "archetype_id",
                    "",
                )
                or ""
            )
        entry = data.get(archetype_id) or {}
        if isinstance(entry, str):
            return {"node_id": entry}
        return dict(entry or {})

    def _world_profile(self, storyline):
        """Профиль мира из личности; не требует пресета и фракции."""
        if self.player_profile is not None:
            return self.player_profile
        identity = dict(self.player_identity or {})
        if not identity:
            return None
        from campaign.world import (
            load_biography,
            profile_from_identity,
        )

        try:
            biography = load_biography(
                (storyline or {}).get("biography_path") or None
            )
        except Exception as exc:
            logger.warning("Биография мира недоступна: %s", exc)
            biography = {}
        self.player_profile = profile_from_identity(
            identity,
            biography=biography,
            seed=self._campaign_seed(storyline or {}),
        )
        return self.player_profile
