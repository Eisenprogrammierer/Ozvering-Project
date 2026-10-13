"""Проверка гипотезы H-A (и альтернатив) против диагноза «днового аттрактора».

Диагноз: среда имеет два аттрактора — ДНО (F<~12) и ПЛАТО (F>=30); переход
дно->плато заблокирован catch-22:
  (a) commit лимит w <= max(1, F//4) при малом F;
  (b) асимптота накопления входа w/(1-DECAY_ADOPT)=20w: при w<=2 предел = 40 = ON
      ровно — окно не открывается НИКОГДА;
  (c) rest_gain на дне ~ +0.02 net против upkeep -1 => покой убыточен внизу.

Конкурирующие гипотезы о ЛЕЧЕНИИ:
H-A: проблема в достижимости порога ON (калибровка DECAY_ADOPT/ON_THRESHOLD).
     Тест: сетка ON x DECAY, замер времени до первого окна при старте F=10.
H-B: проблема в кривой покоя (логистика убывает К нулю у ОБОИХ концов; вершина
     далеко от дна). Тест: чистый рост от отдыха с нуля при разных L_BASE/MAX_RD.
H-C: проблема в цене давления на дне (COST+RETALIATION+FATIGUE > любого выигрыша).
     Тест: изоляция знака обмена по слоям (без возмездия / без трения / все включено).

Методология: скриптованные политики (SAVER — копит отдыхом; PRESSER — давит;
TIMING — копит, бьёт в окно), дуэли и одиночная динамика, 5 сидов.
"""
import random, statistics
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
            if me.force >= 30 and me.energy_pool >= 8:
                return (rng.choice(S.TYPES), int(me.energy_pool * 0.6))
            return ("REST", 0)
        raise ValueError(kind)
    return policy


def step_env(a, b, pa, pb, rng):
    a.sense(b, rng); b.sense(a, rng)
    a.rotate_defense(rng); b.rotate_defense(rng)
    a.upkeep(); b.upkeep()
    a.tick_energy(); b.tick_energy()
    a.tick_input_state(); b.tick_input_state()
    act, w = pa(a, b, rng); wa = 0 if a.rest_if_starving() else a.commit(act, w)
    act, w = pb(b, a, rng); wb = 0 if b.rest_if_starving() else b.commit(act, w)
    S.resolve_attack(a, b, wa, rng)
    S.resolve_attack(b, a, wb, rng)


def duel(policy_a, policy_b, steps=400, seed=0, f0=10):
    rng = random.Random(seed)
    a, b = S.Agent(), S.Agent()
    a.force = f0; b.force = f0
    ha, hb = [], []
    dom_a = dom_b = 0
    for _ in range(steps):
        step_env(a, b, policy_a, policy_b, rng)
        ha.append(a.force); hb.append(b.force)
        dom_a = dom_a + 1 if (a.force >= 1.5*b.force and a.energy_pool >= 1.5*b.energy_pool) else 0
        dom_b = dom_b + 1 if (b.force >= 1.5*a.force and b.energy_pool >= 1.5*a.energy_pool) else 0
        if dom_a >= 20: return "A", _, ha, hb
        if dom_b >= 20: return "B", _, ha, hb
    return None, steps, ha, hb


print("="*78)
print("H-B: ЧИСТЫЙ РОСТ ОТДЫХОМ С ДНА (одиночный автомат, покой без боя)")
print("     = покой без боя). Сколько тактов нужно, чтобы подняться с F=10?")
print("="*78)
for lbase, mrd in ((60, 8), (60, 4), (120, 8)):
    S.L_BASE, S.MAX_REST_DELTA = lbase, mrd
    rng = random.Random(0)
    a = S.Agent(); a.force = 10
    times = []
    for target in (20, 30, 40):
        t_hit = None
        aa = S.Agent(); aa.force = 10
        for t in range(600):
            aa.upkeep(); aa.tick_energy(); aa.tick_input_state()
            aa.do_rest(chosen=True)
            if aa.force >= target and t_hit is None:
                t_hit = t
        times.append((target, t_hit))
    print(f"  L_BASE={lbase}, MAX_REST_DELTA={mrd}: " +
          " | ".join(f"F{tg}: {'не достигнута' if th is None else str(th)+' тактов'}" for tg, th in times))

print()
print("="*78)
print("H-A: ДОСТИЖИМОСТЬ ОКНА ПРИ СТАРТЕ С ДНА. Сетка ON x DECAY.")
print("     Одиночный PRESSER против пассива-мишени; фиксируем первый такт,")
print("     когда вход мишени открылся, старт F=10 у обоих.")
print("="*78)
base_on, base_off, base_decay = S.ON_THRESHOLD, S.OFF_THRESHOLD, S.DECAY_ADOPT
for decay in (0.95, 0.90, 0.80):
    for on in (40.0, 25.0, 15.0):
        S.DECAY_ADOPT = decay; S.ON_THRESHOLD = on; S.OFF_THRESHOLD = on*0.4
        res = []
        for sd in range(3):
            rng = random.Random(sd)
            a, b = S.Agent(), S.Agent(); a.force = b.force = 10
            first_open = None
            p_press = make_scripted("PRESSER"); p_pass = make_scripted("PASSIVE")
            for t in range(400):
                step_env(a, b, p_press, p_pass, rng)
                if b.in_open and first_open is None:
                    first_open = t
            res.append(first_open)
        print(f"  DECAY={decay}, ON={on}: первые окна {res}")
S.ON_THRESHOLD, S.OFF_THRESHOLD, S.DECAY_ADOPT = base_on, base_off, base_decay

print()
print("="*78)
print("H-C: ЗНАК ОБМЕНА ПО СЛОЯМ (давление по закрытому входу, w=2..5, F=10).")
print("="*78)
for label, ret_f, ke, hock in (("полный закон", 0.5, 0.70, 0.25),
                               ("без возмездия", 0.0, 0.70, 0.25),
                               ("без трения(K=1)", 0.5, 1.0, 0.25),
                               ("без шока пула", 0.5, 0.70, 0.0)):
    S.RETALIATE_FRACTION, S.K_EFFECT, S.HOCK_FRACTION = ret_f, ke, hock
    nets = []
    for w in (2, 3, 5):
        rng = random.Random(1)
        a, b = S.Agent(), S.Agent(); a.force = b.force = 10
        d = []
        for i in range(50):
            f0 = a.force
            step_env(a, b, lambda me,op,r: ("WATER", w), lambda me,op,r: ("REST",0), rng)
            d.append(a.force - f0)
        nets.append((w, statistics.mean(d)))
    print(f"  {label:>14}: ΔF за удар по закрытому входу " +
          " | ".join(f"w={w}:{v:+.2f}" for w, v in nets))
S.RETALIATE_FRACTION, S.K_EFFECT, S.HOCK_FRACTION = 0.5, 0.70, 0.25

print()
print("="*78)
print("БАЗОВЫЕ ДУЭЛИ НА ТЕКУЩЕЙ КАЛИБРОВКЕ (старт F=10 и F=30, 5 сидов)")
print("="*78)
P = {k: make_scripted(k) for k in ("PASSIVE","PRESSER","TIMING")}
for f0 in (10, 30):
    for ka, kb in (("TIMING","PASSIVE"), ("PRESSER","PASSIVE"), ("TIMING","PRESSER")):
        tally = {"A":0,"B":0,None:0}; med = []
        for sd in range(5):
            w, st, ha, hb = duel(P[ka], P[kb], 400, sd, f0=f0)
            tally[w] += 1; med.append(ha[-1]-hb[-1])
        print(f"  F0={f0} {ka:>7} vs {kb:<7}: A={tally['A']} B={tally['B']} ничья={tally[None]}"
              f" | медиана ΔF={statistics.median(med):+.0f}")
