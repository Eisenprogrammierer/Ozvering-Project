# Ревью P1: рекурсивная ротация, режим p>1 профиля, отклонение expected_retaliation.
# Запуск из корня: python3 experiments/exp_review_p1_rotation_retaliation.py

import os, sys, math
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import random
import simulation as S
from simulation import Agent, Environment, RLAgent, UtilityAI, play_game, TYPES, MULT, DECAY_ADOPT

print("="*70)
print("P1-4. РЕКУРСИВНАЯ РОТАЦИЯ (глубина 2)")
print("="*70)
top=Environment(); sub=Environment(); leaf=Agent()
sub.members=[leaf]; top.members=[sub]
rng=random.Random(0); seen=set()
for _ in range(60):
    top.rotate_defense(rng); top.tick(); seen.add(leaf.defense)
print(f"  Текущий код: защит листа за 60 тактов: {sorted(seen)} (|set|={len(seen)})")

def recursive_rotate(env, rng):
    Agent.rotate_defense(env, rng)
    for m in env.members:
        if isinstance(m, Environment):
            recursive_rotate(m, rng)
        else:
            Agent.rotate_defense(m, rng)
top2=Environment(); sub2=Environment(); leaf2=Agent()
sub2.members=[leaf2]; top2.members=[sub2]
rng=random.Random(0); seen2=set()
for _ in range(60):
    recursive_rotate(top2, rng); top2.tick(); seen2.add(leaf2.defense)
print(f"  Прототип (рекурсия + листья): {sorted(seen2)} (|set|={len(seen2)})")

print()
print("="*70)
print("P1-3. ПРОФИЛЬ: эффективный decay и режим p>1")
print("="*70)
for prof in ("ZEALOT","ORTHODOX","CANON","PRAGMATIST","OPPORTUNIST"):
    p=S.PROFILES[prof]; eff=DECAY_ADOPT*p
    flag=" <-- RUNAWAY (рост давления без напора!)" if eff>1.0 else ""
    print(f"  {prof:12} p={p:.2f}  eff_decay=DECAY*p={eff:.3f}{flag}")
print("  Наблюдаемость decay-канала (guess -> истина), где применимо:")
for prof in ("ZEALOT","CANON"):
    obs=Agent(); tgt=Agent(profile=prof); tgt.w_adopt=100.0
    rng=random.Random(0)
    for i in range(30): obs.sense(tgt, rng); tgt.tick_input_state()
    g=obs.beliefs.get("opp_decay_guess")
    print(f"    {prof:10} истина={DECAY_ADOPT*tgt.p:.3f} оценка={None if g is None else round(g,3)}")

# демонстрация runaway у OPPORTUNIST: вход открывается сам без напора
tgt=Agent(profile="OPPORTUNIST"); tgt.w_adopt=0.0
first_open=None
for t in range(120):
    tgt.tick_input_state(); tgt.receive_pressure(0.0)
    if tgt.in_open and first_open is None: first_open=t
print(f"  OPPORTUNIST: окно открылось БЕЗ внешнего напора на такте {first_open} "
      f"(w_adopt={tgt.w_adopt:.1f} при ON={tgt.schmitt_on():.1f})")

print()
print("="*70)
print("P1-5. expected_retaliation: отклонение и влияние на канон")
print("="*70)
mism=0; tot=0
orig_er = UtilityAI.expected_retaliation
def patched(self, work):
    global mism, tot
    if int(S.RETALIATE_FRACTION*work)>0:
        for hypo in TYPES:
            tot+=1
            if bool(MULT.get((self.beliefs["opp_last_act"], hypo))) != bool(MULT.get((self.defense, hypo))):
                mism+=1
    return orig_er(self, work)
UtilityAI.expected_retaliation=patched
rl=RLAgent()
for g in range(5): play_game(rl, UtilityAI(), 400, seed=g, with_env=True)
UtilityAI.expected_retaliation=orig_er
print(f"  Вердиктов контр-типа: {tot}, расхождений old/new: {mism} ({100*mism/max(1,tot):.1f}%)")

def er_fixed(self, work):
    r_w=int(S.RETALIATE_FRACTION*work)
    if r_w<=0: return 0.0
    ev=0.0
    for hypo in TYPES:
        mr=MULT.get((hypo, self.defense),1.0)
        pr=S.P_BASE/(1.0+math.exp(-S.K_TYPE)) if MULT.get((self.defense, hypo)) else S.P_BASE
        ev += r_w*self.gain_model_rev(mr, pr)/3.0
    return ev
_,_,base=S.run_batch(10, quiet=True, with_env=True)
UtilityAI.expected_retaliation=er_fixed
_,_,fixed=S.run_batch(10, quiet=True, with_env=True)
UtilityAI.expected_retaliation=orig_er
print(f"  Канон(10) ДО: {base}  ПОСЛЕ: {fixed}")
