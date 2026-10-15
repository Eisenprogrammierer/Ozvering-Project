"""CI-тест баланса: ни одна АКТИВНАЯ чистая стратегия не доминирует.

Критерий из docs/history/ideas.md (VI.4, S3/S4): в матрице «стратегия × стратегия»
ни одна строка не доминирует; зеркальные дуэли (смена ролей) статистически
симметричны; пассивность (S3) лечит, но проигрывает умеренно-активному.

Тест детерминирован: стратегии и дуэль — из ``experiments/strategies.py``,
seed'ы фиксированы. Код возврата 0 — баланс приемлем, 1 — критерий нарушен
(это и есть цель калибровки; красный тест на текущей калибровке — ожидаемо).

Запуск из корня репозитория:
    python3 experiments/exp_balance_ci.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import strategies as ST

# --- Пороги критерия (калибруются вместе с моделью; осознанно вынесены наверх) --
N_SEEDS = 20            # партий на упорядоченную пару
STEPS = 400             # максимум тактов в партии
F0_LEVELS = (10, 30)    # дно и плато (см. docs/FIX_HYPOTHESIS.md)
ACTIVE = ("PRESSER", "TIMING")   # активные стратегии, между которыми нужна ничья
PASSIVE = "PASSIVE"
DOM_LIMIT = 0.65        # макс. доля побед активной стратегии против другой активной
SYM_TOL = 0.30          # допуск асимметрии смены ролей (доля от N_SEEDS)


def _fmt(t):
    return f"{t['A']}:{t['B']}({t[None]}d)"


def _print_matrix(title, mtx, names):
    print(f"\n=== {title} ===")
    print(f"{'':>9}" + "".join(f"{k:>16}" for k in names))
    for ka in names:
        row = [f"{ka:>9}"]
        row += [_fmt(mtx[(ka, kb)]).rjust(16) for kb in names]
        print(*row)


def evaluate(title, mtx, names):
    """Возвращает список реплик-нарушений (пусто — критерий выполнен)."""
    problems = []
    print(f"\n--- Критерий: {title} ---")

    # 1. Симметрия смены ролей: A-победы в A-vs-B ≈ A-победы в B-vs-A.
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            w_first = mtx[(a, b)]["A"]     # a победил, будучи стороной A
            w_second = mtx[(b, a)]["B"]    # a победил, будучи стороной B
            diff = abs(w_first - w_second)
            ok = diff <= SYM_TOL * N_SEEDS
            print(f"  симметрия {a:>7}/{b:<7}: {w_first} vs {w_second} "
                  f"(Δ={diff}, допуск {SYM_TOL*N_SEEDS:.0f}) {'ok' if ok else 'НАРУШЕНА'}")
            if not ok:
                problems.append(f"{title}: асимметрия ролей {a}/{b} (Δ={diff})")

    # 2. Доминирование среди активных: доля побед каждой активной против другой.
    for a in ACTIVE:
        for b in ACTIVE:
            if a == b:
                continue
            wins = mtx[(a, b)]["A"]
            rate = wins / N_SEEDS
            ok = rate < DOM_LIMIT
            print(f"  доминирование {a:>7} против {b:<7}: {rate:.2f} "
                  f"(предел {DOM_LIMIT}) {'ok' if ok else 'ДОМИНИРУЕТ'}")
            if not ok:
                problems.append(f"{title}: {a} доминирует {b} ({rate:.2f})")

    # 3. Пассивность (S3): не должна обыгрывать активную стратегию.
    for a in ACTIVE:
        rate = mtx[(PASSIVE, a)]["A"] / N_SEEDS
        ok = rate < DOM_LIMIT
        print(f"  пассив vs {a:>7}: {rate:.2f} {'ok' if ok else 'ПАССИВ ВЫИГРЫВАЕТ'}")
        if not ok:
            problems.append(f"{title}: PASSIVE обыгрывает {a} ({rate:.2f})")
    return problems


def main():
    names = list(ST.STRATEGIES)
    all_problems = []
    for f0 in F0_LEVELS:
        mtx = ST.duel_matrix(names, n_seeds=N_SEEDS, steps=STEPS, f0=f0)
        _print_matrix(f"Матрица дуэлей F0={f0} ({N_SEEDS} seed)", mtx, names)
        all_problems += evaluate(f"F0={f0}", mtx, names)

    print("\n=== ИТОГ ===")
    if all_problems:
        print("Баланс НЕ выполнен (цель калибровки):")
        for p in all_problems:
            print("  -", p)
        return 1
    print("Критерий баланса выполнен: активные стратегии не доминируют, роли симметричны.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
