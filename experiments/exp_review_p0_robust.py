# Ревью P0: устойчивость порогового фикса W0 на расширенной выборке (N=30).
# Запуск из корня: python3 experiments/exp_review_p0_robust.py

import os, sys
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import simulation as S
import strategies as ST

def make_apply(W0):
    def _apply(att, dfn, work, att_type, rng, env=None):
        open_now=dfn.in_open
        dfn.receive_pressure(work)
        if env is not None: env.receive_pressure(work)
        if rng.random() < S.p_success(att_type, work, dfn.defense, dfn.last_work):
            m=S.MULT.get((att_type, dfn.defense),1.0)
            gf=S.GAIN_MAX if open_now else S.Y_SMALL
            if env is not None and env.in_open: gf*=(1.0+S.ENV_BONUS)
            g=int(work*m*gf)
            if g: att.gain(g); att.rest_units+=g
            dfn.process_hit(work)
            dfn.force=max(1, dfn.force+int(max(0.0, work-(1.0-S.K_EFFECT)*max(0.0, work-W0))))
    return _apply

N=30
for W0 in (4,5,6):
    S.K_EFFECT=0.70; S._apply_transfer=make_apply(W0)
    row=[]
    for f0 in (10,30):
        mtx=ST.duel_matrix(["PASSIVE","PRESSER","TIMING"], n_seeds=N, steps=400, f0=f0)
        pt=mtx[("PRESSER","TIMING")]["A"]/N; tp=mtx[("TIMING","PRESSER")]["A"]/N
        sym=abs(mtx[("PRESSER","TIMING")]["A"]-mtx[("TIMING","PRESSER")]["B"])
        row.append((f0,pt,tp,sym))
    print(f"W0={W0}: " + " | ".join(f"F0={f0} P>T={pt:.2f} T>P={tp:.2f} symΔ={sym}" for f0,pt,tp,sym in row)
          + f"  => CI={'0' if all(pt<0.65 and tp<0.65 and sym<=0.3*N for _,pt,tp,sym in row) else '1'}")
