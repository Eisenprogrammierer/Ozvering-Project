"""CLI: ``python3 -m organizations``.

Без флагов печатает разбор четырёх эталонных сценариев. С ``--write`` пишет
JSON-автоматы в ``configs/automata/`` (или в ``--out``) для редактора
``automata``. С ``--json`` печатает один автомат целиком.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from automata.storage import AutomataStore

from .examples import analyze_scenario, get_scenarios
from .generator import build_automaton, save_automaton


def _default_out():
    return Path(__file__).resolve().parents[1] / "configs" / "automata"


def main(argv=None):
    scenarios = get_scenarios()
    slugs = [scenario.slug for scenario in scenarios]
    parser = argparse.ArgumentParser(
        prog="python3 -m organizations",
        description="Аналитический генератор организаций-суперсистем")
    parser.add_argument(
        "--scenario", choices=["all"] + slugs, default="all",
        help="какой эталонный сценарий обработать")
    parser.add_argument(
        "--write", action="store_true",
        help="записать автоматы в configs/automata/ (или --out)")
    parser.add_argument(
        "--out", default=str(_default_out()),
        help="каталог для --write (по умолчанию configs/automata)")
    parser.add_argument(
        "--json", action="store_true",
        help="напечатать JSON одного автомата (требует --scenario)")
    args = parser.parse_args(argv)

    selected = [
        scenario for scenario in scenarios
        if args.scenario == "all" or scenario.slug == args.scenario
    ]
    if args.json and len(selected) != 1:
        parser.error("--json требует конкретный --scenario, не all")

    store = AutomataStore(args.out) if args.write else None
    for scenario in selected:
        analysis = analyze_scenario(scenario)
        automaton = build_automaton(analysis)
        if args.json:
            print(json.dumps(
                automaton.to_dict(), ensure_ascii=False, indent=2))
            continue
        slug = ""
        if store is not None:
            slug = save_automaton(analysis, store, scenario.slug)
        print(
            "%-22s need=%-12s L=%d %-24s willing=%d/%d%s"
            % (scenario.slug, analysis.need_ru, analysis.level,
               analysis.archetype, analysis.active_count,
               analysis.initial_count,
               (" -> %s.json" % slug) if slug else ""))
        if args.write:
            print("  " + " | ".join(analysis.summary_lines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
