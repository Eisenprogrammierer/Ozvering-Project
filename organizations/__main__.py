from __future__ import annotations

import argparse
import json
from pathlib import Path

from automata.storage import AutomataStore

from .examples import analyze_scenario, get_scenarios
from .generator import build_automaton, save_automaton


def _default_out():
    return Path(__file__).resolve().parents[1] / "configs" / "automata"


def _run_runtime(turns=12):
    from .runtime import build_runtime_demo

    sim, organization = build_runtime_demo(turns=turns)
    summary = sim.run()
    info = summary["organizations"][0]
    analysis = organization.analysis
    need = analysis.need_ru if analysis else "—"
    print("runtime: %s (%s)" % (info["name"], info["side"]))
    print(
        "  фаза: %s; приоритет: %s; уровень: %d; активных: %d/%d (%.0f%%)"
        % (
            info["phase"],
            need,
            info["level"],
            info["active_count"],
            info["initial_count"],
            100.0 * info["willing_share"],
        )
    )
    print(
        "  такт: %d; тактов симуляции: %d; победитель: %s"
        % (info["tick"], summary["turn"], summary["winner"] or "—")
    )
    events = [
        event
        for event in summary["events"]
        if event["kind"].startswith("organization")
    ]
    for event in events:
        print("  [%s] %s" % (event["kind"], event["text"]))
    return 0


def main(argv=None):
    scenarios = get_scenarios()
    slugs = [scenario.slug for scenario in scenarios]
    parser = argparse.ArgumentParser(
        prog="python3 -m organizations",
        description="Аналитический генератор организаций-суперсистем",
    )
    parser.add_argument(
        "--scenario",
        choices=["all"] + slugs,
        default="all",
        help="какой эталонный сценарий обработать",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="записать автоматы в configs/automata/ (или --out)",
    )
    parser.add_argument(
        "--out",
        default=str(_default_out()),
        help="каталог для --write (по умолчанию configs/automata)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="напечатать JSON одного автомата (требует --scenario)",
    )
    parser.add_argument(
        "--name-seed",
        type=int,
        default=None,
        help="seed естественного названия (по умолчанию — из разбора)",
    )
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="прогнать warfare-демо с OrganizationRuntime",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=12,
        help="длина runtime-демо в тактах (по умолчанию 12)",
    )
    args = parser.parse_args(argv)

    if args.runtime:
        if args.write or args.json or args.scenario != "all":
            parser.error("--runtime несовместим с --write/--json/--scenario")
        return _run_runtime(args.turns)

    selected = [
        scenario
        for scenario in scenarios
        if args.scenario == "all" or scenario.slug == args.scenario
    ]
    if args.json and len(selected) != 1:
        parser.error("--json требует конкретный --scenario, не all")

    store = AutomataStore(args.out) if args.write else None
    for scenario in selected:
        analysis = analyze_scenario(scenario)
        automaton = build_automaton(analysis, seed=args.name_seed)
        if args.json:
            print(
                json.dumps(automaton.to_dict(), ensure_ascii=False, indent=2)
            )
            continue
        slug = ""
        if store is not None:
            slug = save_automaton(
                analysis, store, scenario.slug, seed=args.name_seed
            )
        print(
            "%-22s need=%-12s L=%d %-24s willing=%d/%d%s"
            % (
                scenario.slug,
                analysis.need_ru,
                analysis.level,
                analysis.archetype,
                analysis.active_count,
                analysis.initial_count,
                (" -> %s.json" % slug) if slug else "",
            )
        )
        if args.write:
            print("  " + " | ".join(analysis.summary_lines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
