import random, statistics
import simulation as S
from simulation import *

def duel(A_cls, B_cls, n=20, steps=800):
    """Локальные счётчики доминирования — не зависим от глобальных."""
    score=[0,0]; draws=0; ends=[]
    for g in range(n):
        A, B = A_cls(), B_cls()
        r = random.Random(1000+g)
        dom_a=dom_b=0; w=None
        for step in range(steps):
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
            dom_a = dom_a+1 if da else 0
            dom_b = dom_b+1 if db else 0
            if dom_a>=CAPTURE_STREAK: w=0; break
            if dom_b>=CAPTURE_STREAK: w=1; break
        ends.append(step)
        if w is None: draws+=1
        else: score[w]+=1
    return score, draws, statistics.mean(ends)

class Worker(Agent):
    """Упорный давящий: ждёт износа противника, потом бьёт всем пулом, ротируя тип."""
    def __init__(self): super().__init__(); self._i=0
    def act(self):
        self._i+=1
        return TYPES[self._i%3], self.energy_pool
class PatientWorker(Agent):
    """Терпеливый стратег: копит энергию в покое, давит ТОЛЬКО когда x >= X_SCALE."""
    def __init__(self): super().__init__(); self._i=0
    def act(self):
        if self.beliefs["opp_depletion"] < X_SCALE: return "REST",0
        self._i+=1
        return TYPES[self._i%3], self.energy_pool
class Passive(Agent):
    def act(self): return "REST",0

print("== 5a: наивный работник vs пассив ==")
sc,dr,end = duel(Worker, Passive)
print(f"   работник {sc[0]} : пассив {sc[1]}, ничьих {dr}, сред. длительность {end:.0f}")

print("== 5b: терпеливый стратег vs пассив ==")
sc,dr,end = duel(PatientWorker, Passive)
print(f"   стратег {sc[0]} : пассив {sc[1]}, ничьих {dr}, сред. длительность {end:.0f}")

print("== 5c: терпеливый стратег vs наивный работник ==")
sc,dr,end = duel(PatientWorker, Worker)
print(f"   стратег {sc[0]} : работник {sc[1]}, ничьих {dr}, сред. длительность {end:.0f}")

print("== 5d: пассив vs терпеливый (смена мест — проверка симметрии) ==")
sc,dr,end = duel(Passive, PatientWorker)
print(f"   пассив {sc[0]} : стратег {sc[1]}, ничьих {dr}, сред. длительность {end:.0f}")

print("== 6: RL vs UtilityAI — крупный пакет со сквозным обучением (n=40) ==")
rl = RLAgent()
res={"RL":0,"UtilityAI":0,None:0}; tl=[]
for g in range(40):
    w,h1,h2,st = play_game(rl, UtilityAI(), 1000, seed=g)
    res[w]+=1; tl.append((g,w,st))
print(f"   Итог: RL={res['RL']} AI={res['UtilityAI']} без решения={res[None]}")
first_rl = next((g for g,w,_ in tl if w=="RL"), None)
print(f"   Первая победа RL на партии #{first_rl}")
# динамика: разбивки по 10 партий
for i in range(0,40,10):
    chunk = tl[i:i+10]
    rl_w = sum(1 for _,w,_ in chunk if w=="RL")
    print(f"   партии {i}-{i+9}: RL побед {rl_w}/10")
