import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import warfare


def main():
    first = warfare.build_demo_scenario(seed=7, turns=140).run()
    second = warfare.build_demo_scenario(seed=7, turns=140).run()
    counts = first["counts"]
    need = (
        "panic",
        "retreat",
        "banzai",
        "barrier",
        "spawn",
        "reinforcement",
        "support",
    )
    missing = [name for name in need if counts.get(name, 0) <= 0]

    print(
        f"Войсковой сценарий: seed=7, тактов={first['turn']}, "
        f"итог={first['winner']}"
    )
    print(
        "События: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    )
    checks = [
        (
            "детерминизм по seed",
            first["counts"] == second["counts"]
            and first["winner"] == second["winner"]
            and first["turn"] == second["turn"],
        ),
        (
            "обе стороны на поле",
            bool(first["sides"]["red"]) and bool(first["sides"]["blue"]),
        ),
        (
            "16 потребностей у персонажей",
            all(
                set(c["needs"]) == set(warfare.NEEDS)
                for side in first["sides"].values()
                for d in side
                for c in d["characters"]
            ),
        ),
        ("все виды событий", not missing),
    ]
    for name, ok in checks:
        print(f"  [{'OK' if ok else 'FAIL'}] {name}")
    if missing:
        print(f"  нет событий: {', '.join(missing)}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
