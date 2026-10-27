import math
import random
import statistics
import matplotlib.pyplot as plt

TYPES = ["IDEA", "CAPITAL", "FORCE"]


MULT_BASE = {
    ("IDEA", "CAPITAL"): 1.5,
    ("CAPITAL", "FORCE"): 1.5,
    ("FORCE", "IDEA"): 1.5,
    ("CAPITAL", "IDEA"): 0.8,
    ("FORCE", "CAPITAL"): 0.8,
    ("IDEA", "FORCE"): 0.8,
    ("IDEA", "IDEA"): 1.0,
    ("CAPITAL", "CAPITAL"): 1.0,
    ("FORCE", "FORCE"): 1.0,
}

ACTIONS = [("REST", None)] + [
    (t, w_ratio) for t in TYPES for w_ratio in [0.3, 0.7]
]


INITIAL_CAPITAL = 100
ENERGY_REGEN_RATE = 0.1
UPKEEP_COST = 0.02
RESISTANCE_LEARN_RATE = 0.15
RESISTANCE_DECAY = 0.05
EFFICIENCY_SCALE = 10.0


def calc_efficiency(work_amount, current_capital):
    if current_capital <= 0:
        return 0
    ratio = work_amount / math.sqrt(current_capital)
    return 1.0 / (1.0 + (ratio / EFFICIENCY_SCALE) ** 2)


class Entity:
    def __init__(self, name, base_resistance=None):
        self.name = name
        self.capital = INITIAL_CAPITAL
        self.energy_pool = int(INITIAL_CAPITAL * ENERGY_REGEN_RATE)

        self.resistance = {t: 1.0 for t in TYPES}

        self.last_action_type = None
        self.history = []

    @property
    def max_energy(self):
        return int(math.sqrt(self.capital))

    def update_state(self):

        regen = int(self.capital * ENERGY_REGEN_RATE)
        upkeep = int(self.capital * UPKEEP_COST)

        self.energy_pool = min(self.max_energy, self.energy_pool + regen)
        self.capital = max(1, self.capital - upkeep)

        for t in self.resistance:
            self.resistance[t] = max(
                0.5, self.resistance[t] - RESISTANCE_DECAY
            )

    def apply_influence(self, target, action_type, work_amount):
        if action_type == "REST" or work_amount <= 0:
            self.capital += 5
            self.last_action_type = "REST"
            return 0

        cost = int(work_amount * 0.2)
        self.energy_pool = max(0, self.energy_pool - cost)
        self.last_action_type = action_type

        base_mult = MULT_BASE.get((action_type, target.last_action_type), 1.0)

        eff = calc_efficiency(work_amount, self.capital)

        resist_factor = 1.0 / target.resistance[action_type]

        final_transfer = int(work_amount * base_mult * eff * resist_factor)

        self.capital += final_transfer

        target.capital = max(1, target.capital - final_transfer)

        adaptation = RESISTANCE_LEARN_RATE * (
            final_transfer / max(1, target.capital)
        )
        target.resistance[action_type] += adaptation

        return final_transfer


class UtilityEntity(Entity):
    def choose_action(self, opponent):
        best_val = -float("inf")
        best_act = ("REST", None)

        for act_name, ratio in ACTIONS:
            if act_name == "REST":
                val = 5.0
            else:
                work = int(self.energy_pool * ratio)
                if work <= 0:
                    continue

                r = opponent.resistance[act_name]
                m = MULT_BASE.get((act_name, opponent.last_action_type), 1.0)

                ev = (work * m / r) - (work * 0.2)
                val = ev

            if val > best_val:
                best_val = val
                best_act = (act_name, ratio)

        return best_act


class RLEntity(Entity):
    def __init__(self, q_table=None):
        super().__init__("RL")
        self.Q = q_table if q_table is not None else {}

    def get_state_key(self, opponent):

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

    def learn(
        self, prev_state, action_idx, reward, next_state, alpha=0.1, gamma=0.9
    ):
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

    for step in range(steps):
        rl_agent.update_state()
        util_agent.update_state()

        eps = max(0.05, 1.0 - step / 200)
        rl_act = rl_agent.choose_action(util_agent, eps)
        rl_idx = ACTIONS.index(rl_act)
        rl_prev_state = rl_agent.get_state_key(util_agent)

        util_act = util_agent.choose_action(rl_agent)

        rl_work = int(rl_agent.energy_pool * rl_act[1]) if rl_act[1] else 0
        util_work = (
            int(util_agent.energy_pool * util_act[1]) if util_act[1] else 0
        )

        rl_gain = rl_agent.apply_influence(util_agent, rl_act[0], rl_work)
        util_gain = util_agent.apply_influence(
            rl_agent, util_act[0], util_work
        )

        reward = rl_agent.capital - history_rl[-1] if history_rl else 0
        rl_next_state = rl_agent.get_state_key(util_agent)
        rl_agent.learn(rl_prev_state, rl_idx, reward, rl_next_state)

        history_rl.append(rl_agent.capital)
        history_util.append(util_agent.capital)

    return history_rl, history_util, rl_agent, util_agent


def main():
    print("Starting Simulation v2 (Non-Military Abstraction)...")

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
        print(
            f"Game {i + 1}: RL={rl.capital:.0f}, Util={util.capital:.0f} -> "
            f"Winner: {winner}"
        )

    print("\nOverall Results:", results)

    avg_rl = [statistics.mean(x) for x in zip(*all_hist_rl)]
    avg_util = [statistics.mean(x) for x in zip(*all_hist_util)]

    plt.figure(figsize=(10, 6))
    plt.plot(avg_rl, label="RL Agent (Adaptive)", color="blue")
    plt.plot(avg_util, label="Utility AI (Heuristic)", color="red")
    plt.title("Capital Dynamics: Strategic Balance Test")
    plt.xlabel("Steps")
    plt.ylabel("Average Capital")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
