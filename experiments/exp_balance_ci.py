import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import strategies as ST

N_SEEDS = 40
STEPS = 400
F0_LEVELS = (10, 30)
ACTIVE = ST.COMPETITIVE
CONTROLS = ST.CONTROLS
DOM_LIMIT = 0.65
SYM_TOL = 0.30


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
    problems = []
    print(f"\n--- Критерий: {title} ---")

    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            w_first = mtx[(a, b)]["A"]
            w_second = mtx[(b, a)]["B"]
            diff = abs(w_first - w_second)
            ok = diff <= SYM_TOL * N_SEEDS
            print(
                f"  симметрия {a:>7}/{b:<7}: {w_first} vs {w_second} "
                f"(Δ={diff}, допуск {SYM_TOL * N_SEEDS:.0f}) "
                f"{'ok' if ok else 'НАРУШЕНА'}"
            )
            if not ok:
                problems.append(
                    f"{title}: асимметрия ролей {a}/{b} (Δ={diff})"
                )

    for a in ACTIVE:
        for b in ACTIVE:
            if a == b:
                continue
            wins = mtx[(a, b)]["A"]
            rate = wins / N_SEEDS
            ok = rate < DOM_LIMIT
            print(
                f"  доминирование {a:>7} против {b:<7}: {rate:.2f} "
                f"(предел {DOM_LIMIT}) {'ok' if ok else 'ДОМИНИРУЕТ'}"
            )
            if not ok:
                problems.append(f"{title}: {a} доминирует {b} ({rate:.2f})")

    for c in CONTROLS:
        for a in ACTIVE:
            rate = mtx[(c, a)]["A"] / N_SEEDS
            ok = rate < DOM_LIMIT
            print(
                f"  контроль {c:>7} vs {a:<7}: {rate:.2f} "
                f"{'ok' if ok else 'КОНТРОЛЬ ВЫИГРЫВАЕТ'}"
            )
            if not ok:
                problems.append(f"{title}: {c} обыгрывает {a} ({rate:.2f})")
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
    print(
        "Критерий баланса выполнен: конкурентные стратегии не доминируют, "
        "контроли проигрывают, роли симметричны."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
