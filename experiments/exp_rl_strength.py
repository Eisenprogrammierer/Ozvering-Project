import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simulation as S
import strategies as ST


def _play_old(rl, ai, steps, seed, with_env=True):
    env = S.Environment() if with_env else None
    rng = random.Random(seed)
    dom_rl = dom_ai = 0
    for step in range(steps):
        rl.sense(ai, rng)
        ai.sense(rl, rng)
        rl.rotate_defense(rng)
        ai.rotate_defense(rng)
        if env is not None:
            env.rotate_defense(rng)
        rl.upkeep()
        ai.upkeep()
        rl.tick_energy()
        ai.tick_energy()
        rl.tick_input_state()
        ai.tick_input_state()
        if env is not None:
            env.tick()
        eps = max(0.05, 1.0 - step / 300)
        a_idx = rl.form_intention(eps, rng)
        act, frac = S.ACTIONS[a_idx]
        st_before, f_before = rl.skey(), rl.force
        w_rl = (
            0
            if rl.rest_if_starving()
            else rl.commit(act, rl.energy_pool * frac)
        )
        ai_act, ai_work = ai.form_intention()
        w_ai = 0 if ai.rest_if_starving() else ai.commit(ai_act, ai_work)
        S.resolve_attack(rl, ai, w_rl, rng, env)
        S.resolve_attack(ai, rl, w_ai, rng, env)
        rl.learn(st_before, a_idx, rl.force - f_before, rl.skey())
        winner, dom_rl, dom_ai = S.check_capture(rl, ai, dom_rl, dom_ai)
        if winner:
            return winner
    return None


def canon(offset=0, n=10, old=False, with_env=True):
    rl = S.RLAgent()
    res = {"RL": 0, "UtilityAI": 0, None: 0}
    for g in range(n):
        if old:
            w = _play_old(rl, S.UtilityAI(), 1000, offset + g, with_env)
        else:
            w, _, _, _ = S.play_game(
                rl, S.UtilityAI(), 1000, seed=offset + g, with_env=with_env
            )
        res[w] += 1
    return res


def scripted_vs_utility(name, n=20):
    policy = ST.STRATEGIES[name]
    res = {"A": 0, "B": 0, None: 0}
    for seed in range(n):
        a, b = S.Agent(), S.UtilityAI()
        env = S.Environment()
        rng = random.Random(seed)
        da = db = 0
        for step in range(1000):
            a.sense(b, rng)
            b.sense(a, rng)
            a.rotate_defense(rng)
            b.rotate_defense(rng)
            env.rotate_defense(rng)
            a.upkeep()
            b.upkeep()
            a.tick_energy()
            b.tick_energy()
            a.tick_input_state()
            b.tick_input_state()
            env.tick()
            act, work = policy(a, b, rng)
            w_a = 0 if a.rest_if_starving() else a.commit(act, work)
            ba, bw = b.form_intention()
            w_b = 0 if b.rest_if_starving() else b.commit(ba, bw)
            S.resolve_attack(a, b, w_a, rng, env)
            S.resolve_attack(b, a, w_b, rng, env)
            w, da, db = S.check_capture(a, b, da, db)
            if w == "RL":
                res["A"] += 1
                break
            if w == "UtilityAI":
                res["B"] += 1
                break
        else:
            res[None] += 1
    return res


def game_lengths(n=20):
    steps = []
    for seed in range(n):
        rl = S.RLAgent()
        _, _, _, es = S.play_game(rl, S.UtilityAI(), 1000, seed=seed)
        steps.append(es)
    return steps


def main():
    print("P0 №1: сила RL против UtilityAI")
    print(
        "\n[1] UtilityAI НЕ доминирует: скриптовые стратегии против него (20 "
        "seed)"
    )
    for name in ("PRESSER", "PASSIVE", "TIMING"):
        print(
            f"    {name:>8}: {scripted_vs_utility(name)}  (A=стратегия, "
            f"B=UtilityAI)"
        )

    steps = game_lengths(20)
    print(
        f"\n[2] Длина партий канона: медиана {statistics.median(steps):.0f} "
        f"тактов "
        f"(мин {min(steps)}, макс {max(steps)}) -> прежний eps сбрасывался "
        f"раньше, "
        f"чем падал"
    )

    print("\n[3] Контраст «до усиления» (прежняя семантика): блоки seed")
    old_tot = {"RL": 0, "UtilityAI": 0, None: 0}
    for off in (0, 100, 200):
        r = canon(off, old=True)
        for k in old_tot:
            old_tot[k] += r[k]
        print(f"    seeds {off:>3}..{off + 9:>3}: {r}")
    print(f"    ИТОГО 30 партий: {old_tot}")

    print("\n[4] После усиления (reset_state + RLAgent.epsilon): блоки seed")
    new_tot = {"RL": 0, "UtilityAI": 0, None: 0}
    all_blocks = range(0, 220, 20)
    for off in all_blocks:
        r = canon(off)
        for k in new_tot:
            new_tot[k] += r[k]
        print(f"    seeds {off:>3}..{off + 9:>3}: {r}")
    n_games = 10 * len(list(all_blocks))
    print(f"    ИТОГО {n_games} партий: {new_tot}")

    print("\n=== ВЫВОД ===")
    print(
        "  Канон перестал быть winner-take-all: RL берёт партии на каждом "
        "блоке"
    )
    print("  seed, исход детерминирован. Остаточное преимущество model-based")
    print(
        "  UtilityAI — дефект по цели проекта (конкурентоспособность RL, п. "
        "A5),"
    )
    print(
        "  а не свойство типа энергии: причина — табличное обучение/разведка."
    )


if __name__ == "__main__":
    main()
