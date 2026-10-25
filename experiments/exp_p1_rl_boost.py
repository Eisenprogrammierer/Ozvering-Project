"""P1: можно ли поднять долю RL выше 50% без изменения core (docs/TODO.md P1).

Варианты (monkeypatch на время прогона, core не меняется):

  * горизонт разведки EPS_DECAY_STEPS = 3000 (канон) / 6000 / 12000;
  * грубая дискретизация состояния (``exp_rl_sensitivity._coarse_discretize``);
  * shaping награды: r = ΔF − w·ΔF_opp (относительное преимущество) для w=0.25/0.5;
  * литеральная формула из задания r = ΔF + 0.25·ΔF_opp (контроль знака);
  * r = ΔF − 0.25·ΔF_opp + 5 за успешную исходящую передачу RL.

ΔF_opp снимается обёрткой ``run_tick`` (сила AI до/после такта), успех передачи —
обёрткой ``_apply_transfer`` (сила RL выросла внутри передачи, т.е. удар прошёл).
Каждый вариант — 30 партий (seed 0..29, сквозное обучение Q, with_env=True).

Запуск из корня репозитория:
    python3 experiments/exp_p1_rl_boost.py
"""
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simulation as S
from exp_rl_sensitivity import _coarse_discretize

GAMES = 30


def _run(label, eps_decay=None, discretize=None, shape=None, weight=0.0,
         success_bonus=0.0):
    """Один пакет партий с точечными monkeypatch."""
    saved = {
        "EPS_DECAY_STEPS": S.RLAgent.EPS_DECAY_STEPS,
        "discretize": S.RLAgent.discretize,
        "learn": S.RLAgent.learn,
        "run_tick": S.run_tick,
        "apply": S._apply_transfer,
    }
    rl_ref = {"agent": None}

    def wrapped_run_tick(a, b, intent_a, intent_b, rng, env=None):
        rl_ref["agent"] = a
        a._transfer_success = False
        before_opp = b.force
        saved["run_tick"](a, b, intent_a, intent_b, rng, env)
        a._opp_delta = b.force - before_opp

    def wrapped_apply(att, dfn, work, att_type, rng, env=None):
        before = att.force
        saved["apply"](att, dfn, work, att_type, rng, env)
        if att is rl_ref["agent"] and att.force > before:
            att._transfer_success = True

    try:
        if eps_decay is not None:
            S.RLAgent.EPS_DECAY_STEPS = eps_decay
        if discretize is not None:
            S.RLAgent.discretize = discretize
        if shape is not None:
            S.run_tick = wrapped_run_tick
            S._apply_transfer = wrapped_apply

            def learn(self, st, a_idx, reward, nst, alpha=0.3, gamma=0.9):
                d_opp = getattr(self, "_opp_delta", 0.0)
                r = reward
                if shape == "adv":
                    r -= weight * d_opp
                elif shape == "plus":
                    r += weight * d_opp
                if success_bonus and getattr(self, "_transfer_success", False):
                    r += success_bonus
                return saved["learn"](self, st, a_idx, r, nst,
                                      alpha=alpha, gamma=gamma)

            S.RLAgent.learn = learn
        res = S.run_batch(GAMES, quiet=True)[2]
    finally:
        S.RLAgent.EPS_DECAY_STEPS = saved["EPS_DECAY_STEPS"]
        S.RLAgent.discretize = saved["discretize"]
        S.RLAgent.learn = saved["learn"]
        S.run_tick = saved["run_tick"]
        S._apply_transfer = saved["apply"]
    return res


def row(label, res, games=GAMES):
    print(f"  {label:<46} | RL {res['RL']:>2}/{games} "
          f"({100.0 * res['RL'] / games:5.1f}%) | AI {res['UtilityAI']:>2} "
          f"| нет {res[None]:>2}")


def main():
    print("=" * 88)
    print("P1: доля RL при разных гиперпараметрах/награде (30 партий, core не меняется)")
    print("=" * 88)

    print("\n[0] Канон / горизонт разведки")
    row("канон (EPS_DECAY_STEPS=3000)", _run("канон"))
    row("EPS_DECAY_STEPS=6000", _run("e6", eps_decay=6000))
    row("EPS_DECAY_STEPS=12000", _run("e12", eps_decay=12000))
    row("EPS_DECAY_STEPS=24000 (потолок)", _run("e24", eps_decay=24000))
    row("EPS_DECAY_STEPS=48000 (потолок)", _run("e48", eps_decay=48000))

    print("\n[1] Дискретизация")
    row("грубая (log2 после 8)", _run("coarse", discretize=_coarse_discretize))

    print("\n[2] Reward shaping")
    row("r = dF - 0.25*dF_opp", _run("adv.25", shape="adv", weight=0.25))
    row("r = dF - 0.50*dF_opp", _run("adv.50", shape="adv", weight=0.5))
    row("r = dF + 0.25*dF_opp (литерально)", _run("plus.25", shape="plus", weight=0.25))
    row("r = dF - 0.25*dF_opp + 5*success",
        _run("adv.25+succ", shape="adv", weight=0.25, success_bonus=5.0))

    print("\n[3] Комбинация лучших (если есть)")
    row("EPS=6000 + coarse", _run("e6+coarse", eps_decay=6000,
                                  discretize=_coarse_discretize))
    row("EPS=6000 + r=dF-0.25*dF_opp", _run("e6+adv.25", eps_decay=6000,
                                            shape="adv", weight=0.25))
    row("EPS=12000 + coarse + r=dF-0.25*dF_opp",
        _run("e12+coarse+adv.25", eps_decay=12000,
             discretize=_coarse_discretize, shape="adv", weight=0.25))

    print("\n" + "=" * 88)
    print("  Цель P1 — RL > 50%. Сравнивайте строки с каноном; вывод по числам.")
    print("=" * 88)


if __name__ == "__main__":
    main()
