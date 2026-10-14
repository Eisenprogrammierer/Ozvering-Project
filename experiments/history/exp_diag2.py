import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import random, statistics
from simulation import *

# Диагностическая партия после правки денудации
rng = random.Random(7)
rl, ai = RLAgent(), UtilityAI()
for step in range(80):
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
    if step < 14 or step % 10 == 0:
        print(f"t={step:2d} RL F={rl.force:6.0f} E={rl.energy_pool:3d} x={rl.depletion:6.1f} u={rl.last_act}/{rl.last_work:3d} | "
              f"AI F={ai.force:6.0f} E={ai.energy_pool:3d} x={ai.depletion:6.1f} u={ai.last_act}/{ai.last_work:3d}")
    if check_capture(rl, ai):
        print("CAPTURE:", check_capture(rl, ai), "at", step); break
