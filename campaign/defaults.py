"""Загрузка данных кампании автоматов из конфигов.

Ядро кампании не хранит содержимое работ, взаимодействий и коэффициентов:
всё это лежит в ``configs/campaigns/base/automata_defaults.json``. Модуль
только читает JSON и отдаёт неизменяемый словарь. Значения шаблона кампании
могут переопределять их через блок ``scenario.realtime`` и ``scenario.model``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


DEFAULTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs"
    / "campaigns"
    / "base"
    / "automata_defaults.json"
)


class CampaignDefaultsError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_defaults():
    """Прочитать и закешировать базовые данные кампании автоматов."""
    try:
        with DEFAULTS_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise CampaignDefaultsError(
            "не удалось прочитать данные кампании: %s" % DEFAULTS_PATH
        ) from exc
    if not isinstance(data, dict):
        raise CampaignDefaultsError(
            "данные кампании должны быть объектом: %s" % DEFAULTS_PATH
        )
    return data


def default_section(name):
    """Вернуть раздел данных; отсутствие раздела — ошибка конфига."""
    data = load_defaults()
    if name not in data:
        raise CampaignDefaultsError(
            "в данных кампании нет раздела %r" % (name,)
        )
    return data[name]


def default_list(name):
    value = default_section(name)
    if not isinstance(value, list):
        raise CampaignDefaultsError("раздел %r должен быть списком" % (name,))
    return [dict(item) for item in value if isinstance(item, dict)]


def default_dict(name):
    value = default_section(name)
    if not isinstance(value, dict):
        raise CampaignDefaultsError("раздел %r должен быть объектом" % (name,))
    return dict(value)


__all__ = [
    "CampaignDefaultsError",
    "DEFAULTS_PATH",
    "default_dict",
    "default_list",
    "default_section",
    "load_defaults",
]
