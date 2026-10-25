"""Безопасная загрузка JSON-конфигов для UI-слоя."""

import json
from pathlib import Path

from .log_journal import get_logger

logger = get_logger("view.config_loader")


def load_json(path, default=None):
    """Прочитать JSON; вернуть ``default`` при отсутствии/ошибке."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / p
    if not p.exists():
        logger.warning("JSON не найден: %s", p)
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:                       # noqa: BLE001
        logger.warning("Не удалось прочитать %s: %s", p, exc)
        return default
