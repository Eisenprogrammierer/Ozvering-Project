"""A9: знания агента о скрытом состоянии противника.

`Intel` — не состояние мира, а модель наблюдателя. Она хранит последние
известные оценки скрытых полей (`energy`, `health`, `sickness`, `wound`),
уверенность в них и свежую «слабую точку», найденную разведкой. Туман
включается на уровне матча: `ArenaAgent.observe()` подставляет оценки вместо
точных значений, но никогда не скрывает силу, давление, открытость и
подготовку — это внешние признаки.

Разведка (`info`) при успехе раскрывает скрытые поля и ставит слабую точку;
силовая атака по свежей точке получает бонус. Провал разведки не раскрывает
полей, но немного повышает уверенность: сам факт проверки что-то говорит
наблюдателю.
"""

from dataclasses import dataclass, field

FOG_START_CONFIDENCE = 0.5
FOG_CONFIDENCE_DECAY = 0.92
FOG_FAILURE_GAIN = 0.08
INTEL_WEAK_POINT_TICKS = 3

HIDDEN_FIELDS = ("energy", "health", "sickness", "wound")


@dataclass
class Intel:
    confidence: float = FOG_START_CONFIDENCE
    age: int = 0
    weak_point: float = 0.0
    values: dict = field(default_factory=dict)

    def reset(self, unit=None):
        """Сбросить знания; при наличии `unit` — снять стартовый срез."""
        self.confidence = FOG_START_CONFIDENCE
        self.age = 0
        self.weak_point = 0.0
        self.values = {}
        if unit is not None:
            for name in HIDDEN_FIELDS:
                self.values[name] = float(getattr(unit, name))
        return self

    def decay(self):
        """Старение знаний за такт без новой разведки."""
        self.age += 1
        self.confidence = max(
            0.0, self.confidence * FOG_CONFIDENCE_DECAY
        )
        self.weak_point = max(
            0.0,
            self.weak_point - 1.0 / max(1, INTEL_WEAK_POINT_TICKS),
        )
        return self

    def reveal(self, unit):
        """Успешная разведка: точные скрытые поля и слабая точка."""
        for name in HIDDEN_FIELDS:
            self.values[name] = float(getattr(unit, name))
        self.confidence = 1.0
        self.age = 0
        self.weak_point = 1.0
        return self

    def note_failure(self):
        """Неудачная разведка: факт проверки немного повышает уверенность."""
        self.confidence = min(
            1.0, self.confidence + FOG_FAILURE_GAIN
        )
        self.age = 0
        return self

    def estimate(self, name, actual):
        """Оценка скрытого поля; без знания — фактическое значение."""
        return float(self.values.get(name, actual))

    def consume_weak_point(self):
        self.weak_point = 0.0
        return self

    def state_dict(self):
        return {
            "confidence": float(self.confidence),
            "age": int(self.age),
            "weak_point": float(self.weak_point),
            "values": dict(self.values),
        }

    def load_state_dict(self, state):
        state = state or {}
        self.confidence = float(
            state.get("confidence", self.confidence)
        )
        self.age = int(state.get("age", self.age))
        self.weak_point = float(
            state.get("weak_point", self.weak_point)
        )
        self.values = {
            str(name): float(value)
            for name, value in dict(state.get("values", {})).items()
        }
        return self


__all__ = [
    "FOG_CONFIDENCE_DECAY",
    "FOG_FAILURE_GAIN",
    "FOG_START_CONFIDENCE",
    "HIDDEN_FIELDS",
    "INTEL_WEAK_POINT_TICKS",
    "Intel",
]
