import random

import simulation as S


def passive(me, opp, rng):
    return ("REST", 0)


def presser(me, opp, rng):
    return (rng.choice(S.TYPES), int(me.energy_pool * 0.7))


def timing(me, opp, rng):
    b = me.beliefs
    if b["opp_in_open"]:
        return (rng.choice(S.TYPES), int(me.energy_pool * 0.7))
    on_opp = max(S.ON_MIN, S.ON_FRAC * b["opp_force"])
    if b["opp_w_adopt"] >= 0.6 * on_opp and me.force > 30:
        return (rng.choice(S.TYPES), int(me.energy_pool * 0.5))
    return ("REST", 0)


def eager(me, opp, rng):
    b = me.beliefs
    if b["opp_in_open"]:
        return (rng.choice(S.TYPES), int(me.energy_pool * 0.7))
    on_opp = max(S.ON_MIN, S.ON_FRAC * b["opp_force"])
    if b["opp_w_adopt"] >= 0.4 * on_opp and me.force > 30:
        return (rng.choice(S.TYPES), int(me.energy_pool * 0.5))
    return ("REST", 0)


def mixed(me, opp, rng):
    if rng.random() < 0.5:
        return (rng.choice(S.TYPES), max(1, int(me.energy_pool * 0.7)))
    return ("REST", 0)


STRATEGIES = {
    "PASSIVE": passive,
    "PRESSER": presser,
    "TIMING": timing,
    "EAGER": eager,
    "MIXED": mixed,
}


COMPETITIVE = ("PRESSER", "TIMING", "EAGER")
CONTROLS = ("PASSIVE", "MIXED")

POLICY_SIGNATURE = "(me, opp, rng) -> (act, work)"


def duel(
    policy_a, policy_b, steps=400, seed=0, f0=10, env=None, capture_streak=20
):
    rng = random.Random(seed)
    a, b = S.Agent(), S.Agent()
    a.force = b.force = f0
    ha, hb = [], []
    dom_a = dom_b = 0
    for step in range(steps):
        S.run_tick(a, b, policy_a, policy_b, rng, env)
        ha.append(a.force)
        hb.append(b.force)
        dom_a = dom_a + 1 if S.dominates(a, b) else 0
        dom_b = dom_b + 1 if S.dominates(b, a) else 0
        if dom_a >= capture_streak:
            return "A", step, ha, hb
        if dom_b >= capture_streak:
            return "B", step, ha, hb
    return None, steps, ha, hb


def duel_matrix(names, n_seeds=20, steps=400, f0=10, env=None):
    mtx = {}
    for ka in names:
        for kb in names:
            tally = {"A": 0, "B": 0, None: 0}
            dfs = []
            for sd in range(n_seeds):
                w, st, ha, hb = duel(
                    STRATEGIES[ka],
                    STRATEGIES[kb],
                    steps=steps,
                    seed=sd,
                    f0=f0,
                    env=env,
                )
                tally[w] += 1
                dfs.append(ha[-1] - hb[-1])
            tally["df"] = dfs
            mtx[(ka, kb)] = tally
    return mtx
