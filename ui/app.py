"""Приложение сценного слоя: окно, шрифты, главный цикл и навигация.

Владеет окном PyGame и шрифтами (переиспользует ``game_engine.FontSet``,
``compute_window_size``, ``_probe_font`` и логгер), а также менеджером сцен и
системой сохранений. Игровое поле (``GameScene``) получает от него surface и
шрифты — так ``game_engine.py`` остаётся переиспользуемым слоем без правок
модели.

Запуск: ``python -m ui`` (флаги ``--fullscreen`` / ``-f``, ``--scene NAME``).
"""

import sys

import pygame

import game_engine as ge

from . import scenes as scene_pkg
from .save import SaveManager
from .scene import SceneManager

FPS = getattr(ge, "FPS", 60)


class App:
    """Окно + менеджер сцен + настройки/сохранения."""

    def __init__(self, fullscreen=None, seed=0):
        ge.LOG.info("ui.App: инициализация сценного слоя")
        pygame.init()
        self.save = SaveManager(log=ge.LOG)
        self.settings = self.save.settings
        self.seed = seed
        self.fullscreen = bool(
            self.settings.get("fullscreen", False) if fullscreen is None
            else fullscreen)
        self._create_window()
        self.clock = pygame.time.Clock()
        self.fonts = ge.FontSet()
        self.fonts.setup(ge._probe_font())
        self.cyrillic_ok = self.fonts.cyrillic_ok
        ge.LOG.info("ui.App: шрифты=%s кириллица=%s"
                    % ("bitmap" if self.fonts.is_bitmap else "pygame.font",
                       self.cyrillic_ok))
        self.running = True
        self.manager = SceneManager(self)
        self._register()
        self.manager.go("menu")

    # --- окно ---
    def _create_window(self):
        w, h = ge.compute_window_size()
        flags = pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE
        self.screen = pygame.display.set_mode((w, h), flags)
        pygame.display.set_caption("Ozvering-Project - IPO Arena")
        ge.SCREEN_W, ge.SCREEN_H = w, h
        ge.LOG.info("ui.App: окно %sx%s (fullscreen=%s)"
                    % (w, h, self.fullscreen))

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
        m.register("pause", scene_pkg.PauseScene)
        m.register("about", scene_pkg.AboutScene)

    # --- язык / навигация ---
    def t(self, ru, en):
        """Двуязычная строка: русский при доступной кириллице и языке ru."""
        return ru if (self.cyrillic_ok
                      and self.settings.get("language") == "ru") else en

    def go(self, name, **kwargs):
        return self.manager.go(name, **kwargs)

    def push(self, name, **kwargs):
        return self.manager.push(name, **kwargs)

    def pop(self, **kwargs):
        return self.manager.pop(**kwargs)

    def back(self, **kwargs):
        return self.manager.back(**kwargs)

    def refresh(self):
        """Пересобрать текущую сцену (смена языка и т.п.)."""
        cur = self.manager.current
        if cur is not None:
            cur.on_enter()
            cur.layout(*self.size)

    def quit(self):
        self.running = False

    def new_seed(self):
        """Следующий seed для новой партии (счётчик в настройках)."""
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

    # --- события/цикл ---
    def _global_event(self, e):
        if e.type == pygame.QUIT:
            self.quit()
            return True
        if e.type == pygame.KEYDOWN and e.key == pygame.K_F11:
            self.set_fullscreen(not self.fullscreen)
            return True
        if e.type == pygame.VIDEORESIZE and not self.fullscreen:
            self.screen = pygame.display.set_mode(
                (int(e.w), int(e.h)), pygame.RESIZABLE)
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
        pygame.quit()
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
    app = App(fullscreen=fullscreen)
    if start_scene:
        app.go(start_scene)
    return app.run()
