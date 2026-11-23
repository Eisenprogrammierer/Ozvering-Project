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

import copy
import json
import pathlib
import sys
from collections.abc import Mapping
from typing import Iterable, List, Sequence

import bdi
import character_traits as CT
from . import content_schema
from core41.payload import (
    PAYLOAD_KINDS,
    PayloadError,
    normalize_payload_kinds,
)
from .actions import ActionError, FormCatalog, lint_action
from .geometry import GeometryError, MetricGraph
from .identity import (
    IDENTITY_SECTIONS,
    ArchetypeCatalog,
    IdentityError,
)
from .scenes import SceneError, SceneSpec
from .state_machine import StateMachineDefinition, StateMachineError

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_PATHS = (
    ROOT / "configs" / "characters" / "bdi.json",
    ROOT / "configs" / "characters" / "archetypes.json",
    ROOT / "configs" / "content" / "payload_kinds.json",
    ROOT / "configs" / "campaigns",
    ROOT / "configs" / "campaigns" / "base" / "lore_factions.json",
    ROOT / "configs" / "campaigns" / "base" / "automata_defaults.json",
    ROOT / "configs" / "campaigns" / "base" / "automata",
    ROOT / "configs" / "systems" / "events.json",
    ROOT / "configs" / "systems" / "playwright.json",
    ROOT / "configs" / "worlds" / "agora_world.json",
    ROOT / "configs" / "worlds" / "actions",
    ROOT / "configs" / "worlds" / "scenes",
    ROOT / "configs" / "storylines",
)

# Списки ключей не дублируются: их задаёт JSON Schema, которую исполняет
# ядро. Иначе новая схема и линтер расходятся.
EFFECT_KEYS = content_schema.schema_keys("effects")
REQUIRE_KEYS = content_schema.schema_keys("requires")
CONDITION_KINDS = content_schema.condition_kinds()
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
    problems: List[str] = content_schema.validate(
        "effects", effects, source
    )
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
        elif kind == "distance" and not (
            clause.get("from") and clause.get("to")
        ):
            problems.append(
                "%s: для distance нужны from и to" % where
            )
        elif kind == "angle" and not (
            clause.get("node") and clause.get("from") and clause.get("to")
        ):
            problems.append(
                "%s: для angle нужны node, from и to" % where
            )
        elif kind == "relation" and not (
            clause.get("target") or clause.get("key") or clause.get("id")
        ):
            problems.append(
                "%s: для relation нужна цель (target/key)" % where
            )
    return problems


def check_requires(source, requires):
    problems: List[str] = content_schema.validate(
        "requires", requires, source
    )
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


def _faction_organs(faction):
    """Органы фракции, включая вложенные в подфракции."""
    faction = _as_mapping(faction)
    organs = [item for item in _as_list(faction.get("organs")) if item]
    for sub in _as_list(faction.get("subfactions")):
        sub = _as_mapping(sub)
        for organ in _as_list(sub.get("organs")):
            if organ:
                organs.append(organ)
    return organs


def _organ_link_map(organs):
    """Карта соседства по сырым записям органов."""
    by_id = {}
    for organ in organs:
        organ = _as_mapping(organ)
        organ_id = str(organ.get("id") or "")
        if organ_id:
            by_id[organ_id] = organ
    links = {key: set() for key in by_id}
    for organ_id, organ in by_id.items():
        for linked in _as_list(organ.get("links")):
            linked = str(linked or "")
            if linked and linked != organ_id and linked in by_id:
                links[organ_id].add(linked)
                links[linked].add(organ_id)
        parent_id = str(organ.get("parent_id") or "")
        if parent_id and parent_id != organ_id and parent_id in by_id:
            links[organ_id].add(parent_id)
            links[parent_id].add(organ_id)
    return {key: sorted(value) for key, value in links.items()}


def check_geometry(source, geometry, node_ids, links=None):
    """Проверить блок семантической геометрии фракции."""
    if not isinstance(geometry, Mapping) or not geometry:
        return ["%s: геометрия должна быть непустым объектом" % source]
    try:
        MetricGraph.from_record(
            geometry,
            nodes=node_ids,
            links=links,
            source="declared",
        )
    except (GeometryError, ValueError, TypeError) as error:
        return ["%s: %s" % (source, error)]
    return []


def check_faction(side, faction, config, known_targets=None):
    problems: List[str] = []
    prefix = "factions.%s" % side
    faction = _as_mapping(faction)
    faction_id = str(faction.get("id") or "")
    if not faction_id:
        problems.append("%s: пустой id фракции" % prefix)

    organs = _faction_organs(faction)
    subfactions = [
        _as_mapping(item)
        for item in _as_list(faction.get("subfactions"))
        if item
    ]
    organ_ids = set()
    for index, organ in enumerate(organs):
        organ = _as_mapping(organ)
        problems.extend(
            content_schema.validate(
                "organ",
                organ,
                "%s.organs[%d]" % (prefix, index),
            )
        )
        organ_id = str(organ.get("id") or "")
        if not organ_id:
            problems.append("%s.organs[%d]: пустой id" % (prefix, index))
            continue
        if organ_id in organ_ids:
            problems.append(
                "%s.organs: повторяющийся id %r" % (prefix, organ_id)
            )
        organ_ids.add(organ_id)
    by_id = {
        str(_as_mapping(organ).get("id") or ""): _as_mapping(organ)
        for organ in organs
        if _as_mapping(organ).get("id")
    }
    for index, organ in enumerate(organs):
        organ = _as_mapping(organ)
        organ_id = str(organ.get("id") or index)
        for link in _as_list(organ.get("links")):
            if str(link) not in organ_ids:
                problems.append(
                    "%s.organs.%s: ссылка на неизвестный орган %r"
                    % (prefix, organ_id, link)
                )
        parent_id = str(organ.get("parent_id") or "")
        if not parent_id:
            continue
        if parent_id == organ_id:
            problems.append(
                "%s.organs.%s: орган не может быть родителем сам себе"
                % (prefix, organ_id)
            )
            continue
        if parent_id not in organ_ids:
            problems.append(
                "%s.organs.%s: неизвестный родитель %r"
                % (prefix, organ_id, parent_id)
            )
            continue
        seen = {organ_id}
        current = parent_id
        while current:
            if current in seen:
                problems.append(
                    "%s.organs.%s: цикл родителей через %r"
                    % (prefix, organ_id, current)
                )
                break
            seen.add(current)
            current = str(
                _as_mapping(by_id.get(current)).get("parent_id") or ""
            )

    sub_ids = set()
    for index, sub in enumerate(subfactions):
        sub_id = str(sub.get("id") or "")
        source = "%s.subfactions.%s" % (prefix, sub_id or index)
        problems.extend(
            content_schema.validate("subfaction", sub, source)
        )
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

    for index, organ in enumerate(organs):
        organ = _as_mapping(organ)
        organ_id = str(organ.get("id") or index)
        subfaction_id = str(organ.get("subfaction_id") or "")
        if subfaction_id and subfaction_id not in sub_ids:
            problems.append(
                "%s.organs.%s: неизвестная подфракция %r"
                % (prefix, organ_id, subfaction_id)
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
        problems.extend(
            content_schema.validate("work", action, source)
        )
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
        hints = _as_mapping(action.get("hints"))
        for key in ("essence", "intention_essence"):
            hint = str(hints.get(key) or "")
            if hint and hint not in config.essences:
                problems.append(
                    "%s.hints.%s: неизвестная суть намерения %r"
                    % (source, key, hint)
                )
        target = str(action.get("target") or "")
        if (
            target
            and known_targets is not None
            and target not in known_targets
        ):
            problems.append(
                "%s.target: неизвестная цель %r" % (source, target)
            )
        hint_target = str(hints.get("intention_target") or "")
        if (
            hint_target
            and known_targets is not None
            and hint_target not in known_targets
        ):
            problems.append(
                "%s.hints.intention_target: неизвестная цель %r"
                % (source, hint_target)
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

    # История работ ссылается на уже выполненные id. Проверяем после
    # сбора всех работ, иначе ссылка вперёд выглядела бы неизвестной.
    for index, action in enumerate(actions):
        action = _as_mapping(action)
        source = "%s.actions.%s" % (
            prefix, str(action.get("id") or index)
        )
        requires = _as_mapping(action.get("requires"))
        for key in ("used_actions", "not_used_actions"):
            for reference in _as_list(requires.get(key)):
                reference = str(reference or "")
                if reference and reference not in action_ids:
                    problems.append(
                        "%s.requires.%s: неизвестная работа %r"
                        % (source, key, reference)
                    )

    for index, order in enumerate(_as_list(faction.get("orders"))):
        order = _as_mapping(order)
        order_id = str(order.get("id") or index)
        problems.extend(
            _order_problems(
                "%s.orders.%s" % (prefix, order_id), order
            )
        )
    if faction.get("order_model"):
        problems.extend(
            _order_model_problems(
                faction.get("order_model"), prefix + ".order_model"
            )
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

    if faction.get("geometry"):
        problems.extend(
            check_geometry(
                prefix + ".geometry",
                faction.get("geometry"),
                sorted(organ_ids),
                _organ_link_map(organs),
            )
        )
    return problems


def check_events(source, events):
    """Событие не производит состояние и не имеет эффектов."""
    problems: List[str] = []
    categories = set()
    if isinstance(events, Mapping):
        categories = set(_as_mapping(events.get("categories")))
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
        problems.extend(
            content_schema.validate("event_item", event, where)
        )
        for key in event:
            if key in ("effects", "emit", "apply"):
                problems.append(
                    "%s.%s: событие не может менять состояние" % (where, key)
                )
            elif key not in EVENT_KEYS:
                problems.append(
                    "%s: неизвестное поле события %r" % (where, key)
                )
        category = str(event.get("category") or "")
        if category and categories and category not in categories:
            problems.append(
                "%s: неизвестная категория события %r"
                % (where, category)
            )
    return problems


_CHARACTER_SIMPLE_METRICS = {"morale", "force", "energy", "alive"}


def _metric_problem(
    metric, defaults, config=None, traits=None, subfaction_ids=None
):
    """Проверить, что формула ссылается на исполняемую метрику.

    Проверка структурная: читаются те же префиксы, что и в
    ``campaign/faction_state.py::faction_metric``. Значения вроде
    ``need.*`` сверяются с BDI, ``trait.*`` — с каталогом черт,
    ``organs.kind:*`` — с данными ``organ_kinds``.
    """
    metric = str(metric or "").strip()
    if not metric:
        return "пустая метрика"
    try:
        float(metric)
        return ""
    except (TypeError, ValueError):
        pass
    if metric in ("organs.mean", "network.density", "network.degree"):
        return ""
    for prefix in (
        "characters.mean:",
        "characters.max:",
        "characters.min:",
    ):
        if not metric.startswith(prefix):
            continue
        key = metric[len(prefix) :]
        if not key:
            return "пустая метрика персонажа в %r" % metric
        if key in _CHARACTER_SIMPLE_METRICS:
            return ""
        head, separator, name = key.partition(".")
        if not separator or not name:
            return "неизвестная метрика персонажа %r" % key
        needs = set(getattr(config, "needs", {}) or {})
        conditions = set(getattr(config, "conditions", {}) or {})
        if head in ("need", "satisfaction") and name in needs:
            return ""
        if head == "condition" and (
            name in conditions or name in ("sickness", "wound")
        ):
            return ""
        if head == "trait" and (not traits or name in traits):
            return ""
        if head == "division":
            return ""
        return "неизвестная метрика персонажа %r" % key
    if metric.startswith("organs.kind:"):
        kind = metric[len("organs.kind:") :]
        kinds = _as_mapping(_as_mapping(defaults).get("organ_kinds"))
        if not kind:
            return "пустой вид органа в %r" % metric
        if kinds and kind not in kinds:
            return "неизвестный вид органа %r" % kind
        return ""
    if metric.startswith("organization."):
        key = metric[len("organization.") :]
        return "" if key else "пустая метрика организации"
    if metric.startswith(
        ("subfactions.mean:", "subfactions.max:", "subfactions.min:")
    ):
        key = metric.rsplit(":", 1)[-1]
        return "" if key else "пустой актив подфракции"
    if metric.startswith("subfactions."):
        rest = metric[len("subfactions.") :]
        sub_id, separator, asset = rest.partition(".")
        if not separator or not sub_id or not asset:
            return "неизвестная метрика подфракции %r" % rest
        if subfaction_ids is not None and sub_id not in subfaction_ids:
            return "неизвестная подфракция %r" % sub_id
        return ""
    if metric.startswith("context."):
        key = metric[len("context.") :]
        return "" if key else "пустая контекстная метрика"
    return "неизвестная метрика %r" % metric


def _formula_problems(
    source,
    formula,
    defaults,
    config=None,
    traits=None,
    subfaction_ids=None,
):
    problems: List[str] = []
    if not isinstance(formula, list) or not formula:
        return ["%s: формула должна быть непустым списком" % source]
    for index, term in enumerate(formula):
        where = "%s[%d]" % (source, index)
        if not isinstance(term, Mapping):
            problems.append("%s: термин должен быть объектом" % where)
            continue
        extra = set(term) - {"metric", "weight"}
        if extra:
            problems.append(
                "%s: неизвестные поля %s"
                % (where, ", ".join(sorted(extra)))
            )
        try:
            float(term.get("weight"))
        except (TypeError, ValueError):
            problems.append("%s: вес должен быть числом" % where)
        problem = _metric_problem(
            term.get("metric"),
            defaults,
            config=config,
            traits=traits,
            subfaction_ids=subfaction_ids,
        )
        if problem:
            problems.append("%s: %s" % (where, problem))
    return problems


def _relation_model_problems(model):
    problems: List[str] = []
    model = _as_mapping(model)
    axes = model.get("axes")
    if isinstance(axes, Mapping):
        names = [str(key) for key in axes]
    elif isinstance(axes, (list, tuple)):
        names = [str(key) for key in axes]
    else:
        names = []
    if not names:
        problems.append("relation_model.axes: нужен непустой набор осей")
    for name in names:
        if not name.strip():
            problems.append("relation_model.axes: пустое имя оси")
    weights = _as_mapping(model.get("effect_weights"))
    for form, bucket in weights.items():
        if not isinstance(bucket, Mapping):
            problems.append(
                "relation_model.effect_weights.%s: нужен объект" % form
            )
            continue
        for axis, value in bucket.items():
            try:
                float(value)
            except (TypeError, ValueError):
                problems.append(
                    "relation_model.effect_weights.%s.%s: нужен число"
                    % (form, axis)
                )
    try:
        limit = float(model.get("effect_limit", 1.0))
    except (TypeError, ValueError):
        limit = 0.0
    if limit <= 0.0:
        problems.append("relation_model.effect_limit: нужен > 0")
    forms = _as_mapping(model.get("forms"))
    for form, target in forms.items():
        if not str(target or "").strip():
            problems.append(
                "relation_model.forms.%s: пустая форма отношения" % form
            )
    return problems


def _order_problems(source, order):
    """Проверить один приказ: схему, эффекты, условия и числа."""
    problems: List[str] = content_schema.validate("order", order, source)
    order = _as_mapping(order)
    if not str(order.get("id") or "").strip():
        problems.append("%s: пустой id приказа" % source)
    if "effects" in order:
        problems.extend(
            check_effects(source + ".effects", order.get("effects"))
        )
    if "requires" in order:
        problems.extend(
            check_requires(source + ".requires", order.get("requires"))
        )
    if "when" in order:
        problems.extend(
            _condition_problems(source + ".when", order.get("when"))
        )
    relations = _as_mapping(order.get("relations"))
    axes = (
        _as_mapping(relations.get("axes"))
        if "axes" in relations
        else relations
    )
    for axis, value in axes.items():
        if str(axis) in ("source", "from"):
            continue
        try:
            float(value)
        except (TypeError, ValueError):
            problems.append(
                "%s.relations.%s: ожидалось число" % (source, axis)
            )
    for key, value in _as_mapping(order.get("cost")).items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            problems.append(
                "%s.cost.%s: ожидалось число" % (source, key)
            )
            continue
        if number < 0:
            problems.append(
                "%s.cost.%s: цена не может быть отрицательной"
                % (source, key)
            )
    recipient = order.get("recipient")
    if recipient is not None and not str(recipient or "").strip():
        problems.append("%s.recipient: пустой адресат" % source)
    return problems


def _order_model_problems(model, prefix="order_model"):
    """Проверить блок ``order_model`` и уникальность приказов."""
    problems: List[str] = []
    model = _as_mapping(model)
    orders = model.get("orders")
    if not isinstance(orders, (list, tuple)):
        problems.append("%s.orders: нужен список приказов" % prefix)
        orders = []
    seen = set()
    for index, order in enumerate(orders):
        order = _as_mapping(order)
        order_id = str(order.get("id") or "")
        source = "%s.orders.%s" % (prefix, order_id or index)
        if order_id and order_id in seen:
            problems.append(
                "%s: повторяющийся id приказа %r"
                % (prefix, order_id)
            )
        seen.add(order_id)
        problems.extend(_order_problems(source, order))
    for key in ("interval", "max_per_tick", "cooldown"):
        if key not in model:
            continue
        try:
            value = int(float(model.get(key)))
        except (TypeError, ValueError):
            problems.append("%s.%s: ожидалось целое число" % (prefix, key))
            continue
        minimum = 0 if key == "cooldown" else 1
        if value < minimum:
            problems.append(
                "%s.%s: нужно значение не меньше %d"
                % (prefix, key, minimum)
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

    try:
        config = bdi.load_bdi()
        traits = set(CT.load_traits().traits)
    except Exception:
        config = None
        traits = set()

    for asset, formula in assets.items():
        problems.extend(
            _formula_problems(
                "faction_state.assets.%s" % asset,
                formula,
                defaults,
                config=config,
                traits=traits,
            )
        )
    if isinstance(defaults.get("relation_model"), Mapping):
        problems.extend(
            _relation_model_problems(defaults.get("relation_model"))
        )
    if isinstance(defaults.get("order_model"), Mapping):
        problems.extend(
            _order_model_problems(defaults.get("order_model"))
        )

    for faction in faction_map.values():
        faction = _as_mapping(faction)
        local_labels = dict(labels)
        local_labels.update(_as_mapping(faction.get("asset_labels")))
        local_formulas = _as_mapping(faction.get("asset_formulas"))
        subfaction_ids = {
            str(_as_mapping(item).get("id") or "")
            for item in _as_list(faction.get("subfactions"))
            if _as_mapping(item).get("id")
        }
        for asset, formula in local_formulas.items():
            problems.extend(
                _formula_problems(
                    "%s.asset_formulas.%s"
                    % (faction.get("id") or "faction", asset),
                    formula,
                    defaults,
                    config=config,
                    traits=traits,
                    subfaction_ids=subfaction_ids,
                )
            )
        for asset in (
            list(_as_mapping(faction.get("assets")))
            + list(_as_mapping(faction.get("score_assets")))
            + list(local_formulas)
        ):
            if asset not in local_labels:
                problems.append(
                    "asset_labels: нет подписи для актива %r" % asset
                )
            if asset not in assets and asset not in local_formulas:
                problems.append(
                    "faction_state.assets: нет формулы для актива %r"
                    % asset
                )
    return problems


def lint_archetypes_data(data, config=None):
    """Проверить каталог архетипов и его ссылки на модели черт/потребностей.

    Архетип — данные, поэтому опечатка в ``needs`` или ``identity_sections``
    должна быть ошибкой линтера, а не тихо проигнорированной дельтой.
    """
    if not isinstance(data, Mapping) or "archetypes" not in data:
        return []
    try:
        catalog = ArchetypeCatalog(data)
    except IdentityError as error:
        return [str(error)]
    config = config or bdi.load_bdi()
    needs = set(config.needs)
    traits = set(CT.load_traits().traits)
    sections = set(IDENTITY_SECTIONS)
    problems: List[str] = []
    for item in catalog.all():
        for key in item.needs:
            if key not in needs:
                problems.append(
                    "archetype %s: неизвестная потребность %r"
                    % (item.id, key)
                )
        for key in item.priority_needs:
            if key not in needs:
                problems.append(
                    "archetype %s: неизвестная потребность %r"
                    % (item.id, key)
                )
        for key in item.traits:
            if key not in traits:
                problems.append(
                    "archetype %s: неизвестная черта %r"
                    % (item.id, key)
                )
        for section in item.identity_sections:
            if section not in sections:
                problems.append(
                    "archetype %s: неизвестный раздел личности %r"
                    % (item.id, section)
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
    known_targets = {"self", "rival", "strongest", "weakest"}

    def _register_target(value):
        value = str(value or "")
        if not value:
            return
        known_targets.add(value)
        known_targets.add(value.replace(".", "_"))
        known_targets.add(value.replace("_", "."))

    for side, faction in items:
        _register_target(side)
        _register_target(_as_mapping(faction).get("id"))
    geometries = _as_mapping(
        data.get("geometry") if isinstance(data, Mapping) else None
    )
    for side, faction in items:
        faction = _as_mapping(faction)
        faction_id = str(faction.get("id") or "")
        if faction_id in seen:
            problems.append(
                "factions: повторяющийся id фракции %r" % faction_id
            )
        seen.add(faction_id)
        problems.extend(
            check_faction(
                str(side),
                faction,
                config,
                known_targets=known_targets,
            )
        )
        if side in geometries and not faction.get("geometry"):
            organs = _faction_organs(faction)
            node_ids = sorted(
                {
                    str(_as_mapping(organ).get("id") or "")
                    for organ in organs
                }
                - {""}
            )
            problems.extend(
                check_geometry(
                    "factions.%s.geometry" % side,
                    geometries[side],
                    node_ids,
                    _organ_link_map(organs),
                )
            )
    if isinstance(data, Mapping) and "events" in data:
        problems.extend(check_events("events", data.get("events")))
    return problems


def check_automaton(data, source):
    """Проверить исполняемый автомат из ``configs/automata``."""
    problems: List[str] = content_schema.validate(
        "automaton", data, source
    )
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


def _relative_data_path(path, value):
    target = pathlib.Path(str(value))
    if not target.is_absolute():
        target = pathlib.Path(path).parent / target
    return target


def lint_campaign_template_data(path, data):
    """Проверить ссылки шаблона кампании на фракции и события.

    Загрузчик проверяет стороны при генерации, но ошибка в JSON должна
    находиться линтером до запуска. Категории событий сверяются с
    каталогом ``configs/systems/events.json``.
    """
    if not isinstance(data, Mapping):
        return ["шаблон кампании должен быть объектом"]
    problems: List[str] = []
    factions = _as_mapping(data.get("factions"))
    factions_path = str(data.get("factions_path") or "")
    if factions_path:
        target = _relative_data_path(path, factions_path)
        if not target.is_file():
            problems.append(
                "factions_path: файл не найден: %s" % factions_path
            )
        else:
            try:
                base = _load(target)
            except (OSError, ValueError) as error:
                problems.append("factions_path: %s" % error)
            else:
                factions = _as_mapping(_as_mapping(base).get("factions"))
    elif not factions:
        problems.append("нужен factions_path или inline factions")

    slots = _as_mapping(data.get("faction_slots"))
    player = str(
        slots.get("player", data.get("player_side")) or ""
    )
    enemy = str(slots.get("enemy", data.get("enemy_side")) or "")
    if factions:
        if player and player not in factions:
            problems.append("нет фракции player_side=%r" % player)
        if enemy and enemy not in factions:
            problems.append("нет фракции enemy_side=%r" % enemy)
        if player and player == enemy:
            problems.append("player_side и enemy_side совпадают")
        scenario = _as_mapping(data.get("scenario"))
        for side, rival in _as_mapping(scenario.get("rivals")).items():
            if str(side) not in factions:
                problems.append(
                    "scenario.rivals: неизвестная фракция %r" % side
                )
            if str(rival) not in factions:
                problems.append(
                    "scenario.rivals.%s: неизвестная фракция %r"
                    % (side, rival)
                )

    categories = _as_list(_as_mapping(data.get("events")).get("categories"))
    if categories:
        from systems.events import EventCatalog, EventError

        try:
            catalog = EventCatalog.load()
        except (EventError, OSError, ValueError) as error:
            problems.append("events: %s" % error)
        else:
            for category in categories:
                if str(category) not in catalog.categories:
                    problems.append(
                        "events.categories: неизвестная категория %r"
                        % category
                    )
    return problems


def lint_playwright_data(path, data):
    """Проверить, что шаблоны драматурга ссылаются на известные события."""
    if not isinstance(data, Mapping):
        return ["playwright.json должен быть объектом"]
    templates = _as_list(data.get("templates"))
    if not templates:
        return []
    from systems.events import EventCatalog, EventError

    try:
        catalog = EventCatalog.load()
    except (EventError, OSError, ValueError) as error:
        return ["events: %s" % error]
    problems: List[str] = []
    for index, template in enumerate(templates):
        template = _as_mapping(template)
        event_id = str(template.get("event_id") or "")
        if event_id and event_id not in catalog.events:
            problems.append(
                "templates[%d].event_id: неизвестное событие %r"
                % (index, event_id)
            )
    return problems


def _problems_for(path, data, config, factions_data=None, forms=None):
    path = pathlib.Path(path)
    problems: List[str] = []
    if isinstance(data, Mapping) and "needs" in data:
        problems.extend(check_bdi(config))
    if isinstance(data, Mapping) and "belief_predicates" in data:
        problems.extend(
            content_schema.validate("bdi", data, str(path))
        )
    if path.name == "payload_kinds.json":
        problems.extend(lint_payload_kinds_data(data))
    if isinstance(data, Mapping) and "forms" in data:
        problems.extend(lint_forms_data(data))
    is_world = _looks_like_world(data)
    if (
        not is_world
        and isinstance(data, Mapping)
        and "factions" in data
        and "template_id" not in data
    ):
        problems.extend(
            content_schema.validate(
                "lore_factions", data, str(path)
            )
        )
    if is_world:
        problems.extend(lint_world_data(data))
    elif (
        isinstance(data, Mapping) and "actions" in data
    ) or isinstance(data, (list, tuple)):
        problems.extend(lint_actions_data(data, forms=forms))
    if isinstance(data, Mapping) and "archetypes" in data:
        problems.extend(lint_archetypes_data(data, config))
    if isinstance(data, Mapping) and "storyline_id" in data:
        problems.extend(lint_storylines_data(path, data))
    looks_like_scene_file = (
        isinstance(data, Mapping)
        and "id" in data
        and ("public" in data or "works" in data)
        and "actions" not in data
    )
    has_scenes = isinstance(data, Mapping) and isinstance(
        data.get("scenes"), (list, tuple)
    )
    if has_scenes or looks_like_scene_file:
        problems.extend(lint_scenes_data(data))
    if isinstance(data, Mapping) and "factions" in data:
        problems.extend(lint_factions_data(data, config))
    if isinstance(data, Mapping) and "faction_state" in data:
        problems.extend(
            content_schema.validate(
                "automata_defaults", data, str(path)
            )
        )
        problems.extend(check_defaults(data, factions_data))
    if (
        isinstance(data, Mapping)
        and "template_id" in data
        and "scenario" in data
    ):
        problems.extend(
            content_schema.validate(
                "campaign_template", data, str(path)
            )
        )
        problems.extend(
            lint_campaign_template_data(path, data)
        )
    if (
        isinstance(data, Mapping)
        and "events" in data
        and "categories" in data
    ):
        problems.extend(
            content_schema.validate("event", data, str(path))
        )
        problems.extend(check_events(str(path), data))
    if (
        path.name == "playwright.json"
        and isinstance(data, Mapping)
        and "templates" in data
    ):
        problems.extend(lint_playwright_data(path, data))
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


def lint_payload_kinds_data(data):
    """Проверить реестр видов payload и его схему."""
    try:
        normalize_payload_kinds(data)
    except PayloadError as exc:
        return [str(exc)]
    return []


def lint_forms_data(data):
    """Проверить манифест форм и наличие обработчиков."""
    if not isinstance(data, Mapping):
        return ["манифест форм должен быть объектом"]
    entries = data.get("forms")
    if not isinstance(entries, list) or not entries:
        return ["forms должен быть непустым списком"]
    try:
        catalog = FormCatalog(entries, source="forms")
        catalog.check_handlers()
    except ActionError as exc:
        return [str(exc)]
    problems = []
    for form in catalog:
        if not form.payload_kinds:
            problems.append("%s: не задан payload_kinds" % form.id)
        if not form.target_kinds:
            problems.append("%s: не задан target_kinds" % form.id)
        unknown = [
            kind for kind in form.payload_kinds if kind not in PAYLOAD_KINDS
        ]
        if unknown:
            problems.append(
                "%s: неизвестные payload_kinds %s"
                % (form.id, ", ".join(sorted(unknown)))
            )
    return problems


def _looks_like_world(data):
    return (
        isinstance(data, Mapping)
        and "nodes" in data
        and "offices" in data
        and "actions" in data
        and "domains" in data
    )


def lint_world_data(data):
    """Проверить мир целиком: ссылки, сцены, каталоги, формы."""
    if not isinstance(data, Mapping):
        return ["мир должен быть объектом"]
    try:
        from .errors import CampaignError
        from .world import validate_world

        validate_world(copy.deepcopy(data))
    except CampaignError as exc:
        return [str(exc)]
    except (KeyError, TypeError, ValueError) as exc:
        return ["некорректный мир: %s" % exc]
    return []


def _storyline_path(value):
    path = pathlib.Path(str(value))
    if not path.is_absolute():
        path = ROOT / path
    return path


def lint_storylines_data(path, data):
    """Проверить основной сюжет: теги и ссылки на соседние данные."""
    if not isinstance(data, Mapping):
        return ["сюжет должен быть объектом"]
    if not any(
        key in data
        for key in ("storyline_id", "world_path", "campaign_template")
    ):
        return []
    path = pathlib.Path(path)
    problems = []
    storyline_id = str(data.get("storyline_id") or "")
    if storyline_id and storyline_id != path.stem:
        problems.append(
            "storyline_id %r не совпадает с именем файла %r"
            % (storyline_id, path.stem)
        )
    tags = data.get("storyline_tags")
    if tags is not None:
        if not isinstance(tags, (list, tuple)):
            problems.append("storyline_tags должен быть списком")
        else:
            cleaned = [str(tag) for tag in tags if str(tag)]
            if len(cleaned) != len(tags):
                problems.append(
                    "storyline_tags не может содержать пустые теги"
                )
            if len(set(cleaned)) != len(cleaned):
                problems.append("storyline_tags повторяются")
    for key in ("world_path", "campaign_template"):
        value = data.get(key)
        if value and not _storyline_path(value).is_file():
            problems.append("%s: файл не найден: %s" % (key, value))
    for key in ("character_creation", "scenes"):
        value = data.get(key)
        if not value:
            continue
        target = path.parent / ("%s.json" % value)
        if not target.is_file():
            problems.append("%s: файл не найден: %s" % (key, target.name))
    free_start = data.get("free_start")
    if isinstance(free_start, Mapping) and free_start:
        from .identity import load_archetypes_catalog

        catalog = load_archetypes_catalog()
        if catalog is not None:
            unknown = [
                str(archetype_id)
                for archetype_id in free_start
                if catalog.get(str(archetype_id)) is None
            ]
            if unknown:
                problems.append(
                    "free_start: неизвестные архетипы %s"
                    % ", ".join(sorted(unknown))
                )
    return problems


def lint_scenes_data(data):
    """Проверить каталог сцен без привязки к узлам и работам мира.

    Ссылки на локации и работы проверяет ``validate_world``: вне мира у
    сцены нет способа отличить опечатку от ссылки на другой мир.
    """
    if isinstance(data, Mapping):
        entries = data.get("scenes")
        if entries is None and "id" in data:
            entries = [data]
        if entries is None:
            return []
    elif isinstance(data, (list, tuple)):
        entries = data
    else:
        return ["каталог сцен должен быть объектом или списком"]
    if not isinstance(entries, (list, tuple)):
        return ["scenes должен быть списком"]
    problems = []
    seen = set()
    public_ids = set()
    for index, raw in enumerate(entries):
        if not isinstance(raw, Mapping):
            problems.append("сцена[%d] должна быть объектом" % index)
            continue
        try:
            scene = SceneSpec.from_dict(raw)
        except SceneError as exc:
            problems.append(str(exc))
            continue
        if scene.id in seen:
            problems.append("%s: сцена объявлена дважды" % scene.id)
        seen.add(scene.id)
        if not scene.works:
            problems.append("%s: не заданы работы сцены" % scene.id)
        works = [item for item in scene.works if item]
        if len(set(works)) != len(works):
            problems.append("%s: работы сцены повторяются" % scene.id)
        for person in scene.public:
            if person.id in public_ids:
                problems.append(
                    "%s: публика %r объявлена в нескольких сценах"
                    % (scene.id, person.id)
                )
            public_ids.add(person.id)
        slots = scene.time.get("slots")
        if slots is not None:
            try:
                if int(slots) < 1:
                    problems.append(
                        "%s: time.slots должен быть не меньше 1" % scene.id
                    )
            except (TypeError, ValueError):
                problems.append("%s: time.slots должен быть числом" % scene.id)
    return problems


def lint_actions_data(data, forms=None):
    """Проверить каталог действий по манифесту форм."""
    if isinstance(data, Mapping):
        entries = data.get("actions") or ()
    elif isinstance(data, (list, tuple)):
        entries = data
    else:
        return ["каталог действий должен быть объектом или списком"]
    problems = []
    seen = set()
    for action in entries:
        if not isinstance(action, Mapping):
            problems.append("действие должно быть объектом")
            continue
        action_id = str(action.get("id") or "")
        if action_id in seen:
            problems.append("%s: действие объявлено дважды" % action_id)
        seen.add(action_id)
        problems.extend(lint_action(action, forms=forms, require_form=True))
    return problems


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
    forms_data = next(
        (
            data
            for _path, data in loaded
            if isinstance(data, Mapping) and "forms" in data
        ),
        None,
    )
    forms = None
    if isinstance(forms_data, Mapping):
        try:
            forms = FormCatalog(forms_data.get("forms") or ())
        except ActionError:
            forms = None
    for path, data in loaded:
        problems.extend(
            _problems_for(path, data, config, factions_data, forms)
        )
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
