"""LOD: ленивые вычисления с уровнями детализации.

Уровни (см. ``docs/DESIGN_ADVANCED.md``):

* **LOD-1** — событийный (ближний): обычный ``simulation.run_tick``. Это канон
  истины; любой другой уровень обязан иметь оценку ошибки и fallback на него.
* **LOD-2** — интервальный: работа накапливается, событие разрешается по порогу
  ``LOD_WORK_THRESHOLD`` (по работе, не по времени). Временные процессы между
  событиями (``upkeep``, логистический покой, ``decay``, пополнение пула)
  интегрируются **аналитически**, иначе пассивная сущность «замерзает».
* **LOD-3** — аналитический (mean-field): приближение стационарного режима с
  **областью валидности** и принудительным fallback. Точной замкнутой формулы
  для полной модели (гистерезис + скрытая фаза + стохастика + path-dependence)
  не существует, поэтому LOD-3 — это приближение, а не второй канон.

Модуль импортирует ``simulation`` (не наоборот), поэтому цикла нет. Канон
``play_game`` по умолчанию остаётся на LOD-1.
"""

import math

import simulation as S

LOD1, LOD2, LOD3 = 1, 2, 3


def integrate_time(agent, dt, resting=True):
    """Аналитически продвинуть временные процессы агента на ``dt`` тактов.

    Приближение LOD-2 для интервала без событий. Точное для:
      * ``upkeep`` (линейно);
      * пополнения пула ``regen`` с потолком ``E_MAX_MULT * regen``;
      * остывания входа ``w_adopt *= decay**dt``;
      * логистического покоя (замкнутая форма логистического ОДУ).

    Гистерезис окна обрабатывается по числу тактов: окно закрывается, если
    ``open_timer`` истёк или давление упало ниже ``OFF``.

    Returns:
        ``True`` — интервал прошёл без дискретных событий; ``False`` — внутри
        интервала окно закрылось или сила упёрлась в гарантию жизни, поэтому
        вызывающий обязан откатиться на LOD-1 (оценка ошибки L1).
    """
    dt = max(0, int(dt))
    if dt == 0:
        return True

    was_open = agent.in_open
    was_force = agent.force

    # 1. upkeep — линейно, с гарантией жизни (сила >= 1).
    agent.force = max(1.0, agent.force - S.UPKEEP * dt)

    # 2. Пополнение пула потоком regen (потолок E_MAX_MULT * regen).
    regen = agent.regen
    cap = S.E_MAX_MULT * regen
    agent.energy_pool = min(agent.energy_pool + regen * dt, cap)

    # 3. Остывание входа и гистерезис окна.
    agent.w_adopt *= agent.effective_decay() ** dt
    if agent.in_open:
        agent.open_timer -= dt
        off_now = (S.OFF_FRAC / agent.p) * agent.schmitt_on()
        if agent.open_timer <= 0 or agent.w_adopt < off_now:
            agent.in_open = False

    # 4. Логистический покой: замкнутая форма dx/dt = r*x*(1-x).
    if resting:
        L = agent.rest_ceiling
        x0 = max(0.0, (agent.force - S.UPKEEP) / L)
        if 0.0 < x0 < 1.0:
            r = S.MAX_REST_DELTA / L
            e = math.exp(r * dt)
            x = x0 * e / (1.0 - x0 + x0 * e)
            agent.force = min(S.UPKEEP + L * x, L)
        add = max(2, regen)
        agent.energy_pool = min(agent.energy_pool + add * dt, cap)
        agent.last_act, agent.last_work = "REST", 0

    # Оценка ошибки интервала: если внутри него случилось дискретное событие
    # (окно закрылось) или упёрлись в гарантию жизни, аналитический шаг
    # недействителен — вызывающий обязан откатиться на LOD-1.
    ok = True
    if was_open and not agent.in_open:
        ok = False
    if was_force > 1.0 and agent.force <= 1.0:
        ok = False
    return ok


class LodController:
    """Выбор уровня детализации по близости к границам и стационарности."""

    def __init__(self, work_threshold=None, horizon=None, error_tol=None):
        self.work_threshold = float(
            S.LOD_WORK_THRESHOLD if work_threshold is None else work_threshold)
        self.horizon = max(1, int(S.LOD_HORIZON if horizon is None else horizon))
        self.error_tol = float(
            S.LOD_ERROR_TOL if error_tol is None else error_tol)

    def near_boundary(self, agent):
        """Сущность у порога/в окне/на дне — только LOD-1."""
        on = agent.schmitt_on()
        return (agent.in_open
                or agent.energy_pool <= S.STARVING_E
                or agent.force <= 2 * S.UPKEEP
                or abs(agent.w_adopt - on) <= 0.25 * on)

    def stationary(self, agent):
        """Достаточные условия mean-field-режима (вне гистерезиса и дна)."""
        return (agent.force > 2 * S.UPKEEP
                and not agent.in_open
                and agent.energy_pool > 0
                and agent.w_adopt < 0.75 * agent.schmitt_on())

    def work_interval(self, *agents):
        """Длина LOD-2-интервала по накопленной работе, а не по времени.

        Оценка темпа — максимально доступная работа стороны за такт (пул,
        предел структуры, regen). Интервал подбирается так, чтобы суммарная
        работа за него была около ``LOD_WORK_THRESHOLD``; это и есть порог
        события из дизайна (docs/DESIGN_ADVANCED.md), а не фиксированный шаг.
        """
        rate = sum(max(1, int(a.energy_pool), a.force // 4, a.regen)
                   for a in agents)
        return max(1, min(self.horizon,
                          max(1, int(self.work_threshold // max(1, rate)))))

    def level(self, *agents):
        """LOD-1 при близости к границе, иначе LOD-3 в стационаре, иначе LOD-2."""
        if any(self.near_boundary(a) for a in agents):
            return LOD1
        if all(self.stationary(a) for a in agents):
            return LOD3
        return LOD2


def mean_field_step(agent, dt, controller=None):
    """LOD-3: продвинуть стационарный режим; ``False`` — нужен fallback.

    Приближение действительно только внутри области валидности; при выходе за
    неё возвращается ``False``, и вызывающий обязан спуститься на LOD-2/1.
    """
    controller = controller or LodController()
    if not controller.stationary(agent):
        return False
    return integrate_time(agent, dt)


def run_duel_lod(a, b, policy_a, policy_b, rng, env, ticks, controller=None):
    """Дуэль с ленивыми вычислениями (LOD-1/2/3).

    Возвращает ``(hist_a, hist_b, levels)``. Это ЭКСПЕРИМЕНТАЛЬНЫЙ раннер:
    канон ``play_game`` остаётся на LOD-1, а LOD-2/3 — приближения с fallback.
    """
    controller = controller or LodController()
    ha, hb, levels = [], [], []
    tick = 0
    while tick < ticks:
        lvl = controller.level(a, b)
        if lvl == LOD1:
            dt = 1
        elif lvl == LOD2:
            dt = controller.work_interval(a, b)
        else:
            dt = min(controller.horizon, ticks - tick)
        if lvl == LOD1:
            S.run_tick(a, b, policy_a, policy_b, rng, env)
        elif lvl == LOD2:
            # Интервал: время интегрируется аналитически, событие — одним тактом.
            # Если внутри интервала случилось дискретное событие (окно закрылось,
            # упёрлись в дно), интеграл недействителен: откат и LOD-1 на один такт.
            snap_a, snap_b = dict(a.state), dict(b.state)
            ok_a = integrate_time(a, dt - 1)
            ok_b = integrate_time(b, dt - 1)
            if not (ok_a and ok_b):
                a.state, b.state = snap_a, snap_b
                dt = 1
            S.run_tick(a, b, policy_a, policy_b, rng, env)
        else:
            # LOD-3: mean-field; при выходе за область валидности — fallback
            # на LOD-1 (откат состояния, один событийный такт).
            snap_a, snap_b = dict(a.state), dict(b.state)
            ok_a = mean_field_step(a, dt, controller)
            ok_b = mean_field_step(b, dt, controller)
            if not (ok_a and ok_b):
                a.state, b.state = snap_a, snap_b
                dt = 1
                S.run_tick(a, b, policy_a, policy_b, rng, env)
        tick += dt
        ha.append(a.force)
        hb.append(b.force)
        levels.append(lvl)
    return ha, hb, levels
