"""Сравнить разброс траекторий: внутри seed и между seed.

Читает JSON с ``--no-outcome --history`` и печатает, насколько
прогресс расходится между seed'ами по сравнению с шумом внутри одного
прогона. Если между seed'ами разброс не больше шума, исход по порогу
прогресса — подбрасывание монеты.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics


def _load(paths):
    records = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for payload in data.values():
            records.extend(payload.get("records") or ())
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--from-turn", type=int, default=24)
    parser.add_argument("--to-turn", type=int, default=10 ** 6)
    args = parser.parse_args(argv)
    records = _load(args.inputs)
    if not records:
        raise SystemExit("нет записей")
    within = []
    means = []
    for record in records:
        values = [
            float(entry.get("diff") or 0.0)
            for entry in record.get("trajectory") or ()
            if args.from_turn <= int(entry.get("turn") or 0)
            <= args.to_turn
        ]
        if len(values) > 1:
            within.append(statistics.pstdev(values))
            means.append(statistics.mean(values))
    print(
        "records=%d turns=%d..%d within-seed sd mean=%.4f "
        "between-seed sd=%.4f ratio=%.2f"
        % (
            len(records),
            args.from_turn,
            args.to_turn,
            statistics.mean(within) if within else 0.0,
            statistics.pstdev(means) if len(means) > 1 else 0.0,
            (
                statistics.pstdev(means) / statistics.mean(within)
                if within and statistics.mean(within) > 0
                else 0.0
            ),
        )
    )
    print(
        "means: min=%+.4f max=%+.4f spread=%.4f"
        % (
            min(means) if means else 0.0,
            max(means) if means else 0.0,
            (max(means) - min(means)) if means else 0.0,
        )
    )


if __name__ == "__main__":
    main()
