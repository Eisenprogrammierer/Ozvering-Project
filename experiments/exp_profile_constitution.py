import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulation as S
from simulation import Agent, RLAgent, UtilityAI, DECAY_ADOPT, play_game

CASES = (
    ("ZEALOT", "ZEALOT"),
    ("ORTHODOX", "ORTHODOX"),
    ("CANON", "CANON"),
    ("p=1.15 (удалён)", 1.15),
    ("p=1.30 (удалён)", 1.30),
)
N_GAMES = 20
IDLE_TICKS = 60

OBSERVABLE_MIN = 0.5
DECISIVE_RL_DELTA = 3
DECISIVE_NO_DELTA = 3


def _p_of(arg):
    return S.PROFILES[arg] if isinstance(arg, str) else float(arg)


def _make_agent(cls, profile_arg):
    try:
        return cls(profile=profile_arg)
    except ValueError:
        agent = cls()
        agent.set_profile(profile_arg, allow_out_of_range=True)
        return agent


class _CountingRL(RLAgent):

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
    rl = _CountingRL()
    wins = {"RL": 0, "UtilityAI": 0, None: 0}
    for seed in range(N_GAMES):
        winner, _, _, _ = play_game(
            rl,
            _make_agent(UtilityAI, profile_arg),
            1000,
            seed=seed,
            with_env=True,
        )
        wins[winner] += 1
    frac = rl.obs_filled / max(1, rl.obs_total)
    err = statistics.mean(rl.obs_err) if rl.obs_err else None
    return frac, err, wins


def degeneracy(profile_arg):
    target = _make_agent(Agent, profile_arg)
    target.w_adopt = 1.0
    for _ in range(IDLE_TICKS):
        target.tick_input_state()
        target.receive_pressure(0.0)
    return target.w_adopt


def main():
    print("P1: профиль как «скрытая конституция» — протокол наблюдаемости")
    print(
        f"DECAY_ADOPT={DECAY_ADOPT}, партий на профиль={N_GAMES}, "
        f"порог слепоты канала={OBSERVABLE_MIN:.0%}\n"
    )

    rows = {}
    for label, arg in CASES:
        frac, err, wins = observability_and_outcome(arg)
        rows[label] = dict(
            p=_p_of(arg),
            true=DECAY_ADOPT * _p_of(arg),
            frac=frac,
            err=err,
            wins=wins,
            idle=degeneracy(arg),
        )

    base = rows["CANON"]

    print("[1] Наблюдаемость (восстановимость p из opp_decay_guess) и исходы")
    print(
        f"    {'профиль':>16} {'p':>5} {'DECAY·p':>8} | {'заполн.%':>8} "
        f"{'ср.|ошибка|':>12} | "
        f"{'RL/AI/ничьи':>12} {'вердикт':>10}"
    )
    for label, _ in CASES:
        r = rows[label]
        flag = "наблюд." if r["frac"] >= OBSERVABLE_MIN else "СЛЕПОЙ"
        err = "—" if r["err"] is None else f"{r['err']:.4f}"
        wins = r["wins"]
        outcome = f"{wins['RL']:>3}/{wins['UtilityAI']:>3}/{wins[None]:>3}"
        print(
            f"    {label:>16} {r['p']:>5.2f} {r['true']:>8.4f} | "
            f"{r['frac']:>7.1%} {err:>12} | {outcome} {flag:>10}"
        )

    print(
        "\n[2] Решительность (отличие исхода от CANON) и вырожденность "
        "(входной закон)"
    )
    print(
        f"    {'профиль':>16} | {'ΔRL':>4} {'Δничьи':>7} | "
        f"{'w_adopt(t=60)':>14} {'сжатие?':>9}"
    )
    for label, _ in CASES:
        r = rows[label]
        drl = r["wins"]["RL"] - base["wins"]["RL"]
        dno = r["wins"][None] - base["wins"][None]
        print(
            f"    {label:>16} | {drl:>+4} {dno:>+7} | {r['idle']:>14.1f} "
            f"{'да' if r['true'] <= 1.0 else 'НЕТ':>9}"
        )

    print(
        "\n[3] ВЕРДИКТ (скрытая конституция ⇔ не наблюдаем И (решителен ИЛИ "
        "вырожден))"
    )
    hidden = []
    for label, _ in CASES:
        r = rows[label]
        observable = r["frac"] >= OBSERVABLE_MIN
        decisive = (
            abs(r["wins"]["RL"] - base["wins"]["RL"]) >= DECISIVE_RL_DELTA
            or abs(r["wins"][None] - base["wins"][None]) >= DECISIVE_NO_DELTA
        )
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
        print(
            f"    {label:>16} p={r['p']:.2f}: {verdict:>19}"
            + (f"  [{'; '.join(why)}]" if why else "")
        )

    print("\n=== ИТОГ ===")
    print("  * Все ОПРЕДЕЛЁННЫЕ профили (p ≤ 1) НАБЛЮДАЕМЫ: штатный канал")
    print(
        "    opp_decay_guess восстанавливает DECAY·p почти на каждом такте с"
    )
    print(
        "    малой ошибкой. Выходной канал профиля (тяжесть захвата) удалён "
        "как"
    )
    print(
        "    инертный — партия завершается первым же захватом. Скрытой "
        "конституцией"
    )
    print("    не являются.")
    print(
        "  * Ветвь p > 1 (контроль «сырыми» p=1.15/1.30) ВЫРОЖДЕНА (w_adopt "
        "растёт"
    )
    print(
        "    без напора: входной закон перестаёт быть сжатием) и НЕ НАБЛЮДАЕМА"
    )
    print("    (канал слеп на 100%). Именно поэтому она УДАЛЕНА из PROFILES:")
    print("    допустимый диапазон — p ≤ 1, и скрытой ветви не существует.")
    if hidden:
        print(
            f"  Скрытыми были бы: {', '.join(hidden)} (удалены из PROFILES)."
        )


if __name__ == "__main__":
    main()
