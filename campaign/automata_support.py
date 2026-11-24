"""Общие примитивы кампании автоматов: константы, помощники,
рантаймы фракций.

Модуль выделен из ``campaign.automata``, чтобы миксины движка не
образовывали циклический импорт с фасадом. Публичные имена
реэкспортируются из ``campaign.automata``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import logging
import math
import random
from typing import Dict, Iterable, List, Mapping, Optional
from organizations.model import OrganizationParameters
from organizations.runtime import OrganizationRuntime
from systems.events import EventEngine, EventError
from .avatar import (
    AVATAR_SCHEMA_VERSION,
    AvatarError,
    avatar_from_preset,
    avatar_from_snapshot,
)
from .audit import CampaignStats, delta_map
from .conditions import asset_reason, check_conditions, relation_reason
from .dispatch import ReportDispatcher
from .effects import apply_effects, apply_report
from .routine import DEFAULTS as ROUTINE_DEFAULTS
from .routine import run_day as run_routine_day
from .work import build_interaction_work, build_work
from .work_trace import trace_from_report
from .handlers import receive
from .defaults import (
    default_dict,
    default_list,
    default_section,
    load_defaults,
)
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
    organ_children,
    organ_composite,
    organ_degrees,
    organ_depth,
    organ_links,
    readiness_scale,
    spread_organ_effect,
    strengthen_organ,
    tick_organs,
    validate_organ_network,
)
from .geometry import GeometryError, MetricGraph
from .obligations import DEFAULT_OBLIGATION_KIND, ObligationLedger
from .relations import (
    RelationStore,
    relation_axis_labels_from_config,
    relation_effect,
)
from .projections import (
    SCHEMA_VERSION,
    migrate_snapshot,
    stamp_snapshot,
)
from .state_machine import (
    StateMachine,
    StateMachineCatalog,
    StateMachineError,
    load_catalog,
)


logger = logging.getLogger(__name__)
WORK_TRACE_VERSION = 1
CAPABILITY_SCHEMA_VERSION = 2


class AutomataCampaignError(CampaignError):
    pass


def _build_geometry(faction_id, faction, organs):
    """Собрать семантическую геометрию из данных фракции.

    Явный блок ``geometry`` валидируется и падает громко: ошибка длины,
    ориентации или ссылки — это ошибка контента, а не повод молча играть
    в другом мире. Без блока работает совместимый режим: топология из
    ``links``, единичные длины и равные углы.
    """
    nodes = [str(organ.id) for organ in organs]
    links = organ_links(organs)
    record = _as_mapping(faction.get("geometry"))
    if not record:
        return MetricGraph.from_links(
            nodes, links, source="derived"
        )
    try:
        return MetricGraph.from_record(
            record, nodes=nodes, links=links, source="declared"
        )
    except GeometryError as error:
        raise AutomataCampaignError(
            "%s: геометрия: %s" % (faction_id, error)
        ) from error


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
_DEFAULTS_DATA = load_defaults()
DEFAULT_ACTIONS_PER_CYCLE = int(
    _DEFAULTS_DATA.get(
        "actions_per_cycle",
        _DEFAULTS_DATA.get("actions_per_turn", 3),
    )
)
DEFAULT_ACTIONS_PER_TURN = DEFAULT_ACTIONS_PER_CYCLE
DEFAULT_RUN_TURNS = int(default_section("run_turns_default"))
EVENT_LOG_LIMIT = int(default_section("event_log_limit"))
SNAPSHOT_TAIL = int(default_section("snapshot_tail"))
PHYSICAL_SECONDS_PER_REAL_SECOND = 1.0
REALTIME_DEFAULTS = default_dict("realtime")
ACTION_PROCESS_DEFAULTS = default_dict("action_process")
AI_MODEL_DEFAULTS = default_dict("ai_model")
try:
    DEBUG_DEFAULTS = default_dict("debug")
except Exception:  # pragma: no cover - совместимость со старым конфигом
    DEBUG_DEFAULTS = {"stats": False}
ASSET_LABELS = default_dict("asset_labels")
RELATION_MODEL_DEFAULTS = default_dict("relation_model")
ORDER_MODEL_DEFAULTS = default_dict("order_model")
try:
    DISPATCH_DEFAULTS = default_dict("dispatch")
except Exception:  # pragma: no cover - совместимость со старым конфигом
    DISPATCH_DEFAULTS = {"enabled": False}
try:
    ROUTINE_CONFIG_DEFAULTS = default_dict("bdi_routine")
except Exception:  # pragma: no cover - совместимость со старым конфигом
    ROUTINE_CONFIG_DEFAULTS = dict(ROUTINE_DEFAULTS)
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


def _merged_mapping(base, override):
    """Рекурсивно наложить ``override`` на глубокую копию ``base``.

    Копия обязательна: ``AI_MODEL_DEFAULTS`` и другие блоки данных
    разделяются между кампаниями. Иначе тест или сценарий, меняющий
    вложенный вес одной кампании, незаметно менял бы все остальные.
    """
    result = copy.deepcopy(dict(_as_mapping(base)))
    for key, value in _as_mapping(override).items():
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = _merged_mapping(current, value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _text(value, default=""):
    text = str(value or "").strip()
    return text if text else default


def _normalize_gender(value):
    """Привести пол к ``m``/``f``, сохранив пустое значение как пустое."""
    text = _text(value).lower()
    if text in ("m", "male", "man", "муж", "мужской"):
        return "m"
    if text in ("f", "female", "woman", "жен", "женский"):
        return "f"
    return ""


def _character_alive(character):
    """Жив ли персонаж: ``is_dead`` уже учитывает нулевую силу."""
    return not bool(
        getattr(
            character,
            "is_dead",
            getattr(character, "dead", False),
        )
    )


def _same_id(left, right):
    """Сравнить идентификаторы контента, допуская ``.`` и ``_``."""
    def normalize(value):
        return _text(value).replace(".", "_").lower()

    return bool(normalize(left)) and normalize(left) == normalize(right)


def _relation_model(data):
    """Блок ``relation_model``: база из defaults + переопределение сценария."""
    base = _as_mapping(RELATION_MODEL_DEFAULTS)
    override = _as_mapping(
        _as_mapping(data.get("scenario")).get("relation_model")
    )
    return _merged_mapping(base, override)


def _order_model(data):
    """Блок ``order_model``: база из defaults + переопределение сценария."""
    base = _as_mapping(ORDER_MODEL_DEFAULTS)
    override = _as_mapping(
        _as_mapping(data.get("scenario")).get("order_model")
    )
    return _merged_mapping(base, override)


def _dispatch_config(data):
    """Блок ``dispatch``: база из defaults + переопределение сценария."""
    base = _as_mapping(DISPATCH_DEFAULTS)
    override = _as_mapping(
        _as_mapping(data.get("scenario")).get("dispatch")
    )
    return _merged_mapping(base, override)


def _order_payload(effects, character_id):
    """Направить эффекты приказа конкретному персонажу.

    Приказ — нисходящая связь «фракция → человек». Ядро эффектов уже
    понимает ``character_id`` в ``needs``/``traits``/``conditions``/
    ``beliefs``/``intentions``/``morale``; здесь только подставляется
    адресат, чтобы данные приказа оставались декларативными.
    """
    character_id = _text(character_id)
    if not character_id:
        return dict(_as_mapping(effects))
    result = {}
    for key, value in _as_mapping(effects).items():
        if key in ("self", "target") and isinstance(value, Mapping):
            result[key] = _order_payload(value, character_id)
            continue
        if key == "needs" and isinstance(value, Mapping) and (
            "self" in value or "target" in value
        ):
            result[key] = {
                scope: _order_payload({key: payload}, character_id)[key]
                for scope, payload in value.items()
            }
            continue
        if key in (
            "needs",
            "traits",
            "conditions",
            "beliefs",
            "intentions",
        ) and isinstance(value, Mapping):
            item = dict(value)
            item["character_id"] = character_id
            result[key] = item
            continue
        if key == "morale":
            if isinstance(value, Mapping):
                item = dict(value)
                item["character_id"] = character_id
                result[key] = item
            else:
                result[key] = {
                    "character_id": character_id,
                    "amount": value,
                }
            continue
        result[key] = value
    return result


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
    # Легаси-граница: кампанийный персонаж — это warfare.Character,
    # который наследует simulation.UtilityAI. Импорт намеренно ленивый,
    # чтобы `import campaign.automata` не тянул simulation в sys.modules;
    # зависимость нужна только при создании персонажа.
    import warfare as W

    character = W.Character(
        record.get("name") or "Участник",
        record.get("side"),
        seed=int(record.get("seed", seed)),
        archetype=record.get("archetype") or "citizen",
        role=record.get("post_id") or record.get("role") or "citizen",
    )
    # Пресет хранит силу поста отдельно от BDI-персонажа. Без переноса
    # все кампанийные люди стартовали с одинаковой силой 10, хотя у
    # лидера Империи в контенте 26, а у главы собора — 2.
    character.force = max(
        0.0, _number(record.get("force"), character.force)
    )
    # Без явного максимума ``faction_state`` нормировала силу и энергию
    # на 1.0, и вклад персонажей в активы ``influence``/``energy``
    # всегда был равен единице. Для кампанийных персонажей потолок —
    # их стартовый запас: активы показывают, насколько он просел.
    state = getattr(character, "state", None)
    if isinstance(state, dict):
        state["max_force"] = max(
            1.0,
            _number(
                record.get("max_force"), max(1.0, character.force)
            ),
        )
        state["max_energy"] = max(
            1.0,
            _number(
                record.get("max_energy"),
                max(1.0, character.energy_pool),
            ),
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
    # Пол нужен ролевому слою: без него события «рождения» и «свадьбы»
    # выбирали двух мужчин и описывали невозможную пару. Пресет уже
    # хранит пол в записи имени, просто не переносил его в персонажа.
    character.campaign_gender = _normalize_gender(
        record.get("gender") or record.get("sex")
    )
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
    character.campaign_portrait = str(
        record.get("portrait")
        or "characters/%s" % str(record.get("id") or "unknown")
    )
    character.campaign_leader = bool(record.get("is_faction_leader"))
    character.campaign_is_player = bool(record.get("is_player"))
    character.campaign_leverage = [
        dict(item)
        for item in (record.get("leverage") or ())
        if isinstance(item, Mapping)
    ]
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
    course_weight_shift: float = 0.0
    geometry: Optional[MetricGraph] = None
    automaton_interactions: List[dict] = field(default_factory=list)
    character_interactions: List[dict] = field(default_factory=list)
    character_cooldowns: Dict[str, Dict[str, int]] = field(
        default_factory=dict
    )
    cooldowns: Dict[str, int] = field(default_factory=dict)
    low_streaks: Dict[str, int] = field(default_factory=dict)
    organization_snapshot: dict = field(default_factory=dict)
    orders: List[dict] = field(default_factory=list)
    order_cooldowns: Dict[str, int] = field(default_factory=dict)
    last_order_turn: int = 0
    last_order: dict = field(default_factory=dict)
    relations: Optional[RelationStore] = None
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
            "portrait": str(
                getattr(
                    character,
                    "campaign_portrait",
                    "characters/%s"
                    % str(getattr(character, "campaign_id", "") or ""),
                )
                or ""
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
            "goal": {
                str(key): value
                for key, value in _as_mapping(
                    getattr(character, "campaign_goal", {})
                ).items()
            },
            "agency": {
                "trust": round(
                    _clamp(_as_mapping(
                        getattr(character, "campaign_agency", {})
                    ).get("trust", 0.5)),
                    6,
                ),
                "grievance": round(
                    _clamp(_as_mapping(
                        getattr(character, "campaign_agency", {})
                    ).get("grievance", 0.0)),
                    6,
                ),
                "initiative": round(
                    _clamp(_as_mapping(
                        getattr(character, "campaign_agency", {})
                    ).get("initiative", 0.0)),
                    6,
                ),
                "assignments": int(
                    _number(_as_mapping(
                        getattr(character, "campaign_agency", {})
                    ).get("assignments"), 0)
                ),
                "orders": int(
                    _number(_as_mapping(
                        getattr(character, "campaign_agency", {})
                    ).get("orders"), 0)
                ),
                "last_order": str(
                    _as_mapping(
                        getattr(character, "campaign_agency", {})
                    ).get("last_order", "")
                    or ""
                ),
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
        Империи, Республики, культа и корпорации разные цели. Курс
        правящей подфракции добавляет небольшой сдвиг к её главному
        активу: это следствие состояния, а не отдельная ветка сюжета.
        """
        weights = self.score_weights()
        total_weight = sum(abs(value) for value in weights.values())
        if total_weight <= 0.0:
            values = list(self.assets.values())
            if not values:
                return 0.0
            return sum(values) / float(len(values))
        return sum(
            weight * self.asset(key) for key, weight in weights.items()
        ) / total_weight

    def course(self):
        """Правящая подфракция и её главный актив — из состояния."""

        if not self.subfactions:
            return {}
        dominant = max(
            self.subfactions,
            key=lambda item: (_number(item.share), str(item.id)),
        )
        assets = [
            (str(key), _number(value))
            for key, value in (dominant.assets or {}).items()
            if str(key) != "grievance"
        ]
        asset, strength = ("", 0.0)
        if assets:
            asset, strength = max(
                assets, key=lambda pair: (pair[1], pair[0])
            )
        return {
            "id": str(dominant.id),
            "label": str(dominant.label or dominant.id),
            "share": round(_clamp(dominant.share), 6),
            "asset": asset,
            "strength": round(_clamp(strength), 6),
            "organ_ids": list(dominant.organ_ids),
        }

    def score_weights(self):
        """Веса счёта с поправкой на курс правящей подфракции."""

        weights = {
            str(key): _number(value, 0.0)
            for key, value in self.score_assets.items()
        }
        course = self.course()
        asset = str(course.get("asset") or "")
        share = _number(course.get("share"))
        count = max(1, len(self.subfactions))
        dominance = max(0.0, share - 1.0 / float(count))
        shift = max(0.0, _number(self.course_weight_shift)) * dominance
        if asset and shift > 0.0:
            weights[asset] = weights.get(asset, 0.0) + shift
        return weights

    def action_course(self, action):
        """Насколько работа соответствует курсу правящей подфракции."""

        course = self.course()
        organ_id = str((action or {}).get("organ_id") or "")
        aligned = bool(
            course
            and organ_id
            and organ_id in (course.get("organ_ids") or ())
        )
        return {
            "id": str(course.get("id") or ""),
            "label": str(course.get("label") or ""),
            "asset": str(course.get("asset") or ""),
            "aligned": aligned,
        }

    def progress(self):
        """Насколько фракция продвинулась к своим целям от старта.

        Абсолютные активы дают преимущество тому, кто уже силён. Для
        кампаний, где игрок заведомо слабее в ресурсах, сравнивается
        изменение взвешенной цели. ``0.5`` — стартовый уровень.
        """
        weights = self.score_weights()
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
        children = organ_children(self.organs)
        organ_snapshots = []
        for organ in self.organs:
            item = organ.snapshot()
            item["links"] = list(links.get(organ.id, ()))
            item["degree"] = int(degrees.get(organ.id, 0))
            item["children"] = list(children.get(organ.id, ()))
            item["depth"] = organ_depth(self.organs, organ.id)
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
            "score_weights": {
                key: round(_number(value), 6)
                for key, value in self.score_weights().items()
            },
            "course": self.course(),
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
            "order_cooldowns": {
                str(key): int(value)
                for key, value in self.order_cooldowns.items()
            },
            "last_order_turn": int(self.last_order_turn),
            "last_order": dict(self.last_order),
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
