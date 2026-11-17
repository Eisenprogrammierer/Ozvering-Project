"""Предмет как автомат ``I/O/H/S/F/E/W``.

Предмет не получает бонус к строке персонажа. У него есть собственные
входы и выходы, обработчики, состояние, сила, энергия и журнал работ.
Данные лежат в поле ``automaton`` предмета мира; этот модуль только
нормализует их, применяет обработчик и сохраняет состояние в снимок.

Схема намеренно маленькая:

* ``I`` — ``inputs``: какие формы работы предмет принимает;
* ``O`` — ``outputs``: какие формы отдаёт;
* ``H`` — ``handlers``: именованные обработчики с ценой и эффектами;
* ``S`` — ``state``: числовые состояния предмета (износ, страницы, заряд);
* ``F`` — ``force``: целостность и предел работы;
* ``E`` — ``energy``: запас, который тратит обработчик;
* ``W`` — ``work``: последние работы предмета.

Модуль не знает о мире, персонажах и нормах. Эффекты обработчика
применяет ``WorldEngine``, поэтому предмет остаётся данными, а не
отдельной веткой правил в ядре.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping

ITEM_AUTOMATON_SCHEMA = "I/O/H/S/F/E/W"
ITEM_WORK_LIMIT = 32


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _text(value, default=""):
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _handler_map(raw):
    result = {}
    for name, payload in (raw or {}).items():
        name = _text(name)
        if not name or not isinstance(payload, Mapping):
            continue
        result[name] = {
            "label": _text(payload.get("label"), name),
            "energy": max(0.0, _as_float(payload.get("energy"), 0.0)),
            "force": max(0.0, _as_float(payload.get("force"), 0.0)),
            "state": {
                _text(key): _as_float(value)
                for key, value in (payload.get("state") or {}).items()
                if _text(key)
            },
            "consume": bool(payload.get("consume", False)),
            "effects": copy.deepcopy(
                dict(payload.get("effects") or {})
            ),
        }
    return result


def normalize_item_automaton(item_id, spec):
    """Собрать изменяемое состояние автомата предмета из JSON."""
    spec = spec if isinstance(spec, Mapping) else {}
    handlers = _handler_map(spec.get("handlers"))
    default_handler = _text(spec.get("default_handler"))
    if default_handler not in handlers:
        default_handler = next(iter(handlers), "")
    force = max(0.0, _as_float(spec.get("force"), 1.0))
    energy = max(0.0, _as_float(spec.get("energy"), 1.0))
    max_force = max(
        force, max(0.0, _as_float(spec.get("max_force"), force))
    )
    max_energy = max(
        energy, max(0.0, _as_float(spec.get("max_energy"), energy))
    )
    return {
        "schema": ITEM_AUTOMATON_SCHEMA,
        "id": _text(item_id),
        "inputs": tuple(
            _text(value)
            for value in (spec.get("inputs") or ())
            if _text(value)
        ),
        "outputs": tuple(
            _text(value)
            for value in (spec.get("outputs") or ())
            if _text(value)
        ),
        "handlers": handlers,
        "state": {
            _text(key): _as_float(value)
            for key, value in (spec.get("state") or {}).items()
            if _text(key)
        },
        "force": force,
        "max_force": max_force,
        "energy": energy,
        "max_energy": max_energy,
        "default_handler": default_handler,
        "work": [
            dict(entry)
            for entry in (spec.get("work") or ())
            if isinstance(entry, Mapping)
        ][-ITEM_WORK_LIMIT:],
    }


def item_automaton_view(automaton):
    """Копия автомата для UI и снимка: без общих изменяемых ссылок."""
    return copy.deepcopy(automaton)


def item_automaton_snapshot(automaton):
    """Сериализуемое состояние автомата для снимка мира."""
    data = item_automaton_view(automaton)
    data["inputs"] = list(data.get("inputs") or ())
    data["outputs"] = list(data.get("outputs") or ())
    return data


def restore_item_automaton(automaton, saved):
    """Наложить сохранённое состояние на данные текущего предмета.

    Форма автомата и обработчики всегда берутся из актуального JSON:
    контент может измениться между версиями. Из снимка читаются только
    изменяемые величины, поэтому старый снимок без поля
    ``item_automata`` получает начальное состояние, а не пустой предмет.
    """
    if not isinstance(automaton, dict) or not isinstance(saved, Mapping):
        return automaton
    automaton["force"] = max(
        0.0,
        min(
            automaton["max_force"],
            _as_float(saved.get("force"), automaton["force"]),
        ),
    )
    automaton["energy"] = max(
        0.0,
        min(
            automaton["max_energy"],
            _as_float(saved.get("energy"), automaton["energy"]),
        ),
    )
    if isinstance(saved.get("state"), Mapping):
        for key, value in saved["state"].items():
            key = _text(key)
            if key:
                automaton["state"][key] = _as_float(
                    value, automaton["state"].get(key, 0.0)
                )
    if isinstance(saved.get("work"), (list, tuple)):
        automaton["work"] = [
            dict(entry)
            for entry in saved["work"]
            if isinstance(entry, Mapping)
        ][-ITEM_WORK_LIMIT:]
    return automaton


def resolve_item_handler(automaton, handler=""):
    """Вернуть имя и данные обработчика или пару ``(name, None)``."""
    if not automaton:
        return "", None
    name = _text(handler, automaton.get("default_handler", ""))
    return name, automaton.get("handlers", {}).get(name)


def item_handler_reason(automaton, handler=""):
    """Причина, по которой предмет не может запустить обработчик."""
    if not automaton:
        return "у предмета нет автомата"
    name, payload = resolve_item_handler(automaton, handler)
    if not name:
        return "у предмета нет обработчика"
    if payload is None:
        return "предмет не умеет это действие"
    if _as_float(automaton.get("force"), 0.0) <= 0.0:
        return "предмет сломан"
    if _as_float(automaton.get("energy"), 0.0) + 1e-9 < _as_float(
        payload.get("energy"), 0.0
    ):
        return "предмету не хватает запаса"
    return ""


def apply_item_handler(automaton, handler, day):
    """Списать цену обработчика, изменить состояние и записать работу.

    Возвращает ``(payload, reason)``. При ошибке автомат не меняется.
    """
    reason = item_handler_reason(automaton, handler)
    if reason:
        return None, reason
    name, payload = resolve_item_handler(automaton, handler)
    energy = max(0.0, _as_float(payload.get("energy"), 0.0))
    force = max(0.0, _as_float(payload.get("force"), 0.0))
    automaton["energy"] = max(
        0.0, _as_float(automaton.get("energy"), 0.0) - energy
    )
    automaton["force"] = max(
        0.0, _as_float(automaton.get("force"), 0.0) - force
    )
    for key, delta in (payload.get("state") or {}).items():
        automaton["state"][key] = _as_float(
            automaton["state"].get(key), 0.0
        ) + _as_float(delta)
    automaton.setdefault("work", []).append(
        {
            "day": int(day),
            "handler": name,
            "energy": energy,
            "force": force,
            "state": dict(payload.get("state") or {}),
        }
    )
    automaton["work"] = automaton["work"][-ITEM_WORK_LIMIT:]
    return payload, ""
