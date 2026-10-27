from __future__ import annotations

import json
from pathlib import Path

from .errors import CampaignError
from .preset import CampaignPreset


class CampaignStorageError(CampaignError):
    pass


def repository_root():
    return Path(__file__).resolve().parents[1]


def default_presets_dir(root=None):
    if root is not None:
        return Path(root)
    return repository_root() / "campaigns"


def _resolve(path_or_id, directory=None):
    directory = default_presets_dir(directory)
    value = Path(str(path_or_id))
    if value.is_file():
        return value
    if value.suffix != ".json":
        value = value.with_suffix(".json")
    candidate = value if value.is_absolute() else directory / value
    return candidate


def save_preset(preset, path=None, directory=None):
    if not isinstance(preset, CampaignPreset):
        raise CampaignStorageError("save_preset ожидает CampaignPreset")
    directory = default_presets_dir(directory)
    if path is None:
        path = directory / ("%s.json" % preset.preset_id)
    try:
        return preset.save(path)
    except Exception as exc:
        raise CampaignStorageError("не удалось сохранить пресет: %s" % exc)


def load_preset(path_or_id, directory=None):
    path = _resolve(path_or_id, directory)
    if not path.exists():
        raise CampaignStorageError("пресет не найден: %s" % path)
    try:
        return CampaignPreset.load(path)
    except Exception as exc:
        raise CampaignStorageError("не удалось прочитать пресет: %s" % exc)


def list_presets(directory=None):
    directory = default_presets_dir(directory)
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "preset_id" not in data:
            continue
        out.append(
            {
                "path": str(path),
                "preset_id": data.get("preset_id"),
                "title": data.get("title"),
                "seed": data.get("seed"),
                "role_id": data.get("role_id")
                or (data.get("role") or {}).get("id"),
                "player_faction_id": data.get("player_faction_id"),
            }
        )
    out.sort(key=lambda item: str(item.get("preset_id") or ""), reverse=True)
    return out


def find_preset(preset_id, directory=None):
    return _resolve(preset_id, directory)


__all__ = [
    "CampaignStorageError",
    "repository_root",
    "default_presets_dir",
    "save_preset",
    "load_preset",
    "list_presets",
    "find_preset",
]
