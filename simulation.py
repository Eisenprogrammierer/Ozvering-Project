import math
import random
import matplotlib.pyplot as plt


TYPES = ["FIRE", "WATER", "EARTH"]
MULT = {("WATER", "FIRE"): 3.0, ("FIRE", "EARTH"): 3.0, ("EARTH", "WATER"): 3.0}

ACTIONS = [("REST", 0)] + [(t, w) for t in TYPES for w in [0.3, 0.7]]


class Agent:
    """Базовый автомат (IPO + BDI)"""
    def __init__(self, defense="FIRE"):
        self.force = 10
        self.defense = defense
        self.last_act = "REST"
        self.beliefs = {"opp_energy": 3, "opp_last_act": "REST"}

    @property
    def energy(self): 
        return max(1, math.floor(math.sqrt(self.force)))

    def apply(self, act, work, dfn):
        """Processing: передача энергии и изменение силы"""
        if act == "REST": 
            self.force += 2 
            self.last_act = "REST"
            return
        m = MULT.get((act, dfn.defense), 1.0)
        tr = int(work * m)
        self.force += tr
        dfn.force = max(1, dfn.force - tr)
        self.last_act = act
        dfn.beliefs["opp_last_act"] = act 


class UtilityAI(Agent):
    """Заскриптованный агент (жестко привязан к Огню)"""
    def __init__(self):
        super().__init__("FIRE") 
        
    def form_intention(self):
        return ("FIRE", 0.7) if self.energy > self.beliefs["opp_energy"] else ("REST", 0)


class RLAgent(Agent):
    """Обучающийся агент (Q-Learning)"""
    def __init__(self):
        super().__init__("WATER") 
        self.Q = {}
        
    def state(self):
        return (self.energy // 5, self.beliefs["opp_energy"] // 5, self.beliefs["opp_last_act"])
        
    def form_intention(self, step):
        st = self.state()
        if st not in self.Q: self.Q[st] = [0.0] * len(ACTIONS)
        eps = max(0.02, 1.0 - step / 300) 
        if random.random() < eps:
            return random.randint(0, len(ACTIONS) - 1)
        return self.Q[st].index(max(self.Q[st]))
        
    def learn(self, st, a_idx, reward, nst):
        if nst not in self.Q: self.Q[nst] = [0.0] * len(ACTIONS)
        self.Q[st][a_idx] += 0.3 * (reward + 0.9 * max(self.Q[nst]) - self.Q[st][a_idx])


def simulate():
    rl, ai = RLAgent(), UtilityAI()
    rl_hist, ai_hist = [], []
    
    for step in range(1000):
        rl.beliefs["opp_energy"] = max(1, ai.energy + random.randint(-1, 1))
        ai.beliefs["opp_energy"] = max(1, rl.energy + random.randint(-1, 1))

        a_rl_idx = rl.form_intention(step)
        a_rl_act, a_rl_frac = ACTIONS[a_rl_idx]
        a_ai_act, a_ai_frac = ai.form_intention()
        
        f_rl_old = rl.force
        
        w_rl = 0 if a_rl_act == "REST" else int(rl.energy * a_rl_frac)
        w_ai = 0 if a_ai_act == "REST" else int(ai.energy * a_ai_frac)

        rl.apply(a_rl_act, w_rl, ai)
        ai.apply(a_ai_act, w_ai, rl)

        rl_hist.append(rl.force)
        ai_hist.append(ai.force)
        rl.learn(rl.state(), a_rl_idx, rl.force - f_rl_old, rl.state())

    print(f"Step 1000 | RL: {rl.force} | UtilityAI: {ai.force}")
    print("Winner:", "RL" if rl.force > ai.force else "UtilityAI")


    plt.figure(figsize=(10, 6))
    plt.plot(rl_hist, label="RL Agent (Water)", color='blue', linewidth=2)
    plt.plot(ai_hist, label="Utility AI (Fire)", color='red', linewidth=2)
    
    plt.title("Динамика силы агентов в процессе обучения", fontsize=14)
    plt.xlabel("Шаг симуляции", fontsize=12)
    plt.ylabel("Сила (Force)", fontsize=12)

    plt.yscale("log") 
    
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.show()

simulate()