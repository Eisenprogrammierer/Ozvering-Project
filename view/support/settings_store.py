"""Настройки клиента `view/`: хранение и применение.

Настройки живут отдельно от сейвов кампании, потому что относятся к
клиенту, а не к миру. Файл читается при старте и перезаписывается при
каждом изменении, поэтому звук, полный экран и анимации переживают
перезапуск. Некорректный файл не ломает запуск: значения проверяются по
схеме и заменяются умолчаниями.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .log_journal import get_logger

logger = get_logger("view.settings")

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "saves" / "settings.json"
SCHEMA_VERSION = 1

DEFAULT_SETTINGS = {
    "version": SCHEMA_VERSION,
    "sound": True,
    "music_volume": 0.6,
    "fullscreen": False,
    "animations": True,
    "text_speed": 1.0,
}


def _clamp(value, low=0.0, high=1.0):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def normalize_settings(data):
    """Привести прочитанные настройки к текущей схеме."""
    data = data if isinstance(data, dict) else {}
    result = dict(DEFAULT_SETTINGS)
    if "sound" in data:
        result["sound"] = bool(data.get("sound"))
    if "fullscreen" in data:
        result["fullscreen"] = bool(data.get("fullscreen"))
    if "animations" in data:
        result["animations"] = bool(data.get("animations"))
    if "music_volume" in data:
        result["music_volume"] = _clamp(data.get("music_volume"), 0.0, 1.0)
    if "text_speed" in data:
        result["text_speed"] = max(
            0.25, min(4.0, _clamp(data.get("text_speed"), 0.25, 4.0))
        )
    result["version"] = SCHEMA_VERSION
    return result


def load_settings(path=None):
    path = Path(path) if path else SETTINGS_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(DEFAULT_SETTINGS)
    except (OSError, ValueError) as exc:
        logger.warning("Настройки не прочитаны (%s): %s", path, exc)
        return dict(DEFAULT_SETTINGS)
    return normalize_settings(raw)


def save_settings(settings, path=None):
    path = Path(path) if path else SETTINGS_PATH
    data = normalize_settings(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        logger.warning("Настройки не сохранены (%s): %s", path, exc)
    return data


def apply_music(settings, music):
    """Включить/выключить музыку, не падая без pygame.mixer."""
    if music is None:
        return
    enabled = bool(settings.get("sound", True))
    music.enabled = enabled
    volume = _clamp(settings.get("music_volume", 0.6), 0.0, 1.0)
    try:
        import pygame

        if pygame.mixer.get_init():
            pygame.mixer.music.set_volume(volume)
    except Exception as exc:  # pragma: no cover - защитный путь аудио
        logger.debug("Громкость музыки не применена: %s", exc)


__all__ = [
    "DEFAULT_SETTINGS",
    "SETTINGS_PATH",
    "apply_music",
    "load_settings",
    "normalize_settings",
    "save_settings",
]
