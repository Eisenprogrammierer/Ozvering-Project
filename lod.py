import math

import simulation as S

LOD1, LOD2, LOD3 = 1, 2, 3


def integrate_time(agent, dt, resting=True):
    dt = max(0, int(dt))
    if dt == 0:
        return True

    was_open = agent.in_open
    was_force = agent.force

    agent.force = max(1.0, agent.force - S.UPKEEP * dt)

    regen = agent.regen
    cap = S.E_MAX_MULT * regen
    agent.energy_pool = min(agent.energy_pool + regen * dt, cap)

    agent.w_adopt *= agent.effective_decay() ** dt
    if agent.in_open:
        agent.open_timer -= dt
        off_now = (S.OFF_FRAC / agent.p) * agent.schmitt_on()
        if agent.open_timer <= 0 or agent.w_adopt < off_now:
            agent.in_open = False

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

    ok = True
    if was_open and not agent.in_open:
        ok = False
    if was_force > 1.0 and agent.force <= 1.0:
        ok = False
    return ok


class LodController:

    def __init__(self, work_threshold=None, horizon=None, error_tol=None):
        self.work_threshold = float(
            S.LOD_WORK_THRESHOLD if work_threshold is None else work_threshold
        )
        self.horizon = max(
            1, int(S.LOD_HORIZON if horizon is None else horizon)
        )
        self.error_tol = float(
            S.LOD_ERROR_TOL if error_tol is None else error_tol
        )

    def near_boundary(self, agent):
        on = agent.schmitt_on()
        return (
            agent.in_open
            or agent.energy_pool <= S.STARVING_E
            or agent.force <= 2 * S.UPKEEP
            or abs(agent.w_adopt - on) <= 0.25 * on
        )

    def stationary(self, agent):
        return (
            agent.force > 2 * S.UPKEEP
            and not agent.in_open
            and agent.energy_pool > 0
            and agent.w_adopt < 0.75 * agent.schmitt_on()
        )

    def work_interval(self, *agents):
        rate = sum(
            max(1, int(a.energy_pool), a.force // 4, a.regen) for a in agents
        )
        return max(
            1,
            min(
                self.horizon, max(1, int(self.work_threshold // max(1, rate)))
            ),
        )

    def level(self, *agents):
        if any(self.near_boundary(a) for a in agents):
            return LOD1
        if all(self.stationary(a) for a in agents):
            return LOD3
        return LOD2


def mean_field_step(agent, dt, controller=None):
    controller = controller or LodController()
    if not controller.stationary(agent):
        return False
    return integrate_time(agent, dt)


def run_duel_lod(a, b, policy_a, policy_b, rng, env, ticks, controller=None):
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

            snap_a, snap_b = dict(a.state), dict(b.state)
            ok_a = integrate_time(a, dt - 1)
            ok_b = integrate_time(b, dt - 1)
            if not (ok_a and ok_b):
                a.state, b.state = snap_a, snap_b
                dt = 1
            S.run_tick(a, b, policy_a, policy_b, rng, env)
        else:

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
