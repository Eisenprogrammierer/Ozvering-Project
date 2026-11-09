"""Прогон лорных кампаний-автоматов с подробным журналом и аудитом модели.

Скрипт не является частью игрового рантайма: он запускает те же шаблоны,
которые использует игра, записывает пошаговые состояния и работы, а затем
перечисляет аномалии математической модели. Артефакты пишутся только по
явному пути ``--out``.

Запуск из корня репозитория::

    venv/bin/python experiments/exp_automata_lore.py
    venv/bin/python experiments/exp_automata_lore.py --out /tmp/automata
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from campaign.automata import AutomataCampaign
from campaign.preset import CampaignPresetGenerator
from campaign.roles import RoleCatalog

TEMPLATES = (
    "empire_campaign",
    "republic_campaign",
    "cult_campaign",
    "corporation_campaign",
)
HORIZONS = (60, 288)
SEEDS = (7,)
WARMUP = 10
SATURATION_HIGH = 0.98
SATURATION_LOW = 0.02
STARVATION = 0.05


def _preset(template_id, seed, horizon):
    generator = CampaignPresetGenerator(
        catalog=RoleCatalog.load(ROOT / "configs" / "roles"),
        template_path=(
            ROOT / "configs" / "campaigns" / ("%s.json" % template_id)
        ),
    )
    preset = generator.generate(seed=seed)
    if horizon != preset.scenario.get("turns"):
        preset = copy.deepcopy(preset)
        preset.scenario["turns"] = int(horizon)
    return preset


def _run(template_id, seed, horizon):
    preset = _preset(template_id, seed, horizon)
    campaign = AutomataCampaign(preset, seed=seed)
    rows = []
    works = []
    previous_action = {}
    repeats = Counter()
    for _ in range(horizon):
        if campaign.finished:
            break
        campaign.advance()
        turn = campaign.turn
        for side, faction in campaign.factions.items():
            snapshot = faction.snapshot()
            for asset, value in snapshot["assets"].items():
                rows.append(
                    {
                        "template": template_id,
                        "seed": seed,
                        "horizon": horizon,
                        "turn": turn,
                        "side": side,
                        "faction": snapshot["name"],
                        "asset": asset,
                        "value": value,
                        "willing_share": snapshot["willing_share"],
                        "active_count": snapshot["active_count"],
                        "initial_count": snapshot["initial_count"],
                        "dissolved": snapshot["dissolved"],
                    }
                )
        for item in campaign.log:
            if item.get("turn") != turn:
                continue
            works.append(
                {
                    "template": template_id,
                    "seed": seed,
                    "horizon": horizon,
                    "turn": turn,
                    "actor_side": item["actor_side"],
                    "actor": item["actor_name"],
                    "target": item["target_name"],
                    "action_id": item["action_id"],
                    "label": item["label"],
                    "form": item["form"],
                    "chance": item["chance"],
                    "roll": item["roll"],
                    "success": item["success"],
                    "attack_asset": item["attack_asset"],
                    "attack_value": item["attack_value"],
                    "defense_asset": item["defense_asset"],
                    "defense_value": item["defense_value"],
                }
            )
        for side in campaign.factions:
            acted = next(
                (
                    item["action_id"]
                    for item in reversed(campaign.log)
                    if item.get("turn") == turn
                    and item.get("actor_side") == side
                ),
                None,
            )
            if acted is None:
                continue
            key = (side, acted)
            if previous_action.get(side) == acted:
                repeats[key] += 1
            previous_action[side] = acted
    return campaign, rows, works, repeats


def _anomalies(campaign, rows, works, repeats):
    found = list(campaign.audit())
    by_side = defaultdict(lambda: defaultdict(list))
    for row in rows:
        by_side[row["side"]][row["asset"]].append(
            (row["turn"], row["value"])
        )
    warm = [row for row in rows if row["turn"] >= WARMUP]
    if warm:
        saturated = sum(
            1
            for row in warm
            if (
                row["value"] >= SATURATION_HIGH
                or row["value"] <= SATURATION_LOW
            )
        )
        share = saturated / float(len(warm))
        if share > 0.55:
            found.append(
                "насыщение активов: %.1f%% измерений "
                "у границ [0,1] после хода %d"
                % (100.0 * share, WARMUP)
            )
    final = campaign.snapshot()["factions"]
    starving = [
        side
        for side, faction in final.items()
        if min(
            faction["assets"].get("supply", 1.0),
            faction["assets"].get("energy", 1.0),
        )
        <= STARVATION
    ]
    if len(starving) >= 3:
        found.append(
            "ресурсное истощение: у %d/%d фракций supply/energy ≤ %.2f"
            % (len(starving), len(final), STARVATION)
        )
    for side, assets in by_side.items():
        for asset in ("legitimacy", "cohesion"):
            values = [
                value
                for turn, value in assets.get(asset, ())
                if turn >= WARMUP
            ]
            if values and min(values) > 0.55:
                found.append(
                    "%s.%s не опускается ниже %.3f после хода %d: "
                    "порог поражения недостижим"
                    % (side, asset, min(values), WARMUP)
                )
    if campaign.outcome is None:
        found.append(
            "исход не наступил за %d ходов: победа/поражение не различаются"
            % campaign.max_turns
        )
    elif campaign.outcome == "stalemate":
        found.append(
            "исход=stalemate на ходе %d: модель не доводит "
            "конфликт до победы/поражения"
            % campaign.turn
        )

    action_counts = defaultdict(Counter)
    for item in works:
        action_counts[item["actor_side"]][item["action_id"]] += 1
    for side, counts in action_counts.items():
        total = sum(counts.values())
        if total < 10:
            continue
        action_id, count = counts.most_common(1)[0]
        if count / float(total) > 0.55:
            found.append(
                "%s: работа «%s» занимает %.0f%% ходов (%d/%d) — "
                "автоматический выбор вырожден"
                % (side, action_id, 100.0 * count / total, count, total)
            )
    for (side, action_id), count in repeats.items():
        if count >= 4:
            found.append(
                "%s: «%s» повторяется %d раз подряд — "
                "контур без обратной связи"
                % (side, action_id, count + 1)
            )

    if works:
        chances = [item["chance"] for item in works]
        extreme = sum(1 for value in chances if value < 0.05 or value > 0.95)
        if extreme / float(len(chances)) > 0.25:
            found.append(
                "детерминизм работ: %.0f%% бросков имеют шанс вне [0.05, 0.95]"
                % (100.0 * extreme / len(chances))
            )
        successes = sum(1 for item in works if item["success"])
        rate = successes / float(len(works))
        found.append(
            "калибровка: фактических успехов %.3f при среднем шансе %.3f "
            "(работ: %d)" % (rate, sum(chances) / len(chances), len(works))
        )

    willing = defaultdict(list)
    active = defaultdict(list)
    for row in rows:
        willing[row["side"]].append(row["willing_share"])
        active[row["side"]].append(row["active_count"])
    for side, values in willing.items():
        if len(values) > 1 and max(values) - min(values) < 1e-6:
            if values[0] >= 0.999:
                found.append(
                    "%s: willing_share постоянно %.3f — "
                    "организация не реагирует"
                    % (side, values[0])
                )
        if len(active[side]) > 1 and len(set(active[side])) == 1:
            found.append(
                "%s: active_count постоянно %d — распад не моделируется"
                % (side, active[side][0])
            )
    return found


def _summary(campaign, rows, works, anomalies):
    final = campaign.snapshot()
    return {
        "preset": campaign.preset_id,
        "turn": campaign.turn,
        "max_turns": campaign.max_turns,
        "outcome": campaign.outcome,
        "works": len(works),
        "events": len(campaign.log),
        "final_assets": {
            side: {
                key: round(value, 4)
                for key, value in faction["assets"].items()
            }
            for side, faction in final["factions"].items()
        },
        "anomalies": anomalies,
    }


def _write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="",
        help="каталог для CSV/JSON-артефактов (по умолчанию только stdout)",
    )
    parser.add_argument(
        "--horizons",
        default=",".join(str(item) for item in HORIZONS),
        help="горизонты через запятую",
    )
    args = parser.parse_args(argv)
    horizons = [int(item) for item in args.horizons.split(",") if item.strip()]
    out = Path(args.out) if args.out else None
    report = []
    for template_id in TEMPLATES:
        for seed in SEEDS:
            for horizon in horizons:
                campaign, rows, works, repeats = _run(
                    template_id, seed, horizon
                )
                anomalies = _anomalies(campaign, rows, works, repeats)
                summary = _summary(campaign, rows, works, anomalies)
                summary.update(
                    {"template": template_id, "seed": seed, "horizon": horizon}
                )
                report.append(summary)
                print(
                    "\n=== %s seed=%d horizon=%d ==="
                    % (template_id, seed, horizon)
                )
                print(
                    "ход=%d/%d исход=%s работ=%d"
                    % (
                        campaign.turn,
                        campaign.max_turns,
                        campaign.outcome,
                        len(works),
                    )
                )
                for side, faction in campaign.snapshot()["factions"].items():
                    assets = " ".join(
                        "%s=%.2f" % (key, value)
                        for key, value in sorted(faction["assets"].items())
                    )
                    print(
                        "  %-5s %-18s %s"
                        % (side, faction["name"], assets)
                    )
                for item in anomalies:
                    print("  ! %s" % item)

                if out is not None:
                    stem = "%s_seed%d_%d" % (template_id, seed, horizon)
                    _write_csv(
                        out / ("%s_assets.csv" % stem),
                        rows,
                        [
                            "template",
                            "seed",
                            "horizon",
                            "turn",
                            "side",
                            "faction",
                            "asset",
                            "value",
                            "willing_share",
                            "active_count",
                            "initial_count",
                            "dissolved",
                        ],
                    )
                    _write_csv(
                        out / ("%s_works.csv" % stem),
                        works,
                        [
                            "template",
                            "seed",
                            "horizon",
                            "turn",
                            "actor_side",
                            "actor",
                            "target",
                            "action_id",
                            "label",
                            "form",
                            "chance",
                            "roll",
                            "success",
                            "attack_asset",
                            "attack_value",
                            "defense_asset",
                            "defense_value",
                        ],
                    )
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("\nАртефакты: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
