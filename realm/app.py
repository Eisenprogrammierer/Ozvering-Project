"""Приложение игры «Престол»: окно, сцены, сохранения, главный цикл.

Точка входа — ``python3 main.py --realm`` или ``python3 -m realm``. Игра
использует общий сценный каркас ``ui.scene``/``ui.theme``/``ui.widgets``, но
собственные контент, модель и экраны (``realm/``). Канон ``simulation.py`` не
затрагивается.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pygame

import game_engine as ge
from ui import scene as scene_base
from ui.save import SaveManager

from .assets import RealmAssets
from .content import ContentPack

FPS = getattr(ge, "FPS", 60)
SAVE_DIR = Path(__file__).resolve().parents[1] / "saves" / "realm"


class App:
    """Окно + менеджер сцен + контент и партия «Престола»."""

    def __init__(self, fullscreen=None, seed=None):
        ge.init_pygame_minimal()
        self.save = SaveManager(directory=SAVE_DIR, log=ge.LOG)
        self.settings = self.save.settings
        self.fullscreen = bool(
            self.settings.get("fullscreen", False)
            if fullscreen is None else fullscreen
        )
        self._create_window()
        self.clock = pygame.time.Clock()
        self.fonts = ge.FontSet()
        self.fonts.setup(ge._probe_font())
        self.cyrillic_ok = self.fonts.cyrillic_ok
        self.content = ContentPack()
        self.assets = RealmAssets(self.content)
        self.game = None
        self.forced_seed = seed
        self.running = True
        self.manager = scene_base.SceneManager(self)
        self._register()
        self.manager.go("menu")
        ge.LOG.info(
            "realm.App: игра «Престол» запущена, кириллица=%s"
            % self.cyrillic_ok
        )

    # --- окно ------------------------------------------------------------
    def _create_window(self):
        w, h = ge.compute_window_size()
        flags = pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE
        self.screen = pygame.display.set_mode((w, h), flags)
        pygame.display.set_caption("ПРЕСТОЛ — номинальный лидер фракции")
        ge.SCREEN_W, ge.SCREEN_H = w, h
        ge.LOG.info("realm.App: окно %sx%s (fullscreen=%s)"
                    % (w, h, self.fullscreen))

    @property
    def size(self):
        return self.screen.get_size()

    def _register(self):
        from .scenes.about import AboutScene
        from .scenes.chronicle import ChronicleScene
        from .scenes.council import CouncilScene
        from .scenes.ending import EndingScene
        from .scenes.intro import IntroScene
        from .scenes.mandate import MandateScene
        from .scenes.menu import MainMenuScene
        from .scenes.pause import PauseScene
        from .scenes.saves import SavesScene
        from .scenes.settings import SettingsScene

        m = self.manager
        m.register("menu", MainMenuScene)
        m.register("mandate", MandateScene)
        m.register("intro", IntroScene)
        m.register("council", CouncilScene)
        m.register("chronicle", ChronicleScene)
        m.register("ending", EndingScene)
        m.register("saves", SavesScene)
        m.register("settings", SettingsScene)
        m.register("pause", PauseScene)
        m.register("about", AboutScene)

    # --- навигация -------------------------------------------------------
    def go(self, name, **kwargs):
        return self.manager.go(name, **kwargs)

    def push(self, name, **kwargs):
        return self.manager.push(name, **kwargs)

    def pop(self, **kwargs):
        return self.manager.pop(**kwargs)

    def back(self, fallback="menu", **kwargs):
        return self.manager.back(fallback, **kwargs)

    def refresh(self):
        cur = self.manager.current
        if cur is not None:
            cur.on_enter()
            cur.layout(*self.size)

    def quit(self):
        self.running = False

    def set_fullscreen(self, value):
        value = bool(value)
        self.settings["fullscreen"] = value
        self.save.save_settings()
        if value == self.fullscreen:
            return
        self.fullscreen = value
        self._create_window()
        self.manager.resize(*self.size)

    # --- партия ----------------------------------------------------------
    def _next_seed(self):
        value = int(self.settings.get("last_seed", 0)) + 1
        self.save.set_setting("last_seed", value)
        return value

    def start_new_game(self, mandate_id):
        from .model import CouncilGame

        seed = self.forced_seed
        if seed is None:
            seed = self._next_seed()
        else:
            self.forced_seed = None
        self.game = CouncilGame(self.content, seed=seed,
                                mandate_id=mandate_id)
        self.go("intro")

    def summary(self):
        if self.game is None:
            return {}
        return {
            "week": self.game.week,
            "max_weeks": self.game.max_weeks,
            "mandate": self.game.mandate_title(),
            "status": self.game.status,
            "ending": (self.game.ending or {}).get("title", ""),
            "seed": self.game.seed,
        }

    def save_game(self, slot):
        if self.game is None:
            return None
        payload = {
            "game": self.game.snapshot(),
            "meta": self.summary(),
        }
        return self.save.write(slot, payload)

    def autosave(self):
        if not self.settings.get("autosave", True):
            return None
        return self.save.autosave({
            "game": self.game.snapshot() if self.game else None,
            "meta": self.summary(),
        })

    def load_game(self, slot):
        from .model import CouncilGame

        data = self.save.read(slot)
        if not data:
            return False
        snapshot = data.get("game") or data.get("state")
        if not snapshot:
            return False
        try:
            self.game = CouncilGame.from_snapshot(self.content, snapshot)
        except Exception as exc:  # битое/устаревшее сохранение не роняет игру
            ge.LOG.warn("realm.App: не удалось загрузить %s (%s)"
                        % (slot, exc))
            return False
        self.go("council")
        return True

    def continue_game(self):
        data = self.save.read("autosave")
        if data:
            return self.load_game("autosave")
        saves = [item for item in self.save.list_slots()
                 if not item["empty"] and item["slot"] != "autosave"]
        if saves:
            return self.load_game(saves[0]["slot"])
        return False

    def open_saves(self, mode="load"):
        self.push("saves", mode=mode)

    def open_settings(self):
        self.push("settings")

    # --- события/цикл ----------------------------------------------------
    def _global_event(self, event):
        if event.type == pygame.QUIT:
            self.quit()
            return True
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            self.set_fullscreen(not self.fullscreen)
            return True
        if event.type == pygame.VIDEORESIZE and not self.fullscreen:
            self.screen = pygame.display.set_mode(
                (int(event.w), int(event.h)), pygame.RESIZABLE
            )
            ge.SCREEN_W, ge.SCREEN_H = self.size
            self.manager.resize(*self.size)
            return True
        return False

    def run(self):
        ge.LOG.info("realm.App: главный цикл запущен (fps=%s)" % FPS)
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if self._global_event(event):
                    continue
                try:
                    self.manager.handle_event(event)
                except Exception as exc:
                    ge.LOG.exc("realm.scene.handle_event", exc, key="realm-events")
            try:
                self.manager.update(dt)
            except Exception as exc:
                ge.LOG.exc("realm.scene.update", exc, key="realm-update")
            try:
                self.manager.draw(self.screen)
            except Exception as exc:
                ge.LOG.exc("realm.scene.draw", exc, key="realm-draw")
            pygame.display.flip()
        ge.quit_pygame()
        ge.LOG.info("realm.App: завершение, rc=0")
        return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fullscreen = ("--fullscreen" in argv) or ("-f" in argv)
    seed = None
    if "--seed" in argv:
        try:
            seed = int(argv[argv.index("--seed") + 1])
        except (IndexError, ValueError):
            seed = None
    app = App(fullscreen=fullscreen, seed=seed)
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
