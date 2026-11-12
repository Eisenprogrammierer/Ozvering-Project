"""Семантическая геометрия автоматов: метрический граф без глобальных осей.

Модуль реализует первый этап гибридной геометрии мира:

* **узлы** — автоматы (органы, подфракции, состояния), а не точки на
  абсолютной плоскости;
* **рёбра** — соседство с локальной длиной и необязательной длительностью;
* **ориентация** — циклический порядок полуребер в узле и углы поворота
  между соседними полуребрами;
* **дальние расстояния** не хранятся, а складываются по кратчайшему пути;
* **дальние направления** разворачиваются вдоль выбранного пути как
  последовательность локальных поворотов.

Главный инвариант: игровые расчёты не читают ``layout.x/y``. Координаты
остаются проекцией для редактора и отрисовки, а семантика живёт в длинах,
углах, порядке соседей и (позже) переносах базисов.

Модуль не знает о кампании, органах и событиях. Он принимает уже
нормализованные данные и отдаёт детерминированные запросы.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import heapq
import math
from typing import Dict, Iterable, List, Optional, Tuple

SCHEMA = 1
MODEL = "metric_graph"
DIMENSION = 2
COMPOSITION = "shortest_path"

TAU = math.tau
_EPSILON = 1e-9
_ROUND = 12

ANGLE_UNITS = {
    "radian": 1.0,
    "radians": 1.0,
    "rad": 1.0,
    "degree": math.pi / 180.0,
    "degrees": math.pi / 180.0,
    "deg": math.pi / 180.0,
}


class GeometryError(ValueError):
    """Ошибка данных или запроса геометрии."""


def edge_key(source, target):
    """Канонический ключ ненаправленного ребра."""
    left, right = sorted((str(source), str(target)))
    return "%s|%s" % (left, right)


def _number(value, default=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _text(value, default=""):
    text = str(value or "").strip()
    return text or default


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _normalize_signed(value, total=TAU):
    """Привести угол к диапазону (-π, π] в плоском случае."""
    if total <= 0:
        return 0.0
    value = math.fmod(value, total)
    if value <= -math.pi:
        value += total
    elif value > math.pi:
        value -= total
    return value


def _same_angle(left, right):
    return abs(_normalize_signed(left - right)) <= 1e-6


@dataclass(frozen=True)
class GeometryEdge:
    """Ненаправленное ребро метрического графа."""

    key: str
    source: str
    target: str
    length: float
    duration: float = 0.0
    kind: str = "spatial"

    def other(self, node):
        node = str(node)
        if node == self.source:
            return self.target
        if node == self.target:
            return self.source
        return ""

    def to_dict(self):
        return {
            "from": self.source,
            "to": self.target,
            "length": round(self.length, 9),
            "duration": round(self.duration, 9),
            "kind": self.kind,
        }


@dataclass(frozen=True)
class GeometryPath:
    """Канонический путь и развёрнутое вдоль него направление."""

    nodes: Tuple[str, ...] = ()
    edges: Tuple[str, ...] = ()
    length: float = 0.0
    duration: float = 0.0
    bearing: float = 0.0

    def to_dict(self):
        return {
            "nodes": list(self.nodes),
            "edges": list(self.edges),
            "length": round(self.length, 9),
            "duration": round(self.duration, 9),
            "bearing": round(self.bearing, 9),
        }


class MetricGraph:
    """Метрический граф с циклическим порядком полуребер и углами.

    Узел не имеет координат. Он хранит только порядок соседей и поворот
    от каждого полуребра к следующему. Сумма поворотов вокруг плоского
    узла равна ``2π``; отклонение сохраняется как ``curvature`` и позже
    станет источником кривизны этапа C.
    """

    def __init__(
        self,
        nodes: Iterable[str],
        edges: Iterable[GeometryEdge],
        orientation: Mapping[str, Sequence[float]],
        *,
        source: str = "declared",
    ):
        self.nodes = tuple(sorted({str(item) for item in nodes if str(item)}))
        self.source = str(source or "declared")
        self._node_set = set(self.nodes)
        self._edges: Dict[str, GeometryEdge] = {}
        self._adjacency: Dict[str, Dict[str, GeometryEdge]] = {
            node: {} for node in self.nodes
        }
        self._neighbor_order: Dict[str, List[str]] = {
            node: [] for node in self.nodes
        }
        for edge in edges:
            if edge.key in self._edges:
                raise GeometryError(
                    "повторяющееся ребро %s" % edge.key
                )
            if edge.source not in self._node_set:
                raise GeometryError(
                    "ребро %s ссылается на неизвестный узел %s"
                    % (edge.key, edge.source)
                )
            if edge.target not in self._node_set:
                raise GeometryError(
                    "ребро %s ссылается на неизвестный узел %s"
                    % (edge.key, edge.target)
                )
            self._edges[edge.key] = edge
            self._adjacency[edge.source][edge.target] = edge
            self._adjacency[edge.target][edge.source] = edge
            if edge.target not in self._neighbor_order[edge.source]:
                self._neighbor_order[edge.source].append(edge.target)
            if edge.source not in self._neighbor_order[edge.target]:
                self._neighbor_order[edge.target].append(edge.source)

        self._order: Dict[str, Tuple[str, ...]] = {}
        self._turns: Dict[str, Tuple[float, ...]] = {}
        self._index: Dict[str, Dict[str, int]] = {}
        for node in self.nodes:
            configured = orientation.get(node)
            if configured is None:
                configured = self._neighbor_order[node]
                turns = self._uniform_turns(len(configured))
            else:
                configured, turns = list(configured[0]), list(configured[1])
            if not configured:
                if turns:
                    raise GeometryError(
                        "узел %s: углы без соседей" % node
                    )
                self._order[node] = ()
                self._turns[node] = ()
                self._index[node] = {}
                continue
            if len(configured) != len(turns):
                raise GeometryError(
                    "узел %s: число соседей и поворотов не совпадает"
                    % node
                )
            if len(set(configured)) != len(configured):
                raise GeometryError(
                    "узел %s: сосед указан в ориентации дважды" % node
                )
            incident = set(self._adjacency[node])
            if set(configured) != incident:
                missing = sorted(incident - set(configured))
                extra = sorted(set(configured) - incident)
                details = []
                if missing:
                    details.append("нет углов для: %s" % ", ".join(missing))
                if extra:
                    details.append("лишние соседи: %s" % ", ".join(extra))
                raise GeometryError(
                    "узел %s: %s" % (node, "; ".join(details))
                )
            total = sum(turns)
            if total <= 0:
                raise GeometryError(
                    "узел %s: сумма поворотов должна быть > 0" % node
                )
            if not _same_angle(total, TAU):
                raise GeometryError(
                    "узел %s: сумма поворотов %.6f, ожидалась 2π"
                    % (node, total)
                )
            self._order[node] = tuple(configured)
            self._turns[node] = tuple(turns)
            self._index[node] = {
                neighbor: index
                for index, neighbor in enumerate(configured)
            }

    @staticmethod
    def _uniform_turns(count):
        if count <= 0:
            return []
        step = TAU / float(count)
        return [step for _ in range(count)]

    # ------------------------------------------------------------------
    # Сборка из данных
    # ------------------------------------------------------------------

    @classmethod
    def from_links(cls, nodes, links, *, default_length=1.0, source="derived"):
        """Собрать граф из сетевой карты ``{узел: [соседи]}``.

        Топология берётся из связей, длина по умолчанию — ``default_length``,
        ориентация — равные углы в порядке соседей. Это совместимый режим
        для старых данных: он не требует геометрии в JSON, но и не
        описывает реальные расстояния.
        """
        return cls.from_record(
            {"default_length": default_length},
            nodes=nodes,
            links=links,
            source=source,
        )

    @classmethod
    def from_record(
        cls,
        record,
        *,
        nodes=None,
        links=None,
        source="declared",
    ):
        """Прочитать геометрию из JSON-объекта.

        ``nodes`` — полный список узлов (например, органов фракции).
        ``links`` — карта соседства; используется, если ``edges`` не заданы.
        Неизвестные ключи игнорируются, но ошибки в известных — громкие.
        """
        record = _as_mapping(record)
        schema = record.get("schema", SCHEMA)
        try:
            schema_number = int(schema)
        except (TypeError, ValueError):
            raise GeometryError("схема геометрии: ожидалось число 1")
        if schema_number != SCHEMA:
            raise GeometryError(
                "схема геометрии %r, ожидалась %d"
                % (schema, SCHEMA)
            )
        model = _text(record.get("model"), MODEL)
        if model != MODEL:
            raise GeometryError(
                "модель геометрии %r не поддерживается" % model
            )
        dimension = record.get("dimension", DIMENSION)
        try:
            dimension_number = int(dimension)
        except (TypeError, ValueError):
            raise GeometryError("размерность геометрии должна быть числом")
        if dimension_number != DIMENSION:
            raise GeometryError(
                "размерность %r не поддерживается: этап 1 — только 2D"
                % dimension
            )
        composition = _text(
            record.get("composition"), COMPOSITION
        )
        if composition != COMPOSITION:
            raise GeometryError(
                "композиция %r не поддерживается" % composition
            )
        unit_text = _text(record.get("angle_unit"), "radian").lower()
        if unit_text not in ANGLE_UNITS:
            raise GeometryError(
                "единица угла %r не поддерживается" % unit_text
            )
        unit = ANGLE_UNITS[unit_text]

        default_length = _number(
            record.get("default_length"), 1.0
        )
        if default_length is None or default_length <= 0:
            raise GeometryError("default_length должен быть > 0")
        default_duration = _number(record.get("default_duration"), 0.0)
        if default_duration is None or default_duration < 0:
            raise GeometryError("default_duration должен быть >= 0")

        explicit_edges = record.get("edges")
        lengths = record.get("lengths")
        durations = record.get("durations")
        if explicit_edges is not None and lengths is not None:
            raise GeometryError(
                "нельзя задавать одновременно edges и lengths"
            )
        if lengths is not None and not isinstance(lengths, Mapping):
            raise GeometryError("lengths должен быть объектом")
        if durations is not None and not isinstance(durations, Mapping):
            raise GeometryError("durations должен быть объектом")

        node_ids = None
        if nodes is not None:
            node_ids = sorted(
                {str(item) for item in nodes if str(item)}
            )
        link_map = {
            str(key): [str(item) for item in value]
            for key, value in _as_mapping(links).items()
        }
        if node_ids is None and link_map:
            node_ids = sorted(link_map)
        if node_ids is None:
            node_ids = []
        known_nodes = (
            set(node_ids)
            if (nodes is not None or link_map)
            else None
        )

        edge_records = []
        if explicit_edges is not None:
            if not isinstance(explicit_edges, Sequence) or isinstance(
                explicit_edges, (str, bytes)
            ):
                raise GeometryError("edges должен быть списком")
            for index, item in enumerate(explicit_edges):
                item = _as_mapping(item)
                edge_source = _text(
                    item.get("from") or item.get("source")
                )
                edge_target = _text(
                    item.get("to") or item.get("target")
                )
                if not edge_source or not edge_target:
                    raise GeometryError(
                        "edges[%d]: нужны from и to" % index
                    )
                edge_records.append(
                    (
                        edge_source,
                        edge_target,
                        _number(item.get("length"), default_length),
                        _number(item.get("duration"), default_duration),
                        _text(item.get("kind"), "spatial"),
                    )
                )
        else:
            pairs = []
            seen_pairs = set()
            for node in sorted(link_map):
                for neighbor in link_map[node]:
                    key = edge_key(node, neighbor)
                    if key in seen_pairs:
                        continue
                    seen_pairs.add(key)
                    pairs.append((node, neighbor))
            for pair in pairs:
                key = edge_key(*pair)
                length = _number(
                    _as_mapping(lengths).get(key), default_length
                )
                duration = _number(
                    _as_mapping(durations).get(key), default_duration
                )
                edge_records.append(
                    (
                        pair[0],
                        pair[1],
                        length,
                        duration,
                        "spatial",
                    )
                )

        known_lengths = {
            edge_key(item[0], item[1]) for item in edge_records
        }
        for key in _as_mapping(lengths):
            if str(key) not in known_lengths:
                raise GeometryError(
                    "lengths: ребро %s отсутствует в связях" % key
                )
        for key in _as_mapping(durations):
            if str(key) not in known_lengths:
                raise GeometryError(
                    "durations: ребро %s отсутствует в связях" % key
                )

        edges = []
        for edge_source, edge_target, length, duration, kind in edge_records:
            if edge_source == edge_target:
                raise GeometryError(
                    "петля %s не является ребром" % edge_source
                )
            if known_nodes is not None:
                for endpoint in (edge_source, edge_target):
                    if endpoint not in known_nodes:
                        raise GeometryError(
                            "ребро %s|%s: неизвестный узел %s"
                            % (edge_source, edge_target, endpoint)
                        )
            else:
                if edge_source not in node_ids:
                    node_ids.append(edge_source)
                if edge_target not in node_ids:
                    node_ids.append(edge_target)
            if length is None or length <= 0:
                raise GeometryError(
                    "ребро %s|%s: длина должна быть > 0"
                    % (edge_source, edge_target)
                )
            if duration is None or duration < 0:
                raise GeometryError(
                    "ребро %s|%s: длительность должна быть >= 0"
                    % (edge_source, edge_target)
                )
            edges.append(
                GeometryEdge(
                    key=edge_key(edge_source, edge_target),
                    source=min(edge_source, edge_target),
                    target=max(edge_source, edge_target),
                    length=length,
                    duration=duration,
                    kind=kind or "spatial",
                )
            )
        node_ids = sorted(set(node_ids))

        orientation = {}
        raw_orientation = _as_mapping(record.get("orientation"))
        for node, payload in raw_orientation.items():
            node = str(node)
            if node not in node_ids:
                raise GeometryError(
                    "orientation: неизвестный узел %s" % node
                )
            entries = list(payload or ())
            if not entries:
                orientation[node] = ((), ())
                continue
            neighbors = []
            turns = []
            gaps = []
            for index, entry in enumerate(entries):
                if isinstance(entry, Mapping):
                    neighbor = _text(
                        entry.get("to")
                        or entry.get("neighbor")
                        or entry.get("id")
                    )
                    raw_turn = entry.get("turn")
                else:
                    neighbor = _text(entry)
                    raw_turn = None
                if not neighbor:
                    raise GeometryError(
                        "orientation.%s[%d]: нужен сосед" % (node, index)
                    )
                neighbors.append(neighbor)
                gaps.append(raw_turn)
            if any(gap is not None for gap in gaps) and any(
                gap is None for gap in gaps
            ):
                raise GeometryError(
                    "orientation.%s: укажите turn у всех соседей или ни у одного"
                    % node
                )
            if all(gap is None for gap in gaps):
                turns = cls._uniform_turns(len(neighbors))
            else:
                turns = []
                for index, raw in enumerate(gaps):
                    turn = _number(raw)
                    if turn is None:
                        raise GeometryError(
                            "orientation.%s[%d]: turn должен быть числом"
                            % (node, index)
                        )
                    turn *= unit
                    if turn <= 0 or turn > TAU + _EPSILON:
                        raise GeometryError(
                            "orientation.%s[%d]: поворот должен быть в (0, 2π]"
                            % (node, index)
                        )
                    turns.append(turn)
            orientation[node] = (tuple(neighbors), tuple(turns))

        return cls(
            node_ids,
            edges,
            orientation,
            source=source,
        )

    # ------------------------------------------------------------------
    # Запросы
    # ------------------------------------------------------------------

    def __len__(self):
        return len(self.nodes)

    def __contains__(self, node):
        return str(node) in self._node_set

    def neighbors(self, node):
        """Соседи в циклическом порядке узла."""
        node = str(node)
        if node not in self._node_set:
            raise GeometryError("неизвестный узел %s" % node)
        return self._order[node]

    def edges(self):
        """Все рёбра в детерминированном порядке."""
        return tuple(self._edges[key] for key in sorted(self._edges))

    def edge(self, source, target):
        """Ребро между соседями или ``None``."""
        return self._adjacency.get(str(source), {}).get(str(target))

    def degree(self, node):
        node = str(node)
        if node not in self._node_set:
            raise GeometryError("неизвестный узел %s" % node)
        return len(self._adjacency[node])

    def length(self, source, target):
        """Длина ближайшего ребра; ``None``, если узлы не соседи."""
        edge = self.edge(source, target)
        return edge.length if edge is not None else None

    def duration(self, source, target):
        """Длительность ближайшего ребра; ``None``, если узлы не соседи."""
        edge = self.edge(source, target)
        return edge.duration if edge is not None else None

    def _forward_angle(self, node, source, target):
        node = str(node)
        source = str(source)
        target = str(target)
        index = self._index.get(node, {})
        if source not in index or target not in index:
            raise GeometryError(
                "узел %s: %s и %s не являются соседями"
                % (node, source, target)
            )
        if source == target:
            return 0.0
        turns = self._turns[node]
        start = index[source]
        end = index[target]
        count = (end - start) % len(turns)
        value = 0.0
        for step in range(count):
            value += turns[(start + step) % len(turns)]
        return value

    def angle(self, node, source, target):
        """Меньший угол между двумя лучами в узле, радианы ``[0, π]``."""
        node = str(node)
        total = sum(self._turns.get(node, ()))
        forward = self._forward_angle(node, source, target)
        return min(forward, max(0.0, total - forward), math.pi)

    def signed_angle(self, node, source, target):
        """Знаковый поворот от луча ``source`` к лучу ``target``."""
        node = str(node)
        total = sum(self._turns.get(node, ()))
        return _normalize_signed(
            self._forward_angle(node, source, target), total
        )

    def turn(self, node, incoming, outgoing):
        """Поворот пути: пришёл из ``incoming``, ушёл в ``outgoing``.

        Прямой проход через узел даёт ``0``; поворот на 90° — ``±π/2``.
        """
        delta = self.signed_angle(node, incoming, outgoing)
        return _normalize_signed(delta - math.pi, TAU)

    def curvature(self, node):
        """Дефицит угла ``2π - Σturn``; для плоского узла — 0."""
        node = str(node)
        if node not in self._node_set:
            raise GeometryError("неизвестный узел %s" % node)
        if not self._turns[node]:
            return 0.0
        defect = TAU - sum(self._turns[node])
        return 0.0 if abs(defect) <= 1e-6 else defect

    def nearest(self, node):
        """Ближайшие соседи с длиной, длительностью и локальным углом."""
        node = str(node)
        result = []
        for neighbor in self.neighbors(node):
            edge = self.edge(node, neighbor)
            result.append(
                {
                    "node": neighbor,
                    "length": edge.length,
                    "duration": edge.duration,
                    "kind": edge.kind,
                }
            )
        return result

    def _search(self, source):
        source = str(source)
        if source not in self._node_set:
            raise GeometryError("неизвестный узел %s" % source)
        best = {source: (0.0, (source,), ())}
        heap = [((0.0, (source,), ()), source)]
        while heap:
            key, node = heapq.heappop(heap)
            current = best.get(node)
            if current is None:
                continue
            if (
                round(current[0], _ROUND),
                current[1],
                current[2],
            ) != key:
                continue
            for neighbor in sorted(self._adjacency[node]):
                edge = self._adjacency[node][neighbor]
                length = current[0] + edge.length
                nodes = current[1] + (neighbor,)
                edges = current[2] + (edge.key,)
                candidate = (
                    round(length, _ROUND),
                    nodes,
                    edges,
                )
                previous = best.get(neighbor)
                if previous is not None:
                    previous_key = (
                        round(previous[0], _ROUND),
                        previous[1],
                        previous[2],
                    )
                    if previous_key <= candidate:
                        continue
                best[neighbor] = (length, nodes, edges)
                heapq.heappush(heap, (candidate, neighbor))
        return best

    def path(self, source, target):
        """Канонический кратчайший путь или ``None``, если пути нет.

        Ничьи разрешаются лексикографически по последовательности узлов,
        затем по ключам ребер. Это делает результат независимым от порядка
        обхода словаря и от платформы.
        """
        source = str(source)
        target = str(target)
        best = self._search(source)
        item = best.get(target)
        if item is None:
            return None
        length, nodes, edges = item
        duration = sum(
            self._edges[key].duration for key in edges
        )
        return GeometryPath(
            nodes=nodes,
            edges=edges,
            length=length,
            duration=duration,
            bearing=self._developed_bearing(nodes),
        )

    def _developed_bearing(self, nodes):
        """Развернуть путь в локальной плоскости, начиная с первого ребра."""
        if len(nodes) <= 2:
            return 0.0
        value = 0.0
        for index in range(1, len(nodes) - 1):
            value += self.turn(
                nodes[index], nodes[index - 1], nodes[index + 1]
            )
        return _normalize_signed(value)

    def distance(self, source, target):
        """Длина кратчайшего пути; ``inf``, если узлы не связаны."""
        item = self.path(source, target)
        return item.length if item is not None else math.inf

    def travel_time(self, source, target):
        """Сумма длительностей вдоль канонического пути.

        Это ещё не физическое время: локальные часы и причинность —
        следующий этап. Здесь длительность ребра — просто метаданные.
        """
        item = self.path(source, target)
        return item.duration if item is not None else math.inf

    def angle_between_targets(self, observer, first, second, signed=False):
        """Угол между направлениями на две цели из узла-наблюдателя.

        Направления разворачиваются вдоль канонических путей. В графе с
        циклами разные геодезические могут дать разные углы; эта функция
        фиксирует один, shortest_path, и тем самым остаётся
        детерминированной. Возвращает ``None``, если пути нет.
        """
        observer = str(observer)
        first = str(first)
        second = str(second)
        if observer == first or observer == second:
            raise GeometryError(
                "направление из узла в себя не определено"
            )
        path_first = self.path(observer, first)
        path_second = self.path(observer, second)
        if path_first is None or path_second is None:
            return None
        first_step = path_first.nodes[1]
        second_step = path_second.nodes[1]
        delta = self.signed_angle(
            observer, first_step, second_step
        )
        value = _normalize_signed(
            delta + path_second.bearing - path_first.bearing
        )
        return value if signed else abs(value)

    def validate(self):
        """Вернуть список проблем; для построенного графа он пуст."""
        problems = []
        for key, edge in self._edges.items():
            if edge.length <= 0:
                problems.append("ребро %s: длина <= 0" % key)
            if edge.duration < 0:
                problems.append("ребро %s: длительность < 0" % key)
        for node in self.nodes:
            order = self._order[node]
            turns = self._turns[node]
            incident = set(self._adjacency[node])
            if set(order) != incident:
                problems.append(
                    "узел %s: ориентация не совпадает со связями" % node
                )
            if order and not _same_angle(sum(turns), TAU):
                problems.append(
                    "узел %s: сумма поворотов не равна 2π" % node
                )
        return problems

    def to_dict(self):
        """Нормализованное представление для отладки и снимков."""
        orientation = {}
        for node in self.nodes:
            orientation[node] = [
                {
                    "to": neighbor,
                    "turn": round(turn, 9),
                }
                for neighbor, turn in zip(
                    self._order[node], self._turns[node]
                )
            ]
        return {
            "schema": SCHEMA,
            "model": MODEL,
            "dimension": DIMENSION,
            "composition": COMPOSITION,
            "angle_unit": "radian",
            "source": self.source,
            "nodes": list(self.nodes),
            "edges": [edge.to_dict() for edge in self.edges()],
            "orientation": orientation,
            "curvature": {
                node: round(self.curvature(node), 9)
                for node in self.nodes
            },
        }


__all__ = [
    "COMPOSITION",
    "DIMENSION",
    "GeometryEdge",
    "GeometryError",
    "GeometryPath",
    "MODEL",
    "MetricGraph",
    "SCHEMA",
    "edge_key",
]
