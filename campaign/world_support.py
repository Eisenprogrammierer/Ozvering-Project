"""Общие примитивы мира: константы, загрузка и проверка конфигов.

Модуль выделен из ``campaign.world``, чтобы миксины движка не
образовывали циклический импорт с фасадом. Публичные имена
реэкспортируются из ``campaign.world``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections.abc import Mapping
from pathlib import Path
from core41 import Automaton, HEALTH_MAX, SICKNESS_MAX
from core41.model import WOUND_MAX
from .actor import (
    CAMPAIGN_ENERGY_MAX,
    CampaignActor,
    campaign_success_chance,
)
from .actions import (
    ActionError,
    FormCatalog,
    lint_action,
    merge_action_catalogs,
    normalize_action,
    parse_entity_ref,
)
from .character import CampaignCharacter
from .handlers import HandlerRegistry
from .work import build_work
from .item_automaton import (
    apply_item_handler,
    item_automaton_snapshot,
    item_automaton_view,
    item_handler_reason,
    normalize_item_automaton,
    restore_item_automaton,
)
from . import logbook as _logbook
from .lod import CampaignLod
from .qualitative import cost_phrase, effect_phrase, metric_word
from .scenes import SceneCatalog, SceneError, SceneSpec
from .coalitions import (
    CoalitionBook,
    coalition_config,
    pair_score,
)
from . import values as _values
from .economy import (
    CREDIT_DAYS,
    MAINTENANCE_STARVE_FORCE,
    MAINTENANCE_STARVE_HEALTH,
    NATURE_BASE_WORK,
    NATURE_SEASON_LENGTH,
    balance,
    conversion_quote,
    credit_quote,
    help_quote,
    maintenance_cost,
    nature_yield,
    poverty_status,
    repair_quote,
    resource_projection,
    rest_quote,
    scaled_cost,
    scaled_effect,
    season_multiplier,
    season_name,
)
from .errors import CampaignError
from .planner import (
    AUTONOMY_PERIOD,
    IntentQueue,
    SLOT_DAY_EDGE,
    SLOTS_MAX,
    _as_slot,
    condition_holds,
)
from .node_strategy import StrategyBook
from .control import DirectiveBook
from .obligations import (
    DEFAULT_OBLIGATION_KIND,
    OBLIGATION_BREACH_AFFINITY,
    OBLIGATION_BREACH_TRUST,
    OBLIGATION_FULFILL_AFFINITY,
    OBLIGATION_FULFILL_TRUST,
    ObligationLedger,
)
from .relations import (
    DEFAULT_RELATION_FORM,
    RELATION_AXES,
    RELATION_AXIS_LABELS,
    asymmetry_rows,
    normalize_relation_axes_config,
    relation_axis_labels_from_config,
    relation_axis_short_labels_from_config,
    relation_axes_from_config,
    relation_effect,
    relation_effect_limit_from_config,
    relation_effect_weights_from_config,
)
from .success import resolve_success_coefficients, success_margin
from .projections import (
    SCHEMA_VERSION,
    migrate_snapshot,
    player_projection_view,
)


logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
WORLD_WORK_DEFAULTS = {
    "default_form": "world",
    "default_amount": 0.01,
}
AUTONOMY_BASE_CHANCE = 0.6
AUTONOMY_AFFINITY_THRESHOLD = -0.2
AUTONOMY_TRUST_THRESHOLD = 0.35
DEFAULT_OVERDUE_OBLIGATION = {
    "enabled": True,
    "relation": {
        "trust": OBLIGATION_BREACH_TRUST,
        "affinity": OBLIGATION_BREACH_AFFINITY,
    },
    "negotiation_penalty": 0.18,
    "max_stack": 3,
}
_AUTONOMY_POLICIES = {
    "reconcile": {
        "effects": {"affinity": 0.02},
        "text": "предложил(а) примирение.",
        "failure_text": "попытка примирения отскочила.",
    },
    "rapprochement": {
        "effects": {"affinity": 0.02, "trust": 0.01},
        "text": "укрепил(а) контакт.",
        "failure_text": "контакт не сложился.",
    },
    "probe": {
        "effects": {"affinity": 0.01},
        "text": "нашёл(ла) повод для разговора.",
        "failure_text": "разговор не задался.",
    },
}
CAMPAIGN_HEALTH_REGEN = 1.0
CAMPAIGN_SICKNESS_PROGRESS = 0.01
CAMPAIGN_SICKNESS_HEALTH_DECAY = 6.0
CAMPAIGN_WOUND_MAX = WOUND_MAX
CAMPAIGN_WOUND_HEALTH_DECAY = 4.0
CAMPAIGN_WOUND_REGEN_PENALTY = 0.5
CAMPAIGN_WOUND_TREAT_AMOUNT = 0.25
CAMPAIGN_ENV_WOUND_CHANCE = 0.05
CAMPAIGN_ENV_WOUND_DAMAGE = 8.0
CAMPAIGN_ENV_WOUND_SEVERITY = 0.30
CAMPAIGN_ACTION_WOUND_CHANCE = 0.15
CAMPAIGN_ACTION_WOUND_SEVERITY = 0.20
CAMPAIGN_ACTION_WOUND_DAMAGE = 6.0
CAMPAIGN_WOUND_DODGE_SKILL = "command"
WOUND_RISKY_ACTIONS = (
    "duel",
    "sabotage",
    "enforce_order",
    "martial_law",
    "embargo",
    "strike",
)


def _is_wound_risky(action):
    """Рискует ли действие устойчивой раной (`wound_risk` или список)."""
    if "wound_risk" in action:
        return bool(action.get("wound_risk"))
    return _text(action.get("id")) in WOUND_RISKY_ACTIONS


CAMPAIGN_CONTAGION_CHANCE = 0.30
CAMPAIGN_CONTAGION_SEVERITY = 0.35
CAMPAIGN_INFLUENCE_INCOME = 0.04
CAMPAIGN_INFLUENCE_PER_AUTHORITY = 0.21
CAMPAIGN_FAVOR_INCOME = 0.03
CAMPAIGN_FAVOR_PER_STANDING = 0.20
CAMPAIGN_SKILL_GAIN = 0.03
CAMPAIGN_SKILL_FAILURE_GAIN = 0.01
CAMPAIGN_SKILL_CAP = 0.90
COLLAPSE_POWER = 0.05
COLLAPSE_COHESION = 0.05
COLLAPSE_GRACE_DAYS = 2
COLLAPSE_LEGITIMACY = 0.02
DISMISSAL_STANDING = 0.05
DISMISSAL_LEGITIMACY = 0.08
ROLE_CHANGE_COOLDOWN_DAYS = 5
LABOR_MARKET_RIVALS = 2
LABOR_MARKET_RIVAL_BASE = 0.22
LABOR_MARKET_RIVAL_SPREAD = 0.20
LABOR_MARKET_RANK_BONUS = 0.05
LABOR_MARKET_SKILL_WEIGHT = 0.40
LABOR_MARKET_STANDING_WEIGHT = 0.60
LABOR_MARKET_REFRESH_DAYS = 1
LABOR_MARKET_STRUCTURE_QUOTA = 2
LABOR_MARKET_CONNECTION_WEIGHT = 0.10
LEGITIMACY_RECOVERY = 0.02
DECAY_STRAIN_COHESION = 0.010
DECAY_STRAIN_POWER = 0.005
DECAY_CRISIS_COHESION = 0.020
DECAY_CRISIS_POWER = 0.010
DECAY_BROKE_WEALTH = 0.10
DECAY_BROKE_COHESION = 0.010
DECAY_RECOVERY_LEGITIMACY = 0.45
DECAY_RECOVERY_COHESION = 0.005
DECAY_RECOVERY_POWER = 0.005
ENDING_KINDS = ("win", "lose", "neutral")
NODE_STATS = (
    "power",
    "wealth",
    "legitimacy",
    "cohesion",
    "reach",
    "capacity",
)
PLAYER_STATS = ("influence", "favor", "evidence", "standing")
KIND_LABELS = {
    "institution": "учреждение",
    "asset": "имущество",
    "person": "человек",
    "character": "человек",
    "organization": "организация",
    "organ": "орган",
    "item": "предмет",
    "place": "место",
    "norm": "норма",
    "obligation": "обязательство",
    "network": "сеть",
    "event": "событие",
}
CHARACTER_CIRCLES = {
    "close": "ближний круг",
    "companion": "попутчики",
    "acquaintance": "знакомства",
}
ORGANIZATION_CATEGORIES = {
    "allied": "союзные",
    "hostile": "враждебные",
    "neutral": "нейтральные",
}
CHARACTER_STAT_LABELS = dict(RELATION_AXIS_LABELS)
RELATION_BACK_SHARE = 0.5
LABOR_NEGOTIATION_INFLUENCE = 0.03
LABOR_NEGOTIATION_FAVOR = 0.05
LABOR_NEGOTIATION_SUCCESS_AFFINITY = 0.04
LABOR_NEGOTIATION_FAILURE_AFFINITY = -0.04
LABOR_NEGOTIATION_BASE_LOGIT = -0.20
LABOR_NEGOTIATION_MARGIN_WEIGHT = 4.0
LABOR_NEGOTIATION_RELATION_WEIGHT = 1.2
LABOR_NEGOTIATION_RETRY_BONUS = 0.12
LABOR_NEGOTIATION_RETRY_BONUS_MAX = 0.36
SKILL_ORDER = (
    "administration",
    "diplomacy",
    "command",
    "faith",
    "trade",
    "scholarship",
    "care",
    "intrigue",
    "media",
)
DOMAIN_SKILLS = {
    "order": ("administration", "command"),
    "meaning": ("faith", "diplomacy"),
    "provision": ("trade", "administration"),
    "status": ("diplomacy", "intrigue"),
    "knowledge": ("scholarship", "media"),
    "care": ("care", "diplomacy"),
    "exchange": ("trade", "intrigue"),
}


class WorldError(CampaignError):
    pass


def _clamp(value, low=0.0, high=1.0):
    return max(float(low), min(float(high), float(value)))


def _normalize_labor_market(raw):
    """Data-Driven настройки рынка труда с обратной совместимостью.

    Все ключи необязательны. Неизвестные поля сохраняются в словаре,
    поэтому будущий контент может добавить новую механику, не ломая
    текущий `WorldEngine`.
    """
    raw = dict(raw or {})
    weights = dict(raw.get("weights") or {})
    result = dict(raw)
    result["rivals"] = max(
        0, _as_int(raw.get("rivals"), LABOR_MARKET_RIVALS)
    )
    result["refresh_days"] = max(
        1, _as_int(raw.get("refresh_days"), LABOR_MARKET_REFRESH_DAYS)
    )
    result["structure_quota"] = max(
        0,
        _as_int(
            raw.get("structure_quota"),
            LABOR_MARKET_STRUCTURE_QUOTA,
        ),
    )
    result["rival_base"] = _as_float(
        raw.get("rival_base"), LABOR_MARKET_RIVAL_BASE
    )
    result["rival_spread"] = _as_float(
        raw.get("rival_spread"), LABOR_MARKET_RIVAL_SPREAD
    )
    result["rank_bonus"] = _as_float(
        raw.get("rank_bonus"), LABOR_MARKET_RANK_BONUS
    )
    result["skill_weight"] = _as_float(
        weights.get("skill"), LABOR_MARKET_SKILL_WEIGHT
    )
    result["standing_weight"] = _as_float(
        weights.get("standing"), LABOR_MARKET_STANDING_WEIGHT
    )
    result["connection_weight"] = _as_float(
        weights.get("connection"), LABOR_MARKET_CONNECTION_WEIGHT
    )
    result["weights"] = weights
    result["quota"] = {
        str(key): max(0, _as_int(value))
        for key, value in (raw.get("quota") or {}).items()
    }
    return result


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


class _PlayerResources(dict):
    """Личные ресурсы позиции; `standing` — проекция `F` персонажа.

    Словарь остаётся обычным `dict` для UI/сейвов и сравнений, но запись
    `standing` синхронно меняет `CampaignActor.force`. Так `F` перестаёт
    быть отдельной копией и не расходится с репутацией.
    """

    def __init__(self, actor, initial=None):
        self.actor = actor
        super().__init__()
        for key, value in (initial or {}).items():
            self[key] = value
        self.actor.force = float(self.get("standing", 0.0))

    def __setitem__(self, key, value):
        if key == "standing":
            value = _clamp(value)
            self.actor.force = value
        super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value


def _text(value, default=""):
    if value is None:
        return default
    return str(value)


def _read_json(path):
    target = Path(path)
    if not target.is_absolute():
        target = ROOT / target
    try:
        with open(target, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise WorldError("файл мира не найден: %s" % target)
    except Exception as exc:
        raise WorldError("не удалось прочитать %s: %s" % (target, exc))


def _resolve_config_path(value):
    path = Path(str(value))
    return path if path.is_absolute() else ROOT / path


def _merge_world_action_catalogs(data):
    """Подключить внешние каталоги действий к миру (P3).

    Порядок: сначала собственные ``actions`` мира, затем
    ``action_catalogs`` по порядку. Действие с тем же ``id`` из более
    позднего источника переопределяет раннее; дубликат внутри одного
    файла — ошибка.
    """
    catalogs = data.get("action_catalogs") or []
    if not catalogs:
        return data
    sources = [
        (
            str(data.get("id") or "world"),
            {"actions": list(data.get("actions") or [])},
        )
    ]
    for item in catalogs:
        if isinstance(item, str):
            path = item
        elif isinstance(item, dict):
            path = item.get("path")
        else:
            path = None
        if not path:
            raise WorldError("action_catalogs: нужен путь к JSON")
        catalog = _read_json(_resolve_config_path(path))
        if not isinstance(catalog, dict):
            raise WorldError(
                "%s: каталог действий должен быть объектом" % path
            )
        sources.append((str(path), catalog))
    actions, problems, overrides = merge_action_catalogs(sources)
    if problems:
        raise WorldError("; ".join(problems))
    merged = dict(data)
    merged["actions"] = actions
    merged["action_catalog_overrides"] = overrides
    merged.pop("action_catalogs", None)
    return merged


def _forms_for_world(data):
    path = data.get("forms_path")
    try:
        return FormCatalog.load(
            _resolve_config_path(path) if path else None
        )
    except ActionError as exc:
        raise WorldError(str(exc))


def _merge_world_scene_catalog(data):
    """Подключить каталоги сцен к миру (P6).

    ``scene_catalog`` — путь или список путей к JSON-файлам со сценами.
    Сцены из более позднего файла переопределяют ранние по ``id``.
    """
    entry = data.get("scene_catalog")
    if not entry:
        return data
    paths = [entry] if isinstance(entry, str) else list(entry)
    merged = {}
    for item in paths:
        if isinstance(item, str):
            path = item
        elif isinstance(item, dict):
            path = item.get("path")
        else:
            path = None
        if not path:
            raise WorldError("scene_catalog: нужен путь к JSON")
        try:
            catalog = SceneCatalog.load(_resolve_config_path(path))
        except SceneError as exc:
            raise WorldError(str(exc))
        for scene_id, scene in catalog.scenes.items():
            merged[scene_id] = scene
    result = dict(data)
    result["scenes"] = [scene.as_dict() for scene in merged.values()]
    result.pop("scene_catalog", None)
    return result


def _validate_unique(items, label):
    if not isinstance(items, list) or not items:
        raise WorldError("%s должен быть непустым списком" % label)
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise WorldError("%s: элемент должен быть объектом" % label)
        item_id = _text(item.get("id")).strip()
        if not item_id:
            raise WorldError("%s: пустой id" % label)
        if item_id in seen:
            raise WorldError("%s: повторяется id %r" % (label, item_id))
        seen.add(item_id)


def validate_world(data):
    data = dict(data)
    if data.get("action_catalogs"):
        data = _merge_world_action_catalogs(data)
    if data.get("scene_catalog"):
        data = _merge_world_scene_catalog(data)
    data["id"] = _text(data.get("id"), "world")
    data["title"] = _text(data.get("title"), data["id"])
    data["domains"] = list(data.get("domains") or [])
    data["polities"] = list(data.get("polities") or [])
    data["nodes"] = list(data.get("nodes") or [])
    data["offices"] = list(data.get("offices") or [])
    data["actions"] = list(data.get("actions") or [])
    data["characters"] = list(data.get("characters") or [])
    data["character_actions"] = list(data.get("character_actions") or [])
    data["items"] = list(data.get("items") or [])
    data["norms"] = list(data.get("norms") or [])
    data["scenes"] = list(data.get("scenes") or [])
    data["skill_tree"] = dict(data.get("skill_tree") or {})
    try:
        data["relation_axes"] = normalize_relation_axes_config(
            data.get("relation_axes")
        )
    except ValueError as exc:
        raise WorldError(str(exc))
    _validate_unique(data["domains"], "domains")
    _validate_unique(data["polities"], "polities")
    _validate_unique(data["nodes"], "nodes")
    _validate_unique(data["offices"], "offices")
    _validate_unique(data["actions"], "actions")
    for key, label in (
        ("characters", "characters"),
        ("character_actions", "character_actions"),
        ("items", "items"),
        ("norms", "norms"),
        ("scenes", "scenes"),
    ):
        if data[key]:
            _validate_unique(data[key], label)
    forms = _forms_for_world(data)
    for action in data["actions"]:
        has_form = bool(
            action.get("form") or (action.get("template") or {}).get("form")
        )
        try:
            if has_form:
                problems = lint_action(
                    action, forms=forms, require_form=True
                )
                if problems:
                    raise WorldError("; ".join(problems))
            normalized = normalize_action(action, forms=forms)
            action.clear()
            action.update(normalized)
        except ActionError as exc:
            raise WorldError("%s: %s" % (data["id"], exc))
    for action in data["character_actions"]:
        try:
            normalized = normalize_action(action, forms=forms)
            action.clear()
            action.update(normalized)
        except ActionError as exc:
            raise WorldError("%s: %s" % (data["id"], exc))

    domain_index = {item["id"]: item for item in data["domains"]}
    polity_index = {item["id"]: item for item in data["polities"]}
    for domain in data["domains"]:
        levels = domain.get("levels") or []
        if not levels:
            raise WorldError("%s: нет уровней" % domain["id"])
        _validate_unique(levels, "domains.%s.levels" % domain["id"])
        level_ids = {item["id"] for item in levels}
        domain["level_index"] = {
            item["id"]: int(item.get("rank", index + 1))
            for index, item in enumerate(levels)
        }
        if len(level_ids) != len(levels):
            raise WorldError("%s: повторяются уровни" % domain["id"])

    for office in data["offices"]:
        domain_id = _text(office.get("domain"))
        if domain_id not in domain_index:
            raise WorldError(
                "%s: неизвестный домен %r" % (office["id"], domain_id)
            )
        levels = office.get("levels") or []
        known = domain_index[domain_id]["level_index"]
        for level in levels:
            if level not in known and level != "*":
                raise WorldError(
                    "%s: неизвестный уровень %r" % (office["id"], level)
                )

    node_ids = {item["id"] for item in data["nodes"]}
    for node in data["nodes"]:
        domain_id = _text(node.get("domain"))
        if domain_id not in domain_index:
            raise WorldError(
                "%s: неизвестный домен %r" % (node["id"], domain_id)
            )
        level = _text(node.get("level"))
        if level not in domain_index[domain_id]["level_index"]:
            raise WorldError(
                "%s: неизвестный уровень %r" % (node["id"], level)
            )
        polity = _text(node.get("polity"))
        if polity and polity not in polity_index:
            raise WorldError(
                "%s: неизвестная политика %r" % (node["id"], polity)
            )
        parent = node.get("parent")
        if parent and parent not in node_ids:
            raise WorldError(
                "%s: неизвестный родитель %r" % (node["id"], parent)
            )
        if parent == node["id"]:
            raise WorldError(
                "%s: узел не может быть родителем себе" % node["id"]
            )
    for node in data["nodes"]:
        parent = node.get("parent")
        if not parent:
            continue
        seen = {node["id"]}
        cursor = data["nodes"]
        by_id = {item["id"]: item for item in cursor}
        while parent:
            if parent in seen:
                raise WorldError("цикл иерархии у узла %s" % node["id"])
            seen.add(parent)
            parent = (by_id.get(parent) or {}).get("parent")
    for character in data["characters"]:
        circle = _text(character.get("circle"), "acquaintance")
        if circle not in CHARACTER_CIRCLES:
            raise WorldError(
                "%s: неизвестный круг общения %r" % (character["id"], circle)
            )
        node_id = _text(character.get("node_id"))
        if node_id and node_id not in node_ids:
            raise WorldError(
                "%s: неизвестная структура %r" % (character["id"], node_id)
            )
    action_ids = {item["id"] for item in data["actions"]}
    public_ids = set()
    for raw_scene in data["scenes"]:
        try:
            scene = SceneSpec.from_dict(raw_scene)
        except SceneError as exc:
            raise WorldError(str(exc))
        if scene.location and scene.location not in node_ids:
            raise WorldError(
                "%s: неизвестная локация сцены %r"
                % (scene.id, scene.location)
            )
        unknown = [item for item in scene.works if item not in action_ids]
        if unknown:
            raise WorldError(
                "%s: неизвестные работы сцены: %s"
                % (scene.id, ", ".join(sorted(unknown)))
            )
        for person in scene.public:
            if person.id in public_ids:
                raise WorldError(
                    "%s: публика %r объявлена в нескольких сценах"
                    % (scene.id, person.id)
                )
            public_ids.add(person.id)
            if person.node_id and person.node_id not in node_ids:
                raise WorldError(
                    "%s: неизвестная структура публики %r"
                    % (person.id, person.node_id)
                )
    for action in data["character_actions"]:
        circles = action.get("circles") or ()
        for circle in circles:
            if circle not in CHARACTER_CIRCLES:
                raise WorldError(
                    "%s: неизвестный круг общения %r" % (action["id"], circle)
                )
    storyline = data.get("storyline")
    if storyline is not None:
        if not isinstance(storyline, dict):
            raise WorldError("storyline должен быть объектом")
        min_day = _as_int(storyline.get("min_day"), 0)
        if min_day < 0:
            raise WorldError("storyline.min_day не может быть отрицательным")
        deadline = storyline.get("deadline_day")
        if deadline is not None:
            deadline = _as_int(deadline, 0)
            if deadline < min_day:
                raise WorldError(
                    "storyline.deadline_day не может быть раньше min_day"
                )
        for side in ("win", "lose"):
            goal = storyline.get(side)
            if goal is None:
                continue
            if not isinstance(goal, dict):
                raise WorldError("storyline.%s должен быть объектом" % side)
            for key in ("standing_at_least", "standing_at_most"):
                if key not in goal:
                    continue
                value = _as_float(goal.get(key))
                if not 0.0 <= value <= 1.0:
                    raise WorldError(
                        "storyline.%s.%s должен быть в [0, 1]"
                        % (side, key)
                    )
            if side == "lose":
                days = _as_int(goal.get("days"), 1)
                if days < 1:
                    raise WorldError("storyline.lose.days должен быть >= 1")
    speeds = data.get("time_speeds")
    if speeds is not None:
        if not isinstance(speeds, list) or not speeds:
            raise WorldError("time_speeds должен быть непустым списком")
        for value in speeds:
            try:
                speed = float(value)
            except (TypeError, ValueError):
                raise WorldError("time_speeds: %r не число" % (value,))
            if speed < 1.0:
                raise WorldError("time_speeds: скорость не может быть < 1")
    try:
        strategies = StrategyBook.from_config(data)
        strategies.validate(
            action_ids={item["id"] for item in data["actions"]},
            node_ids={item["id"] for item in data["nodes"]},
        )
    except CampaignError as exc:
        raise WorldError(str(exc))
    return data


def _profile_connection_strength(profile, kinds=None):
    best = 0.0
    kinds = set(kinds or ())
    for connection in profile.get("connections") or ():
        if kinds and connection.get("kind") not in kinds:
            continue
        best = max(best, _as_float(connection.get("strength"), 0.0))
    return best


def _profile_skill(profile, key):
    return _as_float((profile.get("skills") or {}).get(key), 0.0)


def _add_skills(skills, addition):
    for key, value in (addition or {}).items():
        if key not in skills:
            skills[key] = 0.0
        skills[key] = _clamp(skills[key] + _as_float(value))


def _add_connections(connections, additions, source):
    for item in additions or ():
        record = dict(item)
        record.setdefault("id", "%s:%s" % (source, record.get("kind", "link")))
        record["strength"] = _clamp(record.get("strength", 0.2))
        connections.append(record)


def build_player_profile(variables, biography=None, seed=0):
    biography = biography or {}
    variables = dict(variables or {})
    tables = {
        "origin": "origins",
        "family": "families",
        "education": "educations",
        "formative": "formative_events",
        "vocation": "vocations",
        "value": "values",
        "value2": "values",
        "flaw": "flaws",
        "patron": "patrons",
        "reputation": "reputations",
    }
    default_name = _text(
        variables.get("name"),
        biography.get("default_name", "Новый герой"),
    ).strip()
    profile = {
        "name": default_name or "Новый герой",
        "gender": _text(variables.get("gender"), "unspecified"),
        "origin": "",
        "family": "",
        "education": "",
        "formative": "",
        "vocation": "",
        "values": [],
        "value_ids": [],
        "flaw": "",
        "patron": "",
        "reputation": "",
        "traits": [],
        "skills": {key: 0.08 for key in SKILL_ORDER},
        "connections": [],
        "biography": [],
        "seed": int(seed),
    }
    for variable, table_name in tables.items():
        selected = _text(variables.get(variable))
        entry = (biography.get(table_name) or {}).get(selected)
        if not isinstance(entry, dict):
            continue
        label = _text(entry.get("label"), selected)
        if variable in ("value", "value2"):
            if label not in profile["values"]:
                profile["values"].append(label)
            value_id = _values.value_id(selected or label)
            if value_id and value_id not in profile["value_ids"]:
                profile["value_ids"].append(value_id)
        else:
            profile[variable] = label
        _add_skills(profile["skills"], entry.get("skills"))
        for trait in entry.get("traits") or ():
            if trait not in profile["traits"]:
                profile["traits"].append(str(trait))
        _add_connections(
            profile["connections"],
            entry.get("connections"),
            "%s:%s" % (table_name, selected),
        )
        text = _text(entry.get("text"))
        if text:
            profile["biography"].append(text)
    if not profile["values"]:
        profile["values"].append("достоинство")
    if not profile["value_ids"]:
        profile["value_ids"] = [
            _values.value_id(item) for item in profile["values"]
        ]
    if not profile["traits"]:
        profile["traits"].append("незаметный")
    profile["aptitudes"] = {
        domain: _clamp(
            sum(_profile_skill(profile, key) for key in keys)
            / max(1, len(keys))
        )
        for domain, keys in DOMAIN_SKILLS.items()
    }
    return profile


def profile_from_identity(identity, biography=None, seed=0):
    """Собрать профиль мира из личности, собранной редактором.

    ``build_player_profile`` читает биографические таблицы по id. Личность
    из ``configs/characters/identity.json`` использует собственные id,
    поэтому часть разделов может не найтись в biography. В этом случае
    профиль сохраняет подписи и текст личности, чтобы герой не терял
    происхождение, призвание и ценность при переходе в мир.

    Функция не требует фракции, должности или кампании: это точка входа
    свободного режима.
    """
    identity = dict(identity or {})
    variables = {
        "name": identity.get("name"),
        "gender": identity.get("gender"),
        "origin": identity.get("origin"),
        "vocation": identity.get("vocation"),
        "value": identity.get("value"),
        "value2": identity.get("value2"),
        "flaw": identity.get("flaw"),
    }
    profile = build_player_profile(
        variables,
        biography=biography,
        seed=seed,
    )

    labels = {
        "origin": identity.get("origin_label"),
        "vocation": identity.get("vocation_label"),
        "flaw": identity.get("flaw_label"),
    }
    for key, label in labels.items():
        if label and not profile.get(key):
            profile[key] = _text(label)

    value_labels = []
    for key in ("value_label", "value2_label"):
        label = _text(identity.get(key)).strip()
        if label and label not in value_labels:
            value_labels.append(label)
    if value_labels:
        profile["values"] = value_labels
        value_ids = []
        for key in ("value", "value2"):
            value_id = _values.value_id(identity.get(key))
            if value_id and value_id not in value_ids:
                value_ids.append(value_id)
        profile["value_ids"] = value_ids

    trait_labels = []
    try:
        import character_traits as CT

        trait_model = CT.load_traits()
        trait_labels = [
            trait_model.labels.get(str(key), str(key))
            for key, amount in (identity.get("traits") or {}).items()
            if _as_float(amount) > 0.0
        ]
    except Exception:
        trait_labels = []
    for label in trait_labels:
        if label and label not in profile["traits"]:
            profile["traits"].append(label)

    biography_text = _text(identity.get("biography")).strip()
    if biography_text:
        profile["biography"] = [biography_text]
    for key in (
        "summary",
        "gender_label",
        "trait",
        "trait_label",
        "trait_summary",
        "archetype_id",
    ):
        value = identity.get(key)
        if value:
            profile[key] = value
    profile["seed"] = int(seed)
    return profile


def normalize_profile(profile):
    profile = dict(profile or {})
    profile.setdefault("name", "Новый герой")
    profile.setdefault("gender", "unspecified")
    profile.setdefault("traits", [])
    profile.setdefault("skills", {})
    profile.setdefault("connections", [])
    profile.setdefault("biography", [])
    profile.setdefault("values", [])
    profile.setdefault("value_ids", [])
    profile.setdefault("aptitudes", {})
    if not profile["value_ids"]:
        profile["value_ids"] = [
            _values.value_id(item)
            for item in profile.get("values") or ()
            if _values.value_id(item)
        ]
    for key in SKILL_ORDER:
        profile["skills"].setdefault(key, 0.08)
    for domain, keys in DOMAIN_SKILLS.items():
        profile["aptitudes"].setdefault(
            domain,
            _clamp(
                sum(_profile_skill(profile, key) for key in keys)
                / max(1, len(keys))
            ),
        )
    return profile


def office_profile_status(profile, office, skill_labels=None):
    requirements = office.get("requires") or {}
    skill_labels = skill_labels or {}
    for skill, minimum in (requirements.get("skills") or {}).items():
        if _profile_skill(profile, skill) + 1e-9 < _as_float(minimum):
            return False, "нужен навык «%s» не ниже %.0f%%" % (
                skill_labels.get(skill, skill),
                100.0 * _as_float(minimum),
            )
    traits = requirements.get("traits_any") or []
    if traits and not any(
        item in (profile.get("traits") or []) for item in traits
    ):
        return False, "нужен один из признаков: %s" % ", ".join(traits)
    values = requirements.get("values_any") or []
    if values and not any(
        item in (profile.get("values") or []) for item in values
    ):
        return False, "нужны ценности: %s" % ", ".join(values)
    connection_kinds = requirements.get("connections_any") or []
    if connection_kinds and not any(
        item.get("kind") in connection_kinds
        for item in (profile.get("connections") or ())
    ):
        return False, "нужна связь: %s" % ", ".join(connection_kinds)
    return True, ""
