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


from .preset_support import (
    CampaignPresetError,
    SCHEMA,
    _as_float,
    _as_int,
    _as_mapping,
    _read_json,
    _round_mapping,
    _text,
)


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
    player_identity: Dict = field(default_factory=dict)
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
        self.player_identity = dict(self.player_identity or {})
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
    def avatar(self):
        """Явная ссылка на управляемого персонажа (P2).

        Собирается из пресета, поэтому не расходится с
        ``player_character_id``; режим по умолчанию — ``delegated``,
        чтобы лорные кампании и старые сейвы вели себя как раньше.
        """
        return avatar_from_preset(
            {
                "player_character_id": self.player_character_id,
                "player_faction_id": self.player_faction_id,
                "characters": self.characters,
            }
        )

    def select_player_character(self, character_id, control_mode="direct"):
        """Сделать управляемым любого персонажа своей стороны (P2).

        Лидер фракции остаётся лидером: меняется только тот, кем играет
        игрок. Это позволяет выбрать школьника или музыканта внутри
        фракции, не переписывая организации и не создавая «вторую игру».
        """
        record = self.character(character_id)
        if record is None:
            raise CampaignPresetError(
                "нет персонажа %r" % (character_id,)
            )
        side = _text(record.get("side"))
        if side and side != self.player_side:
            raise CampaignPresetError(
                "персонаж %r на стороне %r, а не %r"
                % (character_id, side, self.player_side)
            )
        mode = _text(control_mode, "direct").strip().lower()
        if mode not in ("direct", "delegated"):
            raise CampaignPresetError(
                "неизвестный режим управления %r" % (control_mode,)
            )
        for item in self.characters:
            item["is_player"] = item.get("id") == character_id
        record["control_mode"] = mode
        self.player_character_id = _text(character_id)
        self.player_faction_id = _text(record.get("faction_id")) or (
            self.player_faction_id
        )
        return self

    def available_player_characters(self):
        """Кандидаты в аватар: все персонажи стороны игрока."""
        side = self.player_side
        return [
            item
            for item in self.characters
            if _text(item.get("side")) == side
        ]

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

    @property
    def player_role_title(self):
        """Титул героя с учётом выбранного пола.

        До редактора личности возвращается форма из данных роли; после
        ``apply_player_identity`` — женская или мужская форма фракции.
        """
        faction = self.player_faction or {}
        return _text(faction.get("role_title"), self.role.label)

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

    def apply_player_identity(self, identity):
        """Перенести личность героя на персонажа и его фракцию.

        Личность задаётся до запуска кампании и меняет только игрового
        персонажа: имя, биографию, потребности и черты. Посты, активы и
        баланс фракций при этом не трогаются, поэтому один и тот же seed
        остаётся детерминированным.

        Новое (P1/P2): если в ``identity`` передан ``archetype_id`` и
        каталог архетипов ``configs/characters/archetypes.json`` содержит
        запись, на игрового персонажа переносятся ``social_layer``,
        ``start_offices``, ``start_faction`` и ``storyline_tags``
        архетипа. Если каталога нет, поведение прежнее.
        """
        identity = dict(identity or {})
        if not identity:
            return self
        player = self.player_character
        if not player:
            return self
        name = _text(identity.get("name")).strip()
        if not name:
            name = _text(player.get("name"), "Лидер фракции")
        player["name"] = name
        name_data = player.get("name_data")
        if isinstance(name_data, Mapping):
            name_data = dict(name_data)
            name_data["full"] = name
            player["name_data"] = name_data

        for key in (
            "gender",
            "gender_label",
            "origin",
            "origin_label",
            "vocation",
            "vocation_label",
            "value",
            "value_label",
            "flaw",
            "flaw_label",
            "trait",
            "trait_label",
            "summary",
        ):
            if key in identity:
                player[key] = identity.get(key)
        biography = _text(identity.get("biography"))
        if biography:
            player["biography"] = biography

        needs = {
            str(key): _as_float(value, 0.0)
            for key, value in _as_mapping(player.get("needs")).items()
        }
        for key, delta in _as_mapping(identity.get("needs")).items():
            key = str(key)
            if key not in needs:
                continue
            needs[key] = max(0.0, min(1.0, needs[key] + _as_float(delta)))
        player["needs"] = _round_mapping(needs)

        personality = {
            str(key): _as_float(value, 0.0)
            for key, value in _as_mapping(
                player.get("personality")
            ).items()
        }
        for key, delta in _as_mapping(identity.get("traits")).items():
            key = str(key)
            if key not in personality:
                continue
            personality[key] = max(
                0.0,
                min(1.0, personality[key] + _as_float(delta)),
            )
        player["personality"] = _round_mapping(personality)

        archetype_id = _text(identity.get("archetype_id")).strip()
        if archetype_id:
            archetype = _apply_archetype(player, archetype_id)
            if archetype is not None:
                player["archetype_id"] = archetype.id

        control_mode = _text(identity.get("control_mode")).strip().lower()
        if control_mode in ("direct", "delegated"):
            player["control_mode"] = control_mode
        office_id = _text(identity.get("office_id")).strip()
        if office_id:
            player["office_id"] = office_id
        scene_id = _text(identity.get("scene_id")).strip()
        if scene_id:
            player["scene_id"] = scene_id

        is_female = str(identity.get("gender") or "").strip().lower() in (
            "female",
            "f",
            "woman",
            "женщина",
        )

        def _gendered_title(record, base_key, female_key, current_key):
            """Выбрать титул по полу, не теряя исходную мужскую форму."""
            base = _text(record.get(base_key))
            if not base:
                base = _text(record.get(current_key))
                record[base_key] = base
            female = _text(record.get(female_key), base)
            return female if is_female else base

        faction = self.faction(player.get("faction_id"))
        if faction is not None:
            role_title = _gendered_title(
                faction,
                "role_title_base",
                "role_title_female",
                "role_title",
            )
            if role_title:
                faction["role_title"] = role_title
                player["role_title"] = role_title
        if faction is not None and player.get("is_faction_leader"):
            faction["leader_name"] = name
            organization = self.organization(
                faction.get("organization_id")
            )
            if organization is not None:
                organization["leader_name"] = name
                leader_title = _gendered_title(
                    organization,
                    "leader_title_base",
                    "leader_title_female",
                    "leader_title",
                )
                if leader_title:
                    organization["leader_title"] = leader_title
                runtime = dict(organization.get("runtime") or {})
                runtime["leader_id"] = name
                if leader_title:
                    runtime["leader_title"] = leader_title
                organization["runtime"] = runtime
        self.player_identity = identity
        return self

    def summary(self):
        events = self.events.get("hooks") or []
        avatar = self.avatar
        return {
            "preset_id": self.preset_id,
            "title": self.title,
            "seed": self.seed,
            "role_id": self.role.id,
            "player_faction_id": self.player_faction_id,
            "player_character_id": self.player_character_id,
            "avatar": avatar.as_dict() if avatar is not None else None,
            "player_identity": dict(self.player_identity),
            "factions": len(self.factions),
            "characters": len(self.characters),
            "organizations": len(self.organizations),
            "automata": len(self.automata),
            "environment_features": len(
                (self.environment.get("features") or {})
            ),
            "event_hooks": len(events),
            "mode": self.scenario.get("mode", "military"),
            "groups": dict(self.scenario.get("groups") or {}),
            "populations": dict(self.scenario.get("populations") or {}),
            "characters_per_faction": int(
                self.scenario.get("characters_per_faction") or 0
            ),
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
            "avatar": (
                self.avatar.as_dict() if self.avatar is not None else None
            ),
            "player_identity": dict(self.player_identity),
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
            player_identity=data.get("player_identity") or {},
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


def _apply_archetype(player, archetype_id):
    """Перенести стартовую точку архетипа на игрового персонажа.

    Мутирует ``player`` только по ключам архетипа. Ошибки каталога
    (нет файла, битый JSON) не роняют кампанию: возвращается ``None``, и
    ``apply_player_identity`` продолжает без архетипа.
    """
    try:
        from .identity import load_archetypes_catalog

        catalog = load_archetypes_catalog()
    except Exception:
        return None
    if catalog is None:
        return None
    try:
        archetype = catalog.require(archetype_id)
    except Exception:
        return None
    player["archetype"] = archetype.id
    player["social_layer"] = archetype.social_layer
    player["start_offices"] = list(archetype.start_offices)
    player["start_faction"] = archetype.start_faction
    player["storyline_tags"] = list(archetype.storyline_tags)
    player["archetype_scenes"] = list(archetype.scenes)
    if archetype.priority_needs:
        player["archetype_priority_needs"] = list(
            archetype.priority_needs
        )
    if archetype.needs:
        needs = {
            str(key): _as_float(value, 0.0)
            for key, value in _as_mapping(player.get("needs")).items()
        }
        for key, delta in archetype.needs.items():
            key = str(key)
            if key not in needs:
                continue
            needs[key] = max(0.0, min(1.0, needs[key] + _as_float(delta)))
        player["needs"] = _round_mapping(needs)
    if archetype.traits:
        personality = {
            str(key): _as_float(value, 0.0)
            for key, value in _as_mapping(
                player.get("personality")
            ).items()
        }
        for key, delta in archetype.traits.items():
            key = str(key)
            if key not in personality:
                continue
            personality[key] = max(
                0.0,
                min(1.0, personality[key] + _as_float(delta)),
            )
        player["personality"] = _round_mapping(personality)
        player["archetype_traits"] = dict(archetype.traits)
    return archetype
