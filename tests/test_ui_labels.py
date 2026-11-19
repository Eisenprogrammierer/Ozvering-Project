"""Подписи кнопок на экранах выбора.

Регрессия: экраны писали ``button.label``, хотя ``Button`` рисует
``button.text``. Кнопки оставались пустыми при живом списке ролей,
архетипов и персонажей. Тесты проверяют именно то, что увидит игрок, —
текст кнопки после отрисовки.
"""

from __future__ import annotations

import os

import pytest

pygame = pytest.importorskip("pygame")

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


@pytest.fixture()
def app():
    from view.app import App

    instance = App(checkpoint="")
    yield instance
    instance.running = False
    pygame.quit()


def _surface():
    return pygame.Surface((1280, 720))


def test_role_select_buttons_show_role_labels(app):
    from view.screens.role_select import RoleSelectScreen

    screen = RoleSelectScreen(app)
    assert screen.roles, "для теста нужна хотя бы одна роль"
    screen.draw(_surface())
    visible = screen._visible_roles()
    assert visible

    for index, role in enumerate(visible):
        button = screen.buttons[index]
        assert role.label.strip()
        assert button.text == role.label
        assert button.text.strip()


def test_role_select_filter_button_updates_text(app):
    from view.screens.role_select import RoleSelectScreen

    screen = RoleSelectScreen(app)
    before = screen.filter_button.text
    screen.next_filter()
    assert screen.filter_button.text != before
    assert screen.filter_button.text.startswith("Фильтр: ")


def test_archetype_select_buttons_show_labels(app):
    from view.screens.archetype_select import ArchetypeSelectScreen

    screen = ArchetypeSelectScreen(app)
    assert screen.archetypes, "для теста нужен хотя бы один архетип"
    screen.draw(_surface())
    visible = screen._visible()
    assert visible

    for index, item in enumerate(visible):
        button = screen.buttons[index]
        assert item.label.strip()
        assert button.text == item.label
        assert button.text.strip()


def test_character_select_buttons_show_name_and_post(app):
    from view.screens.character_select import CharacterSelectScreen

    screen = CharacterSelectScreen(app)
    screen.characters = [
        {"id": "char_one", "name": "Анна", "post": "Офицер"},
        {"id": "char_two", "name": "Борис", "post": "Связной"},
    ]
    screen.selected_id = "char_one"
    screen.draw(_surface())

    assert screen.buttons[0].text == "Анна — Офицер"
    assert screen.buttons[1].text == "Борис — Связной"
    assert screen.buttons[2].text == ""
