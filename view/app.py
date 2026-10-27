import os
import sys
import logging
import pygame

SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 60
BG_COLOR = (15, 15, 25)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.normpath(
    os.path.join(BASE_DIR, "..", "operation_ozverin.log")
)


def _build_logger(name):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.propagate = False
    return logger


logger = _build_logger("view.app")


def _find_first_valid_ttf():
    fonts_dir = os.path.normpath(
        os.path.join(BASE_DIR, "..", "assets", "fonts")
    )
    if not os.path.isdir(fonts_dir):
        return None
    for filename in sorted(os.listdir(fonts_dir)):
        if filename.lower().endswith(".ttf"):
            path = os.path.join(fonts_dir, filename)
            try:
                font = pygame.font.Font(path, 12)
                if font.render("Test", True, (255, 255, 255)) is not None:
                    return path
            except Exception:
                continue
    return None


pygame.font.init()
FONT_PATH = _find_first_valid_ttf()


def load_font(size):
    if FONT_PATH:
        try:
            return pygame.font.Font(FONT_PATH, size)
        except Exception:
            pass
    logger.warning("Шрифт не найден или не работает, использую встроенный")
    return pygame.font.Font(None, size)


class App:

    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Operation Ozverin — MVP")
        self.fullscreen = False
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        self.clock = pygame.time.Clock()
        self.font_title = load_font(32)
        self.font_body = load_font(20)
        self.font_small = load_font(15)
        self.font_tiny = load_font(11)
        self.running = True
        self.scenario_path = "scenarios/mvp.json"
        self.storyline_interpreter = None
        self.pending_storyline_outcome = None
        self.strategy = None
        self.strategy_config = None

        from campaign import RoleCatalog

        self.role_catalog = RoleCatalog.load()
        self.selected_role = None
        self.selected_faction_id = None
        self.campaign_preset = None
        from .ui.music_manager import MusicManager

        self.music = MusicManager(
            os.path.normpath(os.path.join(BASE_DIR, "..", "music"))
        )
        from view.support.content import Content
        from view.support.scenario import build_world
        from view.support.world import CampaignEngine
        from view.support.time_system import CampaignTimeSystem

        self.content = Content()
        state = build_world(content=self.content)
        self.state = state
        self.engine = CampaignEngine(state)
        self.engine.engagements = getattr(state, "engagements", [])
        self.player_idx = state.player_idx
        self.time_system = CampaignTimeSystem(
            state, engine=self.engine, app=self
        )
        self.engine.time_system = self.time_system
        from .ui.time_hud import TimeHUD

        self.time_hud = TimeHUD(self)
        from .ui.screen_manager import ScreenManager
        from .screens.main_menu import MainMenuScreen

        self.manager = ScreenManager()
        self.manager.replace_all(MainMenuScreen(self))
        self.music.request_category("overture")
        logger.info("Приложение инициализировано")

    def finish_storyline_outcome(self, outcome):
        if outcome not in ("win", "lose"):
            return False
        if self.storyline_interpreter is None:
            return False
        if self.pending_storyline_outcome is not None or getattr(
            self.storyline_interpreter, "finished", False
        ):
            return False
        self.pending_storyline_outcome = outcome
        self.storyline_interpreter.finished = True
        return True

    def check_storyline_end_of_day(self):
        if self.storyline_interpreter is None:
            return
        if getattr(self.storyline_interpreter, "finished", False):
            return
        lose = False
        win = False
        if hasattr(self.storyline_interpreter, "check_lose_conditions"):
            lose = self.storyline_interpreter.check_lose_conditions()
        if hasattr(self.storyline_interpreter, "check_win_conditions"):
            win = self.storyline_interpreter.check_win_conditions()
        if lose:
            self.finish_storyline_outcome("lose")
        elif win:
            self.finish_storyline_outcome("win")

    def apply_to_player(self, channel, delta):
        if self.engine:
            self.engine.state.add_voltage(self.player_idx, channel, delta)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.screen = pygame.display.set_mode(
                (SCREEN_WIDTH, SCREEN_HEIGHT),
                pygame.FULLSCREEN | pygame.SCALED,
            )
        else:
            self.screen = pygame.display.set_mode(
                (SCREEN_WIDTH, SCREEN_HEIGHT)
            )
        logger.info("Полноэкранный режим: %s", self.fullscreen)

    def advance_turn(self):
        if not self.engine:
            return
        self.engine.tick()
        st = self.engine.state
        if 0 <= st.player_idx < st.count:
            st.log_event(
                st.player_idx, f"Ход {self.engine.tick_count} обработан"
            )
        logger.info("Выполнен тик: %d", self.engine.tick_count)

    def open_turn_log(self):
        from .ui.overlays import TurnLogOverlay

        self.manager.push(TurnLogOverlay(self))
        logger.debug("Открыт оверлей лога тика")

    def execute_player_action(self, action_id, on_completed=None):
        if self.time_system is None:
            return
        result = self.time_system.execute_action(action_id)
        status = result.get("status")
        logger.info("Действие игрока: %s, статус: %s", action_id, status)
        if status == "interrupted":
            interrupt = result.get("interrupt")
            if interrupt is not None:
                from .screens.interrupt_modal import InterruptModal

                self.manager.push(InterruptModal(self, interrupt))
        elif status == "mandatory_scene":
            scene_id = result.get("mandatory_scene")
            if scene_id is not None:
                from .screens.mandatory_screen import MandatorySceneScreen

                self.manager.push(MandatorySceneScreen(self, scene_id))
        elif status == "blocked":
            scene_id = result.get("mandatory_scene")
            if result.get("reason") == "mandatory_scene_pending" and scene_id:
                from .screens.mandatory_screen import MandatorySceneScreen

                self.manager.push(MandatorySceneScreen(self, scene_id))
        elif status == "completed":
            if on_completed is not None:
                on_completed()

    def new_game(self):
        from .screens.role_select import RoleSelectScreen

        self.selected_role = None
        self.selected_faction_id = None
        self.campaign_preset = None
        self.strategy = None
        self.strategy_config = None
        self.manager.push(RoleSelectScreen(self))
        logger.info("Запрошена новая игра: выбор роли")

    def _campaign_seed(self, storyline):
        try:
            return int(
                storyline.get("campaign_seed", storyline.get("seed", 7))
            )
        except (TypeError, ValueError):
            return 7

    def start_storyline(self, storyline, faction_id=None):
        from campaign import CampaignPresetGenerator
        from view.support.storyline import StorylineInterpreter
        from view.support.scenario import build_world
        from view.support.world import CampaignEngine
        from view.support.time_system import CampaignTimeSystem

        role = self.selected_role or self.role_catalog.default_role()
        self.selected_role = role
        if faction_id is not None:
            self.selected_faction_id = faction_id
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
        self.selected_faction_id = self.campaign_preset.player_faction_id
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
        elif scene_type == "gameplay":
            if self._is_strategy_campaign():
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

    def _play_gameplay(self, scene):
        from .screens.rts_screen import RTSScreen

        self.music.request_category("ambient")
        self.manager.replace_all(RTSScreen(self))

    def _show_win_scene(self):
        interp = self.storyline_interpreter
        if interp is None:
            self._return_to_menu()
            return
        win_scene = interp.resolve_variant(
            interp.storyline.get("win_scene", {})
        )
        slides = self._resolve_slides(win_scene)
        if not slides:
            self._return_to_menu()
            return
        self.music.request_category("victorious", fade=True)
        from .screens.visual_novel import VisualNovelScreen

        logger.info("Показана победная сцена")
        self.manager.replace_all(
            VisualNovelScreen(self, slides, self._return_to_menu)
        )

    def _show_lose_scene(self):
        interp = self.storyline_interpreter
        if interp is None:
            self._return_to_menu()
            return
        lose_scene = interp.resolve_variant(
            interp.storyline.get("lose_scene", {})
        )
        slides = self._resolve_slides(lose_scene)
        if not slides:
            self._return_to_menu()
            return
        self.music.request_category("tragic", fade=True)
        from .screens.visual_novel import VisualNovelScreen

        logger.info("Показана проигрышная сцена")
        self.manager.replace_all(
            VisualNovelScreen(self, slides, self._return_to_menu)
        )

    def _return_to_menu(self):
        self.storyline_interpreter = None
        self.pending_storyline_outcome = None
        self.strategy = None
        self.strategy_config = None
        self.music.request_category("overture")
        from .screens.main_menu import MainMenuScreen

        self.manager.replace_all(MainMenuScreen(self))
        logger.info("Возврат в главное меню")

    def process_pending_storyline_outcome(self):
        outcome = self.pending_storyline_outcome
        if outcome is None:
            return
        self.pending_storyline_outcome = None
        if outcome == "lose":
            self._show_lose_scene()
        elif outcome == "win":
            self._show_win_scene()

    def process_pending_mandatory_scene(self):
        ts = self.time_system
        if ts is None:
            return
        scene_id = ts.pending_mandatory_scene
        if scene_id is None:
            return
        if not self.manager.has_time_hud_screen():
            return
        current = self.manager.current
        if current is None:
            return
        name = type(current).__name__
        if name in ("MandatorySceneScreen", "InterruptModal"):
            return
        from .screens.mandatory_screen import MandatorySceneScreen

        self.manager.push(MandatorySceneScreen(self, scene_id))
        logger.info("Выведена обязательная сцена: %s", scene_id)

    def save_game(self, slot_name):
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
            storyline_snapshot.setdefault("state", {})["strategy"] = (
                self.strategy.to_dict()
            )
        path = do_save(
            self.engine.state,
            self.time_system,
            slot_name,
            scenario_path=self.scenario_path,
            storyline_snapshot=storyline_snapshot,
            campaign_role=self.selected_role,
            campaign_preset=self.campaign_preset,
        )
        logger.info("Сохранение записано: слот=%s", slot_name)
        return path

    def load_game(self, slot_name):
        from view.support.save_system import load_game as do_load
        from view.support.scenario import build_world
        from view.support.world import CampaignEngine
        from view.support.time_system import CampaignTimeSystem

        snapshot = do_load(slot_name)
        if snapshot is None:
            logger.warning("Загрузка не выполнена: слот=%s", slot_name)
            return False
        scenario_path = snapshot.get("scenario_path", "scenarios/mvp.json")
        self.scenario_path = scenario_path
        self.pending_storyline_outcome = None
        self.strategy = None
        self.strategy_config = None
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
        self.time_system.load_from_snapshot(snapshot.get("time_system", {}))
        self.engine.time_system = self.time_system
        from .ui.time_hud import TimeHUD

        self.time_hud = TimeHUD(self)
        storyline_snapshot = snapshot.get("storyline", None)
        strategy_snapshot = None
        if storyline_snapshot is not None:
            from view.support.storyline import (
                load_storyline,
                StorylineInterpreter,
            )

            strategy_snapshot = (storyline_snapshot.get("state") or {}).get(
                "strategy"
            )
            storyline_id = storyline_snapshot.get("storyline_id")
            if storyline_id:
                storyline = load_storyline(storyline_id)
                if storyline is not None:
                    self.storyline_interpreter = StorylineInterpreter(
                        self, storyline
                    )
                    self.storyline_interpreter.load_from_snapshot(
                        storyline_snapshot
                    )
        if self._is_strategy_campaign() or strategy_snapshot is not None:
            self._open_strategy(snapshot=strategy_snapshot)
        else:
            from .screens.rts_screen import RTSScreen

            self.manager.replace_all(RTSScreen(self))
            self.music.request_category("ambient")
        logger.info("Загрузка выполнена: слот=%s", slot_name)
        return True

    def continue_game(self):
        from view.support.save_system import list_saves

        saves = list_saves()
        if not saves:
            return
        saves.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        self.load_game(saves[0]["name"])

    def open_saves(self):
        from .screens.saves_menu import SavesMenuScreen

        self.manager.push(SavesMenuScreen(self))
        logger.debug("Открыто меню сохранений")

    def open_settings(self):
        from .screens.settings_menu import SettingsMenuScreen

        self.manager.push(SettingsMenuScreen(self))
        logger.debug("Открыто меню настроек")

    def quit(self):
        logger.info("Приложение останавливается")
        self.running = False

    def run(self):
        logger.info("Главный цикл запущен")
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_F11
                ):
                    self.toggle_fullscreen()
                elif (
                    event.type == pygame.KEYDOWN
                    and event.key == pygame.K_ESCAPE
                ):
                    self.manager.handle_escape()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_t:
                    self.advance_turn()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_l:
                    self.open_turn_log()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F5:
                    self.save_game("quicksave")
                else:
                    self.manager.handle_event(event)
            dt = self.clock.tick(FPS) / 1000.0
            self.manager.update(dt)
            self.music.update()
            self.process_pending_storyline_outcome()
            self.process_pending_mandatory_scene()
            self.screen.fill(BG_COLOR)
            self.manager.draw(self.screen)
            if self.manager.has_time_hud_screen() and not getattr(
                self.manager.current, "hide_time_hud", False
            ):
                self.time_hud.draw(self.screen)
            pygame.display.flip()
        pygame.quit()
        return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fullscreen = ("--fullscreen" in argv) or ("-f" in argv)
    app = App()
    if fullscreen:
        app.toggle_fullscreen()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
