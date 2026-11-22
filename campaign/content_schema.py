"""JSON Schema для контента (G-12).

Схемы лежат в ``configs/schemas`` и описывают то, что ядро действительно
исполняет: эффекты, условия, требования, органы, подфракции и автоматы.
Модуль не заменяет ``campaign/content_lint.py``: семантические проверки
ссылок и имён остаются там, а схема ловит опечатки в полях и неверные
типы вложенных структур.

Зависимость ``jsonschema`` необязательна. Если её нет, ``validate``
возвращает пустой список, а линтер работает как раньше. Это сохраняет
принцип «ядро и тесты — на стандартной библиотеке»: строгая проверка
включается там, где установлены dev-зависимости.
"""

from __future__ import annotations

import json
import pathlib
import re
from functools import lru_cache
from typing import Any, List, Mapping

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "configs" / "schemas"

SCHEMA_FILES = {
    "effects": "effects.schema.json",
    "conditions": "conditions.schema.json",
    "requires": "requires.schema.json",
    "organ": "organ.schema.json",
    "subfaction": "subfaction.schema.json",
    "order": "order.schema.json",
    "automaton": "automaton.schema.json",
    "bdi": "bdi.schema.json",
    "work": "work.schema.json",
    "lore_factions": "lore_factions.schema.json",
    "automata_defaults": "automata_defaults.schema.json",
    "campaign_template": "campaign_template.schema.json",
    "event": "event.schema.json",
    "event_item": "event_item.schema.json",
}


def available() -> bool:
    """Есть ли в окружении ``jsonschema`` (и его ``referencing``)."""
    try:
        import jsonschema  # noqa: F401
        import referencing  # noqa: F401
    except ImportError:
        return False
    return True


def _require():
    if not available():
        raise RuntimeError("jsonschema не установлен")
    import jsonschema
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    return jsonschema, Registry, Resource, DRAFT202012


@lru_cache(maxsize=1)
def _registry():
    """Реестр всех схем: ссылки между файлами резолвятся по ``$id``."""
    _jsonschema, Registry, Resource, DRAFT202012 = _require()
    pairs = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        with path.open(encoding="utf-8") as handle:
            contents = json.load(handle)
        schema_id = str(contents.get("$id") or "")
        if not schema_id:
            raise ValueError("%s: нет $id" % path)
        resource = Resource.from_contents(
            contents, default_specification=DRAFT202012
        )
        pairs.append((schema_id, resource))
    return Registry().with_resources(pairs)


@lru_cache(maxsize=None)
def _validator(name):
    jsonschema, _Registry, _Resource, _Draft = _require()
    filename = SCHEMA_FILES[name]
    with (SCHEMA_DIR / filename).open(encoding="utf-8") as handle:
        schema = json.load(handle)
    return jsonschema.Draft202012Validator(schema, registry=_registry())


def schema_names() -> tuple:
    return tuple(SCHEMA_FILES)


@lru_cache(maxsize=None)
def schema_document(name: str) -> Mapping:
    """Прочитать файл схемы без участия ``jsonschema``.

    Нужен линтеру, чтобы не дублировать списки ключей в Python: даже без
    установленной dev-зависимости контракт остаётся единственным
    источником истины.
    """
    if name not in SCHEMA_FILES:
        raise KeyError("неизвестная схема %r" % name)
    path = SCHEMA_DIR / SCHEMA_FILES[name]
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ValueError("%s: корень схемы должен быть объектом" % path)
    return data


def schema_keys(name: str) -> frozenset:
    """Верхнеуровневые ключи исполняемого блока."""
    return frozenset(schema_document(name).get("properties") or {})


@lru_cache(maxsize=1)
def condition_kinds() -> frozenset:
    """Виды атомарных условий из ``conditions.schema.json``."""
    definitions = schema_document("conditions").get("$defs") or {}
    atomic = definitions.get("atomic") or {}
    enum = (atomic.get("properties") or {}).get("kind", {}).get(
        "enum"
    ) or ()
    return frozenset(str(item) for item in enum)


def check_schema_files() -> List[str]:
    """Проверить сами файлы схем; возвращает проблемы, не бросает."""
    if not available():
        return []
    import jsonschema

    problems = []
    for name, filename in SCHEMA_FILES.items():
        path = SCHEMA_DIR / filename
        try:
            with path.open(encoding="utf-8") as handle:
                contents = json.load(handle)
            jsonschema.Draft202012Validator.check_schema(contents)
        except (OSError, ValueError, jsonschema.SchemaError) as error:
            problems.append("%s: %s" % (path, error))
    return problems


def _all_leaves(error):
    """Собрать листья составной ошибки, не выбирая ветку заранее."""
    if error.context and error.validator != "additionalProperties":
        result = []
        for item in error.context:
            result.extend(_all_leaves(item))
        return result
    return [error]


def _best_leaves(leaves):
    """Оставить самые точные листья: глубже и конкретнее, чем ``type``.

    ``oneOf``/``anyOf`` дают ошибки всех веток. Ветка «не тот тип» почти
    всегда мельче настоящей причины (неизвестное поле, missing required),
    поэтому сначала выбирается максимальная глубина пути, затем —
    конкретный валидатор вместо ``type``.
    """
    if not leaves:
        return []
    depth = max(len(list(item.absolute_path)) for item in leaves)
    deepest = [
        item
        for item in leaves
        if len(list(item.absolute_path)) == depth
    ]
    rank = {
        "additionalProperties": 0,
        "required": 0,
        "enum": 1,
        "const": 1,
        "type": 5,
    }
    best = min(rank.get(item.validator, 3) for item in deepest)
    chosen = [
        item
        for item in deepest
        if rank.get(item.validator, 3) == best
    ]
    # Ветка-группа ``all/any/not`` считает неизвестными все поля атомарного
    # условия. Если обе ветки дали ``additionalProperties`` на одном пути,
    # побеждает ветка с меньшим числом лишних полей.
    by_path = {}
    for item in chosen:
        key = tuple(item.absolute_path)
        by_path.setdefault(key, []).append(item)
    result = []
    for items in by_path.values():
        if items and all(
            item.validator == "additionalProperties" for item in items
        ):
            smallest = min(
                len(re.findall(r"'([^']+)'", str(item.message))) or 1
                for item in items
            )
            result.extend(
                item
                for item in items
                if (
                    len(re.findall(r"'([^']+)'", str(item.message))) or 1
                )
                == smallest
            )
        else:
            result.extend(items)
    return result


def _leaves(error):
    """Развернуть составную ошибку до наиболее точных листьев."""
    if error.context and error.validator != "additionalProperties":
        yield from _best_leaves(_all_leaves(error))
        return
    yield error


def _message(error) -> str:
    validator = error.validator
    if validator == "required":
        required = error.validator_value
        if isinstance(error.instance, Mapping):
            missing = [
                str(item) for item in required if item not in error.instance
            ]
        else:
            missing = [str(item) for item in required]
        return "обязательное поле: %s" % ", ".join(missing or ["?"])
    if validator == "additionalProperties":
        names = re.findall(r"'([^']+)'", str(error.message))
        if names:
            return "неизвестное поле: %s" % ", ".join(names)
        return "неизвестное поле"
    if validator == "type":
        expected = error.validator_value
        if isinstance(expected, (list, tuple)):
            expected = "/".join(str(item) for item in expected)
        return "ожидался тип %s" % expected
    if validator == "enum":
        return "ожидалось одно из: %s" % ", ".join(
            str(item) for item in error.validator_value
        )
    if validator == "const":
        return "ожидалось значение %r" % (error.validator_value,)
    if validator == "minimum":
        return "значение меньше %s" % error.validator_value
    if validator == "maximum":
        return "значение больше %s" % error.validator_value
    if validator == "minLength":
        return "слишком короткое значение"
    if validator == "minProperties":
        return "нужен хотя бы один ключ"
    if validator == "pattern":
        return "значение не соответствует образцу %s" % (
            error.validator_value,
        )
    return str(error.message)


def _location(where: str, path: str) -> str:
    if where and path:
        return "%s.%s" % (where, path)
    return where or path or "контент"


def validate(name: str, data: Any, where: str = "") -> List[str]:
    """Проверить ``data`` схемой ``name``; вернуть читаемые проблемы.

    ``None`` означает отсутствие блока и не проверяется. Если
    ``jsonschema`` не установлен, проверка пропускается.
    """
    if data is None or not available():
        return []
    if name not in SCHEMA_FILES:
        raise KeyError("неизвестная схема %r" % name)
    validator = _validator(name)
    problems: List[str] = []
    seen = set()
    for error in validator.iter_errors(data):
        for leaf in _leaves(error):
            path = "/".join(str(item) for item in leaf.absolute_path)
            message = _message(leaf)
            key = (path, message)
            if key in seen:
                continue
            seen.add(key)
            problems.append(
                "%s: схема %s: %s"
                % (_location(where, path), name, message)
            )
    return problems


__all__ = [
    "SCHEMA_DIR",
    "SCHEMA_FILES",
    "available",
    "check_schema_files",
    "condition_kinds",
    "schema_document",
    "schema_keys",
    "schema_names",
    "validate",
]
