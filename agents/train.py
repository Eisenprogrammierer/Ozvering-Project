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
held-out seed'ах, без исследования и без обновления весов. В кампании
оппонента нет, поэтому held-out — одна строка «политика против мира», а
усечение горизонта (`truncated`) учитывается как ничья, не поражение.

Доменная рандомизация (проблема готовности №7): флаги `--domain-randomize`
и компания (`--profiles`, `--sickness-min/max`, `--health-factors`,
`--health-min/max`, `--skill-jitter`) заставляют цикл обучения перед каждым
эпизодом брать новый домен через `randomize_draw(rng)` среды и применять
его через `apply_domain(...)`. Draw детерминирован rng'ом с зерном
`seed + 7919`: одна и та же команда даёт одну и ту же последовательность
доменов. Held-out оценка по умолчанию идёт на фиксированном каноническом
домене — иначе матрица силы несравнима между запусками; для оценки по
распределению нужен явный `--eval-domain-randomize` (усреднение по новым
доменам того же распределения).
"""

import argparse
import json
import os
import random

from core41 import ArenaEnv, DuelEnv, randomize_draw
from core41.types import CampaignAction, Transition

from .policies import load_policy, make_policy

WINNERS_RL = ("RL", "agent")
WINNERS_AI = ("AI", "opponent")
# Сдвиг зерна доменного rng от игрового seed: разные потоки случайности,
# воспроизводимые одним и тем же --seed.
DOMAIN_SEED_SALT = 7919
# Политики без ручных весов, которым нужен прогрев перед held-out оценкой.
# Иначе «qtable/mlp» в матрице силы — это случайная таблица/сеть, и строка
# измеряет не baseline, а шум инициализации.
LEARNABLE_EVAL_BASELINES = frozenset(
    {"qtable", "mlp", "qtable-campaign"}
)
DEFAULT_EVAL_BASELINE_EPISODES = 50
# Единые defaults Python API и CLI. Раньше CLI подставлял arena=2000/20,
# а `train()` — 160/0, поэтому одинаковый вызов давал разные эксперименты.
DEFAULT_MAX_STEPS = {"arena": 2000, "duel": 160, "campaign": 30}
DEFAULT_EPISODES = {"arena": 500, "duel": 500, "campaign": 50}
DEFAULT_EVAL_EPISODES = 20
# Отдельный сдвиг зерна прогрева: он не должен совпадать с eval seed'ами.
BASELINE_SEED_SALT = 500003
# Held-out поток для выбора лучшего чекпойнта во время обучения.
BEST_CHECKPOINT_SEED_SALT = 700001


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


def _domain_draw(env, env_name, domain_rng, domain_opts):
    """Один доменный draw (проблема №7) в виде kwargs для `apply_domain`.

    `duel` — легаси-срез без доменных параметров: возвращаем None, чтобы
    цикл обучения честно пропускал рандомизацию, а не молча её имитировал.
    """
    if env_name == "duel":
        return None
    if env_name == "campaign":
        return env.randomize_draw(
            rng=domain_rng,
            skill_jitter=domain_opts.get("skill_jitter", 0.0),
            sickness_min=domain_opts.get("sickness_min", 0.0),
            sickness_max=domain_opts.get("sickness_max", 0.6),
        )
    return randomize_draw(
        rng=domain_rng,
        profiles=domain_opts.get("profiles", ()),
        health_factors=domain_opts.get("health_factors", ()),
        sickness_min=domain_opts.get("sickness_min", 0.0),
        sickness_max=domain_opts.get("sickness_max", 0.6),
        health_min=domain_opts.get("health_min", 0.75),
        health_max=domain_opts.get("health_max", 1.25),
    )


def _apply_domain(env, draw):
    if draw is None:
        return
    env.apply_domain(**draw)


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
    truncated = False
    info = {}
    while not (done or truncated):
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
            truncated,
            info,
        ) = env.step(action, opponent_action=opponent_action)
        next_opponent_observation = env.observe("ai")
        # Таймаут — усечение, а не терминал: `ArenaEnv` уже помечает его
        # `truncated=True`, но `ArenaMatch` завершает партию (`done=True`).
        # Для TD-обновления это не терминальное состояние, иначе политика
        # учится на выдуманном ±1.0 за «кто лучше стоял в REST».
        terminal = bool(done and not truncated)

        if learn:
            policy.observe(
                Transition(
                    observation=observation,
                    action=action,
                    reward=reward,
                    next_observation=next_observation,
                    done=terminal,
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
                        done=terminal,
                        next_actions=env.legal_actions("ai"),
                        info=dict(info),
                    )
                )

        observation = next_observation
        opponent_observation = next_opponent_observation
    if truncated:
        info = dict(info)
        info["winner"] = None
        info["truncated"] = True
    return info


def _play_campaign_episode(env, policy, seed, *, learn, explore):
    """Одиночный агент в `CampaignEnv` (проблема готовности №6).

    Кампания — сюжет одного героя против мира: оппонента нет, self-play не
    применяется. Политика получает тот же контракт `Transition`, что и на
    арене; эпизод завершается на терминальном исходе (`done`) или на
    горизонте `max_days` (`truncated`, вопрос §7 №30). Возвращаемый `info`
    содержит ключ `winner` ("agent" — сюжетный win, "opponent" — lose,
    None — усечение горизонта), чтобы общий учёт `_count_winner` считал
    усечение ничьей, а не поражением.
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
    if truncated and not outcome:
        winner = None
    elif outcome == "win":
        winner = "agent"
    elif outcome == "lose":
        winner = "opponent"
    else:
        winner = None
    return {
        "winner": winner,
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


def _warmup_baseline(
    name,
    seed,
    episodes,
    max_steps,
    env_name,
    env_kwargs,
):
    """Прогреть обучаемый baseline перед held-out матрицей.

    `qtable`/`mlp` без чекпойнта стартуют со случайных весов: их строка в
    матрице силы измеряла бы инициализацию, а не baseline. Здесь политика
    обучается на отдельном потоке seed'ов против стабильного `bdi`, не
    касаясь ни основной политики, ни eval seed'ов. Возвращает
    `(policy, trained_episodes)`; для политик с готовыми весами — `(policy, 0)`.

    Для кампании (`single_agent`) прогрев идёт против детерминированного
    мира: `qtable-campaign`/`mlp` получают тот же шанс, что и аренные
    baseline, иначе их строка измеряла бы случайную инициализацию.
    """
    policy = make_policy(name, seed=seed)
    if name not in LEARNABLE_EVAL_BASELINES or episodes <= 0:
        return policy, 0
    partner = make_policy("bdi", seed=seed + 1)
    env = _make_env(
        env_name,
        seed,
        max_steps,
        policy,
        partner,
        env_kwargs,
    )
    if getattr(env, "single_agent", False):
        for episode in range(int(episodes)):
            _play_campaign_episode(
                env,
                policy,
                seed + episode,
                learn=True,
                explore=True,
            )
        return policy, int(episodes)
    for episode in range(int(episodes)):
        _play_episode(
            env,
            policy,
            partner,
            seed + episode,
            self_play=False,
            learn=True,
            explore=True,
        )
    return policy, int(episodes)


def _save_policy(policy, path):
    """Сохранить политику любого типа (BDI не имеет собственного `save`)."""
    if hasattr(policy, "save"):
        policy.save(path)
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(policy.state_dict(), handle, ensure_ascii=False)


def _seed_out_path(path, seed):
    """Путь чекпойнта для конкретного seed: `model.json` → `model.seed3.json`."""
    stem, suffix = os.path.splitext(path)
    return "%s.seed%d%s" % (stem, int(seed), suffix)


def wilson_interval(successes, trials, z=1.96):
    """Доверительный интервал Уилсона для доли успехов.

    Возвращает `(low, high)` в `[0, 1]`; при `trials = 0` — `(0, 1)`.
    Нужен, чтобы матрица силы не выдавала шум за превосходство политики.
    """
    trials = int(trials)
    if trials <= 0:
        return 0.0, 1.0
    successes = max(0, min(trials, int(successes)))
    p = successes / trials
    z2 = float(z) * float(z)
    denominator = 1.0 + z2 / trials
    center = (p + z2 / (2.0 * trials)) / denominator
    margin = (
        float(z)
        * ((p * (1.0 - p) / trials + z2 / (4.0 * trials * trials)) ** 0.5)
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)



def evaluate(
    policy,
    opponent,
    episodes=20,
    seed=100000,
    max_steps=None,
    env_name="arena",
    env_kwargs=None,
    domain_opts=None,
):
    """Оценить `policy` против `opponent` на held-out seed'ах.

    Для одиночных сред (`campaign`) аргумент `opponent` игнорируется:
    оценка идёт против детерминированного среза мира `WorldEngine`.
    Усечение горизонта считается ничьей (`draws`), а не поражением.

    По умолчанию оценка идёт на фиксированном домене из `env_kwargs` —
    иначе матрица силы несравнима между запусками. Если `domain_opts`
    задан (не None), каждый эпизод получает новый домен из того же
    распределения, что и обучение (усреднение по распределению,
    проблема №7); зерно доменов — отдельное от обучающего.
    """
    env = _make_env(
        env_name,
        seed,
        (
            DEFAULT_MAX_STEPS.get(env_name, 160)
            if max_steps is None
            else int(max_steps)
        ),
        policy,
        opponent,
        env_kwargs,
    )
    domain_rng = (
        random.Random(seed + DOMAIN_SEED_SALT)
        if domain_opts is not None
        else None
    )
    wins = losses = draws = 0
    for episode in range(episodes):
        if domain_rng is not None:
            _apply_domain(env, _domain_draw(env, env_name, domain_rng, domain_opts))
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
        "win_rate_ci": list(wilson_interval(wins, episodes)),
        "seed": int(seed),
        "env": env_name,
    }
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
    max_steps=None,
    env_name="arena",
    env_kwargs=None,
    domain_opts=None,
):
    """Матрица силы: каждая политика против каждого оппонента.

    `policies` и `opponents` — словари `{name: policy}` или пары
    `(name, policy)`. Оценка не меняет веса и не использует exploration.
    `domain_opts` (проблема №7) — усреднение по распределению доменов;
    по умолчанию None — фиксированный канонический домен.
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
                domain_opts=domain_opts,
            )
            row = {"policy": policy_name, "opponent": opponent_name}
            row.update(stats)
            rows.append(row)
    return rows


def train(
    episodes=None,
    seed=0,
    policy_name="bdi",
    opponent_name="bdi",
    max_steps=None,
    env_name="arena",
    self_play=True,
    env_kwargs=None,
    eval_episodes=DEFAULT_EVAL_EPISODES,
    eval_seed=None,
    eval_opponents=(),
    eval_baseline_episodes=DEFAULT_EVAL_BASELINE_EPISODES,
    eval_campaign_baselines=False,
    eval_checkpoints=None,
    resume=None,
    resume_opponent=None,
    domain_randomize=False,
    domain_opts=None,
    eval_domain_randomize=False,
    best_out=None,
    best_every=0,
    best_eval_episodes=5,
):
    # --resume (проблема готовности №5): чекпойнт загружается явно,
    # автопоиска нет. Формат v0 мигрируется внутри load_policy/load_state_dict.
    if episodes is None:
        episodes = DEFAULT_EPISODES.get(env_name, 500)
    episodes = int(episodes)
    if max_steps is None:
        max_steps = DEFAULT_MAX_STEPS.get(env_name, 160)
    max_steps = int(max_steps)
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
    # Доменная рандомизация (проблема №7): rng с солью от seed — одна и та
    # же команда воспроизводит ту же последовательность доменов. `duel` —
    # легаси-срез без доменов: честно сообщаем в stats, что фича не сработала.
    domain_opts = dict(domain_opts or {})
    use_domain = bool(domain_randomize) and env_name != "duel"
    domain_rng = random.Random(seed + DOMAIN_SEED_SALT) if use_domain else None
    wins = 0
    losses = 0
    draws = 0
    best_score = -1.0
    best_episode = 0
    for episode in range(episodes):
        if domain_rng is not None:
            _apply_domain(env, _domain_draw(env, env_name, domain_rng, domain_opts))
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
        if (
            best_out
            and best_every
            and (episode + 1) % int(best_every) == 0
        ):
            probe_seed = seed + BEST_CHECKPOINT_SEED_SALT
            probe = evaluate(
                policy,
                None if single_agent else opponent,
                episodes=int(best_eval_episodes),
                seed=probe_seed,
                max_steps=max_steps,
                env_name=env_name,
                env_kwargs=env_kwargs,
            )
            score = float(probe["win_rate"])
            if score > best_score:
                best_score = score
                best_episode = episode + 1
                _save_policy(policy, best_out)

    stats = {
        "episodes": episodes,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": wins / max(1, episodes),
        "win_rate_ci": list(wilson_interval(wins, episodes)),
        "seed": int(seed),
        "env": env_name,
        "with_env": bool(getattr(env, "with_env", False)),
        "self_play": bool(self_play and not single_agent),
        "policy_updates": int(getattr(policy, "updates", 0)),
        "resumed_from": resume or "",
        "domain_randomize": use_domain,
    }
    if best_out:
        # Если периодическая оценка выключена или не успела сработать,
        # сохраняем финальное состояние: путь всегда существует.
        if best_episode == 0:
            _save_policy(policy, best_out)
            best_episode = int(episodes)
        stats["best_out"] = best_out
        stats["best_episode"] = best_episode
        stats["best_win_rate"] = best_score if best_score >= 0.0 else None
    if not single_agent:
        stats["opponent_updates"] = int(getattr(opponent, "updates", 0))

    if eval_episodes:
        if eval_seed is None:
            eval_seed = seed + 100000
        eval_domain_opts = (
            domain_opts
            if eval_domain_randomize and env_name != "duel"
            else None
        )
        if single_agent:
            # Кампания — один агент против детерминированного мира:
            # матрица «политика × оппонент» выродилась бы в одинаковые
            # строки. Оцениваем одну политику против мира (`opponent:
            # "world"`), сохраняя тот же контракт held-out оценки.
            # `eval_campaign_baselines=True` добавляет warmed baseline-строки
            # (`qtable-campaign`/`mlp`), чтобы кампанийная матрица не
            # измеряла случайную инициализацию. По умолчанию выключено:
            # прогрев кампании дорогой (дни × эпизоды).
            names = [policy_name]
            if eval_campaign_baselines:
                names.extend(
                    name for name in eval_opponents if name not in names
                )
            rows = []
            for index, name in enumerate(names):
                if name == policy_name:
                    candidate = policy
                    source = {
                        "trained_episodes": int(episodes),
                        "policy_source": (
                            resume if resume else "train"
                        ),
                    }
                else:
                    checkpoint = (eval_checkpoints or {}).get(name)
                    if checkpoint:
                        candidate = load_policy(
                            checkpoint, seed=eval_seed + index
                        )
                        source = {
                            "trained_episodes": -1,
                            "policy_source": checkpoint,
                        }
                    else:
                        candidate, trained = _warmup_baseline(
                            name,
                            eval_seed + BASELINE_SEED_SALT + index * 101,
                            eval_baseline_episodes,
                            max_steps,
                            env_name,
                            env_kwargs,
                        )
                        source = {
                            "trained_episodes": trained,
                            "policy_source": (
                                "warmup" if trained else "builtin"
                            ),
                        }
                row = dict(
                    evaluate(
                        candidate,
                        None,
                        episodes=eval_episodes,
                        seed=eval_seed,
                        max_steps=max_steps,
                        env_name=env_name,
                        env_kwargs=env_kwargs,
                        domain_opts=eval_domain_opts,
                    ),
                    policy=name,
                    opponent="world",
                )
                row.update(source)
                rows.append(row)
            stats["eval"] = rows
        else:
            names = tuple(eval_opponents) or (opponent_name,)
            opponents = {}
            sources = {}
            for index, name in enumerate(names):
                checkpoint = (eval_checkpoints or {}).get(name)
                if checkpoint:
                    opponents[name] = load_policy(
                        checkpoint, seed=eval_seed + index
                    )
                    sources[name] = {
                        "trained_episodes": -1,
                        "policy_source": checkpoint,
                    }
                else:
                    baseline, trained = _warmup_baseline(
                        name,
                        eval_seed + BASELINE_SEED_SALT + index * 101,
                        eval_baseline_episodes,
                        max_steps,
                        env_name,
                        env_kwargs,
                    )
                    opponents[name] = baseline
                    sources[name] = {
                        "trained_episodes": trained,
                        "policy_source": (
                            "warmup" if trained else "builtin"
                        ),
                    }
            stats["eval"] = evaluate_matrix(
                {policy_name: policy},
                opponents,
                episodes=eval_episodes,
                seed=eval_seed,
                max_steps=max_steps,
                env_name=env_name,
                env_kwargs=env_kwargs,
                domain_opts=eval_domain_opts,
            )
            for row in stats["eval"]:
                row.update(sources.get(row["opponent"], {}))
        if eval_domain_opts is not None:
            for row in stats["eval"]:
                row["domain_randomized"] = True
    return policy, stats


def _train_seed_worker(payload):
    """Один seed для `train_seeds`; верхнеуровневый, чтобы работать в pool."""
    seed, kwargs = payload
    policy, stats = train(seed=seed, **kwargs)
    return {"stats": stats, "policy_state": policy.state_dict()}


def train_seeds(
    seeds=1,
    workers=1,
    base_seed=0,
    **kwargs,
):
    """Обучить несколько seed'ов и агрегировать win-rate.

    `workers > 1` запускает seed'ы в `ProcessPoolExecutor`; `workers=1`
    выполняет их последовательно (удобно для отладки и тестов). Агрегат
    считает pooled Wilson CI по сумме побед/эпизодов, а не среднее
    интервалов: так он остаётся корректным при разном числе эпизодов.

    Возвращает `{"runs": [...], "aggregate": {...}}`, где каждый run —
    `{"stats": ..., "policy_state": ...}`. Сохранение чекпойнтов делает
    вызывающий код: путь и политика остаются его ответственностью.
    """
    seeds = max(1, int(seeds))
    seed_list = [int(base_seed) + index for index in range(seeds)]
    base_kwargs = dict(kwargs)
    payloads = []
    for seed in seed_list:
        local = dict(base_kwargs)
        # `--save-best` в параллельном режиме не должен гоняться за один
        # путь: каждый seed пишет свой чекпойнт.
        if local.get("best_out"):
            local["best_out"] = _seed_out_path(local["best_out"], seed)
        payloads.append((seed, local))
    if workers and int(workers) > 1 and seeds > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(
            max_workers=min(int(workers), seeds)
        ) as pool:
            runs = list(pool.map(_train_seed_worker, payloads))
    else:
        runs = [_train_seed_worker(payload) for payload in payloads]
    stats_rows = [run["stats"] for run in runs]
    episodes = sum(int(row.get("episodes", 0)) for row in stats_rows)
    wins = sum(int(row.get("wins", 0)) for row in stats_rows)
    losses = sum(int(row.get("losses", 0)) for row in stats_rows)
    draws = sum(int(row.get("draws", 0)) for row in stats_rows)
    aggregate = {
        "seeds": seed_list,
        "runs": len(stats_rows),
        "episodes": episodes,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "mean_win_rate": (
            sum(float(row.get("win_rate", 0.0)) for row in stats_rows)
            / max(1, len(stats_rows))
        ),
        "win_rate": wins / max(1, episodes),
        "win_rate_ci": list(wilson_interval(wins, episodes)),
        "with_env": (
            stats_rows[0].get("with_env") if stats_rows else None
        ),
        "env": stats_rows[0].get("env") if stats_rows else "",
        "workers": max(1, int(workers or 1)),
    }
    return {"runs": runs, "aggregate": aggregate}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--episodes",
        type=int,
        default=None,
        help=(
            "эпизодов обучения; по умолчанию 500 для arena/duel и 50 для "
            "campaign"
        ),
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--seeds",
        type=int,
        default=1,
        help=(
            "сколько seed'ов обучить подряд (seed, seed+1, …) и "
            "агрегировать; 1 — обычный одиночный запуск"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "параллельные процессы для --seeds > 1; 1 — последовательно"
        ),
    )
    parser.add_argument("--policy", default="bdi")
    parser.add_argument("--opponent", default="bdi")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help=(
            "горизонт эпизода; по умолчанию 2000 для arena, 160 для duel "
            "и 30 дней для campaign"
        ),
    )
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
        "--no-with-env",
        action="store_true",
        help=(
            "отключить актор среды ArenaEnvironment (контрольное плечо); "
            "по умолчанию обучение и оценка идут со средой, как активная игра"
        ),
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
        "--eval-baseline-episodes",
        type=int,
        default=DEFAULT_EVAL_BASELINE_EPISODES,
        help=(
            "сколько эпизодов прогреть обучаемый baseline (qtable/mlp) "
            "перед held-out оценкой; 0 — не греть"
        ),
    )
    parser.add_argument(
        "--eval-campaign-baselines",
        action="store_true",
        help=(
            "в кампании добавить в held-out матрицу warmed baseline-строки "
            "(qtable-campaign/mlp); дороже, по умолчанию только основная "
            "политика против мира"
        ),
    )
    parser.add_argument(
        "--save-best",
        default="",
        metavar="PATH",
        help=(
            "сохранять чекпойнт с лучшим held-out win_rate во время обучения "
            "(production-выбор чекпойнта)"
        ),
    )
    parser.add_argument(
        "--best-every",
        type=int,
        default=50,
        help="как часто (в эпизодах) оценивать политику для --save-best",
    )
    parser.add_argument(
        "--best-eval-episodes",
        type=int,
        default=5,
        help="эпизодов held-out оценки для --save-best",
    )
    parser.add_argument(
        "--eval-checkpoint",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help=(
            "готовый чекпойнт baseline для оценки (можно несколько раз); "
            "переопределяет прогрев для этого имени"
        ),
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
    # Доменная рандомизация (проблема готовности №7).
    parser.add_argument(
        "--domain-randomize",
        action="store_true",
        help=(
            "новый домен перед каждым обучающим эпизодом (arena/campaign); "
            "для --env duel игнорируется (легаси-срез без доменов)"
        ),
    )
    parser.add_argument(
        "--eval-domain-randomize",
        action="store_true",
        help=(
            "усреднять held-out оценку по распределению доменов; по "
            "умолчанию оценка идёт на фиксированном каноническом домене, "
            "чтобы матрица силы была сравнима между запусками"
        ),
    )
    parser.add_argument(
        "--profiles",
        default="",
        help="профили арены для жеребьёвки через запятую (CANON,ZEALOT,ORTHODOX)",
    )
    parser.add_argument(
        "--sickness-min",
        type=float,
        default=0.0,
        help="нижняя граница стартовой болезни в домене",
    )
    parser.add_argument(
        "--sickness-max",
        type=float,
        default=0.6,
        help="верхняя граница стартовой болезни в домене",
    )
    parser.add_argument(
        "--health-factors",
        default="",
        help="факторы здоровья с джиттером через запятую (aging,illness,stress,care)",
    )
    parser.add_argument(
        "--health-min",
        type=float,
        default=0.75,
        help="нижний множитель выбираемых health-факторов",
    )
    parser.add_argument(
        "--health-max",
        type=float,
        default=1.25,
        help="верхний множитель выбираемых health-факторов",
    )
    parser.add_argument(
        "--skill-jitter",
        type=float,
        default=0.0,
        help="относительный джиттер навыков профиля кампании (0.25 = ±25%%)",
    )
    parser.add_argument("--out", default="")
    parser.add_argument("--eval-out", default="")
    args = parser.parse_args(argv)
    max_steps = args.max_steps
    if max_steps is None:
        max_steps = {"arena": 2000, "duel": 160, "campaign": 30}[args.env]
    eval_opponents = tuple(
        name.strip()
        for name in args.eval_opponents.split(",")
        if name.strip()
    )
    eval_checkpoints = {}
    for item in args.eval_checkpoint:
        name, separator, path = item.partition("=")
        name = name.strip()
        path = path.strip()
        if not separator or not name or not path:
            parser.error(
                "--eval-checkpoint ожидает NAME=PATH, получено %r" % item
            )
        eval_checkpoints[name] = path
    domain_opts = {
        "profiles": tuple(
            name.strip().upper()
            for name in args.profiles.split(",")
            if name.strip()
        ),
        "health_factors": tuple(
            name.strip()
            for name in args.health_factors.split(",")
            if name.strip()
        ),
        "sickness_min": args.sickness_min,
        "sickness_max": args.sickness_max,
        "health_min": args.health_min,
        "health_max": args.health_max,
        "skill_jitter": args.skill_jitter,
    }
    env_kwargs = {}
    if args.env == "arena" and args.no_with_env:
        env_kwargs["with_env"] = False
    train_kwargs = dict(
        episodes=args.episodes,
        policy_name=args.policy,
        opponent_name=args.opponent,
        max_steps=max_steps,
        env_name=args.env,
        env_kwargs=env_kwargs or None,
        self_play=not args.no_self_play,
        eval_episodes=args.eval_episodes,
        eval_seed=args.eval_seed,
        eval_opponents=eval_opponents,
        eval_baseline_episodes=args.eval_baseline_episodes,
        eval_campaign_baselines=args.eval_campaign_baselines,
        eval_checkpoints=eval_checkpoints,
        resume=args.resume or None,
        resume_opponent=args.resume_opponent or None,
        domain_randomize=args.domain_randomize,
        domain_opts=domain_opts,
        eval_domain_randomize=args.eval_domain_randomize,
        best_out=args.save_best or None,
        best_every=args.best_every,
        best_eval_episodes=args.best_eval_episodes,
    )
    if args.seeds > 1:
        result = train_seeds(
            seeds=args.seeds,
            workers=args.workers,
            base_seed=args.seed,
            **train_kwargs,
        )
        print(json.dumps(result["aggregate"], ensure_ascii=False))
        if args.out:
            for run in result["runs"]:
                seed = int(run["stats"].get("seed", args.seed))
                path = _seed_out_path(args.out, seed)
                directory = os.path.dirname(path)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(
                        run["policy_state"], handle, ensure_ascii=False
                    )
        if args.eval_out:
            directory = os.path.dirname(args.eval_out)
            if directory:
                os.makedirs(directory, exist_ok=True)
            payload = [
                {
                    "seed": run["stats"].get("seed"),
                    "eval": run["stats"].get("eval", []),
                }
                for run in result["runs"]
            ]
            with open(args.eval_out, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
        return 0
    policy, stats = train(seed=args.seed, **train_kwargs)
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
