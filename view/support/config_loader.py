import json
from pathlib import Path

from .log_journal import get_logger

logger = get_logger("view.config_loader")
ROOT = Path(__file__).resolve().parents[2]


def load_json(path, default=None):
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists():
        logger.warning("JSON не найден: %s", p)
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Не удалось прочитать %s: %s", p, exc)
        return default
