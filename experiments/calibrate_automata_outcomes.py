"""Калибровка исхода лорных кампаний-автоматов по разнице прогресса.

Скрипт запускает production-шаблоны (с их `score_bias` из JSON), собирает
разницу прогресса игрока и соперника и печатает, как она превращается в
победу/поражение/ничью при разных `score_margin`. Кампании, завершившиеся
досрочно — по порогу поражения или по устойчивому преимуществу
(`score_after` + `score_streak`), — учитываются своим исходом и не зависят
от перебора `score_margin`.

Запуск из корня репозитория::

    venv/bin/python experiments/calibrate_automata_outcomes.py
    venv/bin/python experiments/calibrate_automata_outcomes.py --seeds 1-50
    venv/bin/python experiments/calibrate_automata_outcomes.py --out /tmp/calibration.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from campaign.automata import AutomataCampaign
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

TEMPLATES = ("empire", "republic", "cult", "corporation")
HORIZON = 72


def _seeds(value):
    result = []
    for chunk in str(value).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, end = chunk.split("-", 1)
            result.extend(range(int(start), int(end) + 1))
        else:
            result.append(int(chunk))
    return tuple(sorted(set(result)))


def _preset(template_id, seed):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=ROOT / "configs" / "campaigns" / (
            "%s_campaign.json" % template_id
        ),
    )
    return generator.generate(seed=seed)


def _collect(template_id, seed):
    preset = _preset(template_id, seed)
    campaign = AutomataCampaign(preset, seed=seed)
    # Кампания больше не ограничена ходами: горизонт задаёт эксперимент.
    for _ in range(HORIZON):
        if campaign.finished:
            break
        campaign.advance()
    return {
        "seed": seed,
        "turn": campaign.turn,
        "max_turns": HORIZON,
        "finished": bool(campaign.finished),
        "outcome": campaign.outcome,
        "diff": campaign.player.progress() - campaign.rival.progress(),
        "bias": float(
            (preset.scenario.get("outcome") or {}).get("score_bias") or 0.0
        ),
    }


def _outcomes(records, margin):
    counts = {"win": 0, "lose": 0, "stalemate": 0}
    for record in records:
        if record.get("finished"):
            counts[record["outcome"] or "stalemate"] += 1
            continue
        difference = record["diff"] + record["bias"]
        if difference > margin:
            counts["win"] += 1
        elif difference < -margin:
            counts["lose"] += 1
        else:
            counts["stalemate"] += 1
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", default="1-50", help="например, 1-50 или 1,3,7")
    parser.add_argument(
        "--margins",
        default="0,0.01,0.02,0.03,0.04,0.05,0.06,0.07,0.08",
        help="список score_margin через запятую",
    )
    parser.add_argument("--out", default="", help="JSON с записями прогонов")
    args = parser.parse_args(argv)
    seeds = _seeds(args.seeds)
    margins = [float(item) for item in args.margins.split(",") if item.strip()]

    report = {}
    for template_id in TEMPLATES:
        records = [_collect(template_id, seed) for seed in seeds]
        diffs = [record["diff"] for record in records]
        early = [record for record in records if record.get("finished")]
        print("\n=== %s ===" % template_id)
        print(
            "diff: mean=%+.3f median=%+.3f min=%+.3f max=%+.3f"
            % (
                statistics.mean(diffs),
                statistics.median(diffs),
                min(diffs),
                max(diffs),
            )
        )
        print(
            "исходы до горизонта: %d / %d"
            % (len(early), len(records))
        )
        bias = records[0]["bias"] if records else 0.0
        print("score_bias из шаблона: %+.3f" % bias)
        for margin in margins:
            counts = _outcomes(records, margin)
            print(
                "  margin %.3f -> W%d L%d S%d"
                % (
                    margin,
                    counts["win"],
                    counts["lose"],
                    counts["stalemate"],
                )
            )
        report[template_id] = {
            "seeds": list(seeds),
            "records": records,
        }

    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("\nJSON: %s" % args.out)


if __name__ == "__main__":
    main()
