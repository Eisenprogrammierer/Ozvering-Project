import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import simulation as S
import strategies as ST


def make_apply(W0):
    def _apply(att, dfn, work, att_type, rng, env=None):
        open_now = dfn.in_open
        dfn.receive_pressure(work)
        if env is not None:
            env.receive_pressure(work)
        if rng.random() < S.p_success(
            att_type, work, dfn.defense, dfn.last_work
        ):
            m = S.MULT.get((att_type, dfn.defense), 1.0)
            gain_frac = S.GAIN_MAX if open_now else S.Y_SMALL
            if env is not None and env.in_open:
                gain_frac *= 1.0 + S.ENV_BONUS
            gained = int(work * m * gain_frac)
            if gained:
                att.gain(gained)
                att.rest_units += gained
            dfn.process_hit(work)
            rec = max(0.0, work - (1.0 - S.K_EFFECT) * max(0.0, work - W0))
            dfn.force = max(1, dfn.force + int(rec))

    return _apply


DOM = 0.65
SYM = 0.30
N = 20
ACTIVE = ("PRESSER", "TIMING")


def check(f0):
    mtx = ST.duel_matrix(
        ["PASSIVE", "PRESSER", "TIMING"], n_seeds=N, steps=400, f0=f0
    )
    probs = []
    for a, b in (("PRESSER", "TIMING"), ("TIMING", "PRESSER")):
        r = mtx[(a, b)]["A"] / N
        if r >= DOM:
            probs.append(f"{a}>{b}={r:.2f}")
    for a, b in (("PASSIVE", "PRESSER"), ("PASSIVE", "TIMING")):
        r = mtx[(a, b)]["A"] / N
        if r >= DOM:
            probs.append(f"PASSIVE>{b}={r:.2f}")
    for a, b in (
        ("PRESSER", "TIMING"),
        ("PASSIVE", "PRESSER"),
        ("PASSIVE", "TIMING"),
    ):
        d = abs(mtx[(a, b)]["A"] - mtx[(b, a)]["B"])
        if d > SYM * N:
            probs.append(f"asym {a}/{b} Δ={d}")
    rates = tuple(
        mtx[(a, b)]["A"] / N
        for a, b in (("PRESSER", "TIMING"), ("TIMING", "PRESSER"))
    )
    return rates, probs


def batch(with_env):
    _, _, r = S.run_batch(8, quiet=True, with_env=with_env)
    return r


print("=== Пороговая отдача: полный критерий CI (N=20) + канон ===")
for W0 in (0, 2, 3, 4, 5, 6, 8):
    S.K_EFFECT = 0.70
    S._apply_transfer = make_apply(W0)
    r10, p10 = check(10)
    r30, p30 = check(30)
    b0 = batch(False)
    b1 = batch(True)
    ok = (not p10) and (not p30)
    print(
        f"W0={W0}: F0=10 P/T={r10[0]:.2f}/{r10[1]:.2f} probs={p10 or 'ok'} | "
        f"F0=30 P/T={r30[0]:.2f}/{r30[1]:.2f} probs={p30 or 'ok'} || "
        f"envF {b0['RL']}/{b0['UtilityAI']}/{b0[None]} envT "
        f"{b1['RL']}/{b1['UtilityAI']}/{b1[None]} => "
        f"CI={'0' if ok else '1'}"
    )
