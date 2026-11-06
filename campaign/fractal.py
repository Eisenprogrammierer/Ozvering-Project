"""Фрактальный слой кампании автоматов: органы как уменьшенные копии.

Фракция и её органы описываются одной и той же идеей: у узла есть
целостность, он реагирует на состояние родителя и передаёт ему часть
своего изменения обратно. Поэтому органы — не декоративный список, а
самоподобные автоматы:

* **вниз** (downscale) — состояние фракции задаёт цель для целостности
  органа, но с меньшей амплитудой;
* **вверх** (upscale) — среднее состояние органов возвращается во
  фракцию небольшим потоком, поэтому слабый орган постепенно ослабляет
  свою фракцию;
* **работы** — сила работы зависит от целостности исполнившего органа;
  успех укрепляет орган, провал и чужая атака ослабляют его;
* **взаимодействия** — данные ``organ_interactions`` позволяют игроку
  усиливать, реформировать, чистить или снабжать конкретный орган.

Модуль не импортирует ``campaign.automata`` и не знает про интерфейс:
он работает с любым объектом фракции, у которого есть ``asset``,
``add_asset`` и ``dissolved``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, List, Mapping


ORGAN_KIND_ASSETS = {
    "command": "cohesion",
    "coercion": "morale",
    "intelligence": "influence",
    "information": "influence",
    "maintenance": "supply",
    "legitimacy": "legitimacy",
    "care": "morale",
    "meaning": "morale",
    "exchange": "supply",
}
"""Какой актив фракции является «проекцией» органа данного типа."""

ORGAN_KIND_WEIGHTS = {
    "command": 1.2,
    "legitimacy": 1.1,
    "coercion": 1.05,
    "intelligence": 1.0,
    "information": 1.0,
    "maintenance": 0.95,
    "care": 0.9,
    "meaning": 0.9,
    "exchange": 0.95,
}

ORGAN_MODEL_DEFAULTS = {
    "organ_downscale": 0.6,
    "organ_recovery": 0.12,
    "organ_upscale": 0.012,
    "organ_action_gain": 0.08,
    "organ_action_loss": 0.06,
    "organ_damage": 0.05,
    "organ_spread": 0.18,
    "organ_dissolve_rate": 0.05,
    "organ_effect_floor": 0.55,
}

DEFAULT_ORGAN_INTERACTIONS = [
    {
        "id": "reinforce",
        "label": "Усилить орган",
        "description": "Перебросить людей и ресурсы: целостность органа растёт.",
        "cost": {"supply": 0.04},
        "integrity": 0.12,
        "faction": {"cohesion": 0.015},
        "cooldown": 2,
    },
    {
        "id": "reform",
        "label": "Реформировать",
        "description": "Изменить порядок работы органа ценой энергии.",
        "cost": {"energy": 0.035},
        "integrity": 0.07,
        "faction": {"influence": 0.012},
        "cooldown": 3,
    },
    {
        "id": "purge",
        "label": "Провести чистку",
        "description": "Подчинить орган центру: страх растёт, целостность падает.",
        "cost": {"influence": 0.05},
        "integrity": -0.15,
        "faction": {"fear": 0.02, "legitimacy": 0.01},
        "cooldown": 3,
    },
    {
        "id": "resupply",
        "label": "Наладить снабжение",
        "description": "Влить запас в орган: целостность и мораль растут.",
        "cost": {"supply": 0.06},
        "integrity": 0.18,
        "faction": {"morale": 0.01},
        "cooldown": 4,
    },
]

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
    if value >= 0.65:
        return STATUS_ACTIVE
    if value >= 0.35:
        return STATUS_STRAINED
    if value > 0.15:
        return STATUS_RESTORING
    return STATUS_DISBANDED


def organ_asset_key(kind):
    """Актив фракции, на который проецируется орган."""
    return ORGAN_KIND_ASSETS.get(str(kind or ""), "cohesion")


def organ_weight(kind, explicit=None):
    return max(
        0.1,
        _number(explicit, ORGAN_KIND_WEIGHTS.get(str(kind or ""), 1.0)),
    )


def validate_organ_hierarchy(organs):
    """Проверить ссылки ``parent_id`` и отсутствие циклов.

    Возвращает список человекочитаемых проблем. Пустой список означает,
    что из органов можно построить корректное дерево/лес.
    """
    organs = list(organs or ())
    by_id = {str(getattr(item, "id", "") or ""): item for item in organs}
    problems = []
    for organ in organs:
        parent_id = str(getattr(organ, "parent_id", "") or "")
        if not parent_id:
            continue
        if parent_id == organ.id:
            problems.append("орган %s ссылается сам на себя" % organ.id)
            continue
        if parent_id not in by_id:
            problems.append(
                "орган %s: неизвестный parent_id=%s"
                % (organ.id, parent_id)
            )
    if problems:
        return problems

    state = {}

    def visit(organ_id, path):
        marker = state.get(organ_id)
        if marker == "done":
            return
        if marker == "visiting":
            cycle = " → ".join(path + [organ_id])
            problems.append("цикл иерархии органов: %s" % cycle)
            return
        state[organ_id] = "visiting"
        parent_id = str(getattr(by_id[organ_id], "parent_id", "") or "")
        if parent_id:
            visit(parent_id, path + [organ_id])
        state[organ_id] = "done"

    for organ_id in by_id:
        visit(organ_id, [])
        if problems:
            break
    return problems


def organ_depths(organs):
    """Глубина каждого органа от корня (у корня — 0)."""
    by_id = {str(getattr(item, "id", "") or ""): item for item in organs}
    depths = {}

    def depth(organ_id, trail=()):
        if organ_id in depths:
            return depths[organ_id]
        if organ_id in trail:
            return 0
        organ = by_id.get(organ_id)
        if organ is None:
            return 0
        parent_id = str(getattr(organ, "parent_id", "") or "")
        if not parent_id or parent_id not in by_id:
            value = 0
        else:
            value = depth(parent_id, trail + (organ_id,)) + 1
        depths[organ_id] = value
        return value

    for organ_id in by_id:
        depth(organ_id)
    return depths


def organ_composite(
    organs,
    root_id="faction",
    *,
    force_of=None,
    energy_of=None,
    root_max_depth=None,
):
    """Построить `CompositeAutomaton`-представление иерархии органов.

    Это диагностический слой (WORLD_CORE_MODEL §2.7): `OrganRuntime`
    остаётся источником истины и хранит взаимодействия/перезарядки, а
    составной автомат даёт агрегаты `F/E/S` по дереву и распределение
    работы между листьями.

    Отображение по умолчанию:

    * `F` органа — его `integrity`, умноженная на `weight`;
    * `E` органа — `readiness_scale(organ)`, то есть готовность проводить
      работу (пол не обнуляет расформированный орган);
    * `H` — та же `integrity`, чтобы агрегат здоровья читался как
      взвешенная целостность.

    `force_of`/`energy_of` позволяют подставить другую проекцию, не меняя
    модуль. Повреждённая иерархия (циклы, неизвестные родители) строится
    плоским лесом под корнем, а не роняет вызов.
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
    problems = validate_organ_hierarchy(organs)
    depths = organ_depths(organs) if not problems else {}
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
    ordered.sort(
        key=lambda item: (
            depths.get(item[1].id, 0),
            item[1].id,
        )
    )
    for organ, node in ordered:
        parent_id = "" if problems else str(
            getattr(organ, "parent_id", "") or ""
        )
        parent = nodes.get(parent_id) if parent_id else None
        target = parent if parent is not None and parent is not node else root
        try:
            target.add_child(node)
        except ValueError:
            # Повреждённая ссылка/глубина: орган остаётся в дереве, но
            # без спорного родителя.
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
    action_ids: List[str] = field(default_factory=list)
    integrity: float = 0.72
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
            action_ids=[
                str(item) for item in (record.get("action_ids") or ())
            ],
            integrity=_clamp(_number(record.get("integrity"), 0.72)),
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

    # ------------------------------------------------------------------
    # Производные значения
    # ------------------------------------------------------------------
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
    keys = keys or (
        "legitimacy",
        "cohesion",
        "morale",
        "supply",
        "influence",
    )
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
    # 60% — профильный актив органа, 40% — общее давление фракции.
    target = 0.5 + downscale * (
        0.6 * (specific - 0.5) + 0.4 * (pressure - 0.5)
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
        # Обратный поток: органы — уменьшенные копии, но и фракция
        # складывается из них. Коэффициент мал, чтобы не ломать баланс.
        for organ in organs:
            feedback = upscale * organ.weight * (organ.integrity - 0.5)
            if feedback:
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
    applied = delta * spread * max(0.1, organ.weight)
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
    "ORGAN_KIND_ASSETS",
    "ORGAN_KIND_WEIGHTS",
    "ORGAN_MODEL_DEFAULTS",
    "OrganRuntime",
    "damage_organs",
    "faction_pressure",
    "organ_asset_key",
    "organ_depths",
    "organ_status",
    "organ_target",
    "organ_weight",
    "readiness_scale",
    "spread_organ_effect",
    "strengthen_organ",
    "tick_organs",
    "validate_organ_hierarchy",
]
