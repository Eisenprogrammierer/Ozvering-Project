"""Обучение и оценка политик на арене.

По умолчанию используется `ArenaEnv` — среда активной арены. `DuelEnv`
остаётся ранним `force`-срезом и включается через `--env duel`.

Self-play: обе стороны получают собственный `Transition` и обновляют свои
политики. `ArenaEnv` создаёт матч с `auto_learn=False`, поэтому один и тот
же такт не учитывается дважды. Оценка (`evaluate`) всегда идёт на отдельных
held-out seed'ах, без исследования и без обновления весов.
"""

import argparse
import json
import os

from core41 import ArenaEnv, DuelEnv
from core41.types import Transition

from .policies import load_policy, make_policy

WINNERS_RL = ("RL", "agent")
WINNERS_AI = ("AI", "opponent")


def _make_env(
    env_name,
    seed,
    max_steps,
    policy,
    opponent,
    env_kwargs=None,
):
    kwargs = dict(env_kwargs or {})
    if env_name == "duel":
        return DuelEnv(seed=seed, max_steps=max_steps)
    return ArenaEnv(
        seed=seed,
        steps=max_steps,
        policy=policy,
        opponent_policy=opponent,
        **kwargs,
    )


def _reward_for(env, side):
    """Награда стороны с учётом разных ключей `ArenaEnv`/`DuelEnv`."""
    rewards = getattr(env, "last_rewards", {}) or {}
    if side == "rl":
        return float(rewards.get("rl", rewards.get("agent", 0.0)))
    return float(rewards.get("ai", rewards.get("opponent", 0.0)))


def _play_episode(
    env,
    policy,
    opponent,
    seed,
    *,
    self_play,
    learn,
    explore,
):
    observation = env.reset(seed=seed)
    opponent_observation = env.observe("ai")
    done = False
    info = {}
    while not done:
        actions = env.legal_actions("rl")
        action = policy.act(observation, actions, explore=explore)
        opponent_actions = env.legal_actions("ai")
        opponent_action = opponent.act(
            opponent_observation,
            opponent_actions,
            explore=explore,
        )
        (
            next_observation,
            reward,
            done,
            _truncated,
            info,
        ) = env.step(action, opponent_action=opponent_action)
        next_opponent_observation = env.observe("ai")

        if learn:
            policy.observe(
                Transition(
                    observation=observation,
                    action=action,
                    reward=reward,
                    next_observation=next_observation,
                    done=done,
                    next_actions=env.legal_actions("rl"),
                    info=dict(info),
                )
            )
            if self_play:
                opponent.observe(
                    Transition(
                        observation=opponent_observation,
                        action=opponent_action,
                        reward=_reward_for(env, "ai"),
                        next_observation=next_opponent_observation,
                        done=done,
                        next_actions=env.legal_actions("ai"),
                        info=dict(info),
                    )
                )

        observation = next_observation
        opponent_observation = next_opponent_observation
    return info


def _count_winner(info, wins, losses, draws):
    winner = info.get("winner")
    if winner in WINNERS_RL:
        return wins + 1, losses, draws
    if winner in WINNERS_AI:
        return wins, losses + 1, draws
    return wins, losses, draws + 1


def evaluate(
    policy,
    opponent,
    episodes=20,
    seed=100000,
    max_steps=160,
    env_name="arena",
    env_kwargs=None,
):
    """Оценить `policy` против `opponent` на held-out seed'ах."""
    env = _make_env(
        env_name,
        seed,
        max_steps,
        policy,
        opponent,
        env_kwargs,
    )
    wins = losses = draws = 0
    for episode in range(episodes):
        info = _play_episode(
            env,
            policy,
            opponent,
            seed + episode,
            self_play=False,
            learn=False,
            explore=False,
        )
        wins, losses, draws = _count_winner(info, wins, losses, draws)
    return {
        "episodes": int(episodes),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": wins / max(1, episodes),
        "seed": int(seed),
        "env": env_name,
    }


def _named(items):
    if isinstance(items, dict):
        return list(items.items())
    return list(items)


def evaluate_matrix(
    policies,
    opponents,
    episodes=20,
    seed=100000,
    max_steps=160,
    env_name="arena",
    env_kwargs=None,
):
    """Матрица силы: каждая политика против каждого оппонента.

    `policies` и `opponents` — словари `{name: policy}` или пары
    `(name, policy)`. Оценка не меняет веса и не использует exploration.
    """
    rows = []
    for policy_name, policy in _named(policies):
        for opponent_name, opponent in _named(opponents):
            stats = evaluate(
                policy,
                opponent,
                episodes=episodes,
                seed=seed,
                max_steps=max_steps,
                env_name=env_name,
                env_kwargs=env_kwargs,
            )
            row = {"policy": policy_name, "opponent": opponent_name}
            row.update(stats)
            rows.append(row)
    return rows


def train(
    episodes=500,
    seed=0,
    policy_name="bdi",
    opponent_name="bdi",
    max_steps=160,
    env_name="arena",
    self_play=True,
    env_kwargs=None,
    eval_episodes=0,
    eval_seed=None,
    eval_opponents=(),
    resume=None,
    resume_opponent=None,
):
    # --resume (проблема готовности №5): чекпойнт загружается явно,
    # автопоиска нет. Формат v0 мигрируется внутри load_policy/load_state_dict.
    if resume:
        policy = load_policy(resume, seed=seed)
    else:
        policy = make_policy(policy_name, seed=seed)
    if resume_opponent:
        opponent = load_policy(resume_opponent, seed=seed + 1)
    else:
        opponent = make_policy(opponent_name, seed=seed + 1)
    env = _make_env(
        env_name,
        seed,
        max_steps,
        policy,
        opponent,
        env_kwargs,
    )
    wins = 0
    losses = 0
    draws = 0
    for episode in range(episodes):
        info = _play_episode(
            env,
            policy,
            opponent,
            seed + episode,
            self_play=self_play,
            learn=True,
            explore=True,
        )
        wins, losses, draws = _count_winner(info, wins, losses, draws)

    stats = {
        "episodes": episodes,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": wins / max(1, episodes),
        "env": env_name,
        "self_play": bool(self_play),
        "policy_updates": int(getattr(policy, "updates", 0)),
        "opponent_updates": int(getattr(opponent, "updates", 0)),
        "resumed_from": resume or "",
    }

    if eval_episodes:
        if eval_seed is None:
            eval_seed = seed + 100000
        names = tuple(eval_opponents) or (opponent_name,)
        opponents = {
            name: make_policy(name, seed=eval_seed + index)
            for index, name in enumerate(names)
        }
        stats["eval"] = evaluate_matrix(
            {policy_name: policy},
            opponents,
            episodes=eval_episodes,
            seed=eval_seed,
            max_steps=max_steps,
            env_name=env_name,
            env_kwargs=env_kwargs,
        )
    return policy, stats


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=500)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--policy", default="bdi")
    parser.add_argument("--opponent", default="bdi")
    parser.add_argument("--max-steps", type=int, default=160)
    parser.add_argument(
        "--env",
        choices=("arena", "duel"),
        default="arena",
        help="arena — активная арена (по умолчанию), duel — ранний срез",
    )
    parser.add_argument(
        "--no-self-play",
        action="store_true",
        help="не обучать политику противника",
    )
    parser.add_argument(
        "--eval-episodes",
        type=int,
        default=20,
        help="партий на каждого оппонента в held-out оценке; 0 — выключить",
    )
    parser.add_argument(
        "--eval-seed",
        type=int,
        default=100000,
        help="начальный seed held-out оценки",
    )
    parser.add_argument(
        "--eval-opponents",
        default="bdi,qtable,random,mlp",
        help="имена оппонентов для матрицы силы через запятую",
    )
    parser.add_argument(
        "--resume",
        default="",
        help="явный чекпойнт стартовых весов обучаемой политики "
        "(без автопоиска; формат v0 мигрируется)",
    )
    parser.add_argument(
        "--resume-opponent",
        default="",
        help="явный чекпойнт стартовых весов политики противника",
    )
    parser.add_argument("--out", default="")
    parser.add_argument("--eval-out", default="")
    args = parser.parse_args(argv)
    eval_opponents = tuple(
        name.strip()
        for name in args.eval_opponents.split(",")
        if name.strip()
    )
    policy, stats = train(
        episodes=args.episodes,
        seed=args.seed,
        policy_name=args.policy,
        opponent_name=args.opponent,
        max_steps=args.max_steps,
        env_name=args.env,
        self_play=not args.no_self_play,
        eval_episodes=args.eval_episodes,
        eval_seed=args.eval_seed,
        eval_opponents=eval_opponents,
        resume=args.resume or None,
        resume_opponent=args.resume_opponent or None,
    )
    print(json.dumps(stats, ensure_ascii=False))
    if args.out:
        directory = os.path.dirname(args.out)
        if directory:
            os.makedirs(directory, exist_ok=True)
        save = getattr(policy, "save", None)
        if save is None:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(policy.state_dict(), handle, ensure_ascii=False)
        else:
            save(args.out)
    if args.eval_out:
        directory = os.path.dirname(args.eval_out)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(args.eval_out, "w", encoding="utf-8") as handle:
            json.dump(stats.get("eval", []), handle, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
