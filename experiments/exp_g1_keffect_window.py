import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simulation as S
import strategies as ST

K_LEVELS = (0.4, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9, 1.0)
N_SEEDS = 12
STEPS = 400
F0 = 30
DOM_LIMIT = 0.65
SYM_TOL = 0.30
NAMES = list(ST.STRATEGIES)
ACTIVE = ST.COMPETITIVE
CONTROLS = ST.CONTROLS


def metrics(mtx, n_seeds):
    dom, dom_pair = 0.0, None
    for a in ACTIVE:
        for b in ACTIVE:
            if a == b:
                continue
            rate = mtx[(a, b)]["A"] / n_seeds
            if rate > dom:
                dom, dom_pair = rate, (a, b)
    ctrl, ctrl_pair, ctrl_n = 0.0, None, 0
    for c in CONTROLS:
        for a in ACTIVE:
            rate = mtx[(c, a)]["A"] / n_seeds
            if rate > ctrl:
                ctrl, ctrl_pair = rate, (c, a)
            if rate >= DOM_LIMIT:
                ctrl_n += 1
    asym, asym_pair = 0, None
    for i, a in enumerate(NAMES):
        for b in NAMES[i + 1 :]:
            d = abs(mtx[(a, b)]["A"] - mtx[(b, a)]["B"])
            if d > asym:
                asym, asym_pair = d, (a, b)
    draws = sum(mtx[p][None] for p in mtx)
    total = len(mtx) * n_seeds
    core_draws = sum(mtx[(a, b)][None] for a in ACTIVE for b in ACTIVE)
    core_total = len(ACTIVE) * len(ACTIVE) * n_seeds
    ok = dom < DOM_LIMIT and ctrl < DOM_LIMIT and asym <= SYM_TOL * n_seeds
    return dict(
        dom=dom,
        dom_pair=dom_pair,
        ctrl=ctrl,
        ctrl_pair=ctrl_pair,
        ctrl_n=ctrl_n,
        asym=asym,
        asym_pair=asym_pair,
        draws=draws,
        total=total,
        core_draws=core_draws,
        core_total=core_total,
        ok=ok,
    )


def one_k(k, n_seeds=N_SEEDS, steps=STEPS, f0=F0):
    saved = S.K_EFFECT
    S.K_EFFECT = k
    try:
        mtx = ST.duel_matrix(NAMES, n_seeds=n_seeds, steps=steps, f0=f0)
    finally:
        S.K_EFFECT = saved
    return metrics(mtx, n_seeds)


def sweep(label, n_seeds=N_SEEDS, steps=STEPS, f0=F0, ks=K_LEVELS):
    print(f"\n=== {label} (n_seeds={n_seeds}, steps={steps}, f0={f0}) ===")
    print(
        f"{'K':>5} | {'maxDom':>7} {'пара':>20} | {'ctrl':>6} {'наруш.':>6} | "
        f"{'ничьи':>7} {'ядро':>7} | {'асимм':>6} | CI"
    )
    rows = {}
    for k in ks:
        r = one_k(k, n_seeds=n_seeds, steps=steps, f0=f0)
        rows[k] = r
        pair = (
            f"{r['dom_pair'][0]}/{r['dom_pair'][1]}" if r["dom_pair"] else "-"
        )
        cp = (
            f"{r['ctrl_pair'][0]}/{r['ctrl_pair'][1]}"
            if r["ctrl_pair"]
            else "-"
        )
        print(
            f"{k:>5.2f} | {r['dom']:>7.2f} {pair:>20} | {r['ctrl']:>6.2f} "
            f"{r['ctrl_n']:>6} | {r['draws']:>3}/{r['total']:<3} "
            f"{r['core_draws']:>3}/{r['core_total']:<3} | "
            f"{r['asym']:>6} | {'OK' if r['ok'] else 'FAIL'}"
        )
    ok_k = [k for k, r in rows.items() if r["ok"]]
    print(f"  окно CI: K ∈ {{{', '.join(f'{k:.2f}' for k in ok_k)}}}")
    return rows


def canon_at_k07(label):
    saved = S.K_EFFECT
    S.K_EFFECT = 0.7
    try:
        res = S.run_batch(10, quiet=True)[2]
    finally:
        S.K_EFFECT = saved
    print(
        f"  канон run_batch(10) @K=0.70: RL {res['RL']} / UtilityAI "
        f"{res['UtilityAI']} / нет {res[None]}   [{label}]"
    )
    return res


def main():
    print("G1: окно баланса K_EFFECT на плато F0=30")
    print(
        f"канон K_EFFECT={S.K_EFFECT}, f0={F0}, n_seeds={N_SEEDS}, "
        f"steps={STEPS}"
    )
    base = sweep("БАЗА (core без правок)")
    canon_at_k07("база")

    base40 = sweep("БАЗА, контроль N=40", n_seeds=40)

    saved_off = S.OFF_FRAC
    saved_gain = S.GAIN_MAX

    v1 = None
    print(
        f"\n########## ВАРИАНТ: OFF_FRAC x0.8 (окно открыто дольше) ##########"
    )
    try:
        S.OFF_FRAC = saved_off * 0.8
        v1 = sweep("OFF_FRAC x0.8")
        canon_at_k07("OFF_FRAC x0.8")
    finally:
        S.OFF_FRAC = saved_off

    v2 = None
    print(
        f"\n########## ВАРИАНТ: GAIN_MAX x0.85 (слабее засадный удар) "
        f"##########"
    )
    try:
        S.GAIN_MAX = saved_gain * 0.85
        v2 = sweep("GAIN_MAX x0.85")
        canon_at_k07("GAIN_MAX x0.85")
    finally:
        S.GAIN_MAX = saved_gain

    print("\n########## ДОП. ПРОТОТИПЫ N=40 (верхняя граница окна) ##########")
    for lab, attr, mult in (
        ("OFF_FRAC x1.2", "OFF_FRAC", 1.2),
        ("GAIN_MAX x1.15", "GAIN_MAX", 1.15),
    ):
        old = getattr(S, attr)
        print(f"\n--- {lab} ---")
        try:
            setattr(S, attr, old * mult)
            sweep(lab, n_seeds=40, ks=(0.7, 0.8, 0.9, 1.0))
        finally:
            setattr(S, attr, old)

    print("\n=== ИТОГ G1 ===")
    for label, rows in (
        ("база N=12", base),
        ("OFF_FRACx0.8", v1),
        ("GAIN_MAXx0.85", v2),
        ("база N=40", base40),
    ):
        ok = [f"{k:.2f}" for k, r in rows.items() if r["ok"]]
        print(
            f"  {label:>16}: CI OK при K = {{ {', '.join(ok) if ok else '—'} "
            f"}}"
        )


if __name__ == "__main__":
    main()
