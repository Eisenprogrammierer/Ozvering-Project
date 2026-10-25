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
    """
    dt = max(0, int(dt))
    if dt == 0:
        return

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
    integrate_time(agent, dt)
    return True


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
        dt = 1 if lvl == LOD1 else min(controller.horizon, ticks - tick)
        if lvl == LOD1:
            S.run_tick(a, b, policy_a, policy_b, rng, env)
        elif lvl == LOD2:
            # Интервал: время интегрируется аналитически, событие — одним тактом.
            integrate_time(a, dt - 1)
            integrate_time(b, dt - 1)
            S.run_tick(a, b, policy_a, policy_b, rng, env)
        else:
            # LOD-3: mean-field; при выходе за область валидности — fallback
            # на LOD-2 (dt-1 тактов аналитики + один событийный такт).
            if controller.stationary(a) and controller.stationary(b):
                integrate_time(a, dt)
                integrate_time(b, dt)
            else:
                integrate_time(a, dt - 1)
                integrate_time(b, dt - 1)
                S.run_tick(a, b, policy_a, policy_b, rng, env)
        tick += dt
        ha.append(a.force)
        hb.append(b.force)
        levels.append(lvl)
    return ha, hb, levels
