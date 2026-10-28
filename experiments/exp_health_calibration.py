"""Калибровка здоровья core41 на дуэлях QTable против BDI.

Запуск из корня репозитория:

    python3 experiments/exp_health_calibration.py
    python3 experiments/exp_health_calibration.py --baseline
    python3 experiments/exp_health_calibration.py --seeds 100 --steps 2000
    python3 experiments/exp_health_calibration.py \
        --set HEALTH_DAMAGE_RATIO=0.75,HEALTH_REST_REGEN=0.8

Скрипт не меняет код: константы `core41.model` подменяются только на время
пакета партий и затем восстанавливаются. Цели калибровки и результаты —
в `docs/WORLD_CORE_MODEL.md`, раздел 2.3.2.
"""

import argparse
import os
import statistics
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import BDIPolicy, QTablePolicy
from core41 import ArenaMatch
import core41.model as model

CALIBRATABLE = (
    "HEALTH_DAMAGE_RATIO",
    "HEALTH_REST_REGEN",
    "HEALTH_STARVE_DECAY",
)

BASELINE = {
    "HEALTH_DAMAGE_RATIO": 1.0,
    "HEALTH_REST_REGEN": 0.5,
    "HEALTH_STARVE_DECAY": 1.0,
}

TARGETS = {
    "death": (0.35, 0.60),
    "capture": (0.15, 0.35),
    "timeout": (0.10, 0.35),
    "median_ticks": (300.0, 900.0),
    "starve_share": (0.15, 0.35),
}

_METER = {"starve": 0.0, "damage": 0.0}
_ORIG_TICK = model.Automaton.tick_health
_ORIG_DAMAGE = model.Automaton.apply_force_damage


def _meter_tick(self, resting=False):
    before = self.health
    result = _ORIG_TICK(self, resting)
    if self.energy <= 0.0 and result < before:
        _METER["starve"] += before - result
    return result


def _meter_damage(self, damage):
    before = self.health
    result = _ORIG_DAMAGE(self, damage)
    _METER["damage"] += before - self.health
    return result


@contextmanager
def metering():
    model.Automaton.tick_health = _meter_tick
    model.Automaton.apply_force_damage = _meter_damage
    try:
        yield
    finally:
        model.Automaton.tick_health = _ORIG_TICK
        model.Automaton.apply_force_damage = _ORIG_DAMAGE


def _make_match(seed, steps):
    return ArenaMatch(
        seed=seed,
        steps=steps,
        rl_policy=QTablePolicy(seed=seed),
        ai_policy=BDIPolicy(seed=seed ^ 0xB01),
    )


def run_match(seed, steps):
    match = _make_match(seed, steps)
    critical_ticks = 0
    recoveries = 0
    below = {"rl": False, "ai": False}
    while not match.finished:
        match.step_tick()
        for side in ("rl", "ai"):
            health = getattr(match, side).health
            if health <= model.HEALTH_CRITICAL:
                critical_ticks += 1
                below[side] = True
            elif below[side]:
                recoveries += 1
                below[side] = False
    if match.rl.is_dead or match.ai.is_dead:
        cause = "death"
    elif match.step < steps:
        cause = "capture"
    else:
        cause = "timeout"
    return {
        "cause": cause,
        "ticks": match.step,
        "winner": match.winner,
        "critical": critical_ticks,
        "recoveries": recoveries,
    }


def _with_overrides(overrides):
    saved = {}
    for name, value in overrides.items():
        saved[name] = getattr(model, name)
        setattr(model, name, value)
    return saved


def _restore(saved):
    for name, value in saved.items():
        setattr(model, name, value)


def run_batch(seeds, steps, overrides, label):
    saved = _with_overrides(overrides)
    _METER["starve"] = 0.0
    _METER["damage"] = 0.0
    try:
        with metering():
            rows = [run_match(seed, steps) for seed in range(seeds)]
    finally:
        _restore(saved)
    _report(label, rows, seeds, steps)
    return rows


def _share(count, total):
    return count / max(1, total)


def _report(label, rows, seeds, steps):
    counts = {
        cause: sum(1 for row in rows if row["cause"] == cause)
        for cause in ("death", "capture", "timeout")
    }
    winners = {
        name: sum(1 for row in rows if row["winner"] == name)
        for name in ("RL", "AI", None)
    }
    median_ticks = statistics.median(row["ticks"] for row in rows)
    total_damage = _METER["starve"] + _METER["damage"]
    starve_share = _METER["starve"] / max(1.0, total_damage)
    critical = statistics.mean(row["critical"] for row in rows)
    recoveries = statistics.mean(row["recoveries"] for row in rows)

    print(
        "\n=== %s (N=%d, steps=%d) ==="
        % (label, seeds, steps)
    )
    for cause in ("death", "capture", "timeout"):
        print(
            "  %-8s %3d  %5.1f%%"
            % (cause, counts[cause], 100.0 * _share(counts[cause], seeds))
        )
    print(
        "  победы   RL %d / AI %d / ничья %d"
        % (winners["RL"], winners["AI"], winners[None])
    )
    print("  медиана тактов            %.0f" % median_ticks)
    print(
        "  урон здоровью за партию   %.1f" % (total_damage / seeds)
    )
    print(
        "  доля голодного урона      %.1f%%" % (100.0 * starve_share)
    )
    print(
        "  критические такты/партию  %.1f" % critical
    )
    print(
        "  выходы из критики/партию  %.2f" % recoveries
    )
    metrics = {
        "death": _share(counts["death"], seeds),
        "capture": _share(counts["capture"], seeds),
        "timeout": _share(counts["timeout"], seeds),
        "median_ticks": median_ticks,
        "starve_share": starve_share,
    }
    failures = []
    for name, (low, high) in TARGETS.items():
        value = metrics[name]
        if not low <= value <= high:
            failures.append(
                "%s=%.2f вне [%.2f; %.2f]" % (name, value, low, high)
            )
    if failures:
        print("  цели: " + "; ".join(failures))
    else:
        print("  цели: все в допуске")


def parse_overrides(text):
    overrides = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        name, separator, value = part.partition("=")
        name = name.strip().upper()
        if not separator or not name:
            raise ValueError("ожидалось NAME=VALUE: %r" % part)
        if name not in CALIBRATABLE:
            raise ValueError(
                "%s не калибруется здесь; допустимо: %s"
                % (name, ", ".join(CALIBRATABLE))
            )
        overrides[name] = float(value)
    return overrides


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=50)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument(
        "--set",
        dest="overrides",
        default="",
        help="переопределения через запятую: NAME=VALUE",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="показать старую калибровку (1.0/0.5) для сравнения",
    )
    args = parser.parse_args(argv)
    if args.seeds < 1 or args.steps < 1:
        parser.error("--seeds и --steps должны быть положительными")
    try:
        overrides = parse_overrides(args.overrides)
    except ValueError as error:
        parser.error(str(error))

    if args.baseline:
        run_batch(args.seeds, args.steps, BASELINE, "baseline: 1.0/0.5")
    run_batch(args.seeds, args.steps, overrides, "текущая калибровка")
    return 0


if __name__ == "__main__":
    sys.exit(main())
