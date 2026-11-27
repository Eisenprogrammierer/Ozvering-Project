"""Ошибки когнитивного слоя.

Модуль намеренно не импортирует Soar и RiveScript: ошибки описывают
контракты фасада и моста, а не конкретный бэкенд.
"""

from __future__ import annotations


class CognitionError(RuntimeError):
    """Базовая ошибка когнитивного слоя."""


class BackendError(CognitionError, ValueError):
    """Неизвестный или недоступный бэкенд."""


class FrameError(CognitionError, ValueError):
    """Кадр понимания не соответствует схеме."""


class BridgeError(CognitionError, ValueError):
    """Сообщение моста Python ↔ Soar не прошло валидацию."""


class CorpusError(CognitionError, ValueError):
    """Золотой корпус повреждён или несовместим по версии."""


class RiveError(CognitionError, ValueError):
    """Сгенерированный RiveScript-артефакт или его источник повреждён."""


class SoarError(CognitionError, ValueError):
    """Политика Soar или её артефакт повреждены."""


class SnapshotError(CognitionError, ValueError):
    """JSON-снимок рабочей памяти Soar несовместим или повреждён."""


__all__ = [
    "BackendError",
    "BridgeError",
    "CognitionError",
    "CorpusError",
    "FrameError",
    "RiveError",
    "SnapshotError",
    "SoarError",
]
