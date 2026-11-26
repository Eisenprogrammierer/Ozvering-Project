"""Офлайн-подбор `score_bias`/`score_margin` по траекториям кампаний.

Читает JSON, снятый
``experiments/calibrate_automata_outcomes.py --no-outcome --history``,
и проигрывает исход для сетки параметров. Симуляция не запускается:
`score_bias`/`score_margin` влияют только на проверку исхода, поэтому
траектории diff и активов поражения переиспользуются.

`TARGETS` — желаемое распределение побед/поражений/ничьих, а не
наблюдаемое: по нему считается ошибка сетки. `--window`, `--streak` и
`--defeat` переопределяют параметры шаблона так же, как в
`calibrate_automata_outcomes.py`.

Запуск::

    venv/bin/python experiments/calibrate_outcome_grid.py \
        --inputs /tmp/opencode/hist_empire.json \
        --template empire --window 12
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

TARGETS = {
    "empire": (32, 16, 2),
    "republic": (22, 24, 4),
    "cult": (17, 27, 6),
    "corporation": (30, 12, 8),
}


def _fractions(counts):
    total = float(sum(counts))
    if total <= 0.0:
        return (0.0, 0.0, 0.0)
    return tuple(value / total for value in counts)


def _replay(record, bias, margin, window=1, streak=None):
    """Вернуть ``win|lose|stalemate`` для одной траектории.

    ``window`` сглаживает разницу прогресса скользящим средним: исход
    проверяется по среднему за последние ``window`` ходов, а не по
    мгновенному значению. ``streak`` переопределяет ``score_streak``
    шаблона.
    """
    player = str(record.get("player_side") or "")
    defeat = record.get("defeat") or {}
    streak_limit = max(1, int(record.get("streak_turns") or 1))
    score_after = max(0, int(record.get("score_after") or 0))
    if streak is None:
        streak = record.get("score_streak") or 1
    score_streak_limit = max(1, int(streak))
    window = max(1, int(window))
    low = {
        (side, asset): 0
        for side, thresholds in defeat.items()
        for asset in thresholds
    }
    score_streak = 0
    score_side = None
    recent = []
    for entry in record.get("trajectory") or ():
        turn = int(entry.get("turn") or 0)
        assets = entry.get("assets") or {}
        for side, thresholds in defeat.items():
            for asset, threshold in thresholds.items():
                key = (side, asset)
                value = (assets.get(side) or {}).get(asset)
                if value is None:
                    continue
                if float(value) <= float(threshold) + 1e-9:
                    low[key] = low.get(key, 0) + 1
                else:
                    low[key] = 0
                if low[key] >= streak_limit:
                    return "lose" if side == player else "win"
        recent.append(float(entry.get("diff") or 0.0))
        if len(recent) > window:
            recent.pop(0)
        difference = sum(recent) / float(len(recent)) + float(bias)
        side = (
            "win"
            if difference > margin
            else ("lose" if difference < -margin else None)
        )
        if turn < score_after or side is None:
            score_streak = 0
            score_side = None
        elif side == score_side:
            score_streak += 1
        else:
            score_streak = 1
            score_side = side
        if (
            turn >= score_after
            and side is not None
            and score_streak >= score_streak_limit
        ):
            return side
    return "stalemate"


def _score(records, bias, margin, target, window=1, streak=None):
    counts = {"win": 0, "lose": 0, "stalemate": 0}
    for record in records:
        counts[
            _replay(record, bias, margin, window=window, streak=streak)
        ] += 1
    actual = _fractions(
        (counts["win"], counts["lose"], counts["stalemate"])
    )
    error = sum(
        (value - expected) ** 2
        for value, expected in zip(actual, target)
    )
    return error, counts


def _grid(records, target, step, margin_max, window=1, streak=None):
    best = []
    bias = -0.30
    while bias <= 0.3001:
        margin = step
        while margin <= margin_max + 1e-9:
            error, counts = _score(
                records,
                bias,
                margin,
                target,
                window=window,
                streak=streak,
            )
            best.append(
                (
                    round(error, 6),
                    round(bias, 4),
                    round(margin, 4),
                    counts["win"],
                    counts["lose"],
                    counts["stalemate"],
                )
            )
            margin = round(margin + step, 6)
        bias = round(bias + step, 6)
    best.sort(key=lambda item: (item[0], abs(item[1]), item[2]))
    return best


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="JSON, снятые с --no-outcome --history",
    )
    parser.add_argument(
        "--template",
        required=True,
        choices=sorted(TARGETS),
        help="шаблон, к которому относятся записи",
    )
    parser.add_argument(
        "--target",
        default="",
        help="W,L,S через запятую; по умолчанию цель из docs",
    )
    parser.add_argument("--step", type=float, default=0.005)
    parser.add_argument("--margin-max", type=float, default=0.08)
    parser.add_argument(
        "--window",
        type=int,
        default=1,
        help="сглаживание diff скользящим средним, ходов",
    )
    parser.add_argument(
        "--streak",
        type=int,
        default=None,
        help="переопределить score_streak шаблона",
    )
    parser.add_argument(
        "--defeat",
        default="",
        help="порог поражения side:asset=value через запятую",
    )
    parser.add_argument("--top", type=int, default=8)
    args = parser.parse_args(argv)

    records = []
    for path in args.inputs:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for payload in data.values():
            for record in payload.get("records") or ():
                if not record.get("trajectory"):
                    raise SystemExit(
                        "%s: нет trajectory; снимите с --history" % path
                    )
                records.append(record)
    if not records:
        raise SystemExit("нет записей")
    for item in args.defeat.split(","):
        item = item.strip()
        if not item:
            continue
        key, _, value = item.partition("=")
        side, _, asset = key.partition(":")
        if not side or not asset or not value:
            raise SystemExit("--defeat: ожидается side:asset=value")
        for record in records:
            record.setdefault("defeat", {}).setdefault(side, {})[
                asset
            ] = float(value)
    if args.target:
        raw = [float(item) for item in args.target.split(",")]
        if len(raw) != 3:
            raise SystemExit("--target: нужно три числа W,L,S")
        target = _fractions(raw)
    else:
        target = _fractions(TARGETS[args.template])
    print(
        "template=%s seeds=%d target W/L/S = %.2f/%.2f/%.2f "
        "window=%d streak=%s"
        % (
            args.template,
            len(records),
            target[0],
            target[1],
            target[2],
            args.window,
            args.streak if args.streak is not None else "template",
        )
    )
    best = _grid(
        records,
        target,
        args.step,
        args.margin_max,
        window=args.window,
        streak=args.streak,
    )
    print("error   bias    margin  W  L  S")
    for item in best[: max(1, args.top)]:
        error, bias, margin, win, lose, stale = item
        print(
            "%.5f  %+.3f  %.3f  %d  %d  %d"
            % (error, bias, margin, win, lose, stale)
        )
    diffs = [float(record.get("diff") or 0.0) for record in records]
    print(
        "diff: mean=%+.3f median=%+.3f min=%+.3f max=%+.3f"
        % (
            statistics.mean(diffs),
            statistics.median(diffs),
            min(diffs),
            max(diffs),
        )
    )


if __name__ == "__main__":
    main()
