import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import statistics
import simulation as S
import strategies as ST

N = 12
STEPS = 400
NAMES = ("PASSIVE", "PRESSER", "TIMING")


def matrix_stats(f0):
    mtx = ST.duel_matrix(list(NAMES), n_seeds=N, steps=STEPS, f0=f0)
    pt = mtx[("PRESSER", "TIMING")]["A"] / N
    tp = mtx[("TIMING", "PRESSER")]["A"] / N
    solved = sum(
        mtx[(a, b)]["A"] + mtx[(a, b)]["B"] for a in NAMES for b in NAMES
    )
    total = N * len(NAMES) * len(NAMES)
    fl = (
        statistics.median(mtx[("PRESSER", "TIMING")]["df"])
        if mtx[("PRESSER", "TIMING")]["df"]
        else 0
    )
    return pt, tp, solved / total, fl


print("=== CI-матрица (скриптовые, env=None), сдвиг K_EFFECT ===")
print(f"{'K':>5} | F0=10 P>T T>P solved  medΔF(P-T) | F0=30 P>T T>P solved")
for K in [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 1.0]:
    S.K_EFFECT = K
    p10, t10, s10, f10 = matrix_stats(10)
    p30, t30, s30, _ = matrix_stats(30)
    print(
        f"{K:5.2f} | {p10:4.2f} {t10:4.2f} {s10:5.2f} {f10:+9.1f} | "
        f"{p30:4.2f} {t30:4.2f} {s30:5.2f}"
    )
S.K_EFFECT = 0.70

print("\n=== Канон run_batch (6 партий): solved по K_EFFECT ===")


def batch_counts(K, with_env):
    S.K_EFFECT = K
    _, _, res = S.run_batch(6, quiet=True, with_env=with_env)
    return res


print(f"{'K':>5} | with_env=True  (RL/AI/no)      | with_env=False (RL/AI/no)")
for K in [0.7, 0.85, 0.9, 0.95, 1.0]:
    a = batch_counts(K, True)
    b = batch_counts(K, False)
    print(
        f"{K:5.2f} | RL={a['RL']} AI={a['UtilityAI']} no={a[None]}           "
        f"| RL={b['RL']} AI={b['UtilityAI']} no={b[None]}"
    )
S.K_EFFECT = 0.70
