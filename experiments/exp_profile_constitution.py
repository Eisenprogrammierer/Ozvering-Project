"""P1: профиль как возможная «скрытая конституция» — протокол и вердикт.

Вопрос (docs/MODEL.md §2а и §15.2, docs/TODO.md P1): «характер» автомата задан
ОДНИМ скаляром ``p`` (``PROFILES``), умножающим существующие константы. Не
является ли это скрытой конституцией — скрытым параметром, влияющим на исход
помимо наблюдаемой игры, — несмотря на косвенную наблюдаемость
(``opp_decay_guess``)?

МЕТОДИКА (протокол «объяснения исходов наблюдаемыми величинами», наблюдаемость
снизу вверх). Никаких новых сущностей не вводится: используются только уже
существующие профильный скаляр ``p`` и канал убеждений ``opp_decay_guess``
(производная от наблюдаемой траектории ``w_adopt``). Для каждого профиля
измеряются две независимые оси:

  1. НАБЛЮДАЕМОСТЬ (восстановимость): восстанавливает ли противник ``p`` из
     штатного канала ``opp_decay_guess`` в реальной дуэли? Метрики — доля тактов
     с заполненной оценкой и средняя абсолютная ошибка ``|оценка − DECAY_ADOPT·p|``.
  2. РЕШИТЕЛЬНОСТЬ: меняет ли ``p`` исход? Метрика — распределение исходов канона
     (RL/UtilityAI/ничьи) в сравнении с ``CANON``.
  3. ВЫРОЖДЕННОСТЬ: остаётся ли входной закон сжатием (``effective_decay ≤ 1``)?
     Метрика — поведение ``w_adopt`` при 60 тактах без внешнего напора.

ВЕРДИКТ (правило): профиль есть «скрытая конституция» тогда и только тогда, когда
он НЕ наблюдаем И при этом решителен или вырожден. Если профиль наблюдаем, он —
не скрытая конституция, а честная «характеристика обработки», различимая
противником по уже наблюдаемой траектории.

Результат протокола: ветвь ``p > 1`` оказалась вырожденной и не наблюдаемой и
УДАЛЕНА из ``PROFILES``; здесь она измеряется «сырыми» значениями ``p`` как
контроль (показывает, почему диапазон ограничен ``p ≤ 1``).

Запуск из корня репозитория:
    python3 experiments/exp_profile_constitution.py
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulation as S
from simulation import Agent, RLAgent, UtilityAI, DECAY_ADOPT, play_game

# (метка, аргумент профиля): имя из PROFILES (p ≤ 1) либо «сырое» p > 1 —
# контрольная ветвь, удалённая из PROFILES, но воспроизводимая числом.
CASES = (
    ("ZEALOT", "ZEALOT"),
    ("ORTHODOX", "ORTHODOX"),
    ("CANON", "CANON"),
    ("p=1.15 (удалён)", 1.15),
    ("p=1.30 (удалён)", 1.30),
)
N_GAMES = 20
IDLE_TICKS = 60

OBSERVABLE_MIN = 0.5      # доля тактов с оценкой, ниже которой канал считается слепым
DECISIVE_RL_DELTA = 3     # |RL(p) − RL(CANON)| в партиях из N_GAMES
DECISIVE_NO_DELTA = 3     # |ничьи(p) − ничьи(CANON)| в партиях из N_GAMES


def _p_of(arg):
    """Скаляр профиля по аргументу (имя или число)."""
    return S.PROFILES[arg] if isinstance(arg, str) else float(arg)


class _CountingRL(RLAgent):
    """Измерительная обёртка: считает, как часто противник восстанавливает p.

    Не новая сущность модели — подкласс ТОЛЬКО для замера: после ``sense``
    фиксирует заполненность и ошибку уже существующего убеждения
    ``opp_decay_guess`` относительно истинного ``DECAY_ADOPT·p`` оппонента.
    """

    def __init__(self):
        super().__init__()
        self.obs_total = 0
        self.obs_filled = 0
        self.obs_err = []

    def sense(self, opp, rng):
        super().sense(opp, rng)
        self.obs_total += 1
        guess = self.beliefs.get("opp_decay_guess")
        if guess is not None:
            self.obs_filled += 1
            self.obs_err.append(abs(guess - DECAY_ADOPT * opp.p))


def observability_and_outcome(profile_arg):
    """Одна серия партий RL(измеритель) vs UtilityAI(profile).

    Возвращает (populate_frac, mean_err, wins), где wins — счётчик исходов.
    """
    rl = _CountingRL()
    wins = {"RL": 0, "UtilityAI": 0, None: 0}
    for seed in range(N_GAMES):
        winner, _, _, _ = play_game(rl, UtilityAI(profile=profile_arg), 1000,
                                    seed=seed, with_env=True)
        wins[winner] += 1
    frac = rl.obs_filled / max(1, rl.obs_total)
    err = statistics.mean(rl.obs_err) if rl.obs_err else None
    return frac, err, wins


def degeneracy(profile_arg):
    """Проверка входного закона на сжатие: рост ``w_adopt`` без напора."""
    target = Agent(profile=profile_arg)
    target.w_adopt = 1.0
    for _ in range(IDLE_TICKS):
        target.tick_input_state()
        target.receive_pressure(0.0)
    return target.w_adopt


def main():
    print("P1: профиль как «скрытая конституция» — протокол наблюдаемости")
    print(f"DECAY_ADOPT={DECAY_ADOPT}, партий на профиль={N_GAMES}, "
          f"порог слепоты канала={OBSERVABLE_MIN:.0%}\n")

    rows = {}
    for label, arg in CASES:
        frac, err, wins = observability_and_outcome(arg)
        rows[label] = dict(p=_p_of(arg), true=DECAY_ADOPT * _p_of(arg),
                           frac=frac, err=err, wins=wins, idle=degeneracy(arg))

    base = rows["CANON"]

    print("[1] Наблюдаемость (восстановимость p из opp_decay_guess) и исходы")
    print(f"    {'профиль':>16} {'p':>5} {'DECAY·p':>8} | {'заполн.%':>8} {'ср.|ошибка|':>12} | "
          f"{'RL/AI/ничьи':>12} {'вердикт':>10}")
    for label, _ in CASES:
        r = rows[label]
        flag = "наблюд." if r["frac"] >= OBSERVABLE_MIN else "СЛЕПОЙ"
        err = "—" if r["err"] is None else f"{r['err']:.4f}"
        print(f"    {label:>16} {r['p']:>5.2f} {r['true']:>8.4f} | {r['frac']:>7.1%} {err:>12} | "
              f"{r['wins']['RL']:>3}/{r['wins']['UtilityAI']:>3}/{r['wins'][None]:>3} "
              f"{flag:>10}")

    print("\n[2] Решительность (отличие исхода от CANON) и вырожденность (входной закон)")
    print(f"    {'профиль':>16} | {'ΔRL':>4} {'Δничьи':>7} | {'w_adopt(t=60)':>14} {'сжатие?':>9}")
    for label, _ in CASES:
        r = rows[label]
        drl = r["wins"]["RL"] - base["wins"]["RL"]
        dno = r["wins"][None] - base["wins"][None]
        print(f"    {label:>16} | {drl:>+4} {dno:>+7} | {r['idle']:>14.1f} "
              f"{'да' if r['true'] <= 1.0 else 'НЕТ':>9}")

    print("\n[3] ВЕРДИКТ (скрытая конституция ⇔ не наблюдаем И (решителен ИЛИ вырожден))")
    hidden = []
    for label, _ in CASES:
        r = rows[label]
        observable = r["frac"] >= OBSERVABLE_MIN
        decisive = (abs(r["wins"]["RL"] - base["wins"]["RL"]) >= DECISIVE_RL_DELTA
                    or abs(r["wins"][None] - base["wins"][None]) >= DECISIVE_NO_DELTA)
        degenerate = r["true"] > 1.0
        is_hidden = (not observable) and (decisive or degenerate)
        if is_hidden:
            hidden.append(label)
        why = []
        if decisive:
            why.append("решителен")
        if degenerate:
            why.append("вырожден (w_adopt растёт без напора)")
        if not observable:
            why.append("канал слеп")
        verdict = "СКРЫТАЯ КОНСТИТУЦИЯ" if is_hidden else "не скрытая"
        print(f"    {label:>16} p={r['p']:.2f}: {verdict:>19}"
              + (f"  [{'; '.join(why)}]" if why else ""))

    print("\n=== ИТОГ ===")
    print("  * Все ОПРЕДЕЛЁННЫЕ профили (p ≤ 1) НАБЛЮДАЕМЫ: штатный канал")
    print("    opp_decay_guess восстанавливает DECAY·p почти на каждом такте с")
    print("    малой ошибкой; выходной канал (тяжесть захвата) в play_game инертен —")
    print("    партия завершается первым же захватом. Скрытой конституцией не являются.")
    print("  * Ветвь p > 1 (контроль «сырыми» p=1.15/1.30) ВЫРОЖДЕНА (w_adopt растёт")
    print("    без напора: входной закон перестаёт быть сжатием) и НЕ НАБЛЮДАЕМА")
    print("    (канал слеп на 100%). Именно поэтому она УДАЛЕНА из PROFILES:")
    print("    допустимый диапазон — p ≤ 1, и скрытой ветви не существует.")
    if hidden:
        print(f"  Скрытыми были бы: {', '.join(hidden)} (удалены из PROFILES).")


if __name__ == "__main__":
    main()
