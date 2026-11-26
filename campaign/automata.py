"""Кампания взаимодействия автоматов.

Класс ``AutomataCampaign`` собран из миксинов по швам: ядро и
время, действия и процессы, ИИ, персонажи, заказы, доклады и
снимок. Публичный API и формат снимка не менялись.
"""

from __future__ import annotations

from .automata_support import (
    ACTION_PROCESS_DEFAULTS,
    AI_MODEL_DEFAULTS,
    ASSET_LABELS,
    AVATAR_SCHEMA_VERSION,
    AutomataCampaignError,
    AvatarError,
    CAPABILITY_SCHEMA_VERSION,
    CONTEXT_MAX,
    CONTEXT_MIN,
    CampaignError,
    CampaignStats,
    DEBUG_DEFAULTS,
    DEFAULT_ACTIONS_PER_CYCLE,
    DEFAULT_ACTIONS_PER_TURN,
    DEFAULT_AUTOMATON_INTERACTIONS,
    DEFAULT_CHARACTER_INTERACTIONS,
    DEFAULT_OBLIGATION_KIND,
    DEFAULT_RUN_TURNS,
    DISPATCH_DEFAULTS,
    DerivedAssets,
    Dict,
    EVENT_LOG_LIMIT,
    EventEngine,
    EventError,
    FactionRuntime,
    GeometryError,
    Iterable,
    List,
    MODEL_DEFAULTS,
    Mapping,
    MetricGraph,
    ORDER_MODEL_DEFAULTS,
    ORGANIZATION_RUNTIME_DEFAULTS,
    ORGAN_MIN_WEIGHT,
    ORGAN_MODEL_DEFAULTS,
    ObligationLedger,
    Optional,
    OrganRuntime,
    OrganizationParameters,
    OrganizationRuntime,
    PHYSICAL_SECONDS_PER_REAL_SECOND,
    PRESET_DEFAULTS,
    REALTIME_DEFAULTS,
    RELATION_MODEL_DEFAULTS,
    ROUTINE_CONFIG_DEFAULTS,
    ROUTINE_DEFAULTS,
    RelationStore,
    ReportDispatcher,
    SCHEMA_VERSION,
    SNAPSHOT_TAIL,
    StateMachine,
    StateMachineCatalog,
    StateMachineError,
    SubfactionRuntime,
    WORK_TRACE_VERSION,
    _DEFAULTS_DATA,
    _as_mapping,
    _build_geometry,
    _build_subfactions,
    _character_alive,
    _character_from_record,
    _clamp,
    _dispatch_config,
    _merged_mapping,
    _nested_tuple,
    _normalize_gender,
    _number,
    _order_model,
    _order_payload,
    _organization_parameters,
    _preset_data,
    _relation_model,
    _same_id,
    _sigmoid,
    _subfaction_organ,
    _text,
    apply_asset_delta,
    apply_effects,
    apply_report,
    asset_keys,
    asset_reason,
    avatar_from_preset,
    avatar_from_snapshot,
    build_interaction_work,
    build_work,
    bump_context,
    check_conditions,
    copy,
    damage_organs,
    dataclass,
    default_dict,
    default_list,
    default_section,
    delta_map,
    derived_asset,
    derived_assets,
    field,
    load_catalog,
    load_defaults,
    logger,
    logging,
    math,
    migrate_snapshot,
    network_density,
    organ_children,
    organ_composite,
    organ_degrees,
    organ_depth,
    organ_links,
    random,
    readiness_scale,
    receive,
    relation_axis_labels_from_config,
    relation_effect,
    relation_reason,
    relax_context,
    run_routine_day,
    set_asset_value,
    spread_organ_effect,
    stamp_snapshot,
    strengthen_organ,
    tick_organs,
    trace_from_report,
    validate_organ_network,
)

from .automata_core import AutomataCoreMixin
from .automata_actions import AutomataActionsMixin
from .automata_processes import AutomataProcessesMixin
from .automata_ai import AutomataAIMixin
from .automata_characters import AutomataCharactersMixin
from .automata_orders import AutomataOrdersMixin
from .automata_reports import AutomataReportsMixin
from .automata_snapshot import AutomataSnapshotMixin


class AutomataCampaign(
    AutomataCoreMixin,
    AutomataActionsMixin,
    AutomataProcessesMixin,
    AutomataAIMixin,
    AutomataCharactersMixin,
    AutomataOrdersMixin,
    AutomataReportsMixin,
    AutomataSnapshotMixin,
):

    """Кампания фракций-автоматов."""

    def __init__(self, preset, seed=None, snapshot=None):
        data = _preset_data(preset)
        self.data = data
        try:
            self.avatar = avatar_from_preset(data)
        except AvatarError as exc:
            logger.warning("Аватар не создан: %s", exc)
            self.avatar = None
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
        limit = scenario.get("cycle_limit")
        if limit is None:
            limit = scenario.get("max_turns")
        if limit is None:
            limit = scenario.get("turns")
        try:
            limit_value = int(limit) if limit is not None else 0
        except (TypeError, ValueError):
            limit_value = 0
        self.cycle_limit = limit_value if limit_value > 0 else None
        per_cycle = scenario.get("actions_per_cycle")
        if per_cycle is None:
            per_cycle = scenario.get("actions_per_turn")
        self.actions_per_cycle = max(
            1,
            int(
                _number(
                    per_cycle,
                    DEFAULT_ACTIONS_PER_CYCLE,
                )
            ),
        )
        self.actions_left = 0
        self._turn_active = False
        self.realtime = dict(REALTIME_DEFAULTS)
        realtime_source = {
            str(key): value
            for key, value in _as_mapping(scenario.get("realtime")).items()
        }
        if (
            "cycle_seconds" not in realtime_source
            and "turn_seconds" in realtime_source
        ):
            realtime_source["cycle_seconds"] = realtime_source["turn_seconds"]
        self.realtime.update(realtime_source)
        configured_scale = _number(
            self.realtime.get("game_seconds_per_real_second"),
            PHYSICAL_SECONDS_PER_REAL_SECOND,
        )
        if not math.isclose(
            configured_scale,
            PHYSICAL_SECONDS_PER_REAL_SECOND,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            logger.warning(
                "realtime.game_seconds_per_real_second=%s нарушает "
                "физический инвариант 1:1; используется %.1f",
                configured_scale,
                PHYSICAL_SECONDS_PER_REAL_SECOND,
            )
        self.realtime["game_seconds_per_real_second"] = (
            PHYSICAL_SECONDS_PER_REAL_SECOND
        )
        speeds = [
            max(1, int(_number(value, 1)))
            for value in (self.realtime.get("speeds") or (1,))
        ]
        self.speed_levels = sorted(set(speeds)) or [1]
        self.speed = 1
        self.elapsed = 0.0
        self.action_process = dict(ACTION_PROCESS_DEFAULTS)
        self.action_process.update(
            {
                str(key): value
                for key, value in _as_mapping(
                    scenario.get("action_process")
                ).items()
            }
        )
        self.action_slots = max(
            1, int(_number(self.action_process.get("slots"), 2))
        )
        self.routine = _merged_mapping(
            ROUTINE_CONFIG_DEFAULTS, scenario.get("bdi_routine")
        )
        self.ai_model = _merged_mapping(
            AI_MODEL_DEFAULTS, scenario.get("ai_model")
        )
        self.processes: List[dict] = []
        self._process_seq = 0
        self.last_process_result = None
        self._action_progress = 0.0
        self._ai_progress = 0.0
        self._round_progress = 0.0
        self.score_streak = 0
        self.score_streak_side = None
        self.score_recent: List[float] = []
        self._npc_tick_spent_ms = 0.0
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
        self.narrative = []
        self._narrative_cause = ""
        self.briefing_seen = False
        self.history = []
        self.last_organ_result = None
        self.last_automaton_result = None
        self.last_character_result = None
        self.debug = _merged_mapping(
            DEBUG_DEFAULTS, scenario.get("debug")
        )
        self.stats = CampaignStats(self, self.debug)
        self.factions: Dict[str, FactionRuntime] = {}
        self._character_index = {}
        self._story_progress = 0.0
        self.capability_schema = CAPABILITY_SCHEMA_VERSION
        self.work_trace_version = WORK_TRACE_VERSION
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
        self.obligations = ObligationLedger()
        self.relations = RelationStore.from_config(_relation_model(data))
        self.dispatch = ReportDispatcher(self, _dispatch_config(data))
        self.order_model = _order_model(data)
        self.last_order_result = None
        self._build_factions(data)
        for faction in self.factions.values():
            self._init_character_agency(faction)
        self._seed_obligations()
        self._build_machines()
        if snapshot:
            self.load_snapshot(snapshot)
        self.stats.log(
            "campaign_start",
            preset_id=self.preset_id,
            seed=self.seed,
            player_side=self.player_side,
            rival_side=self.rival_side,
            speed_levels=list(self.speed_levels),
            factions=[
                {
                    "side": side,
                    "id": faction.id,
                    "name": faction.name,
                    "characters": len(faction.characters),
                    "organs": len(faction.organs),
                }
                for side, faction in self.factions.items()
            ],
            model=dict(self.model),
            upkeep=dict(self.upkeep),
        )


__all__ = [
    "AutomataCampaign",
    "AutomataCampaignError",
    "CAPABILITY_SCHEMA_VERSION",
    "DEFAULT_ACTIONS_PER_CYCLE",
    "DEFAULT_ACTIONS_PER_TURN",
    "DEFAULT_CHARACTER_INTERACTIONS",
    "DEFAULT_RUN_TURNS",
    "EVENT_LOG_LIMIT",
    "FactionRuntime",
    "MODEL_DEFAULTS",
    "PHYSICAL_SECONDS_PER_REAL_SECOND",
    "REALTIME_DEFAULTS",
    "WORK_TRACE_VERSION",
]
