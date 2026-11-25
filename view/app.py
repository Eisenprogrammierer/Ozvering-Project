"""Приложение: экраны, сюжеты, кампании и сохранения.

Класс ``App`` собран из миксинов по швам: ядро, запуск
сюжета, сцены, поток кампании, диалог, сохранения и меню.
Публичный API и точка входа ``main`` не менялись."""

from __future__ import annotations

from .app_support import (
    BASE_DIR,
    BG_COLOR,
    BaseScreen,
    FONT_PATH,
    FPS,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    _ArenaHostScreen,
    _AutomataSaveState,
    _WorldSaveState,
    _find_first_valid_ttf,
    load_font,
    logger,
    os,
    pygame,
    sys,
    time,
)

from .app_core import AppCoreMixin
from .app_storyline import AppStorylineMixin
from .app_scenes import AppScenesMixin
from .app_flow import AppFlowMixin
from .app_dialogue import AppDialogueMixin
from .app_saves import AppSavesMixin
from .app_menu import AppMenuMixin


class App(
    AppCoreMixin,
    AppStorylineMixin,
    AppScenesMixin,
    AppFlowMixin,
    AppDialogueMixin,
    AppSavesMixin,
    AppMenuMixin,
):

    def __init__(self, checkpoint=""):
        pygame.init()
        pygame.display.set_caption("Operation Ozverin — MVP")
        from view.support.settings_store import load_settings

        self.settings = load_settings()
        self.fullscreen = False
        self.checkpoint = str(checkpoint or "")
        self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        if self.settings.get("fullscreen"):
            self.toggle_fullscreen()
        self.clock = pygame.time.Clock()
        self.font_title = load_font(32)
        self.font_body = load_font(20)
        self.font_small = load_font(15)
        self.font_tiny = load_font(11)
        self.running = True
        self.active = True
        self.scenario_path = "scenarios/mvp.json"
        self.storyline_interpreter = None
        self.pending_storyline_outcome = None
        self.strategy = None
        self.strategy_config = None
        self.world = None
        self.world_config = None
        self.world_clock = None
        self.player_profile = None
        self.player_identity = None

        from campaign import RoleCatalog, RoleError

        try:
            self.role_catalog = RoleCatalog.load()
        except RoleError as exc:
            logger.warning("Роли не загружены: %s", exc)
            self.role_catalog = None
        self.selected_role = None
        self.selected_archetype_id = ""
        self.selected_player_character_id = ""
        self.selected_player_character_label = ""
        self.selected_archetype_label = ""
        self.selected_faction_id = None
        self.campaign_preset = None
        self.automata_campaign = None
        self.dialogue_memory = None
        self._dialogue_catalog_cache = None
        from .ui.music_manager import MusicManager

        self.music = MusicManager(
            os.path.normpath(os.path.join(BASE_DIR, "..", "music"))
        )
        from view.support.settings_store import apply_music

        apply_music(self.settings, self.music)
        from view.support.content import Content
        from view.support.scenario import build_world
        from view.support.world import CampaignEngine
        from view.support.time_system import CampaignTimeSystem
        from campaign.errors import CampaignError

        self.content = Content()
        state = None
        if self.role_catalog is not None:
            try:
                state = build_world(content=self.content)
            except (ValueError, CampaignError) as exc:
                logger.warning("Базовый военный мир не собран: %s", exc)
        self.state = state
        if state is None:
            self.engine = None
            self.player_idx = 0
            self.time_system = None
        else:
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


def _arg_value(argv, name, default=""):
    """Значение флага `name` из списка аргументов; `default`, если нет."""
    if name not in argv:
        return default
    index = argv.index(name)
    if index + 1 >= len(argv):
        return default
    return argv[index + 1]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fullscreen = ("--fullscreen" in argv) or ("-f" in argv)
    from agents import find_checkpoint, list_checkpoints

    checkpoints_dir = _arg_value(argv, "--checkpoints-dir")
    if "--list-checkpoints" in argv:
        rows = list_checkpoints(directory=checkpoints_dir or None)
        if not rows:
            print("Чекпойнтов не найдено.")
        for row in rows:
            print("%-8s %s" % (row["kind"], row["path"]))
        return 0
    checkpoint = _arg_value(argv, "--checkpoint")
    if not checkpoint and "--no-auto-checkpoint" not in argv:
        checkpoint = find_checkpoint(directory=checkpoints_dir or None)
    app = App(checkpoint=checkpoint)
    if fullscreen:
        app.toggle_fullscreen()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
