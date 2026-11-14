"""CLI текстовой RPG D7.0.

``python -m campaign.dialogue.textgame --side red --allow-actions``
"""

from __future__ import annotations

import argparse

from .console import TextGame
from .repl import DEFAULT_TEMPLATES, build_session


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Текстовая RPG: фразы, действия, история и откат."
    )
    parser.add_argument("--side", default="red",
                        choices=sorted(DEFAULT_TEMPLATES))
    parser.add_argument("--template", default="")
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--character", default="")
    parser.add_argument("--allow-actions", action="store_true")
    args = parser.parse_args(argv)

    session = build_session(
        args.side,
        args.template,
        args.seed,
        args.character,
        allow_actions=args.allow_actions,
    )
    game = TextGame(session)
    print("Текстовая RPG. /help — команды, /quit — выход.")
    while not game.closed:
        try:
            text = input("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text.strip():
            continue
        entry = game.submit(text)
        print(entry.reply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
