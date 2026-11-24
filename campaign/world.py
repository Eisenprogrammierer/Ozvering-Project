"""Мир кампании: загрузка, проверка и движок состояния.

Класс ``WorldEngine`` собран из миксинов по швам ответственности:
жизненный цикл, сущности, отношения, карьера, действия, день и
снимок. Публичный API и формат снимка не менялись.
"""

from __future__ import annotations

from .world_support import (
    AUTONOMY_AFFINITY_THRESHOLD,
    AUTONOMY_BASE_CHANCE,
    AUTONOMY_PERIOD,
    AUTONOMY_TRUST_THRESHOLD,
    ActionError,
    Automaton,
    CAMPAIGN_ACTION_WOUND_CHANCE,
    CAMPAIGN_ACTION_WOUND_DAMAGE,
    CAMPAIGN_ACTION_WOUND_SEVERITY,
    CAMPAIGN_CONTAGION_CHANCE,
    CAMPAIGN_CONTAGION_SEVERITY,
    CAMPAIGN_ENERGY_MAX,
    CAMPAIGN_ENV_WOUND_CHANCE,
    CAMPAIGN_ENV_WOUND_DAMAGE,
    CAMPAIGN_ENV_WOUND_SEVERITY,
    CAMPAIGN_FAVOR_INCOME,
    CAMPAIGN_FAVOR_PER_STANDING,
    CAMPAIGN_HEALTH_REGEN,
    CAMPAIGN_INFLUENCE_INCOME,
    CAMPAIGN_INFLUENCE_PER_AUTHORITY,
    CAMPAIGN_SICKNESS_HEALTH_DECAY,
    CAMPAIGN_SICKNESS_PROGRESS,
    CAMPAIGN_SKILL_CAP,
    CAMPAIGN_SKILL_FAILURE_GAIN,
    CAMPAIGN_SKILL_GAIN,
    CAMPAIGN_WOUND_DODGE_SKILL,
    CAMPAIGN_WOUND_HEALTH_DECAY,
    CAMPAIGN_WOUND_MAX,
    CAMPAIGN_WOUND_REGEN_PENALTY,
    CAMPAIGN_WOUND_TREAT_AMOUNT,
    CHARACTER_CIRCLES,
    CHARACTER_STAT_LABELS,
    COLLAPSE_COHESION,
    COLLAPSE_GRACE_DAYS,
    COLLAPSE_LEGITIMACY,
    COLLAPSE_POWER,
    CREDIT_DAYS,
    CampaignActor,
    CampaignCharacter,
    CampaignError,
    CampaignLod,
    CoalitionBook,
    DECAY_BROKE_COHESION,
    DECAY_BROKE_WEALTH,
    DECAY_CRISIS_COHESION,
    DECAY_CRISIS_POWER,
    DECAY_RECOVERY_COHESION,
    DECAY_RECOVERY_LEGITIMACY,
    DECAY_RECOVERY_POWER,
    DECAY_STRAIN_COHESION,
    DECAY_STRAIN_POWER,
    DEFAULT_OBLIGATION_KIND,
    DEFAULT_OVERDUE_OBLIGATION,
    DEFAULT_RELATION_FORM,
    DISMISSAL_LEGITIMACY,
    DISMISSAL_STANDING,
    DOMAIN_SKILLS,
    DirectiveBook,
    ENDING_KINDS,
    FormCatalog,
    HEALTH_MAX,
    HandlerRegistry,
    IntentQueue,
    KIND_LABELS,
    LABOR_MARKET_CONNECTION_WEIGHT,
    LABOR_MARKET_RANK_BONUS,
    LABOR_MARKET_REFRESH_DAYS,
    LABOR_MARKET_RIVALS,
    LABOR_MARKET_RIVAL_BASE,
    LABOR_MARKET_RIVAL_SPREAD,
    LABOR_MARKET_SKILL_WEIGHT,
    LABOR_MARKET_STANDING_WEIGHT,
    LABOR_MARKET_STRUCTURE_QUOTA,
    LABOR_NEGOTIATION_BASE_LOGIT,
    LABOR_NEGOTIATION_FAILURE_AFFINITY,
    LABOR_NEGOTIATION_FAVOR,
    LABOR_NEGOTIATION_INFLUENCE,
    LABOR_NEGOTIATION_MARGIN_WEIGHT,
    LABOR_NEGOTIATION_RELATION_WEIGHT,
    LABOR_NEGOTIATION_RETRY_BONUS,
    LABOR_NEGOTIATION_RETRY_BONUS_MAX,
    LABOR_NEGOTIATION_SUCCESS_AFFINITY,
    LEGITIMACY_RECOVERY,
    MAINTENANCE_STARVE_FORCE,
    MAINTENANCE_STARVE_HEALTH,
    Mapping,
    NATURE_BASE_WORK,
    NATURE_SEASON_LENGTH,
    NODE_STATS,
    OBLIGATION_BREACH_AFFINITY,
    OBLIGATION_BREACH_TRUST,
    OBLIGATION_FULFILL_AFFINITY,
    OBLIGATION_FULFILL_TRUST,
    ORGANIZATION_CATEGORIES,
    ObligationLedger,
    PLAYER_STATS,
    Path,
    RELATION_AXES,
    RELATION_AXIS_LABELS,
    RELATION_BACK_SHARE,
    ROLE_CHANGE_COOLDOWN_DAYS,
    ROOT,
    SCHEMA_VERSION,
    SICKNESS_MAX,
    SKILL_ORDER,
    SLOTS_MAX,
    SLOT_DAY_EDGE,
    SceneCatalog,
    SceneError,
    SceneSpec,
    StrategyBook,
    WORLD_WORK_DEFAULTS,
    WOUND_MAX,
    WOUND_RISKY_ACTIONS,
    WorldError,
    _AUTONOMY_POLICIES,
    _PlayerResources,
    _add_connections,
    _add_skills,
    _as_float,
    _as_int,
    _as_slot,
    _clamp,
    _forms_for_world,
    _is_wound_risky,
    _logbook,
    _merge_world_action_catalogs,
    _merge_world_scene_catalog,
    _normalize_labor_market,
    _profile_connection_strength,
    _profile_skill,
    _read_json,
    _resolve_config_path,
    _text,
    _validate_unique,
    _values,
    apply_item_handler,
    asymmetry_rows,
    balance,
    build_player_profile,
    build_work,
    campaign_success_chance,
    coalition_config,
    condition_holds,
    conversion_quote,
    cost_phrase,
    credit_quote,
    effect_phrase,
    hashlib,
    help_quote,
    item_automaton_snapshot,
    item_automaton_view,
    item_handler_reason,
    json,
    lint_action,
    logger,
    logging,
    maintenance_cost,
    math,
    merge_action_catalogs,
    metric_word,
    migrate_snapshot,
    nature_yield,
    normalize_action,
    normalize_item_automaton,
    normalize_profile,
    normalize_relation_axes_config,
    office_profile_status,
    pair_score,
    parse_entity_ref,
    player_projection_view,
    poverty_status,
    profile_from_identity,
    relation_axes_from_config,
    relation_axis_labels_from_config,
    relation_axis_short_labels_from_config,
    relation_effect,
    relation_effect_limit_from_config,
    relation_effect_weights_from_config,
    repair_quote,
    resolve_success_coefficients,
    resource_projection,
    rest_quote,
    restore_item_automaton,
    scaled_cost,
    scaled_effect,
    season_multiplier,
    season_name,
    success_margin,
    time,
    validate_world,
)

DEFAULT_WORLD_PATH = ROOT / "configs" / "worlds" / "agora_world.json"
DEFAULT_WORLD_HANDLERS = ROOT / "configs" / "worlds" / "handlers"
DEFAULT_BIOGRAPHY_PATH = ROOT / "configs" / "worlds" / "biography.json"

from .world_core import WorldCoreMixin
from .world_entities import WorldEntitiesMixin
from .world_relations import WorldRelationsMixin
from .world_career import WorldCareerMixin
from .world_actions import WorldActionsMixin
from .world_day import WorldDayMixin
from .world_snapshot import WorldSnapshotMixin


def load_world(path=None):
    """Загрузить мир из JSON.

    Если явный путь не задан, сначала берётся `agora_world.json` для
    обратной совместимости, а при его отсутствии — первый валидный мир
    из `configs/worlds/`. Так добавление нового JSON-мира не требует
    правки кода или переименования файла.
    """
    if path is None:
        path = DEFAULT_WORLD_PATH
        if not Path(path).is_file():
            worlds = list_worlds()
            if worlds:
                path = worlds[0]["path"]
    data = _read_json(path)
    if not isinstance(data, dict):
        raise WorldError("мир должен быть объектом")
    return validate_world(data)


def default_worlds_dir():
    return ROOT / "configs" / "worlds"


def list_worlds(directory=None):
    """Найти JSON-миры в каталоге (биография и прочие файлы пропускаются)."""
    root = Path(directory) if directory is not None else default_worlds_dir()
    root = root.resolve()
    worlds = []
    if not root.is_dir():
        return worlds
    for path in sorted(root.glob("*.json")):
        try:
            data = _read_json(path)
        except WorldError:
            continue
        if not isinstance(data, dict):
            continue
        if not data.get("domains") or not data.get("nodes"):
            continue
        try:
            world = validate_world(data)
        except WorldError:
            continue
        worlds.append(
            {
                "world_id": world["id"],
                "title": world["title"],
                "path": str(path),
            }
        )
    worlds.sort(key=lambda item: (item["title"], item["world_id"]))
    return worlds


def load_biography(path=None):
    data = _read_json(path if path is not None else DEFAULT_BIOGRAPHY_PATH)
    if not isinstance(data, dict):
        raise WorldError("биография должна быть объектом")
    return data


class WorldEngine(
    WorldCoreMixin,
    WorldEntitiesMixin,
    WorldRelationsMixin,
    WorldCareerMixin,
    WorldActionsMixin,
    WorldDayMixin,
    WorldSnapshotMixin,
):

    """Движок мира кампании."""

    def __init__(
        self,
        config,
        profile=None,
        node_id=None,
        office_id=None,
        seed=None,
        snapshot=None,
    ):
        self.config = validate_world(dict(config))
        self.work_config = dict(WORLD_WORK_DEFAULTS)
        work_raw = self.config.get("work")
        if isinstance(work_raw, Mapping):
            self.work_config.update(
                {str(key): value for key, value in work_raw.items()}
            )
        handlers_path = self.config.get("handlers_path")
        if handlers_path:
            handlers_dir = _resolve_config_path(handlers_path)
        else:
            handlers_dir = DEFAULT_WORLD_HANDLERS
        self.world_handlers = HandlerRegistry(handlers_dir)
        self.seed = _as_int(
            seed,
            _as_int(snapshot.get("seed"), 7) if snapshot else 7,
        )
        self.days = max(1, _as_int(self.config.get("days"), 30))
        self.infinite = bool(self.config.get("infinite", True))
        self.collapse_grace_days = max(
            1,
            _as_int(
                self.config.get("collapse_grace_days"),
                COLLAPSE_GRACE_DAYS,
            ),
        )
        self.role_change_cooldown_days = max(
            0,
            _as_int(
                self.config.get("role_change_cooldown_days"),
                ROLE_CHANGE_COOLDOWN_DAYS,
            ),
        )
        self.legitimacy_recovery = max(
            0.0,
            _as_float(
                self.config.get("legitimacy_recovery"),
                LEGITIMACY_RECOVERY,
            ),
        )
        self.dismissal_standing = _clamp(
            _as_float(
                self.config.get("dismissal_standing"),
                DISMISSAL_STANDING,
            )
        )
        self.dismissal_legitimacy = _clamp(
            _as_float(
                self.config.get("dismissal_legitimacy"),
                DISMISSAL_LEGITIMACY,
            )
        )
        self.collapse_min_power = _clamp(
            _as_float(
                self.config.get("collapse_power"), COLLAPSE_POWER
            )
        )
        self.collapse_min_cohesion = _clamp(
            _as_float(
                self.config.get("collapse_cohesion"),
                COLLAPSE_COHESION,
            )
        )
        self.collapse_legitimacy = _clamp(
            _as_float(
                self.config.get("collapse_legitimacy"),
                COLLAPSE_LEGITIMACY,
            )
        )
        self.decay_broke_wealth = _clamp(
            _as_float(
                self.config.get("decay_broke_wealth"),
                DECAY_BROKE_WEALTH,
            )
        )
        self.organizational_drift = bool(
            self.config.get("organizational_drift", True)
        )
        self.organizational_drift_scale = max(
            0.0,
            _as_float(
                self.config.get("organizational_drift_scale"), 1.0
            ),
        )
        self.offline_progress = bool(
            self.config.get("offline_progress", True)
        )
        self.seconds_per_day = max(
            1.0, _as_float(self.config.get("seconds_per_day"), 86400.0)
        )
        self.max_offline_days = max(
            1, _as_int(self.config.get("max_offline_days"), 7)
        )
        self.actions_per_day = max(
            1, _as_int(self.config.get("actions_per_day"), 3)
        )
        self.sandbox = bool(self.config.get("sandbox", False))
        self.realtime = bool(self.config.get("realtime", False))
        speeds = []
        for value in self.config.get("time_speeds") or (1, 2, 4, 8):
            try:
                speed = float(value)
            except (TypeError, ValueError):
                continue
            if speed >= 1.0 and speed not in speeds:
                speeds.append(speed)
        self.time_speeds = tuple(sorted(speeds or [1.0]))
        self.skill_labels = dict(self.config.get("skill_labels") or {})
        self.stat_labels = dict(self.config.get("stat_labels") or {})
        self.relation_axis_ids = relation_axes_from_config(self.config)
        self.relation_axis_labels = relation_axis_labels_from_config(
            self.config, self.relation_axis_ids
        )
        self.relation_axis_short_labels = (
            relation_axis_short_labels_from_config(
                self.config, self.relation_axis_ids
            )
        )
        self.relation_effect_weights = relation_effect_weights_from_config(
            self.config
        )
        self.relation_effect_limit = relation_effect_limit_from_config(
            self.config
        )
        self.domain_labels = {
            item["id"]: _text(item.get("label"), item["id"])
            for item in self.config["domains"]
        }
        self.domain_index = {
            item["id"]: item for item in self.config["domains"]
        }
        self.polities = {item["id"]: item for item in self.config["polities"]}
        self.offices = {item["id"]: item for item in self.config["offices"]}
        self.actions = {item["id"]: item for item in self.config["actions"]}
        self.character_order = [
            item["id"] for item in self.config["characters"]
        ]
        self.characters = {
            item["id"]: self._build_character(
                item, self.relation_axis_ids
            )
            for item in self.config["characters"]
        }
        self.player_relations = {}
        self.character_actions = {
            item["id"]: item for item in self.config["character_actions"]
        }
        self.item_order = [item["id"] for item in self.config["items"]]
        self.item_catalog = {
            item["id"]: dict(item) for item in self.config["items"]
        }
        self.item_automata = {
            item_id: normalize_item_automaton(
                item_id, item.get("automaton")
            )
            for item_id, item in self.item_catalog.items()
            if item.get("automaton")
        }
        self.norm_order = [item["id"] for item in self.config["norms"]]
        self.norms = {
            item["id"]: dict(item) for item in self.config["norms"]
        }
        self.nodes = self._build_nodes()
        self.node_order = [item["id"] for item in self.config["nodes"]]
        self._entity_kinds = {}
        for character in self.characters.values():
            self._entity_kinds[id(character)] = "character"
        for node in self.nodes.values():
            self._entity_kinds[id(node)] = _text(
                node.get("kind"), "institution"
            )
        for item in self.item_catalog.values():
            self._entity_kinds[id(item)] = "item"
        for norm in self.norms.values():
            self._entity_kinds[id(norm)] = "norm"
        self.scene_catalog = SceneCatalog.from_list(
            self.config.get("scenes") or (), source=self.config["id"]
        )
        self.scene_public_ids = {}
        for scene in self.scene_catalog:
            ids = []
            for person in scene.public:
                if person.id not in self.characters:
                    self.characters[person.id] = self._build_character(
                        person.as_character(scene.location),
                        self.relation_axis_ids,
                    )
                    self.character_order.append(person.id)
                ids.append(person.id)
                self._entity_kinds[id(self.characters[person.id])] = (
                    "character"
                )
            self.scene_public_ids[scene.id] = ids
        self.scene_id = ""
        self.scene_entered_day = 0
        self.strategies = StrategyBook.from_config(self.config)
        self.strategy_state = {}
        self.labor_market = _normalize_labor_market(
            self.config.get("labor_market") or {}
        )
        self.labor_negotiations = {}
        self.profile = normalize_profile(
            profile or self.config.get("default_profile") or {}
        )
        self.player_node_id = _text(node_id)
        self.player_office_id = _text(office_id)
        self.player_authority = 0.0
        condition = self.config.get("condition") or {}
        initial_health = _clamp(
            _as_float(condition.get("health"), HEALTH_MAX),
            0.0,
            HEALTH_MAX,
        )
        initial_sickness = _clamp(
            _as_float(condition.get("sickness"), 0.0),
            0.0,
            SICKNESS_MAX,
        )
        initial_wound = _clamp(
            _as_float(condition.get("wound"), 0.0),
            0.0,
            CAMPAIGN_WOUND_MAX,
        )
        self.player = CampaignActor(
            actions_per_day=self.actions_per_day,
            health=initial_health,
            sickness=initial_sickness,
            wound=initial_wound,
        )
        self.player_resources = _PlayerResources(
            self.player,
            {key: 0.0 for key in PLAYER_STATS},
        )
        self.player_item_ids = []
        self.granted_items = set()
        self.consumed_items = set()
        self.day = 1
        self.actions_left = self.actions_per_day
        self.action_count = 0
        self.cooldowns = {}
        self.used_actions = []
        self.log = []
        self.log_trimmed = 0
        self._lod = None
        self._lod_root = None
        self.tick_stats = {
            "ticks": 0,
            "intents": 0,
            "nodes_considered": 0,
            "nodes_skipped": 0,
            "nodes_acted": 0,
            "last_cost": 0.0,
            "last_slot": 0,
        }
        self.last_result = None
        self.outcome = None
        self.finished = False
        self.career_history = []
        self.node_action_day = {}
        self.dismissed = False
        self.dismissal_count = 0
        self.collapsed = False
        self.collapse_days = 0
        self.storyline_days = 0
        self._collapse_day = 0
        self._dismissal_day = 0
        self.last_role_change_day = -self.role_change_cooldown_days
        self.intents = IntentQueue()
        self.directives = DirectiveBook()
        self.obligations = ObligationLedger()
        self.coalitions = CoalitionBook()
        self.horizon_passed = False
        self.ending = None
        self.attached = False
        self._player_dead = False
        if snapshot:
            self.load_snapshot(snapshot)
        else:
            if self.player_node_id and self.player_office_id:
                self.attach(self.player_node_id, self.player_office_id)
            self._opening()


def build_world(
    config,
    profile=None,
    node_id=None,
    office_id=None,
    seed=None,
    snapshot=None,
):
    return WorldEngine(
        config,
        profile=profile,
        node_id=node_id,
        office_id=office_id,
        seed=seed,
        snapshot=snapshot,
    )


__all__ = [
    "DEFAULT_BIOGRAPHY_PATH",
    "DEFAULT_WORLD_PATH",
    "DOMAIN_SKILLS",
    "NODE_STATS",
    "PLAYER_STATS",
    "WorldEngine",
    "WorldError",
    "build_player_profile",
    "build_world",
    "default_worlds_dir",
    "list_worlds",
    "load_biography",
    "load_world",
    "normalize_profile",
    "office_profile_status",
    "profile_from_identity",
    "validate_world",
]


if __name__ == "__main__":
    print("campaign.world — библиотечный модуль мира, а не точка входа.")
    print("Запуск игры: python3 main.py --view")
    print("Пресеты:     python3 -m campaign --list-presets")
    print("Импорт:      from campaign.world import WorldEngine, load_world")
    raise SystemExit(0)
