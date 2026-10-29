"""Калибровка кампании на обучаемых политиках (`bdi`/`qtable-campaign`/`mlp`).

Дуэльная калибровка здоровья (`exp_health_calibration.py`) отвечает на вопрос
«как заканчивается бой». Этот скрипт отвечает на другой: «что делает политика
за 30 дней кампании и заканчивается ли история вообще».

Запуск из корня репозитория:

    python3 experiments/exp_campaign_calibration.py
    python3 experiments/exp_campaign_calibration.py --seeds 50 --days 30
    python3 experiments/exp_campaign_calibration.py \
        --policies bdi,qtable-campaign,mlp --train-episodes 20

Скрипт ничего не меняет в коде: политики прогреваются на отдельном потоке
seed'ов, а оценка идёт на held-out seed'ах без исследования и без обучения.
Цели — не «баланс побед», а работоспособность мира:

- ни одна политика не падает и не зависает;
- история может закончиться (`agent`/`opponent`), а не только усечением;
- усечение не поглощает все эпизоды (иначе действия не влияют на мир);
- медиана длины эпизода заметно больше одного дня;
- награды и состояние остаются конечными.

Результаты и трактовка — `docs/WORLD_CORE_MODEL.md` §2.3.4 и `docs/TODO.md`.
"""

import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.train import _play_campaign_episode, _warmup_baseline
from campaign.env import CampaignEnv

POLICIES = ("bdi", "qtable-campaign", "mlp")


def _median(values, default=0.0):
    values = [float(value) for value in values]
    return statistics.median(values) if values else float(default)


def _run_policy(
    name, seeds, days, train_episodes, train_seed, career_actions=False
):
    policy, trained = _warmup_baseline(
        name,
        seed=train_seed,
        episodes=train_episodes,
        max_steps=days,
        env_name="campaign",
        env_kwargs=None,
    )
    rows = []
    for seed in seeds:
        env = CampaignEnv(
            seed=seed,
            max_days=days,
            career_actions=career_actions,
        )
        result = _play_campaign_episode(
            env, policy, seed=seed, learn=False, explore=False
        )
        engine = env.engine
        rows.append(
            {
                "seed": seed,
                "winner": result["winner"],
                "outcome": result["outcome"],
                "day": int(result["day"]),
                "truncated": bool(result["truncated"]),
                "standing": float(engine.player_resources["standing"]),
                "health": float(engine.player_health),
                "sickness": float(engine.player_sickness),
                "max_skill": max(
                    float(value)
                    for value in (engine.profile.get("skills") or {}).values()
                ),
                "dismissals": int(engine.dismissal_count),
                "collapsed": bool(engine.collapsed),
            }
        )
    agent = sum(1 for row in rows if row["winner"] == "agent")
    opponent = sum(1 for row in rows if row["winner"] == "opponent")
    draws = len(rows) - agent - opponent
    truncated = sum(1 for row in rows if row["truncated"])
    # «Нейтральный финал»: эпизод закончился не по горизонту, но и не
    # победой/поражением — сейчас это потеря должности без замены.
    neutral_done = sum(
        1
        for row in rows
        if not row["truncated"] and row["winner"] is None
    )
    return {
        "policy": name,
        "trained_episodes": int(trained),
        "episodes": len(rows),
        "agent": agent,
        "opponent": opponent,
        "draws": draws,
        "truncated": truncated,
        "neutral_done": neutral_done,
        "agent_share": agent / max(1, len(rows)),
        "opponent_share": opponent / max(1, len(rows)),
        "truncated_share": truncated / max(1, len(rows)),
        "neutral_share": neutral_done / max(1, len(rows)),
        "median_day": _median([row["day"] for row in rows]),
        "median_standing": _median(
            [row["standing"] for row in rows]
        ),
        "median_health": _median([row["health"] for row in rows]),
        "median_sickness": _median([row["sickness"] for row in rows]),
        "median_max_skill": _median(
            [row["max_skill"] for row in rows]
        ),
        "dismissals": sum(row["dismissals"] for row in rows),
        "collapses": sum(1 for row in rows if row["collapsed"]),
        "rows": rows,
    }


def _goals(report):
    """Санитарные цели: мир работает, а не «все всегда выживают»."""
    checks = []
    checks.append(
        (
            "история может закончиться",
            any(
                row["agent"] + row["opponent"] > 0
                for row in report
            ),
        )
    )
    checks.append(
        (
            "усечение не поглощает всё",
            all(row["truncated_share"] <= 0.90 for row in report),
        )
    )
    checks.append(
        (
            "эпизод длиннее одного дня",
            all(row["median_day"] >= 5 for row in report),
        )
    )
    checks.append(
        (
            "состояние конечно",
            all(
                row["median_health"] >= 0.0
                and row["median_sickness"] >= 0.0
                for row in report
            ),
        )
    )
    return checks


def _print_report(report, days):
    print()
    print(
        "=== калибровка кампании (N=%d, days=%d) ==="
        % (report[0]["episodes"], days)
    )
    print(
        "%-16s %7s %7s %7s %7s %8s %9s %9s"
        % (
            "политика",
            "agent",
            "opp",
            "neutral",
            "trunc",
            "медиана",
            "standing",
            "здоровье",
        )
    )
    for row in report:
        print(
            "%-16s %6.0f%% %6.0f%% %6.0f%% %6.0f%% %8.0f %9.2f %9.1f"
            % (
                row["policy"],
                row["agent_share"] * 100.0,
                row["opponent_share"] * 100.0,
                row["neutral_share"] * 100.0,
                row["truncated_share"] * 100.0,
                row["median_day"],
                row["median_standing"],
                row["median_health"],
            )
        )
    print()
    for row in report:
        print(
            "  %-16s смен роли: %d · распадов: %d · медиана болезни: %.2f"
            " · медиана навыка: %.2f"
            % (
                row["policy"],
                row["dismissals"],
                row["collapses"],
                row["median_sickness"],
                row["median_max_skill"],
            )
        )
    print()
    for label, ok in _goals(report):
        print("  %-34s %s" % (label, "ok" if ok else "ВНЕ ЦЕЛИ"))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--policies",
        default=",".join(POLICIES),
        help="политики через запятую (bdi,qtable-campaign,mlp)",
    )
    parser.add_argument(
        "--train-episodes",
        type=int,
        default=10,
        help="сколько эпизодов прогреть обучаемые политики перед оценкой",
    )
    parser.add_argument(
        "--train-seed",
        type=int,
        default=90000,
        help="поток seed'ов прогрева (не пересекается с оценкой)",
    )
    parser.add_argument(
        "--eval-seed",
        type=int,
        default=100000,
        help="первый held-out seed оценки",
    )
    parser.add_argument(
        "--career-actions",
        action="store_true",
        help="разрешить политике seek_promotion/request_transfer/resign",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    policies = [
        item.strip() for item in str(args.policies).split(",") if item.strip()
    ]
    unknown = [item for item in policies if item not in POLICIES]
    if unknown:
        parser.error("неизвестные политики: %s" % ", ".join(unknown))
    seeds = [args.eval_seed + index for index in range(max(1, args.seeds))]
    report = [
        _run_policy(
            name,
            seeds,
            max(1, args.days),
            max(0, args.train_episodes),
            args.train_seed,
            career_actions=args.career_actions,
        )
        for name in policies
    ]
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report, max(1, args.days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
