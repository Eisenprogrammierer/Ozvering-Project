"""Потребности и их удовлетворение в кампанийном UI.

Модель 16 потребностей уже живёт в ``warfare.Character``. Этот модуль —
RPG-прослойка между интерфейсом и персонажами:

* хранит ресурсы (продовольствие, вода, медикаменты, влияние);
* выполняет **личные** действия командира и списывает ресурсы;
* ведёт кулдауны, чтобы одно действие не применялось каждый кадр;
* каждый такт «прокручивает» потребности подразделений, которые не были
  в бою (в бою это делает ``Detachment.after_combat``);
* выполняет лагерное довольствие утром и сон/дежурство вечером.

Подразделения больше не являются целями действий игрока: их базовые
потребности закрываются автоматически логистикой (``LogisticsSystem``),
а игрок заботится только о собственном персонаже-командире. Старый вызов
``apply(idx, action_id)`` сохранён для внутренних сценариев и регрессионных
тестов, но RTS-интерфейс его не использует.

Никакой новой математики боя здесь нет: действия меняют только
``Character.needs``, а агрегаты отделения пересчитываются штатным
``refresh_psychology``.
"""

from __future__ import annotations

import warfare as W
from .log_journal import get_logger

logger = get_logger("view.needs")

TICK_SECONDS = 300

# Действия доступны из панели выбранного подразделения. Стоимость указана
# за одно применение на отделение, а не на каждого персонажа.
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
            "fear": 0.18, "anxiety": 0.16, "status": 0.09,
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
            "loneliness": 0.30, "friendship": 0.28, "love": 0.20,
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
            "knowledge": 0.24, "skill": 0.22, "creativity": 0.10,
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
            "spirituality": 0.30, "fear": 0.10, "anxiety": 0.08,
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
            "love": 0.24, "loneliness": 0.18, "reproduction": 0.16,
            "friendship": 0.08,
        },
        "morale": 1.0,
        "cooldown": 14400,
        "hint": "Письма и мысли о близких: любовь, одиночество, семья.",
    },
}

ACTION_ORDER = (
    "feed", "water", "rest", "medical", "encourage",
    "socialize", "train", "pray", "letters",
)

# Личные действия командира. Эффекты те же, но стоимость считается не на
# отделение, а на одного человека, поэтому она заметно меньше.
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

# Полные названия потребностей и способы их закрытия — для панели RPG.
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

# Действие/событие, которое закрывает потребность (текст для игрока).
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
    """Ресурсы, действия и пассивное движение потребностей."""

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
        # Важно сохранить тот же объект словаря, который ведёт логистика:
        # иначе действия потребностей и расход запасов начнут жить в разных
        # копиях состояния.
        for key, value in defaults.items():
            supplies.setdefault(key, value)
        self.supplies = supplies
        self.state.supplies = self.supplies
        self.cooldowns = {}
        # Личный персонаж игрока-командира. Он не является отделением и не
        # участвует в боевой математике, но имеет те же 16 потребностей.
        self.commander = W.Character(
            "Командир", getattr(self.state, "player_side", "red"),
            seed=90210, archetype="veteran",
        )
        self.player_cooldowns = {}

    # --- ресурсы и действия ---------------------------------------------
    def _key(self, idx, action_id):
        return "%s:%s" % (idx, action_id)

    def _player_key(self, action_id):
        return "commander:%s" % action_id

    def cooldown_remaining(self, idx, action_id):
        return int(self.cooldowns.get(self._key(idx, action_id), 0))

    def can_apply(self, idx, action_id):
        """Проверить действие без его выполнения."""
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
        """Выполнить действие удовлетворения для подразделения."""
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
            "%s: %s" % (
                definition["label"],
                ", ".join("%s −%.0f%%" % (
                    W.NEEDS_RU.get(need, need), value * 100 / count
                ) for need, value in restored.items()) or "без эффекта",
            ),
        )
        logger.info(
            "Потребности: %s для %s, ресурсы=%s",
            definition["label"], det.name, self.supplies,
        )
        return {
            "ok": True,
            "restored": restored,
            "supplies": dict(self.supplies),
        }

    def status(self, idx):
        """Состояние действий для панели выбранного подразделения."""
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

    # --- личные потребности командира -----------------------------------
    def player_needs_summary(self):
        """Средние (фактические) потребности персонажа игрока."""
        return self.commander.needs_summary()

    def player_cooldown_remaining(self, action_id):
        return int(self.player_cooldowns.get(self._player_key(action_id), 0))

    def can_apply_player(self, action_id):
        """Проверить личное действие командира без его выполнения."""
        definition = PLAYER_NEED_ACTIONS.get(action_id)
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
        """Выполнить личное действие командира (не подразделения)."""
        ok, reason = self.can_apply_player(action_id)
        if not ok:
            return {"ok": False, "reason": reason}
        definition = PLAYER_NEED_ACTIONS[action_id]
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
            definition["label"], self.supplies,
        )
        return {
            "ok": True,
            "restored": restored,
            "supplies": dict(self.supplies),
        }

    def status_player(self):
        """Состояние личных действий для оверлея «Нужды»."""
        result = {}
        for action_id in ACTION_ORDER:
            ok, reason = self.can_apply_player(action_id)
            definition = PLAYER_NEED_ACTIONS[action_id]
            result[action_id] = {
                "ok": ok,
                "reason": reason,
                "cooldown": self.player_cooldown_remaining(action_id),
                "label": definition["label"],
                "hint": definition.get("hint", ""),
                "cost": dict(definition.get("cost", {})),
                "effects": dict(definition.get("effects", {})),
            }
        return result

    def _tick_player(self, seconds, engaged_names):
        """Прокрутить личные потребности командира за прошедший интервал."""
        player_side = getattr(self.state, "player_side", "red")
        engaged = set(engaged_names or [])
        under_fire = 0.0
        if engaged:
            player_names = {
                det.name for det in self.state.units
                if det.side == player_side
            }
            under_fire = 0.35 if player_names & engaged else 0.0
        self.commander.tick_needs(
            in_combat=bool(under_fire),
            under_fire=under_fire,
            supported=0.45,
            seconds=seconds,
        )

    def _satisfy_player(self, effects, morale_bonus=0.0):
        self.commander.satisfy(effects, morale_bonus=morale_bonus)

    # --- течение времени ------------------------------------------------
    def on_tick(self, seconds=TICK_SECONDS, engaged_names=None):
        """Прокрутить потребности и кулдауны на один такт.

        Подразделения, которые участвовали в паре, уже получили
        ``after_combat`` внутри ``warfare``. Остальным нужен «мирный» такт,
        иначе их голод и усталость никогда не меняются.
        """
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
        for det in self.state.units:
            if det.name in engaged or not det.characters:
                continue
            support = det.cohesion * min(
                1.0, 0.3 + 0.7 * (det.morale / 100.0)
            )
            rested = getattr(det, "ui_order", "") == "rest"
            for character in det.characters:
                character.tick_needs(
                    in_combat=False,
                    supported=support,
                    rested=rested,
                    seconds=seconds,
                )
            det.refresh_psychology()
        self._tick_player(seconds, engaged)

    def camp_morning(self):
        """Утреннее довольствие лагеря: бесплатное, но не полное."""
        for idx in self._player_indices():
            det = self.state.det_at(idx)
            if det is None:
                continue
            det.satisfy_needs({
                "hunger": 0.26, "thirst": 0.30, "fatigue": 0.18,
                "health": 0.08, "boredom": 0.12,
            }, morale_bonus=0.5)
            self.state.log_event(idx, "Утреннее довольствие лагеря")
        self._satisfy_player({
            "hunger": 0.30, "thirst": 0.34, "fatigue": 0.22,
            "health": 0.10, "boredom": 0.14,
        }, morale_bonus=0.5)
        self.supplies["food"] = min(220, self.supplies.get("food", 0) + 12)
        self.supplies["water"] = min(260, self.supplies.get("water", 0) + 16)
        self.supplies["medicine"] = min(
            110, self.supplies.get("medicine", 0) + 4
        )
        logistics = getattr(self.state, "logistics", None)
        if logistics is not None and hasattr(logistics, "morning_resupply"):
            logistics.morning_resupply()
        logger.info("Лагерь: утреннее довольствие, ресурсы=%s", self.supplies)

    def camp_night(self, slept=True):
        """Ночь в лагере: сон восстанавливает силы, дежурство — нет."""
        for idx in self._player_indices():
            det = self.state.det_at(idx)
            if det is None:
                continue
            if slept:
                det.satisfy_needs({
                    "fatigue": 0.46, "boredom": 0.22, "anxiety": 0.14,
                    "fear": 0.10, "health": 0.06,
                }, morale_bonus=0.8)
                self.state.log_event(idx, "Ночной сон в лагере")
            else:
                det.satisfy_needs({
                    "anxiety": 0.10, "status": 0.04,
                }, morale_bonus=0.4)
                # Дежурство не даёт отдыха: усталость растёт.
                for character in det.characters:
                    character.needs["fatigue"] = min(
                        1.0, character.needs.get("fatigue", 0.0) + 0.12
                    )
                det.refresh_psychology()
                self.state.log_event(idx, "Ночное дежурство")
        if slept:
            self._satisfy_player({
                "fatigue": 0.50, "boredom": 0.24, "anxiety": 0.18,
                "fear": 0.12, "health": 0.08,
            }, morale_bonus=0.8)
        else:
            self._satisfy_player({"anxiety": 0.12, "status": 0.05},
                                 morale_bonus=0.4)
            self.commander.needs["fatigue"] = min(
                1.0, self.commander.needs.get("fatigue", 0.0) + 0.12
            )
        logger.info("Лагерь: ночь, сон=%s", slept)

    def _player_indices(self):
        player_side = getattr(self.state, "player_side", "red")
        return [
            i for i, det in enumerate(self.state.units)
            if det.side == player_side
        ]

    # --- сохранение -----------------------------------------------------
    def get_save_snapshot(self):
        return {
            "supplies": dict(self.supplies),
            "cooldowns": dict(self.cooldowns),
            "player": {
                "needs": dict(self.commander.needs),
                "morale": float(self.commander.morale),
            },
            "player_cooldowns": dict(self.player_cooldowns),
        }

    def load_from_snapshot(self, snapshot):
        if not snapshot:
            return
        # Сохраняем стартовые значения для ресурсов, которых нет в старом
        # сохранении; явно записанные нули при этом не теряются.
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
                self.commander.needs[need] = max(
                    0.0, min(1.0, float(value))
                )
        if "morale" in player:
            self.commander.morale = max(
                0.0, min(100.0, float(player["morale"]))
            )
