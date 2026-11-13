"""Сборка и нормализация логических форм.

Шаблоны семантики тоже данные: правило грамматики ссылается на роли
дочерних разборов через ``$role`` и ``$role.path``.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from .errors import DialogueError


def _get_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise DialogueError("в семантике нет пути %r" % path)
        current = current[part]
    return current


def resolve(reference: str, roles: Mapping[str, Any]) -> Any:
    """Разрешить ``$role`` или ``$role.path`` в семантике."""

    path = reference[1:] if reference.startswith("$") else reference
    if not path:
        raise DialogueError("пустая ссылка в семантике")
    head, _, tail = path.partition(".")
    if head not in roles:
        raise DialogueError("в семантике нет роли %r" % head)
    value = roles[head]
    if tail:
        return _get_path(value, tail)
    return value


def substitute(template: Any, roles: Mapping[str, Any]) -> Any:
    """Подставить семантику дочерних разборов в шаблон правила."""

    if isinstance(template, str):
        if template.startswith("$"):
            return resolve(template, roles)
        return template
    if isinstance(template, list):
        return [substitute(item, roles) for item in template]
    if isinstance(template, Mapping):
        return {
            str(key): substitute(value, roles)
            for key, value in template.items()
        }
    return template


def flatten(value: Any) -> Any:
    """Свернуть лексические дескрипторы в компактную логическую форму."""

    if isinstance(value, list):
        return [flatten(item) for item in value]
    if not isinstance(value, Mapping):
        return value
    kind = value.get("kind")
    if kind == "entity":
        return {"entity": value.get("id")}
    if kind == "neg":
        return True
    if kind in (
        "predicate",
        "adjective",
        "wh",
        "prep",
        "essence",
        "pronoun",
    ):
        return value.get("id")
    if kind == "number":
        return value.get("value")
    if kind == "np":
        result: Dict[str, Any] = {
            "kind": "np",
            "head": flatten(value.get("head")),
        }
        modifiers = value.get("modifiers")
        if modifiers:
            result["modifiers"] = [flatten(item) for item in modifiers]
        return result
    if kind == "pp":
        return {
            "kind": "pp",
            "prep": flatten(value.get("prep")),
            "object": flatten(value.get("object")),
        }
    return {str(key): flatten(item) for key, item in value.items()}


def entity_id(value: Any) -> str:
    """Найти идентификатор сущности в логической форме."""

    if isinstance(value, Mapping):
        if value.get("kind") == "entity":
            return str(value.get("id") or "")
        if "entity" in value and len(value) == 1:
            return str(value.get("entity") or "")
        for item in value.values():
            found = entity_id(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = entity_id(item)
            if found:
                return found
    return ""


def predicate_id(value: Any) -> str:
    """Найти идентификатор предиката/прилагательного в форме."""

    if isinstance(value, Mapping):
        if value.get("kind") in ("predicate", "adjective"):
            return str(value.get("id") or "")
        for item in value.values():
            found = predicate_id(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = predicate_id(item)
            if found:
                return found
    return ""