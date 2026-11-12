from __future__ import annotations

"""Кампания взаимодействия автоматов.

Модуль не знает о «красных» и «синих», ротах или отделениях. Единица
симуляции — фракция-автомат: у неё есть состояние (assets), организация
участников (``OrganizationRuntime``) и набор работ, которыми она действует
на другие автоматы. Победа и поражение задаются данными шаблона.
"""

from dataclasses import dataclass, field
import logging
import math
import random
from typing import Dict, Iterable, List, Mapping, Optional

import warfare as W
from organizations.model import OrganizationParameters
from organizations.runtime import OrganizationRuntime
from systems.events import EventEngine, EventError
from .conditions import asset_reason, check_conditions
from .effects import apply_effects

from .defaults import default_dict, default_list, default_section
from .errors import CampaignError
from .faction_state import (
    CONTEXT_MAX,
    CONTEXT_MIN,
    DerivedAssets,
    apply_asset_delta,
    asset_keys,
    bump_context,
    derived_asset,
    derived_assets,
    relax_context,
    set_asset_value,
)
from .fractal import (
    ORGAN_MIN_WEIGHT,
    ORGAN_MODEL_DEFAULTS,
    OrganRuntime,
    damage_organs,
    network_density,
    organ_composite,
    organ_degrees,
    organ_links,
    readiness_scale,
    spread_organ_effect,
    strengthen_organ,
    tick_organs,
    validate_organ_network,
)
from .projections import (
    SCHEMA_VERSION,
    ensure_supported_snapshot,
    stamp_snapshot,
)
from .state_machine import (
    StateMachine,
    StateMachineCatalog,
    StateMachineError,
    load_catalog,
)

logger = logging.getLogger(__name__)


class AutomataCampaignError(CampaignError):
    pass


def _subfaction_organ(organs, organ_id):
    for organ in organs:
        if str(organ.id) == str(organ_id):
            return organ
    return None


def _build_subfactions(faction, organs, interactions):
    """Собрать подфракции и связать их органы с родителем."""
    result = []
    for record in _as_mapping(faction).get("subfactions") or ():
        if not isinstance(record, Mapping):
            continue
        sub_id = str(record.get("id") or "").strip()
        if not sub_id:
            continue
        organ_ids = []
        for item in record.get("organ_ids") or ():
            organ_id = str(item or "").strip()
            if not organ_id:
                continue
            organ = _subfaction_organ(organs, organ_id)
            if organ is not None:
                organ.subfaction_id = sub_id
            if organ_id not in organ_ids:
                organ_ids.append(organ_id)
        for item in record.get("organs") or ():
            if isinstance(item, Mapping):
                organ = OrganRuntime.from_record(
                    item, interactions=interactions
                )
                if organ is None:
                    continue
                organ.subfaction_id = sub_id
                existing = _subfaction_organ(organs, organ.id)
                if existing is None:
                    organs.append(organ)
                else:
                    existing.subfaction_id = sub_id
                if organ.id not in organ_ids:
                    organ_ids.append(organ.id)
                continue
            organ_id = str(item or "").strip()
            organ = _subfaction_organ(organs, organ_id)
            if organ is not None:
                organ.subfaction_id = sub_id
            if organ_id and organ_id not in organ_ids:
                organ_ids.append(organ_id)
        result.append(
            SubfactionRuntime(
                id=sub_id,
                label=str(
                    record.get("label") or record.get("name") or sub_id
                ),
                share=_clamp(record.get("share", 0.0)),
                assets={
                    str(key): _clamp(value)
                    for key, value in _as_mapping(
                        record.get("assets")
                    ).items()
                },
                organ_ids=organ_ids,
                machine_id=str(record.get("automaton") or ""),
            )
        )
    return result


MODEL_DEFAULTS = default_dict("automata_model")
MODEL_DEFAULTS.update(ORGAN_MODEL_DEFAULTS)

DEFAULT_ACTIONS_PER_TURN = int(default_section("actions_per_turn"))
DEFAULT_RUN_TURNS = int(default_section("run_turns_default"))
EVENT_LOG_LIMIT = int(default_section("event_log_limit"))
SNAPSHOT_TAIL = int(default_section("snapshot_tail"))
REALTIME_DEFAULTS = default_dict("realtime")
ASSET_LABELS = default_dict("asset_labels")
PRESET_DEFAULTS = default_dict("preset_defaults")
ORGANIZATION_RUNTIME_DEFAULTS = dict(
    PRESET_DEFAULTS["organization_runtime"]
)

DEFAULT_AUTOMATON_INTERACTIONS = default_list("automaton_interactions")
DEFAULT_CHARACTER_INTERACTIONS = default_list("character_interactions")


def _number(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(result) or math.isinf(result):
        return float(default)
    return result


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, _number(value, low)))


def _sigmoid(value):
    value = max(-60.0, min(60.0, _number(value, 0.0)))
    return 1.0 / (1.0 + math.exp(-value))


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _nested_tuple(value):
    """Вернуть вложенные списки JSON обратно в кортежи для ``random``."""
    if isinstance(value, (list, tuple)):
        return tuple(_nested_tuple(item) for item in value)
    return value


def _organization_parameters(data):
    """Собрать параметры организации, сохраняя значения по умолчанию."""
    overrides = _as_mapping(data)
    defaults = OrganizationParameters()
    values = {}
    for name in OrganizationParameters.__dataclass_fields__:
        if name not in overrides:
            continue
        default = getattr(defaults, name)
        if isinstance(default, int) and not isinstance(default, bool):
            values[name] = max(1, int(_number(overrides[name], default)))
        else:
            values[name] = _number(overrides[name], default)
    try:
        return OrganizationParameters(**values)
    except (TypeError, ValueError):
        return defaults


def _preset_data(preset):
    if preset is None:
        raise AutomataCampaignError("не передан пресет кампании")
    if hasattr(preset, "as_dict"):
        return dict(preset.as_dict())
    if isinstance(preset, Mapping):
        return dict(preset)
    raise AutomataCampaignError("не удалось распознать пресет кампании")


def _character_from_record(record, seed):
    character = W.Character(
        record.get("name") or "Участник",
        record.get("side"),
        seed=int(record.get("seed", seed)),
        archetype=record.get("archetype") or "citizen",
        role=record.get("post_id") or record.get("role") or "citizen",
    )
    for need, value in _as_mapping(record.get("needs")).items():
        if need in character.needs:
            character.needs[need] = _clamp(value)
    personality = _as_mapping(record.get("personality"))
    for trait, value in personality.items():
        if trait in character.personality.values:
            character.personality.values[trait] = _clamp(value)
    beliefs = record.get("beliefs")
    intentions = record.get("intentions")
    if beliefs or intentions:
        character.bdi.seed(beliefs=beliefs, intentions=intentions)
    character.desires = character.weighted_urgency()
    if record.get("morale") is not None:
        character.morale = max(
            0.0,
            min(
                100.0,
                _number(record.get("morale"), character.morale),
            ),
        )
    character.campaign_id = record.get("id")
    character.campaign_faction_id = record.get("faction_id")
    character.deliberate_target = str(
        record.get("deliberate_target") or ""
    )
    divisions = _as_mapping(record.get("divisions"))
    if divisions and getattr(character, "divisions", None) is not None:
        try:
            character.divisions.update(divisions)
        except Exception:
            pass
    character.campaign_post = record.get("post")
    character.campaign_post_id = record.get("post_id", "")
    character.campaign_organ_id = record.get("organ_id", "")
    character.campaign_role_id = record.get("campaign_role_id", "")
    character.campaign_leader = bool(record.get("is_faction_leader"))
    character.campaign_is_player = bool(record.get("is_player"))
    character.campaign_cooldowns = {}
    return character


@dataclass
class SubfactionRuntime:
    """Подсистема внутри фракции: своя доля и свои активы."""

    id: str
    label: str = ""
    share: float = 0.0
    assets: Dict[str, float] = field(default_factory=dict)
    organ_ids: List[str] = field(default_factory=list)
    machine_id: str = ""

    def asset(self, key, default=0.0):
        return _clamp(_number(self.assets.get(str(key)), default))

    def add_asset(self, key, delta):
        key = str(key)
        self.assets[key] = _clamp(
            _number(self.assets.get(key)) + _number(delta)
        )
        return self.assets[key]

    def snapshot(self):
        return {
            "id": self.id,
            "label": self.label,
            "share": round(_clamp(self.share), 6),
            "assets": {
                str(key): round(_clamp(value), 6)
                for key, value in self.assets.items()
            },
            "organ_ids": list(self.organ_ids),
            "machine_id": self.machine_id,
        }


@dataclass
class FactionRuntime:
    side: str
    id: str
    name: str
    record: dict
    characters: list = field(default_factory=list)
    organization: Optional[OrganizationRuntime] = None
    context: Dict[str, float] = field(default_factory=dict)
    baseline_context: Dict[str, float] = field(default_factory=dict)
    baseline_assets: Dict[str, float] = field(default_factory=dict)
    flags: Dict[str, object] = field(default_factory=dict)
    income: Dict[str, float] = field(default_factory=dict)
    score_assets: Dict[str, float] = field(default_factory=dict)
    action_uses: Dict[str, int] = field(default_factory=dict)
    actions: List[dict] = field(default_factory=list)
    organs: List[OrganRuntime] = field(default_factory=list)
    subfactions: List[SubfactionRuntime] = field(default_factory=list)
    automaton_interactions: List[dict] = field(default_factory=list)
    character_interactions: List[dict] = field(default_factory=list)
    character_cooldowns: Dict[str, Dict[str, int]] = field(
        default_factory=dict
    )
    cooldowns: Dict[str, int] = field(default_factory=dict)
    low_streaks: Dict[str, int] = field(default_factory=dict)
    organization_snapshot: dict = field(default_factory=dict)
    dissolved: bool = False

    @property
    def assets(self):
        """Производные активы: BDI + органы + контекст взаимодействий."""
        return DerivedAssets(self)

    @assets.setter
    def assets(self, values):
        for key, value in _as_mapping(values).items():
            self.set_asset(key, value)

    def asset(self, key, default=0.0):
        if str(key) in asset_keys(self):
            return derived_asset(self, key, default)
        return _number(default, default)

    def set_asset(self, key, value):
        """Совместимая запись: подбирает контекст под производное значение."""
        return set_asset_value(self, key, value)

    def add_asset(self, key, delta):
        """Разложить изменение актива в BDI, органы и контекст сети."""
        return apply_asset_delta(self, key, delta)

    def bump_context(self, key, delta):
        return bump_context(self, key, delta)

    def derived_assets(self):
        return derived_assets(self)

    def relax_context(self, rate):
        return relax_context(self, rate)

    def action(self, action_id):
        for action in self.actions:
            if str(action.get("id")) == str(action_id):
                return action
        return None

    def organ(self, organ_id):
        for organ in self.organs:
            if str(organ.id) == str(organ_id):
                return organ
        return None

    def subfaction(self, subfaction_id):
        for item in self.subfactions:
            if str(item.id) == str(subfaction_id):
                return item
        return None

    def character(self, character_id):
        for character in self.characters:
            if str(getattr(character, "campaign_id", "")) == str(character_id):
                return character
        return None

    def character_snapshot(self, character):
        if character is None:
            return None
        values = getattr(character.personality, "values", {})
        return {
            "id": str(getattr(character, "campaign_id", "") or ""),
            "name": str(getattr(character, "name", "") or ""),
            "post": str(getattr(character, "campaign_post", "") or ""),
            "post_id": str(getattr(character, "campaign_post_id", "") or ""),
            "organ_id": str(
                getattr(character, "campaign_organ_id", "") or ""
            ),
            "morale": round(
                _clamp(_number(character.morale) / 100.0) * 100.0,
                3,
            ),
            "force": round(float(getattr(character, "force", 0.0)), 6),
            "energy": round(
                float(getattr(character, "energy_pool", 0.0)), 6
            ),
            "needs": {
                str(key): round(_clamp(value), 6)
                for key, value in character.needs.items()
            },
            "desires": {
                str(key): round(_clamp(value), 6)
                for key, value in getattr(
                    character, "desires", {}
                ).items()
            },
            "intention": (
                character.bdi.latest_intention().as_dict()
                if getattr(character, "bdi", None) is not None
                and character.bdi.latest_intention() is not None
                else None
            ),
            "beliefs": (
                [item.as_dict() for item in character.bdi.beliefs]
                if getattr(character, "bdi", None) is not None
                else []
            ),
            "conditions": (
                {
                    str(key): round(_clamp(value), 6)
                    for key, value in character.bdi.conditions.items()
                }
                if getattr(character, "bdi", None) is not None
                else {}
            ),
            "divisions": (
                character.divisions.as_dict()
                if getattr(character, "divisions", None) is not None
                else {}
            ),
            "personality": {
                str(key): round(_clamp(value), 6)
                for key, value in values.items()
            },
            "is_leader": bool(
                getattr(character, "campaign_leader", False)
            ),
            "is_player": bool(
                getattr(character, "campaign_is_player", False)
            ),
            "dead": bool(
                getattr(
                    character,
                    "is_dead",
                    getattr(character, "dead", False),
                )
            ),
            "cooldowns": {
                str(key): int(value)
                for key, value in _as_mapping(
                    getattr(character, "campaign_cooldowns", {})
                ).items()
            },
        }

    def character_options(self):
        return [
            item
            for item in (
                self.character_snapshot(character)
                for character in self.characters
            )
            if item is not None
        ]

    def organ_average(self):
        """Средняя целостность органов — самоподобный показатель фракции."""
        if not self.organs:
            return 0.5
        total_weight = sum(
            max(ORGAN_MIN_WEIGHT, organ.weight) for organ in self.organs
        )
        return sum(
            organ.integrity * max(ORGAN_MIN_WEIGHT, organ.weight)
            for organ in self.organs
        ) / total_weight

    def score(self):
        """Взвешенная оценка целей фракции из данных шаблона.

        Без ``score_assets`` остаётся среднее по всем активам — совместимый
        путь для старых пресетов. Веса задаются в данных, потому что у
        Империи, Республики, культа и корпорации разные цели.
        """
        weights = {
            str(key): _number(value, 0.0)
            for key, value in self.score_assets.items()
        }
        total_weight = sum(abs(value) for value in weights.values())
        if total_weight <= 0.0:
            values = list(self.assets.values())
            if not values:
                return 0.0
            return sum(values) / float(len(values))
        return sum(
            weight * self.asset(key) for key, weight in weights.items()
        ) / total_weight

    def progress(self):
        """Насколько фракция продвинулась к своим целям от старта.

        Абсолютные активы дают преимущество тому, кто уже силён. Для
        кампаний, где игрок заведомо слабее в ресурсах, сравнивается
        изменение взвешенной цели. ``0.5`` — стартовый уровень.
        """
        weights = {
            str(key): _number(value, 0.0)
            for key, value in self.score_assets.items()
        }
        total_weight = sum(abs(value) for value in weights.values())
        if total_weight <= 0.0:
            return 0.5
        delta = sum(
            weight
            * (
                self.asset(key)
                - _number(self.baseline_assets.get(key), 0.0)
            )
            for key, weight in weights.items()
        ) / total_weight
        return _clamp(0.5 + delta)

    def snapshot(self):
        analysis = self.organization.analysis if self.organization else None
        stored = self.organization_snapshot or {}
        original = len(self.characters)
        if analysis is not None:
            initial = original or int(analysis.initial_count)
            active = int(analysis.active_count)
            willing_count = int(analysis.willing_count)
            willing_share = (
                willing_count / float(initial) if initial else 0.0
            )
        else:
            initial = int(_number(stored.get("initial_count"), original))
            active = int(_number(stored.get("active_count"), initial))
            willing_count = int(_number(stored.get("willing_count"), active))
            willing_share = _clamp(
                stored.get(
                    "willing_share",
                    willing_count / float(initial) if initial else 0.0,
                )
            )
        links = organ_links(self.organs)
        degrees = organ_degrees(self.organs)
        organ_snapshots = []
        for organ in self.organs:
            item = organ.snapshot()
            item["links"] = list(links.get(organ.id, ()))
            item["degree"] = int(degrees.get(organ.id, 0))
            organ_snapshots.append(item)
        return {
            "side": self.side,
            "id": self.id,
            "name": self.name,
            "role_title": str(self.record.get("role_title") or ""),
            "assets": {
                key: round(_clamp(value), 6)
                for key, value in self.assets.items()
            },
            "score": round(self.score(), 6),
            "progress": round(self.progress(), 6),
            "score_assets": {
                key: round(_number(value), 6)
                for key, value in self.score_assets.items()
            },
            "actions": [str(item.get("id")) for item in self.actions],
            "cooldowns": {
                key: int(value) for key, value in self.cooldowns.items()
            },
            "action_uses": {
                key: int(value) for key, value in self.action_uses.items()
            },
            "dissolved": bool(self.dissolved),
            "organs": organ_snapshots,
            "subfactions": [
                item.snapshot() for item in self.subfactions
            ],
            "characters": self.character_options(),
            "organ_integrity": round(self.organ_average(), 6),
            "network_density": round(network_density(self.organs), 6),
            "context": {
                key: round(
                    _clamp(value, CONTEXT_MIN, CONTEXT_MAX), 6
                )
                for key, value in self.context.items()
            },
            "flags": dict(self.flags),
            "organization": dict(stored),
            "willing_share": round(_clamp(willing_share), 6),
            "willing_count": int(willing_count),
            "active_count": int(active),
            "initial_count": int(initial),
            "priority_need": (
                analysis.priority_need
                if analysis
                else stored.get("priority_need")
            ),
            "archetype": (
                analysis.archetype
                if analysis
                else stored.get("archetype", "—")
            ),
            "level": (
                int(analysis.level)
                if analysis
                else int(_number(stored.get("level"), 0))
            ),
        }


class AutomataCampaign:

    def __init__(self, preset, seed=None, snapshot=None):
        data = _preset_data(preset)
        self.data = data
        scenario = _as_mapping(data.get("scenario"))
        self.mode = str(scenario.get("mode") or "automata")
        self.title = str(data.get("title") or "Кампания автоматов")
        self.preset_id = str(
            data.get("preset_id") or data.get("template_id") or ""
        )
        self.seed = int(
            _number(
                seed if seed is not None else data.get("seed"),
                7,
            )
        )
        self.rng = random.Random(self.seed)
        turns = scenario.get("turns")
        try:
            turns_value = int(turns) if turns is not None else 0
        except (TypeError, ValueError):
            turns_value = 0
        self.max_turns = turns_value if turns_value > 0 else None
        self.actions_per_turn = max(
            1,
            int(
                _number(
                    scenario.get("actions_per_turn"),
                    DEFAULT_ACTIONS_PER_TURN,
                )
            ),
        )
        self.actions_left = 0
        self._turn_active = False
        self.realtime = dict(REALTIME_DEFAULTS)
        self.realtime.update(
            {
                str(key): value
                for key, value in _as_mapping(
                    scenario.get("realtime")
                ).items()
            }
        )
        speeds = [
            max(1, int(_number(value, 1)))
            for value in (self.realtime.get("speeds") or (1,))
        ]
        self.speed_levels = sorted(set(speeds)) or [1]
        self.speed = 1
        self.elapsed = 0.0
        self._action_progress = 0.0
        self._ai_progress = 0.0
        self._round_progress = 0.0
        self.score_streak = 0
        self.score_streak_side = None
        self.player_side = str(scenario.get("player_side") or "red")
        self.rival_side = str(scenario.get("enemy_side") or "blue")
        self.model = dict(MODEL_DEFAULTS)
        self.model.update(
            {
                str(key): _number(value, self.model.get(str(key), 0.0))
                for key, value in _as_mapping(scenario.get("model")).items()
            }
        )
        self.outcome_rules = dict(_as_mapping(scenario.get("outcome")))
        self.upkeep = {
            str(key): _number(value, 0.0)
            for key, value in _as_mapping(scenario.get("upkeep")).items()
        }
        self._rivals = {
            str(key): str(value)
            for key, value in _as_mapping(scenario.get("rivals")).items()
        }
        self.turn = 0
        self.outcome = None
        self.finished = False
        self.log = []
        self.events = []
        self.story_events = []
        self.history = []
        self.last_organ_result = None
        self.last_automaton_result = None
        self.last_character_result = None
        self.factions: Dict[str, FactionRuntime] = {}
        self._character_index = {}
        self._story_progress = 0.0
        self.machine_catalog = self._load_machine_catalog()
        self.faction_machines: Dict[str, StateMachine] = {}
        self.organ_machines: Dict[str, Dict[str, StateMachine]] = {}
        self.subfaction_machines: Dict[
            str, Dict[str, StateMachine]
        ] = {}
        try:
            self.story_engine = EventEngine(seed=self.seed)
        except EventError:
            self.story_engine = None
        except Exception:
            logger.exception("не удалось поднять движок событий")
            self.story_engine = None
        self._build_factions(data)
        self._build_machines()
        if snapshot:
            self.load_snapshot(snapshot)

    @staticmethod
    def _load_machine_catalog():
        """Прочитать исполняемые автоматы из ``configs/automata``."""
        try:
            return load_catalog()
        except (OSError, StateMachineError, ValueError) as error:
            logger.warning("Автоматы кампании не загружены: %s", error)
            return StateMachineCatalog()

    def _build_machines(self):
        """Создать рантайм автоматов для фракций, подсистем и органов."""
        self.faction_machines = {}
        self.organ_machines = {}
        self.subfaction_machines = {}
        faction_definition = self.machine_catalog.first("faction")
        organ_definition = self.machine_catalog.first("organ")
        subfaction_definition = self.machine_catalog.first("subfaction")
        for side, faction in self.factions.items():
            if faction_definition is not None:
                self.faction_machines[side] = StateMachine(
                    faction_definition
                )
            subs = {}
            for subfaction in faction.subfactions:
                definition = None
                if subfaction.machine_id:
                    definition = self.machine_catalog.get(
                        subfaction.machine_id
                    )
                definition = definition or subfaction_definition
                if definition is not None:
                    subs[subfaction.id] = StateMachine(definition)
            if subs:
                self.subfaction_machines[side] = subs
            if organ_definition is None:
                continue
            machines = {}
            for organ in faction.organs:
                machines[str(organ.id)] = StateMachine(organ_definition)
            if machines:
                self.organ_machines[side] = machines

    def _machine_context(self, faction, organ=None, subfaction=None):
        character = faction.characters[0] if faction.characters else None
        context = {
            "faction": faction,
            "character": character,
            "turn": self.turn,
        }
        if organ is not None:
            context["organ"] = organ
        if subfaction is not None:
            context["subfaction"] = subfaction
        return context

    def _tick_machines(self):
        """Продвинуть исполняемые автоматы на один тик.

        Переходы читают состояние; эффекты состояний проходят через
        ``campaign/effects.py``. События сюда не попадают.
        """
        for side, machine in self.faction_machines.items():
            faction = self.factions.get(side)
            if faction is None or faction.dissolved:
                continue
            machine.tick(
                self._machine_context(faction), actor=faction
            )
        for side, machines in self.subfaction_machines.items():
            faction = self.factions.get(side)
            if faction is None or faction.dissolved:
                continue
            for subfaction in faction.subfactions:
                machine = machines.get(subfaction.id)
                if machine is None:
                    continue
                machine.tick(
                    self._machine_context(faction, subfaction=subfaction),
                    actor=faction,
                )
        for side, machines in self.organ_machines.items():
            faction = self.factions.get(side)
            if faction is None:
                continue
            for organ in faction.organs:
                machine = machines.get(str(organ.id))
                if machine is None or organ.integrity <= 0.0:
                    continue
                machine.tick(
                    self._machine_context(faction, organ),
                    actor=faction,
                )

    def _machines_snapshot(self):
        return {
            "factions": {
                side: machine.to_dict()
                for side, machine in self.faction_machines.items()
            },
            "subfactions": {
                side: {
                    sub_id: machine.to_dict()
                    for sub_id, machine in machines.items()
                }
                for side, machines in self.subfaction_machines.items()
            },
            "organs": {
                side: {
                    organ_id: machine.to_dict()
                    for organ_id, machine in machines.items()
                }
                for side, machines in self.organ_machines.items()
            },
        }

    def _restore_machines(self, data):
        data = _as_mapping(data)
        for side, payload in _as_mapping(
            data.get("factions")
        ).items():
            machine = self.faction_machines.get(str(side))
            if machine is None:
                continue
            try:
                self.faction_machines[str(side)] = StateMachine.from_dict(
                    payload, machine.definition
                )
            except (StateMachineError, ValueError) as error:
                logger.warning(
                    "Автомат фракции %s не восстановлен: %s",
                    side,
                    error,
                )
        for side, entries in _as_mapping(
            data.get("subfactions")
        ).items():
            machines = self.subfaction_machines.get(str(side), {})
            for sub_id, payload in _as_mapping(entries).items():
                machine = machines.get(str(sub_id))
                if machine is None:
                    continue
                try:
                    machines[str(sub_id)] = StateMachine.from_dict(
                        payload, machine.definition
                    )
                except (StateMachineError, ValueError) as error:
                    logger.warning(
                        "Автомат подфракции %s/%s не восстановлен: %s",
                        side,
                        sub_id,
                        error,
                    )
        for side, entries in _as_mapping(data.get("organs")).items():
            machines = self.organ_machines.get(str(side), {})
            for organ_id, payload in _as_mapping(entries).items():
                machine = machines.get(str(organ_id))
                if machine is None:
                    continue
                try:
                    machines[str(organ_id)] = StateMachine.from_dict(
                        payload, machine.definition
                    )
                except (StateMachineError, ValueError) as error:
                    logger.warning(
                        "Автомат органа %s/%s не восстановлен: %s",
                        side,
                        organ_id,
                        error,
                    )

    def _build_factions(self, data):
        characters = list(data.get("characters") or ())
        organizations = {
            str(item.get("id")): item
            for item in (data.get("organizations") or ())
            if item.get("id")
        }
        for index, faction in enumerate(data.get("factions") or ()):
            if not isinstance(faction, Mapping):
                continue
            side = str(faction.get("side") or "")
            if not side:
                continue
            faction_id = str(faction.get("id") or side)
            own_records = [
                item for item in characters if item.get("side") == side
            ]
            specs = []
            for record in own_records:
                spec = _character_from_record(
                    record,
                    self.seed + index * 1009 + len(specs) * 17,
                )
                specs.append(spec)
                self._character_index[str(record.get("id"))] = spec
            organization_id = str(faction.get("organization_id") or "")
            organization_record = organizations.get(organization_id, {})
            runtime_cfg = _as_mapping(organization_record.get("runtime"))
            leader = next(
                (
                    item
                    for item in own_records
                    if item.get("is_faction_leader")
                ),
                own_records[0] if own_records else {},
            )
            parameters = _organization_parameters(
                runtime_cfg.get("parameters")
            )
            organization = None
            if specs:
                organization = OrganizationRuntime(
                    name=str(
                        organization_record.get("name")
                        or faction.get("name")
                        or faction_id
                    ),
                    side=side,
                    characters=specs,
                    parameters=parameters,
                    complete_weight=_clamp(
                        runtime_cfg.get(
                            "complete_weight",
                            PRESET_DEFAULTS["organization_complete_weight"],
                        )
                    ),
                    leader_id=str(
                        runtime_cfg.get("leader_id")
                        or leader.get("name")
                        or ""
                    )
                    or None,
                    satisfaction_per_tick=_number(
                        runtime_cfg.get("satisfaction_per_tick"),
                        ORGANIZATION_RUNTIME_DEFAULTS["satisfaction_per_tick"],
                    ),
                    contribution_cost=_number(
                        runtime_cfg.get("contribution_cost"),
                        ORGANIZATION_RUNTIME_DEFAULTS["contribution_cost"],
                    ),
                    coercion_factor=_number(
                        runtime_cfg.get("coercion_factor"),
                        ORGANIZATION_RUNTIME_DEFAULTS["coercion_factor"],
                    ),
                    leader_morale_bonus=_number(
                        runtime_cfg.get("leader_morale_bonus"),
                        ORGANIZATION_RUNTIME_DEFAULTS["leader_morale_bonus"],
                    ),
                    allow_rejoin=bool(
                        runtime_cfg.get(
                            "allow_rejoin",
                            ORGANIZATION_RUNTIME_DEFAULTS["allow_rejoin"],
                        )
                    ),
                    jitter_salt=organization_id or faction_id,
                )
            assets = {
                str(key): _clamp(value)
                for key, value in _as_mapping(faction.get("assets")).items()
            }
            organ_interactions = [
                dict(item)
                for item in (faction.get("organ_interactions") or ())
                if isinstance(item, Mapping) and item.get("id")
            ]
            character_interactions = [
                dict(item)
                for item in (faction.get("character_interactions") or ())
                if isinstance(item, Mapping) and item.get("id")
            ]
            if not character_interactions:
                character_interactions = [
                    dict(item) for item in DEFAULT_CHARACTER_INTERACTIONS
                ]
            automaton_interactions = [
                dict(item)
                for item in (faction.get("automaton_interactions") or ())
                if isinstance(item, Mapping) and item.get("id")
            ]
            if not automaton_interactions:
                automaton_interactions = [
                    dict(item) for item in DEFAULT_AUTOMATON_INTERACTIONS
                ]
            organs = []
            for organ_record in faction.get("organs") or ():
                if not isinstance(organ_record, Mapping):
                    continue
                organ = OrganRuntime.from_record(
                    organ_record, interactions=organ_interactions
                )
                if organ is not None:
                    organs.append(organ)
            subfactions = _build_subfactions(
                faction, organs, organ_interactions
            )
            network_problems = validate_organ_network(organs)
            if network_problems:
                raise AutomataCampaignError(
                    "%s: %s"
                    % (faction_id, "; ".join(network_problems))
                )
            runtime = FactionRuntime(
                side=side,
                id=faction_id,
                name=str(faction.get("name") or faction_id),
                record=dict(faction),
                characters=specs,
                organization=organization,
                income={
                    str(key): _number(value, 0.0)
                    for key, value in _as_mapping(
                        faction.get("income")
                    ).items()
                },
                score_assets={
                    str(key): _number(value, 0.0)
                    for key, value in _as_mapping(
                        faction.get("score_assets")
                    ).items()
                },
                actions=[
                    dict(item)
                    for item in (faction.get("actions") or ())
                    if isinstance(item, Mapping) and item.get("id")
                ],
                organs=organs,
                subfactions=subfactions,
                automaton_interactions=automaton_interactions,
                character_interactions=character_interactions,
            )
            # Стартовые значения пресета задают фон, а не отдельный
            # кошелёк: подбираем контекст так, чтобы производные активы
            # начинались с данных шаблона.
            for key in asset_keys(runtime):
                runtime.context.setdefault(str(key), 0.5)
            for key, value in assets.items():
                runtime.set_asset(key, value)
            runtime.baseline_context = dict(runtime.context)
            runtime.baseline_assets = runtime.derived_assets()
            self.factions[side] = runtime

    def faction(self, side):
        return self.factions.get(str(side or ""))

    @property
    def player(self):
        return self.faction(self.player_side)

    @property
    def rival(self):
        return self.faction(self.rival_side)

    def rival_of(self, side):
        side = str(side or "")
        explicit = self._rivals.get(side)
        if explicit:
            return explicit
        faction = self.faction(side)
        if faction is not None:
            explicit = str(faction.record.get("rival_side") or "")
            if explicit:
                return explicit
        if side == self.rival_side:
            return self.player_side
        return self.rival_side

    def other_sides(self, side):
        return [item for item in self.factions if item != str(side or "")]

    def composite(self, side=None):
        """Составной автомат сети органов стороны.

        Это диагностическое представление (WORLD_CORE_MODEL §2.7):
        `OrganRuntime` остаётся источником истины, а сеть отдаёт
        агрегаты `F/E/S` и распределение работы. ``side`` по умолчанию —
        сторона игрока; неизвестная сторона возвращает ``None``.
        """
        side = str(side or self.player_side)
        faction = self.faction(side)
        if faction is None:
            return None
        return organ_composite(
            faction.organs,
            root_id="%s:faction" % side,
        )

    def begin_turn(self):
        """Начать ход, если он ещё не начат."""
        if self.finished or self._turn_active:
            return self.snapshot()
        self.turn += 1
        self.actions_left = self.actions_per_turn
        self._turn_active = True
        return self.snapshot()

    def action_budget(self):
        return {
            "turn": self.turn,
            "actions_per_turn": self.actions_per_turn,
            "actions_left": self.actions_left,
            "active": bool(self._turn_active),
            "finished": bool(self.finished),
        }

    def _interval(self, name):
        """Положительный интервал реального времени из конфига."""
        return max(1e-6, _number(self.realtime.get(name), 1e-6))

    @property
    def turn_seconds(self):
        return self._interval("turn_seconds")

    @property
    def action_interval_seconds(self):
        return self._interval("action_interval_seconds")

    @property
    def ai_interval_seconds(self):
        return self._interval("ai_interval_seconds")

    @property
    def organization_interval_seconds(self):
        return self._interval("organization_interval_seconds")

    def time_label(self):
        """Игровое время в формате ЧЧ:ММ:СС."""
        total = max(0, int(self.elapsed))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return "%02d:%02d:%02d" % (hours, minutes, seconds)

    def speed_label(self):
        return "×%d" % int(self.speed)

    def speed_cap(self):
        return int(self.speed_levels[-1])

    def can_speed_up(self):
        return int(self.speed) < self.speed_cap()

    def can_slow_down(self):
        """Можно ли отменить ускорение и вернуться к более медленному темпу."""
        return int(self.speed) > int(self.speed_levels[0])

    def speed_up(self):
        """Ускорить время до следующего разрешённого значения.

        Замедление ниже физической секунды, пауза и откат не
        предусмотрены: минимальная скорость — ``speed_levels[0]`` (обычно
        ``1×``). Ускорение можно отменить методом ``slow_down()``.
        """
        if self.finished:
            return self.speed
        for value in self.speed_levels:
            if value > int(self.speed):
                self.speed = int(value)
                break
        return self.speed

    def slow_down(self):
        """Отменить одно ускорение, но не ниже минимальной скорости."""
        if self.finished:
            return self.speed
        for value in reversed(self.speed_levels):
            if value < int(self.speed):
                self.speed = int(value)
                break
        return self.speed

    def reset_speed(self):
        """Вернуть физический темп ``1×`` (если он есть в конфиге)."""
        self.speed = int(self.speed_levels[0])
        return self.speed

    def set_speed(self, value):
        """Задать любую разрешённую скорость не ниже минимальной.

        ``False`` возвращается для неизвестного значения или попытки
        опуститься ниже физического темпа; пауза и откат не допускаются.
        """
        try:
            requested = int(value)
        except (TypeError, ValueError):
            return False
        minimum = int(self.speed_levels[0])
        if requested < minimum:
            return False
        allowed = [level for level in self.speed_levels if level >= requested]
        if not allowed:
            return False
        self.speed = int(allowed[0])
        return True

    def advance_time(self, dt):
        """Продвинуть кампанию на ``dt`` реальных секунд.

        Игровое время идёт со скоростью ``speed`` (не меньше 1). Работа,
        ИИ и организации обновляются непрерывно, без кнопки «завершить
        ход»; пауза, замедление и откат отсутствуют.
        """
        if self.finished or dt is None:
            return self.snapshot()
        try:
            seconds = float(dt)
        except (TypeError, ValueError):
            return self.snapshot()
        if seconds <= 0.0:
            return self.snapshot()
        if not self._turn_active:
            self._turn_active = True
            if self.turn <= 0:
                self.turn = 1
            self.actions_left = max(self.actions_left, self.actions_per_turn)
        scaled = seconds * float(self.speed)
        self.elapsed += scaled
        self._regenerate_actions(scaled)
        self._advance_ai(scaled)
        self._advance_rounds(scaled)
        self._advance_story_events(scaled)
        return self.snapshot()

    def _regenerate_actions(self, seconds):
        if self.finished:
            return
        if self.actions_left >= self.actions_per_turn:
            self._action_progress = 0.0
            return
        self._action_progress += seconds
        interval = self.action_interval_seconds
        while (
            self._action_progress >= interval
            and self.actions_left < self.actions_per_turn
        ):
            self.actions_left += 1
            self._action_progress -= interval
        if self.actions_left >= self.actions_per_turn:
            self._action_progress = 0.0

    def _advance_ai(self, seconds):
        if self.finished:
            return
        self._ai_progress += seconds
        interval = self.ai_interval_seconds
        while self._ai_progress >= interval and not self.finished:
            self._ai_progress -= interval
            for side in list(self.factions):
                if side == self.player_side or self.finished:
                    continue
                faction = self.faction(side)
                if faction is None or faction.dissolved:
                    continue
                self._auto_play_side(side, 1)

    def _advance_rounds(self, seconds):
        if self.finished:
            return
        self._round_progress += seconds
        interval = self.organization_interval_seconds
        while self._round_progress >= interval and not self.finished:
            self._round_progress -= interval
            self.turn += 1
            self._tick_organizations()
            self._check_outcome()
            self.history.append(self.snapshot())

    # --- ролевые события -------------------------------------------
    def _story_context(self, side=None):
        """Контекст для условий/видимости событий.

        Берётся лидер фракции (по умолчанию — игрок). Все числа
        нормированы в ``0..1``, чтобы условия в JSON были переносимыми.
        """
        side = str(side or self.player_side)
        faction = self.faction(side)
        if faction is None or not faction.characters:
            return {
                "side": side,
                "faction_id": getattr(faction, "id", ""),
                "alive": False,
                "time": self.elapsed,
            }
        leader = faction.characters[0]
        bdi = getattr(leader, "bdi", None)
        divisions = getattr(leader, "divisions", None)
        max_force = float(getattr(leader, "state", {}).get("max_force", 10.0))
        max_energy = float(
            getattr(leader, "state", {}).get("max_energy", 3.0)
        )
        return {
            "id": str(getattr(leader, "campaign_id", "") or ""),
            "name": str(getattr(leader, "name", "") or ""),
            "side": side,
            "faction_id": str(getattr(faction, "id", "") or ""),
            "role": str(getattr(leader, "campaign_role_id", "") or ""),
            "needs": dict(getattr(leader, "needs", {}) or {}),
            "traits": dict(getattr(leader.personality, "values", {}) or {}),
            "divisions": (
                divisions.as_dict() if divisions is not None else {}
            ),
            "tags": divisions.tags() if divisions is not None else [],
            "conditions": (
                dict(bdi.conditions) if bdi is not None else {}
            ),
            "beliefs": list(bdi.beliefs) if bdi is not None else [],
            "force": max(
                0.0,
                float(getattr(leader, "force", 0.0))
                / max(1e-9, max_force),
            ),
            "energy": max(
                0.0,
                float(getattr(leader, "energy_pool", 0.0))
                / max(1e-9, max_energy),
            ),
            "alive": not bool(getattr(leader, "is_dead", False)),
            "time": float(self.elapsed),
        }

    # События — ролевой слой, а не часть ядра. Они ничего не производят:
    # единственный источник изменений — работы, переходы автоматов и
    # действия игрока. Событие только описывает уже случившееся.

    def _advance_story_events(self, seconds):
        if self.finished or self.story_engine is None:
            return []
        context = self._story_context()
        self.story_engine.advance(seconds, context=context)
        self._story_progress += max(0.0, float(seconds))
        interval = max(4.0, self.organization_interval_seconds * 0.5)
        spawned = []
        while self._story_progress >= interval:
            self._story_progress -= interval
            instance = self.story_engine.trigger(context=context)
            if instance is None:
                continue
            # Ролевой слой только фиксирует событие. Никаких записей в
            # состояние: на состояние влияют работы и автоматы.
            applied = {}
            entry = {
                "id": instance.id,
                "template_id": instance.template_id,
                "category": instance.category,
                "title": instance.title,
                "text": instance.text,
                "severity": instance.severity,
                "stakes": instance.stakes,
                "speed": instance.speed,
                "duration": instance.duration,
                "elapsed": instance.elapsed,
                "visible": instance.mature,
                "visibility": instance.visibility.as_dict(),
                "effects": applied,
                "turn": self.turn,
            }
            self.story_events.append(entry)
            spawned.append(entry)
        if len(self.story_events) > EVENT_LOG_LIMIT:
            self.story_events = self.story_events[-EVENT_LOG_LIMIT:]
        return spawned

    def _player_action_gate(self, side):
        """Проверить бюджет перед действием игрока."""
        if str(side) != self.player_side:
            return None
        if self.finished:
            return "кампания завершена"
        if not self._turn_active:
            self.begin_turn()
        if self.actions_left <= 0:
            return (
                "бюджет действий исчерпан: завершите ход "
                "(доступно %d за ход)" % self.actions_per_turn
            )
        return None

    def _spend_player_action(self, side):
        if str(side) == self.player_side and self.actions_left > 0:
            self.actions_left -= 1

    def _cooldown_left(self, faction, action, turn=None):
        """Сколько ходов ещё нельзя повторять работу.

        ``cooldown=1`` означает один пропущенный ход: работа, использованная
        на ходе ``t``, снова доступна на ходе ``t + 2``. Так значение
        совпадает с текстом «перезарядка ещё N» и одинаково трактуется для
        игрока и для автоматического выбора.
        """
        cooldown = int(
            _number(
                action.get(
                    "cooldown", self.model.get("cooldown_turns")
                ),
                0,
            )
        )
        last = faction.cooldowns.get(str(action.get("id")))
        if cooldown <= 0 or last is None:
            return 0
        current = self.turn if turn is None else int(turn)
        return max(0, cooldown + 1 - (current - int(last)))

    def _action_use_limit(self, action):
        """Сколько раз работу вообще можно выполнить (0 — без лимита)."""
        if action.get("once") is True or action.get("repeatable") is False:
            return 1
        try:
            value = int(_number(action.get("max_uses"), 0))
        except (TypeError, ValueError):
            value = 0
        return max(0, value)

    def _action_use_reason(self, faction, action):
        limit = self._action_use_limit(action)
        used = int(faction.action_uses.get(str(action.get("id")), 0))
        if limit <= 0 or used < limit:
            return ""
        if limit == 1:
            return "уже выполнено"
        return "исчерпано (%d из %d)" % (used, limit)

    @staticmethod
    def _asset_requirement_reason(prefix, assets, conditions):
        """Проверить условия на активы и вернуть первую причину отказа."""
        return asset_reason(prefix, assets, conditions, ASSET_LABELS)

    def _condition_context(self, faction, target=None):
        """Собрать состояние для типизированных условий."""
        return {
            "faction": faction,
            "target": target,
            "character": (
                faction.characters[0] if faction.characters else None
            ),
            "target_character": (
                target.characters[0]
                if target is not None and target.characters
                else None
            ),
            "turn": int(self.turn),
            "used_actions": {
                str(key)
                for key, value in faction.action_uses.items()
                if int(value) > 0
            },
            "labels": ASSET_LABELS,
        }

    def _action_requirement_reason(self, faction, action, target=None):
        """Проверить предпосылки работы: состояния, историю и цели.

        Данные работы могут задавать блок ``requires``:

        * ``self``/``target`` — минимальные/максимальные значения активов;
        * ``used_actions``/``not_used_actions`` — зависимость от истории;
        * ``min_turn`` — самый ранний цикл, когда работа допустима.
        """
        requires = _as_mapping(action.get("requires"))
        if not requires:
            return ""
        minimum_turn = requires.get("min_turn")
        if minimum_turn is not None and self.turn < int(
            _number(minimum_turn, 0)
        ):
            return "доступно с цикла %d" % int(_number(minimum_turn, 0))
        used = {
            str(key)
            for key, value in faction.action_uses.items()
            if int(value) > 0
        }
        required_used = requires.get("used_actions") or ()
        if isinstance(required_used, str):
            required_used = (required_used,)
        for action_id in required_used:
            if str(action_id) not in used:
                return "сначала нужно: %s" % str(action_id)
        forbidden_used = requires.get("not_used_actions") or ()
        if isinstance(forbidden_used, str):
            forbidden_used = (forbidden_used,)
        for action_id in forbidden_used:
            if str(action_id) in used:
                return "несовместимо с: %s" % str(action_id)
        reason = self._asset_requirement_reason(
            "нужно", faction.assets, requires.get("self")
        )
        if reason:
            return reason
        if target is not None:
            reason = self._asset_requirement_reason(
                "цель", target.assets, requires.get("target")
            )
            if reason:
                return reason
        reason = check_conditions(
            requires.get("when"),
            self._condition_context(faction, target),
        )
        if reason:
            return reason
        return ""

    def action_options(self, side, turn=None):
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        options = []
        for action in faction.actions:
            cost = _as_mapping(action.get("cost"))
            affordable = all(
                faction.asset(key) + 1e-9 >= _number(value, 0.0)
                for key, value in cost.items()
            )
            left = self._cooldown_left(faction, action, turn=turn)
            target = self.faction(self._target_side(side, action))
            used_reason = self._action_use_reason(faction, action)
            requirement_reason = self._action_requirement_reason(
                faction, action, target
            )
            if used_reason:
                reason = used_reason
            elif requirement_reason:
                reason = requirement_reason
            elif not affordable:
                reason = "не хватает состояния"
            elif left > 0:
                reason = "перезарядка ещё %d" % left
            else:
                reason = ""
            options.append(
                {
                    "action": action,
                    "id": str(action.get("id")),
                    "label": str(action.get("label") or action.get("id")),
                    "enabled": bool(not reason),
                    "reason": reason,
                    "uses": int(
                        faction.action_uses.get(str(action.get("id")), 0)
                    ),
                    "max_uses": self._action_use_limit(action),
                }
            )
        return options

    def available_actions(self, side):
        return [
            item["id"]
            for item in self.action_options(side)
            if item.get("enabled")
        ]

    def organ(self, side, organ_id):
        faction = self.faction(side)
        if faction is None:
            return None
        return faction.organ(organ_id)

    def organ_options(self, side):
        """Снимки органов фракции для графа и кодекса."""
        faction = self.faction(side)
        if faction is None:
            return []
        return [organ.snapshot() for organ in faction.organs]

    def organ_interaction_options(self, side, organ_id):
        """Доступные взаимодействия с конкретным органом."""
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        organ = faction.organ(organ_id)
        if organ is None:
            return []
        options = []
        for interaction in organ.interactions:
            cost = _as_mapping(interaction.get("cost"))
            affordable = all(
                faction.asset(key) + 1e-9 >= _number(value, 0.0)
                for key, value in cost.items()
            )
            left = organ.cooldown_left(interaction, self.turn)
            options.append(
                {
                    "interaction": interaction,
                    "id": str(interaction.get("id")),
                    "label": str(
                        interaction.get("label")
                        or interaction.get("id")
                    ),
                    "description": str(
                        interaction.get("description") or ""
                    ),
                    "integrity": round(
                        _number(interaction.get("integrity")), 6
                    ),
                    "cost": {
                        str(key): round(_number(value), 6)
                        for key, value in cost.items()
                    },
                    "enabled": bool(affordable and left <= 0),
                    "reason": (
                        "не хватает состояния"
                        if not affordable
                        else ("перезарядка ещё %d" % left if left > 0 else "")
                    ),
                }
            )
        return options

    def perform_organ_interaction(
        self, side, organ_id, interaction_id
    ):
        """Повлиять на орган: усилить, реформировать, почистить, снабдить.

        Изменение органа распространяется на фракцию через
        ``spread_organ_effect``: это и есть самоподобный up-масштаб.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        gate = self._player_action_gate(side)
        if gate:
            return {"ok": False, "reason": gate}
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        organ = faction.organ(organ_id)
        if organ is None:
            return {"ok": False, "reason": "орган не найден"}
        option = next(
            (
                item
                for item in self.organ_interaction_options(
                    side, organ_id
                )
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return {"ok": False, "reason": "взаимодействие не найдено"}
        if not option.get("enabled"):
            return {
                "ok": False,
                "reason": option.get("reason") or "взаимодействие недоступно",
            }
        interaction = option["interaction"]
        cost = _as_mapping(interaction.get("cost"))
        for key, value in cost.items():
            faction.add_asset(key, -_number(value))
        before = organ.integrity
        delta = strengthen_organ(
            organ, _number(interaction.get("integrity"))
        )
        explicit = _as_mapping(interaction.get("faction"))
        for key, value in explicit.items():
            faction.add_asset(key, _number(value))
        spread = spread_organ_effect(
            faction, organ, delta, self.model
        )
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if cooldown > 0:
            organ.interaction_cooldowns[
                str(interaction.get("id"))
            ] = self.turn
        organ.used_turn = self.turn
        self._spend_player_action(side)
        result = {
            "ok": True,
            "turn": self.turn,
            "actions_left": self.actions_left,
            "side": faction.side,
            "organ_id": organ.id,
            "organ_name": organ.name,
            "organ_kind": organ.kind,
            "interaction_id": str(interaction.get("id")),
            "label": option["label"],
            "description": option["description"],
            "integrity_before": round(before, 6),
            "integrity_after": round(organ.integrity, 6),
            "integrity_delta": round(delta, 6),
            "faction_spread": round(spread, 6),
            "cost": {
                str(key): round(_number(value), 6)
                for key, value in cost.items()
            },
            "text": str(interaction.get("text") or option["description"]),
            "status": organ.status(),
        }
        detail = (
            "ход %d: %s → орган «%s»: %s; целостность %.2f → %.2f"
            % (
                self.turn,
                faction.name,
                organ.name,
                result["label"],
                before,
                organ.integrity,
            )
        )
        self.events.append(
            {
                "turn": self.turn,
                "kind": "organ",
                "text": detail,
                "side": faction.side,
                "organ_id": organ.id,
                "actor": faction.name,
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]
        self.last_organ_result = result
        return result

    interact_organ = perform_organ_interaction

    def _automaton_targets(self, faction, source, relation):
        """Кандидаты в цели для команды автомата.

        ``relation`` задаётся данными: ``any`` — любой другой узел,
        ``linked``/``neighbor`` — соседи по сети, ``same_kind`` — узлы
        того же типа. Старые ``subordinate``/``superior``/``peer``
        читаются как сетевые связи, а не как вертикаль подчинения.
        """
        relation = str(relation or "any").lower()
        organs = list(faction.organs)
        links = organ_links(organs)
        if relation in ("linked", "neighbor", "adjacent", "subordinate",
                        "superior", "peer"):
            neighbors = set(links.get(source.id, ()))
            return [organ for organ in organs if organ.id in neighbors]
        if relation in ("same_kind", "kind"):
            return [
                organ
                for organ in organs
                if organ.id != source.id
                and str(organ.kind) == str(source.kind)
            ]
        return [organ for organ in organs if organ.id != source.id]

    def automaton_interaction_options(self, side, organ_id):
        """Команды выбранного автомата другим автоматам своей фракции."""
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        source = faction.organ(organ_id)
        if source is None:
            return []
        options = []
        for interaction in faction.automaton_interactions:
            cost = _as_mapping(interaction.get("cost"))
            affordable = all(
                faction.asset(key) + 1e-9 >= _number(value, 0.0)
                for key, value in cost.items()
            )
            relation = str(interaction.get("relation") or "any").lower()
            targets = self._automaton_targets(faction, source, relation)
            left = source.cooldown_left(interaction, self.turn)
            if not targets:
                if relation in (
                    "linked",
                    "neighbor",
                    "adjacent",
                    "subordinate",
                    "superior",
                    "peer",
                ):
                    reason = "нет связанных автоматов"
                elif relation in ("same_kind", "kind"):
                    reason = "нет автоматов того же типа"
                else:
                    reason = "нет других автоматов"
            elif not affordable:
                reason = "не хватает состояния"
            elif left > 0:
                reason = "перезарядка ещё %d" % left
            else:
                reason = ""
            options.append(
                {
                    "interaction": interaction,
                    "id": str(interaction.get("id")),
                    "label": str(
                        interaction.get("label")
                        or interaction.get("id")
                    ),
                    "description": str(
                        interaction.get("description") or ""
                    ),
                    "relation": relation,
                    "cost": {
                        str(key): round(_number(value), 6)
                        for key, value in cost.items()
                    },
                    "source_integrity": round(
                        _number(interaction.get("source_integrity")), 6
                    ),
                    "target_integrity": round(
                        _number(interaction.get("target_integrity")), 6
                    ),
                    "targets": [
                        {
                            "id": target.id,
                            "name": target.name,
                            "integrity": round(target.integrity, 6),
                            "status": target.status(),
                        }
                        for target in targets
                    ],
                    "enabled": bool(targets and affordable and left <= 0),
                    "reason": reason,
                }
            )
        return options

    def perform_automaton_interaction(
        self, side, source_organ_id, target_organ_id, interaction_id
    ):
        """Провести команду одного автомата другому внутри своей сети."""
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        gate = self._player_action_gate(side)
        if gate:
            return {"ok": False, "reason": gate}
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        source = faction.organ(source_organ_id)
        if source is None:
            return {"ok": False, "reason": "автомат-источник не найден"}
        target = faction.organ(target_organ_id)
        if target is None:
            return {"ok": False, "reason": "автомат-цель не найден"}
        option = next(
            (
                item
                for item in self.automaton_interaction_options(
                    side, source_organ_id
                )
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return {"ok": False, "reason": "команда не найдена"}
        if not option.get("enabled"):
            return {
                "ok": False,
                "reason": option.get("reason") or "команда недоступна",
            }
        if target.id not in {
            item["id"] for item in option.get("targets", ())
        }:
            return {
                "ok": False,
                "reason": "цель не подходит для этой команды",
            }
        interaction = option["interaction"]
        cost = _as_mapping(interaction.get("cost"))
        for key, value in cost.items():
            faction.add_asset(key, -_number(value))
        source_before = source.integrity
        target_before = target.integrity
        source_delta = strengthen_organ(
            source, _number(interaction.get("source_integrity"))
        )
        target_delta = strengthen_organ(
            target, _number(interaction.get("target_integrity"))
        )
        explicit = _as_mapping(interaction.get("faction"))
        for key, value in explicit.items():
            faction.add_asset(key, _number(value))
        source_spread = spread_organ_effect(
            faction, source, source_delta, self.model
        )
        target_spread = spread_organ_effect(
            faction, target, target_delta, self.model
        )
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if cooldown > 0:
            source.interaction_cooldowns[
                str(interaction.get("id"))
            ] = self.turn
        source.used_turn = self.turn
        target.used_turn = self.turn
        self._spend_player_action(side)
        result = {
            "ok": True,
            "turn": self.turn,
            "actions_left": self.actions_left,
            "side": faction.side,
            "source_organ_id": source.id,
            "source_organ_name": source.name,
            "target_organ_id": target.id,
            "target_organ_name": target.name,
            "interaction_id": str(interaction.get("id")),
            "label": option["label"],
            "description": option["description"],
            "relation": option.get("relation", "any"),
            "source_integrity_before": round(source_before, 6),
            "source_integrity_after": round(source.integrity, 6),
            "source_integrity_delta": round(source_delta, 6),
            "target_integrity_before": round(target_before, 6),
            "target_integrity_after": round(target.integrity, 6),
            "target_integrity_delta": round(target_delta, 6),
            "faction_spread": round(source_spread + target_spread, 6),
            "cost": {
                str(key): round(_number(value), 6)
                for key, value in cost.items()
            },
            "text": str(interaction.get("text") or option["description"]),
            "status": target.status(),
        }
        detail = (
            "ход %d: %s → %s → %s: %s; цель %.2f → %.2f"
            % (
                self.turn,
                faction.name,
                source.name,
                target.name,
                result["label"],
                target_before,
                target.integrity,
            )
        )
        self.events.append(
            {
                "turn": self.turn,
                "kind": "automaton",
                "text": detail,
                "side": faction.side,
                "organ_id": source.id,
                "target_organ_id": target.id,
                "actor": source.name,
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]
        self.last_automaton_result = result
        return result

    interact_automaton = perform_automaton_interaction

    def character(self, side, character_id):
        faction = self.faction(side)
        if faction is None:
            return None
        return faction.character(character_id)

    def character_options(self, side):
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        return faction.character_options()

    def _character_cooldown_left(self, character, interaction):
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if cooldown <= 0:
            return 0
        last = _as_mapping(
            getattr(character, "campaign_cooldowns", {})
        ).get(str(interaction.get("id")))
        if last is None:
            return 0
        return max(
            0,
            cooldown + 1 - (int(self.turn) - int(last)),
        )

    def character_interaction_options(self, side, character_id):
        """Взаимодействия с конкретным персонажем."""
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        character = faction.character(character_id)
        if character is None:
            return []
        is_self = bool(getattr(character, "campaign_is_player", False))
        options = []
        for interaction in faction.character_interactions:
            cost = _as_mapping(interaction.get("cost"))
            affordable = all(
                faction.asset(key) + 1e-9 >= _number(value, 0.0)
                for key, value in cost.items()
            )
            left = self._character_cooldown_left(character, interaction)
            self_blocked = bool(
                is_self and not interaction.get("allow_self", False)
            )
            if self_blocked:
                reason = "нельзя применять к самому себе"
            elif not affordable:
                reason = "не хватает состояния"
            elif left > 0:
                reason = "перезарядка ещё %d" % left
            else:
                reason = ""
            options.append(
                {
                    "interaction": interaction,
                    "id": str(interaction.get("id")),
                    "label": str(
                        interaction.get("label")
                        or interaction.get("id")
                    ),
                    "description": str(
                        interaction.get("description") or ""
                    ),
                    "cost": {
                        str(key): round(_number(value), 6)
                        for key, value in cost.items()
                    },
                    "morale": round(_number(interaction.get("morale")), 6),
                    "needs": {
                        str(key): round(_number(value), 6)
                        for key, value in _as_mapping(
                            interaction.get("needs")
                        ).items()
                    },
                    "personality": {
                        str(key): round(_number(value), 6)
                        for key, value in _as_mapping(
                            interaction.get("personality")
                        ).items()
                    },
                    "target_is_self": is_self,
                    "allow_self": bool(
                        interaction.get("allow_self", False)
                    ),
                    "enabled": bool(
                        affordable and left <= 0 and not self_blocked
                    ),
                    "reason": reason,
                }
            )
        return options

    def perform_character_interaction(
        self, side, character_id, interaction_id
    ):
        """Применить действие к выбранному персонажу."""
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        gate = self._player_action_gate(side)
        if gate:
            return {"ok": False, "reason": gate}
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        character = faction.character(character_id)
        if character is None:
            return {"ok": False, "reason": "персонаж не найден"}
        option = next(
            (
                item
                for item in self.character_interaction_options(
                    side, character_id
                )
                if item["id"] == str(interaction_id)
            ),
            None,
        )
        if option is None:
            return {"ok": False, "reason": "взаимодействие не найдено"}
        if not option.get("enabled"):
            return {
                "ok": False,
                "reason": option.get("reason")
                or "взаимодействие недоступно",
            }
        interaction = option["interaction"]
        cost = _as_mapping(interaction.get("cost"))
        for key, value in cost.items():
            faction.add_asset(key, -_number(value))
        needs_before = {
            str(key): _clamp(character.needs.get(key, 0.0))
            for key in _as_mapping(interaction.get("needs"))
        }
        for key, value in _as_mapping(interaction.get("needs")).items():
            if key in character.needs:
                character.needs[key] = _clamp(
                    character.needs.get(key, 0.0) + _number(value)
                )
        values = getattr(character.personality, "values", {})
        for key, value in _as_mapping(
            interaction.get("personality")
        ).items():
            if key in values:
                values[key] = _clamp(values.get(key, 0.0) + _number(value))
        morale_before = _number(character.morale)
        character.morale = max(
            0.0,
            min(100.0, morale_before + _number(interaction.get("morale"))),
        )
        organ = faction.organ(
            getattr(character, "campaign_organ_id", "")
        )
        organ_before = organ.integrity if organ is not None else None
        organ_delta = 0.0
        integrity_delta = _number(interaction.get("organ_integrity"))
        if organ is not None and integrity_delta:
            organ_delta = strengthen_organ(organ, integrity_delta)
            spread_organ_effect(faction, organ, organ_delta, self.model)
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if cooldown > 0:
            character.campaign_cooldowns[
                str(interaction.get("id"))
            ] = self.turn
        self._spend_player_action(side)
        result = {
            "ok": True,
            "turn": self.turn,
            "actions_left": self.actions_left,
            "side": faction.side,
            "character_id": str(
                getattr(character, "campaign_id", character_id)
            ),
            "character_name": str(getattr(character, "name", "")),
            "post": str(getattr(character, "campaign_post", "") or ""),
            "interaction_id": str(interaction.get("id")),
            "label": option["label"],
            "description": option["description"],
            "cost": {
                str(key): round(_number(value), 6)
                for key, value in cost.items()
            },
            "needs_before": {
                key: round(value, 6) for key, value in needs_before.items()
            },
            "needs_after": {
                key: round(_clamp(character.needs.get(key, 0.0)), 6)
                for key in needs_before
            },
            "morale_before": round(morale_before, 6),
            "morale_after": round(_number(character.morale), 6),
            "organ_id": organ.id if organ is not None else "",
            "organ_integrity_before": (
                round(organ_before, 6) if organ_before is not None else None
            ),
            "organ_integrity_after": (
                round(organ.integrity, 6) if organ is not None else None
            ),
            "organ_integrity_delta": round(organ_delta, 6),
            "text": str(
                interaction.get("text") or option["description"]
            ),
        }
        detail = (
            "ход %d: %s → персонаж «%s» (%s): %s; мораль %.0f → %.0f"
            % (
                self.turn,
                faction.name,
                result["character_name"],
                result["post"] or "без должности",
                result["label"],
                morale_before,
                character.morale,
            )
        )
        self.events.append(
            {
                "turn": self.turn,
                "kind": "character",
                "text": detail,
                "side": faction.side,
                "character_id": result["character_id"],
                "actor": faction.name,
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]
        self.last_character_result = result
        return result

    interact_character = perform_character_interaction

    def _target_side(self, side, action, target=None):
        faction = self.faction(side)
        if faction is None:
            return None
        requested = str(target or action.get("target") or "rival")
        if requested in ("self", faction.id, faction.side):
            return faction.side
        if requested == "rival":
            return self.rival_of(side)
        if requested in ("any", "all", "all_rivals", "other"):
            others = self.other_sides(side)
            return others[0] if others else None
        if requested == "strongest":
            others = [self.faction(item) for item in self.other_sides(side)]
            others = [item for item in others if item is not None]
            if not others:
                return None
            return max(
                others, key=lambda item: (item.score(), item.side)
            ).side
        if requested == "weakest":
            others = [self.faction(item) for item in self.other_sides(side)]
            others = [item for item in others if item is not None]
            if not others:
                return None
            return min(
                others, key=lambda item: (item.score(), item.side)
            ).side
        if requested in self.factions:
            return requested
        for item in self.factions.values():
            if requested in (item.id, item.record.get("name")):
                return item.side
        return self.rival_of(side)

    def _apply_branch(self, actor, target, branch, scale=None):
        """Тонкая обёртка над единым движком эффектов."""
        if scale is None:
            scale = self.model["effect_scale"]
        return apply_effects(
            actor,
            branch,
            target=target,
            scale=scale,
            source="work",
        )

    def _log_work(self, result):
        self.log.append(result)
        detail = (
            "ход %d: %s → %s работой «%s» (%s); шанс %.3f, бросок %.3f, "
            "успех=%s; атака %s=%.3f против %s=%.3f"
            % (
                result["turn"],
                result["actor_name"],
                result["target_name"],
                result["label"],
                result["form"],
                result["chance"],
                result["roll"],
                "да" if result["success"] else "нет",
                result["attack_asset"],
                result["attack_value"],
                result["defense_asset"],
                result["defense_value"],
            )
        )
        if result.get("reason"):
            detail += "; причина: %s" % result["reason"]
        self.events.append(
            {
                "turn": result["turn"],
                "kind": "work",
                "text": detail,
                "side": result["actor_side"],
                "actor": result["actor_name"],
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]

    def perform(self, side, action_id, target=None):
        actor = self.faction(side)
        if actor is None or actor.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        gate = self._player_action_gate(side)
        if gate:
            return {"ok": False, "reason": gate}
        action = actor.action(action_id)
        if action is None:
            return {"ok": False, "reason": "действие не найдено"}
        if action_id not in self.available_actions(side):
            option = next(
                (
                    item
                    for item in self.action_options(side)
                    if item["id"] == str(action_id)
                ),
                {},
            )
            return {
                "ok": False,
                "reason": option.get("reason") or "действие недоступно",
            }
        target_side = self._target_side(side, action, target=target)
        target_faction = self.faction(target_side)
        if target_faction is None:
            return {"ok": False, "reason": "нет цели"}
        cost = _as_mapping(action.get("cost"))
        for key, value in cost.items():
            actor.add_asset(key, -_number(value))
        attack_asset = str(action.get("attack_asset") or "influence")
        defense_asset = str(action.get("defense_asset") or "cohesion")
        attack_value = actor.asset(attack_asset)
        defense_value = (
            actor.asset(defense_asset)
            if target_faction.side == actor.side
            else target_faction.asset(defense_asset)
        )
        base = _number(action.get("base"), self.model["success_base"])
        slope = _number(action.get("slope"), self.model["success_slope"])
        chance = _sigmoid(base + slope * (attack_value - defense_value))
        roll = self.rng.random()
        success = roll < chance
        branch = action.get("effects") if success else action.get("failure")
        organ_id = str(action.get("organ_id") or "")
        organ = actor.organ(organ_id) if organ_id else None
        readiness = readiness_scale(organ, self.model)
        used_before = int(actor.action_uses.get(str(action_id), 0))
        decay = _number(
            action.get(
                "repeat_effect_decay",
                self.model.get("repeat_effect_decay", 1.0),
            ),
            1.0,
        )
        decay = max(0.0, min(1.0, decay))
        repeat_scale = decay ** used_before if used_before > 0 else 1.0
        self._apply_branch(
            actor,
            target_faction,
            branch,
            scale=self.model["effect_scale"] * readiness * repeat_scale,
        )
        if organ is not None:
            if success:
                gain = self.model["organ_action_gain"] * (
                    1.0 - organ.integrity
                )
                strengthen_organ(organ, gain)
            else:
                loss = self.model["organ_action_loss"] * organ.integrity
                strengthen_organ(organ, -loss)
            organ.used_turn = self.turn
        if success and target_faction.side != actor.side:
            damage_organs(
                target_faction,
                defense_asset,
                self.model["organ_damage"] * readiness,
                self.model,
            )
        cooldown = int(
            _number(
                action.get(
                    "cooldown", self.model.get("cooldown_turns")
                ),
                0,
            )
        )
        if cooldown > 0:
            actor.cooldowns[str(action_id)] = self.turn
        actor.action_uses[str(action_id)] = used_before + 1
        self._spend_player_action(side)
        result = {
            "ok": True,
            "turn": self.turn,
            "actions_left": self.actions_left,
            "actor_side": actor.side,
            "actor_id": actor.id,
            "actor_name": actor.name,
            "target_side": target_faction.side,
            "target_id": target_faction.id,
            "target_name": target_faction.name,
            "action_id": str(action_id),
            "label": str(action.get("label") or action_id),
            "uses": used_before + 1,
            "repeat_scale": round(repeat_scale, 6),
            "organ_id": str(action.get("organ_id") or ""),
            "organ": str(action.get("organ") or ""),
            "organ_integrity": round(
                organ.integrity if organ is not None else 1.0, 6
            ),
            "organ_status": (
                organ.status() if organ is not None else "нет органа"
            ),
            "organ_readiness": round(readiness, 6),
            "form": str(action.get("form") or "work"),
            "attack_asset": attack_asset,
            "attack_value": round(attack_value, 6),
            "defense_asset": defense_asset,
            "defense_value": round(defense_value, 6),
            "chance": round(chance, 6),
            "roll": round(roll, 6),
            "success": bool(success),
            "cost": {
                key: round(_number(value), 6)
                for key, value in cost.items()
            },
            "self_after": {
                key: round(_clamp(value), 6)
                for key, value in actor.assets.items()
            },
            "target_after": {
                key: round(_clamp(value), 6)
                for key, value in target_faction.assets.items()
            },
            "text": str(
                (branch or {}).get("text")
                if isinstance(branch, Mapping) and branch.get("text")
                else action.get("text")
                or ""
            ),
        }
        self._log_work(result)
        return result

    def auto_action(self, side, turn=None):
        options = [
            item
            for item in self.action_options(side, turn=turn)
            if item["enabled"]
        ]
        if not options:
            return None
        faction = self.faction(side)
        if faction is None:
            return None
        weights = []
        for option in options:
            action = option["action"]
            weight = max(0.01, _number(action.get("ai_priority"), 1.0))
            target_side = self._target_side(side, action)
            target = self.faction(target_side)
            if target is not None:
                defense = target.asset(
                    str(action.get("defense_asset") or "cohesion")
                )
                weight *= 1.0 + max(0.0, 0.5 - defense)
            weights.append(weight)
        total = sum(weights)
        pick = self.rng.random() * total
        upto = 0.0
        for option, weight in zip(options, weights):
            upto += weight
            if pick <= upto:
                return option["id"]
        return options[-1]["id"]

    def advance(
        self,
        player_action=None,
        target=None,
        organ_action=None,
        character_action=None,
    ):
        """Совместимый helper: выполнить действие и завершить ход.

        Для нескольких действий за ход используйте ``perform``,
        ``perform_organ_interaction`` и ``perform_character_interaction``,
        а затем отдельно ``end_turn``. ``advance`` оставлен для тестов,
        экспериментов и старых вызовов. Если ``player_action`` не задан,
        игрок, как и ИИ, автоматически тратит оставшийся бюджет действий.
        """
        if self.finished:
            return self.snapshot()
        self.begin_turn()
        if organ_action:
            if isinstance(organ_action, Mapping):
                organ_id = organ_action.get("organ_id")
                interaction_id = organ_action.get("interaction_id")
            elif (
                isinstance(organ_action, (list, tuple))
                and len(organ_action) >= 2
            ):
                organ_id, interaction_id = organ_action[0], organ_action[1]
            else:
                organ_id = interaction_id = None
            if organ_id and interaction_id:
                self.perform_organ_interaction(
                    self.player_side, organ_id, interaction_id
                )
        if character_action:
            if isinstance(character_action, Mapping):
                character_id = character_action.get("character_id")
                interaction_id = character_action.get("interaction_id")
            elif (
                isinstance(character_action, (list, tuple))
                and len(character_action) >= 2
            ):
                character_id = character_action[0]
                interaction_id = character_action[1]
            else:
                character_id = interaction_id = None
            if character_id and interaction_id:
                self.perform_character_interaction(
                    self.player_side, character_id, interaction_id
                )
        if player_action:
            self.perform(self.player_side, player_action, target=target)
        else:
            self._auto_play_side(self.player_side, self.actions_left)
        return self.end_turn()

    def _auto_play_side(self, side, budget):
        """Потратить бюджет действий стороны на автоматический выбор."""
        for _ in range(max(0, int(budget))):
            if self.finished:
                break
            faction = self.faction(side)
            if faction is None or faction.dissolved:
                break
            action_id = self.auto_action(side)
            if action_id is None:
                break
            result = self.perform(side, action_id)
            if not result.get("ok"):
                break

    def end_turn(self):
        """Завершить текущий ход: ИИ действует, органы и организации тикают."""
        if self.finished:
            return self.snapshot()
        self.begin_turn()
        for side in list(self.factions):
            if side == self.player_side or self.finished:
                continue
            faction = self.faction(side)
            if faction is None or faction.dissolved:
                continue
            self._auto_play_side(side, self.actions_per_turn)
        self._tick_organizations()
        self._check_outcome()
        self.history.append(self.snapshot())
        self.actions_left = 0
        self._turn_active = False
        return self.snapshot()

    def run(self, turns=None, player_action=None, target=None):
        if turns is None:
            limit = self.max_turns or DEFAULT_RUN_TURNS
        else:
            limit = max(0, int(turns))
        for _ in range(limit):
            if self.finished:
                break
            self.advance(player_action=player_action, target=target)
        return self.snapshot()

    def _tick_faction_characters(self, faction, seconds):
        """Дать BDI персонажей прожить организационный интервал.

        Активы фракции производны от потребностей, морали и силы людей,
        поэтому без этого шага «политические» шкалы выглядели бы
        застывшими между редкими взаимодействиями.
        """
        stored = _as_mapping(faction.organization_snapshot)
        support = _clamp(stored.get("willing_share", 0.5))
        for character in faction.characters:
            if bool(
                getattr(
                    character,
                    "is_dead",
                    getattr(character, "dead", False),
                )
            ):
                continue
            if not callable(getattr(character, "tick_needs", None)):
                continue
            try:
                character.tick_needs(
                    seconds=seconds,
                    supported=support,
                    in_combat=False,
                    under_fire=0.0,
                    rng=getattr(character, "rng", None),
                )
            except Exception:
                logger.exception(
                    "BDI персонажа %s не обновлён",
                    getattr(character, "name", "?"),
                )

    def _tick_organizations(self):
        seconds = max(30.0, float(self.organization_interval_seconds))
        self._tick_machines()
        for faction in self.factions.values():
            self._tick_faction_characters(faction, seconds)
            if faction.organization is None:
                faction.relax_context(self.model["asset_relax"])
                for key, value in faction.income.items():
                    faction.bump_context(key, value)
                for key, value in self.upkeep.items():
                    faction.bump_context(key, -value)
                tick_organs(faction, faction.organs, self.model)
                continue
            snapshot = faction.organization.tick(turn=self.turn)
            initial = max(
                1,
                len(faction.characters)
                or int(_number(snapshot.get("initial_count"), 1)),
            )
            active = int(_number(snapshot.get("active_count"), initial))
            willing_count = int(_number(snapshot.get("willing_count"), active))
            willing = _clamp(willing_count / float(initial))
            share = _clamp(active / float(initial))
            snapshot = dict(snapshot)
            snapshot.update(
                {
                    "initial_count": initial,
                    "active_count": active,
                    "willing_count": willing_count,
                    "willing_share": willing,
                    "active_share": share,
                }
            )
            faction.organization_snapshot = snapshot
            if not snapshot.get("active", True):
                faction.dissolved = True
            # Это не запись в независимый кошелёк, а контекстные
            # импульсы организации: производные активы читают их вместе
            # с BDI людей и целостностью сети.
            faction.bump_context(
                "cohesion",
                self.model["organization_cohesion"] * (willing - 0.5),
            )
            faction.bump_context(
                "legitimacy",
                self.model["organization_legitimacy"] * (share - 0.5),
            )
            faction.bump_context(
                "supply", -self.model["organization_supply_drain"]
            )
            mode_weights = _as_mapping(snapshot.get("mode_weights"))
            faction.bump_context(
                "fear",
                self.model["organization_fear"]
                * _number(mode_weights.get("order"), 0.0),
            )
            faction.bump_context(
                "morale",
                self.model["organization_morale"] * share,
            )
            faction.relax_context(self.model["asset_relax"])
            for key, value in faction.income.items():
                faction.bump_context(key, value)
            for key, value in self.upkeep.items():
                faction.bump_context(key, -value)
            tick_organs(faction, faction.organs, self.model)

    def _check_outcome(self):
        if self.outcome is not None:
            return
        rules = self.outcome_rules
        streak_limit = max(
            1,
            int(
                _number(
                    rules.get("streak_turns"),
                    self.model["collapse_streak"],
                )
            ),
        )
        for side, thresholds in _as_mapping(rules.get("defeat")).items():
            faction = self.faction(side)
            if faction is None:
                continue
            for asset, threshold in _as_mapping(thresholds).items():
                key = "%s:%s" % (side, asset)
                if faction.asset(asset) <= _number(threshold, 0.0) + 1e-9:
                    faction.low_streaks[key] = (
                        faction.low_streaks.get(key, 0) + 1
                    )
                else:
                    faction.low_streaks[key] = 0
                if faction.low_streaks.get(key, 0) >= streak_limit:
                    self.outcome = (
                        "lose" if side == self.player_side else "win"
                    )
                    self.finished = True
                    return
        if rules.get("score_margin") is not None:
            margin = _number(rules.get("score_margin"), 0.0)
            player = self.player
            rival = self.rival
            basis = str(rules.get("score_basis") or "assets")
            if basis == "progress":

                def measure(faction):
                    return faction.progress()

            else:

                def measure(faction):
                    return faction.score()

            if player is not None and rival is not None:
                difference = (
                    measure(player)
                    - measure(rival)
                    + _number(rules.get("score_bias"), 0.0)
                )
                side = (
                    "win"
                    if difference > margin
                    else ("lose" if difference < -margin else None)
                )
                after = max(1, int(_number(rules.get("score_after"), 1)))
                required = max(
                    1, int(_number(rules.get("score_streak"), 2))
                )
                if self.turn < after:
                    self.score_streak = 0
                    self.score_streak_side = None
                elif side is None:
                    self.score_streak = 0
                    self.score_streak_side = None
                elif side == self.score_streak_side:
                    self.score_streak += 1
                else:
                    self.score_streak = 1
                    self.score_streak_side = side
                if (
                    self.turn >= after
                    and side is not None
                    and self.score_streak >= required
                ):
                    self.outcome = side
                    self.finished = True
                    return

    def snapshot(self):
        return {
            "preset_id": self.preset_id,
            "title": self.title,
            "turn": self.turn,
            "max_turns": self.max_turns,
            "actions_per_turn": self.actions_per_turn,
            "actions_left": self.actions_left,
            "turn_active": bool(self._turn_active),
            "elapsed": round(float(self.elapsed), 6),
            "speed": int(self.speed),
            "realtime": dict(self.realtime),
            "action_progress": round(float(self._action_progress), 6),
            "ai_progress": round(float(self._ai_progress), 6),
            "round_progress": round(float(self._round_progress), 6),
            "score_streak": self.score_streak,
            "score_streak_side": self.score_streak_side,
            "player_side": self.player_side,
            "rival_side": self.rival_side,
            "outcome": self.outcome,
            "finished": self.finished,
            "factions": {
                side: faction.snapshot()
                for side, faction in self.factions.items()
            },
            "events": list(self.events[-SNAPSHOT_TAIL:]),
            "story_events": list(self.story_events[-SNAPSHOT_TAIL:]),
            "machines": self._machines_snapshot(),
            "log": list(self.log[-SNAPSHOT_TAIL:]),
        }

    to_dict = snapshot

    def save_snapshot(self):
        """Полный снимок: журнал, организации и состояние ГСЧ."""
        data = stamp_snapshot(self.snapshot(), SCHEMA_VERSION)
        data["log"] = list(self.log)
        data["events"] = list(self.events)
        data["rng_state"] = _nested_tuple(self.rng.getstate())
        data["seed"] = self.seed
        for side, faction in self.factions.items():
            state = data.get("factions", {}).get(side)
            if isinstance(state, dict):
                state["raw_assets"] = {
                    str(key): float(value)
                    for key, value in faction.assets.items()
                }
                state["context"] = {
                    str(key): float(value)
                    for key, value in faction.context.items()
                }
                state["baseline_context"] = {
                    str(key): float(value)
                    for key, value in faction.baseline_context.items()
                }
                state["baseline_assets"] = {
                    str(key): float(value)
                    for key, value in faction.baseline_assets.items()
                }
                state["flags"] = dict(faction.flags)
                state["subfactions"] = [
                    {
                        "id": item.id,
                        "share": float(item.share),
                        "assets": {
                            str(key): float(value)
                            for key, value in item.assets.items()
                        },
                    }
                    for item in faction.subfactions
                ]
                state["low_streaks"] = {
                    str(key): int(value)
                    for key, value in faction.low_streaks.items()
                }
                state["organ_state"] = [
                    {
                        "id": organ.id,
                        "integrity": float(organ.integrity),
                        "interaction_cooldowns": {
                            str(key): int(value)
                            for key, value in (
                                organ.interaction_cooldowns.items()
                            )
                        },
                        "used_turn": int(organ.used_turn),
                    }
                    for organ in faction.organs
                ]
                state["character_state"] = [
                    {
                        "id": str(
                            getattr(character, "campaign_id", "") or ""
                        ),
                        "needs": {
                            str(key): float(value)
                            for key, value in character.needs.items()
                        },
                        "personality": {
                            str(key): float(value)
                            for key, value in getattr(
                                character.personality, "values", {}
                            ).items()
                        },
                        "morale": float(character.morale),
                        "force": float(getattr(character, "force", 0.0)),
                        "energy": float(
                            getattr(character, "energy_pool", 0.0)
                        ),
                        "dead": bool(getattr(character, "dead", False)),
                        "conditions": {
                            str(key): float(value)
                            for key, value in getattr(
                                getattr(character, "bdi", None),
                                "conditions",
                                {},
                            ).items()
                        },
                        "beliefs": [
                            item.as_dict()
                            for item in getattr(
                                getattr(character, "bdi", None),
                                "beliefs",
                                [],
                            )
                        ],
                        "intentions": [
                            item.as_dict()
                            for item in getattr(
                                getattr(character, "bdi", None),
                                "intentions",
                                [],
                            )
                        ],
                        "divisions": (
                            character.divisions.as_dict()
                            if getattr(
                                character, "divisions", None
                            )
                            is not None
                            else {}
                        ),
                        "cooldowns": {
                            str(key): int(value)
                            for key, value in _as_mapping(
                                getattr(
                                    character, "campaign_cooldowns", {}
                                )
                            ).items()
                        },
                    }
                    for character in faction.characters
                ]
                if faction.organization is not None:
                    state["organization_state"] = (
                        faction.organization.state_dict()
                    )
        return data

    def load_snapshot(self, snapshot):
        snapshot = _as_mapping(snapshot)
        if not snapshot:
            return
        ensure_supported_snapshot(snapshot)
        self.turn = int(_number(snapshot.get("turn"), self.turn))
        saved_max = snapshot.get("max_turns")
        if saved_max is None:
            self.max_turns = None
        else:
            value = int(_number(saved_max, 0))
            self.max_turns = value if value > 0 else None
        self.actions_per_turn = max(
            1,
            int(
                _number(
                    snapshot.get("actions_per_turn"),
                    self.actions_per_turn,
                )
            ),
        )
        self.actions_left = max(
            0,
            min(
                self.actions_per_turn,
                int(
                    _number(
                        snapshot.get("actions_left"), self.actions_left
                    )
                ),
            ),
        )
        self._turn_active = bool(
            snapshot.get("turn_active", self._turn_active)
        )
        self.elapsed = max(
            0.0, _number(snapshot.get("elapsed"), self.elapsed)
        )
        self._action_progress = max(
            0.0,
            _number(snapshot.get("action_progress"), self._action_progress),
        )
        self._ai_progress = max(
            0.0, _number(snapshot.get("ai_progress"), self._ai_progress)
        )
        self._round_progress = max(
            0.0,
            _number(snapshot.get("round_progress"), self._round_progress),
        )
        saved_speed = max(1, int(_number(snapshot.get("speed"), self.speed)))
        allowed_speeds = [
            level for level in self.speed_levels if level >= saved_speed
        ]
        self.speed = (
            allowed_speeds[0]
            if allowed_speeds
            else self.speed_levels[-1]
        )
        self.score_streak = max(
            0, int(_number(snapshot.get("score_streak"), self.score_streak))
        )
        self.score_streak_side = snapshot.get(
            "score_streak_side", self.score_streak_side
        )
        self.outcome = snapshot.get("outcome")
        self.finished = bool(snapshot.get("finished", False))
        self._restore_machines(snapshot.get("machines"))
        rng_state = snapshot.get("rng_state")
        if rng_state:
            try:
                self.rng.setstate(_nested_tuple(rng_state))
            except (TypeError, ValueError):
                logger.warning(
                    "Состояние ГСЧ кампании автоматов не восстановлено"
                )
        for side, state in _as_mapping(snapshot.get("factions")).items():
            faction = self.faction(side)
            if faction is None:
                continue
            saved_context = _as_mapping(state.get("context"))
            if saved_context:
                faction.context = {
                    str(key): _clamp(
                        value, CONTEXT_MIN, CONTEXT_MAX
                    )
                    for key, value in saved_context.items()
                }
            else:
                # Старый сейв: раньше активы были независимыми. Для
                # совместимости подбираем контекст под сохранённые
                # значения, но не создаём отдельный кошелёк.
                for key in asset_keys(faction):
                    faction.context.setdefault(str(key), 0.5)
                for key, value in _as_mapping(
                    state.get("raw_assets") or state.get("assets")
                ).items():
                    faction.set_asset(key, value)
            faction.baseline_context = {
                str(key): _clamp(
                    value, CONTEXT_MIN, CONTEXT_MAX
                )
                for key, value in _as_mapping(
                    state.get("baseline_context")
                ).items()
            } or dict(faction.context)
            faction.baseline_assets = {
                str(key): _clamp(value)
                for key, value in _as_mapping(
                    state.get("baseline_assets")
                ).items()
            }
            faction.flags = dict(_as_mapping(state.get("flags")))
            for saved_sub in state.get("subfactions") or ():
                if not isinstance(saved_sub, Mapping):
                    continue
                sub = faction.subfaction(saved_sub.get("id"))
                if sub is None:
                    continue
                sub.share = _clamp(
                    saved_sub.get("share", sub.share)
                )
                sub.assets = {
                    str(key): _clamp(value)
                    for key, value in _as_mapping(
                        saved_sub.get("assets")
                    ).items()
                }
            faction.cooldowns = {
                str(key): int(_number(value))
                for key, value in _as_mapping(state.get("cooldowns")).items()
            }
            faction.action_uses = {
                str(key): max(0, int(_number(value)))
                for key, value in _as_mapping(
                    state.get("action_uses")
                ).items()
            }
            faction.dissolved = bool(state.get("dissolved", False))
            faction.low_streaks = {
                str(key): int(_number(value))
                for key, value in _as_mapping(
                    state.get("low_streaks")
                ).items()
            }
            faction.organization_snapshot = dict(
                _as_mapping(state.get("organization"))
            )
            saved_organs = {
                str(item.get("id")): item
                for item in (state.get("organ_state") or ())
                if isinstance(item, Mapping) and item.get("id")
            }
            for organ in faction.organs:
                saved = saved_organs.get(str(organ.id))
                if not saved:
                    continue
                organ.integrity = _clamp(
                    _number(saved.get("integrity"), organ.integrity)
                )
                organ.interaction_cooldowns = {
                    str(key): int(_number(value))
                    for key, value in _as_mapping(
                        saved.get("interaction_cooldowns")
                    ).items()
                }
                organ.used_turn = int(
                    _number(saved.get("used_turn"), organ.used_turn)
                )
            saved_characters = {
                str(item.get("id")): item
                for item in (state.get("character_state") or ())
                if isinstance(item, Mapping) and item.get("id")
            }
            for character in faction.characters:
                saved = saved_characters.get(
                    str(getattr(character, "campaign_id", ""))
                )
                if not saved:
                    continue
                for key, value in _as_mapping(saved.get("needs")).items():
                    if key in character.needs:
                        character.needs[key] = _clamp(value)
                values = getattr(character.personality, "values", {})
                for key, value in _as_mapping(
                    saved.get("personality")
                ).items():
                    if key in values:
                        values[key] = _clamp(value)
                divisions = _as_mapping(saved.get("divisions"))
                if (
                    divisions
                    and getattr(character, "divisions", None) is not None
                ):
                    try:
                        character.divisions.update(divisions)
                    except Exception:
                        pass
                bdi = getattr(character, "bdi", None)
                if bdi is not None:
                    for key, value in _as_mapping(
                        saved.get("conditions")
                    ).items():
                        if key in bdi.conditions:
                            bdi.conditions[key] = max(
                                0.0, _number(value, bdi.conditions[key])
                            )
                    if saved.get("beliefs") is not None:
                        try:
                            character.beliefs = list(saved["beliefs"])
                        except Exception:
                            pass
                    if saved.get("intentions") is not None:
                        try:
                            character.intentions = list(
                                saved["intentions"]
                            )
                        except Exception:
                            pass
                if saved.get("force") is not None:
                    character.force = max(
                        0.0, _number(saved.get("force"), character.force)
                    )
                if saved.get("energy") is not None:
                    character.energy_pool = max(
                        0.0,
                        _number(
                            saved.get("energy"), character.energy_pool
                        ),
                    )
                if saved.get("dead") is not None:
                    character.dead = bool(saved.get("dead"))
                character.morale = max(
                    0.0,
                    min(
                        100.0,
                        _number(
                            saved.get("morale"), character.morale
                        ),
                    ),
                )
                character.campaign_cooldowns = {
                    str(key): int(_number(value))
                    for key, value in _as_mapping(
                        saved.get("cooldowns")
                    ).items()
                }
                try:
                    character.desires = character.weighted_urgency()
                except Exception:
                    pass
            if faction.organization is not None:
                faction.organization.load_state_dict(
                    _as_mapping(state.get("organization_state"))
                )
        self.events = list(snapshot.get("events") or [])
        self.story_events = list(snapshot.get("story_events") or [])
        self.log = list(snapshot.get("log") or [])
        if self.outcome:
            self.finished = True

    def audit(self):
        anomalies = []
        seen = set()
        for side, faction in self.factions.items():
            for key, value in faction.assets.items():
                token = (side, key)
                if not math.isfinite(_number(value)):
                    anomalies.append("%s/%s: не конечное значение" % token)
                if not 0.0 <= _number(value) <= 1.0:
                    anomalies.append(
                        "%s/%s: %.6f вне диапазона [0,1]"
                        % (side, key, _number(value))
                    )
                seen.add(token)
            organ_ids = set()
            for organ in faction.organs:
                if organ.id in organ_ids:
                    anomalies.append(
                        "%s: орган %s повторяется" % (side, organ.id)
                    )
                organ_ids.add(organ.id)
                if not 0.0 <= _number(organ.integrity) <= 1.0:
                    anomalies.append(
                        "%s/%s: целостность %.6f вне [0,1]"
                        % (side, organ.id, _number(organ.integrity))
                    )
            anomalies.extend(
                "%s: %s" % (side, problem)
                for problem in validate_organ_network(faction.organs)
            )
            snapshot = faction.organization_snapshot
            if snapshot:
                active = int(_number(snapshot.get("active_count"), 0))
                initial = int(_number(snapshot.get("initial_count"), 0))
                if active > initial:
                    anomalies.append(
                        "%s: активных %d больше исходных %d"
                        % (side, active, initial)
                    )
                willing = _number(snapshot.get("willing_share"), 0.0)
                if not 0.0 <= willing <= 1.0:
                    anomalies.append(
                        "%s: willing_share %.6f вне [0,1]" % (side, willing)
                    )
            if faction.dissolved and not snapshot.get("active", True):
                continue
        for item in self.log:
            if item.get("ok") and not (
                0.0 <= _number(item.get("chance"), 0.0) <= 1.0
            ):
                anomalies.append(
                    "работа %s: шанс %.6f вне [0,1]"
                    % (item.get("action_id"), _number(item.get("chance")))
                )
        return anomalies


__all__ = [
    "AutomataCampaign",
    "AutomataCampaignError",
    "DEFAULT_ACTIONS_PER_TURN",
    "DEFAULT_CHARACTER_INTERACTIONS",
    "DEFAULT_RUN_TURNS",
    "EVENT_LOG_LIMIT",
    "FactionRuntime",
    "MODEL_DEFAULTS",
    "REALTIME_DEFAULTS",
]
