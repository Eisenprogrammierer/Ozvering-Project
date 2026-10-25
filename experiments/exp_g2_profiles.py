"""G2: балансовая пригодность профилей p<1 (docs/TODO.md, ревью A4.2).

Что меряется (core не меняется; monkeypatch только на время прогона):

  * 7 профильных пар (RL-сторона, UtilityAI-сторона), по 20 партий
    (seed 0..19, steps=1000, with_env=True, сквозное обучение RL в серии);
  * доля захватов (партия решилась), распределение победителей, медианный
    end_step (по всем партиям и только по решённым);
  * 3 компенсации профильного канала входа:
      A. OFF_FRAC/p -> OFF_FRAC*sqrt(p)     (нижний порог ниже, окно живёт дольше)
      B. DECAY_ADOPT*p -> DECAY_ADOPT*(0.5+0.5p)  (остывание медленнее)
      C. A+B одновременно;
  * диагностика механизма:
      D. DECAY_ADOPT*p -> DECAY_ADOPT (профиль остаётся только в OFF/p);
      E. p полностью нейтрализован (оба канала = канон);
      F. сильная компенсация DECAY_ADOPT*(0.85+0.15p) — подобрана по порогу
         восстановления self-play (см. ниже);
  * контроль канона при p=1 (run_batch(10)) — компенсации не должны менять
    канонический баланс.

Почему это «компенсации»: при p<1 канон делает вход ДОГМАТИЧНЕЕ сразу по двум
каналам — быстрее остывание (DECAY*p) и выше нижний порог ((OFF_FRAC/p)·ON).
Оба затрудняют открытие окна, отсюда ничьи. Компенсации ослабляют ровно это
искажение, оставляя p=1 каноническим (обе формулы в p=1 дают исходные значения).

Запуск из корня репозитория:
    python3 experiments/exp_g2_profiles.py
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulation as S

N_GAMES = 20
STEPS = 1000
PAIRS = (
    ("CANON", "CANON"),
    ("ZEALOT", "ZEALOT"),
    ("ORTHODOX", "ORTHODOX"),
    ("ZEALOT", "CANON"),
    ("CANON", "ZEALOT"),
    ("ORTHODOX", "CANON"),
    ("CANON", "ORTHODOX"),
)


def run_pair(pair):
    """Серия из N_GAMES партий; Q переносится, физика сбрасывается play_game."""
    rl = S.RLAgent()
    wins = {"RL": 0, "UtilityAI": 0, None: 0}
    ends, ends_cap = [], []
    for seed in range(N_GAMES):
        winner, _, _, end = S.play_game(
            rl, S.UtilityAI(), STEPS, seed=seed, profiles=pair, with_env=True)
        wins[winner] += 1
        ends.append(end)
        if winner is not None:
            ends_cap.append(end)
    return wins, ends, ends_cap


def table(label):
    print(f"\n=== {label} (N={N_GAMES}, steps={STEPS}) ===")
    print(f"{'пара (RL / AI)':>26} | {'захват':>7} | {'RL':>3} {'AI':>3} {'нет':>3} "
          f"| {'med end':>8} {'med cap':>8} | {'RL%':>5}")
    rows = {}
    for pair in PAIRS:
        wins, ends, caps = run_pair(pair)
        cap = N_GAMES - wins[None]
        rows[pair] = dict(wins=wins, ends=ends, caps=caps)
        print(f"{pair[0] + ' / ' + pair[1]:>26} | "
              f"{cap:>3}/{N_GAMES:<2} {cap/N_GAMES:>5.0%} | "
              f"{wins['RL']:>3} {wins['UtilityAI']:>3} {wins[None]:>3} | "
              f"{statistics.median(ends):>8.0f} "
              f"{(statistics.median(caps) if caps else float('nan')):>8.0f} | "
              f"{wins['RL']/N_GAMES:>5.0%}")
    return rows


def _patched_tick(off_expr):
    """Копия Agent.tick_input_state с подменённым нижним порогом OFF(F)."""
    def tick_input_state(self):
        self.w_adopt *= self.effective_decay()
        if self.in_open:
            self.open_timer -= 1
            off_now = off_expr(self.p) * self.schmitt_on()
            if self.open_timer <= 0 or self.w_adopt < off_now:
                self.in_open = False
    return tick_input_state


def _patched_decay(self):
    """DECAY_ADOPT*p -> DECAY_ADOPT*(0.5+0.5p); при p=1 канон."""
    return S.DECAY_ADOPT * (0.5 + 0.5 * self.p)


def _off_canon(p):
    return S.OFF_FRAC / p


def _off_neutral(p):
    """p вообще не влияет на OFF: диагностическая верхняя граница."""
    return S.OFF_FRAC


def _off_sqrt(p):
    import math
    return S.OFF_FRAC * math.sqrt(p)


def _decay_canon(self):
    """DECAY_ADOPT*p -> DECAY_ADOPT: p вообще не влияет на остывание."""
    return S.DECAY_ADOPT


def _decay_strong(self):
    """DECAY_ADOPT*p -> DECAY_ADOPT*(0.85+0.15p).

    Коэффициент 0.85 — эмпирический порог: при нём self-play ZEALOT/ZEALOT
    перестаёт схлопываться в F=1 (см. секцию F отчёта). При p=1 — канон.
    """
    return S.DECAY_ADOPT * (0.85 + 0.15 * self.p)


def canon_check(label):
    res = S.run_batch(10, quiet=True)[2]
    print(f"  канон run_batch(10) [{label}]: RL {res['RL']} / UtilityAI "
          f"{res['UtilityAI']} / нет {res[None]}")


def compensation(label, decay_fn=None, off_fn=None):
    print(f"\n########## КОМПЕНСАЦИЯ: {label} ##########")
    saved_decay = S.Agent.effective_decay
    saved_tick = S.Agent.tick_input_state
    try:
        if decay_fn is not None:
            S.Agent.effective_decay = decay_fn
        if off_fn is not None:
            S.Agent.tick_input_state = _patched_tick(off_fn)
        rows = table(label)
        canon_check(label)
        return rows
    finally:
        S.Agent.effective_decay = saved_decay
        S.Agent.tick_input_state = saved_tick


def summarize(label, base, rows):
    print(f"\n--- Сводка: {label} ---")
    print(f"{'пара':>26} | {'захват база':>10} {'комп.':>7} {'Δ':>4} | "
          f"{'ничьи база':>9} {'комп.':>5}")
    for pair in PAIRS:
        b, r = base[pair], rows[pair]
        bc = N_GAMES - b["wins"][None]
        rc = N_GAMES - r["wins"][None]
        print(f"{pair[0] + ' / ' + pair[1]:>26} | {bc:>10} {rc:>7} "
              f"{rc - bc:>+4} | {b['wins'][None]:>9} {r['wins'][None]:>5}")


def main():
    print("G2: профили p<1 — доля захватов, исходы, медианный end_step")
    print(f"N_GAMES={N_GAMES}, steps={STEPS}, профили: "
          f"{S.PROFILES}")
    base = table("БАЗА (каноническая профильная обработка)")

    comps = {}
    comps["OFF_sqrt"] = compensation(
        "A: OFF_FRAC/p -> OFF_FRAC*sqrt(p)",
        off_fn=_off_sqrt)
    comps["DECAY_mix"] = compensation(
        "B: DECAY_ADOPT*p -> DECAY_ADOPT*(0.5+0.5p)",
        decay_fn=_patched_decay)
    comps["BOTH"] = compensation(
        "C: A+B одновременно",
        decay_fn=_patched_decay, off_fn=_off_sqrt)

    # D/E — диагностика механизма: какой канал профиля вообще активен.
    comps["DECAY_canon"] = compensation(
        "D: DECAY_ADOPT*p -> DECAY_ADOPT (профиль только через OFF/p)",
        decay_fn=_decay_canon, off_fn=_off_canon)
    comps["NEUTRAL"] = compensation(
        "E: p полностью нейтрализован (оба канала = канон)",
        decay_fn=_decay_canon, off_fn=_off_neutral)
    comps["DECAY_strong"] = compensation(
        "F: DECAY_ADOPT*p -> DECAY_ADOPT*(0.85+0.15p)",
        decay_fn=_decay_strong, off_fn=_off_canon)

    for label, rows in comps.items():
        summarize(label, base, rows)

    print("\n=== ИТОГ G2 ===")
    for pair in PAIRS:
        b = base[pair]
        print(f"  {pair[0] + '/' + pair[1]:>18}: захват "
              f"{N_GAMES - b['wins'][None]}/{N_GAMES}, "
              f"RL/AI/нет = {b['wins']['RL']}/{b['wins']['UtilityAI']}/"
              f"{b['wins'][None]}, med end="
              f"{statistics.median(b['ends']):.0f}"
              + (f", med cap={statistics.median(b['caps']):.0f}"
                 if b["caps"] else ""))


if __name__ == "__main__":
    main()
