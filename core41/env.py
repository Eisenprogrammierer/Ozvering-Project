from .duel import DuelWorld


class DuelEnv:

    def __init__(self, seed=0, max_steps=200):
        self.world = DuelWorld(seed=seed, max_steps=max_steps)

    @property
    def action_space(self):
        return self.world.legal_actions("agent")

    def reset(self, seed=None):
        return self.world.reset(seed)

    def step(self, action, opponent_action=None):
        if opponent_action is None:
            choices = self.world.legal_actions("opponent")
            opponent_action = choices[
                self.world.rng.randrange(len(choices))
            ]
        observations, rewards, done, info = self.world.step(
            {"agent": action, "opponent": opponent_action}
        )
        truncated = bool(
            done
            and self.world.time >= self.world.max_steps
            and self.world.agent.force > 0
            and self.world.opponent.force > 0
        )
        return (
            observations["agent"],
            rewards["agent"],
            done,
            truncated,
            info,
        )
