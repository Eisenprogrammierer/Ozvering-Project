from __future__ import annotations

"""Кампания взаимодействия автоматов.

Модуль не знает о «красных» и «синих», ротах или отделениях. Единица
симуляции — фракция-автомат: у неё есть состояние (assets), организация
участников (``OrganizationRuntime``) и набор работ, которыми она действует
на другие автоматы. Победа и поражение задаются данными шаблона.

**Модель работы (фазы 3–4a
[`WORK_MECHANIC_PLAN.md`](../docs/WORK_MECHANIC_PLAN.md)).**
Каждая работа и каждое взаимодействие проходят один путь:

``build_work``/``build_interaction_work`` → ``handlers.receive`` →
``WorkReport`` → ``apply_report``.

Capability хранит только шаблон работы (``template.amount/form/payload``),
шанс (``chance``) и подсказки (``hints``). Результат вычисляет обработчик
получателя; стохастика (бросок) остаётся в этом модуле и не попадает в
обработчик. Legacy-ветки и флаги миграции удалены.
"""

from dataclasses import dataclass, field
import copy
import logging
import math
import random
from typing import Dict, Iterable, List, Mapping, Optional

import warfare as W
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
from .effects import apply_effects, apply_report
from .work import build_interaction_work, build_work
from .work_trace import trace_from_report
from .handlers import receive

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

DEFAULT_ACTIONS_PER_TURN = int(default_section("actions_per_turn"))
DEFAULT_RUN_TURNS = int(default_section("run_turns_default"))
EVENT_LOG_LIMIT = int(default_section("event_log_limit"))
SNAPSHOT_TAIL = int(default_section("snapshot_tail"))
# Физический инвариант времени: при скорости 1× одна реальная секунда
# равна одной игровой секунде. Ускорение — только явный множитель
# ``speed``; пауза, замедление ниже 1× и откат запрещены. Значение из
# контента читается, но не может нарушить инвариант.
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


class AutomataCampaign:

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

    @staticmethod
    def _load_machine_catalog():
        """Прочитать исполняемые автоматы из ``configs/automata``."""
        try:
            return load_catalog()
        except (OSError, StateMachineError, ValueError) as error:
            logger.warning("Автоматы кампании не загружены: %s", error)
            return StateMachineCatalog()

    def _build_machines(self):
        """Создать рантайм автоматов для фракций, подсистем и органов.

        Явная ссылка в данных сильнее общего автомата вида:
        ``faction.automaton`` выбирает автомат фракции, ``automaton_id``
        органа — его собственный, а при его отсутствии используется
        автомат по ``kind``. ``*.default`` остаётся совместимым fallback.
        """
        self.faction_machines = {}
        self.organ_machines = {}
        self.subfaction_machines = {}
        faction_definition = self.machine_catalog.first("faction")
        organ_definition = self.machine_catalog.first("organ")
        subfaction_definition = self.machine_catalog.first("subfaction")
        for side, faction in self.factions.items():
            definition = self.machine_catalog.get(
                str(faction.record.get("automaton") or "")
            )
            definition = definition or faction_definition
            if definition is not None:
                self.faction_machines[side] = StateMachine(definition)
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
                definition = self.machine_catalog.get(
                    str(organ.automaton_id or "")
                )
                if definition is None:
                    definition = self.machine_catalog.get(
                        "organ.%s" % str(organ.kind or "")
                    )
                definition = definition or organ_definition
                machines[str(organ.id)] = StateMachine(definition)
            if machines:
                self.organ_machines[side] = machines

    def _seed_obligations(self):
        """Развернуть стартовые обязательства из постов персонажей.

        Источник — ``post.leverage``/``character_defaults.leverage``:
        каждая запись описывает рычаг, который герой имеет на персонажа.
        По умолчанию кредитор — ``"player"``, должник — сам персонаж.
        Невалидная запись пропускается: контент не должен ломать кампанию.
        """

        for faction in self.factions.values():
            for character in getattr(faction, "characters", ()) or ():
                seeds = getattr(character, "campaign_leverage", ()) or ()
                debtor_default = _text(
                    getattr(character, "campaign_id", "")
                )
                for raw in seeds:
                    if not isinstance(raw, Mapping):
                        continue
                    creditor = _text(raw.get("creditor"), "player")
                    debtor = _text(raw.get("debtor"), debtor_default)
                    kind = _text(
                        raw.get("kind"), DEFAULT_OBLIGATION_KIND
                    )
                    amount = _number(raw.get("amount"), 1.0)
                    note = _text(raw.get("note"))
                    try:
                        self.obligations.add(
                            creditor,
                            debtor,
                            kind,
                            amount,
                            created_day=self.turn,
                            note=note,
                        )
                    except CampaignError as error:
                        logger.warning(
                            "Обязательство %s/%s пропущено: %s",
                            debtor,
                            kind,
                            error,
                        )

    def add_obligation(
        self,
        creditor,
        debtor,
        kind=DEFAULT_OBLIGATION_KIND,
        amount=1.0,
        *,
        due_day=None,
        note="",
    ):
        """Создать обязательство: ``debtor`` должен ``creditor``."""

        return self.obligations.add(
            creditor,
            debtor,
            kind,
            amount,
            created_day=self.turn,
            due_day=due_day,
            note=note,
        ).to_dict()

    def fulfill_obligation(self, obligation_id, day=None):
        """Отметить обязательство исполненным."""

        obligation = self.obligations.fulfill(
            obligation_id,
            self.turn if day is None else day,
        )
        return None if obligation is None else obligation.to_dict()

    def cancel_obligation(self, obligation_id, day=None):
        """Отменить обязательство, не исполняя его."""

        obligation = self.obligations.cancel(
            obligation_id,
            self.turn if day is None else day,
        )
        return None if obligation is None else obligation.to_dict()

    def obligation_view(self, party=None, day=None):
        """Срез журнала обязательств для UI и диалога."""

        day = self.turn if day is None else int(_number(day, self.turn))
        entries = (
            self.obligations.for_party(party)
            if party is not None
            else list(self.obligations)
        )
        return {
            "summary": self.obligations.summary(day),
            "entries": [item.to_dict() for item in entries],
            "due": [
                item.to_dict() for item in self.obligations.due(day)
            ],
            "overdue": [
                item.to_dict() for item in self.obligations.overdue(day)
            ],
        }

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
            order_model = _merged_mapping(
                self.order_model, faction.get("order_model")
            )
            orders = [
                dict(item)
                for item in (
                    faction.get("orders")
                    or order_model.get("orders")
                    or ()
                )
                if isinstance(item, Mapping) and item.get("id")
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
            geometry = _build_geometry(faction_id, faction, organs)
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
                geometry=geometry,
                automaton_interactions=automaton_interactions,
                character_interactions=character_interactions,
                orders=orders,
                relations=self.relations,
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

    def relation_view(self, source=None, target=None):
        """Срез отношений для UI и диалога.

        Без аргументов — вся матрица; с ``source`` — исходящие связи
        субъекта; с ``source`` и ``target`` — обе стороны пары.
        """
        model = _relation_model(self.data)
        axes = list(self.relations.axes)
        labels = relation_axis_labels_from_config(
            {"relation_axes": model.get("axes")}, axes
        )
        if source and target:
            return {
                "source": str(source),
                "target": str(target),
                "outgoing": self.relations.axes_for(source, target),
                "incoming": self.relations.axes_for(target, source),
                "axes": axes,
                "labels": labels,
            }
        return {
            "source": str(source or ""),
            "axes": axes,
            "labels": labels,
            "limit": self.relations.limit,
            "matrix": self.relations.view(source),
        }

    def geometry(self, side):
        """Семантическая геометрия стороны или ``None``."""
        faction = self.faction(side)
        if faction is None:
            return None
        return getattr(faction, "geometry", None)

    def geometry_distance(self, side, source, target):
        """Кратчайшее расстояние по сети стороны; ``inf`` без пути."""
        graph = self.geometry(side)
        if graph is None:
            return math.inf
        return graph.distance(source, target)

    def geometry_path(self, side, source, target):
        """Канонический путь стороны или ``None``."""
        graph = self.geometry(side)
        if graph is None:
            return None
        return graph.path(source, target)

    def geometry_angle(self, side, node, source, target):
        """Локальный угол между двумя соседями узла, радианы."""
        graph = self.geometry(side)
        if graph is None:
            raise AutomataCampaignError(
                "у стороны %s нет геометрии" % side
            )
        return graph.angle(node, source, target)

    def geometry_bearing(self, side, observer, source, target):
        """Угол между направлениями на две цели из наблюдателя."""
        graph = self.geometry(side)
        if graph is None:
            raise AutomataCampaignError(
                "у стороны %s нет геометрии" % side
            )
        return graph.angle_between_targets(observer, source, target)

    @property
    def player(self):
        return self.faction(self.player_side)

    @property
    def rival(self):
        return self.faction(self.rival_side)

    def avatar_character(self):
        """``Character`` аватара или ``None``.

        Аватар может не иметь фракции (свободный режим); тогда персонаж
        ищется по всем сторонам. Отсутствие аватара не ошибка: старые
        снимки и сценарии без героя продолжают работать.
        """
        if self.avatar is None:
            return None
        if self.avatar.faction_id:
            faction = self.faction(self.avatar.faction_id)
            if faction is not None:
                found = faction.character(self.avatar.character_id)
                if found is not None:
                    return found
        for faction in self.factions.values():
            found = faction.character(self.avatar.character_id)
            if found is not None:
                return found
        return None

    def assign_avatar_office(self, office_id):
        """Сменить должность аватара; потеря поста — не поражение."""
        if self.avatar is None:
            return None
        office_id = str(office_id or "").strip()
        character = self.avatar_character()
        if character is not None:
            character.campaign_post_id = office_id
            character.campaign_post = office_id
        self.avatar = self.avatar.with_office(office_id)
        return self.avatar

    def move_avatar(self, scene_id):
        """Перевести аватара в сцену. Сцена — данные, а не сторона."""
        if self.avatar is None:
            return None
        scene_id = str(scene_id or "").strip()
        character = self.avatar_character()
        if character is not None:
            character.scene_id = scene_id
        self.avatar = self.avatar.with_scene(scene_id)
        return self.avatar

    def _sync_avatar_state(self):
        """Сделать аватар источником истины для флагов персонажа.

        Снимок хранит аватар отдельно, а ``FactionRuntime`` — записи
        персонажей. После загрузки флаги ``campaign_is_player`` и
        должность/сцена приводятся к аватару, иначе старый сейв мог бы
        оставить игроком лидера.
        """
        if self.avatar is None:
            return
        for faction in self.factions.values():
            for character in faction.characters:
                character.campaign_is_player = (
                    str(getattr(character, "campaign_id", "") or "")
                    == self.avatar.character_id
                )
        character = self.avatar_character()
        if character is None:
            return
        previous_id = str(
            getattr(character, "campaign_post_id", "") or ""
        )
        if previous_id != self.avatar.office_id:
            character.campaign_post = self.avatar.office_id
        character.campaign_post_id = self.avatar.office_id
        character.scene_id = self.avatar.scene_id

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

    def _activate_clock(self):
        """Разбудить цикл без построения полного снимка.

        Отделено от :meth:`ensure_clock`, потому что игровой цикл вызывает
        активацию каждый кадр. Полный ``snapshot()`` тяжёлый: он обходит
        персонажей, органы и производные активы, поэтому в горячем пути
        нужен только переход состояния.
        """
        if self.finished:
            return
        if not self._turn_active:
            self._turn_active = True
            if self.turn <= 0:
                self.turn = 1
            self.actions_left = max(
                self.actions_left, self.actions_per_turn
            )

    def ensure_clock(self):
        """Активировать реальное время, не сдвигая организационный цикл.

        Свободный режим идёт непрерывно: открытие экрана или действие
        игрока не являются TBS-ходом и не должны увеличивать ``turn``.
        Цикл двигают только ``advance_time`` и внутренние таймеры.
        """
        self._activate_clock()
        return self.snapshot()

    def begin_turn(self):
        """Legacy: начать ход, если он ещё не начат.

        Оставлен для старых сейвов, CLI и тестов. Игровые экраны
        используют ``ensure_clock`` и не переключают цикл вручную.
        """
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

    @property
    def realtime_scale(self):
        """Сколько игровых секунд проходит за одну реальную секунду.

        Физический инвариант проекта: масштаб всегда ``1:1``. Экран
        вызывает ``advance_realtime(dt)``; ускорение задаётся только
        множителем ``speed``, а не скрытым пересчётом часов. Старый
        контент со значением вроде ``3600`` не может ускорить время:
        при загрузке он нормализуется к ``1.0`` с предупреждением.
        """
        return PHYSICAL_SECONDS_PER_REAL_SECOND

    def time_label(self):
        """Игровое время: ``ЧЧ:ММ:СС``, а с первых суток — ``Д д ЧЧ:ММ:СС``."""
        total = max(0, int(self.elapsed))
        days, remainder = divmod(total, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        if days:
            return "%d д %02d:%02d:%02d" % (
                days,
                hours,
                minutes,
                seconds,
            )
        return "%02d:%02d:%02d" % (hours, minutes, seconds)

    def duration_label(self, seconds):
        """Человеческая длительность для UI: минуты, часы, дни, недели."""
        seconds = max(0.0, _number(seconds, 0.0))
        if seconds >= 86400.0:
            return "%.1f дн" % (seconds / 86400.0)
        if seconds >= 3600.0:
            return "%.1f ч" % (seconds / 3600.0)
        if seconds >= 60.0:
            return "%.0f мин" % (seconds / 60.0)
        return "%.0f с" % seconds

    def speed_label(self):
        # Шрифт интерфейса не содержит знака «×», поэтому темп пишется
        # латинской «x»: так подпись читается на всех экранах.
        return "x%d" % int(self.speed)

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

    def _advance_seconds(
        self, seconds, *, scale=True, tick_rounds=True, tick_ai=True
    ):
        """Продвинуть состояние без построения снимка.

        ``seconds`` — уже игровые секунды (до умножения на ``speed``).
        Это горячий путь игрового цикла: экран обновляется 60 раз в
        секунду, а ``snapshot()`` обходит всех персонажей и органы.
        Поэтому снимок строится только по явному запросу.

        ``scale=False`` нужен эмуляции: она пропускает выбранный
        интервал игрового времени целиком, не умножая его на скорость.
        ``tick_rounds=False`` и ``tick_ai=False`` тоже нужны эмуляции:
        длинный шаг не должен прогонять полную автономию персонажей и
        все ответы ИИ на каждый игровой день.
        """
        if self.finished:
            return
        if seconds <= 0.0:
            return
        self._activate_clock()
        scaled = seconds * float(self.speed) if scale else float(seconds)
        self.elapsed += scaled
        self._regenerate_actions(scaled)
        if tick_ai:
            self._advance_ai(scaled)
        self._advance_rounds(scaled, tick_rounds=tick_rounds)
        self._advance_story_events(scaled)
        self._advance_processes(scaled)

    def advance_time(self, dt, *, snapshot=True):
        """Продвинуть кампанию на ``dt`` игровых секунд.

        Это базовый вызов для тестов и legacy-кода. Игровые экраны
        используют ``advance_realtime``, который переводит реальные
        секунды кадра в игровые через ``realtime_scale``. Внутри обеих
        функций время идёт со скоростью ``speed`` (не меньше 1); работа,
        ИИ и организации обновляются непрерывно, без кнопки «завершить
        ход»; пауза, замедление и откат отсутствуют.

        ``snapshot=False`` нужен горячему пути: снимок стоит дороже
        самого шага и не нужен, пока интерфейс не запросит его явно.
        """
        try:
            seconds = float(dt)
        except (TypeError, ValueError):
            seconds = 0.0
        self._advance_seconds(seconds)
        return self.snapshot() if snapshot else None

    def advance_realtime(self, dt, *, snapshot=True):
        """Продвинуть кампанию на ``dt`` реальных секунд из игрового цикла.

        При ``1×`` это ровно ``dt`` игровых секунд; при ``2×`` — ``2·dt``.
        Никакой другой масштаб не применяется: физическое соответствие
        времени — инвариант проекта. Экраны передают ``snapshot=False``,
        чтобы не строить полный снимок каждый кадр.
        """
        try:
            seconds = float(dt)
        except (TypeError, ValueError):
            seconds = 0.0
        self._advance_seconds(seconds * self.realtime_scale)
        return self.snapshot() if snapshot else None

    def advance_simulation(self, seconds, *, snapshot=False, tick=True):
        """Пропустить ровно ``seconds`` игрового времени.

        В отличие от ``advance_time``/``advance_realtime`` множитель
        скорости не применяется: эмуляция принимает шаг в игровых часах
        или днях. Это осознанный пропуск времени, а не ускорение темпа,
        поэтому физический инвариант реального цикла не меняется.

        ``tick=False`` пропускает организационный такт и ответ ИИ:
        месяцы и годы нельзя прогонять полной автономией всех персонажей
        на каждый день. Эмуляция включает такт несколько раз за шаг,
        а работа, события и процессы считаются на всём интервале.
        """
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            seconds = 0.0
        self._advance_seconds(
            seconds, scale=False, tick_rounds=False, tick_ai=bool(tick)
        )
        if tick and not self.finished and seconds > 0.0:
            self._tick_organizations()
            self._check_outcome()
        return self.snapshot() if snapshot else None

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
                self._ai_start_work(side)

    def _ai_start_work(self, side):
        """Занять свободные слоты ИИ процессами, а не мгновенными работами."""
        started = []
        while (
            not self.finished
            and self.slot_state(side)["free"] > 0
        ):
            action_id = self.auto_action(side, exclude_active=True)
            if action_id is None:
                break
            result = self.start_action(side, action_id)
            if not result.get("ok"):
                break
            started.append(action_id)
        return started

    def _history_record(self):
        """Короткая запись хода для истории.

        Полный ``snapshot()`` обходит всех персонажей и органы. История
        нужна только как хронология циклов, поэтому хранит сводку, а не
        тяжёлый снимок мира.
        """
        return {
            "turn": int(self.turn),
            "elapsed": round(float(self.elapsed), 6),
            "outcome": self.outcome,
            "finished": bool(self.finished),
        }

    def _advance_rounds(self, seconds, *, tick_rounds=True):
        if self.finished:
            return
        self._round_progress += seconds
        interval = self.organization_interval_seconds
        if interval <= 0.0:
            return
        steps = int(self._round_progress // interval)
        if steps <= 0:
            return
        self._round_progress -= steps * interval
        if not tick_rounds:
            # Эмуляция: ходы идут, но полный такт организаций будет
            # вызван отдельными «крупными» срезами.
            self.turn += steps
            self.history.append(self._history_record())
            return
        for _ in range(steps):
            if self.finished:
                break
            self.turn += 1
            self._tick_organizations()
            self._check_outcome()
            self.history.append(self._history_record())

    # --- ролевые события -------------------------------------------
    def _story_character_stats(self, character):
        """Нормированный срез персонажа для условий событий."""
        if character is None:
            return {}
        state = getattr(character, "state", {}) or {}
        max_force = float(state.get("max_force", 10.0) or 10.0)
        max_energy = float(state.get("max_energy", 3.0) or 3.0)
        bdi = getattr(character, "bdi", None)
        return {
            "id": str(getattr(character, "campaign_id", "") or ""),
            "name": str(getattr(character, "name", "") or ""),
            "role": str(getattr(character, "campaign_role_id", "") or ""),
            "post": str(getattr(character, "campaign_post", "") or ""),
            "organ_id": str(
                getattr(character, "campaign_organ_id", "") or ""
            ),
            "alive": not bool(getattr(character, "is_dead", False)),
            "morale": round(
                _clamp(float(getattr(character, "morale", 0.0)) / 100.0),
                6,
            ),
            "force": round(
                _clamp(
                    float(getattr(character, "force", 0.0))
                    / max(1e-9, max_force)
                ),
                6,
            ),
            "energy": round(
                _clamp(
                    float(getattr(character, "energy_pool", 0.0))
                    / max(1e-9, max_energy)
                ),
                6,
            ),
            "needs": dict(getattr(character, "needs", {}) or {}),
            "conditions": (
                dict(bdi.conditions) if bdi is not None else {}
            ),
            "beliefs": (
                [item.as_dict() for item in bdi.beliefs]
                if bdi is not None
                else []
            ),
            "intentions": (
                [item.as_dict() for item in bdi.intentions]
                if bdi is not None
                else []
            ),
        }

    def _story_relations(self, leader):
        """Проекция убеждений-отношений лидера: объект → предикат → сила.

        Слой отражения читает только то, что уже записано в BDI. Никакого
        отдельного хранилища отношений не появляется (G-11 остаётся
        отдельной задачей).
        """
        bdi = getattr(leader, "bdi", None)
        config = getattr(bdi, "config", None)
        if bdi is None or config is None:
            return {}
        relations = {}
        for belief in bdi.beliefs:
            spec = config.predicate(belief.predicate) or {}
            if str(spec.get("kind") or "") != "relation":
                continue
            target = str(belief.object or "").strip()
            if not target:
                continue
            strength = _clamp(
                float(belief.value) * float(belief.confidence)
            )
            bucket = relations.setdefault(target, {})
            bucket[belief.predicate] = max(
                float(bucket.get(belief.predicate, 0.0)), strength
            )
        return relations

    def _story_organization(self, faction):
        """Снимок организации для событий: свежий или сохранённый."""
        state = {}
        organization = getattr(faction, "organization", None)
        if organization is not None:
            try:
                state = dict(organization.snapshot())
            except Exception:
                logger.exception("не удалось прочитать снимок организации")
        if not state:
            state = dict(
                _as_mapping(getattr(faction, "organization_snapshot", {}))
            )
        state.setdefault("name", str(getattr(faction, "name", "") or ""))
        return state

    def _story_context(self, side=None):
        """Контекст для условий/видимости событий.

        Берётся лидер фракции (по умолчанию — игрок). Числа нормированы в
        ``0..1``, чтобы условия в JSON были переносимыми. Помимо лидера
        контекст видит активы, органы, флаги, ростер персонажей, намерения
        и отношения — событие отражает фракцию, а не один силуэт.
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
        rival_faction = self.faction(self.rival_of(side))
        rival_leader = (
            rival_faction.characters[0]
            if rival_faction is not None and rival_faction.characters
            else None
        )
        target_character = (
            faction.characters[1]
            if len(faction.characters) > 1
            else rival_leader
        )
        rival_name = str(
            getattr(rival_leader, "name", "")
            or getattr(rival_faction, "name", "")
            or ""
        )
        characters = {}
        for character in faction.characters:
            stats = self._story_character_stats(character)
            if stats.get("id"):
                characters[stats["id"]] = stats
        return {
            "id": str(getattr(leader, "campaign_id", "") or ""),
            "name": str(getattr(leader, "name", "") or ""),
            "actor": str(getattr(leader, "name", "") or ""),
            "target": str(getattr(target_character, "name", "") or ""),
            "rival": rival_name,
            "side": side,
            "faction_id": str(getattr(faction, "id", "") or ""),
            "faction_name": str(getattr(faction, "name", "") or ""),
            "organization": str(getattr(faction, "name", "") or ""),
            "organization_state": self._story_organization(faction),
            "rival_id": str(getattr(rival_faction, "id", "") or ""),
            "rival_organization": rival_name,
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
            "intentions": (
                [item.as_dict() for item in bdi.intentions]
                if bdi is not None
                else []
            ),
            "relations": self._story_relations(leader),
            "assets": {
                str(key): float(value)
                for key, value in faction.assets.items()
            },
            "organs": {
                str(organ.id): float(organ.integrity)
                for organ in faction.organs
            },
            "organ_statuses": {
                str(organ.id): organ.status() for organ in faction.organs
            },
            "organ_scales": {
                str(organ.id): dict(organ.scales)
                for organ in faction.organs
            },
            "flags": dict(getattr(faction, "flags", {}) or {}),
            "characters": characters,
            "character_count": len(faction.characters),
            "priority_needs": list(
                _as_mapping(faction.record).get("priority_needs") or ()
            ),
            "goals": list(
                _as_mapping(faction.record).get("goals") or ()
            ),
            "doctrine": dict(
                _as_mapping(
                    _as_mapping(faction.record).get("doctrine")
                )
            ),
            "turn": int(self.turn),
            "used_actions": sorted(
                str(key)
                for key, value in faction.action_uses.items()
                if int(value) > 0
            ),
            "force": max(
                0.0,
                float(getattr(leader, "force", 0.0))
                / max(
                    1e-9,
                    float(
                        getattr(leader, "state", {}).get(
                            "max_force", 10.0
                        )
                    ),
                ),
            ),
            "energy": max(
                0.0,
                float(getattr(leader, "energy_pool", 0.0))
                / max(
                    1e-9,
                    float(
                        getattr(leader, "state", {}).get(
                            "max_energy", 3.0
                        )
                    ),
                ),
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
        # Контекст события — дорогой срез всех персонажей и органов.
        # Строим его только когда событие действительно может сработать,
        # а не каждый кадр: ``advance`` нужен лишь для хода времени.
        self.story_engine.advance(seconds)
        self._story_progress += max(0.0, float(seconds))
        interval = max(4.0, self.organization_interval_seconds * 0.5)
        spawned = []
        context = None
        render_context = None
        while self._story_progress >= interval:
            self._story_progress -= interval
            if context is None:
                context = self._story_context()
                # Условия читают структуры (активы, органы, ростер), а
                # тексту нужны только имена. Разделяем, чтобы словари не
                # попадали в подстановки и в контекст события.
                render_context = {
                    key: context[key]
                    for key in (
                        "actor",
                        "target",
                        "rival",
                        "organization",
                        "rival_organization",
                    )
                    if context.get(key)
                }
            instance = self.story_engine.trigger(
                context=context, render_context=render_context
            )
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
        self.ensure_clock()
        if self.actions_left <= 0:
            return (
                "бюджет действий исчерпан: действия восстанавливаются "
                "со временем (до %d за интервал)" % self.actions_per_turn
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
            "relations": (
                self.relations.view(faction.id)
                if faction is not None
                else {}
            ),
            "target_relations": (
                self.relations.view(target.id)
                if target is not None
                else {}
            ),
            "relation_store": self.relations,
        }

    def _action_requirement_reason(
        self, faction, action, target=None, assets=None
    ):
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
            "нужно",
            assets if assets is not None else faction.assets,
            requires.get("self"),
        )
        if reason:
            return reason
        if target is not None:
            reason = self._asset_requirement_reason(
                "цель", target.assets, requires.get("target")
            )
            if reason:
                return reason
        reason = relation_reason(
            "нужно",
            requires.get("relations"),
            self.relations,
            getattr(faction, "id", ""),
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
        assets = derived_assets(faction)
        options = []
        for action in faction.actions:
            cost = _as_mapping(action.get("cost"))
            affordable = all(
                assets.get(str(key), 0.0) + 1e-9 >= _number(value, 0.0)
                for key, value in cost.items()
            )
            left = self._cooldown_left(faction, action, turn=turn)
            target = self.faction(self._target_side(side, action))
            used_reason = self._action_use_reason(faction, action)
            requirement_reason = self._action_requirement_reason(
                faction, action, target, assets=assets
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
        assets = derived_assets(faction)
        options = []
        for interaction in organ.interactions:
            cost = _as_mapping(interaction.get("cost"))
            affordable = all(
                assets.get(str(key), 0.0) + 1e-9
                >= _number(value, 0.0)
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

    def _busy_interaction(self, side, kind, interaction_id, target_id):
        for record in self._active_processes(side):
            if record.get("kind") != kind:
                continue
            if str(record.get("interaction_id")) != str(interaction_id):
                continue
            if str(record.get("target_id")) != str(target_id):
                continue
            return record
        return None

    def _start_interaction_process(
        self,
        side,
        kind,
        interaction,
        *,
        label,
        description,
        target_id,
        target_name,
    ):
        """Занять слот взаимодействием и применить его по завершении.

        Влияния и команды больше не тратят отдельный запас действий:
        единственный лимит — два слота. Стоимость списывается сразу,
        эффект применяется в :meth:`_finish_process`, когда процесс
        доходит до ``finish_at``. Это позволяет видеть в интерфейсе
        занятость слотов и не выполнять одно и то же действие дважды.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        self._activate_clock()
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        interaction_id = str(
            interaction.get("id") or kind
        )
        busy = self._busy_interaction(
            side, kind, interaction_id, target_id
        )
        if busy is not None:
            return {
                "ok": False,
                "reason": "это действие уже выполняется",
            }
        slots = self.slot_state(faction.side)
        if slots["free"] <= 0:
            return {
                "ok": False,
                "reason": "заняты все слоты (%d)" % slots["slots"],
                "slots": slots,
            }
        cost = {
            str(key): _number(value)
            for key, value in _as_mapping(
                interaction.get("cost")
            ).items()
        }
        for key, value in cost.items():
            faction.add_asset(key, -value)
        seconds = self._interaction_duration(kind, interaction)
        self._process_seq += 1
        record = {
            "id": "process-%d" % self._process_seq,
            "kind": str(kind),
            "phase": "interaction",
            "side": faction.side,
            "action_id": interaction_id,
            "interaction_id": interaction_id,
            "label": str(label or interaction.get("label") or kind),
            "description": str(
                description or interaction.get("description") or ""
            ),
            "target_side": str(kind),
            "target_id": str(target_id or ""),
            "target_name": str(target_name or ""),
            "turn": int(self.turn),
            "started": round(float(self.elapsed), 6),
            "finish_at": round(float(self.elapsed) + float(seconds), 6),
            "duration": round(float(seconds), 6),
            "remaining": round(float(seconds), 6),
            "cost": cost,
            "interaction": copy.deepcopy(dict(interaction)),
            "status": "active",
        }
        self.processes.append(record)
        self._log_process(record, "начата")
        result = {
            "ok": True,
            "started": True,
            "side": faction.side,
            "kind": str(kind),
            "turn": self.turn,
            "interaction_id": interaction_id,
            "label": record["label"],
            "description": record["description"],
            "target_id": record["target_id"],
            "target_name": record["target_name"],
            "duration": record["duration"],
            "cost": dict(cost),
            "process": dict(record),
            "slots": self.slot_state(faction.side),
            "actions_left": self.actions_left,
        }
        for key in (
            "organ_id",
            "character_id",
            "source_organ_id",
            "target_organ_id",
            "relation",
        ):
            if key in interaction:
                result[key] = interaction[key]
        return result

    def _apply_organ_interaction(
        self, faction, organ, interaction, label, description
    ):
        """Применить уже начатое влияние на орган (без списания цены)."""
        record = dict(interaction)
        record["organ_id"] = organ.id
        plan = build_interaction_work(
            record,
            "organ_interaction",
            faction,
            faction,
            self,
        )
        if plan is None:
            return {
                "ok": False,
                "reason": "работа взаимодействия не собрана",
            }
        try:
            report = receive(
                plan.to_work(),
                plan,
                faction,
                faction,
                self,
                success=True,
            )
        except Exception as exc:
            logger.warning(
                "Обработчик organ_interaction не сработал: %s", exc
            )
            return {
                "ok": False,
                "reason": "обработчик взаимодействия: %s" % exc,
            }
        cost = _as_mapping(interaction.get("cost"))
        before = organ.integrity
        apply_report(
            faction,
            faction,
            report,
            scale=1.0,
            source="organ_interaction",
        )
        delta = organ.integrity - before
        spread = spread_organ_effect(
            faction, organ, delta, self.model
        )
        organ.used_turn = self.turn
        result = {
            "ok": True,
            "turn": self.turn,
            "actions_left": self.actions_left,
            "side": faction.side,
            "organ_id": organ.id,
            "organ_name": organ.name,
            "organ_kind": organ.kind,
            "interaction_id": str(interaction.get("id")),
            "label": str(label or interaction.get("label") or ""),
            "description": str(
                description or interaction.get("description") or ""
            ),
            "integrity_before": round(before, 6),
            "integrity_after": round(organ.integrity, 6),
            "integrity_delta": round(delta, 6),
            "faction_spread": round(spread, 6),
            "cost": {
                str(key): round(_number(value), 6)
                for key, value in cost.items()
            },
            "text": str(
                interaction.get("text")
                or description
                or interaction.get("description")
                or ""
            ),
            "status": organ.status(),
        }
        if report is not None:
            result["report"] = report.as_dict()
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

    def perform_organ_interaction(
        self, side, organ_id, interaction_id, *, defer=True
    ):
        """Повлиять на орган: усилить, реформировать, почистить, снабдить.

        По умолчанию влияние занимает свободный слот и применяется,
        когда процесс завершится. ``defer=False`` оставлен для
        синхронных legacy-вызовов (``advance(organ_action=...)``).
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        if not defer:
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
        interaction = copy.deepcopy(dict(option["interaction"]))
        interaction["organ_id"] = organ.id
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if defer:
            result = self._start_interaction_process(
                side,
                "organ",
                interaction,
                label=option["label"],
                description=option["description"],
                target_id=organ.id,
                target_name=organ.name,
            )
            if result.get("ok") and cooldown > 0:
                organ.interaction_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            if result.get("ok"):
                organ.used_turn = self.turn
            return result
        for key, value in _as_mapping(interaction.get("cost")).items():
            faction.add_asset(key, -_number(value))
        result = self._apply_organ_interaction(
            faction,
            organ,
            interaction,
            option["label"],
            option["description"],
        )
        if result.get("ok"):
            if cooldown > 0:
                organ.interaction_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            self._spend_player_action(side)
            result["actions_left"] = self.actions_left
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
        assets = derived_assets(faction)
        options = []
        for interaction in faction.automaton_interactions:
            cost = _as_mapping(interaction.get("cost"))
            affordable = all(
                assets.get(str(key), 0.0) + 1e-9
                >= _number(value, 0.0)
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

    def _apply_automaton_interaction(
        self,
        faction,
        source,
        target,
        interaction,
        label,
        description,
    ):
        """Применить уже начатую команду автомата (без списания цены)."""
        record = dict(interaction)
        record["source_organ_id"] = source.id
        record["target_organ_id"] = target.id
        plan = build_interaction_work(
            record,
            "automaton_interaction",
            faction,
            faction,
            self,
        )
        if plan is None:
            return {
                "ok": False,
                "reason": "работа взаимодействия не собрана",
            }
        try:
            report = receive(
                plan.to_work(),
                plan,
                faction,
                faction,
                self,
                success=True,
            )
        except Exception as exc:
            logger.warning(
                "Обработчик automaton_interaction не сработал: %s", exc
            )
            return {
                "ok": False,
                "reason": "обработчик взаимодействия: %s" % exc,
            }
        cost = _as_mapping(interaction.get("cost"))
        source_before = source.integrity
        target_before = target.integrity
        apply_report(
            faction,
            faction,
            report,
            scale=1.0,
            source="automaton_interaction",
        )
        source_delta = source.integrity - source_before
        target_delta = target.integrity - target_before
        source_spread = spread_organ_effect(
            faction, source, source_delta, self.model
        )
        target_spread = spread_organ_effect(
            faction, target, target_delta, self.model
        )
        source.used_turn = self.turn
        target.used_turn = self.turn
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
            "label": str(label or interaction.get("label") or ""),
            "description": str(
                description or interaction.get("description") or ""
            ),
            "relation": str(interaction.get("relation") or "any"),
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
            "text": str(
                interaction.get("text")
                or description
                or interaction.get("description")
                or ""
            ),
            "status": target.status(),
        }
        if report is not None:
            result["report"] = report.as_dict()
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

    def perform_automaton_interaction(
        self,
        side,
        source_organ_id,
        target_organ_id,
        interaction_id,
        *,
        defer=True,
    ):
        """Провести команду одного автомата другому внутри своей сети.

        По умолчанию команда занимает слот и применяется по завершении
        процесса. ``defer=False`` — синхронный legacy-путь.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        if not defer:
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
        interaction = copy.deepcopy(dict(option["interaction"]))
        interaction["source_organ_id"] = source.id
        interaction["target_organ_id"] = target.id
        interaction["relation"] = option.get("relation", "any")
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if defer:
            result = self._start_interaction_process(
                side,
                "automaton",
                interaction,
                label=option["label"],
                description=option["description"],
                target_id=target.id,
                target_name=target.name,
            )
            if result.get("ok") and cooldown > 0:
                source.interaction_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            if result.get("ok"):
                source.used_turn = self.turn
                target.used_turn = self.turn
            return result
        for key, value in _as_mapping(interaction.get("cost")).items():
            faction.add_asset(key, -_number(value))
        result = self._apply_automaton_interaction(
            faction,
            source,
            target,
            interaction,
            option["label"],
            option["description"],
        )
        if result.get("ok"):
            if cooldown > 0:
                source.interaction_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            self._spend_player_action(side)
            result["actions_left"] = self.actions_left
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
        assets = derived_assets(faction)
        options = []
        for interaction in faction.character_interactions:
            cost = _as_mapping(interaction.get("cost"))
            affordable = all(
                assets.get(str(key), 0.0) + 1e-9
                >= _number(value, 0.0)
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

    def _apply_interaction_relations(
        self, faction, character, interaction
    ):
        """Записать отношения взаимодействия «фракция ↔ персонаж».

        Блок ``relations`` у взаимодействия может быть простым словарём
        осей или объектом ``{"source": "character", "axes": {...}}``.
        По умолчанию источник — фракция, потому что эффект применяет она.
        """
        raw = _as_mapping(interaction.get("relations"))
        if not raw or self.relations is None:
            return []
        axes = _as_mapping(raw.get("axes")) if "axes" in raw else raw
        if not axes:
            return []
        mode = _text(raw.get("source") or raw.get("from"), "faction")
        faction_id = str(getattr(faction, "id", "") or "")
        character_id = str(
            getattr(character, "campaign_id", "") or ""
        )
        if not faction_id or not character_id:
            return []
        if mode in ("character", "target", "self_character"):
            source, target = character_id, faction_id
        else:
            source, target = faction_id, character_id
        changes = self.relations.add(source, target, axes, 1.0)
        return [
            {
                "source": source,
                "target": target,
                "axis": str(axis),
                "delta": delta,
            }
            for axis, delta in changes.items()
        ]

    def _apply_character_interaction(
        self, faction, character, interaction, label, description
    ):
        """Применить уже начатое действие персонала (без списания цены)."""
        if character is None or bool(
            getattr(character, "is_dead", False)
        ) or bool(getattr(character, "dead", False)):
            return {"ok": False, "reason": "персонаж недоступен"}
        organ = faction.organ(
            getattr(character, "campaign_organ_id", "")
        )
        record = dict(interaction)
        record["character_id"] = str(
            getattr(character, "campaign_id", "")
        )
        record["organ_id"] = organ.id if organ is not None else ""
        plan = build_interaction_work(
            record,
            "character_interaction",
            faction,
            faction,
            self,
        )
        if plan is None:
            return {
                "ok": False,
                "reason": "работа взаимодействия не собрана",
            }
        try:
            report = receive(
                plan.to_work(),
                plan,
                faction,
                faction,
                self,
                success=True,
            )
        except Exception as exc:
            logger.warning(
                "Обработчик character_interaction не сработал: %s", exc
            )
            return {
                "ok": False,
                "reason": "обработчик взаимодействия: %s" % exc,
            }
        cost = _as_mapping(interaction.get("cost"))
        needs_snapshot = {
            str(key): _clamp(value)
            for key, value in character.needs.items()
        }
        morale_before = _number(character.morale)
        organ_before = organ.integrity if organ is not None else None
        apply_report(
            faction,
            faction,
            report,
            scale=1.0,
            source="character_interaction",
        )
        relation_changes = self._apply_interaction_relations(
            faction, character, interaction
        )
        needs_before = {}
        for key, before_value in needs_snapshot.items():
            after_value = _clamp(character.needs.get(key, 0.0))
            if abs(after_value - before_value) > 1e-9:
                needs_before[key] = before_value
        organ_delta = 0.0
        if organ is not None and organ_before is not None:
            organ_delta = organ.integrity - organ_before
            spread_organ_effect(
                faction, organ, organ_delta, self.model
            )
        result = {
            "ok": True,
            "turn": self.turn,
            "actions_left": self.actions_left,
            "side": faction.side,
            "character_id": str(
                getattr(character, "campaign_id", "")
            ),
            "character_name": str(getattr(character, "name", "")),
            "post": str(getattr(character, "campaign_post", "") or ""),
            "interaction_id": str(interaction.get("id")),
            "label": str(label or interaction.get("label") or ""),
            "description": str(
                description or interaction.get("description") or ""
            ),
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
            "relations": relation_changes,
            "text": str(
                interaction.get("text")
                or description
                or interaction.get("description")
                or ""
            ),
        }
        if report is not None:
            result["report"] = report.as_dict()
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

    def perform_character_interaction(
        self, side, character_id, interaction_id, *, defer=True
    ):
        """Применить действие к выбранному персонажу.

        По умолчанию действие занимает слот и применяется по завершении
        процесса. ``defer=False`` — синхронный legacy-путь.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        if not defer:
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
        interaction = copy.deepcopy(dict(option["interaction"]))
        interaction["character_id"] = str(
            getattr(character, "campaign_id", character_id)
        )
        cooldown = int(_number(interaction.get("cooldown"), 0))
        if defer:
            result = self._start_interaction_process(
                side,
                "character",
                interaction,
                label=option["label"],
                description=option["description"],
                target_id=interaction["character_id"],
                target_name=str(getattr(character, "name", "")),
            )
            if result.get("ok") and cooldown > 0:
                character.campaign_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            return result
        for key, value in _as_mapping(interaction.get("cost")).items():
            faction.add_asset(key, -_number(value))
        result = self._apply_character_interaction(
            faction,
            character,
            interaction,
            option["label"],
            option["description"],
        )
        if result.get("ok"):
            if cooldown > 0:
                character.campaign_cooldowns[
                    str(interaction.get("id"))
                ] = self.turn
            self._spend_player_action(side)
            result["actions_left"] = self.actions_left
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

    def _log_work(self, result):
        self.log.append(result)
        trace = result.get("trace")
        if not isinstance(trace, Mapping):
            trace = {}
        detail = (
            "ход %d: %s → %s работой «%s» (%s); amount=%.3f "
            "eff=%.3f stored=%.3f loss=%.3f entropy=%.3f; "
            "шанс %.3f, бросок %.3f, успех=%s"
            % (
                result["turn"],
                result["actor_name"],
                result["target_name"],
                result["label"],
                result["form"],
                _number(trace.get("amount"), 0.0),
                _number(trace.get("efficiency"), 0.0),
                _number(trace.get("stored"), 0.0),
                _number(trace.get("loss"), 0.0),
                _number(trace.get("entropy"), 0.0),
                result["chance"],
                result["roll"],
                "да" if result["success"] else "нет",
            )
        )
        if trace.get("essence"):
            detail += "; суть=%s" % trace["essence"]
        if result.get("reason"):
            detail += "; причина: %s" % result["reason"]
        logger.debug("%s", detail)
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

    def _action_intention(self, action, actor, target_faction):
        """Собрать дуплет намерения из подсказок capability.

        Авторская метка живёт в ``hints.intention_essence`` (fallback —
        ``hints.essence``), цель — в ``hints.intention_target``. Старый
        блок ``intention`` читается только как совместимый fallback.
        Пустой/алиасный target разрешается в фактическую цель работы,
        поэтому один и тот же шаблон работает для любой стороны.
        """
        action = _as_mapping(action)
        hints = _as_mapping(action.get("hints"))
        raw = _as_mapping(action.get("intention"))
        essence = str(
            hints.get("intention_essence")
            or hints.get("essence")
            or raw.get("essence")
            or action.get("essence")
            or ""
        ).strip()
        if not essence:
            return None
        target = str(
            hints.get("intention_target") or raw.get("target") or ""
        ).strip()
        if target == "self":
            target = actor.id
        elif target in (
            "",
            "target",
            "rival",
            "any",
            "all",
            "all_rivals",
            "other",
            "strongest",
            "weakest",
        ):
            target = (
                target_faction.id
                if target_faction is not None
                else actor.id
            )
        return {"target": target, "essence": essence}

    def perform(self, side, action_id, target=None):
        """Выполнить работу стороны.

        Работа строится из capability (``build_work``), проходит через
        ``handlers.receive`` и применяется как ``WorkReport.projections``
        через ``apply_report``. Провал — это ветка ``failure`` в правиле
        обработчика, а не отдельный словарь эффектов в capability.
        """
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
        return self._resolve_action(
            actor,
            action,
            action_id,
            target_side,
            target_faction,
            charge_cost=True,
            spend_budget=True,
        )

    def _resolve_action(
        self,
        actor,
        action,
        action_id,
        target_side,
        target_faction,
        charge_cost=True,
        spend_budget=False,
        effect_fraction=1.0,
        executor=None,
    ):
        """Рассчитать и применить работу без предварительных гейтов.

        Общая часть ``perform`` и завершения процесса: бросок, обработчик,
        эффекты, перезарядка и запись в журнал. Стоимость списывает
        вызывающий: ``perform`` — сразу, процесс — при запуске.

        ``effect_fraction`` позволяет применить только часть проекций.
        Процесс делает так первый импульс, а остаток разворачивает во
        времени через ``_advance_effects``. Legacy ``perform`` передаёт
        ``1.0`` и остаётся мгновенным.
        """
        side = actor.side
        stats_before = None
        if self.stats.enabled and self.stats.actions:
            stats_before = {
                "actor": self.stats.assets(actor),
                "target": self.stats.assets(target_faction),
            }
        cost = _as_mapping(action.get("cost"))
        chance_spec = _as_mapping(action.get("chance"))
        attack_asset = str(
            chance_spec.get("attack")
            or action.get("attack_asset")
            or "influence"
        )
        defense_asset = str(
            chance_spec.get("defense")
            or action.get("defense_asset")
            or "cohesion"
        )
        attack_value = actor.asset(attack_asset)
        defense_value = (
            actor.asset(defense_asset)
            if target_faction.side == actor.side
            else target_faction.asset(defense_asset)
        )
        base = _number(
            chance_spec.get("base"),
            _number(action.get("base"), self.model["success_base"]),
        )
        slope = _number(
            chance_spec.get("slope"),
            _number(action.get("slope"), self.model["success_slope"]),
        )
        form = self._action_form(action)
        relation_shift = 0.0
        if (
            self.relations is not None
            and target_faction.id != actor.id
        ):
            relation_shift = self.relations.effect(
                target_faction.id, actor.id, form
            )
        chance = _sigmoid(
            base
            + slope * (attack_value - defense_value)
            + relation_shift
        )
        roll = self.rng.random()
        success = roll < chance
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

        plan = build_work(action, actor, target_faction, self)
        if plan is None:
            return {
                "ok": False,
                "reason": "работа не собрана: нет template/amount",
            }
        try:
            report = receive(
                plan.to_work(),
                plan,
                actor,
                target_faction,
                self,
                success=success,
            )
        except Exception as exc:
            logger.warning("Обработчик работы не сработал: %s", exc)
            return {
                "ok": False,
                "reason": "обработчик работы: %s" % exc,
            }
        if charge_cost:
            for key, value in cost.items():
                actor.add_asset(key, -_number(value))
        fraction = max(0.0, min(1.0, _number(effect_fraction, 1.0)))
        executor_support = 0.0
        executor_competence = 0.0
        executor_factor = 1.0
        if executor is not None:
            agency = self._agency_model()
            effect_model = _as_mapping(agency.get("executor_effect"))
            executor_support = self._character_support(
                executor, action, actor
            )
            executor_competence = self._character_competence(executor)
            spec = 1.0 + _number(
                effect_model.get("support_weight"), 0.2
            ) * executor_support + _number(
                effect_model.get("competence_weight"), 0.15
            ) * (executor_competence - 0.5)
            executor_factor = max(
                _number(effect_model.get("min_factor"), 0.7),
                min(
                    _number(effect_model.get("max_factor"), 1.25),
                    spec,
                ),
            )
        effect_scale = (
            self.model["effect_scale"]
            * readiness
            * repeat_scale
            * executor_factor
        )
        applied = apply_report(
            actor,
            target_faction,
            report,
            scale=effect_scale * fraction,
            source="work",
        )
        intention = (
            self._action_intention(action, actor, target_faction)
            if success
            else None
        )
        trace_essence = str(
            (report.trace or {}).get("essence")
            or plan.essence_hint
            or ""
        )
        if intention is not None:
            if trace_essence:
                intention = dict(intention, essence=trace_essence)
            apply_effects(
                actor,
                {"self": {"intentions": {"push": [intention]}}},
                target=None,
                scale=1.0,
                source="work",
            )
        try:
            trace = trace_from_report(
                plan, chance, roll, success, report
            ).as_dict()
        except Exception:
            trace = None
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
        if spend_budget:
            self._spend_player_action(actor.side)
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
            "form": str(plan.form),
            "attack_asset": attack_asset,
            "attack_value": round(attack_value, 6),
            "defense_asset": defense_asset,
            "defense_value": round(defense_value, 6),
            "chance": round(chance, 6),
            "relation_shift": round(relation_shift, 6),
            "roll": round(roll, 6),
            "success": bool(success),
            "effect_scale": round(effect_scale, 6),
            "effect_fraction": round(fraction, 6),
            "executor_id": str(
                getattr(executor, "campaign_id", "") or ""
            ),
            "executor_name": str(
                getattr(executor, "name", "") or ""
            ),
            "executor_support": round(executor_support, 6),
            "executor_competence": round(executor_competence, 6),
            "executor_factor": round(executor_factor, 6),
            "intention": dict(intention or {}),
            "trace": trace,
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
            "text": str(action.get("text") or ""),
        }
        result["report"] = report.as_dict()
        if stats_before is not None:
            assets_after = {
                "actor": self.stats.assets(actor),
                "target": self.stats.assets(target_faction),
            }
            applied_log = {
                key: value
                for key, value in applied.items()
                if key != "report"
            }
            self.stats.log(
                "work",
                side=actor.side,
                actor_id=actor.id,
                actor=actor.name,
                target_side=target_faction.side,
                target_id=target_faction.id,
                target=target_faction.name,
                action_id=str(action_id),
                label=str(action.get("label") or action_id),
                form=str(plan.form),
                chance_formula={
                    "base": round(base, 6),
                    "slope": round(slope, 6),
                    "attack_asset": attack_asset,
                    "attack_value": round(attack_value, 6),
                    "defense_asset": defense_asset,
                    "defense_value": round(defense_value, 6),
                    "difference": round(
                        attack_value - defense_value, 6
                    ),
                    "relation_shift": round(relation_shift, 6),
                    "logit": round(
                        base
                        + slope * (attack_value - defense_value)
                        + relation_shift,
                        6,
                    ),
                    "chance": round(chance, 6),
                    "roll": round(roll, 6),
                    "success": bool(success),
                },
                modifiers={
                    "readiness": round(readiness, 6),
                    "repeat_uses": used_before,
                    "repeat_decay": round(decay, 6),
                    "repeat_scale": round(repeat_scale, 6),
                    "effect_scale": round(effect_scale, 6),
                    "effect_fraction": round(fraction, 6),
                    "executor_support": round(executor_support, 6),
                    "executor_competence": round(
                        executor_competence, 6
                    ),
                    "executor_factor": round(executor_factor, 6),
                },
                cost=result["cost"],
                applied=applied_log,
                trace=trace,
                report=(
                    report.as_dict()
                    if self.stats.verbose_report
                    else None
                ),
                assets_before=stats_before,
                assets_after=assets_after,
                asset_deltas={
                    "actor": delta_map(
                        stats_before["actor"], assets_after["actor"]
                    ),
                    "target": delta_map(
                        stats_before["target"], assets_after["target"]
                    ),
                },
                organ={
                    "id": str(action.get("organ_id") or ""),
                    "integrity": round(
                        organ.integrity if organ is not None else 1.0,
                        6,
                    ),
                    "readiness": round(readiness, 6),
                    "status": (
                        organ.status() if organ is not None else "нет"
                    ),
                },
            )
        self._log_work(result)
        return result

    # --- процессы действий -----------------------------------------
    def _active_processes(self, side=None):
        side = None if side is None else str(side)
        return [
            record
            for record in self.processes
            if record.get("status") == "active"
            and (side is None or str(record.get("side")) == side)
        ]

    def active_processes(self, side=None):
        """Копии активных процессов: для UI и диалогового моста."""
        return [dict(record) for record in self._active_processes(side)]

    def settling_processes(self, side=None):
        """Процессы, чей эффект ещё разворачивается во времени."""
        side = None if side is None else str(side)
        return [
            dict(record)
            for record in self.processes
            if _as_mapping(record.get("effect")).get("status")
            == "settling"
            and (side is None or str(record.get("side")) == side)
        ]

    def ongoing_processes(self, side=None):
        """Подготовка и разворачивающийся эффект — для панели времени."""
        return self.active_processes(side) + self.settling_processes(side)

    def slot_state(self, side=None):
        """Сколько слотов занято и свободно у стороны."""
        side = str(side or self.player_side)
        used = len(self._active_processes(side))
        return {
            "side": side,
            "slots": self.action_slots,
            "used": used,
            "free": max(0, self.action_slots - used),
        }

    def _duration_unit_seconds(self):
        """Сколько игровых секунд в одной единице ``template.duration``.

        В данных единица — час: ``duration_scale=3600``. Старые пресеты
        могли использовать секунды; они задают свой ``duration_scale``.
        """
        return max(
            0.0,
            _number(
                self.action_process.get("duration_unit"),
                _number(self.action_process.get("duration_scale"), 3600.0),
            ),
        )

    def _duration_class_hours(self, name):
        raw = _as_mapping(
            self.action_process.get("duration_classes")
        ).get(str(name))
        if isinstance(raw, Mapping):
            raw = raw.get("hours")
        return max(0.0, _number(raw, 0.0))

    def _action_duration(self, action, duration=None):
        """Длительность работы в игровых секундах.

        Приоритет: явное значение вызова, поле ``duration`` работы,
        ``template.duration`` (часы по умолчанию) с множителем из
        ``action_process.duration_scale``. Если задан
        ``template.duration_class`` (``hours``/``day``/``week``/…), его
        часы умножаются на ``template.duration`` и ``duration_unit``.
        Всё берётся из данных.
        """
        minimum = max(
            0.0, _number(self.action_process.get("min_duration"), 1.0)
        )
        if duration is not None:
            return max(minimum, _number(duration, minimum))
        explicit = action.get("duration")
        if explicit is not None:
            return max(minimum, _number(explicit, minimum))
        template = _as_mapping(action.get("template"))
        class_hours = self._duration_class_hours(
            template.get("duration_class")
        )
        if class_hours > 0.0:
            raw = template.get("duration")
            multiplier = 1.0 if raw is None else _number(raw, 1.0)
            return max(
                minimum,
                class_hours
                * max(0.0, multiplier)
                * self._duration_unit_seconds(),
            )
        scale = _number(
            self.action_process.get("duration_scale"),
            _number(self.action_process.get("default_duration"), 1.0),
        )
        raw = template.get("duration")
        if raw is None:
            raw = 1.0
        return max(minimum, _number(raw, 1.0) * max(0.0, scale))

    def _interaction_duration(self, kind, interaction, duration=None):
        """Длительность влияния или команды с учётом политики видов.

        Шаблоны в лорных фракциях исторически хранят ``duration: 1.0``
        (час). Реалистичный темп задаётся один раз в
        ``action_process.interaction_durations``: реформа — недели,
        повышение — неделя, поддержка — часы. Явная длительность
        вызова остаётся главнее политики.
        """
        minimum = max(
            0.0, _number(self.action_process.get("min_duration"), 1.0)
        )
        if duration is not None:
            return max(minimum, _number(duration, minimum))
        explicit = interaction.get("duration")
        if explicit is not None:
            return max(minimum, _number(explicit, minimum))
        policies = _as_mapping(
            self.action_process.get("interaction_durations")
        )
        entry = _as_mapping(
            _as_mapping(policies.get(str(kind))).get(
                str(interaction.get("id"))
            )
        )
        class_hours = self._duration_class_hours(entry.get("class"))
        if class_hours > 0.0:
            amount = _number(entry.get("amount"), 1.0)
            return max(
                minimum,
                class_hours
                * max(0.0, amount)
                * self._duration_unit_seconds(),
            )
        return self._action_duration(interaction, duration)

    def _action_effect_window(self, action, duration):
        """Сколько игровых секунд эффект действия разворачивается.

        Явное ``effect_duration`` в действии — часы. Иначе окно считается
        от длительности по коэффициенту формы из
        ``action_process.effect_window``. Это позволяет эдикту действовать
        неделями, а медицинской помощи — часами.
        """
        explicit = action.get("effect_duration")
        if explicit is not None:
            return max(
                0.0,
                _number(explicit, 0.0) * self._duration_unit_seconds(),
            )
        model = _as_mapping(
            self.action_process.get("effect_window")
        )
        form = self._action_form(action)
        by_form = _as_mapping(model.get("by_form"))
        scale = _number(
            by_form.get(form),
            _number(model.get("default_scale"), 1.0),
        )
        return max(0.0, _number(duration, 0.0) * max(0.0, scale))

    def _process_for_action(self, side, action_id):
        for record in self._active_processes(side):
            if str(record.get("action_id")) == str(action_id):
                return record
        return None

    def process_for_action(self, side, action_id):
        record = self._process_for_action(side, action_id)
        return dict(record) if record is not None else None

    def start_action(self, side, action_id, target=None, duration=None):
        """Начать процесс работы: слот, оплата и длительность.

        Эффект не применяется сразу. Процесс завершается в
        ``advance_time``; к этому моменту мир мог измениться, поэтому
        предпосылки проверяются повторно. Бюджет хода не тратится:
        ограничение — число слотов и время.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        actor = self.faction(side)
        if actor is None or actor.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        action = actor.action(action_id)
        if action is None:
            return {"ok": False, "reason": "действие не найдено"}
        if self._process_for_action(side, action_id) is not None:
            return {"ok": False, "reason": "действие уже выполняется"}
        slots = self.slot_state(actor.side)
        if slots["free"] <= 0:
            return {
                "ok": False,
                "reason": "заняты все слоты (%d)" % slots["slots"],
                "slots": slots,
            }
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
                "slots": slots,
            }
        target_side = self._target_side(side, action, target=target)
        target_faction = self.faction(target_side)
        if target_faction is None:
            return {"ok": False, "reason": "нет цели", "slots": slots}
        cost = {
            str(key): _number(value)
            for key, value in _as_mapping(action.get("cost")).items()
        }
        for key, value in cost.items():
            actor.add_asset(key, -value)
        seconds = self._action_duration(action, duration)
        executor = self._choose_executor(actor.side, action)
        self._process_seq += 1
        record = {
            "id": "process-%d" % self._process_seq,
            "side": actor.side,
            "action_id": str(action_id),
            "label": str(action.get("label") or action_id),
            "target_side": target_faction.side,
            "target_id": target_faction.id,
            "target_name": target_faction.name,
            "turn": int(self.turn),
            "started": round(float(self.elapsed), 6),
            "finish_at": round(float(self.elapsed) + float(seconds), 6),
            "duration": round(float(seconds), 6),
            "remaining": round(float(seconds), 6),
            "cost": cost,
            "executor_id": str(
                getattr(executor, "campaign_id", "") or ""
            ),
            "executor_name": str(
                getattr(executor, "name", "") or ""
            ),
            "executor_support": round(
                self._character_support(executor, action, actor)
                if executor is not None
                else 0.0,
                6,
            ),
            "executor_competence": round(
                self._character_competence(executor)
                if executor is not None
                else 0.0,
                6,
            ),
            "status": "active",
        }
        self.processes.append(record)
        self._remember_assignment(executor, record, started=True)
        self._log_process(record, "начата")
        if self.stats.enabled and self.stats.actions:
            self.stats.log(
                "process_start",
                process_id=record["id"],
                side=record["side"],
                action_id=record["action_id"],
                label=record["label"],
                target_side=record["target_side"],
                target_id=record["target_id"],
                target_name=record["target_name"],
                duration=record["duration"],
                finish_at=record["finish_at"],
                cost=record["cost"],
                executor_id=record["executor_id"],
                executor_name=record["executor_name"],
                slots=self.slot_state(actor.side),
            )
        return {
            "ok": True,
            "process": dict(record),
            "slots": self.slot_state(actor.side),
            "actions_left": self.actions_left,
        }

    def _refund_process(self, record):
        if not bool(self.action_process.get("refund_on_cancel", True)):
            return
        actor = self.faction(record.get("side"))
        if actor is None:
            return
        for key, value in _as_mapping(record.get("cost")).items():
            actor.add_asset(key, _number(value))

    def _cancel_process(self, record, reason):
        record["status"] = "cancelled"
        record["reason"] = str(reason or "процесс отменён")
        record["finished"] = round(float(self.elapsed), 6)
        record["remaining"] = 0.0
        self._refund_process(record)
        self.last_process_result = dict(record)
        self._log_process(record, "отменена")
        self._log_process_stats(record)

    def _log_process_stats(self, record, result=None):
        """Записать начало/конец процесса в файловый аудит."""
        if not self.stats.enabled or not self.stats.actions:
            return
        result = _as_mapping(result)
        summary = {}
        for key in (
            "ok",
            "reason",
            "interaction_id",
            "organ_id",
            "organ_name",
            "integrity_before",
            "integrity_after",
            "integrity_delta",
            "morale_before",
            "morale_after",
            "needs_before",
            "needs_after",
            "faction_spread",
            "status",
            "text",
        ):
            if key in result:
                summary[key] = result[key]
        self.stats.log(
            "process_finish",
            process_id=record.get("id"),
            kind=record.get("kind") or "work",
            side=record.get("side"),
            action_id=record.get("action_id"),
            label=record.get("label"),
            target_side=record.get("target_side"),
            target_id=record.get("target_id"),
            target_name=record.get("target_name"),
            status=record.get("status"),
            duration=record.get("duration"),
            started=record.get("started"),
            finished=record.get("finished"),
            reason=record.get("reason", ""),
            result=summary,
        )

    def _finish_interaction_process(self, record):
        """Завершить влияние/команду и применить её эффект."""
        kind = str(record.get("kind") or "")
        faction = self.faction(record.get("side"))
        interaction = _as_mapping(record.get("interaction"))
        label = record.get("label")
        description = record.get("description")
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        if kind == "organ":
            organ = faction.organ(record.get("target_id"))
            if organ is None:
                return {"ok": False, "reason": "орган не найден"}
            return self._apply_organ_interaction(
                faction,
                organ,
                interaction,
                label,
                description,
            )
        if kind == "automaton":
            source = faction.organ(
                interaction.get("source_organ_id")
                or record.get("source_organ_id")
            )
            target = faction.organ(
                interaction.get("target_organ_id")
                or record.get("target_id")
            )
            if source is None:
                return {
                    "ok": False,
                    "reason": "автомат-источник не найден",
                }
            if target is None:
                return {
                    "ok": False,
                    "reason": "автомат-цель не найден",
                }
            return self._apply_automaton_interaction(
                faction,
                source,
                target,
                interaction,
                label,
                description,
            )
        if kind == "character":
            character = faction.character(record.get("target_id"))
            if character is None:
                return {"ok": False, "reason": "персонаж не найден"}
            return self._apply_character_interaction(
                faction,
                character,
                interaction,
                label,
                description,
            )
        return {"ok": False, "reason": "неизвестный процесс"}

    def _finish_process(self, record):
        if str(record.get("kind") or "") in (
            "organ",
            "automaton",
            "character",
        ):
            result = self._finish_interaction_process(record)
            record["finished"] = round(float(self.elapsed), 6)
            record["remaining"] = 0.0
            if result.get("ok"):
                record["status"] = "done"
                record["result"] = result
            else:
                record["status"] = "cancelled"
                record["reason"] = result.get(
                    "reason"
                ) or "действие не выполнено"
                self._refund_process(record)
            self.last_process_result = dict(record)
            self._log_process(
                record,
                "завершена" if result.get("ok") else "отменена",
            )
            self._log_process_stats(record, result)
            return result
        actor = self.faction(record.get("side"))
        action_id = str(record.get("action_id") or "")
        target_side = str(record.get("target_side") or "")
        target_faction = self.faction(target_side)
        reason = ""
        if actor is None or actor.dissolved:
            reason = "фракция недоступна"
        elif target_faction is None:
            reason = "нет цели"
        else:
            action = actor.action(action_id)
            if action is None:
                reason = "действие не найдено"
            elif bool(self.action_process.get("recheck_on_finish", True)):
                reason = self._action_use_reason(
                    actor, action
                ) or self._action_requirement_reason(
                    actor, action, target_faction
                )
            if not reason:
                initial = max(
                    0.0,
                    min(
                        1.0,
                        _number(
                            self.action_process.get(
                                "effect_initial_share"
                            ),
                            1.0,
                        ),
                    ),
                )
                executor = (
                    actor.character(record.get("executor_id"))
                    if actor is not None
                    else None
                )
                result = self._resolve_action(
                    actor,
                    action,
                    action_id,
                    target_side,
                    target_faction,
                    charge_cost=False,
                    spend_budget=False,
                    effect_fraction=initial,
                    executor=executor,
                )
                record["finished"] = round(float(self.elapsed), 6)
                record["remaining"] = 0.0
                record["result"] = result
                self._remember_assignment(
                    executor,
                    record,
                    success=bool(result.get("success")),
                )
                if result.get("ok"):
                    record["status"] = "done"
                    self._start_settlement(
                        record,
                        action,
                        _number(record.get("duration"), 0.0),
                        initial,
                    )
                else:
                    record["status"] = "cancelled"
                    record["reason"] = result.get(
                        "reason"
                    ) or "работа не выполнена"
                    self._refund_process(record)
                self.last_process_result = dict(record)
                self._log_process(record, "завершена")
                self._log_process_stats(record, result)
                return
        self._cancel_process(record, reason)

    def _start_settlement(self, record, action, duration, initial=1.0):
        """Начать постепенное разворачивание эффекта действия.

        Подготовка (``status="done"``) закончена, но проекции работы
        применяются не разом: первый импульс уже прошёл вместе с
        завершением, остаток распределяется по окну
        ``action_process.effect_window``. Поэтому эдикт продолжает
        действовать дни и недели, а не «срабатывает» в один кадр.
        """
        effect = _as_mapping(record.get("effect"))
        initial = max(0.0, min(1.0, _number(initial, 1.0)))
        remaining = max(0.0, 1.0 - initial)
        window = self._action_effect_window(action, duration)
        pulses = max(
            1,
            int(_number(self.action_process.get("effect_pulses"), 8)),
        )
        power = max(0.1, _number(
            self.action_process.get("effect_curve_power"), 1.5
        ))
        if remaining <= 1e-9 or window <= 0.0:
            effect.update(
                {
                    "initial": round(initial, 6),
                    "applied": round(initial, 6),
                    "effective": round(initial, 6),
                    "remaining": 0.0,
                    "pulses": 0,
                    "next_pulse": 0,
                    "status": "settled",
                    "started": round(float(self.elapsed), 6),
                    "finish_at": round(float(self.elapsed), 6),
                }
            )
            record["effect"] = effect
            return
        interval = window / float(pulses)
        effect.update(
            {
                "initial": round(initial, 6),
                "applied": round(initial, 6),
                "effective": round(initial, 6),
                "remaining": round(remaining, 6),
                "window": round(window, 6),
                "interval": round(interval, 6),
                "pulses": pulses,
                "next_pulse": 1,
                "curve_power": power,
                "started": round(float(self.elapsed), 6),
                "next_at": round(float(self.elapsed) + interval, 6),
                "finish_at": round(float(self.elapsed) + window, 6),
                "status": "settling",
            }
        )
        record["effect"] = effect
        self._log_effect(
            record,
            "эффект начал разворачиваться",
            "окно %.1f ч, импульсов %d" % (
                window / max(1.0, self._duration_unit_seconds()),
                pulses,
            ),
        )

    def _effect_condition_factor(self, record):
        """Насколько обстоятельства усиливают или гасят эффект.

        Данные ``action_process.settlement`` задают опорные активы,
        препятствия и вес органов. Мир меняется между импульсами, поэтому
        один и тот же эдикт в сильной и слабой фракции действует
        по-разному.
        """
        actor = self.faction(record.get("side"))
        if actor is None or actor.dissolved:
            return 0.0
        result = _as_mapping(record.get("result"))
        model = _as_mapping(self.action_process.get("settlement"))
        factor = 1.0
        support = [
            str(item)
            for item in (model.get("support_assets") or ())
            if str(item)
        ]
        if support:
            average = sum(actor.asset(key) for key in support) / float(
                len(support)
            )
            factor *= 0.5 + _clamp(average)
        obstacles = [
            str(item)
            for item in (model.get("obstacle_assets") or ())
            if str(item)
        ]
        threshold = _number(model.get("obstacle_threshold"), 0.35)
        penalty = _number(model.get("obstacle_penalty"), 0.6)
        for key in obstacles:
            if actor.asset(key) < threshold:
                factor *= max(0.05, penalty)
        organ_id = str(result.get("organ_id") or "")
        organ = actor.organ(organ_id) if organ_id else None
        if organ is not None:
            organ_weight = _clamp(_number(
                model.get("organ_weight"), 0.35
            ))
            factor *= 1.0 - organ_weight * (1.0 - _clamp(organ.integrity))
        target = self.faction(record.get("target_side"))
        defense_asset = str(result.get("defense_asset") or "")
        if target is not None and defense_asset:
            resistance = _clamp(target.asset(defense_asset))
            factor *= max(
                0.2,
                1.0
                - _clamp(_number(model.get("defense_weight"), 0.3))
                * resistance,
            )
        # Исполнитель продолжает влиять на эффект и после подготовки:
        # его поддержка цели и компетентность записаны в результат
        # процесса и переживают сохранение/загрузку.
        factor *= _number(result.get("executor_factor"), 1.0)
        return max(
            _number(model.get("min_factor"), 0.1),
            min(_number(model.get("max_factor"), 1.6), factor),
        )

    def _pulse_effect(self, record):
        effect = _as_mapping(record.get("effect"))
        if not effect or effect.get("status") != "settling":
            return
        index = int(_number(effect.get("next_pulse"), 1))
        total = max(1, int(_number(effect.get("pulses"), 1)))
        power = max(0.1, _number(effect.get("curve_power"), 1.5))
        remaining = max(0.0, _number(effect.get("remaining"), 0.0))
        weights = [float(i) ** power for i in range(index, total + 1)]
        weight_sum = sum(weights) or 1.0
        fraction = remaining * weights[0] / weight_sum
        factor = self._effect_condition_factor(record)
        result = _as_mapping(record.get("result"))
        report = _as_mapping(result.get("report"))
        actor = self.faction(record.get("side"))
        target = self.faction(record.get("target_side"))
        base_scale = _number(
            result.get("effect_scale"), self.model["effect_scale"]
        )
        applied = apply_report(
            actor,
            target,
            report,
            scale=base_scale * fraction * factor,
            source="process",
        )
        effect["applied"] = round(
            _number(effect.get("applied"), 0.0) + fraction, 6
        )
        effect["effective"] = round(
            _number(effect.get("effective"), 0.0) + fraction * factor, 6
        )
        effect["remaining"] = round(max(0.0, remaining - fraction), 6)
        effect["next_pulse"] = index + 1
        effect["last_factor"] = round(factor, 6)
        effect["last_scale"] = round(base_scale * fraction * factor, 6)
        effect["last_applied"] = applied
        started = _number(effect.get("started"), self.elapsed)
        interval = _number(effect.get("interval"), 0.0)
        if index >= total or effect["remaining"] <= 1e-9:
            effect["status"] = "settled"
            effect["finish_at"] = round(float(self.elapsed), 6)
            effect["next_at"] = round(float(self.elapsed), 6)
        else:
            effect["next_at"] = round(
                started + interval * float(index + 1), 6
            )
        record["effect"] = effect
        if self.stats.enabled and self.stats.effects:
            self.stats.log(
                "effect_pulse",
                process_id=record.get("id"),
                side=record.get("side"),
                action_id=record.get("action_id"),
                label=record.get("label"),
                pulse=index,
                pulses=total,
                fraction=round(fraction, 6),
                condition_factor=round(factor, 6),
                base_scale=round(base_scale, 6),
                effective_scale=round(
                    base_scale * fraction * factor, 6
                ),
                remaining=effect.get("remaining"),
                status=effect.get("status"),
                applied={
                    key: value
                    for key, value in applied.items()
                    if key != "report"
                },
            )
        self._log_effect(
            record,
            "импульс эффекта",
            "%.0f%% применено, множитель обстоятельств %.2f" % (
                effect["applied"] * 100.0,
                factor,
            ),
        )

    def _advance_effects(self):
        """Провести импульсы эффектов, у которых подошло время."""
        for record in list(self.processes):
            effect = _as_mapping(record.get("effect"))
            if effect.get("status") != "settling":
                continue
            guard = 0
            while (
                _as_mapping(record.get("effect")).get("status")
                == "settling"
                and self.elapsed + 1e-9
                >= _number(
                    _as_mapping(record.get("effect")).get(
                        "next_at", float("inf")
                    ),
                    float("inf"),
                )
                and guard < 10000
            ):
                self._pulse_effect(record)
                guard += 1
            effect = _as_mapping(record.get("effect"))
            if effect.get("status") == "settled":
                self._log_effect(
                    record, "эффект завершён", "действие перестало меняться"
                )

    def _log_effect(self, record, phase, detail=""):
        self.events.append(
            {
                "turn": int(self.turn),
                "kind": "effect",
                "phase": str(phase),
                "process_id": record.get("id"),
                "side": record.get("side"),
                "action_id": record.get("action_id"),
                "label": record.get("label"),
                "remaining": _as_mapping(record.get("effect")).get(
                    "remaining"
                ),
                "text": "эффект «%s»: %s%s"
                % (
                    record.get("label") or record.get("action_id"),
                    phase,
                    (" (%s)" % detail) if detail else "",
                ),
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]

    def _advance_processes(self, seconds):
        if self.finished:
            return
        expired = []
        for record in self._active_processes():
            remaining = _number(record.get("remaining"), 0.0) - seconds
            record["remaining"] = round(max(0.0, remaining), 6)
            if remaining <= 0.0:
                expired.append(record)
        expired.sort(
            key=lambda item: (
                _number(item.get("finish_at"), self.elapsed),
                str(item.get("id")),
            )
        )
        for record in expired:
            self._finish_process(record)
        self._advance_effects()
        self._trim_processes()

    def _log_process(self, record, phase):
        self.events.append(
            {
                "turn": int(self.turn),
                "kind": "process",
                "phase": str(phase),
                "process_id": record.get("id"),
                "side": record.get("side"),
                "action_id": record.get("action_id"),
                "label": record.get("label"),
                "status": record.get("status"),
                "remaining": record.get("remaining"),
                "reason": record.get("reason", ""),
                "text": "процесс «%s» %s" % (
                    record.get("label") or record.get("action_id"),
                    phase,
                ),
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]

    def _trim_processes(self):
        limit = max(
            1, int(_number(self.action_process.get("log_limit"), 40))
        )
        if len(self.processes) <= limit:
            return
        active = [
            record
            for record in self.processes
            if record.get("status") == "active"
        ]
        settling = [
            record
            for record in self.processes
            if _as_mapping(record.get("effect")).get("status")
            == "settling"
        ]
        done = [
            record
            for record in self.processes
            if record.get("status") != "active"
            and _as_mapping(record.get("effect")).get("status")
            != "settling"
        ]
        keep = max(0, limit - len(active) - len(settling))
        self.processes = (
            active + settling + done[-keep:] if keep else active + settling
        )

    def _leader(self, side):
        """Лидер фракции: первый персонаж, чьи BDI/органы ведут политику."""
        faction = self.faction(side)
        if faction is None or not faction.characters:
            return None
        return faction.characters[0]

    def _action_form(self, action):
        action = _as_mapping(action)
        return _text(
            action.get("form")
            or _as_mapping(action.get("template")).get("form")
        )

    def _action_essences(self, action):
        hints = _as_mapping(_as_mapping(action).get("hints"))
        values = [
            _text(hints.get("essence")),
            _text(hints.get("intention_essence")),
        ]
        return [value for value in values if value]

    def _action_need(self, essence, leader):
        if leader is None or not essence:
            return ""
        config = getattr(getattr(leader, "bdi", None), "config", None)
        if config is None:
            return ""
        return _text(config.need_for_essence(essence))

    # --- автономия персонажей -------------------------------------
    def _agency_model(self):
        return _as_mapping(
            _as_mapping(self.ai_model).get("character_agency")
        )

    def _agency_enabled(self):
        return bool(self._agency_model().get("enabled", False))

    def _agency_state(self, character, faction=None):
        """Личная память персонажа: доверие, обида, инициатива.

        Состояние живёт на самом персонаже и попадает в снимок. Старые
        сейвы без блока получают нейтральные значения, поэтому загрузка
        не ломается.
        """
        raw = getattr(character, "campaign_agency", None)
        state = dict(raw) if isinstance(raw, Mapping) else {}
        state["trust"] = _clamp(_number(state.get("trust"), 0.5))
        state["grievance"] = _clamp(
            _number(state.get("grievance"), 0.0)
        )
        state["initiative"] = _clamp(
            _number(state.get("initiative"), 0.0)
        )
        state["assignments"] = max(
            0, int(_number(state.get("assignments"), 0))
        )
        state["orders"] = max(0, int(_number(state.get("orders"), 0)))
        state["last_order"] = _text(state.get("last_order"))
        memory = [
            dict(item)
            for item in (state.get("memory") or ())
            if isinstance(item, Mapping)
        ]
        state["memory"] = memory[-8:]
        return state

    def _goal_need(self, character):
        """Ведущая потребность персонажа для личной цели.

        Сначала читаются BDI-желания, затем сырые потребности. Сортировка
        по имени делает выбор детерминированным и не тратит
        ``character.rng``.
        """
        values = _as_mapping(getattr(character, "desires", {}))
        if not values:
            values = _as_mapping(getattr(character, "needs", {}))
        if not values:
            return ""
        need, _value = max(
            values.items(),
            key=lambda item: (_number(item[1]), str(item[0])),
        )
        return _text(need)

    def _goal_target(self, character, faction, kind):
        """Разрешить вид цели в конкретный объект мира.

        Виды целей приходят из данных: ``organ`` (свой орган или самый
        целый орган фракции), ``faction``, ``rival``, ``leader``, ``self``.
        Неизвестный вид безопасно сводится к личности самого персонажа.
        """
        kind = _text(kind, "self")
        if kind == "organ" and faction is not None:
            organ_id = _text(
                getattr(character, "campaign_organ_id", "")
            )
            organ = faction.organ(organ_id) if organ_id else None
            if organ is None and faction.organs:
                organ = max(
                    faction.organs,
                    key=lambda item: (
                        _number(getattr(item, "integrity", 0.0)),
                        str(getattr(item, "id", "")),
                    ),
                )
            if organ is not None:
                return str(organ.id), str(
                    getattr(organ, "name", organ.id)
                )
            return str(faction.id), str(faction.name)
        if kind == "faction" and faction is not None:
            return str(faction.id), str(faction.name)
        if kind == "rival":
            rival_side = _text(self.rival_side)
            if faction is not None and rival_side == faction.side:
                rival_side = next(
                    (
                        side
                        for side in self.factions
                        if side != faction.side
                    ),
                    "",
                )
            rival = self.faction(rival_side)
            if rival is not None:
                return str(rival.id), str(rival.name)
        if kind == "leader" and faction is not None and faction.characters:
            leader = faction.characters[0]
            if leader is not character:
                return (
                    str(getattr(leader, "campaign_id", "")),
                    str(getattr(leader, "name", "")),
                )
            return str(faction.id), str(faction.name)
        return (
            str(getattr(character, "campaign_id", "")),
            str(getattr(character, "name", "")),
        )

    def _character_goal(self, character, faction=None):
        """Личная цель персонажа из данных ``character_agency.goals``."""
        model = self._agency_model()
        goals = _as_mapping(model.get("goals"))
        by_need = _as_mapping(goals.get("by_need"))
        kinds = _as_mapping(goals.get("kinds"))
        default_kind = _text(goals.get("default_kind"), "duty")
        need = self._goal_need(character)
        kind = _text(by_need.get(need), default_kind)
        spec = _as_mapping(kinds.get(kind))
        if not spec:
            spec = _as_mapping(kinds.get(default_kind))
        if not spec:
            spec = {
                "label": kind,
                "essence": need or "seek_order",
                "target": "faction",
            }
        essence = _text(spec.get("essence"), need or "seek_order")
        target_kind = _text(spec.get("target"), "self")
        target, target_name = self._goal_target(
            character, faction, target_kind
        )
        return {
            "kind": kind,
            "label": _text(spec.get("label"), kind),
            "need": need,
            "essence": essence,
            "target_kind": target_kind,
            "target": target,
            "target_name": target_name,
            "started": int(self.turn),
            "revised": int(self.turn),
        }

    def _init_character_agency(self, faction):
        """Завести цели и память всем персонажам фракции.

        Вызывается после сборки фракций и после загрузки снимка. Уже
        существующие цель и память сохраняются: старый сейв остаётся
        источником истины.
        """
        if not self._agency_enabled() or faction is None:
            return
        for character in faction.characters:
            character.campaign_agency = self._agency_state(
                character, faction
            )
            goal = getattr(character, "campaign_goal", None)
            if (
                not isinstance(goal, Mapping)
                or not _text(goal.get("kind"))
            ):
                character.campaign_goal = self._character_goal(
                    character, faction
                )

    def _character_competence(self, character):
        """Компетентность исполнителя по чертам из данных."""
        model = self._agency_model()
        traits = [
            _text(item)
            for item in (model.get("competence_traits") or ())
            if _text(item)
        ]
        if not traits:
            return 0.5
        values = _as_mapping(
            getattr(getattr(character, "personality", None), "values", {})
        )
        total = sum(_clamp(values.get(trait, 0.0)) for trait in traits)
        return total / float(len(traits))

    def _character_support(self, character, action, faction=None):
        """Насколько персонаж поддерживает работу или саботирует её.

        Поддержка складывается из личной цели, BDI-намерения, потребности
        и совпадения адресата. Доверие и инициатива усиливают вклад,
        обида его гасит. При высокой обиде персонаж переходит к саботажу,
        и работа теряет вес.
        """
        model = self._agency_model()
        if not bool(model.get("enabled", False)) or character is None:
            return 0.0
        if bool(
            getattr(
                character,
                "is_dead",
                getattr(character, "dead", False),
            )
        ):
            return 0.0
        if faction is None:
            faction = self.faction(str(getattr(character, "side", "")))
        essences = self._action_essences(action)
        need = ""
        for essence in essences:
            need = self._action_need(essence, character)
            if need:
                break
        target = None
        if faction is not None:
            target = self.faction(
                self._target_side(faction.side, action)
            )
        target_id = _text(getattr(target, "id", ""))
        state = self._agency_state(character, faction)
        goal = _as_mapping(getattr(character, "campaign_goal", {}))
        goal_weight = _number(model.get("goal_weight"), 0.35)
        target_weight = _number(model.get("target_weight"), 0.2)
        intention_weight = _number(model.get("intention_weight"), 0.25)
        need_weight = _number(model.get("need_weight"), 0.2)
        trust_weight = _number(model.get("trust_weight"), 0.25)
        grievance_weight = _number(model.get("grievance_weight"), 0.45)
        initiative_weight = _number(
            model.get("initiative_weight"), 0.15
        )
        sabotage_weight = _number(model.get("sabotage_weight"), 0.35)
        sabotage_floor = _number(model.get("sabotage_floor"), 0.35)
        urgency_floor = _number(model.get("urgency_floor"), 0.25)

        support = 0.0
        if _text(goal.get("essence")) in essences:
            support += goal_weight
        if need and _text(goal.get("need")) == need:
            support += goal_weight * 0.5
        if (
            target_id
            and _text(goal.get("target"))
            and _same_id(goal.get("target"), target_id)
        ):
            support += target_weight
        bdi = getattr(character, "bdi", None)
        intention = (
            bdi.latest_intention()
            if bdi is not None
            and callable(getattr(bdi, "latest_intention", None))
            else None
        )
        desires = _as_mapping(getattr(character, "desires", {}))
        urgency = max(
            [_number(value) for value in desires.values()] or [0.0]
        )
        if (
            intention is not None
            and _text(getattr(intention, "essence", "")) in essences
            and urgency >= urgency_floor
        ):
            support += intention_weight * urgency
        if need:
            support += need_weight * _clamp(
                _as_mapping(getattr(character, "needs", {})).get(need)
            )
        trust = _clamp(state.get("trust", 0.5))
        initiative = _clamp(state.get("initiative", 0.0))
        grievance = _clamp(state.get("grievance", 0.0))
        support *= 1.0 + trust_weight * (trust - 0.5) * 2.0
        support *= 1.0 + initiative_weight * initiative
        support -= grievance_weight * grievance
        if grievance >= sabotage_floor:
            support -= sabotage_weight * grievance
        return support

    def _remember_assignment(self, character, record, success=None,
                             started=False):
        """Запомнить назначение на работу и его исход."""
        if character is None or not self._agency_enabled():
            return {}
        faction = self.faction(_text(record.get("side")))
        state = self._agency_state(character, faction)
        model = self._agency_model()
        if started:
            state["assignments"] = (
                max(0, int(state.get("assignments", 0))) + 1
            )
            state["initiative"] = _clamp(
                state.get("initiative", 0.0)
                + _number(model.get("initiative_gain"), 0.2) * 0.25
            )
        if success is True:
            state["trust"] = _clamp(
                state.get("trust", 0.5)
                + _number(model.get("order_trust"), 0.1) * 0.5
            )
            state["grievance"] = _clamp(
                state.get("grievance", 0.0) * 0.9
            )
        elif success is False:
            state["grievance"] = _clamp(
                state.get("grievance", 0.0)
                + _number(model.get("order_grievance"), 0.15) * 0.5
            )
        character.campaign_agency = state
        return dict(state)

    def _order_goal_harmony(self, order, goal):
        """Согласован ли приказ с личной целью адресата.

        Данные приказа могут прямо задать ``goal_alignment`` или списки
        ``goal_needs``/``goal_essences``. Иначе выводятся из эффектов:
        снижение целевой потребности поддерживает цель, повышение —
        вызывает обиду; совпадение сути намерения усиливает доверие.
        """
        goal = _as_mapping(goal)
        order = _as_mapping(order)
        if not goal:
            return 0.0
        harmony = 0.0
        effects = _as_mapping(order.get("effects"))
        need_delta = _as_mapping(effects.get("needs"))
        goal_need = _text(goal.get("need"))
        declared_needs = {
            _text(item) for item in (order.get("goal_needs") or ())
        }
        if goal_need and goal_need in declared_needs:
            harmony += 0.5
        if goal_need and goal_need in need_delta:
            delta = _number(need_delta.get(goal_need), 0.0)
            harmony += 0.55 if delta < 0.0 else -0.45
        order_essences = set()
        intentions = _as_mapping(effects.get("intentions"))
        for item in intentions.get("push") or ():
            if isinstance(item, Mapping):
                essence = _text(item.get("essence"))
                if essence:
                    order_essences.add(essence)
        for item in order.get("goal_essences") or ():
            essence = _text(item)
            if essence:
                order_essences.add(essence)
        goal_essence = _text(goal.get("essence"))
        if goal_essence and goal_essence in order_essences:
            harmony += 0.6
        elif order_essences:
            harmony -= 0.2
        alignment = _text(order.get("goal_alignment"))
        if alignment == "support":
            harmony += 0.5
        elif alignment == "conflict":
            harmony -= 0.5
        return max(-1.0, min(1.0, harmony))

    def _remember_order(self, character, order, faction=None):
        """Приказ оставляет след: доверие или обиду у адресата."""
        if character is None or not self._agency_enabled():
            return {}
        state = self._agency_state(character, faction)
        model = self._agency_model()
        goal = _as_mapping(getattr(character, "campaign_goal", {}))
        harmony = self._order_goal_harmony(order, goal)
        trust_delta = _number(model.get("order_trust"), 0.1) * (
            0.5 + 0.5 * harmony
        )
        grievance_delta = _number(
            model.get("order_grievance"), 0.15
        ) * (0.5 - 0.5 * harmony)
        state["trust"] = _clamp(
            _number(state.get("trust"), 0.5) + trust_delta
        )
        state["grievance"] = _clamp(
            _number(state.get("grievance"), 0.0) + grievance_delta
        )
        state["orders"] = max(0, int(state.get("orders", 0))) + 1
        state["last_order"] = _text(order.get("id"))
        memory = list(state.get("memory") or ())
        memory.append(
            {
                "turn": int(self.turn),
                "order_id": _text(order.get("id")),
                "harmony": round(harmony, 6),
                "trust": round(state["trust"], 6),
                "grievance": round(state["grievance"], 6),
            }
        )
        state["memory"] = memory[-8:]
        character.campaign_agency = state
        return {
            "trust": round(state["trust"], 6),
            "grievance": round(state["grievance"], 6),
            "harmony": round(harmony, 6),
            "goal": str(goal.get("label") or ""),
        }

    def _choose_executor(self, side, action):
        """Выбрать исполнителя работы по цели, компетентности и органу.

        Персонаж игрока не назначается автоматически: им управляет
        игрок. Лидер фракции может быть исполнителем, если лучше всех
        подходит по цели. При равенстве выигрывает стабильный порядок
        персонажей, поэтому выбор детерминирован.
        """
        if not self._agency_enabled():
            return None
        faction = self.faction(side)
        if faction is None:
            return None
        model = self._agency_model()
        competence_weight = _number(
            model.get("competence_weight"), 0.2
        )
        organ_bonus = _number(model.get("executor_organ_bonus"), 0.25)
        organ_id = _text(action.get("organ_id"))
        best = None
        best_score = -math.inf
        for character in faction.characters:
            if bool(
                getattr(
                    character,
                    "is_dead",
                    getattr(character, "dead", False),
                )
            ):
                continue
            if bool(getattr(character, "campaign_is_player", False)):
                continue
            support = self._character_support(
                character, action, faction
            )
            competence = self._character_competence(character)
            score = 1.0 + support + competence_weight * (
                competence - 0.5
            )
            if (
                organ_id
                and _same_id(
                    getattr(character, "campaign_organ_id", ""),
                    organ_id,
                )
            ):
                score += organ_bonus
            if score > best_score + 1e-9:
                best = character
                best_score = score
        return best

    def _tick_character_autonomy(self, faction, seconds=None):
        """Пересмотреть личные цели и выбрать BDI-намерение.

        Цель живёт ``goal_hold_turns`` ходов и не меняется каждый такт:
        иначе персонаж дёргается между потребностями. Память приказов
        затухает, инициатива возвращается к норме. Персонаж игрока
        сохраняет цель для отображения, но не выбирает намерение сам.
        """
        if not self._agency_enabled() or faction is None:
            return
        model = self._agency_model()
        decay = _clamp(_number(model.get("memory_decay"), 0.92))
        hold = max(
            1, int(_number(model.get("goal_hold_turns"), 3))
        )
        every = max(
            1, int(_number(model.get("deliberate_every"), 1))
        )
        for character in faction.characters:
            if bool(
                getattr(
                    character,
                    "is_dead",
                    getattr(character, "dead", False),
                )
            ):
                continue
            state = self._agency_state(character, faction)
            state["trust"] = 0.5 + (
                _number(state.get("trust"), 0.5) - 0.5
            ) * decay
            state["grievance"] = _clamp(
                _number(state.get("grievance"), 0.0) * decay
            )
            state["initiative"] = _clamp(
                _number(state.get("initiative"), 0.0) * decay
            )
            character.campaign_agency = state
            goal = _as_mapping(getattr(character, "campaign_goal", {}))
            started = int(_number(goal.get("started"), -10 ** 9))
            if not goal or int(self.turn) - started >= hold:
                goal = self._character_goal(character, faction)
                goal["started"] = int(self.turn)
                goal["revised"] = int(self.turn)
                character.campaign_goal = goal
            if bool(getattr(character, "campaign_is_player", False)):
                continue
            if every and int(self.turn) % every:
                continue
            try:
                character.deliberate(
                    target=_text(goal.get("target")) or None,
                    preferred=_text(goal.get("essence")) or None,
                )
            except Exception:
                logger.exception(
                    "Намерение персонажа %s не выбрано",
                    getattr(character, "name", "?"),
                )

    def _ai_action_weight(self, side, action, leader=None):
        """Вес работы для ИИ: данные, BDI лидера, доктрина и органы.

        Базовый вес — ``ai_priority`` работы. Дальше множители берутся
        из ``automata_defaults.json::ai_model``: потребность, намерение,
        доктрина фракции, убеждения лидера, целостность органа и защита
        цели. Ни один множитель не зашит в код: отсутствующий блок или
        нулевой вес просто не меняет базовый приоритет.
        """
        model = _as_mapping(self.ai_model)
        floor = max(0.01, _number(model.get("score_floor"), 0.01))
        weight = max(floor, _number(action.get("ai_priority"), 1.0))
        faction = self.faction(side)
        if leader is None:
            leader = self._leader(side)
        if faction is None:
            return weight

        essences = self._action_essences(action)
        form = self._action_form(action)
        target = self.faction(self._target_side(side, action))
        target_id = _text(getattr(target, "id", ""))
        faction_id = _text(getattr(faction, "id", ""))
        need = ""
        for essence in essences:
            need = self._action_need(essence, leader)
            if need:
                break

        if leader is not None and need:
            needs = _as_mapping(model.get("needs"))
            current = _clamp(
                _as_mapping(getattr(leader, "needs", {})).get(need)
            )
            weight *= 1.0 + _number(needs.get("weight"), 1.4) * current
            priorities = {
                str(item)
                for item in (
                    faction.record.get("priority_needs") or ()
                )
                if str(item)
            }
            if need in priorities:
                weight *= (
                    1.0
                    + _number(needs.get("priority_weight"), 0.6)
                    * current
                )

        intention = None
        if leader is not None:
            bdi = getattr(leader, "bdi", None)
            if bdi is not None:
                intention = bdi.latest_intention()
        if intention is not None:
            intent = _as_mapping(model.get("intention"))
            if intention.essence in essences:
                weight *= 1.0 + _number(
                    intent.get("essence_weight"), 0.6
                )
            focus = self._action_need(intention.essence, leader)
            if focus and need == focus:
                current = _clamp(
                    _as_mapping(getattr(leader, "needs", {})).get(focus)
                )
                weight *= (
                    1.0
                    + _number(intent.get("focus_weight"), 0.4)
                    * current
                )
            if target_id and _same_id(intention.target, target_id):
                weight *= 1.0 + _number(
                    intent.get("target_weight"), 0.35
                )
            if (
                essences
                and _text(intention.essence)
                and _text(intention.essence) not in essences
            ):
                weight *= max(
                    0.05,
                    1.0
                    - _number(intent.get("mismatch_penalty"), 0.15),
                )

        # Автономия персонажей: не только лидер, но и остальные люди
        # фракции вносят вклад в выбор работы своей целью, намерением,
        # потребностью, доверием и обидой. Веса — данные
        # ``ai_model.character_agency``.
        agency = _as_mapping(model.get("character_agency"))
        if bool(agency.get("enabled", False)):
            limit = max(
                1, int(_number(agency.get("max_characters"), 6))
            )
            support = 0.0
            sabotage = 0.0
            for member in list(faction.characters)[:limit]:
                if member is leader:
                    continue
                value = self._character_support(
                    member, action, faction
                )
                if value >= 0.0:
                    support += value
                else:
                    sabotage += -value
            if support > 0.0:
                weight *= 1.0 + support
            if sabotage > 0.0:
                floor = _clamp(
                    _number(agency.get("sabotage_floor"), 0.35)
                )
                weight *= max(
                    floor,
                    1.0
                    - _number(agency.get("sabotage_weight"), 0.35)
                    * sabotage,
                )

        doctrine = _as_mapping(faction.record.get("doctrine"))
        doctrine_model = _as_mapping(model.get("doctrine"))
        form_weights = _as_mapping(doctrine.get("forms"))
        essence_weights = _as_mapping(doctrine.get("essences"))
        if form and form in form_weights:
            weight *= max(
                0.05,
                1.0
                + _number(doctrine_model.get("form_weight"), 1.0)
                * _number(form_weights.get(form), 0.0),
            )
        doctrine_essence = None
        for essence in essences:
            if essence not in essence_weights:
                continue
            value = _number(essence_weights.get(essence), 0.0)
            if doctrine_essence is None or value > doctrine_essence:
                doctrine_essence = value
        if doctrine_essence is not None:
            weight *= max(
                0.05,
                1.0
                + _number(doctrine_model.get("essence_weight"), 1.0)
                * doctrine_essence,
            )

        beliefs = (
            getattr(getattr(leader, "bdi", None), "beliefs", ())
            if leader is not None
            else ()
        )
        for rule in (
            _as_mapping(model.get("beliefs")).get("rules") or ()
        ):
            if not isinstance(rule, Mapping):
                continue
            predicate = _text(rule.get("predicate"))
            if not predicate:
                continue
            rule_forms = {
                str(item) for item in (rule.get("forms") or ()) if item
            }
            rule_essences = {
                str(item)
                for item in (rule.get("essences") or ())
                if item
            }
            if (rule_forms or rule_essences) and not (
                form in rule_forms or set(essences) & rule_essences
            ):
                continue
            target_mode = _text(rule.get("target") or "any")
            strength = 0.0
            for belief in beliefs:
                if belief.predicate != predicate:
                    continue
                if (
                    target_mode == "action"
                    and not _same_id(belief.object, target_id)
                ):
                    continue
                if (
                    target_mode == "self"
                    and not _same_id(belief.object, faction_id)
                ):
                    continue
                strength = max(
                    strength,
                    _clamp(belief.value) * _clamp(belief.confidence),
                )
            if strength <= 0.0:
                continue
            weight *= max(
                0.05,
                1.0 + _number(rule.get("weight"), 0.0) * strength,
            )

        organs = _as_mapping(model.get("organs"))
        organ_id = _text(action.get("organ_id"))
        organ = faction.organ(organ_id) if organ_id else None
        if organ is not None:
            integrity = _clamp(organ.integrity)
            weight *= max(
                0.05,
                1.0
                - _number(organs.get("integrity_weight"), 0.5)
                * (1.0 - integrity),
            )
            threshold = _number(organs.get("low_threshold"), 0.4)
            repair = {
                str(item)
                for item in (organs.get("repair_essences") or ())
                if item
            }
            if integrity < threshold and set(essences) & repair:
                gap = (threshold - integrity) / max(threshold, 1e-6)
                weight *= 1.0 + _number(
                    organs.get("repair_weight"), 0.5
                ) * gap

        if target is not None:
            chance_spec = _as_mapping(action.get("chance"))
            defense = target.asset(
                str(
                    chance_spec.get("defense")
                    or action.get("defense_asset")
                    or "cohesion"
                )
            )
            defense_model = _as_mapping(model.get("defense"))
            reference = _number(defense_model.get("reference"), 0.5)
            weight *= 1.0 + _number(
                defense_model.get("weight"), 1.0
            ) * max(0.0, reference - defense)
            if self.relations is not None and target.id != faction.id:
                relation_model = _as_mapping(model.get("relations"))
                shift = self.relations.effect(
                    target.id, faction.id, form
                )
                weight *= max(
                    0.05,
                    1.0
                    + _number(
                        relation_model.get("weight"), 1.0
                    )
                    * shift,
                )
        return weight

    def _ai_weighted_options(
        self, side, turn=None, exclude_active=False
    ):
        options = [
            item
            for item in self.action_options(side, turn=turn)
            if item["enabled"]
        ]
        if exclude_active:
            running = {
                str(record.get("action_id"))
                for record in self._active_processes(side)
            }
            options = [
                item for item in options if item["id"] not in running
            ]
        leader = self._leader(side)
        return [
            (
                option,
                self._ai_action_weight(
                    side, option["action"], leader=leader
                ),
            )
            for option in options
        ]

    def ai_action_weights(
        self, side, turn=None, exclude_active=False
    ):
        """Веса ИИ по доступным работам стороны (диагностика/тесты)."""
        return {
            str(option["id"]): round(weight, 6)
            for option, weight in self._ai_weighted_options(
                side, turn=turn, exclude_active=exclude_active
            )
        }

    def auto_action(self, side, turn=None, exclude_active=False):
        weighted = self._ai_weighted_options(
            side, turn=turn, exclude_active=exclude_active
        )
        if not weighted:
            if self.stats.enabled and self.stats.actions:
                self.stats.log(
                    "ai_choice",
                    side=str(side),
                    chosen=None,
                    reason="нет доступных работ",
                    slots=self.slot_state(side),
                )
            return None
        total = sum(weight for _option, weight in weighted)
        chosen = None
        if total <= 0.0:
            chosen = weighted[-1][0]["id"]
        else:
            pick = self.rng.random() * total
            upto = 0.0
            for option, weight in weighted:
                upto += weight
                if pick <= upto:
                    chosen = option["id"]
                    break
            if chosen is None:
                chosen = weighted[-1][0]["id"]
        if self.stats.enabled and self.stats.actions:
            self.stats.log(
                "ai_choice",
                side=str(side),
                chosen=str(chosen),
                total=round(total, 6),
                weights={
                    str(option["id"]): round(weight, 6)
                    for option, weight in weighted
                },
                slots=self.slot_state(side),
            )
        return chosen

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
                    self.player_side,
                    organ_id,
                    interaction_id,
                    defer=False,
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
                    self.player_side,
                    character_id,
                    interaction_id,
                    defer=False,
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
        self.history.append(self._history_record())
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

    def _tick_faction_orders(self, faction):
        """Отдать приказ от фракции персонажу на организационном такте.

        Приказы — данные ``order_model.orders``. Игровая сторона не
        получает автоматических приказов: её направляет игрок
        (``issue_order``).
        """
        model = _as_mapping(self.order_model)
        if not model or not bool(model.get("enabled", True)):
            return None
        if faction.side == self.player_side or not faction.orders:
            return None
        interval = max(1, int(_number(model.get("interval"), 1)))
        if faction.last_order_turn and (
            int(self.turn) - int(faction.last_order_turn) < interval
        ):
            return None
        limit = max(1, int(_number(model.get("max_per_tick"), 1)))
        result = None
        for _ in range(limit):
            selected = self._choose_order(faction)
            if selected is None:
                break
            issued = self.issue_order(faction.side, selected["id"])
            if not issued.get("ok"):
                break
            result = issued
        return result

    def _choose_order(self, faction):
        """Выбрать доступный приказ по весам ``priority`` из данных."""
        options = [
            item
            for item in self.order_options(faction.side)
            if item["enabled"]
        ]
        if not options:
            return None
        weights = [
            max(1e-6, _number(item["order"].get("priority"), 1.0))
            for item in options
        ]
        pick = self.rng.random() * sum(weights)
        upto = 0.0
        for item, weight in zip(options, weights):
            upto += weight
            if pick <= upto:
                return item["order"]
        return options[-1]["order"]

    def _order_cooldown_left(self, faction, order):
        cooldown = max(
            0,
            int(
                _number(
                    order.get("cooldown"),
                    self.order_model.get("cooldown", 1),
                )
            ),
        )
        if cooldown <= 0:
            return 0
        last = faction.order_cooldowns.get(str(order.get("id")))
        if last is None:
            return 0
        return max(0, cooldown + 1 - (int(self.turn) - int(last)))

    def _order_affordable(self, faction, order):
        cost = _as_mapping(order.get("cost"))
        return all(
            faction.asset(key) + 1e-9 >= _number(value)
            for key, value in cost.items()
        )

    def _order_requirement_reason(self, faction, order):
        requires = _as_mapping(order.get("requires"))
        reason = self._asset_requirement_reason(
            "нужно", faction.assets, requires.get("self")
        )
        if reason:
            return reason
        when = requires.get("when")
        if when is None:
            when = order.get("when")
        return check_conditions(when, self._condition_context(faction))

    def _order_targets(self, faction, order, character_id=None):
        alive = [
            character
            for character in faction.characters
            if not bool(
                getattr(
                    character,
                    "is_dead",
                    getattr(character, "dead", False),
                )
            )
        ]
        if not alive:
            return []
        if character_id:
            wanted = str(character_id)
            return [
                character
                for character in alive
                if str(getattr(character, "campaign_id", "")) == wanted
            ]
        recipient = _text(
            order.get("recipient") or self.order_model.get("recipient"),
            "priority",
        )
        if recipient in ("all", "everyone", "broadcast"):
            return alive
        if recipient == "leader":
            return alive[:1]
        if recipient == "lowest_morale":
            return [
                min(
                    alive,
                    key=lambda item: _number(
                        getattr(item, "morale", 0.0)
                    ),
                )
            ]
        if recipient == "highest_morale":
            return [
                max(
                    alive,
                    key=lambda item: _number(
                        getattr(item, "morale", 0.0)
                    ),
                )
            ]

        def need_score(character):
            values = [
                _clamp(value)
                for value in _as_mapping(
                    getattr(character, "needs", {})
                ).values()
            ]
            return sum(values) / float(len(values)) if values else 1.0

        return [min(alive, key=need_score)]

    def order_options(self, side):
        """Приказы стороны с причиной недоступности (UI и тесты)."""
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        options = []
        for order in faction.orders:
            cost = _as_mapping(order.get("cost"))
            left = self._order_cooldown_left(faction, order)
            requirement = self._order_requirement_reason(faction, order)
            affordable = self._order_affordable(faction, order)
            if requirement:
                reason = requirement
            elif left > 0:
                reason = "перезарядка ещё %d" % left
            elif not affordable:
                reason = "не хватает состояния"
            else:
                reason = ""
            options.append(
                {
                    "order": order,
                    "id": str(order.get("id")),
                    "label": str(order.get("label") or order.get("id")),
                    "description": str(order.get("description") or ""),
                    "priority": round(
                        _number(order.get("priority"), 1.0), 6
                    ),
                    "recipient": _text(
                        order.get("recipient")
                        or self.order_model.get("recipient"),
                        "priority",
                    ),
                    "cooldown": left,
                    "cost": {
                        str(key): round(_number(value), 6)
                        for key, value in cost.items()
                    },
                    "enabled": not reason,
                    "reason": reason,
                }
            )
        return options

    def _apply_order_relations(self, faction, character, order):
        """Записать отношение приказа «фракция → персонаж»."""
        raw = _as_mapping(order.get("relations"))
        if not raw or self.relations is None:
            return []
        axes = _as_mapping(raw.get("axes")) if "axes" in raw else raw
        if not axes:
            return []
        mode = _text(raw.get("source") or raw.get("from"), "faction")
        faction_id = str(getattr(faction, "id", "") or "")
        character_id = str(
            getattr(character, "campaign_id", "") or ""
        )
        if not faction_id or not character_id:
            return []
        if mode in ("character", "target", "self_character"):
            source, target = character_id, faction_id
        else:
            source, target = faction_id, character_id
        changes = self.relations.add(source, target, axes, 1.0)
        return [
            {
                "source": source,
                "target": target,
                "axis": str(axis),
                "delta": delta,
            }
            for axis, delta in changes.items()
        ]

    def issue_order(self, side, order_id, character_id=None):
        """Отдать приказ фракции конкретному персонажу.

        Игрок и ИИ используют один путь: проверка требований → эффекты
        через ``apply_effects`` → отношения → расход цены → перезарядка.
        """
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        order = next(
            (
                item
                for item in faction.orders
                if str(item.get("id")) == str(order_id)
            ),
            None,
        )
        if order is None:
            return {"ok": False, "reason": "приказ не найден"}
        option = next(
            (
                item
                for item in self.order_options(side)
                if item["id"] == str(order_id)
            ),
            None,
        )
        if option is None or not option["enabled"]:
            return {
                "ok": False,
                "reason": (
                    option.get("reason")
                    if option is not None
                    else "приказ недоступен"
                ),
            }
        targets = self._order_targets(faction, order, character_id)
        if not targets:
            return {"ok": False, "reason": "нет персонажа для приказа"}
        cost = _as_mapping(order.get("cost"))
        broadcast = (
            not character_id
            and option["recipient"] in ("all", "everyone", "broadcast")
            and len(targets) > 1
        )
        applied = []
        relations = []
        agency_memory = []
        for character in targets:
            payload = _order_payload(
                order.get("effects"),
                "" if broadcast else getattr(character, "campaign_id", ""),
            )
            applied.append(
                apply_effects(
                    faction,
                    payload,
                    target=faction,
                    scale=1.0,
                    source="order",
                )
            )
            relations.extend(
                self._apply_order_relations(faction, character, order)
            )
            memory = self._remember_order(character, order, faction)
            agency_memory.append(
                {
                    "id": str(
                        getattr(character, "campaign_id", "") or ""
                    ),
                    "name": str(
                        getattr(character, "name", "") or ""
                    ),
                    **memory,
                }
            )
        for key, value in cost.items():
            faction.add_asset(key, -_number(value))
        cooldown = max(
            0,
            int(
                _number(
                    order.get("cooldown"),
                    self.order_model.get("cooldown", 1),
                )
            ),
        )
        if cooldown > 0:
            faction.order_cooldowns[str(order.get("id"))] = int(self.turn)
        faction.last_order_turn = int(self.turn)
        record = {
            "turn": int(self.turn),
            "side": faction.side,
            "order_id": str(order.get("id")),
            "label": option["label"],
            "description": option["description"],
            "recipient": option["recipient"],
            "characters": [
                {
                    "id": str(
                        getattr(character, "campaign_id", "") or ""
                    ),
                    "name": str(getattr(character, "name", "") or ""),
                }
                for character in targets
            ],
            "cost": dict(option["cost"]),
            "relations": relations,
            "agency": agency_memory,
            "applied": applied,
        }
        faction.last_order = {
            key: value
            for key, value in record.items()
            if key != "applied"
        }
        detail = "ход %d: %s отдаёт приказ «%s» → %s" % (
            self.turn,
            faction.name,
            record["label"],
            ", ".join(
                item["name"] or item["id"]
                for item in record["characters"]
            )
            or "никому",
        )
        self.events.append(
            {
                "turn": self.turn,
                "kind": "order",
                "text": detail,
                "side": faction.side,
                "order_id": record["order_id"],
                "actor": faction.name,
            }
        )
        if len(self.events) > EVENT_LOG_LIMIT:
            self.events = self.events[-EVENT_LOG_LIMIT:]
        self.last_order_result = record
        result = {"ok": True}
        result.update(record)
        return result

    def _tick_faction_characters(self, faction, seconds):
        """Дать BDI персонажей прожить организационный интервал.

        Активы фракции производны от потребностей, морали и силы людей,
        поэтому без этого шага «политические» шкалы выглядели бы
        застывшими между редкими взаимодействиями.
        """
        stored = _as_mapping(faction.organization_snapshot)
        support = _clamp(stored.get("willing_share", 0.5))
        # Организационный такт теперь равен дню игрового времени.
        # BDI нельзя прогонять на полные сутки: без еды и сна
        # потребности уходят в крайности, сила падает до нуля и
        # организация распадается за пару дней. Поэтому за такт
        # моделируется короткий «срез» жизни (``bdi_horizon``),
        # а суточную рутину закрывают эффекты организации. Дробим
        # срез на шаги, чтобы срабатывали пороги и спилловер.
        horizon = max(
            0.0,
            _number(
                self.realtime.get("bdi_horizon_seconds"), 1800.0
            ),
        )
        step = max(
            30.0,
            _number(self.realtime.get("bdi_tick_seconds"), 900.0),
        )
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
            before = (
                self.stats.character_state(character)
                if self.stats.enabled
                else None
            )
            simulated = 0.0
            try:
                left = min(max(0.0, float(seconds)), horizon)
                while left > 1e-9:
                    chunk = min(step, left)
                    character.tick_needs(
                        seconds=chunk,
                        supported=support,
                        in_combat=False,
                        under_fire=0.0,
                        rng=getattr(character, "rng", None),
                    )
                    left -= chunk
                    simulated += chunk
            except Exception:
                logger.exception(
                    "BDI персонажа %s не обновлён",
                    getattr(character, "name", "?"),
                )
                continue
            if before is None:
                continue
            after = self.stats.character_state(character)
            self.stats.log(
                "bdi",
                side=faction.side,
                character_id=before.get("id"),
                name=before.get("name"),
                post=before.get("post"),
                support=round(support, 6),
                interval_seconds=round(float(seconds), 3),
                horizon_seconds=round(horizon, 3),
                simulated_seconds=round(simulated, 3),
                before=before,
                after=after,
                delta=self.stats.character_delta(before, after),
            )

    def _tick_organizations(self):
        seconds = max(30.0, float(self.organization_interval_seconds))
        self._tick_machines()
        for faction in self.factions.values():
            before = (
                self.stats.faction_state(faction)
                if self.stats.enabled
                else None
            )
            self._tick_faction_characters(faction, seconds)
            self._tick_character_autonomy(faction, seconds)
            self._tick_faction_orders(faction)
            if faction.organization is None:
                faction.relax_context(self.model["asset_relax"])
                for key, value in faction.income.items():
                    faction.bump_context(key, value)
                for key, value in self.upkeep.items():
                    faction.bump_context(key, -value)
                tick_organs(faction, faction.organs, self.model)
                self._log_tick_stats(faction, seconds, before)
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
            self._log_tick_stats(faction, seconds, before)

    def _log_tick_stats(self, faction, seconds, before):
        """Записать дневной срез: активы, их формулы и BDI-сводку."""
        if before is None or not self.stats.enabled:
            return
        after = self.stats.faction_state(faction)
        self.stats.log(
            "tick",
            side=faction.side,
            faction=faction.name,
            seconds=round(float(seconds), 3),
            assets_before=before.get("assets"),
            assets_after=after.get("assets"),
            asset_deltas=delta_map(
                before.get("assets"), after.get("assets")
            ),
            context_before=before.get("context"),
            context_after=after.get("context"),
            context_deltas=delta_map(
                before.get("context"), after.get("context")
            ),
            organization=after.get("organization"),
            characters=after.get("characters"),
            breakdowns=self.stats.breakdowns(faction),
            low_streaks={
                str(key): int(value)
                for key, value in faction.low_streaks.items()
            },
            dissolved=bool(faction.dissolved),
        )

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
        checks = []
        notable = False
        for side, thresholds in _as_mapping(rules.get("defeat")).items():
            faction = self.faction(side)
            if faction is None:
                continue
            for asset, threshold in _as_mapping(thresholds).items():
                key = "%s:%s" % (side, asset)
                value = faction.asset(asset)
                limit = _number(threshold, 0.0)
                if value <= limit + 1e-9:
                    faction.low_streaks[key] = (
                        faction.low_streaks.get(key, 0) + 1
                    )
                else:
                    faction.low_streaks[key] = 0
                streak = faction.low_streaks.get(key, 0)
                if streak:
                    notable = True
                checks.append(
                    {
                        "side": str(side),
                        "asset": str(asset),
                        "value": round(value, 6),
                        "threshold": round(limit, 6),
                        "streak": int(streak),
                        "streak_limit": int(streak_limit),
                    }
                )
                if streak >= streak_limit:
                    decision = (
                        "lose" if side == self.player_side else "win"
                    )
                    if self.stats.enabled and self.stats.outcome:
                        self.stats.log(
                            "outcome",
                            decision=decision,
                            rule="defeat",
                            checks=checks,
                            streak_limit=streak_limit,
                        )
                    self.outcome = decision
                    self.finished = True
                    return
        score_info = None
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
                player_score = measure(player)
                rival_score = measure(rival)
                difference = (
                    player_score
                    - rival_score
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
                if side is not None:
                    notable = True
                score_info = {
                    "basis": basis,
                    "player": round(player_score, 6),
                    "rival": round(rival_score, 6),
                    "difference": round(difference, 6),
                    "margin": round(margin, 6),
                    "side": side,
                    "streak": int(self.score_streak),
                    "required": int(required),
                    "after_turn": int(after),
                }
                if (
                    self.turn >= after
                    and side is not None
                    and self.score_streak >= required
                ):
                    if self.stats.enabled and self.stats.outcome:
                        self.stats.log(
                            "outcome",
                            decision=side,
                            rule="score",
                            checks=checks,
                            score=score_info,
                        )
                    self.outcome = side
                    self.finished = True
                    return
        if notable and self.stats.enabled and self.stats.outcome:
            self.stats.log(
                "outcome",
                decision=None,
                rule="score" if score_info else "defeat",
                checks=checks,
                score=score_info,
                streak_limit=streak_limit,
            )

    def snapshot(self):
        return {
            "preset_id": self.preset_id,
            "title": self.title,
            "capability_schema": int(
                getattr(
                    self, "capability_schema", CAPABILITY_SCHEMA_VERSION
                )
            ),
            "work_trace_version": int(
                getattr(self, "work_trace_version", WORK_TRACE_VERSION)
            ),
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
            "action_process": dict(self.action_process),
            "action_slots": int(self.action_slots),
            "process_seq": int(self._process_seq),
            "processes": [
                dict(record) for record in self.processes
            ],
            "score_streak": self.score_streak,
            "score_streak_side": self.score_streak_side,
            "player_side": self.player_side,
            "avatar_schema": AVATAR_SCHEMA_VERSION,
            "avatar": (
                self.avatar.as_dict() if self.avatar is not None else None
            ),
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
            "obligations": self.obligations.to_list(),
            "relations": self.relations.snapshot(),
        }

    to_dict = snapshot

    def save_snapshot(self):
        """Полный снимок: журнал, организации и состояние ГСЧ."""
        data = stamp_snapshot(self.snapshot(), SCHEMA_VERSION)
        data["capability_schema"] = int(
            getattr(
                self, "capability_schema", CAPABILITY_SCHEMA_VERSION
            )
        )
        data["work_trace_version"] = int(
            getattr(self, "work_trace_version", WORK_TRACE_VERSION)
        )
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
                        "scales": {
                            str(key): float(value)
                            for key, value in organ.scales.items()
                        },
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
                        "rng_state": (
                            _nested_tuple(character.rng.getstate())
                            if getattr(character, "rng", None) is not None
                            else None
                        ),
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
                        "goal": dict(
                            _as_mapping(
                                getattr(character, "campaign_goal", {})
                            )
                        ),
                        "agency": dict(
                            _as_mapping(
                                getattr(character, "campaign_agency", {})
                            )
                        ),
                        "mind": str(getattr(character, "mind", "steady")),
                        "last_mind": str(
                            getattr(character, "_last_mind", "steady")
                        ),
                        "panicked": bool(
                            getattr(character, "panicked", False)
                        ),
                        "fanatical": bool(
                            getattr(character, "fanatical", False)
                        ),
                        "panic_timer": int(
                            getattr(character, "panic_timer", 0)
                        ),
                        "fanatic_timer": int(
                            getattr(character, "fanatic_timer", 0)
                        ),
                        "panic_cooldown": int(
                            getattr(character, "panic_cooldown", 0)
                        ),
                        "fanatic_cooldown": int(
                            getattr(character, "fanatic_cooldown", 0)
                        ),
                        "under_fire": float(
                            getattr(character, "under_fire", 0.0)
                        ),
                        "casualties": int(
                            getattr(character, "casualties", 0)
                        ),
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
        snapshot = migrate_snapshot(snapshot)
        self.capability_schema = max(
            1,
            int(
                _number(
                    snapshot.get("capability_schema"),
                    1,
                )
            ),
        )
        self.work_trace_version = max(
            0,
            int(
                _number(
                    snapshot.get("work_trace_version"),
                    0,
                )
            ),
        )
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
        saved_process = _as_mapping(snapshot.get("action_process"))
        if saved_process:
            self.action_process.update(
                {str(key): value for key, value in saved_process.items()}
            )
        self.action_slots = max(
            1,
            int(
                _number(
                    snapshot.get("action_slots"),
                    _number(self.action_process.get("slots"), 2),
                )
            ),
        )
        self.processes = [
            dict(record)
            for record in (snapshot.get("processes") or ())
            if isinstance(record, Mapping) and record.get("id")
        ]
        self._process_seq = max(
            int(
                _number(
                    snapshot.get("process_seq"),
                    self._process_seq,
                )
            ),
            len(self.processes),
        )
        for record in self.processes:
            if "remaining" not in record:
                record["remaining"] = _number(
                    record.get("duration"), 0.0
                )
            if "finish_at" not in record:
                record["finish_at"] = float(self.elapsed) + _number(
                    record.get("remaining"), 0.0
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
        try:
            restored = avatar_from_snapshot(snapshot, fallback_data=self.data)
        except AvatarError as exc:
            logger.warning("Аватар из снимка не восстановлен: %s", exc)
        else:
            if "avatar" in snapshot:
                self.avatar = restored
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
            faction.order_cooldowns = {
                str(key): int(_number(value))
                for key, value in _as_mapping(
                    state.get("order_cooldowns")
                ).items()
            }
            faction.last_order_turn = max(
                0, int(_number(state.get("last_order_turn"), 0))
            )
            faction.last_order = dict(
                _as_mapping(state.get("last_order"))
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
                for key, value in _as_mapping(
                    saved.get("scales")
                ).items():
                    organ.scales[str(key)] = _clamp(
                        _number(value, organ.scales.get(str(key), 0.0))
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
                rng_state = saved.get("rng_state")
                if rng_state and getattr(character, "rng", None) is not None:
                    try:
                        character.rng.setstate(_nested_tuple(rng_state))
                    except (TypeError, ValueError):
                        pass
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
                if isinstance(saved.get("goal"), Mapping):
                    character.campaign_goal = dict(saved["goal"])
                if isinstance(saved.get("agency"), Mapping):
                    character.campaign_agency = dict(saved["agency"])
                if "mind" in saved:
                    character.mind = str(
                        saved.get("mind") or "steady"
                    )
                if "last_mind" in saved:
                    character._last_mind = str(
                        saved.get("last_mind") or "steady"
                    )
                if "panicked" in saved:
                    character.panicked = bool(saved.get("panicked"))
                if "fanatical" in saved:
                    character.fanatical = bool(saved.get("fanatical"))
                if "panic_timer" in saved:
                    character.panic_timer = max(
                        0, int(_number(saved.get("panic_timer"), 0))
                    )
                if "fanatic_timer" in saved:
                    character.fanatic_timer = max(
                        0, int(_number(saved.get("fanatic_timer"), 0))
                    )
                if "panic_cooldown" in saved:
                    character.panic_cooldown = max(
                        0, int(_number(saved.get("panic_cooldown"), 0))
                    )
                if "fanatic_cooldown" in saved:
                    character.fanatic_cooldown = max(
                        0, int(_number(saved.get("fanatic_cooldown"), 0))
                    )
                if "under_fire" in saved:
                    character.under_fire = max(
                        0.0, _number(saved.get("under_fire"), 0.0)
                    )
                if "casualties" in saved:
                    character.casualties = max(
                        0, int(_number(saved.get("casualties"), 0))
                    )
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
        # Старый сейв без ``obligations`` очищает стартовые обязательства:
        # снимок — источник истины, а не пресет.
        self.obligations = ObligationLedger()
        self.obligations.load(snapshot.get("obligations") or ())
        self.relations = RelationStore.from_config(
            _relation_model(self.data)
        ).load(snapshot.get("relations") or {})
        for faction in self.factions.values():
            faction.relations = self.relations
            self._init_character_agency(faction)
        if self.outcome:
            self.finished = True
        self._sync_avatar_state()

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
    "CAPABILITY_SCHEMA_VERSION",
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
