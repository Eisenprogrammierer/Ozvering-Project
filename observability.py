import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:

    work: float = 0.0
    count: int = 0


class LossyChannel:

    def __init__(self, resolution=1.0, delay=0):
        self.resolution = max(1e-9, float(resolution))
        self.delay = max(0, int(delay))
        self._acc = 0.0
        self._count = 0
        self._queue = []

    def push(self, work):
        w = max(0.0, float(work))
        if w <= 0.0:
            return
        self._acc += w
        self._count += 1

    def drain(self):
        quantum = math.floor(self._acc / self.resolution) * self.resolution
        self._acc -= quantum
        obs = Observation(work=quantum, count=self._count)
        self._count = 0
        if self.delay <= 0:
            return obs
        self._queue.append(obs)
        if len(self._queue) <= self.delay:
            return Observation()
        return self._queue.pop(0)

    def clear(self):
        self._acc = 0.0
        self._count = 0
        self._queue = []


class PublicEnvironment:

    def __init__(self, env):
        self._env = env

    @property
    def in_open(self):
        return self._env.public_window()

    def __repr__(self):
        return "PublicEnvironment(open=%s)" % self.in_open
