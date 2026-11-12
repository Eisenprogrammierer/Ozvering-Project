"""Сетевой слой кампании автоматов: органы как связанные узлы.

Фракция и её органы описываются одной и той же идеей: у узла есть
целостность и связи с другими узлами. Поэтому органы — не декоративная
вертикаль подчинения, а самоподобная сеть:

* **связи** (links) — данные задают соседей органа; связь двусторонняя,
  а не «родитель → ребёнок»;
* **вниз** (downscale) — состояние фракции задаёт цель для целостности
  каждого узла, но с меньшей амплитудой;
* **отклик** (upscale) — изменение узла возвращается во фракцию
  контекстным импульсом, а производные активы читают целостность сети;
* **работы** — сила работы зависит от целостности исполнившего органа;
  успех укрепляет узел, провал и чужая атака ослабляют его;
* **взаимодействия** — данные ``organ_interactions`` позволяют игроку
  усиливать, реформировать, чистить или снабжать конкретный узел.

Модуль не импортирует ``campaign.automata`` и не знает про интерфейс:
он работает с любым объектом фракции, у которого есть ``asset``,
``add_asset``, ``bump_context`` и ``dissolved``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, List, Mapping

from .defaults import default_dict, default_list, default_section


_ORGAN_KINDS = default_dict("organ_kinds")
ORGAN_KIND_ASSETS = {
    str(kind): str(config.get("asset") or "cohesion")
    for kind, config in _ORGAN_KINDS.items()
}
"""Какой актив фракции является «проекцией» органа данного типа."""

ORGAN_KIND_WEIGHTS = {
    str(kind): float(config.get("weight", 1.0))
    for kind, config in _ORGAN_KINDS.items()
}
ORGAN_WEIGHT_DEFAULT = ORGAN_KIND_WEIGHTS["support"]

ORGAN_MODEL_DEFAULTS = default_dict("organ_model")
DEFAULT_ORGAN_INTERACTIONS = default_list("organ_interactions")
ORGAN_STATUS_THRESHOLDS = default_dict("organ_status_thresholds")
ORGAN_TARGET_DEFAULTS = default_dict("organ_target")
ORGAN_DEFAULT_INTEGRITY = float(default_section("organ_default_integrity"))
ORGAN_MIN_WEIGHT = float(default_section("organ_min_weight"))

STATUS_ACTIVE = "в строю"
STATUS_STRAINED = "напряжение"
STATUS_RESTORING = "восстановление"
STATUS_DISBANDED = "расформирован"


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


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def organ_status(integrity):
    """Состояние органа по его целостности."""
    value = _clamp(integrity)
    if value >= float(ORGAN_STATUS_THRESHOLDS["active"]):
        return STATUS_ACTIVE
    if value >= float(ORGAN_STATUS_THRESHOLDS["strained"]):
        return STATUS_STRAINED
    if value > float(ORGAN_STATUS_THRESHOLDS["restoring"]):
        return STATUS_RESTORING
    return STATUS_DISBANDED


def organ_asset_key(kind):
    """Актив фракции, на который проецируется орган."""
    return ORGAN_KIND_ASSETS.get(str(kind or ""), ORGAN_KIND_ASSETS["support"])


def organ_weight(kind, explicit=None):
    return max(
        ORGAN_MIN_WEIGHT,
        _number(
            explicit,
            ORGAN_KIND_WEIGHTS.get(
                str(kind or ""), ORGAN_WEIGHT_DEFAULT
            ),
        ),
    )


def organ_links(organs):
    """Двусторонняя карта связей сети органов.

    Явный список ``links`` — основной источник. Старое поле ``parent_id``
    читается как одна дополнительная связь, чтобы открыть пресеты,
    созданные до перехода на сетку. Возвращаются отсортированные соседи,
    поэтому обход и отрисовка детерминированы.
    """
    organs = list(organs or ())
    by_id = {str(getattr(item, "id", "") or ""): item for item in organs}
    links = {organ_id: set() for organ_id in by_id if organ_id}
    for organ in organs:
        organ_id = str(getattr(organ, "id", "") or "")
        if not organ_id:
            continue
        for linked in getattr(organ, "links", ()) or ():
            linked = str(linked or "")
            if not linked or linked == organ_id or linked not in by_id:
                continue
            links[organ_id].add(linked)
            links[linked].add(organ_id)
        parent_id = str(getattr(organ, "parent_id", "") or "")
        if parent_id and parent_id != organ_id and parent_id in by_id:
            links[organ_id].add(parent_id)
            links[parent_id].add(organ_id)
    return {key: sorted(value) for key, value in links.items()}


def organ_degrees(organs):
    """Степень каждого узла сети (число соседей)."""
    return {
        key: len(value) for key, value in organ_links(organs).items()
    }


def network_density(organs):
    """Доля существующих связей от всех возможных (0..1)."""
    links = organ_links(organs)
    count = len(links)
    if count <= 1:
        return 0.0
    edges = sum(len(value) for value in links.values()) / 2.0
    return _clamp(edges / float(count * (count - 1) / 2.0))


def validate_organ_network(organs):
    """Проверить ссылки сети и вернуть список проблем.

    Сеть не обязана быть деревом: допускаются циклы, несколько связей и
    изолированные узлы. Ошибка — только ссылка на неизвестный узел или
    связь узла с самим собой.
    """
    organs = list(organs or ())
    by_id = {str(getattr(item, "id", "") or ""): item for item in organs}
    problems = []
    for organ in organs:
        organ_id = str(getattr(organ, "id", "") or "")
        if not organ_id:
            problems.append("орган без id")
            continue
        for linked in getattr(organ, "links", ()) or ():
            linked = str(linked or "")
            if not linked:
                continue
            if linked == organ_id:
                problems.append(
                    "орган %s связан сам с собой" % organ_id
                )
            elif linked not in by_id:
                problems.append(
                    "орган %s: неизвестная связь %s"
                    % (organ_id, linked)
                )
        parent_id = str(getattr(organ, "parent_id", "") or "")
        if parent_id:
            if parent_id == organ_id:
                problems.append(
                    "орган %s ссылается сам на себя" % organ_id
                )
            elif parent_id not in by_id:
                problems.append(
                    "орган %s: неизвестная связь %s"
                    % (organ_id, parent_id)
                )
    return problems


def organ_network_distances(organs, root_id=None):
    """Кратчайшее расстояние по связям сети от выбранного узла.

    Это метрика связности для диагностики, а не уровень подчинения.
    Недостижимые узлы получают ``-1``.
    """
    organs = list(organs or ())
    links = organ_links(organs)
    if not links:
        return {}
    start = str(root_id or next(iter(links)))
    if start not in links:
        start = next(iter(links))
    distances = {key: -1 for key in links}
    distances[start] = 0
    queue = [start]
    while queue:
        current = queue.pop(0)
        for neighbor in links.get(current, ()):
            if distances.get(neighbor, -1) == -1:
                distances[neighbor] = distances[current] + 1
                queue.append(neighbor)
    return distances


def validate_organ_hierarchy(organs):
    """Устаревшее имя; сеть проверяется :func:`validate_organ_network`."""
    return validate_organ_network(organs)


def organ_depths(organs):
    """Устаревшее имя; расстояние по связям, не уровень иерархии."""
    return organ_network_distances(organs)


def organ_composite(
    organs,
    root_id="faction",
    *,
    force_of=None,
    energy_of=None,
    root_max_depth=None,
):
    """Построить `CompositeAutomaton`-представление сети органов.

    Это диагностический слой (WORLD_CORE_MODEL §2.7): `OrganRuntime`
    остаётся источником истины и хранит взаимодействия/перезарядки, а
    составной автомат даёт агрегаты `F/E/S` по сети и распределение
    работы между узлами. Узлы сети висят под корнем плоско: связи
    ``links`` остаются в данных, но не превращаются в вертикаль власти.

    Отображение по умолчанию:

    * `F` органа — его `integrity`, умноженная на `weight`;
    * `E` органа — `readiness_scale(organ)`, то есть готовность проводить
      работу (пол не обнуляет расформированный орган);
    * `H` — та же `integrity`, чтобы агрегат здоровья читался как
      взвешенная целостность.

    `force_of`/`energy_of` позволяют подставить другую проекцию, не меняя
    модуль. Сеть может содержать циклы и кластеры: все узлы всё равно
    строятся плоским слоем под корнем, а связи остаются в данных органов.
    """
    organs = list(organs or ())
    if not organs:
        return None
    from core41 import (
        HEALTH_MAX,
        UNIT_SCALE,
        CompositeAutomaton,
    )

    force_of = force_of or (lambda organ: _clamp(organ.integrity))
    energy_of = energy_of or (
        lambda organ: _clamp(readiness_scale(organ))
    )
    root = CompositeAutomaton(
        id=str(root_id or "faction"),
        force=0.0,
        max_force=0.0,
        energy=0.0,
        max_energy=0.0,
        health=0.0,
        max_health=HEALTH_MAX,
    )
    if root_max_depth is not None:
        root.max_depth = max(0, int(_number(root_max_depth, root.max_depth)))
    nodes = {}
    ordered = []
    for organ in organs:
        organ_id = str(getattr(organ, "id", "") or "")
        if not organ_id or organ_id in nodes:
            continue
        weight = max(1e-9, _number(getattr(organ, "weight", 1.0), 1.0))
        integrity = _clamp(force_of(organ))
        readiness = _clamp(energy_of(organ))
        node = CompositeAutomaton(
            id=organ_id,
            force=integrity * UNIT_SCALE * weight,
            max_force=UNIT_SCALE * weight,
            energy=readiness * UNIT_SCALE * weight,
            max_energy=UNIT_SCALE * weight,
            health=integrity * HEALTH_MAX,
            max_health=HEALTH_MAX,
        )
        node.state["organ_kind"] = str(getattr(organ, "kind", "") or "")
        nodes[organ_id] = node
        ordered.append((organ, node))
    ordered.sort(key=lambda item: item[1].id)
    for _organ, node in ordered:
        try:
            root.add_child(node)
        except ValueError:
            if getattr(node, "_composite_parent", None) is not None:
                node._composite_parent.remove_child(node.id)
            try:
                root.add_child(node)
            except ValueError:
                continue
    return root


@dataclass
class OrganRuntime:
    """Состояние одного органа внутри фракции."""

    id: str
    name: str
    kind: str = "support"
    description: str = ""
    automaton_id: str = ""
    parent_id: str = ""
    subfaction_id: str = ""
    links: List[str] = field(default_factory=list)
    action_ids: List[str] = field(default_factory=list)
    integrity: float = ORGAN_DEFAULT_INTEGRITY
    weight: float = 1.0
    interactions: List[dict] = field(default_factory=list)
    interaction_cooldowns: Dict[str, int] = field(default_factory=dict)
    used_turn: int = -1

    @classmethod
    def from_record(cls, record, interactions=None):
        record = _as_mapping(record)
        organ_id = str(record.get("id") or "").strip()
        if not organ_id:
            return None
        configured = list(
            interactions
            if interactions is not None
            else record.get("organ_interactions") or ()
        )
        if not configured:
            configured = DEFAULT_ORGAN_INTERACTIONS
        return cls(
            id=organ_id,
            name=str(record.get("name") or organ_id),
            kind=str(record.get("kind") or "support"),
            description=str(record.get("description") or ""),
            automaton_id=str(record.get("automaton_id") or ""),
            parent_id=str(record.get("parent_id") or ""),
            subfaction_id=str(record.get("subfaction_id") or ""),
            links=[
                str(item)
                for item in (record.get("links") or ())
                if str(item or "").strip()
            ],
            action_ids=[
                str(item) for item in (record.get("action_ids") or ())
            ],
            integrity=_clamp(
                _number(record.get("integrity"), ORGAN_DEFAULT_INTEGRITY)
            ),
            weight=organ_weight(
                record.get("kind"), record.get("weight")
            ),
            interactions=[
                dict(item)
                for item in configured
                if isinstance(item, Mapping) and item.get("id")
            ],
            interaction_cooldowns={
                str(key): int(_number(value))
                for key, value in _as_mapping(
                    record.get("interaction_cooldowns")
                ).items()
            },
            used_turn=int(_number(record.get("used_turn"), -1)),
        )

    def asset_key(self):
        return organ_asset_key(self.kind)

    def status(self):
        return organ_status(self.integrity)

    def interaction(self, interaction_id):
        for item in self.interactions:
            if str(item.get("id")) == str(interaction_id):
                return item
        return None

    def cooldown_left(self, interaction, turn=0):
        cooldown = int(_number(interaction.get("cooldown"), 0))
        last = self.interaction_cooldowns.get(str(interaction.get("id")))
        if cooldown <= 0 or last is None:
            return 0
        return max(0, cooldown + 1 - (int(turn) - int(last)))

    def snapshot(self):
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "automaton_id": self.automaton_id,
            "parent_id": self.parent_id,
            "subfaction_id": self.subfaction_id,
            "links": list(self.links),
            "action_ids": list(self.action_ids),
            "integrity": round(_clamp(self.integrity), 6),
            "status": self.status(),
            "weight": round(self.weight, 6),
            "interaction_cooldowns": {
                key: int(value)
                for key, value in self.interaction_cooldowns.items()
            },
            "used_turn": int(self.used_turn),
        }


def faction_pressure(faction, keys=None):
    """Среднее состояние фракции по опорным активам."""
    keys = keys or ORGAN_TARGET_DEFAULTS["pressure_assets"]
    values = [_clamp(faction.asset(key, 0.5)) for key in keys]
    if not values:
        return 0.5
    return sum(values) / float(len(values))


def organ_target(faction, kind, downscale=None):
    """Куда стремится целостность органа: уменьшенная копия фракции."""
    downscale = _number(
        downscale, ORGAN_MODEL_DEFAULTS["organ_downscale"]
    )
    specific = _clamp(faction.asset(organ_asset_key(kind), 0.5))
    pressure = faction_pressure(faction)
    profile_weight = _number(
        ORGAN_TARGET_DEFAULTS.get("profile_weight"), 0.0
    )
    pressure_weight = _number(
        ORGAN_TARGET_DEFAULTS.get("pressure_weight"), 0.0
    )
    target = 0.5 + downscale * (
        profile_weight * (specific - 0.5)
        + pressure_weight * (pressure - 0.5)
    )
    return _clamp(target)


def readiness_scale(organ, model=None):
    """Насколько сильно орган проводит работу фракции.

    Даже расформированный орган не обнуляет эффект полностью: иначе
    игрок мог бы «выключить» половину кампании. Пол задаётся моделью.
    """
    if organ is None:
        return 1.0
    floor = _number(
        _as_mapping(model).get("organ_effect_floor"),
        ORGAN_MODEL_DEFAULTS["organ_effect_floor"],
    )
    floor = _clamp(floor, 0.0, 1.0)
    return floor + (1.0 - floor) * _clamp(organ.integrity)


def tick_organs(faction, organs, model=None):
    """Один тик самоподобия для органов одной фракции.

    Возвращает список ``(organ, delta)``, чтобы вызывающий код мог
    записать изменения в журнал или проверить их в тестах.
    """
    organs = list(organs or ())
    if not organs:
        return []
    model = _as_mapping(model)
    recovery = _number(
        model.get("organ_recovery"),
        ORGAN_MODEL_DEFAULTS["organ_recovery"],
    )
    upscale = _number(
        model.get("organ_upscale"), ORGAN_MODEL_DEFAULTS["organ_upscale"]
    )
    dissolve_rate = _number(
        model.get("organ_dissolve_rate"),
        ORGAN_MODEL_DEFAULTS["organ_dissolve_rate"],
    )
    deltas = []
    for organ in organs:
        if getattr(faction, "dissolved", False):
            target = 0.0
            rate = min(1.0, recovery + dissolve_rate)
        else:
            target = organ_target(
                faction,
                organ.kind,
                model.get("organ_downscale"),
            )
            rate = recovery
        before = organ.integrity
        organ.integrity = _clamp(before + (target - before) * rate)
        deltas.append((organ, organ.integrity - before))
    if not getattr(faction, "dissolved", False):
        bump = getattr(faction, "bump_context", None)
        for organ in organs:
            feedback = upscale * organ.weight * (organ.integrity - 0.5)
            if not feedback:
                continue
            if callable(bump):
                bump(organ.asset_key(), feedback)
            else:
                faction.add_asset(organ.asset_key(), feedback)
    return deltas


def spread_organ_effect(faction, organ, delta, model=None):
    """Передать изменение органа фракции (up-масштаб)."""
    delta = _number(delta)
    if not delta:
        return 0.0
    spread = _number(
        _as_mapping(model).get("organ_spread"),
        ORGAN_MODEL_DEFAULTS["organ_spread"],
    )
    applied = delta * spread * max(ORGAN_MIN_WEIGHT, organ.weight)
    bump = getattr(faction, "bump_context", None)
    if callable(bump):
        bump(organ.asset_key(), applied)
    else:
        faction.add_asset(organ.asset_key(), applied)
    return applied


def strengthen_organ(organ, delta):
    before = organ.integrity
    organ.integrity = _clamp(before + _number(delta))
    return organ.integrity - before


def damage_organs(faction, asset_key, amount, model=None):
    """Ослабить органы, проецирующиеся на атакованный актив.

    Если ни один орган не связан с активом напрямую, страдают все органы
    фракции: атака по общему состоянию не может быть «бесплатной».
    """
    organs = list(getattr(faction, "organs", ()) or ())
    if not organs:
        return []
    amount = abs(_number(amount))
    if amount <= 0.0:
        return []
    targets = [
        organ for organ in organs if organ.asset_key() == str(asset_key)
    ] or organs
    per_organ = amount / float(max(1, len(targets)))
    applied = []
    for organ in targets:
        before = organ.integrity
        organ.integrity = _clamp(before - per_organ)
        applied.append((organ, organ.integrity - before))
    return applied


__all__ = [
    "DEFAULT_ORGAN_INTERACTIONS",
    "ORGAN_DEFAULT_INTEGRITY",
    "ORGAN_KIND_ASSETS",
    "ORGAN_KIND_WEIGHTS",
    "ORGAN_MIN_WEIGHT",
    "ORGAN_MODEL_DEFAULTS",
    "ORGAN_STATUS_THRESHOLDS",
    "ORGAN_TARGET_DEFAULTS",
    "OrganRuntime",
    "damage_organs",
    "faction_pressure",
    "network_density",
    "organ_asset_key",
    "organ_degrees",
    "organ_depths",
    "organ_links",
    "organ_network_distances",
    "organ_status",
    "organ_target",
    "organ_weight",
    "readiness_scale",
    "spread_organ_effect",
    "strengthen_organ",
    "tick_organs",
    "validate_organ_hierarchy",
    "validate_organ_network",
]
