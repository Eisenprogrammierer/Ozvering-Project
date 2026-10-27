import os
import sys
import math

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import random
from collections import Counter
import simulation as S
from simulation import Agent, RLAgent, UtilityAI, TYPES, play_game, ACTIONS


def hidden_of(act):
    return TYPES.index(act) if act in TYPES else 0


def entropy(counts):
    total = sum(counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        p = c / total
        if p > 0:
            h -= p * math.log(p)
    return h


def table(counts):
    total = sum(counts.values()) or 1
    return "  ".join(
        f"{k}:{counts.get(k, 0) / total:.3f}"
        for k in sorted(set(list(counts.keys()) + [0, 1, 2]))
    )


_orig_cc = S.check_capture
_CUR = None


def _spy_cc(rl, ai, dom_rl, dom_ai):
    if _CUR is not None:
        _CUR["rl"].append(rl.last_act)
        _CUR["ai"].append(ai.last_act)
    return _orig_cc(rl, ai, dom_rl, dom_ai)


S.check_capture = _spy_cc


def collect(n_games=10, seeds=range(0, 40, 4), with_env=True):
    global _CUR
    rl, ai = RLAgent(), UtilityAI()
    acts = {"rl": Counter(), "ai": Counter()}
    for g in seeds:
        _CUR = {"rl": [], "ai": []}
        play_game(rl, ai, steps=1000, seed=g, with_env=with_env)
        acts["rl"].update(_CUR["rl"])
        acts["ai"].update(_CUR["ai"])
    return acts


def hidden_dist(act_counter):
    d = Counter()
    for act, n in act_counter.items():
        d[hidden_of(act)] += n
    return d


print("=" * 72)
print("A1. Маргинал скрытой фазы hidden (TYPES.index(last_act), REST->0)")
print("=" * 72)
print(f"TYPES = {TYPES}; ACTIONS = {[a for a, _ in ACTIONS]}")
print(
    "Отображение действий в фазу: "
    + ", ".join(f"{a}->{hidden_of(a)}" for a, _ in ACTIONS)
    + f"  (цена коллизии: REST и FIRE оба -> {hidden_of('REST')})"
)
print()

for with_env in (True, False):
    acts = collect(with_env=with_env)
    print(f"--- Канон RL vs UtilityAI, with_env={with_env} ---")
    for side in ("rl", "ai"):
        hd = hidden_dist(acts[side])
        total = sum(hd.values()) or 1
        rest = acts[side].get("REST", 0)
        print(
            f"  {side.upper():>3}: hidden {table(hd)}  | H={entropy(hd):.4f} "
            f"(max ln3={math.log(3):.4f})  | доля REST={rest / total:.3f}"
        )
    print()


class _AlwaysRest(Agent):
    def form_intention(self):
        return ("REST", 0)


print("--- Контроль: всегда отдыхающий противник (иллюстрация вырождения) ---")
_orig_cc2 = S.check_capture
acts_ctl = Counter()
_CUR = None


def _spy_cc2(rl, ai, dom_rl, dom_ai):
    acts_ctl[ai.last_act] += 1
    return _orig_cc2(rl, ai, dom_rl, dom_ai)


S.check_capture = _spy_cc2
rl = RLAgent()
rest_ai = _AlwaysRest()
for g in range(4):
    play_game(rl, rest_ai, steps=200, seed=g, with_env=True)
hd = hidden_dist(acts_ctl)
print(
    f"  всегда-REST: hidden {table(hd)}  | H={entropy(hd):.4f}  "
    f"| действия={dict(acts_ctl)}"
)
print()


print("--- hidden только по атакующим действиям (REST исключён) ---")
for with_env in (True, False):
    acts = collect(with_env=with_env)
    for side in ("rl", "ai"):
        atk = Counter({a: n for a, n in acts[side].items() if a in TYPES})
        hd = hidden_dist(atk)
        print(
            f"  with_env={with_env} {side.upper():>3}: hidden {table(hd)}  "
            f"| H={entropy(hd):.4f}  | атак={sum(atk.values())}"
        )
print()


print("=" * 72)
print("ВЫВОД")
print("=" * 72)
print(
    "1. hidden=0 при покое И при FIRE — коллизия заложена в отображение (стр. "
    "270)."
)
print(
    "2. Маргинал hidden задаётся ПОЛИТИКОЙ адресата (частотой типов "
    "действий), а не"
)
print(
    "   архитектурой; равномерность — не закон, а (приблизительное) наблюдение"
)
print(
    "   для конкретных стратегий. У отдыхающего противника маргинал вырожден."
)
print(
    "3. Следствие: усреднение 1/3 в "
    "UtilityAI.expected_gain/expected_retaliation и"
)
print(
    "   «типо-безразличие» strategies.timing опираются на априор, не на закон."
)
print("4. Резолв A1 (2026-10-16): равномерность трактуется как МАКСИМАЛЬНО-")
print("   ЭНТРОПИЙНЫЙ (неинформированный) АПРИОР наблюдателя, а не свойство")
print(
    "   архитектуры; MODEL.md §2/§15.1 и docstrings переформулированы. "
    "Поведение"
)
print("   модели не менялось (априор уже был 1/3).")
print(
    "5. Тип входа = TYPES[(base+hidden)%3]: равномерность ТИПА слабее "
    "равномерности"
)
print(
    "   hidden и не следует из неё автоматически — две величины не смешивать."
)
