"""Сохранение, загрузка, продолжение и быстрый старт."""

from __future__ import annotations

from .app_support import (
    _AutomataSaveState,
    _WorldSaveState,
    logger,
    time,
)


class AppSavesMixin:

    def _save_automata_game(self, slot_name, campaign):
        from view.support.save_system import save_game as do_save

        storyline_snapshot = None
        if self.storyline_interpreter is not None:
            storyline_snapshot = self.storyline_interpreter.get_save_snapshot()
        dialogue_snapshot = None
        if self.dialogue_memory is not None:
            dialogue_snapshot = self.dialogue_memory.to_dict()
        path = do_save(
            _AutomataSaveState(campaign.save_snapshot()),
            None,
            slot_name,
            scenario_path="automata",
            storyline_snapshot=storyline_snapshot,
            campaign_role=self.selected_role,
            campaign_preset=self.campaign_preset,
            dialogue_snapshot=dialogue_snapshot,
        )
        logger.info(
            "Сохранение автоматов записано: слот=%s, цикл=%d",
            slot_name,
            campaign.turn,
        )
        return path

    def _load_automata_game(self, snapshot, preset, automata_snapshot):
        from campaign.automata import AutomataCampaign
        from view.support.storyline import (
            StorylineInterpreter,
            load_storyline,
        )

        if preset is None:
            logger.warning(
                "Сохранение автоматов без пресета: восстановление невозможно"
            )
            return False
        self.state = None
        self.engine = None
        self.player_idx = 0
        self.time_system = None
        self.strategy = None
        self.strategy_config = None
        self.world = None
        self.world_config = None
        self.world_clock = None
        self.player_profile = None
        self.pending_storyline_outcome = None
        self.automata_campaign = AutomataCampaign(
            preset, snapshot=automata_snapshot
        )
        self.storyline_interpreter = None
        storyline_snapshot = snapshot.get("storyline")
        if storyline_snapshot:
            storyline_id = storyline_snapshot.get("storyline_id")
            storyline = load_storyline(storyline_id) if storyline_id else None
            if storyline is not None:
                self.storyline_interpreter = StorylineInterpreter(
                    self, storyline
                )
                self.storyline_interpreter.load_from_snapshot(
                    storyline_snapshot
                )
        from .screens.automata_screen import AutomataScreen

        self.music.request_category("ambient")
        self.manager.replace_all(
            AutomataScreen(self, self.automata_campaign)
        )
        return True

    def _save_world_game(self, slot_name):
        from view.support.save_system import save_game as do_save

        storyline_snapshot = None
        if self.storyline_interpreter is not None:
            storyline_snapshot = self.storyline_interpreter.get_save_snapshot()
        if storyline_snapshot is None:
            storyline_snapshot = {"state": {}}
        world_payload = self.world.to_dict()
        world_payload["saved_at"] = time.time()
        if self.world_clock is not None:
            world_payload["clock"] = self.world_clock.to_snapshot()
        storyline_snapshot.setdefault("state", {})["world"] = world_payload
        path = do_save(
            _WorldSaveState(),
            None,
            slot_name,
            scenario_path=self.scenario_path,
            storyline_snapshot=storyline_snapshot,
            campaign_role=self.selected_role,
            campaign_preset=None,
            dialogue_snapshot=(
                self.dialogue_memory.to_dict()
                if self.dialogue_memory is not None
                else None
            ),
        )
        logger.info("Сохранение мира записано: слот=%s", slot_name)
        return path

    def save_game(self, slot_name):
        campaign = getattr(self, "automata_campaign", None)
        if campaign is not None:
            return self._save_automata_game(slot_name, campaign)
        if self.engine is None and self.world is not None:
            return self._save_world_game(slot_name)
        if self.engine is None or self.time_system is None:
            return None
        self.engine.state.engagements = list(self.engine.engagements)
        from view.support.save_system import save_game as do_save

        storyline_snapshot = None
        if self.storyline_interpreter is not None:
            storyline_snapshot = self.storyline_interpreter.get_save_snapshot()
        if self.strategy is not None:
            if storyline_snapshot is None:
                storyline_snapshot = {"state": {}}
            storyline_snapshot.setdefault("state", {})[
                "strategy"
            ] = self.strategy.to_dict()
        if self.world is not None:
            if storyline_snapshot is None:
                storyline_snapshot = {"state": {}}
            world_payload = self.world.to_dict()
            world_payload["saved_at"] = time.time()
            if self.world_clock is not None:
                world_payload["clock"] = self.world_clock.to_snapshot()
            storyline_snapshot.setdefault("state", {})[
                "world"
            ] = world_payload
        path = do_save(
            self.engine.state,
            self.time_system,
            slot_name,
            scenario_path=self.scenario_path,
            storyline_snapshot=storyline_snapshot,
            campaign_role=self.selected_role,
            campaign_preset=self.campaign_preset,
            dialogue_snapshot=(
                self.dialogue_memory.to_dict()
                if self.dialogue_memory is not None
                else None
            ),
        )
        logger.info("Сохранение записано: слот=%s", slot_name)
        return path

    def load_game(self, slot_name):
        from view.support.save_system import load_game as do_load
        from view.support.save_system import save_is_compatible
        from view.support.scenario import build_world
        from view.support.world import CampaignEngine
        from view.support.time_system import CampaignTimeSystem

        snapshot = do_load(slot_name)
        if snapshot is None:
            logger.warning("Загрузка не выполнена: слот=%s", slot_name)
            return False
        if not save_is_compatible(snapshot):
            logger.warning(
                "Сохранение несовместимо с кампаниями автоматов, "
                "стратегии и мира: слот=%s (легаси-RTS не открывается)",
                slot_name,
            )
            return False
        scenario_path = snapshot.get("scenario_path", "scenarios/mvp.json")
        self.scenario_path = scenario_path
        self.pending_storyline_outcome = None
        self._restore_dialogue_memory(snapshot.get("dialogue"))
        self.strategy = None
        self.strategy_config = None
        self.world = None
        self.world_config = None
        self.world_clock = None
        self.player_profile = None
        from campaign.preset import CampaignPreset
        from campaign.roles import RoleSpec

        raw_preset = snapshot.get("campaign_preset")
        preset = None
        if raw_preset:
            try:
                preset = CampaignPreset.from_dict(raw_preset)
            except Exception as exc:
                logger.warning("Пресет из сохранения не прочитан: %s", exc)
        self.campaign_preset = preset
        self.selected_faction_id = (
            preset.player_faction_id if preset is not None else None
        )
        raw_role = snapshot.get("campaign_role")
        if not raw_role and preset is not None:
            raw_role = preset.role.as_dict()
        if not raw_role:
            raw_role = (snapshot.get("campaign") or {}).get("campaign_role")
        self.selected_role = None
        if raw_role:
            try:
                self.selected_role = RoleSpec.from_data(raw_role)
            except Exception as exc:
                try:
                    role_id = (
                        raw_role.get("id")
                        if isinstance(raw_role, dict)
                        else raw_role
                    )
                    self.selected_role = self.role_catalog.role(role_id)
                except Exception:
                    logger.warning("Роль из сохранения не прочитана: %s", exc)
        automata_snapshot = (snapshot.get("campaign") or {}).get(
            "automata"
        )
        if automata_snapshot is not None:
            if self._load_automata_game(
                snapshot, preset, automata_snapshot
            ):
                logger.info(
                    "Загрузка автоматов выполнена: слот=%s", slot_name
                )
                return True
            return False
        storyline_snapshot = snapshot.get("storyline", None)
        strategy_snapshot = None
        world_snapshot = None
        if isinstance(storyline_snapshot, dict):
            state_snapshot = storyline_snapshot.get("state") or {}
            strategy_snapshot = state_snapshot.get("strategy")
            world_snapshot = state_snapshot.get("world")
            storyline_id = storyline_snapshot.get("storyline_id")
            if storyline_id:
                from view.support.storyline import (
                    load_storyline,
                    StorylineInterpreter,
                )

                storyline = load_storyline(storyline_id)
                if storyline is not None:
                    self.storyline_interpreter = StorylineInterpreter(
                        self, storyline
                    )
                    self.storyline_interpreter.load_from_snapshot(
                        storyline_snapshot
                    )
        if world_snapshot is not None:
            # Свободный режим: состояние живёт в WorldEngine, а не в
            # военной кампании. Не требуем CampaignState и пресет.
            self.state = None
            self.engine = None
            self.player_idx = 0
            self.time_system = None
            from .ui.time_hud import TimeHUD

            self.time_hud = TimeHUD(self)
        else:
            state = build_world(
                scenario_path=scenario_path,
                campaign_snapshot=snapshot.get("campaign", {}),
                content=self.content,
                campaign_preset=preset,
                campaign_role=self.selected_role,
            )
            self.state = state
            self.engine = CampaignEngine(state)
            self.engine.engagements = state.engagements
            self.player_idx = state.player_idx
            self.time_system = CampaignTimeSystem(
                state, engine=self.engine, app=self
            )
            self.time_system.load_from_snapshot(
                snapshot.get("time_system", {})
            )
            self.engine.time_system = self.time_system
            from .ui.time_hud import TimeHUD

            self.time_hud = TimeHUD(self)
        if world_snapshot is not None or self._is_world_campaign():
            from campaign.world import WorldEngine, load_world
            from .screens.automaton_select import AutomatonSelectScreen
            from .screens.world_screen import WorldScreen

            storyline = (
                self.storyline_interpreter.storyline
                if self.storyline_interpreter is not None
                else {}
            )
            self.world_config = load_world(storyline.get("world_path") or None)
            profile = (
                world_snapshot.get("profile")
                if world_snapshot is not None
                else None
            )
            self.player_profile = profile
            self.world = WorldEngine(
                self.world_config,
                profile=profile,
                seed=self._campaign_seed(storyline),
                snapshot=world_snapshot,
            )
            if getattr(self.world, "realtime", False):
                from campaign.free_clock import FreeClock

                self.world_clock = FreeClock.from_snapshot(
                    (world_snapshot or {}).get("clock"),
                    seconds_per_day=self.world.seconds_per_day,
                    max_catchup_days=self.world.max_offline_days,
                    speeds=getattr(self.world, "time_speeds", None),
                )
            else:
                self.world_clock = None
            self._apply_offline_progress(world_snapshot)
            self.music.request_category("ambient")
            if self.world.attached:
                self.manager.replace_all(
                    WorldScreen(
                        self, self.world, free_clock=self.world_clock
                    )
                )
            else:
                self.manager.replace_all(
                    AutomatonSelectScreen(
                        self,
                        storyline.get("world_path") or None,
                        engine=self.world,
                    )
                )
        elif self._is_strategy_campaign() or strategy_snapshot is not None:
            self._open_strategy(snapshot=strategy_snapshot)
        else:
            logger.warning(
                "Сохранение не содержит автоматов, стратегии или мира: "
                "слот=%s",
                slot_name,
            )
            return False
        logger.info("Загрузка выполнена: слот=%s", slot_name)
        return True

    def continue_game(self):
        from view.support.save_system import list_compatible_saves

        saves = list_compatible_saves()
        if not saves:
            logger.info(
                "Продолжить: нет совместимых сохранений (легаси-RTS пропущен)"
            )
            return
        saves.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        self.load_game(saves[0]["name"])

    def quick_campaign(self):
        """Быстрая кампания из главного меню (ось B, единый путь запуска).

        Тот же `WorldEngine`/`CampaignEnv`, что и в полном потоке новой
        игры и в обучении, но без выбора роли/фракции/сюжетной линии —
        игрок попадает в мир сразу. Сeed общий с полным потоком
        (`_campaign_seed`), чтобы старты были воспроизводимы.
        """
        from .screens.campaign_quick import CampaignQuickScreen

        seed = self._campaign_seed({})
        self.manager.push(CampaignQuickScreen(self, seed=seed))
        logger.info("Открыта быстрая кампания: seed=%s", seed)
