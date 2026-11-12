"""CLI разбора: python -m campaign.dialogue "фраза"."""

from __future__ import annotations

import argparse
import json

from .loader import load_dialogue
from .morphology import tokenize
from .parser import ChartParser


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Разобрать русскую фразу диалоговым парсером."
    )
    parser.add_argument("text", nargs="+", help="фраза для разбора")
    parser.add_argument(
        "--json",
        action="store_true",
        help="печатать разборы как JSON",
    )
    args = parser.parse_args(argv)
    text = " ".join(args.text)
    catalog = load_dialogue()
    parses = ChartParser(catalog).parse(text)
    if args.json:
        payload = [
            {
                "rule": item.rule,
                "cat": item.cat,
                "text": item.text,
                "features": dict(item.features),
                "sem": item.sem,
            }
            for item in parses
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if parses else 2
    print("Токены:", " / ".join(tokenize(text)))
    if not parses:
        print("Разбор не найден.")
        return 2
    for index, item in enumerate(parses, 1):
        print(
            "%d. %s [%s] %s"
            % (index, item.rule, item.cat, item.text)
        )
        print(
            json.dumps(
                item.sem, ensure_ascii=False, indent=2, sort_keys=True
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
