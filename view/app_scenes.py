"""Показ сцен, новеллы, документов и переходов кампаний."""

from __future__ import annotations

from .app_support import (
    logger,
)


class AppScenesMixin:

    def _play_next_scene(self):
        interp = self.storyline_interpreter
        if interp is None:
            return
        scene = interp.get_current_scene()
        if scene is None:
            if interp.check_win_conditions():
                self._show_win_scene()
            else:
                self._return_to_menu()
            return
        resolved = interp.resolve_variant(scene)
        self._play_scene(resolved)

    def _resolve_slides(self, block):
        slides = block.get("slides", []) if isinstance(block, dict) else []
        interp = self.storyline_interpreter
        if interp is None:
            return list(slides)
        return [interp.resolve_variant(s) for s in slides]

    def _play_scene(self, scene):
        scene_type = scene.get("type", "")
        logger.debug("Запуск сцены: %s", scene_type)
        if scene_type == "character_creation":
            self._play_character_creation(scene)
        elif scene_type == "automaton_choice":
            self._play_automaton_choice(scene)
        elif scene_type == "world":
            self._play_world(scene)
        elif scene_type == "world_briefing":
            self._play_world_briefing(scene)
        elif scene_type == "visual_novel":
            self._play_visual_novel(scene)
        elif scene_type == "document":
            self._play_document(scene)
        elif scene_type == "dialogue":
            self._play_dialogue(scene)
        elif scene_type == "mandatory_scene":
            self._play_mandatory_scene(scene)
        elif scene_type in ("rts_scene", "hq_scene"):
            self._play_gameplay(scene)
        elif scene_type == "strategy":
            self._play_strategy(scene)
        elif scene_type == "automata":
            self._play_automata(scene)
        elif scene_type == "gameplay":
            if self._is_automata_campaign():
                self._play_automata(scene)
            elif self._is_strategy_campaign():
                self._play_strategy(scene)
            else:
                self._play_gameplay(scene)
        else:
            interp = self.storyline_interpreter
            if interp is not None:
                interp.advance()
                self._play_next_scene()

    def _play_character_creation(self, scene):
        interp = self.storyline_interpreter
        if interp is None:
            return
        self.music.request_category("overture")
        steps = interp.storyline.get("character_creation", {}).get("steps", [])
        if not steps:
            interp.advance()
            self._play_next_scene()
            return
        interp.advance()
        from .screens.character_creation import CharacterCreationScreen

        self.manager.replace_all(CharacterCreationScreen(self, steps))

    def _play_automaton_choice(self, scene):
        interp = self.storyline_interpreter
        if interp is None:
            return
        self.music.request_category("overture")
        interp.advance()
        from .screens.automaton_select import AutomatonSelectScreen

        self.manager.replace_all(
            AutomatonSelectScreen(self, scene.get("world_path") or None)
        )

    def open_office_selection(self, engine=None):
        """Выбор должности для уже существующего мира (§7 №29)."""
        from .screens.automaton_select import AutomatonSelectScreen

        engine = engine if engine is not None else self.world
        self.manager.replace_all(AutomatonSelectScreen(self, engine=engine))
        logger.info(
            "Открыт выбор должности: день=%s",
            getattr(engine, "day", "?"),
        )

    def _play_world_briefing(self, scene):
        """Показать сводку мира, собранную из конфига и состояния."""

        from campaign.world import load_world
        from campaign.world_briefing import briefing_slides
        from .screens.visual_novel import VisualNovelScreen

        interp = self.storyline_interpreter
        storyline = (interp.storyline if interp else {}) or {}
        config = self.world_config
        if config is None:
            path = scene.get("world_path")
            if not path and interp is not None:
                path = storyline.get("world_path")
            config = load_world(path or None)
            self.world_config = config
        profile = self.player_profile
        if profile is None and (self.player_identity or interp is not None):
            profile = self._world_profile(storyline)
        slides = briefing_slides(
            config, world=self.world, profile=profile
        )
        if not slides:
            if interp is not None:
                interp.advance()
                self._play_next_scene()
            return

        def on_finish():
            if interp is not None:
                interp.advance()
                self._play_next_scene()

        self.music.request_category("overture")
        self.manager.replace_all(
            VisualNovelScreen(self, slides, on_finish)
        )
        logger.info("Сводка мира собрана из состояния: %s", storyline.get(
            "storyline_id", ""
        ))

    def _play_world(self, scene):
        from campaign.world import WorldEngine, load_world
        from .screens.world_screen import WorldScreen

        interp = self.storyline_interpreter
        storyline = (interp.storyline if interp else {}) or {}
        snapshot = (interp.state or {}).get("world") if interp else None
        config = self.world_config
        if config is None:
            path = scene.get("world_path")
            if not path and interp is not None:
                path = storyline.get("world_path")
            config = load_world(path or None)
            self.world_config = config
        profile = self.player_profile
        if profile is None and snapshot:
            profile = snapshot.get("profile")
        entry = self._free_start_entry(storyline, scene)
        if profile is None and (self.player_identity or entry):
            profile = self._world_profile(storyline)
        node_id = str(scene.get("node_id") or entry.get("node_id") or "")
        office_id = str(
            scene.get("office_id") or entry.get("office_id") or ""
        )
        if self.world is None:
            self.world = WorldEngine(
                config,
                profile=profile,
                node_id=node_id,
                office_id=office_id,
                seed=self._campaign_seed(storyline),
                snapshot=snapshot,
            )
        if getattr(self.world, "realtime", False):
            if self.world_clock is None:
                from campaign.free_clock import FreeClock

                self.world_clock = FreeClock.from_snapshot(
                    (snapshot or {}).get("clock"),
                    seconds_per_day=self.world.seconds_per_day,
                    max_catchup_days=self.world.max_offline_days,
                    speeds=getattr(self.world, "time_speeds", None),
                )
        else:
            self.world_clock = None
        if self.world.profile:
            self.player_profile = self.world.profile
        self.music.request_category("ambient")
        self.manager.replace_all(
            WorldScreen(self, self.world, free_clock=self.world_clock)
        )
        logger.info(
            "Экран мира открыт: день=%d, прикреплён=%s, узел=%s, должность=%s",
            self.world.day,
            self.world.attached,
            self.world.player_node_id,
            self.world.player_office_id,
        )

    def _play_visual_novel(self, scene):
        from .screens.visual_novel import VisualNovelScreen

        self.music.request_category("overture")

        def on_finish():
            interp = self.storyline_interpreter
            if interp is not None:
                interp.advance()
                self._play_next_scene()

        slides = self._resolve_slides(scene)
        self.manager.replace_all(VisualNovelScreen(self, slides, on_finish))

    def _play_document(self, scene):
        from .screens.document_intro import DocumentIntroScreen

        self.music.request_category("overture")

        def on_finish():
            interp = self.storyline_interpreter
            if interp is not None:
                interp.advance()
                self._play_next_scene()

        doc_data = {
            "title": scene.get("title", "ПРИКАЗ"),
            "content_stylized": scene.get("content_stylized", ""),
            "content_plain": scene.get("content_plain", ""),
            "hands_asset": scene.get("hands_asset", "items/hands_paper"),
        }
        self.manager.replace_all(
            DocumentIntroScreen(self, doc_data, on_finish_callback=on_finish)
        )

    def _play_dialogue(self, scene):
        from .screens.dialogue import DialogueScreen

        node_id = scene.get("node_id", "")
        if node_id and node_id in self.content.dialogues:
            self.manager.push(DialogueScreen(self, node_id))
        interp = self.storyline_interpreter
        if interp is not None:
            interp.advance()
            self._play_next_scene()

    def _play_mandatory_scene(self, scene):
        scene_id = scene.get("scene_id", "")
        if scene_id and self.time_system is not None:
            self.time_system.pending_mandatory_scene = scene_id
        interp = self.storyline_interpreter
        if interp is not None:
            interp.advance()
            self._play_next_scene()

    def _is_world_campaign(self):
        interp = self.storyline_interpreter
        if interp is not None:
            storyline = interp.storyline or {}
            if storyline.get("world_path"):
                return True
            scenes = storyline.get("scenes") or []
            if any(scene.get("type") == "world" for scene in scenes):
                return True
        return self.world is not None

    def _is_automata_campaign(self):
        if getattr(self, "automata_campaign", None) is not None:
            return True
        preset = self.campaign_preset
        return bool(
            preset is not None
            and str(preset.scenario.get("mode") or "") == "automata"
        )

    def _is_strategy_campaign(self):
        preset = self.campaign_preset
        if preset is not None:
            if str(preset.scenario.get("mode") or "") == "strategy":
                return True
        interp = self.storyline_interpreter
        if interp is not None:
            storyline = interp.storyline or {}
            if storyline.get("strategy_path"):
                return True
            scenes = storyline.get("scenes") or []
            if any(scene.get("type") == "strategy" for scene in scenes):
                return True
        return False

    def _play_strategy(self, scene):
        interp = self.storyline_interpreter
        snapshot = None
        if interp is not None:
            snapshot = (interp.state or {}).get("strategy")
        path = scene.get("strategy_path")
        if not path and interp is not None:
            path = (interp.storyline or {}).get("strategy_path")
        if not path and self.campaign_preset is not None:
            path = self.campaign_preset.scenario.get("strategy_path")
        self._open_strategy(snapshot=snapshot, path=path)

    def _open_strategy(self, snapshot=None, path=None):
        from campaign.strategy import StrategyEngine, load_strategy
        from .screens.strategy_screen import StrategyScreen

        if not path and self.campaign_preset is not None:
            path = self.campaign_preset.scenario.get("strategy_path")
        self.strategy_config = load_strategy(path)
        self.strategy = StrategyEngine(
            self.strategy_config,
            preset=self.campaign_preset,
            snapshot=snapshot,
        )
        interp = self.storyline_interpreter
        if interp is not None:
            interp.state["strategy"] = self.strategy.to_dict()
        self.music.request_category("ambient")
        self.manager.replace_all(StrategyScreen(self, self.strategy))
        logger.info(
            "Стратегическая кампания открыта: %s, день=%d",
            self.strategy_config.get("title", "?"),
            self.strategy.day,
        )

    def _play_automata(self, scene):
        from .screens.automata_screen import AutomataScreen

        campaign = getattr(self, "automata_campaign", None)
        if campaign is None:
            from campaign.automata import AutomataCampaign

            campaign = AutomataCampaign(
                self.campaign_preset,
                seed=self.campaign_preset.seed,
            )
            self.automata_campaign = campaign
        self.music.request_category("ambient")
        if not getattr(campaign, "briefing_seen", False):
            from campaign.chronicle import briefing_slides
            from .screens.visual_novel import VisualNovelScreen

            slides = briefing_slides(campaign)
            if slides:
                campaign.briefing_seen = True

                def on_finish():
                    self.manager.replace_all(AutomataScreen(self, campaign))

                self.manager.replace_all(
                    VisualNovelScreen(self, slides, on_finish)
                )
                logger.info(
                    "Стартовая сводка кампании собрана из состояния: %s",
                    campaign.preset_id,
                )
                return
        self.manager.replace_all(AutomataScreen(self, campaign))
        logger.info(
            "Кампания автоматов открыта: %s, цикл=%d, запас действий=%d/%d",
            campaign.preset_id,
            campaign.turn,
            campaign.actions_left,
            campaign.actions_per_cycle,
        )

    def _play_gameplay(self, scene):
        from .screens.rts_screen import RTSScreen

        self.music.request_category("ambient")
        self.manager.replace_all(RTSScreen(self))

    def _ending_slides(self, outcome):
        """Слайды финала: хроника состояния или сцена legacy-сюжета."""

        campaign = getattr(self, "automata_campaign", None)
        if campaign is not None:
            from campaign.chronicle import ending_view

            view = ending_view(campaign)
            slides = view.get("slides") or []
            if slides:
                return slides
        world = getattr(self, "world", None)
        if world is not None:
            from campaign.world_briefing import ending_view as world_ending

            view = world_ending(world, self.world_config)
            slides = view.get("slides") or []
            if slides:
                return slides
        interp = self.storyline_interpreter
        if interp is None:
            return []
        key = "win_scene" if outcome == "win" else "lose_scene"
        return self._resolve_slides(
            interp.resolve_variant(interp.storyline.get(key, {}))
        )

    def _show_win_scene(self):
        slides = self._ending_slides("win")
        if not slides:
            self._return_to_menu()
            return
        self.music.request_category("victorious", fade=True)
        from .screens.visual_novel import VisualNovelScreen

        logger.info("Показан победный финал из состояния кампании")
        self.manager.replace_all(
            VisualNovelScreen(self, slides, self._return_to_menu)
        )

    def _show_lose_scene(self):
        slides = self._ending_slides("lose")
        if not slides:
            self._return_to_menu()
            return
        self.music.request_category("tragic", fade=True)
        from .screens.visual_novel import VisualNovelScreen

        logger.info("Показан проигрышный финал из состояния кампании")
        self.manager.replace_all(
            VisualNovelScreen(self, slides, self._return_to_menu)
        )

    def _return_to_menu(self):
        self.storyline_interpreter = None
        self.pending_storyline_outcome = None
        self.automata_campaign = None
        self.strategy = None
        self.strategy_config = None
        self.world = None
        self.world_config = None
        self.world_clock = None
        self.player_profile = None
        self.music.request_category("overture")
        from .screens.main_menu import MainMenuScreen

        self.manager.replace_all(MainMenuScreen(self))
        logger.info("Возврат в главное меню")
