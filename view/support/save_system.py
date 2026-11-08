import json
import os
import time
from pathlib import Path

from .log_journal import get_logger

logger = get_logger("view.save")
ROOT = Path(__file__).resolve().parents[2]
SAVES_DIR = ROOT / "saves" / "campaign"
# Версия формата сохранения. Миграции аддитивны: старый снимок получает
# недостающие ветки состояния, а неизвестные поля сохраняются как есть.
SAVE_VERSION = 2


def _migrate_v1_to_v2(data):
    """Миграция 1 → 2: стратегии узлов и долгосрочные планы среды.

    Оба поля необязательны и при отсутствии означают «поведение прежних
    версий». Поэтому миграция не переписывает кампанию, а только создаёт
    контейнеры, в которые `WorldEngine.load_snapshot()` и среда положат
    состояние при следующем сохранении.
    """
    campaign = data.get("campaign")
    if not isinstance(campaign, dict):
        campaign = {}
    campaign.setdefault("node_strategy_state", {})
    campaign.setdefault("environment_plan", {})
    data["campaign"] = campaign
    return data


def _ensure_containers(data):
    """Гарантировать контейнеры текущей версии даже у свежего сейва."""
    campaign = data.get("campaign")
    if not isinstance(campaign, dict):
        campaign = {}
    campaign.setdefault("node_strategy_state", {})
    campaign.setdefault("environment_plan", {})
    data["campaign"] = campaign
    return data


MIGRATIONS = {
    1: _migrate_v1_to_v2,
}

COMPATIBLE_MODES = ("automata", "strategy", "world")


def save_is_compatible(data):
    """Подходит ли сохранение текущим кампаниям, а не легаси-RTS.

    «Продолжить» должно возвращать в автоматы, стратегию или мир. Старые
    военные снимки без этих веток не открываются: иначе игрок попадает
    на устаревшую карту «Долина-1».
    """
    if not isinstance(data, dict):
        return False
    campaign = data.get("campaign")
    if isinstance(campaign, dict) and campaign.get("automata") is not None:
        return True
    storyline = data.get("storyline")
    state = (
        storyline.get("state")
        if isinstance(storyline, dict)
        else None
    )
    if isinstance(state, dict) and (
        state.get("strategy") is not None
        or state.get("world") is not None
    ):
        return True
    preset = data.get("campaign_preset")
    scenario = (
        preset.get("scenario")
        if isinstance(preset, dict)
        else None
    )
    if isinstance(scenario, dict):
        mode = str(scenario.get("mode") or "")
        if mode in COMPATIBLE_MODES:
            return True
    return False


def migrate_save(data):
    """Привести сохранение к текущей версии, не теряя старые поля.

    Неизвестная будущая версия не ломает загрузку: снимок возвращается
    как есть, а предупреждение попадает в лог. Это позволяет откатиться
    на старую сборку без потери файла.
    """
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    try:
        version = int(version) if version is not None else 1
    except (TypeError, ValueError):
        version = 1
    if version > SAVE_VERSION:
        logger.warning(
            "Сохранение новее этой сборки: %s > %s",
            version,
            SAVE_VERSION,
        )
        return data
    guarded = 0
    while version < SAVE_VERSION and guarded < 16:
        migrate = MIGRATIONS.get(version)
        if migrate is None:
            break
        data = migrate(data)
        version += 1
        guarded += 1
    data["version"] = SAVE_VERSION
    return _ensure_containers(data)


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
    payload = _ensure_containers(payload)
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
        return migrate_save(data)
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
                "compatible": save_is_compatible(data),
            }
        )
    out.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return out


def list_compatible_saves():
    """Сохранения, которые открываются в текущих кампаниях."""
    return [item for item in list_saves() if item.get("compatible")]


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
