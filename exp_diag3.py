import random
from simulation import *

def trace(seed, steps=120):
    rng = random.Random(seed)
    rl, ai = RLAgent(), UtilityAI()
    for step in range(steps):
        rl.sense(ai, rng); ai.sense(rl, rng)
        rl.rotate_defense(rng); ai.rotate_defense(rng)
        rl.upkeep(); ai.upkeep(); rl.tick_energy(); ai.tick_energy()
        rl.heal_depletion(); ai.heal_depletion()
        eps = max(0.05, 1.0-step/300)
        a_idx = rl.form_intention(eps)
        act_name, frac = ACTIONS[a_idx]
        w_rl = 0 if rl.rest_if_starving() else rl.commit(act_name, rl.energy_pool*frac)
        ai_act, ai_work = ai.form_intention()
        w_ai = 0 if ai.rest_if_starving() else ai.commit(ai_act, ai_work)
        resolve_attack(rl, ai, w_rl, rng)
        resolve_attack(ai, rl, w_ai, rng)
        if step % 10 == 0 or step < 6:
            print(f"t={step:3d} RL F={rl.force:7.1f} E={rl.energy_pool:3d} x={rl.depletion:6.1f} u={rl.last_act}/{rl.last_work:3d} | "
                  f"AI F={ai.force:7.1f} E={ai.energy_pool:3d} x={ai.depletion:6.1f} u={ai.last_act}/{ai.last_work:3d}")
        win = check_capture(rl, ai)
        if win: print("CAPTURE:", win, "at", step); return
    print("no capture after", steps)

trace(7)
