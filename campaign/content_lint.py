"""Проверка контента до запуска кампании.

Задача модуля — сделать ошибки данных громкими. Сейчас загрузчики молча
пропускают неизвестные ключи: опечатка в эффекте работы превращается в
«ничего не произошло». Линтер читает JSON, сверяет ссылки и печатает
``файл: сообщение``.

Запуск::

    python -m campaign.content_lint
    python -m campaign.content_lint configs/campaigns/base/lore_factions.json

Проверяется только то, что ядро действительно исполняет. Если контент
использует ещё не реализованный эффект (например, ``beliefs`` в работе),
линтер сообщает об этом — это и есть граница Data-Driven ядра.
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections.abc import Mapping
from typing import Iterable, List, Sequence

import bdi
from .state_machine import StateMachineDefinition, StateMachineError

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_PATHS = (
    ROOT / "configs" / "characters" / "bdi.json",
    ROOT / "configs" / "campaigns" / "base" / "lore_factions.json",
    ROOT / "configs" / "campaigns" / "base" / "automata_defaults.json",
    ROOT / "configs" / "campaigns" / "base" / "automata",
)

# Ключи, которые применяет `campaign/effects.py`.
EFFECT_KEYS = {
    "self",
    "target",
    "assets",
    "needs",
    "traits",
    "conditions",
    "beliefs",
    "intentions",
    "organs",
    "subfactions",
    "flags",
    "text",
}
# Ключи, которые понимает `_asset_requirement_reason` и `action_options`.
REQUIRE_KEYS = {
    "min_turn",
    "used_actions",
    "not_used_actions",
    "self",
    "target",
    "when",
}
CONDITION_KINDS = {
    "asset",
    "need",
    "desire",
    "trait",
    "condition",
    "sickness",
    "wound",
    "belief",
    "intention",
    "organ",
    "subfaction",
    "flag",
    "context",
    "turn",
    "used_action",
    "not_used_action",
}
# Поля события кампании. Событие — ролевой слой: оно только отражает
# состояние и не имеет права ничего производить.
EVENT_KEYS = {
    "id",
    "title",
    "text",
    "templates",
    "template",
    "category",
    "weight",
    "probability",
    "chance",
    "speed",
    "duration",
    "cooldown",
    "conditions",
    "visibility",
    "tags",
    "context",
    "severity",
    "stakes",
}


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _load(path):
    with pathlib.Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def _belief_parts(item):
    if isinstance(item, Mapping):
        return (
            str(item.get("subject") or ""),
            str(item.get("predicate") or ""),
            str(item.get("object") or ""),
        )
    if isinstance(item, (list, tuple)) and len(item) == 3:
        return tuple(str(part or "") for part in item)
    return ("", "", "")


def _intention_parts(item):
    if isinstance(item, Mapping):
        return (
            str(item.get("target") or ""),
            str(item.get("essence") or ""),
        )
    if isinstance(item, (list, tuple)) and len(item) == 2:
        return tuple(str(part or "") for part in item)
    return ("", "")


def check_bdi(config):
    """Проверить ``configs/characters/bdi.json``."""
    problems: List[str] = []
    if tuple(config.needs) != bdi.NEEDS:
        problems.append(
            "needs: набор должен совпадать с bdi.NEEDS (%d позиций)"
            % len(bdi.NEEDS)
        )
    for key, definition in config.predicates.items():
        definition = _as_mapping(definition)
        kind = str(definition.get("kind") or "")
        if kind not in ("relation", "property"):
            problems.append(
                "belief_predicates.%s: kind должен быть relation/property"
                % key
            )
        rule = definition.get("object")
        if rule is not None and str(rule) not in ("required", "forbidden"):
            problems.append(
                "belief_predicates.%s.object: ожидалось "
                "required/forbidden" % key
            )
    for key, essence in config.essences.items():
        need = str(_as_mapping(essence).get("need") or "")
        if need not in config.needs:
            problems.append(
                "intention_essences.%s: неизвестная потребность %r"
                % (key, need)
            )
    return problems


def check_beliefs(source, items, config):
    problems: List[str] = []
    for index, item in enumerate(_as_list(items)):
        subject, predicate, obj = _belief_parts(item)
        where = "%s.beliefs[%d]" % (source, index)
        if not subject or not predicate:
            problems.append(
                "%s: убеждение требует subject и predicate" % where
            )
            continue
        if predicate not in config.predicates:
            problems.append(
                "%s: неизвестный предикат %r" % (where, predicate)
            )
            continue
        rule = config.predicate_object_rule(predicate)
        if rule == "required" and not obj:
            problems.append(
                "%s: предикат %r требует object" % (where, predicate)
            )
        elif rule == "forbidden" and obj:
            problems.append(
                "%s: предикат-свойство %r не имеет object"
                % (where, predicate)
            )
    return problems


def check_intentions(source, items, config):
    problems: List[str] = []
    for index, item in enumerate(_as_list(items)):
        target, essence = _intention_parts(item)
        where = "%s.intentions[%d]" % (source, index)
        if not target or not essence:
            problems.append(
                "%s: намерение должно быть дуплетом target/essence" % where
            )
            continue
        if essence not in config.essences:
            problems.append("%s: неизвестная суть %r" % (where, essence))
    return problems


def check_effects(source, effects):
    problems: List[str] = []
    effects = _as_mapping(effects)
    for key, value in effects.items():
        where = "%s.%s" % (source, key)
        if key not in EFFECT_KEYS:
            problems.append(
                "%s: эффект %r не поддерживается ядром" % (where, key)
            )
        elif key in (
            "self",
            "target",
            "assets",
            "needs",
            "traits",
            "conditions",
            "organs",
            "subfactions",
            "flags",
        ):
            if not isinstance(value, Mapping):
                problems.append("%s: ожидался объект" % where)
    return problems


def _condition_problems(source, conditions):
    problems: List[str] = []
    if isinstance(conditions, Mapping):
        if any(key in conditions for key in ("all", "any", "not")):
            items = [conditions]
        else:
            items = [conditions]
    elif isinstance(conditions, (list, tuple)):
        items = list(conditions)
    else:
        return ["%s: условие должно быть объектом или списком" % source]
    for index, clause in enumerate(items):
        where = "%s[%d]" % (source, index)
        clause = _as_mapping(clause)
        if not clause:
            problems.append("%s: пустое условие" % where)
            continue
        for group in ("all", "any"):
            if group in clause:
                problems.extend(
                    _condition_problems(
                        "%s.%s" % (where, group), clause.get(group)
                    )
                )
        if "not" in clause:
            problems.extend(
                _condition_problems(where + ".not", clause.get("not"))
            )
        if any(key in clause for key in ("all", "any", "not")):
            continue
        kind = str(clause.get("kind") or "asset")
        if kind not in CONDITION_KINDS:
            problems.append(
                "%s: неизвестный вид условия %r" % (where, kind)
            )
    return problems


def check_requires(source, requires):
    problems: List[str] = []
    requires = _as_mapping(requires)
    for key in requires:
        if key not in REQUIRE_KEYS:
            problems.append(
                "%s: условие %r не поддерживается ядром" % (source, key)
            )
    if "when" in requires:
        problems.extend(
            _condition_problems(
                source + ".when", requires.get("when")
            )
        )
    return problems


def check_faction(side, faction, config):
    problems: List[str] = []
    prefix = "factions.%s" % side
    faction = _as_mapping(faction)
    faction_id = str(faction.get("id") or "")
    if not faction_id:
        problems.append("%s: пустой id фракции" % prefix)

    organs = [item for item in _as_list(faction.get("organs")) if item]
    subfactions = [
        _as_mapping(item)
        for item in _as_list(faction.get("subfactions"))
        if item
    ]
    for sub in subfactions:
        for organ in _as_list(sub.get("organs")):
            if organ:
                organs.append(organ)
    organ_ids = set()
    for index, organ in enumerate(organs):
        organ = _as_mapping(organ)
        organ_id = str(organ.get("id") or "")
        if not organ_id:
            problems.append("%s.organs[%d]: пустой id" % (prefix, index))
            continue
        if organ_id in organ_ids:
            problems.append(
                "%s.organs: повторяющийся id %r" % (prefix, organ_id)
            )
        organ_ids.add(organ_id)
    for index, organ in enumerate(organs):
        organ = _as_mapping(organ)
        organ_id = str(organ.get("id") or index)
        for link in _as_list(organ.get("links")):
            if str(link) not in organ_ids:
                problems.append(
                    "%s.organs.%s: ссылка на неизвестный орган %r"
                    % (prefix, organ_id, link)
                )

    sub_ids = set()
    for index, sub in enumerate(subfactions):
        sub_id = str(sub.get("id") or "")
        source = "%s.subfactions.%s" % (prefix, sub_id or index)
        if not sub_id:
            problems.append("%s: пустой id" % source)
        elif sub_id in sub_ids:
            problems.append(
                "%s: повторяющийся id подфракции %r"
                % (prefix, sub_id)
            )
        sub_ids.add(sub_id)
        share = sub.get("share")
        if share is not None:
            try:
                number = float(share)
            except (TypeError, ValueError):
                problems.append("%s.share: ожидалось число" % source)
            else:
                if not 0.0 <= number <= 1.0:
                    problems.append(
                        "%s.share: вне диапазона 0..1" % source
                    )
        assets = sub.get("assets")
        if assets is not None and not isinstance(assets, Mapping):
            problems.append("%s.assets: ожидался объект" % source)
        for organ in _as_list(sub.get("organs")):
            organ_id = (
                str(_as_mapping(organ).get("id") or "")
                if isinstance(organ, Mapping)
                else str(organ or "")
            )
            if organ_id and organ_id not in organ_ids:
                problems.append(
                    "%s: ссылка на неизвестный орган %r"
                    % (source, organ_id)
                )
        for organ_id in _as_list(sub.get("organ_ids")):
            if str(organ_id) not in organ_ids:
                problems.append(
                    "%s: ссылка на неизвестный орган %r"
                    % (source, organ_id)
                )

    actions = [item for item in _as_list(faction.get("actions")) if item]
    action_ids = set()
    for index, action in enumerate(actions):
        action = _as_mapping(action)
        action_id = str(action.get("id") or "")
        source = "%s.actions.%s" % (prefix, action_id or index)
        if not action_id:
            problems.append("%s: пустой id работы" % source)
        elif action_id in action_ids:
            problems.append(
                "%s: повторяющийся id работы %r" % (prefix, action_id)
            )
        action_ids.add(action_id)
        organ_id = str(action.get("organ_id") or "")
        if organ_id and organ_id not in organ_ids:
            problems.append(
                "%s: неизвестный орган %r" % (source, organ_id)
            )
        essence = str(action.get("essence") or "")
        if essence and essence not in config.essences:
            problems.append(
                "%s: неизвестная суть намерения %r" % (source, essence)
            )
        intention = _as_mapping(action.get("intention"))
        if intention:
            problems.extend(
                check_intentions(
                    source + ".intention",
                    [intention],
                    config,
                )
            )
        problems.extend(
            check_effects(source + ".effects", action.get("effects"))
        )
        failure = _as_mapping(action.get("failure"))
        if failure:
            problems.extend(
                check_effects(source + ".failure", failure)
            )
        problems.extend(
            check_requires(source + ".requires", action.get("requires"))
        )

    defaults = _as_mapping(faction.get("character_defaults"))
    problems.extend(
        check_beliefs(
            prefix + ".character_defaults",
            defaults.get("beliefs"),
            config,
        )
    )
    problems.extend(
        check_intentions(
            prefix + ".character_defaults",
            defaults.get("intentions"),
            config,
        )
    )

    for index, post in enumerate(_as_list(faction.get("posts"))):
        post = _as_mapping(post)
        post_id = str(post.get("id") or index)
        source = "%s.posts.%s" % (prefix, post_id)
        organ_id = str(post.get("organ_id") or "")
        if organ_id and organ_id not in organ_ids:
            problems.append(
                "%s: неизвестный орган %r" % (source, organ_id)
            )
        problems.extend(
            check_beliefs(source, post.get("beliefs"), config)
        )
        problems.extend(
            check_intentions(source, post.get("intentions"), config)
        )
    return problems


def check_events(source, events):
    """Событие не производит состояние и не имеет эффектов."""
    problems: List[str] = []
    if isinstance(events, Mapping):
        items = _as_list(events.get("events"))
        for key in events:
            if key in ("effects", "emit"):
                problems.append(
                    "%s.%s: событие не может менять состояние" % (source, key)
                )
        events = items
    for index, event in enumerate(_as_list(events)):
        event = _as_mapping(event)
        event_id = str(event.get("id") or index)
        where = "%s.%s" % (source, event_id)
        for key in event:
            if key in ("effects", "emit", "apply"):
                problems.append(
                    "%s.%s: событие не может менять состояние" % (where, key)
                )
            elif key not in EVENT_KEYS:
                problems.append(
                    "%s: неизвестное поле события %r" % (where, key)
                )
    return problems


def check_defaults(defaults, factions=None):
    """Проверить ``automata_defaults.json``: подписи и формулы активов."""
    problems: List[str] = []
    defaults = _as_mapping(defaults)
    labels = _as_mapping(defaults.get("asset_labels"))
    state = _as_mapping(defaults.get("faction_state"))
    assets = _as_mapping(state.get("assets"))
    faction_map = {}
    if isinstance(factions, Mapping):
        faction_map = _as_mapping(factions.get("factions")) or factions
    for faction in faction_map.values():
        faction = _as_mapping(faction)
        for asset in list(_as_mapping(faction.get("assets"))) + list(
            _as_mapping(faction.get("score_assets"))
        ):
            if asset not in labels:
                problems.append(
                    "asset_labels: нет подписи для актива %r" % asset
                )
            if asset not in assets:
                problems.append(
                    "faction_state.assets: нет формулы для актива %r"
                    % asset
                )
    return problems


def lint_factions_data(data, config):
    problems: List[str] = []
    factions = data.get("factions") if isinstance(data, Mapping) else data
    if isinstance(factions, Mapping):
        items = list(factions.items())
    elif isinstance(factions, Sequence) and not isinstance(factions, str):
        items = [
            (str(_as_mapping(item).get("id") or index), item)
            for index, item in enumerate(factions)
        ]
    else:
        return ["factions: ожидался объект или список"]
    seen = set()
    for side, faction in items:
        faction = _as_mapping(faction)
        faction_id = str(faction.get("id") or "")
        if faction_id in seen:
            problems.append(
                "factions: повторяющийся id фракции %r" % faction_id
            )
        seen.add(faction_id)
        problems.extend(check_faction(str(side), faction, config))
    if isinstance(data, Mapping) and "events" in data:
        problems.extend(check_events("events", data.get("events")))
    return problems


def check_automaton(data, source):
    """Проверить исполняемый автомат из ``configs/automata``."""
    problems: List[str] = []
    data = _as_mapping(data)
    schema = data.get("schema")
    if schema is not None:
        try:
            schema_number = int(schema)
        except (TypeError, ValueError):
            problems.append(
                "%s: схема %r, ожидалась 2" % (source, schema)
            )
        else:
            if schema_number != 2:
                problems.append(
                    "%s: схема %r, ожидалась 2" % (source, schema)
                )
    try:
        definition = StateMachineDefinition.from_data(data, source)
    except (StateMachineError, ValueError) as error:
        return problems + [str(error)]
    for state in definition.states.values():
        for key in ("on_enter", "on_tick", "outputs"):
            for index, effect in enumerate(getattr(state, key)):
                problems.extend(
                    check_effects(
                        "%s.state.%s.%s[%d]"
                        % (source, state.id, key, index),
                        effect,
                    )
                )
        for index, transition in enumerate(state.transitions):
            if transition.when is None:
                continue
            problems.extend(
                _condition_problems(
                    "%s.state.%s.transitions[%d].when"
                    % (source, state.id, index),
                    transition.when,
                )
            )
    for name, payload in definition.handlers.items():
        payload = _as_mapping(payload)
        if payload.get("when") is not None:
            problems.extend(
                _condition_problems(
                    "%s.handlers.%s.when" % (source, name),
                    payload.get("when"),
                )
            )
        problems.extend(
            check_effects(
                "%s.handlers.%s.effects" % (source, name),
                payload.get("effects"),
            )
        )
    return problems


def _problems_for(path, data, config, factions_data=None):
    path = pathlib.Path(path)
    problems: List[str] = []
    if isinstance(data, Mapping) and "needs" in data:
        problems.extend(check_bdi(config))
    if isinstance(data, Mapping) and "factions" in data:
        problems.extend(lint_factions_data(data, config))
    if isinstance(data, Mapping) and "faction_state" in data:
        problems.extend(check_defaults(data, factions_data))
    if (
        isinstance(data, Mapping)
        and (
            data.get("schema") == 2
            or (
                data.get("kind") in ("faction", "organ", "subfaction")
                and "states" in data
            )
        )
    ):
        problems.extend(check_automaton(data, str(path)))
    return ["%s: %s" % (path, item) for item in problems]


def lint_path(path, config=None, factions_data=None):
    path = pathlib.Path(path)
    if path.is_dir():
        return lint([path], config=config)
    try:
        data = _load(path)
    except (OSError, ValueError) as error:
        return ["%s: %s" % (path, error)]
    if config is None:
        config = bdi.load_bdi()
    return _problems_for(path, data, config, factions_data)


def _expand(paths):
    """Развернуть каталоги в список JSON-файлов."""
    files = []
    for path in paths:
        path = pathlib.Path(path)
        if path.is_dir():
            files.extend(sorted(path.glob("*.json")))
        else:
            files.append(path)
    return files


def lint(paths: Iterable = DEFAULT_PATHS, config=None):
    config = config or bdi.load_bdi()
    loaded = []
    problems: List[str] = []
    for path in _expand(paths):
        path = pathlib.Path(path)
        try:
            loaded.append((path, _load(path)))
        except (OSError, ValueError) as error:
            problems.append("%s: %s" % (path, error))
    factions_data = next(
        (
            data
            for _path, data in loaded
            if isinstance(data, Mapping) and "factions" in data
        ),
        None,
    )
    for path, data in loaded:
        problems.extend(_problems_for(path, data, config, factions_data))
    return problems


def main(argv: Sequence[str] | None = None):
    argv = list(sys.argv[1:] if argv is None else argv)
    paths = [pathlib.Path(item) for item in argv] or list(DEFAULT_PATHS)
    files = _expand(paths)
    problems = lint(files)
    for item in problems:
        print(item)
    if problems:
        print("найдено проблем: %d" % len(problems), file=sys.stderr)
        return 1
    print("контент в порядке: %d файл(ов)" % len(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
