from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, List, Mapping, Optional, Tuple

from .needs import (
    ARCHETYPE_TIERS,
    COERCION_MODES,
    CONTRIBUTION_MODES,
    LEGITIMATION_MODES,
    LEVEL_MODE_BOOST,
    MODE_ORDER,
    MODE_RU,
    NEED_AFFINITY,
    NEED_GOODS,
    NEEDS,
    NEEDS_RU,
    REPRODUCTION_MODES,
)


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


def organization_level(effective_count, threshold=165.0):
    effective_count = max(0.0, _number(effective_count, 0.0))
    threshold = max(1e-12, _number(threshold, 165.0))
    if effective_count <= 0.0:
        return 0
    return max(1, int(math.ceil(math.sqrt(effective_count / threshold))))


def level_capacity(level, threshold=165.0):
    level = max(0, int(level))
    return max(1e-12, _number(threshold, 165.0)) * level * level


@dataclass
class Member:

    id: str
    needs: Mapping[str, float] = field(default_factory=dict)
    urgency: Optional[Mapping[str, float]] = None
    energy: float = 1.0
    force: float = 1.0
    name: str = ""

    def __post_init__(self):
        self.id = str(self.id or "").strip()
        if not self.id:
            raise ValueError("у участника должен быть непустой id")
        self.name = str(self.name or self.id)
        raw_needs = dict(self.needs or {})
        self.needs = {
            need: _clamp(raw_needs.get(need, 0.0), 0.0, 1.0) for need in NEEDS
        }
        raw_urgency = self.urgency if self.urgency is not None else self.needs
        raw_urgency = dict(raw_urgency or {})
        self.urgency = {
            need: max(0.0, _number(raw_urgency.get(need, 0.0), 0.0))
            for need in NEEDS
        }
        self.energy = max(0.0, _number(self.energy, 0.0))
        self.force = max(0.0, _number(self.force, 0.0))

    @classmethod
    def from_character(cls, character, member_id=None):
        urgency = None
        getter = getattr(character, "weighted_urgency", None)
        if callable(getter):
            urgency = getter()
        needs = getattr(character, "needs", None)
        if needs is None:
            needs = urgency or {}
        return cls(
            id=member_id or getattr(character, "name", None) or "member",
            needs=needs,
            urgency=urgency,
            energy=getattr(character, "energy_pool", 1.0),
            force=getattr(character, "force", 1.0),
            name=getattr(character, "name", "") or "",
        )

    def priority_demand(self, priority_weights):
        return sum(
            _clamp(priority_weights.get(need, 0.0), 0.0, 1.0)
            * self.needs[need]
            for need in NEEDS
        )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "needs": dict(self.needs),
            "urgency": dict(self.urgency),
            "energy": self.energy,
            "force": self.force,
        }


@dataclass
class Population:

    members: List[Member] = field(default_factory=list)
    links: List[Tuple[str, str, float]] = field(default_factory=list)
    complete_weight: Optional[float] = None

    def __post_init__(self):
        self.members = list(self.members or [])
        self.links = list(self.links or [])
        if not self.members:
            raise ValueError("население не может быть пустым")
        self._by_id = {}
        for member in self.members:
            if not isinstance(member, Member):
                raise TypeError("members должен содержать Member")
            if member.id in self._by_id:
                raise ValueError("повторяющийся id участника: %s" % member.id)
            self._by_id[member.id] = member

        if self.complete_weight is not None:
            self.complete_weight = _clamp(self.complete_weight, 0.0, 1.0)
            if self.links:
                raise ValueError(
                    "нельзя одновременно задавать links и complete_weight"
                )
            self._adjacency = {}
        else:
            adjacency = {}
            for item in self.links:
                if not isinstance(item, (tuple, list)) or len(item) != 3:
                    raise ValueError("связь должна быть (id_a, id_b, weight)")
                left, right, weight = item
                if left not in self._by_id or right not in self._by_id:
                    raise ValueError(
                        "связь ссылается на неизвестного участника"
                    )
                if left == right:
                    raise ValueError("петля участника не является связью")
                key = (left, right) if left < right else (right, left)
                if key in adjacency:
                    raise ValueError("повторяющаяся связь: %s — %s" % key)
                adjacency[key] = _clamp(weight, 0.0, 1.0)
            self._adjacency = adjacency

    @classmethod
    def complete(cls, members, weight=1.0):
        return cls(members=list(members), complete_weight=weight)

    @classmethod
    def from_characters(cls, characters, links=None, complete_weight=None):
        members = [
            Member.from_character(character) for character in characters
        ]
        return cls(
            members=members,
            links=list(links or []),
            complete_weight=complete_weight,
        )

    @property
    def ids(self):
        return [member.id for member in self.members]

    @property
    def leader(self):
        return max(self.members, key=lambda member: member.force)

    def _active(self, member_ids=None):
        if member_ids is None:
            return list(self.ids)
        known = set(self._by_id)
        return [
            str(member_id)
            for member_id in member_ids
            if str(member_id) in known
        ]

    def density(self, member_ids=None):
        active = self._active(member_ids)
        count = len(active)
        if count <= 0:
            return 0.0
        if count == 1:
            if self.complete_weight is not None:
                return self.complete_weight
            return 1.0
        if self.complete_weight is not None:
            return self.complete_weight
        active_set = set(active)
        total = 0.0
        for (left, right), weight in self._adjacency.items():
            if left in active_set and right in active_set:
                total += weight
        pairs = count * (count - 1) / 2.0
        return _clamp(total / pairs, 0.0, 1.0)

    def strengths(self, member_ids=None):
        active = self._active(member_ids)
        if self.complete_weight is not None:
            weight = self.complete_weight
            return {
                member_id: (len(active) - 1) * weight for member_id in active
            }
        active_set = set(active)
        result = {member_id: 0.0 for member_id in active}
        for (left, right), weight in self._adjacency.items():
            if left in active_set and right in active_set:
                result[left] += weight
                result[right] += weight
        return result

    def centrality(self, member_ids=None):
        strengths = self.strengths(member_ids)
        maximum = max(strengths.values(), default=0.0)
        if maximum <= 0.0:
            return {member_id: 0.0 for member_id in strengths}
        return {
            member_id: value / maximum
            for member_id, value in strengths.items()
        }

    def mean_energy(self, member_ids=None):
        active = self._active(member_ids)
        if not active:
            return 0.0
        return sum(
            self._by_id[member_id].energy for member_id in active
        ) / len(active)


@dataclass
class OrganizationParameters:

    threshold: float = 165.0
    leader_priority_weight: float = 0.35
    centrality_weight: float = 0.50

    service_base: float = 0.40
    service_per_level: float = 0.10
    service_legitimation: float = 0.25
    service_provision: float = 0.15
    service_care: float = 0.10
    service_status: float = 0.15

    network_bonus: float = 0.25
    outside_base: float = 0.30
    outside_dominant_discount: float = 0.20

    contribution_base: float = 0.05
    contribution_order: float = 0.12
    contribution_status: float = 0.03
    contribution_hierarchy: float = 0.04
    coercion_risk: float = 0.06
    leader_rent: float = 0.08

    hierarchy_base: float = 0.10
    hierarchy_step: float = 0.18
    formalization_base: float = 0.10
    formalization_step: float = 0.22
    specialization_base: float = 0.10
    specialization_step: float = 0.25

    max_iterations: int = 32

    def __post_init__(self):
        self.threshold = max(1e-12, _number(self.threshold, 165.0))
        self.leader_priority_weight = _clamp(
            self.leader_priority_weight, 0.0, 1.0
        )
        self.centrality_weight = max(0.0, _number(self.centrality_weight, 0.5))
        self.max_iterations = max(1, int(self.max_iterations))


@dataclass
class MemberAssessment:

    member: Member
    centrality: float
    demand: float
    benefit: float
    contribution: float
    coercion_risk: float
    leader_rent: float
    outside_utility: float
    margin: float
    willing: bool
    leader: bool = False

    @property
    def id(self):
        return self.member.id

    def to_dict(self):
        return {
            "id": self.member.id,
            "name": self.member.name,
            "centrality": self.centrality,
            "demand": self.demand,
            "benefit": self.benefit,
            "contribution": self.contribution,
            "coercion_risk": self.coercion_risk,
            "leader_rent": self.leader_rent,
            "outside_utility": self.outside_utility,
            "margin": self.margin,
            "willing": self.willing,
            "leader": self.leader,
        }


@dataclass
class OrganizationAnalysis:

    priority_need: Optional[str]
    priority_weights: Dict[str, float]
    priority_share: float
    leader_id: Optional[str]
    leader_force: float
    initial_count: int
    active_count: int
    effective_count: float
    density: float
    mean_energy: float
    scale: float
    level: int
    capacity: float
    hierarchy: float
    formalization: float
    specialization: float
    mode_weights: Dict[str, float]
    top_mode: Optional[str]
    archetype: str
    goods: str
    contribution: str
    coercion: str
    legitimation: str
    reproduction: str
    service_quality: float
    contribution_rate: float
    willing_count: int
    willing_share: float
    dissolved: bool
    iterations: int
    active_ids: List[str] = field(default_factory=list)
    assessments: List[MemberAssessment] = field(default_factory=list)

    @property
    def need_ru(self):
        return NEEDS_RU.get(self.priority_need or "", "не определена")

    @property
    def top_mode_ru(self):
        return MODE_RU.get(self.top_mode or "", "—")

    @property
    def label(self):
        if self.dissolved:
            return "распущена"
        return self.archetype

    @property
    def leader_willing(self):
        return any(item.leader and item.willing for item in self.assessments)

    def summary_lines(self):
        parts = []
        if self.priority_need:
            parts.append(
                "приоритетная потребность — %s (%.2f)"
                % (self.need_ru, self.priority_share)
            )
        else:
            parts.append("приоритетная потребность не определена")
        if self.leader_id:
            parts.append(
                "лидер %s (сила %.1f)" % (self.leader_id, self.leader_force)
            )
        parts.append(
            "активных N=%d, ρ=%.2f, N_eff=%.1f, S=%.1f"
            % (
                self.active_count,
                self.density,
                self.effective_count,
                self.scale,
            )
        )
        if self.level:
            parts.append(
                "уровень %d (ёмкость %d)" % (self.level, int(self.capacity))
            )
        else:
            parts.append("уровень 0 (организация не состоялась)")
        parts.append(
            "участников %d из %d (%.0f%%), итераций %d"
            % (
                self.active_count,
                self.initial_count,
                100.0 * self.willing_share,
                self.iterations,
            )
        )
        return parts

    def to_dict(self):
        return {
            "priority_need": self.priority_need,
            "priority_weights": dict(self.priority_weights),
            "priority_share": self.priority_share,
            "leader_id": self.leader_id,
            "leader_force": self.leader_force,
            "initial_count": self.initial_count,
            "active_count": self.active_count,
            "effective_count": self.effective_count,
            "density": self.density,
            "mean_energy": self.mean_energy,
            "scale": self.scale,
            "level": self.level,
            "capacity": self.capacity,
            "hierarchy": self.hierarchy,
            "formalization": self.formalization,
            "specialization": self.specialization,
            "mode_weights": dict(self.mode_weights),
            "top_mode": self.top_mode,
            "archetype": self.archetype,
            "goods": self.goods,
            "contribution": self.contribution,
            "coercion": self.coercion,
            "legitimation": self.legitimation,
            "reproduction": self.reproduction,
            "service_quality": self.service_quality,
            "contribution_rate": self.contribution_rate,
            "willing_count": self.willing_count,
            "willing_share": self.willing_share,
            "dissolved": self.dissolved,
            "leader_willing": self.leader_willing,
            "iterations": self.iterations,
            "active_ids": list(self.active_ids),
            "assessments": [item.to_dict() for item in self.assessments],
        }


class OrganizationSolver:

    def __init__(self, parameters=None):
        self.parameters = parameters or OrganizationParameters()

    def analyze(self, population):
        if not isinstance(population, Population):
            raise TypeError("population должен быть Population")
        parameters = self.parameters
        initial_ids = list(population.ids)
        initial_centrality = population.centrality(initial_ids)
        leader = population.leader
        priority = self._priority(
            population, initial_ids, initial_centrality, leader
        )

        active_ids = list(initial_ids)
        assessments = []
        iterations = 0
        while active_ids:
            metrics = self._metrics(population, active_ids, priority)
            assessments = self._assess(
                population, active_ids, metrics, priority, leader
            )
            willing_ids = [item.id for item in assessments if item.willing]
            iterations += 1
            if len(willing_ids) == len(active_ids):
                break
            active_ids = willing_ids
            if iterations >= parameters.max_iterations:
                break

        if active_ids:
            metrics = self._metrics(population, active_ids, priority)
            assessments = self._assess(
                population, active_ids, metrics, priority, leader
            )
            if iterations >= parameters.max_iterations:
                willing_ids = [item.id for item in assessments if item.willing]
                if len(willing_ids) != len(active_ids):
                    active_ids = willing_ids
                    if active_ids:
                        metrics = self._metrics(
                            population, active_ids, priority
                        )
                        assessments = self._assess(
                            population, active_ids, metrics, priority, leader
                        )
                    else:
                        metrics = self._metrics(population, [], priority)
                        assessments = []
        else:
            metrics = self._metrics(population, [], priority)
            assessments = []

        active_count = len(active_ids)
        willing_count = sum(1 for item in assessments if item.willing)
        initial_count = len(initial_ids)
        priority_need = None
        priority_share = 0.0
        if priority:
            priority_need = max(NEEDS, key=lambda need: priority[need])
            priority_share = priority[priority_need]

        dissolved = active_count == 0
        archetype = "распущена"
        if not dissolved and metrics["top_mode"]:
            archetype = self._archetype(metrics["top_mode"], metrics["level"])

        goods = NEED_GOODS.get(priority_need or "", "потребность")
        top_mode = metrics["top_mode"]
        contribution = CONTRIBUTION_MODES.get(top_mode, "взносы")
        coercion = COERCION_MODES.get(top_mode, "санкции")
        legitimation = LEGITIMATION_MODES.get(top_mode, "нормы")
        reproduction = REPRODUCTION_MODES.get(top_mode, "воспроизводство")

        return OrganizationAnalysis(
            priority_need=priority_need,
            priority_weights=priority,
            priority_share=priority_share,
            leader_id=leader.id if leader else None,
            leader_force=leader.force if leader else 0.0,
            initial_count=initial_count,
            active_count=active_count,
            effective_count=metrics["effective_count"],
            density=metrics["density"],
            mean_energy=metrics["mean_energy"],
            scale=metrics["scale"],
            level=metrics["level"],
            capacity=metrics["capacity"],
            hierarchy=metrics["hierarchy"],
            formalization=metrics["formalization"],
            specialization=metrics["specialization"],
            mode_weights=metrics["mode_weights"],
            top_mode=top_mode,
            archetype=archetype,
            goods=goods,
            contribution=contribution,
            coercion=coercion,
            legitimation=legitimation,
            reproduction=reproduction,
            service_quality=metrics["service_quality"],
            contribution_rate=metrics["contribution_rate"],
            willing_count=willing_count,
            willing_share=(
                willing_count / initial_count if initial_count else 0.0
            ),
            dissolved=dissolved,
            iterations=iterations,
            active_ids=list(active_ids),
            assessments=list(assessments),
        )

    def _priority(self, population, member_ids, centrality, leader):
        parameters = self.parameters
        mass_weights = []
        for member_id in member_ids:
            member = population._by_id[member_id]
            weight = member.energy * (
                1.0
                + parameters.centrality_weight * centrality.get(member_id, 0.0)
            )
            mass_weights.append((member, weight))
        total_weight = sum(weight for _, weight in mass_weights)
        if total_weight > 0.0:
            mass = {
                need: sum(
                    weight * member.urgency[need]
                    for member, weight in mass_weights
                )
                / total_weight
                for need in NEEDS
            }
        else:
            mass = {need: 0.0 for need in NEEDS}
        mass_total = sum(mass.values())
        if mass_total > 0.0:
            mass = {need: value / mass_total for need, value in mass.items()}

        leader_total = sum(leader.urgency.values()) if leader else 0.0
        if leader_total > 0.0:
            leader_priority = {
                need: leader.urgency[need] / leader_total for need in NEEDS
            }
        else:
            leader_priority = {need: 0.0 for need in NEEDS}

        mix = _clamp(parameters.leader_priority_weight, 0.0, 1.0)
        mixed = {
            need: (1.0 - mix) * mass[need] + mix * leader_priority[need]
            for need in NEEDS
        }
        total = sum(mixed.values())
        if total <= 0.0:
            return {}
        return {need: value / total for need, value in mixed.items()}

    def _mode_weights(self, priority, level):
        if not priority:
            return {mode: 0.0 for mode in MODE_ORDER}
        raw = {
            mode: sum(
                priority.get(need, 0.0) * NEED_AFFINITY[mode].get(need, 0.0)
                for need in NEEDS
            )
            for mode in MODE_ORDER
        }
        total = sum(raw.values())
        if total <= 0.0:
            return {mode: 0.0 for mode in MODE_ORDER}
        weights = {mode: value / total for mode, value in raw.items()}
        boost = max(0, int(level) - 1)
        if boost:
            for mode, amount in LEVEL_MODE_BOOST.items():
                weights[mode] += amount * boost
            total = sum(weights.values())
            weights = {mode: value / total for mode, value in weights.items()}
        return weights

    def _metrics(self, population, active_ids, priority):
        parameters = self.parameters
        count = len(active_ids)
        density = population.density(active_ids) if count else 0.0
        mean_energy = population.mean_energy(active_ids) if count else 0.0
        effective_count = count * density
        scale = effective_count * mean_energy
        level = organization_level(effective_count, parameters.threshold)
        capacity = level_capacity(level, parameters.threshold)
        if level:
            hierarchy = _clamp(
                parameters.hierarchy_base
                + parameters.hierarchy_step * (level - 1)
            )
            formalization = _clamp(
                parameters.formalization_base
                + parameters.formalization_step * (level - 1)
            )
            specialization = _clamp(
                parameters.specialization_base
                + parameters.specialization_step * (level - 1)
            )
        else:
            hierarchy = formalization = specialization = 0.0

        mode_weights = self._mode_weights(priority, level)
        top_mode = None
        if mode_weights and max(mode_weights.values()) > 0.0:
            top_mode = max(MODE_ORDER, key=lambda mode: mode_weights[mode])
        legitimation = _clamp(
            0.5 * mode_weights.get("meaning", 0.0)
            + 0.3 * mode_weights.get("order", 0.0)
            + 0.2 * mode_weights.get("status", 0.0)
        )
        service_quality = 0.0
        contribution_rate = 0.0
        if level:
            service_quality = _clamp(
                parameters.service_base
                + parameters.service_per_level * (level - 1)
                + parameters.service_legitimation * legitimation
                + parameters.service_provision
                * mode_weights.get("provision", 0.0)
                + parameters.service_care * mode_weights.get("care", 0.0)
                + parameters.service_status * mode_weights.get("status", 0.0)
            )
            contribution_rate = max(
                0.0,
                parameters.contribution_base
                + parameters.contribution_order
                * mode_weights.get("order", 0.0)
                + parameters.contribution_status
                * mode_weights.get("status", 0.0)
                + parameters.contribution_hierarchy * hierarchy,
            )
        return {
            "density": density,
            "mean_energy": mean_energy,
            "effective_count": effective_count,
            "scale": scale,
            "level": level,
            "capacity": capacity,
            "hierarchy": hierarchy,
            "formalization": formalization,
            "specialization": specialization,
            "mode_weights": mode_weights,
            "top_mode": top_mode,
            "legitimation": legitimation,
            "service_quality": service_quality,
            "contribution_rate": contribution_rate,
        }

    def _assess(self, population, active_ids, metrics, priority, leader):
        parameters = self.parameters
        centrality = population.centrality(active_ids)
        mean_energy = metrics["mean_energy"]
        mode_weights = metrics["mode_weights"]
        top_weight = max(mode_weights.values(), default=0.0)
        coercion_weight = mode_weights.get("order", 0.0)
        status_weight = mode_weights.get("status", 0.0)
        legitimation = metrics["legitimation"]
        assessments = []
        for member_id in active_ids:
            member = population._by_id[member_id]
            member_centrality = centrality.get(member_id, 0.0)
            demand = member.priority_demand(priority)
            benefit = (
                demand
                * metrics["service_quality"]
                * (
                    1.0
                    + parameters.network_bonus
                    * member_centrality
                    * metrics["density"]
                )
            )
            if mean_energy > 0.0:
                energy_factor = 0.5 + 0.5 * (member.energy / mean_energy)
            else:
                energy_factor = 0.5
            contribution = metrics["contribution_rate"] * energy_factor
            coercion_risk = (
                parameters.coercion_risk
                * coercion_weight
                * (1.0 - 0.5 * legitimation)
                * (1.0 - 0.5 * member_centrality)
            )
            is_leader = leader is not None and member.id == leader.id
            leader_rent = (
                parameters.leader_rent * (status_weight + coercion_weight)
                if is_leader
                else 0.0
            )
            outside_utility = max(
                0.0,
                parameters.outside_base * demand
                - parameters.outside_dominant_discount * demand * top_weight,
            )
            margin = (
                benefit
                - contribution
                - coercion_risk
                + leader_rent
                - outside_utility
            )
            willing = margin >= 0.0 and demand > 1e-12
            assessments.append(
                MemberAssessment(
                    member=member,
                    centrality=member_centrality,
                    demand=demand,
                    benefit=benefit,
                    contribution=contribution,
                    coercion_risk=coercion_risk,
                    leader_rent=leader_rent,
                    outside_utility=outside_utility,
                    margin=margin,
                    willing=willing,
                    leader=is_leader,
                )
            )
        return assessments

    @staticmethod
    def _archetype(top_mode, level):
        tiers = ARCHETYPE_TIERS.get(top_mode)
        if not tiers:
            return top_mode
        if level <= 1:
            return tiers[0]
        if level == 2:
            return tiers[1]
        return tiers[2]


__all__ = [
    "Member",
    "MemberAssessment",
    "OrganizationAnalysis",
    "OrganizationParameters",
    "OrganizationSolver",
    "Population",
    "level_capacity",
    "organization_level",
]
