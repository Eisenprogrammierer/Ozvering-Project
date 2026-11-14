"""D7.2: перемещение через текст поверх семантической геометрии.

Маршрут не хранит координат: кратчайший путь и расстояние берутся из
``MetricGraph`` стороны (P6.5, этап B). Места, пороги «рядом/далеко» и
сообщения — данные ``movement.json``. Перемещение меняет только
``ConversationState.location``; кампания и BDI остаются нетронутыми.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Tuple

from .model import DialogueCatalog


@dataclass(frozen=True)
class MoveResult:
    """Результат маршрута или текстового перемещения."""

    ok: bool
    moved: bool
    reason: str = ""
    destination: str = ""
    node: str = ""
    distance: float = 0.0
    band: str = ""
    path: Tuple[str, ...] = ()
    text: str = ""

    def snapshot(self) -> dict:
        return {
            "ok": self.ok,
            "moved": self.moved,
            "reason": self.reason,
            "destination": self.destination,
            "node": self.node,
            "distance": self.distance,
            "band": self.band,
            "path": list(self.path),
            "text": self.text,
        }


class MovementGuide:
    """Детерминированный маршрутизатор одного разговора."""

    def __init__(
        self,
        catalog: DialogueCatalog,
        knowledge: Any,
        campaign: Any = None,
        state: Any = None,
        allow_actions: bool = False,
    ):
        self.catalog = catalog
        self.knowledge = knowledge
        self.campaign = campaign
        self.state = state
        self.allow_actions = bool(allow_actions)
        self.spec: Mapping[str, Any] = catalog.movement or {}
        # Карта — сторона игрока, а не собеседника: разговор с синим не
        # переносит красного игрока в чужую геометрию.
        self.side = str(
            getattr(knowledge, "player_side", "")
            or getattr(knowledge, "side", "")
            or ""
        )

    def message(self, key: str, default: str = "", *args: Any) -> str:
        template = str(
            (self.spec.get("messages") or {}).get(key) or default
        )
        if not args:
            return template
        try:
            return template % args
        except (TypeError, ValueError):
            return template

    def node_for(self, entity_id: str) -> str:
        entry = (self.spec.get("places") or {}).get(str(entity_id))
        if not isinstance(entry, Mapping):
            return ""
        return str(entry.get(self.side) or "")

    def node_name(self, node: str) -> str:
        entity_id = "organ:%s:%s" % (self.side, node)
        return str(self.knowledge.name(entity_id) or node)

    def current_node(self) -> str:
        if self.state is not None:
            value = str(getattr(self.state, "location", "") or "")
            if value:
                return value
        value = str(
            getattr(self.knowledge, "player_organ_id", "") or ""
        )
        if value:
            return value
        defaults = self.spec.get("defaults") or {}
        if isinstance(defaults, Mapping):
            return str(defaults.get(self.side) or "")
        return ""

    def band_for(self, distance: float) -> Tuple[str, str]:
        bands = [
            item
            for item in (self.spec.get("bands") or ())
            if isinstance(item, Mapping)
        ]
        for item in bands:
            maximum = item.get("max")
            if maximum is None:
                return str(item.get("id") or ""), str(
                    item.get("label") or ""
                )
            try:
                limit = float(maximum)
            except (TypeError, ValueError):
                continue
            if distance <= limit + 1e-9:
                return str(item.get("id") or ""), str(
                    item.get("label") or ""
                )
        if bands:
            last = bands[-1]
            return str(last.get("id") or ""), str(
                last.get("label") or ""
            )
        return "", ""

    def plan(self, entity_id: str) -> MoveResult:
        """Построить маршрут, ничего не меняя."""

        destination = str(entity_id or "")
        if not destination:
            return MoveResult(
                ok=False,
                moved=False,
                reason="not_a_place",
                text=self.message(
                    "unknown", "Не знаю такого места: %s.", destination
                ),
            )
        node = self.node_for(destination)
        if not node:
            return MoveResult(
                ok=False,
                moved=False,
                reason="unknown_place",
                destination=destination,
                text=self.message(
                    "unknown",
                    "Не знаю такого места: %s.",
                    self.knowledge.name(destination),
                ),
            )
        current = self.current_node()
        if not current:
            return MoveResult(
                ok=False,
                moved=False,
                reason="no_start",
                destination=destination,
                node=node,
                text=self.message(
                    "no_start", "Не знаю, где вы находитесь."
                ),
            )
        if node == current:
            name = self.node_name(node)
            return MoveResult(
                ok=True,
                moved=False,
                reason="already",
                destination=destination,
                node=node,
                path=(node,),
                text=self.message(
                    "already", "Вы уже здесь: %s.", name
                ),
            )
        graph = None
        if self.campaign is not None:
            try:
                graph = self.campaign.geometry(self.side)
            except AttributeError:
                graph = None
        if graph is None:
            return MoveResult(
                ok=False,
                moved=False,
                reason="no_geometry",
                destination=destination,
                node=node,
                text=self.message(
                    "no_geometry", "У этой стороны нет геометрии."
                ),
            )
        if current not in graph.nodes or node not in graph.nodes:
            return MoveResult(
                ok=False,
                moved=False,
                reason="no_path",
                destination=destination,
                node=node,
                text=self.message(
                    "no_path",
                    "Пути к %s нет.",
                    self.node_name(node),
                ),
            )
        path = graph.path(current, node)
        if path is None:
            return MoveResult(
                ok=False,
                moved=False,
                reason="no_path",
                destination=destination,
                node=node,
                text=self.message(
                    "no_path",
                    "Пути к %s нет.",
                    self.node_name(node),
                ),
            )
        distance = float(path.length)
        band, band_label = self.band_for(distance)
        path_text = " → ".join(
            self.node_name(item) for item in path.nodes
        )
        return MoveResult(
            ok=True,
            moved=False,
            destination=destination,
            node=node,
            distance=distance,
            band=band,
            path=tuple(path.nodes),
            text=self.message(
                "route", "Путь: %s; %s.", path_text, band_label
            ),
        )

    def move(self, entity_id: str) -> MoveResult:
        """Построить маршрут и, если действия разрешены, переместиться."""

        plan = self.plan(entity_id)
        if not plan.ok or plan.reason == "already":
            return plan
        path_text = " → ".join(
            self.node_name(item) for item in plan.path
        ) if plan.path else self.node_name(plan.node)
        band_label = self.band_for(plan.distance)[1]
        if not self.allow_actions:
            return replace(
                plan,
                ok=False,
                reason="actions_disabled",
                text=self.message(
                    "disabled",
                    "Перемещение выключено. Путь: %s; %s.",
                    path_text,
                    band_label,
                ),
            )
        if self.state is None:
            return replace(
                plan,
                ok=False,
                reason="no_state",
            )
        self.state.location = plan.node
        return replace(
            plan,
            moved=True,
            text=self.message(
                "arrived",
                "Вы прибыли: %s. Путь: %s; %s.",
                self.node_name(plan.node),
                path_text,
                band_label,
            ),
        )
