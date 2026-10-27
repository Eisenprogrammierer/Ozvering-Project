import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulation as S

GAMES = 30
_EPS_KEYS = ("EPS_START", "EPS_MIN", "EPS_DECAY_STEPS")


def _run(
    games=GAMES,
    eps_start=None,
    eps_min=None,
    eps_decay=None,
    alpha=None,
    gamma=None,
    discretize=None,
):
    saved = {
        k: getattr(S.RLAgent, k) for k in (*_EPS_KEYS, "discretize", "learn")
    }
    if eps_start is not None:
        S.RLAgent.EPS_START = eps_start
    if eps_min is not None:
        S.RLAgent.EPS_MIN = eps_min
    if eps_decay is not None:
        S.RLAgent.EPS_DECAY_STEPS = eps_decay
    if alpha is not None or gamma is not None:
        a = 0.3 if alpha is None else alpha
        g = 0.9 if gamma is None else gamma
        orig_learn = saved["learn"]

        def learn(self, st, a_idx, reward, nst, alpha=a, gamma=g):
            return orig_learn(
                self, st, a_idx, reward, nst, alpha=alpha, gamma=gamma
            )

        S.RLAgent.learn = learn
    if discretize is not None:
        S.RLAgent.discretize = discretize
    try:
        return S.run_batch(games, quiet=True)[2]
    finally:
        for k, v in saved.items():
            setattr(S.RLAgent, k, v)


def _row(label, value, res, games=GAMES):
    rl = res["RL"]
    print(
        f"  {label:<26} {str(value):>10} | RL {rl:>3}/{games:<3} "
        f"({100.0 * rl / games:4.1f}%)  UtilityAI {res['UtilityAI']:>3}  "
        f"нет {res[None]:>3}"
    )


def _coarse_discretize(self, e):
    if e <= 8:
        return e
    return 8 + int(math.log2(e / 8))


def main():
    print("=" * 76)
    print(
        "  A5. Чувствительность канона RL vs UtilityAI к гиперпараметрам "
        "Q-learning"
    )
    print("=" * 76)

    print("\n[0] Базовая линия (канон)")
    _row("канон @10 партий", "-", _run(games=10), games=10)
    _row("канон @30 партий", "-", _run(), games=30)

    print("\n[1] Объём обучения (горизонт разведки EPS_DECAY_STEPS)")
    for v in (500, 1500, 3000, 6000, 12000):
        _row("EPS_DECAY_STEPS", v, _run(eps_decay=v))

    print("\n[2] Нижний порог разведки EPS_MIN (и контроли)")
    for v in (0.0, 0.05, 0.2):
        _row("EPS_MIN", v, _run(eps_min=v))
    _row("чистая разведка", "EPS_MIN=1.0", _run(eps_start=1.0, eps_min=1.0))
    _row("чистая жадность", "EPS_MIN=0.0", _run(eps_start=0.0, eps_min=0.0))

    print("\n[3] Темп обучения alpha / дисконт gamma")
    for v in (0.1, 0.3, 0.6, 1.0):
        _row("alpha", v, _run(alpha=v))
    for v in (0.0, 0.5, 0.9, 0.99):
        _row("gamma", v, _run(gamma=v))

    print("\n[4] Дискретизация состояния discretize")
    _row("канон (мультишкала)", "-", _run())
    _row("грубая (log2)", "-", _run(discretize=_coarse_discretize))

    print("\n" + "=" * 76)
    print(
        "  (доля RL — победы RL из партий; канон = EPS 1.0→0.05/3000, α=0.3, "
        "γ=0.9)"
    )
    print(
        "  Вывод: RL остаётся в меньшинстве во всём разумном диапазоне, но НЕ"
    )
    print(
        "  инвариантен — доля растёт с горизонтом разведки (3000→6000: "
        "13%→27%)."
    )
    print(
        "  Значит 1/9 — дефект по цели (п. A5): слабость табличного "
        "RL/разведки,"
    )
    print(
        "  частично артефакт калибровки EPS_DECAY_STEPS (короткий горизонт)."
    )
    print("=" * 76)


if __name__ == "__main__":
    main()
