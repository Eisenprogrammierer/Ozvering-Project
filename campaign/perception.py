"""Призма восприятия: мир → сигналы → знание агента.

F-23. Объективный мир не попадает в диалоговое знание напрямую. Каждый
факт приходит через канал (``sight``/``hearing``/``reading``/``memory``/
``inference``), имеет источник, уверенность и истинностный статус.
``Perception`` — это то, что наблюдатель действительно воспринял;
``WorldView`` добавляет место, сцену и видимые сущности.

Слой read-only: он только отбирает и размечает факты. Мир, кампания и BDI
не меняются, поэтому ложное убеждение или слух не могут переписать мир.

Правила видимости задаются данными в ``world.json`` (блок
``perception.relations``); Python знает лишь родовые области видимости:
``public``, ``reading``, ``visible``, ``self``, ``faction``, ``belief``,
``intention``, ``hidden``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass, replace
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

CHANNELS = ("sight", "hearing", "reading", "memory", "inference")

SCOPES = (
    "public",
    "reading",
    "visible",
    "self",
    "faction",
    "belief",
    "intention",
    "hidden",
)

CHANNEL_LABELS = {
    "sight": "я видел",
    "hearing": "мне сказали",
    "reading": "я прочитал",
    "memory": "я помню",
    "inference": "я догадался",
}

# Правила по ролям адаптера. Конкретные имена отношений берутся из
# ``world.json``, поэтому новый мир может переопределить блок целиком.
DEFAULT_SCOPES = {
    "faction_name": "public",
    "asset": "reading",
    "leader": "public",
    "speaks_for": "public",
    "has_organ": "reading",
    "organ_kind": "reading",
    "organ_integrity": "faction",
    "description": "public",
    "character_info": "visible",
    "post_info": "public",
    "has_work": "reading",
    "work_label": "reading",
    "work_essence": "reading",
    "work_target": "reading",
    "work_organ": "reading",
    "belief": "belief",
    "intention": "intention",
    "recent_work": "visible",
    "has_authority": "self",
    "trusts": "self",
}

DEFAULT_SCOPE = "visible"

# Реализации протокола ``WorldView``. Имена — данные для
# ``world.json.adapters``; сам протокол не зависит от конкретной модели
# мира.
WORLD_ADAPTER_KINDS = (
    "automata_campaign",
    "world_engine",
    "scene",
)


def _text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _key(rel: Any, args: Iterable[Any]) -> Tuple[str, Tuple[str, ...]]:
    return (_text(rel), tuple(_text(item) for item in args))


@dataclass(frozen=True)
class Signal:
    """Один воспринятый факт вместе с провенансом."""

    rel: str
    args: Tuple[str, ...] = ()
    channel: str = "sight"
    source: str = ""
    speaker: str = ""
    confidence: float = 1.0
    truth: str = "true"
    day: int = 0
    note: str = ""

    def __post_init__(self):
        object.__setattr__(self, "rel", _text(self.rel))
        object.__setattr__(
            self, "args", tuple(_text(item) for item in self.args or ())
        )
        channel = _text(self.channel, "sight")
        if channel not in CHANNELS:
            channel = "sight"
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "source", _text(self.source))
        object.__setattr__(self, "speaker", _text(self.speaker))
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError):
            confidence = 1.0
        object.__setattr__(
            self, "confidence", min(1.0, max(0.0, confidence))
        )
        truth = _text(self.truth, "true")
        if truth not in ("true", "false", "unknown"):
            truth = "unknown"
        object.__setattr__(self, "truth", truth)
        try:
            day = int(self.day)
        except (TypeError, ValueError):
            day = 0
        object.__setattr__(self, "day", day)
        object.__setattr__(self, "note", _text(self.note))

    @property
    def key(self) -> Tuple[str, Tuple[str, ...]]:
        return (self.rel, self.args)

    @property
    def group(self) -> str:
        """Куда отнести сигнал: сказанное, убеждение или восприятие."""

        if self.channel == "hearing" or self.speaker:
            return "said"
        if self.channel == "memory" or self.truth != "true":
            return "believed"
        if self.channel in ("sight", "reading", "inference"):
            return "perceived"
        return "perceived"

    @property
    def label(self) -> str:
        if self.group == "said":
            return CHANNEL_LABELS["hearing"]
        if self.group == "believed":
            return "я так считаю"
        return CHANNEL_LABELS.get(self.channel, "")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rel": self.rel,
            "args": list(self.args),
            "channel": self.channel,
            "source": self.source,
            "speaker": self.speaker,
            "confidence": self.confidence,
            "truth": self.truth,
            "day": self.day,
            "note": self.note,
            "group": self.group,
        }


@dataclass(frozen=True)
class Perception:
    """Снимок восприятия одного наблюдателя.

    ``signals`` — уже воспринятые факты (слух, прочитанное, память).
    ``scopes`` — правила видимости для отношений; ``visible`` — множество
    идентификаторов, которые наблюдатель видит в текущей сцене.
    """

    observer: str
    self_id: str = ""
    faction_id: str = ""
    visible: frozenset = frozenset()
    scopes: Mapping[str, str] = field(default_factory=dict)
    signals: Tuple[Signal, ...] = ()
    day: int = 0
    location: str = ""
    scene: str = ""
    default_scope: str = DEFAULT_SCOPE

    def __post_init__(self):
        object.__setattr__(self, "observer", _text(self.observer))
        object.__setattr__(self, "self_id", _text(self.self_id))
        object.__setattr__(self, "faction_id", _text(self.faction_id))
        object.__setattr__(
            self,
            "visible",
            frozenset(
                _text(item) for item in self.visible or () if _text(item)
            ),
        )
        scopes = {}
        for rel, scope in (self.scopes or {}).items():
            scope = _text(scope, DEFAULT_SCOPE)
            if scope not in SCOPES:
                scope = DEFAULT_SCOPE
            scopes[_text(rel)] = scope
        object.__setattr__(self, "scopes", scopes)
        signals = tuple(self.signals or ())
        index = {}
        for signal in signals:
            if not isinstance(signal, Signal):
                signal = Signal(**dict(signal))
            index[signal.key] = signal
        object.__setattr__(self, "signals", signals)
        object.__setattr__(self, "_index", index)
        object.__setattr__(self, "day", _day(self.day))
        object.__setattr__(self, "location", _text(self.location))
        object.__setattr__(self, "scene", _text(self.scene))
        scope = _text(self.default_scope, DEFAULT_SCOPE)
        if scope not in SCOPES:
            scope = DEFAULT_SCOPE
        object.__setattr__(self, "default_scope", scope)

    def __hash__(self):
        return hash(
            (
                self.observer,
                self.self_id,
                self.faction_id,
                self.visible,
                tuple(sorted(self.scopes.items())),
                self.signals,
                self.day,
                self.location,
                self.scene,
                self.default_scope,
            )
        )

    def _own_ids(self) -> frozenset:
        ids = {self.observer, self.self_id}
        if self.self_id:
            ids.add("character:%s" % self.self_id)
        if self.observer:
            ids.add("character:%s" % self.observer)
        return frozenset(item for item in ids if item)

    def _reason(self, rel: str, args: Tuple[str, ...]) -> str:
        scope = self.scopes.get(rel, self.default_scope)
        if scope == "hidden":
            return "hidden"
        if scope in ("self", "belief", "intention"):
            return "not-self"
        if scope == "faction":
            return "not-faction"
        if scope == "visible":
            return "not-visible"
        return "unknown"

    def signal_for(
        self, rel: str, args: Iterable[Any]
    ) -> Optional[Signal]:
        """Вернуть сигнал, если наблюдатель может знать факт."""

        key = _key(rel, args)
        explicit = self._index.get(key)
        if explicit is not None:
            return explicit
        rel, args = key
        scope = self.scopes.get(rel, self.default_scope)
        own = bool(self._own_ids().intersection(args))
        if scope == "public":
            return Signal(
                rel,
                args,
                channel="reading",
                source="world",
                day=self.day,
                note=scope,
            )
        if scope == "reading":
            return Signal(
                rel,
                args,
                channel="reading",
                source="records",
                day=self.day,
                note=scope,
            )
        if scope == "hidden":
            return None
        if scope == "self":
            if own:
                return Signal(
                    rel,
                    args,
                    channel="memory",
                    source="self",
                    day=self.day,
                    note=scope,
                )
            return None
        if scope == "faction":
            if own or self.faction_id in args:
                return Signal(
                    rel,
                    args,
                    channel="sight",
                    source="faction",
                    day=self.day,
                    note=scope,
                )
            if set(args).intersection(self.visible):
                return Signal(
                    rel,
                    args,
                    channel="sight",
                    source="scene",
                    day=self.day,
                    note=scope,
                )
            return None
        if scope == "visible":
            if set(args).intersection(self.visible):
                return Signal(
                    rel,
                    args,
                    channel="sight",
                    source="scene",
                    day=self.day,
                    note=scope,
                )
            return None
        if scope in ("belief", "intention"):
            if own:
                return Signal(
                    rel,
                    args,
                    channel="memory",
                    source=scope,
                    day=self.day,
                    note=scope,
                )
            return None
        return None

    def explain(self, rel: str, args: Iterable[Any]) -> Dict[str, Any]:
        key = _key(rel, args)
        signal = self.signal_for(*key)
        if signal is None:
            return {
                "rel": key[0],
                "args": list(key[1]),
                "known": False,
                "reason": self._reason(*key),
                "label": "не знаю",
            }
        data = signal.as_dict()
        data["known"] = True
        data["label"] = signal.label
        return data

    def annotate(self, fact: Any, signal: Signal) -> Any:
        """Разметить факт провенансом, не меняя его класса."""

        if not is_dataclass(fact):
            return fact
        changes = {}
        for name, value in (
            ("source", signal.source),
            ("channel", signal.channel),
            ("speaker", signal.speaker),
            ("confidence", signal.confidence),
            ("truth", signal.truth),
            ("day", signal.day),
        ):
            if hasattr(fact, name):
                changes[name] = value
        return replace(fact, **changes) if changes else fact

    def group(self, kind: str) -> Tuple[Signal, ...]:
        kind = _text(kind)
        return tuple(
            signal for signal in self.signals if signal.group == kind
        )

    def known(self, rel: str = "") -> Tuple[Signal, ...]:
        rel = _text(rel)
        return tuple(
            signal
            for signal in self.signals
            if not rel or signal.rel == rel
        )


@dataclass(frozen=True)
class WorldView:
    """Мир глазами наблюдателя: место, сцена и призма восприятия."""

    observer: str
    perception: Perception
    day: int = 0
    location: str = ""
    scene: str = ""
    visible_nodes: Tuple[str, ...] = ()
    visible_characters: Tuple[str, ...] = ()

    @property
    def signals(self) -> Tuple[Signal, ...]:
        return self.perception.signals

    @property
    def perceived(self) -> Tuple[Signal, ...]:
        """Факты, которые наблюдатель видел, прочитал или вывел."""

        return self.perception.group("perceived")

    @property
    def believed(self) -> Tuple[Signal, ...]:
        """Факты памяти и сомнительной истинности."""

        return self.perception.group("believed")

    @property
    def said(self) -> Tuple[Signal, ...]:
        """Факты, полученные через слух или речь."""

        return self.perception.group("said")

    @property
    def relations(self) -> Dict[str, Tuple[Tuple[str, ...], ...]]:
        """Известные отношения в виде ``rel -> args``."""

        result: Dict[str, list] = {}
        for signal in self.perception.known():
            result.setdefault(signal.rel, []).append(signal.args)
        return {rel: tuple(args) for rel, args in result.items()}

    @property
    def recent_work(self) -> Tuple[Signal, ...]:
        """Последние работы, доступные наблюдателю."""

        return self.perception.known("recent_work")

    @property
    def entities(self) -> Tuple[str, ...]:
        """Идентификаторы видимых сцены и известных фактов."""

        found: list = []

        def add(value: Any) -> None:
            text = _text(value)
            if text and text not in found:
                found.append(text)

        for value in self.visible_nodes:
            add(value)
        for value in self.visible_characters:
            add(value)
        for value in self.perception.visible:
            add(value)
        for signal in self.perception.known():
            for value in signal.args:
                if ":" in value:
                    add(value)
        return tuple(found)

    def unknown(self, rel: str, args: Iterable[Any]) -> bool:
        """Истина, если факт недоступен наблюдателю."""

        return self.signal_for(rel, args) is None

    def signal_for(
        self, rel: str, args: Iterable[Any]
    ) -> Optional[Signal]:
        return self.perception.signal_for(rel, args)

    def accepts(self, rel: str, args: Iterable[Any]) -> bool:
        return self.signal_for(rel, args) is not None

    def annotate(self, fact: Any) -> Optional[Any]:
        rel = _text(getattr(fact, "rel", ""))
        args = getattr(fact, "args", ()) or ()
        signal = self.signal_for(rel, args)
        if signal is None:
            return None
        return self.perception.annotate(fact, signal)

    def explain(self, rel: str, args: Iterable[Any]) -> Dict[str, Any]:
        data = self.perception.explain(rel, args)
        data.setdefault("location", self.location)
        data.setdefault("scene", self.scene)
        data.setdefault("visible_nodes", list(self.visible_nodes))
        data.setdefault(
            "visible_characters", list(self.visible_characters)
        )
        return data


def perception_scopes(
    world: Optional[Mapping[str, Any]] = None,
) -> Dict[str, str]:
    """Правила видимости из ``world.json`` с именами адаптера."""

    world = world or {}
    adapter = world.get("adapter") or {}
    block = world.get("perception") or {}
    raw = block.get("relations") if isinstance(block, Mapping) else None
    if not isinstance(raw, Mapping) or not raw:
        raw = DEFAULT_SCOPES
    result: Dict[str, str] = {}
    for role, scope in raw.items():
        rel = _text((adapter or {}).get(role), role)
        scope = _text(scope, DEFAULT_SCOPE)
        result[rel] = scope if scope in SCOPES else DEFAULT_SCOPE
    return result


def _find_observer(
    campaign: Any, observer_id: Optional[str], side: str = ""
) -> Tuple[Any, Any, str]:
    factions = getattr(campaign, "factions", {}) or {}
    observer_id = _text(observer_id)
    order = [side] if side in factions else []
    order.extend(name for name in factions if name not in order)
    for name in order:
        faction = factions.get(name)
        if faction is None:
            continue
        characters = list(getattr(faction, "characters", ()) or ())
        if observer_id:
            for character in characters:
                if _text(getattr(character, "campaign_id", "")) == observer_id:
                    return character, faction, name
            continue
        for character in characters:
            if bool(getattr(character, "campaign_leader", False)):
                return character, faction, name
        if characters:
            return characters[0], faction, name
    return None, None, side


def _campaign_visible(
    faction: Any,
    observer: Any,
    side: str,
    world: Optional[Mapping[str, Any]],
) -> frozenset:
    visible = set()
    observer_id = _text(getattr(observer, "campaign_id", ""))
    if observer_id:
        visible.add(observer_id)
        visible.add("character:%s" % observer_id)
    config = world or {}
    specs = config.get("factions") or {}
    faction_entity = _text(
        (specs.get(side) or {}).get("entity"), "faction:%s" % side
    )
    visible.add(faction_entity)
    visible.add(side)
    for character in getattr(faction, "characters", ()) or ():
        char_id = _text(getattr(character, "campaign_id", ""))
        if not char_id:
            continue
        visible.add(char_id)
        visible.add("character:%s" % char_id)
    for organ in getattr(faction, "organs", ()) or ():
        organ_id = _text(getattr(organ, "id", ""))
        if organ_id:
            visible.add("organ:%s:%s" % (side, organ_id))
    return frozenset(visible)


def campaign_perception(
    campaign: Any,
    observer_id: Optional[str] = None,
    *,
    world: Optional[Mapping[str, Any]] = None,
    side: str = "",
    signals: Iterable[Signal] = (),
    day: Optional[int] = None,
) -> Perception:
    """Построить призму персонажа кампании автоматов."""

    observer, faction, found_side = _find_observer(
        campaign, observer_id, side
    )
    if observer is None or faction is None:
        raise ValueError("наблюдатель не найден в кампании")
    self_id = _text(getattr(observer, "campaign_id", ""))
    visible = _campaign_visible(faction, observer, found_side, world)
    specs = (world or {}).get("factions") or {}
    faction_id = _text(
        (specs.get(found_side) or {}).get("entity"),
        "faction:%s" % found_side,
    )
    return Perception(
        observer=self_id or found_side,
        self_id=self_id,
        faction_id=faction_id,
        visible=visible,
        scopes=perception_scopes(world),
        signals=tuple(signals),
        day=_clock(campaign) if day is None else day,
    )


def campaign_view(
    campaign: Any,
    observer_id: Optional[str] = None,
    *,
    world: Optional[Mapping[str, Any]] = None,
    side: str = "",
    signals: Iterable[Signal] = (),
    day: Optional[int] = None,
    scene: str = "",
    location: str = "",
) -> WorldView:
    """Построить ``WorldView`` для персонажа кампании автоматов."""

    perception = campaign_perception(
        campaign,
        observer_id,
        world=world,
        side=side,
        signals=signals,
        day=day,
    )
    return WorldView(
        observer=perception.observer,
        perception=perception,
        day=perception.day,
        location=location,
        scene=scene,
    )


def _visible_nodes(world: Any, location: str) -> Tuple[str, ...]:
    node = world.node(location) if location else None
    if node is None:
        return ()
    found = []

    def add(node_id: str) -> None:
        node_id = _text(node_id)
        if node_id and node_id not in found:
            found.append(node_id)

    add(node["id"])
    path = world.node_path(node["id"]) if hasattr(world, "node_path") else []
    for item in path:
        add(item.get("id"))
        for child in item.get("children") or ():
            add(child)
    for child in node.get("children") or ():
        add(child)
    parent = world.node(node.get("parent")) if hasattr(world, "node") else None
    if parent is not None:
        for sibling in parent.get("children") or ():
            add(sibling)
    return tuple(found)


def world_perception(
    world: Any,
    observer_id: str = "player",
    *,
    world_data: Optional[Mapping[str, Any]] = None,
    signals: Iterable[Signal] = (),
    scene: str = "",
) -> Perception:
    """Построить призму для ``WorldEngine``: место, сцена, публика."""

    observer_id = _text(observer_id, "player")
    character = None
    if observer_id not in ("player", "you", "hero"):
        character = world.character(observer_id)
    if character is not None:
        location = _text(character.get("node_id"))
        visible = {observer_id, "character:%s" % observer_id}
    else:
        location = _text(getattr(world, "player_node_id", ""))
        visible = {observer_id}
    nodes = _visible_nodes(world, location)
    for node_id in nodes:
        visible.add(node_id)
    for char_id, item in getattr(world, "characters", {}).items():
        if _text(item.get("node_id")) in nodes:
            visible.add(char_id)
            visible.add("character:%s" % char_id)
    scene_obj = None
    if hasattr(world, "scene"):
        scene_obj = world.scene(scene or None)
    if scene_obj is not None:
        for person in world.scene_public(scene_obj.id):
            person_id = _text(person.get("id"))
            if person_id:
                visible.add(person_id)
                visible.add("character:%s" % person_id)
    return Perception(
        observer=observer_id,
        self_id=observer_id,
        faction_id="",
        visible=frozenset(visible),
        scopes=perception_scopes(world_data),
        signals=tuple(signals),
        day=_clock(world),
        location=location,
        scene=getattr(scene_obj, "id", "") if scene_obj else scene,
    )


def world_view(
    world: Any,
    observer_id: str = "player",
    *,
    world_data: Optional[Mapping[str, Any]] = None,
    signals: Iterable[Signal] = (),
    scene: str = "",
) -> WorldView:
    """Построить ``WorldView`` для ``WorldEngine``."""

    perception = world_perception(
        world,
        observer_id,
        world_data=world_data,
        signals=signals,
        scene=scene,
    )
    location = perception.location
    visible_nodes = _visible_nodes(world, location)
    visible_characters = []
    for char_id, item in getattr(world, "characters", {}).items():
        if _text(item.get("node_id")) in visible_nodes:
            visible_characters.append(char_id)
    return WorldView(
        observer=perception.observer,
        perception=perception,
        day=perception.day,
        location=location,
        scene=perception.scene,
        visible_nodes=visible_nodes,
        visible_characters=tuple(visible_characters),
    )


# --- адаптеры миров (F-16) -------------------------------------------


class AutomataCampaignAdapter:
    """Мост ``AutomataCampaign`` → ``WorldView``.

    Кампания остаётся единственным владельцем истины; адаптер только
    пропускает её состояние через ``Perception`` выбранного персонажа.
    """

    kind = "automata_campaign"

    def __init__(
        self,
        campaign: Any,
        world: Optional[Mapping[str, Any]] = None,
    ):
        self.campaign = campaign
        self.world = world or {}

    def view(
        self,
        observer_id: Optional[str] = None,
        *,
        side: str = "",
        signals: Iterable[Signal] = (),
        day: Optional[int] = None,
        scene: str = "",
        location: str = "",
    ) -> WorldView:
        return campaign_view(
            self.campaign,
            observer_id,
            world=self.world,
            side=side,
            signals=signals,
            day=day,
            scene=scene,
            location=location,
        )


class WorldEngineAdapter:
    """Мост ``WorldEngine`` → ``WorldView``.

    Работает с любым миром, который загрузил ``WorldEngine``: узлы,
    персонажи, предметы, нормы и сцены берутся из самого движка, а не
    из списка четырёх фракций.
    """

    kind = "world_engine"

    def __init__(
        self,
        world: Any,
        world_data: Optional[Mapping[str, Any]] = None,
    ):
        self.world = world
        self.world_data = world_data or {}

    def view(
        self,
        observer_id: str = "player",
        *,
        signals: Iterable[Signal] = (),
        scene: str = "",
    ) -> WorldView:
        return world_view(
            self.world,
            observer_id,
            world_data=self.world_data,
            signals=signals,
            scene=scene,
        )


class SceneAdapter(WorldEngineAdapter):
    """Мост локальной сцены → ``WorldView``.

    Сцена сужает видимость до узла и публики ``WorldEngine``; если
    сцена не задана, используется текущая.
    """

    kind = "scene"

    def view(
        self,
        observer_id: str = "player",
        *,
        signals: Iterable[Signal] = (),
        scene: str = "",
    ) -> WorldView:
        current = scene
        if not current and hasattr(self.world, "current_scene"):
            try:
                current = _text(getattr(self.world.current_scene(), "id", ""))
            except Exception:
                current = ""
        return world_view(
            self.world,
            observer_id,
            world_data=self.world_data,
            signals=signals,
            scene=current,
        )


def adapter_for(
    source: Any,
    kind: str = "",
    world_data: Optional[Mapping[str, Any]] = None,
) -> Any:
    """Выбрать адаптер по явному ``kind`` или по форме источника."""

    kind = _text(kind)
    if kind == "automata_campaign":
        return AutomataCampaignAdapter(source, world_data)
    if kind == "world_engine":
        return WorldEngineAdapter(source, world_data)
    if kind == "scene":
        return SceneAdapter(source, world_data)
    if hasattr(source, "factions"):
        return AutomataCampaignAdapter(source, world_data)
    if hasattr(source, "nodes") and hasattr(source, "characters"):
        return WorldEngineAdapter(source, world_data)
    raise ValueError("не удалось выбрать адаптер мира")


def _clock(source: Any) -> int:
    for name in ("day", "turn"):
        value = getattr(source, name, None)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _day(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
