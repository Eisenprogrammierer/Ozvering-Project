import math
import random
import statistics

import information
import observability

PARAMETERS = {
    "TYPES": ["FIRE", "WATER", "EARTH"],
    "P_BASE": 0.6,
    "K_MASS": 1.0,
    "K_TYPE": 0.8,
    "COST_FRACTION": 0.2,
    "ON_FRAC": 0.25,
    "ON_MIN": 6.0,
    "OFF_FRAC": 0.4,
    "MIN_OUTPUT": 2,
    "OPEN_TTL": 8,
    "GAIN_MAX": 1.2,
    "Y_SMALL": 0.05,
    "DECAY_ADOPT": 0.95,
    "RETALIATE_FRACTION": 0.5,
    "HOCK_FRACTION": 0.25,
    "OPTION_VALUE": 0.10,
    "K_EFFECT": 0.70,
    "L_BASE": 60,
    "L_STEP": 10,
    "MAX_REST_DELTA": 8,
    "STARVING_E": 2,
    "E_MAX_MULT": 3,
    "UPKEEP": 1,
    "MAX_WORK": 200,
    "BELIEF_NOISE": 2,
    "CAPTURE_RATIO": 1.5,
    "CAPTURE_STREAK": 20,
    "CAPTURE_FRAC": 0.10,
    "ENV_BONUS": 0.25,
    "ENV_INCOME": 2,
    "ENV_REST_CAP": 10.0,
    "ENTROPY_EMA": 0.25,
    "ENTROPY_SIGMA": 0.15,
    "ENTROPY_DF": 3.0,
    "ENTROPY_DEADBAND": 0.15,
    "OBS_RESOLUTION": 1.0,
    "OBS_DELAY": 1,
    "LOD_WORK_THRESHOLD": 20.0,
    "LOD_HORIZON": 10,
    "LOD_ERROR_TOL": 0.05,
}

globals().update(PARAMETERS)

MULT = {
    ("WATER", "FIRE"): 3.0,
    ("FIRE", "EARTH"): 3.0,
    ("EARTH", "WATER"): 3.0,
}

PROFILES = {
    "ZEALOT": 0.7,
    "ORTHODOX": 0.85,
    "CANON": 1.0,
}


_nonnum = {
    n: p
    for n, p in PROFILES.items()
    if isinstance(p, bool) or not isinstance(p, (int, float))
}
if _nonnum:
    raise TypeError(f"PROFILES: p должно быть числом: {_nonnum}")
_bad_profiles = {n: p for n, p in PROFILES.items() if not (0.0 < p <= 1.0)}
if _bad_profiles:
    raise ValueError(f"PROFILES вне диапазона 0 < p ≤ 1: {_bad_profiles}")
del _nonnum, _bad_profiles

ACTIONS = [("REST", 0)] + [(t, w) for t in TYPES for w in [0.3, 0.7]]


def p_success(att_type, att_work, dfn_type, dfn_work):
    mass = min(att_work, MAX_WORK) / max(dfn_work, 1)
    penalty = K_TYPE if MULT.get((dfn_type, att_type)) else 0.0
    logit = math.log(mass) * K_MASS - penalty
    return P_BASE / (1.0 + math.exp(-logit))


class Agent:

    def __init__(self, profile="CANON"):
        self.entropy_enabled = False
        self.info = information.BeliefEntropy(
            ema=ENTROPY_EMA,
            sigma=ENTROPY_SIGMA,
            df=ENTROPY_DF,
            deadband=ENTROPY_DEADBAND,
        )
        self.set_profile(profile)
        self.reset_state()

    def set_profile(self, profile, allow_out_of_range=False):
        if isinstance(profile, bool):

            raise ValueError(f"profile не может быть bool: {profile!r}")
        if isinstance(profile, str):
            if profile not in PROFILES:
                raise ValueError(
                    f"неизвестный профиль {profile!r}; допустимы: "
                    f"{sorted(PROFILES)}"
                )
            p, norm = PROFILES[profile], profile
        else:
            p, norm = float(profile), round(float(profile), 4)
        if not allow_out_of_range and not (0.0 < p <= 1.0):
            raise ValueError(
                f"профиль p={p} вне допустимого диапазона 0 < p ≤ 1 "
                f"(docs/MODEL.md, раздел 2а)"
            )
        self.profile, self.p = norm, p

    def reset_state(self):

        if hasattr(self, "info"):
            self.new_entropy_lineage()

        self.state = {
            "force": 10,
            "energy_pool": 3,
            "rest_units": 0.0,
            "last_act": "REST",
            "last_work": 0,
            "w_adopt": 0.0,
            "in_open": False,
            "open_timer": 0,
        }
        self.beliefs = {
            "opp_energy": 3,
            "opp_last_act": "REST",
            "opp_last_work": 0,
            "opp_force": 10,
            "opp_w_adopt": 0.0,
            "opp_in_open": False,
            "opp_ctx_base": None,
            "entropy": 0.0,
            "entropy_cum": (self.info.H_cum if hasattr(self, "info") else 0.0),
            "entropy_lineage": (
                self.info.lineage if hasattr(self, "info") else 0
            ),
            "noise_floor": (
                self.info.noise_floor if hasattr(self, "info") else 0.0
            ),
            "belief_noise_factor": 1.0,
        }

    def new_entropy_lineage(self):
        if hasattr(self, "info"):
            self.info.new_lineage(reset_counts=True)

    @property
    def force(self):
        return self.state["force"]

    @force.setter
    def force(self, value):
        self.state["force"] = value

    @property
    def energy_pool(self):
        return self.state["energy_pool"]

    @energy_pool.setter
    def energy_pool(self, value):
        self.state["energy_pool"] = value

    @property
    def rest_units(self):
        return self.state["rest_units"]

    @rest_units.setter
    def rest_units(self, value):
        self.state["rest_units"] = value

    @property
    def defense(self):
        hidden = TYPES.index(self.last_act) if self.last_act in TYPES else 0
        return self.receptive_type(
            self.energy_pool, self.w_adopt, self.in_open, self.force, hidden
        )

    @staticmethod
    def context_base(energy_pool, w_adopt, in_open, force):
        full = energy_pool / max(
            1.0, E_MAX_MULT * max(1, math.floor(math.sqrt(max(1, force))))
        )
        press = w_adopt / max(1.0, max(ON_MIN, ON_FRAC * force))
        if in_open or press >= 1.0:
            return 2
        if full >= 0.5:
            return 1
        return 0

    @staticmethod
    def receptive_type(energy_pool, w_adopt, in_open, force, hidden=0):
        base = Agent.context_base(energy_pool, w_adopt, in_open, force)
        return TYPES[(base + int(hidden)) % 3]

    @property
    def last_act(self):
        return self.state["last_act"]

    @last_act.setter
    def last_act(self, value):
        self.state["last_act"] = value

    @property
    def last_work(self):
        return self.state["last_work"]

    @last_work.setter
    def last_work(self, value):
        self.state["last_work"] = value

    @property
    def w_adopt(self):
        return self.state["w_adopt"]

    @w_adopt.setter
    def w_adopt(self, value):
        self.state["w_adopt"] = value

    @property
    def in_open(self):
        return self.state["in_open"]

    @in_open.setter
    def in_open(self, value):
        self.state["in_open"] = value

    @property
    def open_timer(self):
        return self.state["open_timer"]

    @open_timer.setter
    def open_timer(self, value):
        self.state["open_timer"] = value

    @property
    def rest_ceiling(self):
        return L_BASE + L_STEP * self.rest_units

    def rest_gain(self):
        e = self.force - UPKEEP
        ceiling = self.rest_ceiling
        return MAX_REST_DELTA * (e / ceiling) * (1.0 - e / ceiling)

    def do_rest(self, chosen=True):
        gain = self.rest_gain() if chosen else 0.5 * self.rest_gain()
        self.force = min(self.force + gain, self.rest_ceiling)
        add = max(2, self.regen) if chosen else 1
        self.energy_pool = min(self.energy_pool + add, E_MAX_MULT * self.regen)
        self.last_act, self.last_work = "REST", 0

    @property
    def regen(self):
        return max(1, math.floor(math.sqrt(self.force)))

    def tick_energy(self):
        self.energy_pool = min(
            self.energy_pool + self.regen, E_MAX_MULT * self.regen
        )

    def schmitt_on(self):
        return max(ON_MIN, ON_FRAC * self.force)

    def effective_decay(self):
        return DECAY_ADOPT * self.p

    def receive_pressure(self, w):
        self.w_adopt += w
        if not self.in_open and self.w_adopt >= self.schmitt_on():
            self.in_open = True
            self.open_timer = OPEN_TTL

    def tick_input_state(self):
        self.w_adopt *= self.effective_decay()
        if self.in_open:
            self.open_timer -= 1
            off_now = (OFF_FRAC / self.p) * self.schmitt_on()
            if self.open_timer <= 0 or self.w_adopt < off_now:
                self.in_open = False

    def sense(self, opp, rng):
        prev_w = self.beliefs.get("opp_w_adopt_prev")
        self.beliefs["opp_energy"] = max(
            1, opp.energy_pool + rng.randint(-BELIEF_NOISE, BELIEF_NOISE)
        )
        self.beliefs["opp_force"] = max(1, int(round(opp.force, -1)))
        self.beliefs["opp_w_adopt"] = max(0.0, opp.w_adopt)
        self.beliefs["opp_in_open"] = opp.in_open
        if prev_w is not None and prev_w > 1e-6 and opp.w_adopt <= prev_w:

            obs_decay = min(0.999, max(0.5, opp.w_adopt / prev_w))
            dq = self.beliefs.setdefault("opp_decay_hist", [])
            dq.append(obs_decay)
            if len(dq) > 8:
                dq.pop(0)
            self.beliefs["opp_decay_guess"] = sum(dq) / len(dq)
        self.beliefs["opp_w_adopt_prev"] = opp.w_adopt
        hist = self.beliefs.setdefault("opp_act_hist", [])
        hist.append(opp.last_act)
        if len(hist) > 5:
            hist.pop(0)
        non_rest = [a for a in hist if a != "REST"]

        self.beliefs["opp_defense_guess"] = (
            max(TYPES, key=non_rest.count) if non_rest else None
        )

        self.beliefs["opp_ctx_base"] = self.context_base(
            self.beliefs["opp_energy"],
            self.beliefs["opp_w_adopt"],
            self.beliefs["opp_in_open"],
            self.beliefs["opp_force"],
        )

        if getattr(self, "entropy_enabled", False):
            self.info.observe(
                self.beliefs["opp_ctx_base"], self.beliefs["opp_in_open"]
            )
            self.beliefs["entropy"] = self.info.H_local
            self.beliefs["entropy_cum"] = self.info.H_cum
            self.beliefs["entropy_lineage"] = self.info.lineage
            self.beliefs["noise_floor"] = self.info.noise_floor
            self.info.perturb(self.beliefs, rng)

            self.beliefs["opp_ctx_base"] = self.context_base(
                self.beliefs["opp_energy"],
                self.beliefs["opp_w_adopt"],
                self.beliefs["opp_in_open"],
                self.beliefs["opp_force"],
            )
        self.beliefs["opp_last_act"] = opp.last_act
        self.beliefs["opp_last_work"] = opp.last_work

    def rotate_defense(self, rng):
        return None

    def upkeep(self):
        self.force = max(1, self.force - UPKEEP)

    def commit(self, act, work):
        if act == "REST":
            self.do_rest(chosen=True)
            return 0
        w = min(
            int(work),
            self.energy_pool,
            MAX_WORK,
            max(MIN_OUTPUT, self.force // 4),
        )
        if w <= 0:
            self.do_rest(chosen=False)
            return 0
        self.energy_pool -= w
        self.last_act, self.last_work = act, w
        return w

    def committed_work(self, act, work):
        if act == "REST":
            return 0
        w = min(
            int(work),
            self.energy_pool,
            MAX_WORK,
            max(MIN_OUTPUT, self.force // 4),
        )
        return w if w > 0 else 0

    def defense_after(self, act, work):
        hidden = TYPES.index(act) if act in TYPES else 0
        pool = self.energy_pool - self.committed_work(act, work)
        return self.receptive_type(
            pool, self.w_adopt, self.in_open, self.force, hidden
        )

    def rest_if_starving(self):
        if self.energy_pool <= STARVING_E:
            self.do_rest(chosen=True)
            return True
        return False

    def process_hit(self, tr):
        self.force = max(1, self.force - tr)
        self.energy_pool = max(0, self.energy_pool - int(HOCK_FRACTION * tr))

    def gain(self, tr):
        self.force += tr


class UtilityAI(Agent):

    def __init__(self, profile="CANON", profile_aware=False):
        super().__init__(profile=profile)
        self.profile_aware = profile_aware

    def gain_model(self, m, p):
        if self.beliefs["opp_in_open"]:
            return p * m * GAIN_MAX
        base = Y_SMALL * p * m
        on_opp = max(ON_MIN, ON_FRAC * self.beliefs["opp_force"])
        progress = min(1.0, self.beliefs["opp_w_adopt"] / on_opp)

        eff_decay = DECAY_ADOPT
        if self.profile_aware:
            dg = self.beliefs.get("opp_decay_guess")
            if dg is not None:
                eff_decay = dg
        k = 3
        retained = sum(eff_decay**i for i in range(1, k + 1)) / k

        reliability = max(0.0, 1.0 - self.beliefs.get("noise_floor", 0.0))
        option = (
            OPTION_VALUE
            * progress
            * reliability
            * (retained / (sum(DECAY_ADOPT**i for i in range(1, k + 1)) / k))
        )
        return base + option

    def expected_retaliation(self, act, work):
        w = self.committed_work(act, work)
        r_w = int(RETALIATE_FRACTION * w)
        if r_w <= 0:
            return 0.0
        dfn_type = self.defense_after(act, work)
        ev = 0.0
        for t in TYPES:
            mr = MULT.get((t, dfn_type), 1.0)
            pr = p_success(t, r_w, dfn_type, w)
            ev += r_w * self.gain_model_rev(mr, pr) / 3.0
        return ev

    def gain_model_rev(self, m, p):
        if self.in_open:
            return p * m * GAIN_MAX
        return Y_SMALL * p * m

    def retaliation_penalty(self, act, work):
        w = self.committed_work(act, work)
        r_w = int(RETALIATE_FRACTION * w)
        return COST_FRACTION * w + HOCK_FRACTION * r_w

    def expected_gain(self, act, work):
        if act == "REST" or work <= 0:
            return self.rest_gain()
        ev = 0.0
        for hypo in TYPES:
            m = MULT.get((act, hypo), 1.0)
            p = p_success(act, work, hypo, self.beliefs["opp_last_work"])
            ev += work * self.gain_model(m, p) / 3.0
        return (
            ev
            - self.retaliation_penalty(act, work)
            - self.expected_retaliation(act, work)
        )

    def form_intention(self):
        best, best_u = ("REST", 0), self.rest_gain()
        for t in TYPES:
            for frac in (0.3, 0.7):
                w = int(self.energy_pool * frac)
                u = self.expected_gain(t, w)
                if u > best_u:
                    best, best_u = (t, w), u
        return best


class RLAgent(Agent):

    EPS_START = 1.0
    EPS_MIN = 0.05
    EPS_DECAY_STEPS = 3000

    def __init__(self, q=None, profile="CANON"):
        super().__init__(profile=profile)
        self.Q = q if q is not None else {}
        self.steps_trained = 0

    def epsilon(self):
        e = max(
            self.EPS_MIN,
            self.EPS_START - self.steps_trained / self.EPS_DECAY_STEPS,
        )
        self.steps_trained += 1
        return e

    def discretize(self, e):
        if e <= 8:
            return e
        if e <= 32:
            return 8 + (e - 8) // 4
        return 14 + int(math.log(e / 32))

    def skey(self):
        threat = (
            "T"
            if MULT.get((self.beliefs["opp_last_act"], self.defense))
            else "-"
        )
        adopt = self.discretize(int(self.beliefs["opp_w_adopt"]))
        openg = "O" if self.beliefs["opp_in_open"] else "C"
        return (
            self.discretize(self.energy_pool),
            self.discretize(self.beliefs["opp_energy"]),
            self.beliefs["opp_last_act"],
            threat,
            adopt,
            openg,
            self.beliefs.get("opp_ctx_base"),
        )

    def form_intention(self, eps, rng):
        st = self.skey()
        if st not in self.Q:
            self.Q[st] = [0.0] * len(ACTIONS)
        if rng.random() < eps:
            return rng.randint(0, len(ACTIONS) - 1)
        return self.Q[st].index(max(self.Q[st]))

    def learn(self, st, a_idx, reward, nst, alpha=0.3, gamma=0.9):
        if nst not in self.Q:
            self.Q[nst] = [0.0] * len(ACTIONS)
        td = reward + gamma * max(self.Q[nst]) - self.Q[st][a_idx]
        self.Q[st][a_idx] += alpha * td


class Environment(Agent):

    def __init__(self, start_force=10, members=None, lossy=False):

        super().__init__(profile="CANON")
        self.force = float(start_force)

        self.members = list(members) if members else []

        self.lossy = bool(lossy)
        self.channel = observability.LossyChannel(
            resolution=OBS_RESOLUTION, delay=OBS_DELAY
        )
        self._public_window = False
        self._public_window_prev = False

        self.beliefs.update(
            {
                "opp_last_act": "REST",
                "opp_last_work": 0,
                "opp_energy": 0,
                "opp_force": 1,
                "opp_w_adopt": 0.0,
                "opp_in_open": False,
            }
        )

    def receive_pressure(self, w):
        super().receive_pressure(w)
        self.rest_units = min(self.rest_units + w * 0.01, ENV_REST_CAP)

    def ingest(self, work):
        if self.lossy:
            self.channel.push(work)
        else:
            self.receive_pressure(work)

    def public_window(self):
        return self._public_window_prev if self.lossy else self.in_open

    def rotate_defense(self, rng):
        super().rotate_defense(rng)
        for m in self.members:
            if isinstance(m, Environment):
                Agent.rotate_defense(m, rng)

    def snapshot(self):
        return {
            "force": self.force,
            "energy_pool": self.energy_pool,
            "w_adopt": round(self.w_adopt, 2),
            "in_open": self.in_open,
            "defense": self.defense,
            "last_act": self.last_act,
            "last_work": self.last_work,
            "members": [
                m.snapshot()
                for m in self.members
                if isinstance(m, Environment)
            ],
        }

    def public_snapshot(self):
        on = max(ON_MIN, ON_FRAC * self.force)
        pressure = self.w_adopt / on if on > 0 else 0.0
        pressure_band = 0 if pressure < 0.5 else (1 if pressure < 1.0 else 2)
        ceiling = max(1.0, self.rest_ceiling)
        force_band = (
            0
            if self.force < ceiling / 3.0
            else (1 if self.force < 2.0 * ceiling / 3.0 else 2)
        )
        return {
            "window": self.public_window(),
            "pressure_band": pressure_band,
            "force_band": force_band,
            "member_count": len(self.members),
            "lossy": self.lossy,
        }

    def member_output(self):
        total = 0.0
        for m in self.members:
            if isinstance(m, Environment):
                total += m.member_output()
            elif m.last_act != "REST":
                total += m.last_work
        return total

    def tick(self):
        for m in self.members:
            if isinstance(m, Environment):
                m.tick()
        if self.lossy:

            obs = self.channel.drain()
            w_members = obs.work
            for m in self.members:
                if isinstance(m, Environment):
                    w_members += m.member_output()
            if w_members:
                self.receive_pressure(w_members)
        elif self.members:
            w_members = self.member_output()
            if w_members:
                self.receive_pressure(w_members)
        self.tick_energy()
        self.tick_input_state()

        self.force = min(self.force + ENV_INCOME, self.rest_ceiling)
        if self.force < self.rest_ceiling:
            self.do_rest(chosen=False)
        self.upkeep()

        self._public_window_prev = self._public_window
        self._public_window = self.in_open


def _apply_transfer(att, dfn, work, att_type, rng, env=None):
    open_now = dfn.in_open
    dfn.receive_pressure(work)
    if env is not None:
        env.ingest(work)
    if rng.random() < p_success(att_type, work, dfn.defense, dfn.last_work):
        m = MULT.get((att_type, dfn.defense), 1.0)
        gain_frac = GAIN_MAX if open_now else Y_SMALL
        if env is not None:

            env_window = env.public_window() if env.lossy else env.in_open
            if env_window:
                gain_frac *= 1.0 + ENV_BONUS
        gained = int(work * m * gain_frac)
        if gained:
            att.gain(gained)
            att.rest_units += gained
        dfn.process_hit(work)
        dfn.force = max(1, dfn.force + int(K_EFFECT * work))


def resolve_attack(att, dfn, work, rng, env=None):
    if not work:
        return
    att.force = max(1, att.force - int(COST_FRACTION * work))
    _apply_transfer(att, dfn, work, att.last_act, rng, env)

    r_w = int(RETALIATE_FRACTION * work)
    if r_w > 0 and dfn.energy_pool >= 1:
        r_w = min(r_w, dfn.energy_pool, MAX_WORK)
        dfn.energy_pool -= r_w
        dfn.force = max(1, dfn.force - int(COST_FRACTION * r_w))
        _apply_transfer(dfn, att, r_w, dfn.defense, rng, env)


def dominates(att, dfn):
    return (
        att.energy_pool >= CAPTURE_RATIO * dfn.energy_pool
        and att.force > dfn.force
    )


def check_capture(
    rl,
    ai,
    dom_rl=0,
    dom_ai=0,
    winner_rl="RL",
    winner_ai="UtilityAI",
):
    dom_rl = dom_rl + 1 if dominates(rl, ai) else 0
    dom_ai = dom_ai + 1 if dominates(ai, rl) else 0
    if dom_rl >= CAPTURE_STREAK:
        sev = 2.0 if ai.in_open else 1.0
        cap = int(ai.force * min(CAPTURE_FRAC * sev, 0.5))
        ai.force = max(1, ai.force - cap)
        ai.rest_units = max(0.0, ai.rest_units - cap / L_STEP)
        rl.gain(cap)

        rl.new_entropy_lineage()
        ai.new_entropy_lineage()
        return winner_rl, 0, 0
    if dom_ai >= CAPTURE_STREAK:
        sev = 2.0 if rl.in_open else 1.0
        cap = int(rl.force * min(CAPTURE_FRAC * sev, 0.5))
        rl.force = max(1, rl.force - cap)
        rl.rest_units = max(0.0, rl.rest_units - cap / L_STEP)
        ai.gain(cap)
        rl.new_entropy_lineage()
        ai.new_entropy_lineage()
        return winner_ai, 0, 0
    return None, dom_rl, dom_ai


def run_tick(a, b, intent_a, intent_b, rng, env=None):
    a.sense(b, rng)
    b.sense(a, rng)

    a.rotate_defense(rng)
    b.rotate_defense(rng)
    if env is not None:
        env.rotate_defense(rng)

    a.upkeep()
    b.upkeep()
    a.tick_energy()
    b.tick_energy()
    a.tick_input_state()
    b.tick_input_state()
    if env is not None:
        env.tick()

    act_a, work_a = intent_a(a, b, rng)
    work_a = 0 if a.rest_if_starving() else a.commit(act_a, work_a)
    act_b, work_b = intent_b(b, a, rng)
    work_b = 0 if b.rest_if_starving() else b.commit(act_b, work_b)

    resolve_attack(a, b, work_a, rng, env)
    resolve_attack(b, a, work_b, rng, env)
    return work_a, work_b


def play_game(
    rl,
    ai,
    steps=1000,
    seed=0,
    profiles=None,
    with_env=True,
    env_members=None,
    entropy=False,
    lossy=False,
):
    if profiles is not None:
        p_rl, p_ai = profiles
        rl.set_profile(p_rl)
        ai.set_profile(p_ai)

    rl.entropy_enabled = bool(entropy)
    ai.entropy_enabled = bool(entropy)
    rl.reset_state()
    ai.reset_state()
    env = Environment(members=env_members, lossy=lossy) if with_env else None
    dom_rl = dom_ai = 0
    rng = random.Random(seed)
    rl_hist, ai_hist = [], []

    trace = {}

    def rl_intent(me, opp, r):
        idx = me.form_intention(me.epsilon(), r)
        trace["idx"] = idx
        trace["f_before"] = me.force
        trace["st_before"] = me.skey()
        name, frac = ACTIONS[idx]
        return name, me.energy_pool * frac

    def ai_intent(me, opp, r):
        return me.form_intention()

    for step in range(steps):
        run_tick(rl, ai, rl_intent, ai_intent, rng, env)

        rl_hist.append(rl.force)
        ai_hist.append(ai.force)
        rl.learn(
            trace["st_before"],
            trace["idx"],
            rl.force - trace["f_before"],
            rl.skey(),
        )

        winner, dom_rl, dom_ai = check_capture(rl, ai, dom_rl, dom_ai)
        if winner:
            return winner, rl_hist, ai_hist, step
    return None, rl_hist, ai_hist, steps


def run_batch(
    n_games=10,
    steps=1000,
    quiet=False,
    with_env=True,
    env_members_fn=None,
    entropy=False,
    lossy=False,
):
    rl = RLAgent()
    results = {"RL": 0, "UtilityAI": 0, None: 0}
    finals = {"RL": [], "UtilityAI": [], None: []}
    last = None
    for g in range(n_games):
        ai = UtilityAI()
        members = env_members_fn(rl, ai) if env_members_fn else None
        winner, rl_hist, ai_hist, end_step = play_game(
            rl,
            ai,
            steps,
            seed=g,
            with_env=with_env,
            env_members=members,
            entropy=entropy,
            lossy=lossy,
        )
        results[winner] += 1
        finals[winner].append(rl.force)
        last = (winner, rl_hist, ai_hist, end_step)
        if not quiet:
            print(
                f"Game {g + 1}: winner={winner or 'no-capture'} at step "
                f"{end_step} | "
                f"final RL force={rl.force:.0f}, final UtilityAI "
                f"force={ai_hist[-1]:.0f}"
            )
    if not quiet:
        print("\nИтоги пакетного прогона:")
        print(
            f"  RL победил: {results['RL']}/{n_games}, "
            f"UtilityAI: {results['UtilityAI']}/{n_games}, "
            f"без решения: {results[None]}/{n_games}"
        )
        for k in finals:
            if finals[k]:
                print(
                    f"  Финальная сила RL при '{k}': "
                    f"медиана={statistics.median(finals[k]):.0f}"
                )
    return rl, last, results


def main():
    rl, (winner, rl_hist, ai_hist, end_step), results = run_batch(n_games=10)

    print(
        f"\nПоследняя партия: winner={winner or 'no-capture'}, "
        f"шагов={end_step}"
    )
    print(f"Q-состояний изучено: {len(rl.Q)}")

    import matplotlib.pyplot as plt

    plt.figure(figsize=(10, 6))
    plt.plot(rl_hist, label="RL Agent", color="blue", linewidth=2)
    plt.plot(ai_hist, label="Utility AI", color="red", linewidth=2)
    plt.title(
        "Динамика силы агентов (пороги Шмитта на входе адресата)", fontsize=14
    )
    plt.xlabel("Шаг симуляции", fontsize=12)
    plt.ylabel("Сила (Force, log)", fontsize=12)
    plt.yscale("log")
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
