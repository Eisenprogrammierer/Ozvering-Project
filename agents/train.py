"""Обучение и оценка политик на арене и кампании.

По умолчанию используется `ArenaEnv` — среда активной арены. `DuelEnv`
остаётся ранним `force`-срезом и включается через `--env duel`.
`CampaignEnv` (`--env campaign`, проблема готовности №6) — дневная среда
над `WorldEngine`: одиночный агент, без оппонента и self-play; награда
собрана из нормированных дельт положения/организации/здоровья/болезни
плюс терминальный бонус исхода сюжета.

Self-play: обе стороны получают собственный `Transition` и обновляют свои
политики. `ArenaEnv` создаёт матч с `auto_learn=False`, поэтому один и тот
же такт не учитывается дважды. Оценка (`evaluate`) всегда идёт на отдельных
held-out seed'ах, без исследования и без обновления весов.
"""

import argparse
import json
import os

from core41 import ArenaEnv, DuelEnv
from core41.types import CampaignAction, Transition

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
    if env_name == "campaign":
        from campaign.env import CampaignEnv

        # max_days берётся из max_steps (число дней горизонта обучения).
        return CampaignEnv(seed=seed, max_days=max_steps, **kwargs)
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
    if getattr(env, "single_agent", False):
        return _play_campaign_episode(
            env,
            policy,
            seed,
            learn=learn,
            explore=explore,
        )
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


def _play_campaign_episode(env, policy, seed, *, learn, explore):
    """Одиночный агент в `CampaignEnv` (проблема готовности №6).

    Кампания — сюжет одного героя против мира: оппонента нет, self-play не
    применяется. Политика получает тот же контракт `Transition`, что и на
    арене; эпизод завершается на терминальном исходе (`done`) или на
    горизонте `max_days` (`truncated`, вопрос §7 №30). Возвращаемый `info`
    содержит ключ `winner` ("agent"/"opponent"), чтобы общий учёт побед
    `_count_winner` работал без разветвлений.
    """
    observation = env.reset(seed=seed)
    done = False
    truncated = False
    info = {}
    while not (done or truncated):
        actions = tuple(env.legal_actions())
        action = policy.act(observation, actions, explore=explore)
        next_observation, reward, done, truncated, step_info = env.step(action)
        if learn:
            policy.observe(
                Transition(
                    observation=observation,
                    action=action,
                    reward=float(reward),
                    next_observation=next_observation,
                    done=bool(done),
                    next_actions=tuple(env.legal_actions()),
                    info=dict(step_info),
                )
            )
        observation = next_observation
        info = step_info
    outcome = str(info.get("outcome") or "")
    return {
        "winner": "agent" if outcome == "win" else "opponent",
        "outcome": outcome,
        "day": int(info.get("day", 0)),
        "truncated": bool(truncated),
    }


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
    """Оценить `policy` против `opponent` на held-out seed'ах.

    Для одиночных сред (`campaign`) аргумент `opponent` игнорируется:
    оценка идёт против детерминированного среза мира `WorldEngine`.
    """
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
    result = {
        "episodes": int(episodes),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": wins / max(1, episodes),
        "seed": int(seed),
        "env": env_name,
    }
    if getattr(env, "single_agent", False):
        # В кампании draw = усечение горизонта без исхода (§7 №30).
        result["draws"] = 0
    return result


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
    single_agent = bool(getattr(env, "single_agent", False))
    wins = 0
    losses = 0
    draws = 0
    for episode in range(episodes):
        info = _play_episode(
            env,
            policy,
            opponent,
            seed + episode,
            self_play=self_play and not single_agent,
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
        "self_play": bool(self_play and not single_agent),
        "policy_updates": int(getattr(policy, "updates", 0)),
        "resumed_from": resume or "",
    }
    if not single_agent:
        stats["opponent_updates"] = int(getattr(opponent, "updates", 0))

    if eval_episodes and not single_agent:
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
        choices=("arena", "duel", "campaign"),
        default="arena",
        help=(
            "arena — активная арена (по умолчанию), duel — ранний срез, "
            "campaign — дневная среда WorldEngine (проблема №6)"
        ),
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
