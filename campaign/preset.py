from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import random
from typing import Dict, List, Mapping

import warfare as W
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

from .errors import CampaignError
from .roles import RoleSpec, default_catalog as default_role_catalog

SCHEMA = 1


class CampaignPresetError(CampaignError):
    pass


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
    return default_root() / "test_skirmish.json"


def load_template(path=None):
    path = Path(path) if path is not None else default_template_path()
    if path.is_dir():
        path = path / "test_skirmish.json"
    data = _read_json(path)
    if not isinstance(data, Mapping):
        raise CampaignPresetError("шаблон пресета должен быть объектом")
    return dict(data)


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
    companies = scenario.get("companies")
    if not isinstance(companies, Mapping) or not companies:
        raise CampaignPresetError(
            "template.scenario.companies должен быть объектом"
        )
    for side in factions:
        if side not in companies:
            raise CampaignPresetError("нет companies для стороны %r" % side)
        if _as_int(companies.get(side), 0) <= 0:
            raise CampaignPresetError("companies[%s] должно быть > 0" % side)
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
    base = {
        "hunger": 0.18,
        "thirst": 0.15,
        "fatigue": 0.12,
        "health": 0.05,
        "fear": 0.10,
        "anxiety": 0.12,
        "loneliness": 0.18,
        "reproduction": 0.10,
        "knowledge": 0.25,
        "creativity": 0.22,
        "boredom": 0.25,
        "status": 0.35,
        "spirituality": 0.25,
        "skill": 0.35,
        "love": 0.18,
        "friendship": 0.18,
    }
    needs = dict(base)
    priorities = [str(item) for item in (priority_needs or ()) if str(item)]
    for index, need in enumerate(priorities[:4]):
        if need in needs:

            floor = max(0.42, 0.80 - 0.10 * index)
            needs[need] = max(needs[need], floor + 0.16 * randomizer.random())
    return {key: max(0.0, min(1.0, value)) for key, value in needs.items()}


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
    character.desires = character.weighted_urgency()
    character.deliberate()
    morale = character.morale
    if is_leader:
        morale += 4.0
    if is_player:
        morale += 2.0
    morale = max(0.0, min(100.0, morale))
    return {
        "id": char_id,
        "name": name.full,
        "name_data": name.as_dict(),
        "side": side,
        "faction_id": cfg["id"],
        "organization_id": (cfg.get("organization") or {}).get("id"),
        "unit_id": unit_id,
        "archetype": archetype,
        "post_id": post.get("id") or "",
        "post": post.get("title") or "Боец",
        "role": post.get("id") or archetype,
        "force": round(_as_float(force, 1.0), 3),
        "needs": _round_mapping(character.needs),
        "urgency": _round_mapping(character.desires),
        "personality": _round_mapping(personality.as_dict()),
        "morale": round(morale, 3),
        "seed": int(char_seed),
        "is_player": bool(is_player),
        "is_faction_leader": bool(is_leader),
        "campaign_role_id": "",
        "biography": "%s — %s фракции «%s»."
        % (name.full, post.get("title") or "боец", cfg["name"]),
    }


def _build_faction_automaton(faction_name, leader_name, priority_need, seed):
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
    weight = max(
        0.0, min(1.0, _as_float(org_cfg.get("complete_weight"), 0.84))
    )
    population = Population.complete(members, weight=weight)
    analysis = OrganizationSolver(OrganizationParameters()).analyze(population)
    automaton = build_organization_automaton(
        analysis,
        name=_text(org_cfg.get("name"), "Организация"),
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
    record = {
        "id": org_id,
        "name": _text(org_cfg.get("name"), "Организация"),
        "faction_id": cfg["id"],
        "side": side,
        "leader_id": leader["id"],
        "leader_name": leader["name"],
        "leader_title": _text(
            org_cfg.get("leader_title"), "номинальный председатель"
        ),
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
            "leader_title": _text(
                org_cfg.get("leader_title"), "номинальный председатель"
            ),
            "parameters": OrganizationParameters().__dict__,
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
    return {
        "id": cfg["id"],
        "side": side,
        "name": cfg["name"],
        "kind": _text(cfg.get("kind"), "automaton"),
        "culture": cfg.get("culture"),
        "role_title": _text(cfg.get("role_title"), "номинальный лидер"),
        "leader_id": leader["id"],
        "leader_name": leader["name"],
        "organization_id": organization["id"],
        "automaton_id": "automaton_%s" % cfg["id"],
        "priority_needs": list(cfg.get("priority_needs") or ()),
        "goals": list(cfg.get("goals") or ()),
        "assets": dict(cfg.get("assets") or {}),
        "character_ids": [character["id"] for character in characters],
        "is_player": side == player_side,
    }


@dataclass
class CampaignPreset:

    preset_id: str
    title: str
    role: RoleSpec
    seed: int
    player_faction_id: str
    player_character_id: str = ""
    factions: List[dict] = field(default_factory=list)
    characters: List[dict] = field(default_factory=list)
    organizations: List[dict] = field(default_factory=list)
    automata: List[dict] = field(default_factory=list)
    environment: Dict = field(default_factory=dict)
    events: Dict = field(default_factory=dict)
    playwright: Dict = field(default_factory=dict)
    scenario: Dict = field(default_factory=dict)
    template_id: str = ""
    description: str = ""
    schema: int = SCHEMA

    def __post_init__(self):
        if isinstance(self.role, Mapping):
            self.role = RoleSpec.from_data(self.role)
        if not isinstance(self.role, RoleSpec):
            raise CampaignPresetError("role должен быть RoleSpec")
        self.preset_id = _text(self.preset_id).strip()
        if not self.preset_id:
            raise CampaignPresetError("у пресета должен быть preset_id")
        self.title = _text(self.title).strip() or self.preset_id
        self.description = _text(self.description)
        self.template_id = _text(self.template_id)
        self.seed = _as_int(self.seed, 0)
        self.schema = _as_int(self.schema, SCHEMA)
        self.player_faction_id = _text(self.player_faction_id).strip()
        self.player_character_id = _text(self.player_character_id).strip()
        self.factions = [dict(item) for item in (self.factions or ())]
        self.characters = [dict(item) for item in (self.characters or ())]
        self.organizations = [
            dict(item) for item in (self.organizations or ())
        ]
        self.automata = [dict(item) for item in (self.automata or ())]
        self.environment = dict(self.environment or {})
        self.events = dict(self.events or {})
        self.playwright = dict(self.playwright or {})
        self.scenario = dict(self.scenario or {})
        self._character_index = {
            item.get("id"): item for item in self.characters if item.get("id")
        }
        self._faction_index = {
            item.get("id"): item for item in self.factions if item.get("id")
        }
        self._organization_index = {
            item.get("id"): item
            for item in self.organizations
            if item.get("id")
        }
        self._automaton_index = {
            item.get("id"): item for item in self.automata if item.get("id")
        }
        if not self.player_faction_id and self.factions:
            player = next(
                (item for item in self.factions if item.get("is_player")),
                self.factions[0],
            )
            self.player_faction_id = player.get("id", "")
        if not self.player_character_id and self.player_faction_id:
            faction = self._faction_index.get(self.player_faction_id, {})
            self.player_character_id = faction.get("leader_id", "")

    def faction(self, faction_id):
        return self._faction_index.get(str(faction_id or ""))

    def character(self, character_id):
        return self._character_index.get(str(character_id or ""))

    def organization(self, organization_id):
        return self._organization_index.get(str(organization_id or ""))

    def automaton(self, automaton_id):
        return self._automaton_index.get(str(automaton_id or ""))

    @property
    def player_faction(self):
        return self.faction(self.player_faction_id)

    @property
    def player_character(self):
        return self.character(self.player_character_id)

    @property
    def player_side(self):
        return _text(self.scenario.get("player_side"), "red")

    @property
    def enemy_side(self):
        return _text(self.scenario.get("enemy_side"), "blue")

    @property
    def enemy_faction(self):
        return next(
            (
                item
                for item in self.factions
                if item.get("side") == self.enemy_side
            ),
            None,
        )

    @property
    def player_organization(self):
        faction = self.player_faction or {}
        return self.organization(faction.get("organization_id"))

    def characters_for_side(self, side):
        return [item for item in self.characters if item.get("side") == side]

    def roster_by_side(self):
        by_id = self._character_index
        result = {}
        for unit in self.scenario.get("units") or ():
            side = unit.get("side")
            ids = unit.get("character_ids") or ()
            roster = [by_id[item] for item in ids if item in by_id]
            result.setdefault(side, []).append(roster)
        return result

    def summary(self):
        events = self.events.get("hooks") or []
        return {
            "preset_id": self.preset_id,
            "title": self.title,
            "seed": self.seed,
            "role_id": self.role.id,
            "player_faction_id": self.player_faction_id,
            "player_character_id": self.player_character_id,
            "factions": len(self.factions),
            "characters": len(self.characters),
            "organizations": len(self.organizations),
            "automata": len(self.automata),
            "environment_features": len(
                (self.environment.get("features") or {})
            ),
            "event_hooks": len(events),
            "companies": {
                side: len(items)
                for side, items in self.roster_by_side().items()
            },
        }

    def as_dict(self):
        return {
            "schema": self.schema,
            "template_id": self.template_id,
            "preset_id": self.preset_id,
            "title": self.title,
            "description": self.description,
            "seed": self.seed,
            "role_id": self.role.id,
            "role": self.role.as_dict(),
            "leadership": self.role.leadership,
            "player": {
                "role_id": self.role.id,
                "faction_id": self.player_faction_id,
                "character_id": self.player_character_id,
                "leadership": self.role.leadership,
            },
            "player_faction_id": self.player_faction_id,
            "player_character_id": self.player_character_id,
            "factions": list(self.factions),
            "characters": list(self.characters),
            "organizations": list(self.organizations),
            "automata": list(self.automata),
            "environment": self.environment,
            "events": self.events,
            "playwright": self.playwright,
            "scenario": self.scenario,
        }

    to_dict = as_dict

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise CampaignPresetError("пресет должен быть объектом")
        raw_role = data.get("role")
        if raw_role is None:
            role_id = data.get("role_id")
            if role_id:
                raw_role = {"id": role_id}
            else:
                raise CampaignPresetError("в пресете нет role/role_id")
        if isinstance(raw_role, str):
            raw_role = {"id": raw_role}
        if isinstance(raw_role, Mapping):
            role_id = raw_role.get("id") or data.get("role_id")
            if raw_role.get("label"):
                role = RoleSpec.from_data(raw_role)
            else:

                role = default_role_catalog().role(role_id)
        else:
            role = raw_role
        return cls(
            schema=data.get("schema", SCHEMA),
            template_id=data.get("template_id", ""),
            preset_id=data.get("preset_id") or data.get("id"),
            title=data.get("title") or data.get("preset_id") or "Кампания",
            description=data.get("description", ""),
            seed=data.get("seed", 0),
            role=role,
            player_faction_id=data.get("player_faction_id", ""),
            player_character_id=data.get("player_character_id", ""),
            factions=data.get("factions") or [],
            characters=data.get("characters") or [],
            organizations=data.get("organizations") or [],
            automata=data.get("automata") or [],
            environment=data.get("environment") or {},
            events=data.get("events") or {},
            playwright=data.get("playwright") or {},
            scenario=data.get("scenario") or {},
        )

    @classmethod
    def load(cls, path):
        path = Path(path)
        return cls.from_dict(_read_json(path))

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.as_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return path

    def __str__(self):
        return "CampaignPreset(%s, seed=%s, role=%s)" % (
            self.preset_id,
            self.seed,
            self.role.id,
        )


class CampaignPresetGenerator:

    def __init__(self, catalog=None, template=None, template_path=None):
        self.catalog = catalog or default_role_catalog()
        if template is None:
            template = load_template(template_path)
        self.template = _validate_template(dict(template))
        self.role_catalog = self.catalog

    def generate(
        self,
        role_id="faction_leader",
        seed=None,
        preset_id=None,
        player_faction_id=None,
    ):
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
        slots = template.get("faction_slots") or {}
        default_side = _text(
            slots.get("player", template.get("player_side")), "red"
        )
        options = []
        for side in _ordered_sides(template):
            cfg = template["factions"][side]
            organization = cfg.get("organization") or {}
            leader = PersonNameGenerator(seed=base_seed).generate_many(
                1,
                culture=_text(cfg.get("culture")),
                seed=base_seed + _stable_offset("names:%s" % side),
            )[0]
            options.append(
                {
                    "id": _text(cfg.get("id")),
                    "side": side,
                    "name": _text(cfg.get("name")),
                    "kind": _text(cfg.get("kind"), "automaton"),
                    "culture": _text(cfg.get("culture")),
                    "leader_name": leader.full,
                    "organization_name": _text(organization.get("name")),
                    "companies": max(0, _as_int(companies.get(side), 0)),
                    "goals": list(cfg.get("goals") or ()),
                    "assets": dict(cfg.get("assets") or {}),
                    "is_default": side == default_side,
                }
            )
        return options

    def _generate(self, role, seed, preset_id=None, player_faction_id=None):
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
            names = name_generator.generate_many(
                count * per_company,
                culture=_text(cfg.get("culture")),
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
            "place": "«Двойная переправа»",
            "object": "полевая печать",
            "cause": "первый залп на переправе",
            "consequence": "линия фронта дрогнула",
            "amount": "триста человек",
        }
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
    "load_template",
    "generate_preset",
]
