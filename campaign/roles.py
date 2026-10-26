"""Роли игрока: декларативный каталог и стабильный выбор роли.

Роль — это не класс персонажа и не боевая специальность. Это позиция
игрока в кампании: кем он входит в мир, какие права и ограничения получает.
Первый каталог намеренно содержит только одну доступную роль —
``faction_leader`` (номинальный лидер фракции-автомата). Будущие роли
добавляются в ``configs/roles/roles.json`` без изменения кода генератора и
экрана выбора.

Слой чистый: он не импортирует pygame и не зависит от ``view``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Dict, Mapping, Tuple

from .errors import CampaignError


ROLE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class RoleError(CampaignError):
    """Ошибка каталога ролей или выбранной роли."""


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise RoleError("конфиг ролей не найден: %s" % path)
    except Exception as exc:
        raise RoleError("не удалось прочитать %s: %s" % (path, exc))


def _text(value, default=""):
    if value is None:
        return default
    return str(value)


def _tags(value):
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        return (str(value).strip(),)
    return tuple(str(item).strip() for item in value if str(item).strip())


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


@dataclass(frozen=True)
class RoleSpec:
    """Одна роль игрока из каталога.

    Attributes:
        id: Стабильный машинный идентификатор (например, ``faction_leader``).
        label: Название для игрока.
        short_label: Короткое название для HUD и кнопок.
        description: Пояснение, что роль значит в кампании.
        leadership: Режим лидерства (``nominal``, затем, возможно, другие).
        faction_kind: Тип фракции, к которой относится роль.
        faction_slot: Слот фракции в пресете (``player``/``enemy``).
        faction_choice: Показывать ли выбор фракции после роли.
        storyline_id: Сюжет, который запускается для этой роли.
        available: Можно ли выбрать роль в текущей сборке.
        sort_order: Порядок в каталоге и на экране выбора.
        grants: Переменные, которые роль передаёт сюжету/кампании.
        tags: Смысловые теги для будущих правил и фильтров.
    """

    id: str
    label: str
    description: str = ""
    short_label: str = ""
    leadership: str = "nominal"
    faction_kind: str = "automaton"
    faction_slot: str = "player"
    faction_choice: bool = False
    storyline_id: str = ""
    available: bool = True
    sort_order: int = 0
    grants: Mapping[str, object] = field(default_factory=dict)
    tags: Tuple[str, ...] = ()

    def __post_init__(self):
        role_id = str(self.id or "").strip()
        label = str(self.label or "").strip()
        if not ROLE_ID_RE.match(role_id):
            raise RoleError(
                "id роли: строчная латиница, цифры и _, первый символ — буква"
            )
        if not label:
            raise RoleError("%s: пустой label" % role_id)
        if not str(self.leadership or "").strip():
            raise RoleError("%s: пустой leadership" % role_id)
        if not str(self.faction_kind or "").strip():
            raise RoleError("%s: пустой faction_kind" % role_id)
        if not str(self.faction_slot or "").strip():
            raise RoleError("%s: пустой faction_slot" % role_id)
        if not isinstance(self.grants, Mapping):
            raise RoleError("%s: grants должен быть объектом" % role_id)
        object.__setattr__(self, "id", role_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "description", _text(self.description))
        object.__setattr__(self, "short_label", _text(self.short_label) or label)
        object.__setattr__(self, "leadership", str(self.leadership).strip())
        object.__setattr__(self, "faction_kind",
                           str(self.faction_kind).strip())
        object.__setattr__(self, "faction_slot",
                           str(self.faction_slot).strip())
        object.__setattr__(self, "faction_choice", bool(self.faction_choice))
        object.__setattr__(self, "storyline_id",
                           str(self.storyline_id or "").strip())
        object.__setattr__(self, "available", bool(self.available))
        object.__setattr__(self, "sort_order", _as_int(self.sort_order, 0))
        object.__setattr__(self, "grants", dict(self.grants))
        object.__setattr__(self, "tags", _tags(self.tags))

    @classmethod
    def from_data(cls, data, index=0):
        if not isinstance(data, Mapping):
            raise RoleError("role[%d] должен быть объектом" % index)
        return cls(
            id=data.get("id"),
            label=data.get("label") or data.get("name"),
            description=data.get("description", ""),
            short_label=data.get("short_label", ""),
            leadership=data.get("leadership", "nominal"),
            faction_kind=data.get("faction_kind", "automaton"),
            faction_slot=data.get("faction_slot", "player"),
            faction_choice=data.get("faction_choice", False),
            storyline_id=data.get("storyline_id", ""),
            available=data.get("available", True),
            sort_order=data.get("sort_order", index),
            grants=data.get("grants") or {},
            tags=data.get("tags") or (),
        )

    @property
    def display_name(self):
        return self.short_label or self.label

    @property
    def is_available(self):
        return bool(self.available)

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "short_label": self.short_label,
            "description": self.description,
            "leadership": self.leadership,
            "faction_kind": self.faction_kind,
            "faction_slot": self.faction_slot,
            "faction_choice": self.faction_choice,
            "storyline_id": self.storyline_id,
            "available": self.available,
            "sort_order": self.sort_order,
            "grants": dict(self.grants),
            "tags": list(self.tags),
        }


class RoleCatalog:
    """Каталог ролей, загруженный из ``configs/roles/roles.json``."""

    def __init__(self, roles, schema=1):
        roles = list(roles or ())
        if not roles:
            raise RoleError("в каталоге нет ни одной роли")
        self.roles: Dict[str, RoleSpec] = {}
        for role in roles:
            if not isinstance(role, RoleSpec):
                raise RoleError("каталог должен содержать RoleSpec")
            if role.id in self.roles:
                raise RoleError("повторяется id роли: %s" % role.id)
            self.roles[role.id] = role
        self.schema = _as_int(schema, 1)
        if not self.available_roles():
            raise RoleError("в каталоге нет ни одной доступной роли")

    @classmethod
    def load(cls, root=None):
        path = Path(root) if root is not None else default_root()
        if path.is_dir():
            path = path / "roles.json"
        data = _read_json(path)
        return cls.from_data(data, root=path.parent)

    @classmethod
    def from_data(cls, data, root=None):
        del root  # зарезервировано для будущих относительных ссылок
        if not isinstance(data, Mapping):
            raise RoleError("roles.json должен быть объектом")
        raw = data.get("roles")
        if not isinstance(raw, (list, tuple)):
            raise RoleError("roles должен быть списком")
        roles = [
            RoleSpec.from_data(item, index)
            for index, item in enumerate(raw)
        ]
        return cls(roles, schema=data.get("schema", 1))

    def role(self, role_id):
        role_id = str(role_id or "").strip()
        role = self.roles.get(role_id)
        if role is None:
            raise RoleError("нет роли %r" % (role_id,))
        return role

    def require(self, role_id, available=True):
        role = self.role(role_id)
        if available and not role.available:
            raise RoleError("роль %r недоступна" % (role_id,))
        return role

    def available_roles(self):
        return sorted(
            (role for role in self.roles.values() if role.available),
            key=lambda role: (role.sort_order, role.label, role.id),
        )

    def all_roles(self):
        return sorted(
            self.roles.values(),
            key=lambda role: (role.sort_order, role.label, role.id),
        )

    def default_role(self):
        available = self.available_roles()
        if not available:
            raise RoleError("нет доступных ролей")
        return available[0]

    def select(self, role_id=None):
        """Выбрать роль; ``None`` означает первую доступную."""
        if role_id is None:
            return self.default_role()
        return self.require(role_id, available=True)

    def as_dict(self):
        return {
            "schema": self.schema,
            "roles": [self.roles[key].as_dict()
                      for key in sorted(self.roles)],
        }


def default_root():
    return Path(__file__).resolve().parents[1] / "configs" / "roles"


_DEFAULT = None


def default_catalog():
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = RoleCatalog.load()
    return _DEFAULT


__all__ = [
    "ROLE_ID_RE",
    "RoleError",
    "RoleSpec",
    "RoleCatalog",
    "default_root",
    "default_catalog",
]
