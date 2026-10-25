"""Тесты сценного слоя (``ui/``).

Разделены на две группы:

  * **без графики** — система сохранений/настроек (``ui.save``) и контент
    (``ui.content``): чистый Python, работают и в CI без pygame;
  * **с графикой** — навигация между сценами и отрисовка кадров через
    ``ui.app.App`` под headless-драйвером SDL (``importorskip("pygame")``).

Проверяется, что сценный слой не трогает модель: ``simulation.py`` и канон
``run_batch(10)`` остаются неизменными (см. ``test_canon.py``).
"""

import os
import sys

import pytest

from ui import content
from ui.save import (AUTOSAVE_SLOT, DEFAULT_SETTINGS, MANUAL_SLOTS,
                     SaveManager)


# --------------------------------------------------------------------------
# 1. Система сохранений/настроек (без pygame)
# --------------------------------------------------------------------------

def test_settings_defaults_and_roundtrip(tmp_path):
    sm = SaveManager(directory=tmp_path)
    assert sm.settings["language"] in ("ru", "en")
    assert set(DEFAULT_SETTINGS) <= set(sm.settings)

    sm.set_setting("volume_master", 0.42)
    sm.set_setting("autosave", False)

    sm2 = SaveManager(directory=tmp_path)
    assert sm2.settings["volume_master"] == 0.42
    assert sm2.settings["autosave"] is False


def test_slots_write_read_delete(tmp_path):
    sm = SaveManager(directory=tmp_path)
    assert sm.read("slot_1") is None
    assert not sm.has_any_save()

    payload = sm.write("slot_1", {"seed": 5, "tick": 33, "winner": None,
                                  "finished": False})
    assert payload["version"] == sm.settings["version"]
    assert payload["created"] and payload["updated"]

    stored = sm.read("slot_1")
    assert stored["seed"] == 5 and stored["tick"] == 33
    assert sm.has_any_save()

    assert sm.delete("slot_1") is True
    assert sm.read("slot_1") is None
    assert sm.delete("slot_1") is False


def test_autosave_slot_and_listing(tmp_path):
    sm = SaveManager(directory=tmp_path)
    assert not sm.has_autosave()
    sm.autosave({"seed": 1, "tick": 0})
    assert sm.has_autosave()

    slots = sm.list_slots()
    assert [s["slot"] for s in slots] == [AUTOSAVE_SLOT] + list(MANUAL_SLOTS)
    assert slots[0]["empty"] is False
    assert all(s["empty"] for s in slots[1:])


def test_corrupt_json_is_survived(tmp_path):
    sm = SaveManager(directory=tmp_path)
    (tmp_path / "slot_2.json").write_text("{ not json", encoding="utf-8")
    assert sm.read("slot_2") is None                  # не падает
    assert sm.list_slots()[2]["empty"] is True


def test_content_is_bilingual():
    assert content.TITLE
    for page in content.INTRO_PAGES:
        assert set(("image", "title", "body")) <= set(page)
        assert len(page["title"]) == 2 and len(page["body"]) == 2
        assert all(isinstance(x, str) and x for x in page["title"])
        assert all(isinstance(x, str) and x for x in page["body"])
    for pair in content.ABOUT_LINES + content.HELP_LINES:
        assert len(pair) == 2 and all(pair)


# --------------------------------------------------------------------------
# 2. Навигация и отрисовка сцен (pygame, headless)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app(tmp_path_factory):
    pytest.importorskip("pygame")
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    # Свежий интерпретатор чист, но на всякий случай сбрасываем кеш модулей ui.
    for mod in [m for m in list(sys.modules) if m.startswith("ui")]:
        del sys.modules[mod]
    from ui.app import App
    instance = App()
    # Изолируем запись от репозитория: слоты/настройки — во временный каталог.
    work = tmp_path_factory.mktemp("ui_saves")
    instance.save.dir = work
    instance.save.settings_path = work / "settings.json"
    yield instance
    import game_engine as ge
    ge.quit_pygame()


def _frame(app):
    app.manager.update(1.0 / 60.0)
    app.manager.draw(app.screen)


def test_starts_at_main_menu(app):
    assert app.manager.current.name == "menu"
    _frame(app)


def test_audio_never_initialized(app):
    """Аудио-подсистема не инициализируется (иначе mixer может зависнуть)."""
    import pygame
    assert pygame.mixer.get_init() is None


@pytest.mark.parametrize("name", ["menu", "settings", "saves", "about",
                                  "narrative", "game", "battlefield", "pause"])
def test_every_scene_draws(app, name):
    app.go(name)
    assert app.manager.current.name == name
    _frame(app)


def test_battlefield_layout_fits_window(app):
    app.go("battlefield", new=True)
    scene = app.manager.current
    for size in ((640, 480), (1024, 640), (1920, 1080)):
        scene.on_resize(*size)
        w, h = size
        for wdg in scene.widgets:
            assert wdg.rect.left >= 0 and wdg.rect.top >= 0, (size, wdg.rect)
            assert wdg.rect.right <= w and wdg.rect.bottom <= h, \
                (size, wdg.rect)
        _frame(app)


@pytest.mark.parametrize("name", ["menu", "settings", "saves", "about",
                                  "narrative"])
@pytest.mark.parametrize("size", [(640, 480), (1024, 640), (1920, 1080)])
def test_layout_fits_window(app, name, size):
    app.go(name)
    scene = app.manager.current
    scene.on_resize(*size)
    w, h = size
    for wdg in scene.widgets:
        assert wdg.rect.left >= 0 and wdg.rect.top >= 0, (name, size, wdg.rect)
        assert wdg.rect.right <= w and wdg.rect.bottom <= h, \
            (name, size, wdg.rect)


def test_narrative_to_game_and_autosave(app, tmp_path):
    app.save.dir = tmp_path
    app.save.settings["autosave"] = True
    app.go("narrative", pages=content.INTRO_PAGES, next_scene="game",
           next_kwargs={"new": True})
    nar = app.manager.current
    assert nar.index == 0
    nar._skip()
    game = app.manager.current
    assert game.name == "game" and game.view is not None
    game.view.paused = False
    for _ in range(20):
        _frame(app)
    assert game.view.match.step > 0
    assert (tmp_path / "autosave.json").exists()


def test_pause_overlay_keeps_match(app, tmp_path):
    app.save.dir = tmp_path
    app.go("game", new=True)
    game = app.manager.current
    game.view.paused = False
    for _ in range(5):
        _frame(app)
    step = game.view.match.step
    app.push("pause")
    assert app.manager.depth == 2
    _frame(app)
    app.pop()
    assert app.manager.current is game           # тот же экземпляр — партия цела
    assert app.manager.current.view.match.step >= step


def test_save_slot_from_pause_and_load(app, tmp_path):
    app.save.dir = tmp_path
    app.go("game", new=True)
    app.manager.find("game").view.paused = False
    _frame(app)
    app.push("pause")
    app.push("saves", mode="save")
    app.manager.current._save("slot_1")
    saved = app.save.read("slot_1")
    assert saved is not None and "seed" in saved

    app.go("saves", mode="load")
    app.manager.current._load("slot_1")
    assert app.manager.current.name == "game"
    assert app.manager.current.view.match.seed == saved["seed"]


def test_button_click_navigates(app, tmp_path):
    import pygame
    app.save.dir = tmp_path
    app.go("menu")
    menu = app.manager.current
    about_btn = next(b for b in menu.widgets if b.label == app.t("Об игре",
                                                                "About"))
    pos = about_btn.rect.center
    app.manager.handle_event(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
    app.manager.handle_event(pygame.event.Event(
        pygame.MOUSEBUTTONUP, button=1, pos=pos))
    assert app.manager.current.name == "about"


def test_arena_quit_button_exits(app):
    """В HUD арены есть кнопка QUIT; клик по ней завершает цикл (rc=False)."""
    import pygame
    import game_engine as ge
    view = ge.GameApp(screen=app.screen, fonts=app.fonts)
    names = [n for n, _label, _r in view.buttons]
    assert "QUIT" in names
    rect = next(r for n, _label, r in view.buttons if n == "QUIT")
    pos = rect.center
    running = view.handle_events([pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=pos)])
    assert running is False


def test_entry_point_dispatches_to_ui(monkeypatch):
    pytest.importorskip("pygame")
    import main as entry
    import ui.app as ui_app
    monkeypatch.setattr(sys, "argv", list(sys.argv))     # восстановить после
    seen = {}
    monkeypatch.setattr(ui_app, "main",
                        lambda argv=None: seen.__setitem__("argv", argv) or 0)
    rc = entry.main(["--scene", "game"])
    assert rc == 0 and seen["argv"] == ["--scene", "game"]


def test_entry_point_dispatches_to_arena(monkeypatch):
    pytest.importorskip("pygame")
    import main as entry
    import game_engine as ge
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    monkeypatch.setattr(ge, "main", lambda: 42)
    assert entry.main(["--arena"]) == 42


def test_save_layer_is_pygame_free():
    """``ui.save`` (и контент) импортируются без pygame — доступны в CI."""
    import subprocess
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    code = ("import sys, ui.save, ui.content; "
            "sys.exit(1 if 'pygame' in sys.modules else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=root,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_entry_point_importable():
    """Единая точка запуска ``main.py`` импортируется без графики."""
    import main as entry
    assert callable(entry.main)
