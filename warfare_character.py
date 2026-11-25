"""Персонаж тактической симуляции: BDI, черты и состояния.

Вынесено из ``warfare.py`` после W4. Общие константы и приказы живут в
``warfare_core.py``; ``warfare.py`` остаётся фасадом и хранит отряды и
симуляцию.
"""

from __future__ import annotations

import random

import simulation as S
from warfare_core import *  # noqa: F401,F403


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
        # Объект намерения из контента (фракция, орган, персонаж). Если
        # пуст, BDI направляет намерение на ведущую потребность.
        self.deliberate_target = ""

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
        self.bdi = BDI.BDIState(
            character_id=str(name),
            needs={n: initial[n] for n in NEEDS},
            traits=self.personality.as_dict(),
        )
        self.desires = self.bdi.weighted_desires(TRAIT_MODEL)
        self.beliefs = self.bdi.beliefs
        self.intentions = self.bdi.intentions
        self.morale = TRAIT_MODEL.morale_value(
            "initial_base", 59.0
        ) + TRAIT_MODEL.morale_value(
            "initial_courage", 12.0
        ) * self.personality["courage"]
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

        # Ролевые деления: 15 измерений из
        # ``configs/characters/divisions.json``.
        try:
            from campaign.divisions import Divisions

            self.divisions = Divisions.from_data({})
        except Exception:
            self.divisions = None

    def set_division(self, dimension, value_id):
        """Задать одно из 15 ролевых делений персонажа."""
        if self.divisions is None:
            from campaign.divisions import Divisions

            self.divisions = Divisions.from_data({})
        return self.divisions.set(dimension, value_id)

    def division(self, dimension, default=None):
        if self.divisions is None:
            return default
        return self.divisions.get(dimension, default)

    def division_tags(self):
        if self.divisions is None:
            return []
        return self.divisions.tags()

    # --- BDI: желания, убеждения, намерения -------------------------
    @property
    def needs(self):
        """16 желаний BDI (0 — удовлетворено, 1 — предельная нужда)."""
        return self.bdi.needs

    @needs.setter
    def needs(self, values):
        values = dict(values or {})
        for key, definition in self.bdi.config.needs.items():
            if key in values:
                try:
                    self.bdi.needs[key] = max(
                        0.0, min(1.0, float(values[key]))
                    )
                except (TypeError, ValueError):
                    continue

    @property
    def beliefs(self):
        """Убеждения-триплеты ``(субъект, предикат, объект)``."""
        bdi = getattr(self, "bdi", None)
        if bdi is None:
            return getattr(self, "_legacy_beliefs", {})
        return bdi.beliefs

    @beliefs.setter
    def beliefs(self, values):
        bdi = getattr(self, "bdi", None)
        if bdi is None:
            # ``simulation.Agent.reset_state`` пишет сюда легаси-словарь до
            # создания BDI. Не смешиваем его с триплетами.
            self._legacy_beliefs = dict(values or {})
            return
        self.bdi.beliefs = [
            self.bdi.config.validate_belief(item)
            for item in (values or ())
        ]

    @property
    def intentions(self):
        """Намерения-дуплеты ``(объект, суть)``."""
        return self.bdi.intentions

    @intentions.setter
    def intentions(self, values):
        self.bdi.intentions = [
            self.bdi.config.validate_intention(item)
            for item in (values or ())
        ][-self.bdi.config.history :]

    def believe(self, subject, predicate, object):
        """Записать триплет убеждения и вернуть его."""
        belief = self.bdi.believe(subject, predicate, object)
        self.beliefs = self.bdi.beliefs
        return belief

    def forget(self, subject, predicate=None, object=None):
        removed = self.bdi.forget(subject, predicate, object)
        self.beliefs = self.bdi.beliefs
        return removed

    def intend(self, target, essence):
        """Записать дуплет намерения и вернуть его."""
        intention = self.bdi.intend(target, essence)
        self.intentions = self.bdi.intentions
        return intention

    @property
    def conditions(self):
        """Состояния BDI: болезнь и раны (не метрики автомата)."""
        return self.bdi.conditions

    @property
    def sickness(self):
        return float(self.bdi.condition("sickness"))

    @sickness.setter
    def sickness(self, value):
        definition = self.bdi.config.conditions.get("sickness")
        maximum = definition.maximum if definition else 1.0
        self.bdi.conditions["sickness"] = max(
            0.0, min(maximum, float(value))
        )

    @property
    def wound(self):
        return float(self.bdi.condition("wound"))

    @wound.setter
    def wound(self, value):
        definition = self.bdi.config.conditions.get("wound")
        maximum = definition.maximum if definition else 1.0
        self.bdi.conditions["wound"] = max(0.0, min(maximum, float(value)))

    @property
    def health(self):
        """Здоровье как BDI-желание, спроецированное в шкалу ``0..100``.

        Это не отдельная метрика автомата: ``100`` — здоровая потребность
        ``health == 0``, ``0`` — предельная нужда ``health == 1``.
        """
        return 100.0 * (1.0 - float(self.bdi.needs.get("health", 0.0)))

    @health.setter
    def health(self, value):
        try:
            need = 1.0 - max(0.0, min(100.0, float(value))) / 100.0
        except (TypeError, ValueError):
            return
        self.bdi.needs["health"] = max(0.0, min(1.0, need))

    @property
    def is_dead(self):
        """Смерть персонажа наступает, когда кончается сила ``F``.

        Здоровье, раны и болезнь — состояния BDI; они давят на силу и
        энергию, но не являются отдельным порогом смерти.
        """
        return bool(self.dead or float(self.force) <= 0.0)

    def add_force(self, amount):
        before = float(self.force)
        maximum = float(self.state.get("max_force", max(1.0, before)))
        self.force = max(0.0, min(maximum, before + float(amount)))
        return float(self.force) - before

    def add_energy(self, amount):
        before = float(self.energy_pool)
        maximum = float(self.state.get("max_energy", max(1.0, before)))
        self.energy_pool = max(
            0.0, min(maximum, before + float(amount))
        )
        return float(self.energy_pool) - before

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
        self.bdi.traits = self.personality.as_dict()
        return self.bdi.weighted_desires(TRAIT_MODEL)

    def deliberate(self, target=None, preferred=None):
        """Выбрать намерение, по умолчанию направленное на потребность.

        ``target`` — объект из контента (фракция, орган, персонаж). Если
        он задан, BDI не подменяет его ведущей потребностью: суть
        политического действия важнее биологического fallback.

        ``preferred`` — подсказка личной цели (данные автономии
        кампании). Паника и фанатизм сильнее цели: они спасают или
        ломают человека раньше, чем он вспомнит о своём замысле.
        """
        self.bdi.traits = self.personality.as_dict()
        self.desires = self.bdi.weighted_desires(TRAIT_MODEL)
        need = max(NEEDS, key=lambda n: self.desires[n])
        target = target or self.deliberate_target
        values = self.personality.as_dict()
        mod = self.modulation()
        hint = str(preferred or "")

        forbidden = [] if mod.retreat_allowed else ["retreat"]
        preferred = ""
        if self.panicked and mod.retreat_allowed:
            preferred = "retreat"
        elif (
            self.fanatical
            or mod.fanaticism > TRAIT_MODEL.fanaticism_override()
        ):
            preferred = "attack"
        elif hint and hint not in forbidden:
            preferred = hint
        else:
            kind, _scores = TRAIT_MODEL.choose_intent(
                self.desires, values, mod
            )
            preferred = ESSENCE_FOR_KIND.get(kind, "")
        intent = self.bdi.choose_intention(
            TRAIT_MODEL,
            {
                "target": target or need,
                "preferred": preferred,
                "forbidden": forbidden,
            },
        )
        self.beliefs = self.bdi.beliefs
        self.intentions = self.bdi.intentions
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
        resting_needs=None,
        rng=None,
        seconds=1800,
        rate_multipliers=None,
        morale_baseline_bonus=0.0,
        seconds_per_unit=1800.0,
        morale_seconds_per_unit=None,
        morale_stress_mul=1.0,
        morale_drift_mul=1.0,
    ):
        rng = rng or self.rng
        if self.is_dead:
            self.dead = True
            self.mind = "dead"
            self.morale = 0.0
            return
        mod = self.modulation()
        uf = max(0.0, min(1.0, float(under_fire)))
        support = max(0.0, min(1.0, float(supported)))
        unit = max(1e-9, float(seconds_per_unit))
        morale_unit = max(
            1e-9,
            float(
                morale_seconds_per_unit
                if morale_seconds_per_unit is not None
                else unit
            ),
        )
        scale = max(0.0, float(seconds)) / unit
        # Мораль и приказы в кампании считаются за сутки, а потребности —
        # за свой такт BDI. В бою оба масштаба совпадают.
        morale_scale = max(0.0, float(seconds)) / morale_unit
        values = self.personality.as_dict()
        self.bdi.traits = values

        deltas = self.bdi.tick(
            seconds=seconds,
            in_combat=in_combat,
            under_fire=uf,
            support=support,
            resting=rested,
            resting_needs=resting_needs,
            order_needs=mod.needs,
            rate_multipliers=rate_multipliers,
            trait_model=TRAIT_MODEL,
            seconds_per_unit=unit,
        )

        # BDI не хранит силу и энергию: персонаж применяет давление сам.
        force_delta = float(deltas.get("force", 0.0))
        energy_delta = float(deltas.get("energy", 0.0))
        if force_delta:
            self.force = max(0.0, float(self.force) + force_delta)
        if energy_delta:
            self.energy_pool = max(
                0.0, float(self.energy_pool) + energy_delta
            )

        if mod.fear:
            self.bdi.needs["fear"] = min(
                1.0, self.bdi.needs["fear"] + mod.fear * morale_scale
            )
        if mod.discipline:
            self.bdi.needs["anxiety"] = max(
                0.0,
                self.bdi.needs["anxiety"]
                - 0.02 * mod.discipline * morale_scale,
            )
            self.bdi.needs["fear"] = max(
                0.0,
                self.bdi.needs["fear"]
                - 0.01 * mod.discipline * morale_scale,
            )

        stress = TRAIT_MODEL.morale_stress(self.needs)
        baseline = (
            TRAIT_MODEL.morale_value("base", 50.0)
            + TRAIT_MODEL.morale_baseline(values)
            + float(morale_baseline_bonus)
        )
        drift = TRAIT_MODEL.morale_value("drift", 0.03) * (
            baseline - self.morale
        )
        self.morale += morale_scale * (
            drift * max(0.0, float(morale_drift_mul))
            - TRAIT_MODEL.morale_value("stress_scale", 4.0)
            * stress
            * max(0.0, float(morale_stress_mul))
            - TRAIT_MODEL.morale_value("under_fire_penalty", 3.0) * uf
            + TRAIT_MODEL.morale_value("order_morale", 0.15) * mod.morale
            + TRAIT_MODEL.morale_value("support_bonus", 0.20) * support
            + TRAIT_MODEL.morale_value("order_discipline", 0.10)
            * mod.discipline
        )
        self.morale = max(0.0, min(100.0, self.morale))
        self.under_fire = uf
        self.casualties = max(
            0.0, self.casualties + uf * 0.1 * morale_scale
        )

        if self.is_dead:
            self.dead = True
            self.mind = "dead"
            self.morale = 0.0
            return

        self._update_mind(rng)
        self.deliberate()

    def _update_mind(self, rng):
        values = self.personality.as_dict()
        mod = self.modulation()
        fear = self.needs["fear"]
        anxiety = self.needs["anxiety"]
        morale_norm = self.morale / 100.0
        noise = (rng.random() - 0.5) * TRAIT_MODEL.mind_value(
            "panic_noise", 0.08
        )

        panic_needs = TRAIT_MODEL.mind.get("panic_needs") or {}
        panic_score = (
            sum(
                self.needs.get(str(need), 0.0) * float(weight)
                for need, weight in panic_needs.items()
            )
            + TRAIT_MODEL.mind_value("panic_morale", 0.38)
            * (1.0 - morale_norm)
            + noise
            + TRAIT_MODEL.panic_contribution(values)
            + TRAIT_MODEL.mind_value("panic_mod_discipline", -0.10)
            * mod.discipline
        )
        fanatic_needs = TRAIT_MODEL.mind.get("fanatic_needs") or {}
        fanatic_score = (
            sum(
                self.needs.get(str(need), 0.0) * float(weight)
                for need, weight in fanatic_needs.items()
            )
            + TRAIT_MODEL.mind_value("fanatic_morale", 0.16) * morale_norm
            + noise
            + TRAIT_MODEL.fanatic_contribution(values)
            + TRAIT_MODEL.mind_value("fanatic_mod_fanaticism", 0.25)
            * mod.fanaticism
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
            panic_score > TRAIT_MODEL.panic_threshold()
            and mod.retreat_allowed
            and self.panic_timer == 0
            and self.panic_cooldown == 0
        )
        fanatical_now = (
            fanatic_score > TRAIT_MODEL.fanatic_threshold()
            and not panicked_now
            and self.fanatic_timer == 0
            and self.fanatic_cooldown == 0
            and self.morale > TRAIT_MODEL.fanatic_morale_floor()
        )
        if panicked_now:
            self.panicked = True
            self.fanatical = False
            self.mind = "panicked"
            self.panic_timer = TRAIT_MODEL.panic_timer()
            self.panic_cooldown = TRAIT_MODEL.panic_cooldown()
        elif fanatical_now:
            self.fanatical = True
            self.panicked = False
            self.mind = "fanatical"
            self.fanatic_timer = TRAIT_MODEL.fanatic_timer()
            self.fanatic_cooldown = TRAIT_MODEL.fanatic_cooldown()
        elif panic_score > TRAIT_MODEL.shaken_threshold():
            self.panicked = False
            self.fanatical = False
            self.mind = "shaken"
        else:
            self.panicked = False
            self.fanatical = False
            self.mind = "steady"

    def satisfy(self, effects, morale_bonus=0.0):
        if self.is_dead:
            return {}
        result = self.bdi.satisfy(effects)
        restored = dict(result.get("restored") or {})
        if result.get("force"):
            self.force = min(
                float(self.state.get("max_force", 10.0)),
                max(0.0, float(self.force) + float(result["force"])),
            )
        if result.get("energy"):
            self.energy_pool = max(
                0.0, float(self.energy_pool) + float(result["energy"])
            )
        total = sum(restored.values())
        if total and morale_bonus:
            self.morale = max(
                0.0, min(100.0, self.morale + morale_bonus * total)
            )
        self.desires = self.bdi.weighted_desires(TRAIT_MODEL)
        return restored

    def needs_summary(self):
        if not self.needs:
            return {}
        return {need: float(self.needs.get(need, 0.0)) for need in NEEDS}

    def snapshot(self):
        intention = self.bdi.latest_intention()
        return {
            "name": self.name,
            "side": self.side,
            "role": self.role,
            "mind": self.mind,
            "morale": round(self.morale, 1),
            "force": round(float(self.force), 3),
            "energy": round(float(self.energy_pool), 3),
            "needs": {n: round(v, 3) for n, v in self.needs.items()},
            "desires": {n: round(v, 3) for n, v in self.desires.items()},
            "intention": intention.as_dict() if intention else None,
            "beliefs": [item.as_dict() for item in self.bdi.beliefs],
            "conditions": {
                key: round(value, 3)
                for key, value in self.bdi.conditions.items()
            },
            "divisions": (
                self.divisions.as_dict() if self.divisions is not None else {}
            ),
            "personality": self.personality.as_dict(),
        }
