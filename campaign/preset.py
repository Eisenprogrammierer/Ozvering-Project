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


from .preset_entities import CampaignPreset, _apply_archetype
from .preset_support import (
    CampaignPresetError,
    PRESET_DEFAULTS,
    SCHEMA,
    _append_organ_automata,
    _as_float,
    _as_int,
    _build_faction_automaton,
    _build_faction_record,
    _build_organization,
    _layout_for,
    _make_character,
    _normalize_sector,
    _ordered_sides,
    _organ_records,
    _stable_offset,
    _subfaction_records,
    _text,
    _validate_template,
    default_role_catalog,
    list_templates as _list_templates,
    load_template as _load_template,
)


def default_root():
    return Path(__file__).resolve().parents[1] / "configs" / "campaigns"


def list_templates(directory=None):
    """Найти шаблоны кампаний; по умолчанию — в ``default_root``."""
    root = default_root() if directory is None else directory
    return _list_templates(root)


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
    """Загрузить шаблон; путь по умолчанию берётся из ``default_root``."""
    if path is None:
        path = default_template_path()
    return _load_template(path)


class CampaignPresetGenerator:

    def __init__(self, catalog=None, template=None, template_path=None):
        self.catalog = catalog or default_role_catalog()
        if template is None:
            template = load_template(template_path)
        self.template = _validate_template(dict(template))
        self.role_catalog = self.catalog

    def generate(
        self,
        role_id=None,
        seed=None,
        preset_id=None,
        player_faction_id=None,
    ):
        if role_id is None:
            role = self.role_catalog.default_role()
        else:
            role = self.role_catalog.select(role_id)
        base_seed = _as_int(
            seed if seed is not None else self.template.get("default_seed", 7),
            7,
        )
        return self._generate(
            role,
            base_seed,
            preset_id=preset_id,
            player_faction_id=player_faction_id,
        )

    def faction_options(self, seed=None):
        template = self.template
        base_seed = _as_int(
            seed if seed is not None else template.get("default_seed", 7),
            7,
        )
        scenario_cfg = template.get("scenario") or {}
        companies = scenario_cfg.get("companies") or {}
        groups = scenario_cfg.get("groups") or {}
        default_population = scenario_cfg.get("characters_per_faction") or 0
        slots = template.get("faction_slots") or {}
        default_side = _text(
            slots.get("player", template.get("player_side")), "red"
        )
        options = []
        for side in _ordered_sides(template):
            cfg = template["factions"][side]
            organization = cfg.get("organization") or {}
            name_generator = PersonNameGenerator(seed=base_seed)
            faction_policy = name_generator.policy(_text(cfg.get("id")))
            leader = name_generator.generate_many(
                1,
                culture=(
                    None
                    if faction_policy
                    else _text(cfg.get("culture"))
                ),
                policy=faction_policy,
                seed=base_seed + _stable_offset("names:%s" % side),
            )[0]
            assets = dict(cfg.get("assets") or {})
            support = sum(
                _as_float(assets.get(key), 0.0)
                for key in ("legitimacy", "cohesion", "charter")
            ) / 3.0
            options.append(
                {
                    "id": _text(cfg.get("id")),
                    "side": side,
                    "name": _text(cfg.get("name")),
                    "kind": _text(cfg.get("kind"), "coalition"),
                    "culture": _text(cfg.get("culture")),
                    "leader_name": leader.full,
                    "organization_name": _text(organization.get("name")),
                    "companies": max(0, _as_int(companies.get(side), 0)),
                    "groups": max(0, _as_int(groups.get(side), 0)),
                    "population": max(
                        0, _as_int(cfg.get("population"), default_population)
                    ),
                    "support": max(0.0, min(1.0, support)),
                    "goals": list(cfg.get("goals") or ()),
                    "assets": assets,
                    "is_default": side == default_side,
                }
            )
        return options

    def _generate(self, role, seed, preset_id=None, player_faction_id=None):
        template = self.template
        scenario_cfg = template.get("scenario") or {}
        mode = _text(scenario_cfg.get("mode"))
        if mode == "automata":
            return self._generate_automata(
                role,
                seed,
                preset_id=preset_id,
                player_faction_id=player_faction_id,
            )
        if mode == "strategy":
            return self._generate_strategy(
                role,
                seed,
                preset_id=preset_id,
                player_faction_id=player_faction_id,
            )
        slots = template.get("faction_slots") or {}
        slot = role.faction_slot or "player"
        other_slot = "enemy" if slot == "player" else "player"
        default_player_side = _text(
            slots.get(slot, template.get("player_side")), "red"
        )
        player_side = default_player_side
        if player_faction_id:
            chosen = next(
                (
                    side
                    for side, cfg in template["factions"].items()
                    if _text(cfg.get("id")) == _text(player_faction_id)
                ),
                None,
            )
            if chosen is None:
                raise CampaignPresetError(
                    "нет фракции %r" % (player_faction_id,)
                )
            player_side = chosen
        enemy_side = _text(
            slots.get(other_slot, template.get("enemy_side")), "blue"
        )
        if player_side not in template["factions"]:
            raise CampaignPresetError("нет фракции игрока %r" % player_side)
        if enemy_side not in template["factions"]:
            raise CampaignPresetError("нет фракции противника %r" % enemy_side)
        if player_side == enemy_side:
            enemy_side = next(
                (
                    side
                    for side in _ordered_sides(template)
                    if side != player_side
                ),
                enemy_side,
            )
        if player_side == enemy_side:
            raise CampaignPresetError("не удалось выбрать фракцию противника")
        sides = _ordered_sides(template)
        companies = scenario_cfg.get("companies") or {}
        per_company = max(
            1, _as_int(scenario_cfg.get("characters_per_company"), 4)
        )
        name_generator = PersonNameGenerator(seed=seed)
        characters = []
        units = []
        side_characters = {side: [] for side in sides}
        side_units = {side: [] for side in sides}

        for side in sides:
            cfg = template["factions"][side]
            count = max(1, _as_int(companies.get(side), 0))
            faction_policy = name_generator.policy(_text(cfg.get("id")))
            names = name_generator.generate_many(
                count * per_company,
                culture=(
                    None
                    if faction_policy
                    else _text(cfg.get("culture"))
                ),
                policy=faction_policy,
                seed=seed + _stable_offset("names:%s" % side),
            )
            posts = list(cfg.get("posts") or ())
            line_posts = list(cfg.get("line_posts") or ())
            archetypes = cfg.get("archetypes") or {}
            priority_needs = cfg.get("priority_needs") or ()
            layout = _layout_for(side, count)
            side_offset = _stable_offset("side:%s" % side)
            for unit_index in range(count):
                sector, position = layout[unit_index]
                sector = _normalize_sector(sector)
                unit_id = "%s-%02d" % (side, unit_index + 1)
                unit_name = (
                    "Р-%02d" % (unit_index + 1)
                    if side == "red"
                    else (
                        "С-%02d" % (unit_index + 1)
                        if side == "blue"
                        else "%s-%02d" % (side, unit_index + 1)
                    )
                )
                unit_characters = []
                for item_index in range(per_company):
                    global_index = unit_index * per_company + item_index
                    name = names[global_index]
                    if global_index < len(posts):
                        post = dict(posts[global_index])
                    else:
                        title = (
                            line_posts[item_index % len(line_posts)]
                            if line_posts
                            else "Боец"
                        )
                        post = {
                            "id": "line_%d" % (item_index + 1),
                            "title": title,
                            "archetype": "",
                            "force": 1.0,
                        }
                    archetype = post.get("archetype") or ""
                    if not archetype:
                        options = archetypes.get(sector)
                        if isinstance(options, (list, tuple)) and options:
                            archetype = options[item_index % len(options)]
                        else:
                            archetype = "rifleman"
                    force = post.get("force", 1.0)
                    char_id = "char_%s_%03d_%d" % (
                        side,
                        unit_index + 1,
                        item_index + 1,
                    )
                    char_seed = seed + side_offset + global_index * 37 + 17
                    is_leader = global_index == 0
                    is_player = side == player_side and global_index == 0
                    randomizer = random.Random(char_seed + 101)
                    character = _make_character(
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
                        is_player=is_player,
                        is_leader=is_leader,
                    )
                    if is_player:
                        character["campaign_role_id"] = role.id
                    characters.append(character)
                    side_characters[side].append(character)
                    unit_characters.append(character["id"])
                unit = {
                    "unit_id": unit_id,
                    "name": unit_name,
                    "side": side,
                    "sector": sector,
                    "position": list(position),
                    "faction_id": cfg["id"],
                    "character_ids": unit_characters,
                    "leader_id": unit_characters[0],
                }
                units.append(unit)
                side_units[side].append(unit)

        organizations = []
        automata = []
        factions = []
        for side in sides:
            cfg = template["factions"][side]
            side_chars = side_characters[side]
            organization, org_automaton = _build_organization(
                cfg,
                side,
                side_chars,
                seed + _stable_offset("org:%s" % side),
            )
            organizations.append(organization)
            automata.append(
                {
                    "id": organization["automaton_id"],
                    "kind": "organization",
                    "side": side,
                    "owner_id": organization["id"],
                    "name": org_automaton.name,
                    "automaton": org_automaton.to_dict(),
                }
            )
            leader = next(
                (item for item in side_chars if item.get("is_faction_leader")),
                side_chars[0],
            )
            priority = (cfg.get("priority_needs") or [""])[0]
            faction_automaton = _build_faction_automaton(
                cfg["name"],
                leader["name"],
                priority,
                seed + _stable_offset("faction:%s" % side),
            )
            factions.append(
                _build_faction_record(
                    cfg,
                    side,
                    side_chars,
                    organization,
                    faction_automaton,
                    player_side,
                )
            )
            automata.append(
                {
                    "id": "automaton_%s" % cfg["id"],
                    "kind": "faction",
                    "side": side,
                    "owner_id": cfg["id"],
                    "name": faction_automaton.name,
                    "automaton": faction_automaton.to_dict(),
                }
            )
            _append_organ_automata(
                automata,
                factions[-1],
                cfg,
                side,
                leader["name"],
                seed,
            )

        player_faction = next(
            item for item in factions if item["side"] == player_side
        )
        player_character = next(
            item
            for item in side_characters[player_side]
            if item.get("is_player")
        )
        player_character["campaign_role_id"] = role.id

        environment = self._build_environment(seed)
        events = self._build_events(
            seed,
            player_faction,
            characters,
            next(item for item in factions if item["side"] == enemy_side),
            organizations,
        )
        playwright = self._build_playwright(seed, characters, organizations)

        scenario = {
            "template_id": _text(template.get("template_id"), "test_skirmish"),
            "seed": seed,
            "turns": _as_int(scenario_cfg.get("turns"), 2016),
            "map_name": _text(scenario_cfg.get("map_name"), "valley_01"),
            "player_side": player_side,
            "enemy_side": enemy_side,
            "companies": {side: len(side_units[side]) for side in sides},
            "characters_per_company": per_company,
            "units": units,
        }
        explicit_id = _text(preset_id).strip()
        preset_id = explicit_id or "%s_seed%d" % (
            _text(template.get("template_id"), "test_skirmish"),
            seed,
        )
        if not explicit_id and player_side != default_player_side:
            preset_id += "_%s" % _text(player_faction["id"]).replace(
                "faction_", ""
            )
        return CampaignPreset(
            schema=SCHEMA,
            template_id=_text(template.get("template_id"), "test_skirmish"),
            preset_id=preset_id,
            title=_text(template.get("title"), "Тестовая кампания"),
            description=_text(template.get("description")),
            seed=seed,
            role=role,
            player_faction_id=player_faction["id"],
            player_character_id=player_character["id"],
            factions=factions,
            characters=characters,
            organizations=organizations,
            automata=automata,
            environment=environment,
            events=events,
            playwright=playwright,
            scenario=scenario,
        )

    def _generate_automata(
        self, role, seed, preset_id=None, player_faction_id=None
    ):
        template = self.template
        scenario_cfg = template.get("scenario") or {}
        slots = template.get("faction_slots") or {}
        slot = role.faction_slot or "player"
        other_slot = "enemy" if slot == "player" else "player"
        default_player_side = _text(
            slots.get(slot, template.get("player_side")), "red"
        )
        player_side = default_player_side
        if player_faction_id:
            chosen = next(
                (
                    side
                    for side, cfg in template["factions"].items()
                    if _text(cfg.get("id")) == _text(player_faction_id)
                ),
                None,
            )
            if chosen is None:
                raise CampaignPresetError(
                    "нет фракции %r" % (player_faction_id,)
                )
            player_side = chosen
        enemy_side = _text(
            slots.get(other_slot, template.get("enemy_side")), "blue"
        )
        if player_side not in template["factions"]:
            raise CampaignPresetError("нет фракции игрока %r" % player_side)
        if enemy_side not in template["factions"]:
            raise CampaignPresetError("нет фракции противника %r" % enemy_side)
        if player_side == enemy_side:
            enemy_side = next(
                (
                    side
                    for side in _ordered_sides(template)
                    if side != player_side
                ),
                enemy_side,
            )
        if player_side == enemy_side:
            raise CampaignPresetError("не удалось выбрать фракцию противника")
        sides = _ordered_sides(template)
        default_population = max(
            1,
            _as_int(
                scenario_cfg.get("characters_per_faction"),
                int(PRESET_DEFAULTS["characters_per_faction"]),
            ),
        )
        name_generator = PersonNameGenerator(seed=seed)
        characters = []
        side_characters = {side: [] for side in sides}
        for side in sides:
            cfg = template["factions"][side]
            count = max(
                1,
                _as_int(
                    cfg.get("population"),
                    default_population,
                ),
            )
            faction_policy = name_generator.policy(_text(cfg.get("id")))
            names = name_generator.generate_many(
                count,
                culture=(
                    None
                    if faction_policy
                    else _text(cfg.get("culture"))
                ),
                policy=faction_policy,
                seed=seed + _stable_offset("names:%s" % side),
            )
            posts = list(cfg.get("posts") or ())
            line_posts = list(cfg.get("line_posts") or ())
            archetypes = cfg.get("archetypes") or {}
            flat_archetypes = []
            if isinstance(archetypes, Mapping):
                for values in archetypes.values():
                    if isinstance(values, (list, tuple)):
                        flat_archetypes.extend(str(item) for item in values)
            default_archetype = (
                _text(cfg.get("default_archetype"))
                or (flat_archetypes[0] if flat_archetypes else "citizen")
            )
            priority_needs = cfg.get("priority_needs") or ()
            side_offset = _stable_offset("side:%s" % side)
            for index in range(count):
                name = names[index]
                if index < len(posts):
                    post = dict(posts[index])
                else:
                    title = (
                        line_posts[index % len(line_posts)]
                        if line_posts
                        else str(PRESET_DEFAULTS["participant_title"])
                    )
                    post = {
                        "id": "participant_%d" % (index + 1),
                        "title": title,
                        "archetype": default_archetype,
                        "force": 1.0,
                    }
                archetype = _text(post.get("archetype")) or default_archetype
                force = post.get("force", 1.0)
                char_id = "char_%s_%03d" % (side, index + 1)
                char_seed = seed + side_offset + index * 37 + 17
                is_leader = index == 0
                is_player = side == player_side and index == 0
                randomizer = random.Random(char_seed + 101)
                character = _make_character(
                    randomizer,
                    name,
                    side,
                    cfg,
                    _text((cfg.get("organization") or {}).get("id")),
                    char_id,
                    post,
                    archetype,
                    force,
                    priority_needs,
                    char_seed,
                    is_player=is_player,
                    is_leader=is_leader,
                )
                if is_player:
                    character["campaign_role_id"] = role.id
                characters.append(character)
                side_characters[side].append(character)

        organizations = []
        automata = []
        factions = []
        for side in sides:
            cfg = template["factions"][side]
            side_chars = side_characters[side]
            organization, org_automaton = _build_organization(
                cfg,
                side,
                side_chars,
                seed + _stable_offset("org:%s" % side),
            )
            organizations.append(organization)
            automata.append(
                {
                    "id": organization["automaton_id"],
                    "kind": "organization",
                    "side": side,
                    "owner_id": organization["id"],
                    "name": org_automaton.name,
                    "automaton": org_automaton.to_dict(),
                }
            )
            leader = next(
                (item for item in side_chars if item.get("is_faction_leader")),
                side_chars[0],
            )
            priority = (cfg.get("priority_needs") or [""])[0]
            faction_automaton = _build_faction_automaton(
                cfg["name"],
                leader["name"],
                priority,
                seed + _stable_offset("faction:%s" % side),
            )
            factions.append(
                _build_faction_record(
                    cfg,
                    side,
                    side_chars,
                    organization,
                    faction_automaton,
                    player_side,
                )
            )
            automata.append(
                {
                    "id": "automaton_%s" % cfg["id"],
                    "kind": "faction",
                    "side": side,
                    "owner_id": cfg["id"],
                    "name": faction_automaton.name,
                    "automaton": faction_automaton.to_dict(),
                }
            )
            _append_organ_automata(
                automata,
                factions[-1],
                cfg,
                side,
                leader["name"],
                seed,
            )

        player_faction = next(
            item for item in factions if item["side"] == player_side
        )
        player_character = next(
            item
            for item in side_characters[player_side]
            if item.get("is_player")
        )
        player_character["campaign_role_id"] = role.id
        environment = self._build_environment(seed)
        events = self._build_events(
            seed,
            player_faction,
            characters,
            next(item for item in factions if item["side"] == enemy_side),
            organizations,
        )
        playwright = self._build_playwright(seed, characters, organizations)
        scenario = {
            "mode": "automata",
            "template_id": _text(
                template.get("template_id"), "automata_campaign"
            ),
            "seed": seed,
            "turns": (
                _as_int(scenario_cfg.get("turns"), 0)
                if scenario_cfg.get("turns") is not None
                else None
            ),
            "actions_per_cycle": max(
                1,
                _as_int(
                    scenario_cfg.get(
                        "actions_per_cycle",
                        scenario_cfg.get("actions_per_turn"),
                    ),
                    3,
                ),
            ),
            "player_side": player_side,
            "enemy_side": enemy_side,
            "characters_per_faction": default_population,
            "populations": {
                side: len(side_characters[side]) for side in sides
            },
            "rivals": dict(scenario_cfg.get("rivals") or {}),
            "model": dict(scenario_cfg.get("model") or {}),
            "outcome": dict(scenario_cfg.get("outcome") or {}),
        }
        explicit_id = _text(preset_id).strip()
        preset_id = explicit_id or "%s_seed%d" % (
            _text(template.get("template_id"), "automata_campaign"),
            seed,
        )
        if not explicit_id and player_side != default_player_side:
            preset_id += "_%s" % _text(player_faction["id"]).replace(
                "faction_", ""
            )
        return CampaignPreset(
            schema=SCHEMA,
            template_id=_text(
                template.get("template_id"), "automata_campaign"
            ),
            preset_id=preset_id,
            title=_text(template.get("title"), "Кампания автоматов"),
            description=_text(template.get("description")),
            seed=seed,
            role=role,
            player_faction_id=player_faction["id"],
            player_character_id=player_character["id"],
            factions=factions,
            characters=characters,
            organizations=organizations,
            automata=automata,
            environment=environment,
            events=events,
            playwright=playwright,
            scenario=scenario,
        )

    def _generate_strategy(
        self, role, seed, preset_id=None, player_faction_id=None
    ):
        template = self.template
        scenario_cfg = template.get("scenario") or {}
        slots = template.get("faction_slots") or {}
        slot = role.faction_slot or "player"
        other_slot = "enemy" if slot == "player" else "player"
        default_player_side = _text(
            slots.get(slot, template.get("player_side")), "red"
        )
        player_side = default_player_side
        if player_faction_id:
            chosen = next(
                (
                    side
                    for side, cfg in template["factions"].items()
                    if _text(cfg.get("id")) == _text(player_faction_id)
                ),
                None,
            )
            if chosen is None:
                raise CampaignPresetError(
                    "нет фракции %r" % (player_faction_id,)
                )
            player_side = chosen
        enemy_side = _text(
            slots.get(other_slot, template.get("enemy_side")), "blue"
        )
        if player_side not in template["factions"]:
            raise CampaignPresetError("нет фракции игрока %r" % player_side)
        if enemy_side not in template["factions"]:
            raise CampaignPresetError("нет фракции противника %r" % enemy_side)
        if player_side == enemy_side:
            enemy_side = next(
                (
                    side
                    for side in _ordered_sides(template)
                    if side != player_side
                ),
                enemy_side,
            )
        if player_side == enemy_side:
            raise CampaignPresetError("не удалось выбрать фракцию противника")
        sides = _ordered_sides(template)
        groups = scenario_cfg.get("groups") or {}
        per_group = max(
            1, _as_int(scenario_cfg.get("characters_per_group"), 4)
        )
        name_generator = PersonNameGenerator(seed=seed)
        characters = []
        side_characters = {side: [] for side in sides}
        for side in sides:
            cfg = template["factions"][side]
            group_count = max(1, _as_int(groups.get(side), 0))
            count = group_count * per_group
            faction_policy = name_generator.policy(_text(cfg.get("id")))
            names = name_generator.generate_many(
                count,
                culture=(
                    None
                    if faction_policy
                    else _text(cfg.get("culture"))
                ),
                policy=faction_policy,
                seed=seed + _stable_offset("names:%s" % side),
            )
            posts = list(cfg.get("posts") or ())
            line_posts = list(cfg.get("line_posts") or ())
            side_offset = _stable_offset("side:%s" % side)
            for global_index in range(count):
                group_index = global_index // per_group
                item_index = global_index % per_group
                name = names[global_index]
                if global_index < len(posts):
                    post = dict(posts[global_index])
                else:
                    post = {
                        "id": "line_%d" % (item_index + 1),
                        "title": (
                            line_posts[item_index % len(line_posts)]
                            if line_posts
                            else "Делегат"
                        ),
                        "archetype": "citizen",
                        "force": 1.0,
                    }
                archetype = post.get("archetype") or "citizen"
                force = post.get("force", 1.0)
                unit_id = "%s-%02d" % (side, group_index + 1)
                char_id = "char_%s_%03d_%d" % (
                    side,
                    group_index + 1,
                    item_index + 1,
                )
                char_seed = seed + side_offset + global_index * 37 + 17
                is_leader = global_index == 0
                is_player = side == player_side and global_index == 0
                randomizer = random.Random(char_seed + 101)
                character = _make_character(
                    randomizer,
                    name,
                    side,
                    cfg,
                    unit_id,
                    char_id,
                    post,
                    archetype,
                    force,
                    cfg.get("priority_needs") or (),
                    char_seed,
                    is_player=is_player,
                    is_leader=is_leader,
                )
                if is_player:
                    character["campaign_role_id"] = role.id
                characters.append(character)
                side_characters[side].append(character)
        organizations = []
        automata = []
        factions = []
        for side in sides:
            cfg = template["factions"][side]
            side_chars = side_characters[side]
            organization, org_automaton = _build_organization(
                cfg,
                side,
                side_chars,
                seed + _stable_offset("org:%s" % side),
            )
            organizations.append(organization)
            automata.append(
                {
                    "id": organization["automaton_id"],
                    "kind": "organization",
                    "side": side,
                    "owner_id": organization["id"],
                    "name": org_automaton.name,
                    "automaton": org_automaton.to_dict(),
                }
            )
            leader = next(
                (item for item in side_chars if item.get("is_faction_leader")),
                side_chars[0],
            )
            priority = (cfg.get("priority_needs") or [""])[0]
            faction_automaton = _build_faction_automaton(
                cfg["name"],
                leader["name"],
                priority,
                seed + _stable_offset("faction:%s" % side),
            )
            factions.append(
                _build_faction_record(
                    cfg,
                    side,
                    side_chars,
                    organization,
                    faction_automaton,
                    player_side,
                )
            )
            automata.append(
                {
                    "id": "automaton_%s" % cfg["id"],
                    "kind": "faction",
                    "side": side,
                    "owner_id": cfg["id"],
                    "name": faction_automaton.name,
                    "automaton": faction_automaton.to_dict(),
                }
            )
        player_faction = next(
            item for item in factions if item["side"] == player_side
        )
        player_character = next(
            item
            for item in side_characters[player_side]
            if item.get("is_player")
        )
        player_character["campaign_role_id"] = role.id
        environment = self._build_environment(seed)
        events = self._build_events(
            seed,
            player_faction,
            characters,
            next(item for item in factions if item["side"] == enemy_side),
            organizations,
        )
        playwright = self._build_playwright(seed, characters, organizations)
        scenario = {
            "template_id": _text(template.get("template_id"), "agora_charter"),
            "seed": seed,
            "mode": "strategy",
            "turns": _as_int(scenario_cfg.get("turns"), 10),
            "strategy_path": _text(
                scenario_cfg.get("strategy_path"),
                "configs/strategy/agora_charter.json",
            ),
            "player_side": player_side,
            "enemy_side": enemy_side,
            "groups": {
                side: len(side_characters[side]) // per_group
                for side in sides
            },
            "characters_per_group": per_group,
            "units": [],
        }
        explicit_id = _text(preset_id).strip()
        preset_id = explicit_id or "%s_seed%d" % (
            _text(template.get("template_id"), "agora_charter"),
            seed,
        )
        if not explicit_id and player_side != default_player_side:
            preset_id += "_%s" % _text(player_faction["id"]).replace(
                "faction_", ""
            )
        return CampaignPreset(
            schema=SCHEMA,
            template_id=_text(template.get("template_id"), "agora_charter"),
            preset_id=preset_id,
            title=_text(template.get("title"), "Хартия Агоры"),
            description=_text(template.get("description")),
            seed=seed,
            role=role,
            player_faction_id=player_faction["id"],
            player_character_id=player_character["id"],
            factions=factions,
            characters=characters,
            organizations=organizations,
            automata=automata,
            environment=environment,
            events=events,
            playwright=playwright,
            scenario=scenario,
        )

    def _build_environment(self, seed):
        cfg = self.template.get("environment") or {}
        catalog = EnvironmentCatalog.load()
        feature_ids = [_text(item) for item in (cfg.get("features") or ())]
        if not feature_ids:
            raise CampaignPresetError(
                "template.environment.features не может быть пустым"
            )
        features = []
        for feature_id in feature_ids:
            features.append(catalog.feature(feature_id))
        runtime = EnvironmentRuntime(
            features,
            seed=seed + _stable_offset("environment"),
            drift_chance=_as_float(
                cfg.get("drift_chance"), catalog.drift_chance
            ),
        )
        snapshot = runtime.snapshot()
        return {
            "catalog": "configs/systems/environment.json",
            "seed": runtime.seed,
            "drift_chance": runtime.drift_chance,
            "feature_ids": feature_ids,
            "features": snapshot["features"],
        }

    def _build_events(
        self, seed, player_faction, characters, enemy_faction, organizations
    ):
        cfg = self.template.get("events") or {}
        catalog = EventCatalog.load()
        categories = [_text(item) for item in (cfg.get("categories") or ())]
        if not categories:
            categories = sorted(catalog.categories)
        for category in categories:
            if category not in catalog.categories:
                raise CampaignPresetError(
                    "нет категории событий %r" % category
                )
        count = max(1, _as_int(cfg.get("count"), 8))
        player_leader = next(
            (item for item in characters if item.get("is_player")),
            next(
                item
                for item in characters
                if item.get("side") == player_faction["side"]
            ),
        )
        enemy_leader = next(
            (
                item
                for item in characters
                if item.get("side") == enemy_faction["side"]
                and item.get("is_faction_leader")
            ),
            next(
                item
                for item in characters
                if item.get("side") == enemy_faction["side"]
            ),
        )
        player_org = next(
            (
                item
                for item in organizations
                if item.get("side") == player_faction.get("side")
            ),
            None,
        )
        enemy_org = next(
            (
                item
                for item in organizations
                if item.get("side") == enemy_faction.get("side")
            ),
            None,
        )
        context = {
            "actor": player_leader["name"],
            "target": enemy_leader["name"],
            "rival": enemy_leader["name"],
            "organization": (player_org or {}).get("name")
            or player_faction.get("name")
            or "фракция",
            "rival_organization": (enemy_org or {}).get("name")
            or enemy_faction.get("name")
            or "противник",
            "place": "«Узел связи»",
            "object": "полевая печать",
            "cause": "первый залп по позициям",
            "consequence": "линия фронта дрогнула",
            "amount": "триста человек",
        }
        overrides = cfg.get("context")
        if isinstance(overrides, Mapping):
            context.update(
                {str(key): _text(value) for key, value in overrides.items()}
            )
        generator = EventTextGenerator(
            catalog=catalog,
            seed=seed + _stable_offset("events"),
            auto_names=False,
        )
        hooks = []
        for index in range(count):
            category = categories[index % len(categories)]
            event = generator.generate(
                category=category,
                context=context,
                seed=seed + _stable_offset("event:%d" % index),
            )
            hooks.append(event.as_dict())
        return {
            "catalog": "configs/systems/events.json",
            "seed": generator.seed,
            "categories": categories,
            "context": context,
            "hooks": hooks,
        }

    def _build_playwright(self, seed, characters, organizations):
        cfg = self.template.get("playwright") or {}
        config = PlaywrightConfig.load()
        max_actors = max(2, _as_int(cfg.get("max_actors"), 8))
        org_by_side = {
            item.get("side"): item.get("name")
            for item in organizations
            if item.get("side")
        }
        by_side = {}
        for character in characters:
            by_side.setdefault(character["side"], []).append(character)
        actors = []
        for side in _ordered_sides(self.template):
            pool = by_side.get(side) or []
            take = max(1, max_actors // max(1, len(by_side)))
            for character in pool[:take]:
                needs = character.get("needs") or {}
                stakes = max(needs.values()) if needs else 0.5
                traits = [
                    key
                    for key, value in (
                        character.get("personality") or {}
                    ).items()
                    if _as_float(value, 0.0) >= 0.60
                ][:4]
                actors.append(
                    DramaActor(
                        id=character["id"],
                        name=character["name"],
                        organization=org_by_side.get(
                            character.get("side"),
                            character.get("faction_id", ""),
                        ),
                        tags=(
                            character.get("side", ""),
                            character.get("post_id", ""),
                            character.get("archetype", ""),
                        ),
                        stakes=round(_as_float(stakes, 0.5), 4),
                        traits=tuple(traits),
                    )
                )
                if len(actors) >= max_actors:
                    break
            if len(actors) >= max_actors:
                break
        event_generator = EventTextGenerator(
            seed=seed + _stable_offset("playwright-events"),
            auto_names=False,
        )
        playwright = Playwright(
            config=config,
            seed=seed + _stable_offset("playwright"),
            event_generator=event_generator,
        )
        candidates = playwright.spawn_candidates(actors)
        return {
            "catalog": "configs/systems/playwright.json",
            "seed": playwright.seed,
            "turns": _as_int(cfg.get("turns"), 12),
            "max_actors": max_actors,
            "config": config.as_dict(),
            "actors": [actor.as_dict() for actor in actors],
            "templates": [item.as_dict() for item in config.templates],
            "candidate_count": len(candidates),
            "candidates": [item.as_dict() for item in candidates[:24]],
            "initial_state": playwright.machine.current,
            "initial_state_name": playwright.machine.state_name(),
        }


def generate_preset(
    role_id="faction_leader",
    seed=None,
    preset_id=None,
    template=None,
    template_path=None,
    catalog=None,
    player_faction_id=None,
):
    """Сгенерировать пресет кампании.

    Дефолт `role_id="faction_leader"` сохранён для легаси-кода и старых
    тестов. CLI передаёт `None`, чтобы выбрать первую доступную роль.
    """
    generator = CampaignPresetGenerator(
        catalog=catalog, template=template, template_path=template_path
    )
    return generator.generate(
        role_id=role_id,
        seed=seed,
        preset_id=preset_id,
        player_faction_id=player_faction_id,
    )


__all__ = [
    "SCHEMA",
    "CampaignPresetError",
    "CampaignPreset",
    "CampaignPresetGenerator",
    "default_root",
    "default_template_path",
    "list_templates",
    "load_template",
    "generate_preset",
]
