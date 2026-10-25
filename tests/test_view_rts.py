"""Дымовые тесты RTS-экрана (требуют pygame)."""

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
pygame = pytest.importorskip("pygame")


def _app():
    from view.app import App
    return App()


def test_rts_screen_draws_and_selects_units():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    app.manager.replace_all(screen)
    surface = pygame.Surface((1280, 720))
    screen.draw(surface)
    assert screen.selected
    assert screen._project((0, 0)) != screen._project((1, 0))
    cell = screen._cell_from_mouse(screen._project((6, 6)))
    assert cell == (6, 6)


def test_rts_move_order_and_needs_action():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    app.manager.replace_all(screen)
    idx = screen.selected[0]
    start = screen.state.det_at(idx).position
    screen._issue_ground((5, 5))
    app.time_system.advance(1800)
    assert screen.state.det_at(idx).position != start
    result = screen.state.needs.apply(idx, "feed")
    assert result["ok"]
    assert screen.state.supplies["food"] < 120


def test_text_layout_breaks_long_words():
    from view.ui.text_layout import wrap_text

    font = pygame.font.Font(None, 20)
    lines = wrap_text(font, "A" * 80, 50)
    assert len(lines) > 1
    assert all(font.size(line)[0] <= 50 for line in lines)


def test_rts_tick_spawns_battle_particles():
    from view.screens.rts_screen import RTSScreen

    app = _app()
    screen = RTSScreen(app)
    for _ in range(4):
        app.time_system.advance(1800)
        screen._after_tick()
    assert screen._particles
