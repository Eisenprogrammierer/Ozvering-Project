from dataclasses import dataclass, field


@dataclass(frozen=True)
class Work:
    amount: float
    form: str = "force"
    payload: tuple = ()
    duration: float = 1.0


@dataclass(frozen=True)
class Action:
    kind: str = "REST"
    form: str = "force"
    fraction: float = 0.0
    target: str = "opponent"


@dataclass(frozen=True)
class Observation:
    self_force: float
    self_energy: float
    self_max_force: float
    self_max_energy: float
    opponent_force: float
    opponent_energy: float
    opponent_max_force: float
    opponent_max_energy: float
    opponent_pressure: float
    opponent_open: bool
    time: float
    forms: tuple = ("force",)
    opponent_defense: str = ""
    self_health: float = 100.0
    self_max_health: float = 100.0
    self_sickness: float = 0.0
    opponent_health: float = 100.0
    opponent_max_health: float = 100.0
    opponent_sickness: float = 0.0


@dataclass(frozen=True)
class Transition:
    observation: Observation
    action: Action
    reward: float
    next_observation: Observation
    done: bool
    next_actions: tuple = ()
    info: dict = field(default_factory=dict)
