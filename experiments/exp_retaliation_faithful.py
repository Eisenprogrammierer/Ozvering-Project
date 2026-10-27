import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import simulation as S
from simulation import Agent, RLAgent, UtilityAI, play_game

_orig_commit = Agent.commit
_stat = {"att": 0, "work_ok": 0, "def_ok": 0}


def _probe(self, act, work):
    pred_w = self.committed_work(act, work)
    pred_d = self.defense_after(act, work)
    r = _orig_commit(self, act, work)
    if r > 0:
        _stat["att"] += 1
        _stat["work_ok"] += pred_w == r
        _stat["def_ok"] += pred_d == self.defense
    return r


Agent.commit = _probe
try:
    rl = RLAgent()
    for g in range(10):
        play_game(rl, UtilityAI(), 400, seed=g, with_env=True)
finally:
    Agent.commit = _orig_commit

n = _stat["att"]
ok_work = _stat["work_ok"] == n
ok_def = _stat["def_ok"] == n

print("A3. Верность оценки возмездия состоянию ПОСЛЕ commit")
print("=" * 60)
print(f"  атакующих тактов (r>0): {n}")
print(f"  committed_work == фактической работе : {_stat['work_ok']}/{n}")
print(f"  defense_after == defense после commit: {_stat['def_ok']}/{n}")

print()
print("  канон run_batch(10):", S.run_batch(10, quiet=True)[2])

print()
print(
    "ИТОГ:",
    (
        "проекция совпадает с commit на 100%"
        if (ok_work and ok_def)
        else "РАСХОЖДЕНИЕ с commit — регрессия A3"
    ),
)
sys.exit(0 if (ok_work and ok_def) else 1)
