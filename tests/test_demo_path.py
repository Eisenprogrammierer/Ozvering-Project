"""Демо-путь: «Быстрая кампания» играбельна без роли и сюжета.

Самый короткий путь к игре из главного меню. Тест держит его живым:
экран открывается, среда даёт легальные действия, ход завершает день,
кадр рисуется без исключения.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _reset_audio():
    yield
    try:
        import pygame
    except ImportError:
        return
    if pygame.mixer.get_init():
        pygame.mixer.quit()


def test_quick_campaign_plays_and_advances_day():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame = pytest.importorskip("pygame")
    from view.app import App

    app = App()
    app.quick_campaign()
    screen = app.manager.current
    assert type(screen).__name__ == "CampaignQuickScreen"
    assert screen.env is not None
    assert screen.env.legal_actions()

    surface = pygame.Surface((1280, 720))
    screen.draw(surface)

    day = screen.env.engine.day
    end_day = next(
        action
        for action in screen.env.legal_actions()
        if action.kind == "END_DAY"
    )
    screen._do(end_day)
    assert screen.env.engine.day == day + 1
    screen.draw(surface)
    pygame.quit()
