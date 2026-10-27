import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import statistics
import simulation as S
import strategies as ST

ORIG = S._apply_transfer


def make_apply(recovery_fn):
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
            dfn.force = max(1, dfn.force + int(recovery_fn(work)))

    return _apply


def recovery_linear(w):
    return S.K_EFFECT * w


def recovery_thresh(W0):
    return lambda w: max(0.0, w - (1.0 - S.K_EFFECT) * max(0.0, w - W0))


def recovery_smooth(W0):
    return lambda w: w - (1.0 - S.K_EFFECT) * w * w / (w + W0)


def ci_pt(f0=10, N=10):
    mtx = ST.duel_matrix(
        ["PASSIVE", "PRESSER", "TIMING"], n_seeds=N, steps=400, f0=f0
    )
    return (
        mtx[("PRESSER", "TIMING")]["A"] / N,
        mtx[("TIMING", "PRESSER")]["A"] / N,
    )


def batch(with_env):
    _, _, res = S.run_batch(6, quiet=True, with_env=with_env)
    return res


configs = [
    ("baseline linear K=0.70", recovery_linear, 0.70),
    ("thresh W0=2 K=0.70", recovery_thresh(2), 0.70),
    ("thresh W0=4 K=0.70", recovery_thresh(4), 0.70),
    ("thresh W0=6 K=0.70", recovery_thresh(6), 0.70),
    ("smooth W0=4 K=0.70", recovery_smooth(4), 0.70),
    ("smooth W0=8 K=0.70", recovery_smooth(8), 0.70),
    ("thresh W0=4 K=0.90", recovery_thresh(4), 0.90),
]
print(
    f"{'config':<26} | F0=10 P>T T>P | env=False RL/AI/no | env=True RL/AI/no"
)
for name, fn, K in configs:
    S.K_EFFECT = K
    S._apply_transfer = make_apply(fn)
    pt, tp = ci_pt()
    b0 = batch(False)
    b1 = batch(True)
    print(
        f"{name:<26} | {pt:4.2f} {tp:4.2f} | "
        f"{b0['RL']}/{b0['UtilityAI']}/{b0[None]:<2}          | "
        f"{b1['RL']}/{b1['UtilityAI']}/{b1[None]}"
    )
S._apply_transfer = ORIG
S.K_EFFECT = 0.70
