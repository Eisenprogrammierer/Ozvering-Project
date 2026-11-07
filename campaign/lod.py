"""LOD кампании: детальность автономных узлов и стоимость тика.

Закрывает §7.7 №39–40.

Кампания — не арена: её автоматы действуют не каждый кадр, а по слотам
дня. Но при сотнях узлов даже один проход `_run_node_actions()` за тик
дорог. Модуль задаёт три уровня детальности (LOD):

* **LOD0** — узел героя, его прямые соседи и (по умолчанию) подчинённые:
  полный ИИ каждый день;
* **LOD1** — близкая периферия: ИИ раз в `intervals[1]` дней;
* **LOD2** — дальняя периферия: редкий агрегированный ход раз в
  `intervals[2]` дней.

Расстояние считается по иерархии `parent`/`children` (и явным `links`),
а не по текущим отношениям: иначе LOD менялся бы от каждого контакта и
ломал детерминизм расписания. Слот узла уже детерминирован
(`WorldEngine._node_slot`), здесь добавляется детерминированное смещение
по id, чтобы периферия не ходила одной пачкой.

По умолчанию LOD выключен: старые миры и сейвы сохраняют поведение.
Включается блоком `lod` в конфиге мира:

```json
{"enabled": true, "radii": [1, 3], "intervals": [1, 4, 12],
 "player_children_always_lod0": true}
```
"""

import hashlib

MAX_TIERS = 3
DEFAULT_RADII = (1, 3)
DEFAULT_INTERVALS = (1, 1, 1)
DEFAULT_LOD = {
    "enabled": False,
    "radii": DEFAULT_RADII,
    "intervals": DEFAULT_INTERVALS,
    "player_children_always_lod0": True,
}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _pair(value, default):
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return (_as_int(value[0], default[0]), _as_int(value[1], default[1]))
    return default


def _triple(value, default):
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return (
            max(1, _as_int(value[0], default[0])),
            max(1, _as_int(value[1], default[1])),
            max(1, _as_int(value[2], default[2])),
        )
    return default


def lod_config(raw):
    """Нормализовать блок `lod`; выключенный/пустой блок безопасен."""
    raw = raw if isinstance(raw, dict) else {}
    config = dict(DEFAULT_LOD)
    config["enabled"] = _as_bool(raw.get("enabled"), False)
    config["radii"] = _pair(raw.get("radii"), DEFAULT_RADII)
    config["intervals"] = _triple(raw.get("intervals"), DEFAULT_INTERVALS)
    config["player_children_always_lod0"] = _as_bool(
        raw.get("player_children_always_lod0"), True
    )
    return config


def _adjacency(nodes):
    """Граф `parent`/`children` плюс явные `links` (без отношений)."""
    adjacency = {node_id: set() for node_id in nodes}
    for node_id, node in nodes.items():
        parent = (node or {}).get("parent")
        if parent in adjacency:
            adjacency[node_id].add(parent)
            adjacency[parent].add(node_id)
        for child in (node or {}).get("children") or ():
            if child in adjacency:
                adjacency[node_id].add(child)
                adjacency[child].add(node_id)
        for linked in (node or {}).get("links") or ():
            if linked in adjacency:
                adjacency[node_id].add(linked)
                adjacency[linked].add(node_id)
    return adjacency


def node_distances(nodes, root_id):
    """Кратчайшие расстояния по иерархии от узла героя.

    Недостижимые узлы получают `len(nodes) + 1`: они автоматически
    попадают в дальний LOD, но не теряются из симуляции.
    """
    adjacency = _adjacency(nodes)
    root_id = str(root_id or "")
    distances = {node_id: len(nodes) + 1 for node_id in adjacency}
    if root_id not in adjacency:
        return distances
    distances[root_id] = 0
    frontier = [root_id]
    while frontier:
        current = frontier.pop(0)
        for neighbor in adjacency.get(current, ()):
            if distances.get(neighbor, len(nodes) + 1) > (
                distances[current] + 1
            ):
                distances[neighbor] = distances[current] + 1
                frontier.append(neighbor)
    return distances


def tier_for_distance(distance, radii=DEFAULT_RADII):
    first, second = radii
    if distance <= first:
        return 0
    if distance <= second:
        return 1
    return 2


def _stable_offset(node_id, interval):
    if interval <= 1:
        return 0
    digest = hashlib.sha256(str(node_id).encode("utf-8")).hexdigest()
    return int(digest, 16) % interval


def due_on_day(node_id, interval, day):
    """Детерминированное расписание: узел ходит раз в `interval` дней."""
    interval = max(1, _as_int(interval, 1))
    if interval <= 1:
        return True
    return max(0, _as_int(day, 0)) % interval == _stable_offset(
        node_id, interval
    )


def _descendants(nodes, root_id):
    result = set()
    stack = [str(root_id or "")]
    root_id = stack[0]
    while stack:
        current = stack.pop()
        node = nodes.get(current) or {}
        for child in node.get("children") or ():
            if child in nodes and child not in result:
                result.add(child)
                stack.append(child)
    result.discard(root_id)
    return result


class CampaignLod:
    """Детерминированный LOD-профиль узлов и расписание их ходов."""

    def __init__(self, nodes, root_id, config=None):
        self.nodes = nodes or {}
        self.root_id = str(root_id or "")
        self.config = lod_config(config)
        self.distances = node_distances(self.nodes, self.root_id)
        self.children = (
            _descendants(self.nodes, self.root_id)
            if self.config["player_children_always_lod0"]
            else set()
        )
        self.tiers = {
            node_id: self._tier(node_id, distance)
            for node_id, distance in self.distances.items()
        }

    def _tier(self, node_id, distance):
        if not self.config["enabled"]:
            return 0
        if node_id == self.root_id or node_id in self.children:
            return 0
        return tier_for_distance(distance, self.config["radii"])

    def tier(self, node_id):
        return self.tiers.get(str(node_id or ""), 2)

    def interval(self, node_id):
        tier = self.tier(node_id)
        return self.config["intervals"][tier]

    def due(self, node_id, day):
        if not self.config["enabled"]:
            return True
        return due_on_day(node_id, self.interval(node_id), day)

    def report(self, day=None):
        counts = {0: 0, 1: 0, 2: 0}
        due = {0: 0, 1: 0, 2: 0}
        for node_id, tier in self.tiers.items():
            counts[tier] += 1
            if day is None or self.due(node_id, day):
                due[tier] += 1
        return {
            "enabled": self.config["enabled"],
            "root": self.root_id,
            "radii": list(self.config["radii"]),
            "intervals": list(self.config["intervals"]),
            "tiers": {str(tier): counts[tier] for tier in counts},
            "due": {str(tier): due[tier] for tier in due},
            "nodes": dict(self.tiers),
        }


__all__ = [
    "CampaignLod",
    "DEFAULT_INTERVALS",
    "DEFAULT_LOD",
    "DEFAULT_RADII",
    "MAX_TIERS",
    "due_on_day",
    "lod_config",
    "node_distances",
    "tier_for_distance",
]
