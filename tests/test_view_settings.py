"""W6: настройки клиента переживают перезапуск, меню ведёт в «Как играть».

Настройки относятся к клиенту, а не к миру, поэтому хранятся отдельным
файлом и не должны ломать запуск при повреждении. Экран «Как играть»
обязан существовать в меню, иначе новая сессия снова требует читать
документацию.
"""

from __future__ import annotations

import json

import pytest

from view.app_menu import AppMenuMixin
from view.screens.how_to_play import LINES
from view.support.settings_store import (
    DEFAULT_SETTINGS,
    apply_music,
    load_settings,
    normalize_settings,
    save_settings,
)


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(
        {
            "sound": False,
            "music_volume": 0.2,
            "fullscreen": True,
            "animations": False,
            "text_speed": 1.5,
        },
        path=path,
    )
    restored = load_settings(path)
    assert restored["sound"] is False
    assert restored["music_volume"] == pytest.approx(0.2)
    assert restored["fullscreen"] is True
    assert restored["animations"] is False
    assert restored["text_speed"] == pytest.approx(1.5)


def test_missing_or_broken_settings_fall_back_to_defaults(tmp_path):
    missing = load_settings(tmp_path / "missing.json")
    assert missing == DEFAULT_SETTINGS

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_settings(broken) == DEFAULT_SETTINGS


def test_normalize_clamps_and_ignores_unknown_keys():
    result = normalize_settings(
        {
            "music_volume": 9.0,
            "text_speed": 0.01,
            "fullscreen": "yes",
            "unknown": 1,
        }
    )
    assert result["music_volume"] == pytest.approx(1.0)
    assert result["text_speed"] == pytest.approx(0.25)
    assert result["fullscreen"] is True
    assert "unknown" not in result
    assert result["version"] == DEFAULT_SETTINGS["version"]


def test_saved_file_is_valid_json(tmp_path):
    path = tmp_path / "settings.json"
    save_settings({"sound": True}, path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == DEFAULT_SETTINGS["version"]
    assert set(DEFAULT_SETTINGS) <= set(data)


def test_apply_music_without_mixer_does_not_raise():
    assert apply_music({"sound": True, "music_volume": 0.5}, None) is None


def test_menu_exposes_how_to_play_and_its_text_covers_controls():
    assert hasattr(AppMenuMixin, "open_how_to_play")
    text = " ".join(line for _head, line in LINES)
    for hint in ("F11", "Esc", "F5", "Недоступное действие"):
        assert hint in text
