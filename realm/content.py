"""Загрузка контента игры «Престол» (``configs/realm/*.json``).

Пакет ``realm`` — отдельная игра внутри репозитория. Она не импортирует
``simulation.py``/``warfare.py`` и не меняет канон. Контент отделён от логики:
модель получает уже разобранные словари, поэтому её можно тестировать без
графики и без чтения файлов.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs" / "realm"


class ContentError(RuntimeError):
    """Контент игры отсутствует или имеет неверную структуру."""


def _read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ContentError("не найден файл контента: %s" % path) from exc
    except json.JSONDecodeError as exc:
        raise ContentError("битый JSON контента: %s (%s)" % (path, exc)) from exc


class ContentPack:
    """Все статические данные «Престола» в одном объекте."""

    def __init__(self, config_dir=None):
        self.config_dir = Path(config_dir) if config_dir else CONFIG_DIR
        self.game = _read_json(self.config_dir / "game.json")
        self.advisors = _read_json(self.config_dir / "advisors.json").get(
            "advisors", []
        )
        self.petitions = _read_json(self.config_dir / "petitions.json").get(
            "petitions", []
        )
        self.events = _read_json(self.config_dir / "events.json").get(
            "events", []
        )
        self.mandates = _read_json(self.config_dir / "mandates.json").get(
            "mandates", []
        )
        self.story = _read_json(self.config_dir / "story.json")
        self.assets = _read_json(self.config_dir / "assets.json").get(
            "assets", []
        )
        self.petitions_by_id = {
            item.get("id"): item for item in self.petitions if item.get("id")
        }
        self.events_by_id = {
            item.get("id"): item for item in self.events if item.get("id")
        }
        self.mandates_by_id = {
            item.get("id"): item for item in self.mandates if item.get("id")
        }
        self._validate()

    def _validate(self):
        if not self.advisors:
            raise ContentError("нет советников в advisors.json")
        if not self.petitions:
            raise ContentError("нет прошений в petitions.json")
        if not self.mandates:
            raise ContentError("нет мандатов в mandates.json")
        for advisor in self.advisors:
            for key in ("id", "name", "role", "influence", "preferences"):
                if key not in advisor:
                    raise ContentError(
                        "советник %r: нет поля %s" % (advisor.get("id"), key)
                    )
        for petition in self.petitions:
            options = petition.get("options") or []
            if len(options) < 2:
                raise ContentError(
                    "прошение %r: нужно минимум два варианта"
                    % petition.get("id")
                )
            for option in options:
                for key in ("id", "label", "effects"):
                    if key not in option:
                        raise ContentError(
                            "прошение %r: вариант %r без поля %s"
                            % (petition.get("id"), option.get("id"), key)
                        )

    # --- выборки ---------------------------------------------------------
    def petition(self, petition_id):
        return self.petitions_by_id.get(petition_id)

    def event(self, event_id):
        return self.events_by_id.get(event_id)

    def mandate(self, mandate_id):
        return self.mandates_by_id.get(mandate_id)

    def default_mandate_id(self):
        return self.mandates[0]["id"]

    def asset(self, key):
        for item in self.assets:
            if item.get("key") == key:
                return item
        return None
