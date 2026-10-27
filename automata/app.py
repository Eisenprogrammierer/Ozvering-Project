from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pygame

import game_engine as ge
from ui import scene as scene_base

from .model import Automaton
from .storage import AutomataStore, StoreError

FPS = getattr(ge, "FPS", 60)
SAVE_DIR = Path(__file__).resolve().parents[1] / "saves" / "automata"
SETTINGS_PATH = SAVE_DIR / "settings.json"


class AutomataApp:

    def __init__(self, fullscreen=None, store=None):
        ge.init_pygame_minimal()
        self.settings = self._load_settings()
        self.fullscreen = bool(
            self.settings.get("fullscreen", False)
            if fullscreen is None
            else fullscreen
        )
        self.store = store or AutomataStore()
        self._create_window()
        self.clock = pygame.time.Clock()
        self.fonts = ge.FontSet()
        self.fonts.setup(ge._probe_font())
        self.cyrillic_ok = self.fonts.cyrillic_ok
        self.running = True
        self.manager = scene_base.SceneManager(self)
        self._register()
        self.manager.go("library")
        ge.LOG.info(
            "automata.App: редактор запущен, кириллица=%s" % self.cyrillic_ok
        )

    def _create_window(self):
        w, h = ge.compute_window_size()
        flags = pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE
        self.screen = pygame.display.set_mode((w, h), flags)
        pygame.display.set_caption("Редактор автоматов — Ozvering-Project")
        ge.SCREEN_W, ge.SCREEN_H = w, h
        ge.LOG.info(
            "automata.App: окно %sx%s (fullscreen=%s)"
            % (w, h, self.fullscreen)
        )

    @property
    def size(self):
        return self.screen.get_size()

    def set_title(self, name=None):
        if name:
            caption = "%s — редактор автоматов" % name
        else:
            caption = "Редактор автоматов — Ozvering-Project"
        pygame.display.set_caption(caption)

    def _load_settings(self):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_settings(self):
        try:
            SAVE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = SETTINGS_PATH.with_name(SETTINGS_PATH.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.settings, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp, SETTINGS_PATH)
        except OSError as exc:
            ge.LOG.warn(
                "automata.App: не удалось сохранить настройки: %s" % exc
            )

    def _register(self):
        from .scenes.confirm import ConfirmScene
        from .scenes.editor import EditorScene
        from .scenes.help import HelpScene
        from .scenes.library import LibraryScene

        m = self.manager
        m.register("library", LibraryScene)
        m.register("editor", EditorScene)
        m.register("help", HelpScene)
        m.register("confirm", ConfirmScene)

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

    def push_help(self):
        self.push("help")

    def new_automaton(self):
        automaton = Automaton()
        automaton.add_state(name="Состояние 1", x=220, y=180, initial=True)
        self.go("editor", automaton=automaton, slug=None, saved_data=None)
        self._focus_initial()

    def open_automaton(self, slug):
        try:
            automaton = self.store.load(slug)
        except StoreError as exc:
            ge.LOG.warn("automata.App: %s" % exc)
            self.go("library", message=str(exc))
            return False
        self.go(
            "editor",
            automaton=automaton,
            slug=slug,
            saved_data=automaton.to_dict(),
        )
        self._focus_initial()
        return True

    def _focus_initial(self):
        scene = self.manager.current
        if scene is None or getattr(scene, "name", None) != "editor":
            return
        states = scene.automaton.states
        if not states:
            return
        target = (
            scene.automaton.initial_states[0]
            if scene.automaton.initial_states
            else states[0]
        )
        scene.canvas.select("state", target.id)

    def set_fullscreen(self, value):
        value = bool(value)
        self.settings["fullscreen"] = value
        self._save_settings()
        if value == self.fullscreen:
            return
        self.fullscreen = value
        self._create_window()
        self.manager.resize(*self.size)

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
        ge.LOG.info("automata.App: главный цикл запущен (fps=%s)" % FPS)
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if self._global_event(event):
                    continue
                try:
                    self.manager.handle_event(event)
                except Exception as exc:
                    ge.LOG.exc(
                        "automata.scene.handle_event",
                        exc,
                        key="automata-events",
                    )
            try:
                self.manager.update(dt)
            except Exception as exc:
                ge.LOG.exc("automata.scene.update", exc, key="automata-update")
            try:
                self.manager.draw(self.screen)
            except Exception as exc:
                ge.LOG.exc("automata.scene.draw", exc, key="automata-draw")
            pygame.display.flip()
        ge.quit_pygame()
        ge.LOG.info("automata.App: завершение, rc=0")
        return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    fullscreen = ("--fullscreen" in argv) or ("-f" in argv)
    open_slug = None
    if "--open" in argv:
        try:
            open_slug = argv[argv.index("--open") + 1]
        except IndexError:
            open_slug = None
    app = AutomataApp(fullscreen=fullscreen)
    if open_slug:
        app.open_automaton(open_slug)
    elif "--new" in argv:
        app.new_automaton()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
