import json
import os
import time
from pathlib import Path

from .log_journal import get_logger

logger = get_logger("view.save")
ROOT = Path(__file__).resolve().parents[2]
SAVES_DIR = ROOT / "saves" / "campaign"
SAVE_VERSION = 1


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _safe_slot(slot_name):
    name = Path(str(slot_name)).name.strip()
    if not name:
        raise ValueError("пустое имя сохранения")
    if not name.endswith(".json"):
        name += ".json"
    return name


def _ensure_dir():
    SAVES_DIR.mkdir(parents=True, exist_ok=True)


def _path(slot_name):
    return SAVES_DIR / _safe_slot(slot_name)


def _jsonable(value):
    if value is None:
        return None
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, dict):
        return dict(value)
    return value


def save_game(
    state,
    time_system,
    slot_name,
    scenario_path=None,
    storyline_snapshot=None,
    campaign_role=None,
    campaign_preset=None,
):
    _ensure_dir()
    payload = {
        "version": SAVE_VERSION,
        "updated": _now(),
        "scenario_path": scenario_path or "scenarios/mvp.json",
        "campaign": state.to_snapshot(),
        "time_system": (
            time_system.get_save_snapshot() if time_system is not None else {}
        ),
        "storyline": storyline_snapshot,
        "campaign_role": _jsonable(campaign_role),
        "campaign_preset": _jsonable(campaign_preset),
    }
    path = _path(slot_name)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    logger.info("Сохранение записано: %s", path)
    return str(path)


def load_game(slot_name):
    path = _path(slot_name)
    if not path.exists():
        logger.warning("Сохранение не найдено: %s", path)
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("Не удалось прочитать %s: %s", path, exc)
        return None


def deserialize_world_state(state, snapshot):
    state.apply_snapshot(snapshot or {})
    return state


def list_saves():
    if not SAVES_DIR.is_dir():
        return []
    out = []
    for path in SAVES_DIR.glob("*.json"):
        if path.name.endswith(".tmp"):
            continue
        data = None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        timestamp = (data or {}).get("updated") or _now()
        out.append(
            {
                "name": path.stem,
                "timestamp": timestamp,
                "path": str(path),
            }
        )
    out.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return out


def delete_save(slot_name):
    path = _path(slot_name)
    try:
        path.unlink()
        logger.info("Сохранение удалено: %s", path)
        return True
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.warning("Не удалось удалить %s: %s", path, exc)
        return False
