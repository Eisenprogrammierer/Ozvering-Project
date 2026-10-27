from __future__ import annotations

import warfare as W
from .log_journal import get_logger
from .traits import (
    trait_modifiers,
    trait_label,
    trait_summary,
    normalize_trait,
)

logger = get_logger("view.needs")

TICK_SECONDS = 300


NEED_ACTIONS = {
    "feed": {
        "label": "Довольствие",
        "short": "Кормить",
        "cost": {"food": 4},
        "effects": {"hunger": 0.34, "thirst": 0.10},
        "morale": 0.8,
        "cooldown": 7200,
        "hint": "Горячая пища и сухпай: голод и жажда.",
    },
    "water": {
        "label": "Водоснабжение",
        "short": "Поить",
        "cost": {"water": 3},
        "effects": {"thirst": 0.46, "health": 0.04},
        "morale": 0.3,
        "cooldown": 3600,
        "hint": "Выдать воду: жажда и обезвоживание.",
    },
    "rest": {
        "label": "Отдых",
        "short": "Отдых",
        "cost": {},
        "effects": {"fatigue": 0.40, "boredom": 0.18, "anxiety": 0.08},
        "morale": 0.6,
        "cooldown": 14400,
        "hint": "Полевой отдых: усталость, скука, тревога.",
    },
    "medical": {
        "label": "Медицина",
        "short": "Медицина",
        "cost": {"medicine": 3},
        "effects": {"health": 0.38, "fear": 0.08},
        "morale": 0.9,
        "cooldown": 10800,
        "hint": "Перевязки и помощь санитара: здоровье и страх.",
    },
    "encourage": {
        "label": "Воодушевление",
        "short": "Воодушевить",
        "cost": {"influence": 2},
        "effects": {
            "fear": 0.18,
            "anxiety": 0.16,
            "status": 0.09,
            "spirituality": 0.08,
        },
        "morale": 2.2,
        "cooldown": 7200,
        "hint": "Слово командира: страх, тревога, статус, дух.",
    },
    "socialize": {
        "label": "Общение",
        "short": "Общение",
        "cost": {"influence": 1},
        "effects": {
            "loneliness": 0.30,
            "friendship": 0.28,
            "love": 0.20,
            "boredom": 0.12,
        },
        "morale": 0.8,
        "cooldown": 10800,
        "hint": "Письма, разговоры, товарищество: одиночество и дружба.",
    },
    "train": {
        "label": "Боевая учёба",
        "short": "Учёба",
        "cost": {"influence": 2},
        "effects": {
            "knowledge": 0.24,
            "skill": 0.22,
            "creativity": 0.10,
            "status": 0.06,
        },
        "morale": 0.6,
        "cooldown": 14400,
        "hint": "Разбор боя и тренировка: знания, умение, творчество.",
    },
    "pray": {
        "label": "Духовная поддержка",
        "short": "Молитва",
        "cost": {"influence": 1},
        "effects": {
            "spirituality": 0.30,
            "fear": 0.10,
            "anxiety": 0.08,
        },
        "morale": 0.9,
        "cooldown": 10800,
        "hint": "Молитва и тишина: духовность, страх, тревога.",
    },
    "letters": {
        "label": "Письма домой",
        "short": "Письма",
        "cost": {},
        "effects": {
            "love": 0.24,
            "loneliness": 0.18,
            "reproduction": 0.16,
            "friendship": 0.08,
        },
        "morale": 1.0,
        "cooldown": 14400,
        "hint": "Письма и мысли о близких: любовь, одиночество, семья.",
    },
}

ACTION_ORDER = (
    "feed",
    "water",
    "rest",
    "medical",
    "encourage",
    "socialize",
    "train",
    "pray",
    "letters",
)


PLAYER_NEED_ACTIONS = {}
for _action_id in ACTION_ORDER:
    _definition = dict(NEED_ACTIONS[_action_id])
    _definition["cost"] = {
        key: max(1, int(round(value * 0.25)))
        for key, value in NEED_ACTIONS[_action_id].get("cost", {}).items()
    }
    _definition["cooldown"] = max(
        600, int(NEED_ACTIONS[_action_id].get("cooldown", 0) * 0.5)
    )
    PLAYER_NEED_ACTIONS[_action_id] = _definition

SUPPLY_LABELS = {
    "food": "Продовольствие",
    "water": "Вода",
    "medicine": "Медикаменты",
    "influence": "Влияние",
    "ammo": "Боеприпасы",
    "fuel": "Горючее",
    "engineering": "Инженерное",
    "morale": "Предметы морали",
}


NEED_LABELS = {
    "hunger": "Голод",
    "thirst": "Жажда",
    "fatigue": "Усталость",
    "health": "Здоровье",
    "fear": "Страх",
    "anxiety": "Тревога",
    "loneliness": "Одиночество",
    "reproduction": "Репродукция",
    "knowledge": "Знания",
    "creativity": "Творчество",
    "boredom": "Скука",
    "status": "Статус",
    "spirituality": "Духовность",
    "skill": "Умение",
    "love": "Любовь",
    "friendship": "Дружба",
}


NEED_SOURCES = {
    "hunger": "Довольствие, утреннее довольствие лагеря",
    "thirst": "Водоснабжение, довольствие",
    "fatigue": "Отдых, ночной сон, утреннее довольствие",
    "health": "Медицина, водоснабжение, сон",
    "fear": "Воодушевление, молитва, медицина",
    "anxiety": "Воодушевление, отдых, молитва, сон",
    "loneliness": "Общение, письма домой",
    "reproduction": "Письма домой",
    "knowledge": "Боевая учёба",
    "creativity": "Боевая учёба",
    "boredom": "Отдых, общение, утреннее довольствие",
    "status": "Воодушевление, учёба, ночное дежурство",
    "spirituality": "Молитва, воодушевление",
    "skill": "Боевая учёба",
    "love": "Общение, письма домой",
    "friendship": "Общение, письма домой",
}


class NeedsSystem:

    def __init__(self, state, supplies=None):
        self.state = state
        defaults = {
            "food": 120,
            "water": 140,
            "medicine": 60,
            "influence": 30,
            "ammo": 160,
            "fuel": 90,
            "engineering": 35,
            "morale": 45,
        }
        if supplies is None:
            supplies = {}

        for key, value in defaults.items():
            supplies.setdefault(key, value)
        self.supplies = supplies
        self.state.supplies = self.supplies
        self.cooldowns = {}

        self.commander = W.Character(
            "Командир",
            getattr(self.state, "player_side", "red"),
            seed=90210,
            archetype="veteran",
        )

        self.commander.trait = normalize_trait(
            getattr(self.state, "commander_trait", None)
        )
        self.player_cooldowns = {}
        self._death_logged = False

    @property
    def trait(self):
        return normalize_trait(getattr(self.commander, "trait", None))

    @property
    def trait_info(self):
        return {
            "key": self.trait,
            "label": trait_label(self.trait),
            "summary": trait_summary(self.trait),
        }

    def trait_modifiers(self):
        return trait_modifiers(self.trait)

    def set_commander_trait(self, trait):
        key = normalize_trait(trait)
        self.commander.trait = key
        self.state.commander_trait = key
        return key

    def _trait_action_definition(self, action_id):
        base = PLAYER_NEED_ACTIONS[action_id]
        mods = self.trait_modifiers()
        bonus = float(mods.get("action_bonus", {}).get(action_id, 1.0))
        effect_scale = float(mods.get("action_effect", 1.0)) * bonus
        cost_scale = float(mods.get("action_cost", 1.0))
        definition = dict(base)
        definition["effects"] = {
            need: value * effect_scale
            for need, value in base.get("effects", {}).items()
        }
        definition["morale"] = float(base.get("morale", 0.0)) * effect_scale
        definition["cost"] = {
            key: max(1, int(round(value * cost_scale)))
            for key, value in base.get("cost", {}).items()
        }
        definition["cooldown"] = max(
            600,
            int(
                round(
                    base.get("cooldown", 0)
                    * float(mods.get("action_cooldown", 1.0))
                )
            ),
        )
        return definition

    @property
    def player_dead(self):
        return bool(getattr(self.commander, "is_dead", False))

    def _key(self, idx, action_id):
        return "%s:%s" % (idx, action_id)

    def _player_key(self, action_id):
        return "commander:%s" % action_id

    def cooldown_remaining(self, idx, action_id):
        return int(self.cooldowns.get(self._key(idx, action_id), 0))

    def can_apply(self, idx, action_id):
        det = self.state.det_at(idx)
        definition = NEED_ACTIONS.get(action_id)
        if det is None or definition is None or not det.characters:
            return False, "нет подразделения"
        if self.cooldown_remaining(idx, action_id) > 0:
            minutes = (self.cooldown_remaining(idx, action_id) + 59) // 60
            return False, "кулдаун %d мин" % minutes
        for resource, amount in definition["cost"].items():
            if self.supplies.get(resource, 0) < amount:
                return False, "нет: %s" % SUPPLY_LABELS.get(resource, resource)
        return True, ""

    def apply(self, idx, action_id):
        ok, reason = self.can_apply(idx, action_id)
        if not ok:
            return {"ok": False, "reason": reason}
        det = self.state.det_at(idx)
        definition = NEED_ACTIONS[action_id]
        for resource, amount in definition["cost"].items():
            self.supplies[resource] = max(
                0, self.supplies.get(resource, 0) - amount
            )
        restored = det.satisfy_needs(
            definition["effects"], morale_bonus=definition.get("morale", 0.0)
        )
        self.cooldowns[self._key(idx, action_id)] = int(
            definition.get("cooldown", 0)
        )
        count = max(1, len(det.characters))
        self.state.log_event(
            idx,
            "%s: %s"
            % (
                definition["label"],
                ", ".join(
                    "%s −%.0f%%"
                    % (W.NEEDS_RU.get(need, need), value * 100 / count)
                    for need, value in restored.items()
                )
                or "без эффекта",
            ),
        )
        logger.info(
            "Потребности: %s для %s, ресурсы=%s",
            definition["label"],
            det.name,
            self.supplies,
        )
        return {
            "ok": True,
            "restored": restored,
            "supplies": dict(self.supplies),
        }

    def status(self, idx):
        result = {}
        for action_id in ACTION_ORDER:
            ok, reason = self.can_apply(idx, action_id)
            result[action_id] = {
                "ok": ok,
                "reason": reason,
                "cooldown": self.cooldown_remaining(idx, action_id),
                "label": NEED_ACTIONS[action_id]["label"],
                "hint": NEED_ACTIONS[action_id].get("hint", ""),
                "cost": dict(NEED_ACTIONS[action_id].get("cost", {})),
                "effects": dict(NEED_ACTIONS[action_id].get("effects", {})),
            }
        return result

    def player_needs_summary(self):
        return self.commander.needs_summary()

    def player_cooldown_remaining(self, action_id):
        return int(self.player_cooldowns.get(self._player_key(action_id), 0))

    def can_apply_player(self, action_id):
        definition = (
            self._trait_action_definition(action_id)
            if action_id in PLAYER_NEED_ACTIONS
            else None
        )
        if definition is None:
            return False, "неизвестное действие"
        remaining = self.player_cooldown_remaining(action_id)
        if remaining > 0:
            minutes = (remaining + 59) // 60
            return False, "кулдаун %d мин" % minutes
        for resource, amount in definition["cost"].items():
            if self.supplies.get(resource, 0) < amount:
                return False, "нет: %s" % SUPPLY_LABELS.get(resource, resource)
        return True, ""

    def apply_player(self, action_id):
        ok, reason = self.can_apply_player(action_id)
        if not ok:
            return {"ok": False, "reason": reason}
        definition = self._trait_action_definition(action_id)
        for resource, amount in definition["cost"].items():
            self.supplies[resource] = max(
                0, self.supplies.get(resource, 0) - amount
            )
        restored = self.commander.satisfy(
            definition["effects"], morale_bonus=definition.get("morale", 0.0)
        )
        self.player_cooldowns[self._player_key(action_id)] = int(
            definition.get("cooldown", 0)
        )
        self.state.log_event(
            self.state.player_idx,
            "Лично: %s" % definition["label"],
        )
        logger.info(
            "Личные потребности: %s, ресурсы=%s",
            definition["label"],
            self.supplies,
        )
        return {
            "ok": True,
            "restored": restored,
            "supplies": dict(self.supplies),
        }

    def status_player(self):
        result = {}
        for action_id in ACTION_ORDER:
            ok, reason = self.can_apply_player(action_id)
            definition = self._trait_action_definition(action_id)
            result[action_id] = {
                "ok": ok,
                "reason": reason,
                "cooldown": self.player_cooldown_remaining(action_id),
                "label": definition["label"],
                "hint": definition.get("hint", ""),
                "cost": dict(definition.get("cost", {})),
                "effects": dict(definition.get("effects", {})),
                "morale": float(definition.get("morale", 0.0)),
            }
        return result

    def _tick_player(self, seconds, engaged_names):
        if self.player_dead:
            return
        player_side = getattr(self.state, "player_side", "red")
        engaged = set(engaged_names or [])
        under_fire = 0.0
        if engaged:
            player_names = {
                det.name for det in self.state.units if det.side == player_side
            }
            under_fire = 0.20 if player_names & engaged else 0.0
        mods = self.trait_modifiers()
        self.commander.tick_needs(
            in_combat=bool(under_fire),
            under_fire=under_fire,
            supported=0.55,
            seconds=seconds,
            rate_multipliers={
                "fear": mods["fear_rate"],
                "anxiety": mods["anxiety_rate"],
                "fatigue": mods["fatigue_rate"],
                "health": mods["health_rate"],
                "hunger": mods["hunger_rate"],
                "thirst": mods["thirst_rate"],
            },
            morale_baseline_bonus=mods["morale_baseline"],
        )
        self._commander_self_care(seconds)
        if self.player_dead and not self._death_logged:
            self._death_logged = True
            self.state.log_event(
                self.state.player_idx,
                "Командир погиб: здоровье достигло критического значения.",
            )
            logger.warning("Потребности: персонаж игрока погиб")

    def _commander_self_care(self, seconds):
        share = max(0.0, float(seconds)) / 1800.0
        if not share:
            return
        consumption = float(
            self.trait_modifiers().get("supply_consumption", 1.0)
        )
        effects = {}
        food = min(
            self.supplies.get("food", 0.0),
            0.06 * share * consumption,
        )
        if food > 0:
            ratio = food / max(1e-9, 0.06 * share * consumption)
            effects["hunger"] = 0.0045 * share * ratio
            effects["health"] = 0.0004 * share * ratio
            self.supplies["food"] = max(
                0.0, self.supplies.get("food", 0.0) - food
            )
        water = min(
            self.supplies.get("water", 0.0),
            0.10 * share * consumption,
        )
        if water > 0:
            ratio = water / max(1e-9, 0.10 * share * consumption)
            effects["thirst"] = 0.0058 * share * ratio
            effects["health"] = effects.get("health", 0.0) + (
                0.0004 * share * ratio
            )
            self.supplies["water"] = max(
                0.0, self.supplies.get("water", 0.0) - water
            )
        if effects:
            self.commander.satisfy(effects)

    def _apply_trait_morale(self, seconds):
        delta = (
            float(self.trait_modifiers().get("troop_morale_per_day", 0.0))
            * max(0.0, float(seconds))
            / 86400.0
        )
        if not delta:
            return
        player_side = getattr(self.state, "player_side", "red")
        for det in self.state.units:
            if det.side != player_side or not det.characters:
                continue
            for character in det.characters:
                character.morale = max(
                    0.0, min(100.0, character.morale + delta)
                )
            det.refresh_psychology()

    def _satisfy_player(self, effects, morale_bonus=0.0):
        self.commander.satisfy(effects, morale_bonus=morale_bonus)

    def on_tick(self, seconds=TICK_SECONDS, engaged_names=None):
        seconds = max(0, int(seconds))
        for key in list(self.cooldowns):
            self.cooldowns[key] = max(0, self.cooldowns[key] - seconds)
            if self.cooldowns[key] == 0:
                self.cooldowns.pop(key, None)
        for key in list(self.player_cooldowns):
            self.player_cooldowns[key] = max(
                0, self.player_cooldowns[key] - seconds
            )
            if self.player_cooldowns[key] == 0:
                self.player_cooldowns.pop(key, None)

        engaged = set(engaged_names or [])
        player_side = getattr(self.state, "player_side", "red")
        mods = self.trait_modifiers()
        troop_rates = {
            "fear": mods["fear_rate"],
            "anxiety": mods["anxiety_rate"],
            "fatigue": mods["fatigue_rate"],
            "health": mods["health_rate"],
        }
        for det in self.state.units:
            if det.name in engaged or not det.characters:
                continue
            support = det.cohesion * min(1.0, 0.3 + 0.7 * (det.morale / 100.0))
            rested = getattr(det, "ui_order", "") == "rest"
            is_player = det.side == player_side
            for character in det.characters:
                character.tick_needs(
                    in_combat=False,
                    supported=support,
                    rested=rested,
                    seconds=seconds,
                    rate_multipliers=troop_rates if is_player else None,
                )
            det.refresh_psychology()
        self._tick_player(seconds, engaged)
        self._apply_trait_morale(seconds)

    def camp_morning(self):
        for idx in self._player_indices():
            det = self.state.det_at(idx)
            if det is None:
                continue
            det.satisfy_needs(
                {
                    "hunger": 0.26,
                    "thirst": 0.30,
                    "fatigue": 0.18,
                    "health": 0.08,
                    "boredom": 0.12,
                },
                morale_bonus=0.5,
            )
            self.state.log_event(idx, "Утреннее довольствие лагеря")
        self._satisfy_player(
            {
                "hunger": 0.30,
                "thirst": 0.34,
                "fatigue": 0.22,
                "health": 0.10,
                "boredom": 0.14,
            },
            morale_bonus=0.5,
        )
        logistics = getattr(self.state, "logistics", None)
        if logistics is not None and hasattr(logistics, "morning_resupply"):
            logistics.morning_resupply()
        logger.info("Лагерь: утреннее довольствие, ресурсы=%s", self.supplies)

    def camp_night(self, slept=True):
        for idx in self._player_indices():
            det = self.state.det_at(idx)
            if det is None:
                continue
            if slept:
                det.satisfy_needs(
                    {
                        "fatigue": 0.46,
                        "boredom": 0.22,
                        "anxiety": 0.14,
                        "fear": 0.10,
                        "health": 0.06,
                    },
                    morale_bonus=0.8,
                )
                self.state.log_event(idx, "Ночной сон в лагере")
            else:
                det.satisfy_needs(
                    {
                        "anxiety": 0.10,
                        "status": 0.04,
                    },
                    morale_bonus=0.4,
                )

                for character in det.characters:
                    character.needs["fatigue"] = min(
                        1.0, character.needs.get("fatigue", 0.0) + 0.12
                    )
                det.refresh_psychology()
                self.state.log_event(idx, "Ночное дежурство")
        if slept:
            self._satisfy_player(
                {
                    "fatigue": 0.50,
                    "boredom": 0.24,
                    "anxiety": 0.18,
                    "fear": 0.12,
                    "health": 0.08,
                },
                morale_bonus=0.8,
            )
        else:
            self._satisfy_player(
                {"anxiety": 0.12, "status": 0.05}, morale_bonus=0.4
            )
            self.commander.needs["fatigue"] = min(
                1.0, self.commander.needs.get("fatigue", 0.0) + 0.12
            )
        logger.info("Лагерь: ночь, сон=%s", slept)

    def _player_indices(self):
        player_side = getattr(self.state, "player_side", "red")
        return [
            i
            for i, det in enumerate(self.state.units)
            if det.side == player_side
        ]

    def get_save_snapshot(self):
        return {
            "supplies": dict(self.supplies),
            "cooldowns": dict(self.cooldowns),
            "trait": self.trait,
            "player": {
                "needs": dict(self.commander.needs),
                "morale": float(self.commander.morale),
                "dead": bool(self.commander.dead),
            },
            "player_cooldowns": dict(self.player_cooldowns),
        }

    def load_from_snapshot(self, snapshot):
        if not snapshot:
            return
        trait = normalize_trait(
            snapshot.get("trait", getattr(self.state, "commander_trait", None))
        )
        if trait:
            self.set_commander_trait(trait)

        supplies = dict(self.supplies)
        supplies.update(snapshot.get("supplies") or {})
        self.supplies.clear()
        self.supplies.update(supplies)
        self.state.supplies = self.supplies
        self.cooldowns = {
            str(key): int(value)
            for key, value in (snapshot.get("cooldowns") or {}).items()
        }
        self.player_cooldowns = {
            str(key): int(value)
            for key, value in (snapshot.get("player_cooldowns") or {}).items()
        }
        player = snapshot.get("player") or {}
        for need, value in (player.get("needs") or {}).items():
            if need in self.commander.needs:
                self.commander.needs[need] = max(0.0, min(1.0, float(value)))
        if "morale" in player:
            self.commander.morale = max(
                0.0, min(100.0, float(player["morale"]))
            )
        self.commander.dead = bool(player.get("dead", self.commander.is_dead))
        self._death_logged = bool(self.commander.dead)
