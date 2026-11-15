"""Управляемый персонаж кампании (``PlayerAvatar``).

До P2 игрок был тождественен стороне фракции: ``player_side`` задавал и
армию, и героя, а ``player_character_id`` почти всегда указывал на
лидера. Это смешение мешает играть за школьника, музыканта или рядового
жреца: у них может не быть фракции и органов.

``PlayerAvatar`` — явная ссылка на персонажа, которым управляет игрок.
Он не заменяет ``player_side``: лорные кампании продолжают работать в
режиме ``delegated`` (игрок командует фракцией через лидера), а новый
режим ``direct`` позволяет управлять любым ``Character``.

Снимок аватара версионируется отдельно от снимка кампании. Старые сейвы
без блока ``avatar`` читаются как ``delegated``-аватар, собранный из
``player_character_id`` и ``player_faction_id``: миграция не требует
перезаписи файлов.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .errors import CampaignError

AVATAR_SCHEMA_VERSION = 1

CONTROL_MODES = ("direct", "delegated")


class AvatarError(CampaignError):
    pass


def _text(value, default=""):
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _mapping(value):
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


@dataclass(frozen=True)
class PlayerAvatar:
    """Ссылка на персонажа игрока и его положение в мире.

    ``character_id`` обязателен: даже свободный персонаж без фракции —
    это запись ``Character`` в состоянии кампании. ``faction_id`` и
    ``office_id`` опциональны; их отсутствие означает «без фракции» и
    «без должности», а не ошибку.
    """

    character_id: str
    faction_id: str = ""
    office_id: str = ""
    scene_id: str = ""
    control_mode: str = "delegated"
    schema: int = AVATAR_SCHEMA_VERSION

    def __post_init__(self):
        character_id = _text(self.character_id)
        if not character_id:
            raise AvatarError("avatar: пустой character_id")
        object.__setattr__(self, "character_id", character_id)
        object.__setattr__(self, "faction_id", _text(self.faction_id))
        object.__setattr__(self, "office_id", _text(self.office_id))
        object.__setattr__(self, "scene_id", _text(self.scene_id))
        mode = _text(self.control_mode, "delegated").lower()
        if mode not in CONTROL_MODES:
            raise AvatarError(
                "avatar: control_mode=%r не из %s"
                % (mode, ", ".join(CONTROL_MODES))
            )
        object.__setattr__(self, "control_mode", mode)
        schema = _as_int(self.schema, AVATAR_SCHEMA_VERSION)
        if schema != AVATAR_SCHEMA_VERSION:
            raise AvatarError(
                "avatar: неподдерживаемая версия схемы %s" % schema
            )
        object.__setattr__(self, "schema", schema)

    @property
    def has_faction(self):
        return bool(self.faction_id)

    @property
    def has_office(self):
        return bool(self.office_id)

    def with_office(self, office_id):
        return PlayerAvatar(
            character_id=self.character_id,
            faction_id=self.faction_id,
            office_id=office_id,
            scene_id=self.scene_id,
            control_mode=self.control_mode,
        )

    def with_scene(self, scene_id):
        return PlayerAvatar(
            character_id=self.character_id,
            faction_id=self.faction_id,
            office_id=self.office_id,
            scene_id=scene_id,
            control_mode=self.control_mode,
        )

    @classmethod
    def from_data(cls, data):
        if not isinstance(data, Mapping):
            raise AvatarError("avatar должен быть объектом")
        return cls(
            character_id=(
                data.get("character_id")
                or data.get("player_character_id")
                or ""
            ),
            faction_id=data.get("faction_id") or data.get("player_faction_id") or "",
            office_id=data.get("office_id") or data.get("post_id") or "",
            scene_id=data.get("scene_id") or data.get("location") or "",
            control_mode=data.get("control_mode") or "delegated",
            schema=data.get("schema", AVATAR_SCHEMA_VERSION),
        )

    def as_dict(self):
        return {
            "schema": self.schema,
            "character_id": self.character_id,
            "faction_id": self.faction_id,
            "office_id": self.office_id,
            "scene_id": self.scene_id,
            "control_mode": self.control_mode,
        }

    to_dict = as_dict


def _find_character(data, character_id):
    for item in data.get("characters") or ():
        if not isinstance(item, Mapping):
            continue
        if _text(item.get("id")) == character_id:
            return dict(item)
    return {}


def avatar_from_preset(data, control_mode="delegated"):
    """Собрать аватар из данных пресета или снимка кампании.

    Возвращает ``None``, если у пресета нет игрового персонажа: каталог
    ролей и сценарии без героя допустимы, но тогда аватар не создаётся.
    """
    data = _mapping(data)
    player = _mapping(data.get("player"))
    character_id = _text(
        data.get("player_character_id") or player.get("character_id")
    )
    if not character_id:
        return None
    faction_id = _text(
        data.get("player_faction_id") or player.get("faction_id")
    )
    record = _find_character(data, character_id)
    office_id = _text(
        record.get("office_id")
        or record.get("post_id")
        or record.get("post")
    )
    scene_id = _text(
        record.get("scene_id") or record.get("location")
    )
    mode = _text(
        record.get("control_mode")
        or player.get("control_mode")
        or control_mode,
        "delegated",
    )
    return PlayerAvatar(
        character_id=character_id,
        faction_id=faction_id,
        office_id=office_id,
        scene_id=scene_id,
        control_mode=mode,
    )


def avatar_from_snapshot(snapshot, fallback_data=None):
    """Восстановить аватар из снимка; старые сейвы читаются как delegated."""
    snapshot = _mapping(snapshot)
    raw = snapshot.get("avatar")
    if isinstance(raw, Mapping):
        return PlayerAvatar.from_data(raw)
    if raw is None and "avatar" in snapshot:
        return None
    return avatar_from_preset(fallback_data or snapshot, control_mode="delegated")


__all__ = [
    "AVATAR_SCHEMA_VERSION",
    "CONTROL_MODES",
    "AvatarError",
    "PlayerAvatar",
    "avatar_from_preset",
    "avatar_from_snapshot",
]
