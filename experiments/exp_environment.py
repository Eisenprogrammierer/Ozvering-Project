import os
import sys
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation import (
    RLAgent,
    UtilityAI,
    Environment,
    Agent,
    play_game,
    ENV_BONUS,
    ENV_INCOME,
)

N_GAMES = 6
STEPS = 400


def run_arm(with_env):
    rl = RLAgent()
    wins = {"RL": 0, "UtilityAI": 0, None: 0}
    finals_rl, finals_ai = [], []
    for g in range(N_GAMES):
        winner, rl_hist, ai_hist, end_step = play_game(
            rl, UtilityAI(), STEPS, seed=g, with_env=with_env
        )
        wins[winner] += 1
        finals_rl.append(rl_hist[-1])
        finals_ai.append(ai_hist[-1])
    return wins, finals_rl, finals_ai


def main():
    print(
        "=== Контроль: прежнее поведение без участия среды (with_env=False) "
        "==="
    )
    wins_a, frl_a, fai_a = run_arm(False)
    print(
        f"  Итоги: RL={wins_a['RL']}, AI={wins_a['UtilityAI']}, "
        f"без решения={wins_a[None]}"
    )
    print(
        f"  Финальная сила: RL медиана={statistics.median(frl_a):.0f}, "
        f"AI медиана={statistics.median(fai_a):.0f}"
    )

    print(
        "\n=== Утверждённая онтология: среда-автомат (Environment, "
        "with_env=True) ==="
    )
    env = Environment()
    agent_fields = set(vars(Agent()))
    env_fields = set(vars(env))

    new_scalars = sorted(env_fields - agent_fields - {"members"})
    print(f"  Компонент state среды: {sorted(env.state)}")
    print(
        f"  Поля экземпляра сверх Agent: {sorted(env_fields - agent_fields)} "
        "(members — контейнер, не скаляр состояния)"
    )
    print(
        f"  Из них НОВЫХ скалярных переменных состояния: "
        f"{new_scalars or 'нет'}"
    )
    print(
        f"  isinstance(env, Agent) == {isinstance(env, Agent)} "
        f"(среда наследует кодекс автомата — повторения кода нет)"
    )
    wins_b, frl_b, fai_b = run_arm(True)
    print(
        f"  Итоги: RL={wins_b['RL']}, AI={wins_b['UtilityAI']}, "
        f"без решения={wins_b[None]}"
    )
    print(
        f"  Финальная сила: RL медиана={statistics.median(frl_b):.0f}, "
        f"AI медиана={statistics.median(fai_b):.0f}"
    )

    print("\n=== Сводка ===")
    print(
        "  Простота: среда-автомат не вводит ни одной новой переменной — "
        "набор её состояний есть подмножество полей Agent; кодекс унаследован."
    )
    print(
        "  Мощность: окна конъюнктуры (ENV_BONUS={}, доход ENV_INCOME={}) "
        "порождают семейство динамик вместо одной канонической".format(
            ENV_BONUS, ENV_INCOME
        )
    )
    force_delta = statistics.median(frl_b) - statistics.median(frl_a)
    wins_delta = (wins_b["RL"] + wins_b["UtilityAI"]) - (
        wins_a["RL"] + wins_a["UtilityAI"]
    )
    print(
        "  Различие итогов по силе RL (медиана с env − без env): "
        f"{force_delta:+.0f}; различие решённых партий: {wins_delta:+d}."
    )


if __name__ == "__main__":
    main()
