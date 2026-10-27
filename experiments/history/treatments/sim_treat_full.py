import math
import random
import statistics
import matplotlib.pyplot as plt

TYPES = ["FIRE", "WATER", "EARTH"]


MULT = {
    ("WATER", "FIRE"): 3.0,
    ("FIRE", "EARTH"): 3.0,
    ("EARTH", "WATER"): 3.0,
}

ACTIONS = [("REST", 0)] + [(t, w) for t in TYPES for w in [0.3, 0.7]]


P_BASE = 0.6
K_MASS = 1.0
K_TYPE = 0.8
COST_FRACTION = 0.2


ON_THRESHOLD = 40.0
OFF_THRESHOLD = 15.0

OPEN_TTL = 8
GAIN_MAX = 1.2


Y_SMALL = 0.05
RECOUP_FRAC = GAIN_MAX / (1.0 + GAIN_MAX)


DECAY_ADOPT = 0.95


RETALIATE_FRACTION = 0.5
HOCK_FRACTION = 0.25
OPTION_VALUE = 0.10


K_EFFECT = 0.70


L_BASE = 15
L_STEP = 10
MAX_REST_DELTA = 4
STARVING_E = 2
E_MAX_MULT = 3
UPKEEP = 1
MAX_WORK = 200
MIN_OUTPUT = 3
BELIEF_NOISE = 2


CAPTURE_RATIO = 1.5
CAPTURE_STREAK = 20
CAPTURE_FRAC = 0.10


def p_success(att_type, att_work, dfn_type, dfn_work):
    mass = min(att_work, MAX_WORK) / max(dfn_work, 1)
    penalty = K_TYPE if MULT.get((dfn_type, att_type)) else 0.0
    logit = math.log(mass) * K_MASS - penalty
    return P_BASE / (1.0 + math.exp(-logit))


class Agent:
    def __init__(self, defense=None):
        self.force = 10
        self.energy_pool = 3
        self.rest_units = 0.0
        self.defense = defense if defense is not None else random.choice(TYPES)
        self.last_act = "REST"
        self.last_work = 0

        self.w_adopt = 0.0
        self.in_open = False
        self.open_timer = 0
        self.state = {"energy": 3, "defense": self.defense, "last_act": "REST"}
        self.beliefs = {
            "opp_energy": 3,
            "opp_defense": None,
            "opp_last_act": "REST",
            "opp_last_work": 0,
            "opp_force": 10,
            "opp_w_adopt": 0.0,
            "opp_in_open": False,
        }

    @property
    def rest_ceiling(self):
        return L_BASE + L_STEP * self.rest_units

    def rest_gain(self):
        e = self.force - UPKEEP
        ceiling = self.rest_ceiling
        return MAX_REST_DELTA * (e / ceiling) * (1.0 - e / ceiling)

    def do_rest(self, chosen=True):
        gain = self.rest_gain() if chosen else 0.5 * self.rest_gain()
        self.force = min(self.force + gain, self.rest_ceiling)

        add = max(2, self.regen) if chosen else 1
        self.energy_pool = min(self.energy_pool + add, E_MAX_MULT * self.regen)
        self.last_act, self.last_work = "REST", 0

    @property
    def regen(self):
        return max(1, math.floor(math.sqrt(self.force)))

    def tick_energy(self):
        self.energy_pool = min(
            self.energy_pool + self.regen, E_MAX_MULT * self.regen
        )

    def receive_pressure(self, w):
        self.w_adopt += w
        if not self.in_open and self.w_adopt >= ON_THRESHOLD:
            self.in_open = True
            self.open_timer = OPEN_TTL

    def tick_input_state(self):
        self.w_adopt *= DECAY_ADOPT
        if self.in_open:
            self.open_timer -= 1
            if self.open_timer <= 0 or self.w_adopt < OFF_THRESHOLD:
                self.in_open = False

    def sense(self, opp, rng):
        self.beliefs["opp_energy"] = max(
            1, opp.energy_pool + rng.randint(-BELIEF_NOISE, BELIEF_NOISE)
        )
        self.beliefs["opp_force"] = max(1, int(round(opp.force, -1)))
        self.beliefs["opp_w_adopt"] = max(0.0, opp.w_adopt)
        self.beliefs["opp_in_open"] = opp.in_open
        hist = self.beliefs.setdefault("opp_act_hist", [])
        hist.append(opp.last_act)
        if len(hist) > 5:
            hist.pop(0)
        non_rest = [a for a in hist if a != "REST"]
        self.beliefs["opp_defense_guess"] = (
            max(set(non_rest), key=non_rest.count) if non_rest else None
        )
        self.beliefs["opp_last_act"] = opp.last_act
        self.beliefs["opp_last_work"] = opp.last_work

    def rotate_defense(self, rng):
        counters = [
            t for t in TYPES if not MULT.get((self.beliefs["opp_last_act"], t))
        ]
        self.defense = rng.choice(counters) if counters else rng.choice(TYPES)
        self.state = {
            "energy": self.energy_pool,
            "defense": self.defense,
            "last_act": self.last_act,
        }

    def upkeep(self):
        self.force = max(1, self.force - UPKEEP)

    def commit(self, act, work):
        if act == "REST":
            self.do_rest(chosen=True)
            return 0

        w = min(
            int(work),
            self.energy_pool,
            MAX_WORK,
            max(MIN_OUTPUT, self.force // 4),
        )
        if w <= 0:
            self.do_rest(chosen=False)
            return 0
        self.energy_pool -= w
        self.last_act, self.last_work = act, w
        return w

    def rest_if_starving(self):
        if self.energy_pool <= STARVING_E:
            self.do_rest(chosen=True)
            return True
        return False

    def process_hit(self, tr):
        self.force = max(1, self.force - tr)
        self.energy_pool = max(0, self.energy_pool - int(HOCK_FRACTION * tr))
        self.state = {
            "energy": self.energy_pool,
            "defense": self.defense,
            "last_act": self.last_act,
        }

    def gain(self, tr):
        self.force += tr
        self.state = {
            "energy": self.energy_pool,
            "defense": self.defense,
            "last_act": self.last_act,
        }


class UtilityAI(Agent):
    def __init__(self):
        super().__init__()

    def gain_model(self, m, p):
        if self.beliefs["opp_in_open"]:
            return p * m * GAIN_MAX
        base = Y_SMALL * p * m

        progress = min(1.0, self.beliefs["opp_w_adopt"] / ON_THRESHOLD)
        option = OPTION_VALUE * progress
        return base + option

    def expected_retaliation(self, work):
        r_w = int(RETALIATE_FRACTION * work)
        if r_w <= 0:
            return 0.0
        ev_loss = 0.0
        for hypo_def in TYPES:
            mr = MULT.get((hypo_def, self.defense), 1.0)
            pr = (
                P_BASE / (1.0 + math.exp(-K_TYPE))
                if MULT.get((self.beliefs["opp_last_act"], hypo_def))
                else P_BASE
            )
            g = self.gain_model_rev(mr, pr)
            ev_loss += r_w * g / 3.0
        return ev_loss

    def gain_model_rev(self, m, p):
        if self.in_open:
            return p * m * GAIN_MAX
        return Y_SMALL * p * m

    def retaliation_penalty(self, work):
        r_w = int(RETALIATE_FRACTION * work)
        return COST_FRACTION * work + HOCK_FRACTION * r_w

    def expected_gain(self, act, work):
        if act == "REST" or work <= 0:
            return self.rest_gain()
        ev = 0.0
        for hypo in TYPES:
            m = MULT.get((act, hypo), 1.0)
            p = (
                P_BASE / (1.0 + math.exp(-K_TYPE))
                if MULT.get((hypo, act))
                else P_BASE
            )
            ev += work * self.gain_model(m, p) / 3.0
        return (
            ev
            - self.retaliation_penalty(work)
            - self.expected_retaliation(work)
        )

    def form_intention(self):
        best, best_u = ("REST", 0), self.rest_gain()
        for t in TYPES:
            for frac in (0.3, 0.7):
                w = int(self.energy_pool * frac)
                u = self.expected_gain(t, w)
                if u > best_u:
                    best, best_u = (t, w), u
        return best


class RLAgent(Agent):
    def __init__(self, q=None):
        super().__init__()
        self.Q = q if q is not None else {}

    def discretize(self, e):
        if e <= 8:
            return e
        if e <= 32:
            return 8 + (e - 8) // 4
        return 14 + int(math.log(e / 32))

    def skey(self):
        threat = (
            "T"
            if MULT.get((self.beliefs["opp_last_act"], self.defense))
            else "-"
        )
        adopt = self.discretize(int(self.beliefs["opp_w_adopt"]))
        openg = "O" if self.beliefs["opp_in_open"] else "C"
        return (
            self.discretize(self.energy_pool),
            self.discretize(self.beliefs["opp_energy"]),
            self.beliefs["opp_last_act"],
            threat,
            adopt,
            openg,
        )

    def form_intention(self, eps):
        st = self.skey()
        if st not in self.Q:
            self.Q[st] = [0.0] * len(ACTIONS)
        if random.random() < eps:
            return random.randint(0, len(ACTIONS) - 1)
        return self.Q[st].index(max(self.Q[st]))

    def learn(self, st, a_idx, reward, nst, alpha=0.3, gamma=0.9):
        if nst not in self.Q:
            self.Q[nst] = [0.0] * len(ACTIONS)
        td = reward + gamma * max(self.Q[nst]) - self.Q[st][a_idx]
        self.Q[st][a_idx] += alpha * td


def resolve_attack(att, dfn, work, rng):
    if not work:
        return
    att.force = max(1, att.force - int(COST_FRACTION * work))
    open_now = dfn.in_open

    dfn.receive_pressure(work)
    hit = rng.random() < p_success(
        att.last_act, work, dfn.defense, dfn.last_work
    )
    gained = 0
    if hit:
        m = MULT.get((att.last_act, dfn.defense), 1.0)
        gained = int(work * m * (GAIN_MAX if open_now else Y_SMALL))
        if gained:
            att.gain(gained)
            att.rest_units += gained
        dfn.process_hit(work)

        dfn.force = max(1, dfn.force + int(K_EFFECT * work))

    r_w = int(RETALIATE_FRACTION * work)
    if r_w > 0 and dfn.energy_pool >= 1:
        r_w = min(r_w, dfn.energy_pool, MAX_WORK)
        dfn.energy_pool -= r_w
        dfn.last_act = dfn.defense
        dfn.last_work = r_w
        rt = rng.random() < p_success(
            dfn.last_act, r_w, att.defense, att.last_work
        )
        if rt:
            mr = MULT.get((dfn.last_act, att.defense), 1.0)
            rg = int(r_w * mr * (GAIN_MAX if att.in_open else Y_SMALL))
            if rg:
                dfn.gain(rg)
                dfn.rest_units += rg
            att.process_hit(r_w)
            att.force = max(1, att.force + int(K_EFFECT * r_w))
            att.state = {
                "energy": att.energy_pool,
                "defense": att.defense,
                "last_act": att.last_act,
            }


def check_capture(rl, ai):
    global _dom_rl, _dom_ai
    _dom_rl = (
        _dom_rl + 1
        if (
            rl.energy_pool >= CAPTURE_RATIO * ai.energy_pool
            and rl.force > ai.force
        )
        else 0
    )
    _dom_ai = (
        _dom_ai + 1
        if (
            ai.energy_pool >= CAPTURE_RATIO * rl.energy_pool
            and ai.force > rl.force
        )
        else 0
    )
    if _dom_rl >= CAPTURE_STREAK:
        _dom_rl = _dom_ai = 0
        sev = 2.0 if ai.in_open else 1.0
        cap = int(ai.force * min(CAPTURE_FRAC * sev, 0.5))
        ai.force = max(1, ai.force - cap)
        ai.rest_units = max(0.0, ai.rest_units - cap / L_STEP)
        rl.gain(cap)
        return "RL"
    if _dom_ai >= CAPTURE_STREAK:
        _dom_ai = _dom_rl = 0
        sev = 2.0 if rl.in_open else 1.0
        cap = int(rl.force * min(CAPTURE_FRAC * sev, 0.5))
        rl.force = max(1, rl.force - cap)
        rl.rest_units = max(0.0, rl.rest_units - cap / L_STEP)
        ai.gain(cap)
        return "UtilityAI"
    return None


_dom_rl = 0
_dom_ai = 0


def play_game(rl, ai, steps=1000, seed=0):
    global _dom_rl, _dom_ai
    _dom_rl = _dom_ai = 0
    rng = random.Random(seed)
    rl_hist, ai_hist = [], []
    for step in range(steps):
        rl.sense(ai, rng)
        ai.sense(rl, rng)

        rl.rotate_defense(rng)
        ai.rotate_defense(rng)

        rl.upkeep()
        ai.upkeep()
        rl.tick_energy()
        ai.tick_energy()
        rl.tick_input_state()
        ai.tick_input_state()

        eps = max(0.05, 1.0 - step / 300)
        a_idx = rl.form_intention(eps)
        act_name, frac = ACTIONS[a_idx]
        st_before = rl.skey()
        f_before = rl.force

        if rl.rest_if_starving():
            w_rl = 0
        else:
            w_rl = rl.commit(act_name, rl.energy_pool * frac)

        ai_act, ai_work = ai.form_intention()
        if ai.rest_if_starving():
            w_ai = 0
        else:
            w_ai = ai.commit(ai_act, ai_work)

        resolve_attack(rl, ai, w_rl, rng)
        resolve_attack(ai, rl, w_ai, rng)

        rl_hist.append(rl.force)
        ai_hist.append(ai.force)
        rl.learn(st_before, a_idx, rl.force - f_before, rl.skey())

        winner = check_capture(rl, ai)
        if winner:
            return winner, rl_hist, ai_hist, step
    return None, rl_hist, ai_hist, steps


def run_batch(n_games=10, steps=1000, quiet=False):
    rl = RLAgent()
    results = {"RL": 0, "UtilityAI": 0, None: 0}
    finals = {"RL": [], "UtilityAI": [], None: []}
    last = None
    for g in range(n_games):
        winner, rl_hist, ai_hist, end_step = play_game(
            rl, UtilityAI(), steps, seed=g
        )
        results[winner] += 1
        finals[winner].append(rl.force)
        last = (winner, rl_hist, ai_hist, end_step)
        if not quiet:
            print(
                f"Game {g + 1}: winner={winner or 'no-capture'} at step "
                f"{end_step} | "
                f"final RL force={rl.force:.0f}, final UtilityAI "
                f"force={ai_hist[-1]:.0f}"
            )
    if not quiet:
        print("\nИтоги пакетного прогона:")
        print(
            f"  RL победил: {results['RL']}/{n_games}, "
            f"UtilityAI: {results['UtilityAI']}/{n_games}, "
            f"без решения: {results[None]}/{n_games}"
        )
        for k in finals:
            if finals[k]:
                print(
                    f"  Финальная сила RL при '{k}': "
                    f"медиана={statistics.median(finals[k]):.0f}"
                )
    return rl, last, results


def main():
    rl, (winner, rl_hist, ai_hist, end_step), results = run_batch(n_games=10)

    print(
        f"\nПоследняя партия: winner={winner or 'no-capture'}, "
        f"шагов={end_step}"
    )
    print(f"Q-состояний изучено: {len(rl.Q)}")

    plt.figure(figsize=(10, 6))
    plt.plot(rl_hist, label="RL Agent", color="blue", linewidth=2)
    plt.plot(ai_hist, label="Utility AI", color="red", linewidth=2)
    plt.title(
        "Динамика силы агентов (пороги Шмитта на входе адресата)", fontsize=14
    )
    plt.xlabel("Шаг симуляции", fontsize=12)
    plt.ylabel("Сила (Force, log)", fontsize=12)
    plt.yscale("log")
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
