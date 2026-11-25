"""Детерминированная сериализация для когнитивных контрактов."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Компактный JSON с сортировкой ключей и без потери Unicode."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_digest(value: Any) -> str:
    """SHA-256 от канонического JSON."""

    return hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def pretty_json(value: Any) -> str:
    """Читаемый JSON с завершающим переводом строки."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )


__all__ = ["canonical_digest", "canonical_json", "pretty_json"]
