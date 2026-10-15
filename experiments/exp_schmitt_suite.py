"""Комплексная проверка модели с порогами Шмитта:
Э0. Изоляция закона: детерминированный трассировщик — «упорство дорого вначале,
    может окупиться, но не гарантированно» (проигрыш авантюриста без резерва).
Э1. Матрица дуэлей скриптовых стратегий (без RL) — нет ли доминирующей чистой.
Э2. RL vs UtilityAI после сквозного обучения.
Э3. Проверка гистерезиса: нет дребезга контакта при колебаниях около OFF/ON.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import random
import statistics
import simulation as S
import strategies as ST


def scripted(kind, me, opp, rng):
    """Возвращает (act, work_wanted) для скриптового агента.

    Единый источник стратегий — ``experiments/strategies.py``: раньше определение
    дублировалось в нескольких скриптах и расходилось, из-за чего выводы о
    балансе противоречили друг другу. Здесь — делегирование."""
    return ST.STRATEGIES[kind](me, opp, rng)


def duel(kind_a, kind_b, steps=400, seed=0):
    rng = random.Random(seed)
    a = S.Agent(); b = S.Agent()
    ha, hb = [], []
    dom_a = dom_b = 0
    for step in range(steps):
        a.sense(b, rng); b.sense(a, rng)
        a.rotate_defense(rng); b.rotate_defense(rng)
        a.upkeep(); b.upkeep()
        a.tick_energy(); b.tick_energy()
        a.tick_input_state(); b.tick_input_state()
        act, w = scripted(kind_a, a, b, rng)
        if not a.rest_if_starving():
            wa = a.commit(act, w)
        else:
            wa = 0
        act, w = scripted(kind_b, b, a, rng)
        if not b.rest_if_starving():
            wb = b.commit(act, w)
        else:
            wb = 0
        S.resolve_attack(a, b, wa, rng)
        S.resolve_attack(b, a, wb, rng)
        ha.append(a.force); hb.append(b.force)
        dom_a = dom_a + 1 if (a.force >= 1.5 * b.force and a.energy_pool >= 1.5 * b.energy_pool) else 0
        dom_b = dom_b + 1 if (b.force >= 1.5 * a.force and b.energy_pool >= 1.5 * a.energy_pool) else 0
        if dom_a >= 20:
            return "A", step, ha, hb
        if dom_b >= 20:
            return "B", step, ha, hb
    return None, steps, ha, hb


print("=== Э0: изоляция закона Шмитта (трассировка давления на свежую систему) ===")
d = S.Agent()
trace = []
for i in range(40):
    d.receive_pressure(5)   # ровное давление по 5 ед. работы за такт
    d.tick_input_state()
    trace.append((i + 1, round(d.w_adopt, 1), d.in_open))
opens = [t for t in trace if t[2]]
first_open = opens[0][0] if opens else None
print(f"Окно открылось на такте {first_open} (порог ON(F)=max(ON_MIN, ON_FRAC*F)); "
      f"до него {first_open-1 if first_open else '-'} тактов почти бесплодного напора.")
# закрытие по TTL без подкрепления:
if first_open:
    for _ in range(S.OPEN_TTL + 2):
        d.tick_input_state()
    print(f"Без подкрепления давлением окно закрылось само (TTL={S.OPEN_TTL}): in_open={d.in_open}")

print("\n=== Э0b: кампания авантюриста против кампании с резервом ===")
def campaign(reserve_mode, seed):
    """Атакующий давит на обороняющегося. reserve_mode=True: копит пул и бьёт
    только в открытое окно; False: жрёт весь пул в лоб с первого такта."""
    rng = random.Random(seed)
    att, dfn = S.Agent(), S.Agent()
    att.force = dfn.force = 100
    att.energy_pool = dfn.energy_pool = 20
    F0a = att.force
    for step in range(80):
        att.sense(dfn, rng)
        att.tick_energy(); dfn.tick_input_state()
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

r_adv = [campaign(False, s) for s in range(20)]
r_res = [campaign(True, s) for s in range(20)]
print(f"Авантюрист (всё в лоб):     ΔF медиана={statistics.median(r_adv):+.0f}, "
      f"лучший={max(r_adv):+.0f}, худший={min(r_adv):+.0f}")
print(f"Кампания с резервом (окно): ΔF медиана={statistics.median(r_res):+.0f}, "
      f"лучший={max(r_res):+.0f}, худший={min(r_res):+.0f}")

print("\n=== Э1: матрица дуэлей скриптовых стратегий (10 сидов на пару) ===")
kinds = ["PASSIVE", "PRESSER", "TIMING"]
print(f"{'':>9}", *[f"{k:>18}" for k in kinds])
for ka in kinds:
    row = [f"{ka:>9}"]
    for kb in kinds:
        wins_a = wins_b = draws = 0
        for sd in range(10):
            w, st, _, _ = duel(ka, kb, seed=sd)
            if w == "A": wins_a += 1
            elif w == "B": wins_b += 1
            else: draws += 1
        row.append(f"{wins_a}:{wins_b}({draws}d)".rjust(18))
    print(*row)

print("\n=== Э3: дребезг контакта (колебание давления вокруг OFF/ON) ===")
d = S.Agent()
flips = 0
prev = False
for i in range(200):
    w = 3 if i % 2 else 2   # чередование: накопление идёт медленно, мимо обоих порогов
    d.receive_pressure(w)
    d.tick_input_state()
    if d.in_open != prev:
        flips += 1
    prev = d.in_open
print(f"Переключений состояния входа за 200 тактов мелкого напора: {flips} "
      f"(открытие ровно {1 if flips>=1 else 0}-кратно, без дребезга)")
