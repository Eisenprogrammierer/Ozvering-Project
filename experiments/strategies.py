"""Единый референсный набор скриптовых стратегий и протокол дуэли.

Зачем отдельный модуль: раньше PRESSER/TIMING определялись по-разному в
``exp_schmitt_suite.py``, ``exp_fix.py`` и ``exp_hypotheses.py``, из-за чего
выводы о балансе расходились (например, «PRESSER доминирует» против «TIMING
контрит PRESSER» в разных скриптах). Здесь — единый источник стратегий и
протокола дуэли для ``exp_schmitt_suite.py`` и ``exp_balance_ci.py``. Скрипты
``exp_fix.py``/``exp_hypotheses.py`` сохраняют собственные исторические варианты
``make_scripted`` (их TIMING отличается) — при суждении о балансе опирайтесь
только на этот модуль.

Политика — функция ``(me, opp, rng) -> (act, work)``, где ``me``/``opp`` —
автоматы ``simulation.Agent``, ``rng`` — генератор партии ``random.Random``.
``work`` — желаемая работа; фактическую отсекает ``Agent.commit`` (пул, кап,
предел структуры). Возврат ``("REST", 0)`` — покой.
"""
import random

import simulation as S


def passive(me, opp, rng):
    """Пас: вечный покой, вход не нагружается."""
    return ("REST", 0)


def presser(me, opp, rng):
    """Вечно давит случайным типом, игнорируя состояние чужого входа (0.7 пула)."""
    return (rng.choice(S.TYPES), int(me.energy_pool * 0.7))


def timing(me, opp, rng):
    """Копит давление малыми ударами, бьёт крупно в открытое окно.

    Пока чужой вход закрыт и напор ещё не близок к порогу — отдыхает;
    на подходе к ``ON(F)`` начинает продавливать; в открытое окно бьёт крупно.

    Тип рецептивного входа противника КОНТЕКСТЕН, но содержит СКРЫТУЮ выходную
    фазу текущего такта (см. §2 MODEL.md), недоступную наблюдателю при
    одновременных ходах. Её маргинал равномерен, поэтому выбор типа безразличен:
    контрить «базовую» оценку смысла нет — берём случайный тип, а преимущество
    стратегии даёт только тайминг окна.
    """
    b = me.beliefs
    if b["opp_in_open"]:
        return (rng.choice(S.TYPES), int(me.energy_pool * 0.7))
    on_opp = max(S.ON_MIN, S.ON_FRAC * b["opp_force"])
    if b["opp_w_adopt"] >= 0.6 * on_opp and me.force > 30:
        return (rng.choice(S.TYPES), int(me.energy_pool * 0.5))
    return ("REST", 0)


STRATEGIES = {"PASSIVE": passive, "PRESSER": presser, "TIMING": timing}
"""Референсные стратегии: имя -> политика ``(me, opp, rng) -> (act, work)``."""

POLICY_SIGNATURE = "(me, opp, rng) -> (act, work)"


def duel(policy_a, policy_b, steps=400, seed=0, f0=10, env=None, capture_streak=20):
    """Одна дуэль двух политик на симметричных автоматах.

    Порядок такта повторяет ``simulation.play_game`` (sense → (ротация защит —
    упразднена, ``rotate_defense`` вызывается no-op ради совместимости
    протокола) → upkeep → энергия → состояния входов → намерения →
    ``resolve_attack`` в обе стороны → проверка устойчивого доминирования).

    Args:
        policy_a, policy_b: политики сторон A и B.
        steps: максимум тактов.
        seed: seed партии (детерминизм).
        f0: стартовая сила обеих сторон (дно F=10 / плато F=30).
        env: необязательная среда-автомат для передачи в ``resolve_attack``
            (по умолчанию None — «дуэль стратегий без среды»).
        capture_streak: длина серии доминирования (как CAPTURE_STREAK).

    Returns:
        (winner, step, hist_a, hist_b); winner — "A" | "B" | None.
    """
    rng = random.Random(seed)
    a, b = S.Agent(), S.Agent()
    a.force = b.force = f0
    ha, hb = [], []
    dom_a = dom_b = 0
    for step in range(steps):
        a.sense(b, rng); b.sense(a, rng)
        a.rotate_defense(rng); b.rotate_defense(rng)
        a.upkeep(); b.upkeep()
        a.tick_energy(); b.tick_energy()
        a.tick_input_state(); b.tick_input_state()
        act, w = policy_a(a, b, rng)
        wa = 0 if a.rest_if_starving() else a.commit(act, w)
        act, w = policy_b(b, a, rng)
        wb = 0 if b.rest_if_starving() else b.commit(act, w)
        S.resolve_attack(a, b, wa, rng, env)
        S.resolve_attack(b, a, wb, rng, env)
        ha.append(a.force); hb.append(b.force)
        dom_a = dom_a + 1 if (a.force >= 1.5 * b.force and a.energy_pool >= 1.5 * b.energy_pool) else 0
        dom_b = dom_b + 1 if (b.force >= 1.5 * a.force and b.energy_pool >= 1.5 * a.energy_pool) else 0
        if dom_a >= capture_streak:
            return "A", step, ha, hb
        if dom_b >= capture_streak:
            return "B", step, ha, hb
    return None, steps, ha, hb


def duel_matrix(names, n_seeds=20, steps=400, f0=10, env=None):
    """Матрица дуэлей: для каждой упорядоченной пары — счёт A/B/ничьи.

    Returns:
        dict[(a,b)] = {"A": int, "B": int, None: int, "df": [ΔF]}.
    """
    mtx = {}
    for ka in names:
        for kb in names:
            tally = {"A": 0, "B": 0, None: 0}
            dfs = []
            for sd in range(n_seeds):
                w, st, ha, hb = duel(STRATEGIES[ka], STRATEGIES[kb],
                                     steps=steps, seed=sd, f0=f0, env=env)
                tally[w] += 1
                dfs.append(ha[-1] - hb[-1])
            tally["df"] = dfs
            mtx[(ka, kb)] = tally
    return mtx
