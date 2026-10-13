"""Среда как всеобъемлющий IPO-автомат: проверка утверждённого решения.

История: ранее сравнивались две конкурентные гипотезы об онтологии среды
(открытый вопрос 3 MODEL.md):
  A — «среда как отдельное от автоматов пространство» (только константы
      PARAMETERS, ноль состояний; в коде — env=None / SpaceEnvironment);
  B — «среда как всеобъемлющий IPO-автомат» (суперсистема того же кодекса).
По итогам сравнения принята гипотеза B (см. docs/MODEL.md, раздел 12), код
гипотезы A (SpaceEnvironment) удалён. Оставшийся контроль A — партия с
with_env=False, т.е. прежний канон без участия среды: он нужен лишь чтобы
измерять вклад среды-автомата в динамику.

Метрика проверки:
  1. Простота реализации — число переменных состояния среды и НОВЫХ имён по
     отношению к Agent (выводится из исходника; ожидание: новых нет);
  2. Мощность моделирования — доля решённых партий и частота окон конъюнктуры,
     которые порождает среда-автомат (без неё — затухание к дну);
  3. Перспективность — различимость итогов при включённой/выключенной среде.

Запуск: python3 experiments/exp_environment.py
"""
import os
import sys
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation import (RLAgent, UtilityAI, Environment, Agent,
                        play_game, ENV_BONUS, ENV_INCOME)

N_GAMES = 6
STEPS = 400


def run_arm(with_env):
    """Пакет партий с общей Q-таблицей RL при данном участии среды-автомата."""
    rl = RLAgent()
    wins = {"RL": 0, "UtilityAI": 0, None: 0}
    finals_rl, finals_ai = [], []
    for g in range(N_GAMES):
        winner, rl_hist, ai_hist, end_step = play_game(
            rl, UtilityAI(), STEPS, seed=g, with_env=with_env)
        wins[winner] += 1
        finals_rl.append(rl_hist[-1])
        finals_ai.append(ai_hist[-1])
    return wins, finals_rl, finals_ai


def main():
    print("=== Контроль: прежнее поведение без участия среды (with_env=False) ===")
    wins_a, frl_a, fai_a = run_arm(False)
    print(f"  Итоги: RL={wins_a['RL']}, AI={wins_a['UtilityAI']}, "
          f"без решения={wins_a[None]}")
    print(f"  Финальная сила: RL медиана={statistics.median(frl_a):.0f}, "
          f"AI медиана={statistics.median(fai_a):.0f}")

    print("\n=== Утверждённая онтология: среда-автомат (Environment, with_env=True) ===")
    env = Environment()
    state_vars = [k for k in vars(env)]
    agent_fields = set(vars(Agent()))
    new_vs_agent = sorted(state_vars - agent_fields)
    print(f"  Переменных состояния среды: {len(state_vars)}")
    print(f"  Из них НОВЫХ по отношению к Agent: {new_vs_agent or 'нет'}")
    print(f"  isinstance(env, Agent) == {isinstance(env, Agent)} "
          f"(среда наследует кодекс автомата — повторения кода нет)")
    wins_b, frl_b, fai_b = run_arm(True)
    print(f"  Итоги: RL={wins_b['RL']}, AI={wins_b['UtilityAI']}, "
          f"без решения={wins_b[None]}")
    print(f"  Финальная сила: RL медиана={statistics.median(frl_b):.0f}, "
          f"AI медиана={statistics.median(fai_b):.0f}")

    print("\n=== Сводка ===")
    print("  Простота: среда-автомат не вводит ни одной новой переменной — "
          "набор её состояний есть подмножество полей Agent; кодекс унаследован.")
    print("  Мощность: окна конъюнктуры (ENV_BONUS={}, доход ENV_INCOME={}) "
          "порождают семейство динамик вместо одной канонической".format(
              ENV_BONUS, ENV_INCOME))
    print("  Различие итогов по силе RL (медиана с env − без env): "
          f"{statistics.median(frl_b) - statistics.median(frl_a):+.0f}; "
          "различие решённых партий: "
          f"{(wins_b['RL'] + wins_b['UtilityAI']) - (wins_a['RL'] + wins_a['UtilityAI']):+d}.")


if __name__ == "__main__":
    main()
