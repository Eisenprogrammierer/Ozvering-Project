from __future__ import annotations

"""Кампания взаимодействия автоматов.

Модуль не знает о «красных» и «синих», ротах или отделениях. Единица
симуляции — фракция-автомат: у неё есть состояние (assets), организация
участников (``OrganizationRuntime``) и набор работ, которыми она действует
на другие автоматы. Победа и поражение задаются данными шаблона.
"""

from dataclasses import dataclass, field
import logging
import math
import random
from typing import Dict, Iterable, List, Mapping, Optional

import warfare as W
from organizations.model import OrganizationParameters
from organizations.runtime import OrganizationRuntime

from .errors import CampaignError

logger = logging.getLogger(__name__)


class AutomataCampaignError(CampaignError):
    pass


MODEL_DEFAULTS = {
    "success_base": 0.0,
    "success_slope": 1.6,
    "cooldown_turns": 0,
    "asset_relax": 0.03,
    "effect_scale": 1.0,
    "organization_cohesion": 0.06,
    "organization_legitimacy": 0.04,
    "organization_supply_drain": 0.006,
    "organization_fear": 0.03,
    "organization_morale": 0.002,
    "collapse_streak": 3,
}


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


def _sigmoid(value):
    value = max(-60.0, min(60.0, _number(value, 0.0)))
    return 1.0 / (1.0 + math.exp(-value))


def _as_mapping(value):
    return value if isinstance(value, Mapping) else {}


def _nested_tuple(value):
    """Вернуть вложенные списки JSON обратно в кортежи для ``random``."""
    if isinstance(value, (list, tuple)):
        return tuple(_nested_tuple(item) for item in value)
    return value


def _organization_parameters(data):
    """Собрать параметры организации из данных, не теряя значения по умолчанию."""
    overrides = _as_mapping(data)
    defaults = OrganizationParameters()
    values = {}
    for name in OrganizationParameters.__dataclass_fields__:
        if name not in overrides:
            continue
        default = getattr(defaults, name)
        if isinstance(default, int) and not isinstance(default, bool):
            values[name] = max(1, int(_number(overrides[name], default)))
        else:
            values[name] = _number(overrides[name], default)
    try:
        return OrganizationParameters(**values)
    except (TypeError, ValueError):
        return defaults


def _preset_data(preset):
    if preset is None:
        raise AutomataCampaignError("не передан пресет кампании")
    if hasattr(preset, "as_dict"):
        return dict(preset.as_dict())
    if isinstance(preset, Mapping):
        return dict(preset)
    raise AutomataCampaignError("не удалось распознать пресет кампании")


def _character_from_record(record, seed):
    character = W.Character(
        record.get("name") or "Участник",
        record.get("side"),
        seed=int(record.get("seed", seed)),
        archetype=record.get("archetype") or "citizen",
        role=record.get("post_id") or record.get("role") or "citizen",
    )
    for need, value in _as_mapping(record.get("needs")).items():
        if need in character.needs:
            character.needs[need] = _clamp(value)
    character.desires = character.weighted_urgency()
    if record.get("morale") is not None:
        character.morale = max(0.0, min(100.0, _number(record.get("morale"), character.morale)))
    character.campaign_id = record.get("id")
    character.campaign_faction_id = record.get("faction_id")
    character.campaign_post = record.get("post")
    character.campaign_role_id = record.get("campaign_role_id", "")
    character.campaign_leader = bool(record.get("is_faction_leader"))
    return character


@dataclass
class FactionRuntime:
    side: str
    id: str
    name: str
    record: dict
    characters: list = field(default_factory=list)
    organization: Optional[OrganizationRuntime] = None
    assets: Dict[str, float] = field(default_factory=dict)
    baseline_assets: Dict[str, float] = field(default_factory=dict)
    income: Dict[str, float] = field(default_factory=dict)
    score_assets: Dict[str, float] = field(default_factory=dict)
    actions: List[dict] = field(default_factory=list)
    cooldowns: Dict[str, int] = field(default_factory=dict)
    low_streaks: Dict[str, int] = field(default_factory=dict)
    organization_snapshot: dict = field(default_factory=dict)
    dissolved: bool = False

    def asset(self, key, default=0.0):
        return _number(self.assets.get(str(key), default), default)

    def set_asset(self, key, value):
        self.assets[str(key)] = _clamp(value)

    def add_asset(self, key, delta):
        self.set_asset(key, self.asset(key) + _number(delta, 0.0))

    def action(self, action_id):
        for action in self.actions:
            if str(action.get("id")) == str(action_id):
                return action
        return None

    def score(self):
        """Взвешенная оценка целей фракции из данных шаблона.

        Без ``score_assets`` остаётся среднее по всем активам — совместимый
        путь для старых пресетов. Веса задаются в данных, потому что у
        Империи, Республики, культа и корпорации разные цели.
        """
        weights = {
            str(key): _number(value, 0.0)
            for key, value in self.score_assets.items()
        }
        total_weight = sum(abs(value) for value in weights.values())
        if total_weight <= 0.0:
            values = list(self.assets.values())
            if not values:
                return 0.0
            return sum(values) / float(len(values))
        return sum(
            weight * self.asset(key) for key, weight in weights.items()
        ) / total_weight

    def progress(self):
        """Насколько фракция продвинулась к своим целям от старта.

        Абсолютные активы дают преимущество тому, кто уже силён. Для
        кампаний, где игрок заведомо слабее в ресурсах, сравнивается
        изменение взвешенной цели. ``0.5`` — стартовый уровень.
        """
        weights = {
            str(key): _number(value, 0.0)
            for key, value in self.score_assets.items()
        }
        total_weight = sum(abs(value) for value in weights.values())
        if total_weight <= 0.0:
            return 0.5
        delta = sum(
            weight
            * (
                self.asset(key)
                - _number(self.baseline_assets.get(key), 0.0)
            )
            for key, weight in weights.items()
        ) / total_weight
        return _clamp(0.5 + delta)

    def snapshot(self):
        analysis = self.organization.analysis if self.organization else None
        stored = self.organization_snapshot or {}
        original = len(self.characters)
        if analysis is not None:
            initial = original or int(analysis.initial_count)
            active = int(analysis.active_count)
            willing_count = int(analysis.willing_count)
            willing_share = (
                willing_count / float(initial) if initial else 0.0
            )
        else:
            initial = int(_number(stored.get("initial_count"), original))
            active = int(_number(stored.get("active_count"), initial))
            willing_count = int(_number(stored.get("willing_count"), active))
            willing_share = _clamp(
                stored.get(
                    "willing_share",
                    willing_count / float(initial) if initial else 0.0,
                )
            )
        return {
            "side": self.side,
            "id": self.id,
            "name": self.name,
            "assets": {key: round(_clamp(value), 6) for key, value in self.assets.items()},
            "score": round(self.score(), 6),
            "progress": round(self.progress(), 6),
            "score_assets": {
                key: round(_number(value), 6)
                for key, value in self.score_assets.items()
            },
            "actions": [str(item.get("id")) for item in self.actions],
            "cooldowns": {key: int(value) for key, value in self.cooldowns.items()},
            "dissolved": bool(self.dissolved),
            "organization": dict(stored),
            "willing_share": round(_clamp(willing_share), 6),
            "willing_count": int(willing_count),
            "active_count": int(active),
            "initial_count": int(initial),
            "priority_need": (
                analysis.priority_need
                if analysis
                else stored.get("priority_need")
            ),
            "archetype": (
                analysis.archetype if analysis else stored.get("archetype", "—")
            ),
            "level": (
                int(analysis.level)
                if analysis
                else int(_number(stored.get("level"), 0))
            ),
        }


class AutomataCampaign:

    def __init__(self, preset, seed=None, snapshot=None):
        data = _preset_data(preset)
        self.data = data
        scenario = _as_mapping(data.get("scenario"))
        self.mode = str(scenario.get("mode") or "automata")
        self.title = str(data.get("title") or "Кампания автоматов")
        self.preset_id = str(data.get("preset_id") or data.get("template_id") or "")
        self.seed = int(_number(seed if seed is not None else data.get("seed"), 7))
        self.rng = random.Random(self.seed)
        self.max_turns = max(1, int(_number(scenario.get("turns"), 72)))
        self.player_side = str(scenario.get("player_side") or "red")
        self.rival_side = str(scenario.get("enemy_side") or "blue")
        self.model = dict(MODEL_DEFAULTS)
        self.model.update(
            {
                str(key): _number(value, self.model.get(str(key), 0.0))
                for key, value in _as_mapping(scenario.get("model")).items()
            }
        )
        self.outcome_rules = dict(_as_mapping(scenario.get("outcome")))
        self.upkeep = {
            str(key): _number(value, 0.0)
            for key, value in _as_mapping(scenario.get("upkeep")).items()
        }
        self._rivals = {
            str(key): str(value)
            for key, value in _as_mapping(scenario.get("rivals")).items()
        }
        self.turn = 0
        self.outcome = None
        self.finished = False
        self.log = []
        self.events = []
        self.history = []
        self.factions: Dict[str, FactionRuntime] = {}
        self._character_index = {}
        self._build_factions(data)
        if snapshot:
            self.load_snapshot(snapshot)

    # ------------------------------------------------------------------
    # Построение
    # ------------------------------------------------------------------
    def _build_factions(self, data):
        characters = list(data.get("characters") or ())
        organizations = {
            str(item.get("id")): item
            for item in (data.get("organizations") or ())
            if item.get("id")
        }
        for index, faction in enumerate(data.get("factions") or ()):
            if not isinstance(faction, Mapping):
                continue
            side = str(faction.get("side") or "")
            if not side:
                continue
            faction_id = str(faction.get("id") or side)
            own_records = [
                item for item in characters if item.get("side") == side
            ]
            specs = []
            for record in own_records:
                spec = _character_from_record(
                    record,
                    self.seed + index * 1009 + len(specs) * 17,
                )
                specs.append(spec)
                self._character_index[str(record.get("id"))] = spec
            organization_id = str(faction.get("organization_id") or "")
            organization_record = organizations.get(organization_id, {})
            runtime_cfg = _as_mapping(organization_record.get("runtime"))
            leader = next(
                (item for item in own_records if item.get("is_faction_leader")),
                own_records[0] if own_records else {},
            )
            parameters = _organization_parameters(
                runtime_cfg.get("parameters")
            )
            organization = None
            if specs:
                organization = OrganizationRuntime(
                    name=str(
                        organization_record.get("name")
                        or faction.get("name")
                        or faction_id
                    ),
                    side=side,
                    characters=specs,
                    parameters=parameters,
                    complete_weight=_clamp(
                        runtime_cfg.get("complete_weight", 0.84)
                    ),
                    leader_id=str(
                        runtime_cfg.get("leader_id")
                        or leader.get("name")
                        or ""
                    )
                    or None,
                    satisfaction_per_tick=_number(
                        runtime_cfg.get("satisfaction_per_tick"), 0.03
                    ),
                    contribution_cost=_number(
                        runtime_cfg.get("contribution_cost"), 0.08
                    ),
                    coercion_factor=_number(
                        runtime_cfg.get("coercion_factor"), 0.5
                    ),
                    leader_morale_bonus=_number(
                        runtime_cfg.get("leader_morale_bonus"), 10.0
                    ),
                    allow_rejoin=bool(
                        runtime_cfg.get("allow_rejoin", False)
                    ),
                    jitter_salt=organization_id or faction_id,
                )
            assets = {
                str(key): _clamp(value)
                for key, value in _as_mapping(faction.get("assets")).items()
            }
            runtime = FactionRuntime(
                side=side,
                id=faction_id,
                name=str(faction.get("name") or faction_id),
                record=dict(faction),
                characters=specs,
                organization=organization,
                assets=assets,
                baseline_assets=dict(assets),
                income={
                    str(key): _number(value, 0.0)
                    for key, value in _as_mapping(
                        faction.get("income")
                    ).items()
                },
                score_assets={
                    str(key): _number(value, 0.0)
                    for key, value in _as_mapping(
                        faction.get("score_assets")
                    ).items()
                },
                actions=[
                    dict(item)
                    for item in (faction.get("actions") or ())
                    if isinstance(item, Mapping) and item.get("id")
                ],
            )
            self.factions[side] = runtime

    # ------------------------------------------------------------------
    # Доступ и проверки
    # ------------------------------------------------------------------
    def faction(self, side):
        return self.factions.get(str(side or ""))

    @property
    def player(self):
        return self.faction(self.player_side)

    @property
    def rival(self):
        return self.faction(self.rival_side)

    def rival_of(self, side):
        side = str(side or "")
        explicit = self._rivals.get(side)
        if explicit:
            return explicit
        faction = self.faction(side)
        if faction is not None:
            explicit = str(faction.record.get("rival_side") or "")
            if explicit:
                return explicit
        if side == self.rival_side:
            return self.player_side
        return self.rival_side

    def other_sides(self, side):
        return [item for item in self.factions if item != str(side or "")]

    def _cooldown_left(self, faction, action, turn=None):
        """Сколько ходов ещё нельзя повторять работу.

        ``cooldown=1`` означает один пропущенный ход: работа, использованная
        на ходе ``t``, снова доступна на ходе ``t + 2``. Так значение
        совпадает с текстом «перезарядка ещё N» и одинаково трактуется для
        игрока и для автоматического выбора.
        """
        cooldown = int(
            _number(action.get("cooldown", self.model.get("cooldown_turns")), 0)
        )
        last = faction.cooldowns.get(str(action.get("id")))
        if cooldown <= 0 or last is None:
            return 0
        current = self.turn if turn is None else int(turn)
        return max(0, cooldown + 1 - (current - int(last)))

    def action_options(self, side, turn=None):
        faction = self.faction(side)
        if faction is None or faction.dissolved:
            return []
        options = []
        for action in faction.actions:
            cost = _as_mapping(action.get("cost"))
            affordable = all(
                faction.asset(key) + 1e-9 >= _number(value, 0.0)
                for key, value in cost.items()
            )
            left = self._cooldown_left(faction, action, turn=turn)
            options.append(
                {
                    "action": action,
                    "id": str(action.get("id")),
                    "label": str(action.get("label") or action.get("id")),
                    "enabled": bool(affordable and left <= 0),
                    "reason": (
                        "не хватает состояния"
                        if not affordable
                        else ("перезарядка ещё %d" % left if left > 0 else "")
                    ),
                }
            )
        return options

    def available_actions(self, side):
        return [
            item["id"]
            for item in self.action_options(side)
            if item.get("enabled")
        ]

    def _target_side(self, side, action, target=None):
        faction = self.faction(side)
        if faction is None:
            return None
        requested = str(target or action.get("target") or "rival")
        if requested in ("self", faction.id, faction.side):
            return faction.side
        if requested == "rival":
            return self.rival_of(side)
        if requested in ("any", "all", "all_rivals", "other"):
            others = self.other_sides(side)
            return others[0] if others else None
        if requested == "strongest":
            others = [self.faction(item) for item in self.other_sides(side)]
            others = [item for item in others if item is not None]
            return max(others, key=lambda item: (item.score(), item.side)).side if others else None
        if requested == "weakest":
            others = [self.faction(item) for item in self.other_sides(side)]
            others = [item for item in others if item is not None]
            return min(others, key=lambda item: (item.score(), item.side)).side if others else None
        if requested in self.factions:
            return requested
        for item in self.factions.values():
            if requested in (item.id, item.record.get("name")):
                return item.side
        return self.rival_of(side)

    def _apply_branch(self, actor, target, branch):
        branch = _as_mapping(branch)
        scale = self.model["effect_scale"]
        for key, value in _as_mapping(branch.get("self")).items():
            actor.add_asset(key, _number(value) * scale)
        for key, value in _as_mapping(branch.get("target")).items():
            if target is not None:
                target.add_asset(key, _number(value) * scale)
        for scope, effects in _as_mapping(branch.get("needs")).items():
            recipient = actor if scope == "self" else target
            if recipient is None:
                continue
            for key, value in _as_mapping(effects).items():
                for character in recipient.characters:
                    if key in character.needs:
                        character.needs[key] = _clamp(
                            character.needs.get(key, 0.0) + _number(value)
                        )

    def _log_work(self, result):
        self.log.append(result)
        detail = (
            "ход %d: %s → %s работой «%s» (%s); шанс %.3f, бросок %.3f, "
            "успех=%s; атака %s=%.3f против %s=%.3f"
            % (
                result["turn"],
                result["actor_name"],
                result["target_name"],
                result["label"],
                result["form"],
                result["chance"],
                result["roll"],
                "да" if result["success"] else "нет",
                result["attack_asset"],
                result["attack_value"],
                result["defense_asset"],
                result["defense_value"],
            )
        )
        if result.get("reason"):
            detail += "; причина: %s" % result["reason"]
        self.events.append(
            {
                "turn": result["turn"],
                "kind": "work",
                "text": detail,
                "side": result["actor_side"],
                "actor": result["actor_name"],
            }
        )
        if len(self.events) > 400:
            self.events = self.events[-400:]

    # ------------------------------------------------------------------
    # Работа
    # ------------------------------------------------------------------
    def perform(self, side, action_id, target=None):
        actor = self.faction(side)
        if actor is None or actor.dissolved:
            return {"ok": False, "reason": "фракция недоступна"}
        action = actor.action(action_id)
        if action is None:
            return {"ok": False, "reason": "действие не найдено"}
        if action_id not in self.available_actions(side):
            option = next(
                (
                    item
                    for item in self.action_options(side)
                    if item["id"] == str(action_id)
                ),
                {},
            )
            return {
                "ok": False,
                "reason": option.get("reason") or "действие недоступно",
            }
        target_side = self._target_side(side, action, target=target)
        target_faction = self.faction(target_side)
        if target_faction is None:
            return {"ok": False, "reason": "нет цели"}
        cost = _as_mapping(action.get("cost"))
        for key, value in cost.items():
            actor.add_asset(key, -_number(value))
        attack_asset = str(action.get("attack_asset") or "influence")
        defense_asset = str(action.get("defense_asset") or "cohesion")
        attack_value = actor.asset(attack_asset)
        defense_value = (
            actor.asset(defense_asset)
            if target_faction.side == actor.side
            else target_faction.asset(defense_asset)
        )
        base = _number(action.get("base"), self.model["success_base"])
        slope = _number(action.get("slope"), self.model["success_slope"])
        chance = _sigmoid(base + slope * (attack_value - defense_value))
        roll = self.rng.random()
        success = roll < chance
        branch = action.get("effects") if success else action.get("failure")
        self._apply_branch(actor, target_faction, branch)
        cooldown = int(
            _number(action.get("cooldown", self.model.get("cooldown_turns")), 0)
        )
        if cooldown > 0:
            actor.cooldowns[str(action_id)] = self.turn
        result = {
            "ok": True,
            "turn": self.turn,
            "actor_side": actor.side,
            "actor_id": actor.id,
            "actor_name": actor.name,
            "target_side": target_faction.side,
            "target_id": target_faction.id,
            "target_name": target_faction.name,
            "action_id": str(action_id),
            "label": str(action.get("label") or action_id),
            "form": str(action.get("form") or "work"),
            "attack_asset": attack_asset,
            "attack_value": round(attack_value, 6),
            "defense_asset": defense_asset,
            "defense_value": round(defense_value, 6),
            "chance": round(chance, 6),
            "roll": round(roll, 6),
            "success": bool(success),
            "cost": {key: round(_number(value), 6) for key, value in cost.items()},
            "self_after": {
                key: round(_clamp(value), 6) for key, value in actor.assets.items()
            },
            "target_after": {
                key: round(_clamp(value), 6)
                for key, value in target_faction.assets.items()
            },
            "text": str(
                (branch or {}).get("text")
                if isinstance(branch, Mapping) and branch.get("text")
                else action.get("text")
                or ""
            ),
        }
        self._log_work(result)
        self._check_outcome()
        return result

    # ------------------------------------------------------------------
    # Автоматический выбор
    # ------------------------------------------------------------------
    def auto_action(self, side, turn=None):
        options = [
            item
            for item in self.action_options(side, turn=turn)
            if item["enabled"]
        ]
        if not options:
            return None
        faction = self.faction(side)
        if faction is None:
            return None
        weights = []
        for option in options:
            action = option["action"]
            weight = max(0.01, _number(action.get("ai_priority"), 1.0))
            target_side = self._target_side(side, action)
            target = self.faction(target_side)
            if target is not None:
                defense = target.asset(
                    str(action.get("defense_asset") or "cohesion")
                )
                weight *= 1.0 + max(0.0, 0.5 - defense)
            weights.append(weight)
        total = sum(weights)
        pick = self.rng.random() * total
        upto = 0.0
        for option, weight in zip(options, weights):
            upto += weight
            if pick <= upto:
                return option["id"]
        return options[-1]["id"]

    # ------------------------------------------------------------------
    # Ход
    # ------------------------------------------------------------------
    def advance(self, player_action=None, target=None):
        if self.finished:
            return self.snapshot()
        self.turn += 1
        acted = set()
        if player_action:
            result = self.perform(self.player_side, player_action, target=target)
            if result.get("ok"):
                acted.add(self.player_side)
        for side in list(self.factions):
            if side in acted or self.finished:
                continue
            action_id = self.auto_action(side)
            if action_id is None:
                continue
            self.perform(side, action_id)
        self._tick_organizations()
        self._check_outcome()
        self.history.append(self.snapshot())
        return self.snapshot()

    def run(self, turns=None, player_action=None, target=None):
        limit = self.max_turns if turns is None else max(0, int(turns))
        for _ in range(limit):
            if self.finished:
                break
            # Если игрок не задал работу явно, ход выбирается внутри
            # ``advance`` уже на новом ходе — так кулдауны игрока и ИИ
            # отсчитываются одинаково.
            self.advance(player_action=player_action, target=target)
        return self.snapshot()

    def _tick_organizations(self):
        for faction in self.factions.values():
            if faction.organization is None:
                continue
            snapshot = faction.organization.tick(turn=self.turn)
            # Доля участия считается от исходного состава фракции, а не от
            # текущего пула: иначе после выхода половины участников
            # willing_share снова становится 1.0 и организация продолжает
            # поддерживать легитимность так, будто ничего не произошло.
            initial = max(
                1,
                len(faction.characters)
                or int(_number(snapshot.get("initial_count"), 1)),
            )
            active = int(_number(snapshot.get("active_count"), initial))
            willing_count = int(_number(snapshot.get("willing_count"), active))
            willing = _clamp(willing_count / float(initial))
            share = _clamp(active / float(initial))
            snapshot = dict(snapshot)
            snapshot.update(
                {
                    "initial_count": initial,
                    "active_count": active,
                    "willing_count": willing_count,
                    "willing_share": willing,
                }
            )
            faction.organization_snapshot = snapshot
            if not snapshot.get("active", True):
                faction.dissolved = True
            faction.add_asset(
                "cohesion",
                self.model["organization_cohesion"] * (willing - 0.5),
            )
            faction.add_asset(
                "legitimacy",
                self.model["organization_legitimacy"] * (share - 0.5),
            )
            faction.add_asset(
                "supply", -self.model["organization_supply_drain"]
            )
            mode_weights = _as_mapping(snapshot.get("mode_weights"))
            faction.add_asset(
                "fear",
                self.model["organization_fear"]
                * _number(mode_weights.get("order"), 0.0),
            )
            faction.add_asset(
                "morale",
                self.model["organization_morale"] * share,
            )
            relax = self.model["asset_relax"]
            for key, baseline in faction.baseline_assets.items():
                faction.add_asset(
                    key, relax * (baseline - faction.asset(key))
                )
            for key, value in faction.income.items():
                faction.add_asset(key, value)
            for key, value in self.upkeep.items():
                faction.add_asset(key, -value)

    def _check_outcome(self):
        if self.outcome is not None:
            return
        rules = self.outcome_rules
        streak_limit = max(
            1, int(_number(rules.get("streak_turns"), self.model["collapse_streak"]))
        )
        for side, thresholds in _as_mapping(rules.get("defeat")).items():
            faction = self.faction(side)
            if faction is None:
                continue
            for asset, threshold in _as_mapping(thresholds).items():
                key = "%s:%s" % (side, asset)
                if faction.asset(asset) <= _number(threshold, 0.0) + 1e-9:
                    faction.low_streaks[key] = faction.low_streaks.get(key, 0) + 1
                else:
                    faction.low_streaks[key] = 0
                if faction.low_streaks.get(key, 0) >= streak_limit:
                    self.outcome = "lose" if side == self.player_side else "win"
                    self.finished = True
                    return
        if rules.get("score_margin") is not None and self.turn >= self.max_turns:
            margin = _number(rules.get("score_margin"), 0.0)
            player = self.player
            rival = self.rival
            basis = str(rules.get("score_basis") or "assets")
            if basis == "progress":
                measure = lambda faction: faction.progress()
            else:
                measure = lambda faction: faction.score()
            if player is not None and rival is not None:
                difference = (
                    measure(player)
                    - measure(rival)
                    + _number(rules.get("score_bias"), 0.0)
                )
                if difference > margin:
                    self.outcome = "win"
                elif difference < -margin:
                    self.outcome = "lose"
                else:
                    self.outcome = "stalemate"
                self.finished = True
                return
        if rules.get("stalemate_at_end") and self.turn >= self.max_turns:
            self.outcome = "stalemate"
            self.finished = True

    # ------------------------------------------------------------------
    # Снимки
    # ------------------------------------------------------------------
    def snapshot(self):
        return {
            "preset_id": self.preset_id,
            "title": self.title,
            "turn": self.turn,
            "max_turns": self.max_turns,
            "player_side": self.player_side,
            "rival_side": self.rival_side,
            "outcome": self.outcome,
            "finished": self.finished,
            "factions": {
                side: faction.snapshot() for side, faction in self.factions.items()
            },
            "events": list(self.events[-80:]),
            "log": list(self.log[-80:]),
        }

    to_dict = snapshot

    def save_snapshot(self):
        """Полный снимок для сохранения игры, включая журнал и состояние ГСЧ."""
        data = self.snapshot()
        data["log"] = list(self.log)
        data["events"] = list(self.events)
        data["rng_state"] = _nested_tuple(self.rng.getstate())
        data["seed"] = self.seed
        # ``snapshot()`` округляет активы для интерфейса и журнала. Для
        # точного восстановления сохраняем исходные значения отдельно.
        for side, faction in self.factions.items():
            state = data.get("factions", {}).get(side)
            if isinstance(state, dict):
                state["raw_assets"] = {
                    str(key): float(value)
                    for key, value in faction.assets.items()
                }
                state["low_streaks"] = {
                    str(key): int(value)
                    for key, value in faction.low_streaks.items()
                }
                if faction.organization is not None:
                    state["organization_state"] = (
                        faction.organization.state_dict()
                    )
        return data

    def load_snapshot(self, snapshot):
        snapshot = _as_mapping(snapshot)
        if not snapshot:
            return
        self.turn = int(_number(snapshot.get("turn"), self.turn))
        self.max_turns = max(
            1, int(_number(snapshot.get("max_turns"), self.max_turns))
        )
        self.outcome = snapshot.get("outcome")
        self.finished = bool(snapshot.get("finished", False))
        rng_state = snapshot.get("rng_state")
        if rng_state:
            try:
                self.rng.setstate(_nested_tuple(rng_state))
            except (TypeError, ValueError):
                logger.warning(
                    "Состояние ГСЧ кампании автоматов не восстановлено"
                )
        for side, state in _as_mapping(snapshot.get("factions")).items():
            faction = self.faction(side)
            if faction is None:
                continue
            faction.assets = {
                str(key): _clamp(value)
                for key, value in _as_mapping(
                    state.get("raw_assets") or state.get("assets")
                ).items()
            }
            faction.cooldowns = {
                str(key): int(_number(value))
                for key, value in _as_mapping(state.get("cooldowns")).items()
            }
            faction.dissolved = bool(state.get("dissolved", False))
            faction.low_streaks = {
                str(key): int(_number(value))
                for key, value in _as_mapping(
                    state.get("low_streaks")
                ).items()
            }
            faction.organization_snapshot = dict(
                _as_mapping(state.get("organization"))
            )
            if faction.organization is not None:
                faction.organization.load_state_dict(
                    _as_mapping(state.get("organization_state"))
                )
        self.events = list(snapshot.get("events") or [])
        self.log = list(snapshot.get("log") or [])
        if self.outcome:
            self.finished = True

    # ------------------------------------------------------------------
    # Диагностика математической модели
    # ------------------------------------------------------------------
    def audit(self):
        anomalies = []
        seen = set()
        for side, faction in self.factions.items():
            for key, value in faction.assets.items():
                token = (side, key)
                if not math.isfinite(_number(value)):
                    anomalies.append("%s/%s: не конечное значение" % token)
                if not 0.0 <= _number(value) <= 1.0:
                    anomalies.append(
                        "%s/%s: %.6f вне диапазона [0,1]" % (side, key, _number(value))
                    )
                seen.add(token)
            snapshot = faction.organization_snapshot
            if snapshot:
                active = int(_number(snapshot.get("active_count"), 0))
                initial = int(_number(snapshot.get("initial_count"), 0))
                if active > initial:
                    anomalies.append(
                        "%s: активных %d больше исходных %d" % (side, active, initial)
                    )
                willing = _number(snapshot.get("willing_share"), 0.0)
                if not 0.0 <= willing <= 1.0:
                    anomalies.append(
                        "%s: willing_share %.6f вне [0,1]" % (side, willing)
                    )
            if faction.dissolved and not snapshot.get("active", True):
                continue
        for item in self.log:
            if item.get("ok") and not 0.0 <= _number(item.get("chance"), 0.0) <= 1.0:
                anomalies.append(
                    "работа %s: шанс %.6f вне [0,1]"
                    % (item.get("action_id"), _number(item.get("chance")))
                )
        return anomalies


__all__ = [
    "AutomataCampaign",
    "AutomataCampaignError",
    "FactionRuntime",
    "MODEL_DEFAULTS",
]
