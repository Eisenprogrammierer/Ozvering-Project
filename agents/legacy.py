from core41.types import Action, Observation, Transition

import simulation as S

from .policies import BDIPolicy


class PolicyAgent(S.Agent):

    def __init__(self, profile="CANON", policy=None, seed=0):
        self.policy = policy if policy is not None else BDIPolicy(seed=seed)
        self._opponent = None
        self._last_observation = None
        self._last_action = None
        self._time = 0
        super().__init__(profile=profile)

    def reset_state(self):
        super().reset_state()
        self._opponent = None
        self._last_observation = None
        self._last_action = None
        self._time = 0

    def sense(self, opp, rng):
        super().sense(opp, rng)
        self._opponent = opp

    def observation(self):
        max_energy = max(1.0, float(S.E_MAX_MULT * self.regen))
        return Observation(
            self_force=float(self.force),
            self_energy=float(self.energy_pool),
            self_max_force=float(max(1.0, self.rest_ceiling)),
            self_max_energy=max_energy,
            opponent_force=float(self.beliefs.get("opp_force", 1)),
            opponent_energy=float(self.beliefs.get("opp_energy", 1)),
            opponent_max_force=float(max(1.0, self.rest_ceiling)),
            opponent_max_energy=max_energy,
            opponent_pressure=float(self.beliefs.get("opp_w_adopt", 0.0)),
            opponent_open=bool(self.beliefs.get("opp_in_open", False)),
            time=float(self._time),
            forms=tuple(S.TYPES),
            opponent_defense=str(
                self.beliefs.get("opp_defense_guess") or ""
            ),
        )

    def actions(self):
        actions = [Action("REST", form="rest")]
        for form in S.TYPES:
            for fraction in (0.3, 0.7):
                if int(self.energy_pool * fraction) > 0:
                    actions.append(
                        Action("WORK", form=form, fraction=fraction)
                    )
        return tuple(actions)

    def form_intention(self, *args):
        observation = self.observation()
        action = self.policy.act(
            observation, self.actions(), explore=True
        )
        self._last_observation = observation
        self._last_action = action
        self._time += 1
        if action.kind == "REST":
            return "REST", 0
        work = int(self.energy_pool * action.fraction)
        if work <= 0 or action.form not in S.TYPES:
            return "REST", 0
        return action.form, work

    def observe_reward(self, reward, done=False):
        if self._last_observation is None or self._last_action is None:
            return
        transition = Transition(
            observation=self._last_observation,
            action=self._last_action,
            reward=float(reward),
            next_observation=self.observation(),
            done=bool(done),
            next_actions=self.actions(),
        )
        observe = getattr(self.policy, "observe", None)
        if observe is not None:
            observe(transition)
        self._last_observation = None
        self._last_action = None

    def policy_state(self):
        return self.policy.state_dict()

    def load_policy_state(self, state):
        self.policy.load_state_dict(state)

    def save_policy(self, path):
        save = getattr(self.policy, "save", None)
        if save is None:
            raise ValueError("policy is not serializable")
        save(path)

    def load_policy(self, path):
        load = getattr(self.policy, "load", None)
        if load is None:
            raise ValueError("policy is not serializable")
        load(path)
