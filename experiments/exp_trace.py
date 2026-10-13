import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import random, math
from simulation import *

# Трассировка одной партии с логами
def traced_game(seed=1, steps=40):
    rng = random.Random(seed)
    rl, ai = RLAgent(), UtilityAI()
    for step in range(steps):
        rl.sense(ai, rng); ai.sense(rl, rng)
        rl.rotate_defense(rng); ai.rotate_defense(rng)
        rl.upkeep(); ai.upkeep()
        rl.tick_energy(); ai.tick_energy()
        rl.heal_depletion(); ai.heal_depletion()
        eps = max(0.05, 1.0 - step/300)
        a_idx = rl.form_intention(eps)
        act_name, frac = ACTIONS[a_idx]
        if rl.rest_if_starving(): w_rl = 0
        else: w_rl = rl.commit(act_name, rl.energy_pool*frac)
        ai_act, ai_work = ai.form_intention()
        if ai.rest_if_starving(): w_ai = 0
        else: w_ai = ai.commit(ai_act, ai_work)
        resolve_attack(rl, ai, w_rl, rng)
        resolve_attack(ai, rl, w_ai, rng)
        print(f"t={step}: RL F={rl.force:.0f} E={rl.energy_pool} x={rl.depletion:.1f} act={rl.last_act}/{rl.last_work} | "
              f"AI F={ai.force:.0f} E={ai.energy_pool} x={ai.depletion:.1f} act={ai.last_act}/{ai.last_work}")
        if check_capture(rl, ai): print("CAPTURE at", step); break

traced_game()
