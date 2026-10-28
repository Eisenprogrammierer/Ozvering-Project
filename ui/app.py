import sys

import pygame

import game_engine as ge

from . import scenes as scene_pkg
from .save import SaveManager
from .scene import SceneManager

FPS = getattr(ge, "FPS", 60)


class App:

    def __init__(
        self,
        fullscreen=None,
        seed=0,
        checkpoint="",
        health_factors=None,
        speed=None,
        auto_pause=True,
    ):
        ge.LOG.info("ui.App: инициализация сценного слоя")
        ge.init_pygame_minimal()
        self.save = SaveManager(log=ge.LOG)
        self.settings = self.save.settings
        self.seed = seed
        self.checkpoint = checkpoint or ""
        self.health_factors = dict(health_factors or {})
        self.speed = speed
        self.auto_pause = bool(auto_pause)
        self.fullscreen = bool(
            self.settings.get("fullscreen", False)
            if fullscreen is None
            else fullscreen
        )
        self._create_window()
        self.clock = pygame.time.Clock()
        self.fonts = ge.FontSet()
        self.fonts.setup(ge._probe_font())
        self.cyrillic_ok = self.fonts.cyrillic_ok
        ge.LOG.info(
            "ui.App: шрифты=%s кириллица=%s"
            % (
                "bitmap" if self.fonts.is_bitmap else "pygame.font",
                self.cyrillic_ok,
            )
        )
        self.running = True
        self.manager = SceneManager(self)
        self._register()
        self.manager.go("menu")

    def _create_window(self):
        w, h = ge.compute_window_size()
        flags = pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE
        self.screen = pygame.display.set_mode((w, h), flags)
        pygame.display.set_caption("Ozvering-Project - IPO Arena")
        ge.SCREEN_W, ge.SCREEN_H = w, h
        ge.LOG.info(
            "ui.App: окно %sx%s (fullscreen=%s)" % (w, h, self.fullscreen)
        )

    @property
    def size(self):
        return self.screen.get_size()

    def _register(self):
        m = self.manager
        m.register("menu", scene_pkg.MainMenuScene)
        m.register("settings", scene_pkg.SettingsScene)
        m.register("saves", scene_pkg.SavesScene)
        m.register("narrative", scene_pkg.NarrativeScene)
        m.register("game", scene_pkg.GameScene)
        m.register("battlefield", scene_pkg.BattlefieldScene)
        m.register("interaction", scene_pkg.InteractionScene)
        m.register("pause", scene_pkg.PauseScene)
        m.register("about", scene_pkg.AboutScene)

    def t(self, ru, en):
        return (
            ru
            if (self.cyrillic_ok and self.settings.get("language") == "ru")
            else en
        )

    def go(self, name, **kwargs):
        return self.manager.go(name, **kwargs)

    def push(self, name, **kwargs):
        return self.manager.push(name, **kwargs)

    def pop(self, **kwargs):
        return self.manager.pop(**kwargs)

    def back(self, **kwargs):
        return self.manager.back(**kwargs)

    def refresh(self):
        cur = self.manager.current
        if cur is not None:
            cur.on_enter()
            cur.layout(*self.size)

    def quit(self):
        self.running = False

    def new_seed(self):
        value = int(self.settings.get("last_seed", 0)) + 1
        self.save.set_setting("last_seed", value)
        return value

    def set_fullscreen(self, value):
        value = bool(value)
        self.settings["fullscreen"] = value
        self.save.save_settings()
        if value == self.fullscreen:
            return
        self.fullscreen = value
        self._create_window()
        self.manager.resize(*self.size)

    def _global_event(self, e):
        if e.type == pygame.QUIT:
            self.quit()
            return True
        if e.type == pygame.KEYDOWN and e.key == pygame.K_F11:
            self.set_fullscreen(not self.fullscreen)
            return True
        if e.type == pygame.VIDEORESIZE and not self.fullscreen:
            self.screen = pygame.display.set_mode(
                (int(e.w), int(e.h)), pygame.RESIZABLE
            )
            ge.SCREEN_W, ge.SCREEN_H = self.size
            self.manager.resize(*self.size)
            return True
        return False

    def run(self):
        ge.LOG.info("ui.App: главный цикл запущен (fps=%s)" % FPS)
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for e in pygame.event.get():
                if self._global_event(e):
                    continue
                try:
                    self.manager.handle_event(e)
                except Exception as exc:
                    ge.LOG.exc("scene.handle_event", exc, key="ui-events")
            try:
                self.manager.update(dt)
            except Exception as exc:
                ge.LOG.exc("scene.update", exc, key="ui-update")
            try:
                self.manager.draw(self.screen)
            except Exception as exc:
                ge.LOG.exc("scene.draw", exc, key="ui-draw")
            pygame.display.flip()
        ge.quit_pygame()
        ge.LOG.info("ui.App: завершение, rc=0")
        return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fullscreen = ("--fullscreen" in argv) or ("-f" in argv)
    start_scene = None
    if "--scene" in argv:
        try:
            start_scene = argv[argv.index("--scene") + 1]
        except IndexError:
            start_scene = None
    checkpoint = ""
    if "--checkpoint" in argv:
        try:
            checkpoint = argv[argv.index("--checkpoint") + 1]
        except IndexError:
            checkpoint = ""
    health_factors = {}
    if "--health-factors" in argv:
        try:
            health_factors = ge.parse_health_factors(
                argv[argv.index("--health-factors") + 1]
            )
        except IndexError:
            health_factors = {}
    speed = None
    if "--speed" in argv:
        try:
            speed = ge.normalize_speed(
                argv[argv.index("--speed") + 1]
            )
        except (IndexError, ValueError):
            speed = None
    auto_pause = "--no-auto-pause" not in argv
    app = App(
        fullscreen=fullscreen,
        checkpoint=checkpoint,
        health_factors=health_factors,
        speed=speed,
        auto_pause=auto_pause,
    )
    if start_scene:
        app.go(start_scene)
    return app.run()
