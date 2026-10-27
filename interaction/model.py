from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import random
from typing import Iterable, List, Optional, Tuple


def _clamp(value, low=0.0, high=1.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    if value != value:
        return low
    return max(low, min(high, value))


def _stable_rng(seed, key):
    digest = hashlib.sha256(
        ("%s|%s" % (seed, key)).encode("utf-8")
    ).hexdigest()
    return random.Random(int(digest[:16], 16))


@dataclass(frozen=True)
class OutcomeSpec:

    id: str
    label: str
    description: str = ""
    probability: float = 1.0
    uncertainty: float = 0.1
    hidden: bool = False
    tone: str = "neutral"

    def __post_init__(self):
        if not str(self.id or "").strip():
            raise ValueError("у исхода должен быть непустой id")
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "label", str(self.label or self.id))
        object.__setattr__(self, "description", str(self.description or ""))
        object.__setattr__(
            self, "probability", max(0.0, float(self.probability))
        )
        object.__setattr__(
            self, "uncertainty", _clamp(self.uncertainty, 0.0, 1.0)
        )


@dataclass(frozen=True)
class ActionSpec:

    id: str
    label: str
    description: str = ""
    outcomes: Tuple[OutcomeSpec, ...] = field(default_factory=tuple)
    uncertainty: float = 0.15
    unknown_share: float = 0.0
    unknown_description: str = (
        "Возможен эффект, который не описан известной моделью."
    )
    enabled: bool = True

    def __post_init__(self):
        if not str(self.id or "").strip():
            raise ValueError("у действия должен быть непустой id")
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "label", str(self.label or self.id))
        object.__setattr__(self, "description", str(self.description or ""))
        object.__setattr__(self, "outcomes", tuple(self.outcomes or ()))
        object.__setattr__(
            self, "uncertainty", _clamp(self.uncertainty, 0.0, 1.0)
        )
        object.__setattr__(
            self, "unknown_share", _clamp(self.unknown_share, 0.0, 1.0)
        )

    @property
    def total_weight(self):
        return sum(outcome.probability for outcome in self.outcomes)


@dataclass(frozen=True)
class Target:

    id: str
    label: str
    description: str = ""
    tags: Tuple[str, ...] = field(default_factory=tuple)
    actions: Tuple[ActionSpec, ...] = field(default_factory=tuple)
    available: bool = True

    def __post_init__(self):
        if not str(self.id or "").strip():
            raise ValueError("у объекта должен быть непустой id")
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "label", str(self.label or self.id))
        object.__setattr__(self, "description", str(self.description or ""))
        object.__setattr__(self, "tags", tuple(self.tags or ()))
        object.__setattr__(self, "actions", tuple(self.actions or ()))


@dataclass(frozen=True)
class OutcomeForecast:

    outcome_id: Optional[str]
    label: str
    description: str
    tone: str
    known: bool
    confidence: float
    low: Optional[float] = None
    high: Optional[float] = None
    hidden: bool = False
    unknown: bool = False

    @property
    def probability_text(self):
        if not self.known:
            return "вероятность неизвестна"
        low = 0.0 if self.low is None else self.low
        high = 0.0 if self.high is None else self.high
        if high - low < 0.02:
            return "~%d%%" % round(100.0 * (low + high) / 2.0)
        return "~%d-%d%% · уверенность %d%%" % (
            round(100.0 * low),
            round(100.0 * high),
            round(100.0 * self.confidence),
        )

    @property
    def short_label(self):
        return self.label if self.known else "Неизвестный исход"


@dataclass(frozen=True)
class InteractionResult:

    target_id: str
    target_label: str
    action_id: str
    action_label: str
    outcome_id: Optional[str]
    label: str
    description: str
    tone: str = "neutral"
    unknown: bool = False
    hidden: bool = False


class InteractionModel:

    def __init__(self, targets: Iterable[Target], seed=0):
        self.targets = list(targets or ())
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.selected_target_id = None
        self.selected_action_id = None
        self.last_result = None
        self.history: List[InteractionResult] = []
        self._forecast_cache = {}

    def target(self, target_id=None):
        target_id = self.selected_target_id if target_id is None else target_id
        for item in self.targets:
            if item.id == target_id:
                return item
        return None

    def available_targets(self):
        return [item for item in self.targets if item.available]

    def select_target(self, target_id):
        item = self.target(target_id)
        if item is None or not item.available:
            return False
        self.selected_target_id = item.id
        self.selected_action_id = None
        self.last_result = None
        return True

    def actions_for(self, target_id=None):
        item = self.target(target_id)
        if item is None:
            return []
        return [action for action in item.actions if action.enabled]

    def action(self, action_id=None):
        action_id = self.selected_action_id if action_id is None else action_id
        for action in self.actions_for():
            if action.id == action_id:
                return action
        return None

    def select_action(self, action_id):
        action = self.action(action_id)
        if action is None:
            return False
        self.selected_action_id = action.id
        self.last_result = None
        return True

    def clear_selection(self):
        self.selected_target_id = None
        self.selected_action_id = None
        self.last_result = None

    def reset(self):
        self.clear_selection()
        self.rng = random.Random(self.seed)
        self.history = []
        self._forecast_cache = {}

    def forecasts(self, target_id=None, action_id=None):
        target = self.target(target_id)
        if target is None:
            return []
        action_id = self.selected_action_id if action_id is None else action_id
        action = next(
            (
                item
                for item in target.actions
                if item.id == action_id and item.enabled
            ),
            None,
        )
        if action is None:
            return []
        key = (target.id, action.id)
        cached = self._forecast_cache.get(key)
        if cached is None:
            cached = self._build_forecasts(target, action)
            self._forecast_cache[key] = tuple(cached)
        return list(cached)

    def _build_forecasts(self, target, action):
        total = action.total_weight
        visible_mass = (1.0 - action.unknown_share) if total > 0.0 else 0.0
        forecasts = []
        if total > 0.0:
            for outcome in action.outcomes:
                true_p = (outcome.probability / total) * visible_mass
                noise = _clamp(action.uncertainty + outcome.uncertainty)
                if outcome.hidden or noise >= 0.95:
                    forecasts.append(
                        OutcomeForecast(
                            outcome_id=outcome.id,
                            label="Неизвестный исход",
                            description=(
                                "Один из возможных эффектов пока не "
                                "наблюдается."
                            ),
                            tone="unknown" if outcome.hidden else outcome.tone,
                            known=False,
                            confidence=0.0,
                            hidden=outcome.hidden,
                        )
                    )
                    continue
                rng = _stable_rng(
                    self.seed,
                    "%s|%s|%s" % (target.id, action.id, outcome.id),
                )
                center = _clamp(true_p + rng.uniform(-0.5, 0.5) * noise)
                low = _clamp(center - 0.5 * noise)
                high = _clamp(center + 0.5 * noise)
                forecasts.append(
                    OutcomeForecast(
                        outcome_id=outcome.id,
                        label=outcome.label,
                        description=outcome.description,
                        tone=outcome.tone,
                        known=True,
                        confidence=_clamp(1.0 - noise),
                        low=low,
                        high=high,
                        hidden=False,
                    )
                )
        if action.unknown_share > 0.0:
            forecasts.append(
                OutcomeForecast(
                    outcome_id=None,
                    label="Неизвестный исход",
                    description=action.unknown_description,
                    tone="unknown",
                    known=False,
                    confidence=0.0,
                    unknown=True,
                )
            )
        return forecasts

    def resolve(self, target_id=None, action_id=None):
        target = self.target(target_id)
        if target is None:
            return None
        action_id = self.selected_action_id if action_id is None else action_id
        action = next(
            (
                item
                for item in target.actions
                if item.id == action_id and item.enabled
            ),
            None,
        )
        if action is None:
            return None
        if self.rng.random() < action.unknown_share:
            result = InteractionResult(
                target_id=target.id,
                target_label=target.label,
                action_id=action.id,
                action_label=action.label,
                outcome_id=None,
                label="Неизвестный исход",
                description=action.unknown_description,
                tone="unknown",
                unknown=True,
            )
        else:
            outcome = self._choose_outcome(action)
            if outcome is None:
                result = InteractionResult(
                    target_id=target.id,
                    target_label=target.label,
                    action_id=action.id,
                    action_label=action.label,
                    outcome_id=None,
                    label="Нет наблюдаемого эффекта",
                    description="Действие не дало описанного исхода.",
                    tone="neutral",
                )
            else:
                result = InteractionResult(
                    target_id=target.id,
                    target_label=target.label,
                    action_id=action.id,
                    action_label=action.label,
                    outcome_id=outcome.id,
                    label=outcome.label,
                    description=outcome.description,
                    tone=outcome.tone,
                    hidden=outcome.hidden,
                )
        self.last_result = result
        self.history.append(result)
        return result

    def _choose_outcome(self, action):
        total = action.total_weight
        if total <= 0.0:
            return None
        roll = self.rng.random() * total
        cursor = 0.0
        for outcome in action.outcomes:
            cursor += outcome.probability
            if roll <= cursor:
                return outcome
        return action.outcomes[-1]

    def snapshot(self):
        return {
            "seed": self.seed,
            "selected_target": self.selected_target_id,
            "selected_action": self.selected_action_id,
            "last_result": (
                self.last_result.__dict__.copy()
                if self.last_result is not None
                else None
            ),
            "history": [item.__dict__.copy() for item in self.history],
        }


__all__ = [
    "ActionSpec",
    "InteractionModel",
    "InteractionResult",
    "OutcomeForecast",
    "OutcomeSpec",
    "Target",
]
