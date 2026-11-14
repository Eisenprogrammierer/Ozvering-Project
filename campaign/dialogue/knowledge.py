"""Read-only адаптер кампании и BDI к фактам диалогового слоя.

Адаптер ничего не меняет: он снимает копию нужных значений в неизменяемые
факты. Все дальнейшие ответы строятся только по этой копии, поэтому
диалог не может изменить кампанию или BDI.

D4 добавляет факты социального слоя: ``has_authority``, ``trusts``,
``has_leverage``. Они вычисляются из данных кампании, а не из BDI, и
используются ``SocialEngine`` для проверки допустимости речевых актов.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .errors import DialogueError
from .model import DialogueCatalog, LexEntry


@dataclass(frozen=True)
class Fact:
    """Факт предметной области: отношение и аргументы."""

    rel: str
    args: Tuple[str, ...] = ()

    def key(self) -> Tuple[str, Tuple[str, ...]]:
        return (self.rel, self.args)


@dataclass(frozen=True)
class EntityInfo:
    """Сведения о сущности для отображения и описания."""

    id: str
    type: str
    name: str
    source: str = "lexicon"


def _text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _nominal(entry: LexEntry) -> str:
    for form in entry.forms:
        if form.features.get("case") == "nom":
            return form.text
    for form in entry.all_forms():
        if form.text:
            return form.text
    return entry.lemma


class AgentKnowledge:
    """Неизменяемая картина мира говорящего агента."""

    def __init__(
        self,
        catalog: DialogueCatalog,
        facts: Iterable[Fact],
        entities: Mapping[str, EntityInfo],
        *,
        side: str,
        faction_id: str,
        speaker_id: str,
        speaker_name: str,
        world: Mapping[str, Any],
        clock: int = 0,
        run_id: str = "",
        speaker_post: str = "",
        faction_name: str = "",
        player_id: str = "",
        player_name: str = "",
        player_post: str = "",
        player_faction: str = "",
        player_side: str = "",
        player_gender: str = "",
        player_organ_id: str = "",
    ):
        self.catalog = catalog
        self.facts = tuple(facts)
        self.entities = dict(entities)
        self.side = side
        self.faction_id = faction_id
        self.speaker_id = speaker_id
        self.speaker_name = speaker_name
        self.speaker_post = speaker_post
        self.faction_name = faction_name
        self.player_id = player_id
        self.player_name = player_name
        self.player_post = player_post
        self.player_faction = player_faction
        self.player_side = player_side
        self.player_gender = player_gender
        self.player_organ_id = player_organ_id
        self.world = world
        self.clock = clock
        self.run_id = run_id or "campaign"
        self._by_rel: Dict[str, List[Fact]] = {}
        for fact in self.facts:
            self._by_rel.setdefault(fact.rel, []).append(fact)
        self._lexemes = {entry.id: entry for entry in catalog.lexicon}

    def facts_for(self, relation: str) -> Tuple[Fact, ...]:
        return tuple(self._by_rel.get(str(relation), ()))

    def entity(self, entity_id: str) -> Optional[EntityInfo]:
        return self.entities.get(str(entity_id))

    def type_of(self, entity_id: str) -> str:
        info = self.entity(entity_id)
        if info is not None:
            return info.type
        entry = self._lexemes.get(str(entity_id))
        if entry is not None:
            return entry.type
        return str(entity_id).split(":", 1)[0]

    def type_label(self, entity_id: str) -> str:
        type_name = self.type_of(entity_id)
        definition = self.catalog.ontology.entity_types.get(type_name) or {}
        return _text(definition.get("label"), type_name)

    def name(self, entity_id: str) -> str:
        info = self.entity(entity_id)
        if info is not None:
            return info.name
        entry = self._lexemes.get(str(entity_id))
        if entry is not None:
            return _nominal(entry)
        return str(entity_id)

    def surface(
        self, entity_id: str, case: str = "nom", number: str = "sg"
    ) -> str:
        """Поверхностная форма сущности в нужном падеже и числе."""

        entity_id = str(entity_id)
        info = self.entity(entity_id)
        if info is not None and info.source == "dynamic":
            return info.name
        entry = self._lexemes.get(entity_id)
        if entry is not None:
            found = _find_form(entry, case, number)
            if found:
                return found
            other = "pl" if number == "sg" else "sg"
            found = _find_form(entry, case, other)
            if found:
                return found
        if info is not None:
            return info.name
        entry = self._lexemes.get(entity_id)
        if entry is not None:
            return _nominal(entry)
        return entity_id


def _find_form(entry: LexEntry, case: str, number: str) -> str:
    for form in entry.forms:
        features = form.features
        if (
            features.get("case") == case
            and features.get("number") == number
        ):
            return form.text
    return ""


def _alias_map(world: Mapping[str, Any]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for side, item in (world.get("factions") or {}).items():
        data = item if isinstance(item, Mapping) else {}
        entity = _text(data.get("entity"))
        if not entity:
            continue
        aliases[str(side)] = entity
        aliases[entity] = entity
        for key in ("campaign_id",):
            value = _text(data.get(key))
            if value:
                aliases[value] = entity
        for value in data.get("belief_aliases") or ():
            if _text(value):
                aliases[str(value)] = entity
    return aliases


def _normalize(raw: Any, aliases: Mapping[str, str]) -> str:
    text = _text(raw)
    return aliases.get(text, text)


def _fact(rel: str, *args: Any) -> Fact:
    return Fact(rel, tuple(_text(arg) for arg in args))


def _numeric(value: Any) -> str:
    try:
        return "%.6f" % float(value)
    except (TypeError, ValueError):
        return _text(value)


def build_knowledge(
    catalog: DialogueCatalog,
    campaign: Any,
    side: str,
    character_id: Optional[str] = None,
) -> AgentKnowledge:
    """Снять read-only снимок кампании для диалога с агентом стороны."""

    if side not in campaign.factions:
        raise DialogueError("в кампании нет стороны %r" % side)
    faction = campaign.factions[side]
    world = catalog.world or {}
    aliases = _alias_map(world)
    specs = world.get("factions") or {}
    adapter = world.get("adapter") or {}

    def rel(name: str) -> str:
        """Имя отношения в диалоговой онтологии по роли адаптера."""

        return _text(adapter.get(name), name)

    faction_entity = _text(
        (specs.get(side) or {}).get("entity"),
        aliases.get(side, "faction:%s" % side),
    )

    speaker = _select_speaker(faction, character_id)
    if speaker is None:
        raise DialogueError("у стороны %r нет персонажей для диалога" % side)
    speaker_id = _text(getattr(speaker, "campaign_id", ""), "character")
    speaker_name = _text(getattr(speaker, "name", ""), speaker_id)
    speaker_post = _text(getattr(speaker, "campaign_post", ""))
    faction_name = _text(getattr(faction, "name", ""), side)
    player = _player_character(campaign)
    player_side, player_faction_runtime, player_character = player
    player_name = _text(getattr(player_character, "name", ""))
    player_post = _text(
        getattr(player_character, "campaign_post", "")
    )
    player_faction = _text(
        getattr(player_faction_runtime, "name", ""), player_side
    )
    player_gender = _player_gender(campaign, player_character)

    entities: Dict[str, EntityInfo] = {}
    for entry in catalog.lexicon:
        entities[entry.id] = EntityInfo(
            id=entry.id,
            type=entry.type,
            name=_nominal(entry),
        )

    facts: List[Fact] = []
    seen: set = set()

    def add(fact: Fact) -> None:
        key = fact.key()
        if key not in seen:
            seen.add(key)
            facts.append(fact)

    def add_entity(
        entity_id: str, type_name: str, name: str
    ) -> None:
        if not entity_id:
            return
        if (
            entity_id not in entities
            or entities[entity_id].source != "lexicon"
        ):
            entities[entity_id] = EntityInfo(
                id=entity_id,
                type=type_name,
                name=name,
                source="dynamic",
            )

    for spec in catalog.facts:
        add(Fact(spec.rel, spec.args))

    for other_side, other in campaign.factions.items():
        other_entity = _text(
            (specs.get(other_side) or {}).get("entity"),
            aliases.get(other_side, "faction:%s" % other_side),
        )
        add_entity(other_entity, "faction", _text(other.name, other_side))
        add(_fact(rel("faction_name"), other_entity, _text(other.name)))

        for key in world.get("assets") or ():
            try:
                value = other.asset(key)
            except Exception:
                continue
            add(_fact(rel("asset"), other_entity, key, _numeric(value)))

        leader = _leader(other)
        if leader is not None:
            leader_id = _text(getattr(leader, "campaign_id", ""))
            leader_name = _text(getattr(leader, "name", ""), leader_id)
            post_id = _text(getattr(leader, "campaign_post_id", ""))
            post_entity = (
                "post:%s:%s" % (other_side, post_id) if post_id else ""
            )
            add(
                _fact(
                    rel("leader"),
                    other_entity,
                    leader_id,
                    post_entity,
                    leader_name,
                )
            )
            if leader_id:
                add(_fact(rel("speaks_for"), leader_id, other_entity))

        for organ in getattr(other, "organs", ()) or ():
            organ_id = _text(getattr(organ, "id", ""))
            if not organ_id:
                continue
            entity_id = "organ:%s:%s" % (other_side, organ_id)
            add_entity(
                entity_id,
                "organ",
                _text(getattr(organ, "name", ""), organ_id),
            )
            add(_fact(rel("has_organ"), other_entity, entity_id))
            add(
                _fact(
                    rel("organ_kind"),
                    entity_id,
                    getattr(organ, "kind", ""),
                )
            )
            add(
                _fact(
                    rel("organ_integrity"),
                    entity_id,
                    _numeric(getattr(organ, "integrity", 0.0)),
                )
            )
            description = _text(getattr(organ, "description", ""))
            if description:
                add(_fact(rel("description"), entity_id, description))

        for character in getattr(other, "characters", ()) or ():
            char_id = _text(getattr(character, "campaign_id", ""))
            if not char_id:
                continue
            entity_id = "character:%s" % char_id
            char_name = _text(getattr(character, "name", ""), char_id)
            add_entity(entity_id, "character", char_name)
            add(
                _fact(
                    rel("character_info"),
                    entity_id,
                    other_entity,
                    char_name,
                    getattr(character, "campaign_post", ""),
                )
            )
            post_id = _text(getattr(character, "campaign_post_id", ""))
            if post_id:
                post_entity = "post:%s:%s" % (other_side, post_id)
                add_entity(
                    post_entity,
                    "post",
                    getattr(character, "campaign_post", post_id),
                )
                add(
                    _fact(
                        rel("post_info"),
                        post_entity,
                        other_entity,
                        getattr(character, "campaign_post", ""),
                        char_name,
                        getattr(character, "campaign_organ_id", ""),
                    )
                )

        for action in getattr(other, "actions", ()) or ():
            action_id = _text(action.get("id"))
            if not action_id:
                continue
            entity_id = "work:%s:%s" % (other_side, action_id)
            label = _text(action.get("label"), action_id)
            add_entity(entity_id, "work", label)
            add(_fact(rel("has_work"), other_entity, entity_id))
            add(_fact(rel("work_label"), entity_id, label))
            add(
                _fact(
                    rel("work_essence"),
                    entity_id,
                    action.get("essence", ""),
                )
            )
            add(
                _fact(
                    rel("work_target"),
                    entity_id,
                    action.get("target", ""),
                )
            )
            add(
                _fact(
                    rel("work_organ"),
                    entity_id,
                    action.get("organ_id", ""),
                )
            )

    for belief in getattr(getattr(speaker, "bdi", None), "beliefs", ()) or ():
        subject = _normalize(getattr(belief, "subject", ""), aliases)
        target = _normalize(getattr(belief, "object", ""), aliases)
        add(
            _fact(
                rel("belief"),
                speaker_id,
                subject,
                getattr(belief, "predicate", ""),
                target,
            )
        )
    for intention in (
        getattr(getattr(speaker, "bdi", None), "intentions", ()) or ()
    ):
        target = _normalize(getattr(intention, "target", ""), aliases)
        add(
            _fact(
                rel("intention"),
                speaker_id,
                target,
                getattr(intention, "essence", ""),
            )
        )

    for entry in getattr(campaign, "log", ()) or ():
        if not isinstance(entry, Mapping):
            continue
        actor_side = _text(entry.get("actor_side"))
        if not actor_side:
            continue
        actor_entity = _text(
            (specs.get(actor_side) or {}).get("entity"),
            aliases.get(actor_side, "faction:%s" % actor_side),
        )
        add(
            _fact(
                rel("recent_work"),
                actor_entity,
                entry.get("turn", ""),
                entry.get("label", ""),
                "1" if entry.get("success") else "0",
                entry.get("text", ""),
            )
        )

    player_entity = _text(
        getattr(player_character, "campaign_id", "")
    )
    if player_entity and speaker_id and player_entity != speaker_id:
        add(
            _authority_fact(
                player_character, speaker, player_entity, speaker_id
            )
        )
        if _allied(player_character, speaker):
            add(_fact(rel("trusts"), player_entity, speaker_id))

    return AgentKnowledge(
        catalog,
        facts,
        entities,
        side=side,
        faction_id=faction_entity,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        world=world,
        clock=_clock(campaign),
        run_id=_run_id(campaign),
        speaker_post=speaker_post,
        faction_name=faction_name,
        player_id=player_entity,
        player_name=player_name,
        player_post=player_post,
        player_faction=player_faction,
        player_side=player_side,
        player_gender=player_gender,
        player_organ_id=_text(
            getattr(player_character, "campaign_organ_id", "")
        ),
    )


def _authority_fact(
    player: Any, speaker: Any, player_id: str, speaker_id: str
) -> Fact:
    """Факт ``has_authority(player, speaker)`` по данным кампании.

    Полномочия определяются по ``campaign_post_rank``, если он заполнен
    у обеих сторон; иначе — по ``campaign_post_id`` (равенство должности
    не даёт полномочий). Это консервативная проверка: если данных
    недостаточно, факт не выставляется, и ``SocialEngine`` вернёт
    ``reject`` с причиной ``has_authority``. Это не баг, а честное «нет
    данных о полномочиях».
    """

    player_rank = getattr(player, "campaign_post_rank", None)
    speaker_rank = getattr(speaker, "campaign_post_rank", None)
    try:
        if player_rank is not None and speaker_rank is not None:
            if int(player_rank) > int(speaker_rank):
                return _fact("has_authority", player_id, speaker_id)
    except (TypeError, ValueError):
        pass
    player_post = _text(getattr(player, "campaign_post_id", ""))
    speaker_post = _text(getattr(speaker, "campaign_post_id", ""))
    if player_post and speaker_post and player_post != speaker_post:
        return _fact("has_authority", player_id, speaker_id)
    return _fact("has_authority", "", "")


def _allied(player: Any, speaker: Any) -> bool:
    """Игрок и говорящий в одной фракции/альянсе — слабый признак доверия."""

    player_faction = getattr(player, "campaign_faction", None)
    speaker_faction = getattr(speaker, "campaign_faction", None)
    if player_faction is not None and speaker_faction is not None:
        return player_faction is speaker_faction
    player_faction = str(
        getattr(player, "campaign_faction_id", "") or ""
    )
    speaker_faction = str(
        getattr(speaker, "campaign_faction_id", "") or ""
    )
    return bool(player_faction) and player_faction == speaker_faction


def _clock(campaign: Any) -> int:
    """Игровое время для памяти: день мира, иначе ход кампании."""

    for name in ("day", "turn"):
        value = getattr(campaign, name, None)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    world = getattr(campaign, "world", None)
    value = getattr(world, "day", None)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _run_id(campaign: Any) -> str:
    """Идентификатор партии: пресет и зерно, без привязки к сюжету."""

    preset = _text(getattr(campaign, "preset_id", ""))
    seed = _text(getattr(campaign, "seed", ""))
    if preset or seed:
        return "campaign:%s:%s" % (preset, seed)
    return "campaign"


def _leader(faction: Any) -> Any:
    leader_id = _text((getattr(faction, "record", {}) or {}).get("leader_id"))
    if leader_id:
        found = faction.character(leader_id)
        if found is not None:
            return found
    for character in getattr(faction, "characters", ()) or ():
        if bool(getattr(character, "campaign_leader", False)):
            return character
    characters = list(getattr(faction, "characters", ()) or ())
    return characters[0] if characters else None


def _player_character(campaign: Any):
    """Найти игрового персонажа, не меняя кампанию.

    Сначала проверяется сторона игрока, затем остальные фракции: это
    делает поиск устойчивым к старым снимкам, где ``player_side`` мог не
    совпасть с записью персонажа.
    """

    factions = getattr(campaign, "factions", {}) or {}
    player_side = _text(getattr(campaign, "player_side", ""))
    order = [player_side] + [
        str(side) for side in factions if str(side) != player_side
    ]
    for side in order:
        faction = factions.get(side)
        if faction is None:
            continue
        for character in getattr(faction, "characters", ()) or ():
            if bool(getattr(character, "campaign_is_player", False)):
                return side, faction, character
    return player_side, factions.get(player_side), None


def _player_gender(campaign: Any, player: Any) -> str:
    """Пол игрока для обращений; пустая строка даёт нейтральную форму."""

    data = getattr(campaign, "data", {}) or {}
    identity = (
        data.get("player_identity")
        if isinstance(data, Mapping)
        else None
    )
    identity = identity if isinstance(identity, Mapping) else {}
    for value in (
        identity.get("gender"),
        getattr(player, "gender", ""),
        getattr(player, "sex", ""),
    ):
        text = _text(value)
        if text:
            return text
    return ""


def _select_speaker(faction: Any, character_id: Optional[str]) -> Any:
    if character_id:
        found = faction.character(character_id)
        if found is None:
            raise DialogueError(
                "у стороны %r нет персонажа %r"
                % (getattr(faction, "side", "?"), character_id)
            )
        return found
    return _leader(faction)
