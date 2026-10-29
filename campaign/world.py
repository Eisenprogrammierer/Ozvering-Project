from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core41 import HEALTH_MAX, SICKNESS_MAX

from .errors import CampaignError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORLD_PATH = ROOT / "configs" / "worlds" / "agora_world.json"
DEFAULT_BIOGRAPHY_PATH = ROOT / "configs" / "worlds" / "biography.json"

CAMPAIGN_HEALTH_REGEN = 1.0
CAMPAIGN_SICKNESS_PROGRESS = 0.01
CAMPAIGN_SICKNESS_HEALTH_DECAY = 6.0
COLLAPSE_POWER = 0.05
COLLAPSE_COHESION = 0.05
# Распад — не мгновенный срез одной шкалы (вопрос §7 №28): организация
# должна продержаться ниже порога `COLLAPSE_GRACE_DAYS` дней подряд.
# Полный ноль силы и связности распадается сразу, чтобы «мёртвая»
# организация не висела в мире лишний день.
COLLAPSE_GRACE_DAYS = 2
# Более глубокий критерий первого среза: легитимность ниже этого порога
# делает структуру нежизнеспособной, но пока не завершает игру сама по
# себе — она лишь усиливает давление распада (см. organization_status()).
COLLAPSE_LEGITIMACY = 0.02
# Увольнение — смена роли, а не поражение (вопрос §7 №29). Пороги те же,
# что были у старого терминального «потерял должность», но теперь они
# переводят игрока в другую роль.
DISMISSAL_STANDING = 0.05
DISMISSAL_LEGITIMACY = 0.08
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
CHARACTER_STAT_LABELS = {
    "affinity": "расположение",
    "trust": "доверие",
}
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


def load_world(path=None):
    data = _read_json(path if path is not None else DEFAULT_WORLD_PATH)
    if not isinstance(data, dict):
        raise WorldError("мир должен быть объектом")
    return validate_world(data)


def load_biography(path=None):
    data = _read_json(path if path is not None else DEFAULT_BIOGRAPHY_PATH)
    if not isinstance(data, dict):
        raise WorldError("биография должна быть объектом")
    return data


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
    data["skill_tree"] = dict(data.get("skill_tree") or {})
    _validate_unique(data["domains"], "domains")
    _validate_unique(data["polities"], "polities")
    _validate_unique(data["nodes"], "nodes")
    _validate_unique(data["offices"], "offices")
    _validate_unique(data["actions"], "actions")
    for key, label in (
        ("characters", "characters"),
        ("character_actions", "character_actions"),
        ("items", "items"),
    ):
        if data[key]:
            _validate_unique(data[key], label)

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
    for action in data["character_actions"]:
        circles = action.get("circles") or ()
        for circle in circles:
            if circle not in CHARACTER_CIRCLES:
                raise WorldError(
                    "%s: неизвестный круг общения %r" % (action["id"], circle)
                )
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


def normalize_profile(profile):
    profile = dict(profile or {})
    profile.setdefault("name", "Новый герой")
    profile.setdefault("gender", "unspecified")
    profile.setdefault("traits", [])
    profile.setdefault("skills", {})
    profile.setdefault("connections", [])
    profile.setdefault("biography", [])
    profile.setdefault("values", [])
    profile.setdefault("aptitudes", {})
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


class WorldEngine:

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
        self.seed = _as_int(
            seed,
            _as_int(snapshot.get("seed"), 7) if snapshot else 7,
        )
        self.days = max(1, _as_int(self.config.get("days"), 30))
        # Бесконечная рамка (вопрос §7 №30): `days` остаётся сюжетным
        # горизонтом для старых сюжетов и UI, но по умолчанию больше не
        # завершает игру «победой на 31-й день». Явный `infinite: false`
        # возвращает легаси-конец для старых кампаний.
        self.infinite = bool(self.config.get("infinite", True))
        self.collapse_grace_days = max(
            1,
            _as_int(
                self.config.get("collapse_grace_days"),
                COLLAPSE_GRACE_DAYS,
            ),
        )
        # Оффлайн-догон (вопрос §7 №31): значения можно переопределить
        # конфигом мира, но по умолчанию фон ограничен.
        self.offline_progress = bool(
            self.config.get("offline_progress", True)
        )
        self.seconds_per_day = max(
            1.0, _as_float(self.config.get("seconds_per_day"), 120.0)
        )
        self.max_offline_days = max(
            1, _as_int(self.config.get("max_offline_days"), 7)
        )
        self.actions_per_day = max(
            1, _as_int(self.config.get("actions_per_day"), 3)
        )
        self.skill_labels = dict(self.config.get("skill_labels") or {})
        self.stat_labels = dict(self.config.get("stat_labels") or {})
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
            item["id"]: self._build_character(item)
            for item in self.config["characters"]
        }
        self.character_actions = {
            item["id"]: item for item in self.config["character_actions"]
        }
        self.item_order = [item["id"] for item in self.config["items"]]
        self.item_catalog = {
            item["id"]: dict(item) for item in self.config["items"]
        }
        self.nodes = self._build_nodes()
        self.node_order = [item["id"] for item in self.config["nodes"]]
        self.profile = normalize_profile(
            profile or self.config.get("default_profile") or {}
        )
        self.player_node_id = _text(node_id)
        self.player_office_id = _text(office_id)
        self.player_authority = 0.0
        self.player_resources = {key: 0.0 for key in PLAYER_STATS}
        self.player_item_ids = []
        condition = self.config.get("condition") or {}
        self.player_health = _clamp(
            _as_float(condition.get("health"), HEALTH_MAX),
            0.0,
            HEALTH_MAX,
        )
        self.player_sickness = _clamp(
            _as_float(condition.get("sickness"), 0.0),
            0.0,
            SICKNESS_MAX,
        )
        self.player_alive = self.player_health > 0.0
        self.day = 1
        self.actions_left = self.actions_per_day
        self.action_count = 0
        self.cooldowns = {}
        self.used_actions = []
        self.log = []
        self.last_result = None
        self.outcome = None
        self.finished = False
        self.career_history = []
        # Состояние вопросов §7 №28–30. `dismissed` — событие смены роли,
        # `collapse_days` — счётчик подряд идущих дней ниже порога силы/
        # связности, `ending` — нарративный финал без объективной победы.
        self.dismissed = False
        self.dismissal_count = 0
        self.collapsed = False
        self.collapse_days = 0
        self.horizon_passed = False
        self.ending = None
        self.attached = False
        if snapshot:
            self.load_snapshot(snapshot)
        else:
            if self.player_node_id and self.player_office_id:
                self.attach(self.player_node_id, self.player_office_id)
            self._opening()

    def _build_nodes(self):
        nodes = {}
        for raw in self.config["nodes"]:
            node = {
                "id": raw["id"],
                "name": _text(raw.get("name"), raw["id"]),
                "domain": raw["domain"],
                "level": raw["level"],
                "polity": _text(raw.get("polity")),
                "kind": _text(raw.get("kind"), "institution"),
                "parent": _text(raw.get("parent")),
                "tags": list(raw.get("tags") or ()),
                "description": _text(raw.get("description")),
                "interests": dict(raw.get("interests") or {}),
                "stats": {
                    key: _clamp((raw.get("stats") or {}).get(key, 0.5))
                    for key in NODE_STATS
                },
                "relations": {},
                "children": [],
            }
            nodes[node["id"]] = node
        for node in nodes.values():
            parent = node.get("parent")
            if parent and parent in nodes:
                nodes[parent]["children"].append(node["id"])
        for node in nodes.values():
            for other in nodes.values():
                if other["id"] == node["id"]:
                    continue
                base = 0.0
                if node["polity"] and node["polity"] == other["polity"]:
                    base += 0.15
                if node["domain"] == other["domain"]:
                    base += 0.1
                if node["parent"] == other["id"]:
                    base += 0.1
                node["relations"][other["id"]] = _clamp(base, -1.0, 1.0)
        return nodes

    @staticmethod
    def _build_character(raw):
        health = _clamp(
            _as_float(raw.get("health"), HEALTH_MAX),
            0.0,
            HEALTH_MAX,
        )
        return {
            "id": raw["id"],
            "name": _text(raw.get("name"), raw["id"]),
            "role": _text(raw.get("role")),
            "circle": _text(raw.get("circle"), "acquaintance"),
            "affinity": _clamp(raw.get("affinity", 0.0), -1.0, 1.0),
            "trust": _clamp(raw.get("trust", 0.0), -1.0, 1.0),
            "health": health,
            "sickness": _clamp(
                _as_float(raw.get("sickness"), 0.0),
                0.0,
                SICKNESS_MAX,
            ),
            "alive": bool(raw.get("alive", health > 0.0)),
            "node_id": _text(raw.get("node_id")),
            "tags": list(raw.get("tags") or ()),
            "description": _text(raw.get("description")),
        }

    def _opening(self):
        for text in self.config.get("opening_log") or ():
            self.log.append(
                {"day": self.day, "kind": "opening", "text": str(text)}
            )

    def domain_label(self, domain_id):
        return self.domain_labels.get(domain_id, domain_id)

    def kind_label(self, kind_id):
        return KIND_LABELS.get(kind_id, kind_id)

    def level_label(self, domain_id, level_id):
        domain = self.domain_index.get(domain_id) or {}
        for level in domain.get("levels") or ():
            if level.get("id") == level_id:
                return _text(level.get("label"), level_id)
        return level_id

    def node_level_label(self, node):
        if not node:
            return "—"
        return self.level_label(node.get("domain"), node.get("level"))

    def node(self, node_id):
        return self.nodes.get(_text(node_id))

    def node_label(self, node_id):
        node = self.node(node_id)
        return node["name"] if node else "—"

    def node_path(self, node_id):
        node = self.node(node_id)
        if node is None:
            return []
        path = []
        seen = set()
        while node is not None and node["id"] not in seen:
            path.append(node)
            seen.add(node["id"])
            node = self.node(node.get("parent"))
        return list(reversed(path))

    def node_depth(self, node_id):
        return max(0, len(self.node_path(node_id)) - 1)

    def is_descendant(self, node_id, ancestor_id):
        node = self.node(node_id)
        while node is not None:
            if node["id"] == ancestor_id:
                return node_id != ancestor_id
            node = self.node(node.get("parent"))
        return False

    def relation(self, source_id, target_id):
        source = self.node(source_id) or {}
        return _as_float((source.get("relations") or {}).get(target_id), 0.0)

    def office_templates_for_node(self, node):
        if not node:
            return []
        result = []
        for office in self.offices.values():
            if office.get("domain") != node.get("domain"):
                continue
            levels = office.get("levels") or []
            if node.get("level") not in levels and "*" not in levels:
                continue
            result.append(office)
        return sorted(
            result,
            key=lambda item: (
                _as_int(item.get("rank"), 99),
                -_as_float(item.get("authority"), 0.0),
                item["id"],
            ),
        )

    def office_label(self, office_id):
        office = self.offices.get(_text(office_id)) or {}
        return _text(office.get("label"), office_id)

    def head_office_for_node(self, node):
        templates = self.office_templates_for_node(node)
        if not templates:
            return None
        return templates[0]

    def _office_authority(self, office, node, is_player=True):
        base = _as_float(office.get("authority"), 0.5)
        if not is_player:
            return _clamp(base)
        skill_key = _text(office.get("skill"))
        skill = _profile_skill(self.profile, skill_key)
        connection = _profile_connection_strength(
            self.profile,
            office.get("connection_kinds") or (),
        )
        return _clamp(base + 0.18 * skill + 0.10 * connection)

    def office_options(self, node_id):
        node = self.node(node_id)
        if node is None:
            return []
        result = []
        for office in self.office_templates_for_node(node):
            enabled, reason = office_profile_status(
                self.profile, office, self.skill_labels
            )
            result.append(
                {
                    "office": office,
                    "id": office["id"],
                    "label": _text(office.get("label"), office["id"]),
                    "enabled": enabled,
                    "reason": reason,
                    "authority": self._office_authority(office, node),
                    "rank": _as_int(office.get("rank"), 99),
                }
            )
        return result

    def attach(self, node_id, office_id):
        node = self.node(node_id)
        office = self.offices.get(_text(office_id))
        if node is None:
            return {"ok": False, "reason": "неизвестная структура"}
        if office is None:
            return {"ok": False, "reason": "неизвестная должность"}
        options = {item["id"]: item for item in self.office_options(node_id)}
        option = options.get(office["id"])
        if option is None:
            return {
                "ok": False,
                "reason": "должность не относится к этой структуре",
            }
        if not option.get("enabled"):
            return {
                "ok": False,
                "reason": option.get("reason") or "должность недоступна",
            }
        self.player_node_id = node["id"]
        self.player_office_id = office["id"]
        self.player_authority = option["authority"]
        aptitude = _as_float(
            (self.profile.get("aptitudes") or {}).get(node["domain"]), 0.0
        )
        connection = _profile_connection_strength(
            self.profile,
            office.get("connection_kinds") or (),
        )
        self.player_resources = {
            "influence": _clamp(0.22 + 0.25 * aptitude + 0.10 * connection),
            "favor": _clamp(0.18 + 0.20 * connection),
            "evidence": 0.0,
            "standing": _clamp(0.28 + 0.25 * aptitude + 0.10 * connection),
        }
        self.attached = True
        self._refresh_items()
        self.log.append(
            {
                "day": self.day,
                "kind": "career",
                "text": "%s занял должность «%s» в структуре «%s»."
                % (
                    self.profile.get("name", "Герой"),
                    _text(office.get("label"), office["id"]),
                    node["name"],
                ),
            }
        )
        return {"ok": True, "node": node, "office": office}

    def _context(self, node, office, is_player=False):
        if node is None or office is None:
            return None
        return {
            "node": node,
            "office": office,
            "domain": node["domain"],
            "level": node["level"],
            "kind": node["kind"],
            "polity": node["polity"],
            "authority": self._office_authority(
                office, node, is_player=is_player
            ),
            "is_player": bool(is_player),
            "ai": not bool(is_player),
        }

    def player_context(self):
        if not self.attached:
            return None
        node = self.node(self.player_node_id)
        office = self.offices.get(self.player_office_id)
        context = self._context(node, office, is_player=True)
        if context is None:
            return None
        context["authority"] = self.player_authority
        return context

    def node_context(self, node_id):
        node = self.node(node_id)
        if node is None:
            return None
        office = self.head_office_for_node(node)
        return self._context(node, office, is_player=False)

    def player_office(self):
        office = self.offices.get(self.player_office_id) or {}
        node = self.node(self.player_node_id) or {}
        return {
            "id": office.get("id", ""),
            "title": _text(office.get("label"), office.get("id", "—")),
            "node_id": node.get("id", ""),
            "node_name": node.get("name", "—"),
            "domain": node.get("domain", ""),
            "domain_label": self.domain_label(node.get("domain", "")),
            "level": node.get("level", ""),
            "level_label": self.node_level_label(node),
            "authority": self.player_authority,
            "rank": _as_int(office.get("rank"), 99),
        }

    def character(self, character_id):
        return self.characters.get(_text(character_id))

    def character_circle_label(self, circle_id):
        return CHARACTER_CIRCLES.get(circle_id, circle_id)

    def characters_by_circle(self, circle_id):
        circle_id = _text(circle_id)
        return [
            self.characters[character_id]
            for character_id in self.character_order
            if self.characters[character_id]["circle"] == circle_id
        ]

    def character_relation(self, character_id):
        character = self.character(character_id) or {}
        return _as_float(character.get("affinity"), 0.0)

    def character_trust(self, character_id):
        character = self.character(character_id) or {}
        return _as_float(character.get("trust"), 0.0)

    def player_condition(self):
        return {
            "health": float(self.player_health),
            "max_health": float(HEALTH_MAX),
            "sickness": float(self.player_sickness),
            "alive": bool(self.player_alive),
        }

    def character_condition(self, character_id):
        character = self.character(character_id)
        if character is None:
            return None
        return {
            "health": float(character["health"]),
            "max_health": float(HEALTH_MAX),
            "sickness": float(character["sickness"]),
            "alive": bool(character["alive"]),
        }

    def infect_player(self, severity):
        self.player_sickness = min(
            SICKNESS_MAX,
            max(self.player_sickness, _as_float(severity)),
        )
        return self.player_sickness

    def treat_player(self, amount):
        self.player_sickness = max(
            0.0,
            self.player_sickness - max(0.0, _as_float(amount)),
        )
        return self.player_sickness

    def infect_character(self, character_id, severity):
        character = self.character(character_id)
        if character is None or not character["alive"]:
            return None
        character["sickness"] = min(
            SICKNESS_MAX,
            max(character["sickness"], _as_float(severity)),
        )
        return character["sickness"]

    def treat_character(self, character_id, amount):
        character = self.character(character_id)
        if character is None or not character["alive"]:
            return None
        character["sickness"] = max(
            0.0,
            character["sickness"] - max(0.0, _as_float(amount)),
        )
        return character["sickness"]

    def _advance_condition(self, health, sickness):
        health = _clamp(health, 0.0, HEALTH_MAX)
        sickness = _clamp(sickness, 0.0, SICKNESS_MAX)
        if sickness > 0.0:
            health = max(
                0.0,
                health - CAMPAIGN_SICKNESS_HEALTH_DECAY * sickness,
            )
            sickness = min(
                SICKNESS_MAX,
                sickness + CAMPAIGN_SICKNESS_PROGRESS,
            )
        else:
            health = min(HEALTH_MAX, health + CAMPAIGN_HEALTH_REGEN)
        return health, sickness

    def _advance_conditions(self):
        changed = []
        if self.player_alive:
            before = (self.player_health, self.player_sickness)
            self.player_health, self.player_sickness = (
                self._advance_condition(
                    self.player_health, self.player_sickness
                )
            )
            if (self.player_health, self.player_sickness) != before:
                changed.append(
                    (
                        "герой · здоровье",
                        self.player_health - before[0],
                    )
                )
            if self.player_health <= 0.0:
                self.player_alive = False
                self.outcome = "lose"
                self.finished = True
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "death",
                        "text": "Герой умер от болезни и истощения.",
                    }
                )
        for character_id in self.character_order:
            character = self.characters[character_id]
            if not character["alive"]:
                continue
            before = (character["health"], character["sickness"])
            character["health"], character["sickness"] = (
                self._advance_condition(
                    character["health"], character["sickness"]
                )
            )
            if (character["health"], character["sickness"]) != before:
                changed.append(
                    (
                        "%s · здоровье" % character["name"],
                        character["health"] - before[0],
                    )
                )
            if character["health"] <= 0.0:
                character["alive"] = False
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "death",
                        "text": "%s умер(ла) от болезни."
                        % character["name"],
                    }
                )
        return self._merge_changes(changed)

    def organization_category(self, node_id):
        node = self.node(node_id)
        if node is None:
            return ""
        if not self.attached:
            return "neutral"
        if node["id"] == self.player_node_id:
            return "allied"
        if node.get("kind") == "asset":
            return ""
        if self.is_descendant(node["id"], self.player_node_id):
            return "allied"
        relation = self.relation(self.player_node_id, node["id"])
        if relation >= 0.22:
            return "allied"
        if relation <= -0.15:
            return "hostile"
        return "neutral"

    def organization_groups(self):
        groups = {key: [] for key in ORGANIZATION_CATEGORIES}
        for node in self.sorted_nodes():
            if (
                node.get("kind") == "asset"
                and node["id"] != self.player_node_id
            ):
                continue
            category = self.organization_category(node["id"])
            if category:
                groups[category].append(node)
        return groups

    def _refresh_items(self):
        self.player_item_ids = []
        if not self.attached:
            return
        node = self.node(self.player_node_id) or {}
        domain = node.get("domain", "")
        for item_id in self.item_order:
            item = self.item_catalog[item_id]
            domains = item.get("domains") or ()
            if item.get("always") or (domains and domain in domains):
                self.player_item_ids.append(item_id)
                continue
            min_skills = item.get("min_skills") or {}
            if min_skills and all(
                _profile_skill(self.profile, key) + 1e-9 >= _as_float(value)
                for key, value in min_skills.items()
            ):
                self.player_item_ids.append(item_id)
        limit = max(1, _as_int(self.config.get("max_items"), 6))
        self.player_item_ids = self.player_item_ids[:limit]

    def player_items(self):
        return [
            dict(self.item_catalog[item_id])
            for item_id in self.player_item_ids
            if item_id in self.item_catalog
        ]

    def skill_tree(self):
        raw_tree = self.config.get("skill_tree") or {}
        branches = raw_tree.get("branches") or []
        descriptions = raw_tree.get("descriptions") or {}
        result = []
        for branch in branches:
            skills = []
            for skill_id in branch.get("skills") or ():
                if skill_id not in self.skill_labels:
                    continue
                skills.append(
                    {
                        "id": skill_id,
                        "label": self.skill_labels[skill_id],
                        "value": _profile_skill(self.profile, skill_id),
                        "description": _text(descriptions.get(skill_id)),
                    }
                )
            if skills:
                result.append(
                    {
                        "id": branch.get("id", ""),
                        "label": _text(branch.get("label"), ""),
                        "description": _text(branch.get("description")),
                        "skills": skills,
                    }
                )
        return result

    def _character_reason_cost(self, action):
        context = self.player_context()
        if context is None:
            return "сначала выберите должность"
        return self._reason_cost(action, context)

    def _reason_character(self, action, character):
        if not character.get("alive", True):
            return "собеседник мёртв"
        circles = action.get("circles") or ()
        if circles and character["circle"] not in circles:
            return "этот шаг не подходит для такой связи"
        requires = action.get("requires") or {}
        for key, minimum in (requires.get("character") or {}).items():
            current = _as_float(character.get(key), 0.0)
            if current + 1e-9 < _as_float(minimum):
                label = CHARACTER_STAT_LABELS.get(key, key)
                return "недостаточно: %s" % label
        for key, minimum in (requires.get("player") or {}).items():
            if _as_float(
                self.player_resources.get(key), 0.0
            ) + 1e-9 < _as_float(minimum):
                return "нужно больше личного ресурса «%s»" % self.stat_label(
                    key
                )
        for skill, minimum in (requires.get("skills") or {}).items():
            if _profile_skill(self.profile, skill) + 1e-9 < _as_float(minimum):
                return "нужен навык «%s»" % self.skill_labels.get(skill, skill)
        reason = self._character_reason_cost(action)
        if reason:
            return reason
        if self.actions_left <= 0:
            return "действия на сегодня исчерпаны"
        if action.get("once") and action["id"] in self.used_actions:
            return "действие уже использовано"
        cooldown = _as_int(action.get("cooldown_days"), 0)
        if cooldown:
            key = "character:%s:%s" % (action["id"], character["id"])
            last_day = self.cooldowns.get(key)
            if last_day is not None and self.day - int(last_day) < cooldown:
                return "повтор не раньше дня %d" % (int(last_day) + cooldown)
        return ""

    def character_action_options(self, character_id):
        character = self.character(character_id)
        if character is None:
            return []
        result = []
        for action in self.character_actions.values():
            reason = self._reason_character(action, character)
            success = action.get("success") or {}
            result.append(
                {
                    "action": action,
                    "id": action["id"],
                    "label": _text(action.get("label"), action["id"]),
                    "enabled": not reason,
                    "reason": reason,
                    "cost": self._cost_text(action),
                    "chance": _as_float(
                        success.get("chance"),
                        action.get("success_chance", 0.6),
                    ),
                    "character_id": character["id"],
                    "character_name": character["name"],
                }
            )
        return result

    def character_preview(self, action_id, character_id):
        action = self.character_actions.get(_text(action_id))
        character = self.character(character_id)
        if action is None:
            return None
        reason = (
            self._reason_character(action, character)
            if character is not None
            else "собеседник не найден"
        )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        return {
            "action": action,
            "character": character,
            "target_label": (
                character["name"] if character is not None else "—"
            ),
            "enabled": not reason,
            "reason": reason,
            "cost": self._cost_text(action),
            "immediate": self._effect_lines(action.get("immediate")),
            "success_chance": _as_float(
                success.get("chance"),
                action.get("success_chance", 0.6),
            ),
            "success_text": _text(success.get("text")),
            "success_effects": self._effect_lines(success.get("effects")),
            "failure_chance": _as_float(
                failure.get("chance"),
                max(
                    0.0,
                    1.0 - _as_float(action.get("success_chance"), 0.6),
                ),
            ),
            "failure_text": _text(failure.get("text")),
            "failure_effects": self._effect_lines(failure.get("effects")),
            "immediate_map": action.get("immediate") or {},
            "success_effects_map": success.get("effects") or {},
            "failure_effects_map": failure.get("effects") or {},
        }

    def _apply_character_effects(self, effects, character):
        effects = effects or {}
        changed = []
        for key in ("affinity", "trust"):
            if key not in effects:
                continue
            before = _as_float(character.get(key), 0.0)
            character[key] = _clamp(
                before + _as_float(effects.get(key)), -1.0, 1.0
            )
            delta = character[key] - before
            if abs(delta) > 1e-9:
                changed.append(
                    (
                        "%s · %s"
                        % (
                            character["name"],
                            CHARACTER_STAT_LABELS.get(key, key),
                        ),
                        delta,
                    )
                )
        changed.extend(self._apply_player_map(effects.get("player")))
        node_relation = _as_float(effects.get("node_relation"), 0.0)
        if (
            abs(node_relation) > 1e-9
            and self.attached
            and character.get("node_id")
            and self.node(character["node_id"]) is not None
        ):
            target = self.node(character["node_id"])
            current = self.relation(self.player_node_id, target["id"])
            value = _clamp(current + node_relation, -1.0, 1.0)
            source = self.node(self.player_node_id)
            if source is not None:
                source["relations"][target["id"]] = value
            target["relations"][self.player_node_id] = value
            changed.append(
                (
                    "%s · отношения" % target["name"],
                    value - current,
                )
            )
        return self._merge_changes(changed)

    def execute_character_action(self, action_id, character_id):
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        action = self.character_actions.get(_text(action_id))
        character = self.character(character_id)
        if action is None:
            return {"ok": False, "reason": "неизвестное действие"}
        if character is None:
            return {"ok": False, "reason": "собеседник не найден"}
        reason = self._reason_character(action, character)
        if reason:
            return {"ok": False, "reason": reason}
        context = self.player_context()
        if context is None:
            return {"ok": False, "reason": "сначала выберите должность"}
        self._pay_cost(action, context)
        changed = self._apply_character_effects(
            action.get("immediate"), character
        )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        chance = _as_float(
            success.get("chance"), action.get("success_chance", 0.6)
        )
        roll = self._roll(
            "character:%s:%s:%s:%s"
            % (
                self.day,
                action["id"],
                character["id"],
                self.action_count,
            )
        )
        outcome = "success" if roll < chance else "failure"
        branch = success if outcome == "success" else failure
        changed.extend(
            self._apply_character_effects(branch.get("effects"), character)
        )
        self.actions_left = max(0, self.actions_left - 1)
        self.action_count += 1
        cooldown = _as_int(action.get("cooldown_days"), 0)
        if cooldown:
            self.cooldowns[
                "character:%s:%s" % (action["id"], character["id"])
            ] = self.day
        if action.get("once"):
            self.used_actions.append(action["id"])
        text = _text(branch.get("text"), action.get("description", ""))
        result = {
            "ok": True,
            "action": action["id"],
            "action_label": _text(action.get("label"), action["id"]),
            "target": character["id"],
            "target_label": character["name"],
            "outcome": outcome,
            "text": text,
            "changes": changed,
            "day": self.day,
            "context": "character",
        }
        self.last_result = result
        self.log.append(
            {
                "day": self.day,
                "kind": outcome,
                "text": "%s → %s: %s"
                % (
                    result["action_label"],
                    character["name"],
                    text,
                ),
            }
        )
        self._check_dismissal()
        return result

    def _reason_actor(self, action, context):
        spec = action.get("actor") or {}
        domains = spec.get("domains") or []
        if domains and context["domain"] not in domains:
            return "действие относится к другой сфере: %s" % ", ".join(
                self.domain_label(item) for item in domains
            )
        levels = spec.get("levels") or []
        if levels and context["level"] not in levels:
            return "должность не того уровня: нужно %s" % ", ".join(
                self.level_label(context["domain"], item) for item in levels
            )
        offices = spec.get("offices") or []
        if offices and context["office"].get("id") not in offices:
            return "ваша должность не даёт этого права"
        kinds = spec.get("kinds") or []
        if kinds and context["kind"] not in kinds:
            return "этот тип структуры не может так действовать: нужно %s" % (
                ", ".join(self.kind_label(item) for item in kinds)
            )
        if context["authority"] + 1e-9 < _as_float(
            spec.get("min_authority"), 0.0
        ):
            return "недостаточно полномочий: нужно %.0f%%" % (
                100.0 * _as_float(spec.get("min_authority"), 0.0)
            )
        tags = spec.get("tags_any") or []
        if tags and not any(
            tag in context["node"].get("tags", ()) for tag in tags
        ):
            return "нужен признак структуры: %s" % ", ".join(tags)
        return ""

    def _reason_target(self, action, context, target):
        spec = action.get("target") or {}
        if spec.get("self"):
            if target is not None and target["id"] != context["node"]["id"]:
                return "действие выполняется для вашей собственной должности"
            return ""
        if not spec.get("required", True):
            return ""
        if target is None:
            return "нужно выбрать цель"
        if spec.get("exclude_self") and target["id"] == context["node"]["id"]:
            return "нельзя выбрать собственную структуру"
        kinds = spec.get("kinds") or []
        if kinds and target["kind"] not in kinds:
            return _text(
                spec.get("invalid_kind_reason"),
                "цель не того типа: нужно %s"
                % ", ".join(self.kind_label(item) for item in kinds),
            )
        domains = spec.get("domains") or []
        if domains and target["domain"] not in domains:
            return "цель относится к другой сфере: %s" % ", ".join(
                self.domain_label(item) for item in domains
            )
        levels = spec.get("levels") or []
        if levels and target["level"] not in levels:
            return "цель не того уровня: нужно %s" % ", ".join(
                self.level_label(target["domain"], item) for item in levels
            )
        polities = spec.get("polities") or []
        if polities and target["polity"] not in polities:
            return "цель находится в другой политии"
        if spec.get("same_polity") and target["polity"] != context["polity"]:
            return "цель должна быть в вашей политии"
        if spec.get("other_polity") and target["polity"] == context["polity"]:
            return "цель должна быть вне вашей политии"
        lineage = spec.get("lineage") or []
        if lineage:
            relation = "self" if target["id"] == context["node"]["id"] else ""
            if not relation and target["id"] in context["node"].get(
                "children", []
            ):
                relation = "child"
            if not relation and self.is_descendant(
                target["id"], context["node"]["id"]
            ):
                relation = "descendant"
            if not relation and context["node"].get("parent") == target["id"]:
                relation = "parent"
            if not relation and self.is_descendant(
                context["node"]["id"], target["id"]
            ):
                relation = "ancestor"
            if relation not in lineage:
                return "цель вне нужной ветви иерархии"
        return ""

    def _reason_requirements(self, action, context, target):
        requires = action.get("requires") or {}
        if context.get("is_player"):
            for key, minimum in (requires.get("player") or {}).items():
                if _as_float(
                    self.player_resources.get(key), 0.0
                ) + 1e-9 < _as_float(minimum):
                    return (
                        "нужно больше личного ресурса «%s»"
                        % self.stat_label(key)
                    )
            for skill, minimum in (requires.get("skills") or {}).items():
                if _profile_skill(self.profile, skill) + 1e-9 < _as_float(
                    minimum
                ):
                    return "нужен навык «%s» не ниже %.0f%%" % (
                        self.skill_labels.get(skill, skill),
                        100.0 * _as_float(minimum),
                    )
        for key, minimum in (requires.get("node") or {}).items():
            if _as_float(
                context["node"]["stats"].get(key), 0.0
            ) + 1e-9 < _as_float(minimum):
                return "у структуры мало ресурса «%s»" % self.stat_label(key)
        if target is not None:
            for key, minimum in (requires.get("target") or {}).items():
                if _as_float(target["stats"].get(key), 0.0) + 1e-9 < _as_float(
                    minimum
                ):
                    return "у цели мало ресурса «%s»" % self.stat_label(key)
            relation_min = requires.get("relation_min")
            if relation_min is not None:
                value = self.relation(context["node"]["id"], target["id"])
                if value + 1e-9 < _as_float(relation_min):
                    return "слишком плохие отношения с целью"
        return ""

    def _reason_cost(self, action, context):
        for key, value in (action.get("cost") or {}).get("node", {}).items():
            if _as_float(
                context["node"]["stats"].get(key), 0.0
            ) + 1e-9 < _as_float(value):
                return "недостаточно ресурса структуры «%s»" % self.stat_label(
                    key
                )
        if context.get("is_player"):
            for key, value in (
                (action.get("cost") or {}).get("player", {}).items()
            ):
                if _as_float(
                    self.player_resources.get(key), 0.0
                ) + 1e-9 < _as_float(value):
                    return (
                        "недостаточно личного ресурса «%s»"
                        % self.stat_label(key)
                    )
        return ""

    def validate(self, action_id, target_id=None, context=None):
        action = self.actions.get(_text(action_id))
        context = context or self.player_context()
        if action is None:
            return False, "неизвестное действие"
        if context is None:
            return False, "сначала выберите должность"
        target = self.node(target_id) if target_id else None
        if (action.get("target") or {}).get("self"):
            target = context["node"]
        reason = self._reason_actor(action, context)
        if reason:
            return False, reason
        reason = self._reason_target(action, context, target)
        if reason:
            return False, reason
        reason = self._reason_requirements(action, context, target)
        if reason:
            return False, reason
        reason = self._reason_cost(action, context)
        if reason:
            return False, reason
        if not context.get("ai"):
            cooldown = _as_int(action.get("cooldown_days"), 0)
            if cooldown:
                key = "%s:%s" % (
                    action["id"],
                    target["id"] if target else "",
                )
                last_day = self.cooldowns.get(key)
                if (
                    last_day is not None
                    and self.day - int(last_day) < cooldown
                ):
                    return False, "повтор не раньше дня %d" % (
                        int(last_day) + cooldown
                    )
            if self.actions_left <= 0:
                return False, "действия на сегодня исчерпаны"
            if action.get("once") and action["id"] in self.used_actions:
                return False, "действие уже использовано"
        return True, ""

    def action_options(self, target_id=None, include_disabled=True):
        context = self.player_context()
        if context is None:
            return []
        result = []
        for action in self.actions.values():
            self_target = bool((action.get("target") or {}).get("self"))
            target = context["node"] if self_target else self.node(target_id)
            enabled, reason = self.validate(
                action["id"], target["id"] if target else None, context
            )
            if not enabled and not include_disabled:
                continue
            result.append(
                {
                    "action": action,
                    "id": action["id"],
                    "label": _text(action.get("label"), action["id"]),
                    "enabled": enabled,
                    "reason": reason,
                    "self": self_target,
                    "target_id": target["id"] if target else "",
                    "cost": self._cost_text(action),
                }
            )
        return result

    def available_actions(self, target_id=None):
        return [
            item["id"]
            for item in self.action_options(target_id, include_disabled=False)
        ]

    def _cost_text(self, action):
        cost = action.get("cost") or {}
        parts = []
        for key, value in (cost.get("node") or {}).items():
            parts.append(
                "%s −%.0f%%" % (self.stat_label(key), 100.0 * _as_float(value))
            )
        for key, value in (cost.get("player") or {}).items():
            parts.append(
                "%s −%.0f%%" % (self.stat_label(key), 100.0 * _as_float(value))
            )
        return ", ".join(parts) or "без прямой платы"

    def stat_label(self, key):
        return self.stat_labels.get(key, key)

    def _effect_lines(self, effects):
        lines = []
        if not effects:
            return lines
        for section, label in (
            ("node", "структура"),
            ("target", "цель"),
            ("player", "вы"),
        ):
            for key, value in (effects.get(section) or {}).items():
                amount = _as_float(value)
                if abs(amount) < 1e-9:
                    continue
                lines.append(
                    "%s: %s %s%.0f%%"
                    % (
                        label,
                        self.stat_label(key),
                        "+" if amount > 0 else "",
                        100.0 * amount,
                    )
                )
        return lines

    def preview(self, action_id, target_id=None):
        action = self.actions.get(_text(action_id))
        if action is None:
            return None
        context = self.player_context()
        target = (
            context["node"]
            if action.get("target", {}).get("self") and context
            else self.node(target_id)
        )
        enabled, reason = self.validate(
            action["id"], target["id"] if target else None, context
        )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        return {
            "action": action,
            "target": target,
            "target_label": target["name"] if target else "своя должность",
            "enabled": enabled,
            "reason": reason,
            "cost": self._cost_text(action),
            "immediate": self._effect_lines(action.get("immediate")),
            "success_chance": _as_float(
                success.get("chance"), action.get("success_chance", 0.6)
            ),
            "success_text": _text(success.get("text")),
            "success_effects": self._effect_lines(success.get("effects")),
            "failure_chance": _as_float(
                failure.get("chance"),
                max(0.0, 1.0 - _as_float(action.get("success_chance"), 0.6)),
            ),
            "failure_text": _text(failure.get("text")),
            "failure_effects": self._effect_lines(failure.get("effects")),
            "immediate_map": action.get("immediate") or {},
            "success_effects_map": success.get("effects") or {},
            "failure_effects_map": failure.get("effects") or {},
        }

    def _apply_stat_map(self, node, changes):
        if node is None:
            return []
        changed = []
        for key, value in (changes or {}).items():
            if key not in node["stats"]:
                continue
            before = node["stats"][key]
            node["stats"][key] = _clamp(before + _as_float(value))
            delta = node["stats"][key] - before
            if abs(delta) > 1e-9:
                changed.append(
                    ("%s · %s" % (node["name"], self.stat_label(key)), delta)
                )
        return changed

    def _apply_player_map(self, changes):
        changed = []
        for key, value in (changes or {}).items():
            if key not in self.player_resources:
                continue
            before = self.player_resources[key]
            self.player_resources[key] = _clamp(before + _as_float(value))
            delta = self.player_resources[key] - before
            if abs(delta) > 1e-9:
                changed.append((self.stat_label(key), delta))
        return changed

    def end_storyline(self, kind, text=""):
        """Публичный вход в нарративный финал (§7 №30).

        Сюжет/UI может завершить главу без объективной победы: `win`/`lose`
        остаются совместимыми с легаси, `neutral` — «глава закончилась».
        """
        return self._apply_ending(kind, text)

    def _apply_ending(self, kind, text=""):
        """Нарративный финал без объективной победы (вопрос §7 №30).

        `win`/`lose` — сюжетный исход для старых сюжетов; `neutral` —
        глава закончилась, но поражения нет. Во всех случаях `finished`
        останавливает дневной цикл, а `outcome=None` для `neutral` не даёт
        `CampaignEnv` терминального бонуса победы/поражения.
        """
        kind = _text(kind).lower()
        if kind not in ENDING_KINDS or self.finished:
            return ""
        self.ending = kind
        self.outcome = None if kind == "neutral" else kind
        self.finished = True
        label = {
            "win": "Сюжетный финал: победа.",
            "lose": "Сюжетный финал: поражение.",
            "neutral": "Сюжетный финал: глава завершена.",
        }[kind]
        self.log.append(
            {
                "day": self.day,
                "kind": "ending",
                "text": text or label,
            }
        )
        return text or label

    def _apply_effects(self, effects, context, target, is_player=True):
        effects = effects or {}
        changed = []
        changed.extend(
            self._apply_stat_map(context["node"], effects.get("node"))
        )
        changed.extend(self._apply_stat_map(target, effects.get("target")))
        if is_player:
            changed.extend(self._apply_player_map(effects.get("player")))
        relation = _as_float(effects.get("relation"), 0.0)
        if target is not None and abs(relation) > 1e-9:
            source = context["node"]
            current = self.relation(source["id"], target["id"])
            value = _clamp(current + relation, -1.0, 1.0)
            source["relations"][target["id"]] = value
            target["relations"][source["id"]] = value
        if effects.get("ending"):
            self._apply_ending(effects.get("ending"), effects.get("text"))
        return self._merge_changes(changed)

    @staticmethod
    def _merge_changes(changed):
        merged = {}
        for label, value in changed:
            merged[label] = merged.get(label, 0.0) + float(value)
        return [
            (label, value)
            for label, value in merged.items()
            if abs(value) > 1e-9
        ]

    def _roll(self, token):
        digest = hashlib.sha256(
            ("%s:%s" % (self.seed, token)).encode("utf-8")
        ).hexdigest()
        return int(digest[:12], 16) / float(16**12)

    def _pay_cost(self, action, context):
        for key, value in (action.get("cost") or {}).get("node", {}).items():
            if key in context["node"]["stats"]:
                context["node"]["stats"][key] = _clamp(
                    context["node"]["stats"][key] - _as_float(value)
                )
        if context.get("is_player"):
            for key, value in (
                (action.get("cost") or {}).get("player", {}).items()
            ):
                if key in self.player_resources:
                    self.player_resources[key] = _clamp(
                        self.player_resources[key] - _as_float(value)
                    )

    def _career_target_available(self, action, target):
        if not target:
            return False, "нужна цель"
        office_kind = action.get("career")
        if office_kind not in ("promote", "transfer"):
            return True, ""
        options = self.office_options(target["id"])
        if not options:
            return False, "в цели нет подходящей должности"
        if office_kind == "promote":
            current_rank = _as_int(
                self.offices.get(self.player_office_id, {}).get("rank"), 99
            )
            candidates = [
                item
                for item in options
                if item.get("enabled") and item["rank"] < current_rank
            ]
            if not candidates:
                return False, "нет вакансии выше вашей должности"
        else:
            candidates = [item for item in options if item.get("enabled")]
            if not candidates:
                return False, "нет доступной должности в цели"
        return True, ""

    def _career_transition(self, action, target):
        kind = action.get("career")
        if kind == "resign":
            # Добровольная отставка — тоже смена роли, а не поражение
            # (вопрос §7 №29). Автоперевода здесь нет: игрок сам выбирает
            # новую должность через экран выбора роли.
            return self._dismiss(
                "добровольная отставка",
                kind="resign",
                auto_reassign=False,
            )
        if kind not in ("promote", "transfer") or target is None:
            return ""
        options = [
            item
            for item in self.office_options(target["id"])
            if item.get("enabled")
        ]
        if kind == "promote":
            current_rank = _as_int(
                self.offices.get(self.player_office_id, {}).get("rank"), 99
            )
            options = [item for item in options if item["rank"] < current_rank]
        if not options:
            return "Вакансия не открылась."
        chosen = sorted(
            options,
            key=lambda item: (item["rank"], -item["authority"]),
        )[0]
        previous_node = self.player_node_id
        previous_office = self.player_office_id
        self.player_node_id = target["id"]
        self.player_office_id = chosen["id"]
        self.player_authority = chosen["authority"]
        self._refresh_items()
        self.career_history.append(
            {
                "day": self.day,
                "kind": kind,
                "from": previous_node,
                "to": target["id"],
                "office_from": previous_office,
                "office_to": chosen["id"],
            }
        )
        self.log.append(
            {
                "day": self.day,
                "kind": "career",
                "text": "Новая должность: %s в структуре %s."
                % (chosen["label"], target["name"]),
            }
        )
        return "Новая должность: %s." % chosen["label"]

    def execute(self, action_id, target_id=None):
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        action = self.actions.get(_text(action_id))
        if action is None:
            return {"ok": False, "reason": "неизвестное действие"}
        context = self.player_context()
        if context is None:
            return {"ok": False, "reason": "сначала выберите должность"}
        target = (
            context["node"]
            if action.get("target", {}).get("self")
            else self.node(target_id)
        )
        enabled, reason = self.validate(
            action["id"], target["id"] if target else None, context
        )
        if not enabled:
            return {"ok": False, "reason": reason}
        if action.get("career"):
            available, career_reason = self._career_target_available(
                action, target
            )
            if not available:
                return {"ok": False, "reason": career_reason}
        self._pay_cost(action, context)
        changed = self._apply_effects(
            action.get("immediate"), context, target, is_player=True
        )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        chance = _as_float(
            success.get("chance"), action.get("success_chance", 0.6)
        )
        roll = self._roll(
            "player:%s:%s:%s:%s"
            % (
                self.day,
                action["id"],
                target["id"] if target else "-",
                self.action_count,
            )
        )
        outcome = "success" if roll < chance else "failure"
        branch = success if outcome == "success" else failure
        changed.extend(
            self._apply_effects(
                branch.get("effects"), context, target, is_player=True
            )
        )
        career_text = ""
        if outcome == "success" and action.get("career"):
            career_text = self._career_transition(action, target)
        if outcome == "failure" and action.get("career") == "resign":
            career_text = self._career_transition(action, target)
        self.actions_left = max(0, self.actions_left - 1)
        self.action_count += 1
        cooldown = _as_int(action.get("cooldown_days"), 0)
        if cooldown:
            self.cooldowns[
                "%s:%s" % (action["id"], target["id"] if target else "")
            ] = self.day
        if action.get("once"):
            self.used_actions.append(action["id"])
        text = _text(branch.get("text"), action.get("description", ""))
        if career_text:
            text = "%s %s" % (text, career_text) if text else career_text
        result = {
            "ok": True,
            "action": action["id"],
            "action_label": _text(action.get("label"), action["id"]),
            "target": target["id"] if target else "",
            "target_label": target["name"] if target else "своя должность",
            "outcome": outcome,
            "text": text,
            "changes": changed,
            "day": self.day,
            "ending": self.ending,
        }
        self.last_result = result
        self.log.append(
            {
                "day": self.day,
                "kind": outcome,
                "text": "%s → %s: %s"
                % (
                    result["action_label"],
                    result["target_label"],
                    text,
                ),
            }
        )
        self._check_dismissal()
        return result

    def _ai_targets(self, action, context):
        spec = action.get("target") or {}
        if spec.get("self"):
            return [context["node"]]
        if not spec.get("required", True):
            return [None]
        result = []
        for node in self.nodes.values():
            if node["id"] == context["node"]["id"]:
                if spec.get("exclude_self"):
                    continue
            reason = self._reason_target(action, context, node)
            if not reason:
                result.append(node)
        return result

    def _ai_score(self, action, context, target):
        weight = action.get("ai_weight") or {}
        score = 0.0
        interests = context["node"].get("interests") or {}
        for key, value in weight.items():
            score += _as_float(interests.get(key), 0.0) * _as_float(value)
        if not weight:
            score = 0.2
        if target is not None:
            score += 0.15 * self.relation(context["node"]["id"], target["id"])
            if target.get("polity") == context["node"].get("polity"):
                score += 0.05
        token = "ai:%s:%s:%s:%s" % (
            self.day,
            context["node"]["id"],
            action["id"],
            target["id"] if target else "-",
        )
        score += 0.20 * self._roll(token)
        for key, value in (action.get("cost") or {}).get("node", {}).items():
            score -= 0.10 * _as_float(value)
            if _as_float(context["node"]["stats"].get(key), 0.0) < 0.2:
                score -= 0.3
        return score

    def _ai_action(self, node_id):
        context = self.node_context(node_id)
        if context is None:
            return None
        best = None
        for action in self.actions.values():
            if not action.get("ai", True):
                continue
            if action.get("target", {}).get("self"):
                candidates = [context["node"]]
            else:
                candidates = self._ai_targets(action, context)
            for target in candidates:
                enabled, _reason = self.validate(
                    action["id"],
                    target["id"] if target else None,
                    context,
                )
                if not enabled:
                    continue
                score = self._ai_score(action, context, target)
                if best is None or score > best[0]:
                    best = (score, action, target)
        if best is None:
            return None
        _score, action, target = best
        self._pay_cost(action, context)
        changed = self._apply_effects(
            action.get("immediate"), context, target, is_player=False
        )
        success = action.get("success") or {}
        failure = action.get("failure") or {}
        chance = _as_float(
            success.get("chance"), action.get("success_chance", 0.6)
        )
        roll = self._roll(
            "ai:%s:%s:%s:%s"
            % (
                self.day,
                node_id,
                action["id"],
                target["id"] if target else "-",
            )
        )
        outcome = "success" if roll < chance else "failure"
        branch = success if outcome == "success" else failure
        changed.extend(
            self._apply_effects(
                branch.get("effects"), context, target, is_player=False
            )
        )
        text = _text(branch.get("text"), action.get("description", ""))
        entry = {
            "day": self.day,
            "kind": "world",
            "source": context["node"]["id"],
            "target": target["id"] if target else "",
            "text": "%s: %s %s"
            % (
                context["node"]["name"],
                _text(action.get("label"), action["id"]).lower(),
                "— %s" % text if text else "",
            ),
            "changes": changed,
        }
        self.log.append(entry)
        return entry

    def organization_status(self):
        """Состояние организации игрока для UI/наблюдения (§7 №28).

        `strain` — организация ниже порога силы или связности; `pressure`
        — нормированное давление 0..1 по худшей из двух шкал; `collapse_in`
        — сколько ещё дней подряд ниже порога осталось до распада.
        Легитимность входит в `deep_risk`: это более глубокий критерий,
        который пока не завершает игру сам, но сигнализирует о хрупкости.
        """
        node = self.node(self.player_node_id)
        if node is None:
            return {
                "node_id": "",
                "power": 0.0,
                "cohesion": 0.0,
                "legitimacy": 0.0,
                "strain": False,
                "deep_risk": False,
                "pressure": 0.0,
                "collapse_days": int(self.collapse_days),
                "collapse_in": 0,
            }
        stats = node["stats"]
        power = float(stats["power"])
        cohesion = float(stats["cohesion"])
        legitimacy = float(stats["legitimacy"])
        strain = (
            power <= COLLAPSE_POWER or cohesion <= COLLAPSE_COHESION
        )
        power_gap = max(
            0.0,
            (COLLAPSE_POWER - power) / max(COLLAPSE_POWER, 1e-9),
        )
        cohesion_gap = max(
            0.0,
            (COLLAPSE_COHESION - cohesion) / max(COLLAPSE_COHESION, 1e-9),
        )
        return {
            "node_id": node["id"],
            "power": power,
            "cohesion": cohesion,
            "legitimacy": legitimacy,
            "strain": bool(strain),
            "deep_risk": bool(
                legitimacy <= COLLAPSE_LEGITIMACY and strain
            ),
            "pressure": max(power_gap, cohesion_gap),
            "collapse_days": int(self.collapse_days),
            "collapse_in": max(
                0,
                int(self.collapse_grace_days) - int(self.collapse_days),
            )
            if strain
            else 0,
        }

    def _replacement_office(self, node_id, previous_office):
        """Найти другую доступную должность в той же структуре.

        Первый срез смены роли (§7 №29) — не полноценный рынок труда, а
        немедленный перевод внутри структуры. Если другой должности нет,
        игрок остаётся вне службы и может выбрать роль через UI.
        """
        previous = _text(previous_office)
        options = [
            item
            for item in self.office_options(node_id)
            if item.get("enabled") and item["id"] != previous
        ]
        if not options:
            return None
        options.sort(
            key=lambda item: (
                item["rank"],
                -_as_float(item.get("authority"), 0.0),
                item["id"],
            )
        )
        return options[0]

    def _dismiss(self, reason, kind="dismiss", auto_reassign=True):
        """Снять игрока с должности, не завершая кампанию (§7 №29).

        Возвращает текст для журнала/результата. При `auto_reassign=True`
        игрок сразу получает другую роль в той же структуре, если она есть;
        иначе остаётся `attached=False` и может выбрать должность в UI.
        """
        if not self.attached:
            return ""
        previous_node = self.player_node_id
        previous_office = self.player_office_id
        previous_label = self.office_label(previous_office)
        self.attached = False
        self.dismissed = True
        self.dismissal_count += 1
        self.player_office_id = ""
        self.player_authority = 0.0
        self._refresh_items()
        self.career_history.append(
            {
                "day": self.day,
                "kind": kind,
                "from": previous_node,
                "to": "",
                "office_from": previous_office,
                "reason": str(reason or ""),
            }
        )
        self.log.append(
            {
                "day": self.day,
                "kind": kind,
                "text": "Потеряна должность «%s»: %s."
                % (previous_label, reason or "смена роли"),
            }
        )
        if not auto_reassign:
            return "Вы оставили должность. История продолжается."
        replacement = self._replacement_office(
            previous_node, previous_office
        )
        if replacement is None:
            return "Вы потеряли должность. Вы вне службы."
        result = self.attach(previous_node, replacement["id"])
        if not result.get("ok"):
            return "Вы потеряли должность. Вы вне службы."
        self.career_history.append(
            {
                "day": self.day,
                "kind": "reassign",
                "from": previous_node,
                "to": previous_node,
                "office_from": previous_office,
                "office_to": replacement["id"],
                "reason": str(reason or ""),
            }
        )
        self.log.append(
            {
                "day": self.day,
                "kind": "career",
                "text": "Новая роль: %s в структуре %s."
                % (replacement["label"], self.node(previous_node)["name"]),
            }
        )
        return "Новая роль: %s." % replacement["label"]

    def _check_dismissal(self):
        """Проверить распад организации и смену роли (§7 №28–29).

        Имя сохранено ради совместимости с вызовами из `execute`/`end_day`,
        но терминального «увольнения» здесь больше нет: потеря должности —
        смена роли, а не `lose`.
        """
        if self.finished:
            return
        if not self.attached:
            self.collapse_days = 0
            return
        node = self.node(self.player_node_id)
        if node is None:
            self.outcome = "lose"
            self.finished = True
            self.collapsed = True
            self.log.append(
                {
                    "day": self.day,
                    "kind": "collapse",
                    "text": "Структура исчезла: организация распалась.",
                }
            )
            return
        power = float(node["stats"]["power"])
        cohesion = float(node["stats"]["cohesion"])
        strain = (
            power <= COLLAPSE_POWER or cohesion <= COLLAPSE_COHESION
        )
        total_collapse = power <= 0.0 and cohesion <= 0.0
        if strain:
            self.collapse_days += 1
        else:
            if self.collapse_days:
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "recovery",
                        "text": "Организация восстановилась выше порога "
                        "распада.",
                    }
                )
            self.collapse_days = 0
        if total_collapse or self.collapse_days >= self.collapse_grace_days:
            self.outcome = "lose"
            self.finished = True
            self.collapsed = True
            self.log.append(
                {
                    "day": self.day,
                    "kind": "collapse",
                    "text": "Организация распалась: сила или связность "
                    "пробыли ниже порога %d дн." % self.collapse_days,
                }
            )
            return
        if self.player_resources["standing"] <= DISMISSAL_STANDING:
            self._dismiss("потеря опоры и репутации")
        elif node["stats"]["legitimacy"] <= DISMISSAL_LEGITIMACY:
            self._dismiss("структура потеряла легитимность")

    def end_day(self):
        if self.finished:
            return {"ok": False, "reason": "кампания завершена"}
        events = []
        for node_id in self.node_order:
            entry = self._ai_action(node_id)
            if entry is not None:
                events.append(entry)
        daily = self.config.get("daily") or {}
        changed = []
        for key, value in (daily.get("node") or {}).items():
            for node in self.nodes.values():
                if key in node["stats"]:
                    before = node["stats"][key]
                    node["stats"][key] = _clamp(before + _as_float(value))
                    delta = node["stats"][key] - before
                    if abs(delta) > 1e-9:
                        changed.append(
                            (
                                "%s · %s"
                                % (node["name"], self.stat_label(key)),
                                delta,
                            )
                        )
        if daily.get("player"):
            changed.extend(self._apply_player_map(daily.get("player")))
        changed.extend(self._advance_conditions())
        self.day += 1
        self.actions_left = self.actions_per_day
        if self.infinite:
            # Бесконечная рамка (вопрос §7 №30): прохождение сюжетного
            # горизонта больше не даёт win/lose. Сценарий продолжается,
            # пока герой жив и организация не распалась.
            if self.day > self.days and not self.horizon_passed:
                self.horizon_passed = True
                self.log.append(
                    {
                        "day": self.day,
                        "kind": "horizon",
                        "text": "Сюжетный горизонт пройден; история "
                        "продолжается.",
                    }
                )
        elif self.day > self.days and self.outcome is None:
            # Легаси-режим для старых конечных сюжетов: явный
            # `infinite: false` в конфиге сохраняет прежний финал.
            self.outcome = (
                "win" if self.player_resources["standing"] >= 0.35 else "lose"
            )
            self.finished = True
        self._check_dismissal()
        summary = "Мир сделал ход: %d событий." % len(events)
        result = {
            "ok": True,
            "day": self.day,
            "text": summary,
            "events": events,
            "changes": self._merge_changes(changed),
        }
        self.last_result = {
            "ok": True,
            "action": "end_day",
            "action_label": "Завершение дня",
            "target": "",
            "target_label": "",
            "outcome": "day",
            "text": summary,
            "changes": result["changes"],
            "day": self.day,
        }
        self.log.append({"day": self.day, "kind": "day", "text": summary})
        return result

    def advance_days(self, days, max_days=None):
        """Продвинуть мир на несколько дней для фона/оффлайна (§7 №31).

        Останавливается на первом терминальном исходе или ошибке. Возвращает
        список результатов `end_day()`; ограничение `max_days` защищает от
        случайного огромного догона.
        """
        try:
            limit = max(0, int(days))
        except (TypeError, ValueError):
            limit = 0
        if max_days is not None:
            limit = min(limit, max(0, int(max_days)))
        results = []
        for _ in range(limit):
            if self.finished:
                break
            result = self.end_day()
            if not result.get("ok"):
                break
            results.append(result)
            if self.finished:
                break
        return results

    def world_outcome(self):
        return {
            "outcome": self.outcome,
            "finished": self.finished,
            "day": self.day,
            "standing": self.player_resources["standing"],
            "health": self.player_health,
            "sickness": self.player_sickness,
            "alive": self.player_alive,
            "infinite": bool(self.infinite),
            "horizon_passed": bool(self.horizon_passed),
            "ending": self.ending,
            "dismissed": bool(self.dismissed),
            "dismissal_count": int(self.dismissal_count),
            "collapsed": bool(self.collapsed),
            "collapse_days": int(self.collapse_days),
            "organization": self.organization_status(),
        }

    def to_dict(self):
        return {
            "world_id": self.config.get("id"),
            "seed": self.seed,
            "day": self.day,
            "days": self.days,
            "actions_left": self.actions_left,
            "action_count": self.action_count,
            "profile": dict(self.profile),
            "player": {
                "node_id": self.player_node_id,
                "office_id": self.player_office_id,
                "authority": self.player_authority,
                "resources": dict(self.player_resources),
                "career_history": list(self.career_history),
                "items": list(self.player_item_ids),
                "health": float(self.player_health),
                "sickness": float(self.player_sickness),
                "alive": bool(self.player_alive),
            },
            "characters": {
                character_id: {
                    "affinity": character["affinity"],
                    "trust": character["trust"],
                    "health": float(character["health"]),
                    "sickness": float(character["sickness"]),
                    "alive": bool(character["alive"]),
                }
                for character_id, character in self.characters.items()
            },
            "nodes": {
                node_id: {
                    "stats": dict(node["stats"]),
                    "relations": dict(node["relations"]),
                }
                for node_id, node in self.nodes.items()
            },
            "cooldowns": dict(self.cooldowns),
            "used_actions": list(self.used_actions),
            "log": list(self.log),
            "last_result": self.last_result,
            "outcome": self.outcome,
            "finished": self.finished,
            "attached": self.attached,
            "infinite": bool(self.infinite),
            "horizon_passed": bool(self.horizon_passed),
            "ending": self.ending,
            "dismissed": bool(self.dismissed),
            "dismissal_count": int(self.dismissal_count),
            "collapsed": bool(self.collapsed),
            "collapse_days": int(self.collapse_days),
        }

    def load_snapshot(self, snapshot):
        if not snapshot:
            return
        self.seed = _as_int(snapshot.get("seed"), self.seed)
        self.day = max(1, _as_int(snapshot.get("day"), 1))
        self.days = max(1, _as_int(snapshot.get("days"), self.days))
        self.actions_left = _as_int(
            snapshot.get("actions_left"), self.actions_per_day
        )
        self.action_count = _as_int(snapshot.get("action_count"), 0)
        if snapshot.get("profile"):
            self.profile = normalize_profile(snapshot["profile"])
        player = snapshot.get("player") or {}
        self.player_node_id = _text(player.get("node_id"))
        self.player_office_id = _text(player.get("office_id"))
        self.player_authority = _as_float(player.get("authority"), 0.0)
        if "health" in player:
            self.player_health = _clamp(
                _as_float(player.get("health"), HEALTH_MAX),
                0.0,
                HEALTH_MAX,
            )
        if "sickness" in player:
            self.player_sickness = _clamp(
                _as_float(player.get("sickness"), 0.0),
                0.0,
                SICKNESS_MAX,
            )
        if "alive" in player:
            self.player_alive = bool(player.get("alive"))
        else:
            self.player_alive = self.player_health > 0.0
        for key, value in (player.get("resources") or {}).items():
            if key in self.player_resources:
                self.player_resources[key] = _clamp(value)
        self.career_history = list(player.get("career_history") or [])
        if "items" in player:
            self.player_item_ids = [
                str(item_id)
                for item_id in (player.get("items") or ())
                if str(item_id) in self.item_catalog
            ]
        for character_id, saved in (snapshot.get("characters") or {}).items():
            character = self.characters.get(character_id)
            if character is None:
                continue
            character["affinity"] = _clamp(
                saved.get("affinity", character["affinity"]), -1.0, 1.0
            )
            character["trust"] = _clamp(
                saved.get("trust", character["trust"]), -1.0, 1.0
            )
            if "health" in saved:
                character["health"] = _clamp(
                    _as_float(saved.get("health"), HEALTH_MAX),
                    0.0,
                    HEALTH_MAX,
                )
            if "sickness" in saved:
                character["sickness"] = _clamp(
                    _as_float(saved.get("sickness"), 0.0),
                    0.0,
                    SICKNESS_MAX,
                )
            if "alive" in saved:
                character["alive"] = bool(saved.get("alive"))
            else:
                character["alive"] = character["health"] > 0.0
        for node_id, saved in (snapshot.get("nodes") or {}).items():
            node = self.nodes.get(node_id)
            if node is None:
                continue
            for key, value in (saved.get("stats") or {}).items():
                if key in node["stats"]:
                    node["stats"][key] = _clamp(value)
            for other_id, value in (saved.get("relations") or {}).items():
                if other_id in self.nodes:
                    node["relations"][other_id] = _clamp(value, -1.0, 1.0)
        self.cooldowns = {
            str(key): _as_int(value)
            for key, value in (snapshot.get("cooldowns") or {}).items()
        }
        self.used_actions = list(snapshot.get("used_actions") or [])
        self.log = list(snapshot.get("log") or [])
        self.last_result = snapshot.get("last_result")
        self.outcome = snapshot.get("outcome")
        self.finished = bool(snapshot.get("finished", False))
        self.infinite = bool(snapshot.get("infinite", self.infinite))
        self.horizon_passed = bool(
            snapshot.get("horizon_passed", self.horizon_passed)
        )
        self.ending = snapshot.get("ending", self.ending)
        self.dismissed = bool(snapshot.get("dismissed", self.dismissed))
        self.dismissal_count = _as_int(
            snapshot.get("dismissal_count"), self.dismissal_count
        )
        self.collapsed = bool(snapshot.get("collapsed", self.collapsed))
        self.collapse_days = max(
            0, _as_int(snapshot.get("collapse_days"), self.collapse_days)
        )
        self.attached = bool(
            snapshot.get("attached")
            or (self.player_node_id and self.player_office_id)
        )
        if "items" not in player and self.attached:
            self._refresh_items()

    def sorted_nodes(self):
        return [self.nodes[node_id] for node_id in self.node_order]


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
    "load_biography",
    "load_world",
    "normalize_profile",
    "office_profile_status",
    "validate_world",
]
