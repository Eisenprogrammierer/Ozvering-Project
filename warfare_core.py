from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
import math
import random

import character_traits as CT
import bdi as BDI
import simulation as S

# Потребности, подписи и темпы роста — данные BDI, а не копия в Python.
_BDI_CONFIG = BDI.load_bdi()
NEEDS = tuple(_BDI_CONFIG.needs)
NEEDS_RU = {
    key: definition.label for key, definition in _BDI_CONFIG.needs.items()
}


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


TRAIT_MODEL = CT.load_traits()

TRAITS = TRAIT_MODEL.trait_names
TRAITS_RU = {
    key: definition.label.lower()
    for key, definition in TRAIT_MODEL.traits.items()
}

_ARCHETYPES = {
    name: dict(item["modifiers"])
    for name, item in TRAIT_MODEL.archetypes.items()
}


@dataclass
class Personality:

    values: dict
    archetype: str = "rifleman"
    seed: int = 0

    @classmethod
    def from_seed(cls, seed=0, archetype="rifleman"):
        values = TRAIT_MODEL.roll(seed=seed, archetype=archetype)
        return cls(values=values, archetype=archetype, seed=int(seed))

    def __getitem__(self, name):
        return self.values[name]

    def get(self, name, default=0.5):
        return self.values.get(name, default)

    def as_dict(self):
        return dict(self.values)


# Намерение персонажа — дуплет BDI ``(объект, суть)``. Старое локальное
# намерение хранило ``kind/need/urgency/reason``; теперь это производные
# свойства ``bdi.Intention``, а каноническими остаются ``target``/``essence``.
Intention = BDI.Intention

# Тактические виды намерений из ``traits.json`` переводятся в BDI-сути.
ESSENCE_FOR_KIND = dict(TRAIT_MODEL.essence_for_kind)


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


__all__ = [
    'annotations',
    'dataclass',
    'field',
    'Counter',
    'math',
    'random',
    'CT',
    'BDI',
    'S',
    '_BDI_CONFIG',
    'NEEDS',
    'NEEDS_RU',
    'HEALTH_NEED_WEIGHTS',
    'HEALTH_MULTIPLIER_MIN',
    'HEALTH_MULTIPLIER_MAX',
    'TRAIT_MODEL',
    'TRAITS',
    'TRAITS_RU',
    '_ARCHETYPES',
    'Personality',
    'Intention',
    'ESSENCE_FOR_KIND',
    'OrderSignal',
    'Order',
]
