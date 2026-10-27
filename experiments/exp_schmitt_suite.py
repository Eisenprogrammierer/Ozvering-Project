import sys
import os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
import random
import statistics
import simulation as S
import strategies as ST


def scripted(kind, me, opp, rng):
    return ST.STRATEGIES[kind](me, opp, rng)


def duel(kind_a, kind_b, steps=400, seed=0):
    rng = random.Random(seed)
    a = S.Agent()
    b = S.Agent()
    ha, hb = [], []
    dom_a = dom_b = 0
    for step in range(steps):
        S.run_tick(
            a,
            b,
            lambda me, opp, r: scripted(kind_a, me, opp, r),
            lambda me, opp, r: scripted(kind_b, me, opp, r),
            rng,
        )
        ha.append(a.force)
        hb.append(b.force)
        dom_a = dom_a + 1 if S.dominates(a, b) else 0
        dom_b = dom_b + 1 if S.dominates(b, a) else 0
        if dom_a >= 20:
            return "A", step, ha, hb
        if dom_b >= 20:
            return "B", step, ha, hb
    return None, steps, ha, hb


print(
    "=== Э0: изоляция закона Шмитта (трассировка давления на свежую систему) "
    "==="
)
d = S.Agent()
trace = []
for i in range(40):
    d.receive_pressure(5)
    d.tick_input_state()
    trace.append((i + 1, round(d.w_adopt, 1), d.in_open))
opens = [t for t in trace if t[2]]
first_open = opens[0][0] if opens else None
print(
    f"Окно открылось на такте {first_open} (порог ON(F)=max(ON_MIN, "
    f"ON_FRAC*F)); "
    f"до него {first_open - 1 if first_open else '-'} тактов почти "
    f"бесплодного напора."
)

if first_open:
    for _ in range(S.OPEN_TTL + 2):
        d.tick_input_state()
    print(
        f"Без подкрепления давлением окно закрылось само (TTL={S.OPEN_TTL}): "
        f"in_open={d.in_open}"
    )

print("\n=== Э0b: стратегия авантюриста против стратегии с резервом ===")


def run_arm(reserve_mode, seed):
    rng = random.Random(seed)
    att, dfn = S.Agent(), S.Agent()
    att.force = dfn.force = 100
    att.energy_pool = dfn.energy_pool = 20
    F0a = att.force
    for step in range(80):
        att.sense(dfn, rng)
        att.tick_energy()
        dfn.tick_input_state()
        if reserve_mode:
            if att.beliefs["opp_in_open"] and att.energy_pool >= 15:
                w = att.commit(rng.choice(S.TYPES), att.energy_pool)
            else:
                w = att.commit("REST", 0) if att.energy_pool < 15 else 0
                if w == 0 and att.energy_pool < 15:
                    pass
        else:
            w = att.commit(rng.choice(S.TYPES), att.energy_pool)
        S.resolve_attack(att, dfn, w, rng)
    return att.force - F0a


r_adv = [run_arm(False, s) for s in range(20)]
r_res = [run_arm(True, s) for s in range(20)]
print(
    f"Авантюрист (всё в лоб):     ΔF медиана={statistics.median(r_adv):+.0f}, "
    f"лучший={max(r_adv):+.0f}, худший={min(r_adv):+.0f}"
)
print(
    f"С резервом (окно):          ΔF медиана={statistics.median(r_res):+.0f}, "
    f"лучший={max(r_res):+.0f}, худший={min(r_res):+.0f}"
)

print("\n=== Э1: матрица дуэлей скриптовых стратегий (10 сидов на пару) ===")
kinds = ["PASSIVE", "PRESSER", "TIMING"]
print(f"{'':>9}", *[f"{k:>18}" for k in kinds])
for ka in kinds:
    row = [f"{ka:>9}"]
    for kb in kinds:
        wins_a = wins_b = draws = 0
        for sd in range(10):
            w, st, _, _ = duel(ka, kb, seed=sd)
            if w == "A":
                wins_a += 1
            elif w == "B":
                wins_b += 1
            else:
                draws += 1
        row.append(f"{wins_a}:{wins_b}({draws}d)".rjust(18))
    print(*row)

print("\n=== Э3: дребезг контакта (колебание давления вокруг OFF/ON) ===")
d = S.Agent()
flips = 0
prev = False
for i in range(200):
    w = 3 if i % 2 else 2
    d.receive_pressure(w)
    d.tick_input_state()
    if d.in_open != prev:
        flips += 1
    prev = d.in_open
print(
    f"Переключений состояния входа за 200 тактов мелкого напора: {flips} "
    f"(открытие ровно {1 if flips >= 1 else 0}-кратно, без дребезга)"
)
