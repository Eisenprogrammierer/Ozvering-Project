from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
import math
import random

import simulation as S

NEEDS = (
    "hunger",
    "thirst",
    "fatigue",
    "health",
    "fear",
    "anxiety",
    "loneliness",
    "reproduction",
    "knowledge",
    "creativity",
    "boredom",
    "status",
    "spirituality",
    "skill",
    "love",
    "friendship",
)

NEEDS_RU = {
    "hunger": "голод",
    "thirst": "жажда",
    "fatigue": "усталость",
    "health": "здоровье",
    "fear": "страх",
    "anxiety": "тревога",
    "loneliness": "одиночество",
    "reproduction": "репродукция",
    "knowledge": "знания",
    "creativity": "творчество",
    "boredom": "скука",
    "status": "статус",
    "spirituality": "духовность",
    "skill": "умение",
    "love": "любовь",
    "friendship": "дружба",
}


_NEED_RATES = {
    "hunger": 0.0038,
    "thirst": 0.0052,
    "fatigue": 0.0042,
    "health": 0.0020,
    "fear": 0.0022,
    "anxiety": 0.0024,
    "loneliness": 0.0022,
    "reproduction": 0.0010,
    "knowledge": 0.0018,
    "creativity": 0.0018,
    "boredom": 0.0025,
    "status": 0.0024,
    "spirituality": 0.0018,
    "skill": 0.0018,
    "love": 0.0018,
    "friendship": 0.0018,
}


HEALTH_DEATH_THRESHOLD = 1.0
HEALTH_NEED_WEIGHTS = {
    "hunger": 0.10,
    "thirst": 0.14,
    "fatigue": 0.12,
    "fear": 0.08,
    "anxiety": 0.07,
    "loneliness": 0.04,
    "reproduction": 0.02,
    "knowledge": 0.02,
    "creativity": 0.02,
    "boredom": 0.03,
    "status": 0.03,
    "spirituality": 0.02,
    "skill": 0.02,
    "love": 0.03,
    "friendship": 0.03,
}
HEALTH_MULTIPLIER_MIN = 0.35
HEALTH_MULTIPLIER_MAX = 3.00


TRAITS = (
    "courage",
    "discipline",
    "aggression",
    "empathy",
    "curiosity",
    "creativity",
    "ambition",
    "spirituality",
    "sociability",
    "loyalty",
    "fanaticism",
    "endurance",
)

TRAITS_RU = {
    "courage": "смелость",
    "discipline": "дисциплина",
    "aggression": "агрессия",
    "empathy": "эмпатия",
    "curiosity": "любознательность",
    "creativity": "креативность",
    "ambition": "амбициозность",
    "spirituality": "духовность",
    "sociability": "общительность",
    "loyalty": "верность",
    "fanaticism": "фанатизм",
    "endurance": "выносливость",
}


_ARCHETYPES = {
    "rifleman": {},
    "veteran": {
        "courage": 0.18,
        "endurance": 0.16,
        "discipline": 0.12,
        "loyalty": 0.10,
    },
    "conscript": {
        "courage": -0.18,
        "discipline": -0.12,
        "endurance": -0.10,
        "loyalty": -0.08,
    },
    "commissar": {
        "discipline": 0.22,
        "fanaticism": 0.22,
        "aggression": 0.15,
        "empathy": -0.16,
    },
    "chaplain": {
        "spirituality": 0.22,
        "fanaticism": 0.18,
        "empathy": 0.12,
        "courage": 0.10,
    },
    "medic": {"empathy": 0.22, "discipline": 0.10, "aggression": -0.15},
    "scout": {"curiosity": 0.20, "creativity": 0.14, "discipline": -0.08},
    "machinegunner": {"discipline": 0.14, "endurance": 0.18, "courage": 0.10},
}


@dataclass
class Personality:

    values: dict
    archetype: str = "rifleman"
    seed: int = 0

    @classmethod
    def from_seed(cls, seed=0, archetype="rifleman"):
        rng = random.Random(int(seed))
        base = {name: 0.5 for name in TRAITS}
        base["courage"] = 0.55
        base["discipline"] = 0.55
        base["aggression"] = 0.45
        base["empathy"] = 0.50
        base["curiosity"] = 0.55
        base["creativity"] = 0.50
        base["ambition"] = 0.50
        base["spirituality"] = 0.45
        base["sociability"] = 0.55
        base["loyalty"] = 0.60
        base["fanaticism"] = 0.30
        base["endurance"] = 0.55
        mods = _ARCHETYPES.get(archetype, {})
        for name in TRAITS:

            base[name] += rng.uniform(-0.12, 0.12)
            base[name] += mods.get(name, 0.0)

            base[name] = max(0.0, min(1.0, base[name]))
        return cls(values=base, archetype=archetype, seed=int(seed))

    def __getitem__(self, name):
        return self.values[name]

    def get(self, name, default=0.5):
        return self.values.get(name, default)

    def as_dict(self):
        return dict(self.values)


@dataclass
class Intention:

    kind: str
    need: str
    urgency: float
    reason: str = ""


@dataclass
class OrderSignal:

    aggression: float = 0.0
    discipline: float = 0.0
    morale: float = 0.0
    fear: float = 0.0
    fanaticism: float = 0.0
    retreat_allowed: bool = True
    needs: dict = field(default_factory=dict)
    label: str = ""


class Order:

    def __init__(
        self, name, signal=None, duration=5, targets=(), side=None, defer=False
    ):
        self.name = name
        self.side = side
        self.signal = (
            signal
            if isinstance(signal, OrderSignal)
            else OrderSignal(**(signal or {}))
        )
        self.duration = int(duration)
        self.state = {"ttl": self.duration, "active": self.duration > 0}
        self.targets = []
        self._pending_targets = list(targets)
        if not defer:
            self.activate()

    @property
    def active(self):
        return self.state["active"]

    @property
    def ttl(self):
        return self.state["ttl"]

    def activate(self):
        for target in self._pending_targets:
            self.touch(target)
        self._pending_targets = []
        return self

    def touch(self, target):
        if target is None or target in self.targets:
            return
        self.targets.append(target)
        receiver = getattr(target, "receive_order", None)
        if callable(receiver):
            receiver(self)

    def tick(self):
        if not self.state["active"]:
            return False
        self.state["ttl"] -= 1
        if self.state["ttl"] <= 0:
            self.state["active"] = False
        return self.state["active"]

    def modulation(self):
        return self.signal if self.active else OrderSignal()

    def snapshot(self):
        return {
            "name": self.name,
            "side": self.side,
            "ttl": self.ttl,
            "active": self.active,
            "signal": self.signal.__dict__.copy(),
            "targets": [getattr(t, "name", repr(t)) for t in self.targets],
        }


class Character(S.UtilityAI):

    def __init__(
        self,
        name,
        side,
        seed=0,
        archetype="rifleman",
        profile="CANON",
        role="rifleman",
    ):
        super().__init__(profile=profile)
        self.name = name
        self.side = side
        self.role = role
        self.personality = Personality.from_seed(
            seed=seed, archetype=archetype
        )
        self.rng = random.Random(int(seed) * 1009 + 17)

        initial = {
            "hunger": 0.18,
            "thirst": 0.15,
            "fatigue": 0.12,
            "health": 0.05,
            "fear": 0.10,
            "anxiety": 0.12,
            "loneliness": 0.18,
            "reproduction": 0.10,
            "knowledge": 0.25,
            "creativity": 0.22,
            "boredom": 0.25,
            "status": 0.35,
            "spirituality": 0.25,
            "skill": 0.35,
            "love": 0.18,
            "friendship": 0.18,
        }
        self.needs = {n: initial[n] for n in NEEDS}
        self.desires = {}
        self.intentions = []
        self.morale = 65.0 + 12.0 * (self.personality["courage"] - 0.5)
        self.mind = "steady"
        self._last_mind = "steady"
        self.panicked = False
        self.fanatical = False
        self.panic_timer = 0
        self.fanatic_timer = 0

        self.panic_cooldown = 0
        self.fanatic_cooldown = 0
        self.orders = []
        self.under_fire = 0.0
        self.casualties = 0

        self.dead = False

    @property
    def is_dead(self):
        return bool(
            self.dead
            or float(self.needs.get("health", 0.0)) >= HEALTH_DEATH_THRESHOLD
        )

    def health_degradation_multiplier(self):
        multiplier = 1.0
        for need, weight in HEALTH_NEED_WEIGHTS.items():
            value = max(0.0, min(1.0, float(self.needs.get(need, 0.0))))
            multiplier *= 1.0 + float(weight) * (2.0 * value - 1.0)
        return max(
            HEALTH_MULTIPLIER_MIN,
            min(HEALTH_MULTIPLIER_MAX, multiplier),
        )

    def weighted_urgency(self):
        p = self.personality
        weight = {n: 1.0 for n in NEEDS}
        weight["fear"] *= 0.75 + 0.6 * p["courage"]
        weight["anxiety"] *= 0.70 + 0.8 * p["discipline"]
        weight["fatigue"] *= 0.75 + 0.5 * p["endurance"]
        weight["health"] *= 0.80 + 0.4 * p["endurance"]
        weight["status"] *= 0.65 + 0.9 * p["ambition"]
        weight["spirituality"] *= 0.55 + 1.1 * p["spirituality"]
        weight["loneliness"] *= 0.55 + 0.9 * p["sociability"]
        weight["friendship"] *= 0.55 + 0.9 * p["sociability"]
        weight["love"] *= 0.55 + 0.8 * p["empathy"]
        weight["knowledge"] *= 0.60 + 0.8 * p["curiosity"]
        weight["creativity"] *= 0.60 + 0.8 * p["creativity"]
        weight["skill"] *= 0.60 + 0.8 * p["discipline"]
        weight["boredom"] *= 0.60 + 0.7 * p["curiosity"]
        weight["reproduction"] *= 0.50 + 0.9 * p["sociability"]
        return {n: self.needs[n] * weight[n] for n in NEEDS}

    def deliberate(self):
        self.desires = self.weighted_urgency()
        need = max(NEEDS, key=lambda n: self.desires[n])
        urgency = self.desires[need]
        p = self.personality
        mod = self.modulation()

        if self.panicked and mod.retreat_allowed:
            intent = Intention("retreat", need, urgency, "паника")
        elif self.fanatical or mod.fanaticism > 0.35:
            intent = Intention("banzai", need, urgency, "фанатичный порыв")
        elif (
            need in ("fatigue", "hunger", "thirst", "health")
            and urgency > 0.42
        ):
            intent = Intention("rest", need, urgency, "истощение")
        elif (
            need in ("fear", "anxiety")
            and urgency > 0.40
            and mod.retreat_allowed
        ):
            intent = Intention("hold", need, urgency, "страх/тревога")
        elif (
            need in ("status", "spirituality")
            or p["aggression"] > 0.66
            or mod.aggression > 0.20
        ):
            intent = Intention("assault", need, urgency, "порыв")
        elif need in ("knowledge", "creativity", "skill", "boredom"):
            intent = Intention("fire", need, urgency, "расчёт")
        else:
            intent = Intention("fire", need, urgency, "устав")
        self.intentions = (self.intentions + [intent])[-3:]
        return intent

    def receive_order(self, order):
        if order not in self.orders:
            self.orders.append(order)

    def modulation(self):
        total = OrderSignal()
        for order in list(self.orders):
            if not order.active:
                continue
            sig = order.modulation()
            total.aggression += sig.aggression
            total.discipline += sig.discipline
            total.morale += sig.morale
            total.fear += sig.fear
            total.fanaticism += sig.fanaticism
            total.retreat_allowed = (
                total.retreat_allowed and sig.retreat_allowed
            )
            for need, delta in sig.needs.items():
                total.needs[need] = total.needs.get(need, 0.0) + delta

        self.orders = [o for o in self.orders if o.active]
        return total

    def tick_needs(
        self,
        in_combat=False,
        under_fire=0.0,
        supported=0.0,
        rested=False,
        rng=None,
        seconds=1800,
        rate_multipliers=None,
        morale_baseline_bonus=0.0,
    ):
        rng = rng or self.rng
        if self.is_dead:
            self.dead = True
            self.needs["health"] = HEALTH_DEATH_THRESHOLD
            self.mind = "dead"
            self.morale = 0.0
            return
        p = self.personality
        mod = self.modulation()
        uf = max(0.0, min(1.0, float(under_fire)))
        support = max(0.0, min(1.0, float(supported)))
        scale = max(0.0, float(seconds)) / 1800.0
        health_multiplier = self.health_degradation_multiplier()
        rate_multipliers = rate_multipliers or {}

        rates = dict(_NEED_RATES)
        rates["fatigue"] *= 0.70 + 0.6 * (1.0 - p["endurance"])
        rates["fear"] *= 0.55 + 0.9 * (1.0 - p["courage"])
        rates["anxiety"] *= 0.60 + 0.9 * (1.0 - p["discipline"])
        rates["health"] *= 0.70 + 0.7 * (1.0 - p["endurance"])
        rates["loneliness"] *= 0.75 + 0.7 * (1.0 - p["sociability"])
        rates["boredom"] *= 0.75 + 0.6 * (1.0 - p["curiosity"])
        rates["status"] *= 0.80 + 0.5 * p["ambition"]
        rates["spirituality"] *= 0.80 + 0.5 * p["spirituality"]
        for need, multiplier in rate_multipliers.items():
            if need in rates:
                rates[need] *= max(0.0, float(multiplier))

        for need in NEEDS:
            delta = rates[need]
            if in_combat and need in ("fatigue", "fear", "anxiety", "health"):
                delta += (0.003 + 0.010 * uf) * (0.8 + 0.4 * rng.random())
            if need in ("fear", "anxiety"):
                delta += 0.006 * uf
            if need == "boredom" and not in_combat:
                delta += 0.003
            if need == "health":

                delta *= health_multiplier
            self.needs[need] = min(1.0, self.needs[need] + delta * scale)
            self.needs[need] = max(
                0.0,
                self.needs[need] - mod.needs.get(need, 0.0) * scale,
            )

        if support > 0:
            for need in (
                "loneliness",
                "friendship",
                "love",
                "fear",
                "anxiety",
            ):
                self.needs[need] = max(
                    0.0, self.needs[need] - 0.014 * support * scale
                )
        if rested:
            for need in ("fatigue", "hunger", "thirst", "boredom"):
                self.needs[need] = max(0.0, self.needs[need] - 0.035 * scale)
        if in_combat:

            self.needs["skill"] = max(0.0, self.needs["skill"] - 0.012 * scale)
            self.needs["status"] = max(
                0.0, self.needs["status"] - 0.006 * scale
            )

        if self.needs["health"] >= HEALTH_DEATH_THRESHOLD:
            self.needs["health"] = HEALTH_DEATH_THRESHOLD
            self.dead = True
            self.mind = "dead"
            self.morale = 0.0
            return

        if mod.fear:
            self.needs["fear"] = min(
                1.0, self.needs["fear"] + mod.fear * scale
            )
        if mod.discipline:
            self.needs["anxiety"] = max(
                0.0, self.needs["anxiety"] - 0.02 * mod.discipline * scale
            )
            self.needs["fear"] = max(
                0.0, self.needs["fear"] - 0.01 * mod.discipline * scale
            )

        stress = (
            self.needs["fear"] * 0.30
            + self.needs["anxiety"] * 0.22
            + self.needs["fatigue"] * 0.20
            + self.needs["health"] * 0.18
            + self.needs["loneliness"] * 0.10
        )
        baseline = (
            50.0
            + 18.0 * p["discipline"]
            + 10.0 * p["courage"]
            + float(morale_baseline_bonus)
        )
        drift = 0.03 * (baseline - self.morale)
        self.morale += scale * (
            drift
            - 4.0 * stress
            - 3.0 * uf
            + 0.15 * mod.morale
            + 0.20 * support
            + 0.10 * mod.discipline
        )
        self.morale = max(0.0, min(100.0, self.morale))
        self.under_fire = uf
        self.casualties = max(0.0, self.casualties + uf * 0.1 * scale)

        self._update_mind(rng)
        self.deliberate()

    def _update_mind(self, rng):
        p = self.personality
        mod = self.modulation()
        fear = self.needs["fear"]
        anxiety = self.needs["anxiety"]
        fatigue = self.needs["fatigue"]
        morale_norm = self.morale / 100.0
        noise = (rng.random() - 0.5) * 0.08

        panic_score = (
            0.34 * fear
            + 0.24 * anxiety
            + 0.18 * fatigue
            + 0.38 * (1.0 - morale_norm)
            + noise
            - 0.34 * p["courage"]
            - 0.20 * p["discipline"]
            - 0.10 * mod.discipline
        )
        fanatic_score = (
            0.30 * p["aggression"]
            + 0.26 * p["fanaticism"]
            + 0.16 * p["spirituality"]
            + 0.10 * p["ambition"]
            + 0.16 * morale_norm
            + noise
            - 0.24 * fear
            - 0.16 * anxiety
            + 0.25 * mod.fanaticism
        )

        if self.fanatic_timer > 0:
            self.fanatic_timer -= 1
        if self.panic_timer > 0:
            self.panic_timer -= 1
        if self.fanatic_cooldown > 0:
            self.fanatic_cooldown -= 1
        if self.panic_cooldown > 0:
            self.panic_cooldown -= 1

        panicked_now = (
            panic_score > 0.42
            and mod.retreat_allowed
            and self.panic_timer == 0
            and self.panic_cooldown == 0
        )
        fanatical_now = (
            fanatic_score > 0.48
            and not panicked_now
            and self.fanatic_timer == 0
            and self.fanatic_cooldown == 0
            and self.morale > 32.0
        )
        if panicked_now:
            self.panicked = True
            self.fanatical = False
            self.mind = "panicked"
            self.panic_timer = 3
            self.panic_cooldown = 20
        elif fanatical_now:
            self.fanatical = True
            self.panicked = False
            self.mind = "fanatical"
            self.fanatic_timer = 3
            self.fanatic_cooldown = 16
        elif panic_score > 0.30:
            self.panicked = False
            self.fanatical = False
            self.mind = "shaken"
        else:
            self.panicked = False
            self.fanatical = False
            self.mind = "steady"

    def satisfy(self, effects, morale_bonus=0.0):
        restored = {}
        if self.is_dead:
            return restored
        for need, amount in (effects or {}).items():
            if need not in self.needs:
                continue
            try:
                amount = max(0.0, float(amount))
            except (TypeError, ValueError):
                continue
            before = self.needs[need]
            self.needs[need] = max(0.0, before - amount)
            restored[need] = before - self.needs[need]
        total = sum(restored.values())
        if total and morale_bonus:
            self.morale = max(
                0.0, min(100.0, self.morale + morale_bonus * total)
            )
        return restored

    def needs_summary(self):
        if not self.needs:
            return {}
        return {need: float(self.needs.get(need, 0.0)) for need in NEEDS}

    def snapshot(self):
        return {
            "name": self.name,
            "side": self.side,
            "role": self.role,
            "mind": self.mind,
            "morale": round(self.morale, 1),
            "needs": {n: round(v, 3) for n, v in self.needs.items()},
            "desires": {n: round(v, 3) for n, v in self.desires.items()},
            "intention": (
                self.intentions[-1].__dict__.copy()
                if self.intentions
                else None
            ),
            "personality": self.personality.as_dict(),
        }


class Detachment(S.Environment):

    def __init__(
        self,
        name,
        side,
        characters,
        position=(0, 0),
        profile="CANON",
        role="line",
        doctrine="balanced",
    ):
        chars = list(characters)

        start_force = min(34.0, 6.0 + 2.0 * len(chars))
        super().__init__(start_force=start_force, members=chars)
        self.name = name
        self.side = side
        self.role = role
        self.doctrine = doctrine
        self.position = tuple(position)
        self.characters = chars
        self.orders = []
        self.morale = 70.0
        self.cohesion = 0.5
        self.aggression = 0.5
        self.discipline = 0.5
        self.fanaticism = 0.3
        self.retreating = False
        self.panicked = False
        self.fanatical = False
        self.broken = False
        self.coerced_by = None
        self.last_under_fire = 0.0
        self.last_intent = None
        self.engagements = 0

        self.losses = 0.0

        self.combat_loss_scale = 1.0

        self.start_force = float(start_force)

        self.needs_tick_seconds = 1800
        self._reported_banzai = False
        self._reported_retreat = False
        self._retreat_ticks = 0
        self._initialized = False
        self.refresh_psychology()

    def _avg(self, values):
        return sum(values) / max(1, len(values))

    def refresh_psychology(self):
        if not self.characters:
            return
        self.morale = self._avg([c.morale for c in self.characters])
        self.aggression = self._avg(
            [c.personality["aggression"] for c in self.characters]
        )
        self.discipline = self._avg(
            [c.personality["discipline"] for c in self.characters]
        )
        self.fanaticism = self._avg(
            [c.personality["fanaticism"] for c in self.characters]
        )
        self.cohesion = self._avg(
            [
                (1.0 - c.needs["loneliness"]) * 0.4
                + (1.0 - c.needs["friendship"]) * 0.4
                + (1.0 - c.needs["love"]) * 0.2
                for c in self.characters
            ]
        )
        mod = self.modulation()
        self.aggression = max(0.0, min(1.5, self.aggression + mod.aggression))
        self.discipline = max(0.0, min(1.5, self.discipline + mod.discipline))
        self.fanaticism = max(0.0, min(1.5, self.fanaticism + mod.fanaticism))

        if self.doctrine == "assault":
            self.aggression = min(1.5, self.aggression + 0.10)
            self.fanaticism = min(1.5, self.fanaticism + 0.04)
        elif self.doctrine == "defensive":
            self.discipline = min(1.5, self.discipline + 0.10)

        self.panicked = any(c.panicked for c in self.characters)
        self.fanatical = any(c.fanatical for c in self.characters)
        if not self.retreat_allowed:
            self.panicked = False

    def receive_order(self, order):
        if order not in self.orders:
            self.orders.append(order)
        for c in self.characters:
            c.receive_order(order)
        self.refresh_psychology()

    def process_hit(self, tr):
        scale = max(
            0.0, min(1.0, float(getattr(self, "combat_loss_scale", 1.0)))
        )
        if scale >= 1.0:
            super().process_hit(tr)
            return
        gross = int(round(float(tr) * (S.K_EFFECT + scale)))
        super().process_hit(gross)

    def modulation(self):
        total = OrderSignal()
        for order in list(self.orders):
            if not order.active:
                continue
            sig = order.modulation()
            total.aggression += sig.aggression
            total.discipline += sig.discipline
            total.morale += sig.morale
            total.fear += sig.fear
            total.fanaticism += sig.fanaticism
            total.retreat_allowed = (
                total.retreat_allowed and sig.retreat_allowed
            )
            for need, delta in sig.needs.items():
                total.needs[need] = total.needs.get(need, 0.0) + delta
        self.orders = [o for o in self.orders if o.active]
        return total

    @property
    def retreat_allowed(self):
        return self.modulation().retreat_allowed

    def after_combat(self, under_fire=0.0, rng=None):
        rng = rng or random.Random(0)
        uf = max(0.0, min(1.0, float(under_fire)))
        support = self.cohesion * min(1.0, 0.3 + 0.7 * (self.morale / 100.0))
        for c in self.characters:
            c.tick_needs(
                in_combat=self.engagements > 0,
                under_fire=uf,
                supported=support,
                rng=rng,
                seconds=getattr(self, "needs_tick_seconds", 1800),
            )
        self.last_under_fire = uf
        self.refresh_psychology()
        self.engagements = 0
        self._update_retreat(rng)

    def satisfy_needs(self, effects, morale_bonus=0.0):
        total = {need: 0.0 for need in NEEDS}
        for character in self.characters:
            for need, amount in character.satisfy(
                effects, morale_bonus=morale_bonus
            ).items():
                total[need] = total.get(need, 0.0) + amount
        self.refresh_psychology()
        return {need: value for need, value in total.items() if value}

    def needs_summary(self):
        if not self.characters:
            return {}
        return {
            need: sum(c.needs.get(need, 0.0) for c in self.characters)
            / len(self.characters)
            for need in NEEDS
        }

    def _update_retreat(self, rng):
        panic_frac = sum(1 for c in self.characters if c.panicked) / max(
            1, len(self.characters)
        )
        fanatic_frac = sum(1 for c in self.characters if c.fanatical) / max(
            1, len(self.characters)
        )
        self.fanatical = fanatic_frac > 0.0

        leader = self.characters[0] if self.characters else None
        leader_panic = bool(leader and leader.panicked)
        should_retreat = (
            panic_frac >= 0.30
            or (leader_panic and self.discipline < 0.52)
            or self.morale < 20.0
        )
        if should_retreat and self.retreat_allowed and not self.fanatical:
            self.retreating = True
            self.panicked = True
        elif not self.retreat_allowed:

            self.retreating = False
            self.panicked = False
        elif panic_frac == 0.0 and self.morale > 38.0:
            self.retreating = False
            self.panicked = False

        if self.fanatical and fanatic_frac > 0.0:
            self.retreating = False
            self.panicked = False

    def prepare_turn(self):
        self.refresh_psychology()
        if (
            self.retreat_allowed
            and not self.panicked
            and self.morale > 45.0
            and not self.fanatical
        ):
            self.retreating = False
        return self

    def choose_intent(self, target, rng=None):
        rng = rng or random.Random(0)
        self.refresh_psychology()
        if self.retreating and not self.fanatical:
            self.last_intent = ("retreat", 0)
            return "REST", 0
        if self.fanatical:
            act = self._fanatic_type(target, rng)
            work = max(1, int(self.energy_pool * 0.7))
            self.last_intent = ("banzai", work, act)
            return act, work
        if self.morale < 28.0 and self.retreat_allowed and not self.fanatical:
            self.last_intent = ("hold", 0)
            return "REST", 0

        best, best_score = ("REST", 0), self._rest_score()
        for act in S.TYPES:
            for frac in (0.3, 0.7):
                work = int(self.energy_pool * frac)
                if work <= 0:
                    continue
                score = self._attack_score(act, work, target)
                score *= 0.70 + 0.55 * self.aggression
                score *= 0.80 + 0.35 * (self.morale / 100.0)
                if score > best_score:
                    best, best_score = (act, work), score
        self.last_intent = (
            ("fire", best[1], best[0]) if best[0] != "REST" else ("rest", 0)
        )
        return best

    def _rest_score(self):
        base = self.rest_gain()
        fatigue = self._avg([c.needs["fatigue"] for c in self.characters])
        fear = self._avg([c.needs["fear"] for c in self.characters])
        return base * (1.0 + 1.5 * fatigue + 0.8 * fear) + (
            1.0 - self.morale / 100.0
        )

    def _attack_score(self, act, work, target):
        if work <= 0:
            return -1e9
        open_now = bool(self.beliefs.get("opp_in_open"))
        expected = 0.0
        for hypo in S.TYPES:
            m = S.MULT.get((act, hypo), 1.0)
            p = S.p_success(act, work, hypo, max(1, target.last_work))
            frac = S.GAIN_MAX if open_now else S.Y_SMALL
            expected += work * m * frac * p / len(S.TYPES)

        if not open_now:
            on_opp = max(
                S.ON_MIN, S.ON_FRAC * self.beliefs.get("opp_force", 10)
            )
            progress = min(1.0, self.beliefs.get("opp_w_adopt", 0.0) / on_opp)
            expected += work * S.OPTION_VALUE * progress
        cost = S.COST_FRACTION * work
        shock = S.HOCK_FRACTION * int(S.RETALIATE_FRACTION * work)
        return expected - cost - shock

    def _fanatic_type(self, target, rng):
        best = S.TYPES[0]
        best_m = -1.0
        for act in S.TYPES:
            m = max(S.MULT.get((act, hypo), 1.0) for hypo in S.TYPES)
            if m > best_m:
                best, best_m = act, m
        if rng.random() < 0.25:
            best = rng.choice(S.TYPES)
        return best

    def move_away(self, opponents, bounds=(0, 24, 0, 24)):
        if not opponents:
            return False
        nearest = min(
            opponents,
            key=lambda d: (
                abs(d.position[0] - self.position[0])
                + abs(d.position[1] - self.position[1])
            ),
        )
        dx = self.position[0] - nearest.position[0]
        dy = self.position[1] - nearest.position[1]
        if dx == 0 and dy == 0:
            dx, dy = 1, 0
        step_x = (1 if dx > 0 else -1) if dx else 0
        step_y = (1 if dy > 0 else -1) if dy else 0
        new = (
            max(bounds[0], min(bounds[1], self.position[0] + step_x)),
            max(bounds[2], min(bounds[3], self.position[1] + step_y)),
        )
        if new == self.position:
            return False
        self.position = new
        return True

    def snapshot(self):
        return {
            "name": self.name,
            "side": self.side,
            "role": self.role,
            "force": round(self.force, 1),
            "energy": self.energy_pool,
            "losses": round(self.losses, 1),
            "morale": round(self.morale, 1),
            "position": self.position,
            "retreating": self.retreating,
            "panicked": self.panicked,
            "fanatical": self.fanatical,
            "coerced_by": self.coerced_by,
            "modulation": self.modulation().__dict__.copy(),
            "characters": [c.snapshot() for c in self.characters],
        }


class BarrierDetachment(Detachment):

    def __init__(
        self,
        name,
        side,
        characters,
        position=(0, 0),
        profile="CANON",
        doctrine="barrier",
        targets=None,
    ):
        super().__init__(
            name,
            side,
            characters,
            position=position,
            profile=profile,
            role="barrier",
            doctrine=doctrine,
        )
        self.enforce_targets = list(targets or [])
        self.stopped = 0
        self.punished = 0

    @property
    def retreat_allowed(self):
        return False

    def enforce(self, allies, rng=None, turn=0):
        out = []
        for det in allies:
            if det is self or det.side != self.side or det.broken:
                continue
            if self.enforce_targets and det.name not in self.enforce_targets:
                continue
            needs_enforce = det.retreating or det.panicked or det.morale < 38.0
            if not needs_enforce:
                continue
            was_retreating = det.retreating
            det.retreating = False
            det.panicked = False
            det.coerced_by = self.name
            signal = OrderSignal(
                aggression=0.10,
                discipline=0.18,
                morale=-2.0,
                fear=0.06,
                fanaticism=0.04,
                retreat_allowed=False,
                label="заградотряд",
            )
            order = Order(
                f"{self.name}-{det.name}-{turn}",
                signal,
                duration=3,
                targets=[det],
                side=self.side,
            )
            self.stopped += 1
            out.append((det, was_retreating, order))
        return out

    def snapshot(self):
        data = super().snapshot()
        data.update(
            {
                "stopped": self.stopped,
                "punished": self.punished,
                "enforce_targets": list(self.enforce_targets),
            }
        )
        return data


class Stan(S.Environment):

    def __init__(
        self,
        name,
        side,
        reserve=None,
        spawn_interval=6,
        position=(2, 2),
        rally=None,
        max_spawns=None,
        factory=None,
    ):
        reserve = list(reserve or [])
        super().__init__(
            start_force=max(10, 4 * len(reserve)), members=reserve
        )
        self.name = name
        self.side = side
        self.spawn_interval = max(1, int(spawn_interval))
        self.position = tuple(position)
        self.rally = tuple(rally or position)
        self.max_spawns = max_spawns
        self.factory = factory
        self.clock = 0
        self.spawned = []
        self._spawn_count = 0

    def tick(self):
        super().tick()
        self.clock += 1

    def can_spawn(self):
        if (
            self.max_spawns is not None
            and self._spawn_count >= self.max_spawns
        ):
            return False
        return bool(self.members or self.factory)

    def drain_spawns(self):
        out = []
        while self.clock >= self.spawn_interval and self.can_spawn():
            self.clock -= self.spawn_interval
            det = None
            if self.members:
                det = self.members.pop(0)
            elif self.factory is not None:
                det = self.factory(self._spawn_count)
            if det is None:
                break
            det.position = self.rally
            self.spawned.append(det)
            self._spawn_count += 1
            out.append(det)
        return out

    def snapshot(self):
        return {
            "name": self.name,
            "side": self.side,
            "clock": self.clock,
            "interval": self.spawn_interval,
            "reserve": [getattr(d, "name", repr(d)) for d in self.members],
            "spawned": [d.name for d in self.spawned],
        }


class Reinforcement(S.Environment):

    def __init__(
        self, name, side, detachments, delay=8, position=(20, 20), rally=None
    ):
        dets = list(detachments)
        super().__init__(start_force=max(10, 4 * len(dets)), members=dets)
        self.name = name
        self.side = side
        self.delay = max(0, int(delay))
        self.position = tuple(position)
        self.rally = tuple(rally or position)
        self.clock = 0
        self.deployed = False
        self.arrived = []

    def tick(self):
        super().tick()
        self.clock += 1

    @property
    def ready(self):
        return (not self.deployed) and self.clock >= self.delay

    def drain_arrivals(self):
        if not self.ready:
            return []
        self.deployed = True
        out = list(self.members)
        self.members = []
        for det in out:
            det.position = self.rally
        self.arrived.extend(out)
        return out

    def snapshot(self):
        return {
            "name": self.name,
            "side": self.side,
            "delay": self.delay,
            "clock": self.clock,
            "ready": self.ready,
            "deployed": self.deployed,
            "arrived": [d.name for d in self.arrived],
        }


class WarfareSimulation:

    def __init__(self, seed=0, turns=120):
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.max_turns = int(turns)
        self.turn = 0
        self.detachments = []
        self.all_detachments = []
        self.stans = []
        self.reinforcements = []
        self.organizations = []
        self.orders = []
        self.events = []
        self.scheduled_orders = []
        self.finished = False
        self.winner = None
        self._log_turn = 0

        self.engage_range = None

        self.focus_targets = {}

    def add_detachment(self, det):
        if det not in self.detachments:
            self.detachments.append(det)
            self.all_detachments.append(det)
        return det

    def add_stan(self, stan):
        self.stans.append(stan)
        return stan

    def add_reinforcement(self, reinforcement):
        self.reinforcements.append(reinforcement)
        return reinforcement

    def add_organization(self, organization):
        if organization not in self.organizations:
            self.organizations.append(organization)
        return organization

    def issue_order(self, order):
        order.activate()
        self.orders.append(order)
        return order

    def schedule_order(self, turn, order):
        self.scheduled_orders.append((int(turn), order))
        return order

    def log_event(self, kind, text, side=None, actor=None):
        self.events.append(
            {
                "turn": self.turn,
                "kind": kind,
                "text": text,
                "side": side,
                "actor": actor,
            }
        )

    def log(self, text, side=None, actor=None):
        self.log_event("log", text, side, actor)

    def _detachments(self, side=None, active_only=True):
        out = []
        for d in self.detachments:
            if side is not None and d.side != side:
                continue
            if active_only and (d.broken or d.force <= 1):
                continue
            out.append(d)
        return out

    def tick(self):
        if self.finished:
            return False
        self.turn += 1
        self._tick_orders()
        self._tick_sources()
        for det in self.detachments:
            det.prepare_turn()
        self._enforce_barriers()
        self._retreat_moves()
        self._fight()
        self._after_fight()
        self._tick_organizations()
        self._check_victory()
        return not self.finished

    def _tick_orders(self):
        for order in list(self.orders):
            if order.active:
                order.tick()
        self.orders = [o for o in self.orders if o.active]
        due = [(t, o) for t, o in self.scheduled_orders if t <= self.turn]
        self.scheduled_orders = [
            (t, o) for t, o in self.scheduled_orders if t > self.turn
        ]
        for _, order in due:
            self.issue_order(order)
            self.log_event(
                "support", f"приказ «{order.name}» передан", side=order.side
            )

    def _tick_sources(self):
        for stan in self.stans:
            stan.tick()
            for det in stan.drain_spawns():
                self.add_detachment(det)
                self.log_event(
                    "spawn",
                    f"стан {stan.name} выпустил {det.name}",
                    side=det.side,
                    actor=det.name,
                )
        for reinf in self.reinforcements:
            reinf.tick()
            for det in reinf.drain_arrivals():
                self.add_detachment(det)
                self.log_event(
                    "reinforcement",
                    f"подкрепление {reinf.name} прибыло: {det.name}",
                    side=det.side,
                    actor=det.name,
                )

    def _enforce_barriers(self):
        for barrier in [
            d
            for d in self._detachments(active_only=False)
            if isinstance(d, BarrierDetachment)
        ]:
            if barrier.broken:
                continue
            allies = self._detachments(side=barrier.side, active_only=False)
            for det, was_retreating, order in barrier.enforce(
                allies, self.rng, self.turn
            ):
                self.issue_order(order)
                self.log_event(
                    "barrier",
                    f"{barrier.name} остановил {det.name}"
                    + (" (был в отходе)" if was_retreating else ""),
                    side=det.side,
                    actor=barrier.name,
                )
                if was_retreating:

                    det.force = max(1, det.force - 1)
                    det.morale = max(0.0, det.morale - 2.0)
                    barrier.punished += 1
                    self.log_event(
                        "barrier_fire",
                        f"{barrier.name} покарал {det.name} за отход",
                        side=det.side,
                        actor=barrier.name,
                    )

    def _retreat_moves(self):
        for det in self._detachments():
            if not det.retreating:
                det._reported_retreat = False
                det._retreat_ticks = 0
                continue
            det._retreat_ticks += 1
            if not det._reported_retreat:
                det._reported_retreat = True
                self.log_event(
                    "retreat",
                    f"{det.name} отходит (мораль {det.morale:.0f})",
                    side=det.side,
                    actor=det.name,
                )
            enemies = self._detachments(side=self._other_side(det.side))
            det.move_away(enemies)

            if det._retreat_ticks >= 4 and det.morale > 30.0:
                det.retreating = False
                det.panicked = False
                det._retreat_ticks = 0
                det._reported_retreat = False

    def _other_side(self, side):
        return "blue" if side == "red" else "red"

    def _pair_engagements(self):
        active = [
            d for d in self._detachments() if not d.retreating or d.fanatical
        ]

        attackers = [d for d in active if d.role != "barrier"]
        if not attackers:
            attackers = active
        used = set()
        pairs = []
        focus_targets = getattr(self, "focus_targets", {}) or {}

        for det in sorted(attackers, key=lambda d: (d.force, d.side, d.name)):
            if id(det) in used:
                continue
            focus_name = focus_targets.get(det.name)
            if focus_name:

                focused_enemies = [
                    e
                    for e in self._detachments(side=self._other_side(det.side))
                    if (not e.retreating or e.fanatical)
                ]
                if self.engage_range is not None:
                    radius = max(1, int(self.engage_range))
                    focused_enemies = [
                        e
                        for e in focused_enemies
                        if (
                            abs(e.position[0] - det.position[0])
                            + abs(e.position[1] - det.position[1])
                        )
                        <= radius
                    ]
                line = [e for e in focused_enemies if e.role != "barrier"]
                if line:
                    focused_enemies = line
                focus_enemy = next(
                    (e for e in focused_enemies if e.name == focus_name),
                    None,
                )
                if focus_enemy is not None:
                    used.add(id(det))
                    used.add(id(focus_enemy))
                    pairs.append((det, focus_enemy))
                    continue

            enemies = [
                e
                for e in self._detachments(side=self._other_side(det.side))
                if id(e) not in used and (not e.retreating or e.fanatical)
            ]
            if self.engage_range is not None:
                radius = max(1, int(self.engage_range))
                enemies = [
                    e
                    for e in enemies
                    if (
                        abs(e.position[0] - det.position[0])
                        + abs(e.position[1] - det.position[1])
                    )
                    <= radius
                ]
            line_enemies = [e for e in enemies if e.role != "barrier"]
            if line_enemies:
                enemies = line_enemies
            if not enemies:
                continue
            target = min(
                enemies,
                key=lambda e: (
                    abs(e.position[0] - det.position[0])
                    + abs(e.position[1] - det.position[1]),
                    e.name,
                ),
            )
            used.add(id(det))
            used.add(id(target))
            pairs.append((det, target))
        return pairs

    def _fight(self):
        for a, b in self._pair_engagements():
            a.engagements += 1
            b.engagements += 1
            before_a, before_b = a.force, b.force
            S.run_tick(
                a,
                b,
                lambda me, opp, rng, _a=a: _a.choose_intent(opp, rng),
                lambda me, opp, rng, _b=b: _b.choose_intent(opp, rng),
                self.rng,
            )
            uf_a = max(0.0, (before_a - a.force) / max(1.0, before_a))
            uf_b = max(0.0, (before_b - b.force) / max(1.0, before_b))
            a.after_combat(under_fire=uf_a, rng=self.rng)
            b.after_combat(under_fire=uf_b, rng=self.rng)
            self.log_event(
                "engagement",
                f"{a.name} ({a.force:.0f}) ↔ {b.name} ({b.force:.0f})",
                side=a.side,
                actor=a.name,
            )
            self._report_mind(a)
            self._report_mind(b)

    def _report_mind(self, det):
        for c in det.characters:
            if c.mind == "panicked" and c._last_mind != "panicked":
                self.log_event(
                    "panic",
                    f"{c.name} паникует ({det.name})",
                    side=det.side,
                    actor=c.name,
                )
            c._last_mind = c.mind

        banzai_now = bool(
            det.last_intent
            and det.last_intent[0] == "banzai"
            and det.last_intent[1] > 0
        )
        if banzai_now and not det._reported_banzai:
            self.log_event(
                "banzai",
                f"{det.name}: банзай-атака ({det.last_intent[2]})",
                side=det.side,
                actor=det.name,
            )
        if not banzai_now:
            det._reported_banzai = False
        else:
            det._reported_banzai = True

    def _after_fight(self):

        for det in self.detachments:
            if det.force <= 1 or det.morale <= 1.0:
                if not det.broken:
                    det.broken = True
                    self.log_event(
                        "broken",
                        f"{det.name} рассеяно",
                        side=det.side,
                        actor=det.name,
                    )
        self.detachments = [d for d in self.detachments if not d.broken]

    def _tick_organizations(self):
        for organization in list(self.organizations):
            if (
                getattr(organization, "active", True) is False
                and getattr(organization, "phase", "") == "dissolved"
                and not getattr(organization, "allow_rejoin", False)
            ):
                continue
            tick = getattr(organization, "tick", None)
            if not callable(tick):
                continue
            update = tick(rng=self.rng, turn=self.turn)
            events = (
                update.get("events", []) if isinstance(update, dict) else []
            )
            for event in events:
                self.log_event(
                    event.get("kind", "organization"),
                    event.get("text", str(organization)),
                    side=event.get(
                        "side", getattr(organization, "side", None)
                    ),
                    actor=event.get(
                        "actor", getattr(organization, "name", None)
                    ),
                )

    def _check_victory(self):
        red = self._detachments(side="red")
        blue = self._detachments(side="blue")
        if not red and not blue:
            self.finished = True
            self.winner = "draw"
        elif not red:
            self.finished = True
            self.winner = "blue"
        elif not blue:
            self.finished = True
            self.winner = "red"
        elif self.turn >= self.max_turns:
            self.finished = True
            red_force = sum(d.force for d in red)
            blue_force = sum(d.force for d in blue)
            self.winner = (
                "red"
                if red_force > blue_force
                else "blue" if blue_force > red_force else "draw"
            )
        if self.finished:
            self.log_event("end", f"итог: {self.winner}", side=self.winner)

    def run(self, turns=None):
        limit = self.max_turns if turns is None else min(self.max_turns, turns)
        while not self.finished and self.turn < limit:
            self.tick()
        return self.summary()

    def counts(self):
        return Counter(e["kind"] for e in self.events)

    def summary(self):
        return {
            "seed": self.seed,
            "turn": self.turn,
            "winner": self.winner,
            "finished": self.finished,
            "counts": dict(self.counts()),
            "sides": {
                "red": [
                    d.snapshot()
                    for d in self._detachments(side="red", active_only=False)
                ],
                "blue": [
                    d.snapshot()
                    for d in self._detachments(side="blue", active_only=False)
                ],
            },
            "organizations": [
                organization.snapshot()
                for organization in self.organizations
                if callable(getattr(organization, "snapshot", None))
            ],
            "events": list(self.events),
        }


def _character_roster(side, prefix, archetypes, seed):
    return [
        Character(
            f"{prefix}-{i + 1}",
            side,
            seed=seed + i * 37,
            archetype=arch,
            role=arch,
        )
        for i, arch in enumerate(archetypes)
    ]


def build_demo_scenario(seed=7, turns=140):
    sim = WarfareSimulation(seed=seed, turns=turns)

    red_chars = _character_roster(
        "red",
        "Р",
        ["rifleman", "veteran", "machinegunner", "conscript", "commissar"],
        seed,
    )
    red2_chars = _character_roster(
        "red",
        "Р2",
        ["rifleman", "medic", "machinegunner", "conscript"],
        seed + 100,
    )
    red3_chars = _character_roster(
        "red",
        "Р3",
        ["conscript", "rifleman", "chaplain", "conscript"],
        seed + 200,
    )
    barrier_chars = _character_roster(
        "red", "З", ["commissar", "commissar", "machinegunner"], seed + 300
    )

    blue_chars = _character_roster(
        "blue",
        "С",
        ["veteran", "rifleman", "scout", "machinegunner", "conscript"],
        seed + 400,
    )
    blue2_chars = _character_roster(
        "blue",
        "С2",
        ["rifleman", "commissar", "scout", "conscript"],
        seed + 500,
    )
    blue3_chars = _character_roster(
        "blue",
        "С3",
        ["chaplain", "commissar", "veteran", "conscript"],
        seed + 600,
    )
    blue4_chars = _character_roster(
        "blue", "С4", ["veteran", "rifleman", "scout", "medic"], seed + 700
    )

    red1 = Detachment("Р-1", "red", red_chars, position=(3, 10))
    red2 = Detachment("Р-2", "red", red2_chars, position=(2, 6))
    red3 = Detachment("Р-3", "red", red3_chars, position=(1, 14))
    barrier = BarrierDetachment(
        "Р-ЗАГРАД",
        "red",
        barrier_chars,
        position=(1, 11),
        targets=["Р-1", "Р-2"],
    )
    blue1 = Detachment(
        "С-1", "blue", blue_chars, position=(12, 9), doctrine="assault"
    )
    blue2 = Detachment("С-2", "blue", blue2_chars, position=(13, 13))
    blue3 = Detachment(
        "С-3", "blue", blue3_chars, position=(14, 6), doctrine="assault"
    )
    blue4 = Detachment("С-4", "blue", blue4_chars, position=(15, 11))

    for det in (red1, red2, red3, barrier, blue1, blue2, blue3, blue4):
        sim.add_detachment(det)

    sim.issue_order(
        Order(
            "Держать рубеж",
            OrderSignal(
                aggression=0.02,
                discipline=0.12,
                morale=1.0,
                retreat_allowed=True,
                label="удержание",
            ),
            duration=999,
            targets=[red1, red2, red3],
            side="red",
        )
    )
    sim.issue_order(
        Order(
            "Вперёд",
            OrderSignal(
                aggression=0.16,
                morale=1.5,
                fanaticism=0.06,
                retreat_allowed=True,
                label="наступление",
            ),
            duration=999,
            targets=[blue1, blue2, blue3, blue4],
            side="blue",
        )
    )

    for turn in (22, 55, 88):
        sim.schedule_order(
            turn,
            Order(
                f"Артобстрел-{turn}",
                OrderSignal(
                    fear=0.10,
                    morale=-1.5,
                    needs={"anxiety": -0.08},
                    label="артиллерия",
                ),
                duration=3,
                targets=[blue1, blue2, blue3, blue4],
                side="red",
                defer=True,
            ),
        )
    for turn in (30, 65, 100):
        sim.schedule_order(
            turn,
            Order(
                f"Дрон-разведка-{turn}",
                OrderSignal(
                    fear=0.06, needs={"anxiety": -0.04}, label="разведка"
                ),
                duration=4,
                targets=[red1, red2, red3],
                side="blue",
                defer=True,
            ),
        )

    red_reserve = Detachment(
        "Р-резерв-1",
        "red",
        _character_roster(
            "red", "РР", ["conscript", "rifleman", "machinegunner"], seed + 800
        ),
        position=(0, 8),
    )
    blue_reserve = Detachment(
        "С-резерв-1",
        "blue",
        _character_roster(
            "blue", "СР", ["veteran", "scout", "conscript"], seed + 900
        ),
        position=(23, 8),
    )
    sim.add_stan(
        Stan(
            "Стан-Р",
            "red",
            reserve=[red_reserve],
            spawn_interval=9,
            position=(0, 8),
            rally=(1, 8),
        )
    )
    sim.add_stan(
        Stan(
            "Стан-С",
            "blue",
            reserve=[blue_reserve],
            spawn_interval=12,
            position=(23, 8),
            rally=(22, 8),
        )
    )

    red_reinf = Detachment(
        "Р-подкрепление",
        "red",
        _character_roster(
            "red",
            "РП",
            ["veteran", "rifleman", "medic", "machinegunner"],
            seed + 1000,
        ),
        position=(0, 18),
    )
    blue_reinf = Detachment(
        "С-подкрепление",
        "blue",
        _character_roster(
            "blue",
            "СП",
            ["veteran", "commissar", "scout", "machinegunner"],
            seed + 1100,
        ),
        position=(23, 18),
    )
    sim.add_reinforcement(
        Reinforcement(
            "Подкрепление-Р",
            "red",
            [red_reinf],
            delay=14,
            position=(0, 18),
            rally=(2, 17),
        )
    )
    sim.add_reinforcement(
        Reinforcement(
            "Подкрепление-С",
            "blue",
            [blue_reinf],
            delay=18,
            position=(23, 18),
            rally=(21, 17),
        )
    )

    return sim


def main(seed=7, turns=140, verbose=True):
    sim = build_demo_scenario(seed=seed, turns=turns)
    summary = sim.run()
    counts = summary["counts"]
    if verbose:
        print(
            f"Войсковая симуляция: seed={seed}, тактов={summary['turn']}, "
            f"итог={summary['winner']}"
        )
        print(
            "События:",
            ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        )
        print("\nКлючевые эпизоды:")
        for event in summary["events"]:
            if event["kind"] in (
                "panic",
                "retreat",
                "banzai",
                "barrier",
                "barrier_fire",
                "spawn",
                "reinforcement",
                "broken",
                "end",
            ):
                print(
                    f"  [{event['turn']:03d}] {event['kind']:14s} "
                    f"{event['text']}"
                )
    return summary


if __name__ == "__main__":
    main()
