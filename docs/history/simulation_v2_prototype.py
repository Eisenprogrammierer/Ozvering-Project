"""
СТАТУС: АРХИТЕКТУРНО ОТВЕРГНУТЫЙ ПРОТОТИП (сохранён для истории идей).
Нейтральная онтология IDEA/CAPITAL/FORCE, переменные capital/resistance и
профили сущностей были отвергнуты автором проекта как избыточные: всё, что они
описывают, выводится из IPO-архитектуры и двух метрик (энергия/сила).
Каноническая модель — simulation.py (в корне репозитория). Не использовать как основу развития.
"""
import math
import random
import statistics
import matplotlib.pyplot as plt

# --- КОНСТАНТЫ МОДЕЛИ ---

TYPES = ["IDEA", "CAPITAL", "FORCE"] 
# Интерпретация типов:
# IDEA: Информационное/культурное влияние (контрит CAPITAL, но слабо против FORCE)
# CAPITAL: Экономическое давление (контрит FORCE, но слабо против IDEA)
# FORCE: Силовое/административное принуждение (контрит IDEA, но слабо против CAPITAL)

# Цикл: IDEA > CAPITAL > FORCE > IDEA
MULT_BASE = {
    ("IDEA", "CAPITAL"): 1.5,
    ("CAPITAL", "FORCE"): 1.5,
    ("FORCE", "IDEA"): 1.5,
    # Обратные связи слабее
    ("CAPITAL", "IDEA"): 0.8,
    ("FORCE", "CAPITAL"): 0.8,
    ("IDEA", "FORCE"): 0.8,
    # Нейтральные
    ("IDEA", "IDEA"): 1.0,
    ("CAPITAL", "CAPITAL"): 1.0,
    ("FORCE", "FORCE"): 1.0,
}

ACTIONS = [("REST", None)] + [(t, w_ratio) for t in TYPES for w_ratio in [0.3, 0.7]]

# Параметры баланса
INITIAL_CAPITAL = 100
ENERGY_REGEN_RATE = 0.1  # Доля capital, превращаемая в доступную энергию за ход
UPKEEP_COST = 0.02       # Стоимость содержания структуры (доля capital)
RESISTANCE_LEARN_RATE = 0.15  # Скорость роста резистентности к успешному воздействию
RESISTANCE_DECAY = 0.05       # Забывание (снижение резистентности)
EFFICIENCY_SCALE = 10.0       # Масштаб для функции эффективности

def calc_efficiency(work_amount, current_capital):
    """
    Закон убывающей отдачи.
    Слишком большое усилие относительно базы дает меньший эффект.
    """
    if current_capital <= 0: return 0
    ratio = work_amount / math.sqrt(current_capital)
    return 1.0 / (1.0 + (ratio / EFFICIENCY_SCALE) ** 2)

class Entity:
    def __init__(self, name, base_resistance=None):
        self.name = name
        self.capital = INITIAL_CAPITAL
        self.energy_pool = int(INITIAL_CAPITAL * ENERGY_REGEN_RATE)
        
        # Профиль резистентности: сколько "щита" накоплено против каждого типа
        # Изначально все равны (нейтральны)
        self.resistance = {t: 1.0 for t in TYPES}
        
        self.last_action_type = None
        self.history = []

    @property
    def max_energy(self):
        return int(math.sqrt(self.capital))

    def update_state(self):
        # Восстановление энергии и содержание структуры
        regen = int(self.capital * ENERGY_REGEN_RATE)
        upkeep = int(self.capital * UPKEEP_COST)
        
        self.energy_pool = min(self.max_energy, self.energy_pool + regen)
        self.capital = max(1, self.capital - upkeep)
        
        # Декей резистентности (если долго не атаковали этим типом, щит слабеет)
        for t in self.resistance:
            self.resistance[t] = max(0.5, self.resistance[t] - RESISTANCE_DECAY)

    def apply_influence(self, target, action_type, work_amount):
        """
        Передача воздействия.
        """
        if action_type == "REST" or work_amount <= 0:
            self.capital += 5 # Отдых восстанавливает немного капитала напрямую
            self.last_action_type = "REST"
            return 0
        
        # 1. Затрата энергии
        cost = int(work_amount * 0.2) # Часть энергии сгорает как накладные расходы
        self.energy_pool = max(0, self.energy_pool - cost)
        self.last_action_type = action_type
        
        # 2. Расчет базовой силы воздействия
        base_mult = MULT_BASE.get((action_type, target.last_action_type), 1.0)
        
        # 3. Эффективность масштаба
        eff = calc_efficiency(work_amount, self.capital)
        
        # 4. Влияние резистентности цели
        # Резистентность снижает передаваемую силу
        resist_factor = 1.0 / target.resistance[action_type]
        
        final_transfer = int(work_amount * base_mult * eff * resist_factor)
        
        # 5. Применение эффекта
        # Агрессор получает выгоду (прирост капитала через доминирование)
        self.capital += final_transfer
        # Цель теряет капитал
        target.capital = max(1, target.capital - final_transfer)
        
        # 6. Обучение резистентности цели
        # Если цель получила сильный удар, она адаптируется к этому типу
        adaptation = RESISTANCE_LEARN_RATE * (final_transfer / max(1, target.capital))
        target.resistance[action_type] += adaptation
        
        return final_transfer

class UtilityEntity(Entity):
    """
    Детерминированный агент, maximizing Expected Value based on simple heuristics.
    """
    def choose_action(self, opponent):
        best_val = -float('inf')
        best_act = ("REST", None)
        
        # Прогноз: ожидаемая эффективность vs затраты
        for act_name, ratio in ACTIONS:
            if act_name == "REST":
                val = 5.0 # Простая эвристика пользы отдыха
            else:
                work = int(self.energy_pool * ratio)
                if work <= 0: continue
                
                # Оценка успеха: зависит от текущего сопротивления оппонента
                r = opponent.resistance[act_name]
                m = MULT_BASE.get((act_name, opponent.last_action_type), 1.0)
                
                # EV = (Gain - Loss_Risk)
                # Gain ~ work * m / r
                # Cost ~ work * 0.2
                ev = (work * m / r) - (work * 0.2)
                val = ev
            
            if val > best_val:
                best_val = val
                best_act = (act_name, ratio)
                
        return best_act

class RLEntity(Entity):
    """
    Q-Learning Agent. State includes own energy, opponent's dominant resistance.
    """
    def __init__(self, q_table=None):
        super().__init__("RL")
        self.Q = q_table if q_table is not None else {}

    def get_state_key(self, opponent):
        # Дискретизация
        e_bucket = self.energy_pool // 10
        opp_r_bucket = sum(opponent.resistance.values()) // 3
        return (e_bucket, opp_r_bucket, opponent.last_action_type)

    def choose_action(self, opponent, eps):
        state = self.get_state_key(opponent)
        if state not in self.Q:
            self.Q[state] = [0.0] * len(ACTIONS)
            
        if random.random() < eps:
            return random.choice(ACTIONS)
        else:
            idx = self.Q[state].index(max(self.Q[state]))
            return ACTIONS[idx]

    def learn(self, prev_state, action_idx, reward, next_state, alpha=0.1, gamma=0.9):
        if next_state not in self.Q:
            self.Q[next_state] = [0.0] * len(ACTIONS)
            
        predict = self.Q[prev_state][action_idx]
        target = reward + gamma * max(self.Q[next_state])
        self.Q[prev_state][action_idx] += alpha * (target - predict)

def run_simulation(steps=500, seed=0):
    rng = random.Random(seed)
    
    rl_agent = RLEntity()
    util_agent = UtilityEntity("Utility")
    
    history_rl = []
    history_util = []
    
    # RL learns across episodes if we pass Q table, here fresh start
    
    for step in range(steps):
        rl_agent.update_state()
        util_agent.update_state()
        
        # RL chooses
        eps = max(0.05, 1.0 - step/200)
        rl_act = rl_agent.choose_action(util_agent, eps)
        rl_idx = ACTIONS.index(rl_act)
        rl_prev_state = rl_agent.get_state_key(util_agent)
        
        # Utility chooses
        util_act = util_agent.choose_action(rl_agent)
        
        # Execute actions simultaneously
        # Work amounts calculated from energy pool
        rl_work = int(rl_agent.energy_pool * rl_act[1]) if rl_act[1] else 0
        util_work = int(util_agent.energy_pool * util_act[1]) if util_act[1] else 0
        
        rl_gain = rl_agent.apply_influence(util_agent, rl_act[0], rl_work)
        util_gain = util_agent.apply_influence(rl_agent, util_act[0], util_work)
        
        # Rewards for RL
        # Reward = Change in Capital
        reward = rl_agent.capital - history_rl[-1] if history_rl else 0
        rl_next_state = rl_agent.get_state_key(util_agent)
        rl_agent.learn(rl_prev_state, rl_idx, reward, rl_next_state)
        
        history_rl.append(rl_agent.capital)
        history_util.append(util_agent.capital)
        
    return history_rl, history_util, rl_agent, util_agent

def main():
    print("Starting Simulation v2 (Non-Military Abstraction)...")
    
    # Batch run to check stability
    results = {"RL": 0, "Utility": 0, "Draw": 0}
    all_hist_rl = []
    all_hist_util = []
    
    n_games = 10
    for i in range(n_games):
        h_rl, h_util, rl, util = run_simulation(steps=500, seed=i)
        winner = "Draw"
        if rl.capital > util.capital * 1.1:
            winner = "RL"
        elif util.capital > rl.capital * 1.1:
            winner = "Utility"
        results[winner] += 1
        all_hist_rl.append(h_rl)
        all_hist_util.append(h_util)
        print(f"Game {i+1}: RL={rl.capital:.0f}, Util={util.capital:.0f} -> Winner: {winner}")

    print("\nOverall Results:", results)
    
    # Plot average trajectories
    avg_rl = [statistics.mean(x) for x in zip(*all_hist_rl)]
    avg_util = [statistics.mean(x) for x in zip(*all_hist_util)]
    
    plt.figure(figsize=(10, 6))
    plt.plot(avg_rl, label="RL Agent (Adaptive)", color='blue')
    plt.plot(avg_util, label="Utility AI (Heuristic)", color='red')
    plt.title("Capital Dynamics: Strategic Balance Test")
    plt.xlabel("Steps")
    plt.ylabel("Average Capital")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    main()
