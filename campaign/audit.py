"""Файловый аудит статистики кампании.

Пишет JSON Lines в ``campaign_stats.log`` (по умолчанию в корне проекта).
Консоль не используется: подробная статистика нужна для разбора партии,
а не для засорения терминала. Один объект на строку удобно фильтровать
через ``jq``, ``grep`` или загружать в pandas.

Формат события::

    {"ts": "...", "event": "tick", "turn": 12, "elapsed": 1036800.0,
     "side": "red", "assets_before": {...}, "assets_after": {...},
     "asset_deltas": {...}, "breakdowns": {...}}

Включается секцией ``debug`` пресета/автодефолтов::

    {"debug": {"stats": true, "stats_path": "campaign_stats.log"}}

Переменные окружения ``OZVERIN_STATS=0`` и ``OZVERIN_STATS_LOG``
переопределяют конфиг. Это удобно для тестов и ручных прогонов.
"""

from __future__ import annotations

from datetime import datetime
import json
import math
import os
from pathlib import Path

from .faction_state import asset_breakdowns, derived_assets


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "campaign_stats.log"
ENV_ENABLED = "OZVERIN_STATS"
ENV_PATH = "OZVERIN_STATS_LOG"
MAX_BYTES = 16 * 1024 * 1024
BACKUPS = 2
_handles = {}


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(result) or math.isinf(result):
        return float(default)
    return result


def _flag(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, str):
        return value.strip().lower() not in (
            "",
            "0",
            "false",
            "no",
            "off",
        )
    return bool(value)


def _env_flag():
    raw = os.environ.get(ENV_ENABLED)
    if raw is None:
        return None
    return _flag(raw, True)


def resolved_path(config=None):
    """Путь журнала: окружение важнее конфига, конфиг — дефолта."""
    raw = os.environ.get(ENV_PATH)
    if not raw:
        raw = (config or {}).get("stats_path")
    path = Path(os.path.expanduser(str(raw or DEFAULT_PATH)))
    if not path.is_absolute():
        path = ROOT / path
    return path


def _json_default(value):
    if isinstance(value, set):
        return sorted(str(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _rotate(path):
    try:
        if not path.exists() or path.stat().st_size < MAX_BYTES:
            return
        for index in range(BACKUPS, 0, -1):
            source = path
            if index > 1:
                source = path.with_name(
                    "%s.%d" % (path.name, index - 1)
                )
            target = path.with_name("%s.%d" % (path.name, index))
            if source.exists():
                source.replace(target)
    except OSError:
        return


def _write(path, payload):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = str(path)
        handle = _handles.get(key)
        needs_rotation = (
            path.exists() and path.stat().st_size >= MAX_BYTES
        )
        if needs_rotation:
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
                _handles.pop(key, None)
            _rotate(path)
            handle = None
        if handle is None or handle.closed:
            handle = path.open("a", encoding="utf-8", buffering=1)
            _handles[key] = handle
        handle.write(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                default=_json_default,
            )
        )
        handle.write("\n")
    except OSError:
        # Аудит не должен ломать кампанию: нет доступа к файлу — молчим.
        return


def reset():
    """Закрыть файловые дескрипторы (тесты и ручная ротация)."""
    for handle in list(_handles.values()):
        try:
            handle.close()
        except OSError:
            pass
    _handles.clear()


def _round_map(values, digits=6):
    return {
        str(key): round(_number(value), digits)
        for key, value in (values or {}).items()
    }


def delta_map(before, after, digits=6):
    keys = set(before or {}) | set(after or {})
    result = {}
    for key in sorted(keys):
        delta = _number((after or {}).get(key)) - _number(
            (before or {}).get(key)
        )
        if abs(delta) > 10 ** (-digits):
            result[str(key)] = round(delta, digits)
    return result


def _character_state(character):
    state = getattr(character, "state", {}) or {}
    force = _number(getattr(character, "force", 0.0))
    energy = _number(getattr(character, "energy_pool", 0.0))
    force_max = max(1e-9, _number(state.get("max_force"), force or 1.0))
    energy_max = max(
        1e-9, _number(state.get("max_energy"), energy or 1.0)
    )
    conditions = getattr(getattr(character, "bdi", None), "conditions", {})
    return {
        "id": str(getattr(character, "campaign_id", "") or ""),
        "name": str(getattr(character, "name", "") or ""),
        "post": str(getattr(character, "campaign_post", "") or ""),
        "morale": round(_number(getattr(character, "morale", 0.0)), 6),
        "force": round(force, 6),
        "force_max": round(force_max, 6),
        "force_share": round(min(1.0, force / force_max), 6),
        "energy": round(energy, 6),
        "energy_max": round(energy_max, 6),
        "energy_share": round(min(1.0, energy / energy_max), 6),
        "needs": _round_map(getattr(character, "needs", {})),
        "conditions": _round_map(conditions),
        "mind": str(getattr(character, "mind", "") or ""),
        "dead": bool(
            getattr(
                character,
                "is_dead",
                getattr(character, "dead", False),
            )
        ),
    }


def _character_delta(before, after):
    result = {}
    for key in (
        "morale",
        "force",
        "energy",
        "force_share",
        "energy_share",
    ):
        delta = _number(after.get(key)) - _number(before.get(key))
        if abs(delta) > 1e-6:
            result[key] = round(delta, 6)
    for section in ("needs", "conditions"):
        changed = delta_map(
            before.get(section), after.get(section)
        )
        if changed:
            result[section] = changed
    return result


def _character_summary(characters):
    states = [_character_state(item) for item in characters]
    if not states:
        return {"count": 0}
    alive = [item for item in states if not item["dead"]]
    sample = alive or states

    def mean(key):
        return round(
            sum(_number(item.get(key)) for item in sample)
            / float(len(sample)),
            6,
        )

    return {
        "count": len(states),
        "alive": len(alive),
        "morale_mean": mean("morale"),
        "force_share_mean": mean("force_share"),
        "energy_share_mean": mean("energy_share"),
        "force_min": round(
            min(_number(item.get("force_share")) for item in sample), 6
        ),
        "energy_min": round(
            min(_number(item.get("energy_share")) for item in sample), 6
        ),
        "mind": {
            str(mind): sum(
                1 for item in states if item.get("mind") == mind
            )
            for mind in sorted(
                {str(item.get("mind") or "") for item in states}
            )
        },
    }


def _organization_state(faction):
    snapshot = getattr(faction, "organization_snapshot", {}) or {}
    return {
        str(key): round(_number(value), 6)
        for key, value in snapshot.items()
        if isinstance(value, (int, float, bool))
    }


class CampaignStats:
    """Писатель диагностических событий конкретной кампании."""

    def __init__(self, campaign, config=None):
        self.campaign = campaign
        self.config = dict(config or {})
        env = _env_flag()
        self.enabled = _flag(self.config.get("stats"), False)
        if env is not None:
            self.enabled = env
        self.path = resolved_path(self.config)
        self.formulas = _flag(
            self.config.get("stats_formulas"), True
        )
        self.characters = _flag(
            self.config.get("stats_characters"), True
        )
        self.actions = _flag(self.config.get("stats_actions"), True)
        self.effects = _flag(self.config.get("stats_effects"), True)
        self.outcome = _flag(self.config.get("stats_outcome"), True)
        self.verbose_report = _flag(
            self.config.get("stats_verbose_report"), False
        )
        self._seq = 0

    def log(self, event, **fields):
        if not self.enabled:
            return
        campaign = self.campaign
        self._seq += 1
        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "seq": self._seq,
            "event": str(event),
            "turn": int(getattr(campaign, "turn", 0)),
            "elapsed": round(
                _number(getattr(campaign, "elapsed", 0.0)), 3
            ),
            "game_time": str(
                getattr(campaign, "time_label", lambda: "")()
            ),
            "speed": int(getattr(campaign, "speed", 1)),
            "outcome": getattr(campaign, "outcome", None),
            "finished": bool(getattr(campaign, "finished", False)),
        }
        for key, value in fields.items():
            if value is not None:
                payload[str(key)] = value
        _write(self.path, payload)

    def assets(self, faction):
        return {
            str(key): round(_number(value), 6)
            for key, value in derived_assets(faction).items()
        }

    def breakdowns(self, faction):
        if not self.formulas:
            return None
        return asset_breakdowns(faction)

    def character_state(self, character):
        if not self.characters:
            return None
        return _character_state(character)

    def character_delta(self, before, after):
        if before is None or after is None:
            return None
        return _character_delta(before, after)

    def character_summary(self, faction):
        if not self.characters:
            return None
        return _character_summary(
            list(getattr(faction, "characters", ()) or ())
        )

    def faction_state(self, faction):
        assets = self.assets(faction)
        return {
            "assets": assets,
            "context": _round_map(getattr(faction, "context", {})),
            "organization": _organization_state(faction),
            "characters": self.character_summary(faction),
        }


__all__ = [
    "CampaignStats",
    "DEFAULT_PATH",
    "ENV_ENABLED",
    "ENV_PATH",
    "delta_map",
    "reset",
    "resolved_path",
]
