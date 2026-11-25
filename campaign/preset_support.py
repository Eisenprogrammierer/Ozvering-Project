# campaign/preset.py
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import random
from typing import Dict, List, Mapping

from automata.model import Automaton
from naming.people import PersonNameGenerator
from organizations.generator import (
    build_automaton as build_organization_automaton,
)
from organizations.model import (
    Member,
    OrganizationParameters,
    OrganizationSolver,
    Population,
)
from systems.environment import EnvironmentCatalog, EnvironmentRuntime
from systems.events import EventCatalog, EventTextGenerator
from systems.playwright import (
    DramaActor,
    Playwright,
    PlaywrightConfig,
)

from .avatar import avatar_from_preset
from .defaults import default_dict
from .divisions import load_divisions
from .errors import CampaignError
from .roles import RoleSpec, default_catalog as default_role_catalog
from .state_machine import StateMachineError, load_catalog

SCHEMA = 1

PRESET_DEFAULTS = default_dict("preset_defaults")
NEEDS_BASE = dict(PRESET_DEFAULTS["needs_base"])
NEEDS_PRIORITY = dict(PRESET_DEFAULTS["needs_priority"])
ORGANIZATION_RUNTIME_DEFAULTS = dict(
    PRESET_DEFAULTS["organization_runtime"]
)


class CampaignPresetError(CampaignError):
    pass


def _organization_parameters(data):
    """Параметры организации из JSON с проверкой типов и умолчаниями."""
    overrides = data if isinstance(data, Mapping) else {}
    defaults = OrganizationParameters()
    values = {}
    for name in OrganizationParameters.__dataclass_fields__:
        if name not in overrides:
            continue
        default = getattr(defaults, name)
        try:
            if isinstance(default, int) and not isinstance(default, bool):
                values[name] = max(1, int(float(overrides[name])))
            else:
                values[name] = float(overrides[name])
        except (TypeError, ValueError):
            continue
    try:
        return OrganizationParameters(**values)
    except (TypeError, ValueError):
        return defaults


_RED_SECTORS = ["front"] * 8 + ["left"] * 3 + ["right"] * 3 + ["rear"] * 2
_BLUE_SECTORS = ["front"] * 12 + ["left"] * 8 + ["right"] * 8 + ["rear"] * 4
_RED_POSITIONS = [
    (10, 3),
    (11, 5),
    (10, 7),
    (11, 9),
    (10, 11),
    (11, 13),
    (10, 15),
    (11, 17),
    (6, 2),
    (7, 4),
    (6, 6),
    (6, 18),
    (7, 20),
    (6, 22),
    (3, 10),
    (3, 14),
]
_BLUE_POSITIONS = (
    [(14 + (i % 2), 1 + i * 2) for i in range(12)]
    + [(18 + (i % 2), 1 + i) for i in range(8)]
    + [(18 + (i % 2), 16 + i) for i in range(8)]
    + [(21 + (i % 2), 6 + i * 4) for i in range(4)]
)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise CampaignPresetError("шаблон пресета не найден: %s" % path)
    except Exception as exc:
        raise CampaignPresetError("не удалось прочитать %s: %s" % (path, exc))


def _text(value, default=""):
    if value is None:
        return default
    return str(value)


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _stable_offset(token, modulo=100000):
    digest = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % max(1, int(modulo))


def _round_mapping(values, digits=4):
    return {
        str(key): round(_as_float(value, 0.0), digits)
        for key, value in (values or {}).items()
    }


def _ordered_sides(template):
    factions = template.get("factions") or {}
    if not isinstance(factions, Mapping) or not factions:
        raise CampaignPresetError(
            "template.factions должен быть непустым объектом"
        )
    known = ("red", "blue")
    result = [side for side in known if side in factions]
    result.extend(sorted(side for side in factions if side not in known))
    return result


def _layout_for(side, count):
    if side == "red" and count == len(_RED_SECTORS):
        return list(zip(_RED_SECTORS, _RED_POSITIONS))
    if side == "blue" and count == len(_BLUE_SECTORS):
        return list(zip(_BLUE_SECTORS, _BLUE_POSITIONS))

    count = max(0, int(count))
    if count == 0:
        return []
    front = max(1, count // 2)
    rest = count - front
    left = rest // 2
    right = rest - left
    sectors = ["front"] * front + ["left"] * left + ["right"] * right
    positions = []
    for index, sector in enumerate(sectors):
        column = index % 2
        if sector == "front":
            x = (10 if side == "red" else 14) + column
            y = 2 + (index * 3) % 21
        elif sector == "left":
            x = 6 if side == "red" else 18
            y = 2 + (index * 2) % 21
        else:
            x = 7 if side == "red" else 19
            y = 2 + (index * 2) % 21
        positions.append((x, y))
    return list(zip(sectors, positions))


def default_root():
    return Path(__file__).resolve().parents[1] / "configs" / "campaigns"


def default_template_path():
    root = default_root()
    preferred = root / "test_skirmish.json"
    if preferred.is_file():
        return preferred
    templates = list_templates(root)
    if templates:
        return Path(templates[0]["path"])
    return preferred


def load_template(path=None):
    path = Path(path) if path is not None else default_template_path()
    if path.is_dir():
        preferred = path / "test_skirmish.json"
        if preferred.is_file():
            path = preferred
        else:
            templates = list_templates(path)
            if not templates:
                raise CampaignPresetError(
                    "в %s нет JSON-шаблонов кампаний" % path
                )
            path = Path(templates[0]["path"])
    data = _read_json(path)
    if not isinstance(data, Mapping):
        raise CampaignPresetError("шаблон пресета должен быть объектом")
    data = dict(data)
    factions_path = _text(data.get("factions_path"))
    if factions_path:
        base_path = Path(factions_path)
        if not base_path.is_absolute():
            base_path = path.parent / base_path
        base = _read_json(base_path)
        if not isinstance(base, Mapping):
            raise CampaignPresetError(
                "factions_path должен указывать на объект"
            )
        merged = dict(base.get("factions") or {})
        shared_interactions = [
            dict(item)
            for item in (base.get("character_interactions") or ())
            if isinstance(item, Mapping) and item.get("id")
        ]
        shared_automaton_interactions = [
            dict(item)
            for item in (base.get("automaton_interactions") or ())
            if isinstance(item, Mapping) and item.get("id")
        ]
        shared_geometry = base.get("geometry") or {}
        merged.update(dict(data.get("factions") or {}))
        if shared_geometry:
            for side, cfg in merged.items():
                if isinstance(cfg, dict) and side in shared_geometry:
                    cfg.setdefault("geometry", shared_geometry[side])
        if shared_interactions:
            for cfg in merged.values():
                if isinstance(cfg, dict):
                    cfg.setdefault(
                        "character_interactions", shared_interactions
                    )
        if shared_automaton_interactions:
            for cfg in merged.values():
                if isinstance(cfg, dict):
                    cfg.setdefault(
                        "automaton_interactions",
                        shared_automaton_interactions,
                    )
        data["factions"] = merged
        data.setdefault("factions_source", str(base_path))
    return data


def list_templates(directory=None):
    """Найти JSON-шаблоны кампаний и вернуть их краткие описания."""
    root = Path(directory) if directory is not None else default_root()
    root = root.resolve()
    templates = []
    if not root.is_dir():
        return templates
    for path in sorted(root.glob("*.json")):
        try:
            data = _read_json(path)
        except CampaignPresetError:
            continue
        if not isinstance(data, Mapping):
            continue
        if not data.get("factions") and not data.get("factions_path"):
            continue
        templates.append(
            {
                "template_id": str(data.get("template_id") or path.stem),
                "title": str(data.get("title") or path.stem),
                "path": str(path),
            }
        )
    templates.sort(key=lambda item: (item["title"], item["template_id"]))
    return templates


def _validate_template(template):
    if not isinstance(template, Mapping):
        raise CampaignPresetError("template должен быть объектом")
    factions = template.get("factions")
    if not isinstance(factions, Mapping) or not factions:
        raise CampaignPresetError("template.factions должен быть объектом")
    slots = template.get("faction_slots") or {}
    player_side = _text(
        slots.get("player", template.get("player_side")), "red"
    )
    enemy_side = _text(slots.get("enemy", template.get("enemy_side")), "blue")
    if player_side not in factions:
        raise CampaignPresetError("нет фракции player_side=%r" % player_side)
    if enemy_side not in factions:
        raise CampaignPresetError("нет фракции enemy_side=%r" % enemy_side)
    if player_side == enemy_side:
        raise CampaignPresetError("player_side и enemy_side совпадают")
    scenario = template.get("scenario")
    if not isinstance(scenario, Mapping):
        raise CampaignPresetError("template.scenario должен быть объектом")
    mode = _text(scenario.get("mode"))
    automata_mode = mode == "automata"
    strategy_mode = mode == "strategy"
    if automata_mode:
        per_faction = _as_int(scenario.get("characters_per_faction"), 0)
        if per_faction < 0:
            raise CampaignPresetError(
                "scenario.characters_per_faction не может быть отрицательным"
            )
        for side, cfg in factions.items():
            population = _as_int(cfg.get("population"), per_faction)
            if population <= 0:
                raise CampaignPresetError(
                    "factions[%s].population должно быть > 0" % side
                )
    elif strategy_mode:
        groups = scenario.get("groups")
        if not isinstance(groups, Mapping) or not groups:
            raise CampaignPresetError(
                "template.scenario.groups должен быть объектом"
            )
        for side in factions:
            if side not in groups:
                raise CampaignPresetError("нет groups для стороны %r" % side)
            if _as_int(groups.get(side), 0) <= 0:
                raise CampaignPresetError(
                    "groups[%s] должно быть > 0" % side
                )
        if _as_int(scenario.get("characters_per_group"), 0) <= 0:
            raise CampaignPresetError(
                "scenario.characters_per_group должно быть > 0"
            )
    else:
        companies = scenario.get("companies")
        if not isinstance(companies, Mapping) or not companies:
            raise CampaignPresetError(
                "template.scenario.companies должен быть объектом"
            )
        for side in factions:
            if side not in companies:
                raise CampaignPresetError(
                    "нет companies для стороны %r" % side
                )
            if _as_int(companies.get(side), 0) <= 0:
                raise CampaignPresetError(
                    "companies[%s] должно быть > 0" % side
                )
        if _as_int(scenario.get("characters_per_company"), 0) <= 0:
            raise CampaignPresetError(
                "scenario.characters_per_company должно быть > 0"
            )
    for side, cfg in factions.items():
        if not isinstance(cfg, Mapping):
            raise CampaignPresetError(
                "factions[%s] должен быть объектом" % side
            )
        if not _text(cfg.get("id")).strip():
            raise CampaignPresetError("factions[%s]: пустой id" % side)
        if not _text(cfg.get("name")).strip():
            raise CampaignPresetError("factions[%s]: пустой name" % side)
        if not _text(cfg.get("culture")).strip():
            raise CampaignPresetError("factions[%s]: пустая culture" % side)
        if not isinstance(cfg.get("archetypes"), Mapping):
            raise CampaignPresetError(
                "%s: archetypes должен быть объектом" % side
            )
        if not isinstance(cfg.get("posts"), (list, tuple)):
            raise CampaignPresetError("%s: posts должен быть списком" % side)
        if not isinstance(cfg.get("organization"), Mapping):
            raise CampaignPresetError(
                "%s: organization должен быть объектом" % side
            )
    return template


def _normalize_sector(value):
    value = _text(value, "front")
    return value if value in ("front", "left", "right", "rear") else "front"


def _make_needs(randomizer, priority_needs):
    needs = dict(NEEDS_BASE)
    priorities = [str(item) for item in (priority_needs or ()) if str(item)]
    limit = max(0, int(NEEDS_PRIORITY["limit"]))
    for index, need in enumerate(priorities[:limit]):
        if need in needs:
            floor = max(
                float(NEEDS_PRIORITY["floor_min"]),
                float(NEEDS_PRIORITY["floor_base"])
                - float(NEEDS_PRIORITY["floor_step"]) * index,
            )
            needs[need] = max(
                needs[need],
                floor + float(NEEDS_PRIORITY["jitter"]) * randomizer.random(),
            )
    return {key: max(0.0, min(1.0, value)) for key, value in needs.items()}


def _make_divisions(cfg, post, name):
    """Собрать 15 ролевых делений из культуры и должности.

    Данные берутся из ``configs/characters/divisions.json``: ``presets``
    задают культурную основу, ``post.divisions`` — уточнения должности,
    пол берётся из имени. Ошибка данных не должна ломать пресет: кампания
    просто останется без делений.
    """
    try:
        catalog = load_divisions()
    except Exception:
        return {}
    culture = _text(cfg.get("culture")).lower()
    values = catalog.preset(culture)
    values.update(
        {
            str(key): str(value)
            for key, value in _as_mapping(post.get("divisions")).items()
        }
    )
    gender = _text(getattr(name, "gender", "")).lower()
    if gender in ("male", "female", "other"):
        values["sex"] = gender
    return catalog.validate(values)


def _make_character(
    randomizer,
    name,
    side,
    cfg,
    unit_id,
    char_id,
    post,
    archetype,
    force,
    priority_needs,
    char_seed,
    is_player=False,
    is_leader=False,
):
    # Легаси-граница: генератор персонажей опирается на warfare.Character
    # (он наследует simulation.UtilityAI). Импорт ленивый, чтобы загрузка
    # пресета не подтягивала simulation без создания персонажа.
    import warfare as W

    defaults = _as_mapping(cfg.get("character_defaults"))
    post_data = _as_mapping(post)
    beliefs = list(defaults.get("beliefs") or ()) + list(
        post_data.get("beliefs") or ()
    )
    beliefs = [
        dict(item, source=item.get("source") or "content")
        if isinstance(item, Mapping)
        else item
        for item in beliefs
    ]
    intentions = list(defaults.get("intentions") or ()) + list(
        post_data.get("intentions") or ()
    )
    needs = _make_needs(randomizer, priority_needs)
    personality = W.Personality.from_seed(seed=char_seed, archetype=archetype)

    character = W.Character(
        name.full,
        side,
        seed=char_seed,
        archetype=archetype,
        role=post.get("id") or archetype,
    )
    character.needs.update(needs)
    if beliefs:
        character.bdi.seed(beliefs=beliefs)
    deliberate_target = str(
        defaults.get("deliberate_target")
        or post_data.get("deliberate_target")
        or ""
    )
    character.deliberate_target = deliberate_target
    character.desires = character.weighted_urgency()
    character.deliberate(target=deliberate_target or None)
    if intentions:
        character.bdi.seed(intentions=intentions)
    divisions = _make_divisions(cfg, post, name)
    if divisions:
        try:
            character.divisions.update(divisions)
        except Exception:
            pass
    morale = character.morale
    if is_leader:
        morale += float(PRESET_DEFAULTS["morale_leader_bonus"])
    if is_player:
        morale += float(PRESET_DEFAULTS["morale_player_bonus"])
    morale = max(0.0, min(float(PRESET_DEFAULTS["morale_max"]), morale))
    return {
        "id": char_id,
        "name": name.full,
        "portrait": "characters/%s" % char_id,
        "name_data": name.as_dict(),
        "gender": name.gender,
        "side": side,
        "faction_id": cfg["id"],
        "organization_id": (cfg.get("organization") or {}).get("id"),
        "unit_id": unit_id,
        "archetype": archetype,
        "post_id": post.get("id") or "",
        "post": post.get("title") or "Боец",
        "organ_id": post.get("organ_id") or "",
        "role": post.get("id") or archetype,
        "force": round(_as_float(force, 1.0), 3),
        "needs": _round_mapping(character.needs),
        "urgency": _round_mapping(character.desires),
        "divisions": divisions,
        "personality": _round_mapping(personality.as_dict()),
        "beliefs": [item.as_dict() for item in character.bdi.beliefs],
        "intentions": [
            item.as_dict() for item in character.bdi.intentions
        ],
        "deliberate_target": deliberate_target,
        "leverage": [
            dict(item)
            for item in (
                list(defaults.get("leverage") or ())
                + list(post_data.get("leverage") or ())
            )
            if isinstance(item, Mapping)
        ],
        "morale": round(morale, 3),
        "seed": int(char_seed),
        "is_player": bool(is_player),
        "is_faction_leader": bool(is_leader),
        "campaign_role_id": "",
        "biography": "%s — %s фракции «%s»."
        % (name.full, post.get("title") or "боец", cfg["name"]),
    }


def _machine_definition(kind):
    """Вернуть первое определение автомата нужного вида.

    Автоматы — данные в ``configs/automata``. Если файлов нет, пресет
    остаётся работоспособным и собирает старый Python-граф.
    """
    try:
        catalog = load_catalog()
    except (OSError, StateMachineError, ValueError):
        return None
    return catalog.first(kind)


def _automaton_from_definition(definition, name, description):
    """Собрать граф редактора из исполняемого определения."""
    automaton = Automaton(name, description)
    ids = {}
    for state_id, spec in definition.states.items():
        state = automaton.add_state(
            spec.label or state_id,
            x=spec.x,
            y=spec.y,
            initial=(state_id == definition.initial),
            final=spec.final,
        )
        ids[state_id] = state.id
    for state_id, spec in definition.states.items():
        for transition in spec.transitions:
            automaton.add_transition(
                ids[state_id],
                ids[transition.to],
                transition.event or transition.to,
                transition.guard or "",
            )
    return automaton


def _build_faction_automaton(faction_name, leader_name, priority_need, seed):
    definition = _machine_definition("faction")
    if definition is not None:
        return _automaton_from_definition(
            definition,
            "Фракция: %s" % faction_name,
            "Жизненный цикл фракции-автомата; номинальный лидер — %s."
            % leader_name,
        )
    automaton = Automaton(
        "Фракция: %s" % faction_name,
        "Жизненный цикл фракции-автомата; номинальный лидер — %s."
        % leader_name,
    )
    latent = automaton.add_state(
        "Латентная фракция", x=80, y=100, initial=True
    )
    mobilizing = automaton.add_state("Мобилизация", x=300, y=100)
    campaign = automaton.add_state("Кампания", x=530, y=100)
    crisis = automaton.add_state("Кризис легитимности", x=530, y=300)
    dissolved = automaton.add_state("Распад", x=300, y=300, final=True)
    automaton.add_transition(
        latent.id,
        mobilizing.id,
        "угроза осознана",
        "приоритетная потребность: %s" % priority_need,
    )
    automaton.add_transition(
        mobilizing.id, campaign.id, "силы собраны", "легитимность > кризиса"
    )
    automaton.add_transition(
        campaign.id, crisis.id, "потери и раскол", "легитимность падает"
    )
    automaton.add_transition(
        crisis.id,
        campaign.id,
        "внутренний компромисс",
        "лидер сохраняет номинальную власть",
    )
    automaton.add_transition(
        crisis.id, dissolved.id, "фракция распалась", "нет лояльных участников"
    )

    del seed
    return automaton


def _subfaction_organs(cfg):
    """Органы, вложенные в подфракции, в общий список органов фракции."""
    result = []
    for item in cfg.get("subfactions") or ():
        if not isinstance(item, Mapping):
            continue
        sub_id = _text(item.get("id"))
        for organ in item.get("organs") or ():
            if not isinstance(organ, Mapping):
                continue
            record = dict(organ)
            if sub_id:
                record.setdefault("subfaction_id", sub_id)
            result.append(record)
    return result


def _organ_records(cfg):
    organs = [
        dict(item) for item in (cfg.get("organs") or ())
    ] + _subfaction_organs(cfg)
    labels = {
        _text(item.get("id")): _text(item.get("name"))
        for item in organs
    }
    action_ids = {}
    for action in cfg.get("actions") or ():
        organ_id = _text(action.get("organ_id"))
        if organ_id:
            action_ids.setdefault(organ_id, []).append(
                _text(action.get("id"))
            )
    result = []
    for item in organs:
        organ_id = _text(item.get("id"))
        if not organ_id:
            continue
        record = dict(item)
        record["id"] = organ_id
        record["name"] = labels.get(organ_id, organ_id)
        record["action_ids"] = action_ids.get(organ_id, [])
        result.append(record)
    return result


def _subfaction_records(cfg):
    """Подфракции с ссылками на органы, без дублей определений."""
    result = []
    for item in cfg.get("subfactions") or ():
        if not isinstance(item, Mapping):
            continue
        sub_id = _text(item.get("id"))
        if not sub_id:
            continue
        record = {
            key: value
            for key, value in item.items()
            if key not in ("organs", "organ_ids")
        }
        record["id"] = sub_id
        record["label"] = _text(
            item.get("label"), _text(item.get("name"), sub_id)
        )
        record["share"] = max(
            0.0, min(1.0, _as_float(item.get("share"), 0.0))
        )
        record["assets"] = {
            _text(key): _as_float(value, 0.0)
            for key, value in _as_mapping(item.get("assets")).items()
        }
        organ_ids = []
        for organ in item.get("organs") or ():
            if isinstance(organ, Mapping):
                organ_id = _text(organ.get("id"))
            else:
                organ_id = _text(organ)
            if organ_id:
                organ_ids.append(organ_id)
        organ_ids.extend(
            _text(organ_id)
            for organ_id in (item.get("organ_ids") or ())
            if _text(organ_id)
        )
        record["organ_ids"] = list(dict.fromkeys(organ_ids))
        record["automaton"] = _text(item.get("automaton"))
        result.append(record)
    return result


def _action_records(cfg):
    """Работы фракции с подписью автомата-исполнителя.

    Каждая работа обязана иметь человекочитаемое ``description``:
    интерфейс показывает его при выборе. Если данные не задали описание
    явно, берём текст успеха/провала из эффектов, а в крайнем случае
    собираем нейтральную подпись из названия работы и органа.
    """
    organs = [
        dict(item) for item in (cfg.get("organs") or ())
    ] + _subfaction_organs(cfg)
    labels = {
        _text(item.get("id")): _text(item.get("name"))
        for item in organs
    }
    default_id = _text(organs[0].get("id")) if organs else ""
    result = []
    for item in cfg.get("actions") or ():
        action = dict(item)
        organ_id = _text(action.get("organ_id")) or default_id
        if organ_id:
            action["organ_id"] = organ_id
            action.setdefault("organ", labels.get(organ_id, organ_id))
        description = _text(action.get("description"))
        if not description:
            effects = action.get("effects")
            failure = action.get("failure")
            if isinstance(effects, Mapping):
                description = _text(effects.get("text"))
            if not description and isinstance(failure, Mapping):
                description = _text(failure.get("text"))
        if not description:
            label = _text(action.get("label"), _text(action.get("id")))
            organ = _text(action.get("organ"), organ_id or "фракция")
            description = "%s — работа органа «%s»." % (label, organ)
        action["description"] = description
        result.append(action)
    return result


def _build_organ_automaton(organ, faction_name, leader_name, seed):
    """Жизненный цикл органа-автомата внутри фракции."""
    name = _text(organ.get("name"), _text(organ.get("id"), "орган"))
    description = _text(
        organ.get("description"),
        "Орган фракции «%s»; подчинён %s." % (faction_name, leader_name),
    )
    definition = _machine_definition("organ")
    if definition is not None:
        return _automaton_from_definition(
            definition, "Автомат: %s" % name, description
        )
    automaton = Automaton("Автомат: %s" % name, description)
    forming = automaton.add_state(
        "Формирование", x=80, y=100, initial=True
    )
    active = automaton.add_state("В строю", x=300, y=100)
    strained = automaton.add_state("Напряжение", x=530, y=100)
    restored = automaton.add_state("Восстановление", x=530, y=300)
    disbanded = automaton.add_state(
        "Расформирование", x=300, y=300, final=True
    )
    automaton.add_transition(
        forming.id, active.id, "приказ получен", "орган укомплектован"
    )
    automaton.add_transition(
        active.id, strained.id, "потери и перегрузка", "ресурс ниже нормы"
    )
    automaton.add_transition(
        strained.id, active.id, "пополнение", "тыл восстановил запас"
    )
    automaton.add_transition(
        strained.id, restored.id, "выведен в резерв", "нужна передышка"
    )
    automaton.add_transition(
        restored.id, active.id, "возвращён в строй", "готовность подтверждена"
    )
    automaton.add_transition(
        strained.id, disbanded.id, "расформирован", "фракция распалась"
    )
    del seed
    return automaton


def _append_organ_automata(
    automata, faction_record, cfg, side, leader_name, seed
):
    """Добавить в пресет органы фракции как отдельные автоматы.

    Идентификатор органа включает сторону: названия вроде ``medical``
    повторяются у разных фракций, а id автомата обязан быть уникальным.
    """
    organ_records = _organ_records(cfg)
    faction_record["organs"] = organ_records
    for organ in organ_records:
        organ["automaton_id"] = "automaton_organ_%s_%s" % (
            side,
            organ["id"],
        )
        organ_automaton = _build_organ_automaton(
            organ,
            cfg["name"],
            leader_name,
            seed + _stable_offset("organ:%s:%s" % (side, organ["id"])),
        )
        automata.append(
            {
                "id": organ["automaton_id"],
                "kind": "organ",
                "side": side,
                "owner_id": cfg["id"],
                "organ_id": organ["id"],
                "name": organ_automaton.name,
                "automaton": organ_automaton.to_dict(),
            }
        )
    return organ_records


def _build_organization(cfg, side, characters, seed):
    org_cfg = cfg.get("organization") or {}
    org_id = _text(org_cfg.get("id"), "org_%s" % side)
    members = []
    for character in characters:
        members.append(
            Member(
                id=character["id"],
                name=character["name"],
                needs=character["needs"],
                urgency=character["urgency"],
                energy=1.0,
                force=character["force"],
            )
        )
    runtime_cfg = org_cfg.get("runtime") or {}
    weight = max(
        0.0,
        min(
            1.0,
            _as_float(
                runtime_cfg.get("complete_weight"),
                _as_float(
                    org_cfg.get("complete_weight"),
                    float(PRESET_DEFAULTS["organization_complete_weight"]),
                ),
            ),
        ),
    )
    parameters = _organization_parameters(
        runtime_cfg.get("parameters")
    )
    population = Population.complete(members, weight=weight)
    analysis = OrganizationSolver(
        parameters, jitter_salt=org_id
    ).analyze(population)
    automaton = build_organization_automaton(
        analysis,
        name=_text(
            org_cfg.get("name"),
            str(PRESET_DEFAULTS["organization_name"]),
        ),
        seed=seed,
    )
    leader = next(
        (
            character
            for character in characters
            if character.get("is_faction_leader")
        ),
        characters[0],
    )
    leader_title = _text(
        org_cfg.get("leader_title"),
        str(PRESET_DEFAULTS["organization_leader_title"]),
    )
    leader_title_female = _text(
        org_cfg.get("leader_title_female"), leader_title
    )
    record = {
        "id": org_id,
        "name": _text(
            org_cfg.get("name"),
            str(PRESET_DEFAULTS["organization_name"]),
        ),
        "faction_id": cfg["id"],
        "side": side,
        "leader_id": leader["id"],
        "leader_name": leader["name"],
        "leader_title": leader_title,
        "leader_title_base": _text(
            org_cfg.get("leader_title_base"), leader_title
        ),
        "leader_title_female": leader_title_female,
        "member_ids": [character["id"] for character in characters],
        "automaton_id": "automaton_%s" % org_id,
        "archetype": analysis.archetype,
        "level": analysis.level,
        "priority_need": analysis.priority_need,
        "top_mode": analysis.top_mode,
        "dissolved": bool(analysis.dissolved),
        "analysis": analysis.to_dict(),
        "summary": analysis.summary_lines(),
        "runtime": {
            "complete_weight": weight,
            "leader_id": leader["name"],
            "leader_title": leader_title,
            "leader_title_base": _text(
                org_cfg.get("leader_title_base"), leader_title
            ),
            "leader_title_female": leader_title_female,
            "satisfaction_per_tick": _as_float(
                runtime_cfg.get("satisfaction_per_tick"),
                float(ORGANIZATION_RUNTIME_DEFAULTS["satisfaction_per_tick"]),
            ),
            "contribution_cost": _as_float(
                runtime_cfg.get("contribution_cost"),
                float(ORGANIZATION_RUNTIME_DEFAULTS["contribution_cost"]),
            ),
            "coercion_factor": _as_float(
                runtime_cfg.get("coercion_factor"),
                float(ORGANIZATION_RUNTIME_DEFAULTS["coercion_factor"]),
            ),
            "leader_morale_bonus": _as_float(
                runtime_cfg.get("leader_morale_bonus"),
                float(ORGANIZATION_RUNTIME_DEFAULTS["leader_morale_bonus"]),
            ),
            "allow_rejoin": bool(
                runtime_cfg.get(
                    "allow_rejoin",
                    ORGANIZATION_RUNTIME_DEFAULTS["allow_rejoin"],
                )
            ),
            "parameters": parameters.__dict__,
        },
    }
    return record, automaton


def _build_faction_record(
    cfg, side, characters, organization, automaton, player_side
):
    leader = next(
        (
            character
            for character in characters
            if character.get("is_faction_leader")
        ),
        characters[0],
    )
    role_title = _text(
        cfg.get("role_title"),
        str(PRESET_DEFAULTS["faction_leader_title"]),
    )
    return {
        "id": cfg["id"],
        "side": side,
        "name": cfg["name"],
        "kind": _text(cfg.get("kind"), "automaton"),
        "culture": cfg.get("culture"),
        "role_title": role_title,
        "role_title_base": _text(
            cfg.get("role_title_base"), role_title
        ),
        "role_title_female": _text(
            cfg.get("role_title_female"), role_title
        ),
        "leader_id": leader["id"],
        "leader_name": leader["name"],
        "organization_id": organization["id"],
        "automaton_id": "automaton_%s" % cfg["id"],
        "automaton": _text(cfg.get("automaton")),
        "priority_needs": list(cfg.get("priority_needs") or ()),
        "goals": list(cfg.get("goals") or ()),
        "doctrine": dict(cfg.get("doctrine") or {}),
        "assets": dict(cfg.get("assets") or {}),
        "score_assets": dict(cfg.get("score_assets") or {}),
        # Локальные активы и подписи (G-10) — часть данных фракции, а не
        # только шаблона: рантайм читает их из record.
        "asset_labels": dict(cfg.get("asset_labels") or {}),
        "asset_formulas": {
            str(key): [dict(term) for term in (terms or ())]
            for key, terms in _as_mapping(
                cfg.get("asset_formulas")
            ).items()
        },
        # Приказы (G-14) могут быть локальными для фракции.
        "orders": [
            dict(item)
            for item in (cfg.get("orders") or ())
            if isinstance(item, Mapping) and item.get("id")
        ],
        "order_model": dict(cfg.get("order_model") or {}),
        "rival_side": _text(cfg.get("rival_side")),
        "population": _as_int(cfg.get("population"), 0),
        "actions": _action_records(cfg),
        "organs": _organ_records(cfg),
        "subfactions": _subfaction_records(cfg),
        "geometry": dict(cfg.get("geometry") or {}),
        "organ_interactions": [
            dict(item)
            for item in (cfg.get("organ_interactions") or ())
            if isinstance(item, Mapping) and item.get("id")
        ],
        "automaton_interactions": [
            dict(item)
            for item in (cfg.get("automaton_interactions") or ())
            if isinstance(item, Mapping) and item.get("id")
        ],
        "character_interactions": [
            dict(item)
            for item in (cfg.get("character_interactions") or ())
            if isinstance(item, Mapping) and item.get("id")
        ],
        "character_ids": [character["id"] for character in characters],
        "is_player": side == player_side,
    }
