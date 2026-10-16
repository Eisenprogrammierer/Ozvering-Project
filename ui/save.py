"""Система сохранений и настроек сценного слоя.

Всё хранится в каталоге ``saves/`` (в корне репозитория, в ``.gitignore``):
  * ``settings.json``           — пользовательские настройки;
  * ``autosave.json``           — автосохранение;
  * ``slot_1..3.json``          — ручные слоты.

Запись атомарная (временный файл + ``os.replace``), кодировка UTF-8. Битый или
отсутствующий JSON не роняет приложение: чтение возвращает ``None`` и пишет
предупреждение в переданный логгер.

Прогресс партии сериализуется как метаданные (seed, такт, победитель). Само
состояние партии не сохраняется: движок детерминирован по seed, поэтому позиция
восстанавливается повторным проигрыванием до сохранённого такта
(``game_engine.GameApp.start_match``).
"""

import json
import os
import time
from pathlib import Path

SCHEMA = 1
ROOT = Path(__file__).resolve().parents[1]
SAVE_DIR = ROOT / "saves"

AUTOSAVE_SLOT = "autosave"
MANUAL_SLOTS = ("slot_1", "slot_2", "slot_3")
ALL_SLOTS = (AUTOSAVE_SLOT,) + MANUAL_SLOTS

DEFAULT_SETTINGS = {
    "version": SCHEMA,
    "language": "ru",          # ru | en
    "volume_master": 0.8,
    "volume_music": 0.6,
    "volume_sfx": 0.8,
    "fullscreen": False,
    "autosave": True,
    "text_speed": 1.0,          # множитель скорости показа нарратива
}


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


class SaveManager:
    """Чтение/запись настроек и слотов сохранения."""

    def __init__(self, directory=None, log=None):
        self.dir = Path(directory) if directory else SAVE_DIR
        self.settings_path = self.dir / "settings.json"
        self._log = log
        self.settings = dict(DEFAULT_SETTINGS)
        stored = self._read(self.settings_path)
        if stored:
            for key, value in stored.items():
                if key in DEFAULT_SETTINGS:
                    self.settings[key] = value
            self.settings["version"] = SCHEMA

    # --- низкоуровневый ввод/вывод --------------------------------------
    def _warn(self, msg):
        if self._log is not None:
            try:
                self._log.warn(msg)
            except Exception:
                pass

    def _ensure_dir(self):
        self.dir.mkdir(parents=True, exist_ok=True)

    def _read(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except Exception as exc:                      # битый JSON и т.п.
            self._warn("SaveManager: не удалось прочитать %s (%s)"
                       % (path, exc))
            return None

    def _write(self, path, data):
        self._ensure_dir()
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return data

    # --- настройки ------------------------------------------------------
    def set_setting(self, key, value, save=True):
        self.settings[key] = value
        if save:
            self.save_settings()

    def save_settings(self):
        self.settings["version"] = SCHEMA
        self._write(self.settings_path, self.settings)

    # --- слоты ----------------------------------------------------------
    def slot_path(self, slot):
        return self.dir / ("%s.json" % slot)

    def read(self, slot):
        return self._read(self.slot_path(slot))

    def write(self, slot, data):
        payload = dict(data)
        payload["version"] = SCHEMA
        payload["updated"] = _now()
        if not payload.get("created"):
            payload["created"] = payload["updated"]
        payload.setdefault("name", slot)
        self._write(self.slot_path(slot), payload)
        return payload

    def delete(self, slot):
        try:
            self.slot_path(slot).unlink()
            return True
        except FileNotFoundError:
            return False
        except Exception as exc:
            self._warn("SaveManager: не удалось удалить %s (%s)" % (slot, exc))
            return False

    def autosave(self, data):
        return self.write(AUTOSAVE_SLOT, data)

    def has_autosave(self):
        return self.slot_path(AUTOSAVE_SLOT).exists()

    def has_any_save(self):
        return any(self.slot_path(s).exists() for s in ALL_SLOTS)

    def list_slots(self):
        """Список слотов: ``[{slot, empty, data}]`` (autosave первым)."""
        out = []
        for slot in ALL_SLOTS:
            data = self.read(slot)
            out.append({"slot": slot, "empty": data is None, "data": data})
        return out
