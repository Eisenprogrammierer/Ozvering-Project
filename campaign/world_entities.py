"""Узлы, сущности, сцены и персонажи мира."""

from __future__ import annotations

from .world_support import (
    AUTONOMY_PERIOD,
    ActionError,
    CAMPAIGN_WOUND_MAX,
    CHARACTER_CIRCLES,
    CampaignCharacter,
    HEALTH_MAX,
    KIND_LABELS,
    NODE_STATS,
    ORGANIZATION_CATEGORIES,
    RELATION_AXES,
    SICKNESS_MAX,
    _as_float,
    _as_int,
    _clamp,
    _profile_connection_strength,
    _text,
    parse_entity_ref,
    player_projection_view,
)


class WorldEntitiesMixin:

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
                "values": (
                    dict(raw.get("values"))
                    if isinstance(raw.get("values"), dict)
                    else list(raw.get("values") or ())
                ),
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
    def _build_character(raw, axes=RELATION_AXES):
        health = _clamp(
            _as_float(raw.get("health"), HEALTH_MAX),
            0.0,
            HEALTH_MAX,
        )
        character = CampaignCharacter({
            "id": raw["id"],
            "name": _text(raw.get("name"), raw["id"]),
            "role": _text(raw.get("role")),
            "circle": _text(raw.get("circle"), "acquaintance"),
            "health": health,
            "sickness": _clamp(
                _as_float(raw.get("sickness"), 0.0),
                0.0,
                SICKNESS_MAX,
            ),
            "wound": _clamp(
                _as_float(raw.get("wound"), 0.0),
                0.0,
                CAMPAIGN_WOUND_MAX,
            ),
            "alive": bool(raw.get("alive", health > 0.0)),
            "node_id": _text(raw.get("node_id")),
            "tags": list(raw.get("tags") or ()),
            "description": _text(raw.get("description")),
            "autonomous": bool(raw.get("autonomous", False)),
            "autonomy_period": max(
                1, _as_int(raw.get("autonomy_period"), AUTONOMY_PERIOD)
            ),
        })
        for axis in axes:
            character[axis] = _clamp(raw.get(axis, 0.0), -1.0, 1.0)
        return character

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

    def _entity_kind(self, entity):
        if entity is None:
            return ""
        kind = self._entity_kinds.get(id(entity), "")
        if kind:
            return kind
        if isinstance(entity, dict) and entity.get("creditor") is not None:
            return "obligation"
        if hasattr(entity, "creditor") and hasattr(entity, "debtor"):
            return "obligation"
        return ""

    @staticmethod
    def _entity_id(entity):
        if entity is None:
            return ""
        if isinstance(entity, dict):
            return _text(entity.get("id"))
        return _text(getattr(entity, "id", ""))

    def entity(self, ref):
        """Найти сущность по универсальной ссылке ``kind/id``."""
        try:
            ref = parse_entity_ref(ref)
        except ActionError:
            return None
        kind, entity_id = ref["kind"], ref["id"]
        if kind == "character":
            return self.characters.get(entity_id)
        if kind == "item":
            return self.item_catalog.get(entity_id)
        if kind == "norm":
            return self.norms.get(entity_id)
        if kind == "obligation":
            obligation = self.obligations.get(entity_id)
            return obligation.to_dict() if obligation is not None else None
        if kind in ("place", "organization", "institution", "asset"):
            node = self.node(entity_id)
            if node is None:
                return None
            if kind in ("institution", "asset") and node.get("kind") != kind:
                return None
            return node
        return None

    def entity_ref(self, entity):
        """Обратная ссылка ``entity_ref`` для известной сущности."""
        kind = self._entity_kind(entity)
        if not kind:
            return {}
        return {"kind": kind, "id": self._entity_id(entity)}

    def _kind_matches(self, actual, kinds):
        if not kinds:
            return True
        if actual in kinds:
            return True
        if actual in ("institution", "asset"):
            return "place" in kinds or "organization" in kinds
        if actual == "organ":
            return "organization" in kinds
        return False

    def known_entities(self, kinds=None):
        """Перечислить адресатов мира в виде ``entity_ref``."""
        kinds = set(kinds or ())
        result = []
        for character in self.characters.values():
            if self._kind_matches("character", kinds):
                result.append(self.entity_ref(character))
        for node in self.nodes.values():
            actual = self._entity_kind(node)
            if self._kind_matches(actual, kinds):
                result.append(self.entity_ref(node))
        for item in self.item_catalog.values():
            if self._kind_matches("item", kinds):
                result.append(self.entity_ref(item))
        for norm in self.norms.values():
            if self._kind_matches("norm", kinds):
                result.append(self.entity_ref(norm))
        for obligation in self.obligations:
            if self._kind_matches("obligation", kinds):
                result.append(self.entity_ref(obligation))
        return result

    def scene(self, scene_id=None):
        """Найти сцену по id или текущую сцену игрока."""
        if scene_id:
            return self.scene_catalog.get(scene_id)
        if self.scene_id:
            scene = self.scene_catalog.get(self.scene_id)
            if scene is not None:
                return scene
        return self.scene_catalog.for_node(self.player_node_id)

    def scene_for_node(self, node_id):
        return self.scene_catalog.for_node(node_id)

    def current_scene(self):
        return self.scene()

    def scene_public(self, scene_id=None):
        """Именованная публика сцены: локальные люди и жители узла."""
        scene = self.scene(scene_id)
        if scene is None:
            return []
        ids = list(self.scene_public_ids.get(scene.id) or ())
        if scene.location:
            for character_id, character in self.characters.items():
                if character.get("node_id") != scene.location:
                    continue
                if character_id not in ids:
                    ids.append(character_id)
        return [
            self.characters[character_id]
            for character_id in ids
            if character_id in self.characters
        ]

    def scene_actions(self, scene_id=None):
        """Работы, уместные в сцене; пустой список — весь мир."""
        scene = self.scene(scene_id)
        if scene is None:
            return []
        work_ids = scene.works or tuple(self.actions)
        return [
            self.actions[action_id]
            for action_id in work_ids
            if action_id in self.actions
        ]

    def scene_action_options(self, scene_id=None):
        scene = self.scene(scene_id)
        if scene is None:
            return []
        allowed = {action["id"] for action in self.scene_actions(scene.id)}
        return [
            item
            for item in self.action_options()
            if item["id"] in allowed
        ]

    def scene_time(self, scene_id=None):
        scene = self.scene(scene_id)
        data = dict(scene.time) if scene is not None else {}
        data.setdefault("seconds_per_day", self.seconds_per_day)
        data.setdefault("actions_per_day", self.actions_per_day)
        data.setdefault("scene_id", scene.id if scene else "")
        return data

    def scene_exit_reason(self, scene_id=None):
        scene = self.scene(scene_id)
        if scene is None:
            return ""
        entered = self.scene_entered_day or None
        if scene.id == self.scene_id and not entered:
            entered = self.day
        return scene.exit_reason(
            day=self.day, entered_day=entered, attached=self.attached
        )

    def can_enter_scene(self, scene_id):
        scene = self.scene_catalog.get(scene_id)
        if scene is None:
            return False, "сцена не найдена"
        if (
            not scene.remote
            and scene.location
            and self.player_node_id
            and scene.location != self.player_node_id
        ):
            return False, "сцена находится в другом месте"
        office = self.offices.get(self.player_office_id) or {}
        tags = tuple(office.get("tags") or ())
        return scene.allows(
            attached=bool(self.attached),
            office=office,
            day=self.day,
            tags=tags,
            has_office=bool(self.player_office_id),
        )

    def enter_scene(self, scene_id):
        allowed, reason = self.can_enter_scene(scene_id)
        if not allowed:
            return {"ok": False, "reason": reason}
        self.scene_id = _text(scene_id)
        self.scene_entered_day = self.day
        scene = self.scene(self.scene_id)
        self.log.append(
            {
                "day": self.day,
                "kind": "scene",
                "text": "сцена: %s" % (scene.label if scene else scene_id),
            }
        )
        return {
            "ok": True,
            "scene": self.scene_view(self.scene_id),
        }

    def leave_scene(self):
        previous = self.scene_id
        self.scene_id = ""
        self.scene_entered_day = 0
        if previous:
            self.log.append(
                {"day": self.day, "kind": "scene", "text": "сцена завершена"}
            )
        return {"ok": True, "scene": self.scene_view()}

    def scene_view(self, scene_id=None):
        scene = self.scene(scene_id)
        if scene is None:
            return {}
        return {
            "id": scene.id,
            "label": scene.label,
            "description": scene.description,
            "location": scene.location,
            "location_label": self.node_label(scene.location),
            "tags": list(scene.tags),
            "public": [
                self.entity_ref(person)
                for person in self.scene_public(scene.id)
            ],
            "works": [action["id"] for action in self.scene_actions(scene.id)],
            "time": self.scene_time(scene.id),
            "entered_day": int(self.scene_entered_day or 0),
            "exit_reason": self.scene_exit_reason(scene.id),
        }

    def action_targets(self, action_id):
        """Все допустимые адресаты объявленного действия."""
        action = self.actions.get(_text(action_id))
        if action is None:
            return []
        target = action.get("target") or {}
        if target.get("self"):
            node = self.node(self.player_node_id)
            return [self.entity_ref(node)] if node else []
        return self.known_entities(target.get("kinds") or ())

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
        self.player_resources.update(
            {
                "influence": _clamp(
                    0.22 + 0.25 * aptitude + 0.10 * connection
                ),
                "favor": _clamp(0.18 + 0.20 * connection),
                "evidence": 0.0,
                "standing": _clamp(
                    0.28 + 0.25 * aptitude + 0.10 * connection
                ),
            }
        )
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

    def character_relations(self, character_id):
        """Оба направления отношений с персонажем (§2.2).

        `character_to_player` — чувства персонажа (легаси-поля
        `affinity/trust/fear/respect`); `player_to_character` — отношение
        игрока, которое хранится отдельно и не переписывает характер.
        """
        character = self.character(character_id)
        if character is None:
            return {
                "character_to_player": {
                    axis: 0.0 for axis in self.relation_axis_ids
                },
                "player_to_character": {
                    axis: 0.0 for axis in self.relation_axis_ids
                },
            }
        player_view = self.player_relations.get(character["id"]) or {}
        return {
            "character_to_player": {
                axis: _clamp(
                    _as_float(character.get(axis), 0.0), -1.0, 1.0
                )
                for axis in self.relation_axis_ids
            },
            "player_to_character": {
                axis: _clamp(
                    _as_float(player_view.get(axis), 0.0), -1.0, 1.0
                )
                for axis in self.relation_axis_ids
            },
        }

    def player_relation(self, character_id, axis="affinity"):
        return self.character_relations(character_id)[
            "player_to_character"
        ].get(axis, 0.0)

    def _apply_player_view(self, effects, character):
        """Обновить отношение игрока к персонажу (R_player→character).

        Ключи эффекта — `player_affinity`, `player_trust`, `player_fear`,
        `player_respect`. Они не смешиваются с чувствами персонажа:
        принуждение может повысить страх персонажа и одновременно снизить
        расположение игрока, а помощь — наоборот.
        """
        changed = []
        view = self.player_relations.setdefault(character["id"], {})
        for axis in self.relation_axis_ids:
            key = "player_%s" % axis
            if key not in effects:
                continue
            before = _as_float(view.get(axis), 0.0)
            view[axis] = _clamp(
                before + _as_float(effects.get(key)), -1.0, 1.0
            )
            delta = view[axis] - before
            if abs(delta) > 1e-9:
                changed.append(
                    (
                        "вы · %s"
                        % self.relation_axis_labels.get(axis, axis),
                        delta,
                    )
                )
        return changed

    def player_condition(self):
        return {
            "health": float(self.player_health),
            "max_health": float(self.player.max_health),
            "sickness": float(self.player_sickness),
            "wound": float(self.player_wound),
            "alive": bool(self.player_alive),
            "energy": float(self.player_energy),
            "max_energy": float(self.player_max_energy),
            "actions_left": int(self.actions_left),
            "actions_per_day": int(self.actions_per_day),
            "force": float(self.player_force),
            "max_force": float(self.player.max_force),
        }

    def projection_view(self):
        """Ядро и легаси-проекции персонажа в одном стабильном виде."""
        return player_projection_view(self)

    def character_condition(self, character_id):
        character = self.character(character_id)
        if character is None:
            return None
        return {
            "health": float(character["health"]),
            "max_health": float(HEALTH_MAX),
            "sickness": float(character["sickness"]),
            "wound": float(character.get("wound", 0.0)),
            "alive": bool(character["alive"]),
        }

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
            power <= self.collapse_min_power
            or cohesion <= self.collapse_min_cohesion
        )
        power_gap = max(
            0.0,
            (self.collapse_min_power - power)
            / max(self.collapse_min_power, 1e-9),
        )
        cohesion_gap = max(
            0.0,
            (self.collapse_min_cohesion - cohesion)
            / max(self.collapse_min_cohesion, 1e-9),
        )
        return {
            "node_id": node["id"],
            "power": power,
            "cohesion": cohesion,
            "legitimacy": legitimacy,
            "strain": bool(strain),
            "deep_risk": bool(
                legitimacy <= self.collapse_legitimacy and strain
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
