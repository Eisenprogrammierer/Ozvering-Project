"""Лоссовая наблюдаемость: информационная асимметрия между ярусами.

Требование: суперсистема (автомат, включающий автоматы) не должна знать всё,
что знают её части, — и наоборот. Асимметрия реализована как ПРОЕКЦИЯ
наблюдаемости, а не как новый закон обработки: кодекс (Шмитт, экономика,
покоя) остаётся единым на всех ярусах (самоподобие сохраняется).

Два направления:

* **вверх** — суперсистема получает не поток точных событий с identity/типом/
  таймингом, а агрегат ``Observation`` за интервал (квантование + задержка);
* **вниз** — части видят только публичное окно конъюнктуры (с задержкой), а не
  внутренности суперсистемы (``force``, ``w_adopt``, состав ``members``).

Модуль не импортирует ``simulation`` (нет цикла); константы передаются явно.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    """Наблюдаемый агрегат: работа и число событий, без источника и типа."""

    work: float = 0.0
    count: int = 0


class LossyChannel:
    """Аккумулятор событий с квантованием и задержкой.

    ``push`` принимает работу события; ``drain`` отдаёт агрегат, кратный
    ``resolution``. Остаток остаётся в аккумуляторе до следующего дренажа —
    это и есть «накопление работы» без привязки к времени. ``delay`` задаёт
    задержку публикации (в тактах): часть видит прошлое, а не настоящее.
    """

    def __init__(self, resolution=1.0, delay=0):
        self.resolution = max(1e-9, float(resolution))
        self.delay = max(0, int(delay))
        self._acc = 0.0
        self._count = 0
        self._queue = []

    def push(self, work):
        """Добавить событие (идентичность и тип не сохраняются)."""
        w = max(0.0, float(work))
        if w <= 0.0:
            return
        self._acc += w
        self._count += 1

    def drain(self):
        """Забрать агрегат, кратный ``resolution``, с учётом задержки."""
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
        """Сбросить накопленное (начало партии)."""
        self._acc = 0.0
        self._count = 0
        self._queue = []


class PublicEnvironment:
    """Фасад суперсистемы для частей: только окно конъюнктуры.

    Части не должны читать ``force``/``w_adopt``/``members`` суперсистемы;
    для модуляции отдачи им достаточно публичного окна (с задержкой).
    """

    def __init__(self, env):
        self._env = env

    @property
    def in_open(self):
        return self._env.public_window()

    def __repr__(self):                      # не раскрываем внутренности
        return "PublicEnvironment(open=%s)" % self.in_open
