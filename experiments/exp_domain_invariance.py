import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import simulation as S

DOMAINS = ("physical", "informational", "economic")

FAILURES = []


def check(cond, msg):
    print(f"  [{'OK' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILURES.append(msg)


def _signature():
    rl = S.RLAgent()
    sig = []
    for g in range(10):
        ai = S.UtilityAI()
        winner, _rh, _ah, end = S.play_game(
            rl, ai, 1000, seed=g, with_env=True
        )
        sig.append((winner or "none", int(end), int(rl.force), int(ai.force)))
    return tuple(sig)


def _h(sig):
    return hashlib.sha1(repr(sig).encode("utf-8")).hexdigest()[:12]


print("F1. Доменная инвариантность «единого закона»")
print("=" * 60)

_orig = S.resolve_attack
CURRENT = {"d": DOMAINS[0]}

base = _signature()
_base_res = {"RL": 0, "UtilityAI": 0, "none": 0}
for _g in base:
    _base_res[_g[0]] += 1
print(f"  базовый отпечаток канона: {_h(base)}  {_base_res}")


_ke = S.K_EFFECT
S.K_EFFECT = 1.0
try:
    ke_sig = _signature()
finally:
    S.K_EFFECT = _ke
print(f"  P0 мощность: K_EFFECT=1.0 меняет канон: {_h(ke_sig)}")
check(ke_sig != base, "P0: различитель слышит изменение закона (K_EFFECT=1.0)")


def _domain_aware(att, dfn, work, rng, env=None):
    if CURRENT["d"] == "informational" and work:
        saved = S.COST_FRACTION
        S.COST_FRACTION = 0.0
        try:
            return _orig(att, dfn, work, rng, env)
        finally:
            S.COST_FRACTION = saved
    return _orig(att, dfn, work, rng, env)


S.resolve_attack = _domain_aware
try:
    aware = {}
    for d in DOMAINS:
        CURRENT["d"] = d
        aware[d] = _signature()
finally:
    S.resolve_attack = _orig

print("  P1 доменная зависимость замечается:")
for d in DOMAINS:
    mark = "(отличается)" if aware[d] != base else "(совпал)"
    print(f"      d={d:<14} {_h(aware[d])} {mark}")
check(
    any(aware[d] != base for d in DOMAINS),
    "P1: доменная ветка ЗАМЕЧАЕТСЯ различителем",
)


def _domain_blind(att, dfn, work, rng, env=None):
    _ = CURRENT["d"]
    return _orig(att, dfn, work, rng, env)


S.resolve_attack = _domain_blind
try:
    blind = {}
    for d in DOMAINS:
        CURRENT["d"] = d
        blind[d] = _signature()
finally:
    S.resolve_attack = _orig

print("  P2 слепота (неиспользуемый индекс инертен):")
for d in DOMAINS:
    mark = "(== база)" if blind[d] == base else "(ОТЛИЧИЕ!)"
    print(f"      d={d:<14} {_h(blind[d])} {mark}")
check(
    all(blind[d] == base for d in DOMAINS),
    "P2: доменный индекс не влияет на канон (модель доменно-слепа)",
)

print()
print("Заключение: домен — не переменная механизма (P2), и проверка не пуста")
print("(P0/P1). F1 операционализирован как «доменная слепота + инерция»,")
print("а не как тавтология.")
print()
print(
    "ИТОГ:",
    (
        "F1 подтверждён (слепота при работоспособном различителе)"
        if not FAILURES
        else "РЕГРЕССИЯ F1: " + "; ".join(FAILURES)
    ),
)
sys.exit(0 if not FAILURES else 1)
