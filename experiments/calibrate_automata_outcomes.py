"""Калибровка исхода лорных кампаний-автоматов по разнице прогресса.

Скрипт запускает production-шаблоны (с их `score_bias` из JSON), собирает
разницу прогресса игрока и соперника и печатает, как она превращается в
победу/поражение/ничью при разных `score_margin`. Кампании, завершившиеся
досрочно — по порогу поражения или по устойчивому преимуществу
(`score_after` + `score_streak`), — учитываются своим исходом и не зависят
от перебора `score_margin`. Оценка идёт по среднему за последние
`score_window` ходов; `--window` и `--defeat` переопределяют значения
шаблона на время прогона, `--no-outcome` выключает досрочный исход, а
`--history` пишет траекторию для офлайн-подбора
(`calibrate_outcome_grid.py`).

Запуск из корня репозитория::

    venv/bin/python experiments/calibrate_automata_outcomes.py
    venv/bin/python experiments/calibrate_automata_outcomes.py --seeds 1-50
    venv/bin/python experiments/calibrate_automata_outcomes.py \
        --npc-policy legacy --seeds 1-10
    venv/bin/python experiments/calibrate_automata_outcomes.py \
        --no-outcome --history --window 12 --out /tmp/calibration.json
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


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_mapping(value):
    return value if isinstance(value, dict) else {}


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


def _alive(character):
    return not bool(
        getattr(
            character,
            "is_dead",
            getattr(character, "dead", False),
        )
    )


def _collect(
    template_id,
    seed,
    npc_policy="off",
    horizon=HORIZON,
    no_outcome=False,
    history=False,
    bias=None,
    margin=None,
    window=None,
    defeat_overrides=None,
    effect_scale=None,
    asset_relax=None,
):
    preset = _preset(template_id, seed)
    campaign = AutomataCampaign(preset, seed=seed)
    if effect_scale is not None:
        campaign.model["effect_scale"] = float(effect_scale)
    if asset_relax is not None:
        campaign.model["asset_relax"] = float(asset_relax)
    if npc_policy != "off":
        campaign.ai_model["npc_policy"] = dict(
            campaign.ai_model.get("npc_policy") or {},
            enabled=True,
            backend=npc_policy,
        )
        campaign._npc_policy_obj = None
        campaign._soar_policy_obj = None
    rules = campaign.outcome_rules
    if bias is not None:
        rules["score_bias"] = float(bias)
    if margin is not None:
        rules["score_margin"] = float(margin)
    if window is not None:
        rules["score_window"] = int(window)
    for key, value in (defeat_overrides or {}).items():
        side, _, asset = key.partition(":")
        thresholds = rules.setdefault("defeat", {}).setdefault(side, {})
        thresholds[asset] = float(value)
    defeat = {
        str(side): {
            str(asset): float(_number(threshold, 0.0))
            for asset, threshold in _as_mapping(thresholds).items()
        }
        for side, thresholds in _as_mapping(rules.get("defeat")).items()
    }
    if no_outcome:
        # Отключить проверку исхода, чтобы получить полную траекторию
        # для офлайн-подбора bias/margin.
        campaign.outcome_rules = {}
    history_scores = {side: [] for side in campaign.factions}
    trajectory = []
    first_death = None
    dissolved = {}
    for turn in range(1, horizon + 1):
        if campaign.finished:
            break
        campaign.advance()
        for side, faction in campaign.factions.items():
            history_scores[side].append(faction.score())
            if side not in dissolved and faction.dissolved:
                dissolved[side] = turn
            if first_death is None and any(
                not _alive(character) for character in faction.characters
            ):
                first_death = turn
        if history:
            trajectory.append(
                {
                    "turn": turn,
                    "diff": round(
                        campaign.player.progress()
                        - campaign.rival.progress(),
                        6,
                    ),
                    "assets": {
                        side: {
                            asset: round(faction.asset(asset), 6)
                            for asset in defeat.get(side, ())
                        }
                        for side, faction in campaign.factions.items()
                    },
                }
            )
    spread = {
        side: max(values) - min(values)
        for side, values in history_scores.items()
        if values
    }
    final = {
        side: values[-1]
        for side, values in history_scores.items()
        if values
    }
    final_spread = (
        max(final.values()) - min(final.values()) if final else 0.0
    )
    return {
        "seed": seed,
        "turn": campaign.turn,
        "max_turns": horizon,
        "npc_policy": npc_policy,
        "finished": bool(campaign.finished),
        "outcome": campaign.outcome,
        "diff": campaign.player.progress() - campaign.rival.progress(),
        "bias": float(rules.get("score_bias") or 0.0),
        "margin": float(rules.get("score_margin") or 0.0),
        "window": int(_number(rules.get("score_window"), 1)),
        "score_after": int(_number(rules.get("score_after"), 0)),
        "score_streak": int(_number(rules.get("score_streak"), 0)),
        "streak_turns": int(_number(rules.get("streak_turns"), 0)),
        "player_side": campaign.player_side,
        "rival_side": campaign.rival_side,
        "defeat": defeat,
        "first_death": first_death,
        "dissolved": dissolved,
        "score_spread": spread,
        "final_spread": final_spread,
        "final_scores": final,
        "trajectory": trajectory,
        "npc_decisions": (
            campaign.npc_decision_report()
            if npc_policy != "off"
            else None
        ),
    }


def _outcomes(records, margin):
    counts = {"win": 0, "lose": 0, "stalemate": 0}
    for record in records:
        if record.get("finished"):
            counts[record["outcome"] or "stalemate"] += 1
            continue
        window = max(1, int(_number(record.get("window"), 1)))
        trajectory = record.get("trajectory") or []
        if trajectory:
            recent = [
                float(entry.get("diff") or 0.0)
                for entry in trajectory[-window:]
            ]
            difference = (
                sum(recent) / float(len(recent))
                if recent
                else float(record["diff"])
            )
        else:
            difference = float(record["diff"])
        difference += float(record["bias"])
        if difference > margin:
            counts["win"] += 1
        elif difference < -margin:
            counts["lose"] += 1
        else:
            counts["stalemate"] += 1
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seeds",
        default="1-50",
        help="например, 1-50 или 1,3,7",
    )
    parser.add_argument(
        "--margins",
        default="0,0.01,0.02,0.03,0.04,0.05,0.06,0.07,0.08",
        help="список score_margin через запятую",
    )
    parser.add_argument(
        "--templates",
        default=",".join(TEMPLATES),
        help="подмножество шаблонов через запятую",
    )
    parser.add_argument(
        "--npc-policy",
        choices=("off", "legacy", "soar"),
        default="off",
        help="включить ai_model.npc_policy с указанным бэкендом",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=HORIZON,
        help="горизонт симуляции в ходах",
    )
    parser.add_argument(
        "--no-outcome",
        action="store_true",
        help="не проверять исход, чтобы снять полную траекторию",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="писать в JSON траекторию diff и активов поражения",
    )
    parser.add_argument(
        "--bias",
        type=float,
        default=None,
        help="переопределить score_bias шаблона",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=None,
        help="переопределить score_margin шаблона",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=None,
        help="переопределить score_window шаблона",
    )
    parser.add_argument(
        "--defeat",
        default="",
        help="порог поражения side:asset=value через запятую",
    )
    parser.add_argument(
        "--effect-scale",
        type=float,
        default=None,
        help="переопределить model.effect_scale",
    )
    parser.add_argument(
        "--asset-relax",
        type=float,
        default=None,
        help="переопределить model.asset_relax",
    )
    parser.add_argument("--out", default="", help="JSON с записями прогонов")
    args = parser.parse_args(argv)
    seeds = _seeds(args.seeds)
    margins = [float(item) for item in args.margins.split(",") if item.strip()]
    templates = [
        item.strip() for item in args.templates.split(",") if item.strip()
    ]
    if not templates:
        parser.error("--templates не может быть пустым")
    if args.horizon <= 0:
        parser.error("--horizon должен быть положительным")
    defeat_overrides = {}
    for item in args.defeat.split(","):
        item = item.strip()
        if not item:
            continue
        key, _, value = item.partition("=")
        if ":" not in key or not value:
            parser.error("--defeat: ожидается side:asset=value")
        defeat_overrides[key.strip()] = float(value)

    report = {}
    for template_id in templates:
        records = [
            _collect(
                template_id,
                seed,
                npc_policy=args.npc_policy,
                horizon=args.horizon,
                no_outcome=args.no_outcome,
                history=args.history,
                bias=args.bias,
                margin=args.margin,
                window=args.window,
                defeat_overrides=defeat_overrides,
                effect_scale=args.effect_scale,
                asset_relax=args.asset_relax,
            )
            for seed in seeds
        ]
        diffs = [record["diff"] for record in records]
        early = [record for record in records if record.get("finished")]
        print("\n=== %s ===" % template_id)
        print(
            "policy=%s horizon=%d seeds=%d"
            % (args.npc_policy, args.horizon, len(seeds))
        )
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
        early_deaths = [
            record["seed"]
            for record in records
            if record.get("first_death")
            and record["first_death"] <= 3
        ]
        dissolved = [
            (record["seed"], side, turn)
            for record in records
            for side, turn in (record.get("dissolved") or {}).items()
        ]
        spreads = [record.get("final_spread", 0.0) for record in records]
        print(
            "здоровье: смерть на 3-м ходу %d / %d; распадов %d"
            % (len(early_deaths), len(records), len(dissolved))
        )
        if early_deaths:
            print("  ранние смерти, seed: %s" % early_deaths)
        if dissolved:
            print("  распады: %s" % dissolved)
        print(
            "  разброс финальных оценок: mean=%.3f min=%.3f max=%.3f"
            % (
                statistics.mean(spreads),
                min(spreads),
                max(spreads),
            )
        )
        if max(spreads) < 0.02:
            print("  ВНИМАНИЕ: равновесие, фракции не расходятся")
        decisions = [
            record["npc_decisions"]
            for record in records
            if record.get("npc_decisions")
        ]
        if decisions:
            total = sum(item["total"] for item in decisions)
            errors = sum(item["errors"] for item in decisions)
            budget = sum(item["budget"] for item in decisions)
            elapsed = sum(item["elapsed_ms"] for item in decisions)
            evaluated = sum(item["evaluated"] for item in decisions)
            agreement = (
                sum(item["agreements"] for item in decisions)
                / float(evaluated)
                if evaluated
                else None
            )
            print(
                "решения NPC: %d, ошибок %d, бюджет тика %d, "
                "согласие %s, %.1f мс на решение"
                % (
                    total,
                    errors,
                    budget,
                    "%.3f" % agreement if agreement is not None else "—",
                    elapsed / float(total) if total else 0.0,
                )
            )
        bias = records[0]["bias"] if records else 0.0
        print("score_bias из шаблона: %+.3f" % bias)
        print(
            "  оценка по финальному окну; точный перебор streak — "
            "calibrate_outcome_grid.py"
        )
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
            "npc_policy": args.npc_policy,
            "horizon": args.horizon,
            "no_outcome": bool(args.no_outcome),
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
