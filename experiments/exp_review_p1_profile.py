# Ревью P1: профильная дифференциация — ранавей p>1, исходы, состав state (конверсия).
# Запуск из корня: python3 experiments/exp_review_p1_profile.py

import os, sys
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import random
import simulation as S
from simulation import Agent, RLAgent, UtilityAI, play_game

print("=== P1-3: RUNAWAY при p>1 (старт w_adopt=1.0, БЕЗ внешнего напора) ===")
for prof in ("CANON","OPPORTUNIST"):
    tgt=Agent(profile=prof); tgt.w_adopt=1.0
    opened=None
    for t in range(200):
        tgt.tick_input_state(); tgt.receive_pressure(0.0)
        if tgt.in_open and opened is None: opened=t
    print(f"  {prof:12} через 200 тактов: w_adopt={tgt.w_adopt:.1f} in_open={tgt.in_open} "
          f"(первое открытие={opened}, ON={tgt.schmitt_on():.1f})")

print("\n=== P1-3: исходы RL(profile p) vs UtilityAI(CANON), 10 партий, with_env=True ===")
for p in (0.70,0.85,1.0,1.15,1.30):
    rl=RLAgent()
    wins={"RL":0,"UtilityAI":0,None:0}
    for g in range(10):
        w,_,_,_=play_game(rl, UtilityAI(), 1000, seed=g, with_env=True, profiles=(p,1.0))
        wins[w]+=1
    print(f"  p_rl={p:.2f}: RL={wins['RL']} AI={wins['UtilityAI']} no={wins[None]}")

print("\n=== P1-3: зеркальность (A=p, B=CANON) и обратно ===")
def duel_pair(pa,pb,n=10):
    rl=RLAgent(); wins={"RL":0,"UtilityAI":0,None:0}
    for g in range(n):
        w,_,_,_=play_game(rl, UtilityAI(), 1000, seed=g, with_env=True, profiles=(pa,pb))
        wins[w]+=1
    return wins
a=duel_pair(1.30,1.0); b=duel_pair(1.0,1.30)
print(f"  RL(1.30) vs AI(1.00): {a}   |   RL(1.00) vs AI(1.30): {b}  (роли статистически симметричны?)")

print("\n=== P1-6: есть ли в модели пер-типовая валюта? (состав state) ===")
print("  state полей:", sorted(Agent().state.keys()))
print("  -> единый energy_pool; 'тип' хранится лишь в defense/last_act (метки атаки/защиты).")
