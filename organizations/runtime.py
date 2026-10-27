from __future__ import annotations

import math

import simulation as S

from .model import (
    Member,
    OrganizationParameters,
    OrganizationSolver,
    Population,
)
from .needs import NEEDS

MODE_EFFECTS = {
    "order": (("fear", 0.55), ("anxiety", 0.45)),
    "meaning": (("spirituality", 0.70), ("anxiety", 0.20)),
    "provision": (("hunger", 0.50), ("thirst", 0.50), ("fatigue", 0.40)),
    "status": (("status", 0.70),),
    "knowledge": (
        ("knowledge", 0.50),
        ("boredom", 0.40),
        ("creativity", 0.20),
    ),
    "care": (("loneliness", 0.50), ("friendship", 0.40), ("love", 0.30)),
    "exchange": (("hunger", 0.20), ("thirst", 0.20), ("skill", 0.20)),
}

PHASE_ORDER = (
    "mobilizing",
    "producing",
    "distributing",
    "enforcing",
    "legitimating",
    "reproducing",
)


def _clamp(value, low=0.0, high=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    if math.isnan(value) or math.isinf(value):
        return low
    return max(low, min(high, value))


class OrganizationRuntime(S.Environment):

    def __init__(
        self,
        name,
        side,
        detachments=None,
        characters=None,
        parameters=None,
        complete_weight=0.8,
        links=None,
        leader_id=None,
        apply_effects=True,
        satisfaction_per_tick=0.03,
        contribution_cost=0.08,
        coercion_factor=0.5,
        leader_morale_bonus=10.0,
        allow_rejoin=False,
    ):
        detachments = list(detachments or [])
        characters = list(characters or [])
        members = detachments if detachments else characters
        super().__init__(
            start_force=max(10.0, float(len(members))),
            members=members,
        )
        self.name = str(name)
        self.side = side
        self.detachments = detachments
        self.characters = characters
        self.parameters = parameters or OrganizationParameters()
        self.solver = OrganizationSolver(self.parameters)
        self.complete_weight = _clamp(complete_weight, 0.0, 1.0)
        self.links = list(links) if links is not None else None
        self.leader_id = leader_id
        self.apply_effects = bool(apply_effects)
        self.satisfaction_per_tick = max(0.0, float(satisfaction_per_tick))
        self.contribution_cost = max(0.0, float(contribution_cost))
        self.coercion_factor = max(0.0, float(coercion_factor))
        self.leader_morale_bonus = max(0.0, float(leader_morale_bonus))
        self.allow_rejoin = bool(allow_rejoin)

        self.tick_count = 0
        self.phase = "latent"
        self.active = bool(members)
        self.exited = set()
        self.analysis = None
        self.last_effects = {}
        self.events = []
        self._phase_cursor = 0
        self._announced_active = False
        self._dissolved_event_sent = False
        self._dissolution_applied = False
        self._last_crisis = False

    def _character_bindings(self):
        bindings = []
        seen = set()
        for det in self.detachments:
            if getattr(det, "broken", False):
                continue
            for character in list(getattr(det, "characters", []) or []):
                if getattr(character, "is_dead", False):
                    continue
                member_id = "%s/%s" % (
                    getattr(det, "name", "det"),
                    getattr(character, "name", "char"),
                )
                if not self.allow_rejoin and member_id in self.exited:
                    continue
                bindings.append((member_id, character, det))
                seen.add(id(character))
        for character in self.characters:
            if id(character) in seen or getattr(character, "is_dead", False):
                continue
            member_id = str(getattr(character, "name", "char"))
            if not self.allow_rejoin and member_id in self.exited:
                continue
            bindings.append((member_id, character, None))
        return bindings

    def _build_population(self, bindings):
        members = [
            Member.from_character(character, member_id=member_id)
            for member_id, character, _det in bindings
        ]
        if not members:
            return None
        if self.leader_id:
            chosen = next(
                (
                    member
                    for member in members
                    if member.id == self.leader_id
                    or member.name == self.leader_id
                ),
                None,
            )
            if chosen is not None:
                chosen.force = max(member.force for member in members) + 1.0
        if self.links is not None:
            return Population(members=members, links=self.links)
        return Population.complete(members, weight=self.complete_weight)

    def tick(self, rng=None, turn=None):
        del rng
        self.tick_count += 1
        turn = self.tick_count if turn is None else int(turn)
        if self.allow_rejoin:
            self.exited.clear()
        new_events = []

        bindings = self._character_bindings()
        population = self._build_population(bindings)
        if population is None:
            new_events.extend(self._dissolve(turn, "нет живых участников"))
            return self._with_events(new_events)

        analysis = self.solver.analyze(population)
        self.analysis = analysis
        if analysis.dissolved:
            new_events.extend(self._dissolve(turn, "нет желающих"))
            return self._with_events(new_events)

        self.active = True
        active_ids = set(analysis.active_ids)
        new_exits = []
        for member_id, _character, _det in bindings:
            if member_id in active_ids:
                continue
            if not self.allow_rejoin and member_id not in self.exited:
                self.exited.add(member_id)
                new_exits.append(member_id)
        if new_exits:
            new_events.append(
                self._event(
                    "organization_exit",
                    "%s: вышли %d участников" % (self.name, len(new_exits)),
                    turn,
                )
            )

        if not self._announced_active:
            self._announced_active = True
            new_events.append(
                self._event(
                    "organization",
                    "%s: организация активна (%s, уровень %d)"
                    % (self.name, analysis.archetype, analysis.level),
                    turn,
                )
            )

        crisis_now = analysis.willing_share < 0.5
        if crisis_now and not self._last_crisis:
            new_events.append(
                self._event(
                    "organization_crisis",
                    "%s: кризис участия (желающих %.0f%%)"
                    % (self.name, 100.0 * analysis.willing_share),
                    turn,
                )
            )
        self._last_crisis = crisis_now

        self.phase = self._next_phase(analysis)

        if self.apply_effects:
            self._apply_effects(analysis, bindings)
        return self._with_events(new_events)

    def _next_phase(self, analysis):
        if analysis.willing_share < 0.5:
            return "crisis"
        sequence = ["mobilizing", "producing", "distributing"]
        weights = analysis.mode_weights or {}
        if weights.get("order", 0.0) >= 0.12:
            sequence.append("enforcing")
        if weights.get("meaning", 0.0) + weights.get("status", 0.0) >= 0.18:
            sequence.append("legitimating")
        sequence.append("reproducing")
        phase = sequence[self._phase_cursor % len(sequence)]
        self._phase_cursor += 1
        return phase

    def _effects_for(self, analysis):
        base = self.satisfaction_per_tick * analysis.service_quality
        effects = {}

        def add(need, amount):
            if need in NEEDS and amount > 0.0:
                effects[need] = effects.get(need, 0.0) + amount

        if analysis.priority_need:
            add(analysis.priority_need, base * (0.5 + analysis.priority_share))
        for mode, items in MODE_EFFECTS.items():
            weight = (analysis.mode_weights or {}).get(mode, 0.0)
            if weight <= 0.0:
                continue
            for need, factor in items:
                add(need, base * weight * factor)
        return {need: min(0.08, value) for need, value in effects.items()}

    def _apply_effects(self, analysis, bindings):
        effects = self._effects_for(analysis)
        self.last_effects = effects
        assessments = {item.id: item for item in analysis.assessments}
        touched = set()
        for member_id, character, det in bindings:
            assessment = assessments.get(member_id)
            if assessment is None:
                continue
            character.satisfy(
                effects,
                morale_bonus=0.5 * analysis.service_quality,
            )
            cost = analysis.contribution_rate * self.contribution_cost
            character.needs["fatigue"] = min(
                1.0, character.needs.get("fatigue", 0.0) + cost
            )
            character.needs["hunger"] = min(
                1.0, character.needs.get("hunger", 0.0) + cost * 0.3
            )
            risk = self.coercion_factor * assessment.coercion_risk
            character.needs["fear"] = min(
                1.0, character.needs.get("fear", 0.0) + risk
            )
            character.needs["anxiety"] = min(
                1.0, character.needs.get("anxiety", 0.0) + risk * 0.5
            )
            legitimation = _clamp(
                0.5 * (analysis.mode_weights or {}).get("meaning", 0.0)
                + 0.3 * (analysis.mode_weights or {}).get("order", 0.0)
                + 0.2 * (analysis.mode_weights or {}).get("status", 0.0)
            )
            character.needs["anxiety"] = max(
                0.0, character.needs["anxiety"] - 0.003 * legitimation
            )
            character.morale = _clamp(
                character.morale - 10.0 * risk + 0.2 * legitimation, 0.0, 100.0
            )
            if assessment.leader:
                character.morale = _clamp(
                    character.morale
                    + self.leader_morale_bonus * assessment.leader_rent,
                    0.0,
                    100.0,
                )
            character.deliberate()
            if det is not None:
                touched.add(det)
        for det in touched:
            det.refresh_psychology()

    def _dissolve(self, turn, reason):
        events = []
        if not self._dissolved_event_sent:
            self._dissolved_event_sent = True
            self.active = False
            self.phase = "dissolved"
            events.append(
                self._event(
                    "organization_dissolved",
                    "%s: распад (%s)" % (self.name, reason),
                    turn,
                )
            )
        elif not self.active:
            self.phase = "dissolved"
            return events
        self.active = False
        self.phase = "dissolved"
        if not self._dissolution_applied:
            self._dissolution_applied = True
            bindings = self._character_bindings()
            touched = set()
            for _member_id, character, det in bindings:
                character.morale = _clamp(character.morale - 2.0, 0.0, 100.0)
                character.needs["fear"] = min(
                    1.0, character.needs.get("fear", 0.0) + 0.01
                )
                character.needs["anxiety"] = min(
                    1.0, character.needs.get("anxiety", 0.0) + 0.005
                )
                if det is not None:
                    touched.add(det)
            for det in touched:
                det.refresh_psychology()
            if not self.allow_rejoin:
                for member_id, _character, _det in bindings:
                    self.exited.add(member_id)
        return events

    def _event(self, kind, text, turn):
        event = {
            "turn": int(turn),
            "kind": kind,
            "text": text,
            "side": self.side,
            "actor": self.name,
        }
        self.events = (self.events + [event])[-50:]
        return event

    def _with_events(self, events):
        snapshot = self.snapshot()
        snapshot["events"] = list(events)
        return snapshot

    def snapshot(self):
        analysis = self.analysis
        return {
            "force": self.force,
            "energy_pool": self.energy_pool,
            "name": self.name,
            "side": self.side,
            "tick": self.tick_count,
            "active": self.active,
            "phase": self.phase,
            "leader_id": self.leader_id
            or (analysis.leader_id if analysis else None),
            "priority_need": analysis.priority_need if analysis else None,
            "archetype": analysis.archetype if analysis else "—",
            "level": analysis.level if analysis else 0,
            "capacity": analysis.capacity if analysis else 0,
            "initial_count": analysis.initial_count if analysis else 0,
            "active_count": analysis.active_count if analysis else 0,
            "willing_share": analysis.willing_share if analysis else 0.0,
            "density": analysis.density if analysis else 0.0,
            "effective_count": analysis.effective_count if analysis else 0.0,
            "scale": analysis.scale if analysis else 0.0,
            "top_mode": analysis.top_mode if analysis else None,
            "mode_weights": dict(analysis.mode_weights) if analysis else {},
            "exited": len(self.exited),
            "last_effects": dict(self.last_effects),
        }

    def public_snapshot(self):
        return {
            "name": self.name,
            "side": self.side,
            "active": self.active,
            "phase": self.phase,
            "priority_need": (
                self.analysis.priority_need if self.analysis else None
            ),
            "level": self.analysis.level if self.analysis else 0,
            "active_count": self.analysis.active_count if self.analysis else 0,
        }

    def reset(self):
        self.tick_count = 0
        self.phase = "latent"
        self.active = bool(self.detachments or self.characters)
        self.exited.clear()
        self.analysis = None
        self.last_effects = {}
        self.events = []
        self._phase_cursor = 0
        self._announced_active = False
        self._dissolved_event_sent = False
        self._dissolution_applied = False
        self._last_crisis = False


def build_runtime_demo(seed=7, turns=12, side="red", name="фронт"):
    import warfare as W

    sim = W.build_demo_scenario(seed=seed, turns=max(1, int(turns)))
    detachments = [det for det in sim.detachments if det.side == side]
    organization = OrganizationRuntime(name, side, detachments=detachments)
    sim.add_organization(organization)
    return sim, organization


__all__ = [
    "MODE_EFFECTS",
    "OrganizationRuntime",
    "PHASE_ORDER",
    "build_runtime_demo",
]
