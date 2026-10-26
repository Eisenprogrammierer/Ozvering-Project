"""Дымовые тесты графического слоя «Престола» (headless pygame)."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    pytest.importorskip("pygame")
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    from realm.app import App

    instance = App(seed=13)
    work = tmp_path_factory.mktemp("realm_saves")
    instance.save.dir = work
    instance.save.settings_path = work / "settings.json"
    yield instance
    import game_engine as ge
    ge.quit_pygame()


def _frame(app):
    app.manager.update(1.0 / 60.0)
    app.manager.draw(app.screen)


def _start(app, mandate="heir"):
    app.start_new_game(mandate)
    assert app.manager.current.name == "intro"
    app.manager.current._finish()
    assert app.manager.current.name == "council"
    return app.game


def test_menu_and_mandate_render(app):
    app.go("menu")
    _frame(app)
    app.go("mandate")
    _frame(app)
    assert len(app.manager.current.cards) == len(app.content.mandates)
    card = app.manager.current.cards[0]
    card.on_click(card.mandate["id"])
    _frame(app)


def test_new_game_goes_through_intro_to_council(app):
    game = _start(app, "council")
    assert game is not None
    assert game.week == 1
    assert game.mandate_id == "council"
    _frame(app)


def test_resolve_and_report_render(app):
    game = _start(app, "heir")
    scene = app.manager.current
    assert scene.option_cards
    option = scene.option_cards[0].option
    scene._select(option["id"])
    _frame(app)
    mode = "decree" if game.can_decree(option) else "force"
    scene._resolve(mode)
    assert app.game.phase == "report"
    _frame(app)
    scene._continue()
    assert app.game.phase == "audience"
    assert app.game.week == 2
    _frame(app)


def test_save_and_load_roundtrip(app):
    game = _start(app, "popular")
    option = game.current_petition["options"][0]
    game.resolve(option["id"],
                 "decree" if game.can_decree(option) else "force")
    game.continue_after_report()
    week = game.week
    assert app.save_game("slot_1")
    app.go("menu")
    _frame(app)
    assert app.load_game("slot_1") is True
    assert app.game.week == week
    _frame(app)


def test_auxiliary_screens_render(app):
    _start(app, "heir")
    for name in ("chronicle", "saves", "settings", "about", "pause"):
        app.go(name, mode="load") if name == "saves" else app.go(name)
        _frame(app)
    game = app.game
    game.status = "lost"
    game.ending = game._loss_ending("legitimacy")
    game.phase = "ended"
    app.go("ending")
    _frame(app)


def test_missing_asset_falls_back_to_placeholder(app):
    import pygame

    surface = pygame.Surface((320, 180))
    app.assets.draw(surface, (0, 0, 320, 180), "not_yet_drawn",
                    app.fonts, caption="ТЕСТ")
    # Плейсхолдер действительно что-то нарисовал.
    assert surface.get_at((10, 10))[:3] != (0, 0, 0)
