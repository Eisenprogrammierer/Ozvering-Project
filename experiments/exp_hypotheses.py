import sys
import os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
import random
import statistics
import matplotlib

matplotlib.use("Agg")
import simulation as S


def make_scripted(kind):
    def policy(me, opp, rng):
        if kind == "PASSIVE":
            return ("REST", 0)
        if kind == "PRESSER":
            t = rng.choice(S.TYPES)
            return (t, int(me.energy_pool * 0.7))
        if kind == "TIMING":
            if me.beliefs["opp_in_open"]:
                guess = me.beliefs["opp_defense_guess"]
                counters = [t for t in S.TYPES if S.MULT.get((t, guess))]
                t = rng.choice(counters) if counters else rng.choice(S.TYPES)
                return (t, int(me.energy_pool * 0.7))
            if (
                me.beliefs["opp_w_adopt"]
                >= 0.6 * max(S.ON_MIN, S.ON_FRAC * me.beliefs["opp_force"])
                and me.force > 30
            ):
                return (rng.choice(S.TYPES), int(me.energy_pool * 0.5))
            return ("REST", 0)
        raise ValueError(kind)

    return policy


def duel(policy_a, policy_b, steps=400, seed=0, trace=False):
    rng = random.Random(seed)
    a, b = S.Agent(), S.Agent()
    ha, hb = [], []
    tr = []
    dom_a = dom_b = 0
    for step in range(steps):
        a.sense(b, rng)
        b.sense(a, rng)
        a.rotate_defense(rng)
        b.rotate_defense(rng)
        a.upkeep()
        b.upkeep()
        a.tick_energy()
        b.tick_energy()
        a.tick_input_state()
        b.tick_input_state()
        act, w = policy_a(a, b, rng)
        wa = 0 if a.rest_if_starving() else a.commit(act, w)
        act, w = policy_b(b, a, rng)
        wb = 0 if b.rest_if_starving() else b.commit(act, w)
        S.resolve_attack(a, b, wa, rng)
        S.resolve_attack(b, a, wb, rng)
        ha.append(a.force)
        hb.append(b.force)
        if trace:
            tr.append(
                dict(
                    step=step,
                    fa=a.force,
                    fb=b.force,
                    ea=a.energy_pool,
                    eb=b.energy_pool,
                    wa=wa,
                    wb=wb,
                    a_adopt=round(a.w_adopt, 1),
                    b_adopt=round(b.w_adopt, 1),
                    a_open=a.in_open,
                    b_open=b.in_open,
                )
            )
        dom_a = (
            dom_a + 1
            if (
                a.force >= 1.5 * b.force
                and a.energy_pool >= 1.5 * b.energy_pool
            )
            else 0
        )
        dom_b = (
            dom_b + 1
            if (
                b.force >= 1.5 * a.force
                and b.energy_pool >= 1.5 * b.energy_pool
            )
            else 0
        )
        if dom_a >= 20:
            return "A", step, ha, hb, tr
        if dom_b >= 20:
            return "B", step, ha, hb, tr
    return None, steps, ha, hb, tr


print("=" * 78)
print("H1: СЕТКА ПО ОГРАНИЧИТЕЛЯМ СРЕДЫ (E_MAX_MULT x UPKEEP).")
print("    Дуэль PRESSER vs PASSIVE, 5 сидов, 400 шагов.")
print(
    "    Предсказание H1: при низком потолке пула/высоком upkeep преимущество"
)
print("    давления сократится или исчезнет.")
print("=" * 78)
base_emax, base_upk = S.E_MAX_MULT, S.UPKEEP
for emax in (1, 2, 3, 6):
    for upk in (1, 2, 4):
        S.E_MAX_MULT, S.UPKEEP = emax, upk
        wins_p = wins_pass = draws = 0
        dfa = []
        for sd in range(5):
            w, st, ha, hb, _ = duel(
                make_scripted("PRESSER"), make_scripted("PASSIVE"), 400, sd
            )

            if w == "A":
                wins_p += 1
            elif w == "B":
                wins_pass += 1
            else:
                draws += 1
            dfa.append(ha[-1] - hb[-1])
        print(
            f"  E_MAX_MULT={emax}, UPKEEP={upk}: PRESSER {wins_p} | PASSIVE "
            f"{wins_pass} | ничья {draws}"
            f" | медиана ΔF(PRESSER-PASSIVE)={statistics.median(dfa):+.0f}"
        )
S.E_MAX_MULT, S.UPKEEP = base_emax, base_upk

print()
print("=" * 78)
print("H1-контроль: знак чистой экономики обмена (аналитика + замер).")
print(
    "  При закрытом входе давящий платит: COST_FRACTION*w безвозвратно из "
    "силы,"
)
print("  получает Y_SMALL*m*w, теряет возмездие r_w*(...) и fatigue. Замер:")
rng = random.Random(0)
a, b = S.Agent(), S.Agent()
net = []
for i in range(60):
    fa0 = a.force
    w = min(5, a.energy_pool)
    a.energy_pool -= w
    S.resolve_attack(a, b, w, rng)
    net.append(a.force - fa0)
print(
    f"  Средний шаг давления по ЗАКРЫТОМУ входу: {statistics.mean(net):+.2f} "
    f"силы за удар."
)
print(
    "  Если отрицательно устойчиво — давление убыточно при ЛЮБЫХ насыщениях:"
)
print("  проблема не в H1 (насыщении), а в знаке закона передачи.")

print()
print("=" * 78)
print("H2: ПОЧЕМУ КАМПАНИЯ TIMING ИМЕЕТ ΔF=0? Трассировка входа обеих сторон.")
print("=" * 78)
w, st, ha, hb, tr = duel(
    make_scripted("TIMING"), make_scripted("PASSIVE"), 200, 0, trace=True
)
opens = [t for t in tr if t["b_open"]]
hits = [t for t in tr if t["wa"] > 0]
print(
    f"  TIMING vs PASSIVE: winner={w} at {st}; ударов нанесено: {len(hits)};"
    f" тактов с открытым входом пассива: {len(opens)}"
)
if hits[:5]:
    for t in hits[:5]:
        print(
            f"    step {t['step']}: F_A={t['fa']:.0f} pool_A={t['ea']} "
            f"adopt_B={t['b_adopt']} open_B={t['b_open']}"
        )

print(
    "  Проверка чувствительности к наблюдаемости: PRESSER против пассива при"
)
print(
    "  BELIEF_NOISE=0 и =2 (исход результата детерминирован кроме p_success):"
)
for noise in (0, 2, 5):
    S.BELIEF_NOISE = noise
    res = []
    for sd in range(5):
        w, st, ha, hb, _ = duel(
            make_scripted("PRESSER"), make_scripted("PASSIVE"), 400, sd
        )
        res.append(w)
    print(f"    NOISE={noise}: исходы {res}")
S.BELIEF_NOISE = 2

print()
print("=" * 78)
print(
    "H3: РАННЯЯ СМЕРТЬ RL. Трассировка первых 30 шагов партии RL vs UtilityAI"
)
print(
    "     и сравнение: сквозное обучение vs eps=0 после pre-train vs с нуля."
)
print("=" * 78)
rl = S.RLAgent()
ai = S.UtilityAI()
rng = random.Random(0)
log = []
for step in range(30):
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
    a_idx = rl.form_intention(eps, rng)
    act_name, frac = S.ACTIONS[a_idx]
    st_before = rl.skey()
    f_before = rl.force
    w_rl = (
        0
        if rl.rest_if_starving()
        else rl.commit(act_name, rl.energy_pool * frac)
    )
    ai_act, ai_work = ai.form_intention()
    w_ai = 0 if ai.rest_if_starving() else ai.commit(ai_act, ai_work)
    S.resolve_attack(rl, ai, w_rl, rng)
    S.resolve_attack(ai, rl, w_ai, rng)
    rl.learn(st_before, a_idx, rl.force - f_before, rl.skey())
    log.append(
        (
            step,
            round(rl.force),
            rl.energy_pool,
            act_name,
            w_rl,
            round(ai.force),
            w_ai,
        )
    )
print("  step F_RL pool action work | F_AI w_ai")
for row in log[:30]:
    print("  ", row)


def run_mode(mode, n=10):
    rl = S.RLAgent()
    results = {"RL": 0, "UtilityAI": 0, None: 0}
    start_eps = {"full": None, "greedy": 0.0, "pretrain": None}[mode]
    for g in range(n):
        if mode == "pretrain":
            eps_fixed = 0.10 if g < 5 else 0.0
        elif mode == "greedy":
            eps_fixed = 0.0
        else:
            eps_fixed = None

        if eps_fixed is not None:
            orig = rl.form_intention
            rl.form_intention = lambda eps, rng, _o=orig, _e=eps_fixed: _o(
                _e, rng
            )
        w, _, _, st = S.play_game(rl, S.UtilityAI(), 1000, seed=g)
        if eps_fixed is not None:
            del rl.form_intention
        if mode != "pretrain" or g >= 5:
            results[w] += 1
    return results


for mode in ("full", "greedy", "pretrain"):
    r = run_mode(mode)
    print(
        f"  режим {mode:>8}: RL={r['RL']} AI={r['UtilityAI']} "
        f"no-capture={r[None]}"
    )
