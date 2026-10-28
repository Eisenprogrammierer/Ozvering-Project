import argparse
import json
import os

from core41 import ArenaEnv, DuelEnv
from core41.types import Transition

from .policies import make_policy


def train(
    episodes=500,
    seed=0,
    policy_name="bdi",
    opponent_name="bdi",
    max_steps=160,
    env_name="arena",
):
    policy = make_policy(policy_name, seed=seed)
    opponent = make_policy(opponent_name, seed=seed + 1)
    if env_name == "duel":
        env = DuelEnv(seed=seed, max_steps=max_steps)
    else:
        env = ArenaEnv(
            seed=seed,
            steps=max_steps,
            policy=policy,
            opponent_policy=opponent,
        )
    wins = 0
    losses = 0
    draws = 0
    for episode in range(episodes):
        observation = env.reset(seed=seed + episode)
        done = False
        info = {}
        while not done:
            actions = env.action_space
            action = policy.act(observation, actions, explore=True)
            if env_name == "duel":
                opponent_actions = env.world.legal_actions("opponent")
                opponent_action = opponent.act(
                    env.world.observe("opponent"),
                    opponent_actions,
                    explore=True,
                )
            else:
                opponent_action = None
            next_observation, reward, done, truncated, info = env.step(
                action, opponent_action=opponent_action
            )
            policy.observe(
                Transition(
                    observation=observation,
                    action=action,
                    reward=reward,
                    next_observation=next_observation,
                    done=done,
                    next_actions=env.action_space,
                    info=dict(info),
                )
            )
            observation = next_observation
        winner = info.get("winner")
        if winner in ("agent", "RL"):
            wins += 1
        elif winner in ("opponent", "AI"):
            losses += 1
        else:
            draws += 1
    return policy, {
        "episodes": episodes,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": wins / max(1, episodes),
        "env": env_name,
    }


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
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    policy, stats = train(
        episodes=args.episodes,
        seed=args.seed,
        policy_name=args.policy,
        opponent_name=args.opponent,
        max_steps=args.max_steps,
        env_name=args.env,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
