import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import random, statistics
from simulation import *

print("="*70)
print("ЭКСПЕРИМЕНТ 1: жизнеспособность чистого покоя (одиночный агент)")
a = Agent()
for t in range(200):
    a.upkeep(); a.tick_energy(); a.do_rest()
print(f"  200 шагов покоя: F={a.force:.1f} (старт 10), потолок L={a.rest_ceiling:.0f}")

print("="*70)
print("ЭКСПЕРИМЕНТ 2: S-кривая и окупаемость давления (аналитика)")
for x in [0, 5, 15, 30, 60, 120]:
    s = pressure_yield(x)
    ev_m1 = P_BASE*s - COST_FRACTION          # тип не угадан (m=1), p=P_BASE
    ev_m3 = P_BASE*3*s - COST_FRACTION        # тип угадан (m=3)
    print(f"  x={x:4d}: S={s:.3f} | E[dF]/w при m=1: {ev_m1:+.3f} | при m=3: {ev_m3:+.3f}")

print("="*70)
print("ЭКСПЕРИМЕНТ 3: дуэли RL vs UtilityAI (n=20, сквозное обучение)")
rl = RLAgent()
res = {"RL":0,"UtilityAI":0,None:0}; steps_all=[]
for g in range(20):
    w,h1,h2,s = play_game(rl, UtilityAI(), 1000, seed=g)
    res[w]+=1; steps_all.append(s)
print(f"  Итог: RL={res['RL']} AI={res['UtilityAI']} без решения={res[None]}")
print(f"  Средняя длительность: {statistics.mean(steps_all):.0f} шагов")

print("="*70)
print("ЭКСПЕРИМЕНТ 4: зеркальные дуэли (равные архитектуры, разные сиды) n=20")
# UtilityAI vs UtilityAI — ни один не имеет архитектурного преимущества
wins=[0,0]
for g in range(20):
    a1, a2 = UtilityAI(), UtilityAI()
    rng = random.Random(g)
    # переиспользуем play_game через обёртку с двумя utility? проще: свой цикл
    global _dom_rl,_dom_ai
    _dom_rl=_dom_ai=0
    r = random.Random(g)
    winner=None
    for step in range(1000):
        a1.sense(a2,r); a2.sense(a1,r)
        a1.rotate_defense(r); a2.rotate_defense(r)
        a1.upkeep(); a2.upkeep(); a1.tick_energy(); a2.tick_energy()
        a1.heal_depletion(); a2.heal_depletion()
        i1,wk1=a1.form_intention(); i2,wk2=a2.form_intention()
        if a1.rest_if_starving(): wk1=0
        else: wk1=a1.commit(i1,wk1)
        if a2.rest_if_starving(): wk2=0
        else: wk2=a2.commit(i2,wk2)
        resolve_attack(a1,a2,wk1,r); resolve_attack(a2,a1,wk2,r)
        d1 = a1.energy_pool >= CAPTURE_RATIO*a2.energy_pool and a1.force>a2.force
        d2 = a2.energy_pool >= CAPTURE_RATIO*a1.energy_pool and a2.force>a1.force
        _dom_rl = _dom_rl+1 if d1 else 0
        _dom_ai = _dom_ai+1 if d2 else 0
        if _dom_rl>=CAPTURE_STREAK: winner=1; break
        if _dom_ai>=CAPTURE_STREAK: winner=2; break
    if winner: wins[winner-1]+=1
print(f"  Зеркальная дуэль UAI vs UAI: победа1={wins[0]}, победа2={wins[1]}, ничьих={20-wins[0]-wins[1]}")

print("="*70)
print("ЭКСПЕРИМЕНТ 5: пассив vs работник (проверка 'упорство окупается')")
class Worker(Agent):
    """Давит всегда, максимальным объёмом, ротируя тип."""
    def __init__(self): super().__init__(); self._i=0
    def act(self):
        self._i+=1
        return TYPES[self._i%3], self.energy_pool
class Passive(Agent):
    def act(self): return "REST",0

def duel(w_cls, p_cls, n=20):
    score=[0,0]; draws=0
    for g in range(n):
        A, B = w_cls(), p_cls()
        r = random.Random(g)
        w=None
        for step in range(800):
            A.sense(B,r); B.sense(A,r)
            A.rotate_defense(r); B.rotate_defense(r)
            A.upkeep(); B.upkeep(); A.tick_energy(); B.tick_energy()
            A.heal_depletion(); B.heal_depletion()
            ia,wa=A.act(); ib,wb=B.act()
            wa = 0 if A.rest_if_starving() else A.commit(ia,wa)
            wb = 0 if B.rest_if_starving() else B.commit(ib,wb)
            resolve_attack(A,B,wa,r); resolve_attack(B,A,wb,r)
            da = A.energy_pool>=CAPTURE_RATIO*B.energy_pool and A.force>B.force
            db = B.energy_pool>=CAPTURE_RATIO*A.energy_pool and B.force>A.force
            _dom_rl = _dom_rl+1 if da else 0
            _dom_ai = _dom_ai+1 if db else 0
            if _dom_rl>=CAPTURE_STREAK: w=0; break
            if _dom_ai>=CAPTURE_STREAK: w=1; break
        if w is None: draws+=1
        else: score[w]+=1
    return score, draws

sc, dr = duel(Worker, Passive)
print(f"  Работник(всегда давит) vs Пассив(вечно отдыхает): работник {sc[0]}, пассив {sc[1]}, ничьих {dr} (n=20)")
sc, dr = duel(Passive, Worker)
print(f"  То же, но пассив ходит первым: пассив {sc[0]}, работник {sc[1]}, ничьих {dr}")
