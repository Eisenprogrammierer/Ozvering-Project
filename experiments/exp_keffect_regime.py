"""P0 №2: режим `K_EFFECT` — переизмерение «ножа-лезвия» после P0 №1.

Задача docs/TODO.md: вернуться к ножу-лезвию после того, как баланс/наблюдаемость
переопределены (P0 №1), и переизмерить его под снова симметричным каноном.

Что измеряем и что находим:

  1. ИСХОДНЫЙ СИМПТОМ (контроль без среды стагнирует: `F→1`, партии не решаются)
     под текущей архитектурой НЕ воспроизводится — ни для какого `K_EFFECT>0`.
     Контроль решается на всём диапазоне `K∈[0.4,1.0]`; проигравший действительно
     прижат ко дну (`F≈3–11`), но партия ЗАВЕРШАЕТСЯ (захват). Ничьи в скриптовой
     матрице — структурные (обе стороны в покое: TIMING/PASSIVE и т.п.), а не
     «истощение в ничью».

  2. КАНОН (`run_batch`) держит УСТОЙЧИВЫЙ СРЕДНИЙ РЕЖИМ: для `K∈[0.4,0.9]`
     исход стабилен (RL берёт 2–3 партии из 20), вырождается лишь при `K=1.0`
     (чистых потерь нет — снова winner-take-all).

  3. ОСТАТОЧНАЯ ЧУВСТВИТЕЛЬНОСТЬ БАЛАНСА (не исходный симптом): в скриптовом
     CI-критерии на плато `F0=30` баланс держится лишь в узком окне `K∈[0.6,0.7]`;
     при `K≥0.8` TIMING доминирует PRESSER (доля >0.65). На дне `F0=10` баланс
     держится при всех `K`. То есть «нож-лезвие» переродилось из «стагнации» в
     «чувствительность баланса к `K` на плато».

  4. СТРУКТУРНЫЙ ПРОТОТИП (ограниченная отдача удара, порог `W0`) под текущей
     архитектурой уже НЕ инертен, но нож-лезвие баланса им не лечится надёжно:
     при `N=40` и каноническом `K=0.70` вариант `W0=4` ПРОВАЛИВАЕТ критерий на
     `F0=30` (TIMING>PRESSER = 0.68) и возвращает winner-take-all в каноне
     (`env=True`: RL 0/10). Поэтому фикс НЕ добавляется (ТРИЗ: функции, которой
     нет, нет и нужды; исходный симптом снят архитектурой).

Запуск из корня репозитория:
    python3 experiments/exp_keffect_regime.py
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simulation as S
import strategies as ST

K0 = S.K_EFFECT
ORIG_APPLY = S._apply_transfer

K_LEVELS = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
NAMES = list(ST.STRATEGIES)
ACTIVE, CONTROLS = ST.COMPETITIVE, ST.CONTROLS
DOM_LIMIT, SYM_TOL = 0.65, 0.30


# --- структурный прототип: ограниченная отдача удара (порог W0) --------------
def _make_apply(recovery_fn):
    def _apply(att, dfn, work, att_type, rng, env=None):
        open_now = dfn.in_open
        dfn.receive_pressure(work)
        if env is not None:
            env.receive_pressure(work)
        if rng.random() < S.p_success(att_type, work, dfn.defense, dfn.last_work):
            m = S.MULT.get((att_type, dfn.defense), 1.0)
            gain_frac = S.GAIN_MAX if open_now else S.Y_SMALL
            if env is not None and env.in_open:
                gain_frac *= (1.0 + S.ENV_BONUS)
            gained = int(work * m * gain_frac)
            if gained:
                att.gain(gained)
                att.rest_units += gained
            dfn.process_hit(work)
            dfn.force = max(1, dfn.force + int(recovery_fn(work)))
    return _apply


def recovery_thresh(W0):
    """Восстановление с порогом: малый удар адресат переносит без потерь, крупный —
    теряет `(1-K)*(w-W0)` (ограниченная отдача удара)."""
    return lambda w: max(0.0, w - (1.0 - S.K_EFFECT) * max(0.0, w - W0))


def criterion(f0, n_seeds):
    """Метрики CI-критерия: макс. доминирование в ядре, асимметрия ролей, контроль."""
    mtx = ST.duel_matrix(NAMES, n_seeds=n_seeds, steps=400, f0=f0)
    dom, dpair = 0.0, None
    for a in ACTIVE:
        for b in ACTIVE:
            if a == b:
                continue
            rate = mtx[(a, b)]["A"] / n_seeds
            if rate > dom:
                dom, dpair = rate, (a, b)
    asym, apair = 0, None
    for i, a in enumerate(NAMES):
        for b in NAMES[i + 1:]:
            d = abs(mtx[(a, b)]["A"] - mtx[(b, a)]["B"])
            if d > asym:
                asym, apair = d, (a, b)
    ctrl, cpair = 0.0, None
    for c in CONTROLS:
        for a in ACTIVE:
            rate = mtx[(c, a)]["A"] / n_seeds
            if rate > ctrl:
                ctrl, cpair = rate, (c, a)
    ok = dom < DOM_LIMIT and asym <= SYM_TOL * n_seeds and ctrl < DOM_LIMIT
    return dom, dpair, asym, apair, ctrl, cpair, ok


def batch_counts(n_games=20):
    """Канон: (RL, AI, no) для env=True/False + медианы финальной силы."""
    out = {}
    for with_env in (True, False):
        rl = S.RLAgent()
        res = {"RL": 0, "UtilityAI": 0, None: 0}
        loser, winner = [], []
        for g in range(n_games):
            ai = S.UtilityAI()
            w, _, _, _ = S.play_game(rl, ai, 1000, seed=g, with_env=with_env)
            res[w] += 1
            if w is not None:
                loser.append(min(rl.force, ai.force))
                winner.append(max(rl.force, ai.force))
        out[with_env] = (res,
                         round(statistics.median(loser)) if loser else None,
                         round(statistics.median(winner)) if winner else None)
    return out


def main():
    print("P0 №2: режим K_EFFECT после P0 №1")

    print("\n[1] Канон и контроль по K_EFFECT (N=20 партий): есть ли стагнация?")
    print(f"    {'K':>5} | {'env=True RL/AI/no':>17} medF(проигр/побед) | "
          f"{'env=False RL/AI/no':>18}")
    for K in K_LEVELS:
        S.K_EFFECT = K
        b = batch_counts(20)
        (r1, l1, w1) = b[True]
        (r0, l0, w0) = b[False]
        print(f"    {K:>5.2f} | {r1['RL']:>2}/{r1['UtilityAI']:>2}/{r1[None]:>2}"
              f"{'':>8} {str(l1):>4}/{str(w1):>4}     | "
              f"{r0['RL']:>2}/{r0['UtilityAI']:>2}/{r0[None]:>2}")
    S.K_EFFECT = K0

    print("\n[2] CI-баланс по K_EFFECT (скриптовые, N=30): окно устойчивости")
    print(f"    {'K':>5} | {'F0=10 dom/asym/ctrl':>26} | {'F0=30 dom/asym/ctrl':>26}")
    for K in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        S.K_EFFECT = K
        cells = []
        for f0 in (10, 30):
            dom, dp, asym, ap, ctrl, cp, ok = criterion(f0, 30)
            cells.append(f"{dom:.2f}/{asym:>2}/{ctrl:.2f} {'ok' if ok else 'X'}")
        print(f"    {K:>5.2f} | {cells[0]:>26} | {cells[1]:>26}")
    S.K_EFFECT = K0

    print("\n[3] Структурный прототип W0=4 при каноническом K=0.70 (N=40)")
    print("    (проверка: лечит ли нож-лезвие баланса, не ломая канон)")
    S.K_EFFECT = 0.70
    S._apply_transfer = _make_apply(recovery_thresh(4))
    for f0 in (10, 30):
        dom, dp, asym, ap, ctrl, cp, ok = criterion(f0, 40)
        print(f"    F0={f0:>2}: dom={dom:.2f}{str(dp):>18} asym={asym} "
              f"ctrl={ctrl:.2f} -> {'PASS' if ok else 'FAIL'}")
    _, _, r1 = S.run_batch(10, quiet=True, with_env=True)
    print(f"    канон env=True: RL={r1['RL']}/AI={r1['UtilityAI']}/no={r1[None]}")
    S._apply_transfer = ORIG_APPLY
    S.K_EFFECT = K0

    print("\n=== ВЫВОД ===")
    print("  Исходный нож-лезвие (стагнация контроля без среды) СНЯТ архитектурой:")
    print("  контроль решается на всём K>0, канон держит устойчивый режим K∈[0.4,0.9].")
    print("  Остаётся лишь чувствительность баланса к K на плато F0=30 (окно 0.6–0.7);")
    print("  прототип W0 её надёжно не лечит (при N=40 ломает канон) — фикс НЕ добавляется.")


if __name__ == "__main__":
    main()
