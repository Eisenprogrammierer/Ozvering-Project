"""Политика выбора работы поверх BDI-потребностей NPC.

Статус: **запасное решение** (``LEGACY_ROLE = "decision-fallback"``).
Soar-политика — основной путь при ``ai_backend=soar``; этот слой
остаётся для ``legacy``, платформ без ``soar-sml`` и как эталон
сравнения. RL-предпочтения не прошли порог сравнения, поэтому владельцем
решения в поставке остаётся эта политика.

Этот слой закрывает разрыв W2: BDI выбирает **что важно** (потребность и
суть намерения), а политика — **какую доступную работу взять**. Политика
не заменяет BDI и не трогает эвристики по умолчанию: она включается
блоком ``ai_model.npc_policy`` и при отсутствии чекпойнта работает как
детерминированный контекстный бандит с BDI-признаками.

Обучение офлайн: ``observe(need, reward)`` обновляет вес потребности,
``state_dict()``/``load_state_dict()`` сохраняют его. В игре инференс
детерминирован (``epsilon=0``), поэтому один seed и один снимок дают один
и тот же выбор.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SCHEMA_VERSION = 1
LEGACY_ROLE = "decision-fallback"


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value, low=-4.0, high=4.0):
    return max(low, min(high, _number(value)))


class NeedPolicy:
    """Контекстный выбор работы по значению потребности.

    ``weights`` — поправка к базовому весу работы для каждой потребности.
    Положительный вес усиливает работу, закрывающую эту потребность;
    отрицательный — ослабляет. Базовая эвристика кампании остаётся
    множителем, поэтому политика не может выбрать недоступную работу.
    """

    def __init__(
        self,
        weights=None,
        seed=0,
        learning_rate=0.05,
        epsilon=0.0,
        explore=False,
    ):
        self.weights = {
            str(key): _clamp(value)
            for key, value in dict(weights or {}).items()
        }
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.learning_rate = max(0.0, _number(learning_rate, 0.05))
        self.epsilon = max(0.0, min(1.0, _number(epsilon, 0.0)))
        self.explore = bool(explore)
        self.updates = 0

    @classmethod
    def from_config(cls, config, seed=0):
        """Собрать политику из блока ``ai_model.npc_policy``."""
        config = dict(config or {})
        weights = config.get("weights")
        if not isinstance(weights, dict):
            weights = {}
        policy = cls(
            weights=weights,
            seed=seed,
            learning_rate=config.get("learning_rate", 0.05),
            epsilon=config.get("epsilon", 0.0),
            explore=config.get("explore", False),
        )
        checkpoint = config.get("checkpoint")
        if checkpoint:
            path = Path(str(checkpoint))
            if path.is_file():
                try:
                    policy.load_state_dict(
                        json.loads(path.read_text(encoding="utf-8"))
                    )
                except (OSError, ValueError, TypeError):
                    pass
        return policy

    def weight(self, need):
        return self.weights.get(str(need), 0.0)

    def score(self, need, value, base=1.0):
        """Оценка работы: базовая эвристика × поправка на нужду."""
        value = max(0.0, min(1.0, _number(value)))
        factor = 1.0 + self.weight(need) * value
        return max(0.01, _number(base, 1.0) * max(0.05, factor))

    def choose(self, candidates, needs, explore=None):
        """Выбрать ``(id, need, base)`` из кандидатов.

        ``candidates`` — последовательность ``(option_id, need, base)``.
        Возвращает ``option_id`` или ``None``. Исследование включается
        только явно (``explore=True`` или ``epsilon > 0``), чтобы игровой
        инференс оставался воспроизводимым.
        """
        items = [item for item in candidates if item and item[0]]
        if not items:
            return None
        needs = dict(needs or {})
        scored = [
            (
                self.score(
                    need,
                    needs.get(str(need), 0.0),
                    base,
                ),
                str(option_id),
            )
            for option_id, need, base in items
        ]
        do_explore = self.explore if explore is None else bool(explore)
        if do_explore and self.rng.random() < self.epsilon:
            return self.rng.choice([option_id for _s, option_id in scored])
        return max(scored, key=lambda pair: (pair[0], pair[1]))[1]

    def observe(self, need, reward):
        """Обновить вес потребности по награде (офлайн/эпизодически)."""
        need = str(need)
        reward = _number(reward)
        self.weights[need] = _clamp(
            self.weights.get(need, 0.0) + self.learning_rate * reward
        )
        self.updates += 1
        return self.weights[need]

    def state_dict(self):
        return {
            "kind": "need",
            "version": SCHEMA_VERSION,
            "weights": dict(self.weights),
            "seed": self.seed,
            "learning_rate": self.learning_rate,
            "epsilon": self.epsilon,
            "updates": self.updates,
        }

    def load_state_dict(self, state):
        state = dict(state or {})
        weights = state.get("weights")
        if isinstance(weights, dict):
            self.weights = {
                str(key): _clamp(value)
                for key, value in weights.items()
            }
        if "seed" in state:
            self.seed = int(_number(state.get("seed"), self.seed))
            self.rng = random.Random(self.seed)
        if "learning_rate" in state:
            self.learning_rate = max(
                0.0, _number(state.get("learning_rate"), 0.05)
            )
        if "epsilon" in state:
            self.epsilon = max(
                0.0, min(1.0, _number(state.get("epsilon"), 0.0))
            )
        if "updates" in state:
            self.updates = max(0, int(_number(state.get("updates"), 0)))
        return self


__all__ = ["NeedPolicy", "SCHEMA_VERSION"]
