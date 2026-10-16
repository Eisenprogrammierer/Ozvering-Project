"""Автотест ВЕРНОСТИ оценки возмездия (пункт A3 ревью, docs/MODEL.md §7).

``UtilityAI.expected_retaliation`` обещает строиться «ровно по закону фактического
``resolve_attack``». До фикса A3 оценка на этапе планирования брала УСТАРЕВШИЕ
собственные величины: ``self.last_work`` (работа прошлого такта) и ``self.defense``
(тип по прошлому действию и до списания пула), тогда как фактический
``resolve_attack`` использует состояние ПОСЛЕ ``commit``. Фикс ввёл чистые
помощники ``Agent.committed_work`` / ``Agent.defense_after``, проецирующие это
состояние без побочных эффектов.

Здесь helpers сверяются с фактом на канонической траектории (RL vs UtilityAI,
10 партий, with_env): у каждой атаки (r>0, единственный случай, где оценка
возмездия вообще вызывается) проекция обязана совпасть с результатом ``commit``.

Запуск из корня репозитория (0 — верно, 1 — регрессия):
    python3 experiments/exp_retaliation_faithful.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import simulation as S
from simulation import Agent, RLAgent, UtilityAI, play_game

_orig_commit = Agent.commit
_stat = {"att": 0, "work_ok": 0, "def_ok": 0}


def _probe(self, act, work):
    """Обёртка commit: сверяет проекцию ДО с фактом ПОСЛЕ."""
    pred_w = self.committed_work(act, work)
    pred_d = self.defense_after(act, work)
    r = _orig_commit(self, act, work)
    if r > 0:  # атакующий такт: только тут работает expected_retaliation
        _stat["att"] += 1
        _stat["work_ok"] += (pred_w == r)
        _stat["def_ok"] += (pred_d == self.defense)
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
print("ИТОГ:", "проекция совпадает с commit на 100%"
      if (ok_work and ok_def) else "РАСХОЖДЕНИЕ с commit — регрессия A3")
sys.exit(0 if (ok_work and ok_def) else 1)
