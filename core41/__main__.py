from __future__ import annotations

import argparse

from .arena import ArenaMatch
from .types import Action


class _AggressivePolicy:
    def act(self, observation, actions, explore=True):
        for action in actions:
            if action.kind == "WORK" and action.form == "force":
                return action
        if actions:
            return actions[0]
        return Action("REST", form="rest")

    def observe(self, transition):
        return None

    def state_dict(self):
        return {"kind": "aggressive"}

    def load_state_dict(self, state):
        return None


def _demo(seed, steps):
    match = ArenaMatch(
        seed=seed,
        steps=steps,
        rl_policy=_AggressivePolicy(),
        ai_policy=_AggressivePolicy(),
        fog=False,
    )
    while not match.finished:
        match.step_tick()
    if match.winner == "draw":
        winner = "ничья"
    elif match.winner:
        winner = match.winner
    else:
        winner = "лимит шагов"
    print("арена: шагов=%d; победитель=%s" % (match.step, winner))
    print("  сила RL/AI: %.1f / %.1f" % (match.rl.force, match.ai.force))
    print(
        "  здоровье RL/AI: %.1f / %.1f"
        % (match.rl.health, match.ai.health)
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python3 -m core41",
        description="Ядро арены и успеха: библиотека, а не игра.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="короткий детерминированный бой на арене",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="зерно демонстрационного боя",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=40,
        help="лимит шагов демонстрационного боя",
    )
    args = parser.parse_args(argv)
    if args.demo:
        return _demo(args.seed, args.steps)
    print("core41 — библиотека ядра, а не точка входа.")
    print("Запуск арены: python3 main.py --arena")
    print("Кампания:     python3 main.py --view")
    print("Демо ядра:    python3 -m core41 --demo")
    print("Импорт:       from core41 import ArenaMatch,")
    print("              success_probability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
