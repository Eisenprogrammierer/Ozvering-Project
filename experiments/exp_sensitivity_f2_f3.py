#!/usr/bin/env python3
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

import simulation as S
import strategies as ST
import lod

N_GAMES = 10
CANON = {"RL": 1, "UtilityAI": 9, None: 0}
T0 = time.time()


class ParamPatch:

    def __init__(self, **overrides):
        self.overrides = overrides
        self.saved = {}

    def __enter__(self):
        for name, value in self.overrides.items():
            self.saved[name] = getattr(S, name)
            setattr(S, name, value)
        return self

    def __exit__(self, exc_type, exc, tb):
        for name, value in self.saved.items():
            setattr(S, name, value)
        return False


def batch(entropy=False, lossy=False, **overrides):
    with ParamPatch(**overrides):
        return S.run_batch(N_GAMES, quiet=True, entropy=entropy, lossy=lossy)[
            2
        ]


def fmt(res):
    return f"{res['RL']}/{res['UtilityAI']}/{res[None]}"


def dist(res):
    return (
        abs(res["RL"] - CANON["RL"])
        + abs(res["UtilityAI"] - CANON["UtilityAI"])
        + abs(res[None] - CANON[None])
    )


def balance(n_seeds=10, steps=400, f0=10):
    names = list(ST.STRATEGIES)
    mtx = ST.duel_matrix(names, n_seeds=n_seeds, steps=steps, f0=f0)
    comp_pairs = [
        (a, b) for a in ST.COMPETITIVE for b in ST.COMPETITIVE if a != b
    ]
    all_pairs = [(a, b) for a in names for b in names]
    best = max(comp_pairs, key=lambda p: mtx[p]["A"])
    return {
        "max_dom": mtx[best]["A"] / n_seeds,
        "best_pair": best,
        "draws_all": sum(mtx[p][None] for p in all_pairs)
        / (len(all_pairs) * n_seeds),
        "draws_comp": sum(mtx[p][None] for p in comp_pairs)
        / (len(comp_pairs) * n_seeds),
        "mtx": mtx,
    }


def hdr(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def section_f2():
    hdr("F2. BELIEF_NOISE: run_batch(10) + малая матрица баланса")
    vals = [0, 1, 2, 4, 8]
    rows = []
    for v in vals:
        res = batch(BELIEF_NOISE=v)
        rows.append((v, res))
        print(
            f"  BELIEF_NOISE={v:<2} -> RL/UtilityAI/None = {fmt(res):<8} "
            f"dist={dist(res)}"
        )

    print("\n  -- малая матрица баланса (5 стратегий, 10 seed, 400 тактов) --")
    print(
        f"  {'BELIEF_NOISE':<13}{'F0':<5}{'max_dom(comp)':<15}"
        f"{'пара':<20}{'draws_all':<11}{'draws_comp'}"
    )

    for v in (1, 2, 8):
        with ParamPatch(BELIEF_NOISE=v):
            for f0 in (10, 30):
                b = balance(n_seeds=10, steps=400, f0=f0)
                pa, pb = b["best_pair"]
                print(
                    f"  {v:<13}{f0:<5}{b['max_dom']:<15.2f}"
                    f"{pa + '/' + pb:<20}{b['draws_all']:<11.2f}"
                    f"{b['draws_comp']:.2f}"
                )
    return rows


GRIDS_F3 = [
    ("E_MAX_MULT", [2, 3, 4]),
    ("MAX_WORK", [100, 200, 400]),
    ("MIN_OUTPUT", [1, 2, 4]),
    ("L_BASE", [40, 60, 80]),
    ("L_STEP", [5, 10, 20]),
    ("ENV_REST_CAP", [5, 10, 20]),
    ("ENV_INCOME", [1, 2, 3]),
]


def section_f3():
    hdr("F3. Константы пула/покоя/среды: по одной за раз, run_batch(10)")
    results = {}
    print(
        f"  {'константа':<15}{'значение':<10}{'RL/UtilityAI/None':<20}{'dist'}"
    )
    for name, vals in GRIDS_F3:
        for v in vals:
            res = batch(**{name: v})
            results[(name, v)] = res
            print(f"  {name:<15}{str(v):<10}{fmt(res):<20}{dist(res)}")
        print()

    ranked = []
    for (name, v), res in results.items():
        default = S.PARAMETERS[name]
        if v == default:
            continue
        ranked.append((dist(res), abs(v - default), name, v))
    ranked.sort(key=lambda t: (-t[0], t[1], t[2], t[3]))
    picked, seen = [], set()
    for d, _, name, v in ranked:
        if d <= 0 or name in seen:
            continue
        picked.append((name, v, d))
        seen.add(name)
        if len(picked) == 3:
            break
    if len(picked) < 2:
        for name, vals in GRIDS_F3:
            if name not in seen:
                v = max(vals, key=lambda x: abs(x - S.PARAMETERS[name]))
                picked.append((name, v, 0))
                seen.add(name)
            if len(picked) >= 2:
                break

    print(
        "  -- матрица баланса F0=30 (10 seed, 400 тактов) для самых "
        "чувствительных значений --"
    )
    print(
        f"  {'константа':<15}{'значение':<10}{'RL/UtilityAI/None':<20}"
        f"{'max_dom(comp)':<15}{'pair':<20}{'draws_all':<11}{'draws_comp'}"
    )
    for name, v, _ in picked:
        with ParamPatch(**{name: v}):
            b = balance(n_seeds=10, steps=400, f0=30)
        pa, pb = b["best_pair"]
        res = results[(name, v)]
        print(
            f"  {name:<15}{str(v):<10}{fmt(res):<20}"
            f"{b['max_dom']:<15.2f}{pa + '/' + pb:<20}"
            f"{b['draws_all']:<11.2f}{b['draws_comp']:.2f}"
        )
    print(
        f"\n  выбраны (dist до канона): "
        + ", ".join(f"{n}={v} (d={d})" for n, v, d in picked)
    )
    return results, picked


def section_c1():
    hdr("C1. ENTROPY_SIGMA (entropy=True), run_batch(10)")
    sig_rows = []
    print(f"  {'ENTROPY_SIGMA':<15}{'RL/UtilityAI/None':<20}{'dist'}")
    for v in (0.05, 0.10, 0.15, 0.25, 0.40):
        res = batch(entropy=True, ENTROPY_SIGMA=v)
        sig_rows.append((v, res))
        print(f"  {v:<15.2f}{fmt(res):<20}{dist(res)}")

    hdr("C1. OBS_RESOLUTION (lossy=True), run_batch(10)")
    res_rows = []
    print(f"  {'OBS_RESOLUTION':<15}{'RL/UtilityAI/None':<20}{'dist'}")
    for v in (1, 2, 4):
        res = batch(lossy=True, OBS_RESOLUTION=v)
        res_rows.append((v, res))
        print(f"  {v:<15}{fmt(res):<20}{dist(res)}")

    hdr("C1. OBS_DELAY (lossy=True), run_batch(10)")
    delay_rows = []
    print(f"  {'OBS_DELAY':<15}{'RL/UtilityAI/None':<20}{'dist'}")
    for v in (0, 1, 2):
        res = batch(lossy=True, OBS_DELAY=v)
        delay_rows.append((v, res))
        print(f"  {v:<15}{fmt(res):<20}{dist(res)}")

    def ranked(rows, default):
        return [
            v
            for v, _ in sorted(
                rows, key=lambda t: (dist(t[1]), abs(t[0] - default), t[0])
            )
        ]

    sig_rank = ranked(sig_rows, S.PARAMETERS["ENTROPY_SIGMA"])
    res_rank = ranked(res_rows, S.PARAMETERS["OBS_RESOLUTION"])
    delay_rank = ranked(delay_rows, S.PARAMETERS["OBS_DELAY"])
    bs, br, bd = sig_rank[0], res_rank[0], delay_rank[0]
    print(
        f"\n  лучшие по сохранению канона и близости к default: "
        f"ENTROPY_SIGMA={bs}, OBS_RESOLUTION={br}, OBS_DELAY={bd}"
    )

    hdr("C1. Совместный режим entropy=True + lossy=True (3-4 комбинации)")

    combos = [(bs, br, bd)]
    for alt in [
        (sig_rank[1], br, bd) if len(sig_rank) > 1 else None,
        (bs, res_rank[1], bd) if len(res_rank) > 1 else None,
        (bs, br, delay_rank[1]) if len(delay_rank) > 1 else None,
    ]:
        if alt is not None and alt not in combos:
            combos.append(alt)
    combos = combos[:4]
    joint_rows = []
    print(
        f"  {'sigma':<8}{'resolution':<12}{'delay':<8}"
        f"{'RL/UtilityAI/None':<20}{'dist'}"
    )
    for s, r, d in combos:
        res = batch(
            entropy=True,
            lossy=True,
            ENTROPY_SIGMA=s,
            OBS_RESOLUTION=r,
            OBS_DELAY=d,
        )
        joint_rows.append(((s, r, d), res))
        print(f"  {s:<8.2f}{r:<12}{d:<8}{fmt(res):<20}{dist(res)}")

    hdr("C1. Воспроизводимость по seed (повтор прогона)")
    for label, kw in [
        ("канон", {}),
        ("entropy default", {"entropy": True}),
        ("lossy default", {"lossy": True}),
    ]:
        a = batch(**kw)
        b = batch(**kw)
        print(f"  {label:<18} {fmt(a):<10} == {fmt(b):<10} -> {a == b}")
    return sig_rows, res_rows, delay_rows, joint_rows


def section_lod():
    hdr(
        "C1. LOD_WORK_THRESHOLD: smoke lod.run_duel_lod (200 тактов, "
        "REST/REST)"
    )

    def rest(me, opp, rng):
        return ("REST", 0)

    class AlwaysLod1(lod.LodController):
        def level(self, *agents):
            return lod.LOD1

    class AlwaysLod2(lod.LodController):
        def level(self, *agents):
            return lod.LOD2

    def run(controller, seed=0):
        a, b = S.Agent(), S.Agent()
        rng = random.Random(seed)
        ha, hb, levels = lod.run_duel_lod(
            a, b, rest, rest, rng, None, 200, controller
        )
        counts = {1: levels.count(1), 2: levels.count(2), 3: levels.count(3)}
        return a, b, ha, hb, counts

    ref_a, ref_b, ref_ha, ref_hb, ref_counts = run(AlwaysLod1())
    print(
        f"  LOD-1 reference: force={ref_a.force:.3f}/{ref_b.force:.3f} "
        f"pool={ref_a.energy_pool:.3f}/{ref_b.energy_pool:.3f} "
        f"iterations={ref_counts}"
    )
    print(
        f"  {'threshold':<12}{'force A/B':<24}{'pool A/B':<24}"
        f"{'итерации L1/L2/L3':<20}{'Δforce vs LOD-1'}"
    )
    signatures = []
    for th in (10, 20, 40):
        with ParamPatch(LOD_WORK_THRESHOLD=th):
            a, b, ha, hb, counts = run(AlwaysLod2(), seed=0)
        df = max(abs(a.force - ref_a.force), abs(b.force - ref_b.force))
        signatures.append(
            (a.force, a.energy_pool, tuple(counts[i] for i in (1, 2, 3)))
        )
        print(
            f"  {th:<12}{a.force:.3f}/{b.force:.3f}          "
            f"{a.energy_pool:.3f}/{b.energy_pool:.3f}          "
            f"{counts[1]}/{counts[2]}/{counts[3]:<12}{df:.6f}"
        )
    inert = len(set(signatures)) == 1
    print(
        f"\n  Вывод: LOD_WORK_THRESHOLD {'ИНЕРТЕН' if inert else 'влияет'} "
        f"на LOD-2-интервал (AlwaysLod2): порог задаёт длину интервала по "
        f"работе, а не по времени. В дефолтном контроллере этот smoke почти "
        f"весь уходит в LOD-1/LOD-3, поэтому там порог не проявляется."
    )


def main():
    section_f2()
    section_f3()
    section_c1()
    section_lod()
    print(
        f"\nГотово за {time.time() - T0:.1f} с. Канон восстановлен: "
        f"BELIEF_NOISE={S.BELIEF_NOISE}, ENTROPY_SIGMA={S.ENTROPY_SIGMA}, "
        f"OBS_RESOLUTION={S.OBS_RESOLUTION}, OBS_DELAY={S.OBS_DELAY}, "
        f"LOD_WORK_THRESHOLD={S.LOD_WORK_THRESHOLD}"
    )
    import json

    print(
        "PARAMETERS-снимок: "
        + json.dumps(
            {
                k: S.PARAMETERS[k]
                for k in (
                    "E_MAX_MULT",
                    "MAX_WORK",
                    "MIN_OUTPUT",
                    "L_BASE",
                    "L_STEP",
                    "ENV_REST_CAP",
                    "ENV_INCOME",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
